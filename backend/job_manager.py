"""
Job Manager - tracks in-memory job state for all translation and audiobook tasks.
"""

import uuid
import time
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
    return job


def get_job(job_id: str) -> Optional[Job]:
    if job_id in _jobs:
        return _jobs[job_id]

    # Reconstruct from disk if server restarted
    try:
        from pathlib import Path
        base_temp = Path(__file__).resolve().parent.parent / "temp"
        out_dir = base_temp / "outputs" / job_id
        up_dir = base_temp / "uploads" / job_id
        if out_dir.exists():
            files = [f for f in out_dir.iterdir() if f.is_file()]
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
                file_type = out_file.suffix.lstrip(".").lower()
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
    except Exception:
        pass

    return None


def update_job(job_id: str, **kwargs):
    job = _jobs.get(job_id)
    if job:
        for k, v in kwargs.items():
            setattr(job, k, v)
        job.updated_at = time.time()
        # Notify SSE subscribers
        _notify_subscribers(job)


def _notify_subscribers(job: Job):
    import asyncio
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
    """Remove jobs older than max_age_seconds (default 24h)."""
    now = time.time()
    to_delete = [jid for jid, j in _jobs.items() if now - j.created_at > max_age_seconds]
    for jid in to_delete:
        del _jobs[jid]
