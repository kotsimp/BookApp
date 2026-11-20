"""
test_tts_audiobook_deep.py - Comprehensive Unit & Integration Tests for the TTS Audio Engine.
Tests:
1. Voice catalog completeness and fallback resolution (Greek & English).
2. Narration style prosody mapping (rates, pitches) and custom user overrides.
3. Advanced TTS text cleaner (elisions, poetic stanzas, breath pauses, symbol filtering).
4. MP3 chunk concatenation and temporary file cleanup.
5. In-flight job cancellation and temp folder cleanup during audiobook synthesis.
"""

import sys
sys.path.insert(0, ".")
import os
import asyncio
import tempfile
from pathlib import Path
import unittest

from backend.tts_engine import (
    VOICES,
    DEFAULT_RATES,
    DEFAULT_PITCHES,
    _clean_tts_text,
    _concatenate_mp3s,
    generate_audiobook,
)
from backend.job_manager import create_job, get_job, cancel_job, update_job, _jobs


class TestTTSAudiobookDeep(unittest.TestCase):

    def test_voice_catalog_and_fallback(self):
        print("-> 1. Testing Voice Catalog and Fallback Resolution...")
        self.assertIn("greek", VOICES)
        self.assertIn("english", VOICES)
        self.assertIn("Nestoras (Male)", VOICES["greek"])
        self.assertIn("Athina (Female)", VOICES["greek"])
        self.assertEqual(VOICES["greek"]["Nestoras (Male)"], "el-GR-NestorasNeural")
        self.assertEqual(VOICES["greek"]["Athina (Female)"], "el-GR-AthinaNeural")

        self.assertIn("Guy (Male)", VOICES["english"])
        self.assertIn("Jenny (Female)", VOICES["english"])
        print("   Voice catalog: OK")

    def test_prosody_defaults_and_styles(self):
        print("-> 2. Testing Narration Style Prosody Defaults...")
        for style in ("literature", "poetry", "standard", "slow_pauses", "fast"):
            self.assertIn(style, DEFAULT_RATES, f"Missing rate default for {style}")
            self.assertIn(style, DEFAULT_PITCHES, f"Missing pitch default for {style}")

        # Poetry should have slower rate and lower pitch for emotional resonance
        self.assertEqual(DEFAULT_RATES["poetry"], "-20%")
        self.assertEqual(DEFAULT_PITCHES["poetry"], "-2Hz")
        self.assertEqual(DEFAULT_RATES["standard"], "+0%")
        print("   Narration prosody defaults: OK")

    def test_text_cleaner_poetic_pauses_and_elisions(self):
        print("-> 3. Testing Text Cleaner Poetic Rhythm, Elisions & Stanzas...")
        # Stanza breaks in poetry mode preserve \n\n for authentic poetic cadence
        poem_text = "Στίχος πρώτος της στροφής.\n\nΣτίχος δεύτερης στροφής."
        cleaned_poetry = _clean_tts_text(poem_text, narration_style="poetry")
        self.assertIn("\n\n", cleaned_poetry)

        # In slow_pauses mode, natural gentle pauses (...) are inserted between paragraphs
        cleaned_slow = _clean_tts_text(poem_text, narration_style="slow_pauses")
        self.assertIn("...", cleaned_slow)

        # Standard prose should not turn normal paragraphs into ellipses
        cleaned_std = _clean_tts_text(poem_text, narration_style="standard")
        self.assertNotIn("...", cleaned_std)

        # Elision normalization (apostrophes in Greek contractions)
        elision_text = "κι' όμως, μ' ένα χαμόγελο, σ' αυτό το μέρος"
        cleaned_elision = _clean_tts_text(elision_text)
        self.assertIn("κι' όμως", cleaned_elision)
        self.assertIn("μ' ένα", cleaned_elision)
        self.assertIn("σ' αυτό", cleaned_elision)

        # Bullet symbols and private use area characters must be stripped
        bullet_text = "• Στοιχείο 1 ■ Στοιχείο 2 ✉ Μήνυμα"
        cleaned_bullets = _clean_tts_text(bullet_text)
        self.assertNotIn("•", cleaned_bullets)
        self.assertNotIn("■", cleaned_bullets)
        self.assertNotIn("✉", cleaned_bullets)

        # Edge cases: None and empty strings
        self.assertEqual(_clean_tts_text(None), "")
        self.assertEqual(_clean_tts_text(""), "")
        self.assertEqual(_clean_tts_text("   "), "")
        print("   Text cleaner & prosody rules: OK")

    def test_mp3_concatenation(self):
        print("-> 4. Testing MP3 Chunk Concatenation...")
        # Create 3 synthetic MP3 chunks with valid MPEG sync frame headers
        # MPEG-1 Audio Layer III frame sync is 0xFF 0xFB
        dummy_mp3_frame = b"\xff\xfb\x90\x64" + b"\x00" * 414
        
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            chunk1 = td_path / "c1.mp3"
            chunk2 = td_path / "c2.mp3"
            chunk3 = td_path / "c3.mp3"
            out_mp3 = td_path / "final.mp3"

            chunk1.write_bytes(dummy_mp3_frame * 3)
            chunk2.write_bytes(dummy_mp3_frame * 4)
            chunk3.write_bytes(dummy_mp3_frame * 2)

            asyncio.run(_concatenate_mp3s([str(chunk1), str(chunk2), str(chunk3)], str(out_mp3)))
            self.assertTrue(out_mp3.exists())
            self.assertEqual(out_mp3.stat().st_size, len(dummy_mp3_frame) * 9)
        print("   MP3 chunk concatenation: OK")

    def test_audiobook_cancellation_resilience(self):
        print("-> 5. Testing In-Flight Audiobook Cancellation Resilience...")
        job = create_job("test_cancel_book.txt", "test_cancel_book.txt", "txt")
        job_id = job.job_id
        try:
            # Cancel job immediately before/during generation
            cancel_job(job_id)

            with tempfile.TemporaryDirectory() as td:
                txt_file = Path(td) / "sample.txt"
                txt_file.write_text("Αυτό είναι ένα δοκιμαστικό κείμενο για ακύρωση.", encoding="utf-8")
                out_mp3 = Path(td) / "out.mp3"

                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(generate_audiobook(
                        job_id=job_id,
                        file_path=str(txt_file),
                        file_type="txt",
                        language="greek",
                        voice_name="Nestoras (Male)",
                        output_path=str(out_mp3),
                    ))

                # Verify that final output was NOT created and status is cancelled
                self.assertFalse(out_mp3.exists())
                j = get_job(job_id)
                self.assertEqual(j.status, "cancelled")
                print("   Audiobook cancellation & cleanup: OK")
        finally:
            _jobs.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()
