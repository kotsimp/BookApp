"""
test_gemini_quota_warning.py - Comprehensive tests for Gemini API Quota Exhaustion detection and messaging.
Verifies that:
1. get_gemini_quota_info, trip_gemini_quota_exhaustion, and reset_gemini_quota_exhaustion work correctly.
2. The FastAPI /api/gemini/status endpoint returns live quota state and Greek cooldown messages.
3. /api/status/{job_id} includes gemini_quota_exhausted and gemini_quota_message.
4. Smart Batch Queue (/api/queue) includes gemini_quota_exhausted and gemini_quota_message.
5. Automatic teardown leaves zero test jobs in Session History.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import unittest
import urllib.request
import urllib.error

from backend.job_manager import create_job, cleanup_test_jobs
from backend.ai_polisher import (
    is_gemini_quota_exhausted,
    trip_gemini_quota_exhaustion,
    reset_gemini_quota_exhaustion,
    get_gemini_quota_info,
)
from backend.queue_manager import add_to_queue, get_queue_state, clear_queue
from backend.settings_manager import get_setting, save_setting, delete_setting

_KEY_SETTINGS = ("gemini_api_keys", "gemini_api_key")

API = "http://127.0.0.1:8000/api"


def api_get(path):
    req = urllib.request.Request(f"{API}{path}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestGeminiQuotaWarning(unittest.TestCase):
    def setUp(self):
        # No Gemini key during these tests: with a usable key the server's 3-second monitor clears a tripped quota
        # (GeminiKeyPool.check_cooldowns), so a check made just after it ran failed now and then. test_02 saves one.
        # The server keeps a key it was given in its own environment, so it is removed through the server too.
        self._orig_keys = {k: get_setting(k) for k in _KEY_SETTINGS}
        for k in _KEY_SETTINGS:
            delete_setting(k)
        try:
            req = urllib.request.Request(f"{API}/settings/gemini_api_key", method="DELETE")
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            pass
        reset_gemini_quota_exhaustion()
        try:
            api_post_json("/gemini/reset-quota", {})
        except Exception:
            pass
        clear_queue()
        cleanup_test_jobs()

    def tearDown(self):
        reset_gemini_quota_exhaustion()
        try:
            api_post_json("/gemini/reset-quota", {})
        except Exception:
            pass
        clear_queue()
        cleanup_test_jobs()
        for k, value in self._orig_keys.items():
            if value:
                save_setting(k, value)
            else:
                delete_setting(k)

    def test_01_gemini_quota_info_helper(self):
        reset_gemini_quota_exhaustion()
        info = get_gemini_quota_info()
        self.assertFalse(info["exhausted"])
        self.assertEqual(info["remaining_seconds"], 0)
        self.assertIsNone(info["message"])

        # Trip quota for 1800s (30 minutes)
        trip_gemini_quota_exhaustion(1800.0)
        self.assertTrue(is_gemini_quota_exhausted())
        info_tripped = get_gemini_quota_info()
        self.assertTrue(info_tripped["exhausted"])
        self.assertGreater(info_tripped["remaining_seconds"], 1700)
        self.assertGreater(info_tripped["reset_timestamp"], 0)
        self.assertEqual(len(info_tripped["reset_time_str"]), 8)  # HH:MM:SS
        self.assertIn("Εξαντλήθηκε το ημερήσιο όριο του Gemini API", info_tripped["message"])
        self.assertIn("Έτοιμο ξανά στις", info_tripped["message"])
        self.assertIn("Ρυθμίσεις", info_tripped["message"])

        # Reset
        reset_gemini_quota_exhaustion()
        self.assertFalse(is_gemini_quota_exhausted())
        info_reset = get_gemini_quota_info()
        self.assertFalse(info_reset["exhausted"])

    def test_02_gemini_status_api_endpoint(self):
        reset_gemini_quota_exhaustion()
        status, data = api_get("/gemini/status")
        self.assertEqual(status, 200)
        self.assertFalse(data["exhausted"])
        self.assertIsNone(data["message"])

        # Trip and test again
        trip_gemini_quota_exhaustion(3600.0)
        status_tripped, data_tripped = api_get("/gemini/status")
        self.assertEqual(status_tripped, 200)
        self.assertTrue(data_tripped["exhausted"])
        self.assertGreater(data_tripped["reset_timestamp"], 0)
        self.assertEqual(len(data_tripped["reset_time_str"]), 8)
        self.assertIn("Εξαντλήθηκε το ημερήσιο όριο του Gemini API", data_tripped["message"])
        self.assertIn("Έτοιμο ξανά στις", data_tripped["message"])

        # Reset via explicit endpoint
        status_rst, res_rst = api_post_json("/gemini/reset-quota", {})
        self.assertEqual(status_rst, 200)
        self.assertEqual(res_rst["status"], "ok")
        status_cleared, data_cleared = api_get("/gemini/status")
        self.assertFalse(data_cleared["exhausted"])

        # Trip again and reset via settings save
        trip_gemini_quota_exhaustion(3600.0)
        status_set, res_set = api_post_json("/settings", {"gemini_api_key": "AQ.NewKeyTest1234567890abcdef"})
        self.assertEqual(status_set, 200)
        status_cleared2, data_cleared2 = api_get("/gemini/status")
        self.assertFalse(data_cleared2["exhausted"])

    def test_03_job_status_includes_quota_fields(self):
        job = create_job("test_quota_job_file.pdf", "test_quota_job_file.pdf", "pdf")
        jid = job.job_id

        # Normal status
        reset_gemini_quota_exhaustion()
        status, d = api_get(f"/status/{jid}")
        self.assertEqual(status, 200)
        self.assertFalse(d["gemini_quota_exhausted"])
        self.assertIsNone(d["gemini_quota_message"])

        # Tripped status
        trip_gemini_quota_exhaustion(1200.0)
        status2, d2 = api_get(f"/status/{jid}")
        self.assertEqual(status2, 200)
        self.assertTrue(d2["gemini_quota_exhausted"])
        self.assertGreater(d2["gemini_quota_reset_timestamp"], 0)
        self.assertEqual(len(d2["gemini_quota_reset_time_str"]), 8)
        self.assertIn("Εξαντλήθηκε το ημερήσιο όριο", d2["gemini_quota_message"])

    def test_04_batch_queue_includes_quota_state(self):
        job = create_job("test_queue_quota_doc.pdf", "test_queue_quota_doc.pdf", "pdf")
        add_to_queue(job.job_id, ai_polish=True)

        trip_gemini_quota_exhaustion(3600.0)
        q_state = get_queue_state()
        self.assertTrue(q_state["gemini_quota_exhausted"])
        self.assertGreater(q_state["gemini_quota_reset_timestamp"], 0)
        self.assertIn("Εξαντλήθηκε το ημερήσιο όριο", q_state["gemini_quota_message"])

        status, data = api_get("/queue")
        self.assertEqual(status, 200)
        self.assertTrue(data["gemini_quota_exhausted"])
        self.assertGreater(data["gemini_quota_reset_timestamp"], 0)
        self.assertIn("Εξαντλήθηκε το ημερήσιο όριο του Gemini API", data["gemini_quota_message"])

    def test_05_teardown_cleans_up_all_test_jobs(self):
        job1 = create_job("test_clean_1.pdf", "test_clean_1.pdf", "pdf")
        job2 = create_job("reg_clean_2.txt", "reg_clean_2.txt", "txt")
        deleted = cleanup_test_jobs()
        self.assertIn(job1.job_id, deleted)
        self.assertIn(job2.job_id, deleted)

        # Confirm GET /api/jobs has no test jobs
        status, jobs_list = api_get("/jobs")
        self.assertEqual(status, 200)
        for j in jobs_list:
            fname = (j.get("file_name") or "").lower()
            self.assertFalse(fname.startswith("test_"))
            self.assertFalse(fname.startswith("reg_"))


if __name__ == "__main__":
    unittest.main()
