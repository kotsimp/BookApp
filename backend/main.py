"""
Main FastAPI application for the Document Translator & Audiobook Generator.
"""

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.job_manager import create_job, get_job, update_job, list_jobs, cleanup_old_jobs
from backend.parsers import count_pages
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


class AudiobookRequest(BaseModel):
    job_id: str
    language: str      # 'english' or 'greek' — language of the audio output
    voice_name: str    # e.g. 'Athina (Female)'
    use_translated: bool = False  # if True, use the translated text from a prior translation job


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

    # Count pages for metadata
    try:
        page_count = count_pages(str(final_path), file_type)
    except Exception:
        page_count = 0

    logger.info(f"Uploaded: {file.filename} → job_id={job.job_id}, pages≈{page_count}")

    return {
        "job_id": job.job_id,
        "file_name": file.filename,
        "file_type": file_type,
        "estimated_pages": page_count,
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

    update_job(req.job_id, mode="translate", status="running")

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


async def _run_translation(job_id, file_path, file_type, source_lang, target_lang, output_path):
    try:
        # Step 1: Translate to temporary txt file
        await translate_document(
            job_id=job_id,
            file_path=file_path,
            file_type=file_type,
            source_lang=source_lang,
            target_lang=target_lang,
            output_path=output_path,
        )
        # Read translated content
        txt_content = Path(output_path).read_text(encoding="utf-8")
        # Determine requested format (default txt) from job metadata
        job = get_job(job_id)
        fmt = getattr(job, "output_format", "txt") or "txt"
        # Step 2: Export to final format
        update_job(job_id, current_step=f"Exporting to {fmt.upper()}...", progress=95)
        out_dir = Path(output_path).parent
        base_name = Path(output_path).stem.replace(f"_translated_{target_lang}", "_translated")
        final_path = export_text(txt_content, out_dir, fmt, base_name)
        # Step 3: Mark job done
        update_job(job_id,
            status="done",
            progress=100,
            current_step=f"Exported {fmt.upper()}",
            output_path=str(final_path),
            output_format=fmt,
            done_chunks=0,
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
    )

    return {"job_id": req.job_id, "status": "started", "output_path": output_path}


async def _run_audiobook(job_id, file_path, file_type, language, voice_name, output_path, translated_path):
    try:
        await generate_audiobook(
            job_id=job_id,
            file_path=file_path,
            file_type=file_type,
            language=language,
            voice_name=voice_name,
            output_path=output_path,
            translated_text_path=translated_path,
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


@app.get("/api/download/{job_id}")
async def download_output(job_id: str):
    """Download the output file for a completed job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    if job.status != "done" or not job.output_path:
        raise HTTPException(400, "Job is not complete or has no output.")

    out_path = Path(job.output_path)
    if not out_path.exists():
        raise HTTPException(404, "Output file not found.")

    media_type = "audio/mpeg" if out_path.suffix == ".mp3" else "text/plain; charset=utf-8"
    return FileResponse(
        path=str(out_path),
        media_type=media_type,
        filename=out_path.name,
    )


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
