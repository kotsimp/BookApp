"""
Job Manager - tracks in-memory job state for all translation and audiobook tasks.
"""

import uuid
import time
import json
import asyncio
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: str
    file_path: str
    file_name: str
    file_type: str          # 'pdf', 'docx', 'epub', 'cbz'
    status: str             # 'idle', 'running', 'done', 'error', 'cancelled'
    mode: str               # 'translate' or 'audiobook'
    progress: int           # 0-100
    current_step: str       # human-readable status message
    total_chunks: int       # total processing units (pages or AI batches)
    done_chunks: int        # completed units
    created_at: float
    updated_at: float
    # Optional / nullable fields (must have defaults)
    output_path: Optional[str] = None
    output_format: Optional[str] = None  # txt, docx, pdf, epub, cbz, cbr
    layout_mode: str = "standard"        # 'standard', 'literature', 'comic'
    error: Optional[str] = None
    source_lang: str = "english"
    target_lang: str = "greek"
    ai_polish: bool = False
    reading_direction: str = "ltr"
    total_pages: int = 0
    done_pages: int = 0
    quota_behavior: str = "wait"  # 'wait' (pause at checkpoint for quota reset) or 'fallback' (auto-fallback to free engine)
    # SSE subscriber queues (list of asyncio.Queue)
    subscribers: list       = field(default_factory=list)


_WINDOWS_RESERVED_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def is_valid_job_id(job_id: Optional[str]) -> bool:
    """Returns True if job_id is a safe single-segment identifier with no path traversal or reserved names."""
    if not isinstance(job_id, str) or not job_id.strip():
        return False
    jid = job_id.strip()
    if "/" in jid or "\\" in jid or ".." in jid or "\x00" in jid:
        return False
    if jid in (".", "..") or jid.startswith(".") or ":" in jid:
        return False
    if jid.upper() in _WINDOWS_RESERVED_DEVICE_NAMES:
        return False
    return True


def _heal_file_path(job_id: str, file_path: str, file_name: str) -> str:
    """Auto-heals stale temp/uploads/tmp/... paths by checking temp/uploads/<job_id>/."""
    if not is_valid_job_id(job_id):
        return file_path
    if file_path and Path(file_path).exists():
        return file_path
    base_up = Path(__file__).resolve().parent.parent / "temp" / "uploads" / job_id
    if base_up.exists():
        if file_name and (base_up / file_name).is_file():
            return str(base_up / file_name)
        ufiles = [f for f in base_up.iterdir() if f.is_file()]
        if ufiles:
            return str(ufiles[0])
    return file_path


def _job_to_db_dict(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "file_path": job.file_path,
        "file_name": job.file_name,
        "file_type": job.file_type,
        "status": job.status,
        "mode": job.mode,
        "progress": job.progress,
        "current_step": job.current_step,
        "total_chunks": job.total_chunks,
        "done_chunks": job.done_chunks,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "output_path": job.output_path,
        "output_format": job.output_format,
        "layout_mode": job.layout_mode,
        "error": job.error,
        "metadata": {
            "source_lang": job.source_lang,
            "target_lang": job.target_lang,
            "ai_polish": bool(job.ai_polish),
            "reading_direction": job.reading_direction,
            "total_pages": int(job.total_pages or 0),
            "done_pages": int(job.done_pages or 0),
            "quota_behavior": getattr(job, "quota_behavior", "wait") or "wait",
        },
    }


def _job_from_db_row(row: dict) -> Job:
    meta = {}
    raw_meta = row.get("metadata_json")
    if raw_meta:
        try:
            parsed = json.loads(raw_meta)
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            pass

    jid = row["job_id"]
    orig_fp = row["file_path"] or ""
    fname = row["file_name"] or ""
    healed_fp = _heal_file_path(jid, orig_fp, fname)

    job = Job(
        job_id=jid,
        file_path=healed_fp,
        file_name=fname,
        file_type=row["file_type"] or "",
        status=row["status"] or "idle",
        mode=row["mode"] or "",
        progress=row["progress"] or 0,
        current_step=row["current_step"] or "",
        total_chunks=row["total_chunks"] or 0,
        done_chunks=row["done_chunks"] or 0,
        created_at=row["created_at"] or time.time(),
        updated_at=row["updated_at"] or time.time(),
        output_path=row["output_path"],
        output_format=row["output_format"],
        layout_mode=row["layout_mode"] or "standard",
        error=row["error"],
        source_lang=meta.get("source_lang") or "english",
        target_lang=meta.get("target_lang") or "greek",
        ai_polish=bool(meta.get("ai_polish", False)),
        reading_direction=meta.get("reading_direction") or "ltr",
        total_pages=int(meta.get("total_pages") or 0),
        done_pages=int(meta.get("done_pages") or 0),
        quota_behavior=str(meta.get("quota_behavior") or "wait"),
    )

    if healed_fp != orig_fp and healed_fp:
        try:
            from backend.database import db_save_job
            db_save_job(_job_to_db_dict(job))
        except Exception:
            pass
    return job


# Global in-memory registry
_jobs: dict[str, Job] = {}
_active_tasks: dict[str, asyncio.Task] = {}


def register_task(job_id: str, task: asyncio.Task) -> None:
    """Registers an active asyncio Task for cancellation."""
    _active_tasks[job_id] = task


def unregister_task(job_id: str) -> None:
    """Unregisters an active asyncio Task."""
    _active_tasks.pop(job_id, None)


def is_job_cancelled(job_id: str) -> bool:
    """Returns True if the job has been cancelled."""
    job = _jobs.get(job_id)
    return job is not None and job.status == "cancelled"


def cancel_job(job_id: str) -> bool:
    """Cancels a running job and its active asyncio task, persisting cancelled state to SQLite."""
    if not is_valid_job_id(job_id):
        return False
    job = _jobs.get(job_id) or get_job(job_id)
    task = _active_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()
    if job:
        if job.status == "done":
            # Do not corrupt an already completed job's status
            return False
        job.status = "cancelled"
        job.current_step = "🛑 Cancelled by user."
        job.updated_at = time.time()
        try:
            from backend.database import db_save_job
            db_save_job(_job_to_db_dict(job))
        except Exception:
            pass
        _notify_subscribers(job)
        return True
    return False


def clear_job_cancellation(job_id: str) -> None:
    """Clears cancelled status so a previously cancelled job can be restarted cleanly by the user."""
    job = _jobs.get(job_id)
    if job and job.status == "cancelled":
        job.status = "idle"
        job.error = None
        job.updated_at = time.time()
        try:
            from backend.database import db_save_job
            db_save_job(_job_to_db_dict(job))
        except Exception:
            pass


def create_job(file_path: str, file_name: str, file_type: str) -> Job:
    job_id = str(uuid.uuid4())
    now = time.time()
    job = Job(
        job_id=job_id,
        file_path=file_path,
        file_name=file_name,
        file_type=file_type,
        status="idle",
        mode="",
        progress=0,
        current_step="Waiting to start...",
        total_chunks=0,
        done_chunks=0,
        created_at=now,
        updated_at=now,
    )
    _jobs[job_id] = job
    try:
        from backend.database import db_save_job
        db_save_job(_job_to_db_dict(job))
    except Exception:
        pass
    return job


def get_job(job_id: str) -> Optional[Job]:
    if not is_valid_job_id(job_id):
        return None
    if job_id in _jobs:
        job = _jobs[job_id]
        healed = _heal_file_path(job.job_id, job.file_path, job.file_name)
        if healed != job.file_path:
            job.file_path = healed
        return job

    # Check SQLite database first
    try:
        from backend.database import db_get_job
        row = db_get_job(job_id)
        if row:
            job = _job_from_db_row(row)
            _jobs[job_id] = job
            return job
    except Exception:
        pass

    # Reconstruct from disk if server restarted
    try:
        base_temp = Path(__file__).resolve().parent.parent / "temp"
        out_dir = base_temp / "outputs" / job_id
        up_dir = base_temp / "uploads" / job_id
        if out_dir.exists():
            # Exclude images (like cover_image.jpg) - only genuine document/comic/audiobook outputs
            files = [
                f for f in out_dir.iterdir()
                if f.is_file() and f.suffix.lower() in [".docx", ".pdf", ".epub", ".cbz", ".cbr", ".mp3", ".m4b", ".txt"]
            ]
            if files:
                # Prefer final export or audio over intermediate txt
                preferred = [f for f in files if f.suffix.lower() in [".docx", ".pdf", ".epub", ".cbz", ".cbr", ".mp3", ".m4b"]]
                files_to_pick = preferred if preferred else files
                files_to_pick.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                out_file = files_to_pick[0]

                up_file = None
                if up_dir.exists():
                    ufiles = [f for f in up_dir.iterdir() if f.is_file()]
                    if ufiles:
                        up_file = ufiles[0]

                file_name = up_file.name if up_file else out_file.name
                file_type = (up_file.suffix if up_file else out_file.suffix).lstrip(".").lower()
                mode = "audiobook" if out_file.suffix.lower() in (".mp3", ".m4b") else "translate"
                mtime = out_file.stat().st_mtime
                job = Job(
                    job_id=job_id,
                    file_path=str(up_file) if up_file else str(out_file),
                    file_name=file_name,
                    file_type=file_type,
                    status="done",
                    mode=mode,
                    progress=100,
                    current_step="Completed",
                    total_chunks=1,
                    done_chunks=1,
                    output_path=str(out_file),
                    output_format=out_file.suffix.lstrip(".").lower(),
                    created_at=mtime,
                    updated_at=mtime,
                )
                _jobs[job_id] = job
                return job

        if up_dir.exists():
            ufiles = [f for f in up_dir.iterdir() if f.is_file()]
            if ufiles:
                up_file = ufiles[0]
                mtime = up_file.stat().st_mtime
                job = Job(
                    job_id=job_id,
                    file_path=str(up_file),
                    file_name=up_file.name,
                    file_type=up_file.suffix.lstrip(".").lower(),
                    status="idle",
                    mode="",
                    progress=0,
                    current_step="Uploaded",
                    total_chunks=0,
                    done_chunks=0,
                    created_at=mtime,
                    updated_at=mtime,
                )
                _jobs[job_id] = job
                return job
    except Exception:
        pass

    return None


def update_job(job_id: str, **kwargs):
    job = _jobs.get(job_id) or get_job(job_id)
    if job:
        # Protect cancelled status: once cancelled, background steps cannot overwrite status/step/output
        if job.status == "cancelled":
            incoming_status = kwargs.get("status")
            if incoming_status in ("running", "done", "error") or incoming_status is None:
                kwargs.pop("status", None)
                kwargs.pop("current_step", None)
                kwargs.pop("progress", None)
                kwargs.pop("output_path", None)
                kwargs.pop("error", None)
        for k, v in kwargs.items():
            setattr(job, k, v)
        job.updated_at = time.time()
        # Persist to SQLite
        try:
            from backend.database import db_save_job
            db_save_job(_job_to_db_dict(job))
        except Exception:
            pass
        # Notify SSE subscribers
        _notify_subscribers(job)


def _push_to_queue(q: asyncio.Queue, payload: dict) -> None:
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        # Drop oldest stale event so subscriber stays alive and receives latest/terminal state
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait(payload)
        except Exception:
            pass


def _notify_subscribers(job: Job):
    payload = {
        "status": job.status,
        "progress": job.progress,
        "current_step": job.current_step,
        "total_chunks": job.total_chunks,
        "done_chunks": job.done_chunks,
        "total_pages": int(getattr(job, "total_pages", 0) or 0),
        "done_pages": int(getattr(job, "done_pages", 0) or 0),
        "error": job.error,
        "output_path": job.output_path,
        "ai_polish": bool(getattr(job, "ai_polish", False)),
        "quota_behavior": getattr(job, "quota_behavior", "wait"),
    }
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    dead = []
    for q in list(job.subscribers):
        try:
            q_loop = getattr(q, "_loop", None)
            if q_loop is not None and q_loop.is_running() and q_loop is not running_loop:
                q_loop.call_soon_threadsafe(_push_to_queue, q, payload)
            else:
                _push_to_queue(q, payload)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            job.subscribers.remove(q)
        except ValueError:
            pass


def list_jobs() -> list[Job]:
    # Check SQLite database first
    try:
        from backend.database import db_list_jobs
        db_rows = db_list_jobs(limit=100)
        for r in db_rows:
            jid = r["job_id"]
            if jid not in _jobs:
                _jobs[jid] = _job_from_db_row(r)
    except Exception:
        pass

    # Check disk for any jobs from previous runs
    try:
        base_temp = Path(__file__).resolve().parent.parent / "temp"
        out_root = base_temp / "outputs"
        if out_root.exists():
            for d in out_root.iterdir():
                if d.is_dir() and d.name not in _jobs:
                    get_job(d.name)
    except Exception:
        pass

    # Return jobs sorted by creation time, newest first
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


def cleanup_old_jobs(max_age_seconds: int = 86400):
    """Remove stale non-running in-memory jobs, old DB records, and temp upload/output directories."""
    import shutil

    now = time.time()
    active_ids = {
        jid for jid, j in list(_jobs.items())
        if j.status in ("running", "queued") or jid in _active_tasks
    }
    to_delete = [
        jid for jid, j in list(_jobs.items())
        if jid not in active_ids and (now - j.created_at > max_age_seconds)
    ]
    for jid in to_delete:
        _jobs.pop(jid, None)

    try:
        from backend.database import db_cleanup_old_jobs, db_reset_orphaned_running_jobs
        if not _active_tasks:
            db_reset_orphaned_running_jobs()
        db_cleanup_old_jobs(max_age_seconds)
    except Exception:
        pass

    try:
        from backend.storage_cleaner import clean_temp_storage
        clean_temp_storage(max_age_hours=max(1, max_age_seconds // 3600))
    except Exception:
        pass

    base_temp = Path(__file__).resolve().parent.parent / "temp"
    output_max_age = max(max_age_seconds, 7 * 86400)
    for sub, age_limit in (("uploads", max_age_seconds), ("outputs", output_max_age)):
        root = base_temp / sub
        if not root.exists():
            continue
        for entry in root.iterdir():
            if not entry.is_dir() or entry.name == "tmp" or entry.name in active_ids:
                continue
            try:
                if now - entry.stat().st_mtime > age_limit:
                    shutil.rmtree(str(entry), ignore_errors=True)
            except Exception:
                pass


def is_test_job_identifier(job_id: Optional[str], file_name: Optional[str] = None) -> bool:
    """Returns True if the job ID or filename matches test-generated job naming patterns."""
    test_prefixes = (
        "test_", "reg_", "mock_", "sample_", "q_iso_",
        "cover_check", "sse_test", "sse_thread", "cancel_guard",
        "scanned_only", "book_", "book", "path_", "direct_text",
        "temp_", "stress_", "bench_"
    )
    exact_matches = (
        "sample.pdf", "sample.txt", "book.pdf", "book.txt", "active.pdf",
        "direct_text.txt", "direct_text"
    )

    if job_id:
        jid = job_id.strip().lower()
        if any(jid.startswith(p) for p in test_prefixes):
            return True

    if file_name:
        fn = file_name.strip().lower()
        if any(fn.startswith(p) for p in test_prefixes) or fn in exact_matches:
            return True

    return False


def is_test_job_filename(file_name: Optional[str]) -> bool:
    """Returns True if the filename matches test-generated job naming patterns."""
    return is_test_job_identifier(None, file_name)


def cleanup_test_jobs() -> list[str]:
    """Purges all test-generated jobs from in-memory cache, SQLite database, and disk directories."""
    import shutil

    deleted_ids: list[str] = []

    # 1. Purge from in-memory _jobs
    for jid, job in list(_jobs.items()):
        if is_test_job_identifier(jid, job.file_name):
            _jobs.pop(jid, None)
            deleted_ids.append(jid)

    # 2. Purge from SQLite
    try:
        from backend.database import db_delete_test_jobs
        db_deleted = db_delete_test_jobs()
        for jid in db_deleted:
            if jid not in deleted_ids:
                deleted_ids.append(jid)
    except Exception:
        pass

    # 3. Clean up disk directories for purged test jobs
    base_temp = Path(__file__).resolve().parent.parent / "temp"
    for jid in deleted_ids:
        for sub in ("uploads", "outputs"):
            target_dir = base_temp / sub / jid
            if target_dir.exists() and target_dir.is_dir():
                try:
                    shutil.rmtree(str(target_dir), ignore_errors=True)
                except Exception:
                    pass

    # 4. Sweep disk directories in temp/uploads and temp/outputs for orphan test folders or test-only files
    for sub in ("uploads", "outputs"):
        sub_dir = base_temp / sub
        if not sub_dir.is_dir():
            continue
        for entry in sub_dir.iterdir():
            if not entry.is_dir() or entry.name == "tmp":
                continue
            # If the directory name itself matches test prefixes
            if is_test_job_identifier(entry.name, None):
                try:
                    shutil.rmtree(str(entry), ignore_errors=True)
                    if entry.name not in deleted_ids:
                        deleted_ids.append(entry.name)
                except Exception:
                    pass
                continue
            # If directory contains only test-generated files (e.g. direct_text, test_, sample_)
            try:
                child_files = [f for f in entry.iterdir() if f.is_file()]
                if child_files and all(is_test_job_identifier(None, f.name) for f in child_files):
                    shutil.rmtree(str(entry), ignore_errors=True)
                    if entry.name not in deleted_ids:
                        deleted_ids.append(entry.name)
            except Exception:
                pass

    return deleted_ids

