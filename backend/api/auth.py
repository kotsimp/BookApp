"""
backend/api/auth.py - Sign-in, first-time setup and user management (user accounts mode, BOOKAPP_AUTH=1).

The login guard in backend/main.py protects everything else; it also refuses the /api/auth/users* and
/api/auth/audit endpoints to non-administrators (checked here again as defence in depth).
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from backend import auth
from backend.request_context import current_user

router = APIRouter()

_LOGIN_PAGE = Path(__file__).resolve().parent.parent.parent / "frontend" / "login.html"
_ZERO_USAGE = {"requests": 0, "cached": 0, "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    remember: bool = True


class SetupRequest(BaseModel):
    code: str = ""
    username: str = ""
    password: str = ""
    remember: bool = True


class ChangePasswordRequest(BaseModel):
    current_password: str = ""
    new_password: str = ""


class CreateUserRequest(BaseModel):
    username: str = ""
    role: str = "user"
    password: Optional[str] = None  # empty -> a temporary password is generated


class RoleRequest(BaseModel):
    role: str


class DisabledRequest(BaseModel):
    disabled: bool


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _ua(request: Request) -> str:
    return request.headers.get("user-agent", "")


def _err(e: auth.AuthError) -> HTTPException:
    return HTTPException(e.http_status, detail=e.user_message)


def _require_enabled() -> None:
    if not auth.is_enabled():
        raise HTTPException(404, "User accounts are not enabled on this server (BOOKAPP_AUTH=1).")


def _me() -> Dict[str, Any]:
    _require_enabled()
    user = current_user()
    if not user:
        raise HTTPException(401, "Συνδεθείτε για να συνεχίσετε.")
    return user


def _admin() -> Dict[str, Any]:
    user = _me()
    if user.get("role") != "admin":
        raise HTTPException(403, "Μόνο οι διαχειριστές έχουν πρόσβαση σε αυτή τη λειτουργία.")
    return user


def set_session_cookie(response, request: Request, token: str, persistent: bool) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.REMEMBER_SECONDS if persistent else None,  # None: ends when the browser closes
        httponly=True, samesite="lax", secure=auth.cookie_secure(request.url.scheme), path="/",
    )


def _signed_in_response(request: Request, user: Dict[str, Any], token: str, persistent: bool) -> JSONResponse:
    resp = JSONResponse({"status": "ok", "user": user, "must_change": bool(user.get("must_change"))})
    set_session_cookie(resp, request, token, persistent)
    return resp


# ---------------------------------------------------------------------------
# Pages & sign-in (reachable without a session)
# ---------------------------------------------------------------------------

@router.get("/login")
async def login_page():
    """Sign-in page (also: forced change of a temporary password)."""
    if not auth.is_enabled():
        return RedirectResponse("/", status_code=303)
    return FileResponse(str(_LOGIN_PAGE), media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/setup")
async def setup_page():
    """First-time setup page: create the first administrator with the setup code from the server log."""
    if not auth.is_enabled():
        return RedirectResponse("/", status_code=303)
    return FileResponse(str(_LOGIN_PAGE), media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/api/auth/status")
async def auth_status(request: Request):
    """Whether accounts are on, whether first-time setup is pending, and who is signed in (if anyone)."""
    if not auth.is_enabled():
        return {"enabled": False, "setup_required": False, "user": None}
    token = request.cookies.get(auth.SESSION_COOKIE)
    session = await asyncio.to_thread(auth.session_for_token, token) if token else None
    setup = False if session else await asyncio.to_thread(auth.setup_required)
    if setup:
        await asyncio.to_thread(auth.ensure_setup_code)
    return {
        "enabled": True,
        "setup_required": setup,
        "user": session["user"] if session else None,
        "remember_days": auth.REMEMBER_SECONDS // 86400,
        "min_password_length": auth.MIN_PASSWORD_LEN,
    }


@router.post("/api/auth/setup")
async def auth_setup(req: SetupRequest, request: Request):
    """Creates the first administrator (only while no account exists, with the one-time setup code)."""
    _require_enabled()
    try:
        user = await asyncio.to_thread(auth.complete_setup, req.code, req.username, req.password, _ip(request))
        token = await asyncio.to_thread(auth.create_session, user["id"], req.remember, _ua(request), _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return _signed_in_response(request, user, token, req.remember)


@router.post("/api/auth/login")
async def auth_login(req: LoginRequest, request: Request):
    _require_enabled()
    try:
        user = await asyncio.to_thread(auth.authenticate, req.username, req.password, _ip(request))
        token = await asyncio.to_thread(auth.create_session, user["id"], req.remember, _ua(request), _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return _signed_in_response(request, user, token, req.remember)


@router.post("/api/auth/logout")
async def auth_logout(request: Request):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if auth.is_enabled() and token:
        await asyncio.to_thread(auth.revoke_session, token)
    resp = JSONResponse({"status": "signed_out"})
    resp.delete_cookie(auth.SESSION_COOKIE, path="/", httponly=True, samesite="lax",
                       secure=auth.cookie_secure(request.url.scheme))
    return resp


# ---------------------------------------------------------------------------
# The signed-in user
# ---------------------------------------------------------------------------

@router.get("/api/auth/me")
async def auth_me():
    user = _me()
    from backend.ai_polisher import get_daily_gemini_usage_by_user
    return {"user": user, "gemini_usage_today": get_daily_gemini_usage_by_user().get(user["id"], dict(_ZERO_USAGE))}


@router.post("/api/auth/change-password")
async def auth_change_password(req: ChangePasswordRequest, request: Request):
    """Changes the own password; every other session of this user is signed out."""
    user = _me()
    try:
        await asyncio.to_thread(auth.change_own_password, user, req.current_password, req.new_password,
                                request.cookies.get(auth.SESSION_COOKIE), _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------

@router.get("/api/auth/users")
async def auth_list_users():
    me = _admin()
    from backend.ai_polisher import get_daily_gemini_usage_by_user
    from backend.job_manager import list_jobs
    users = await asyncio.to_thread(auth.list_users)
    usage = get_daily_gemini_usage_by_user()
    jobs_per_owner: Dict[str, int] = {}
    known = {u["id"] for u in users}
    for j in list_jobs():
        owner = j.owner if j.owner in known else ""
        jobs_per_owner[owner] = jobs_per_owner.get(owner, 0) + 1
    for u in users:
        u["gemini_usage_today"] = usage.get(u["id"], dict(_ZERO_USAGE))
        u["jobs"] = jobs_per_owner.get(u["id"], 0)
    return {"users": users, "me": me["id"], "unowned_jobs": jobs_per_owner.get("", 0)}


@router.post("/api/auth/users")
async def auth_create_user(req: CreateUserRequest, request: Request):
    """Creates a user; the user must choose an own password at the first sign-in."""
    me = _admin()
    generated = not (req.password or "").strip()
    password = auth.generate_temporary_password() if generated else req.password
    try:
        user = await asyncio.to_thread(auth.create_user, req.username, password, (req.role or "user").strip(),
                                       True, me, _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return {"user": user, "temporary_password": password if generated else None}


@router.post("/api/auth/users/{user_id}/role")
async def auth_set_role(user_id: str, req: RoleRequest, request: Request):
    """Makes a user an administrator (same rights as you) or removes administrator rights."""
    me = _admin()
    try:
        user = await asyncio.to_thread(auth.set_role, me, user_id, (req.role or "").strip(), _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return {"user": user}


@router.post("/api/auth/users/{user_id}/disabled")
async def auth_set_disabled(user_id: str, req: DisabledRequest, request: Request):
    """Disables (signs out immediately) or re-enables an account."""
    me = _admin()
    try:
        user = await asyncio.to_thread(auth.set_disabled, me, user_id, req.disabled, _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return {"user": user}


@router.post("/api/auth/users/{user_id}/reset-password")
async def auth_reset_password(user_id: str, request: Request):
    """A new temporary password (shown once); the user is signed out everywhere and must change it."""
    me = _admin()
    try:
        temp = await asyncio.to_thread(auth.admin_reset_password, me, user_id, _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return {"temporary_password": temp}


@router.post("/api/auth/users/{user_id}/sign-out")
async def auth_sign_out_everywhere(user_id: str, request: Request):
    me = _admin()
    try:
        n = await asyncio.to_thread(auth.sign_out_everywhere, me, user_id, _ip(request))
    except auth.AuthError as e:
        raise _err(e)
    return {"signed_out_sessions": n}


@router.delete("/api/auth/users/{user_id}")
async def auth_delete_user(user_id: str, request: Request, jobs: str = "transfer"):
    """Deletes an account. jobs=transfer gives its jobs to you; jobs=delete removes them with their files."""
    me = _admin()
    if jobs not in ("transfer", "delete"):
        raise HTTPException(400, "jobs must be 'transfer' or 'delete'.")
    try:
        deleted = await asyncio.to_thread(auth.delete_user, me, user_id, _ip(request), f"jobs: {jobs}")
    except auth.AuthError as e:
        raise _err(e)
    from backend.job_manager import list_jobs, update_job
    from backend.api.common import purge_job
    owned = [j.job_id for j in list_jobs() if j.owner == user_id]
    for jid in owned:
        if jobs == "delete":
            purge_job(jid)
        else:
            update_job(jid, owner=me["id"])
    return {"deleted": deleted, "jobs": jobs, "job_count": len(owned)}


@router.get("/api/auth/audit")
async def auth_audit_log(limit: int = 100):
    """Recent administrative actions (newest first)."""
    _admin()
    return {"entries": await asyncio.to_thread(auth.list_audit, limit)}
