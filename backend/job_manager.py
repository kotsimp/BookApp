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
    output_path: Optional[str]
    error: Optional[str]
    created_at: float
    updated_at: float
    # SSE subscriber queues (list of asyncio.Queue)
    subscribers: list       = field(default_factory=list)


# Global in-memory registry
_jobs: dict[str, Job] = {}


def create_job(file_path: str, file_name: str, file_type: str) -> Job:
    job_id = str(uuid.uuid4())
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
        output_path=None,
        error=None,
        created_at=time.time(),
        updated_at=time.time(),
        subscribers=[],
    )
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[Job]:
    return _jobs.get(job_id)


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
    # Return jobs sorted by creation time, newest first
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


def cleanup_old_jobs(max_age_seconds: int = 86400):
    """Remove jobs older than max_age_seconds (default 24h)."""
    now = time.time()
    to_delete = [jid for jid, j in _jobs.items() if now - j.created_at > max_age_seconds]
    for jid in to_delete:
        del _jobs[jid]
