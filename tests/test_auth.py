"""
test_auth.py - Optional user accounts with administrators (backend/auth.py, BOOKAPP_AUTH=1).

Covers: accounts off = nothing changes; first administrator via the one-time setup code (log/file) or the
command line; scrypt hashes; password rules; 5-failure lockout; "keep me signed in" (60-day cookie that slides
forward) vs browser session; temporary passwords that must be changed; admin-only endpoints; users see only their own
jobs (history, status, downloads, queue, clean-up) while admins see all with a filter; promote/demote/disable/reset/
sign-out/delete with job transfer; the last active admin is protected; Secure cookie behind an HTTPS proxy; pairing
off while accounts are on; the browser script (expired session -> login page, admin-only controls hidden).
Uses an in-process server on a private port and a fresh data/auth.db in the sandbox.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import io
import os
import json
import time
import uuid
import socket
import shutil
import sqlite3
import threading
import subprocess
import unittest
import http.client
from pathlib import Path
from unittest import mock

from backend import auth
from backend import device_pairing
from backend.api.common import purge_job
from backend.job_manager import job_owner
from backend.settings_manager import load_settings, save_settings

ROOT = Path(__file__).resolve().parent.parent
_PORT = None
PW = "correct horse battery"


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


def req(method, path, cookie=None, body=None, headers=None, raw=None, content_type=None):
    c = http.client.HTTPConnection("127.0.0.1", _PORT, timeout=30)
    h = {"User-Agent": "Mozilla/5.0 (test)"}
    if cookie:
        h["Cookie"] = f"{auth.SESSION_COOKIE}={cookie}"
    if body is not None:
        h["Content-Type"] = "application/json"
        raw = json.dumps(body)
    elif content_type:
        h["Content-Type"] = content_type
    h.update(headers or {})
    c.request(method, path, body=raw, headers=h)
    r = c.getresponse()
    data = r.read().decode("utf-8", "replace")
    c.close()
    try:
        js = json.loads(data)
    except ValueError:
        js = None
    return r.status, {k.lower(): v for k, v in r.getheaders()}, js if js is not None else data


def session_cookie(headers):
    sc = headers.get("set-cookie", "")
    part = sc.split(";")[0]
    return (part.split("=", 1)[1] if part.startswith(auth.SESSION_COOKIE + "=") else None), sc


def fresh_auth_store():
    """No accounts, sessions, audit entries, setup code or lockouts (tables emptied: Windows keeps files locked)."""
    with auth._db() as c:
        for table in ("users", "sessions", "audit"):
            c.execute(f"DELETE FROM {table}")
    try:
        auth._setup_code_path().unlink()
    except FileNotFoundError:
        pass
    auth._failures.clear()


def db_conn():
    from contextlib import closing
    return closing(sqlite3.connect(str(auth._db_path())))


def login(username, password=PW, remember=True, headers=None):
    st, h, js = req("POST", "/api/auth/login", body={"username": username, "password": password, "remember": remember},
                    headers=headers)
    return st, session_cookie(h)[0], js, h


def make_docx_bytes(text):
    import docx
    d = docx.Document()
    for _ in range(3):
        d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def upload(cookie, name):
    boundary = "----bookappauth" + uuid.uuid4().hex
    payload = make_docx_bytes(f"The lighthouse keeper of {name} wrote every night about the sea and the ships.")
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n").encode()
    body += payload + f"\r\n--{boundary}--\r\n".encode()
    st, _, js = req("POST", "/api/upload", cookie=cookie, raw=body,
                    content_type=f"multipart/form-data; boundary={boundary}")
    assert st == 200, (st, js)
    return js["job_id"]


class AuthBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _start()

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"BOOKAPP_AUTH": "1"})
        self._env.start()
        os.environ.pop("BOOKAPP_COOKIE_SECURE", None)
        fresh_auth_store()
        self.jobs = []

    def tearDown(self):
        for jid in self.jobs:
            try:
                purge_job(jid)
            except Exception:
                pass
        self._env.stop()
        fresh_auth_store()

    def make_admin(self, name="admin1"):
        user = auth.create_user(name, PW, role="admin")
        st, cookie, _, _ = login(name)
        self.assertEqual(st, 200)
        return user, cookie

    def make_user(self, name):
        user = auth.create_user(name, PW, role="user")
        st, cookie, _, _ = login(name)
        self.assertEqual(st, 200)
        return user, cookie


# ===========================================================================
# Core rules (no HTTP)
# ===========================================================================

class TestAuthCore(AuthBase):

    def test_password_hashing_and_rules(self):
        h = auth.hash_password(PW)
        self.assertTrue(h.startswith("scrypt$") and PW not in h)
        self.assertTrue(auth.verify_password(PW, h))
        self.assertFalse(auth.verify_password(PW + "x", h))
        self.assertFalse(auth.verify_password(PW, "garbage"))
        self.assertNotEqual(auth.hash_password(PW), h)  # salted
        for bad in ("short", "aaaaaaaaaaaa", "", None):
            with self.assertRaises(auth.AuthError) as cm:
                auth.validate_password(bad)
            self.assertEqual(cm.exception.code, "weak_password")
        with self.assertRaises(auth.AuthError):
            auth.validate_password("maria.papadopoulou", "Maria.Papadopoulou")
        for bad in ("a", "has space", "ελληνικά", "x" * 40, "-dash"):
            with self.assertRaises(auth.AuthError):
                auth.validate_username(bad)
        self.assertEqual(auth.validate_username("  maria.p_2 "), "maria.p_2")
        temp = auth.generate_temporary_password()
        self.assertRegex(temp, r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$")
        auth.validate_password(temp)
        # only hashes are stored
        auth.create_user("hashcheck", PW)
        with db_conn() as con:
            raw = con.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotIn(PW, raw)

    def test_lockout_after_five_wrong_passwords(self):
        auth.create_user("locky", PW)
        for _ in range(auth.MAX_FAILED_PER_USER):
            with self.assertRaises(auth.AuthError) as cm:
                auth.authenticate("locky", "wrong password!!", "10.0.0.1")
            self.assertEqual(cm.exception.code, "bad_credentials")
        with self.assertRaises(auth.AuthError) as cm:
            auth.authenticate("locky", PW, "10.0.0.2")  # even the right password waits
        self.assertEqual(cm.exception.code, "locked")
        self.assertEqual(cm.exception.http_status, 429)
        auth._failures["u:locky"][1] = time.time() - 1  # the 15 minutes are over
        self.assertEqual(auth.authenticate("LOCKY", PW, "10.0.0.2")["username"], "locky")  # case-insensitive name
        with self.assertRaises(auth.AuthError) as cm:
            auth.authenticate("nobody-here", PW)
        self.assertEqual(cm.exception.code, "bad_credentials")  # unknown names look the same

    def test_last_active_admin_is_protected(self):
        a = auth.create_user("boss", PW, role="admin")
        for action in (lambda: auth.set_role(None, a["id"], "user"),
                       lambda: auth.set_disabled(None, a["id"], True),
                       lambda: auth.delete_user(None, a["id"])):
            with self.assertRaises(auth.AuthError) as cm:
                action()
            self.assertEqual(cm.exception.code, "last_admin")
        with self.assertRaises(auth.AuthError) as cm:
            auth.set_disabled(a, a["id"], True)
        self.assertEqual(cm.exception.code, "self_action")
        b = auth.create_user("deputy", PW, role="user")
        auth.set_role(a, b["id"], "admin")                         # promoted: same rights
        self.assertEqual(auth.get_user(b["id"])["role"], "admin")
        auth.set_role(b, a["id"], "user")                          # now allowed: another active admin exists
        with self.assertRaises(auth.AuthError) as cm:
            auth.set_role(b, b["id"], "user")
        self.assertEqual(cm.exception.code, "last_admin")
        with self.assertRaises(auth.AuthError):
            auth.set_role(b, a["id"], "superuser")

    def test_sessions_remember_slide_and_expire(self):
        u = auth.create_user("sessy", PW)
        long_t = auth.create_session(u["id"], persistent=True)
        short_t = auth.create_session(u["id"], persistent=False)
        self.assertEqual(auth.session_for_token(long_t)["user"]["username"], "sessy")
        th = auth._token_hash(long_t)
        with db_conn() as con:
            con.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE token_hash = ?",
                        (time.time() - 3600, time.time() + 100, th))
            con.commit()
        s = auth.session_for_token(long_t)
        self.assertTrue(s["renewed"] and s["persistent"])
        with db_conn() as con:
            exp = con.execute("SELECT expires_at FROM sessions WHERE token_hash = ?", (th,)).fetchone()[0]
            self.assertAlmostEqual(exp, time.time() + 60 * 24 * 3600, delta=60)   # 60 days from this visit
            con.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                        (time.time() - 1, auth._token_hash(short_t)))
            con.commit()
        self.assertIsNone(auth.session_for_token(short_t))
        self.assertIsNone(auth.session_for_token("not-a-token"))
        auth.set_disabled(None, u["id"], True)
        self.assertIsNone(auth.session_for_token(long_t))                       # disabled -> signed out

    def test_password_change_signs_out_other_sessions(self):
        u = auth.create_user("changer", PW)
        keep = auth.create_session(u["id"], True)
        other = auth.create_session(u["id"], True)
        with self.assertRaises(auth.AuthError) as cm:
            auth.change_own_password(u, "wrong current pw", "a brand new password", keep)
        self.assertEqual(cm.exception.code, "wrong_current_password")
        with self.assertRaises(auth.AuthError) as cm:
            auth.change_own_password(u, PW, PW, keep)
        self.assertEqual(cm.exception.code, "same_password")
        auth.change_own_password(u, PW, "a brand new password", keep)
        self.assertIsNotNone(auth.session_for_token(keep))
        self.assertIsNone(auth.session_for_token(other))
        self.assertEqual(auth.authenticate("changer", "a brand new password")["id"], u["id"])

    def test_setup_code_lifecycle(self):
        code = auth.ensure_setup_code()
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertEqual(auth.ensure_setup_code(), code)                       # stable across restarts
        self.assertEqual(auth._setup_code_path().read_text(encoding="utf-8").strip(), code)
        with self.assertLogs("backend.auth", level="WARNING") as logs:
            auth.announce_setup_code()
        self.assertIn(code, "\n".join(logs.output))
        self.assertIn("/setup", "\n".join(logs.output))
        with self.assertRaises(auth.AuthError) as cm:
            auth.complete_setup("AAAA-AAAA", "firstboss", PW)
        self.assertEqual(cm.exception.code, "bad_setup_code")
        admin = auth.complete_setup(code.replace("-", "").lower(), "firstboss", PW)  # forgiving format
        self.assertEqual(admin["role"], "admin")
        self.assertFalse(auth._setup_code_path().exists())
        self.assertIsNone(auth.ensure_setup_code())
        with self.assertRaises(auth.AuthError) as cm:
            auth.complete_setup(code, "second", PW)
        self.assertEqual(cm.exception.code, "setup_done")

    def test_command_line_tool(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")

        def cli(*args, stdin=""):
            return subprocess.run([sys.executable, "-m", "backend.auth", *args], input=stdin, capture_output=True,
                                  text=True, encoding="utf-8", cwd=str(ROOT), env=env, timeout=60)

        r = cli("setup-code")
        self.assertIn("Setup code:", r.stdout)
        r = cli("create-admin", "cliboss", "--password-stdin", stdin=PW + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(auth.get_user_by_name("cliboss")["role"], "admin")
        self.assertFalse(auth._setup_code_path().exists())
        r = cli("create-user", "cliuser", "--password-stdin", stdin="too short\n")
        self.assertEqual(r.returncode, 1)
        r = cli("create-user", "cliuser", "--password-stdin", stdin=PW + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = cli("reset-password", "cliuser", "--password-stdin", stdin="another long password\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(auth.authenticate("cliuser", "another long password")["username"], "cliuser")
        r = cli("make-admin", "cliuser")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = cli("list-users")
        self.assertIn("cliboss", r.stdout)
        self.assertIn("cliuser", r.stdout)
        r = cli("reset-password", "ghost", "--password-stdin", stdin=PW + "\n")
        self.assertEqual(r.returncode, 1)
        r = cli("setup-code")
        self.assertIn("Setup is complete", r.stdout)

    def test_pairing_is_replaced_by_accounts(self):
        with mock.patch.dict(os.environ, {"BOOKAPP_PAIRING": "1"}):
            self.assertFalse(device_pairing.is_enabled())
            os.environ.pop("BOOKAPP_AUTH")
            self.assertTrue(device_pairing.is_enabled())


# ===========================================================================
# HTTP flows
# ===========================================================================

class TestAuthHttp(AuthBase):

    def test_accounts_off_changes_nothing(self):
        os.environ.pop("BOOKAPP_AUTH")
        st, _, js = req("GET", "/api/jobs")
        self.assertEqual(st, 200)
        st, _, js = req("GET", "/api/auth/status")
        self.assertEqual(js["enabled"], False)
        st, h, _ = req("GET", "/login")
        self.assertEqual((st, h.get("location")), (303, "/"))
        st, _, _ = req("GET", "/api/auth/users")
        self.assertEqual(st, 404)

    def test_first_admin_via_setup_page(self):
        st, h, _ = req("GET", "/")
        self.assertEqual((st, h.get("location")), (303, "/setup"))
        st, _, js = req("GET", "/api/jobs")
        self.assertEqual(st, 401)
        self.assertTrue(js["auth_required"] and js["setup_required"])
        st, _, page = req("GET", "/setup")
        self.assertEqual(st, 200)
        self.assertIn("form-setup", page)
        st, _, js = req("GET", "/api/auth/status")
        self.assertTrue(js["setup_required"])
        code = auth._setup_code_path().read_text(encoding="utf-8").strip()  # what the admin reads in the log
        st, _, js = req("POST", "/api/auth/setup", body={"code": "WRNG-CODE", "username": "kostas", "password": PW})
        self.assertEqual(st, 403)
        st, h, js = req("POST", "/api/auth/setup", body={"code": code, "username": "kostas", "password": PW})
        self.assertEqual(st, 200, js)
        cookie, raw = session_cookie(h)
        self.assertTrue(cookie)
        low = raw.lower()
        self.assertIn("httponly", low)
        self.assertIn("samesite=lax", low)
        self.assertIn(f"max-age={60 * 24 * 3600}", low)
        self.assertNotIn("secure", low)                                    # plain http in this test
        st, _, js = req("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual((js["user"]["username"], js["user"]["role"]), ("kostas", "admin"))
        st, _, _ = req("GET", "/api/jobs", cookie=cookie)
        self.assertEqual(st, 200)
        st, _, _ = req("POST", "/api/auth/setup", body={"code": code, "username": "intruder", "password": PW})
        self.assertEqual(st, 409)

    def test_sign_in_remember_and_sign_out(self):
        self.make_admin()
        auth.create_user("maria", PW)
        st, _, js, _ = login("maria", "wrong password")
        self.assertEqual(st, 401)
        st, cookie, js, h = login("maria", remember=False)
        self.assertEqual(st, 200)
        self.assertNotIn("max-age", h["set-cookie"].lower())               # ends with the browser
        st, cookie, js, h = login("maria", remember=True)
        self.assertIn(f"max-age={60 * 24 * 3600}", h["set-cookie"].lower())
        st, h, _ = req("GET", "/", cookie=cookie)
        self.assertEqual(st, 200)
        st, h, _ = req("GET", "/index.html")
        self.assertEqual((st, h.get("location")), (303, "/login?next=/index.html"))
        st, _, page = req("GET", "/login")
        self.assertIn("form-login", page)
        st, h, js = req("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertIn(auth.SESSION_COOKIE + '=""', h.get("set-cookie", ""))
        st, _, js = req("GET", "/api/jobs", cookie=cookie)
        self.assertEqual(st, 401)
        self.assertTrue(js["auth_required"])

    def test_cookie_secure_behind_https_proxy_and_renewal(self):
        auth.create_user("secure1", PW, role="admin")
        st, cookie, _, h = login("secure1", headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(st, 200)
        self.assertIn("secure", h["set-cookie"].lower())
        with db_conn() as con:
            con.execute("UPDATE sessions SET last_seen = ?", (time.time() - 3600,))
            con.commit()
        st, h, _ = req("GET", "/api/jobs", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertIn(f"max-age={60 * 24 * 3600}", h.get("set-cookie", "").lower())  # cookie slides forward too

    def test_temporary_password_must_be_changed(self):
        _, admin_cookie = self.make_admin()
        st, _, js = req("POST", "/api/auth/users", cookie=admin_cookie, body={"username": "nikos", "role": "user"})
        self.assertEqual(st, 200, js)
        temp = js["temporary_password"]
        self.assertTrue(js["user"]["must_change"])
        st, _, js = req("POST", "/api/auth/users", cookie=admin_cookie, body={"username": "NIKOS", "role": "user"})
        self.assertEqual(st, 409)
        st, cookie, js, _ = login("nikos", temp)
        self.assertEqual(st, 200)
        self.assertTrue(js["must_change"])
        st, _, js = req("GET", "/api/jobs", cookie=cookie)
        self.assertEqual(st, 403)
        self.assertTrue(js["password_change_required"])
        st, h, _ = req("GET", "/", cookie=cookie)
        self.assertEqual((st, h.get("location")), (303, "/login?change=1"))
        st, _, _ = req("POST", "/api/auth/change-password", cookie=cookie,
                       body={"current_password": "not it at all", "new_password": "my own secret phrase"})
        self.assertEqual(st, 400)
        st, _, js = req("POST", "/api/auth/change-password", cookie=cookie,
                        body={"current_password": temp, "new_password": "my own secret phrase"})
        self.assertEqual(st, 200, js)
        st, _, _ = req("GET", "/api/jobs", cookie=cookie)
        self.assertEqual(st, 200)

    def test_admin_only_endpoints_and_hidden_keys(self):
        _, admin_cookie = self.make_admin()
        _, user_cookie = self.make_user("eleni")
        snapshot = load_settings()
        try:
            from backend.gemini_key_pool import GeminiKeyPool
            GeminiKeyPool.set_keys(["AIzaSyAuthSuiteFakeKey00000000000000001"])
            for method, path, body in (("POST", "/api/settings", {"final_refinement_enabled": False}),
                                       ("DELETE", "/api/settings/gemini_api_keys", None),
                                       ("GET", "/api/gemini/pool", None),
                                       ("POST", "/api/gemini/reset-quota", None),
                                       ("POST", "/api/admin/cleanup", {"max_age_hours": 48, "dry_run": True}),
                                       ("GET", "/api/pairing", None),
                                       ("GET", "/api/auth/users", None),
                                       ("GET", "/api/auth/audit", None)):
                st, _, js = req(method, path, cookie=user_cookie, body=body)
                self.assertEqual(st, 403, f"{method} {path} -> {st} {js}")
            self.assertEqual(GeminiKeyPool.get_keys(), ["AIzaSyAuthSuiteFakeKey00000000000000001"])  # untouched
            st, _, js = req("GET", "/api/settings", cookie=user_cookie)
            self.assertEqual(st, 200)
            self.assertEqual((js["gemini_api_keys"], js["gemini_api_key"]), ([], ""))
            self.assertTrue(js["has_gemini_key"])
            self.assertTrue(all(s["masked_key"] == "" for s in js["pool"]["slots"]))
            st, _, js = req("GET", "/api/gemini/status", cookie=user_cookie)
            self.assertEqual(st, 200)
            self.assertNotIn("AuthSuite", json.dumps(js))
            st, _, js = req("GET", "/api/settings", cookie=admin_cookie)
            self.assertEqual(len(js["gemini_api_keys"]), 1)
            self.assertNotIn("AuthSuiteFakeKey", json.dumps(js))           # admins get the masked form only
            st, _, js = req("GET", "/api/auth/audit", cookie=admin_cookie)
            self.assertEqual(st, 200)
        finally:
            save_settings(snapshot)
            from backend.gemini_key_pool import GeminiKeyPool
            GeminiKeyPool.set_keys(snapshot.get("gemini_api_keys") or [])

    def test_users_see_only_their_own_jobs(self):
        admin, admin_cookie = self.make_admin()
        anna, anna_cookie = self.make_user("anna")
        ben, ben_cookie = self.make_user("ben")
        a_job = upload(anna_cookie, "Anna_Novel.docx")
        b_job = upload(ben_cookie, "Ben_Essay.docx")
        self.jobs += [a_job, b_job]
        self.assertEqual(job_owner(a_job), anna["id"])

        st, _, js = req("GET", "/api/jobs", cookie=ben_cookie)
        ids = {j["job_id"] for j in js}
        self.assertIn(b_job, ids)
        self.assertNotIn(a_job, ids)
        for method, path, body in (("GET", f"/api/status/{a_job}", None),
                                   ("GET", f"/api/download/{a_job}", None),
                                   ("GET", f"/api/progress/{a_job}", None),
                                   ("GET", f"/api/jobs/{a_job}/text", None),
                                   ("GET", f"/api/insights/{a_job}", None),
                                   ("POST", f"/api/jobs/{a_job}/cancel", None),
                                   ("DELETE", f"/api/jobs/{a_job}", None),
                                   ("POST", "/api/translate", {"job_id": a_job, "source_lang": "english",
                                                               "target_lang": "greek", "output_format": "txt"}),
                                   ("POST", "/api/polish", {"job_id": a_job, "text": "Hello.", "style": "formal"}),
                                   ("POST", "/api/queue/add", {"job_id": a_job, "output_format": "txt"})):
            st, _, js = req(method, path, cookie=ben_cookie, body=body)
            self.assertEqual(st, 404, f"{method} {path} -> {st} {js}")
        st, _, js = req("GET", f"/api/status/{a_job}", cookie=anna_cookie)
        self.assertEqual(st, 200)

        # the shared batch queue shows each user only their own documents
        st, _, js = req("POST", "/api/queue/add", cookie=anna_cookie, body={"job_id": a_job, "output_format": "txt"})
        self.assertEqual(st, 200, js)
        st, _, js = req("GET", "/api/queue", cookie=ben_cookie)
        self.assertNotIn(a_job, {i["job_id"] for i in js["items"]})
        st, _, js = req("DELETE", "/api/queue", cookie=ben_cookie)                 # clears only Ben's items
        st, _, js = req("GET", "/api/queue", cookie=anna_cookie)
        self.assertIn(a_job, {i["job_id"] for i in js["items"]})
        st, _, _ = req("DELETE", f"/api/queue/{a_job}", cookie=anna_cookie)
        self.assertEqual(st, 200)

        # administrators: own jobs by default, everyone's on request, one user's with the filter
        st, _, js = req("GET", "/api/jobs?scope=mine", cookie=admin_cookie)
        self.assertNotIn(a_job, {j["job_id"] for j in js})
        st, _, js = req("GET", "/api/jobs?scope=all", cookie=admin_cookie)
        by_id = {j["job_id"]: j for j in js}
        self.assertEqual(by_id[a_job]["owner_name"], "anna")
        self.assertIn(b_job, by_id)
        st, _, js = req("GET", f"/api/jobs?scope={anna['id']}", cookie=admin_cookie)
        self.assertEqual({j["job_id"] for j in js} & {a_job, b_job}, {a_job})
        st, _, _ = req("GET", f"/api/status/{a_job}", cookie=admin_cookie)
        self.assertEqual(st, 200)

        # "Clear All" removes only the requester's own jobs
        st, _, js = req("DELETE", "/api/jobs", cookie=ben_cookie)
        self.assertEqual(st, 200)
        self.assertIsNone(job_owner(b_job))
        self.assertEqual(job_owner(a_job), anna["id"])

    def test_user_management(self):
        admin, admin_cookie = self.make_admin()
        st, _, js = req("POST", "/api/auth/users", cookie=admin_cookie,
                        body={"username": "bob", "role": "user", "password": PW})
        self.assertEqual(st, 200, js)
        self.assertIsNone(js["temporary_password"])
        bob_id = js["user"]["id"]
        auth.set_password(bob_id, PW, must_change=False)
        st, bob_cookie, _, _ = login("bob")
        bob_job = upload(bob_cookie, "Bob_Story.docx")
        self.jobs.append(bob_job)

        # promote: same rights as the admin; demote again
        st, _, js = req("POST", f"/api/auth/users/{bob_id}/role", cookie=admin_cookie, body={"role": "admin"})
        self.assertEqual((st, js["user"]["role"]), (200, "admin"))
        st, _, _ = req("GET", "/api/auth/users", cookie=bob_cookie)
        self.assertEqual(st, 200)
        st, _, _ = req("POST", f"/api/auth/users/{bob_id}/role", cookie=admin_cookie, body={"role": "user"})
        st, _, _ = req("GET", "/api/auth/users", cookie=bob_cookie)
        self.assertEqual(st, 403)

        st, _, js = req("GET", "/api/auth/users", cookie=admin_cookie)
        bob = next(u for u in js["users"] if u["username"] == "bob")
        self.assertEqual((bob["jobs"], bob["active_sessions"]), (1, 1))
        self.assertIn("gemini_usage_today", bob)

        # disable signs out at once; enable again
        st, _, _ = req("POST", f"/api/auth/users/{bob_id}/disabled", cookie=admin_cookie, body={"disabled": True})
        self.assertEqual(st, 200)
        self.assertEqual(req("GET", "/api/jobs", cookie=bob_cookie)[0], 401)
        self.assertEqual(login("bob")[0], 403)
        req("POST", f"/api/auth/users/{bob_id}/disabled", cookie=admin_cookie, body={"disabled": False})
        st, bob_cookie, _, _ = login("bob")
        self.assertEqual(st, 200)

        # reset password: temporary, old sessions gone; sign out everywhere
        st, _, js = req("POST", f"/api/auth/users/{bob_id}/reset-password", cookie=admin_cookie)
        temp = js["temporary_password"]
        self.assertEqual(req("GET", "/api/jobs", cookie=bob_cookie)[0], 401)
        st, bob_cookie, js, _ = login("bob", temp)
        self.assertTrue(js["must_change"])
        st, _, js = req("POST", f"/api/auth/users/{bob_id}/sign-out", cookie=admin_cookie)
        self.assertEqual(js["signed_out_sessions"], 1)

        # the admin cannot lock everyone out
        st, _, js = req("POST", f"/api/auth/users/{admin['id']}/role", cookie=admin_cookie, body={"role": "user"})
        self.assertEqual(st, 409)
        st, _, _ = req("DELETE", f"/api/auth/users/{admin['id']}", cookie=admin_cookie)
        self.assertEqual(st, 409)
        st, _, _ = req("DELETE", f"/api/auth/users/{bob_id}?jobs=maybe", cookie=admin_cookie)
        self.assertEqual(st, 400)

        # delete with transfer: the jobs become the admin's
        st, _, js = req("DELETE", f"/api/auth/users/{bob_id}?jobs=transfer", cookie=admin_cookie)
        self.assertEqual((st, js["job_count"]), (200, 1))
        self.assertEqual(job_owner(bob_job), admin["id"])
        self.assertIsNone(auth.get_user(bob_id))

        # delete with jobs: files and record are removed
        carol = auth.create_user("carol", PW)
        st, carol_cookie, _, _ = login("carol")
        carol_job = upload(carol_cookie, "Carol_Poems.docx")
        self.jobs.append(carol_job)
        st, _, js = req("DELETE", f"/api/auth/users/{carol['id']}?jobs=delete", cookie=admin_cookie)
        self.assertEqual(st, 200)
        self.assertIsNone(job_owner(carol_job))

        st, _, js = req("GET", "/api/auth/audit", cookie=admin_cookie)
        actions = [e["action"] for e in js["entries"]]
        for a in ("user_created", "role_changed", "user_disabled", "user_enabled", "password_reset",
                  "signed_out_everywhere", "user_deleted"):
            self.assertIn(a, actions)


# ===========================================================================
# Browser script (frontend/auth.js) and login page
# ===========================================================================

class TestAuthFrontend(unittest.TestCase):

    def _node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js not installed")
        return node

    def test_login_page_script_is_valid(self):
        import re
        node = self._node()
        html = (ROOT / "frontend" / "login.html").read_text(encoding="utf-8")
        for script in re.findall(r"<script>([\s\S]*?)</script>", html):
            r = subprocess.run([node, "--check", "-"], input=script, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
        for el in ("form-login", "form-setup", "form-change", "/auth/login", "/auth/setup", "/auth/change-password"):
            self.assertIn(el, html)
        self.assertIn("startsWith('//')", html)   # ?next= only to same-site paths

    def test_auth_script_hides_admin_controls_and_handles_expired_sessions(self):
        node = self._node()
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  const cls = new Set();
  return { id, value: '', textContent: '', innerHTML: '', checked: false, disabled: false, title: '', dataset: {},
    style: { display: '' }, options: [], setAttribute() {}, getAttribute() {}, removeAttribute() {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c) },
    closest: () => null, addEventListener() {}, focus() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const toggles = [makeEl('t1'), makeEl('t2')];
const body = makeEl('body');
let role = 'user';
const reply = (status, data) => ({ ok: status < 400, status, json: async () => data, clone() { return this; } });
const fetchImpl = async (url) => {
  if (String(url).endsWith('/auth/status')) return reply(200, { enabled: true, setup_required: false,
    user: { id: 'u1', username: 'maria', role } });
  if (String(url).includes('/auth/users')) return reply(200, { users: [{ id: 'u1', username: 'maria' },
    { id: 'u2', username: 'nikos' }], me: 'u1' });
  if (String(url).includes('/jobs')) return reply(401, { detail: 'x', auth_required: true });
  return reply(200, {});
};
const location = { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '', pathname: '/', search: '' };
function makeCtx() {
  const toasts = [];
  const win = { location, addEventListener() {}, fetch: (...a) => fetchImpl(...a), confirm: () => true };
  const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    EventSource: class { close() {} }, FormData: class { append() {} }, URLSearchParams,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: (...a) => win.fetch(...a), window: win,
    document: { documentElement: makeEl('html'), body, readyState: 'complete', getElementById: getEl,
      querySelector: () => null, querySelectorAll: (sel) => sel === '.final-refinement-toggle' ? toggles : [],
      addEventListener() {}, createElement: makeEl } });
  vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
  vm.runInContext(fs.readFileSync('frontend/auth.js', 'utf8') + '\nglobalThis.__a = { authState };', ctx);
  ctx.toast = (m) => toasts.push(m);
  return { ctx, toasts };
}
(async () => {
  // a regular user: admin-only controls hidden, shared settings locked, API key window refused
  let { ctx, toasts } = makeCtx();
  await new Promise((r) => setImmediate(r));
  await ctx.initAuthUi();
  assert.ok(body.classList.contains('auth-on'));
  assert.ok(!body.classList.contains('auth-admin'));
  assert.strictEqual(getEl('auth-user-label').textContent, 'maria');
  assert.ok(toggles.every((t) => t.disabled));
  assert.strictEqual(await ctx.openApiKeyModal(), null);
  assert.ok(toasts.some((m) => m.includes('διαχειριστής')));
  // an expired session sends the browser to the login page (and back here afterwards)
  await ctx.window.fetch('http://127.0.0.1:8000/api/jobs?scope=mine');
  assert.strictEqual(location.href, '/login?next=%2F');
  // an administrator: the Session History filter lists the other users
  role = 'admin'; location.href = '';
  ({ ctx } = makeCtx());
  await ctx.initAuthUi();
  assert.ok(body.classList.contains('auth-admin'));
  assert.ok(getEl('history-owner-filter').innerHTML.includes('nikos'));
  assert.ok(!getEl('history-owner-filter').innerHTML.includes('>👤 maria<'));
  assert.strictEqual(ctx.historyScope(), 'mine');
  process.stdout.write('OK');
})().catch((e) => process.stdout.write('FAIL ' + (e && e.stack || e)));
"""
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30,
                           cwd=str(ROOT))
        self.assertEqual(r.stdout.strip(), "OK", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
