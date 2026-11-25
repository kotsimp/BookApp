"""
device_pairing.py - Optional password-free device pairing (opt-in: BOOKAPP_PAIRING=1).

When enabled, only *trusted* clients can use the app:
* the host computer itself (loopback 127.0.0.1 / ::1) — unless BOOKAPP_TRUST_LOOPBACK=0, which is required behind a
  reverse proxy on the same machine (there every request appears to come from loopback);
* devices that opened a one-time pairing link once (`/pair?code=...`), which stores a long-lived HttpOnly cookie.

There is no password. Pairing codes are single-use and expire after PAIRING_CODE_TTL seconds. Only SHA-256 hashes of
device tokens are stored (config/settings.json, key 'paired_devices'); devices can be listed and revoked.
When pairing is disabled (default) nothing changes.
"""

import os
import time
import hmac
import secrets
import hashlib
import logging
import threading
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

COOKIE_NAME = "bookapp_device"
COOKIE_MAX_AGE = 365 * 24 * 3600
PAIRING_CODE_TTL = 15 * 60
MAX_DEVICES = 50
OPEN_PATHS = ("/api/health", "/pair")          # reachable without pairing (health checks, the pairing link itself)

_lock = threading.RLock()
_codes: Dict[str, float] = {}                 # sha256(code) -> expiry timestamp


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def is_enabled() -> bool:
    """On with BOOKAPP_PAIRING=1 - unless user accounts (BOOKAPP_AUTH=1) are on, which replace pairing."""
    if _truthy(os.environ.get("BOOKAPP_AUTH")):
        return False
    return _truthy(os.environ.get("BOOKAPP_PAIRING"))


def trust_loopback() -> bool:
    v = os.environ.get("BOOKAPP_TRUST_LOOPBACK")
    return True if v is None or v.strip() == "" else _truthy(v)


def is_loopback(host: Optional[str]) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost") or h.startswith("127.")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_devices() -> List[Dict[str, Any]]:
    from backend.settings_manager import get_setting
    devs = get_setting("paired_devices", []) or []
    return [d for d in devs if isinstance(d, dict) and d.get("token_hash")]


def _save_devices(devs: List[Dict[str, Any]]) -> None:
    from backend.settings_manager import save_setting
    save_setting("paired_devices", devs[-MAX_DEVICES:])


# ---------------------------------------------------------------------------
# Pairing codes
# ---------------------------------------------------------------------------

def create_pairing_code() -> str:
    """Creates a one-time pairing code (valid PAIRING_CODE_TTL seconds)."""
    code = secrets.token_urlsafe(18)
    now = time.time()
    with _lock:
        for h, exp in list(_codes.items()):
            if exp < now:
                _codes.pop(h, None)
        _codes[_hash(code)] = now + PAIRING_CODE_TTL
    return code


def redeem_pairing_code(code: str, device_name: str = "") -> Optional[str]:
    """Consumes a valid code and registers a new device. Returns the device token (cookie value) or None."""
    if not code:
        return None
    h = _hash(code)
    now = time.time()
    with _lock:
        exp = _codes.pop(h, None)
        if not exp or exp < now:
            return None
        token = secrets.token_urlsafe(32)
        devs = _load_devices()
        devs.append({
            "id": secrets.token_hex(6),
            "name": (device_name or "Device")[:80],
            "token_hash": _hash(token),
            "created_at": now,
            "last_seen": now,
        })
        _save_devices(devs)
    logger.info(f"[Pairing] New device paired: {device_name[:40]!r}")
    return token


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def device_for_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    th = _hash(token)
    for d in _load_devices():
        if hmac.compare_digest(d["token_hash"], th):
            return d
    return None


def touch_device(device_id: str) -> None:
    """Updates last_seen at most once per hour (avoids rewriting settings on every request)."""
    now = time.time()
    with _lock:
        devs = _load_devices()
        for d in devs:
            if d.get("id") == device_id and now - float(d.get("last_seen", 0)) > 3600:
                d["last_seen"] = now
                _save_devices(devs)
                return


def list_devices() -> List[Dict[str, Any]]:
    return [{k: d.get(k) for k in ("id", "name", "created_at", "last_seen")} for d in _load_devices()]


def revoke_device(device_id: str) -> bool:
    with _lock:
        devs = _load_devices()
        kept = [d for d in devs if d.get("id") != device_id]
        if len(kept) == len(devs):
            return False
        _save_devices(kept)
    logger.info(f"[Pairing] Device revoked: {device_id}")
    return True


# ---------------------------------------------------------------------------
# Request authorisation
# ---------------------------------------------------------------------------

def is_trusted(client_host: Optional[str], cookie_token: Optional[str]) -> bool:
    if not is_enabled():
        return True
    if trust_loopback() and is_loopback(client_host):
        return True
    dev = device_for_token(cookie_token)
    if dev:
        touch_device(dev["id"])
        return True
    return False


def is_open_path(path: str) -> bool:
    # the e-reader catalogue checks its own secret link: a reading app cannot be paired (api/connections.py)
    return any(path == p or path.startswith(p + "?") for p in OPEN_PATHS) or path.startswith("/opds/")


NOT_PAIRED_HTML = """<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>BookApp — μη συνδεδεμένη συσκευή</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0d1a;color:#f0f2ff;display:flex;min-height:100vh;
align-items:center;justify-content:center;margin:0;padding:16px}main{max-width:520px;background:#141728;
border:1px solid #2a2f4a;border-radius:14px;padding:28px;line-height:1.55}h1{font-size:1.25rem;margin:0 0 12px}
code{background:#22263d;padding:2px 6px;border-radius:6px}</style></head><body><main>
<h1>🔒 Αυτή η συσκευή δεν είναι συνδεδεμένη με το BookApp</h1>
<p>Για να τη χρησιμοποιήσετε, ανοίξτε σε αυτή τη συσκευή έναν <strong>σύνδεσμο σύζευξης</strong>.</p>
<p>Θα τον βρείτε στον υπολογιστή όπου τρέχει το BookApp: <em>🔑 Gemini API Key → Συσκευές → Δημιουργία συνδέσμου</em>,
ή στο αρχείο καταγραφής του διακομιστή κατά την εκκίνηση.</p>
<p style="opacity:.7;font-size:.9em">This device is not paired with BookApp. Open a pairing link created on the computer
that runs BookApp.</p></main></body></html>"""
