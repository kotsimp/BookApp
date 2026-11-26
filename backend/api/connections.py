"""
connections.py - The link to the user's reading devices.

/api/connections...  the 📲 Devices window (signed in): the e-reader catalogue link.
/opds/<token>/...    the e-reader catalogue (OPDS 1.2): finished translations for reading apps (KOReader, Moon+ Reader,
                     Librera, Panels…). The secret token in the path is the pass, since these apps cannot sign in.
"""

import asyncio
import datetime
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from backend.api.common import OUTPUT_DIR, _validate_job_id

logger = logging.getLogger(__name__)

router = APIRouter()

FEED_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
MAX_ENTRIES = 300
# what each kind of book offers: (link name, media type, title)
BOOK_FORMATS = (("epub", "application/epub+zip", "EPUB"), ("pdf", "application/pdf", "PDF"),
                ("bilingual-epub", "application/epub+zip", "Δίγλωσσο EPUB · Bilingual EPUB"))
# EPUB too: some reading apps (several on the iPhone among them) open EPUB only, not CBZ or PDF
COMIC_FORMATS = (("cbz", "application/vnd.comicbook+zip", "CBZ"), ("epub", "application/epub+zip", "EPUB"),
                 ("pdf", "application/pdf", "PDF"))
EXTENSIONS = {"epub": "epub", "pdf": "pdf", "bilingual-epub": "epub", "cbz": "cbz"}


def _owner() -> str:
    from backend.request_context import current_user_id
    return current_user_id()


@router.get("/api/connections")
async def connections_status():
    """The signed-in user's e-reader link: whether one exists (it is shown only when made)."""
    from backend.connections import opds_status
    return {"opds": opds_status(_owner())}


@router.post("/api/connections/opds")
async def connections_new_opds_link():
    """A new secret e-reader link: shown this once; the previous link stops working."""
    from backend.connections import new_opds_token
    token = await asyncio.to_thread(new_opds_token, _owner())
    return {"path": f"/opds/{token}/"}


@router.delete("/api/connections/opds")
async def connections_remove_opds_link():
    from backend.connections import remove_opds_token
    await asyncio.to_thread(remove_opds_token, _owner())
    return {"status": "removed"}


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

def _catalogue_user(token: str):
    """Opens the catalogue as the token's user for this request; 404 for anything else.
    Returns (context token to reset, the predicate of the books that are this user's own)."""
    from backend import auth
    from backend.connections import owner_for_opds_token
    from backend.request_context import set_current_user
    owner = owner_for_opds_token(token)
    if owner is None:
        raise HTTPException(404, "Not found.")
    if auth.is_enabled():
        user = auth.get_user(owner) if owner else None
        if not user or user.get("disabled"):  # a link made before accounts were on, or of a removed account
            raise HTTPException(404, "Not found.")
        ctx = set_current_user({"id": user["id"], "username": user["username"], "role": user["role"]})
        # the user's own books (an administrator also has the jobs from before accounts), never other users'
        admin = user["role"] == "admin"
        return ctx, (lambda job: (job.owner or "") == owner or (admin and not job.owner))
    return set_current_user(None), (lambda job: True)


def _translated(job) -> bool:
    """A finished translation of this job is on disk (also after an audiobook was made from it on the same job)."""
    from backend import main
    out_dir = OUTPUT_DIR / job.job_id
    return job.status != "running" and out_dir.is_dir() and bool(main._translated_texts(job, out_dir))


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts or 0, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_comic(job) -> bool:
    return (job.layout_mode or "") == "comic" or (job.file_type or "") in ("cbz", "cbr", "zip")


def _blurb(job) -> str:
    """The book's back-cover blurb from Book Insights, in the translation's language first, as its description."""
    from backend.book_insights import load_insight
    order = ["greek", "english"] if (job.target_lang or "").lower() in ("greek", "el") else ["english", "greek"]
    for lang in order:
        rec = load_insight(OUTPUT_DIR / job.job_id, "blurb", lang)
        if rec and rec.get("text"):
            return rec["text"]
    return ""


def _file_name(job, kind: str) -> str:
    """The name a link ends in: "USS_Nebraska_Sanctum_Vol_01.cbz". E-reader apps take the format and the saved file's
    name from the link's extension (KOReader looks at it before the media type), so a link ending in ".../cbz"
    could leave a reader with a file it cannot open."""
    stem = re.sub(r"\W+", "_", Path(job.file_name or "Book").stem).strip("_")[:120].rstrip("_") or "Book"
    return f"{stem}{'_bilingual' if kind == 'bilingual-epub' else ''}.{EXTENSIONS[kind]}"


def _entry(job, base: str) -> str:
    from backend.bilingual import _lang_code
    title = Path(job.file_name or "Book").stem
    sample = getattr(job, "sample_range", None)
    if sample:
        title += f" · δείγμα / sample {sample[0]}–{sample[1]}"
    langs = f"{(job.source_lang or '').title()} → {(job.target_lang or '').title()}"
    parts = [
        "<entry>",
        f"<title>{escape(title)}</title>",
        f"<id>urn:uuid:{job.job_id}</id>",
        f"<updated>{_iso(job.updated_at)}</updated>",
        "<author><name>BookApp</name></author>",
        f"<dc:language>{_lang_code(job.target_lang)}</dc:language>",
        f"<content type=\"text\">{escape(_blurb(job) or langs)}</content>",
    ]
    cover_known = (OUTPUT_DIR / job.job_id / "cover_image.jpg").is_file() or (job.file_type or "") in ("pdf", "epub")
    if cover_known:
        href = quoteattr(f"{base}cover/{job.job_id}")
        parts.append(f'<link rel="http://opds-spec.org/image" href={href} type="image/jpeg"/>')
        parts.append(f'<link rel="http://opds-spec.org/image/thumbnail" href={href} type="image/jpeg"/>')
    for kind, media, label in (COMIC_FORMATS if _is_comic(job) else BOOK_FORMATS):
        href = quoteattr(f"{base}book/{job.job_id}/{kind}/{quote(_file_name(job, kind))}")
        parts.append(f'<link rel="http://opds-spec.org/acquisition" href={href} type="{media}" title={quoteattr(label)}/>')
    parts.append("</entry>")
    return "".join(parts)


def _catalogue_jobs(own) -> list:
    from backend.job_manager import list_jobs
    return [j for j in list_jobs() if own(j) and _translated(j)][:MAX_ENTRIES]


PREPARE_COMICS = 3  # comics whose CBZ is made in advance on each visit of the catalogue (newest first)
_PREPARING: set = set()


def _comics_to_prepare(jobs) -> list:
    """[(job, source PDF, file)] of the catalogue's newest comics whose EPUB or CBZ is missing or older than their
    translation (EPUB first: every KOReader opens it)."""
    from backend import main
    from backend.exporter import comic_file_outdated
    todo = []
    for job in [j for j in jobs if _is_comic(j)][:PREPARE_COMICS]:
        src = main.comic_source_pdf(job, OUTPUT_DIR / job.job_id)
        if src is None:
            continue
        for target in (src.with_suffix(".epub"), src.with_suffix(".cbz")):
            if (not target.is_file() or target.stat().st_mtime < src.stat().st_mtime
                    or (str(target) not in _PREPARING and comic_file_outdated(target))):
                todo.append((job, src, target))
    return todo


async def _prepare_comics(todo) -> None:
    """A comic's EPUB and CBZ are made from every page (seconds to a minute on a small server), more than an
    e-reader waits for a download to start: made now, one at a time, they are ready when the book is tapped."""
    from backend import main
    from backend.exporter import export_comic_archive, export_comic_epub
    for job, src, target in todo:
        if str(target) in _PREPARING:
            continue
        _PREPARING.add(str(target))
        try:
            if target.suffix == ".epub":
                await main.build_once(target, export_comic_epub, src, target, title=job.file_name or "Graphic Novel",
                                      reading_direction=getattr(job, "reading_direction", None) or "ltr")
            else:
                await main.build_once(target, export_comic_archive, src, target, format="cbz")
        except Exception as e:
            logger.warning(f"E-reader catalogue: {target.name} could not be made in advance: {e}")
        finally:
            _PREPARING.discard(str(target))


def _feed(token: str, own) -> str:
    base = f"/opds/{token}/"
    jobs = _catalogue_jobs(own)
    feed_id = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    updated = _iso(max((j.updated_at for j in jobs), default=0))
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/" '
        'xmlns:opds="http://opds-spec.org/2010/catalog">'
        f"<id>urn:bookapp:{feed_id}</id><title>BookApp</title><updated>{updated}</updated>"
        "<author><name>BookApp</name></author>"
        f'<link rel="self" href={quoteattr(base)} type="{FEED_TYPE}"/>'
        f'<link rel="start" href={quoteattr(base)} type="{FEED_TYPE}"/>'
    )
    return head + "".join(_entry(j, base) for j in jobs) + "</feed>"


@router.get("/opds/{token}")
@router.get("/opds/{token}/")
async def opds_catalogue(token: str):
    from backend.request_context import reset_current_user
    ctx, own = _catalogue_user(token)
    try:
        body = await asyncio.to_thread(_feed, token, own)
        todo = await asyncio.to_thread(lambda: _comics_to_prepare(_catalogue_jobs(own)))
    finally:
        reset_current_user(ctx)
    if todo:
        asyncio.ensure_future(_prepare_comics(todo))
    return Response(content=body, media_type=FEED_TYPE)


@router.get("/opds/{token}/book/{job_id}/{kind}/{filename}")
@router.get("/opds/{token}/book/{job_id}/{kind}")  # the links of earlier versions, without a file name
async def opds_book(request: Request, token: str, job_id: str, kind: str, filename: Optional[str] = None):
    """A book of the catalogue, made in the asked format on demand (as the app's own downloads are). The file name
    at the end of the link is for the reader app only."""
    from backend import main
    from backend.job_manager import get_job
    from backend.request_context import can_view_owner, reset_current_user
    _validate_job_id(job_id)
    ctx, own = _catalogue_user(token)
    try:
        job = get_job(job_id)
        if not job or not can_view_owner(job.owner) or not own(job) or not _translated(job):
            raise HTTPException(404, "Not found.")
        allowed = {k for k, _, _ in (COMIC_FORMATS if _is_comic(job) else BOOK_FORMATS)}
        if kind not in allowed:
            raise HTTPException(404, "Not found.")
        if kind == "bilingual-epub":
            return await main.download_bilingual(job_id, format="epub")
        return await main.download_output(request, job_id, format=kind, layout=None)
    finally:
        reset_current_user(ctx)


@router.get("/opds/{token}/cover/{job_id}")
async def opds_cover(token: str, job_id: str):
    from backend import main
    from backend.job_manager import get_job
    from backend.request_context import can_view_owner, reset_current_user
    _validate_job_id(job_id)
    ctx, own = _catalogue_user(token)
    try:
        job = get_job(job_id)
        if not job or not can_view_owner(job.owner) or not own(job):
            raise HTTPException(404, "Not found.")
        return await main.get_cover_image(job_id)
    finally:
        reset_current_user(ctx)
