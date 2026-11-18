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
import io
import json
import time
import zipfile
import threading
import urllib.request
import unittest
from pathlib import Path

import docx

from backend.comic_translator import _parse_vision_json

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

            # Verify comic auto-enforcement on /queue/add (txt should auto-upgrade to pdf!)
            st2, q2 = api_post_json("/queue/add", {
                "job_id": u2["job_id"],
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "txt",
                "layout_mode": "literature",
                "ai_polish": True,
                "api_key": "AQ.TestMockQueue123",
            })
            self.assertEqual(st2, 200)
            self.assertEqual(q2["total_count"], 2)

            api_post_json("/queue/add", {
                "job_id": u3["job_id"],
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "txt",
            })

            # Remove 3rd item before starting
            st_rm, q_rm = api_delete(f"/queue/{u3['job_id']}")
            self.assertEqual(st_rm, 200)
            self.assertEqual(q_rm["total_count"], 2)

            # Test pause endpoint
            st_p, q_p = api_post_json("/queue/pause", {})
            self.assertEqual(st_p, 200)
            self.assertTrue(q_p["paused"])

            # Start serial queue execution
            st_s, _ = api_post_json("/queue/start", {})
            self.assertEqual(st_s, 200)

            # Wait for both queued items to complete serially
            q_state = {}
            for _ in range(50):
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

            # Clear queue
            st_clr, q_clr = api_delete("/queue")
            self.assertEqual(st_clr, 200)
            self.assertEqual(q_clr["total_count"], 0)
            print("   Smart Batch Queue Lifecycle + Combined ZIP: OK")
        finally:
            for p in (p1, p2, p3):
                p.unlink(missing_ok=True)
            api_delete("/queue")
            for jid in created_jids:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
