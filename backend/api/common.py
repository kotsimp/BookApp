"""
backend/api/common.py - Paths, MIME types and job-id helpers shared by backend.main and the API routers.
"""

import re
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from backend.job_manager import is_valid_job_id

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

UPLOAD_DIR = TEMP_DIR / "uploads"
OUTPUT_DIR = TEMP_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".epub": "application/epub+zip",
    ".txt": "text/plain; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".m4b": "audio/mp4",
    ".cbz": "application/vnd.comicbook+zip",
    ".cbr": "application/vnd.comicbook-rar",
}


OUTPUT_FORMATS = {"txt", "docx", "doc", "pdf", "epub", "cbz", "cbr"}
LAYOUT_MODES = {"standard", "literature", "poetry", "comic", "graphic_novel"}
READING_DIRECTIONS = {"ltr", "rtl"}
QUOTA_BEHAVIORS = {"wait", "fallback"}
_LANGUAGE_RE = re.compile(r"[a-z][a-z-]{0,19}")


def _validate_language(value: Optional[str], field: str = "language") -> str:
    """Languages become part of output file names, so only plain words are accepted."""
    lang = (value or "").strip().lower()
    if not _LANGUAGE_RE.fullmatch(lang):
        raise HTTPException(400, f"Invalid {field}.")
    return lang


def _validate_choice(value: Optional[str], allowed: set, field: str) -> Optional[str]:
    """Normalised value from `allowed`; None when not provided."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v not in allowed:
        raise HTTPException(400, f"Unsupported {field}.")
    return v


def _validate_job_id(job_id: Optional[str]) -> str:
    """Validates a single-segment job_id to prevent path traversal."""
    if not is_valid_job_id(job_id):
        raise HTTPException(400, "Invalid job_id.")
    return job_id


def _job_output_dir(job_id: str) -> Path:
    _validate_job_id(job_id)
    d = OUTPUT_DIR / job_id
    d.mkdir(exist_ok=True)
    return d


def purge_job(job_id: str) -> None:
    """Deletes a job completely: stops it, takes it out of the batch queue, removes its files and its record."""
    import shutil
    from backend.job_manager import cancel_job, _jobs
    from backend.queue_manager import remove_from_queue
    from backend.database import db_delete_job
    from backend.ai_polisher import POLISH_STATUS
    cancel_job(job_id)
    remove_from_queue(job_id)
    for d in (UPLOAD_DIR / job_id, OUTPUT_DIR / job_id):
        if d.exists():
            shutil.rmtree(str(d), ignore_errors=True)
    _jobs.pop(job_id, None)
    POLISH_STATUS.pop(job_id, None)
    db_delete_job(job_id)
