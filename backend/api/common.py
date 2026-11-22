"""
backend/api/common.py - Paths, MIME types and job-id helpers shared by backend.main and the API routers.
"""

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
