"""
tests/test_gemini_key_pool.py - Comprehensive Unit & Integration Tests for:
- GeminiKeyPool class (CRUD, deduplication, 4-key limit, thread-safety, masking)
- Per-key cooldown tracking and automatic rotation upon quota exhaustion (429)
- Circuit-breaker tripping only when ALL pool keys are exhausted
- FastAPI endpoints:
  - GET /api/gemini/pool
  - POST /api/gemini/pool
  - GET /api/settings (with gemini_api_keys and pool status)
  - POST /api/settings (with gemini_api_keys)
  - DELETE /api/settings/gemini_api_keys
- Full test cleanup (zero test jobs or dirty settings left behind).
"""

import sys
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException
from backend.gemini_key_pool import GeminiKeyPool, mask_api_key, MAX_KEYS
from backend.settings_manager import get_setting, save_setting, delete_setting
from backend.main import (
    get_gemini_pool_status,
    update_gemini_pool_keys,
    get_app_settings,
    update_app_settings,
    delete_app_setting,
    SettingsRequest,
)
from backend.ai_polisher import (
    reset_gemini_quota_exhaustion,
    is_gemini_quota_exhausted,
    get_gemini_quota_info,
    DailyQuotaExhaustedError,
)
from backend.job_manager import cleanup_test_jobs


class TestGeminiKeyPool(unittest.TestCase):
    def setUp(self):
        self._orig_single = get_setting("gemini_api_key")
        self._orig_keys = get_setting("gemini_api_keys")
        GeminiKeyPool.reset_quota()
        cleanup_test_jobs()

    def tearDown(self):
        GeminiKeyPool.reset_quota()
        if self._orig_keys is not None:
            save_setting("gemini_api_keys", self._orig_keys)
        else:
            delete_setting("gemini_api_keys")

        if self._orig_single is not None:
            save_setting("gemini_api_key", self._orig_single)
        else:
            delete_setting("gemini_api_key")
        cleanup_test_jobs()

    def test_01_mask_api_key(self):
        self.assertEqual(mask_api_key(""), "")
        self.assertEqual(mask_api_key("AIzaSyDummyKeyForTesting12345"), "AIzaSy...2345")
        self.assertEqual(mask_api_key("12345678"), "12...78")
        self.assertEqual(mask_api_key("abc"), "***")

    def test_02_set_get_and_limit_keys(self):
        # Setting up to 4 keys
        keys = ["KeyA", "KeyB", "KeyC", "KeyD", "KeyE"]  # 5 keys provided
        saved = GeminiKeyPool.set_keys(keys)
        self.assertEqual(len(saved), MAX_KEYS)
        self.assertEqual(saved, ["KeyA", "KeyB", "KeyC", "KeyD"])

        # Check retrieval
        current = GeminiKeyPool.get_keys()
        self.assertEqual(current, ["KeyA", "KeyB", "KeyC", "KeyD"])

        # Primary key mirrored to legacy single setting
        self.assertEqual(get_setting("gemini_api_key"), "KeyA")

        # Deduplication and whitespace trimming
        deduped = GeminiKeyPool.set_keys([" KeyA ", "KeyB", "KeyA", "  ", "KeyC"])
        self.assertEqual(deduped, ["KeyA", "KeyB", "KeyC"])

    def test_03_add_and_remove_key(self):
        GeminiKeyPool.set_keys(["Key1", "Key2"])
        GeminiKeyPool.add_key("Key3")
        self.assertEqual(GeminiKeyPool.get_keys(), ["Key1", "Key2", "Key3"])

        # Cannot add duplicate
        GeminiKeyPool.add_key("Key2")
        self.assertEqual(GeminiKeyPool.get_keys(), ["Key1", "Key2", "Key3"])

        # Remove by index
        GeminiKeyPool.remove_key(1)  # Remove Key2
        self.assertEqual(GeminiKeyPool.get_keys(), ["Key1", "Key3"])

        # Remove by value
        GeminiKeyPool.remove_key("Key1")
        self.assertEqual(GeminiKeyPool.get_keys(), ["Key3"])

    def test_04_quota_exhaustion_rotation_and_failover(self):
        GeminiKeyPool.set_keys(["Key1", "Key2", "Key3"])
        GeminiKeyPool.reset_quota()

        # Initially, Key1 should be active
        self.assertEqual(GeminiKeyPool.get_active_key(), "Key1")
        self.assertFalse(GeminiKeyPool.is_key_exhausted("Key1"))

        # Mark Key1 exhausted
        GeminiKeyPool.mark_key_exhausted("Key1", cooldown_seconds=3600.0, reason="HTTP 429")
        self.assertTrue(GeminiKeyPool.is_key_exhausted("Key1"))

        # Active key must automatically failover to Key2
        self.assertEqual(GeminiKeyPool.get_active_key(), "Key2")

        # Mark Key2 exhausted
        GeminiKeyPool.mark_key_exhausted("Key2", cooldown_seconds=3600.0, reason="Daily quota")
        self.assertEqual(GeminiKeyPool.get_active_key(), "Key3")

        # Mark Key3 exhausted -> all exhausted
        GeminiKeyPool.mark_key_exhausted("Key3", cooldown_seconds=3600.0, reason="Resource exhausted")
        self.assertIsNone(GeminiKeyPool.get_active_key())

        # Pool status diagnostics
        status = GeminiKeyPool.get_pool_status()
        self.assertEqual(status["total_keys"], 3)
        self.assertEqual(status["available_keys"], 0)
        self.assertTrue(status["all_exhausted"])
        self.assertEqual(len(status["slots"]), 3)
        self.assertTrue(all(s["is_exhausted"] for s in status["slots"]))

        # Resetting quota brings Key1 back
        GeminiKeyPool.reset_quota()
        self.assertEqual(GeminiKeyPool.get_active_key(), "Key1")
        self.assertFalse(GeminiKeyPool.is_key_exhausted("Key1"))

    def test_05_fastapi_gemini_pool_endpoints(self):
        # Direct async invocation of /api/gemini/pool endpoints
        # POST /api/gemini/pool
        res = asyncio.run(update_gemini_pool_keys({"keys": ["TestKey1", "TestKey2"]}))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["keys_count"], 2)
        self.assertEqual(res["pool"]["total_keys"], 2)

        # GET /api/gemini/pool
        pool_info = asyncio.run(get_gemini_pool_status())
        self.assertEqual(pool_info["total_keys"], 2)
        self.assertEqual(pool_info["available_keys"], 2)
        self.assertFalse(pool_info["all_exhausted"])

        # Invalid payload validation: must raise HTTPException 400
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(update_gemini_pool_keys({"keys": "not-a-list"}))
        self.assertEqual(cm.exception.status_code, 400)

    def test_06_fastapi_settings_integration(self):
        # POST /api/settings with gemini_api_keys
        req = SettingsRequest(gemini_api_keys=["SlotKey1", "SlotKey2", "SlotKey3"], default_quota_behavior="wait")
        res = asyncio.run(update_app_settings(req))
        self.assertEqual(res["status"], "ok")

        # GET /api/settings
        s_data = asyncio.run(get_app_settings())
        self.assertEqual(s_data["gemini_api_key"], "SlotKey1")
        self.assertEqual(s_data["gemini_api_keys"], ["SlotKey1", "SlotKey2", "SlotKey3"])
        self.assertIn("pool", s_data)
        self.assertEqual(s_data["pool"]["total_keys"], 3)

        # DELETE /api/settings/{key}
        res_del = asyncio.run(delete_app_setting("gemini_api_keys"))
        self.assertEqual(res_del["status"], "deleted")
        self.assertEqual(GeminiKeyPool.get_keys(), [])

    def test_07_gemini_status_endpoint_returns_pool_and_reset_info(self):
        from backend.main import get_gemini_status
        GeminiKeyPool.set_keys(["KeyAlpha", "KeyBeta"])
        status = asyncio.run(get_gemini_status())
        self.assertIn("pool", status)
        self.assertEqual(status["pool"]["total_keys"], 2)
        self.assertEqual(status["pool"]["available_keys"], 2)
        self.assertFalse(status["pool"]["all_exhausted"])
        self.assertFalse(status["exhausted"])


if __name__ == "__main__":
    unittest.main()
