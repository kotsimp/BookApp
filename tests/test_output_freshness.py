"""
test_output_freshness.py - Downloads follow the job's current translation; cover removal, polish language and
cross-site protection.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import job_manager, main

GET = SimpleNamespace(method="GET")


def run(coro):
    return asyncio.run(coro)


class Case(unittest.TestCase):
    def setUp(self):
        self.job = job_manager.create_job("", "book.pdf", "pdf")
        self.jid = self.job.job_id
        src = main.UPLOAD_DIR / self.jid / "book.pdf"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"not needed")
        self.out = main.OUTPUT_DIR / self.jid
        self.out.mkdir(parents=True, exist_ok=True)
        job_manager.update_job(self.jid, file_path=str(src), status="done", target_lang="greek", layout_mode="standard")

    def tearDown(self):
        run(main.delete_job(self.jid))

    def put(self, name, text, age=0.0):
        path = self.out / name
        path.write_text(text, encoding="utf-8")
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def download(self, fmt):
        exported = []

        def export(text, out_dir, kind, base, **_kw):
            exported.append((base, text))
            path = out_dir / f"{base}.{kind}"
            path.write_text(text, encoding="utf-8")
            return path

        with mock.patch.object(main, "_export_from_text", export):
            response = run(main.download_output(GET, self.jid, format=fmt, layout=None))
        return Path(response.path), exported


class TestDownloads(Case):
    def test_export_older_than_the_text_is_rebuilt(self):
        self.put("book_translated_greek.pdf", "OLD", age=100)
        self.put("book_translated_greek.txt", "NEW")
        path, exported = self.download("pdf")
        self.assertEqual((path.read_text(encoding="utf-8"), exported), ("NEW", [("book_translated_greek", "NEW")]))

    def test_current_export_is_served_as_is(self):
        self.put("book_translated_greek.txt", "TEXT", age=50)
        self.put("book_translated_greek.pdf", "EXPORTED", age=49)
        path, exported = self.download("pdf")
        self.assertEqual((path.read_text(encoding="utf-8"), exported), ("EXPORTED", []))

    def test_other_language_is_never_served(self):
        self.put("book_translated_greek.txt", "ΕΛΛΗΝΙΚΑ", age=50)
        self.put("book_translated_english.txt", "ENGLISH", age=10)
        self.put("book_translated_english.pdf", "ENGLISH")
        path, _ = self.download("pdf")
        self.assertEqual(path.name, "book_translated_greek.pdf")

    def test_superseded_formats_are_set_aside_not_deleted(self):
        old = self.put("book_translated_greek.docx", "OLD", age=100)
        before = main._export_snapshot(self.out, "book_translated_greek")
        new = self.put("book_translated_greek.pdf", "NEW")
        main._set_aside_superseded(self.out, before, {new})
        self.assertFalse(old.exists())
        self.assertEqual((self.out / "previous" / old.name).read_text(encoding="utf-8"), "OLD")
        self.assertTrue(new.exists())


class TestCoverAndPolish(Case):
    def test_removed_cover_is_not_extracted_again(self):
        run(main.delete_cover_image(self.jid))
        with mock.patch("backend.exporter.extract_cover_image", return_value=b"jpeg") as extract:
            with self.assertRaises(main.HTTPException):
                run(main.get_cover_image(self.jid))
        extract.assert_not_called()

    def test_polish_uses_the_language_of_the_text(self):
        job_manager.update_job(self.jid, status="idle")
        seen = {}

        async def fake(**kw):
            seen.update(kw)
            return kw["text"]

        with mock.patch("backend.ai_polisher.polish_text_with_gemini", fake), \
                mock.patch.object(main, "_export_from_text", lambda *a, **k: self.out / "unused"):
            request = main.PolishRequest(job_id=self.jid, text="The captain sailed at dawn.", bilingual_mode=False,
                                         final_refinement=False)
            run(main.polish_translation(request))
        self.assertEqual(seen["target_lang"], "english")
        self.assertTrue((self.out / "book_translated_english.txt").exists())
        self.assertEqual(main._text_language("Η κλάση HashMap του Java αποθηκεύει ζεύγη key και value"), "greek")


class TestChapters(Case):
    """GET /api/jobs/{job_id}/chapters feeds the player's chapter list."""

    def test_marks_of_the_newest_audiobook(self):
        self.assertEqual(run(main.get_audiobook_chapters(self.jid))["chapters"], [])
        self.put("book_audiobook_greek.mp3", "audio", age=90)
        marks = [{"start_ms": 0, "title": "One"}, {"start_ms": 65500, "title": "Two", "end_ms": 99000}]
        self.put("book_audiobook_greek.chapters.json", json.dumps(marks), age=90)
        self.assertEqual(run(main.get_audiobook_chapters(self.jid))["chapters"],
                         [{"title": "One", "start_seconds": 0.0}, {"title": "Two", "start_seconds": 65.5}])
        self.put("book_audiobook_english.mp3", "newer recording without chapters")
        self.assertEqual(run(main.get_audiobook_chapters(self.jid))["chapters"], [])


class TestCrossSite(unittest.TestCase):
    def status(self, method, site, origin, path="/api/upload", **more):
        headers = {"origin": origin, **{k.replace("_", "-"): v for k, v in more.items()}}
        if site:
            headers["sec-fetch-site"] = site
        request = SimpleNamespace(method=method, headers=headers, url=SimpleNamespace(path=path))

        async def passed(_request):
            return SimpleNamespace(status_code=200)

        return run(main.refuse_cross_site_changes(request, passed)).status_code

    def test_only_foreign_websites_are_refused(self):
        self.assertEqual(self.status("POST", "cross-site", "https://evil.example"), 403)
        self.assertEqual(self.status("POST", "cross-site", "null"), 403)
        # the reading-position sync server signs reading apps in with headers, never with cookies
        self.assertEqual(self.status("PUT", "cross-site", "tauri://localhost", path="/kosync/syncs/progress"), 200)
        self.assertEqual(self.status("PUT", "cross-site", "https://evil.example", path="/kosyncx"), 403)
        self.assertEqual(self.status("POST", "cross-site", "http://127.0.0.1:5173"), 200)
        self.assertEqual(self.status("POST", "same-origin", "http://192.168.1.5:8000"), 200)
        self.assertEqual(self.status("GET", "cross-site", "https://evil.example"), 200)

    def test_plain_http_on_the_lan_is_protected_too(self):
        lan = "192.168.1.5:8000"  # browsers send no Sec-Fetch-Site here
        self.assertEqual(self.status("POST", None, "https://evil.example", host=lan), 403)
        self.assertEqual(self.status("POST", None, "null", host=lan), 403)
        self.assertEqual(self.status("POST", None, "http://192.168.1.5:9999", host=lan), 403)
        self.assertEqual(self.status("DELETE", None, "https://evil.example", host=lan), 403)
        self.assertEqual(self.status("POST", None, "http://192.168.1.5:8000", host=lan), 200)
        self.assertEqual(self.status("POST", None, "http://books.lan:8080", host="books.lan"), 200, "nginx Host $host")
        self.assertEqual(self.status("POST", None, "https://books.example", host="127.0.0.1:8000",
                                     x_forwarded_host="books.example"), 200)
        self.assertEqual(self.status("POST", None, "", host=lan), 200, "programs send no Origin")


if __name__ == "__main__":
    unittest.main()
