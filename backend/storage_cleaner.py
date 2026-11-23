"""
storage_cleaner.py - Storage & Temporary File Cleaner for BookApp.
Automatically purges temporary audio chunks, extracted pages, and old temporary files
older than a specified retention window (default: 48 hours), preserving final user outputs.
"""

import time
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"


def _active_job_ids() -> set:
    active = set()
    try:
        from backend.job_manager import _jobs, _active_tasks
        for jid, j in list(_jobs.items()):
            if getattr(j, "status", "") in ("running", "queued", "idle") or jid in _active_tasks:
                active.add(jid)
    except Exception:
        pass
    try:
        from backend.queue_manager import _queue_items
        for it in list(_queue_items):
            if it.status in ("running", "queued"):
                active.add(it.job_id)
    except Exception:
        pass
    return active


def _safe_dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


# Files that make an output folder somebody's work (such folders are restored into Session History)
_USER_FILE_SUFFIXES = {".pdf", ".docx", ".doc", ".epub", ".cbz", ".cbr", ".zip", ".txt", ".mp3", ".m4b"}


def _holds_user_files(path: Path) -> bool:
    return any(f.is_file() and f.suffix.lower() in _USER_FILE_SUFFIXES for f in path.rglob("*"))


def _known_job_ids() -> Optional[set]:
    """Job ids in the database, or None when it cannot be read (then no job folder is removed)."""
    try:
        from backend.database import db_get_all_job_ids
        return db_get_all_job_ids()
    except Exception as e:
        logger.warning(f"Job list unavailable ({e}); job folders are left untouched.")
        return None


def clean_temp_storage(max_age_hours: int = 48, dry_run: bool = False) -> Dict[str, Any]:
    """
    Cleans up obsolete temporary files:
    1. temp/chunk_*.mp3 and subdirectories in temp/
    2. Orphaned files in temp/extracted_pages/, chunks/, uploads/, previews/
    3. Intermediate text/image files older than max_age_hours.

    Never removes a job that is in Session History, or an output folder holding user files, whatever its age.
    """
    if max_age_hours is None or max_age_hours < 1:
        raise ValueError("max_age_hours must be at least 1 hour.")

    now = time.time()
    cutoff_temp = now - (max_age_hours * 3600)
    cutoff_outputs = now - (7 * 24 * 3600)  # grace period for empty orphan output folders
    active_ids = _active_job_ids()
    known_ids = _known_job_ids()

    files_deleted = 0
    bytes_freed = 0
    errors = []

    if not TEMP_DIR.exists():
        return {
            "files_deleted": 0,
            "bytes_freed_mb": 0.0,
            "dry_run": dry_run,
            "errors": [],
            "status": "temp_dir_empty",
        }

    # 1. Clean extracted pages, chunks, uploads, and voice previews
    subdirs_to_clean = ["extracted_pages", "chunks", "uploads", "previews"]
    for sub in subdirs_to_clean:
        target_dir = TEMP_DIR / sub
        if not target_dir.exists():
            continue
        for item in list(target_dir.iterdir()):
            if item.name in active_ids or (sub == "uploads" and item.name == "tmp"):
                continue
            if sub == "uploads" and item.is_dir():
                # only true orphans: no job record and no outputs
                if known_ids is None or item.name in known_ids or (TEMP_DIR / "outputs" / item.name).is_dir():
                    continue
                if _holds_user_files(item):
                    continue  # a book, even without a record (database lost or replaced)
            try:
                mtime = item.stat().st_mtime
                if mtime < cutoff_temp:
                    if item.is_file():
                        size = item.stat().st_size
                        if not dry_run:
                            item.unlink(missing_ok=True)
                        files_deleted += 1
                        bytes_freed += size
                    elif item.is_dir():
                        size = _safe_dir_size(item)
                        if not dry_run:
                            shutil.rmtree(item, ignore_errors=True)
                        files_deleted += 1
                        bytes_freed += size
            except Exception as e:
                errors.append(f"{item.name}: {e}")

    # 1b. Clean stale abandoned partial uploads inside temp/uploads/tmp
    tmp_upload_dir = TEMP_DIR / "uploads" / "tmp"
    if tmp_upload_dir.exists() and tmp_upload_dir.is_dir():
        for f in list(tmp_upload_dir.iterdir()):
            if f.is_file():
                try:
                    if f.stat().st_mtime < cutoff_temp:
                        size = f.stat().st_size
                        if not dry_run:
                            f.unlink(missing_ok=True)
                        files_deleted += 1
                        bytes_freed += size
                except Exception as e:
                    errors.append(f"tmp/{f.name}: {e}")

    # 2. Clean root temp loose files (e.g. temp/chunk_*.mp3)
    for item in list(TEMP_DIR.iterdir()):
        if item.is_file() and item.name.startswith("chunk_"):
            try:
                if item.stat().st_mtime < cutoff_temp:
                    size = item.stat().st_size
                    if not dry_run:
                        item.unlink(missing_ok=True)
                    files_deleted += 1
                    bytes_freed += size
            except Exception as e:
                errors.append(f"{item.name}: {e}")

    # 3. Clean orphan output folders (> 7 days) that hold no user files
    outputs_dir = TEMP_DIR / "outputs"
    if outputs_dir.exists() and known_ids is not None:
        for job_dir in list(outputs_dir.iterdir()):
            if job_dir.is_dir() and job_dir.name not in active_ids and job_dir.name not in known_ids:
                try:
                    if job_dir.stat().st_mtime < cutoff_outputs and not _holds_user_files(job_dir):
                        size = _safe_dir_size(job_dir)
                        if not dry_run:
                            shutil.rmtree(job_dir, ignore_errors=True)
                        files_deleted += 1
                        bytes_freed += size
                except Exception as e:
                    errors.append(f"{job_dir.name}: {e}")

    freed_mb = round(bytes_freed / (1024 * 1024), 2)
    logger.info(f"Storage cleanup completed: {files_deleted} files/dirs removed, {freed_mb} MB freed.")
    return {
        "files_deleted": files_deleted,
        "bytes_freed_mb": freed_mb,
        "dry_run": dry_run,
        "errors": errors[:5],
        "status": "ok",
    }
