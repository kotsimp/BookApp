"""
storage_cleaner.py - Storage & Temporary File Cleaner for BookApp.
Automatically purges temporary audio chunks, extracted pages, and old temporary files
older than a specified retention window (default: 48 hours), preserving final user outputs.
"""

import time
import shutil
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"


def _active_job_ids() -> set:
    active = set()
    try:
        from backend.job_manager import _jobs, _active_tasks
        for jid, j in list(_jobs.items()):
            if getattr(j, "status", "") in ("running", "queued") or jid in _active_tasks:
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


def clean_temp_storage(max_age_hours: int = 48, dry_run: bool = False) -> Dict[str, Any]:
    """
    Cleans up obsolete temporary files:
    1. temp/chunk_*.mp3 and subdirectories in temp/
    2. Orphaned files in temp/extracted_pages/, chunks/, uploads/, previews/
    3. Intermediate text/image files older than max_age_hours.

    Leaves active/running/queued jobs and final outputs (< 7 days) intact.
    """
    if max_age_hours is None or max_age_hours < 1:
        raise ValueError("max_age_hours must be at least 1 hour.")

    now = time.time()
    cutoff_temp = now - (max_age_hours * 3600)
    cutoff_outputs = now - (7 * 24 * 3600)  # 7 days retention for outputs
    active_ids = _active_job_ids()

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

    # 3. Clean old outputs (> 7 days), skipping active jobs
    outputs_dir = TEMP_DIR / "outputs"
    if outputs_dir.exists():
        for job_dir in list(outputs_dir.iterdir()):
            if job_dir.is_dir() and job_dir.name not in active_ids:
                try:
                    if job_dir.stat().st_mtime < cutoff_outputs:
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
