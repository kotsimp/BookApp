"""
Main FastAPI application for the Document Translator & Audiobook Generator.
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.job_manager import create_job, get_job, update_job, list_jobs, cleanup_old_jobs
from backend.parsers import count_pages, parse_document
from backend.translator import translate_document
from backend.tts_engine import generate_audiobook, get_available_voices
from backend.exporter import export_text
# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DocTranslate & AudioBook",
    description="Translate documents and generate audiobooks powered by neural AI",
    version="1.0.0",
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
    output_format: str = "txt"  # txt, docx, pdf, epub
    layout_mode: str = "standard"  # 'standard' or 'literature'


class AudiobookRequest(BaseModel):
    job_id: str
    language: str      # 'english' or 'greek' — language of the audio output
    voice_name: str    # e.g. 'Athina (Female)'
    use_translated: bool = False  # if True, use the translated text from a prior translation job
    narration_style: str = "literature"  # 'literature' (natural book flow) or 'standard'
    rate: Optional[str] = None           # optional explicit speed e.g. '-18%', '-10%', '+0%'
    ai_polish: bool = False              # if True, polish script with Gemini before TTS
    api_key: Optional[str] = None        # optional Gemini API key override


class UpdateTextRequest(BaseModel):
    translated_text: str


class PolishRequest(BaseModel):
    job_id: str
    text: Optional[str] = None
    style: str = "formal"
    api_key: Optional[str] = None
    layout_mode: Optional[str] = None


class GlossaryTermRequest(BaseModel):
    source: str
    target: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".epub", ".doc"}

def _get_file_type(filename: str) -> Optional[str]:
    ext = Path(filename).suffix.lower()
    mapping = {".pdf": "pdf", ".docx": "docx", ".epub": "epub"}
    return mapping.get(ext)


def _job_output_dir(job_id: str) -> Path:
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
    ext = Path(file.filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Supported: PDF, DOCX, EPUB.")

    if ext == ".doc":
        raise HTTPException(400, (
            "Legacy .doc format is not supported. "
            "Please save/convert your file as .docx using Microsoft Word or LibreOffice."
        ))

    file_type = _get_file_type(file.filename)

    # Save upload
    job_dir = UPLOAD_DIR / "tmp"
    job_dir.mkdir(exist_ok=True)
    tmp_path = job_dir / file.filename

    async with aiofiles.open(tmp_path, "wb") as out:
        content = await file.read()
        await out.write(content)

    # Create job
    job = create_job(
        file_path=str(tmp_path),
        file_name=file.filename,
        file_type=file_type,
    )

    # Move file to job-specific dir
    job_upload_dir = UPLOAD_DIR / job.job_id
    job_upload_dir.mkdir(exist_ok=True)
    final_path = job_upload_dir / file.filename
    shutil.move(str(tmp_path), str(final_path))
    update_job(job.job_id, file_path=str(final_path))

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

    # Count pages and detect primary language for metadata
    try:
        page_count = count_pages(str(final_path), file_type)
    except Exception:
        page_count = 0

    detected_language = _detect_document_language(str(final_path), file_type)

    logger.info(
        f"Uploaded: {file.filename} → job_id={job.job_id}, pages≈{page_count}, lang={detected_language}"
    )

    return {
        "job_id": job.job_id,
        "file_name": file.filename,
        "file_type": file_type,
        "estimated_pages": page_count,
        "detected_language": detected_language,
    }


@app.post("/api/translate")
async def start_translation(req: TranslateRequest, background_tasks: BackgroundTasks):
    """Start a translation job in the background."""
    job = get_job(req.job_id)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found.")

    if job.status == "running":
        raise HTTPException(409, "A task is already running for this job.")

    if req.source_lang == req.target_lang:
        raise HTTPException(400, "Source and target languages must be different.")

    output_dir = _job_output_dir(req.job_id)
    stem = Path(job.file_name).stem
    output_path = str(output_dir / f"{stem}_translated_{req.target_lang}.txt")

    output_format = getattr(req, "output_format", "txt") or "txt"
    layout_mode = getattr(req, "layout_mode", "standard") or "standard"
    update_job(req.job_id, mode="translate", status="running", output_format=output_format, layout_mode=layout_mode)

    background_tasks.add_task(
        _run_translation,
        req.job_id,
        job.file_path,
        job.file_type,
        req.source_lang,
        req.target_lang,
        output_path,
    )

    return {"job_id": req.job_id, "status": "started", "output_path": output_path}


from backend.format_preserver import translate_docx_in_place, translate_epub_in_place


async def _run_translation(job_id, file_path, file_type, source_lang, target_lang, output_path):
    try:
        job = get_job(job_id)
        fmt = getattr(job, "output_format", "txt") or "txt"
        fmt = fmt.lower()
        layout = getattr(job, "layout_mode", "standard") or "standard"
        out_dir = Path(output_path).parent
        stem = Path(file_path).stem
        base_name = f"{stem}_translated_{target_lang}"

        # 1. DOCX In-Place Format Preservation (styles, fonts, sizes, tables, bold/italic)
        if file_type == "docx" and fmt in ("docx", "doc"):
            final_docx_path = out_dir / f"{base_name}.docx"

            def docx_prog(done, total, msg):
                pct = int((done / max(total, 1)) * 92)
                update_job(job_id, current_step=msg, progress=pct, done_chunks=done, total_chunks=total)

            translated_txt = await translate_docx_in_place(
                file_path, str(final_docx_path), source_lang, target_lang, docx_prog
            )
            # Save plain text version for audiobooks / fallback
            Path(output_path).write_text(translated_txt, encoding="utf-8")
            final_path = final_docx_path

        # 2. EPUB In-Place Format Preservation (HTML tags, CSS, headings, styles, images)
        elif file_type == "epub" and fmt == "epub":
            final_epub_path = out_dir / f"{base_name}.epub"

            def epub_prog(done, total, msg):
                pct = int((done / max(total, 1)) * 92)
                update_job(job_id, current_step=msg, progress=pct, done_chunks=done, total_chunks=total)

            translated_txt = await translate_epub_in_place(
                file_path, str(final_epub_path), source_lang, target_lang, epub_prog
            )
            Path(output_path).write_text(translated_txt, encoding="utf-8")
            final_path = final_epub_path

        # 3. Standard parsing + rich styled export (for PDF or cross-format exports)
        else:
            await translate_document(
                job_id=job_id,
                file_path=file_path,
                file_type=file_type,
                source_lang=source_lang,
                target_lang=target_lang,
                output_path=output_path,
            )
            txt_content = Path(output_path).read_text(encoding="utf-8")
            update_job(job_id, current_step=f"Exporting to {fmt.upper()}...", progress=95)
            final_path = export_text(txt_content, out_dir, fmt, base_name, layout=layout)

        # Mark job complete
        update_job(job_id,
            status="done",
            progress=100,
            current_step=f"Exported {fmt.upper()} (Formatting Preserved)",
            output_path=str(final_path),
            output_format=fmt,
            done_chunks=1,
            total_chunks=1,
        )
    except Exception as e:
        logger.error(f"Translation/export error [{job_id}]: {e}", exc_info=True)
        update_job(job_id, status="error", error=str(e))


@app.post("/api/audiobook")
async def start_audiobook(req: AudiobookRequest, background_tasks: BackgroundTasks):
    """Start an audiobook generation job in the background."""
    job = get_job(req.job_id)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found.")

    if job.status == "running":
        raise HTTPException(409, "A task is already running for this job.")

    output_dir = _job_output_dir(req.job_id)
    stem = Path(job.file_name).stem
    output_path = str(output_dir / f"{stem}_audiobook_{req.language}.mp3")

    # Check for a translated text file to use
    translated_path = None
    if req.use_translated:
        # Look for any translated .txt in output dir
        txt_files = list(output_dir.glob("*_translated_*.txt"))
        if txt_files:
            translated_path = str(txt_files[0])

    if req.ai_polish:
        from backend.settings_manager import get_setting
        resolved_key = (req.api_key or "").strip() or (get_setting("gemini_api_key", "") or "").strip()
        if not resolved_key:
            raise HTTPException(400, "Gemini API key is required for AI Audiobook Polish. Please save your key in AI Polish first.")

    update_job(req.job_id, mode="audiobook", status="running")

    background_tasks.add_task(
        _run_audiobook,
        req.job_id,
        job.file_path,
        job.file_type,
        req.language,
        req.voice_name,
        output_path,
        translated_path,
        req.narration_style,
        req.rate,
        req.ai_polish,
        req.api_key,
    )

    return {"job_id": req.job_id, "status": "started", "output_path": output_path}


async def _run_audiobook(
    job_id, file_path, file_type, language, voice_name, output_path, translated_path,
    narration_style="literature", rate=None, ai_polish=False, api_key=None
):
    try:
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
            ai_polish=ai_polish,
            api_key=api_key,
        )
    except Exception as e:
        logger.error(f"Audiobook error [{job_id}]: {e}", exc_info=True)
        update_job(job_id, status="error", error=str(e))


@app.get("/api/progress/{job_id}")
async def progress_stream(job_id: str):
    """SSE endpoint for real-time job progress."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")

    async def event_generator():
        import asyncio
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        job.subscribers.append(q)

        # Send current state immediately
        state = {
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "total_chunks": job.total_chunks,
            "done_chunks": job.done_chunks,
            "error": job.error,
            "output_path": job.output_path,
        }
        yield f"data: {json.dumps(state)}\n\n"

        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(data)}\n\n"

                    # Stop streaming when terminal state reached
                    if data.get("status") in ("done", "error"):
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
    """Get current job status (non-streaming)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    return {
        "job_id": job.job_id,
        "file_name": job.file_name,
        "status": job.status,
        "mode": job.mode,
        "progress": job.progress,
        "current_step": job.current_step,
        "total_chunks": job.total_chunks,
        "done_chunks": job.done_chunks,
        "error": job.error,
        "has_output": job.output_path is not None,
    }


MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".epub": "application/epub+zip",
    ".txt": "text/plain; charset=utf-8",
    ".mp3": "audio/mpeg",
}


@app.api_route("/api/download/{job_id}", methods=["GET", "HEAD"])
async def download_output(job_id: str, format: Optional[str] = None, layout: Optional[str] = None):
    """
    Download the output file for a completed job.
    If 'format' is requested (e.g. ?format=pdf), dynamically converts the translated
    content to the requested format on-demand if it hasn't been exported yet or if
    a different 'layout' ('standard' vs 'literature') is requested.
    """
    job = get_job(job_id)
    out_dir = OUTPUT_DIR / job_id
    out_path = None
    active_layout = (layout or (getattr(job, "layout_mode", "standard") if job else "standard") or "standard").lower()
    layout_changed = bool(layout and job and layout.lower() != (getattr(job, "layout_mode", "standard") or "standard").lower())

    if format:
        fmt = format.lower().lstrip(".")
        # If cover image is not yet cached in out_dir, check original uploaded file
        cov_file = out_dir / "cover_image.jpg"
        if not cov_file.exists() and job and job.file_path and Path(job.file_path).exists():
            try:
                from backend.exporter import extract_cover_image
                c_bytes = extract_cover_image(job.file_path)
                if c_bytes:
                    cov_file.write_bytes(c_bytes)
            except Exception:
                pass

        # 1. Check if a file in the requested format already exists (unless layout changed)
        if out_dir.exists() and not layout_changed:
            matching = [f for f in out_dir.iterdir() if f.is_file() and f.suffix.lower() == f".{fmt}"]
            if matching:
                matching.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                out_path = matching[0]

        # 2. If not (or if layout changed), generate it on-demand from the translated text
        if not out_path and out_dir.exists():
            txt_files = list(out_dir.glob("*_translated_*.txt")) or list(out_dir.glob("*.txt"))
            if txt_files:
                txt_file = txt_files[0]
                txt_content = txt_file.read_text(encoding="utf-8")
                base_name = txt_file.stem
                out_path = export_text(txt_content, out_dir, fmt, base_name, layout=active_layout)
                if job:
                    job.output_path = str(out_path)
                    job.output_format = fmt
                    job.layout_mode = active_layout

    # Fallback to existing output_path or newest file
    if not out_path:
        if job and job.output_path:
            p = Path(job.output_path)
            if p.exists():
                out_path = p

        if not out_path and out_dir.exists():
            files = [
                f for f in out_dir.iterdir()
                if f.is_file() and f.suffix.lower() in [".docx", ".pdf", ".epub", ".mp3", ".txt"]
            ]
            if files:
                preferred = [f for f in files if f.suffix.lower() in [".docx", ".pdf", ".epub", ".mp3"]]
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
    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty image file.")

    # Convert/validate to JPEG using pymupdf or write directly
    try:
        import pymupdf
        pix = pymupdf.Pixmap(content)
        # If pixmap has alpha or is CMYK, convert to RGB
        if pix.alpha or pix.n > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        jpg_bytes = pix.tobytes("jpeg")
    except Exception:
        jpg_bytes = content

    cov_p = out_dir / "cover_image.jpg"
    cov_p.write_bytes(jpg_bytes)

    # Invalidate older exported PDF/EPUB/DOCX so re-download reflects new cover
    job = get_job(job_id)
    txt_files = list(out_dir.glob("*_translated_*.txt")) or list(out_dir.glob("*.txt"))
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
    """Remove the custom or extracted cover image for a book."""
    out_dir = OUTPUT_DIR / job_id
    cov_p = out_dir / "cover_image.jpg"
    if cov_p.exists():
        try:
            cov_p.unlink()
        except Exception:
            pass
    return {"status": "deleted", "job_id": job_id}


@app.get("/api/voices")
async def list_voices():
    """Returns available TTS voices grouped by language."""
    return get_available_voices()


@app.get("/api/jobs")
async def all_jobs():
    """Returns all jobs (for session history)."""
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
    ]

@app.get("/api/debug/extract/{job_id}")
async def debug_extract(job_id: str, max_chars: int = 500):
    """
    Returns the raw extracted text (first max_chars chars per page) for debugging.
    Use this to verify that the PDF/DOCX has readable text before translating.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")

    from backend.parsers import parse_document
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
    from backend.job_manager import _jobs
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
    return {"status": "cleared", "count": 0}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Clean up a job and its files."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")

    # Remove files
    for d in [UPLOAD_DIR / job_id, OUTPUT_DIR / job_id]:
        if d.exists():
            shutil.rmtree(str(d), ignore_errors=True)

    from backend.job_manager import _jobs
    _jobs.pop(job_id, None)
    return {"deleted": job_id}


# ---------------------------------------------------------------------------
# Text Review, Editing & Re-Export
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}/text")
async def get_job_text(job_id: str):
    """Retrieve original and translated text for a job."""
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
    job = get_job(job_id)
    out_dir = OUTPUT_DIR / job_id
    if not out_dir.exists():
        raise HTTPException(404, "Job output not found.")

    txt_files = list(out_dir.glob("*_translated_*.txt")) or list(out_dir.glob("*.txt"))
    if not txt_files:
        stem = Path(job.file_name).stem if job else job_id
        txt_file = out_dir / f"{stem}_translated_greek.txt"
    else:
        txt_file = txt_files[0]

    # Save edited text
    txt_file.write_text(req.translated_text, encoding="utf-8")
    base_name = txt_file.stem

    # Re-export active format if job has one
    fmt = (job.output_format if job else "docx") or "docx"
    layout = (getattr(job, "layout_mode", "standard") if job else "standard") or "standard"
    export_path = export_text(req.translated_text, out_dir, fmt, base_name, layout=layout)
    if job:
        job.output_path = str(export_path)

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
    if req.gemini_api_key is not None:
        save_setting("gemini_api_key", req.gemini_api_key.strip())
    return {"status": "ok"}


@app.delete("/api/settings/{key}")
async def delete_app_setting(key: str):
    if key not in {"gemini_api_key"}:
        raise HTTPException(400, f"Unsupported setting key '{key}'.")
    from backend.settings_manager import delete_setting
    delete_setting(key)
    return {"status": "deleted", "key": key}


# ---------------------------------------------------------------------------
# AI Polish via Gemini
# ---------------------------------------------------------------------------

POLISH_STATUS: dict[str, dict] = {}


@app.get("/api/polish/status/{job_id}")
async def get_polish_status(job_id: str):
    """Returns current real-time progress of AI Polish for a given job."""
    return POLISH_STATUS.get(job_id, {"current": 0, "total": 1, "percent": 0, "status": "idle"})


@app.post("/api/polish")
async def polish_translation(req: PolishRequest):
    """Polish and proofread document or text directly using Gemini API (with or without prior translation)."""
    if not req.job_id:
        out_dir_tmp = OUTPUT_DIR / "direct"
        out_dir_tmp.mkdir(parents=True, exist_ok=True)
        placeholder_file = out_dir_tmp / "direct_text.txt"
        if not placeholder_file.exists():
            placeholder_file.write_text("", encoding="utf-8")
        job = create_job(str(placeholder_file), "direct_text.txt", "txt")
        job.mode = "translate"
        req.job_id = job.job_id
    else:
        job = get_job(req.job_id)

    out_dir = OUTPUT_DIR / req.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    text_to_polish = req.text

    if req.api_key and req.api_key.strip():
        from backend.settings_manager import save_setting
        save_setting("gemini_api_key", req.api_key.strip())

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

    def on_progress(current: int, total: int):
        pct = int((current / max(1, total)) * 100)
        POLISH_STATUS[req.job_id] = {
            "current": current,
            "total": total,
            "percent": pct,
            "status": "running",
            "step": f"Polishing page {current} of {total}...",
        }

    POLISH_STATUS[req.job_id] = {
        "current": 0,
        "total": 1,
        "percent": 0,
        "status": "running",
        "step": "Connecting to Gemini Flash AI...",
    }

    try:
        polished = await polish_text_with_gemini(
            text=text_to_polish,
            api_key=req.api_key,
            style=req.style,
            progress_callback=on_progress,
        )
        total_p = POLISH_STATUS.get(req.job_id, {}).get("total", 1)
        POLISH_STATUS[req.job_id] = {
            "current": total_p,
            "total": total_p,
            "percent": 100,
            "status": "done",
            "step": "AI Polishing complete!",
        }
    except Exception as e:
        POLISH_STATUS[req.job_id] = {
            "current": 0,
            "total": 1,
            "percent": 0,
            "status": "error",
            "step": str(e),
        }
        logger.error(f"AI Polishing failed: {e}", exc_info=True)
        raise HTTPException(500, f"AI Polishing failed: {str(e)}")

    # Update or create output files on disk
    stem = Path(job.file_name).stem if job else "polished_document"
    txt_file = out_dir / f"{stem}_translated_greek.txt"
    txt_file.write_text(polished, encoding="utf-8")
    base_name = txt_file.stem
    fmt = (job.output_format if job else "docx") or "docx"
    layout = (req.layout_mode or (getattr(job, "layout_mode", "standard") if job else "standard") or "standard").lower()
    export_path = export_text(polished, out_dir, fmt, base_name, layout=layout)

    # Refresh other standard formats on-demand
    for ext in [".pdf", ".epub", ".docx"]:
        try:
            export_text(polished, out_dir, ext.lstrip("."), base_name, layout=layout)
        except Exception:
            pass

    if job:
        job.status = "done"
        job.progress = 100
        job.output_path = str(export_path)
        job.output_format = fmt
        job.layout_mode = layout
        job.current_step = "AI Polishing complete!"

    return {"status": "polished", "job_id": req.job_id, "polished_text": polished}


# ---------------------------------------------------------------------------
# Glossary Management
# ---------------------------------------------------------------------------

@app.get("/api/glossary")
async def get_glossary_terms():
    """Retrieve all custom glossary mappings."""
    from backend.glossary import load_glossary
    return load_glossary()


@app.post("/api/glossary")
async def add_glossary_term(req: GlossaryTermRequest):
    """Add or update a glossary term."""
    from backend.glossary import set_term
    updated = set_term(req.source, req.target)
    return {"status": "saved", "glossary": updated}


@app.delete("/api/glossary/{term}")
async def remove_glossary_term(term: str):
    """Delete a glossary term."""
    from backend.glossary import delete_term
    updated = delete_term(term)
    return {"status": "deleted", "glossary": updated}


# ---------------------------------------------------------------------------
# Serve Frontend
# ---------------------------------------------------------------------------

FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    logger.info("DocTranslate & AudioBook Generator started.")
    cleanup_old_jobs()
