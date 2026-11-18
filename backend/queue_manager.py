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

from backend.job_manager import get_job, cancel_job, update_job, clear_job_cancellation

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
MAX_QUEUE_ITEMS: int = 20


def is_mixed_queue() -> bool:
    """Returns True when the batch queue contains BOTH comic/graphic novel items and regular book/document items."""
    has_comic = any(it.is_comic for it in _queue_items)
    has_book = any(not it.is_comic for it in _queue_items)
    return has_comic and has_book


def get_queue_state() -> Dict[str, Any]:
    """Returns full live snapshot of the Smart Batch Queue synced with JobManager."""
    global _queue_auto_start
    mixed = is_mixed_queue()
    if mixed and _queue_auto_start:
        _queue_auto_start = False

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
            if item.status != "queued" and job.error:
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
        "is_mixed": mixed,
        "done_count": done_count,
        "queued_count": queued_count,
        "total_count": len(serialized),
        "max_items": MAX_QUEUE_ITEMS,
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
    """Adds an uploaded job to the batch queue (or updates/re-queues it if already present)."""
    if source_lang == target_lang:
        raise ValueError("Source and target languages must be different.")

    job = get_job(job_id)
    if not job:
        raise KeyError(f"Job '{job_id}' not found.")

    if job.status == "running":
        raise RuntimeError(f"Job '{job_id}' is already running.")

    # Auto-detect comic vs book compatibility safely for mixed batches
    effective_comic = bool(
        is_comic
        or job.file_type in ("cbz", "cbr")
        or (job.file_name or "").lower().endswith((".cbz", ".cbr", ".zip"))
    )
    fmt_clean = (output_format or "pdf").lower().lstrip(".")
    layout_clean = (layout_mode or "standard").lower()

    if effective_comic:
        layout_clean = "comic"
        if fmt_clean in ("txt", "docx", "doc"):
            fmt_clean = "pdf"
        if is_scanned:
            ai_polish = True
    else:
        # Protect non-comic books in mixed batches from inheriting comic-only settings
        if layout_clean == "comic" and not is_comic:
            layout_clean = "literature" if job.file_type == "epub" else "standard"
        if fmt_clean in ("cbz", "cbr"):
            fmt_clean = "pdf"

    for existing in _queue_items:
        if existing.job_id == job_id:
            if existing.status == "running":
                raise RuntimeError(f"Job '{job_id}' is already running in the queue.")
            existing.source_lang = source_lang
            existing.target_lang = target_lang
            existing.output_format = fmt_clean
            existing.layout_mode = layout_clean
            existing.reading_direction = reading_direction
            existing.ai_polish = ai_polish
            existing.api_key = api_key
            existing.is_comic = effective_comic
            existing.is_scanned = is_scanned
            existing.status = "queued"
            existing.error = None
            clear_job_cancellation(job_id)
            update_job(job_id, status="queued", progress=0, error=None, current_step="⏳ Queued in batch...")
            return existing

    if len(_queue_items) >= MAX_QUEUE_ITEMS:
        raise ValueError(
            f"Το όριο της ουράς είναι {MAX_QUEUE_ITEMS} αρχεία ανά παρτίδα. "
            f"Καθαρίστε ή αφαιρέστε κάποια ολοκληρωμένα αρχεία για να προσθέσετε νέα."
        )

    item = QueueItem(
        job_id=job_id,
        file_name=job.file_name,
        file_type=job.file_type,
        source_lang=source_lang,
        target_lang=target_lang,
        output_format=fmt_clean,
        layout_mode=layout_clean,
        reading_direction=reading_direction,
        ai_polish=ai_polish,
        api_key=api_key,
        is_comic=effective_comic,
        is_scanned=is_scanned,
        status="queued",
    )
    _queue_items.append(item)
    if is_mixed_queue():
        global _queue_auto_start
        if _queue_auto_start:
            logger.info("[Queue] Mixed batch detected (books + comics) — auto-disabling Auto-Start for safe settings review.")
        _queue_auto_start = False
    clear_job_cancellation(job_id)
    update_job(job_id, status="queued", progress=0, error=None, current_step="⏳ Queued in batch...")
    return item


def retry_queue_item(job_id: str) -> QueueItem:
    """Resets a failed, cancelled, or done queue item back to queued state."""
    for item in _queue_items:
        if item.job_id == job_id:
            if item.status == "running":
                raise RuntimeError(f"Job '{job_id}' is currently running.")
            job = get_job(job_id)
            if not job:
                raise KeyError(f"Job '{job_id}' no longer exists.")
            item.status = "queued"
            item.error = None
            clear_job_cancellation(job_id)
            update_job(job_id, status="queued", progress=0, error=None, current_step="⏳ Queued for retry...")
            return item
    raise KeyError(f"Job '{job_id}' not found in queue.")


def set_queue_auto_start(enabled: bool) -> bool:
    global _queue_auto_start
    if enabled and is_mixed_queue():
        _queue_auto_start = False
        return False
    _queue_auto_start = bool(enabled)
    return _queue_auto_start


def pause_queue() -> bool:
    global _queue_paused
    _queue_paused = True
    return _queue_paused


def remove_from_queue(job_id: str) -> bool:
    """Removes a job from the queue (cancelling it if currently running, or resetting queued status to idle)."""
    global _queue_paused
    for idx, item in enumerate(_queue_items):
        if item.job_id == job_id:
            if item.status == "running":
                cancel_job(job_id)
            elif item.status == "queued":
                job = get_job(job_id)
                if job and job.status == "queued":
                    update_job(job_id, status="idle", current_step="Ready")
            _queue_items.pop(idx)
            if not _queue_items:
                _queue_paused = False
            return True
    return False


def clear_queue() -> int:
    """Clears all non-running items from the queue (returns number removed)."""
    global _queue_items, _queue_paused
    before = len(_queue_items)
    kept = []
    for it in _queue_items:
        if it.status == "running":
            kept.append(it)
        elif it.status == "queued":
            job = get_job(it.job_id)
            if job and job.status == "queued":
                update_job(it.job_id, status="idle", current_step="Ready")
    _queue_items = kept
    if not _queue_items:
        _queue_paused = False
    return before - len(_queue_items)


def get_completed_queue_job_ids() -> List[str]:
    """Returns job_ids of all completed queue items."""
    get_queue_state()  # ensure statuses are synced with JobManager
    return [it.job_id for it in _queue_items if it.status == "done"]


async def _process_queue_loop(
    execute_item: Callable[[QueueItem], Awaitable[None]],
) -> None:
    """Serially processes queued items one by one until queue is empty or paused.
    Each item runs in its own isolated child Task so cancelling a single running item
    never terminates the queue processor loop — it cleanly moves on to the next item.
    """
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
            item_task = asyncio.create_task(execute_item(next_item))
            try:
                await item_task
                job = get_job(next_item.job_id)
                if job and job.status in ("done", "error", "cancelled"):
                    next_item.status = job.status
                    next_item.error = job.error
                elif not job:
                    next_item.status = "cancelled"
                else:
                    next_item.status = "done"
            except asyncio.CancelledError:
                cur_task = asyncio.current_task()
                if cur_task is not None and cur_task.cancelling() > 0:
                    # Outer queue loop itself is being cancelled (e.g. server shutdown)
                    if not item_task.done():
                        item_task.cancel()
                    raise
                next_item.status = "cancelled"
                logger.info(f"[Queue] Job {next_item.job_id} cancelled; continuing queue.")
            except Exception as ex:
                next_item.status = "error"
                next_item.error = str(ex)
                logger.error(f"[Queue] Job {next_item.job_id} failed: {ex}")
    finally:
        logger.info("Smart Batch Queue processor finished/idle.")


def apply_settings_to_queued_items(
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
    output_format: Optional[str] = None,
    layout_mode: Optional[str] = None,
    reading_direction: Optional[str] = None,
    ai_polish: Optional[bool] = None,
    api_key: Optional[str] = None,
) -> int:
    """Applies the user's latest Translation Settings to all currently 'queued' items
    while strictly preserving per-item Comic vs Book safety rules.
    """
    if source_lang and target_lang and source_lang == target_lang:
        raise ValueError("Source and target languages must be different.")

    updated = 0
    for item in _queue_items:
        if item.status != "queued":
            continue
        if source_lang:
            item.source_lang = source_lang
        if target_lang:
            item.target_lang = target_lang
        if reading_direction:
            item.reading_direction = reading_direction
        if api_key is not None:
            item.api_key = api_key or None

        fmt_clean = (output_format or item.output_format or "pdf").lower().lstrip(".")
        layout_clean = (layout_mode or item.layout_mode or "standard").lower()

        if item.is_comic:
            item.layout_mode = "comic"
            item.output_format = "pdf" if fmt_clean in ("txt", "docx", "doc") else fmt_clean
            if item.is_scanned:
                item.ai_polish = True
            elif ai_polish is not None:
                item.ai_polish = bool(ai_polish)
        else:
            if layout_clean == "comic":
                # Preserve existing book layout (e.g. 'literature') instead of clobbering it to 'standard'
                if item.layout_mode in ("literature", "standard"):
                    layout_clean = item.layout_mode
                else:
                    layout_clean = "literature" if item.file_type == "epub" else "standard"
            if fmt_clean in ("cbz", "cbr"):
                fmt_clean = "pdf"
            item.layout_mode = layout_clean
            item.output_format = fmt_clean
            if ai_polish is not None:
                item.ai_polish = bool(ai_polish)
        updated += 1
    return updated


def start_queue(
    execute_item: Callable[[QueueItem], Awaitable[None]],
) -> Dict[str, Any]:
    """Starts or resumes background serial queue processing."""
    global _queue_task, _queue_paused
    _queue_paused = False
    has_queued = any(it.status == "queued" for it in _queue_items)
    if has_queued and (_queue_task is None or _queue_task.done()):
        _queue_task = asyncio.create_task(_process_queue_loop(execute_item))
    return get_queue_state()
