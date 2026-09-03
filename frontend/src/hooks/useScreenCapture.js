/**
 * Screen capture via getDisplayMedia.
 *
 * Frames are captured at exactly the resolution the vision model will use, and
 * encoded losslessly. Rationale:
 *
 *  - The API rescales high-detail images so the short side is 768px, then bills
 *    by 512px tile. Capturing larger wastes upload for pixels that get thrown
 *    away; capturing smaller pays the same tokens for a blur.
 *  - The downscale from a 1440p or 4K screen is where on-screen text is won or
 *    lost, so it is done in steps (see `drawScaled`) rather than in one jump.
 *  - PNG by default, not JPEG. The browser's JPEG encoder uses 4:2:0 chroma
 *    subsampling, which smears coloured syntax highlighting into the glyph
 *    edges. The backend does a single chroma-preserving JPEG encode instead, so
 *    the frame is compressed once rather than twice. A screen dominated by
 *    photo or video content falls back to a high-quality JPEG to bound size.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { CAPTURE_MAX_LONG_SIDE, CAPTURE_SHORT_SIDE } from "../config";

/** Above this encoded size, fall back from PNG to high-quality JPEG (~2 MB). */
const MAX_PNG_CHARS = 2_800_000;

/** Target dimensions: short side at the tile boundary, never upscaled. */
export function targetSize(width, height) {
  if (!width || !height) return { width: 0, height: 0 };

  let scale = Math.min(CAPTURE_SHORT_SIDE / Math.min(width, height), 1);
  let w = Math.round(width * scale);
  let h = Math.round(height * scale);

  if (Math.max(w, h) > CAPTURE_MAX_LONG_SIDE) {
    const shrink = CAPTURE_MAX_LONG_SIDE / Math.max(w, h);
    w = Math.round(w * shrink);
    h = Math.round(h * shrink);
  }
  return { width: Math.max(w, 1), height: Math.max(h, 1) };
}

/**
 * Draw `source` into `canvas` at the target size, halving repeatedly when the
 * reduction is large.
 *
 * A single drawImage from 3840px to 768px samples far too sparsely and turns
 * small text into aliased mush regardless of imageSmoothingQuality. Halving
 * first averages every source pixel into the result.
 */
function drawScaled(source, sourceWidth, sourceHeight, canvas, target) {
  let currentWidth = sourceWidth;
  let currentHeight = sourceHeight;
  let current = source;
  const scratch = [];

  while (currentWidth > target.width * 2 && currentHeight > target.height * 2) {
    const nextWidth = Math.max(Math.round(currentWidth / 2), target.width);
    const nextHeight = Math.max(Math.round(currentHeight / 2), target.height);

    const next = document.createElement("canvas");
    next.width = nextWidth;
    next.height = nextHeight;
    const nextCtx = next.getContext("2d");
    nextCtx.imageSmoothingEnabled = true;
    nextCtx.imageSmoothingQuality = "high";
    nextCtx.drawImage(current, 0, 0, currentWidth, currentHeight, 0, 0, nextWidth, nextHeight);

    current = next;
    currentWidth = nextWidth;
    currentHeight = nextHeight;
    scratch.push(next);
  }

  canvas.width = target.width;
  canvas.height = target.height;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(
    current,
    0,
    0,
    currentWidth,
    currentHeight,
    0,
    0,
    target.width,
    target.height
  );

  // Release the intermediates promptly rather than waiting for GC — at 4K
  // these are several megabytes each and one is allocated per capture.
  for (const canvasToFree of scratch) {
    canvasToFree.width = 0;
    canvasToFree.height = 0;
  }
}

export function useScreenCapture() {
  const [isSharing, setIsSharing] = useState(false);
  const [error, setError] = useState(null);
  const streamRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  const releaseStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const stopCapture = useCallback(() => {
    releaseStream();
    setIsSharing(false);
  }, [releaseStream]);

  // Re-attach the stream after a re-render swaps the video element out.
  useEffect(() => {
    if (isSharing && streamRef.current && videoRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, [isSharing]);

  // Release the display stream if the component unmounts while sharing —
  // otherwise the browser keeps showing its "sharing your screen" indicator.
  useEffect(() => releaseStream, [releaseStream]);

  const startCapture = useCallback(async () => {
    try {
      setError(null);

      // CaptureController stops Chrome pulling focus to the shared surface the
      // moment sharing begins, which would otherwise yank the user out of the
      // window they are trying to read.
      const controller = "CaptureController" in window ? new CaptureController() : null;

      const options = {
        video: { cursor: "always", displaySurface: "monitor" },
        audio: false,
      };
      if (controller) options.controller = controller;

      const stream = await navigator.mediaDevices.getDisplayMedia(options);

      if (controller) {
        try {
          controller.setFocusBehavior("no-focus-change");
        } catch {
          // Unsupported in this browser; harmless.
        }
      }

      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => {});
      }
      setIsSharing(true);

      // The user can end sharing from the browser's own bar.
      stream.getVideoTracks()[0].addEventListener("ended", () => {
        releaseStream();
        setIsSharing(false);
      });

      return true;
    } catch (err) {
      setError(
        err.name === "NotAllowedError"
          ? "Screen sharing was denied. Allow screen access and try again."
          : `Could not start screen capture: ${err.message}`
      );
      setIsSharing(false);
      return false;
    }
  }, [releaseStream]);

  /**
   * Grab the current frame as base64 (no data-URL prefix).
   * Returns null if the stream is not producing frames yet.
   */
  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !isSharing) return null;
    if (!video.videoWidth || !video.videoHeight) return null;

    const target = targetSize(video.videoWidth, video.videoHeight);
    drawScaled(video, video.videoWidth, video.videoHeight, canvas, target);

    // PNG is lossless, and at this size a page of text or code encodes small.
    // A photo or video filling the screen does not, so fall back to a very
    // high quality JPEG rather than pushing multiple megabytes over the wire.
    const png = canvas.toDataURL("image/png");
    if (png.length <= MAX_PNG_CHARS) return png.split(",")[1];
    return canvas.toDataURL("image/jpeg", 0.95).split(",")[1];
  }, [isSharing]);

  return {
    isSharing,
    error,
    startCapture,
    stopCapture,
    captureFrame,
    videoRef,
    canvasRef,
  };
}
