"""
scan_reader.py - The text of a scanned book, read from its page images by Gemini Vision.

A scanned PDF holds only pictures of its pages. Before such a book is translated as text, read aloud or summarised,
every page image goes to Gemini once, and the text read is kept next to the uploaded file (`<file>.scantext.json`).
From then on the PDF parser returns that text (backend.parsers.parse_pdf), so translation, audiobooks and Book Insights
work as they do with a digital book.

Pages are read on the Flash-Lite models first: reading print is easy for them and their daily allowance is large, which
leaves the small allowance of the best model for the translation itself. Every answer is also cached by the picture's
hash, so a page read once never costs a request again, even if the text file is lost.
"""

import asyncio
import json
import logging
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".scantext.json"
FORMAT_VERSION = 1
READ_WORKERS = 3
LONG_SIDE_PX = 1600          # sharp enough for body text, small enough to send quickly
NO_TEXT = "[NO TEXT]"
LIGHT_MODELS_FIRST = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]
SAVE_EVERY_PAGES = 10
SAVE_EVERY_SECONDS = 15.0

READ_PROMPT = (
    "The picture is one scanned page of a book. Write out the text printed on it, exactly as printed and in its own "
    "language. Do not translate, summarise, correct or comment.\n"
    "- One paragraph per block, with a blank line between paragraphs. Join the lines of a paragraph, and join a word "
    "that is hyphenated at the end of a line.\n"
    "- Read columns in reading order, one after the other.\n"
    "- Put a heading or chapter title on its own line.\n"
    "- Leave out the running header, the running footer and the page number.\n"
    "- Put footnotes after the main text.\n"
    f"- If the page has no text (a picture or an empty page), answer exactly: {NO_TEXT}\n"
    "Answer with the page's text only."
)
READ_REQUEST = "Read this page."


def sidecar_path(file_path: str) -> Path:
    p = Path(file_path)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def _source_size(file_path: str) -> int:
    try:
        return Path(file_path).stat().st_size
    except OSError:
        return -1


def load_scan_text(file_path: str) -> dict[str, Any]:
    """The pages read so far: {"pages": {"1": text, ...}, "total": n, "complete": bool, "blocked": [page, ...]}.
    Empty when nothing was read, or when the text belongs to another file of the same name."""
    empty: dict[str, Any] = {"version": FORMAT_VERSION, "source_size": _source_size(file_path), "total": 0,
                             "pages": {}, "complete": False, "blocked": []}
    path = sidecar_path(file_path)
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Scanned-text file unreadable, the pages will be read again: {e}")
        return empty
    if (not isinstance(data, dict) or data.get("version") != FORMAT_VERSION
            or data.get("source_size") != empty["source_size"] or not isinstance(data.get("pages"), dict)):
        return empty
    data.setdefault("blocked", [])
    return data


def _save(file_path: str, data: dict[str, Any]) -> None:
    path = sidecar_path(file_path)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        for attempt in range(4):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: a virus scanner may hold the file for a moment
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_pages(file_path: str) -> Optional[list[dict[str, Any]]]:
    """The pages read so far, as the parser yields them ({page, text, total}); None when none was read. After a sample
    only its pages are read: translation, audiobooks and Book Insights read the rest before they start."""
    data = load_scan_text(file_path)
    pages = data["pages"]
    if not pages:
        return None
    total = int(data.get("total") or 0) or max(int(k) for k in pages)
    return [{"page": n, "text": pages[str(n)], "total": total}
            for n in range(1, total + 1) if (pages.get(str(n)) or "").strip()]


def scan_text_complete(file_path: str) -> bool:
    """Every page of the scanned PDF has been read."""
    return bool(load_scan_text(file_path).get("complete"))


def pages_to_read(file_path: str) -> int:
    """Pages of a scanned PDF still waiting to be read."""
    data = load_scan_text(file_path)
    if data.get("complete"):
        return 0
    try:
        import pymupdf
        with pymupdf.open(file_path) as doc:
            total = len(doc)
    except Exception:
        return 0
    return max(0, total - len(data["pages"]))


def is_scanned_pdf(file_path: str, file_type: str, file_name: str = "") -> bool:
    if (file_type or "").lower().lstrip(".") != "pdf" or not file_path or not Path(file_path).is_file():
        return False
    from backend.parsers import detect_is_graphic_novel
    return bool(detect_is_graphic_novel(file_path, "pdf", file_name).get("is_scanned"))


def needs_reading(file_path: str, file_type: str, file_name: str = "") -> bool:
    """A scanned PDF whose text has not been read yet (in full)."""
    return is_scanned_pdf(file_path, file_type, file_name) and not scan_text_complete(file_path)


# ---------------------------------------------------------------------------
# A scanned book or a scanned comic?
# ---------------------------------------------------------------------------

def _looks_like_printed_page(img) -> bool:
    """A page of print: light, nearly colourless paper with thin text, without the large dark or coloured areas of a
    comic's artwork."""
    from PIL import ImageStat
    saturation = ImageStat.Stat(img.convert("HSV").getchannel("S")).mean[0] / 255.0
    hist = img.convert("L").histogram()
    total = float(sum(hist)) or 1.0
    light = sum(hist[170:]) / total
    dark = sum(hist[:70]) / total
    return saturation < 0.2 and light > 0.55 and dark < 0.1


def guess_scanned_book(file_path: str, file_name: str = "") -> bool:
    """Whether a scanned PDF is more likely a book of text than a comic (the upload card preselects that choice)."""
    from backend.parsers import COMIC_FILENAME_PATTERNS
    if any(k in (file_name or Path(file_path).name).lower() for k in COMIC_FILENAME_PATTERNS):
        return False
    try:
        import pymupdf
        from PIL import Image
        with pymupdf.open(file_path) as doc:
            total = len(doc)
            if total == 0:
                return False
            first = 1 if total > 2 else 0           # the cover is often in colour
            count = min(6, total - first)
            step = max(1, (total - first) // count)
            indices = sorted({min(total - 1, first + i * step) for i in range(count)})
            printed = 0
            for i in indices:
                pix = doc[i].get_pixmap(dpi=40, colorspace=pymupdf.csRGB, alpha=False)
                if _looks_like_printed_page(Image.frombytes("RGB", (pix.width, pix.height), pix.samples)):
                    printed += 1
        return printed >= math.ceil(len(indices) * 0.6)
    except Exception as e:
        logger.debug(f"Scanned book guess skipped: {e}")
        return False


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _page_needs_vision(page) -> bool:
    from backend.comic_translator import _is_image_page
    blocks = [b for b in page.get_text("blocks") if len(b) >= 5 and b[4].strip() and b[1] != b[3]]
    return _is_image_page(page, blocks, True)


def _render_page(page) -> bytes:
    import io
    import pymupdf
    from PIL import Image
    long_side_pt = max(page.rect.width, page.rect.height) or 1.0
    dpi = max(100, min(220, int(LONG_SIDE_PX / long_side_pt * 72)))
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80, optimize=True)
    return buf.getvalue()


def _tidy(answer: str) -> str:
    from backend.parsers import _clean_text
    text = (answer or "").strip()
    if text.upper().strip(" .") in (NO_TEXT.upper(), NO_TEXT.upper().strip("[]")):
        return ""
    return _clean_text(text)


class ScanReadError(RuntimeError):
    """Some pages could not be read; the pages read are kept, so starting again reads only the rest."""


async def read_scanned_text(
    file_path: str,
    api_key: str,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    page_range: Optional[tuple] = None,
) -> dict[str, Any]:
    """Reads every page of a scanned PDF that has not been read yet and saves the text next to the file.
    ``page_range`` (first, last): a sample reads only those pages, and two more, since a translation batch may run on.
    Raises DailyQuotaExhaustedError and PermissionError like the other Gemini work (what was read stays saved), and
    ScanReadError when pages failed for another reason. Returns {"total", "read", "blocked", "complete"}."""
    import aiohttp
    import pymupdf
    from backend.ai_polisher import _call_gemini_api, _ContentBlockedError, DailyQuotaExhaustedError
    from backend.parsers import _clean_text, _extract_page_text

    data = load_scan_text(file_path)
    pages: dict[str, str] = data["pages"]
    blocked: list[int] = [int(b) for b in data.get("blocked", []) if str(b).isdigit()]
    failed: dict[int, str] = {}
    read_now = 0
    last_save = {"t": time.monotonic(), "n": 0}
    lock = asyncio.Lock()
    render_lock = asyncio.Lock()

    def _is_cancelled() -> bool:
        return bool(cancelled and cancelled())

    with pymupdf.open(file_path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF file is password-protected / encrypted and cannot be read without a password.")
        total = len(doc)
        data["total"] = total
        wanted = range(total)
        if page_range:
            wanted = range(max(0, int(page_range[0]) - 1), min(total, int(page_range[1]) + 2))
        todo: list[int] = []
        for i in wanted:
            if str(i + 1) in pages:
                continue
            page = doc[i]
            if _page_needs_vision(page):
                todo.append(i)
            else:  # a page with real text (a digital title page in a scan): its own text
                pages[str(i + 1)] = _clean_text(_extract_page_text(page))
        shown_total = len(wanted)
        done = shown_total - len(todo)
        if progress:
            progress(done, shown_total)

        async def _save_now(force: bool = False) -> None:
            async with lock:
                now = time.monotonic()
                if force or read_now - last_save["n"] >= SAVE_EVERY_PAGES or now - last_save["t"] >= SAVE_EVERY_SECONDS:
                    data["blocked"] = sorted(set(blocked))
                    await asyncio.to_thread(_save, file_path, json.loads(json.dumps(data)))
                    last_save.update(t=now, n=read_now)

        sem = asyncio.Semaphore(READ_WORKERS)
        connector = aiohttp.TCPConnector(limit=8, ttl_dns_cache=300)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120), connector=connector) as session:
                async def _read(i: int) -> None:
                    nonlocal done, read_now
                    async with sem:
                        if _is_cancelled():
                            raise asyncio.CancelledError("Cancelled by user.")
                        async with render_lock:  # one page at a time: the document is not thread-safe
                            jpeg = await asyncio.to_thread(_render_page, doc[i])
                        last_error: Optional[Exception] = None
                        text: Optional[str] = None
                        for attempt in range(2):
                            try:
                                text = await _call_gemini_api(
                                    READ_REQUEST, api_key, READ_PROMPT, session=session, temperature=0.0,
                                    image=("image/jpeg", jpeg), prefer_models=LIGHT_MODELS_FIRST,
                                    cache_gate=lambda out: bool(out.strip()),
                                )
                                break
                            except (PermissionError, DailyQuotaExhaustedError):
                                raise
                            except _ContentBlockedError as e:  # Gemini refuses this page: it stays empty, noted
                                logger.warning(f"Scanned page {i + 1} was refused by Gemini ({e}); it stays empty.")
                                blocked.append(i + 1)
                                text = ""
                                break
                            except Exception as e:
                                last_error = e
                                if attempt == 0:
                                    await asyncio.sleep(3.0)
                        if text is None:
                            failed[i + 1] = str(last_error or "no answer")[:160]
                            logger.warning(f"Scanned page {i + 1} could not be read: {failed[i + 1]}")
                            return
                        pages[str(i + 1)] = _tidy(text)
                        read_now += 1
                        done += 1
                    if progress:
                        progress(done, shown_total)
                    await _save_now()

                from backend.async_utils import gather_or_cancel
                await gather_or_cancel(_read(i) for i in todo)
        finally:
            await _save_now(force=True)

    if failed:
        shown = ", ".join(map(str, sorted(failed)[:10])) + (" …" if len(failed) > 10 else "")
        reasons = list(failed.values())
        raise ScanReadError(
            f"{len(failed)} scanned page(s) could not be read ({shown}): {max(set(reasons), key=reasons.count)}. "
            f"Start again to read them: the pages already read are kept.")
    data["complete"] = all(str(n) in pages for n in range(1, total + 1))
    data["blocked"] = sorted(set(blocked))
    await asyncio.to_thread(_save, file_path, data)
    logger.info(f"Scanned book: {len(pages)}/{total} pages read ({read_now} by Gemini Vision now) "
                f"-> {sidecar_path(file_path).name}")
    return {"total": total, "read": read_now, "blocked": data["blocked"], "complete": data["complete"]}
