"""
backend/api/sync.py - The reading-position sync server for KOReader and Readest (the "kosync" protocol), at /kosync.

In the app: Custom sync server = http(s)://<server>/kosync, then Login with the BookApp user name and the sync password
made in 📲 Devices. These paths are open (reading apps cannot sign in to BookApp): each request names its user in
x-auth-user and proves it with x-auth-key, the MD5 of the sync password (backend/reading_sync.py).

  GET  /kosync/users/auth                 -> 200 {"authorized": "OK"} | 401
  POST /kosync/users/create               -> 201 for the account's own user name and password, else 402
  PUT  /kosync/syncs/progress             {document, progress, percentage, device, device_id} -> 200 {document, timestamp}
  GET  /kosync/syncs/progress/<document>  -> 200 the last position, or {} when there is none
  GET  /kosync/healthcheck                -> 200 {"state": "OK"}
"""

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_DOCUMENT_RE = re.compile(r"[0-9A-Za-z_-]{1,64}")
_METHODS = ["GET", "PUT", "POST"]


def _error(status: int, code: int, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


def _unauthorized() -> JSONResponse:
    return _error(401, 2001, "Unauthorized")


def sync_owner(username: Optional[str], key: Optional[str]) -> Optional[str]:
    """The BookApp user a request syncs for ("" with accounts off), or None when its user name or key is wrong."""
    from backend import auth, reading_sync
    name = (username or "").strip()
    if not name or not key or len(name) > 64:
        return None
    if auth.is_enabled():
        user = auth.get_user_by_name(name)
        if not user or user.get("disabled"):
            return None
        owner = user["id"]
    else:
        owner = ""
    return owner if reading_sync.check_key(owner, key) else None


async def _body(request: Request) -> Optional[dict]:
    raw = await request.body()
    if len(raw) > 64 * 1024:
        return None
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


@router.api_route("/kosync", methods=_METHODS)
@router.api_route("/kosync/{rest:path}", methods=_METHODS)
async def kosync(request: Request, rest: str = ""):
    from backend import reading_sync
    path = "/".join(p for p in rest.split("/") if p)  # a server address written with a trailing "/" sends "//users"
    method = request.method
    if path in ("", "healthcheck") and method == "GET":
        return JSONResponse({"state": "OK"})
    headers = request.headers
    user, key = headers.get("x-auth-user"), headers.get("x-auth-key")

    if path == "users/create" and method == "POST":
        # Accounts are made in BookApp: "Register" in the app succeeds only for the account it already is
        data = await _body(request) or {}
        owner = await asyncio.to_thread(sync_owner, str(data.get("username") or ""), str(data.get("password") or ""))
        if owner is None:
            return _error(402, 2002, "Make the sync password in BookApp (Devices), then use Login.")
        return JSONResponse({"username": str(data.get("username"))}, status_code=201)

    owner = await asyncio.to_thread(sync_owner, user, key)
    if owner is None:
        return _unauthorized()

    if path == "users/auth" and method == "GET":
        return JSONResponse({"authorized": "OK"})

    if path == "syncs/progress" and method == "PUT":
        data = await _body(request)
        if data is None:
            return _error(403, 2003, "Invalid request")
        document = str(data.get("document") or "")
        if not _DOCUMENT_RE.fullmatch(document):
            return _error(403, 2004, "Field 'document' not provided.")
        try:
            percentage = min(max(float(data.get("percentage") or 0), 0.0), 1.0)
        except (TypeError, ValueError):
            return _error(403, 2003, "Invalid request")
        progress = str(data.get("progress") if data.get("progress") is not None else "")[:2000]
        device = str(data.get("device") or "")[:100]
        device_id = str(data.get("device_id") or "")[:100]
        stamp = await asyncio.to_thread(reading_sync.save_progress, owner, document, progress, percentage,
                                        device, device_id)
        return JSONResponse({"document": document, "timestamp": int(stamp)})

    if path.startswith("syncs/progress/") and method == "GET":
        document = path[len("syncs/progress/"):]
        if not _DOCUMENT_RE.fullmatch(document):
            return _error(403, 2004, "Field 'document' not provided.")
        found = await asyncio.to_thread(reading_sync.get_progress, owner, document)
        if not found:
            return JSONResponse({})
        return JSONResponse({"document": document, "progress": found.get("progress") or "",
                             "percentage": found.get("percentage") or 0, "device": found.get("device") or "",
                             "device_id": found.get("device_id") or "", "timestamp": int(found.get("timestamp") or 0)})

    return _error(404, 2000, "Not found")
