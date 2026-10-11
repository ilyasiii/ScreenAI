"""
PDF text extraction in a child process.

PDF parsing runs attacker-supplied input through a complex parser: a 20 KB
file whose pages share one huge compressed stream can take minutes of CPU, and
a thread cannot be stopped once started. A process can. Each extraction runs
in a fresh child that is killed at the deadline and, on Linux, capped in
memory, so a hostile upload costs at most `timeout` seconds of one core.

This module imports only pypdf so the spawned child starts quickly.
"""

import multiprocessing as mp
import sys

# Address-space cap for the child on Linux (pypdf allows 75 MB per stream).
_CHILD_MEMORY_BYTES = 512 * 1024 * 1024


class PdfTimeout(Exception):
    pass


class PdfError(Exception):
    pass


def _worker(data: bytes, max_pages: int, max_chars: int, conn) -> None:
    try:
        if sys.platform.startswith("linux"):
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (_CHILD_MEMORY_BYTES, _CHILD_MEMORY_BYTES))

        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        total = 0
        for index, page in enumerate(reader.pages):
            if index >= max_pages or total >= max_chars:
                break
            text = page.extract_text() or ""
            if text:
                pages.append(text)
                total += len(text)
        conn.send(("ok", "\n".join(pages)[:max_chars]))
    except BaseException as exc:  # noqa: BLE001 - report anything, including MemoryError
        conn.send(("error", exc.__class__.__name__))
    finally:
        conn.close()


def extract_text(data: bytes, max_pages: int, max_chars: int, timeout: float) -> str:
    """Blocking. Run from a worker thread, never on the event loop."""
    # "spawn" everywhere: safe to start from a multi-threaded server, unlike fork.
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_worker, args=(data, max_pages, max_chars, child), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise PdfTimeout()
        try:
            status, payload = parent.recv()
        except EOFError as exc:  # child died without reporting (killed by the OS)
            raise PdfError("worker exited") from exc
        if status != "ok":
            raise PdfError(payload)
        return payload
    finally:
        parent.close()
        if proc.is_alive():
            proc.kill()
        proc.join(timeout=5)
