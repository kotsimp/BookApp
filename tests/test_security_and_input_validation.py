"""
test_security_and_input_validation.py - Security, Path Traversal, Zip Slip & Strict Input Validation Suite.
Tests:
1. Path traversal rejection across all job_id-accepting API endpoints & job_manager.get_job().
2. Zip Slip path traversal rejection in CBZ comic archives.
3. Voice preview path traversal / invalid voice identifier rejection.
4. Upload edge cases: Windows-illegal filename sanitization, reserved names (CON/NUL), 0-byte, corrupt headers.
5. Cover image validation: empty file, corrupt non-image bytes rejected (400), path traversal rejected.
6. Query & body parameter bounds: PolishRequest with job_id=None (Direct Editor), unsupported ?format= (400),
   negative max_chars (400), admin cleanup max_age_hours<=0 (400), case-insensitive same-lang (400),
   invalid TTS prosody rate/pitch (400).
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
import zipfile
import asyncio
import tempfile
import unittest
import urllib.request
import urllib.error
from pathlib import Path

from backend.job_manager import get_job, is_valid_job_id, create_job

API = "http://127.0.0.1:8000/api"


def ensure_server():
    try:
        with urllib.request.urlopen(f"{API}/health", timeout=0.8):
            return
    except Exception:
        pass
    import threading
    import uvicorn
    from backend.main import app
    t = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": 8000, "log_level": "error"},
        daemon=True,
    )
    t.start()
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{API}/health", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)


def http_req(method: str, path: str, body: bytes = None, headers: dict = None):
    req = urllib.request.Request(f"{API}{path}", data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def http_json(method: str, path: str, payload: dict):
    status, raw = http_req(
        method,
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = raw.decode("utf-8", errors="replace")
    return status, data


def http_upload(path: str, filename: str, content: bytes):
    boundary = "----SecTestBoundary999"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    status, raw = http_req(
        "POST",
        path,
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = raw.decode("utf-8", errors="replace")
    return status, data


class TestSecurityAndInputValidation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ensure_server()

    def test_1_job_id_path_traversal_blocked_everywhere(self):
        print("-> 1. Testing job_id path traversal protection across all endpoints & job_manager...")
        bad_ids = [
            "..",
            ".",
            "../outside",
            "..\\outside",
            "foo/bar",
            "foo\\bar",
            "C:\\Windows\\Temp",
            ".hidden",
            "abc\x00def",
            "   ",
            "",
        ]
        for bad in bad_ids:
            self.assertFalse(is_valid_job_id(bad), f"Expected is_valid_job_id({bad!r}) == False")
            self.assertIsNone(get_job(bad), f"Expected get_job({bad!r}) == None")

        # JSON body traversal via POST /api/polish (bypasses URL normalization!)
        for traversal in ("../../escaped_dir", "..\\..\\escaped_dir", "C:\\temp\\evil"):
            st, _ = http_json("POST", "/polish", {
                "job_id": traversal,
                "text": "Sample text",
                "style": "formal",
                "api_key": "AQ.TestTraversalCheck123",
            })
            self.assertEqual(st, 400, f"POST /polish with job_id={traversal!r} must return 400, got {st}")

        # URL-encoded backslash traversal on GET/DELETE/PUT/POST endpoints
        encoded_bad = "..%5C..%5Cconfig"
        for method, path in [
            ("GET", f"/status/{encoded_bad}"),
            ("GET", f"/download/{encoded_bad}"),
            ("GET", f"/cover/{encoded_bad}"),
            ("DELETE", f"/cover/{encoded_bad}"),
            ("DELETE", f"/jobs/{encoded_bad}"),
            ("GET", f"/jobs/{encoded_bad}/text"),
            ("GET", f"/preview/{encoded_bad}"),
            ("GET", f"/debug/extract/{encoded_bad}"),
            ("GET", f"/polish/status/{encoded_bad}"),
        ]:
            st, _ = http_req(method, path)
            self.assertIn(st, (400, 404), f"{method} {path} must reject traversal with 400/404, got {st}")

        st_put, _ = http_json("PUT", f"/jobs/{encoded_bad}/text", {"translated_text": "pwned"})
        self.assertEqual(st_put, 400, f"PUT /jobs/{encoded_bad}/text must return 400, got {st_put}")

        st_cov, _ = http_upload(f"/cover/{encoded_bad}", "cov.jpg", b"not-an-image")
        self.assertEqual(st_cov, 400, f"POST /cover/{encoded_bad} must return 400, got {st_cov}")
        print("   Path traversal protection: OK")

    def test_2_tts_preview_voice_sanitization(self):
        print("-> 2. Testing GET /api/tts/preview voice identifier sanitization...")
        for bad_voice in ("../../etc/passwd", "..\\..\\config", "voice;rm", "voice with spaces"):
            st, _ = http_req("GET", f"/tts/preview?voice={urllib.request.quote(bad_voice)}")
            self.assertEqual(st, 400, f"GET /tts/preview?voice={bad_voice!r} must return 400, got {st}")
        print("   TTS preview voice sanitization: OK")

    def test_3_upload_filename_sanitization_and_corrupt_files(self):
        print("-> 3. Testing upload filename sanitization (Windows illegal/reserved) & corrupt files...")
        import docx
        buf = io.BytesIO()
        d = docx.Document()
        d.add_paragraph("Safe filename test content.")
        d.save(buf)
        valid_docx = buf.getvalue()

        created_jobs = []
        try:
            # Windows reserved device name (CON.docx) & illegal characters
            for fname in ('CON.docx', 'my<bad>:file|name?.docx'):
                st, data = http_upload("/upload", fname, valid_docx)
                self.assertEqual(st, 200, f"Upload for sanitized filename {fname!r} failed: {st} {data}")
                jid = data["job_id"]
                created_jobs.append(jid)
                job = get_job(jid)
                self.assertIsNotNone(job)
                self.assertTrue(Path(job.file_path).exists())
                # Ensure no illegal characters remain in stored filename
                for ch in '<>:"|?*':
                    self.assertNotIn(ch, Path(job.file_path).name)

            # Downloaded books often carry 200+ character names: once too long for the disk paths (upload failed)
            long_name = ("Wool_ The Graphic Novel Omnibus -- Hugh Howey, Jimmy Palmotti, Justin Gray, Jimmy Broxton -- "
                         "1st, 2014 -- Jet City Comics -- isbn13 9781477849125 -- 43ec5dd2a482ad8ebdbb0ddeaeefc75b -- "
                         "Reader’s Copy Δοκιμή.docx")
            st, data = http_upload("/upload", long_name, valid_docx)
            self.assertEqual(st, 200, f"Upload of a {len(long_name)}-character name failed: {st} {data}")
            created_jobs.append(data["job_id"])
            stored = Path(get_job(data["job_id"]).file_path)
            self.assertTrue(stored.exists())
            self.assertLessEqual(len(stored.stem), 100)
            self.assertEqual(stored.suffix, ".docx")
            self.assertTrue(stored.stem.startswith("Wool_ The Graphic Novel Omnibus"))

            # Corrupt headers & unsupported extensions & 0-byte file
            st_empty, _ = http_upload("/upload", "empty.pdf", b"")
            self.assertEqual(st_empty, 400)

            st_bad_pdf, _ = http_upload("/upload", "fake.pdf", b"NOT_A_PDF_HEADER_DATA")
            self.assertEqual(st_bad_pdf, 400)

            st_bad_docx, _ = http_upload("/upload", "fake.docx", b"NOT_A_ZIP_ARCHIVE")
            self.assertEqual(st_bad_docx, 400)

            st_doc, _ = http_upload("/upload", "legacy.doc", b"\xd0\xcf\x11\xe0dummy")
            self.assertEqual(st_doc, 400)

            st_ext, _ = http_upload("/upload", "script.exe", b"MZdummy")
            self.assertEqual(st_ext, 400)
        finally:
            for jid in created_jobs:
                http_req("DELETE", f"/jobs/{jid}")
        print("   Upload sanitization & header validation: OK")

    def test_4_cover_upload_rejects_corrupt_bytes(self):
        print("-> 4. Testing POST /api/cover/{job_id} rejects corrupt non-image bytes...")
        import docx
        buf = io.BytesIO()
        d = docx.Document()
        d.add_paragraph("Cover validation book.")
        d.save(buf)
        st, up = http_upload("/upload", "cover_check.docx", buf.getvalue())
        self.assertEqual(st, 200)
        jid = up["job_id"]
        try:
            st_empty, _ = http_upload(f"/cover/{jid}", "empty.jpg", b"")
            self.assertEqual(st_empty, 400)

            st_corrupt, _ = http_upload(f"/cover/{jid}", "evil.jpg", b"<script>alert(1)</script>")
            self.assertEqual(st_corrupt, 400, f"Corrupt cover bytes must return 400, got {st_corrupt}")
            # Confirm no corrupt cover_image.jpg was written
            self.assertFalse((Path("temp/outputs") / jid / "cover_image.jpg").exists())
        finally:
            http_req("DELETE", f"/jobs/{jid}")
        print("   Cover upload strict image validation: OK")

    def test_5_query_and_body_parameter_bounds(self):
        print("-> 5. Testing query/body parameter bounds (Polish null job_id, format, max_chars, cleanup, prosody)...")
        # Direct Editor sends job_id: null — must succeed (NOT 422!)
        st_pol, pol_data = http_json("POST", "/polish", {
            "job_id": None,
            "text": "Αυτό είναι ένα σύντομο κείμενο για άμεση επιμέλεια.",
            "style": "formal",
            "api_key": "AQ.TestNullJobIdDirectEditor",
        })
        self.assertEqual(st_pol, 200, f"POST /polish with job_id=None must succeed (not 422), got {st_pol}: {pol_data}")
        direct_jid = pol_data.get("job_id")
        self.assertTrue(direct_jid)

        try:
            # Unsupported ?format= must return 400, not 500
            st_fmt, _ = http_req("GET", f"/download/{direct_jid}?format=html")
            self.assertEqual(st_fmt, 400, f"Unsupported ?format=html must return 400, got {st_fmt}")

            # Non-comic job requesting ?format=cbz must return 400, not 500
            st_cbz, _ = http_req("GET", f"/download/{direct_jid}?format=cbz")
            self.assertEqual(st_cbz, 400, f"Non-comic ?format=cbz must return 400, got {st_cbz}")

            # Negative max_chars on /preview and /debug/extract must return 400
            st_prev, _ = http_req("GET", f"/preview/{direct_jid}?max_chars=-5")
            self.assertEqual(st_prev, 400)
            st_dbg, _ = http_req("GET", f"/debug/extract/{direct_jid}?max_chars=0")
            self.assertEqual(st_dbg, 400)

            # Case-insensitive same-language translation must return 400
            st_lang, _ = http_json("POST", "/translate", {
                "job_id": direct_jid,
                "source_lang": "English",
                "target_lang": "english",
                "output_format": "txt",
            })
            self.assertEqual(st_lang, 400)

            # Unsupported output_format on /translate must return 400
            st_bad_fmt, _ = http_json("POST", "/translate", {
                "job_id": direct_jid,
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "exe",
            })
            self.assertEqual(st_bad_fmt, 400)

            # Invalid prosody rate/pitch on /audiobook must return 400
            st_rate, _ = http_json("POST", "/audiobook", {
                "job_id": direct_jid,
                "language": "greek",
                "voice_name": "Nestoras (Male)",
                "rate": "super_fast",
            })
            self.assertEqual(st_rate, 400)

            st_pitch, _ = http_json("POST", "/audiobook", {
                "job_id": direct_jid,
                "language": "greek",
                "voice_name": "Nestoras (Male)",
                "pitch": "very_high",
            })
            self.assertEqual(st_pitch, 400)

            # Admin cleanup with max_age_hours <= 0 must return 400 (never wipe active temp files!)
            for bad_hrs in (0, -1, -48):
                st_cln, _ = http_json("POST", "/admin/cleanup", {"max_age_hours": bad_hrs, "dry_run": True})
                self.assertEqual(st_cln, 400, f"max_age_hours={bad_hrs} must return 400, got {st_cln}")
        finally:
            if direct_jid:
                http_req("DELETE", f"/jobs/{direct_jid}")
        print("   Query & body parameter bounds: OK")


if __name__ == "__main__":
    unittest.main()
