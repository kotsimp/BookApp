"""
tests/test_scanned_books_samples_estimate.py - A scanned book's text read by Gemini Vision, sample translations and the
estimate of Gemini requests before starting.

1. Scanned PDFs: book or comic guess, the page reading (test key), the text file next to the PDF and the parser using it,
   samples reading only their pages, pages with their own text, empty and refused pages, failures and quota stops that
   keep what was read, a changed file.
2. The Gemini call with a picture: the image travels inline, Flash-Lite is asked first, the answer keeps the book's own
   brackets, a page read once comes from the cache.
3. Samples: the AI translation translates only the batches of the chosen pages and the whole book reuses them; the free
   engine and the comic translator do only those pages.
4. The estimate of requests: AI batches, the second pass, samples, scanned books, comics, the daily allowance of the
   keys and limits learned from Google.
5. Through the API: the upload's Book / Comic guess, the estimate endpoint, a sample run, its download name and checks.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import asyncio
import io
import json
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

from backend import ai_polisher, job_manager, scan_reader
from backend.database import db_delete_job

API = "http://127.0.0.1:8000/api"
TEST_KEY = "AIzaTestScannedBooks"


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow
        return ImageFont.load_default()


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def book_page_png(seed: int) -> bytes:
    """A scanned page of print: light paper, lines of dark text."""
    img = Image.new("RGB", (1240, 1754), (250, 248, 242))
    draw = ImageDraw.Draw(img)
    font = _font(28)
    for i in range(34):
        draw.text((120, 140 + i * 44), f"Line {i} of page {seed}: the quick brown fox jumps over the lazy dog.",
                  fill=(25, 25, 25), font=font)
    return _png(img)


def comic_page_png(seed: int) -> bytes:
    """A comic page: coloured panels with thick borders and balloons."""
    img = Image.new("RGB", (1240, 1754), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    colours = [(220, 40, 40), (30, 90, 200), (250, 200, 20), (40, 160, 70)]
    for k, (x0, y0) in enumerate([(40, 40), (640, 40), (40, 900), (640, 900)]):
        draw.rectangle([x0, y0, x0 + 560, y0 + 820], fill=colours[(k + seed) % 4], outline=(0, 0, 0), width=14)
        draw.ellipse([x0 + 60, y0 + 60, x0 + 360, y0 + 260], fill=(255, 255, 255), outline=(0, 0, 0), width=6)
    return _png(img)


def image_pdf(path: Path, pngs: list, text_first: str = "") -> Path:
    doc = fitz.open()
    if text_first:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), text_first, fontsize=12)
    for png in pngs:
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=png)
    doc.save(str(path))
    doc.close()
    return path


def text_pdf(path: Path, pages: list) -> Path:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(60, 60, 535, 780), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def run(coro):
    return asyncio.run(coro)


class ScannedBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_book_or_comic_guess(self):
        from backend.parsers import detect_is_graphic_novel
        book = image_pdf(self.dir / "old_novel.pdf", [book_page_png(i) for i in range(5)])
        comic = image_pdf(self.dir / "adventure.pdf", [comic_page_png(i) for i in range(5)])
        self.assertTrue(detect_is_graphic_novel(str(book), "pdf")["is_scanned"])
        self.assertTrue(detect_is_graphic_novel(str(comic), "pdf")["is_scanned"])
        self.assertTrue(scan_reader.guess_scanned_book(str(book)), "pages of print are a book")
        self.assertFalse(scan_reader.guess_scanned_book(str(comic)), "coloured panels are a comic")
        self.assertFalse(scan_reader.guess_scanned_book(str(book), "manga_volume_1.pdf"), "the name says comic")
        self.assertTrue(scan_reader.is_scanned_pdf(str(book), "pdf"))
        self.assertFalse(scan_reader.is_scanned_pdf(str(book), "epub"))

    def test_pages_are_read_once_and_the_parser_uses_them(self):
        from backend.parsers import parse_document
        pdf = image_pdf(self.dir / "scan.pdf", [book_page_png(i) for i in range(3)])
        self.assertEqual(list(parse_document(str(pdf), "pdf")), [], "a scan has no text of its own")
        self.assertTrue(scan_reader.needs_reading(str(pdf), "pdf"))
        self.assertEqual(scan_reader.pages_to_read(str(pdf)), 3)
        seen = []
        result = run(scan_reader.read_scanned_text(str(pdf), TEST_KEY, progress=lambda d, t: seen.append((d, t))))
        self.assertEqual(result, {"total": 3, "read": 3, "blocked": [], "complete": True})
        self.assertEqual(seen[0], (0, 3))
        self.assertEqual(seen[-1], (3, 3))
        self.assertTrue(scan_reader.sidecar_path(str(pdf)).is_file())
        pages = list(parse_document(str(pdf), "pdf"))
        self.assertEqual([p["page"] for p in pages], [1, 2, 3])
        self.assertTrue(all("It was a bright cold day in April." in p["text"] for p in pages))
        self.assertTrue(all(p["total"] == 3 for p in pages))
        self.assertFalse(scan_reader.needs_reading(str(pdf), "pdf"))
        self.assertEqual(scan_reader.pages_to_read(str(pdf)), 0)
        # nothing is asked again
        with mock.patch.object(ai_polisher, "_call_gemini_api", side_effect=AssertionError("asked again")):
            self.assertEqual(run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))["read"], 0)

    def test_a_sample_reads_only_its_pages_and_the_rest_later(self):
        pdf = image_pdf(self.dir / "scan.pdf", [book_page_png(i) for i in range(8)])
        real = ai_polisher._call_gemini_api
        calls = []

        async def counting(*a, **kw):
            calls.append(kw.get("prefer_models"))
            return await real(*a, **kw)

        with mock.patch.object(ai_polisher, "_call_gemini_api", counting):
            result = run(scan_reader.read_scanned_text(str(pdf), TEST_KEY, page_range=(2, 3)))
            self.assertFalse(result["complete"])
            self.assertEqual(len(calls), 4, "pages 2-3 and two more, where a translation batch may run on")
            self.assertEqual(calls[0], scan_reader.LIGHT_MODELS_FIRST, "reading print goes to Flash-Lite first")
            self.assertEqual(sorted(int(k) for k in scan_reader.load_scan_text(str(pdf))["pages"]), [2, 3, 4, 5])
            self.assertEqual([p["page"] for p in scan_reader.read_pages(str(pdf))], [2, 3, 4, 5])
            self.assertEqual(scan_reader.pages_to_read(str(pdf)), 4)
            self.assertTrue(scan_reader.needs_reading(str(pdf), "pdf"))
            calls.clear()
            self.assertTrue(run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))["complete"])
            self.assertEqual(len(calls), 4, "only the pages not read yet")

    def test_a_page_with_its_own_text_is_not_sent(self):
        pdf = image_pdf(self.dir / "scan.pdf", [book_page_png(1), book_page_png(2)], text_first="A digital title page")
        real = ai_polisher._call_gemini_api
        calls = []

        async def counting(*a, **kw):
            calls.append(1)
            return await real(*a, **kw)

        with mock.patch.object(ai_polisher, "_call_gemini_api", counting):
            run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))
        self.assertEqual(len(calls), 2)
        self.assertIn("A digital title page", scan_reader.load_scan_text(str(pdf))["pages"]["1"])

    def test_empty_and_refused_pages(self):
        pdf = image_pdf(self.dir / "scan.pdf", [book_page_png(i) for i in range(3)])
        answers = iter(["[NO TEXT]", ai_polisher._ContentBlockedError("blocked"), "```\nA real page.\n```"])

        async def fake(*a, **kw):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return ai_polisher.clean_transcription(answer)

        with mock.patch.object(scan_reader, "READ_WORKERS", 1), \
                mock.patch.object(ai_polisher, "_call_gemini_api", fake):
            result = run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))
        self.assertTrue(result["complete"])
        self.assertEqual(result["blocked"], [2])
        pages = scan_reader.load_scan_text(str(pdf))["pages"]
        self.assertEqual((pages["1"], pages["2"], pages["3"]), ("", "", "A real page."))
        self.assertEqual([p["page"] for p in scan_reader.read_pages(str(pdf))], [3], "empty pages are left out")

    def test_failed_pages_are_reported_and_read_on_the_next_run(self):
        pdf = image_pdf(self.dir / "scan.pdf", [book_page_png(i) for i in range(3)])
        state = {"n": 0}

        async def flaky(*a, **kw):
            state["n"] += 1
            if state["n"] in (2, 3):  # the second page fails twice: both attempts
                raise RuntimeError("Model timed out after 90s.")
            return "Some page text."

        with mock.patch.object(scan_reader, "READ_WORKERS", 1), mock.patch.object(scan_reader.asyncio, "sleep",
                                                                                 mock.AsyncMock()), \
                mock.patch.object(ai_polisher, "_call_gemini_api", flaky):
            with self.assertRaises(scan_reader.ScanReadError) as ctx:
                run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))
        self.assertIn("1 scanned page(s) could not be read (2): Model timed out", str(ctx.exception))
        data = scan_reader.load_scan_text(str(pdf))
        self.assertEqual(sorted(data["pages"]), ["1", "3"])
        self.assertFalse(data["complete"])
        self.assertTrue(run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))["complete"])

    def test_quota_stop_keeps_what_was_read(self):
        pdf = image_pdf(self.dir / "scan.pdf", [book_page_png(i) for i in range(4)])
        state = {"n": 0}

        async def limited(*a, **kw):
            state["n"] += 1
            if state["n"] >= 3:
                raise ai_polisher.DailyQuotaExhaustedError("⚠️ Εξαντλήθηκε το ημερήσιο όριο")
            return "Page text."

        with mock.patch.object(scan_reader, "READ_WORKERS", 1), \
                mock.patch.object(ai_polisher, "_call_gemini_api", limited):
            with self.assertRaises(ai_polisher.DailyQuotaExhaustedError):
                run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))
        data = scan_reader.load_scan_text(str(pdf))
        self.assertEqual(sorted(data["pages"]), ["1", "2"])
        self.assertFalse(data["complete"])

    def test_text_of_another_file_is_not_used(self):
        pdf = image_pdf(self.dir / "scan.pdf", [book_page_png(1)])
        run(scan_reader.read_scanned_text(str(pdf), TEST_KEY))
        self.assertTrue(scan_reader.scan_text_complete(str(pdf)))
        with open(pdf, "ab") as f:
            f.write(b"\n% another version of the file\n")
        self.assertEqual(scan_reader.load_scan_text(str(pdf))["pages"], {})
        self.assertIsNone(scan_reader.read_pages(str(pdf)))


class _FakeResponse:
    def __init__(self, payload):
        self.status = 200
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, answer):
        self.answer = answer
        self.posts = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json))
        return _FakeResponse({"candidates": [{"content": {"parts": [{"text": self.answer}]}, "finishReason": "STOP"}]})


class GeminiPictureCallTests(unittest.TestCase):
    def test_picture_inline_flash_lite_first_light_cleaning_and_cache(self):
        from backend.gemini_key_pool import GeminiRateLimiter
        session = _FakeSession("```text\nChapter One\n\n[Note: the author's own bracket]\n```")
        image = ("image/jpeg", b"\xff\xd8 a scanned page " + str(time.time()).encode())
        models = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-3.5-flash-lite"]

        async def ask():
            return await ai_polisher._call_gemini_api(
                scan_reader.READ_REQUEST, "AIzaNotATestKeyButAFake", scan_reader.READ_PROMPT, session=session,
                temperature=0.0, image=image, prefer_models=scan_reader.LIGHT_MODELS_FIRST,
                cache_gate=lambda out: bool(out.strip()))

        with mock.patch.object(ai_polisher, "_get_available_models", mock.AsyncMock(return_value=models)), \
                mock.patch.object(GeminiRateLimiter, "acquire", mock.AsyncMock()), \
                mock.patch.object(ai_polisher, "is_gemini_quota_exhausted", return_value=False):
            first = run(ask())
            second = run(ask())
        self.assertEqual(first, "Chapter One\n\n[Note: the author's own bracket]", "only the wrappers go")
        self.assertEqual(second, first)
        self.assertEqual(len(session.posts), 1, "a page read once comes from the cache")
        url, payload = session.posts[0]
        self.assertIn("gemini-3.5-flash-lite:generateContent", url, "Flash-Lite is asked first")
        parts = payload["contents"][0]["parts"]
        self.assertIn("Write out the text printed on it", parts[0]["text"])
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/jpeg")

    def test_learned_daily_limit(self):
        from backend.gemini_key_pool import model_daily_limit, record_model_daily_limit
        before = model_daily_limit("gemini-3.5-flash")
        try:
            record_model_daily_limit("gemini-3.5-flash", "35")
            self.assertEqual(model_daily_limit("gemini-3.5-flash"), 35)
            record_model_daily_limit("gemini-3.5-flash", None)
            record_model_daily_limit("gemini-3.5-flash", "unlimited")
            record_model_daily_limit("gemini-3.5-flash", 0)
            self.assertEqual(model_daily_limit("gemini-3.5-flash"), 35, "nonsense never replaces a real limit")
        finally:
            record_model_daily_limit("gemini-3.5-flash", before)


class SampleTranslationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.job = job_manager.create_job(str(self.dir / "book.pdf"), "book.pdf", "pdf")

    def tearDown(self):
        job_manager._jobs.pop(self.job.job_id, None)
        db_delete_job(self.job.job_id)
        self.tmp.cleanup()

    def test_ai_sample_then_the_whole_book_reuses_its_batches(self):
        pages = [{"page": n, "text": f"Page {n}. " + ("The ship sailed on across the grey sea. " * 50), "total": 12}
                 for n in range(1, 13)]
        out = self.dir / "out" / "book_translated_greek.txt"
        out.parent.mkdir()
        real = ai_polisher._call_gemini_api
        asked = []

        async def counting(content_text, *a, **kw):
            if "<TEXT_TO_TRANSLATE>" in content_text:
                asked.append([int(n) for n in __import__("re").findall(r"=== PAGE (\d+) ===", content_text)])
            return await real(content_text, *a, **kw)

        def translate(page_range=None):
            return run(ai_polisher.translate_and_polish_direct_with_gemini(
                job_id=self.job.job_id, file_path=str(self.dir / "book.pdf"), file_type="pdf",
                source_lang="english", target_lang="greek", output_path=str(out), api_key=TEST_KEY,
                quota_behavior="fallback", page_range=page_range))

        with mock.patch("backend.parsers.parse_document", return_value=pages), \
                mock.patch("backend.glossary.load_glossary", return_value={}), \
                mock.patch.object(ai_polisher, "_call_gemini_api", counting):
            translate((3, 5))
            sample_text = out.read_text(encoding="utf-8")
            self.assertEqual(sorted(asked), [[3, 4], [5, 6]], "whole batches of two pages, as in the whole book")
            self.assertEqual(job_manager.get_job(self.job.job_id).sample_range, [3, 6])
            for n in (3, 4, 5, 6):
                self.assertIn(f"Page {n}.", sample_text)
            for n in (1, 2, 7, 12):
                self.assertNotIn(f"Page {n}.", sample_text)
            self.assertTrue((out.parent / ".direct_ai_checkpoint.json").is_file(), "kept for the whole book")
            asked.clear()
            translate()
            whole = out.read_text(encoding="utf-8")
        self.assertEqual(sorted(p for batch in asked for p in batch), [1, 2, 7, 8, 9, 10, 11, 12],
                         "the sample's pages are not translated again")
        for n in range(1, 13):
            self.assertIn(f"Page {n}.", whole)
        self.assertFalse((out.parent / ".direct_ai_checkpoint.json").exists())

    def test_ai_sample_without_text_says_so(self):
        pages = [{"page": 1, "text": "Only page one has text.", "total": 3}]
        with mock.patch("backend.parsers.parse_document", return_value=pages), \
                mock.patch("backend.glossary.load_glossary", return_value={}):
            with self.assertRaises(ValueError) as ctx:
                run(ai_polisher.translate_and_polish_direct_with_gemini(
                    job_id=self.job.job_id, file_path=str(self.dir / "book.pdf"), file_type="pdf",
                    source_lang="english", target_lang="greek", output_path=str(self.dir / "o.txt"),
                    api_key=TEST_KEY, page_range=(2, 3)))
        self.assertIn("Pages 2–3 hold no text to translate.", str(ctx.exception))

    def test_free_engine_sample(self):
        from backend.translator import translate_document
        pages = [{"page": n, "text": f"Page {n} says hello.", "total": 5} for n in range(1, 6)]
        out = self.dir / "free.txt"
        with mock.patch("backend.translator.parse_document", return_value=pages):
            run(translate_document(job_id=self.job.job_id, file_path=str(self.dir / "book.pdf"), file_type="pdf",
                                   source_lang="english", target_lang="greek", output_path=str(out),
                                   page_range=(2, 3)))
        text = out.read_text(encoding="utf-8")
        self.assertIn("PAGE 2", text)
        self.assertIn("PAGE 3", text)
        self.assertNotIn("PAGE 1\n", text)
        self.assertNotIn("PAGE 4", text)
        self.assertEqual(job_manager.get_job(self.job.job_id).sample_range, [2, 3])

    def test_comic_sample_holds_only_its_pages(self):
        from backend.comic_translator import translate_comic_document
        doc = fitz.open()
        for n in range(1, 5):
            page = doc.new_page(width=595, height=842)
            page.insert_text((80, 120), f"HELLO FROM PAGE {n}!", fontsize=16)
        src = self.dir / "comic.pdf"
        doc.save(str(src))
        doc.close()
        out = self.dir / "comic_out" / "comic_translated_greek.txt"
        out.parent.mkdir()
        pdf = run(translate_comic_document(job_id=self.job.job_id, file_path=str(src), file_type="pdf",
                                           source_lang="english", target_lang="greek", output_path=str(out),
                                           api_key=None, page_range=(2, 3)))
        with fitz.open(pdf) as result:
            self.assertEqual(len(result), 2)
        script = out.read_text(encoding="utf-8")
        self.assertIn("PAGE 2", script)
        self.assertIn("PAGE 3", script)
        self.assertNotIn("PAGE 1\n", script)
        self.assertNotIn("PAGE 4", script)
        self.assertEqual(job_manager.get_job(self.job.job_id).sample_range, [2, 3])
        with self.assertRaises(ValueError):
            run(translate_comic_document(job_id=self.job.job_id, file_path=str(src), file_type="pdf",
                                         source_lang="english", target_lang="greek", output_path=str(out),
                                         page_range=(9, 10)))


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, path, total_pages, **extra):
        values = dict(job_id="estimate-test", file_path=str(path), file_type="pdf", file_name=Path(path).name,
                      total_pages=total_pages, output_format="pdf", scanned=False, read_scanned_text=False)
        values.update(extra)
        return types.SimpleNamespace(**values)

    def _estimate(self, job, **kw):
        from backend import main
        from backend.gemini_key_pool import GeminiKeyPool
        args = dict(ai_polish=True, max_quality=False, layout_mode="standard", output_format="pdf",
                    read_scanned_text=None, page_from=None, page_to=None)
        args.update(kw)
        with mock.patch("backend.gemini_key_pool.resolve_gemini_api_key", return_value="AIzaThreeKeys"), \
                mock.patch.object(GeminiKeyPool, "get_keys", return_value=["k1", "k2", "k3"]):
            return main._estimate_requests(job, **args)

    def test_ai_batches_second_pass_and_sample(self):
        from backend import main
        path = text_pdf(self.dir / "book.pdf", ["x"] * 12)
        job = self._job(path, 12)
        with mock.patch.object(main, "_page_lengths", return_value=[(n, 2000) for n in range(1, 13)]):
            e = self._estimate(job)
            self.assertEqual(e["requests"], {"read": 0, "translate": 7, "revise": 0},
                             "six batches of two pages and the names of a long book")
            self.assertEqual((e["keys"], e["best_per_day"], e["best_model"]), (3, 60, "gemini-3.5-flash"))
            self.assertEqual(e["pages"], 12)
            e = self._estimate(job, max_quality=True)
            self.assertEqual(e["requests"]["revise"], 7)
            self.assertEqual(e["best_days"], 1)
            e = self._estimate(job, max_quality=True, page_from=3, page_to=5)
            self.assertEqual(e["sample"], [3, 5])
            self.assertEqual(e["requests"], {"read": 0, "translate": 3, "revise": 2})
            self.assertEqual(self._estimate(job, ai_polish=False)["total"], 0, "the free engine needs no requests")
            in_place = self._estimate(self._job(path, 12, file_type="docx"), output_format="docx")
            self.assertEqual(in_place["requests"]["translate"], 7, "24,000 characters in ~4,000-character parts")

    def test_scanned_book_and_comic(self):
        path = image_pdf(self.dir / "scan.pdf", [book_page_png(i) for i in range(5)])
        book = self._job(path, 5, scanned=True, read_scanned_text=True)
        e = self._estimate(book)
        self.assertTrue(e["read_scanned_text"])
        self.assertEqual(e["requests"], {"read": 5, "translate": 2, "revise": 0},
                         "every page read once; three unread pages of print fit a batch")
        self.assertEqual(self._estimate(book, page_from=1, page_to=1)["requests"]["read"], 3)
        comic = self._estimate(book, read_scanned_text=False)
        self.assertTrue(comic["comic"])
        self.assertEqual(comic["requests"], {"read": 0, "translate": 5, "revise": 0}, "one Vision request a page")
        from backend.comic_translator import VISION_MODELS_PRIORITY
        from backend.gemini_key_pool import model_daily_limit, record_model_daily_limit
        self.assertEqual(comic["best_model"], VISION_MODELS_PRIORITY[0])
        before = model_daily_limit(comic["best_model"])
        try:
            record_model_daily_limit(comic["best_model"], 7)
            self.assertEqual(self._estimate(book, read_scanned_text=False)["best_per_day"], 21, "Google's own limit")
        finally:
            record_model_daily_limit(comic["best_model"], before)
        run(scan_reader.read_scanned_text(str(path), TEST_KEY))
        self.assertEqual(self._estimate(book)["requests"]["read"], 0, "read already")


def _post_file(filepath: Path, filename: str):
    boundary = "----ScannedBooksBoundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + filepath.read_bytes() + \
        f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(path: str, data: dict):
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _get(path: str):
    with urllib.request.urlopen(f"{API}{path}", timeout=30) as resp:
        return resp.status, resp.headers, resp.read()


class ApiTests(unittest.TestCase):
    """Against the sandbox server that run_all_tests.py starts."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_upload_guesses_book_or_comic(self):
        book = _post_file(image_pdf(self.dir / "b.pdf", [book_page_png(i) for i in range(3)]), "old_novel_scan.pdf")
        self.assertEqual((book["scan_kind"], book["is_comic"], book["is_scanned"]), ("book", False, True))
        comic = _post_file(image_pdf(self.dir / "c.pdf", [comic_page_png(i) for i in range(3)]), "adventure.pdf")
        self.assertEqual((comic["scan_kind"], comic["is_comic"]), ("comic", True))
        digital = _post_file(text_pdf(self.dir / "d.pdf", ["Plain digital text. " * 40] * 2), "digital.pdf")
        self.assertEqual((digital["scan_kind"], digital["is_scanned"]), ("", False))
        _, _, raw = _get(f"/status/{book['job_id']}")
        status = json.loads(raw)
        self.assertEqual((status["scanned"], status["read_scanned_text"]), (True, True))
        _, _, raw = _get(f"/translate/estimate/{book['job_id']}?ai_polish=true&read_scanned_text=true")
        estimate = json.loads(raw)
        self.assertEqual(estimate["requests"]["read"], 3)
        self.assertTrue(estimate["read_scanned_text"])
        _, _, raw = _get(f"/translate/estimate/{book['job_id']}?ai_polish=true&read_scanned_text=false")
        self.assertTrue(json.loads(raw)["comic"])

    def test_sample_run_download_name_and_checks(self):
        pdf = text_pdf(self.dir / "s.pdf", [f"Page {n}: the lighthouse keeper looked at the sea. " * 12
                                            for n in range(1, 5)])
        job_id = _post_file(pdf, "sample_book.pdf")["job_id"]
        settings = {"job_id": job_id, "source_lang": "english", "target_lang": "greek", "output_format": "pdf",
                    "ai_polish": False}
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _post_json("/translate", {**settings, "page_from": 9, "page_to": 12})
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _post_json("/translate", {**settings, "page_from": 3, "page_to": 2})
        self.assertEqual(ctx.exception.code, 400)
        status, _ = _post_json("/translate", {**settings, "page_from": 2, "page_to": 3})
        self.assertEqual(status, 200)
        deadline = time.time() + 90
        info = {}
        while time.time() < deadline:
            info = json.loads(_get(f"/status/{job_id}")[2])
            if info["status"] in ("done", "error"):
                break
            time.sleep(0.5)
        self.assertEqual(info["status"], "done", info.get("error"))
        self.assertEqual(info["sample_range"], [2, 3])
        self.assertTrue(info["current_step"].endswith("· 🧪 Sample: pages 2–3"), info["current_step"])
        _, headers, _ = _get(f"/download/{job_id}?format=pdf&layout=standard")
        self.assertIn("_sample_p2-3.pdf", headers.get("content-disposition", ""))
        _, _, raw = _get(f"/jobs/{job_id}/text")
        translated = json.loads(raw).get("translated_text", "")
        self.assertNotIn("PAGE 1\n", translated)
        self.assertNotIn("PAGE 4", translated)


if __name__ == "__main__":
    unittest.main()
