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
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
import unittest
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException
from backend.gemini_key_pool import GeminiKeyPool, mask_api_key, MAX_KEYS, resolve_gemini_api_key
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
        # Setting up to 8 keys
        keys = [f"Key{c}" for c in "ABCDEFGHI"]  # 9 keys provided
        saved = GeminiKeyPool.set_keys(keys)
        self.assertEqual(MAX_KEYS, 8)
        self.assertEqual(len(saved), MAX_KEYS)
        self.assertEqual(saved, keys[:8])

        # Check retrieval
        current = GeminiKeyPool.get_keys()
        self.assertEqual(current, keys[:8])

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
        # Keys are returned MASKED only (they never leave the server in clear text)
        from backend.gemini_key_pool import mask_api_key
        self.assertEqual(s_data["gemini_api_key"], mask_api_key("SlotKey1"))
        self.assertEqual(s_data["gemini_api_keys"], [mask_api_key(k) for k in ("SlotKey1", "SlotKey2", "SlotKey3")])
        self.assertNotIn("SlotKey1", json.dumps(s_data))
        self.assertTrue(s_data["has_gemini_key"])
        self.assertEqual(s_data["gemini_api_keys_count"], 3)
        self.assertIn("pool", s_data)
        self.assertEqual(s_data["pool"]["total_keys"], 3)

        # Round-trip: saving the masked values back keeps the real keys; a new key in a slot is added
        masked = s_data["gemini_api_keys"]
        asyncio.run(update_app_settings(SettingsRequest(gemini_api_keys=[masked[0], "SlotKeyNEW4", masked[2]])))
        self.assertEqual(GeminiKeyPool.get_keys(), ["SlotKey1", "SlotKeyNEW4", "SlotKey3"])
        # An unknown masked value is never stored as a key
        asyncio.run(update_app_settings(SettingsRequest(gemini_api_keys=["AIzaSy...ZZZZ", masked[0]])))
        self.assertEqual(GeminiKeyPool.get_keys(), ["SlotKey1"])
        # A masked explicit key resolves to the stored key, never to itself
        from backend.gemini_key_pool import resolve_gemini_api_key
        self.assertEqual(resolve_gemini_api_key(masked[0]), "SlotKey1")

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

    def test_07b_status_names_models_at_their_limit_and_waiting_jobs(self):
        # A job may wait although no key is spent: only the models it may use reached their daily limit
        from backend.main import get_gemini_status
        from backend.job_manager import create_job, update_job, cleanup_test_jobs
        GeminiKeyPool.set_keys(["KeyAlpha", "KeyBeta", "KeyGamma"])
        GeminiKeyPool.mark_model_exhausted("KeyAlpha", "gemini-3.5-flash", cooldown_seconds=3600)
        GeminiKeyPool.mark_model_exhausted("KeyBeta", "gemini-3.5-flash", cooldown_seconds=1800)
        GeminiKeyPool.mark_model_exhausted("KeyAlpha", "gemini-3.8-flash", cooldown_seconds=600)
        job = create_job("test_waiting_book.pdf", "test_waiting_book.pdf", "pdf")
        try:
            update_job(job.job_id, status="error",
                       error="All Gemini candidate models are in cooldown across configured keys. (quota)")
            status = asyncio.run(get_gemini_status())
            models = {m["model"]: m for m in status["pool"]["cooling_models"]}
            self.assertEqual(set(models), {"gemini-3.5-flash", "gemini-3.8-flash"})
            self.assertEqual(models["gemini-3.5-flash"]["keys"], 2)
            self.assertLessEqual(models["gemini-3.5-flash"]["remaining_sec"], 1800, "the first key back counts")
            self.assertEqual(models["gemini-3.8-flash"]["keys"], 1)
            self.assertFalse(status["exhausted"], "the keys themselves are not spent")
            waiting = [j["file_name"] for j in status["waiting_jobs"]]
            self.assertIn("test_waiting_book.pdf", waiting)
            slot1 = status["pool"]["slots"][0]
            self.assertEqual(sorted(slot1["cooling_models"]), ["gemini-3.5-flash", "gemini-3.8-flash"])
        finally:
            GeminiKeyPool.reset_quota()
            cleanup_test_jobs()

    def test_08_resolve_gemini_api_key(self):
        # Explicit key takes priority
        self.assertEqual(resolve_gemini_api_key("ExplicitKey123"), "ExplicitKey123")

        # Resolves active key from pool
        GeminiKeyPool.set_keys(["PoolKey1", "PoolKey2"])
        self.assertEqual(resolve_gemini_api_key(), "PoolKey1")

        # When first key exhausted, rotates to next pool key
        GeminiKeyPool.mark_key_exhausted("PoolKey1", cooldown_seconds=3600)
        self.assertEqual(resolve_gemini_api_key(), "PoolKey2")

        # When all exhausted, returns first pool key for quota handling
        GeminiKeyPool.mark_key_exhausted("PoolKey2", cooldown_seconds=3600)
        self.assertEqual(resolve_gemini_api_key(), "PoolKey1")

        # When pool empty, falls back to legacy setting
        GeminiKeyPool.set_keys([])
        delete_setting("gemini_api_keys")
        save_setting("gemini_api_key", "LegacyKey999")
        self.assertEqual(resolve_gemini_api_key(), "LegacyKey999")


if __name__ == "__main__":
    unittest.main()
