"""
tests/test_e2e_regression_guard.py - Real-World User Flow & Anti-Regression Guard Suite.
Explicitly guards against every real production bug ever encountered:
1. Single-job delete (DELETE /api/jobs/{id}) must permanently remove the job from GET /api/jobs AND SQLite.
2. Clear All Session History (DELETE /api/jobs) must empty BOTH GET /api/jobs AND SQLite jobs table, while preserving translation_cache.
3. DOCX + ai_polish=True must route through Single-Pass Direct AI Translation (never bypass AI polish).
4. Invalid Gemini API Key on a scanned comic must fail fast (<10s) with a clear error instead of spinning for 15+ minutes.
5. Full test hygiene: cleans up every job it creates so Session History stays clean.
"""

import sys
sys.path.insert(0, ".")
import json
import time
import threading
import urllib.request
import unittest
from pathlib import Path

import docx
import pymupdf as fitz
from PIL import Image

from backend.database import db_get_job, db_list_jobs, db_get_cache_stats

API = "http://127.0.0.1:8000/api"


def ensure_server():
    try:
        with urllib.request.urlopen(f"{API}/cache/stats", timeout=0.8):
            return
    except Exception:
        pass
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
            with urllib.request.urlopen(f"{API}/cache/stats", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)


def api_get(path):
    with urllib.request.urlopen(f"{API}{path}", timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_delete(path):
    req = urllib.request.Request(f"{API}{path}", method="DELETE")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_post_file(path, filepath, filename):
    boundary = "----TestRegGuardBoundary777"
    file_data = Path(filepath).read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestE2ERegressionGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ensure_server()

    def test_1_single_job_delete_persists_in_sqlite_and_api(self):
        print("-> 1. Testing Single-Job Delete removes job from BOTH GET /api/jobs and SQLite...")
        tmp = Path("temp/reg_single_delete.docx")
        d = docx.Document()
        d.add_paragraph("Hello world regression test.")
        d.save(str(tmp))
        try:
            st, up = api_post_file("/upload", tmp, "reg_single_delete.docx")
            self.assertEqual(st, 200)
            jid = up["job_id"]

            # Confirm present in GET /api/jobs AND SQLite
            _, jobs_before = api_get("/jobs")
            self.assertTrue(any(j["job_id"] == jid for j in jobs_before))
            self.assertIsNotNone(db_get_job(jid))

            # Delete single job
            st_del, _ = api_delete(f"/jobs/{jid}")
            self.assertEqual(st_del, 200)

            # Confirm GONE from GET /api/jobs AND SQLite
            _, jobs_after = api_get("/jobs")
            self.assertFalse(any(j["job_id"] == jid for j in jobs_after), "Deleted job resurrected in GET /api/jobs!")
            self.assertIsNone(db_get_job(jid), "Deleted job still exists in SQLite jobs table!")
            print("   Single-Job Delete (API + SQLite): OK")
        finally:
            tmp.unlink(missing_ok=True)

    def test_2_clear_all_jobs_empties_api_and_sqlite_preserving_cache(self):
        print("-> 2. Testing Clear All (DELETE /api/jobs) empties API + SQLite while preserving cache...")
        cache_before = db_get_cache_stats()["cached_entries"]
        tmp1 = Path("temp/reg_clear_1.docx")
        tmp2 = Path("temp/reg_clear_2.docx")
        for p, msg in [(tmp1, "Clear all test document 1."), (tmp2, "Clear all test document 2.")]:
            d = docx.Document()
            d.add_paragraph(msg)
            d.save(str(p))
        try:
            _, up1 = api_post_file("/upload", tmp1, "reg_clear_1.docx")
            _, up2 = api_post_file("/upload", tmp2, "reg_clear_2.docx")
            _, jobs_before = api_get("/jobs")
            self.assertGreaterEqual(len(jobs_before), 2)

            # Clear All
            st_clr, res_clr = api_delete("/jobs")
            self.assertEqual(st_clr, 200)
            self.assertEqual(res_clr["status"], "cleared")

            # Verify GET /api/jobs AND SQLite jobs table are 100% empty
            _, jobs_after = api_get("/jobs")
            self.assertEqual(jobs_after, [], f"Clear All failed — jobs still returned: {jobs_after}")
            self.assertEqual(db_list_jobs(limit=50), [], "Clear All failed — jobs still remain in SQLite!")

            # Verify semantic translation cache was NOT wiped
            cache_after = db_get_cache_stats()["cached_entries"]
            self.assertEqual(cache_after, cache_before, "Clear All must preserve translation_cache!")
            print("   Clear All (API=[] + SQLite=[] + Cache Preserved): OK")
        finally:
            tmp1.unlink(missing_ok=True)
            tmp2.unlink(missing_ok=True)

    def test_3_docx_with_ai_polish_routes_to_single_pass_direct_ai(self):
        print("-> 3. Testing DOCX + ai_polish=True routes through Single-Pass Direct AI...")
        doc_path = Path("temp/reg_docx_polish.docx")
        d = docx.Document()
        d.add_heading("Chapter 1", level=1)
        d.add_paragraph("Try to touch the past. It is not real. It is just a dream.")
        d.save(str(doc_path))
        jid = None
        try:
            st, up = api_post_file("/upload", doc_path, "reg_docx_polish.docx")
            self.assertEqual(st, 200)
            self.assertFalse(up["is_comic"])
            jid = up["job_id"]

            st_tr, _ = api_post_json("/translate", {
                "job_id": jid,
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "docx",
                "layout_mode": "literature",
                "ai_polish": True,
                "api_key": "AQ.TestMockDirectDocx123",
            })
            self.assertEqual(st_tr, 200)

            for _ in range(40):
                time.sleep(0.25)
                _, sdata = api_get(f"/status/{jid}")
                if sdata["status"] in ("done", "error"):
                    break
            self.assertEqual(sdata["status"], "done", f"DOCX Single-Pass AI failed: {sdata}")

            txt_files = list((Path("temp/outputs") / jid).glob("*_translated_*.txt"))
            self.assertTrue(len(txt_files) >= 1)
            out_txt = txt_files[0].read_text(encoding="utf-8")
            self.assertIn("[Επιμελημένο AI]", out_txt, "DOCX with ai_polish=True bypassed Single-Pass Direct AI!")
            print("   DOCX + AI Polish Single-Pass routing: OK")
        finally:
            doc_path.unlink(missing_ok=True)
            if jid:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass

    def test_4_invalid_api_key_fails_fast_on_scanned_comic(self):
        print("-> 4. Testing Invalid Gemini API Key fails fast on scanned comic PDF...")
        img_p = Path("temp/reg_scan_failfast.jpg")
        Image.new("RGB", (500, 700), (50, 60, 70)).save(img_p, quality=80)
        pdf_p = Path("temp/reg_scan_failfast.pdf")
        doc = fitz.open()
        for _ in range(3):
            p = doc.new_page(width=500, height=700)
            p.insert_image(p.rect, filename=str(img_p))
        doc.save(str(pdf_p))
        doc.close()

        jid = None
        try:
            st, up = api_post_file("/upload", pdf_p, "reg_scan_failfast.pdf")
            self.assertEqual(st, 200)
            self.assertTrue(up["is_comic"])
            self.assertTrue(up["is_scanned"])
            jid = up["job_id"]

            t0 = time.time()
            api_post_json("/translate", {
                "job_id": jid,
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "pdf",
                "layout_mode": "comic",
                "api_key": "INVALID_BOGUS_KEY_1234567890",
            })

            sdata = {}
            for _ in range(40):
                time.sleep(0.3)
                _, sdata = api_get(f"/status/{jid}")
                if sdata["status"] in ("done", "error"):
                    break
            dur = time.time() - t0
            self.assertEqual(sdata["status"], "error", f"Expected fast error on invalid API key, got: {sdata}")
            self.assertLess(dur, 12.0, f"Invalid key took too long ({dur:.1f}s) instead of failing fast!")
            print(f"   Invalid key fail-fast ({dur:.2f}s): OK")
        finally:
            img_p.unlink(missing_ok=True)
            pdf_p.unlink(missing_ok=True)
            if jid:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
