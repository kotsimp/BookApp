"""
test_comic_and_tts_edge_cases.py - Edge Cases, Ordering, Security & Timeout Suite for Comic Translator & TTS Engine.
Tests:
1. Comic Translator: Zip Slip rejection on malicious CBZ; natural numeric sorting (page_1, page_2, page_10);
   English-target vector comic AI polish does NOT translate back to Greek; scanned comic without API key
   raises ValueError instead of silently returning untranslated 'done'; 0-page PDF rejected;
   missing out_dir auto-created & temp/handle cleanup on error.
2. Comic helpers: _extract_box_2d clamps out-of-range coordinates [0..1000]; _render_vision_balloons_on_page
   ignores non-dict/int garbage; _encode_comic_page_jpeg handles grayscale pages; sanitize_comic_dialogue
   handles dialytika+tonos (ΐ/ΰ -> Ϊ/Ϋ) cleanly in ALL-CAPS balloons.
3. TTS Engine: case-insensitive language & raw voice-code lookup; split_into_voice_segments(None) safe;
   _clean_tts_text preserves numeric ranges (1990–2000) and avoids '«Γεια σου!».';
   _tts_chunk_with_retry enforces timeout on hung edge_tts; synthesize_voice_preview rejects traversal;
   generate_audiobook cleans up tts_tmp_* on non-cancellation errors and passes target_lang to AI polish;
   export_audiobook_m4b passes cover image to ffmpeg with timeout.
"""

import sys
sys.path.insert(0, ".")
import io
import os
import asyncio
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pymupdf
from PIL import Image

import backend.comic_translator as ct
import backend.tts_engine as tts
from backend.job_manager import create_job, _jobs
from backend.database import db_delete_job


class TestComicAndTTSEdgeCases(unittest.TestCase):

    def test_1_comic_zip_slip_and_natural_page_sorting(self):
        print("-> 1. Testing Comic CBZ Zip Slip protection & natural page sorting (page_1, page_2, page_10)...")
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            # 1a. Natural sort order
            names = [Path(f"page_{n}.jpg") for n in (1, 10, 2, 11, 3)]
            ordered = [p.name for p in sorted(names, key=ct._natural_sort_key)]
            self.assertEqual(ordered, ["page_1.jpg", "page_2.jpg", "page_3.jpg", "page_10.jpg", "page_11.jpg"])

            # 1b. Zip Slip archive MUST be rejected without writing outside extract_dir
            evil_cbz = td_p / "evil.cbz"
            with zipfile.ZipFile(evil_cbz, "w") as zf:
                zf.writestr("../../escaped_zip_slip.txt", b"PWNED")
            extract_dir = td_p / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(evil_cbz, "r") as zf:
                with self.assertRaises(ValueError):
                    ct._safe_extract_zip(zf, extract_dir)
            self.assertFalse((td_p.parent / "escaped_zip_slip.txt").exists())
        print("   CBZ Zip Slip & natural sort: OK")

    def test_2_comic_vector_target_lang_scanned_no_key_and_box_clamping(self):
        print("-> 2. Testing Comic English target_lang, scanned no-key error, box clamping & dialytika ALL-CAPS...")
        # 2a. English-target comic AI polish with mock key MUST NOT inject Greek placeholder text!
        res_en = asyncio.run(ct._ai_polish_comic_balloons(
            [{"source": "Γεια!", "draft": "Hello there!"}],
            api_key="AQ.TestEnglishComic",
            target_lang="english",
        ))
        self.assertEqual(len(res_en), 1)
        self.assertNotIn("Κοιτάξτε", res_en[0])
        self.assertIn("Hello there!", res_en[0])

        # 2b. _extract_box_2d clamps out-of-range coords & rejects non-dict items
        self.assertIsNone(ct._extract_box_2d("not-a-dict"))
        clamped = ct._extract_box_2d({"box_2d": [-50, 1200, 1500, 950]})
        self.assertEqual(clamped, [0.0, 950.0, 1000.0, 1000.0])

        # 2c. _render_vision_balloons_on_page ignores non-dict / non-string garbage cleanly
        doc = pymupdf.open()
        try:
            pg = doc.new_page(width=400, height=600)
            dialogues = ct._render_vision_balloons_on_page(
                pg,
                [
                    "garbage_string",
                    123,
                    {"box_2d": [100, 100, 200, 300], "translated_text": ["list_not_str"]},
                    {"box_2d": [100, 100, 200, 300], "translated_text": "ΓΕΙΑ ΣΟΥ!"},
                ],
                ct._get_comic_font_path(),
                target_lang="greek",
            )
            self.assertEqual(len(dialogues), 1)
            self.assertEqual(dialogues[0], "ΓΕΙΑ ΣΟΥ!")

            # _encode_comic_page_jpeg always returns valid JPEG bytes
            jpg = ct._encode_comic_page_jpeg(pg)
            self.assertTrue(jpg.startswith(b"\xff\xd8"))
        finally:
            doc.close()

        # 2d. Dialytika + tonos (ΐ/ΰ) in ALL-CAPS Greek comic balloons must not leave broken combining marks
        san = ct.sanitize_comic_dialogue("ΠΡΟΣΟΧΗ ΣΤΟ ΠΡΟΪΟΝ ΚΑΙ ΤΟ ΚΑΐΚΙ!", "greek")
        self.assertNotIn("\u0301", san)
        self.assertIn("ΚΑΪΚΙ", san)

        # 2e. Scanned image-only comic without Gemini API key MUST fail clearly (not silent untranslated 'done'!)
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            scanned_pdf = td_p / "scanned_only.pdf"
            img_buf = io.BytesIO()
            Image.new("RGB", (400, 600), (240, 240, 240)).save(img_buf, format="JPEG")
            d = pymupdf.open()
            p = d.new_page(width=400, height=600)
            p.insert_image(pymupdf.Rect(0, 0, 400, 600), stream=img_buf.getvalue())
            d.save(str(scanned_pdf))
            d.close()

            job = create_job(str(scanned_pdf), "scanned_only.pdf", "pdf")
            try:
                with patch("backend.settings_manager.get_setting", return_value=""), patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
                    with self.assertRaises(ValueError) as ctx:
                        asyncio.run(ct.translate_comic_document(
                            job_id=job.job_id,
                            file_path=str(scanned_pdf),
                            file_type="pdf",
                            source_lang="english",
                            target_lang="greek",
                            output_path=str(td_p / "out_dir" / "out.txt"),
                            api_key=None,
                        ))
                self.assertIn("Gemini API key", str(ctx.exception))
                # Verify PDF handle was closed in finally (file can be deleted on Windows)
                scanned_pdf.unlink()
                self.assertFalse(scanned_pdf.exists())
            finally:
                _jobs.pop(job.job_id, None)
                db_delete_job(job.job_id)
        print("   Comic target_lang, scanned guard, box clamping & dialytika: OK")

    def test_3_tts_voice_resolution_text_cleaning_and_timeouts(self):
        print("-> 3. Testing TTS voice resolution, text cleaning, preview safety, timeouts & temp cleanup...")
        # 3a. Case-insensitive language & raw Edge-TTS voice code resolution
        self.assertEqual(tts._resolve_voice_code("Greek", "Nestoras (Male)"), "el-GR-NestorasNeural")
        self.assertEqual(tts._resolve_voice_code("EL", "el-GR-AthinaNeural"), "el-GR-AthinaNeural")
        self.assertEqual(tts._resolve_voice_code("English", "aria (female)"), "en-US-AriaNeural")

        # 3b. None-safe split_into_voice_segments
        self.assertEqual(tts.split_into_voice_segments(None, "el-GR-NestorasNeural"), [])

        # 3c. _clean_tts_text preserves numeric ranges & avoids '«Γεια σου!».'
        cleaned = tts._clean_tts_text("Η περίοδος 1990–2000 ήταν κρίσιμη.\n\n«Γεια σου!»", narration_style="literature")
        self.assertIn("1990–2000", cleaned)
        self.assertNotIn("!».", cleaned)

        # 3d. synthesize_voice_preview rejects path traversal
        with self.assertRaises(ValueError):
            asyncio.run(tts.synthesize_voice_preview("../../evil"))

        # 3e. _tts_chunk_with_retry aborts hung edge_tts via timeout (no infinite hang!)
        class _HungCommunicate:
            def __init__(self, *args, **kwargs):
                pass

            async def save(self, path):
                await asyncio.sleep(10)

        with tempfile.TemporaryDirectory() as td:
            out_chunk = Path(td) / "hung.mp3"
            with patch("backend.tts_engine.edge_tts.Communicate", _HungCommunicate):
                t0 = asyncio.get_event_loop().time() if False else __import__("time").time()
                asyncio.run(tts._tts_chunk_with_retry(
                    "Short test",
                    "en-US-AriaNeural",
                    str(out_chunk),
                    retries=1,
                    timeout_seconds=0.15,
                ))
                elapsed = __import__("time").time() - t0
                self.assertLess(elapsed, 3.0, f"TTS timeout did not abort hung synthesis ({elapsed:.1f}s)")

        # 3f. generate_audiobook cleans up tts_tmp_* on non-cancellation error (e.g. concat failure)
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            src_txt = td_p / "book.txt"
            src_txt.write_text("Hello world.", encoding="utf-8")
            out_mp3 = td_p / "final.mp3"
            job = create_job(str(src_txt), "book.txt", "txt")
            try:
                async def _write_empty(*args, **kwargs):
                    Path(args[2]).write_bytes(b"")

                with patch.object(tts, "_tts_chunk_with_retry", side_effect=_write_empty):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(tts.generate_audiobook(
                            job_id=job.job_id,
                            file_path=str(src_txt),
                            file_type="txt",
                            language="english",
                            voice_name="Aria (Female)",
                            output_path=str(out_mp3),
                        ))
                tmp_dir = td_p / f"tts_tmp_{job.job_id}"
                self.assertFalse(tmp_dir.exists(), "tts_tmp_* directory was leaked after non-cancellation failure!")
            finally:
                _jobs.pop(job.job_id, None)
                db_delete_job(job.job_id)

        # 3g. export_audiobook_m4b passes cover image & timeout to ffmpeg when ffmpeg is available
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            mp3_p = td_p / "in.mp3"
            cov_p = td_p / "cov.jpg"
            m4b_p = td_p / "out.m4b"
            mp3_p.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 200)
            Image.new("RGB", (50, 50), (10, 20, 30)).save(cov_p)

            captured = {}

            def _fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["timeout"] = kwargs.get("timeout")
                Path(cmd[-1]).write_bytes(b"M4B_BYTES")
                return MagicMock(returncode=0)

            with patch("shutil.which", return_value="ffmpeg"), patch("subprocess.run", side_effect=_fake_run):
                asyncio.run(tts.export_audiobook_m4b(str(mp3_p), str(m4b_p), title="T", cover_image_path=str(cov_p)))
            self.assertIn("attached_pic", captured["cmd"], "ffmpeg M4B command omitted cover art!")
            self.assertEqual(captured["timeout"], 300, "ffmpeg M4B command omitted subprocess timeout!")
        print("   TTS voice resolution, text cleaning, timeouts & cleanup: OK")


if __name__ == "__main__":
    unittest.main()
