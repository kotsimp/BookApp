"""
test_comic_fidelity.py - Comics keep their page order and every balloon, read real scans and WebP, and a short rate
limit never switches a key off for an hour. Synthetic pictures and transport fakes: nothing leaves the computer.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import io
import json
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf
from PIL import Image
from starlette.datastructures import UploadFile

from backend import ai_polisher, gemini_key_pool, job_manager, main
from backend import comic_translator as ct
from backend.database import db_delete_job

KEY = "key-for-offline-tests"


def picture(kind="JPEG", size=(300, 420), shade=235):
    buf = io.BytesIO()
    Image.new("RGB", size, (shade, shade, shade)).save(buf, kind)
    return buf.getvalue()


async def no_wait(*_a, **_k):
    pass


class Response:
    def __init__(self, status, data):
        self.status, self.data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def json(self, **_kw):
        return self.data

    async def text(self):
        return json.dumps(self.data)


def answer(items, reason="STOP", raw=None):
    text = raw if raw is not None else json.dumps(items, ensure_ascii=False)
    return Response(200, {"candidates": [{"finishReason": reason, "content": {"parts": [{"text": text}]}}]})


def refusal(quota_id, delay):
    return Response(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


class Session:
    def __init__(self, *responses):
        self.responses, self.sent = responses, 0

    def post(self, *_a, **_k):
        self.sent += 1
        return self.responses[min(self.sent, len(self.responses)) - 1]


BALLOON = {"box_2d": [100, 100, 300, 700], "original_text": "Hello", "translated_text": "Γεια σου"}


class TestPages(unittest.TestCase):
    def translate(self, src, kind, key=KEY, items=(), text_out=None):
        seen = []

        async def detect(img, *_a, status_out=None, **_k):
            with Image.open(io.BytesIO(img)) as im:
                seen.append(im.size)
            status_out["succeeded"] = True
            return [dict(i) for i in items]

        async def free(text, *_a, **_k):
            return "μετάφραση"

        notes = []
        job = job_manager.create_job(str(src), src.name, kind)
        try:
            with mock.patch.object(ct, "_detect_comic_balloons_vision_async", detect), \
                    mock.patch.object(ct, "_translate_with_retry", free), \
                    mock.patch.object(ct, "_ai_polish_comic_balloons", mock.AsyncMock(return_value=[])), \
                    mock.patch("backend.gemini_key_pool.resolve_gemini_api_key", return_value=key):
                out = asyncio.run(ct.translate_comic_document(
                    job.job_id, str(src), kind, "english", "greek", str(src.parent / "out" / "c.txt"),
                    api_key=key, quota_behavior="fallback", notes=notes))
            with pymupdf.open(out) as doc:
                sizes = [(round(p.rect.width), round(p.rect.height)) for p in doc]
                if text_out is not None:
                    text_out.append(" ".join(p.get_text() for p in doc))
        finally:
            job_manager._jobs.pop(job.job_id, None)
            db_delete_job(job.job_id)
        return seen, sizes, notes

    def test_chapter_folders_keep_the_page_order(self):
        names = ["ch1/01.jpg", "ch1/02.jpg", "ch2/01.jpg", "ch2/02.jpg", "ch10/01.jpg"]
        self.assertEqual([p.as_posix() for p in sorted(map(Path, reversed(names)), key=ct._natural_sort_key)], names)

    def test_webp_pages_are_read(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "scan.cbz"
            with zipfile.ZipFile(src, "w") as zf:
                zf.writestr("1.webp", picture("WEBP", (300, 400)))
                zf.writestr("2.webp", picture("WEBP", (500, 400)))
            seen, sizes, _notes = self.translate(src, "cbz")
            self.assertEqual(len(seen), 2)
            self.assertLess(sizes[0][0] / sizes[0][1], sizes[1][0] / sizes[1][1])

    def scan(self, td, text, render_mode=0):
        src = Path(td) / "scan.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=420)
        page.insert_image(page.rect, stream=picture())
        page.insert_text((20, 400), text, fontsize=8, render_mode=render_mode)
        doc.save(str(src))
        doc.close()
        return src

    def test_scans_with_a_watermark_or_hidden_ocr_go_to_vision(self):
        for text, mode in (("www.scans.example", 0), ("HELLO THERE CAPTAIN WE COUNT THE BOATS TONIGHT", 3)):
            with tempfile.TemporaryDirectory() as td:
                seen, _sizes, _notes = self.translate(self.scan(td, text, mode), "pdf", items=[BALLOON])
                self.assertEqual(len(seen), 1, text)

    def test_balloon_text_copies_as_written(self):
        said = "Πού πας; Απ' το λιμάνι - μα θα ’ρθω."
        shown = []
        with tempfile.TemporaryDirectory() as td:
            self.translate(self.scan(td, "www.scans.example"), "pdf", items=[dict(BALLOON, translated_text=said)],
                           text_out=shown)
        words = " ".join(shown[0].split())
        for word in ("ΠΑΣ;", "ΑΠ'", "-", "’ΡΘΩ."):
            self.assertIn(word, words.upper())
        self.assertEqual([f"U+{ord(c):04X}" for c in shown[0] if c in "\u00a0\u00ad\u037e\u201b\u2219"], [])

    def test_a_watermarked_scan_without_a_key_is_named_untranslated(self):
        with tempfile.TemporaryDirectory() as td:
            _seen, _sizes, notes = self.translate(self.scan(td, "www.scans.example"), "pdf", key="")
        self.assertIn("1 page(s) left untranslated", " ".join(notes))

    def test_hidden_ocr_without_a_key_is_not_passed_off_as_translated(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                self.translate(self.scan(td, "HELLO THERE CAPTAIN WE COUNT THE BOATS TONIGHT", 3), "pdf", key="")


class TestBalloons(unittest.TestCase):
    def vector(self, original, translated):
        with pymupdf.open() as doc:
            page = doc.new_page(width=300, height=300)
            page.insert_text((40, 80), original, fontsize=11)
            blocks = [b for b in page.get_text("blocks") if b[4].strip()]
            with mock.patch.object(ct, "_translate_with_retry", mock.AsyncMock(return_value=translated)), \
                    mock.patch.object(ct, "apply_glossary", lambda t, *_a, **_k: t):
                asyncio.run(ct._translate_page_vector(page, ct._cluster_text_into_balloons(blocks), "english", "greek",
                                                      ct._get_comic_font_path()))
            return " ".join(page.get_text().split())

    def test_a_note_caption_is_content(self):
        self.assertIn("τεύχος", self.vector("[Note: see issue 4]", "[Σημείωση: δες τεύχος 4]"))

    def test_a_balloon_is_never_erased(self):
        self.assertIn("Hello", self.vector("Hello there", ""))

    def test_multiplication_is_not_emphasis(self):
        self.assertEqual(ct.sanitize_comic_dialogue("2*3*4 = 24", "english"), "2*3*4 = 24")
        self.assertEqual(ct.sanitize_comic_dialogue("*gasp* Run!", "english"), "gasp Run!")

    def test_a_kept_sound_effect_in_another_script_is_drawn(self):
        with pymupdf.open() as doc:
            page = doc.new_page(width=300, height=300)
            ct._fit_and_draw_balloon_text(page, pymupdf.Rect(20, 20, 280, 120), "ドーン ἀρχή", ct._get_comic_font_path(),
                                          (1, 1, 1), (0, 0, 0))
            shown = page.get_text()
        self.assertIn("ドーン", shown)
        self.assertIn("ἀ", shown)

    def test_polish_keeps_the_balloon_numbering_and_language(self):
        async def call(content, *_a, **_k):
            self.assertIn("⟦2⟧", content)
            return "⟦1⟧ The captain is here!\n\n⟦2⟧ Μα τι λες τώρα, καπετάνιε, φεύγουμε αμέσως από εδώ!"

        balloons = [{"source": "Ήρθε!", "draft": "The captain came!"},
                    {"source": "Φεύγουμε!", "draft": "We are leaving at once, captain!"}]
        with mock.patch.object(ai_polisher, "_call_gemini_api", call), \
                mock.patch.object(ai_polisher, "is_gemini_quota_exhausted", return_value=False):
            out = asyncio.run(ct._ai_polish_comic_balloons(balloons, KEY, "english", "fallback"))
        self.assertEqual(out, ["The captain is here!", "We are leaving at once, captain!"])


class TestNeighbours(unittest.TestCase):
    """Captions that touch, as under the panels of old Sunday pages: no letter runs under the next caption."""
    TEXTS = ("Ο μικρός Νίμο, αν και νυσταγμένος, δεν μπόρεσε να αντισταθεί στις παρακλήσεις και σηκώθηκε απρόθυμα",
             "Πήγαινε να απαντήσει όταν ανακάλυψε πως το πάτωμα είχε πλημμυρίσει με νερό που ανέβαινε γρήγορα",
             "Τελικά το κρεβάτι προσέκρουσε στη στεριά και η θάλασσα ήταν οργισμένη από τη μεγάλη καταιγίδα")
    LAYOUTS = {
        "side by side, touching": [(0, 200, 250, 240), (250, 200, 500, 240), (500, 200, 750, 240)],
        "side by side, 2 pt apart": [(10, 200, 250, 240), (252, 200, 495, 240)],
        "one under the other": [(100, 100, 400, 140), (100, 140, 400, 180), (100, 181, 400, 220)],
        "small, so the text grows": [(100, 100, 150, 118), (152, 100, 202, 118)],
        "corner to corner": [(100, 100, 160, 120), (161, 121, 221, 141)],
    }

    def ink(self, plan):
        _path, _name, font, box, size, lines, line_h = plan
        top = box.y0 + max(1.0, (box.height - len(lines) * line_h) / 2.0)
        out = []
        for i, line in enumerate(lines):
            width = font.text_length(line, fontsize=size)
            left = box.x0 + max(1.0, (box.width - width) / 2.0)
            out.append(pymupdf.Rect(left, top + i * line_h, left + width, top + i * line_h + size * 0.9))
        return out

    def assert_apart(self, draw):
        for name, boxes in self.LAYOUTS.items():
            with self.subTest(name), pymupdf.open() as doc:
                page = doc.new_page(width=800, height=400)
                plans = []
                with mock.patch.object(ct, "_draw_planned_balloon_text", lambda _page, plan, _colour: plans.append(plan)):
                    draw(page, boxes)
                self.assertEqual(len(plans), len(boxes))
                for i, plan in enumerate(plans):
                    for other in plans[i + 1:]:
                        for line in self.ink(plan):
                            for their in self.ink(other):
                                self.assertTrue((line & their).is_empty, f"{plan[5]} is printed into {other[5]}")

    def test_captions_on_a_scan(self):
        def draw(page, boxes):
            w, h = page.rect.width, page.rect.height
            items = [{"box_2d": [y0 / h * 1000, x0 / w * 1000, y1 / h * 1000, x1 / w * 1000], "bg_color": "#FFFFFF",
                      "original_text": "A caption", "translated_text": text}
                     for (x0, y0, x1, y1), text in zip(boxes, self.TEXTS)]
            ct._render_vision_balloons_on_page(page, items, ct._get_comic_font_path())

        self.assert_apart(draw)

    def test_captions_on_a_page_with_text(self):
        def draw(page, boxes):
            greek = {}
            clusters = []
            for number, (box, text) in enumerate(zip(boxes, self.TEXTS)):
                greek[f"Caption {number}"] = text
                clusters.append({"text": f"Caption {number}", "rect": pymupdf.Rect(box), "original_boxes": [pymupdf.Rect(box)]})

            async def free(text, *_a, **_k):
                return greek[text]

            with mock.patch.object(ct, "_translate_with_retry", free), \
                    mock.patch.object(ct._translator, "google_is_refusing", lambda: False):
                asyncio.run(ct._translate_page_vector(page, clusters, "english", "greek", ct._get_comic_font_path()))

        self.assert_apart(draw)


class TestVisionAnswers(unittest.TestCase):
    def detect(self, session):
        status = {}
        with mock.patch.object(ai_polisher, "is_gemini_quota_exhausted", return_value=False), \
                mock.patch.object(ct.asyncio, "sleep", no_wait), \
                mock.patch.object(ai_polisher, "trip_gemini_quota_exhaustion") as trip, \
                mock.patch.object(gemini_key_pool.GeminiKeyPool, "mark_key_exhausted") as key_off, \
                mock.patch.object(gemini_key_pool.GeminiKeyPool, "mark_model_exhausted"), \
                mock.patch.object(gemini_key_pool.GeminiRateLimiter, "acquire", no_wait):
            items = asyncio.run(ct._detect_comic_balloons_vision_async(
                uuid.uuid4().bytes, KEY, "english", "greek", session=session, status_out=status))
        return items, status, key_off.called, trip.called

    def test_a_cut_page_is_not_a_finished_page(self):
        good = json.dumps(BALLOON)
        for response in (answer(None, "MAX_TOKENS", f'[{good}, {{"box_2d": [400, 10'),
                         answer([BALLOON], "RECITATION"),
                         answer(None, "STOP", f'[{good}, {{"box_2d": [400, 100, 500, 700], "translated_text": "a {{b}} "c""}}]')):
            items, status, _key_off, _trip = self.detect(Session(response))
            self.assertFalse(status["succeeded"], items)

    def test_a_per_minute_limit_keeps_the_key(self):
        items, status, key_off, trip = self.detect(Session(refusal("GenerateRequestsPerMinutePerProject", "12s"),
                                                           answer([BALLOON])))
        self.assertEqual((status["succeeded"], len(items), key_off, trip), (True, 1, False, False))

    def test_an_overload_is_not_called_a_used_up_quota(self):
        busy = Response(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "The model is overloaded."}})
        for response, daily in ((busy, False),
                                (refusal("GenerateRequestsPerMinutePerProject", "12s"), False),
                                (refusal("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "42877s"), True)):
            _items, status, _key_off, _trip = self.detect(Session(response))
            self.assertFalse(status["succeeded"])
            # the word decides whether a "wait" job stops for the daily reset
            self.assertEqual("quota" in status["error"].lower(), daily, status["error"])

    def test_a_daily_limit_still_stops(self):
        _items, status, key_off, trip = self.detect(Session(refusal("GenerateRequestsPerDayPerProject", "3600s")))
        self.assertEqual((status["succeeded"], key_off, trip), (False, True, True))


class TestCover(unittest.TestCase):
    def test_a_webp_cover_is_accepted(self):
        job = job_manager.create_job("", "book.pdf", "pdf")
        try:
            asyncio.run(main.upload_cover_image(job.job_id, UploadFile(io.BytesIO(picture("WEBP")), filename="c.webp")))
            self.assertTrue((main.OUTPUT_DIR / job.job_id / "cover_image.jpg").is_file())
        finally:
            asyncio.run(main.delete_job(job.job_id))


if __name__ == "__main__":
    unittest.main()
