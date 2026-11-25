"""
Main FastAPI application for the Document Translator & Audiobook Generator.
"""

import asyncio
import io
import json
import logging
import os
import re
import shutil
import time
import uuid
from urllib.parse import urlsplit, quote
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.api.common import (  # noqa: E402
    BASE_DIR, TEMP_DIR, UPLOAD_DIR, OUTPUT_DIR, MIME_MAP, _validate_job_id, _job_output_dir,
    OUTPUT_FORMATS, LAYOUT_MODES, READING_DIRECTIONS, QUOTA_BEHAVIORS, _validate_choice, _validate_language,
    purge_job,
)
from backend.job_manager import (
    create_job, get_job, update_job, list_jobs, cleanup_old_jobs,
    cancel_job, clear_job_cancellation, register_task, unregister_task, is_job_cancelled,
    cleanup_test_jobs, is_test_job_identifier, mark_interrupted, is_resumable, is_quota_stop, is_quota_error,
    job_owner,
)
from backend import auth
from backend.request_context import current_user, set_current_user, reset_current_user, can_view_owner
from backend.parsers import count_pages, parse_document
from backend.translator import translate_document
from backend.tts_engine import (
    generate_audiobook, get_available_voices, export_audiobook_m4b, find_ffmpeg, is_mp4_file,
    M4BExportError, M4BUnavailableError,
)
from backend.exporter import export_text
from backend import format_sync
from backend.format_preserver import translate_docx_in_place, translate_epub_in_place
from backend.ai_polisher import POLISH_STATUS
# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

async def _quota_auto_resume_monitor():
    """Background task monitoring Gemini API quota reset and auto-resuming paused batch queue items."""
    from backend.gemini_key_pool import GeminiKeyPool
    from backend.ai_polisher import is_gemini_quota_exhausted
    from backend.queue_manager import is_queue_paused_for_quota, quota_retry_due, resume_queue_after_quota
    while True:
        try:
            await asyncio.sleep(3.0)
            GeminiKeyPool.check_cooldowns()
            # without any key "wait" must keep waiting, not silently continue on the free engine
            if GeminiKeyPool.get_keys() and not is_gemini_quota_exhausted():
                if is_queue_paused_for_quota() and quota_retry_due():
                    logger.info("[Auto-Resume Monitor] Gemini API quota reset! Automatically resuming paused batch queue items...")
                    resume_queue_after_quota(_execute_queue_item)
        except asyncio.CancelledError:
            break
        except Exception as ex:
            logger.debug(f"[Auto-Resume Monitor] Loop tick error: {ex}")
            await asyncio.sleep(3.0)


def _is_quota_failure(error: Exception, uses_ai: bool) -> bool:
    """Whether a failed job stopped for Gemini quota, rather than failing for its own reason while quota is low."""
    from backend.ai_polisher import DailyQuotaExhaustedError, is_gemini_quota_exhausted
    from backend.translator import TranslationUnavailableError
    from backend.tts_engine import NarrationError
    if isinstance(error, DailyQuotaExhaustedError):
        return True
    if isinstance(error, (TranslationUnavailableError, NarrationError, FileNotFoundError)):
        return False
    if is_quota_error(str(error)):
        return True
    return uses_ai and not isinstance(error, (ValueError, OSError)) and is_gemini_quota_exhausted()


def _quota_stop_step(error: Exception, quota: dict) -> str:
    """A per-minute 429 also pauses a job, but then the day's allowance is not used up."""
    from backend.ai_polisher import DailyQuotaExhaustedError
    if quota.get("exhausted") or isinstance(error, DailyQuotaExhaustedError) or "429" not in str(error):
        return "⚠️ Σταμάτησε: Εξαντλήθηκε το ημερήσιο όριο Gemini API"
    return "⚠️ Σταμάτησε: όριο αιτημάτων Gemini (429)· συνεχίστε σε ένα λεπτό"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("DocTranslate & AudioBook Generator started.")
    from backend import device_pairing
    if device_pairing.is_enabled():
        code = device_pairing.create_pairing_code()
        logger.warning(
            "[Pairing] Device pairing is ON: only paired devices%s may use BookApp. "
            "Pair a device by opening (valid %d min, single use):  http://<this-computer>:8000/pair?code=%s",
            " and this computer" if device_pairing.trust_loopback() else "",
            device_pairing.PAIRING_CODE_TTL // 60, code,
        )
    if auth.is_enabled():
        if os.environ.get("BOOKAPP_PAIRING", "").strip().lower() in ("1", "true", "yes", "on"):
            logger.warning("[Auth] BOOKAPP_PAIRING is ignored: user accounts (BOOKAPP_AUTH=1) replace device pairing.")
        if auth.setup_required():
            auth.announce_setup_code()
        else:
            logger.info("[Auth] User accounts are ON: signing in is required.")
    cleanup_old_jobs()
    cleanup_test_jobs()
    from backend.queue_manager import restore_queue
    restore_queue()
    monitor_task = asyncio.create_task(_quota_auto_resume_monitor())
    try:
        yield
    finally:
        monitor_task.cancel()


app = FastAPI(
    title="DocTranslate & AudioBook",
    description="Translate documents and generate audiobooks powered by neural AI",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: the UI is served by this same server (same origin), so cross-origin access is only needed for local
# development tools. A wildcard would let ANY website open in the user's browser read /api/settings (incl. the
# Gemini API keys) or send JSON/DELETE requests to the local app. Extra origins can be allowed explicitly via
# BOOKAPP_CORS_ORIGINS="https://a.example,https://b.example".
_EXTRA_CORS_ORIGINS = [o.strip() for o in os.environ.get("BOOKAPP_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_EXTRA_CORS_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_own_origin(origin: str, headers) -> bool:
    """Whether `origin` is the address this request was sent to (or that a reverse proxy says it was sent to)."""
    try:
        source = urlsplit(origin)
        source_port = source.port or {"http": 80, "https": 443}.get(source.scheme)
        for name in ("host", "x-forwarded-host"):
            value = (headers.get(name) or "").split(",")[0].strip()
            if not value or not source.hostname:
                continue
            target = urlsplit(f"//{value}")
            # a proxy's "Host $host" drops the port, so it is compared only when it is there
            if target.hostname == source.hostname and (target.port is None or target.port == source_port):
                return True
    except ValueError:
        pass
    return False


@app.middleware("http")
async def refuse_cross_site_changes(request: Request, call_next):
    """CORS only hides responses: a form on any website could still POST here (upload, start, pause, clean-up)."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin", "")
        site = request.headers.get("sec-fetch-site")
        # Browsers send Sec-Fetch-Site only to HTTPS and localhost addresses; they send Origin with every POST.
        # A request with neither comes from a program, not from a website.
        foreign = site == "cross-site" if site else bool(origin) and not _is_own_origin(origin, request.headers)
        if foreign and origin not in _EXTRA_CORS_ORIGINS and not re.fullmatch(
                r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?", origin):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def device_pairing_guard(request: Request, call_next):
    """Opt-in (BOOKAPP_PAIRING=1): only the host computer and paired devices may use the app. No-op when disabled."""
    from backend import device_pairing
    if not device_pairing.is_enabled() or device_pairing.is_open_path(request.url.path):
        return await call_next(request)
    client = request.client.host if request.client else None
    if device_pairing.is_trusted(client, request.cookies.get(device_pairing.COOKIE_NAME)):
        return await call_next(request)
    from fastapi.responses import JSONResponse, HTMLResponse
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "This device is not paired with BookApp. Open a pairing link first."},
                            status_code=403)
    return HTMLResponse(device_pairing.NOT_PAIRED_HTML, status_code=403)


_JOB_ID_SEGMENT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@app.middleware("http")
async def account_login_guard(request: Request, call_next):
    """
    Opt-in (BOOKAPP_AUTH=1): signing in is required; users reach only their own jobs; some endpoints are for
    administrators only (backend/auth.py). No-op when user accounts are off.
    """
    if not auth.is_enabled():
        return await call_next(request)
    from fastapi.responses import JSONResponse, RedirectResponse, PlainTextResponse
    path = request.url.path
    if request.method == "OPTIONS" or auth.is_open_path(path):
        return await call_next(request)
    is_api = path.startswith("/api/")
    is_page = request.method in ("GET", "HEAD") and (path in ("", "/") or path.endswith(".html"))

    token = request.cookies.get(auth.SESSION_COOKIE)
    session = await asyncio.to_thread(auth.session_for_token, token) if token else None
    if not session:
        setup = await asyncio.to_thread(auth.setup_required)
        if is_api:
            msg = "Η εφαρμογή χρειάζεται αρχική ρύθμιση (/setup)." if setup else "Συνδεθείτε για να συνεχίσετε."
            return JSONResponse({"detail": msg, "auth_required": True, "setup_required": setup}, status_code=401)
        if is_page:
            nxt = "" if path in ("", "/") else f"?next={quote(path)}"
            return RedirectResponse("/setup" if setup else f"/login{nxt}", status_code=303)
        return PlainTextResponse("Sign in required.", status_code=401)

    user = session["user"]
    if user["must_change"] and path not in auth.PASSWORD_CHANGE_PATHS:
        if is_api:
            return JSONResponse({"detail": "Αλλάξτε πρώτα τον προσωρινό κωδικό σας.", "password_change_required": True},
                                status_code=403)
        if is_page:
            return RedirectResponse("/login?change=1", status_code=303)
        return PlainTextResponse("Password change required.", status_code=403)
    if user["role"] != "admin" and auth.is_admin_path(request.method, path):
        return JSONResponse({"detail": "Μόνο οι διαχειριστές έχουν πρόσβαση σε αυτή τη λειτουργία."}, status_code=403)

    ctx_token = set_current_user(user)
    try:
        if user["role"] != "admin":
            # Another user's job id in the URL (status, download, progress, insights files, ...): "not found"
            for seg in path.split("/"):
                if _JOB_ID_SEGMENT.fullmatch(seg):
                    owner = job_owner(seg)
                    if owner is not None and not can_view_owner(owner):
                        return JSONResponse({"detail": f"Job '{seg}' not found."}, status_code=404)
        response = await call_next(request)
    finally:
        reset_current_user(ctx_token)
    if session["renewed"] and session["persistent"]:
        from backend.api.auth import set_session_cookie
        set_session_cookie(response, request, token, True)  # "keep me signed in" slides forward with every visit
    return response


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".js", ".css", ".html")) or path in ("/", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Directories, MIME types and job-id/path helpers live in backend/api/common.py (shared with routers)

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    job_id: str
    source_lang: str   # 'english' or 'greek'
    target_lang: str   # 'english' or 'greek'
    output_format: Optional[str] = None  # None matches input document format (e.g. PDF->PDF, DOCX->DOCX)
    layout_mode: str = "standard"  # 'standard', 'literature', or 'comic'
    reading_direction: str = "ltr"  # 'ltr' or 'rtl' (Manga)
    ai_polish: bool = False
    api_key: Optional[str] = None
    quota_behavior: str = "wait"  # 'wait' (pause at checkpoint for quota reset) or 'fallback' (auto-fallback to free engine)
    final_refinement: Optional[bool] = None
    max_quality: bool = False  # Advanced Mode: 2nd Gemini pass revising the AI translation against the original
    read_scanned_text: Optional[bool] = None  # scanned PDF: True = a book (read its text first), False = a comic
    page_from: Optional[int] = None  # a sample: translate only pages page_from..page_to
    page_to: Optional[int] = None


class AudiobookRequest(BaseModel):
    job_id: str
    language: str      # 'english' or 'greek' — language of the audio output
    voice_name: str    # e.g. 'Nestoras (Male)'
    dialogue_voice: Optional[str] = None  # optional second voice for character speech / dialogues
    use_translated: bool = False  # if True, use the translated text from a prior translation job
    narration_style: str = "literature"  # 'literature' (natural book flow) or 'standard'
    rate: Optional[str] = None           # optional explicit speed e.g. '-18%', '-10%', '+0%'
    pitch: Optional[str] = None          # optional explicit pitch e.g. '-2Hz', '-1Hz', '+0Hz'
    ai_polish: bool = False              # if True, polish script with Gemini before TTS
    api_key: Optional[str] = None        # optional Gemini API key override
    quota_behavior: str = "wait"         # 'wait' or 'fallback'
    final_refinement: Optional[bool] = None


class GenreDetectionRequest(BaseModel):
    sample_text: Optional[str] = None
    text: Optional[str] = None
    file_type: Optional[str] = ""
    subjects: Optional[list[str]] = None  # what the file says about itself (from /api/preview)


class AdminCleanupRequest(BaseModel):
    max_age_hours: int = 48
    dry_run: bool = False


class QueueAddRequest(BaseModel):
    job_id: str
    source_lang: str = "english"
    target_lang: str = "greek"
    output_format: str = "pdf"
    layout_mode: str = "standard"
    reading_direction: str = "ltr"
    ai_polish: bool = False
    api_key: Optional[str] = None
    is_comic: bool = False
    is_scanned: bool = False
    quota_behavior: str = "wait"


class QueueAutoStartRequest(BaseModel):
    auto_start: bool = False


class QueueStartRequest(BaseModel):
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    output_format: Optional[str] = None
    layout_mode: Optional[str] = None
    reading_direction: Optional[str] = None
    ai_polish: Optional[bool] = None
    api_key: Optional[str] = None
    quota_behavior: Optional[str] = None


class UpdateTextRequest(BaseModel):
    translated_text: str


class PolishRequest(BaseModel):
    job_id: Optional[str] = None
    text: Optional[str] = None
    style: str = "formal"
    api_key: Optional[str] = None
    layout_mode: Optional[str] = None
    bilingual_mode: bool = True
    final_refinement: Optional[bool] = None


class GlossaryTermRequest(BaseModel):
    source: str
    target: str
    category: str = "general"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".epub", ".doc", ".cbz", ".cbr", ".zip"}
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


_MAX_STEM_CHARS = 100  # outputs add "_translated_greek.pdf" etc.; Windows paths stop at 260, Linux names at 255 bytes


def _shorten_stem(stem: str, limit: int = _MAX_STEM_CHARS) -> str:
    """A stem of at most `limit` characters, cut at a word boundary where one is near the end."""
    if len(stem) <= limit:
        return stem
    cut = stem[:limit]
    boundary = max(cut.rfind(" "), cut.rfind("_"), cut.rfind("-"))
    if boundary >= limit * 0.6:
        cut = cut[:boundary]
    return cut.rstrip(" .-_,(") or stem[:limit]


def _sanitize_filename(filename: Optional[str]) -> str:
    """Sanitizes uploaded filenames for Windows/POSIX filesystem safety (characters, reserved names, length)."""
    raw = (filename or "document").replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")
    if not cleaned:
        cleaned = "document"
    p = Path(cleaned)
    if p.stem.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"file_{p.stem}{p.suffix}"
    p = Path(cleaned)
    suffix = p.suffix if len(p.suffix) <= 10 else ""
    stem = cleaned[: len(cleaned) - len(suffix)] if suffix else cleaned
    if len(stem) > _MAX_STEM_CHARS:
        # downloaded books often carry 200+ character names (authors, ISBN, hash): too long for the disk paths
        cleaned = _shorten_stem(stem) + suffix
    return cleaned


def _get_file_type(filename: str) -> Optional[str]:
    ext = Path(filename).suffix.lower()
    mapping = {".pdf": "pdf", ".docx": "docx", ".epub": "epub", ".cbz": "cbz", ".cbr": "cbz", ".zip": "cbz"}
    return mapping.get(ext)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "message": "DocTranslate is running"}


def _detect_document_language(file_path: str, file_type: str) -> Optional[str]:
    """Quickly detect whether a document is primarily 'greek' or 'english'."""
    try:
        sample_parts = []
        total_len = 0
        for page in parse_document(file_path, file_type):
            txt = page.get("text", "")
            if txt:
                sample_parts.append(txt)
                total_len += len(txt)
            if total_len >= 3000:
                break
        sample = " ".join(sample_parts)[:3000]
        if not sample.strip():
            return None
        greek_count = sum(1 for ch in sample if ("\u0370" <= ch <= "\u03ff") or ("\u1f00" <= ch <= "\u1fff"))
        latin_count = sum(1 for ch in sample if ("a" <= ch <= "z") or ("A" <= ch <= "Z"))
        if greek_count == 0 and latin_count == 0:
            return None
        return "greek" if greek_count >= latin_count else "english"
    except Exception:
        return None


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a document and create a job. Returns job_id."""
    safe_filename = _sanitize_filename(file.filename)
    ext = Path(safe_filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Supported: PDF, DOCX, EPUB, CBZ, CBR, ZIP.")

    if ext == ".doc":
        raise HTTPException(400, (
            "Legacy .doc format is not supported. "
            "Please save/convert your file as .docx using Microsoft Word or LibreOffice."
        ))

    file_type = _get_file_type(safe_filename)
    MAX_UPLOAD_SIZE_BYTES = 250 * 1024 * 1024  # 250 MB per file

    # Stream upload to temp file while enforcing max size to prevent OOM
    job_dir = UPLOAD_DIR / "tmp"
    job_dir.mkdir(exist_ok=True)
    tmp_path = job_dir / f"{uuid.uuid4().hex}{ext}"  # the name waits for the job directory: no length to spare here
    header_bytes = bytearray()
    total_bytes = 0
    try:
        async with aiofiles.open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                    size_mb = total_bytes / (1024 * 1024)
                    raise HTTPException(
                        413,
                        f"Το αρχείο '{safe_filename}' ({size_mb:.1f} MB) υπερβαίνει το μέγιστο όριο των 250 MB.",
                    )
                if len(header_bytes) < 1024:
                    header_bytes.extend(chunk[: 1024 - len(header_bytes)])
                await out.write(chunk)

        if total_bytes == 0:
            raise HTTPException(
                400,
                f"Το αρχείο '{safe_filename}' είναι κενό (0 bytes) και δεν περιέχει δεδομένα.",
            )

        if ext in (".docx", ".epub", ".cbz", ".zip") and bytes(header_bytes[:2]) != b"PK":
            raise HTTPException(
                400,
                f"Το αρχείο '{safe_filename}' δεν είναι έγκυρο αρχείο {ext.upper()} "
                f"(ενδέχεται να είναι κατεστραμμένο ή παλιό .doc που μετονομάστηκε). "
                f"Ανοίξτε το και αποθηκεύστε το ξανά ως {ext}.",
            )

        if ext == ".pdf" and b"%PDF" not in bytes(header_bytes):
            raise HTTPException(
                400,
                f"Το αρχείο '{safe_filename}' δεν είναι έγκυρο αρχείο PDF (κατεστραμμένη επικεφαλίδα).",
            )

        stored_name = safe_filename
        if ext == ".cbr":
            # RAR inside, or often simply a ZIP: from here on the app only ever sees a CBZ
            from backend.comic_archive import ComicArchiveError, is_rar, rar_to_cbz
            stored_name = f"{Path(safe_filename).stem}.cbz"
            if is_rar(bytes(header_bytes)):
                converted = job_dir / f"{uuid.uuid4().hex}.cbz"
                try:
                    await asyncio.to_thread(rar_to_cbz, tmp_path, converted)
                    await asyncio.to_thread(os.replace, converted, tmp_path)
                except ComicArchiveError as e:
                    raise HTTPException(400, str(e))
                finally:
                    converted.unlink(missing_ok=True)
            elif bytes(header_bytes[:2]) != b"PK":
                raise HTTPException(400, f"Το αρχείο '{safe_filename}' δεν είναι έγκυρο αρχείο CBR.")

        # Create job and move upload atomically to its job directory
        job = create_job(
            file_path=str(tmp_path),
            file_name=safe_filename,
            file_type=file_type,
        )
        job_upload_dir = UPLOAD_DIR / job.job_id
        job_upload_dir.mkdir(exist_ok=True)
        final_path = job_upload_dir / stored_name
        shutil.move(str(tmp_path), str(final_path))
        update_job(job.job_id, file_path=str(final_path))
    except Exception as e:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        if isinstance(e, OSError):  # disk full, permissions, a path the system refuses: say so, not "error 500"
            logger.error(f"Upload of '{safe_filename}' could not be stored: {e}")
            raise HTTPException(500, f"Δεν ήταν δυνατή η αποθήκευση του αρχείου '{safe_filename}' στον server "
                                     f"({e.strerror or e}).")
        raise

    # Extract and cache cover image from original input if present
    try:
        from backend.exporter import extract_cover_image
        cov_bytes = await asyncio.to_thread(extract_cover_image, str(final_path))
        if cov_bytes:
            out_d = _job_output_dir(job.job_id)
            cov_p = out_d / "cover_image.jpg"
            cov_p.write_bytes(cov_bytes)
            logger.info(f"Preserved original cover image for {file.filename} ({len(cov_bytes)} bytes)")
    except Exception as cov_err:
        logger.warning(f"Could not extract cover image for {file.filename}: {cov_err}")

    # Count pages, detect language, and auto-detect Graphic Novel / Scanned Comic.
    # These parse the whole document (CPU/disk bound): run them in a worker thread so a large upload never blocks
    # the event loop (which would freeze SSE progress of running translations/audiobooks).
    try:
        page_count = await asyncio.to_thread(count_pages, str(final_path), file_type)
    except Exception:
        page_count = 0

    detected_language = await asyncio.to_thread(_detect_document_language, str(final_path), file_type)

    from backend.parsers import detect_is_graphic_novel
    comic_info = await asyncio.to_thread(detect_is_graphic_novel, str(final_path), file_type, file.filename)
    # A scanned PDF is a comic (translated on its page images) or a book (its text is read first, then translated as
    # text). The upload card offers both; the guess preselects one.
    scanned_pdf = file_type == "pdf" and bool(comic_info["is_scanned"])
    scanned_book = False
    if scanned_pdf:
        from backend.scan_reader import guess_scanned_book
        scanned_book = await asyncio.to_thread(guess_scanned_book, str(final_path), file.filename)
    is_comic = bool(comic_info["is_comic"]) and not scanned_book

    # Persist page count and auto-detected comic layout in SQLite metadata
    update_job(
        job.job_id,
        total_pages=page_count,
        layout_mode="comic" if is_comic else "standard",
        ai_polish=bool(comic_info["is_scanned"]),
        scanned=scanned_pdf,
        read_scanned_text=scanned_book,
    )

    logger.info(
        f"Uploaded: {file.filename} → job_id={job.job_id}, pages≈{page_count}, lang={detected_language}, is_comic={comic_info['is_comic']}, is_scanned={comic_info['is_scanned']}"
    )

    return {
        "job_id": job.job_id,
        "file_name": file.filename,
        "file_type": file_type,
        "estimated_pages": page_count,
        "detected_language": detected_language,
        "is_comic": is_comic,
        "is_scanned": comic_info["is_scanned"],
        "scan_kind": ("book" if scanned_book else "comic") if scanned_pdf else "",
        "comic_reason": comic_info["reason"],
    }


@app.post("/api/translate")
async def start_translation(req: TranslateRequest, background_tasks: BackgroundTasks):
    """Start a translation job in the background."""
    _validate_job_id(req.job_id)
    job = get_job(req.job_id)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found.")

    if job.status == "running":
        raise HTTPException(409, "A task is already running for this job.")

    src_lang = (req.source_lang or "").strip().lower()
    tgt_lang = (req.target_lang or "").strip().lower()
    if not src_lang or not tgt_lang or src_lang == tgt_lang:
        raise HTTPException(400, "Source and target languages must be different.")
    _validate_language(src_lang, "source_lang")
    _validate_language(tgt_lang, "target_lang")

    output_dir = _job_output_dir(req.job_id)
    stem = Path(job.file_name).stem
    output_path = str(output_dir / f"{stem}_translated_{tgt_lang}.txt")

    output_format = (getattr(req, "output_format", "") or "").strip().lower().lstrip(".")
    if not output_format:
        inp_ext = (job.file_type or Path(job.file_name or "").suffix or "pdf").lower().lstrip(".")
        if inp_ext in {"pdf", "docx", "doc", "epub", "cbz", "cbr", "txt"}:
            output_format = inp_ext
        elif inp_ext in {"zip"}:
            output_format = "cbz"
        else:
            output_format = "pdf"
    if output_format not in {"txt", "docx", "doc", "pdf", "epub", "cbz", "cbr"}:
        raise HTTPException(400, f"Unsupported output format '{output_format}'.")
    layout_mode = _validate_choice(req.layout_mode, LAYOUT_MODES, "layout_mode") or "standard"
    reading_direction = (getattr(req, "reading_direction", "ltr") or "ltr").strip().lower()
    if reading_direction not in {"ltr", "rtl"}:
        reading_direction = "ltr"

    from backend.gemini_key_pool import resolve_gemini_api_key
    resolved_key = resolve_gemini_api_key(req.api_key)

    quota_behavior = (getattr(req, "quota_behavior", "") or "").strip().lower()
    if not quota_behavior:
        quota_behavior = "wait" if resolved_key else "fallback"
    elif not resolved_key and quota_behavior == "wait":
        # Free models are the default when no Gemini API key is configured
        quota_behavior = "fallback"
    if quota_behavior not in ("wait", "fallback"):
        quota_behavior = "fallback" if not resolved_key else "wait"

    read_scanned = (bool(req.read_scanned_text) if req.read_scanned_text is not None
                    else bool(getattr(job, "read_scanned_text", False)))
    if layout_mode == "comic":
        read_scanned = False
    sample_range = _requested_sample(job, req.page_from, req.page_to)

    clear_job_cancellation(req.job_id)
    update_job(
        req.job_id,
        mode="translate",
        status="running",
        error=None,
        source_lang=src_lang,
        target_lang=tgt_lang,
        output_format=output_format,
        layout_mode=layout_mode,
        reading_direction=reading_direction,
        ai_polish=req.ai_polish,
        quota_behavior=quota_behavior,
        final_refinement=req.final_refinement,
        refinement_report=None,
        max_quality=bool(req.max_quality),
        revision_report=None,
        read_scanned_text=read_scanned,
        sample_range=sample_range,
    )

    background_tasks.add_task(
        _run_translation,
        req.job_id,
        job.file_path,
        job.file_type,
        src_lang,
        tgt_lang,
        output_path,
        req.ai_polish,
        req.api_key,
        quota_behavior,
    )

    return {"job_id": req.job_id, "status": "started", "output_path": output_path}


def _requested_sample(job, page_from: Optional[int], page_to: Optional[int]) -> Optional[list]:
    """[first, last] page of a sample translation (ending at the document's last page), or None for the whole book."""
    if page_from is None and page_to is None:
        return None
    first = int(page_from or 1)
    last = int(page_to if page_to is not None else first)
    if first < 1 or last < first:
        raise HTTPException(400, "Choose pages from 1 upwards, the first no later than the last.")
    total = int(getattr(job, "total_pages", 0) or 0)
    if not total and job.file_path and Path(job.file_path).exists():
        total = count_pages(job.file_path, job.file_type)
    if total:
        if first > total:
            raise HTTPException(400, f"The document has {total} pages: page {first} is past its end.")
        last = min(last, total)
    return [first, last]


_ESTIMATE_PAGES: dict[str, tuple] = {}   # job_id -> (file version, [(page, characters), ...])
SCANNED_PAGE_CHARS = 1800                # a page of print not read yet: a typical book page


def _page_lengths(job) -> list[tuple[int, int]]:
    """(page number, characters) of every page with text, as the translation reads it (kept per file version)."""
    from backend.scan_reader import sidecar_path
    p = Path(job.file_path)
    side = sidecar_path(job.file_path)
    try:
        st = p.stat()
        version = (str(p), st.st_size, st.st_mtime_ns, side.stat().st_mtime_ns if side.exists() else 0)
    except OSError:
        return []
    cached = _ESTIMATE_PAGES.get(job.job_id)
    if cached and cached[0] == version:
        return cached[1]
    lengths = [(int(pg.get("page") or 0), len((pg.get("text") or "").strip()))
               for pg in parse_document(job.file_path, job.file_type)]
    if len(_ESTIMATE_PAGES) > 64:
        _ESTIMATE_PAGES.clear()
    _ESTIMATE_PAGES[job.job_id] = (version, lengths)
    return lengths


def _ai_batches(lengths: list[tuple[int, int]]) -> list[list[int]]:
    """Pages grouped as the AI translation groups them: ~5,500 characters, at most 3 pages per request."""
    batches: list[list[int]] = []
    cur: list[int] = []
    size = 0
    for page, chars in lengths:
        item = chars + 25
        if cur and (size + item > 5500 or len(cur) >= 3):
            batches.append(cur)
            cur, size = [page], item
        else:
            cur.append(page)
            size += item
    if cur:
        batches.append(cur)
    return batches


def _estimate_requests(job, ai_polish: bool, max_quality: bool, layout_mode: str, output_format: str,
                       read_scanned_text: Optional[bool], page_from: Optional[int], page_to: Optional[int]) -> dict:
    """About how many Gemini requests a translation with these settings sends, and what the keys allow a day."""
    import math
    from backend.ai_polisher import PREFERRED_FLASH_MODELS
    from backend.gemini_key_pool import GeminiKeyPool, model_daily_limit, resolve_gemini_api_key
    from backend.scan_reader import LIGHT_MODELS_FIRST, is_scanned_pdf, load_scan_text

    ft = (job.file_type or "").lower().lstrip(".")
    fmt = (output_format or job.output_format or ft or "pdf").lower().lstrip(".")
    layout = (layout_mode or "standard").lower()
    has_key = bool(resolve_gemini_api_key(None))
    keys = max(len(GeminiKeyPool.get_keys()), 1 if has_key else 0)
    total_pages = int(job.total_pages or 0) or count_pages(job.file_path, ft)
    sample = _requested_sample(job, page_from, page_to)
    lo, hi = sample or (1, max(total_pages, 1))
    scanned = ft == "pdf" and (bool(getattr(job, "scanned", False)) or is_scanned_pdf(job.file_path, ft, job.file_name))
    if read_scanned_text is None:
        read_scanned_text = bool(getattr(job, "read_scanned_text", False))
    read_scanned = scanned and bool(read_scanned_text) and layout != "comic"
    comic = layout == "comic" or ft in ("cbz", "cbr", "zip") or (scanned and not read_scanned)
    requests = {"read": 0, "translate": 0, "revise": 0}
    best_model = PREFERRED_FLASH_MODELS[0]

    if comic:
        from backend.comic_translator import VISION_MODELS_PRIORITY
        best_model = VISION_MODELS_PRIORITY[0]
        pages = max(0, min(hi, total_pages) - lo + 1)
        if has_key and (scanned or ft in ("cbz", "cbr", "zip") or ai_polish):
            requests["translate"] = pages  # one Vision (or balloon polish) request per page
    else:
        if read_scanned:
            data = load_scan_text(job.file_path)
            read = data["pages"]
            wanted = range(lo, min(total_pages, hi + 2) + 1) if sample else range(1, total_pages + 1)
            requests["read"] = 0 if data.get("complete") else sum(1 for n in wanted if str(n) not in read)
            lengths = [(n, len(read[str(n)].strip()) if str(n) in read else SCANNED_PAGE_CHARS)
                       for n in range(1, total_pages + 1)]
            lengths = [(n, c) for n, c in lengths if c > 0]
        else:
            lengths = _page_lengths(job)
        chosen = [(n, c) for n, c in lengths if lo <= n <= hi] if sample else lengths
        pages = len(chosen)
        if ai_polish and has_key:
            chars = sum(c for _, c in chosen)
            in_place = not sample and ((ft == "docx" and fmt in ("docx", "doc")) or (ft == "epub" and fmt == "epub"))
            if in_place:
                requests["translate"] = max(1, math.ceil(chars / 3800)) if chars else 0  # paragraphs in ~4,000 chars
            else:
                batches = _ai_batches(lengths)
                if sample:
                    batches = [b for b in batches if any(lo <= p <= hi for p in b)]
                dossier = 1 if sum(c for _, c in lengths) > 18000 else 0  # names and terms of a long book: 1 request
                requests["translate"] = len(batches) + dossier if batches else 0
                if max_quality and batches:
                    requests["revise"] = len(batches) + (1 if chars > 18000 else 0)

    best_per_day = keys * (model_daily_limit(best_model) or 20)
    light_per_day = keys * (model_daily_limit(LIGHT_MODELS_FIRST[0]) or 1500)
    return {
        "pages": pages,
        "sample": sample,
        "comic": comic,
        "scanned": scanned,
        "read_scanned_text": read_scanned,
        "has_key": has_key,
        "uses_ai": sum(requests.values()) > 0,
        "keys": keys,
        "requests": requests,
        "total": sum(requests.values()),
        "best_model": best_model,
        "best_per_day": best_per_day,
        "light_per_day": light_per_day,
        "best_days": math.ceil((requests["translate"] + requests["revise"]) / best_per_day) if best_per_day else 0,
    }


@app.get("/api/translate/estimate/{job_id}")
async def translation_estimate(job_id: str, ai_polish: bool = False, max_quality: bool = False,
                               layout_mode: str = "standard", output_format: str = "",
                               read_scanned_text: Optional[bool] = None, page_from: Optional[int] = None,
                               page_to: Optional[int] = None):
    """About how many Gemini requests a translation of this document with these settings needs (before starting)."""
    _validate_job_id(job_id)
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    if not job.file_path or not Path(job.file_path).exists():
        raise HTTPException(404, "The uploaded file is no longer on the server.")
    return await asyncio.to_thread(_estimate_requests, job, ai_polish, max_quality, layout_mode, output_format,
                                   read_scanned_text, page_from, page_to)


async def _read_scanned_book(job_id: str, file_path: str, api_key: str, page_range=None) -> None:
    """Reads the text of a scanned book's page images (Gemini Vision) unless it was read already: only the pages of
    `page_range` for a sample."""
    from backend.scan_reader import read_scanned_text, scan_text_complete
    if scan_text_complete(file_path):
        return
    if not api_key:
        raise ValueError("A scanned book needs a Gemini API key: Gemini Vision reads the text of its page images. "
                         "Add a key with 🔑, or choose Comic to translate on the page images.")

    def _prog(done: int, total: int) -> None:
        update_job(job_id, current_step=f"📖 Ανάγνωση σκαναρισμένων σελίδων (Gemini Vision): σελίδα {done} από {total}...",
                   done_chunks=done, total_chunks=total, progress=int(done / max(total, 1) * 100))

    update_job(job_id, current_step="📖 Ανάγνωση σκαναρισμένων σελίδων (Gemini Vision)...", progress=0, done_chunks=0,
               done_pages=0)  # the time left follows the pages read, not an earlier run's count
    await read_scanned_text(file_path, api_key, progress=_prog, cancelled=lambda: is_job_cancelled(job_id),
                            page_range=page_range)


def _revision_time_left(elapsed: float, done: int, total: int, start_done: int = 0) -> str:
    """' · απομένουν ~12 λεπτά' from the pace so far ('' before the first part is back). `start_done` parts were
    already done when the clock started (restored from a checkpoint on resume), so they do not count as speed."""
    progressed = done - max(0, start_done)
    if progressed <= 0 or total <= done:
        return ""
    minutes = round(elapsed / progressed * (total - done) / 60)
    if minutes < 1:
        return " · απομένει λιγότερο από 1 λεπτό"
    if minutes < 60:
        return f" · απομένουν ~{minutes} λεπτά"
    hours, rest = divmod(minutes, 60)
    return f" · απομένουν ~{hours} ώρ{'α' if hours == 1 else 'ες'}" + (f" {rest} λεπτά" if rest else "")


async def _run_max_quality_revision(job_id, file_path, output_path, api_key, target_lang, style, quota_behavior):
    """Second AI pass (Advanced Mode): revises the finished AI translation against the original. Never fatal."""
    from backend.ai_polisher import revise_translation_against_source
    original_path = Path(output_path).parent / f"{Path(file_path).stem}_original.txt"
    update_job(job_id, current_step="🏆 Αναθεώρηση της μετάφρασης με το πρωτότυπο (2ο πέρασμα AI, πολύ αργή διαδικασία)· "
                                    "ο χρόνος που απομένει φαίνεται μετά το πρώτο τμήμα…", progress=94)
    started = time.monotonic()
    clock = {"t": started, "done": 0}

    def _prog(done, total):
        now = time.monotonic()
        if done < clock["done"] or (clock["done"] == 0 and done > 0 and now - started < 5):
            # a resume reports the parts restored from its checkpoint at once: they are not speed
            clock.update(t=now, done=done)
        left = _revision_time_left(now - clock["t"], done, total, clock["done"])
        update_job(job_id, current_step=f"🏆 Αναθεώρηση με το πρωτότυπο (πολύ αργή διαδικασία): τμήμα {done}/{max(total, 1)}"
                                        f"{left}…")

    try:
        report = await revise_translation_against_source(
            job_id, output_path, str(original_path), api_key, target_lang=target_lang, style=style,
            quota_behavior=quota_behavior, progress_callback=_prog,
        )
    except Exception as e:  # defensive: the revision must never fail the translation
        logger.warning(f"[{job_id}] Maximum-quality revision crashed ({e}); first-pass translation kept.", exc_info=True)
        report = {"status": "error", "reason": "ai_failed"}
    update_job(job_id, revision_report=report)
    return report


def _revision_notes(report) -> list[str]:
    """The job's final message about the second AI pass, when it did not simply succeed."""
    report = report or {}
    if report.get("status") == "error":
        return [f"The second AI pass (Maximum quality) did not complete ({report.get('reason') or 'error'}); "
                f"the first-pass translation was kept."]
    if report.get("kept_pages"):
        return [f"Maximum quality: {report['kept_pages']} page(s) kept the first-pass translation because the "
                f"revision of those pages was unusable."]
    return []


def _leftover_notes(translated: str, original_path: Path, target_lang: str) -> list[str]:
    """Pages still in the source language and words with letters of another alphabet, for the final message."""
    from backend.ai_polisher import translation_leftover_notes
    try:
        original = original_path.read_text(encoding="utf-8") if original_path.is_file() else ""
        return translation_leftover_notes(translated, original, greek_target=target_lang.lower() in ("greek", "el"))
    except Exception as e:  # a report must never fail the translation
        logger.warning(f"Leftover check skipped: {e}")
        return []


async def _run_translation(job_id, file_path, file_type, source_lang, target_lang, output_path, ai_polish=False, api_key=None, quota_behavior="wait"):
    task = asyncio.current_task()
    if task:
        register_task(job_id, task)
    from backend.ai_polisher import track_gemini_usage
    usage_cm = track_gemini_usage()
    usage = usage_cm.__enter__()          # counts every Gemini call of this job (incl. child tasks)
    doc_pages = 0                         # the document's page count: a sample shows its own while it runs
    page_range = None
    try:
        job = get_job(job_id)
        if not job:
            return
        doc_pages = int(getattr(job, "total_pages", 0) or 0)
        update_job(job_id, error=None)
        fmt = getattr(job, "output_format", "txt") or "txt"
        fmt = fmt.lower()
        layout = getattr(job, "layout_mode", "standard") or "standard"
        out_dir = Path(output_path).parent
        stem = Path(file_path).stem
        base_name = f"{stem}_translated_{target_lang}"
        exports_before = _export_snapshot(out_dir, base_name)
        warnings: list[str] = []
        from backend.translator import start_engine_tracking
        engines = start_engine_tracking()

        if is_job_cancelled(job_id):
            return

        from backend.gemini_key_pool import resolve_gemini_api_key
        from backend.parsers import detect_is_graphic_novel
        resolved_key = resolve_gemini_api_key(api_key)

        # Check if uploaded PDF is a scanned/image-only document or graphic novel
        comic_probe = detect_is_graphic_novel(file_path, file_type, job.file_name or "")
        scanned_pdf = file_type == "pdf" and bool(comic_probe.get("is_scanned", False))
        read_scanned = scanned_pdf and bool(getattr(job, "read_scanned_text", False))
        is_comic_flow = (
            layout in ("comic", "graphic_novel")
            or file_type in ("cbz", "cbr")
            or (scanned_pdf and not read_scanned)
        )
        sample = getattr(job, "sample_range", None)
        page_range = (int(sample[0]), int(sample[1])) if sample else None

        # A scanned book: Gemini Vision reads the text of its page images first, then it is translated as text
        if read_scanned and not is_comic_flow:
            await _read_scanned_book(job_id, file_path, resolved_key, page_range)
            if is_job_cancelled(job_id):
                return

        # Whether the final document is regenerated from the plain-text translation by export_text().
        # Format-preserving outputs (comics, in-place DOCX/EPUB) must never be re-exported by the refiner.
        refine_reexportable = True

        # Format-preserving AI translation: DOCX->DOCX / EPUB->EPUB keep fonts, styles, tables, images and HTML/CSS
        # (AI translates the document's own paragraphs/runs/text nodes in context-preserving batches).
        # (a sample takes the page-based path: its pages are those of the whole book's translation)
        ai_in_place = bool(ai_polish and resolved_key) and not page_range and (
            (file_type == "docx" and fmt in ("docx", "doc")) or (file_type == "epub" and fmt == "epub")
        )
        ai_segment_translator = None
        if ai_in_place:
            from functools import partial
            from backend.ai_segment_translator import translate_segments_with_gemini
            ai_segment_translator = partial(
                translate_segments_with_gemini, source_lang=source_lang, target_lang=target_lang,
                api_key=resolved_key, style="literature" if layout == "literature" else "natural",
                quota_behavior=quota_behavior,
                progress=lambda done, total: update_job(
                    job_id, done_chunks=done, total_chunks=total, progress=int(done / max(total, 1) * 92),
                    current_step=f"✨ AI translation: segment {done} of {total} (preserving formatting)...",
                ),
            )

        # 0. Graphic Novel / Comic / Scanned Image PDF translation (balloons/vision only, preserving 100% artwork)
        if is_comic_flow:
            refine_reexportable = False
            from backend.comic_translator import translate_comic_document
            reading_dir = getattr(job, "reading_direction", "ltr") or "ltr"
            final_comic_pdf = await translate_comic_document(
                job_id=job_id,
                file_path=file_path,
                file_type=file_type,
                source_lang=source_lang,
                target_lang=target_lang,
                output_path=output_path,
                api_key=resolved_key if resolved_key else None,
                reading_direction=reading_dir,
                quota_behavior=quota_behavior,
                notes=warnings,
                page_range=page_range,
            )
            # Export to the user's requested comic format (PDF, CBZ, CBR, EPUB)
            if fmt == "cbz":
                cbz_path = out_dir / f"{base_name}.cbz"
                if not cbz_path.exists():
                    from backend.exporter import export_comic_archive
                    export_comic_archive(final_comic_pdf, cbz_path, format="cbz")
                final_path = cbz_path
                job.output_path = str(cbz_path)
                job.output_format = "cbz"
            elif fmt == "cbr":
                cbr_path = out_dir / f"{base_name}.cbr"
                from backend.exporter import export_comic_archive
                export_comic_archive(final_comic_pdf, cbr_path, format="cbr")
                final_path = cbr_path
                job.output_path = str(cbr_path)
                job.output_format = "cbr"
            elif fmt == "epub":
                epub_path = out_dir / f"{base_name}.epub"
                from backend.exporter import export_comic_epub
                export_comic_epub(final_comic_pdf, epub_path, title=job.file_name or "Graphic Novel", reading_direction=reading_dir)
                final_path = epub_path
                job.output_path = str(epub_path)
                job.output_format = "epub"
            else:
                final_path = Path(final_comic_pdf)
                job.output_path = str(final_comic_pdf)
                job.output_format = "pdf"
                fmt = "pdf"
            job.layout_mode = "comic"

        # 1. Single-Pass Direct AI Translation & Polish for book/document formats (PDF, EPUB, DOCX, TXT)
        elif ai_polish and resolved_key and not ai_in_place:
            from backend.ai_polisher import translate_and_polish_direct_with_gemini
            style_for_layout = "literature" if layout == "literature" else "natural"
            await translate_and_polish_direct_with_gemini(
                job_id=job_id,
                file_path=file_path,
                file_type=file_type,
                source_lang=source_lang,
                target_lang=target_lang,
                output_path=output_path,
                api_key=resolved_key,
                style=style_for_layout,
                quota_behavior=quota_behavior,
                page_range=page_range,
            )
            if is_job_cancelled(job_id):
                return
            if getattr(job, "max_quality", False):
                rev = await _run_max_quality_revision(job_id, file_path, output_path, resolved_key, target_lang,
                                                      style_for_layout, quota_behavior)
                if is_job_cancelled(job_id):
                    return
                warnings.extend(_revision_notes(rev))
            txt_content = Path(output_path).read_text(encoding="utf-8")
            warnings.extend(_leftover_notes(txt_content, Path(output_path).parent / f"{stem}_original.txt", target_lang))
            update_job(job_id, current_step=f"Exporting AI-polished {fmt.upper()}...", progress=95)
            final_path = await asyncio.to_thread(export_text, txt_content, out_dir, fmt, base_name, layout=layout)

        # 2. DOCX In-Place Format Preservation (styles, fonts, sizes, tables, bold/italic)
        elif file_type == "docx" and fmt in ("docx", "doc") and not page_range:
            refine_reexportable = False
            final_docx_path = out_dir / f"{base_name}.docx"

            def docx_prog(done, total, msg):
                if is_job_cancelled(job_id):
                    raise asyncio.CancelledError("Translation cancelled by user")
                pct = int((done / max(total, 1)) * 92)
                update_job(job_id, current_step=msg, progress=pct, done_chunks=done, total_chunks=total)

            translated_txt = await translate_docx_in_place(
                file_path,
                str(final_docx_path),
                source_lang,
                target_lang,
                docx_prog,
                style="literature" if layout == "literature" else None,
                segment_translator=ai_segment_translator,
            )
            if is_job_cancelled(job_id):
                return
            # Save plain text version for audiobooks / fallback
            Path(output_path).write_text(translated_txt, encoding="utf-8")
            final_path = final_docx_path

        # 3. EPUB In-Place Format Preservation (HTML tags, CSS, headings, styles, images)
        elif file_type == "epub" and fmt == "epub" and not page_range:
            refine_reexportable = False
            final_epub_path = out_dir / f"{base_name}.epub"

            def epub_prog(done, total, msg):
                if is_job_cancelled(job_id):
                    raise asyncio.CancelledError("Translation cancelled by user")
                pct = int((done / max(total, 1)) * 92)
                update_job(job_id, current_step=msg, progress=pct, done_chunks=done, total_chunks=total)

            translated_txt = await translate_epub_in_place(
                file_path,
                str(final_epub_path),
                source_lang,
                target_lang,
                epub_prog,
                style="literature",
                segment_translator=ai_segment_translator,
                notes=warnings,
            )
            if is_job_cancelled(job_id):
                return
            Path(output_path).write_text(translated_txt, encoding="utf-8")
            final_path = final_epub_path

        # 4. Standard parsing + rich styled export (for PDF or cross-format exports)
        else:
            await translate_document(
                job_id=job_id,
                file_path=file_path,
                file_type=file_type,
                source_lang=source_lang,
                target_lang=target_lang,
                output_path=output_path,
                style="literature" if layout == "literature" else None,
                page_range=page_range,
            )
            if is_job_cancelled(job_id):
                return
            txt_content = Path(output_path).read_text(encoding="utf-8")
            if ai_polish and not resolved_key and (target_lang.lower() in ("greek", "el")):
                from backend.typography import format_greek_typography
                from backend.glossary import apply_glossary
                txt_content = format_greek_typography(apply_glossary(txt_content, "greek", style="literature" if layout == "literature" else "formal", translated=True))
                Path(output_path).write_text(txt_content, encoding="utf-8")
            update_job(job_id, current_step=f"Exporting to {fmt.upper()}...", progress=95)
            final_path = await asyncio.to_thread(export_text, txt_content, out_dir, fmt, base_name, layout=layout)

        if is_job_cancelled(job_id):
            return

        keep = {Path(final_path)} | ({Path(final_comic_pdf)} if is_comic_flow else set())
        await asyncio.to_thread(_set_aside_superseded, out_dir, exports_before, keep)
        # Remember how this file was made: later edits and exports must never regenerate a format-preserved one
        format_sync.mark_output(final_path, preserved=not refine_reexportable)

        if getattr(job, "max_quality", False) and not is_comic_flow:
            if not (ai_polish and resolved_key):
                update_job(job_id, revision_report={"status": "skipped", "reason": "requires_ai_polish_and_key"})
            elif ai_in_place:
                # The revision pass works on the page-aligned plain-text path; format-preserved documents keep
                # their single, format-preserving AI translation.
                update_job(job_id, revision_report={"status": "skipped", "reason": "format_preserved_output"})

        # Automatic Final Output Refinement & Quality-Control stage (independent, non-fatal, local-only)
        try:
            from backend.output_refiner import refine_translation_output, is_refinement_enabled, build_refinement_report
            if is_refinement_enabled(getattr(job, "final_refinement", None)):
                update_job(job_id, current_step="🔍 Τελικός έλεγχος ποιότητας & βελτίωση κειμένου...", progress=97)
                refine_res = await refine_translation_output(
                    job_id=job_id,
                    output_path=output_path,
                    final_exported_path=str(final_path),
                    source_lang=source_lang,
                    target_lang=target_lang,
                    layout_mode=layout,
                    output_format=fmt,
                    enabled=True,
                    allow_reexport=refine_reexportable,
                )
                update_job(job_id, refinement_report=build_refinement_report(refine_res))
                if refine_res.final_exported_path and Path(refine_res.final_exported_path).exists():
                    final_path = Path(refine_res.final_exported_path)
            else:
                update_job(job_id, refinement_report={"status": "skipped"})
        except Exception as refine_err:
            logger.warning(f"[{job_id}] Final refinement stage failed ({refine_err}); original output preserved.", exc_info=True)

        if is_job_cancelled(job_id):
            return

        # Mark job complete (preserve real batch/page totals)
        if not ai_polish and "gemini" in engines:
            warnings.append("Google's free translation refused the requests, so Gemini translated (this uses your Gemini allowance).")
        if "mymemory" in engines:
            warnings.append("Some text was translated by MyMemory, a simpler free service, because Google refused: please check it.")
        final_total = max(int(getattr(job, "total_chunks", 0) or 0), 1)
        done_sample = getattr(get_job(job_id) or job, "sample_range", None) if page_range else None
        sample_note = f" · 🧪 Sample: pages {done_sample[0]}–{done_sample[1]}" if done_sample else ""
        update_job(job_id,
            status="done",
            progress=100,
            current_step=(f"⚠️ {' '.join(warnings)}" if warnings
                          else f"Exported {fmt.upper()}" + ("" if refine_reexportable else " (Formatting Preserved)"))
                         + sample_note,
            output_path=str(final_path),
            output_format=fmt,
            done_chunks=final_total,
            total_chunks=final_total,
        )
    except asyncio.CancelledError:
        logger.info(f"[{job_id}] Translation task was cancelled.")
        mark_interrupted(job_id)
    except Exception as e:
        logger.error(f"Translation/export error [{job_id}]: {e}", exc_info=True)
        from backend.ai_polisher import get_gemini_quota_info
        err_str = str(e)
        if _is_quota_failure(e, bool(ai_polish)):
            q_info = get_gemini_quota_info()
            update_job(
                job_id,
                status="error",
                error=err_str if "Εξαντλήθηκε" in err_str else f"⚠️ {q_info['message'] or err_str}",
                current_step=_quota_stop_step(e, q_info),
            )
        else:
            update_job(job_id, status="error", error=err_str)
    finally:
        usage_cm.__exit__(None, None, None)
        update_job(job_id, gemini_usage=dict(usage))
        if page_range and doc_pages:
            update_job(job_id, total_pages=doc_pages)  # the next sample and the estimate see the whole document
        unregister_task(job_id)


@app.post("/api/audiobook")
async def start_audiobook(req: AudiobookRequest, background_tasks: BackgroundTasks):
    """Start an audiobook generation job in the background."""
    _validate_job_id(req.job_id)
    job = get_job(req.job_id)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found.")

    if job.status == "running":
        raise HTTPException(409, "A task is already running for this job.")

    if req.rate is not None and req.rate != "" and not re.match(r"^[+-]?\d{1,3}%$", req.rate.strip()):
        raise HTTPException(400, f"Invalid prosody rate '{req.rate}'. Expected format like '-10%' or '+5%'.")
    if req.pitch is not None and req.pitch != "" and not re.match(r"^[+-]?\d{1,3}Hz$", req.pitch.strip()):
        raise HTTPException(400, f"Invalid prosody pitch '{req.pitch}'. Expected format like '-2Hz' or '+0Hz'.")

    lang_norm = _validate_language(req.language or "greek")
    output_dir = _job_output_dir(req.job_id)
    stem = Path(job.file_name).stem
    output_path = str(output_dir / f"{stem}_audiobook_{lang_norm}.mp3")

    # Check for a translated text file to use (prefer matching target language, else newest)
    translated_path = None
    if req.use_translated:
        lang_matches = list(output_dir.glob(f"*_translated_{lang_norm}.txt"))
        txt_files = lang_matches or list(output_dir.glob("*_translated_*.txt"))
        if txt_files:
            txt_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            translated_path = str(txt_files[0])

    from backend.gemini_key_pool import resolve_gemini_api_key
    resolved_key = resolve_gemini_api_key(req.api_key)

    quota_behavior = (getattr(req, "quota_behavior", "") or "").strip().lower()
    if not quota_behavior:
        quota_behavior = "wait" if resolved_key else "fallback"
    elif not resolved_key and quota_behavior == "wait":
        # Free models default when no Gemini API key is configured
        quota_behavior = "fallback"
    if quota_behavior not in ("wait", "fallback"):
        quota_behavior = "fallback" if not resolved_key else "wait"

    if req.ai_polish and not resolved_key and quota_behavior != "fallback":
        raise HTTPException(400, "Gemini API key is required for AI Audiobook Polish. Επιλέξτε 'Αυτόματη μετάβαση σε Δωρεάν Μοντέλο' για εκφώνηση χωρίς κλειδί.")

    clear_job_cancellation(req.job_id)
    update_job(
        req.job_id, mode="audiobook", status="running", error=None, quota_behavior=quota_behavior,
        final_refinement=req.final_refinement, refinement_report=None,
        done_chunks=0, total_chunks=0, progress=0,
        audiobook_options={
            "language": lang_norm, "voice_name": req.voice_name, "dialogue_voice": req.dialogue_voice,
            "use_translated": bool(req.use_translated), "narration_style": req.narration_style,
            "rate": req.rate, "pitch": req.pitch, "ai_polish": bool(req.ai_polish),
        },
    )

    background_tasks.add_task(
        _run_audiobook,
        req.job_id,
        job.file_path,
        job.file_type,
        lang_norm,
        req.voice_name,
        output_path,
        translated_path,
        req.narration_style,
        req.rate,
        req.pitch,
        req.dialogue_voice,
        req.ai_polish,
        req.api_key,
        quota_behavior,
    )

    return {"job_id": req.job_id, "status": "started", "output_path": output_path}


async def _run_audiobook(
    job_id, file_path, file_type, language, voice_name, output_path, translated_path,
    narration_style="literature", rate=None, pitch=None, dialogue_voice=None, ai_polish=False, api_key=None, quota_behavior="wait"
):
    task = asyncio.current_task()
    if task:
        register_task(job_id, task)
    from backend.ai_polisher import track_gemini_usage
    usage_cm = track_gemini_usage()
    usage = usage_cm.__enter__()
    try:
        if is_job_cancelled(job_id):
            return
        if not translated_path:
            from backend.scan_reader import needs_reading
            if await asyncio.to_thread(needs_reading, file_path, file_type):
                # a scanned book: Gemini Vision reads the text of its page images first
                from backend.gemini_key_pool import resolve_gemini_api_key
                await _read_scanned_book(job_id, file_path, resolve_gemini_api_key(api_key))
                if is_job_cancelled(job_id):
                    return
        await generate_audiobook(
            job_id=job_id,
            file_path=file_path,
            file_type=file_type,
            language=language,
            voice_name=voice_name,
            output_path=output_path,
            translated_text_path=translated_path,
            narration_style=narration_style,
            rate=rate,
            pitch=pitch,
            dialogue_voice=dialogue_voice,
            ai_polish=ai_polish,
            api_key=api_key,
            quota_behavior=quota_behavior,
        )
    except asyncio.CancelledError:
        logger.info(f"[{job_id}] Audiobook task was cancelled.")
        mark_interrupted(job_id)
    except Exception as e:
        logger.error(f"Audiobook error [{job_id}]: {e}", exc_info=True)
        from backend.ai_polisher import get_gemini_quota_info
        err_str = str(e)
        if _is_quota_failure(e, bool(ai_polish)):
            q_info = get_gemini_quota_info()
            update_job(
                job_id,
                status="error",
                error=err_str if "Εξαντλήθηκε" in err_str else f"⚠️ {q_info['message'] or err_str}",
                current_step=_quota_stop_step(e, q_info),
            )
        else:
            update_job(job_id, status="error", error=err_str)
    finally:
        usage_cm.__exit__(None, None, None)
        update_job(job_id, gemini_usage=dict(usage))
        unregister_task(job_id)


@app.get("/api/progress/{job_id}")
async def progress_stream(job_id: str):
    """SSE endpoint for real-time job progress."""
    _validate_job_id(job_id)
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")

    async def event_generator():
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        job.subscribers.append(q)

        try:
            # Send current state immediately
            state = {
                "status": job.status,
                "progress": job.progress,
                "current_step": job.current_step,
                "total_chunks": job.total_chunks,
                "done_chunks": job.done_chunks,
                "total_pages": int(getattr(job, "total_pages", 0) or 0),
                "done_pages": int(getattr(job, "done_pages", 0) or 0),
                "error": job.error,
                "output_path": job.output_path,
                "output_format": getattr(job, "output_format", "") or "",
                "layout_mode": getattr(job, "layout_mode", "") or "",
                "file_name": getattr(job, "file_name", "") or "",
                "ai_polish": bool(getattr(job, "ai_polish", False)),
                "quota_behavior": getattr(job, "quota_behavior", "wait"),
                "final_refinement": getattr(job, "final_refinement", None),
                "refinement_report": getattr(job, "refinement_report", None),
                "revision_report": getattr(job, "revision_report", None),
                "gemini_usage": getattr(job, "gemini_usage", None),
                "max_quality": bool(getattr(job, "max_quality", False)),
                "read_scanned_text": bool(getattr(job, "read_scanned_text", False)),
                "sample_range": getattr(job, "sample_range", None),
            }
            yield f"data: {json.dumps(state)}\n\n"

            # Close immediately if already in terminal state so clients don't hang forever
            if state["status"] in ("done", "error", "cancelled"):
                return

            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(data)}\n\n"

                    # Stop streaming when terminal state reached
                    if data.get("status") in ("done", "error", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield ": heartbeat\n\n"
        finally:
            try:
                job.subscribers.remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/status/{job_id}")
async def job_status(job_id: str):
    """Get current job status and persisted translation settings (non-streaming)."""
    _validate_job_id(job_id)
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")

    # Lazily populate exact page count for older jobs if missing
    total_pages = int(getattr(job, "total_pages", 0) or 0)
    if total_pages == 0 and job.file_path and Path(job.file_path).exists():
        try:
            total_pages = count_pages(job.file_path, job.file_type)
            if total_pages > 0:
                update_job(job_id, total_pages=total_pages)
        except Exception:
            pass

    # Detect prior AI Polish session from checkpoint if metadata predates ai_polish persistence
    ai_polish = bool(getattr(job, "ai_polish", False))
    cp_file = OUTPUT_DIR / job_id / ".direct_ai_checkpoint.json"
    if not ai_polish and cp_file.is_file():
        ai_polish = True

    from backend.ai_polisher import get_gemini_quota_info
    quota_info = get_gemini_quota_info()

    return {
        "job_id": job.job_id,
        "file_name": job.file_name,
        "file_type": job.file_type,
        "output_format": job.output_format,
        "layout_mode": job.layout_mode,
        "source_lang": getattr(job, "source_lang", "english") or "english",
        "target_lang": getattr(job, "target_lang", "greek") or "greek",
        "ai_polish": ai_polish,
        "reading_direction": getattr(job, "reading_direction", "ltr") or "ltr",
        "total_pages": total_pages,
        "done_pages": int(getattr(job, "done_pages", 0) or 0),
        "status": job.status,
        "mode": job.mode,
        "progress": job.progress,
        "current_step": job.current_step,
        "total_chunks": job.total_chunks,
        "done_chunks": job.done_chunks,
        "error": job.error,
        "has_output": job.output_path is not None,
        "quota_behavior": getattr(job, "quota_behavior", "wait") or "wait",
        "final_refinement": getattr(job, "final_refinement", None),
        "refinement_report": getattr(job, "refinement_report", None),
        "gemini_usage": getattr(job, "gemini_usage", None),
        "max_quality": bool(getattr(job, "max_quality", False)),
        "audiobook_options": getattr(job, "audiobook_options", None),
        "revision_report": getattr(job, "revision_report", None),
        "scanned": bool(getattr(job, "scanned", False)),
        "read_scanned_text": bool(getattr(job, "read_scanned_text", False)),
        "sample_range": getattr(job, "sample_range", None),
        "gemini_quota_exhausted": quota_info["exhausted"],
        "gemini_quota_message": quota_info["message"],
        "gemini_quota_reset_timestamp": quota_info.get("reset_timestamp", 0.0),
        "gemini_quota_reset_time_str": quota_info.get("reset_time_str", ""),
        "gemini_quota_remaining_seconds": quota_info.get("remaining_seconds", 0),
    }




_COVER_REMOVED = ".cover_removed"  # the user removed the book's cover: do not extract it again


def _export_snapshot(out_dir: Path, base_name: str) -> dict:
    """The exports of a translation as they are before a run: path -> modification time."""
    found = {}
    for ext in (".pdf", ".docx", ".doc", ".epub", ".cbz", ".cbr"):
        path = out_dir / f"{base_name}{ext}"
        if path.is_file():
            found[path] = path.stat().st_mtime_ns
    return found


def _set_aside_superseded(out_dir: Path, before: dict, keep: set) -> None:
    """
    A finished run supersedes the other formats of the run before it: a download must not serve them and an edit must
    not patch them. They are moved to previous/, not deleted.
    """
    for old, stamp in before.items():
        try:
            if old not in keep and old.is_file() and old.stat().st_mtime_ns == stamp:
                (out_dir / "previous").mkdir(exist_ok=True)
                os.replace(old, out_dir / "previous" / old.name)
        except OSError as e:
            logger.warning(f"Could not set aside the superseded {old.name}: {e}")


def _text_language(text: str) -> str:
    sample = (text or "")[:20000]
    greek = len(re.findall(r"[\u0370-\u03ff\u1f00-\u1fff]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    return "english" if latin and greek < 0.25 * (greek + latin) else "greek"  # Greek technical prose is full of Latin


def _translated_texts(job, out_dir: Path) -> list:
    """A job's translation texts: the one in the job's current target language first, then newest first."""
    found = sorted(out_dir.glob("*_translated_*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    lang = (getattr(job, "target_lang", "") or "").lower() if job else ""
    return sorted(found, key=lambda f: not f.stem.endswith(f"_translated_{lang}"))


def _export_from_text(text: str, out_dir: Path, fmt: str, base_name: str, **options) -> Path:
    """export_text for the edit/cover/download paths: records the result as generated, so it can be re-exported later."""
    path = export_text(text, out_dir, fmt, base_name, **options)
    if Path(path).suffix.lower() in (".docx", ".epub"):
        format_sync.mark_output(path, preserved=False)
    return path


@app.api_route("/api/download/{job_id}", methods=["GET", "HEAD"])
async def download_output(request: Request, job_id: str, format: Optional[str] = None, layout: Optional[str] = None):
    """
    Download the output file for a completed job.
    If 'format' is requested (e.g. ?format=pdf), dynamically converts the translated
    content to the requested format on-demand if it hasn't been exported yet or if
    a different 'layout' ('standard' vs 'literature' vs 'comic') is requested.
    """
    _validate_job_id(job_id)
    is_head = request.method == "HEAD"
    job = get_job(job_id)
    out_dir = OUTPUT_DIR / job_id
    out_path = None
    layout = _validate_choice(layout, LAYOUT_MODES, "layout")
    active_layout = (layout or (getattr(job, "layout_mode", "standard") if job else "standard") or "standard").lower()
    layout_changed = bool(layout and job and layout.lower() != (getattr(job, "layout_mode", "standard") or "standard").lower())

    # Only treat as comic when genuinely a comic/graphic-novel job (never misclassify normal PDF books!)
    is_comic_job = (
        active_layout == "comic"
        or bool(job and (
            getattr(job, "layout_mode", "") == "comic"
            or getattr(job, "file_type", "") in ("cbz", "cbr")
            or getattr(job, "file_name", "").lower().endswith((".cbz", ".cbr", ".zip"))
        ))
        or bool(out_dir.exists() and (
            list(out_dir.glob("*.cbz"))
            or list(out_dir.glob("*.cbr"))
            or (out_dir / ".comic_vision_checkpoint.json").exists()
        ))
    )

    if format:
        fmt = format.lower().lstrip(".")
        if fmt not in {"txt", "docx", "doc", "pdf", "epub", "cbz", "cbr", "mp3", "m4b"}:
            raise HTTPException(400, f"Unsupported download format '{fmt}'.")

        if is_comic_job and fmt in ("txt", "docx", "doc"):
            raise HTTPException(400, "TXT and DOCX formats are disabled for Graphic Novels. Please choose PDF, CBZ, CBR, or EPUB.")

        if not is_comic_job and fmt in ("cbz", "cbr"):
            raise HTTPException(400, f"Format '{fmt.upper()}' is only supported for Graphic Novels / Comics.")

        # 1. Check if a file in the requested format already exists (unless layout changed for text documents).
        #    A format-preserved file is always served as is: another layout would mean rebuilding it from plain text.
        if out_dir.exists():
            current_text = None
            if fmt in ("txt", "docx", "doc", "pdf", "epub", "cbz", "cbr"):
                current_text = next(iter(_translated_texts(job, out_dir)), None)
            needs_keep = layout_changed or fmt in ("doc", "docx", "epub")
            keep = await asyncio.to_thread(format_sync.protected_files, job, out_dir) if needs_keep else set()
            if fmt == "doc" and any(f.suffix.lower() == ".docx" for f in keep):
                fmt = "docx"
            matching = [
                f for f in out_dir.iterdir()
                if f.is_file() and f.suffix.lower() == f".{fmt}" and not f.name.endswith("_original.txt")
                and (not layout_changed or fmt in ("mp3", "m4b") or f in keep)
            ]
            if current_text:
                # the job's current translation only: not another language's, nor one older than the text it came from
                text_time = current_text.stat().st_mtime
                matching = [
                    f for f in matching
                    if f.stem == current_text.stem
                    and (is_comic_job or f in keep or f.stat().st_mtime >= text_time - 1)
                ]
            if fmt == "m4b":
                # older versions saved MP3 data under the .m4b name when ffmpeg was missing: convert those again
                matching = [f for f in matching if is_mp4_file(f)]
                # an audiobook generated again makes the earlier conversion stale
                newest_mp3 = max((f.stat().st_mtime for f in out_dir.glob("*.mp3")), default=0.0)
                matching = [f for f in matching if f.stat().st_mtime >= newest_mp3]
            if matching:
                matching.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                out_path = matching[0]

        # Skip write/conversion side effects on HEAD requests
        if not is_head and not out_path:
            # If cover image is not yet cached in out_dir, check original uploaded file
            cov_file = out_dir / "cover_image.jpg"
            if (out_dir.exists() and not cov_file.exists() and not (out_dir / _COVER_REMOVED).exists()
                    and job and job.file_path and Path(job.file_path).exists()):
                try:
                    from backend.exporter import extract_cover_image
                    c_bytes = extract_cover_image(job.file_path)
                    if c_bytes:
                        cov_file.write_bytes(c_bytes)
                except Exception:
                    pass

            # 2. Comic-specific formats: CBZ, CBR, Fixed-Layout EPUB
            if is_comic_job and out_dir.exists():
                comic_pdfs = list(out_dir.glob("*_translated_*.pdf")) or list(out_dir.glob("*.pdf"))
                if comic_pdfs:
                    wanted = f"_translated_{(getattr(job, 'target_lang', '') or '').lower()}" if job else ""
                    comic_pdfs.sort(key=lambda f: (f.stem.endswith(wanted), f.stat().st_mtime), reverse=True)
                    src_pdf = comic_pdfs[0]
                    base_name = src_pdf.stem
                    reading_dir = getattr(job, "reading_direction", "ltr") if job else "ltr"
                    if fmt in ("cbz", "cbr"):
                        from backend.exporter import export_comic_archive
                        out_path = export_comic_archive(src_pdf, out_dir / f"{base_name}.{fmt}", format=fmt)
                        if job:
                            update_job(job_id, output_path=str(out_path), output_format=fmt, layout_mode="comic")
                    elif fmt == "epub":
                        from backend.exporter import export_comic_epub
                        out_path = export_comic_epub(
                            src_pdf,
                            out_dir / f"{base_name}.epub",
                            title=job.file_name if job else "Graphic Novel",
                            reading_direction=reading_dir or "ltr",
                        )
                        if job:
                            update_job(job_id, output_path=str(out_path), output_format="epub", layout_mode="comic")
                    elif fmt == "pdf":
                        out_path = src_pdf
                        if job:
                            update_job(job_id, output_path=str(out_path), output_format="pdf", layout_mode="comic")

            # 2b. Audio format on-demand conversion (e.g. MP3 -> M4B with chapters & cover)
            if fmt == "m4b" and not out_path and out_dir.exists():
                mp3_files = list(out_dir.glob("*.mp3"))
                if mp3_files:
                    mp3_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    src_mp3 = mp3_files[0]
                    target_m4b = out_dir / f"{src_mp3.stem}.m4b"
                    cov_img = None
                    for cname in ("cover_image.jpg", "cover_image.png", "cover.jpg", "cover.png"):
                        cand = out_dir / cname
                        if cand.exists():
                            cov_img = str(cand)
                            break
                    chapters = None
                    ch_file = src_mp3.with_suffix(".chapters.json")
                    if ch_file.is_file():
                        try:
                            chapters = json.loads(ch_file.read_text(encoding="utf-8")) or None
                        except Exception:
                            chapters = None
                    try:
                        await export_audiobook_m4b(
                            str(src_mp3),
                            str(target_m4b),
                            title=job.file_name if job else "Audiobook",
                            author="BookApp",
                            cover_image_path=cov_img,
                            chapters=chapters,
                        )
                    except M4BUnavailableError as e:
                        raise HTTPException(501, str(e))
                    except M4BExportError as e:
                        raise HTTPException(500, str(e))
                    out_path = target_m4b
                    if job:
                        update_job(job_id, output_path=str(out_path), output_format="m4b")

            # 3. Standard text formats
            if not out_path and out_dir.exists() and fmt in ("txt", "docx", "doc", "pdf", "epub"):
                txt_files = _translated_texts(job, out_dir) or [
                    f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
                ]
                if txt_files:
                    txt_file = txt_files[0]
                    txt_content = txt_file.read_text(encoding="utf-8")
                    base_name = txt_file.stem
                    try:
                        out_path = await asyncio.to_thread(_export_from_text, txt_content, out_dir, fmt, base_name, layout=active_layout)
                    except ValueError as ve:
                        raise HTTPException(400, str(ve))
                    if job:
                        update_job(job_id, output_path=str(out_path), output_format=fmt, layout_mode=active_layout)

        if not out_path:
            raise HTTPException(404, f"Output file in format '{fmt}' for job '{job_id}' not found.")

    # Fallback to existing output_path or newest file (only when no specific format was requested)
    if not out_path:
        if job and job.output_path:
            p = Path(job.output_path)
            if p.exists() and (p.suffix.lower() != ".m4b" or is_mp4_file(p)):
                out_path = p

        if not out_path and out_dir.exists():
            files = [
                f for f in out_dir.iterdir()
                if f.is_file() and f.suffix.lower() in [".docx", ".pdf", ".epub", ".mp3", ".m4b", ".cbz", ".cbr", ".txt"]
                and not f.name.endswith("_original.txt")
                and (f.suffix.lower() != ".m4b" or is_mp4_file(f))
            ]
            if files:
                preferred = [f for f in files if f.suffix.lower() in [".cbz", ".cbr", ".pdf", ".epub", ".docx", ".mp3", ".m4b"]]
                files_to_check = preferred if preferred else files
                files_to_check.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                out_path = files_to_check[0]

    if not out_path or not out_path.exists():
        raise HTTPException(404, f"Output file for job '{job_id}' not found.")

    media_type = MIME_MAP.get(out_path.suffix.lower(), "application/octet-stream")
    download_name = out_path.name
    sample = getattr(job, "sample_range", None) if job else None
    if sample and job.mode == "translate" and out_path.suffix.lower() not in (".mp3", ".m4b"):
        download_name = f"{out_path.stem}_sample_p{sample[0]}-{sample[1]}{out_path.suffix}"  # not the whole book
    return FileResponse(
        path=str(out_path),
        media_type=media_type,
        filename=download_name,
    )


_LANGUAGE_NAMES = {"english": ("English", "Αγγλικά"), "greek": ("Greek", "Ελληνικά")}


def _bilingual_subtitle(source_lang: str, target_lang: str) -> str:
    """'Αγγλικά → Ελληνικά · δίγλωσση έκδοση', in the translation's language."""
    greek = (target_lang or "").lower() in ("greek", "el")

    def name(lang: str) -> str:
        return _LANGUAGE_NAMES.get((lang or "").lower(), ((lang or "").title(),) * 2)[1 if greek else 0]

    edition = "δίγλωσση έκδοση" if greek else "bilingual edition"
    return f"{name(source_lang)} → {name(target_lang)} · {edition}"


def _build_bilingual(job, out_dir: Path, translated_file: Path, fmt: str, target: Path) -> Path:
    from backend import bilingual
    translated = translated_file.read_text(encoding="utf-8")
    originals = sorted(out_dir.glob("*_original.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    original = originals[0].read_text(encoding="utf-8") if originals else ""
    if not original.strip() and job.file_path and Path(job.file_path).exists():
        src_type = Path(job.file_path).suffix.lstrip(".").lower() or job.file_type
        original = "\n\n".join(f"=== PAGE {p['page']} ===\n{p['text']}" for p in parse_document(job.file_path, src_type))
    if not original.strip():
        raise HTTPException(422, "The original text is not available, so there is no bilingual edition.")
    passages = bilingual.bilingual_passages(original, translated)
    if not passages:
        raise HTTPException(422, "The translation has no text for a bilingual edition.")
    target.parent.mkdir(parents=True, exist_ok=True)
    title = Path(job.file_name or "Book").stem
    subtitle = _bilingual_subtitle(job.source_lang, job.target_lang)
    tmp = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}{target.suffix}")
    try:
        if fmt == "epub":
            cover = next((c.read_bytes() for c in (out_dir / n for n in ("cover_image.jpg", "cover_image.png",
                                                                          "cover.jpg", "cover.png")) if c.is_file()), None)
            bilingual.export_bilingual_epub(passages, tmp, title, subtitle, job.source_lang, job.target_lang, cover)
        else:
            bilingual.EXPORTERS[fmt](passages, tmp, title, subtitle, job.source_lang, job.target_lang)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


@app.get("/api/download/{job_id}/bilingual")
async def download_bilingual(job_id: str, format: str = "pdf"):
    """The translation with its original: each passage of the original, smaller and grey, then its translation."""
    from backend.bilingual import EXPORTERS
    _validate_job_id(job_id)
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    fmt = (format or "pdf").strip().lower().lstrip(".")
    fmt = "docx" if fmt == "doc" else fmt
    if fmt not in EXPORTERS:
        raise HTTPException(400, "The bilingual edition comes as PDF, DOCX or EPUB.")
    if (job.layout_mode or "") == "comic" or (job.file_type or "") in ("cbz", "cbr", "zip"):
        raise HTTPException(400, "A graphic novel has no bilingual edition: its text is part of the pictures.")
    if job.status == "running":
        raise HTTPException(409, "Wait until the translation finishes.")
    out_dir = OUTPUT_DIR / job_id
    texts = _translated_texts(job, out_dir) if out_dir.exists() else []
    if not texts:
        raise HTTPException(404, "Translate the document first: the bilingual edition needs its translation.")
    stem = Path(job.file_name or "Book").stem
    target = out_dir / "bilingual" / f"{stem}_bilingual.{fmt}"  # apart: never taken for the translation itself
    sources = [texts[0], *out_dir.glob("*_original.txt")]
    if not target.is_file() or target.stat().st_mtime < max(f.stat().st_mtime for f in sources):
        await asyncio.to_thread(_build_bilingual, job, out_dir, texts[0], fmt, target)
    sample = getattr(job, "sample_range", None)
    name = f"{stem}_bilingual" + (f"_sample_p{sample[0]}-{sample[1]}" if sample else "") + f".{fmt}"
    return FileResponse(path=str(target), media_type=MIME_MAP.get(f".{fmt}", "application/octet-stream"), filename=name)


@app.api_route("/api/cover/{job_id}", methods=["GET", "HEAD"])
async def get_cover_image(job_id: str):
    """Retrieve the current cover image for a job, if present."""
    _validate_job_id(job_id)
    out_dir = OUTPUT_DIR / job_id
    cov_p = out_dir / "cover_image.jpg"
    if not cov_p.exists() and not (out_dir / _COVER_REMOVED).exists():
        job = get_job(job_id)
        if job and job.file_path and Path(job.file_path).exists():
            try:
                from backend.exporter import extract_cover_image
                c_bytes = extract_cover_image(job.file_path)
                if c_bytes:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    cov_p.write_bytes(c_bytes)
            except Exception:
                pass

    if cov_p.exists():
        return FileResponse(path=str(cov_p), media_type="image/jpeg", filename="cover.jpg")
    raise HTTPException(404, "No cover image found for this book.")


@app.post("/api/cover/{job_id}")
async def upload_cover_image(job_id: str, file: UploadFile = File(...)):
    """Upload or replace the cover image (JPEG/PNG/WEBP) for a book."""
    _validate_job_id(job_id)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty image file.")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, "Cover image exceeds maximum size of 25 MB.")

    # Convert & strictly validate image bytes to JPEG using pymupdf
    try:
        import pymupdf
        try:
            pix = pymupdf.Pixmap(content)
        except Exception:  # MuPDF has no WebP decoder
            from PIL import Image
            png = io.BytesIO()
            with Image.open(io.BytesIO(content)) as im:
                im.convert("RGB").save(png, "PNG")
            pix = pymupdf.Pixmap(png.getvalue())
        if pix.width <= 0 or pix.height <= 0:
            raise ValueError("Invalid image dimensions.")
        # If pixmap has alpha or is CMYK, convert to RGB
        if pix.alpha or pix.n > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        jpg_bytes = pix.tobytes("jpeg")
    except Exception:
        raise HTTPException(400, "Invalid or corrupt image file. Please upload a valid JPEG, PNG, or WEBP image.")

    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cov_p = out_dir / "cover_image.jpg"
    cov_p.write_bytes(jpg_bytes)
    (out_dir / _COVER_REMOVED).unlink(missing_ok=True)

    # Invalidate older exported PDF/EPUB/DOCX so re-download reflects new cover
    job = get_job(job_id)
    preserved = await asyncio.to_thread(format_sync.protected_files, job, out_dir)
    txt_files = _translated_texts(job, out_dir) or [
        f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
    ]
    if txt_files and not format_sync.is_comic_output(job, out_dir):
        txt_content = txt_files[0].read_text(encoding="utf-8")
        base_name = txt_files[0].stem
        layout = (getattr(job, "layout_mode", "literature") if job else "literature") or "literature"
        for fmt_ext in (".pdf", ".epub", ".docx"):
            if out_dir / f"{base_name}{fmt_ext}" in preserved:
                continue
            try:
                await asyncio.to_thread(_export_from_text, txt_content, out_dir, fmt_ext.lstrip("."), base_name, layout=layout, cover_image=jpg_bytes)
            except Exception:
                pass

    return {"status": "ok", "job_id": job_id, "size": len(jpg_bytes), "preserved_files": sorted(f.name for f in preserved)}


@app.delete("/api/cover/{job_id}")
async def delete_cover_image(job_id: str):
    """Remove the custom or extracted cover image for a book and refresh cached exports."""
    _validate_job_id(job_id)
    out_dir = OUTPUT_DIR / job_id
    job = get_job(job_id)
    cov_p = out_dir / "cover_image.jpg"
    if cov_p.exists():
        try:
            cov_p.unlink()
        except Exception:
            pass
    if job:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / _COVER_REMOVED).touch()
    # Refresh cached PDF/EPUB/DOCX without cover if translated text exists
    if out_dir.exists():
        job = get_job(job_id)
        txt_files = _translated_texts(job, out_dir) or [
            f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
        ]
        if txt_files and not format_sync.is_comic_output(job, out_dir):
            preserved = await asyncio.to_thread(format_sync.protected_files, job, out_dir)
            txt_content = txt_files[0].read_text(encoding="utf-8")
            base_name = txt_files[0].stem
            layout = (getattr(job, "layout_mode", "standard") if job else "standard") or "standard"
            for fmt_ext in (".pdf", ".epub", ".docx"):
                target = out_dir / f"{base_name}{fmt_ext}"
                if target.exists() and target not in preserved:
                    try:
                        await asyncio.to_thread(_export_from_text, txt_content, out_dir, fmt_ext.lstrip("."), base_name, layout=layout, cover_image=None)
                    except Exception:
                        pass
    return {"status": "deleted", "job_id": job_id}


@app.get("/api/voices")
async def list_voices():
    """Returns available TTS voices grouped by language."""
    return get_available_voices()


def _jobs_in_scope(scope: str = "mine"):
    """
    Session History jobs. Accounts off: all. A user: own jobs. An administrator: scope 'mine' (own + jobs from before
    accounts / of removed users), 'all', or a user id.
    """
    jobs = list_jobs()
    if not auth.is_enabled():
        return jobs, {}
    names = auth.usernames_by_id()
    me = current_user()
    if me and me.get("role") == "admin" and scope != "all":
        wanted = {me["id"], ""} if scope in ("", "mine") else {scope}
        jobs = [j for j in jobs if (j.owner if j.owner in names else "") in wanted]
    return jobs, names


@app.get("/api/jobs")
async def all_jobs(include_tests: bool = False, scope: str = "mine"):
    """Returns the requester's jobs for Session History (see _jobs_in_scope). Hides test-generated jobs by default."""
    jobs, names = _jobs_in_scope(scope)
    return [
        {
            "job_id": j.job_id,
            "file_name": j.file_name,
            "file_type": j.file_type,
            "status": j.status,
            "mode": j.mode,
            "progress": j.progress,
            "done_chunks": j.done_chunks,
            "total_chunks": j.total_chunks,
            "done_pages": j.done_pages,
            "total_pages": j.total_pages,
            "resumable": is_resumable(j),
            "quota_stopped": is_quota_stop(j),
            "has_output": j.output_path is not None,
            "owner": j.owner or "",
            "owner_name": names.get(j.owner, ""),
        }
        for j in jobs
        if include_tests or not is_test_job_identifier(j.job_id, j.file_name)
    ]


@app.delete("/api/jobs/tests/cleanup")
async def clean_test_jobs_endpoint():
    """Removes all test-generated jobs from session history, SQLite and disk."""
    deleted = cleanup_test_jobs()
    return {"status": "ok", "deleted_count": len(deleted), "deleted_jobs": deleted}

@app.get("/api/debug/extract/{job_id}")
async def debug_extract(job_id: str, max_chars: int = 500):
    """
    Returns the raw extracted text (first max_chars chars per page) for debugging.
    Use this to verify that the PDF/DOCX has readable text before translating.
    """
    _validate_job_id(job_id)
    if max_chars < 1:
        raise HTTPException(400, "max_chars must be >= 1.")
    job = get_job(job_id)
    if not job or not job.file_path or not Path(job.file_path).exists():
        raise HTTPException(404, f"Job '{job_id}' not found.")

    pages = []
    try:
        for p in parse_document(job.file_path, job.file_type):
            excerpt = p["text"][:max_chars]
            pages.append({
                "page": p["page"],
                "char_count": len(p["text"]),
                "excerpt": excerpt,
            })
            if len(pages) >= 5:   # limit to first 5 pages for speed
                break
    except Exception as e:
        raise HTTPException(500, f"Extraction error: {e}")

    return {
        "job_id": job_id,
        "file_name": job.file_name,
        "file_type": job.file_type,
        "pages_sampled": len(pages),
        "pages": pages,
    }



@app.delete("/api/jobs")
async def clear_all_jobs(scope: str = "mine"):
    """
    Clean up all jobs and all temporary files inside temp/. With user accounts: only the requester's jobs
    (an administrator may pass scope=all for the full clean-up, or a user id).
    """
    if auth.is_enabled():
        me = current_user()
        if not (me and me.get("role") == "admin" and scope == "all"):
            ids = [j.job_id for j in _jobs_in_scope(scope)[0]]
            for jid in ids:
                purge_job(jid)
            return {"status": "cleared", "count": len(ids)}
    from backend.job_manager import _jobs, _active_tasks
    # Cancel and await all running tasks BEFORE deleting directories
    tasks_to_cancel = [t for t in _active_tasks.values() if not t.done()]
    for active_id in list(_active_tasks.keys()):
        cancel_job(active_id)
    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
    for parent_dir in [UPLOAD_DIR, OUTPUT_DIR]:
        if parent_dir.exists():
            for child in parent_dir.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(str(child), ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
                except Exception:
                    pass
    if TEMP_DIR.exists():
        for child in TEMP_DIR.iterdir():
            if child in (UPLOAD_DIR, OUTPUT_DIR):
                continue
            try:
                if child.is_dir():
                    shutil.rmtree(str(child), ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except Exception:
                pass
    _jobs.clear()
    POLISH_STATUS.clear()
    from backend.queue_manager import clear_queue
    clear_queue()
    from backend.database import db_clear_all_jobs
    db_clear_all_jobs()
    return {"status": "cleared", "count": 0}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str):
    """Cancels an active translation or audiobook generation job."""
    _validate_job_id(job_id)
    success = cancel_job(job_id)
    if not success:
        job = get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job '{job_id}' not found.")
        return {"job_id": job_id, "status": job.status}
    return {"job_id": job_id, "status": "cancelled"}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Clean up a job and its files."""
    _validate_job_id(job_id)
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")

    purge_job(job_id)  # cancels the task and leaves the queue BEFORE the files are deleted
    return {"deleted": job_id}


# ---------------------------------------------------------------------------
# Text Review, Editing & Re-Export
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}/chapters")
async def get_audiobook_chapters(job_id: str):
    """Chapter marks of the job's newest audiobook (for the player's chapter list)."""
    _validate_job_id(job_id)
    out_dir = OUTPUT_DIR / job_id
    if not get_job(job_id) and not out_dir.is_dir():
        raise HTTPException(404, f"Job '{job_id}' not found.")
    audio = max(out_dir.glob("*.mp3"), key=lambda f: f.stat().st_mtime, default=None)
    chapters = []
    if audio:
        try:
            marks = json.loads(audio.with_suffix(".chapters.json").read_text(encoding="utf-8"))
            chapters = [{"title": str(c["title"]), "start_seconds": float(c["start_ms"]) / 1000.0} for c in marks]
        except (OSError, ValueError, KeyError, TypeError):
            chapters = []
    return {"job_id": job_id, "chapters": chapters}


@app.get("/api/jobs/{job_id}/read-along")
async def get_audiobook_read_along(job_id: str):
    """The sentences of the job's newest audiobook with their times, for following the text while it plays."""
    _validate_job_id(job_id)
    out_dir = OUTPUT_DIR / job_id
    if not get_job(job_id) and not out_dir.is_dir():
        raise HTTPException(404, f"Job '{job_id}' not found.")
    def newest(pattern: str):
        return max(out_dir.glob(pattern), key=lambda f: f.stat().st_mtime, default=None)

    # the MP3 the player plays (an M4B made from it later for a download is newer, but the same recording)
    audio = (newest("*.mp3") or newest("*.m4b")) if out_dir.is_dir() else None
    segments = []
    if audio:
        sync = audio.with_suffix(".sync.json")
        # times of an earlier recording would be wrong for this one (made before this one finished)
        if sync.is_file() and sync.stat().st_mtime >= audio.stat().st_mtime - 5:
            try:
                segments = json.loads(sync.read_text(encoding="utf-8")).get("segments") or []
            except (OSError, ValueError, AttributeError):
                segments = []
    return {"job_id": job_id, "segments": segments}


@app.get("/api/jobs/{job_id}/text")
async def get_job_text(job_id: str):
    """Retrieve original and translated text for a job."""
    _validate_job_id(job_id)
    job = get_job(job_id)
    out_dir = OUTPUT_DIR / job_id
    if not out_dir.exists():
        if job and job.file_path and Path(job.file_path).exists():
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            raise HTTPException(404, "Job output not found.")

    txt_files = _translated_texts(job, out_dir) or [
        f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
    ]
    translated_text = ""
    if txt_files:
        translated_text = txt_files[0].read_text(encoding="utf-8")

    # Read original text if available (prefer pre-extracted *_original.txt, else parse source file)
    original_text = ""
    orig_files = list(out_dir.glob("*_original.txt"))
    if orig_files:
        try:
            original_text = orig_files[0].read_text(encoding="utf-8")
        except Exception:
            pass
    if not original_text and job and job.file_path and Path(job.file_path).exists():
        try:
            from backend.parsers import parse_document
            src_type = Path(job.file_path).suffix.lstrip(".").lower() or job.file_type
            pages = await asyncio.to_thread(lambda: list(parse_document(job.file_path, src_type)))
            original_text = "\n\n".join(f"=== PAGE {p['page']} ===\n{p['text']}" for p in pages)
        except Exception:
            pass

    # If document hasn't been translated yet, populate translated_text with original for direct editing / polishing
    if not translated_text and original_text:
        translated_text = original_text

    return {
        "job_id": job_id,
        "file_name": job.file_name if job else "",
        "translated_text": translated_text,
        "original_text": original_text,
    }


async def _save_preserving_format(job, txt_file: Path, text: str) -> tuple[set, list]:
    """Saves edited text, carrying the edit into format-preserved documents. Returns (preserved files, updated names)."""
    preserved = await asyncio.to_thread(format_sync.protected_files, job, txt_file.parent)
    if format_sync.is_comic_output(job, txt_file.parent):
        txt_file.write_text(text, encoding="utf-8")  # balloons are part of the artwork: only the text copy changes
        return preserved, []
    try:
        updated = await asyncio.to_thread(format_sync.sync_text, txt_file, text, preserved)
    except format_sync.FormatSyncError as e:
        logger.warning(f"[{txt_file.parent.name}] Edit not applied to format-preserved document: {e}")
        raise HTTPException(409, (
            "Οι αλλαγές δεν μπόρεσαν να εφαρμοστούν στο έγγραφο χωρίς απώλεια μορφοποίησης, γι' αυτό δεν άλλαξε κανένα "
            "αρχείο. Αν το έγγραφο είναι ανοιχτό σε άλλο πρόγραμμα, κλείστε το και δοκιμάστε ξανά. Αλλιώς κατεβάστε το "
            "και διορθώστε το απευθείας."
        ))
    return preserved, updated


def _translation_text_path(job, out_dir: Path, fallback_stem: str, text: str = "") -> Path:
    """Where the job's text is kept; `text` names the language while nothing has been translated."""
    stem = Path(job.file_name).stem if job else fallback_stem
    current = _translated_texts(job, out_dir)
    if current:
        return current[0]
    if text.strip() and not (job and job.status == "done"):  # never translated: edited or polished as it is
        return out_dir / f"{stem}_translated_{_text_language(text)}.txt"
    tgt_lang = re.sub(r"[^a-z-]", "", ((getattr(job, "target_lang", "") if job else "") or "").lower()) or "greek"
    return out_dir / f"{stem}_translated_{tgt_lang}.txt"


@app.put("/api/jobs/{job_id}/text")
async def update_job_text(job_id: str, req: UpdateTextRequest):
    """Save user edits to the translated text and re-export current outputs."""
    _validate_job_id(job_id)
    job = get_job(job_id)
    out_dir = OUTPUT_DIR / job_id
    if not out_dir.exists():
        raise HTTPException(404, "Job output not found.")
    if job and job.status == "running":
        raise HTTPException(409, "A task is running for this job: its output would overwrite these edits.")

    txt_files = _translated_texts(job, out_dir) or [
        f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
    ]
    txt_file = txt_files[0] if txt_files else _translation_text_path(job, out_dir, job_id, req.translated_text)

    # Save edited text (and patch format-preserved documents in place)
    preserved, updated = await _save_preserving_format(job, txt_file, req.translated_text)
    base_name = txt_file.stem

    if format_sync.is_comic_output(job, out_dir):
        return {"status": "saved", "job_id": job_id, "output_path": str(txt_file), "artwork_unchanged": True}

    # Re-export active format if job has a text-exportable format
    fmt = ((job.output_format if job else "docx") or "docx").lower().lstrip(".")
    if fmt not in {"txt", "docx", "doc", "pdf", "epub"}:
        fmt = "docx"
    if fmt == "doc" and out_dir / f"{base_name}.docx" in preserved:
        fmt = "docx"
    layout = (getattr(job, "layout_mode", "standard") if job else "standard") or "standard"
    export_path = out_dir / f"{base_name}.{fmt}"
    if export_path not in preserved:
        export_path = await asyncio.to_thread(_export_from_text, req.translated_text, out_dir, fmt, base_name, layout=layout)
    if job:
        update_job(job_id, output_path=str(export_path), output_format=fmt)

    # Invalidate older non-txt exported files so download endpoint serves the new edited version
    for f in list(out_dir.iterdir()):
        ext = f.suffix.lower()
        if f.is_file() and ext in [".pdf", ".epub", ".docx"] and f.name != export_path.name:
            if f in preserved or out_dir / f"{base_name}{ext}" in preserved:
                continue
            try:
                await asyncio.to_thread(_export_from_text, req.translated_text, out_dir, ext.lstrip("."), base_name, layout=layout)
            except Exception:
                pass

    return {"status": "saved", "job_id": job_id, "output_path": str(export_path), "updated_in_place": updated}


class SettingsRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_api_keys: Optional[list[str]] = None
    default_quota_behavior: Optional[str] = None
    final_refinement_enabled: Optional[bool] = None


def _may_see_keys() -> bool:
    return not auth.is_enabled() or (current_user() or {}).get("role") == "admin"


def _redact_pool(pool: dict) -> dict:
    """Pool health without the (masked) keys, for users who are not administrators."""
    if not isinstance(pool, dict):
        return pool
    out = dict(pool)
    out["slots"] = [dict(s, masked_key="") for s in pool.get("slots") or []]
    return out


@app.get("/api/settings")
async def get_app_settings():
    from backend.settings_manager import get_setting
    from backend.gemini_key_pool import GeminiKeyPool
    keys = GeminiKeyPool.get_keys()
    key = keys[0] if keys else ""
    has_key = bool(key)
    default_behavior = "wait" if has_key else "fallback"
    quota_behavior = get_setting("default_quota_behavior", default_behavior) or default_behavior
    if not has_key:
        quota_behavior = "fallback"
    pool_status = GeminiKeyPool.get_pool_status()
    from backend.output_refiner import is_refinement_enabled
    refinement_on = is_refinement_enabled()
    from backend.gemini_key_pool import mask_api_key
    # Keys never leave the server in clear text: the UI only needs masked forms (it sends them back unchanged to keep
    # a key; GeminiKeyPool.set_keys maps masked values back to the stored keys). Users who are not administrators
    # (user accounts mode) do not see even the masked keys.
    keys_visible = _may_see_keys()
    return {
        "gemini_api_key": mask_api_key(key) if keys_visible else "",
        "gemini_api_keys": [mask_api_key(k) for k in keys] if keys_visible else [],
        "gemini_api_keys_count": len(keys),
        "pool": pool_status if keys_visible else _redact_pool(pool_status),
        "default_quota_behavior": quota_behavior,
        "final_refinement_enabled": refinement_on,
        "m4b_available": bool(find_ffmpeg()),
        "has_gemini_key": has_key,
        "default_engine": "gemini" if has_key else "free",
    }


@app.post("/api/settings")
async def update_app_settings(req: SettingsRequest):
    from backend.settings_manager import save_setting
    from backend.ai_polisher import reset_model_cache
    from backend.comic_translator import reset_vision_model_cache
    from backend.gemini_key_pool import GeminiKeyPool

    if req.gemini_api_keys is not None:
        GeminiKeyPool.set_keys(req.gemini_api_keys)
        GeminiKeyPool.reset_quota()
        reset_model_cache()
        reset_vision_model_cache()
    elif req.gemini_api_key is not None:
        k = req.gemini_api_key.strip()
        GeminiKeyPool.set_keys([k] if k else [])
        GeminiKeyPool.reset_quota()
        reset_model_cache()
        reset_vision_model_cache()

    if req.default_quota_behavior is not None:
        val = req.default_quota_behavior.strip().lower()
        if val in ("wait", "fallback"):
            save_setting("default_quota_behavior", val)
    if req.final_refinement_enabled is not None:
        save_setting("final_refinement_enabled", bool(req.final_refinement_enabled))
    from backend.queue_manager import is_queue_paused_for_quota, resume_queue_after_quota
    keys_changed = req.gemini_api_keys is not None or req.gemini_api_key is not None
    if keys_changed and is_queue_paused_for_quota() and GeminiKeyPool.get_keys():
        resume_queue_after_quota(_execute_queue_item)
    return {"status": "ok", "pool": GeminiKeyPool.get_pool_status()}


@app.get("/api/gemini/pool")
async def get_gemini_pool_status():
    """Returns detailed real-time health diagnostics for the Gemini Multi-Key Pool."""
    from backend.gemini_key_pool import GeminiKeyPool
    return GeminiKeyPool.get_pool_status()


@app.post("/api/gemini/pool")
async def update_gemini_pool_keys(payload: dict):
    """Sets or updates the pool keys (list of up to MAX_KEYS = 8 keys)."""
    keys = payload.get("keys", [])
    if not isinstance(keys, list):
        raise HTTPException(400, "'keys' must be a list of API key strings.")
    from backend.gemini_key_pool import GeminiKeyPool
    from backend.ai_polisher import reset_model_cache
    from backend.comic_translator import reset_vision_model_cache
    saved = GeminiKeyPool.set_keys(keys)
    GeminiKeyPool.reset_quota()
    reset_model_cache()
    reset_vision_model_cache()
    from backend.queue_manager import is_queue_paused_for_quota, resume_queue_after_quota
    if is_queue_paused_for_quota() and saved:
        resume_queue_after_quota(_execute_queue_item)
    return {"status": "ok", "keys_count": len(saved), "pool": GeminiKeyPool.get_pool_status()}


@app.delete("/api/settings/{key}")
async def delete_app_setting(key: str):
    if key not in {"gemini_api_key", "gemini_api_keys"}:
        raise HTTPException(400, f"Unsupported setting key '{key}'.")
    from backend.settings_manager import delete_setting
    from backend.ai_polisher import reset_model_cache, reset_gemini_quota_exhaustion
    from backend.comic_translator import reset_vision_model_cache
    from backend.gemini_key_pool import GeminiKeyPool
    GeminiKeyPool.set_keys([])
    delete_setting("gemini_api_key")
    delete_setting("gemini_api_keys")
    reset_gemini_quota_exhaustion()
    reset_model_cache()
    reset_vision_model_cache()
    return {"status": "deleted", "key": key}


# ---------------------------------------------------------------------------
# AI Polish via Gemini
# ---------------------------------------------------------------------------

def _jobs_waiting_for_quota(limit: int = 5, max_age_hours: float = 48.0) -> list[dict]:
    """The viewer's recent jobs that wait for the Gemini limit to renew (stopped on quota or queued for it)."""
    since = time.time() - max_age_hours * 3600
    waiting = []
    try:
        for job in sorted(list_jobs(), key=lambda j: j.updated_at or 0, reverse=True):
            if (job.updated_at or 0) < since:
                break
            if job.status == "waiting_quota" or is_quota_stop(job):
                waiting.append({"job_id": job.job_id, "file_name": job.file_name, "mode": job.mode,
                                "status": job.status})
                if len(waiting) >= limit:
                    break
    except Exception as e:  # the status must answer even if the job list cannot be read
        logger.debug(f"Waiting jobs not listed: {e}")
    return waiting


@app.get("/api/gemini/status")
async def get_gemini_status():
    """Current Gemini quota state: the daily circuit breaker, models at their limit on the pool's keys, and the
    viewer's jobs that wait for a renewal."""
    from backend.ai_polisher import get_gemini_quota_info, get_daily_gemini_usage
    info = dict(get_gemini_quota_info())
    info["usage_today"] = get_daily_gemini_usage()
    if "pool" in info and not _may_see_keys():
        info["pool"] = _redact_pool(info["pool"])
    info["waiting_jobs"] = _jobs_waiting_for_quota()
    return info


@app.post("/api/gemini/reset-quota")
async def reset_gemini_quota_endpoint():
    """Manually resets the Gemini daily quota circuit breaker cooldown and per-key cooldowns."""
    from backend.gemini_key_pool import GeminiKeyPool
    GeminiKeyPool.reset_quota()
    return {"status": "ok", "message": "Gemini quota circuit breaker reset."}


@app.get("/api/polish/status/{job_id}")
async def get_polish_status(job_id: str):
    """Returns current real-time progress of AI Polish for a given job."""
    _validate_job_id(job_id)
    from backend.ai_polisher import get_polish_job_status
    return get_polish_job_status(job_id)


@app.post("/api/polish")
async def polish_translation(req: PolishRequest):
    """Polish and proofread document or text directly using Gemini API (with or without prior translation)."""
    req.layout_mode = _validate_choice(req.layout_mode, LAYOUT_MODES, "layout_mode")
    if not req.job_id:
        job = create_job("", "direct_text.txt", "txt")
        out_dir = OUTPUT_DIR / job.job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        placeholder_file = out_dir / "direct_text.txt"
        placeholder_file.write_text(req.text or "", encoding="utf-8")
        update_job(job.job_id, file_path=str(placeholder_file), mode="translate")
        req.job_id = job.job_id
    else:
        _validate_job_id(req.job_id)
        job = get_job(req.job_id)
        if job is None and job_owner(req.job_id) is not None:  # another user's job (user accounts mode)
            raise HTTPException(404, f"Job '{req.job_id}' not found.")
        if job and job.status == "running":
            raise HTTPException(409, "A task is already running for this job.")
        out_dir = OUTPUT_DIR / req.job_id
        out_dir.mkdir(parents=True, exist_ok=True)

    text_to_polish = req.text

    if req.api_key and req.api_key.strip() and not req.api_key.strip().startswith(("AQ.Test", "AIzaTest")):
        from backend.settings_manager import save_setting
        from backend.ai_polisher import reset_model_cache
        from backend.comic_translator import reset_vision_model_cache
        save_setting("gemini_api_key", req.api_key.strip())
        reset_model_cache()
        reset_vision_model_cache()

    if not text_to_polish:
        txt_files = _translated_texts(job, out_dir) or list(out_dir.glob("*.txt"))
        if txt_files:
            text_to_polish = txt_files[0].read_text(encoding="utf-8")
        elif job and job.file_path and Path(job.file_path).exists():
            # DIRECT STANDALONE DOCUMENT POLISH: Extract text from original uploaded file
            pages = await asyncio.to_thread(lambda: list(parse_document(job.file_path, job.file_type)))
            sections = []
            for p in pages:
                p_num = p.get("page", 1)
                t = p.get("text", "").strip()
                if t:
                    sections.append(f"=== PAGE {p_num} ===\n{t}")
            text_to_polish = "\n\n".join(sections)
            if not text_to_polish.strip():
                raise HTTPException(400, "Could not extract readable text from the uploaded document.")
            stem = Path(job.file_name).stem
            (out_dir / f"{stem}_original.txt").write_text(text_to_polish, encoding="utf-8")
        else:
            raise HTTPException(404, "No document or text found to polish.")

    from backend.ai_polisher import polish_text_with_gemini

    # Locate or extract original text for bilingual source-anchoring if requested
    original_text: Optional[str] = None
    if req.bilingual_mode:
        orig_files = list(out_dir.glob("*_original.txt"))
        if orig_files:
            try:
                original_text = orig_files[0].read_text(encoding="utf-8")
            except Exception:
                pass
        if not original_text and job and job.file_path and Path(job.file_path).exists():
            try:
                pages = await asyncio.to_thread(lambda: list(parse_document(job.file_path, job.file_type)))
                sections = []
                for p in pages:
                    p_num = p.get("page", 1)
                    t = p.get("text", "").strip()
                    if t:
                        sections.append(f"=== PAGE {p_num} ===\n{t}")
                if sections:
                    original_text = "\n\n".join(sections)
                    stem = Path(job.file_name).stem
                    (out_dir / f"{stem}_original.txt").write_text(original_text, encoding="utf-8")
            except Exception as ex:
                logger.warning(f"Could not extract original text for bilingual anchoring: {ex}")

    # Auto-disable redundant Source-Anchored Verification when original == draft (e.g. standalone Greek polish)
    effective_bilingual = req.bilingual_mode
    if effective_bilingual and original_text and original_text.strip() == (text_to_polish or "").strip():
        logger.info(f"[{req.job_id}] Standalone polish detected (source identical to draft) — auto-disabling Source-Anchored Verification.")
        original_text = None
        effective_bilingual = False

    from backend.ai_polisher import get_polish_job_status, update_polish_job_status

    def on_progress(current: int, total: int):
        pct = int((current / max(1, total)) * 100)
        update_polish_job_status(
            req.job_id,
            current=current,
            total=total,
            percent=pct,
            status="running",
            step=f"Polishing batch {current} of {total}...",
        )

    from backend.gemini_key_pool import resolve_gemini_api_key
    resolved_polish_key = resolve_gemini_api_key(req.api_key)
    polish_quota_behavior = "wait" if resolved_polish_key else "fallback"

    init_step = "Connecting to Gemini Flash AI..." if resolved_polish_key else "ℹ️ Εφαρμογή δωρεάν τυπογραφικών κανόνων & γλωσσαρίου (Free Mode)..."
    update_polish_job_status(
        req.job_id,
        current=0,
        total=1,
        percent=0,
        status="running",
        step=init_step,
    )

    # The text's language picks the prompt, glossary and typography (the pipeline used to assume Greek)
    polish_lang = _text_language(text_to_polish)

    from backend.ai_polisher import track_gemini_usage
    polish_usage_cm = track_gemini_usage()
    polish_usage = polish_usage_cm.__enter__()
    try:
        polished = await polish_text_with_gemini(
            text=text_to_polish,
            api_key=req.api_key,
            style=req.style,
            original_text=original_text,
            job_id=req.job_id,
            use_source_anchoring=effective_bilingual,
            progress_callback=on_progress,
            target_lang=polish_lang,
            quota_behavior=polish_quota_behavior,
        )
        total_p = get_polish_job_status(req.job_id).get("total", 1)
        done_step = "AI Polishing complete!" if resolved_polish_key else "Ολοκληρώθηκε με δωρεάν τυπογραφική επιμέλεια & γλωσσάρι!"
        update_polish_job_status(
            req.job_id,
            current=total_p,
            total=total_p,
            percent=100,
            status="done",
            step=done_step,
        )
    except Exception as e:
        update_polish_job_status(
            req.job_id,
            current=0,
            total=1,
            percent=0,
            status="error",
            step=str(e),
        )
        logger.error(f"AI Polishing failed: {e}", exc_info=True)
        polish_usage_cm.__exit__(None, None, None)
        raise HTTPException(500, f"AI Polishing failed: {str(e)}")

    # Update or create output files on disk
    tgt_lang = polish_lang

    # Automatic Final Output Refinement Stage for Polish
    try:
        from backend.output_refiner import refine_text_content, is_refinement_enabled
        if is_refinement_enabled(getattr(req, "final_refinement", None)):
            polished_refined, _, _ = refine_text_content(
                polished,
                target_lang=tgt_lang,
                source_lang="english",
                style=req.style,
            )
            polished = polished_refined
    except Exception as ref_ex:
        logger.warning(f"Refinement during standalone polish warning: {ref_ex}")

    txt_file = _translation_text_path(job, out_dir, "polished_document", polished)
    preserved, _updated = await _save_preserving_format(job, txt_file, polished)
    base_name = txt_file.stem
    fmt = ((job.output_format if job else "docx") or "docx").lower().lstrip(".")
    layout = (req.layout_mode or (getattr(job, "layout_mode", "standard") if job else "standard") or "standard").lower()
    if format_sync.is_comic_output(job, out_dir):
        # artwork outputs stay exactly as they are
        export_path = Path(job.output_path) if job and job.output_path else txt_file
        layout = "comic"
    else:
        if fmt not in {"txt", "docx", "doc", "pdf", "epub"}:
            fmt = "docx"
        if fmt == "doc" and out_dir / f"{base_name}.docx" in preserved:
            fmt = "docx"
        export_path = out_dir / f"{base_name}.{fmt}"
        if export_path not in preserved:
            export_path = await asyncio.to_thread(_export_from_text, polished, out_dir, fmt, base_name, layout=layout)

        # Refresh other standard formats on-demand (without redundantly re-exporting fmt)
        for other_fmt in ("pdf", "epub", "docx"):
            if other_fmt == fmt or out_dir / f"{base_name}.{other_fmt}" in preserved:
                continue
            try:
                await asyncio.to_thread(_export_from_text, polished, out_dir, other_fmt, base_name, layout=layout)
            except Exception:
                pass

    if job:
        update_job(
            req.job_id,
            status="done",
            progress=100,
            output_path=str(export_path),
            output_format=fmt,
            layout_mode=layout,
            current_step="AI Polishing complete!",
        )

    polish_usage_cm.__exit__(None, None, None)
    return {"status": "polished", "job_id": req.job_id, "polished_text": polished, "gemini_usage": dict(polish_usage)}


# ---------------------------------------------------------------------------
# Self-contained endpoint groups (backend/api/*): refinement, Book Insights, device pairing
# ---------------------------------------------------------------------------
from backend.api import refine as _refine_api, insights as _insights_api, pairing as _pairing_api  # noqa: E402
from backend.api import auth as _auth_api, connections as _connections_api  # noqa: E402

# Register the routers' routes directly on the app (no prefix/dependencies), so they appear as plain APIRoute
# entries in app.routes exactly like routes declared here (FastAPI >= 0.16x nests include_router() routers,
# which hides them from code that inspects app.routes, e.g. the API contract and coverage tests).
for _api_router in (_refine_api.router, _insights_api.router, _pairing_api.router, _auth_api.router,
                    _connections_api.router):
    app.router.routes.extend(_api_router.routes)


# ---------------------------------------------------------------------------
# Glossary Management
# ---------------------------------------------------------------------------

@app.get("/api/glossary")
async def get_glossary_terms(category: Optional[str] = None, categorized: bool = False):
    """Retrieve custom glossary mappings, optionally categorized or filtered by category."""
    from backend.glossary import load_glossary, load_categorized_glossary
    if categorized:
        return load_categorized_glossary()
    return load_glossary(category=category)


@app.post("/api/glossary")
async def add_glossary_term(req: GlossaryTermRequest):
    """Add or update a glossary term with an optional category."""
    from backend.glossary import set_term
    try:
        updated = set_term(req.source, req.target, category=req.category)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "saved", "glossary": updated}


@app.delete("/api/glossary/{term:path}")
async def remove_glossary_term(term: str):
    """Delete a glossary term."""
    from backend.glossary import delete_term
    updated = delete_term(term)
    return {"status": "deleted", "glossary": updated}


# ---------------------------------------------------------------------------
# Genre Detection, Voice Previews & Cache / Storage Ops
# ---------------------------------------------------------------------------

@app.get("/api/preview/{job_id}")
async def preview_document_text(job_id: str, max_chars: int = 3500):
    """Returns a fast text preview snippet of an uploaded document for auto-genre detection."""
    _validate_job_id(job_id)
    if max_chars < 1:
        raise HTTPException(400, "max_chars must be >= 1.")
    job = get_job(job_id)
    if not job or not job.file_path or not Path(job.file_path).exists():
        raise HTTPException(404, f"Job '{job_id}' or its source file not found.")
    try:
        parts = []
        total_len = 0
        for page in parse_document(job.file_path, job.file_type):
            txt = (page.get("text") or "").strip()
            if txt:
                parts.append(txt)
                total_len += len(txt)
            if total_len >= max_chars:
                break
        preview_text = "\n\n".join(parts)[:max_chars]
        from backend.genre_detector import book_subjects
        return {"job_id": job_id, "file_type": job.file_type, "preview_text": preview_text,
                "subjects": book_subjects(job.file_path, job.file_type)}
    except Exception as e:
        raise HTTPException(500, f"Preview extraction failed: {e}")


@app.post("/api/detect-genre")
async def detect_genre(req: GenreDetectionRequest):
    """Auto-detects document genre, tone, recommended polish style and glossary category."""
    from backend.genre_detector import detect_genre_and_style
    input_text = req.sample_text or req.text or ""
    subjects = [str(s)[:200] for s in (req.subjects or [])[:20]]
    return detect_genre_and_style(input_text, req.file_type or "", subjects=subjects)


@app.get("/api/tts/preview")
async def tts_preview(voice: str = "el-GR-NestorasNeural", text: Optional[str] = None):
    """Generates an instant 2-3s audio audition sample for a voice."""
    if not voice or not re.match(r"^[A-Za-z0-9_-]{3,80}$", voice):
        raise HTTPException(400, f"Invalid voice identifier '{voice}'.")
    from backend.tts_engine import synthesize_voice_preview
    try:
        path = await synthesize_voice_preview(voice, text)
        return FileResponse(path, media_type="audio/mpeg", filename=f"preview_{voice}.mp3")
    except Exception as e:
        raise HTTPException(500, f"Voice preview failed: {e}")


@app.get("/api/cache/stats")
async def cache_stats():
    """Returns database translation cache stats."""
    from backend.database import db_get_cache_stats
    return db_get_cache_stats()


@app.post("/api/admin/cleanup")
async def admin_storage_cleanup(req: Optional[AdminCleanupRequest] = None):
    """Triggers storage cleanup for temporary audio chunks and obsolete extractions."""
    from backend.storage_cleaner import clean_temp_storage
    hours = req.max_age_hours if req else 48
    dry = req.dry_run if req else False
    if hours < 1:
        raise HTTPException(400, "max_age_hours must be >= 1.")
    return clean_temp_storage(max_age_hours=hours, dry_run=dry)


# ---------------------------------------------------------------------------
# Smart Batch Queue Endpoints
# ---------------------------------------------------------------------------

async def _execute_queue_item(q_item):
    """Executes a single QueueItem via the existing _run_translation pipeline."""
    job = get_job(q_item.job_id)
    if not job:
        raise ValueError(f"Job '{q_item.job_id}' not found.")
    if job.status == "running":
        raise RuntimeError(f"Job '{q_item.job_id}' is already running.")
    if (q_item.source_lang or "").strip().lower() == (q_item.target_lang or "").strip().lower():
        raise ValueError("Source and target languages must be different.")

    if job.owner:
        # The queue processor serves everyone: inside this item, act as the job's owner (Gemini usage per user)
        set_current_user({"id": job.owner, "username": "", "role": "user"})

    out_dir = _job_output_dir(q_item.job_id)
    stem = Path(job.file_name).stem
    output_path = str(out_dir / f"{stem}_translated_{q_item.target_lang}.txt")

    clear_job_cancellation(q_item.job_id)
    update_job(
        q_item.job_id,
        mode="translate",
        status="running",
        error=None,
        source_lang=q_item.source_lang,
        target_lang=q_item.target_lang,
        output_format=q_item.output_format,
        layout_mode=q_item.layout_mode,
        reading_direction=q_item.reading_direction,
        ai_polish=q_item.ai_polish,
        quota_behavior=getattr(q_item, "quota_behavior", "wait") or "wait",
        final_refinement=None,  # queue items follow the global final_refinement_enabled setting
        refinement_report=None,
        max_quality=False,      # the token-intensive revision pass is never applied implicitly to batches
        revision_report=None,
        read_scanned_text=bool(q_item.is_scanned and not q_item.is_comic),  # a scanned book: its text is read first
        sample_range=None,
    )
    await _run_translation(
        q_item.job_id,
        job.file_path,
        job.file_type,
        q_item.source_lang,
        q_item.target_lang,
        output_path,
        q_item.ai_polish,
        q_item.api_key,
        getattr(q_item, "quota_behavior", "wait") or "wait",
    )


@app.get("/api/queue")
async def get_batch_queue():
    """Returns live Smart Batch Queue state."""
    from backend.queue_manager import get_queue_state
    return get_queue_state()


@app.post("/api/queue/add")
async def add_batch_queue_item(req: QueueAddRequest):
    """Adds an uploaded job to the Smart Batch Queue. Auto-starts if auto_start is enabled."""
    from backend.queue_manager import add_to_queue, get_queue_state, start_queue
    req.source_lang = _validate_language(req.source_lang or "english", "source_lang")
    req.target_lang = _validate_language(req.target_lang or "greek", "target_lang")
    req.output_format = _validate_choice(req.output_format.strip().lstrip("."), OUTPUT_FORMATS, "output_format") or "pdf"
    req.layout_mode = _validate_choice(req.layout_mode, LAYOUT_MODES, "layout_mode") or "standard"
    req.reading_direction = _validate_choice(req.reading_direction, READING_DIRECTIONS, "reading_direction") or "ltr"
    req.quota_behavior = _validate_choice(req.quota_behavior, QUOTA_BEHAVIORS, "quota_behavior") or ""
    try:
        add_to_queue(
            job_id=req.job_id,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            output_format=req.output_format,
            layout_mode=req.layout_mode,
            reading_direction=req.reading_direction,
            ai_polish=req.ai_polish,
            api_key=req.api_key,
            is_comic=req.is_comic,
            is_scanned=req.is_scanned,
            quota_behavior=req.quota_behavior,
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))

    state_data = get_queue_state()
    if state_data["auto_start"] and not state_data["paused"] and not state_data.get("is_mixed"):
        state_data = start_queue(_execute_queue_item)
    return state_data


@app.post("/api/queue/{job_id}/retry")
async def retry_batch_queue_item(job_id: str):
    """Retries a failed, cancelled, or completed queue item and starts processing if not paused."""
    _validate_job_id(job_id)
    from backend.queue_manager import retry_queue_item, get_queue_state, start_queue
    try:
        retry_queue_item(job_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))

    state_data = get_queue_state()
    if not state_data["paused"] or state_data["paused_for_quota"]:  # "Retry Now" while waiting for quota
        state_data = start_queue(_execute_queue_item)
    return state_data


@app.post("/api/queue/start")
async def start_batch_queue(req: Optional[QueueStartRequest] = None):
    """Starts or resumes serial execution of the Smart Batch Queue.
    Optionally syncs the user's latest Translation Settings onto all currently queued items.
    """
    from backend.queue_manager import start_queue, apply_settings_to_queued_items
    if req is not None:
        if req.source_lang:
            req.source_lang = _validate_language(req.source_lang, "source_lang")
        if req.target_lang:
            req.target_lang = _validate_language(req.target_lang, "target_lang")
        req.output_format = _validate_choice((req.output_format or "").strip().lstrip("."), OUTPUT_FORMATS, "output_format")
        req.layout_mode = _validate_choice(req.layout_mode, LAYOUT_MODES, "layout_mode")
        req.reading_direction = _validate_choice(req.reading_direction, READING_DIRECTIONS, "reading_direction")
        req.quota_behavior = _validate_choice(req.quota_behavior, QUOTA_BEHAVIORS, "quota_behavior")
        try:
            apply_settings_to_queued_items(
                source_lang=req.source_lang,
                target_lang=req.target_lang,
                output_format=req.output_format,
                layout_mode=req.layout_mode,
                reading_direction=req.reading_direction,
                ai_polish=req.ai_polish,
                api_key=req.api_key,
                quota_behavior=req.quota_behavior,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
    return start_queue(_execute_queue_item)


@app.post("/api/queue/pause")
async def pause_batch_queue():
    """Pauses the Smart Batch Queue after the current active document finishes."""
    from backend.queue_manager import pause_queue, get_queue_state
    pause_queue()
    return get_queue_state()


@app.post("/api/queue/auto-start")
async def toggle_batch_queue_auto_start(req: QueueAutoStartRequest):
    """Toggles automatic queue execution when new documents are added (disabled on mixed book+comic queues)."""
    from backend.queue_manager import set_queue_auto_start, get_queue_state, start_queue
    effective = set_queue_auto_start(req.auto_start)
    state_data = get_queue_state()
    if effective and state_data["queued_count"] > 0 and not state_data["is_running"] and not state_data.get("is_mixed"):
        state_data = start_queue(_execute_queue_item)
    return state_data


@app.get("/api/queue/download-all")
async def download_batch_queue_zip():
    """Bundles all completed translated files in the queue into a single ZIP archive.
    Requires all translations in the queue to be completed first.
    """
    import zipfile
    from backend.queue_manager import get_queue_state, get_completed_queue_job_ids

    q_state = get_queue_state()
    if q_state["total_count"] == 0:
        raise HTTPException(404, "No completed documents in the queue to download.")
    if q_state["is_running"] or q_state["queued_count"] > 0 or q_state["done_count"] < q_state["total_count"]:
        raise HTTPException(
            409,
            f"All translations must be completed before downloading ({q_state['done_count']}/{q_state['total_count']} completed).",
        )

    done_ids = get_completed_queue_job_ids()
    if not done_ids:
        raise HTTPException(404, "No completed documents in the queue to download.")

    buf = io.BytesIO()
    added_files = 0
    used_names = set()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for jid in done_ids:
            job = get_job(jid)
            if not job or not job.output_path:
                continue
            out_p = Path(job.output_path)
            if not out_p.exists():
                continue
            arc_name = out_p.name
            if arc_name in used_names:
                arc_name = f"{out_p.stem}_{jid[:6]}{out_p.suffix}"
            used_names.add(arc_name)
            zf.write(str(out_p), arcname=arc_name)
            added_files += 1

    if added_files == 0:
        raise HTTPException(404, "No downloadable output files found for completed queue jobs.")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="BookApp_Batch_Translated.zip"'},
    )


@app.delete("/api/queue/{job_id}")
async def remove_batch_queue_item(job_id: str):
    """Removes a single job from the Smart Batch Queue."""
    _validate_job_id(job_id)
    from backend.queue_manager import remove_from_queue, get_queue_state
    removed = remove_from_queue(job_id)
    if not removed:
        raise HTTPException(404, f"Job '{job_id}' not found in queue.")
    return get_queue_state()


@app.delete("/api/queue")
async def clear_batch_queue():
    """Clears all non-running items from the Smart Batch Queue."""
    from backend.queue_manager import clear_queue, get_queue_state
    clear_queue()
    return get_queue_state()


# ---------------------------------------------------------------------------
# Serve Frontend
# ---------------------------------------------------------------------------

FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
