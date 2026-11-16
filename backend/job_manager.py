"""
Job Manager - tracks in-memory job state for all translation and audiobook tasks.
"""

import uuid
import time
import asyncio
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class Job:
    job_id: str
    file_path: str
    file_name: str
    file_type: str          # 'pdf', 'docx', 'epub'
    status: str             # 'idle', 'running', 'done', 'error'
    mode: str               # 'translate' or 'audiobook'
    progress: int           # 0-100
    current_step: str       # human-readable status message
    total_chunks: int       # total processing units
    done_chunks: int        # completed units
    created_at: float
    updated_at: float
    # Optional / nullable fields (must have defaults)
    output_path: Optional[str] = None
    output_format: Optional[str] = None  # txt, docx, pdf, epub
    layout_mode: str = "standard"        # 'standard' or 'literature'
    error: Optional[str] = None
    # SSE subscriber queues (list of asyncio.Queue)
    subscribers: list       = field(default_factory=list)


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
    """Cancels a running job and its active asyncio task."""
    job = _jobs.get(job_id)
    task = _active_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()
    if job:
        job.status = "cancelled"
        job.current_step = "🛑 Cancelled by user."
        job.updated_at = time.time()
        _notify_subscribers(job)
        return True
    return False


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
        db_save_job({
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
        })
    except Exception:
        pass
    return job


def get_job(job_id: str) -> Optional[Job]:
    if job_id in _jobs:
        return _jobs[job_id]

    # Check SQLite database first
    try:
        from backend.database import db_get_job
        row = db_get_job(job_id)
        if row:
            job = Job(
                job_id=row["job_id"],
                file_path=row["file_path"] or "",
                file_name=row["file_name"] or "",
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
            )
            _jobs[job_id] = job
            return job
    except Exception:
        pass

    # Reconstruct from disk if server restarted
    try:
        from pathlib import Path
        base_temp = Path(__file__).resolve().parent.parent / "temp"
        out_dir = base_temp / "outputs" / job_id
        up_dir = base_temp / "uploads" / job_id
        if out_dir.exists():
            # Exclude images (like cover_image.jpg) - only genuine document outputs
            files = [
                f for f in out_dir.iterdir()
                if f.is_file() and f.suffix.lower() in [".docx", ".pdf", ".epub", ".mp3", ".txt"]
            ]
            if files:
                # Prefer final export or mp3 over intermediate txt
                preferred = [f for f in files if f.suffix.lower() in [".docx", ".pdf", ".epub", ".mp3"]]
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
                mode = "audiobook" if out_file.suffix.lower() == ".mp3" else "translate"
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
    job = _jobs.get(job_id)
    if job:
        # Protect cancelled status: once cancelled, background steps cannot reset status to running or done
        if job.status == "cancelled" and kwargs.get("status") in ("running", "done"):
            kwargs.pop("status", None)
        for k, v in kwargs.items():
            setattr(job, k, v)
        job.updated_at = time.time()
        # Persist to SQLite
        try:
            from backend.database import db_save_job
            db_save_job({
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
            })
        except Exception:
            pass
        # Notify SSE subscribers
        _notify_subscribers(job)


def _notify_subscribers(job: Job):
    dead = []
    for q in job.subscribers:
        try:
            # Put without blocking - if queue is full, skip
            q.put_nowait({
                "status": job.status,
                "progress": job.progress,
                "current_step": job.current_step,
                "total_chunks": job.total_chunks,
                "done_chunks": job.done_chunks,
                "error": job.error,
                "output_path": job.output_path,
            })
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
                _jobs[jid] = Job(
                    job_id=r["job_id"],
                    file_path=r["file_path"] or "",
                    file_name=r["file_name"] or "",
                    file_type=r["file_type"] or "",
                    status=r["status"] or "idle",
                    mode=r["mode"] or "",
                    progress=r["progress"] or 0,
                    current_step=r["current_step"] or "",
                    total_chunks=r["total_chunks"] or 0,
                    done_chunks=r["done_chunks"] or 0,
                    created_at=r["created_at"] or time.time(),
                    updated_at=r["updated_at"] or time.time(),
                    output_path=r["output_path"],
                    output_format=r["output_format"],
                    layout_mode=r["layout_mode"] or "standard",
                    error=r["error"],
                )
    except Exception:
        pass

    # Check disk for any jobs from previous runs
    try:
        from pathlib import Path
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
    """Remove in-memory jobs, old DB records, and temp upload/output directories older than max_age_seconds (default 24h)."""
    import shutil
    from pathlib import Path

    now = time.time()
    to_delete = [jid for jid, j in _jobs.items() if now - j.created_at > max_age_seconds]
    for jid in to_delete:
        del _jobs[jid]

    try:
        from backend.database import db_cleanup_old_jobs
        db_cleanup_old_jobs(max_age_seconds)
    except Exception:
        pass

    try:
        from backend.storage_cleaner import clean_temp_storage
        clean_temp_storage(max_age_hours=max(1, max_age_seconds // 3600))
    except Exception:
        pass

    base_temp = Path(__file__).resolve().parent.parent / "temp"
    for sub in ("uploads", "outputs"):
        root = base_temp / sub
        if not root.exists():
            continue
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                if now - entry.stat().st_mtime > max_age_seconds:
                    shutil.rmtree(str(entry), ignore_errors=True)
            except Exception:
                pass
