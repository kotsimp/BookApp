"""
connections.py - Each user's links to their other devices.

* The e-reader catalogue (OPDS): a secret link, /opds/<token>/, that reading apps (KOReader, Moon+ Reader, Panels…)
  open without signing in. Only the token's SHA-256 is kept: the link is shown once, when made, and making a new one
  stops the old one.
* Phone notifications (ntfy): the ntfy server and topic a finished job is announced to.

Stored in data/connections.json, by user id ("" when user accounts are off).
"""

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

STORE = Path(__file__).resolve().parent.parent / "data" / "connections.json"
DEFAULT_NTFY_SERVER = "https://ntfy.sh"
_lock = threading.RLock()


def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"connections.json unreadable, starting empty: {e}")
        return {}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_name(f".{STORE.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STORE)
    finally:
        tmp.unlink(missing_ok=True)


def _user(data: dict, owner: str) -> dict:
    return data.setdefault(owner or "", {})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── E-reader catalogue (OPDS) ──

def opds_status(owner: str) -> dict[str, Any]:
    with _lock:
        link = _load().get(owner or "", {}).get("opds") or {}
    return {"exists": bool(link.get("hash")), "created": link.get("created")}


def new_opds_token(owner: str) -> str:
    """A new secret link for `owner`; the previous one stops working."""
    token = secrets.token_urlsafe(24)
    with _lock:
        data = _load()
        _user(data, owner)["opds"] = {"hash": _hash(token), "created": time.time()}
        _save(data)
    return token


def remove_opds_token(owner: str) -> None:
    with _lock:
        data = _load()
        if (data.get(owner or "") or {}).pop("opds", None) is not None:
            _save(data)


def owner_for_opds_token(token: str) -> Optional[str]:
    """The user whose catalogue `token` opens ("" with accounts off), or None for an unknown token."""
    if not token or len(token) > 100:
        return None
    wanted = _hash(token)
    with _lock:
        data = _load()
    for owner, entry in data.items():
        stored = ((entry or {}).get("opds") or {}).get("hash", "")
        if stored and secrets.compare_digest(stored, wanted):
            return owner
    return None


# ── Phone notifications (ntfy) ──

def ntfy_settings(owner: str) -> dict[str, Any]:
    with _lock:
        n = dict(_load().get(owner or "", {}).get("ntfy") or {})
    return {"server": n.get("server") or DEFAULT_NTFY_SERVER, "topic": n.get("topic") or "",
            "app_url": n.get("app_url") or "", "lang": n.get("lang") or "el", "enabled": bool(n.get("topic"))}


def set_ntfy(owner: str, server: str, topic: str, app_url: str = "", lang: str = "el") -> dict[str, Any]:
    with _lock:
        data = _load()
        if topic:
            _user(data, owner)["ntfy"] = {"server": server or DEFAULT_NTFY_SERVER, "topic": topic, "app_url": app_url,
                                          "lang": "en" if lang == "en" else "el"}
        else:
            (data.get(owner or "") or {}).pop("ntfy", None)
        _save(data)
    return ntfy_settings(owner)
