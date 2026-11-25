"""
connections.py - The links to the user's other devices.

/api/connections...  the 📲 Devices window (signed in): the e-reader catalogue link and phone notifications.
/opds/<token>/...    the e-reader catalogue (OPDS 1.2): finished translations for reading apps (KOReader, Moon+ Reader,
                     Librera, Panels…). The secret token in the path is the pass, since these apps cannot sign in.
"""

import asyncio
import datetime
import hashlib
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from backend.api.common import OUTPUT_DIR, _validate_job_id

router = APIRouter()

FEED_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
MAX_ENTRIES = 300
# what each kind of book offers: (link name, media type, title)
BOOK_FORMATS = (("epub", "application/epub+zip", "EPUB"), ("pdf", "application/pdf", "PDF"),
                ("bilingual-epub", "application/epub+zip", "Δίγλωσσο EPUB · Bilingual EPUB"))
COMIC_FORMATS = (("cbz", "application/vnd.comicbook+zip", "CBZ"), ("pdf", "application/pdf", "PDF"))


def _owner() -> str:
    from backend.request_context import current_user_id
    return current_user_id()


class NtfyRequest(BaseModel):
    server: Optional[str] = None
    topic: Optional[str] = None
    app_url: Optional[str] = None
    lang: Optional[str] = None


@router.get("/api/connections")
async def connections_status():
    """The signed-in user's e-reader link (whether one exists; it is shown only when made) and notifications."""
    from backend.connections import ntfy_settings, opds_status
    return {"opds": opds_status(_owner()), "ntfy": ntfy_settings(_owner())}


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


def _checked_ntfy(req: NtfyRequest) -> tuple[str, str]:
    from backend.notify import TOPIC_RE, normalize_server
    server = normalize_server(req.server or "")
    if not server:
        raise HTTPException(400, "The ntfy server must be an address such as https://ntfy.sh.")
    topic = (req.topic or "").strip()
    if topic and not TOPIC_RE.fullmatch(topic):
        raise HTTPException(400, "The topic name: 6–64 Latin letters, digits, - or _.")
    return server, topic


@router.post("/api/connections/ntfy")
async def connections_save_ntfy(req: NtfyRequest):
    """Saves the phone notifications (an empty topic turns them off)."""
    from backend.connections import set_ntfy
    server, topic = _checked_ntfy(req)
    app_url = (req.app_url or "").strip()
    if app_url and not app_url.startswith(("http://", "https://")):
        app_url = ""
    return await asyncio.to_thread(set_ntfy, _owner(), server, topic, app_url[:300], (req.lang or "el").lower())


@router.post("/api/connections/ntfy/test")
async def connections_test_ntfy(req: NtfyRequest):
    """Sends a test message to the given server and topic, and says whether it went."""
    from backend.notify import send, texts
    server, topic = _checked_ntfy(req)
    if not topic:
        raise HTTPException(400, "Write a topic name first.")
    t = texts(req.lang or "el")
    try:
        await asyncio.to_thread(send, server, topic, t["test_title"], t["test_body"])
    except Exception as e:
        raise HTTPException(502, f"ntfy did not accept the message: {str(e)[:200]}")
    return {"status": "sent"}


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

def _catalogue_user(token: str):
    """Opens the catalogue as the token's user for this request (job visibility); 404 for anything else."""
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
        return set_current_user({"id": user["id"], "username": user["username"], "role": user["role"]})
    return set_current_user(None)


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts or 0, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_comic(job) -> bool:
    return (job.layout_mode or "") == "comic" or (job.file_type or "") in ("cbz", "cbr", "zip")


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
        f"<content type=\"text\">{escape(langs)}</content>",
    ]
    cover_known = (OUTPUT_DIR / job.job_id / "cover_image.jpg").is_file() or (job.file_type or "") in ("pdf", "epub")
    if cover_known:
        href = quoteattr(f"{base}cover/{job.job_id}")
        parts.append(f'<link rel="http://opds-spec.org/image" href={href} type="image/jpeg"/>')
        parts.append(f'<link rel="http://opds-spec.org/image/thumbnail" href={href} type="image/jpeg"/>')
    for kind, media, label in (COMIC_FORMATS if _is_comic(job) else BOOK_FORMATS):
        href = quoteattr(f"{base}book/{job.job_id}/{kind}")
        parts.append(f'<link rel="http://opds-spec.org/acquisition" href={href} type="{media}" title={quoteattr(label)}/>')
    parts.append("</entry>")
    return "".join(parts)


def _feed(token: str) -> str:
    from backend.job_manager import list_jobs
    base = f"/opds/{token}/"
    jobs = [j for j in list_jobs() if j.mode == "translate" and j.status == "done" and j.output_path][:MAX_ENTRIES]
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
    ctx = _catalogue_user(token)
    try:
        body = await asyncio.to_thread(_feed, token)
    finally:
        reset_current_user(ctx)
    return Response(content=body, media_type=FEED_TYPE)


@router.get("/opds/{token}/book/{job_id}/{kind}")
async def opds_book(request: Request, token: str, job_id: str, kind: str):
    """A book of the catalogue, made in the asked format on demand (as the app's own downloads are)."""
    from backend import main
    from backend.job_manager import get_job
    from backend.request_context import can_view_owner, reset_current_user
    _validate_job_id(job_id)
    ctx = _catalogue_user(token)
    try:
        job = get_job(job_id)
        if not job or not can_view_owner(job.owner) or job.status != "done":
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
    ctx = _catalogue_user(token)
    try:
        job = get_job(job_id)
        if not job or not can_view_owner(job.owner):
            raise HTTPException(404, "Not found.")
        return await main.get_cover_image(job_id)
    finally:
        reset_current_user(ctx)
