"""
Image preparation for the vision model.

Two jobs:
  1. Resize/encode a screenshot to the exact shape the vision API will use.
  2. Fingerprint it, so identical frames are not stored or billed twice.

Sizing rationale
----------------
With `detail: "high"` the API rescales the image so its SHORT side is 768px,
then charges ceil(w/512) * ceil(h/512) tiles. Consequences:

  * Larger than 768-short-side  -> downscaled anyway. Same price, wasted upload.
  * Smaller than 768-short-side -> upscaled back to 768. Same price, real
    detail permanently lost.

So 768 on the short side is both the cheapest and the sharpest option. The old
pipeline sent context frames at 800px on the LONG side (450px short side for a
16:9 screen) at JPEG quality 40 — that paid the full tile price for an image
the model then had to upscale from a heavily artefacted source. Small on-screen
text was frequently unreadable.
"""

import base64
import io
import logging

from PIL import Image

from config import settings

logger = logging.getLogger(__name__)

_HASH_SIZE = 8  # dHash grid -> 64-bit fingerprint


def decode_base64_image(image_b64: str) -> Image.Image:
    """Decode a base64 image, with or without a `data:` URL prefix."""
    if image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    raw = base64.b64decode(image_b64, validate=False)
    img = Image.open(io.BytesIO(raw))
    img.load()
    return img


def target_size(width: int, height: int) -> tuple[int, int]:
    """Dimensions to send: short side at the tile target, never upscaled."""
    short_side = settings.image_short_side
    max_long = settings.image_max_long_side

    if width <= 0 or height <= 0:
        return width, height

    scale = short_side / min(width, height)
    # Never upscale: extra pixels invented here carry no information and the
    # API would only throw them away.
    scale = min(scale, 1.0)

    w, h = round(width * scale), round(height * scale)

    # Ultrawide guard: cap the long side so the tile count stays bounded.
    if max(w, h) > max_long:
        shrink = max_long / max(w, h)
        w, h = round(w * shrink), round(h * shrink)

    return max(w, 1), max(h, 1)


def prepare_image(image_b64: str) -> tuple[str, dict]:
    """Normalise a screenshot for the vision API.

    Returns `(base64_jpeg, metadata)` where metadata carries the perceptual
    hash and final dimensions.
    """
    img = decode_base64_image(image_b64)
    original = img.size

    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = target_size(*img.size)
    if (w, h) != img.size:
        # LANCZOS keeps glyph edges intact when shrinking dense text; the
        # default filter smears them.
        img = img.resize((w, h), Image.Resampling.LANCZOS)

    fingerprint = dhash(img)

    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=settings.image_jpeg_quality,
        # 4:4:4. Screenshots are coloured text on flat backgrounds; the default
        # 4:2:0 chroma subsampling bleeds syntax highlighting into the glyphs.
        subsampling=0,
        # Deliberately NOT optimize=True. Pillow's optimised Huffman pass needs
        # the whole encoded frame to fit in one MAXBLOCK buffer, and at 4:4:4 a
        # screenshot containing a photo or video overflows it and raises
        # "broken data stream when writing image file". It buys a few percent
        # of file size for a hard failure on exactly the frames that are
        # already the largest.
    )
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")

    meta = {
        "hash": fingerprint,
        "width": w,
        "height": h,
        "original": original,
        "bytes": buf.tell(),
        "estimated_tokens": estimate_tokens(w, h),
    }
    return encoded, meta


def dhash(img: Image.Image, size: int = _HASH_SIZE) -> int:
    """Difference hash — a fingerprint that survives requantisation.

    Adjacent-pixel comparisons on a tiny greyscale thumbnail, so two captures
    of the same static screen hash identically even though their JPEG bytes
    differ.
    """
    small = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    # tobytes() over getdata(): one byte per pixel in mode "L", stable across
    # Pillow versions, and not deprecated.
    pixels = small.tobytes()
    bits = 0
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            bits = (bits << 1) | int(pixels[base + col] > pixels[base + col + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def is_duplicate(a: int, b: int) -> bool:
    return hamming(a, b) <= settings.duplicate_hash_distance


def estimate_tokens(width: int, height: int) -> int:
    """Approximate prompt-token cost of one `detail: high` image."""
    if width <= 0 or height <= 0:
        return 0
    scale = 768 / min(width, height)
    w, h = width * scale, height * scale
    tiles = -(-int(w) // 512) * -(-int(h) // 512)
    return tiles * 170 + 85
