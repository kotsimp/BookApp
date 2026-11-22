"""
backend/api/pairing.py - Device pairing endpoints (APIRouter included by backend.main).
"""

import re
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Device pairing (opt-in password-free access control) — backend/device_pairing.py
# ---------------------------------------------------------------------------

@router.get("/pair")
async def pair_device(request: Request, code: str = ""):
    """Redeems a one-time pairing link and remembers this device with a long-lived HttpOnly cookie."""
    from fastapi.responses import RedirectResponse, HTMLResponse
    from backend import device_pairing
    if not device_pairing.is_enabled():
        return RedirectResponse("/", status_code=303)
    ua = request.headers.get("user-agent", "")
    name = next((n for n in ("iPhone", "iPad", "Android", "Windows", "Macintosh", "Linux") if n in ua), "Device")
    token = device_pairing.redeem_pairing_code(code, device_name=name)
    if not token:
        return HTMLResponse(device_pairing.NOT_PAIRED_HTML.replace(
            "Αυτή η συσκευή δεν είναι συνδεδεμένη με το BookApp",
            "Ο σύνδεσμος σύζευξης έληξε ή έχει ήδη χρησιμοποιηθεί"), status_code=403)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(device_pairing.COOKIE_NAME, token, max_age=device_pairing.COOKIE_MAX_AGE, httponly=True,
                    samesite="lax", secure=request.url.scheme == "https", path="/")
    return resp


@router.get("/api/pairing")
async def pairing_status(request: Request):
    """Pairing on/off, whether this client is the host computer, and the paired devices."""
    from backend import device_pairing
    client = request.client.host if request.client else None
    current = device_pairing.device_for_token(request.cookies.get(device_pairing.COOKIE_NAME))
    return {
        "enabled": device_pairing.is_enabled(),
        "is_host": device_pairing.trust_loopback() and device_pairing.is_loopback(client),
        "this_device_id": current["id"] if current else None,
        "devices": device_pairing.list_devices() if device_pairing.is_enabled() else [],
    }


@router.post("/api/pairing/links")
async def create_pairing_link(request: Request):
    """Creates a one-time pairing link (only trusted clients reach this endpoint when pairing is on)."""
    from backend import device_pairing
    if not device_pairing.is_enabled():
        raise HTTPException(400, "Device pairing is not enabled (set BOOKAPP_PAIRING=1).")
    code = device_pairing.create_pairing_code()
    base = str(request.base_url).rstrip("/")
    return {"url": f"{base}/pair?code={code}", "expires_in_seconds": device_pairing.PAIRING_CODE_TTL}


@router.delete("/api/pairing/devices/{device_id}")
async def revoke_paired_device(device_id: str):
    from backend import device_pairing
    if not re.fullmatch(r"[0-9a-f]{12}", device_id or ""):
        raise HTTPException(400, "Invalid device id.")
    if not device_pairing.revoke_device(device_id):
        raise HTTPException(404, "Device not found.")
    return {"status": "revoked", "id": device_id}
