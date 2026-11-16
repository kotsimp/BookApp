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


def clean_temp_storage(max_age_hours: int = 48, dry_run: bool = False) -> Dict[str, Any]:
    """
    Cleans up obsolete temporary files:
    1. temp/chunk_*.mp3 and subdirectories in temp/
    2. Orphaned files in temp/extracted_pages/
    3. Intermediate text/image files older than max_age_hours.

    Leaves final outputs in temp/outputs/<job_id> intact unless older than 7 days.
    """
    now = time.time()
    cutoff_temp = now - (max_age_hours * 3600)
    cutoff_outputs = now - (7 * 24 * 3600)  # 7 days retention for outputs

    files_deleted = 0
    bytes_freed = 0
    errors = []

    if not TEMP_DIR.exists():
        return {
            "files_deleted": 0,
            "bytes_freed_mb": 0.0,
            "dry_run": dry_run,
            "status": "temp_dir_empty",
        }

    # 1. Clean extracted pages, chunks, and temp work dirs
    subdirs_to_clean = ["extracted_pages", "chunks", "uploads"]
    for sub in subdirs_to_clean:
        target_dir = TEMP_DIR / sub
        if not target_dir.exists():
            continue
        for item in target_dir.iterdir():
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
                        size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                        if not dry_run:
                            shutil.rmtree(item, ignore_errors=True)
                        files_deleted += 1
                        bytes_freed += size
            except Exception as e:
                errors.append(f"{item.name}: {e}")

    # 2. Clean root temp loose files (e.g. temp/chunk_*.mp3)
    for item in TEMP_DIR.iterdir():
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

    # 3. Clean old outputs (> 7 days)
    outputs_dir = TEMP_DIR / "outputs"
    if outputs_dir.exists():
        for job_dir in outputs_dir.iterdir():
            if job_dir.is_dir():
                try:
                    if job_dir.stat().st_mtime < cutoff_outputs:
                        size = sum(f.stat().st_size for f in job_dir.rglob('*') if f.is_file())
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
    }
