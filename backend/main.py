"""
Main FastAPI application for the Document Translator & Audiobook Generator.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.job_manager import (
    create_job, get_job, update_job, list_jobs, cleanup_old_jobs,
    cancel_job, clear_job_cancellation, register_task, unregister_task, is_job_cancelled,
    is_valid_job_id, cleanup_test_jobs, is_test_job_filename,
)
from backend.parsers import count_pages, parse_document
from backend.translator import translate_document
from backend.tts_engine import generate_audiobook, get_available_voices
from backend.exporter import export_text
from backend.format_preserver import translate_docx_in_place, translate_epub_in_place
from backend.ai_polisher import POLISH_STATUS
# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("DocTranslate & AudioBook Generator started.")
    cleanup_old_jobs()
    cleanup_test_jobs()
    yield


app = FastAPI(
    title="DocTranslate & AudioBook",
    description="Translate documents and generate audiobooks powered by neural AI",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".js", ".css", ".html")) or path in ("/", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Directories
BASE_DIR = Path(__file__).parent.parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

UPLOAD_DIR = TEMP_DIR / "uploads"
OUTPUT_DIR = TEMP_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    job_id: str
    source_lang: str   # 'english' or 'greek'
    target_lang: str   # 'english' or 'greek'
    output_format: str = "txt"  # txt, docx, pdf, epub, cbz, cbr
    layout_mode: str = "standard"  # 'standard', 'literature', or 'comic'
    reading_direction: str = "ltr"  # 'ltr' or 'rtl' (Manga)
    ai_polish: bool = False
    api_key: Optional[str] = None


class AudiobookRequest(BaseModel):
    job_id: str
    language: str      # 'english' or 'greek' — language of the audio output
    voice_name: str    # e.g. 'Athina (Female)'
    dialogue_voice: Optional[str] = None  # optional second voice for character speech / dialogues
    use_translated: bool = False  # if True, use the translated text from a prior translation job
    narration_style: str = "literature"  # 'literature' (natural book flow) or 'standard'
    rate: Optional[str] = None           # optional explicit speed e.g. '-18%', '-10%', '+0%'
    pitch: Optional[str] = None          # optional explicit pitch e.g. '-2Hz', '-1Hz', '+0Hz'
    ai_polish: bool = False              # if True, polish script with Gemini before TTS
    api_key: Optional[str] = None        # optional Gemini API key override


class GenreDetectionRequest(BaseModel):
    sample_text: Optional[str] = None
    text: Optional[str] = None
    file_type: Optional[str] = ""


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


class UpdateTextRequest(BaseModel):
    translated_text: str


class PolishRequest(BaseModel):
    job_id: Optional[str] = None
    text: Optional[str] = None
    style: str = "formal"
    api_key: Optional[str] = None
    layout_mode: Optional[str] = None
    bilingual_mode: bool = True


class GlossaryTermRequest(BaseModel):
    source: str
    target: str
    category: str = "general"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".epub", ".doc", ".cbz", ".zip"}
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def _validate_job_id(job_id: Optional[str]) -> str:
    """Validates a single-segment job_id to prevent path traversal."""
    if not is_valid_job_id(job_id):
        raise HTTPException(400, "Invalid job_id.")
    return job_id


def _sanitize_filename(filename: Optional[str]) -> str:
    """Sanitizes uploaded filenames for Windows/POSIX filesystem safety."""
    raw = (filename or "document").replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")
    if not cleaned:
        cleaned = "document"
    p = Path(cleaned)
    if p.stem.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"file_{p.stem}{p.suffix}"
    return cleaned


def _get_file_type(filename: str) -> Optional[str]:
    ext = Path(filename).suffix.lower()
    mapping = {".pdf": "pdf", ".docx": "docx", ".epub": "epub", ".cbz": "cbz", ".zip": "cbz"}
    return mapping.get(ext)


def _job_output_dir(job_id: str) -> Path:
    _validate_job_id(job_id)
    d = OUTPUT_DIR / job_id
    d.mkdir(exist_ok=True)
    return d


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
        raise HTTPException(400, f"Unsupported file type '{ext}'. Supported: PDF, DOCX, EPUB, CBZ, ZIP.")

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
    tmp_path = job_dir / f"{uuid.uuid4().hex}_{safe_filename}"
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

        # Create job and move upload atomically to its job directory
        job = create_job(
            file_path=str(tmp_path),
            file_name=safe_filename,
            file_type=file_type,
        )
        job_upload_dir = UPLOAD_DIR / job.job_id
        job_upload_dir.mkdir(exist_ok=True)
        final_path = job_upload_dir / safe_filename
        shutil.move(str(tmp_path), str(final_path))
        update_job(job.job_id, file_path=str(final_path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    # Extract and cache cover image from original input if present
    try:
        from backend.exporter import extract_cover_image
        cov_bytes = extract_cover_image(str(final_path))
        if cov_bytes:
            out_d = _job_output_dir(job.job_id)
            cov_p = out_d / "cover_image.jpg"
            cov_p.write_bytes(cov_bytes)
            logger.info(f"Preserved original cover image for {file.filename} ({len(cov_bytes)} bytes)")
    except Exception as cov_err:
        logger.warning(f"Could not extract cover image for {file.filename}: {cov_err}")

    # Count pages, detect language, and auto-detect Graphic Novel / Scanned Comic
    try:
        page_count = count_pages(str(final_path), file_type)
    except Exception:
        page_count = 0

    detected_language = _detect_document_language(str(final_path), file_type)

    from backend.parsers import detect_is_graphic_novel
    comic_info = detect_is_graphic_novel(str(final_path), file_type, file.filename)

    # Persist page count and auto-detected comic layout in SQLite metadata
    update_job(
        job.job_id,
        total_pages=page_count,
        layout_mode="comic" if comic_info["is_comic"] else "standard",
        ai_polish=bool(comic_info["is_scanned"]),
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
        "is_comic": comic_info["is_comic"],
        "is_scanned": comic_info["is_scanned"],
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

    output_dir = _job_output_dir(req.job_id)
    stem = Path(job.file_name).stem
    output_path = str(output_dir / f"{stem}_translated_{tgt_lang}.txt")

    output_format = (getattr(req, "output_format", "txt") or "txt").strip().lower().lstrip(".")
    if output_format not in {"txt", "docx", "doc", "pdf", "epub", "cbz", "cbr"}:
        raise HTTPException(400, f"Unsupported output format '{output_format}'.")
    layout_mode = (getattr(req, "layout_mode", "standard") or "standard").strip().lower()
    reading_direction = (getattr(req, "reading_direction", "ltr") or "ltr").strip().lower()
    if reading_direction not in {"ltr", "rtl"}:
        reading_direction = "ltr"
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
    )

    return {"job_id": req.job_id, "status": "started", "output_path": output_path}


async def _run_translation(job_id, file_path, file_type, source_lang, target_lang, output_path, ai_polish=False, api_key=None):
    task = asyncio.current_task()
    if task:
        register_task(job_id, task)
    try:
        job = get_job(job_id)
        if not job:
            return
        fmt = getattr(job, "output_format", "txt") or "txt"
        fmt = fmt.lower()
        layout = getattr(job, "layout_mode", "standard") or "standard"
        out_dir = Path(output_path).parent
        stem = Path(file_path).stem
        base_name = f"{stem}_translated_{target_lang}"

        if is_job_cancelled(job_id):
            return

        from backend.settings_manager import get_setting
        from backend.parsers import detect_is_graphic_novel
        resolved_key = (api_key or "").strip() or (get_setting("gemini_api_key", "") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()

        # Check if uploaded PDF is a scanned/image-only document or graphic novel
        comic_probe = detect_is_graphic_novel(file_path, file_type, job.file_name or "")
        is_comic_flow = (
            layout in ("comic", "graphic_novel")
            or file_type in ("cbz", "cbr")
            or (file_type == "pdf" and comic_probe.get("is_scanned", False))
        )

        # 0. Graphic Novel / Comic / Scanned Image PDF translation (balloons/vision only, preserving 100% artwork)
        if is_comic_flow:
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
                if not cbr_path.exists():
                    from backend.exporter import export_comic_archive
                    export_comic_archive(final_comic_pdf, cbr_path, format="cbr")
                final_path = cbr_path
                job.output_path = str(cbr_path)
                job.output_format = "cbr"
            elif fmt == "epub":
                epub_path = out_dir / f"{base_name}.epub"
                if not epub_path.exists():
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

        # 1. Single-Pass Direct AI Translation & Polish for ALL book/document formats (PDF, EPUB, DOCX, TXT)
        elif ai_polish and resolved_key:
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
            )
            if is_job_cancelled(job_id):
                return
            txt_content = Path(output_path).read_text(encoding="utf-8")
            update_job(job_id, current_step=f"Exporting AI-polished {fmt.upper()}...", progress=95)
            final_path = export_text(txt_content, out_dir, fmt, base_name, layout=layout)

        # 2. DOCX In-Place Format Preservation (styles, fonts, sizes, tables, bold/italic)
        elif file_type == "docx" and fmt in ("docx", "doc"):
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
            )
            if is_job_cancelled(job_id):
                return
            # Save plain text version for audiobooks / fallback
            Path(output_path).write_text(translated_txt, encoding="utf-8")
            final_path = final_docx_path

        # 3. EPUB In-Place Format Preservation (HTML tags, CSS, headings, styles, images)
        elif file_type == "epub" and fmt == "epub":
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
            )
            if is_job_cancelled(job_id):
                return
            txt_content = Path(output_path).read_text(encoding="utf-8")
            update_job(job_id, current_step=f"Exporting to {fmt.upper()}...", progress=95)
            final_path = export_text(txt_content, out_dir, fmt, base_name, layout=layout)

        if is_job_cancelled(job_id):
            return

        # Mark job complete (preserve real batch/page totals)
        final_total = max(int(getattr(job, "total_chunks", 0) or 0), 1)
        update_job(job_id,
            status="done",
            progress=100,
            current_step=f"Exported {fmt.upper()} (Formatting Preserved)",
            output_path=str(final_path),
            output_format=fmt,
            done_chunks=final_total,
            total_chunks=final_total,
        )
    except asyncio.CancelledError:
        logger.info(f"[{job_id}] Translation task was cancelled.")
        update_job(job_id, status="cancelled", current_step="🛑 Cancelled by user.")
    except Exception as e:
        logger.error(f"Translation/export error [{job_id}]: {e}", exc_info=True)
        from backend.ai_polisher import is_gemini_quota_exhausted, DailyQuotaExhaustedError, get_gemini_quota_info
        err_str = str(e)
        if isinstance(e, DailyQuotaExhaustedError) or is_gemini_quota_exhausted() or any(k in err_str.lower() for k in ("quota", "resource_exhausted", "429")):
            q_info = get_gemini_quota_info()
            update_job(
                job_id,
                status="error",
                error=err_str if "Εξαντλήθηκε" in err_str else f"⚠️ {q_info['message'] or err_str}",
                current_step="⚠️ Σταμάτησε: Εξαντλήθηκε το ημερήσιο όριο Gemini API",
            )
        else:
            update_job(job_id, status="error", error=err_str)
    finally:
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

    lang_norm = (req.language or "greek").strip().lower()
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

    if req.ai_polish:
        from backend.settings_manager import get_setting
        resolved_key = (req.api_key or "").strip() or (get_setting("gemini_api_key", "") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if not resolved_key:
            raise HTTPException(400, "Gemini API key is required for AI Audiobook Polish. Please save your key in AI Polish first.")

    clear_job_cancellation(req.job_id)
    update_job(req.job_id, mode="audiobook", status="running", error=None)

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
    )

    return {"job_id": req.job_id, "status": "started", "output_path": output_path}


async def _run_audiobook(
    job_id, file_path, file_type, language, voice_name, output_path, translated_path,
    narration_style="literature", rate=None, pitch=None, dialogue_voice=None, ai_polish=False, api_key=None
):
    task = asyncio.current_task()
    if task:
        register_task(job_id, task)
    try:
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
        )
    except asyncio.CancelledError:
        logger.info(f"[{job_id}] Audiobook task was cancelled.")
        update_job(job_id, status="cancelled", current_step="🛑 Cancelled by user.")
    except Exception as e:
        logger.error(f"Audiobook error [{job_id}]: {e}", exc_info=True)
        update_job(job_id, status="error", error=str(e))
    finally:
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
        "gemini_quota_exhausted": quota_info["exhausted"],
        "gemini_quota_message": quota_info["message"],
        "gemini_quota_reset_timestamp": quota_info.get("reset_timestamp", 0.0),
        "gemini_quota_reset_time_str": quota_info.get("reset_time_str", ""),
        "gemini_quota_remaining_seconds": quota_info.get("remaining_seconds", 0),
    }


MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".epub": "application/epub+zip",
    ".txt": "text/plain; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".cbz": "application/vnd.comicbook+zip",
    ".cbr": "application/vnd.comicbook-rar",
}


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

        # 1. Check if a file in the requested format already exists (unless layout changed)
        if out_dir.exists() and not layout_changed:
            matching = [
                f for f in out_dir.iterdir()
                if f.is_file() and f.suffix.lower() == f".{fmt}" and not f.name.endswith("_original.txt")
            ]
            if matching:
                matching.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                out_path = matching[0]

        # Skip write/conversion side effects on HEAD requests
        if not is_head and not out_path:
            # If cover image is not yet cached in out_dir, check original uploaded file
            cov_file = out_dir / "cover_image.jpg"
            if out_dir.exists() and not cov_file.exists() and job and job.file_path and Path(job.file_path).exists():
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

            # 3. Standard text formats
            if not out_path and out_dir.exists():
                txt_files = list(out_dir.glob("*_translated_*.txt")) or [
                    f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
                ]
                if txt_files:
                    txt_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    txt_file = txt_files[0]
                    txt_content = txt_file.read_text(encoding="utf-8")
                    base_name = txt_file.stem
                    try:
                        out_path = export_text(txt_content, out_dir, fmt, base_name, layout=active_layout)
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
            if p.exists():
                out_path = p

        if not out_path and out_dir.exists():
            files = [
                f for f in out_dir.iterdir()
                if f.is_file() and f.suffix.lower() in [".docx", ".pdf", ".epub", ".mp3", ".m4b", ".cbz", ".cbr", ".txt"]
                and not f.name.endswith("_original.txt")
            ]
            if files:
                preferred = [f for f in files if f.suffix.lower() in [".cbz", ".cbr", ".pdf", ".epub", ".docx", ".mp3", ".m4b"]]
                files_to_check = preferred if preferred else files
                files_to_check.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                out_path = files_to_check[0]

    if not out_path or not out_path.exists():
        raise HTTPException(404, f"Output file for job '{job_id}' not found.")

    media_type = MIME_MAP.get(out_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=str(out_path),
        media_type=media_type,
        filename=out_path.name,
    )


@app.api_route("/api/cover/{job_id}", methods=["GET", "HEAD"])
async def get_cover_image(job_id: str):
    """Retrieve the current cover image for a job, if present."""
    _validate_job_id(job_id)
    out_dir = OUTPUT_DIR / job_id
    cov_p = out_dir / "cover_image.jpg"
    if not cov_p.exists():
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
        pix = pymupdf.Pixmap(content)
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

    # Invalidate older exported PDF/EPUB/DOCX so re-download reflects new cover
    job = get_job(job_id)
    txt_files = list(out_dir.glob("*_translated_*.txt")) or [
        f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
    ]
    if txt_files:
        txt_content = txt_files[0].read_text(encoding="utf-8")
        base_name = txt_files[0].stem
        layout = (getattr(job, "layout_mode", "literature") if job else "literature") or "literature"
        for fmt_ext in (".pdf", ".epub", ".docx"):
            try:
                export_text(txt_content, out_dir, fmt_ext.lstrip("."), base_name, layout=layout, cover_image=jpg_bytes)
            except Exception:
                pass

    return {"status": "ok", "job_id": job_id, "size": len(jpg_bytes)}


@app.delete("/api/cover/{job_id}")
async def delete_cover_image(job_id: str):
    """Remove the custom or extracted cover image for a book and refresh cached exports."""
    _validate_job_id(job_id)
    out_dir = OUTPUT_DIR / job_id
    cov_p = out_dir / "cover_image.jpg"
    if cov_p.exists():
        try:
            cov_p.unlink()
        except Exception:
            pass
    # Refresh cached PDF/EPUB/DOCX without cover if translated text exists
    if out_dir.exists():
        job = get_job(job_id)
        txt_files = list(out_dir.glob("*_translated_*.txt")) or [
            f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
        ]
        if txt_files:
            txt_content = txt_files[0].read_text(encoding="utf-8")
            base_name = txt_files[0].stem
            layout = (getattr(job, "layout_mode", "standard") if job else "standard") or "standard"
            for fmt_ext in (".pdf", ".epub", ".docx"):
                if (out_dir / f"{base_name}{fmt_ext}").exists():
                    try:
                        export_text(txt_content, out_dir, fmt_ext.lstrip("."), base_name, layout=layout, cover_image=None)
                    except Exception:
                        pass
    return {"status": "deleted", "job_id": job_id}


@app.get("/api/voices")
async def list_voices():
    """Returns available TTS voices grouped by language."""
    return get_available_voices()


@app.get("/api/jobs")
async def all_jobs(include_tests: bool = False):
    """Returns all jobs (for session history). Hides test-generated jobs by default."""
    jobs = list_jobs()
    return [
        {
            "job_id": j.job_id,
            "file_name": j.file_name,
            "file_type": j.file_type,
            "status": j.status,
            "mode": j.mode,
            "progress": j.progress,
            "has_output": j.output_path is not None,
        }
        for j in jobs
        if include_tests or not is_test_job_filename(j.file_name)
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
async def clear_all_jobs():
    """Clean up all jobs and all temporary files inside temp/."""
    from backend.job_manager import _jobs, _active_tasks
    # Cancel all running tasks BEFORE deleting directories
    for active_id in list(_active_tasks.keys()):
        cancel_job(active_id)
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

    from backend.job_manager import _jobs
    from backend.database import db_delete_job
    from backend.queue_manager import remove_from_queue
    # Cancel active task & remove from queue BEFORE deleting files
    cancel_job(job_id)
    remove_from_queue(job_id)

    for d in [UPLOAD_DIR / job_id, OUTPUT_DIR / job_id]:
        if d.exists():
            shutil.rmtree(str(d), ignore_errors=True)

    _jobs.pop(job_id, None)
    POLISH_STATUS.pop(job_id, None)
    db_delete_job(job_id)
    return {"deleted": job_id}


# ---------------------------------------------------------------------------
# Text Review, Editing & Re-Export
# ---------------------------------------------------------------------------

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

    txt_files = list(out_dir.glob("*_translated_*.txt")) or [
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
            pages = list(parse_document(job.file_path, src_type))
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


@app.put("/api/jobs/{job_id}/text")
async def update_job_text(job_id: str, req: UpdateTextRequest):
    """Save user edits to the translated text and re-export current outputs."""
    _validate_job_id(job_id)
    job = get_job(job_id)
    out_dir = OUTPUT_DIR / job_id
    if not out_dir.exists():
        raise HTTPException(404, "Job output not found.")

    txt_files = list(out_dir.glob("*_translated_*.txt")) or [
        f for f in out_dir.glob("*.txt") if not f.name.endswith("_original.txt")
    ]
    if not txt_files:
        stem = Path(job.file_name).stem if job else job_id
        tgt_lang = (getattr(job, "target_lang", "greek") if job else "greek") or "greek"
        txt_file = out_dir / f"{stem}_translated_{tgt_lang}.txt"
    else:
        txt_file = txt_files[0]

    # Save edited text
    txt_file.write_text(req.translated_text, encoding="utf-8")
    base_name = txt_file.stem

    # Re-export active format if job has a text-exportable format
    fmt = ((job.output_format if job else "docx") or "docx").lower().lstrip(".")
    if fmt not in {"txt", "docx", "doc", "pdf", "epub"}:
        fmt = "docx"
    layout = (getattr(job, "layout_mode", "standard") if job else "standard") or "standard"
    export_path = export_text(req.translated_text, out_dir, fmt, base_name, layout=layout)
    if job:
        update_job(job_id, output_path=str(export_path), output_format=fmt)

    # Invalidate older non-txt exported files so download endpoint serves the new edited version
    for f in list(out_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in [".pdf", ".epub", ".docx"] and f.name != export_path.name:
            try:
                export_text(req.translated_text, out_dir, f.suffix.lower().lstrip("."), base_name, layout=layout)
            except Exception:
                pass

    return {"status": "saved", "job_id": job_id, "output_path": str(export_path)}


class SettingsRequest(BaseModel):
    gemini_api_key: Optional[str] = None


@app.get("/api/settings")
async def get_app_settings():
    from backend.settings_manager import get_setting
    key = get_setting("gemini_api_key", "")
    return {"gemini_api_key": key}


@app.post("/api/settings")
async def update_app_settings(req: SettingsRequest):
    from backend.settings_manager import save_setting
    from backend.ai_polisher import reset_model_cache, reset_gemini_quota_exhaustion
    from backend.comic_translator import reset_vision_model_cache
    if req.gemini_api_key is not None:
        save_setting("gemini_api_key", req.gemini_api_key.strip())
        reset_gemini_quota_exhaustion()
        reset_model_cache()
        reset_vision_model_cache()
    return {"status": "ok"}


@app.delete("/api/settings/{key}")
async def delete_app_setting(key: str):
    if key not in {"gemini_api_key"}:
        raise HTTPException(400, f"Unsupported setting key '{key}'.")
    from backend.settings_manager import delete_setting
    from backend.ai_polisher import reset_model_cache
    from backend.comic_translator import reset_vision_model_cache
    delete_setting(key)
    reset_model_cache()
    reset_vision_model_cache()
    return {"status": "deleted", "key": key}


# ---------------------------------------------------------------------------
# AI Polish via Gemini
# ---------------------------------------------------------------------------

@app.get("/api/gemini/status")
async def get_gemini_status():
    """Returns current Gemini daily quota exhaustion status and cooldown info."""
    from backend.ai_polisher import get_gemini_quota_info
    return get_gemini_quota_info()


@app.post("/api/gemini/reset-quota")
async def reset_gemini_quota_endpoint():
    """Manually resets the Gemini daily quota circuit breaker cooldown."""
    from backend.ai_polisher import reset_gemini_quota_exhaustion
    reset_gemini_quota_exhaustion()
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
        txt_files = list(out_dir.glob("*_translated_*.txt")) or list(out_dir.glob("*.txt"))
        if txt_files:
            text_to_polish = txt_files[0].read_text(encoding="utf-8")
        elif job and job.file_path and Path(job.file_path).exists():
            # DIRECT STANDALONE DOCUMENT POLISH: Extract text from original uploaded file
            from backend.parsers import parse_document
            pages = list(parse_document(job.file_path, job.file_type))
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
                from backend.parsers import parse_document
                pages = list(parse_document(job.file_path, job.file_type))
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

    update_polish_job_status(
        req.job_id,
        current=0,
        total=1,
        percent=0,
        status="running",
        step="Connecting to Gemini Flash AI...",
    )

    try:
        polished = await polish_text_with_gemini(
            text=text_to_polish,
            api_key=req.api_key,
            style=req.style,
            original_text=original_text,
            job_id=req.job_id,
            use_source_anchoring=effective_bilingual,
            progress_callback=on_progress,
        )
        total_p = get_polish_job_status(req.job_id).get("total", 1)
        update_polish_job_status(
            req.job_id,
            current=total_p,
            total=total_p,
            percent=100,
            status="done",
            step="AI Polishing complete!",
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
        raise HTTPException(500, f"AI Polishing failed: {str(e)}")

    # Update or create output files on disk
    stem = Path(job.file_name).stem if job else "polished_document"
    tgt_lang = (getattr(job, "target_lang", "greek") if job else "greek") or "greek"
    txt_file = out_dir / f"{stem}_translated_{tgt_lang}.txt"
    txt_file.write_text(polished, encoding="utf-8")
    base_name = txt_file.stem
    fmt = ((job.output_format if job else "docx") or "docx").lower().lstrip(".")
    if fmt not in {"txt", "docx", "doc", "pdf", "epub"}:
        fmt = "docx"
    layout = (req.layout_mode or (getattr(job, "layout_mode", "standard") if job else "standard") or "standard").lower()
    export_path = export_text(polished, out_dir, fmt, base_name, layout=layout)

    # Refresh other standard formats on-demand (without redundantly re-exporting fmt)
    for other_fmt in ("pdf", "epub", "docx"):
        if other_fmt == fmt:
            continue
        try:
            export_text(polished, out_dir, other_fmt, base_name, layout=layout)
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

    return {"status": "polished", "job_id": req.job_id, "polished_text": polished}


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


@app.delete("/api/glossary/{term}")
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
        return {"job_id": job_id, "file_type": job.file_type, "preview_text": preview_text}
    except Exception as e:
        raise HTTPException(500, f"Preview extraction failed: {e}")


@app.post("/api/detect-genre")
async def detect_genre(req: GenreDetectionRequest):
    """Auto-detects document genre, tone, recommended polish style and glossary category."""
    from backend.genre_detector import detect_genre_and_style
    input_text = req.sample_text or req.text or ""
    return detect_genre_and_style(input_text, req.file_type or "")


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
    from backend.queue_manager import retry_queue_item, get_queue_state, start_queue
    try:
        retry_queue_item(job_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))

    state_data = get_queue_state()
    if not state_data["paused"]:
        state_data = start_queue(_execute_queue_item)
    return state_data


@app.post("/api/queue/start")
async def start_batch_queue(req: Optional[QueueStartRequest] = None):
    """Starts or resumes serial execution of the Smart Batch Queue.
    Optionally syncs the user's latest Translation Settings onto all currently queued items.
    """
    from backend.queue_manager import start_queue, apply_settings_to_queued_items
    if req is not None:
        try:
            apply_settings_to_queued_items(
                source_lang=req.source_lang,
                target_lang=req.target_lang,
                output_format=req.output_format,
                layout_mode=req.layout_mode,
                reading_direction=req.reading_direction,
                ai_polish=req.ai_polish,
                api_key=req.api_key,
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
    import io
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
