"""
tests/test_smart_batch_queue.py - Comprehensive Suite #29 covering:
1. Malformed Gemini Vision JSON recovery (_parse_vision_json handling Expecting ',' delimiter,
   markdown fences, trailing commas, unescaped quotes, and truncated arrays without crashing!).
2. Smart Batch Queue full lifecycle via HTTP API:
   - POST /api/queue/add (mixed documents + comic format enforcement)
   - GET /api/queue
   - POST /api/queue/auto-start
   - POST /api/queue/pause
   - POST /api/queue/start (serial execution of 2 documents with mock Single-Pass AI)
   - GET /api/queue/download-all (valid ZIP containing all translated outputs)
   - DELETE /api/queue/{job_id}
   - DELETE /api/queue
"""

import sys
sys.path.insert(0, ".")
import asyncio
import io
import json
import time
import zipfile
import threading
import urllib.error
import urllib.request
import unittest
from pathlib import Path

import docx

from backend.comic_translator import _parse_vision_json
from backend import queue_manager
from backend.job_manager import create_job, get_job, update_job, register_task, unregister_task, _jobs
from backend.database import db_delete_job

API = "http://127.0.0.1:8000/api"


def ensure_server():
    try:
        with urllib.request.urlopen(f"{API}/health", timeout=0.8):
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
            with urllib.request.urlopen(f"{API}/health", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)


def api_get(path):
    with urllib.request.urlopen(f"{API}{path}", timeout=20) as resp:
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


def api_delete(path):
    req = urllib.request.Request(f"{API}{path}", method="DELETE")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_post_file(path, filepath, filename):
    boundary = "----TestBatchQueueBoundary555"
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


class TestSmartBatchQueueAndVisionJson(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ensure_server()

    def test_1_vision_json_parser_recovers_malformed_responses(self):
        print("-> 1. Testing Resilient Gemini Vision JSON Parser (malformed delimiter, fences, truncation)...")
        # Case A: Markdown code fence + trailing comma
        fenced = '```json\n[{"box_2d": [10, 20, 100, 200], "translated_text": "Γεια σου!", "bg_color": "#ffffff",},]\n```'
        res_a = _parse_vision_json(fenced)
        self.assertIsNotNone(res_a)
        self.assertEqual(len(res_a), 1)
        self.assertEqual(res_a[0]["translated_text"], "Γεια σου!")

        # Case B: Missing comma / unescaped quote inside dialogue (exact "Expecting ',' delimiter" bug!)
        malformed = (
            '[\n'
            '  {"box_2d": [100, 100, 200, 400], "original_text": "Wait!", "translated_text": "Περίμενε!"}\n'
            '  {"box_2d": [300, 100, 450, 500], "original_text": "He said "run" now", "translated_text": "Είπε τρέξε τώρα", "bg_color": "#ffffff"}\n'
            ']'
        )
        res_b = _parse_vision_json(malformed)
        self.assertIsNotNone(res_b, "Malformed Vision JSON must recover valid balloon objects instead of raising!")
        self.assertGreaterEqual(len(res_b), 2)
        self.assertEqual(res_b[0]["translated_text"], "Περίμενε!")
        self.assertEqual(res_b[1]["translated_text"], "Είπε τρέξε τώρα")

        # Case C: Completely garbage non-JSON returns None cleanly (never raises ValueError)
        res_c = _parse_vision_json("Sorry, I cannot process this image.")
        self.assertIsNone(res_c)
        print("   Resilient Vision JSON Parser: OK")

    def test_2_smart_batch_queue_full_serial_lifecycle_and_zip(self):
        print("-> 2. Testing Smart Batch Queue Full Lifecycle (Add, Auto-Start, Pause, Start, ZIP, Remove, Clear)...")
        # Ensure clean queue state
        api_delete("/queue")
        api_post_json("/queue/auto-start", {"auto_start": False})

        p1 = Path("temp/test_queue_book_1.docx")
        p2 = Path("temp/test_queue_book_2.docx")
        p3 = Path("temp/test_queue_remove.docx")
        for p, txt in [
            (p1, "The starship Theseus crossed the dark frontier."),
            (p2, "Chapter Two: The silence deepened across the hull."),
            (p3, "Temporary document to test single queue removal."),
        ]:
            d = docx.Document()
            d.add_paragraph(txt)
            d.save(str(p))

        created_jids = []
        try:
            _, u1 = api_post_file("/upload", p1, "test_queue_book_1.docx")
            _, u2 = api_post_file("/upload", p2, "test_queue_book_2.docx")
            _, u3 = api_post_file("/upload", p3, "test_queue_remove.docx")
            created_jids.extend([u1["job_id"], u2["job_id"], u3["job_id"]])

            # Add all 3 to queue (manual mode, so nothing starts yet)
            st1, q1 = api_post_json("/queue/add", {
                "job_id": u1["job_id"],
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "docx",
                "layout_mode": "literature",
                "ai_polish": True,
                "api_key": "AQ.TestMockQueue123",
            })
            self.assertEqual(st1, 200)
            self.assertEqual(q1["queued_count"], 1)

            # Verify comic auto-enforcement & non-comic mixed-batch protection on /queue/add
            st2, q2 = api_post_json("/queue/add", {
                "job_id": u2["job_id"],
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "cbz",      # non-comic must NOT inherit cbz!
                "layout_mode": "comic",      # non-comic must NOT inherit comic!
                "ai_polish": True,
                "api_key": "AQ.TestMockQueue123",
                "is_comic": False,
            })
            self.assertEqual(st2, 200)
            self.assertEqual(q2["total_count"], 2)
            item2 = next(it for it in q2["items"] if it["job_id"] == u2["job_id"])
            self.assertEqual(item2["output_format"], "pdf", "Non-comic book must downgrade cbz to pdf in mixed batch!")
            self.assertEqual(item2["layout_mode"], "standard", "Non-comic book must not inherit comic layout in mixed batch!")

            # Verify comic item auto-upgrades txt -> pdf and locks layout_mode -> comic
            api_post_json("/queue/add", {
                "job_id": u3["job_id"],
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "txt",
                "layout_mode": "standard",
                "is_comic": True,
                "is_scanned": True,
            })
            _, q_comic = api_get("/queue")
            item3 = next(it for it in q_comic["items"] if it["job_id"] == u3["job_id"])
            self.assertEqual(item3["output_format"], "pdf", "Comic item must auto-upgrade txt -> pdf")
            self.assertEqual(item3["layout_mode"], "comic", "Comic item must lock layout_mode -> comic")
            self.assertTrue(item3["ai_polish"], "Scanned comic item must auto-enable ai_polish")

            # Remove 3rd item before starting -> verify job status resets from queued back to idle!
            st_rm, q_rm = api_delete(f"/queue/{u3['job_id']}")
            self.assertEqual(st_rm, 200)
            self.assertEqual(q_rm["total_count"], 2)
            _, u3_status = api_get(f"/status/{u3['job_id']}")
            self.assertEqual(u3_status["status"], "idle", "Removing queued item must reset its job status to idle!")

            # Test pause endpoint
            st_p, q_p = api_post_json("/queue/pause", {})
            self.assertEqual(st_p, 200)
            self.assertTrue(q_p["paused"])

            # Start serial queue execution
            st_s, _ = api_post_json("/queue/start", {})
            self.assertEqual(st_s, 200)

            # Wait for both queued items to complete serially
            q_state = {}
            for _ in range(60):
                time.sleep(0.25)
                _, q_state = api_get("/queue")
                if not q_state["is_running"] and q_state["done_count"] == 2:
                    break

            self.assertEqual(q_state["done_count"], 2, f"Expected 2 done queue items, got: {q_state}")

            # Download combined ZIP archive
            with urllib.request.urlopen(f"{API}/queue/download-all", timeout=15) as zresp:
                self.assertEqual(zresp.status, 200)
                zip_bytes = zresp.read()
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    names = zf.namelist()
                    self.assertEqual(len(names), 2, f"Expected 2 files in batch ZIP, got: {names}")

            # Test retry endpoint on a completed item (re-queues & re-runs cleanly)
            st_retry, q_retry = api_post_json(f"/queue/{u1['job_id']}/retry", {})
            self.assertEqual(st_retry, 200)
            for _ in range(40):
                time.sleep(0.25)
                _, q_retry = api_get("/queue")
                if not q_retry["is_running"] and q_retry["done_count"] == 2:
                    break
            self.assertEqual(q_retry["done_count"], 2, f"Expected retried item to finish cleanly: {q_retry}")

            # Pause then clear queue -> clearing empty queue must reset paused=False!
            api_post_json("/queue/pause", {})
            st_clr, q_clr = api_delete("/queue")
            self.assertEqual(st_clr, 200)
            self.assertEqual(q_clr["total_count"], 0)
            self.assertFalse(q_clr["paused"], "Clearing an empty queue must reset paused flag to False!")
            print("   Smart Batch Queue Lifecycle + Mixed Batch + Retry + ZIP: OK")
        finally:
            for p in (p1, p2, p3):
                p.unlink(missing_ok=True)
            api_delete("/queue")
            for jid in created_jids:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass

    def test_3_queue_validation_and_history_delete_sync(self):
        print("-> 3. Testing Queue Validation (400/404), Re-Queueing Done Jobs, Auto-Start, & Delete Sync...")
        api_delete("/queue")
        api_post_json("/queue/auto-start", {"auto_start": False})

        p1 = Path("temp/test_queue_val_1.docx")
        d = docx.Document()
        d.add_paragraph("Short validation document for batch queue edge cases.")
        d.save(str(p1))
        jid = None
        try:
            # 0) Empty 0-byte DOCX must be rejected cleanly with HTTP 400 (instead of cryptic 'Package not found')
            empty_p = Path("temp/test_empty_zero_bytes.docx")
            empty_p.write_bytes(b"")
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx_empty:
                    api_post_file("/upload", empty_p, "test_empty_zero_bytes.docx")
                self.assertEqual(ctx_empty.exception.code, 400)
            finally:
                empty_p.unlink(missing_ok=True)

            _, u1 = api_post_file("/upload", p1, "test_queue_val_1.docx")
            jid = u1["job_id"]

            # 1) Same source & target language must return HTTP 400
            with self.assertRaises(urllib.error.HTTPError) as ctx_400:
                api_post_json("/queue/add", {
                    "job_id": jid,
                    "source_lang": "english",
                    "target_lang": "english",
                    "output_format": "txt",
                })
            self.assertEqual(ctx_400.exception.code, 400)

            # 2) Nonexistent job_id must return HTTP 404
            with self.assertRaises(urllib.error.HTTPError) as ctx_404:
                api_post_json("/queue/add", {
                    "job_id": "nonexistent-queue-job-xyz",
                    "source_lang": "english",
                    "target_lang": "greek",
                    "output_format": "txt",
                })
            self.assertEqual(ctx_404.exception.code, 404)

            # 3) Enable Auto-Start -> adding a job immediately translates it!
            api_post_json("/queue/auto-start", {"auto_start": True})
            st_a, _ = api_post_json("/queue/add", {
                "job_id": jid,
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "txt",
                "ai_polish": True,
                "api_key": "AQ.TestMockQueue123",
            })
            self.assertEqual(st_a, 200)
            q_st = {}
            for _ in range(40):
                time.sleep(0.25)
                _, q_st = api_get("/queue")
                if not q_st["is_running"] and q_st["done_count"] == 1:
                    break
            self.assertEqual(q_st["done_count"], 1, f"Auto-start did not complete queued job: {q_st}")

            # 4) Turn off auto-start, re-queue the DONE job with new format -> status must stay 'queued', not flip back to 'done'!
            api_post_json("/queue/auto-start", {"auto_start": False})
            _, q_re = api_post_json("/queue/add", {
                "job_id": jid,
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "docx",
                "ai_polish": True,
                "api_key": "AQ.TestMockQueue123",
            })
            self.assertEqual(q_re["queued_count"], 1, f"Re-queued done job must have status='queued', got: {q_re}")
            self.assertEqual(q_re["items"][0]["output_format"], "docx")

            # 5) Deleting the job from Session History (/api/jobs/{id}) must automatically purge it from Queue (no zombie!)
            api_delete(f"/jobs/{jid}")
            jid = None
            _, q_after_del = api_get("/queue")
            self.assertEqual(q_after_del["total_count"], 0, f"Deleted job remained as zombie in queue: {q_after_del}")
            print("   Queue Validation + Auto-Start + Re-Queue + Delete Sync: OK")
        finally:
            p1.unlink(missing_ok=True)
            api_post_json("/queue/auto-start", {"auto_start": False})
            api_delete("/queue")
            if jid:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass

    def test_4_isolated_cancel_pause_resume_and_error_recovery(self):
        print("-> 4. Testing Isolated Cancel-While-Running, Pause/Resume Mid-Batch, and Error->Retry Recovery...")

        async def _run_scenarios():
            # Save & restore queue_manager globals cleanly
            orig_items = list(queue_manager._queue_items)
            orig_paused = queue_manager._queue_paused
            orig_auto = queue_manager._queue_auto_start
            temp_jids = []
            try:
                queue_manager._queue_items.clear()
                queue_manager._queue_paused = False
                queue_manager._queue_auto_start = False

                j1 = create_job("temp/q_iso_1.txt", "q_iso_1.txt", "txt")
                j2 = create_job("temp/q_iso_2.txt", "q_iso_2.txt", "txt")
                j3 = create_job("temp/q_iso_3.txt", "q_iso_3.txt", "txt")
                temp_jids.extend([j1.job_id, j2.job_id, j3.job_id])

                # Scenario A: Cancelling/removing running item 1 cancels ONLY item 1; item 2 completes!
                queue_manager.add_to_queue(j1.job_id, "english", "greek", "txt")
                queue_manager.add_to_queue(j2.job_id, "english", "greek", "txt")
                started_j1 = asyncio.Event()
                completed = []

                async def worker_cancel_test(item):
                    task = asyncio.current_task()
                    register_task(item.job_id, task)
                    try:
                        update_job(item.job_id, status="running", progress=10)
                        if item.job_id == j1.job_id:
                            started_j1.set()
                            await asyncio.sleep(5.0)  # will be cancelled
                        else:
                            await asyncio.sleep(0.05)
                        update_job(item.job_id, status="done", progress=100, output_path="temp/fake.txt")
                        completed.append(item.job_id)
                    except asyncio.CancelledError:
                        update_job(item.job_id, status="cancelled")
                        raise
                    finally:
                        unregister_task(item.job_id)

                queue_manager.start_queue(worker_cancel_test)
                await asyncio.wait_for(started_j1.wait(), timeout=2.0)
                # Remove running item 1 -> must cancel ONLY j1's child task and auto-continue to j2!
                self.assertTrue(queue_manager.remove_from_queue(j1.job_id))
                await asyncio.wait_for(queue_manager._queue_task, timeout=3.0)
                self.assertEqual(completed, [j2.job_id], "Queue must continue and complete j2 after cancelling running j1!")

                # Scenario B: Pause mid-batch stops after active item; Resume completes remaining item; Error -> Retry succeeds!
                queue_manager.clear_queue()
                queue_manager.add_to_queue(j1.job_id, "english", "greek", "txt")
                queue_manager.add_to_queue(j3.job_id, "english", "greek", "txt")
                fail_once = {"j1": True}
                started_j1_b = asyncio.Event()

                async def worker_pause_retry(item):
                    update_job(item.job_id, status="running", progress=25)
                    if item.job_id == j1.job_id:
                        started_j1_b.set()
                        await asyncio.sleep(0.08)
                        if fail_once["j1"]:
                            fail_once["j1"] = False
                            update_job(item.job_id, status="error", error="Simulated transient error")
                            return
                    else:
                        await asyncio.sleep(0.05)
                    update_job(item.job_id, status="done", progress=100, output_path="temp/fake.txt")

                queue_manager.start_queue(worker_pause_retry)
                await asyncio.wait_for(started_j1_b.wait(), timeout=2.0)
                queue_manager.pause_queue()  # pause BEFORE j3 starts
                await asyncio.wait_for(queue_manager._queue_task, timeout=3.0)

                st_mid = queue_manager.get_queue_state()
                s_map = {it["job_id"]: it["status"] for it in st_mid["items"]}
                self.assertEqual(s_map[j1.job_id], "error", "j1 should record transient error")
                self.assertEqual(s_map[j3.job_id], "queued", "j3 must stay queued while paused!")

                # Retry j1 & resume queue -> both j1 and j3 must finish done!
                queue_manager.retry_queue_item(j1.job_id)
                queue_manager.start_queue(worker_pause_retry)
                await asyncio.wait_for(queue_manager._queue_task, timeout=3.0)

                st_end = queue_manager.get_queue_state()
                self.assertEqual(st_end["done_count"], 2, f"Expected both j1 (retried) & j3 done, got: {st_end}")

                # Scenario C: Max 20 files limit & apply_settings_to_queued_items mixed-batch safety!
                queue_manager.clear_queue()
                self.assertEqual(queue_manager.get_queue_state()["max_items"], 20)
                extra_jids = []
                try:
                    for idx in range(21):
                        ft = "cbz" if idx == 0 else "docx"
                        fn = f"batch_limit_{idx}.{ft}"
                        jx = create_job(f"temp/{fn}", fn, ft)
                        extra_jids.append(jx.job_id)
                        if idx < 20:
                            queue_manager.add_to_queue(jx.job_id, "english", "greek", "txt", "standard", ai_polish=False)
                        else:
                            with self.assertRaises(ValueError):
                                queue_manager.add_to_queue(jx.job_id, "english", "greek", "txt", "standard", ai_polish=False)

                    # Apply updated Translation Settings (literature + pdf + ai_polish=True) to all 20 queued items
                    updated_cnt = queue_manager.apply_settings_to_queued_items(
                        source_lang="english",
                        target_lang="greek",
                        output_format="pdf",
                        layout_mode="literature",
                        ai_polish=True,
                    )
                    self.assertEqual(updated_cnt, 20)
                    st_cap = queue_manager.get_queue_state()
                    self.assertEqual(st_cap["total_count"], 20)
                    # Item 0 (CBZ comic) must stay layout='comic', output_format='pdf'
                    self.assertEqual(st_cap["items"][0]["layout_mode"], "comic")
                    self.assertEqual(st_cap["items"][0]["output_format"], "pdf")
                    # Item 1 (DOCX book) must update to layout='literature', output_format='pdf', ai_polish=True
                    self.assertEqual(st_cap["items"][1]["layout_mode"], "literature")
                    self.assertEqual(st_cap["items"][1]["output_format"], "pdf")
                    self.assertTrue(st_cap["items"][1]["ai_polish"])
                finally:
                    queue_manager.clear_queue()
                    for ejid in extra_jids:
                        _jobs.pop(ejid, None)
                        db_delete_job(ejid)
            finally:
                queue_manager._queue_items.clear()
                queue_manager._queue_items.extend(orig_items)
                queue_manager._queue_paused = orig_paused
                queue_manager._queue_auto_start = orig_auto
                for jid in temp_jids:
                    _jobs.pop(jid, None)
                    db_delete_job(jid)

        asyncio.run(_run_scenarios())
        print("   Isolated Cancel + Pause/Resume + Error->Retry Recovery: OK")


if __name__ == "__main__":
    unittest.main()
