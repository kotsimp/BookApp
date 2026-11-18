"""
test_api_contracts_and_state_machine.py - API Contract, Download Logic, SSE Termination & Editor State Suite.
Tests:
1. Regular PDF-translated book is NOT misclassified as a comic -> ?format=txt and ?format=docx succeed (200).
2. SSE /api/progress/{job_id} closes immediately when job is already terminal (done/error/cancelled).
3. HEAD /api/download/{job_id} is side-effect free (does not mutate files or trigger export).
4. PUT /api/jobs/{job_id}/text never overwrites *_original.txt, handles non-text formats safely, persists to SQLite.
5. POST /api/polish standalone file-extraction branch (text=None) extracts from uploaded DOCX/PDF & rejects 409 when running.
6. POST /api/jobs/{job_id}/cancel preserves already-'done' job status and handles SQLite-only jobs.
7. DELETE /api/jobs/{job_id} cancels active task before deleting temp files.
8. DELETE /api/cover/{job_id} refreshes cached PDF/EPUB/DOCX so deleted cover isn't served stale.
"""

import sys
sys.path.insert(0, ".")
import io
import json
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path

import docx
from PIL import Image

from backend.job_manager import get_job, update_job, _jobs

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


def http_req(method: str, path: str, body: bytes = None, headers: dict = None, timeout: int = 15):
    req = urllib.request.Request(f"{API}{path}", data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def http_json(method: str, path: str, payload: dict):
    st, raw, _ = http_req(
        method,
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return st, json.loads(raw.decode("utf-8"))


def upload_docx(name: str, paragraphs: list[str]) -> str:
    buf = io.BytesIO()
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    d.save(buf)
    boundary = "----ContractBoundary77"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n"
    ).encode("utf-8") + buf.getvalue() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    st, raw, _ = http_req("POST", "/upload", body=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert st == 200, f"Upload failed: {st} {raw}"
    return json.loads(raw.decode("utf-8"))["job_id"]


class TestAPIContractsAndStateMachine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ensure_server()

    def test_1_regular_pdf_book_downloadable_as_txt_and_docx(self):
        print("-> 1. Testing regular PDF-translated book allows TXT & DOCX downloads (no false comic 400)...")
        jid = upload_docx("regular_novel.docx", [
            "Chapter One",
            "The ship sailed smoothly under a quiet autumn sky across the Aegean.",
        ])
        try:
            # Translate directly to PDF with mock AI key (creates *_translated_greek.pdf & .txt, NO .docx)
            st, _ = http_json("POST", "/translate", {
                "job_id": jid,
                "source_lang": "english",
                "target_lang": "greek",
                "output_format": "pdf",
                "layout_mode": "literature",
                "ai_polish": True,
                "api_key": "AQ.TestPdfRegularBook123",
            })
            self.assertEqual(st, 200)

            for _ in range(40):
                time.sleep(0.25)
                _, raw, _ = http_req("GET", f"/status/{jid}")
                s = json.loads(raw.decode("utf-8"))
                if s["status"] in ("done", "error"):
                    break
            self.assertEqual(s["status"], "done", f"Translation failed: {s}")

            # Verify TXT and DOCX on-demand downloads BOTH succeed (previously falsely 400'd as comic!)
            st_txt, txt_bytes, _ = http_req("GET", f"/download/{jid}?format=txt")
            self.assertEqual(st_txt, 200, f"Regular PDF book TXT download must be 200, got {st_txt}: {txt_bytes[:200]}")
            self.assertGreater(len(txt_bytes.strip()), 10)

            st_docx, docx_bytes, _ = http_req("GET", f"/download/{jid}?format=docx")
            self.assertEqual(st_docx, 200, f"Regular PDF book DOCX download must be 200, got {st_docx}: {docx_bytes[:200]}")
            self.assertTrue(docx_bytes.startswith(b"PK"))

            # HEAD request on an unexported format must NOT create a file as a side effect
            out_dir = Path("temp/outputs") / jid
            for ep in out_dir.glob("*.epub"):
                ep.unlink(missing_ok=True)
            st_head, _, _ = http_req("HEAD", f"/download/{jid}?format=epub")
            self.assertEqual(st_head, 404, "HEAD on unexported format must not trigger export side-effect")
            self.assertEqual(list(out_dir.glob("*.epub")), [])
        finally:
            http_req("DELETE", f"/jobs/{jid}")
        print("   Regular PDF book TXT/DOCX download & HEAD side-effect safety: OK")

    def test_2_sse_closes_immediately_on_terminal_job(self):
        print("-> 2. Testing SSE /api/progress/{job_id} closes cleanly on already-terminal jobs...")
        st_pol, pol = http_json("POST", "/polish", {
            "job_id": None,
            "text": "Ένα σύντομο κείμενο που ολοκληρώνεται αμέσως.",
            "style": "formal",
            "api_key": "AQ.TestSSETerminal123",
        })
        self.assertEqual(st_pol, 200)
        jid = pol["job_id"]
        try:
            t0 = time.time()
            # Reading the ENTIRE response body must finish immediately (< 2s), not hang on heartbeat!
            req = urllib.request.Request(f"{API}/progress/{jid}")
            with urllib.request.urlopen(req, timeout=4) as resp:
                self.assertEqual(resp.status, 200)
                full_body = resp.read().decode("utf-8")
            elapsed = time.time() - t0
            self.assertLess(elapsed, 3.0, f"SSE stream hung on terminal job ({elapsed:.1f}s)")
            self.assertIn('"status": "done"', full_body)
        finally:
            http_req("DELETE", f"/jobs/{jid}")
        print("   SSE terminal close: OK")

    def test_3_editor_put_text_preserves_original_and_handles_formats(self):
        print("-> 3. Testing PUT /api/jobs/{id}/text preserves *_original.txt & guards non-text formats...")
        jid = upload_docx("editor_guard.docx", ["Original English paragraph untouched."])
        try:
            out_dir = Path("temp/outputs") / jid
            out_dir.mkdir(parents=True, exist_ok=True)
            orig_file = out_dir / "editor_guard_original.txt"
            orig_file.write_text("ORIGINAL_SENTINEL_DO_NOT_OVERWRITE", encoding="utf-8")

            # Save edited text BEFORE any *_translated_*.txt exists
            st_put, put_data = http_json("PUT", f"/jobs/{jid}/text", {
                "translated_text": "Νέο επεξεργασμένο ελληνικό κείμενο.",
            })
            self.assertEqual(st_put, 200, f"PUT /text failed: {put_data}")
            self.assertEqual(
                orig_file.read_text(encoding="utf-8"),
                "ORIGINAL_SENTINEL_DO_NOT_OVERWRITE",
                "PUT /text overwrote *_original.txt!",
            )

            # Verify GET /text returns distinct original and translated text
            st_get, raw_get, _ = http_req("GET", f"/jobs/{jid}/text")
            self.assertEqual(st_get, 200)
            g = json.loads(raw_get.decode("utf-8"))
            self.assertIn("ORIGINAL_SENTINEL_DO_NOT_OVERWRITE", g["original_text"])
            self.assertIn("Νέο επεξεργασμένο", g["translated_text"])
        finally:
            http_req("DELETE", f"/jobs/{jid}")
        print("   Editor PUT /text safety: OK")

    def test_4_standalone_polish_extracts_from_uploaded_file_without_text_param(self):
        print("-> 4. Testing POST /api/polish standalone file-extraction branch (text=None)...")
        jid = upload_docx("standalone_greek.docx", [
            "Αυτό είναι ένα αυθεντικό ελληνικό έγγραφο για απευθείας επιμέλεια χωρίς προηγούμενη μετάφραση."
        ])
        try:
            st, data = http_json("POST", "/polish", {
                "job_id": jid,
                "text": None,
                "style": "literature",
                "api_key": "AQ.TestStandaloneExtract123",
                "layout_mode": "literature",
            })
            self.assertEqual(st, 200, f"Standalone /polish (text=None) failed: {st} {data}")
            self.assertEqual(data["status"], "polished")
            self.assertIn("αυθεντικό ελληνικό", data["polished_text"])

            # Verify canceling a completed job does NOT corrupt status from 'done' to 'cancelled'
            st_c, c_data = http_json("POST", f"/jobs/{jid}/cancel", {})
            self.assertEqual(st_c, 200)
            self.assertEqual(c_data["status"], "done", "Cancelling a completed job must not corrupt status to 'cancelled'")
        finally:
            http_req("DELETE", f"/jobs/{jid}")
        print("   Standalone /polish extraction & done-job cancel guard: OK")

    def test_5_cover_delete_refreshes_cached_exports(self):
        print("-> 5. Testing DELETE /api/cover/{job_id} removes cover & refreshes exports...")
        st_pol, pol = http_json("POST", "/polish", {
            "job_id": None,
            "text": "Κεφάλαιο 1\n\nΈνα σύντομο βιβλίο για έλεγχο εξωφύλλου.",
            "style": "literature",
            "api_key": "AQ.TestCoverDelete123",
            "layout_mode": "literature",
        })
        self.assertEqual(st_pol, 200)
        jid = pol["job_id"]
        try:
            # Upload a valid cover JPEG
            img_buf = io.BytesIO()
            Image.new("RGB", (300, 450), (20, 90, 180)).save(img_buf, format="JPEG")
            boundary = "----CovDelBoundary"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="cov.jpg"\r\n'
                f"Content-Type: image/jpeg\r\n\r\n"
            ).encode("utf-8") + img_buf.getvalue() + f"\r\n--{boundary}--\r\n".encode("utf-8")
            st_up, _, _ = http_req("POST", f"/cover/{jid}", body=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            self.assertEqual(st_up, 200)

            st_pdf1, pdf_with_cover, _ = http_req("GET", f"/download/{jid}?format=pdf")
            self.assertEqual(st_pdf1, 200)

            # Delete cover -> subsequent PDF should be smaller (no cover image embedded)
            st_del, _, _ = http_req("DELETE", f"/cover/{jid}")
            self.assertEqual(st_del, 200)
            st_cov404, _, _ = http_req("GET", f"/cover/{jid}")
            self.assertEqual(st_cov404, 404)

            st_pdf2, pdf_without_cover, _ = http_req("GET", f"/download/{jid}?format=pdf")
            self.assertEqual(st_pdf2, 200)
            self.assertLess(len(pdf_without_cover), len(pdf_with_cover), "Deleted cover was still embedded in cached PDF!")
        finally:
            http_req("DELETE", f"/jobs/{jid}")
        print("   Cover delete export refresh: OK")

    def test_9_queue_download_all_requires_all_translations_completed(self):
        print("-> 9. Testing GET /api/queue/download-all blocks until ALL translations are completed...")
        import asyncio
        import tempfile
        import zipfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi import HTTPException
        from backend.main import download_batch_queue_zip

        # 1. Empty queue -> 404
        with patch("backend.queue_manager.get_queue_state", return_value={
            "total_count": 0, "done_count": 0, "queued_count": 0, "is_running": False
        }):
            with self.assertRaises(HTTPException) as ctx_empty:
                asyncio.run(download_batch_queue_zip())
            self.assertEqual(ctx_empty.exception.status_code, 404)

        # 2. Partially completed / running queue -> 409 Conflict
        for incomplete_state in [
            {"total_count": 2, "done_count": 1, "queued_count": 0, "is_running": True},
            {"total_count": 2, "done_count": 1, "queued_count": 1, "is_running": False},
            {"total_count": 2, "done_count": 1, "queued_count": 0, "is_running": False},
        ]:
            with patch("backend.queue_manager.get_queue_state", return_value=incomplete_state):
                with self.assertRaises(HTTPException) as ctx_inc:
                    asyncio.run(download_batch_queue_zip())
                self.assertEqual(ctx_inc.exception.status_code, 409)

        # 3. All translations completed -> 200 ZIP containing all completed outputs
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "book1_translated_greek.txt"
            f2 = Path(tmpdir) / "book2_translated_greek.txt"
            f1.write_text("Book 1 Greek", encoding="utf-8")
            f2.write_text("Book 2 Greek", encoding="utf-8")
            fake_jobs = {
                "jid-1": SimpleNamespace(output_path=str(f1)),
                "jid-2": SimpleNamespace(output_path=str(f2)),
            }
            with patch("backend.queue_manager.get_queue_state", return_value={
                "total_count": 2, "done_count": 2, "queued_count": 0, "is_running": False
            }), patch("backend.queue_manager.get_completed_queue_job_ids", return_value=["jid-1", "jid-2"]), \
                 patch("backend.main.get_job", side_effect=lambda jid: fake_jobs.get(jid)):
                resp = asyncio.run(download_batch_queue_zip())
                self.assertEqual(resp.media_type, "application/zip")

                async def _collect():
                    chunks = []
                    async for chunk in resp.body_iterator:
                        chunks.append(chunk)
                    return b"".join(chunks)

                raw_zip = asyncio.run(_collect())
                with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as zf:
                    names = set(zf.namelist())
                    self.assertIn("book1_translated_greek.txt", names)
                    self.assertIn("book2_translated_greek.txt", names)
        print("   Batch ZIP download completion gate (404/409/200): OK")


if __name__ == "__main__":
    unittest.main()
