"""
test_device_pairing.py - Opt-in password-free device pairing (backend/device_pairing.py).

Covers: disabled = no change; unpaired clients blocked (JSON for API, HTML page otherwise) while /api/health stays
open; one-time code -> HttpOnly cookie -> access; code reuse and expiry rejected; links created from a trusted device;
device list and revocation (revoked cookie stops working); only token hashes stored; loopback trust on/off.
Uses an in-process server on a private port; user settings are snapshotted and restored.
"""

import sys
sys.path.insert(0, ".")
import os
import json
import time
import socket
import threading
import unittest
import http.client
import urllib.parse
from unittest import mock

from backend import device_pairing as dp
from backend.settings_manager import load_settings, save_settings, get_setting

_PORT = None


def _start():
    global _PORT
    if _PORT:
        return
    import uvicorn
    from backend.main import app
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _PORT = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error", lifespan="off"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        try:
            c = http.client.HTTPConnection("127.0.0.1", _PORT, timeout=1)
            c.request("GET", "/api/health")
            c.getresponse().read()
            return
        except Exception:
            time.sleep(0.1)


def req(method, path, cookie=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", _PORT, timeout=10)
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; test)"}
    if cookie:
        headers["Cookie"] = f"{dp.COOKIE_NAME}={cookie}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body)
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse()
    data = r.read().decode("utf-8", "replace")
    return r.status, dict(r.getheaders()), data


def cookie_from(headers):
    sc = headers.get("set-cookie") or headers.get("Set-Cookie") or ""
    part = sc.split(";")[0]
    return part.split("=", 1)[1] if part.startswith(dp.COOKIE_NAME + "=") else None, sc


class TestDevicePairing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _start()

    def setUp(self):
        self._snap = load_settings()
        self._env = {k: os.environ.get(k) for k in ("BOOKAPP_PAIRING", "BOOKAPP_TRUST_LOOPBACK")}

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        save_settings(self._snap)

    def _enable(self, trust_loopback=False):
        os.environ["BOOKAPP_PAIRING"] = "1"
        os.environ["BOOKAPP_TRUST_LOOPBACK"] = "1" if trust_loopback else "0"

    def _pair(self):
        code = dp.create_pairing_code()
        st, h, _ = req("GET", f"/pair?code={urllib.parse.quote(code)}")
        self.assertEqual(st, 303)
        token, raw = cookie_from(h)
        self.assertTrue(token, raw)
        return code, token, raw

    def test_disabled_is_a_no_op(self):
        os.environ.pop("BOOKAPP_PAIRING", None)
        self.assertEqual(req("GET", "/api/settings")[0], 200)
        self.assertEqual(req("GET", "/")[0], 200)
        st, h, _ = req("GET", "/pair?code=whatever")
        self.assertEqual(st, 303)
        self.assertFalse(json.loads(req("GET", "/api/pairing")[2])["enabled"])

    def test_unpaired_client_is_blocked(self):
        self._enable()
        st, _, body = req("GET", "/api/settings")
        self.assertEqual(st, 403)
        self.assertIn("not paired", json.loads(body)["detail"])
        st2, h2, html = req("GET", "/")
        self.assertEqual(st2, 403)
        self.assertIn("δεν είναι συνδεδεμένη", html)
        self.assertEqual(req("GET", "/api/health")[0], 200, "health checks stay open")
        self.assertEqual(req("POST", "/api/pairing/links")[0], 403, "untrusted clients cannot mint links")

    def test_pairing_link_grants_access_once(self):
        self._enable()
        code, token, raw = self._pair()
        self.assertIn("HttpOnly", raw)
        self.assertIn("SameSite=lax", raw.replace("Lax", "lax"))
        self.assertEqual(req("GET", "/api/settings", cookie=token)[0], 200)
        self.assertEqual(req("GET", "/", cookie=token)[0], 200)
        st, h, body = req("GET", f"/pair?code={urllib.parse.quote(code)}")
        self.assertEqual(st, 403, "a pairing code is single-use")
        self.assertIn("έληξε", body)
        self.assertEqual(req("GET", "/api/settings", cookie="forged-token")[0], 403)

    def test_expired_code_is_rejected(self):
        self._enable()
        code = dp.create_pairing_code()
        with mock.patch("backend.device_pairing.time.time", return_value=time.time() + dp.PAIRING_CODE_TTL + 5):
            self.assertIsNone(dp.redeem_pairing_code(code))

    def test_trusted_device_creates_links_lists_and_revokes(self):
        self._enable()
        _, token, _ = self._pair()
        st, _, body = req("POST", "/api/pairing/links", cookie=token)
        self.assertEqual(st, 200)
        link = json.loads(body)["url"]
        self.assertIn("/pair?code=", link)
        code2 = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)["code"][0]
        st2, h2, _ = req("GET", f"/pair?code={urllib.parse.quote(code2)}")
        token2, _ = cookie_from(h2)
        self.assertTrue(token2)

        status = json.loads(req("GET", "/api/pairing", cookie=token)[2])
        self.assertTrue(status["enabled"])
        self.assertFalse(status["is_host"])
        ids = [d["id"] for d in status["devices"]]
        self.assertIn(status["this_device_id"], ids)
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(d["name"] == "iPhone" for d in status["devices"]))

        other = next(i for i in ids if i != status["this_device_id"])
        st3, _, _ = req("DELETE", f"/api/pairing/devices/{other}", cookie=token)
        self.assertEqual(st3, 200)
        self.assertEqual(req("GET", "/api/settings", cookie=token2)[0], 403, "revoked device loses access")
        self.assertEqual(req("GET", "/api/settings", cookie=token)[0], 200)
        self.assertEqual(req("DELETE", "/api/pairing/devices/zzzz", cookie=token)[0], 400)
        self.assertEqual(req("DELETE", f"/api/pairing/devices/{other}", cookie=token)[0], 404)

    def test_only_token_hashes_are_stored(self):
        self._enable()
        _, token, _ = self._pair()
        stored = json.dumps(get_setting("paired_devices", []))
        self.assertNotIn(token, stored)
        self.assertIn(dp._hash(token), stored)

    def test_loopback_trust(self):
        self._enable(trust_loopback=True)
        self.assertEqual(req("GET", "/api/settings")[0], 200, "the host computer works without pairing")
        self.assertTrue(json.loads(req("GET", "/api/pairing")[2])["is_host"])
        os.environ["BOOKAPP_TRUST_LOOPBACK"] = "0"   # behind a same-machine reverse proxy
        self.assertEqual(req("GET", "/api/settings")[0], 403)


if __name__ == "__main__":
    unittest.main()
