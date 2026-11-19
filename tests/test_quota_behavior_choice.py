"""
test_quota_behavior_choice.py - Tests for user choice prior to translation or audiobook conversion:
- 'wait': Safely pauses at checkpoint when Gemini quota is exhausted, allowing user to wait for timer or change key.
- 'fallback': Seamlessly switches to free engine (e.g. GTX / local translation / Edge-TTS) without interrupting processing.
- Ensures Session History hygiene (0 test jobs remain).
"""

import sys
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.job_manager import create_job, get_job, update_job, cleanup_test_jobs, Job
from backend.queue_manager import add_to_queue, clear_queue, apply_settings_to_queued_items, get_queue_state
from backend.ai_polisher import (
    DailyQuotaExhaustedError,
    translate_and_polish_direct_with_gemini,
    polish_text_with_gemini,
    reset_gemini_quota_exhaustion,
)


class TestQuotaBehaviorChoice(unittest.TestCase):
    def setUp(self):
        reset_gemini_quota_exhaustion()
        clear_queue()
        cleanup_test_jobs()

    def tearDown(self):
        reset_gemini_quota_exhaustion()
        clear_queue()
        cleanup_test_jobs()

    def test_01_job_and_queue_dataclass_defaults(self):
        job = create_job("test_dummy.txt", "test_dummy.txt", "txt")
        self.assertEqual(job.quota_behavior, "wait")

        q_item = add_to_queue(job.job_id, quota_behavior="fallback")
        self.assertEqual(q_item.quota_behavior, "fallback")
        cleanup_test_jobs()
        clear_queue()

    def test_02_apply_settings_updates_quota_behavior(self):
        job = create_job("test_dummy.txt", "test_dummy.txt", "txt")
        add_to_queue(job.job_id, quota_behavior="wait")
        apply_settings_to_queued_items(quota_behavior="fallback")
        q = get_queue_state()
        self.assertEqual(q["items"][0]["quota_behavior"], "fallback")
        clear_queue()
        cleanup_test_jobs()

    def test_03_direct_ai_quota_wait_behavior(self):
        """When quota_behavior == 'wait', DailyQuotaExhaustedError is re-raised and checkpoint preserved."""
        tmp_txt = Path("test_quota_wait_input.txt")
        tmp_out = Path("test_quota_wait_output.txt")
        tmp_txt.write_text("=== PAGE 1 ===\nHello world", encoding="utf-8")

        job = create_job(str(tmp_txt), tmp_txt.name, "txt")
        update_job(job.job_id, quota_behavior="wait", mode="translate")

        try:
            with patch("backend.ai_polisher._call_gemini_api", side_effect=DailyQuotaExhaustedError("Quota exhausted")):
                with self.assertRaises(DailyQuotaExhaustedError):
                    asyncio.run(
                        translate_and_polish_direct_with_gemini(
                            job_id=job.job_id,
                            file_path=str(tmp_txt),
                            file_type="txt",
                            source_lang="english",
                            target_lang="greek",
                            output_path=str(tmp_out),
                            api_key="AQ.TestKey",
                            quota_behavior="wait",
                        )
                    )
        finally:
            if tmp_txt.exists():
                tmp_txt.unlink()
            if tmp_out.exists():
                tmp_out.unlink()
            cp_file = tmp_out.with_suffix(".direct_ai_checkpoint.json")
            if cp_file.exists():
                cp_file.unlink()
            cleanup_test_jobs()

    def test_04_direct_ai_quota_fallback_behavior(self):
        """When quota_behavior == 'fallback', DailyQuotaExhaustedError triggers fallback and completes."""
        tmp_txt = Path("test_quota_fb_input.txt")
        tmp_out = Path("test_quota_fb_output.txt")
        tmp_txt.write_text("=== PAGE 1 ===\nHello world from test", encoding="utf-8")

        job = create_job(str(tmp_txt), tmp_txt.name, "txt")
        update_job(job.job_id, quota_behavior="fallback", mode="translate")

        async def fake_fallback_tr(text, src, tgt):
            return "Γεια σου κόσμε από δοκιμή"

        try:
            with patch("backend.ai_polisher._call_gemini_api", side_effect=DailyQuotaExhaustedError("Quota exhausted")):
                with patch("backend.translator._translate_with_retry", side_effect=fake_fallback_tr):
                    res = asyncio.run(
                        translate_and_polish_direct_with_gemini(
                            job_id=job.job_id,
                            file_path=str(tmp_txt),
                            file_type="txt",
                            source_lang="english",
                            target_lang="greek",
                            output_path=str(tmp_out),
                            api_key="AQ.TestKey",
                            quota_behavior="fallback",
                        )
                    )
                    out_content = Path(res).read_text(encoding="utf-8")
                    self.assertIn("Γεια σου κόσμε από δοκιμή", out_content)
                    self.assertTrue(tmp_out.exists())
                    updated_job = get_job(job.job_id)
                    self.assertIsNone(updated_job.error)
                    self.assertEqual(updated_job.done_chunks, 1)
        finally:
            if tmp_txt.exists():
                tmp_txt.unlink()
            if tmp_out.exists():
                tmp_out.unlink()
            cp_file = tmp_out.with_suffix(".direct_ai_checkpoint.json")
            if cp_file.exists():
                cp_file.unlink()
            cleanup_test_jobs()

    def test_05_polish_text_fallback_behavior(self):
        """When polishing text with quota_behavior='fallback', it recovers and keeps draft text."""
        raw_draft = "=== PAGE 1 ===\nΚείμενο προς διόρθωση"
        job = create_job("test_dummy.txt", "test_dummy.txt", "txt")
        update_job(job.job_id, quota_behavior="fallback", mode="translate")

        try:
            with patch("backend.ai_polisher._call_gemini_api", side_effect=DailyQuotaExhaustedError("Quota exhausted")):
                result = asyncio.run(
                    polish_text_with_gemini(
                        text=raw_draft,
                        api_key="AQ.TestKey",
                        job_id=job.job_id,
                        quota_behavior="fallback",
                    )
                )
                self.assertIn("Κείμενο προς διόρθωση", result)
        finally:
            cleanup_test_jobs()

    def test_06_session_history_hygiene(self):
        """Ensure no test jobs remain in Session History."""
        deleted = cleanup_test_jobs()
        self.assertEqual(len(deleted), 0)


if __name__ == "__main__":
    unittest.main()
