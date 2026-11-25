"""
tests/test_bilingual_opds_ntfy_readalong.py - The bilingual edition, the e-reader catalogue (OPDS), phone notifications
(ntfy) and reading along with an audiobook.

1. Bilingual: page markers of both styles, paragraph matching (joined, split, missing paragraphs, whole texts without
   markers), the PDF / DOCX / EPUB files, and the download endpoint (formats, comics, not yet translated).
2. OPDS: secret links (only a hash kept, a new one stops the old), open paths for reading apps, the Atom feed, book
   downloads and the 404 of unknown or removed links.
3. ntfy: server addresses, messages per outcome and language, the notice sent once when a job stops running, the
   settings endpoints and a test message to a local stand-in server.
4. Reading along: sentence times from the parts' durations, and the endpoint ignoring times of an older recording.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import json
import os
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import pymupdf as fitz

from backend import bilingual, connections, job_manager, notify
from backend.database import db_delete_job

API = "http://127.0.0.1:8000/api"
ROOT = "http://127.0.0.1:8000"
ATOM = "{http://www.w3.org/2005/Atom}"

ORIGINAL = ("=== PAGE 1 ===\nChapter One\n\nThe ship sailed at dawn. The sea was grey.\n\nShe watched the harbour.\n\n"
            "=== PAGE 2 ===\n\"Where are we going?\" he asked.\n\n\"North,\" she said.\n\nThey said nothing more.")
TRANSLATED = ("\n" + "=" * 60 + "\nPAGE 1\n" + "=" * 60 + "\n\nΚεφάλαιο Πρώτο\n\nΤο πλοίο σάλπαρε την αυγή. Η θάλασσα "
              "ήταν γκρίζα.\n\nΕκείνη κοίταζε το λιμάνι.\n\n=== PAGE 2 ===\n«Πού πάμε;» ρώτησε. «Βόρεια», είπε εκείνη."
              "\n\nΔεν είπαν τίποτε άλλο.")


class BilingualTests(unittest.TestCase):
    def test_page_markers_of_both_styles(self):
        pages = bilingual.split_pages(TRANSLATED)
        self.assertEqual([p for p, _ in pages], [1, 2])
        self.assertIn("Κεφάλαιο Πρώτο", pages[0][1])
        self.assertEqual(bilingual.split_pages("Before\n=== PAGE 3 ===\nX")[0], (None, "Before\n"))

    def test_paragraphs_matched_page_by_page(self):
        passages = bilingual.bilingual_passages(ORIGINAL, TRANSLATED)
        self.assertEqual([(len(s), len(t)) for s, t in passages], [(1, 1), (1, 1), (1, 1), (2, 1), (1, 1)])
        self.assertEqual(passages[3][0][1], "\"North,\" she said.")
        self.assertTrue(passages[3][1][0].startswith("«Πού πάμε;»"))

    def test_missing_and_split_paragraphs(self):
        src = ["A short line.", "A much longer paragraph " * 8, "An ending."]
        tgt = ["Μια σύντομη γραμμή.", "Μια πολύ μεγαλύτερη παράγραφος " * 4, "Μια πολύ μεγαλύτερη παράγραφος " * 4,
               "Ένα τέλος."]
        groups = bilingual.align(src, tgt)
        self.assertEqual([(len(s), len(t)) for s, t in groups], [(1, 1), (1, 2), (1, 1)])
        self.assertEqual(sum(len(s) for s, _ in groups), 3)
        self.assertEqual(sum(len(t) for _, t in groups), 4)
        groups = bilingual.align(["One.", "Two two two two.", "Three."], ["Ένα.", "Τρία."])
        self.assertEqual(sum(len(s) for s, _ in groups), 3, "every paragraph is kept")
        self.assertEqual(bilingual.align([], ["Μόνο μετάφραση."]), [([], ["Μόνο μετάφραση."])])

    def test_whole_text_without_markers(self):
        src = [f"Paragraph {i}. " + "x" * (40 + i % 90) for i in range(400)]
        tgt = [f"Παράγραφος {i}. " + "χ" * int((40 + i % 90) * 1.1) for i in range(400)]
        tgt[50:52] = [tgt[50] + " " + tgt[51]]
        passages = bilingual.bilingual_passages("\n\n".join(src), "\n\n".join(tgt))
        self.assertEqual([(len(s), len(t)) for s, t in passages if (len(s), len(t)) != (1, 1)], [(2, 1)])
        self.assertTrue(passages[-1][0][0].startswith("Paragraph 399."))
        self.assertTrue(passages[-1][1][0].startswith("Παράγραφος 399."))

    def test_exported_files(self):
        passages = bilingual.bilingual_passages(ORIGINAL, TRANSLATED)
        with tempfile.TemporaryDirectory() as td:
            pdf = bilingual.export_bilingual_pdf(passages, Path(td) / "b.pdf", "Το πλοίο", "sub", "english", "greek")
            with fitz.open(pdf) as doc:
                text = "".join(page.get_text() for page in doc)
            self.assertIn("The ship sailed at dawn.", text)
            self.assertIn("Το πλοίο σάλπαρε την αυγή.", text)
            self.assertLess(text.index("The ship sailed"), text.index("Το πλοίο σάλπαρε"), "the original first")
            from docx import Document
            docx = bilingual.export_bilingual_docx(passages, Path(td) / "b.docx", "T", "sub", "english", "greek")
            paras = [p.text for p in Document(str(docx)).paragraphs]
            self.assertIn("She watched the harbour.", paras)
            self.assertEqual(paras[paras.index("She watched the harbour.") + 1], "Εκείνη κοίταζε το λιμάνι.")
            from ebooklib import epub, ITEM_DOCUMENT
            ep = bilingual.export_bilingual_epub(passages, Path(td) / "b.epub", "T", "sub", "english", "greek")
            html = "".join(i.get_content().decode("utf-8") for i in epub.read_epub(str(ep)).get_items()
                           if i.get_type() == ITEM_DOCUMENT)
            self.assertIn('class="src" lang="en"', html)
            self.assertIn("Δεν είπαν τίποτε άλλο.", html)


class ConnectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(connections, "STORE", Path(self.tmp.name) / "connections.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_secret_links(self):
        self.assertFalse(connections.opds_status("u1")["exists"])
        first = connections.new_opds_token("u1")
        self.assertEqual(connections.owner_for_opds_token(first), "u1")
        self.assertNotIn(first, connections.STORE.read_text(encoding="utf-8"), "only the token's hash is kept")
        second = connections.new_opds_token("u1")
        self.assertIsNone(connections.owner_for_opds_token(first), "a new link stops the old one")
        self.assertEqual(connections.owner_for_opds_token(second), "u1")
        other = connections.new_opds_token("")
        self.assertEqual(connections.owner_for_opds_token(other), "")
        connections.remove_opds_token("u1")
        self.assertIsNone(connections.owner_for_opds_token(second))
        self.assertIsNone(connections.owner_for_opds_token(""))
        self.assertIsNone(connections.owner_for_opds_token("x" * 500))

    def test_open_paths_for_reading_apps(self):
        from backend import auth, device_pairing
        self.assertTrue(auth.is_open_path("/opds/abc/"))
        self.assertTrue(device_pairing.is_open_path("/opds/abc/book/x/epub"))
        self.assertFalse(auth.is_open_path("/opdsx"))
        self.assertFalse(auth.is_open_path("/api/connections"))

    def test_ntfy_settings(self):
        self.assertFalse(connections.ntfy_settings("u2")["enabled"])
        s = connections.set_ntfy("u2", "https://ntfy.example.org", "bookapp-abc123", "http://192.168.1.5:8000", "en")
        self.assertEqual((s["enabled"], s["topic"], s["lang"]), (True, "bookapp-abc123", "en"))
        self.assertFalse(connections.set_ntfy("u2", "https://ntfy.sh", "")["enabled"])


class NotifyTests(unittest.TestCase):
    def test_server_addresses(self):
        self.assertEqual(notify.normalize_server(""), "https://ntfy.sh")
        self.assertEqual(notify.normalize_server("ntfy.example.org/"), "https://ntfy.example.org")
        self.assertEqual(notify.normalize_server("http://192.168.1.9:8080"), "http://192.168.1.9:8080")
        for bad in ("ftp://x.org", "https://user:pw@x.org", "https://x.org/?a=1", "https://"):
            self.assertIsNone(notify.normalize_server(bad), bad)
        self.assertTrue(notify.TOPIC_RE.fullmatch("bookapp-k7x2m9"))
        self.assertIsNone(notify.TOPIC_RE.fullmatch("short"))
        self.assertIsNone(notify.TOPIC_RE.fullmatch("with space here"))

    def test_messages(self):
        job = types.SimpleNamespace(mode="translate", status="done", file_name="Book.pdf", error=None,
                                    sample_range=[1, 12])
        title, body, prio = notify.job_message(job, "el")
        self.assertEqual(title, "✅ Η μετάφραση ολοκληρώθηκε")
        self.assertEqual(body, "«Book.pdf» · δείγμα, σελίδες 1–12")
        job.sample_range = None
        self.assertEqual(notify.job_message(job, "en")[:2], ("✅ Translation finished", "«Book.pdf»"))
        job.status, job.error = "error", "⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier)."
        self.assertEqual(notify.job_message(job, "el")[0], "⏳ Σταμάτησε στο ημερήσιο όριο Gemini")
        job.error = "No text found to convert to audio."
        job.mode = "audiobook"
        title, body, prio = notify.job_message(job, "en")
        self.assertEqual((title, prio), ("⚠️ Audiobook stopped", 4))
        self.assertIn("No text found", body)
        job.status = "cancelled"
        self.assertIsNone(notify.job_message(job))

    def test_sent_once_when_a_job_stops_running(self):
        job = job_manager.create_job("", "notify_test.pdf", "pdf")
        try:
            with mock.patch("backend.notify.job_finished") as finished:
                job_manager.update_job(job.job_id, mode="translate", status="running")
                job_manager.update_job(job.job_id, progress=50)
                self.assertEqual(finished.call_count, 0)
                job_manager.update_job(job.job_id, status="done")
                self.assertEqual(finished.call_count, 1)
                job_manager.update_job(job.job_id, current_step="later")
                job_manager.update_job(job.job_id, status="done")
                self.assertEqual(finished.call_count, 1, "only the end of a run")
                job_manager.update_job(job.job_id, mode="", status="running")
                job_manager.update_job(job.job_id, status="error")
                self.assertEqual(finished.call_count, 1, "not for other kinds of work")
        finally:
            job_manager._jobs.pop(job.job_id, None)
            db_delete_job(job.job_id)

    def test_job_finished_uses_the_owners_settings(self):
        job = types.SimpleNamespace(job_id="j", owner="u9", mode="audiobook", status="done", file_name="A.epub",
                                    error=None, sample_range=None)
        sent = []

        class InlineThread:
            def __init__(self, target, **kw):
                self.target = target

            def start(self):
                self.target()

        with mock.patch("backend.connections.ntfy_settings", return_value={
                "enabled": True, "server": "https://ntfy.example.org", "topic": "bookapp-xyz789",
                "app_url": "http://nas:8000", "lang": "el"}), \
                mock.patch.object(notify, "send", side_effect=lambda *a, **kw: sent.append((a, kw))), \
                mock.patch.object(notify.threading, "Thread", InlineThread):
            notify.job_finished(job)
        self.assertEqual(sent[0][0][:4], ("https://ntfy.example.org", "bookapp-xyz789", "🎧 Το ηχοβιβλίο είναι έτοιμο",
                                          "«A.epub»"))
        self.assertEqual(sent[0][1]["click"], "http://nas:8000")
        with mock.patch("backend.connections.ntfy_settings", return_value={"enabled": False}), \
                mock.patch.object(notify, "send") as never:
            notify.job_finished(job)
        never.assert_not_called()


class ReadAlongTests(unittest.TestCase):
    def test_sentence_times(self):
        from backend.tts_engine import compute_read_along
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.mp3"
            b = Path(td) / "b.mp3"
            a.write_bytes(b"\x00" * 6000)    # 1 s at 48 kbit/s (an unreadable header: timed from its size)
            b.write_bytes(b"\x00" * 12000)   # 2 s
            segs = compute_read_along([
                ("=== PAGE 1 ===\nFirst sentence here. Second one!\n\nA new paragraph.", str(a)),
                ("«Πού πάμε;» ρώτησε. Τέλος.", str(b)),
            ])
        self.assertEqual([s["t"] for s in segs], ["First sentence here.", "Second one!", "A new paragraph.",
                                                  "«Πού πάμε;» ρώτησε.", "Τέλος."])
        self.assertEqual([s["p"] for s in segs], [1, 0, 1, 1, 0])
        self.assertEqual(segs[0]["s"], 0)
        self.assertEqual(segs[3]["s"], 1000, "the second part starts where the first one ends")
        self.assertEqual(segs[-1]["e"], 3000)
        for prev, cur in zip(segs, segs[1:]):
            self.assertEqual(prev["e"], cur["s"])
        self.assertGreater(segs[0]["e"] - segs[0]["s"], segs[1]["e"] - segs[1]["s"], "a longer sentence lasts longer")


# ---------------------------------------------------------------------------
# Through the sandbox server
# ---------------------------------------------------------------------------

def _post_file(filepath: Path, filename: str) -> dict:
    boundary = "----BilingualOpdsBoundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + filepath.read_bytes() + \
        f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _request(url: str, data: dict = None, method: str = None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, resp.headers, resp.read()


def _translated_job(tmp: Path, name: str) -> str:
    pdf = tmp / "book.pdf"
    doc = fitz.open()
    pages = [  # different on every page: lines repeated on each page are running headers to the parser
        "The lighthouse keeper looked at the sea.\n\nNothing moved on the water that morning.",
        "By noon the wind had turned to the north.\n\nHe climbed the stairs to light the lamp early.",
        "The storm reached the island at dusk.\n\nAll night the beam swept over the waves.",
    ]
    for text in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(60, 60, 535, 780), text, fontsize=11)
    doc.save(str(pdf))
    doc.close()
    job_id = _post_file(pdf, name)["job_id"]
    _request(f"{API}/translate", {"job_id": job_id, "source_lang": "english", "target_lang": "greek",
                                  "output_format": "pdf", "ai_polish": False})
    deadline = time.time() + 90
    while time.time() < deadline:
        info = json.loads(_request(f"{API}/status/{job_id}")[2])
        if info["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert info["status"] == "done", {k: info.get(k) for k in ("error", "current_step", "file_type", "total_pages")}
    return job_id


class _FakeNtfy(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        _FakeNtfy.received.append(json.loads(self.rfile.read(length).decode("utf-8")))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class ApiTests(unittest.TestCase):
    """Against the sandbox server that run_all_tests.py starts."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.job_id = _translated_job(Path(cls.tmp.name), "lighthouse.pdf")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_bilingual_download(self):
        status, headers, body = _request(f"{API}/download/{self.job_id}/bilingual?format=pdf")
        self.assertEqual(status, 200)
        self.assertIn("lighthouse_bilingual.pdf", headers.get("content-disposition", ""))
        with fitz.open("pdf", body) as doc:
            text = "".join(p.get_text() for p in doc)
        self.assertIn("The lighthouse keeper looked at the sea.", text)
        self.assertRegex(text, "[α-ω]{3,}", "the translation is there too")
        for fmt in ("docx", "epub"):
            self.assertEqual(_request(f"{API}/download/{self.job_id}/bilingual?format={fmt}")[0], 200)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _request(f"{API}/download/{self.job_id}/bilingual?format=txt")
        self.assertEqual(ctx.exception.code, 400)
        fresh = _post_file(Path(self.tmp.name) / "book.pdf", "untranslated.pdf")["job_id"]
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _request(f"{API}/download/{fresh}/bilingual?format=pdf")
        self.assertEqual(ctx.exception.code, 404)

    def test_opds_catalogue(self):
        _, _, raw = _request(f"{API}/connections/opds", {})
        path = json.loads(raw)["path"]
        self.assertRegex(path, r"^/opds/[A-Za-z0-9_-]{20,}/$")
        status, headers, feed = _request(ROOT + path)
        self.assertEqual(status, 200)
        self.assertIn("application/atom+xml", headers.get("content-type", ""))
        root = ET.fromstring(feed)
        entry = next(e for e in root.findall(f"{ATOM}entry") if e.findtext(f"{ATOM}id") == f"urn:uuid:{self.job_id}")
        self.assertEqual(entry.findtext(f"{ATOM}title"), "lighthouse")
        links = {l.get("type") + "|" + (l.get("title") or ""): l.get("href") for l in entry.findall(f"{ATOM}link")
                 if l.get("rel") == "http://opds-spec.org/acquisition"}
        self.assertIn("application/epub+zip|EPUB", links)
        self.assertIn("application/pdf|PDF", links)
        epub_status, epub_headers, epub_body = _request(ROOT + links["application/epub+zip|EPUB"])
        self.assertEqual(epub_status, 200)
        self.assertTrue(epub_body.startswith(b"PK"), "an EPUB is a ZIP file")
        bilingual_link = next(h for k, h in links.items() if "Bilingual" in k)
        self.assertEqual(_request(ROOT + bilingual_link)[0], 200)
        status_info = json.loads(_request(f"{API}/connections")[2])
        self.assertTrue(status_info["opds"]["exists"])
        for bad in (ROOT + "/opds/not-a-real-token/", ROOT + path + f"book/{self.job_id}/cbz"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                _request(bad)
            self.assertEqual(ctx.exception.code, 404, bad)
        _request(f"{API}/connections/opds", method="DELETE")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _request(ROOT + path)
        self.assertEqual(ctx.exception.code, 404, "a removed link stops working")

    def test_ntfy_settings_and_test_message(self):
        server = HTTPServer(("127.0.0.1", 0), _FakeNtfy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address = f"http://127.0.0.1:{server.server_address[1]}"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                _request(f"{API}/connections/ntfy", {"server": address, "topic": "bad topic!"})
            self.assertEqual(ctx.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                _request(f"{API}/connections/ntfy", {"server": "ftp://x", "topic": "bookapp-abc123"})
            self.assertEqual(ctx.exception.code, 400)
            _request(f"{API}/connections/ntfy/test", {"server": address, "topic": "bookapp-abc123", "lang": "en"})
            self.assertEqual(_FakeNtfy.received[-1]["topic"], "bookapp-abc123")
            self.assertEqual(_FakeNtfy.received[-1]["title"], "🔔 BookApp")
            self.assertIn("Notifications work", _FakeNtfy.received[-1]["message"])
            _, _, raw = _request(f"{API}/connections/ntfy", {"server": address, "topic": "bookapp-abc123",
                                                             "app_url": "http://nas:8000", "lang": "el"})
            self.assertTrue(json.loads(raw)["enabled"])
            self.assertEqual(json.loads(_request(f"{API}/connections")[2])["ntfy"]["server"], address)
            # a finished job reaches the phone
            before = len(_FakeNtfy.received)
            _translated_job(Path(self.tmp.name), "notified.pdf")
            deadline = time.time() + 10
            while len(_FakeNtfy.received) == before and time.time() < deadline:
                time.sleep(0.1)
            self.assertEqual(_FakeNtfy.received[-1]["title"], "✅ Η μετάφραση ολοκληρώθηκε")
            self.assertEqual(_FakeNtfy.received[-1]["message"], "«notified.pdf»")
            self.assertEqual(_FakeNtfy.received[-1]["click"], "http://nas:8000")
            _request(f"{API}/connections/ntfy", {"server": address, "topic": ""})
            self.assertFalse(json.loads(_request(f"{API}/connections")[2])["ntfy"]["enabled"])
        finally:
            server.shutdown()

    def test_read_along_endpoint(self):
        from backend.api.common import OUTPUT_DIR
        out_dir = OUTPUT_DIR / self.job_id
        audio = out_dir / "lighthouse_audiobook_greek.mp3"
        sync = audio.with_suffix(".sync.json")
        audio.write_bytes(b"\x00" * 1000)
        sync.write_text(json.dumps({"version": 1, "segments": [{"s": 0, "e": 900, "t": "Ένα.", "p": 1}]}),
                        encoding="utf-8")
        try:
            segs = json.loads(_request(f"{API}/jobs/{self.job_id}/read-along")[2])["segments"]
            self.assertEqual(segs[0]["t"], "Ένα.")
            later = time.time() + 120
            os.utime(audio, (later, later))  # a newer recording: the old times no longer fit it
            self.assertEqual(json.loads(_request(f"{API}/jobs/{self.job_id}/read-along")[2])["segments"], [])
        finally:
            audio.unlink(missing_ok=True)
            sync.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
