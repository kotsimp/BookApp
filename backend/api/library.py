"""
backend/api/library.py - The user's library: series, the EPUB's Characters page, reading positions, what the Glossary
learns from the translations, and backups (APIRouter included by backend.main).
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api.common import OUTPUT_DIR, _validate_job_id, _validate_language
from backend.job_manager import get_job

logger = logging.getLogger(__name__)
router = APIRouter()

SUMMARY_KINDS = ("short_summary", "extended_summary", "standard_synopsis", "one_sentence", "extended_synopsis")


def _owner() -> str:
    from backend.request_context import current_user_id
    return current_user_id()


def _is_admin() -> bool:
    from backend.request_context import current_user
    return (current_user() or {}).get("role") == "admin"


def _job(job_id: str):
    _validate_job_id(job_id)
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    return job


def _title(job) -> str:
    return Path(job.file_name or job.job_id).stem


def _alive(job_id: str) -> bool:
    return get_job(job_id) is not None


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

class SeriesCreateRequest(BaseModel):
    name: str


class SeriesUpdateRequest(BaseModel):
    name: Optional[str] = None
    books: Optional[List[str]] = None  # the books in their new order (books left out leave the series)


class BookSeriesRequest(BaseModel):
    series_id: Optional[str] = None    # None: the book is in no series
    position: Optional[int] = None     # 1 = the series' first book; the end when omitted


def _series_http(e) -> HTTPException:
    return HTTPException(getattr(e, "status", 400), str(e))


def _public_series(s: dict) -> dict:
    books = []
    for jid in s["books"]:
        job = get_job(jid)
        if job:
            books.append({"job_id": jid, "title": _title(job), "target_lang": job.target_lang or "",
                          "status": job.status})
    return {"id": s["id"], "name": s["name"], "books": books}


@router.get("/api/series")
async def series_list():
    from backend import series
    found = await asyncio.to_thread(series.list_series, _owner(), _alive)
    return {"series": [_public_series(s) for s in found]}


@router.post("/api/series")
async def series_create(req: SeriesCreateRequest):
    from backend import series
    try:
        made = await asyncio.to_thread(series.create, _owner(), req.name)
    except series.SeriesError as e:
        raise _series_http(e)
    return _public_series(made)


@router.put("/api/series/{series_id}")
async def series_update(series_id: str, req: SeriesUpdateRequest):
    from backend import series
    owner = _owner()
    try:
        result = None
        if req.name is not None:
            result = await asyncio.to_thread(series.rename, owner, series_id, req.name)
        if req.books is not None:
            result = await asyncio.to_thread(series.set_order, owner, series_id, [b for b in req.books if _alive(b)])
        if result is None:
            raise HTTPException(400, "Nothing to change.")
    except series.SeriesError as e:
        raise _series_http(e)
    return _public_series(result)


@router.delete("/api/series/{series_id}")
async def series_delete(series_id: str):
    from backend import series
    try:
        await asyncio.to_thread(series.delete, _owner(), series_id)
    except series.SeriesError as e:
        raise _series_http(e)
    return {"status": "deleted"}


def _summary(out_dir: Path, lang: str) -> Optional[dict]:
    from backend.book_insights import load_insight
    for kind in SUMMARY_KINDS:
        for language in (lang, "greek" if lang == "english" else "english"):
            rec = load_insight(out_dir, kind, language)
            if rec and rec.get("text"):
                return {"kind": kind, "language": language, "text": rec["text"]}
    return None


@router.get("/api/jobs/{job_id}/series")
async def book_series(job_id: str, language: str = "greek"):
    """The book's series and its place in it, with the earlier books (and the summary each one has, if any)."""
    from backend import series
    job = _job(job_id)
    lang = _validate_language(language)
    found = await asyncio.to_thread(series.find, job_id, _owner())
    if not found:
        return {"series": None, "position": None, "earlier": []}
    _, sid, entry, index = found
    earlier = []
    for jid in entry["books"][:index]:
        other = get_job(jid)
        if not other:
            continue
        summary = await asyncio.to_thread(_summary, OUTPUT_DIR / jid, lang)
        earlier.append({"job_id": jid, "title": _title(other), "summary": summary})
    names = await asyncio.to_thread(series.series_terms, job.job_id, OUTPUT_DIR, _owner())
    return {"series": {"id": sid, "name": entry.get("name") or ""}, "position": index + 1,
            "books": len(entry["books"]), "earlier": earlier, "names_from_earlier": len(names)}


@router.put("/api/jobs/{job_id}/series")
async def book_series_set(job_id: str, req: BookSeriesRequest):
    from backend import series
    _job(job_id)
    try:
        result = await asyncio.to_thread(series.place, _owner(), job_id, req.series_id or None, req.position)
    except series.SeriesError as e:
        raise _series_http(e)
    return {"series": _public_series(result) if result else None}


# ---------------------------------------------------------------------------
# The EPUB's Characters page
# ---------------------------------------------------------------------------

class EpubOptionsRequest(BaseModel):
    characters: bool


def _epub_options(job) -> dict:
    from backend import epub_extras
    out_dir = OUTPUT_DIR / job.job_id
    found = epub_extras.entries(out_dir, job.target_lang) if out_dir.is_dir() else None
    return {**epub_extras.options(out_dir), "available": bool(found),
            "language": "greek" if (job.target_lang or "").lower() in ("greek", "el") else "english",
            "people": len(found[1]) if found else 0, "terms": len(found[2]) if found else 0}


@router.get("/api/jobs/{job_id}/epub-options")
async def epub_options_get(job_id: str):
    job = _job(job_id)
    return await asyncio.to_thread(_epub_options, job)


@router.put("/api/jobs/{job_id}/epub-options")
async def epub_options_set(job_id: str, req: EpubOptionsRequest):
    from backend import epub_extras
    job = _job(job_id)
    await asyncio.to_thread(epub_extras.set_options, OUTPUT_DIR / job_id, req.characters)
    return await asyncio.to_thread(_epub_options, job)


# ---------------------------------------------------------------------------
# Reading position (sent by KOReader / Readest to /kosync)
# ---------------------------------------------------------------------------

def _until(job, percentage: float) -> tuple:
    """The page (an EPUB: chapter) of the original that a share of the book reaches, by the length of its text."""
    from backend.insights_more import extract_pages
    pages, unit = extract_pages(job.file_path, job.file_type)
    total = sum(len(t) for _, t in pages)
    if not pages or not total:
        return None, unit
    reached, running = pages[-1][0], 0
    for number, text in pages:
        running += len(text)
        if running >= percentage * total:
            reached = number
            break
    return reached, unit


@router.get("/api/jobs/{job_id}/reading-position")
async def reading_position(job_id: str):
    from backend import reading_sync
    job = _job(job_id)
    # the book's own user's apps (an administrator looking at someone's book sees theirs); a book from before
    # accounts: the administrator's
    pos = (await asyncio.to_thread(reading_sync.book_positions, job.owner or _owner())).get(job_id)
    if not pos:
        return {"position": None}
    until, unit = None, None
    try:
        until, unit = await asyncio.to_thread(_until, job, float(pos.get("percentage") or 0))
    except Exception as e:  # a book Book Insights cannot read (a comic): the position alone
        logger.debug(f"Reading position of {job_id} not mapped to a page: {e}")
    return {"position": pos, "until": until, "unit": unit}


# ---------------------------------------------------------------------------
# What the Glossary learns
# ---------------------------------------------------------------------------

class SuggestionsRequest(BaseModel):
    sources: Optional[List[str]] = None   # these suggestions (by their English name)
    all: bool = False                     # accept: every suggestion without a warning


@router.get("/api/glossary/suggestions")
async def glossary_suggestions():
    from backend import glossary_learning
    items = await asyncio.to_thread(glossary_learning.listing, _owner())
    visible = [s for s in items if not s["books"] or any(_alive(b["job_id"]) for b in s["books"])]
    return {"suggestions": visible, "safe": sum(1 for s in visible if glossary_learning.safe_to_accept(s))}


@router.post("/api/glossary/suggestions/accept")
async def glossary_suggestions_accept(req: SuggestionsRequest):
    from backend import glossary_learning
    if not req.all and not req.sources:
        raise HTTPException(400, "Choose the suggestions to add.")
    added = await asyncio.to_thread(glossary_learning.accept, _owner(), None if req.all else req.sources)
    return {"added": len(added), "terms": [{"source": s, "target": t} for s, t in added]}


@router.post("/api/glossary/suggestions/dismiss")
async def glossary_suggestions_dismiss(req: SuggestionsRequest):
    from backend import glossary_learning
    if not req.sources:
        raise HTTPException(400, "Choose the suggestions to dismiss.")
    gone = await asyncio.to_thread(glossary_learning.dismiss, _owner(), req.sources)
    return {"dismissed": gone}


# ---------------------------------------------------------------------------
# Backup and restore
# ---------------------------------------------------------------------------

class BackupRequest(BaseModel):
    include_audio: bool = False


@router.post("/api/backup")
async def backup_start(req: BackupRequest):
    """Starts a backup of the user's books; GET /api/backup/<task> follows it, .../download hands it out."""
    from backend import auth, backup
    owner = _owner()
    jobs = await asyncio.to_thread(backup.owner_jobs, owner, _is_admin(), not auth.is_enabled())
    if not jobs:
        raise HTTPException(404, "Δεν υπάρχουν βιβλία για αντίγραφο ασφαλείας.")
    return {"task_id": backup.start_backup(owner, jobs, req.include_audio), "books": len(jobs)}


@router.post("/api/backup/restore")
async def backup_restore(request: Request):
    """A backup ZIP as the request body (application/zip), restored into the user's books in the background."""
    from backend import backup
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise HTTPException(400, "Invalid Content-Length.")
    if length > backup.MAX_RESTORE_BYTES:
        raise HTTPException(413, "Το αρχείο είναι μεγαλύτερο από το όριο επαναφοράς.")
    target = await asyncio.to_thread(backup.restore_upload_path)
    free = shutil.disk_usage(target.parent).free
    if length and length * 2 + backup.DISK_MARGIN > free:
        raise HTTPException(507, "Δεν υπάρχει αρκετός χώρος στον δίσκο για την επαναφορά.")
    written = 0
    try:
        with open(target, "wb") as out:
            async for chunk in request.stream():
                written += len(chunk)
                if written > backup.MAX_RESTORE_BYTES:
                    raise HTTPException(413, "Το αρχείο είναι μεγαλύτερο από το όριο επαναφοράς.")
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if not written:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "Διαλέξτε ένα αρχείο αντιγράφου ασφαλείας (.zip).")
    return {"task_id": backup.start_restore(_owner(), target, _is_admin())}


@router.get("/api/backup/{task_id}")
async def backup_status(task_id: str):
    from backend import backup
    task = backup.task_status(task_id, _owner())
    if not task:
        raise HTTPException(404, "Η εργασία δεν βρέθηκε.")
    return task


@router.get("/api/backup/{task_id}/download")
async def backup_download(task_id: str):
    from backend import backup
    found = backup.task_file(task_id, _owner())
    if not found:
        raise HTTPException(404, "Το αντίγραφο δεν είναι έτοιμο ή δεν υπάρχει πια.")
    path, name = found
    return FileResponse(str(path), media_type="application/zip", filename=name)
