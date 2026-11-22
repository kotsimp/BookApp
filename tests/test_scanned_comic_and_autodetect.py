"""
tests/test_scanned_comic_and_autodetect.py - End-to-End Verification Suite for:
1. Automatic Graphic Novel / Scanned Comic Detection on /api/upload (PDF, CBZ vs Standard Novel PDF).
2. Scanned Image-Only Graphic Novel PDF translation via Gemini Vision (opaque balloon erasure + Greek typesetting).
3. Novel EPUB / PDF translation with AI Polish enabled (verifying full Greek output, never left untranslated in English).
"""

import sys
sys.path.insert(0, ".")
import io
import json
import time
import urllib.request
import unittest
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont
from ebooklib import epub

from backend.parsers import detect_is_graphic_novel
from backend.comic_translator import _render_vision_balloons_on_page, _get_comic_font_path

API = "http://127.0.0.1:8000/api"


def api_post_file(path, filepath, filename):
    boundary = "----TestScanBoundary999"
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


def api_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_get(path):
    req = urllib.request.Request(f"{API}{path}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_delete(path):
    req = urllib.request.Request(f"{API}{path}", method="DELETE")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestScannedComicAndAutoDetect(unittest.TestCase):

    def test_1_autodetect_scanned_comic_pdf_vs_normal_novel_pdf(self):
        print("-> 1. Testing Automatic Graphic Novel Detection (Scanned Comic PDF vs Normal Novel PDF)...")
        # A. Create a 2-page scanned/raster comic PDF (0 vector text, full-page image)
        img_path = Path("temp/test_autodetect_comic_page.jpg")
        img = Image.new("RGB", (600, 900), (30, 40, 60))
        d = ImageDraw.Draw(img)
        d.ellipse((60, 60, 420, 220), fill=(255, 255, 255), outline=(0, 0, 0), width=3)
        img.save(img_path, quality=85)

        comic_pdf_path = Path("temp/test_mystery_file.pdf")  # Intentionally NO 'comic' in filename!
        doc = fitz.open()
        for _ in range(2):
            p = doc.new_page(width=595, height=842)
            p.insert_image(p.rect, filename=str(img_path))
        doc.save(str(comic_pdf_path))
        doc.close()

        # Verify backend detector directly
        det_comic = detect_is_graphic_novel(str(comic_pdf_path), "pdf", "test_mystery_file.pdf")
        self.assertTrue(det_comic["is_comic"], f"Expected scanned comic PDF to be auto-detected: {det_comic}")
        self.assertTrue(det_comic["is_scanned"], f"Expected is_scanned=True: {det_comic}")

        # Verify via HTTP /api/upload
        st, up_comic = api_post_file("/upload", comic_pdf_path, "test_mystery_file.pdf")
        self.assertEqual(st, 200)
        self.assertTrue(up_comic["is_comic"])
        self.assertTrue(up_comic["is_scanned"])

        # B. Create a normal text novel PDF (must NOT be detected as comic)
        novel_pdf_path = Path("temp/test_normal_novel.pdf")
        doc2 = fitz.open()
        for i in range(2):
            p = doc2.new_page(width=595, height=842)
            p.insert_textbox(
                fitz.Rect(60, 60, 535, 780),
                f"Chapter {i+1}\n\n" + ("Try to touch the past. Try to deal with the past. It is not real. " * 25),
                fontsize=12,
            )
        doc2.save(str(novel_pdf_path))
        doc2.close()

        st2, up_novel = api_post_file("/upload", novel_pdf_path, "test_normal_novel.pdf")
        self.assertEqual(st2, 200)
        self.assertFalse(up_novel["is_comic"], f"Normal novel must NOT be detected as comic: {up_novel}")
        self.assertFalse(up_novel["is_scanned"])

        # Cleanup temp files & test jobs
        for jid in (up_comic.get("job_id"), up_novel.get("job_id")):
            if jid:
                try:
                    api_delete(f"/jobs/{jid}")
                except Exception:
                    pass
        for p in (img_path, comic_pdf_path, novel_pdf_path):
            p.unlink(missing_ok=True)
        print("   Auto-detection (Scanned Comic PDF=True, Novel PDF=False): OK")

    def test_2_scanned_balloon_opaque_erasure_and_greek_render(self):
        print("-> 2. Testing Scanned Comic Opaque Balloon Erasure & Greek Rendering...")
        img_path = Path("temp/test_erase_check.jpg")
        img = Image.new("RGB", (600, 800), (20, 20, 40))
        d = ImageDraw.Draw(img)
        # Draw white balloon with bright red English marker pixels inside
        d.rectangle((100, 100, 500, 250), fill=(255, 255, 255))
        d.rectangle((150, 140, 450, 210), fill=(255, 0, 0))  # Simulated original raster text pixels
        img.save(img_path, quality=95)

        doc = fitz.open()
        p = doc.new_page(width=600, height=800)
        p.insert_image(p.rect, filename=str(img_path))

        mock_items = [{
            "box_2d": [150, 200, 280, 800],  # ymin, xmin, ymax, xmax in 0..1000
            "original_text": "HOLD THE LINE!",
            "translated_text": "ΚΡΑΤΗΣΤΕ ΤΗ ΓΡΑΜΜΗ!",
            "bg_color": "#ffffff",
        }]
        rendered = _render_vision_balloons_on_page(p, mock_items, _get_comic_font_path())
        self.assertEqual(rendered, ["ΚΡΑΤΗΣΤΕ ΤΗ ΓΡΑΜΜΗ!"])
        extracted = p.get_text("text")
        self.assertIn("ΚΡΑΤΗΣΤΕ ΤΗ ΓΡΑΜΜΗ!", extracted)

        # Verify pixel at (160, 150) inside the red box is now covered white (NOT red!)
        pix = p.get_pixmap(dpi=72)
        out_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        r, g, b = out_img.getpixel((160, 150))
        self.assertGreater(g, 200, f"Expected red raster text to be erased by white fill, got RGB=({r},{g},{b})")

        doc.close()
        img_path.unlink(missing_ok=True)
        print("   Opaque raster erasure + Greek balloon rendering: OK")

    def test_3_epub_novel_with_ai_polish_single_pass(self):
        print("-> 3. Testing EPUB Novel Translation with AI Polish (AI translation, never bypassed)...")
        epub_path = Path("temp/test_blindsight_sample.epub")
        book = epub.EpubBook()
        book.set_identifier("test-blind-001")
        book.set_title("Blindsight Sample")
        book.set_language("en")
        c1 = epub.EpubHtml(title="Prologue", file_name="chap_01.xhtml", lang="en")
        c1.content = (
            "<h1>Prologue</h1>"
            "<p>Try to touch the past. Try to deal with the past. It is not real. It is just a dream.</p>"
            "<p>It did not start out here. Not with the scramblers or Rorschach, not with Big Ben or Theseus.</p>"
        )
        book.add_item(c1)
        book.spine = ["nav", c1]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        epub.write_epub(str(epub_path), book, {})

        st, up = api_post_file("/upload", epub_path, "test_blindsight_sample.epub")
        self.assertEqual(st, 200)
        self.assertFalse(up["is_comic"])
        job_id = up["job_id"]

        st_tr, _ = api_post_json("/translate", {
            "job_id": job_id,
            "source_lang": "english",
            "target_lang": "greek",
            "output_format": "epub",
            "layout_mode": "literature",
            "ai_polish": True,
            "api_key": "AQ.TestMockSinglePassEPUB123",
        })
        self.assertEqual(st_tr, 200)

        for _ in range(40):
            time.sleep(0.3)
            _, sdata = api_get(f"/status/{job_id}")
            if sdata["status"] in ("done", "error"):
                break
        self.assertEqual(sdata["status"], "done", f"EPUB Single-Pass AI failed: {sdata}")

        # Verify output text used Single-Pass AI Polish (not skipped!)
        txt_files = list((Path("temp/outputs") / job_id).glob("*_translated_*.txt"))
        self.assertTrue(len(txt_files) >= 1)
        out_txt = txt_files[0].read_text(encoding="utf-8")
        self.assertIn("[Επιμελημένο AI]", out_txt, "EPUB with ai_polish=True must be translated by AI!")

        try:
            api_delete(f"/jobs/{job_id}")
        except Exception:
            pass
        epub_path.unlink(missing_ok=True)
        print("   EPUB Novel + AI Polish Single-Pass routing: OK")

    def test_4_vision_box_normalization_and_cache_status(self):
        print("-> 4. Testing Vision box_2d normalization, JSON recovery & SQLite cache hit status...")
        import asyncio
        from backend.comic_translator import (
            _extract_box_2d,
            _parse_vision_json,
            _detect_comic_balloons_vision_async,
        )
        from backend.database import compute_cache_key, db_set_cached_translation
        import hashlib

        # _extract_box_2d variants
        self.assertEqual(_extract_box_2d({"box_2d": [10, 20, 100, 200]}), [10.0, 20.0, 100.0, 200.0])
        self.assertEqual(_extract_box_2d({"bbox": [[200, 300, 50, 100]]}), [50.0, 100.0, 200.0, 300.0])
        self.assertIsNone(_extract_box_2d({"box": [10, 10, 10, 10]}))

        # _parse_vision_json recovery with nested bbox
        raw_truncated = '[{"bbox": [[10, 20, 120, 220]], "translated_text": "ΕΜΠΡΟΣ!"}, {"broken":'
        parsed = _parse_vision_json(raw_truncated)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["translated_text"], "ΕΜΠΡΟΣ!")

        # Cache hit MUST mark status_out["succeeded"] = True
        fake_img = b"fake-comic-page-vision-cache-test-bytes-12345"
        img_hash = hashlib.sha256(fake_img).hexdigest()
        cache_key = compute_cache_key(img_hash, "english", "greek", engine="gemini_comic_vision_v2")
        cached_payload = [{"box_2d": [10, 20, 100, 200], "translated_text": "Γεια!"}]
        db_set_cached_translation(
            cache_key,
            img_hash,
            json.dumps(cached_payload, ensure_ascii=False),
            "english",
            "greek",
            engine="gemini_comic_vision_v2",
        )
        st_info = {}
        res = asyncio.run(
            _detect_comic_balloons_vision_async(
                fake_img, "dummy-key", "english", "greek", status_out=st_info
            )
        )
        self.assertEqual(res, cached_payload)
        self.assertTrue(st_info.get("succeeded"), f"Expected succeeded=True on cache hit, got {st_info}")
        self.assertEqual(st_info.get("error"), "")
        print("   Vision box normalization, JSON recovery & cache-hit status: OK")


if __name__ == "__main__":
    unittest.main()
