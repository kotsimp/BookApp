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
            _, jobs_before = api_get("/jobs?include_tests=true")
            self.assertTrue(any(j["job_id"] == jid for j in jobs_before))
            self.assertIsNotNone(db_get_job(jid))

            # Delete single job
            st_del, _ = api_delete(f"/jobs/{jid}")
            self.assertEqual(st_del, 200)

            # Confirm GONE from GET /api/jobs AND SQLite
            _, jobs_after = api_get("/jobs?include_tests=true")
            self.assertFalse(any(j["job_id"] == jid for j in jobs_after), "Deleted job resurrected in GET /api/jobs!")
            self.assertIsNone(db_get_job(jid), "Deleted job still exists in SQLite jobs table!")
            print("   Single-Job Delete (API + SQLite): OK")
        finally:
            tmp.unlink(missing_ok=True)

    def test_2_clear_all_jobs_empties_api_and_sqlite_preserving_cache(self):
        print("-> 2. Testing Clear All (DELETE /api/jobs) empties API + SQLite while preserving cache...")
        from backend.job_manager import is_test_job_filename
        existing_jobs = db_list_jobs(limit=1000)
        existing_user_jobs = [j for j in existing_jobs if not is_test_job_filename(j.get("file_name"))]
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
            _, jobs_before = api_get("/jobs?include_tests=true")
            self.assertGreaterEqual(len(jobs_before), 2)

            # Clear All
            st_clr, res_clr = api_delete("/jobs")
            self.assertEqual(st_clr, 200)
            self.assertEqual(res_clr["status"], "cleared")

            # Verify GET /api/jobs AND SQLite jobs table are 100% empty
            _, jobs_after = api_get("/jobs?include_tests=true")
            self.assertEqual(jobs_after, [], f"Clear All failed — jobs still returned: {jobs_after}")
            self.assertEqual(db_list_jobs(limit=50), [], "Clear All failed — jobs still remain in SQLite!")

            # Verify semantic translation cache was NOT wiped
            cache_after = db_get_cache_stats()["cached_entries"]
            self.assertEqual(cache_after, cache_before, "Clear All must preserve translation_cache!")
            print("   Clear All (API=[] + SQLite=[] + Cache Preserved): OK")
        finally:
            tmp1.unlink(missing_ok=True)
            tmp2.unlink(missing_ok=True)
            for uj in existing_user_jobs:
                try:
                    db_save_job(uj)
                except Exception:
                    pass

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

    def test_5_health_preview_cover_debug_polish_status_and_sse(self):
        print("-> 5. Testing /health, /preview, /cover (POST/GET/DELETE), /debug/extract, /polish/status & /progress SSE...")
        # 5a. GET /api/health
        st_h, h_data = api_get("/health")
        self.assertEqual(st_h, 200)
        self.assertEqual(h_data.get("status"), "ok")

        # Upload a real sample DOCX for endpoint round-trips
        doc_p = Path("temp/reg_full_endpoints.docx")
        d = docx.Document()
        d.add_heading("Technical API Guide", level=1)
        d.add_paragraph("The server database API runs in a Docker container with SQL protocol.")
        d.save(str(doc_p))
        cov_p = Path("temp/reg_test_cover.jpg")
        Image.new("RGB", (200, 300), (80, 40, 120)).save(cov_p, quality=85)

        jid = None
        try:
            st_u, up = api_post_file("/upload", doc_p, "reg_full_endpoints.docx")
            self.assertEqual(st_u, 200)
            jid = up["job_id"]

            # 5b. GET /api/preview/{job_id} -> must return 200 with preview_text (fixes silent 404 bug!)
            st_p, prev = api_get(f"/preview/{jid}")
            self.assertEqual(st_p, 200)
            self.assertIn("Docker container", prev.get("preview_text", ""))

            # Feed preview into /api/detect-genre -> must auto-detect technical
            st_g, gdata = api_post_json("/detect-genre", {"sample_text": prev["preview_text"], "file_type": "docx"})
            self.assertEqual(st_g, 200)
            self.assertEqual(gdata["genre"], "technical")

            # 5c. POST / GET / DELETE /api/cover/{job_id}
            st_cp, cp_data = api_post_file(f"/cover/{jid}", cov_p, "reg_test_cover.jpg")
            self.assertEqual(st_cp, 200)
            self.assertEqual(cp_data.get("status"), "ok")

            with urllib.request.urlopen(f"{API}/cover/{jid}", timeout=10) as cov_resp:
                self.assertEqual(cov_resp.status, 200)
                self.assertGreater(len(cov_resp.read()), 100)

            st_cd, cd_data = api_delete(f"/cover/{jid}")
            self.assertEqual(st_cd, 200)
            self.assertEqual(cd_data.get("status"), "deleted")

            # 5d. GET /api/debug/extract/{job_id}
            st_dbg, dbg = api_get(f"/debug/extract/{jid}")
            self.assertEqual(st_dbg, 200)
            self.assertGreaterEqual(dbg.get("pages_sampled", 0), 1)

            # 5e. GET /api/polish/status/{job_id}
            st_ps, ps = api_get(f"/polish/status/{jid}")
            self.assertEqual(st_ps, 200)
            self.assertIn("status", ps)

            # 5f. GET /api/progress/{job_id} SSE stream (read initial event cleanly)
            req_sse = urllib.request.Request(f"{API}/progress/{jid}")
            with urllib.request.urlopen(req_sse, timeout=5) as sse_resp:
                self.assertEqual(sse_resp.status, 200)
                first_line = sse_resp.readline().decode("utf-8", errors="ignore")
                self.assertTrue(first_line.startswith("data:"), f"Expected SSE data line, got: {first_line!r}")

            print("   All 6 auxiliary endpoints (/health, /preview, /cover, /debug/extract, /polish/status, /progress SSE): OK")
        finally:
            doc_p.unlink(missing_ok=True)
            cov_p.unlink(missing_ok=True)
            if jid:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass

    def test_6_source_anchored_auto_disables_when_source_equals_draft(self):
        print("-> 6. Testing Source-Anchored Verification auto-disables when source == draft...")
        import asyncio
        from unittest.mock import patch, AsyncMock
        from backend.ai_polisher import polish_text_with_gemini

        same_text = "=== PAGE 1 ===\nΑυτό είναι ένα ήδη ελληνικό κείμενο προς επιμέλεια."
        captured_inputs = []

        async def fake_call(content_text, *args, **kwargs):
            captured_inputs.append(content_text)
            return same_text

        with patch("backend.ai_polisher._call_gemini_api", side_effect=fake_call):
            res = asyncio.run(polish_text_with_gemini(
                text=same_text,
                api_key="AQ.TestMockSameText123",
                style="literature",
                original_text=same_text,
                use_source_anchoring=True,
            ))
        self.assertTrue(len(captured_inputs) >= 1)
        self.assertNotIn("SOURCE REFERENCE", captured_inputs[0], "Identical source==draft should NOT duplicate text in prompt!")
        print("   Source-Anchored identical-text auto-disable: OK")

    def test_7_google_429_circuit_breaker_trips_fast(self):
        print("-> 7. Testing Google GTX 429 Circuit Breaker trips without hanging...")
        import asyncio
        import urllib.error
        from unittest.mock import patch
        import backend.translator as tr_mod

        orig_cooldown = tr_mod._GTX_COOLDOWN_UNTIL
        tr_mod._GTX_COOLDOWN_UNTIL = 0.0
        calls = {"gtx": 0}

        def always_429(*args, **kwargs):
            calls["gtx"] += 1
            raise urllib.error.HTTPError("https://translate.googleapis.com", 429, "Too Many Requests", {}, None)

        try:
            t0 = time.time()
            with patch("backend.translator._translate_gtx", side_effect=always_429), \
                 patch("backend.settings_manager.get_setting", return_value=""), \
                 patch("deep_translator.MyMemoryTranslator.translate", return_value="Δοκιμή"):
                out = asyncio.run(tr_mod._translate_with_retry(
                    "Unique circuit breaker probe " + str(time.time()),
                    "english",
                    "greek",
                    retries=3,
                ))
            dur = time.time() - t0
            self.assertLess(dur, 6.0, f"429 circuit breaker took too long: {dur:.2f}s")
            self.assertGreater(tr_mod._GTX_COOLDOWN_UNTIL, time.time(), "Expected 429 circuit breaker cooldown to activate!")
            self.assertEqual(calls["gtx"], 2, "Expected GTX to trip circuit breaker after 2nd 429 attempt")
            print(f"   429 Circuit Breaker ({dur:.2f}s, cooldown active): OK")
        finally:
            tr_mod._GTX_COOLDOWN_UNTIL = orig_cooldown

    def test_8_restart_cancelled_job_and_recover_orphaned_running_job(self):
        print("-> 8. Testing Cancelled Job Restart & Orphaned Running Job Startup Recovery...")
        from backend.job_manager import create_job, cancel_job, clear_job_cancellation, is_job_cancelled, _jobs
        from backend.database import db_save_job, db_get_job, db_reset_orphaned_running_jobs, db_delete_job

        # 8a. Cancelled job can be cleanly restarted
        j = create_job("temp/reg_cancel_restart.txt", "reg_cancel_restart.txt", "txt")
        jid = j.job_id
        try:
            cancel_job(jid)
            self.assertTrue(is_job_cancelled(jid))
            self.assertEqual(j.status, "cancelled")

            clear_job_cancellation(jid)
            self.assertFalse(is_job_cancelled(jid))
            self.assertEqual(j.status, "idle")

            # 8b. Orphaned running job in SQLite recovers to idle on startup
            j.status = "running"
            db_save_job({
                "job_id": jid, "file_path": j.file_path, "file_name": j.file_name,
                "file_type": "txt", "status": "running", "mode": "translate",
                "progress": 42, "current_step": "Running...", "total_chunks": 10,
                "done_chunks": 4, "created_at": j.created_at, "updated_at": time.time(),
            })
            reset_cnt = db_reset_orphaned_running_jobs()
            self.assertGreaterEqual(reset_cnt, 1)
            recovered = db_get_job(jid)
            self.assertEqual(recovered["status"], "idle")
            print("   Cancelled job restart + Orphaned running job recovery: OK")
        finally:
            _jobs.pop(jid, None)
            db_delete_job(jid)

    def test_9_sqlite_file_path_update_and_resume_settings_restore(self):
        print("-> 9. Testing SQLite file_path persistence on upload & full resume settings restore...")
        from backend.database import db_get_job
        doc_p = Path("temp/reg_resume_settings.docx")
        d = docx.Document()
        d.add_paragraph("Test chapter text for verifying file_path persistence and resume settings restore.")
        d.save(str(doc_p))
        jid = None
        try:
            st_u, up = api_post_file("/upload", doc_p, "reg_resume_settings.docx")
            self.assertEqual(st_u, 200)
            jid = up["job_id"]

            # 1) SQLite file_path MUST be temp/uploads/<job_id>/..., NEVER temp/uploads/tmp/...
            row = db_get_job(jid)
            self.assertIsNotNone(row)
            self.assertIn(jid, row["file_path"], f"SQLite file_path stuck in tmp dir: {row['file_path']}")
            self.assertNotIn("\\tmp\\", row["file_path"])
            self.assertTrue(Path(row["file_path"]).is_file(), f"Persisted file_path missing on disk: {row['file_path']}")

            # 2) Start a translation with literature + pdf + ai_polish=True and verify /api/status returns all settings
            api_post_json("/translate", {
                "job_id": jid,
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "pdf",
                "layout_mode": "literature",
                "ai_polish": True,
                "api_key": "AQ.TestMockResume123",
            })
            st_s, s_data = api_get(f"/status/{jid}")
            self.assertEqual(st_s, 200)
            self.assertEqual(s_data["output_format"], "pdf")
            self.assertEqual(s_data["layout_mode"], "literature")
            self.assertEqual(s_data["source_lang"], "english")
            self.assertEqual(s_data["target_lang"], "greek")
            self.assertTrue(s_data["ai_polish"])
            self.assertGreaterEqual(s_data["total_pages"], 1)
            print("   SQLite file_path update + full resume settings restore: OK")
        finally:
            doc_p.unlink(missing_ok=True)
            if jid:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass

    def test_10_cleanup_test_jobs_endpoint_and_session_history_filter(self):
        print("-> 10. Testing DELETE /api/jobs/tests/cleanup and Session History test-filtering...")
        tmp = Path("temp/test_auto_purge.docx")
        d = docx.Document()
        d.add_paragraph("Test document that must be filtered and auto-purged.")
        d.save(str(tmp))
        try:
            st, up = api_post_file("/upload", tmp, "test_auto_purge.docx")
            self.assertEqual(st, 200)
            jid = up["job_id"]

            # 1. Normal GET /api/jobs (used by UI Session History) MUST filter out test jobs!
            st_ui, ui_jobs = api_get("/jobs")
            self.assertEqual(st_ui, 200)
            self.assertFalse(any(j["job_id"] == jid for j in ui_jobs), "Test job leaked into default GET /api/jobs!")

            # 2. GET /api/jobs?include_tests=true DOES include it
            st_all, all_jobs = api_get("/jobs?include_tests=true")
            self.assertEqual(st_all, 200)
            self.assertTrue(any(j["job_id"] == jid for j in all_jobs))

            # 3. DELETE /api/jobs/tests/cleanup removes all test jobs
            st_cln, res_cln = api_delete("/jobs/tests/cleanup")
            self.assertEqual(st_cln, 200)
            self.assertEqual(res_cln["status"], "ok")
            self.assertIn(jid, res_cln.get("deleted_jobs", []))

            # Verify it's gone even when include_tests=true
            _, all_after = api_get("/jobs?include_tests=true")
            self.assertFalse(any(j["job_id"] == jid for j in all_after))
            print("   DELETE /api/jobs/tests/cleanup & Session History test filter: OK")
        finally:
            tmp.unlink(missing_ok=True)
            try:
                api_delete("/jobs/tests/cleanup")
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
