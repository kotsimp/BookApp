"""
queue_manager.py - Smart Serial Batch Queue Engine for BookApp.
Allows queuing multiple mixed documents (novels, technical PDFs, EPUBs, Graphic Novels, Manga)
and translating them serially (1 document at a time, each running at full 4-5x internal worker
parallelism to maximize speed without triggering API 429 rate-limit collisions).
Supports both Manual Queue review + Start and Auto-Start Queue modes.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.job_manager import get_job, cancel_job, update_job

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    job_id: str
    file_name: str
    file_type: str
    source_lang: str = "english"
    target_lang: str = "greek"
    output_format: str = "pdf"
    layout_mode: str = "standard"
    reading_direction: str = "ltr"
    ai_polish: bool = False
    api_key: Optional[str] = None
    is_comic: bool = False
    is_scanned: bool = False
    status: str = "queued"  # queued | running | done | error | cancelled
    error: Optional[str] = None


_queue_items: List[QueueItem] = []
_queue_task: Optional[asyncio.Task] = None
_queue_paused: bool = False
_queue_auto_start: bool = False


def get_queue_state() -> Dict[str, Any]:
    """Returns full live snapshot of the Smart Batch Queue synced with JobManager."""
    serialized = []
    done_count = 0
    queued_count = 0
    running_count = 0

    for item in _queue_items:
        job = get_job(item.job_id)
        progress = 0
        current_step = "⏳ Waiting in queue..."
        has_output = False
        err = item.error

        if job:
            if item.status == "running" or job.status in ("running", "done", "error", "cancelled"):
                if item.status != "queued" or job.status in ("running", "done"):
                    item.status = job.status
            progress = job.progress if item.status != "queued" else 0
            current_step = job.current_step if item.status != "queued" else "⏳ Waiting in queue..."
            has_output = bool(job.output_path) and item.status == "done"
            if job.error:
                err = job.error
                item.error = err

        if item.status == "done":
            done_count += 1
        elif item.status == "queued":
            queued_count += 1
        elif item.status == "running":
            running_count += 1

        serialized.append({
            "job_id": item.job_id,
            "file_name": item.file_name,
            "file_type": item.file_type,
            "source_lang": item.source_lang,
            "target_lang": item.target_lang,
            "output_format": item.output_format,
            "layout_mode": item.layout_mode,
            "reading_direction": item.reading_direction,
            "ai_polish": item.ai_polish,
            "is_comic": item.is_comic,
            "is_scanned": item.is_scanned,
            "status": item.status,
            "progress": progress,
            "current_step": current_step,
            "has_output": has_output,
            "error": err,
        })

    is_running = bool(_queue_task and not _queue_task.done()) or running_count > 0
    return {
        "items": serialized,
        "is_running": is_running,
        "paused": _queue_paused,
        "auto_start": _queue_auto_start,
        "done_count": done_count,
        "queued_count": queued_count,
        "total_count": len(serialized),
    }


def add_to_queue(
    job_id: str,
    source_lang: str = "english",
    target_lang: str = "greek",
    output_format: str = "pdf",
    layout_mode: str = "standard",
    reading_direction: str = "ltr",
    ai_polish: bool = False,
    api_key: Optional[str] = None,
    is_comic: bool = False,
    is_scanned: bool = False,
) -> QueueItem:
    """Adds an uploaded job to the batch queue (or updates it if already queued)."""
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found.")

    # Enforce comic-compatible options automatically
    if is_comic or job.file_type in ("cbz", "cbr"):
        is_comic = True
        layout_mode = "comic"
        if output_format.lower() in ("txt", "docx", "doc"):
            output_format = "pdf"

    for existing in _queue_items:
        if existing.job_id == job_id:
            if existing.status in ("queued", "error", "cancelled"):
                existing.source_lang = source_lang
                existing.target_lang = target_lang
                existing.output_format = output_format
                existing.layout_mode = layout_mode
                existing.reading_direction = reading_direction
                existing.ai_polish = ai_polish
                existing.api_key = api_key
                existing.is_comic = is_comic
                existing.is_scanned = is_scanned
                existing.status = "queued"
                existing.error = None
            return existing

    item = QueueItem(
        job_id=job_id,
        file_name=job.file_name,
        file_type=job.file_type,
        source_lang=source_lang,
        target_lang=target_lang,
        output_format=output_format,
        layout_mode=layout_mode,
        reading_direction=reading_direction,
        ai_polish=ai_polish,
        api_key=api_key,
        is_comic=is_comic,
        is_scanned=is_scanned,
        status="queued",
    )
    _queue_items.append(item)
    update_job(job_id, status="queued", current_step="⏳ Queued in batch...")
    return item


def set_queue_auto_start(enabled: bool) -> bool:
    global _queue_auto_start
    _queue_auto_start = bool(enabled)
    return _queue_auto_start


def pause_queue() -> bool:
    global _queue_paused
    _queue_paused = True
    return _queue_paused


def remove_from_queue(job_id: str) -> bool:
    """Removes a job from the queue (cancelling it if currently running)."""
    for idx, item in enumerate(_queue_items):
        if item.job_id == job_id:
            if item.status == "running":
                cancel_job(job_id)
            _queue_items.pop(idx)
            return True
    return False


def clear_queue() -> int:
    """Clears all non-running items from the queue (returns number removed)."""
    global _queue_items
    before = len(_queue_items)
    _queue_items = [it for it in _queue_items if it.status == "running"]
    return before - len(_queue_items)


def get_completed_queue_job_ids() -> List[str]:
    """Returns job_ids of all completed queue items."""
    return [it.job_id for it in _queue_items if it.status == "done"]


async def _process_queue_loop(
    execute_item: Callable[[QueueItem], Awaitable[None]],
) -> None:
    """Serially processes queued items one by one until queue is empty or paused."""
    global _queue_paused
    logger.info("Smart Batch Queue processor started.")
    try:
        while not _queue_paused:
            next_item = next((it for it in _queue_items if it.status == "queued"), None)
            if not next_item:
                break

            next_item.status = "running"
            next_item.error = None
            logger.info(f"[Queue] Starting job {next_item.job_id} ({next_item.file_name})")
            try:
                await execute_item(next_item)
                job = get_job(next_item.job_id)
                if job and job.status in ("done", "error", "cancelled"):
                    next_item.status = job.status
                    next_item.error = job.error
                else:
                    next_item.status = "done"
            except asyncio.CancelledError:
                next_item.status = "cancelled"
                logger.info(f"[Queue] Job {next_item.job_id} cancelled.")
            except Exception as ex:
                next_item.status = "error"
                next_item.error = str(ex)
                logger.error(f"[Queue] Job {next_item.job_id} failed: {ex}")
    finally:
        logger.info("Smart Batch Queue processor finished/idle.")


def start_queue(
    execute_item: Callable[[QueueItem], Awaitable[None]],
) -> Dict[str, Any]:
    """Starts or resumes background serial queue processing."""
    global _queue_task, _queue_paused
    _queue_paused = False
    if _queue_task is None or _queue_task.done():
        _queue_task = asyncio.create_task(_process_queue_loop(execute_item))
    return get_queue_state()
