"""
request_context.py - Who is making the current request (user accounts mode, BOOKAPP_AUTH=1).

The login guard in backend/main.py sets the signed-in user for the duration of a request; asyncio tasks started from
that request (translation pipelines, Book Insights tasks) inherit it. Code that serves every user — the batch queue
processor — runs in a fresh context, where there is no current user and every job is visible.
"""

import contextvars
from typing import Any, Dict, Optional

_CURRENT_USER: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("bookapp_user", default=None)


def current_user() -> Optional[Dict[str, Any]]:
    """The signed-in user ({id, username, role, ...}) or None (accounts off, or background work for all users)."""
    return _CURRENT_USER.get()


def current_user_id() -> str:
    user = _CURRENT_USER.get()
    return str(user.get("id") or "") if user else ""


def set_current_user(user: Optional[Dict[str, Any]]) -> contextvars.Token:
    return _CURRENT_USER.set(user)


def reset_current_user(token: contextvars.Token) -> None:
    _CURRENT_USER.reset(token)


def can_view_owner(owner: Optional[str]) -> bool:
    """
    Whether the current requester may see a job owned by `owner`.
    No user in context (accounts off / background processing) and admins see everything; a user sees own jobs.
    Jobs without an owner (created before accounts were switched on) belong to the administrators.
    """
    user = _CURRENT_USER.get()
    if not user or user.get("role") == "admin":
        return True
    return bool(owner) and owner == user.get("id")
