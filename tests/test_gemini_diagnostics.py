"""
tests/test_gemini_diagnostics.py - Dedicated Diagnostic and Stress-Test Suite for Gemini Key Pool,
Rate Limiting, Per-Model Isolation, and Automatic Key Rotation.

Verifies:
1. Individual API key validity and safe masking.
2. Error classification (parse_gemini_error: RPM vs RPD vs model-specific vs auth vs server).
3. Sliding-window RateLimiter (RPM, TPM, and Retry-After enforcement).
4. Per-model cooldown isolation (e.g. 20 RPD on 3.8-flash never kills key for 3.5-flash-lite).
5. End-to-end multi-key rotation simulation (Key 1 -> Key 2 -> Key 3 -> Key 4).
6. Complete pool exhaustion and circuit-breaker tripping.
7. Cooldown expiration, automatic key recovery, and pool reuse.
8. Transient 429 exponential backoff and successful retry on the same key without premature rotation.
9. Concurrent requests and race-condition prevention under high async load.
10. Live diagnostic mode for real configured keys (with minimal token usage).
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
import os
import time
import json
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.gemini_key_pool import (
    GeminiKeyPool,
    GeminiRateLimiter,
    parse_gemini_error,
    mask_api_key,
    MAX_KEYS,
    resolve_gemini_api_key,
)
from backend.settings_manager import get_setting, save_setting, delete_setting
from backend.ai_polisher import (
    _call_gemini_api,
    is_gemini_quota_exhausted,
    trip_gemini_quota_exhaustion,
    reset_gemini_quota_exhaustion,
    get_gemini_quota_info,
    DailyQuotaExhaustedError,
)
from backend.job_manager import cleanup_test_jobs


class TestGeminiDiagnosticsAndRotation(unittest.TestCase):
    def setUp(self):
        self._orig_single = get_setting("gemini_api_key")
        self._orig_keys = get_setting("gemini_api_keys")
        GeminiKeyPool.reset_quota()
        GeminiRateLimiter.reset()
        cleanup_test_jobs()

    def tearDown(self):
        GeminiKeyPool.reset_quota()
        GeminiRateLimiter.reset()
        if self._orig_keys is not None:
            save_setting("gemini_api_keys", self._orig_keys)
        else:
            delete_setting("gemini_api_keys")

        if self._orig_single is not None:
            save_setting("gemini_api_key", self._orig_single)
        else:
            delete_setting("gemini_api_key")
        cleanup_test_jobs()

    def test_01_api_key_validity_masking_and_crud(self):
        """Verifies API key pool storage, deduplication, the 8-key limit (MAX_KEYS), and masking."""
        keys = [f"Key{c}123456789" for c in "ABCDEFGHI"]  # 9 keys provided
        saved = GeminiKeyPool.set_keys(keys)
        self.assertEqual(len(saved), MAX_KEYS)
        self.assertEqual(saved, keys[:8])

        # Masking
        self.assertEqual(mask_api_key("KeyA123456789"), "KeyA12...6789")
        self.assertEqual(mask_api_key("short"), "***")
        self.assertEqual(mask_api_key(""), "")

        # Pool retrieval
        status = GeminiKeyPool.get_pool_status()
        self.assertEqual(status["total_keys"], 8)
        self.assertEqual(status["available_keys"], 8)
        self.assertFalse(status["all_exhausted"])
        self.assertEqual(status["active_key_index"], 0)

    def test_02_parse_gemini_error_classification(self):
        """Verifies precise categorization of Google Gemini API error payloads."""
        # 1. 401 Auth error
        err_401 = '{"error": {"code": 401, "message": "API key not valid", "status": "UNAUTHENTICATED"}}'
        p1 = parse_gemini_error(401, err_401)
        self.assertEqual(p1["category"], "AUTH_ERROR")

        # 2. 404 Model sunset / not found
        err_404 = '{"error": {"code": 404, "message": "models/gemini-2.5-flash is no longer available", "status": "NOT_FOUND"}}'
        p2 = parse_gemini_error(404, err_404)
        self.assertEqual(p2["category"], "MODEL_NOT_FOUND")

        # 3. 503 High demand server overload
        err_503 = '{"error": {"code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}}'
        p3 = parse_gemini_error(503, err_503)
        self.assertEqual(p3["category"], "SERVER_ERROR")
        self.assertTrue(p3["is_transient"])

        # 4. 429 Transient per-minute rate limit (RPM burst, retryDelay = 4s)
        err_429_trans = json.dumps({
            "error": {
                "code": 429,
                "message": "Resource has been exhausted (e.g. check quota).",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "4s"},
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                        {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaMetric": "requests"}
                    ]}
                ]
            }
        })
        p4 = parse_gemini_error(429, err_429_trans)
        self.assertEqual(p4["category"], "RATE_LIMIT_TRANSIENT")
        self.assertTrue(p4["is_transient"])
        self.assertEqual(p4["retry_delay_sec"], 4.0)

        # 5. 429 Model-Specific Daily Quota (e.g. limit: 20 on gemini-3.8-flash)
        err_429_model_daily = json.dumps({
            "error": {
                "code": 429,
                "message": "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "71356s"},
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                        {
                            "description": "Generate content requests per day limit exceeded on Free Tier.",
                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                            "quotaDimensions": {"model": "gemini-3.8-flash", "location": "global"},
                            "quotaValue": "20"
                        }
                    ]}
                ]
            }
        })
        p5 = parse_gemini_error(429, err_429_model_daily)
        self.assertEqual(p5["category"], "QUOTA_EXCEEDED_DAILY_MODEL")
        self.assertTrue(p5["is_model_specific"])
        self.assertEqual(p5["model"], "gemini-3.8-flash")
        self.assertEqual(p5["quota_value"], "20")
        self.assertEqual(p5["retry_delay_sec"], 71356.0)

        # 6. 429 Key-wide Daily Quota
        err_429_key_daily = json.dumps({
            "error": {
                "code": 429,
                "message": "Generate content requests per day limit exceeded for project.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "86400s"},
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                        {"quotaId": "GenerateRequestsPerDayPerProject-FreeTier"}
                    ]}
                ]
            }
        })
        p6 = parse_gemini_error(429, err_429_key_daily)
        self.assertEqual(p6["category"], "QUOTA_EXCEEDED_DAILY_KEY")
        self.assertTrue(p6["is_daily_quota"])

    def test_03_rate_limiter_rpm_and_retry_after(self):
        """Verifies that GeminiRateLimiter tracks sliding window RPM and respects Retry-After."""
        key = "AQ.TestKeyLimiter"
        GeminiRateLimiter.reset(key)

        # 1. Fill sliding window with 5 calls at limit 5 RPM
        async def run_calls():
            for _ in range(5):
                await GeminiRateLimiter.acquire(key, model="gemini-3.5-flash-lite", rpm_limit=5)

        asyncio.run(run_calls())
        stats = GeminiRateLimiter.get_stats(key)
        self.assertEqual(stats["requests_last_minute"], 5)

        # 2. Test explicit Retry-After
        GeminiRateLimiter.record_retry_after(key, delay_seconds=2.0)
        stats2 = GeminiRateLimiter.get_stats(key)
        self.assertTrue(stats2["is_throttled"])
        self.assertGreater(stats2["throttle_remaining_sec"], 0.5)

    def test_04_per_model_cooldown_isolation(self):
        """Verifies that exhausting one model on a key does NOT disable other models on that same key."""
        key = "AQ.TestMultiModelKey"
        GeminiKeyPool.set_keys([key])

        candidates = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

        # Mark only gemini-3.8-flash in cooldown
        GeminiKeyPool.mark_model_exhausted(key, "gemini-3.8-flash", cooldown_seconds=3600.0, reason="Limit 20 reached")

        self.assertTrue(GeminiKeyPool.is_model_exhausted(key, "gemini-3.8-flash"))
        self.assertFalse(GeminiKeyPool.is_model_exhausted(key, "gemini-3.5-flash-lite"))
        self.assertFalse(GeminiKeyPool.is_model_exhausted(key, "gemini-3.1-flash-lite"))

        # Filtering candidate models excludes only 3.8-flash
        active_models = GeminiKeyPool.get_active_models_for_key(key, candidates)
        self.assertEqual(active_models, ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"])

        # The key itself must still be active and available in the pool!
        self.assertFalse(GeminiKeyPool.is_key_exhausted(key))
        self.assertEqual(GeminiKeyPool.get_active_key(), key)

    def test_05_e2e_key_rotation_simulation_1_to_4(self):
        """End-to-end simulation: Key 1 -> Key 2 -> Key 3 -> Key 4 automatic failover."""
        keys = ["AQ.SimKey1", "AQ.SimKey2", "AQ.SimKey3", "AQ.SimKey4"]
        GeminiKeyPool.set_keys(keys)
        GeminiKeyPool.reset_quota()

        called_keys = []

        class MockResponse:
            def __init__(self, status, text_val, json_val=None):
                self.status = status
                self._text = text_val
                self._json = json_val or {}
                self.headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self):
                return self._json

            async def text(self):
                return self._text

        def mock_post(url, *args, **kwargs):
            headers = kwargs.get("headers", {})
            k = headers.get("x-goog-api-key", "")
            called_keys.append(k)

            # Key 1 fails with Daily Quota Exceeded
            if k == "AQ.SimKey1":
                body = json.dumps({
                    "error": {
                        "code": 429,
                        "message": "requests per day limit exceeded",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "86400s"}]
                    }
                })
                return MockResponse(429, body)

            # Key 2 fails with Daily Quota Exceeded
            if k == "AQ.SimKey2":
                body = json.dumps({
                    "error": {
                        "code": 429,
                        "message": "requests per day limit exceeded",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "86400s"}]
                    }
                })
                return MockResponse(429, body)

            # Key 3 fails with Daily Quota Exceeded
            if k == "AQ.SimKey3":
                body = json.dumps({
                    "error": {
                        "code": 429,
                        "message": "requests per day limit exceeded",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "86400s"}]
                    }
                })
                return MockResponse(429, body)

            # Key 4 succeeds!
            if k == "AQ.SimKey4":
                success_body = {
                    "candidates": [{
                        "content": {"parts": [{"text": "Επιτυχημένη μετάφραση από Key 4"}]},
                        "finishReason": "STOP"
                    }]
                }
                return MockResponse(200, "", success_body)

            return MockResponse(500, "Unknown key")

        mock_session = MagicMock()
        mock_session.post.side_effect = mock_post

        with patch("backend.ai_polisher._get_available_models", AsyncMock(return_value=["gemini-3.5-flash-lite"])):
            result = asyncio.run(_call_gemini_api(
                content_text="Sample text to polish",
                api_key="AQ.SimKey1",
                system_prompt="Test instruction",
                session=mock_session,
                bypass_cache=True,
            ))

        self.assertEqual(result, "Επιτυχημένη μετάφραση από Key 4")
        # Verify that all 4 keys were attempted in sequence: Key1 -> Key2 -> Key3 -> Key4
        self.assertIn("AQ.SimKey1", called_keys)
        self.assertIn("AQ.SimKey2", called_keys)
        self.assertIn("AQ.SimKey3", called_keys)
        self.assertIn("AQ.SimKey4", called_keys)

        # Check that pool now recognizes Keys 1-3 as exhausted and Key 4 as active
        self.assertTrue(GeminiKeyPool.is_key_exhausted("AQ.SimKey1"))
        self.assertTrue(GeminiKeyPool.is_key_exhausted("AQ.SimKey2"))
        self.assertTrue(GeminiKeyPool.is_key_exhausted("AQ.SimKey3"))
        self.assertFalse(GeminiKeyPool.is_key_exhausted("AQ.SimKey4"))
        self.assertEqual(GeminiKeyPool.get_active_key(), "AQ.SimKey4")

    def test_06_all_keys_exhausted_trips_circuit_breaker(self):
        """Verifies that when all keys are exhausted, the circuit breaker trips and fails fast."""
        keys = ["AQ.Exh1", "AQ.Exh2"]
        GeminiKeyPool.set_keys(keys)
        GeminiKeyPool.reset_quota()

        GeminiKeyPool.mark_key_exhausted("AQ.Exh1", cooldown_seconds=3600.0, reason="Daily quota")
        GeminiKeyPool.mark_key_exhausted("AQ.Exh2", cooldown_seconds=3600.0, reason="Daily quota")

        self.assertIsNone(GeminiKeyPool.get_active_key())
        self.assertTrue(is_gemini_quota_exhausted())

        q_info = get_gemini_quota_info()
        self.assertTrue(q_info["exhausted"])
        self.assertGreater(q_info["remaining_seconds"], 10)
        self.assertTrue(q_info["pool"]["all_exhausted"])

        # Any subsequent call must fail fast with DailyQuotaExhaustedError
        with self.assertRaises(DailyQuotaExhaustedError):
            asyncio.run(_call_gemini_api(
                content_text="Test",
                api_key="AQ.Exh1",
                system_prompt="Test",
                bypass_cache=True,
            ))

    def test_07_cooldown_recovery_and_reuse(self):
        """Verifies that expired cooldowns automatically restore keys and reset the circuit breaker."""
        key = "AQ.TestRecoveryKey"
        GeminiKeyPool.set_keys([key])
        GeminiKeyPool.reset_quota()

        # Mark exhausted with 1 second cooldown
        GeminiKeyPool.mark_key_exhausted(key, cooldown_seconds=0.1)
        self.assertTrue(GeminiKeyPool.is_key_exhausted(key))

        # Wait for cooldown to expire
        time.sleep(0.2)
        recovered = GeminiKeyPool.check_cooldowns()
        self.assertTrue(recovered)
        self.assertFalse(GeminiKeyPool.is_key_exhausted(key))
        self.assertEqual(GeminiKeyPool.get_active_key(), key)
        self.assertFalse(is_gemini_quota_exhausted())

    def test_08_transient_rate_limit_backoff_and_retry(self):
        """Verifies that transient 429 errors back off and retry on the same key without premature rotation."""
        key = "AQ.SimTransientRetry"
        GeminiKeyPool.set_keys([key, "AQ.SimFallbackKey"])
        GeminiKeyPool.reset_quota()

        attempt_count = 0

        class MockResponse:
            def __init__(self, status, text_val, json_val=None):
                self.status = status
                self._text = text_val
                self._json = json_val or {}
                self.headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self):
                return self._json

            async def text(self):
                return self._text

        def mock_post(url, *args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                # First attempt: transient 429 with 0.1s retryDelay
                body = json.dumps({
                    "error": {
                        "code": 429,
                        "message": "Resource has been exhausted (e.g. check quota).",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "0.1s"}]
                    }
                })
                return MockResponse(429, body)
            else:
                # Second attempt: 200 OK!
                return MockResponse(200, "", {
                    "candidates": [{
                        "content": {"parts": [{"text": "Recovered after transient backoff"}]},
                        "finishReason": "STOP"
                    }]
                })

        mock_session = MagicMock()
        mock_session.post.side_effect = mock_post

        with patch("backend.ai_polisher._get_available_models", AsyncMock(return_value=["gemini-3.5-flash-lite"])):
            res = asyncio.run(_call_gemini_api(
                content_text="Sample text",
                api_key=key,
                system_prompt="Test",
                session=mock_session,
                bypass_cache=True,
            ))

        self.assertEqual(res, "Recovered after transient backoff")
        self.assertEqual(attempt_count, 2)
        # Key must NOT be exhausted!
        self.assertFalse(GeminiKeyPool.is_key_exhausted(key))
        self.assertEqual(GeminiKeyPool.get_active_key(), key)

    def test_09_concurrent_requests_race_condition_safety(self):
        """Verifies thread-safety and lock coordination under concurrent async execution."""
        keys = ["AQ.ConcKey1", "AQ.ConcKey2"]
        GeminiKeyPool.set_keys(keys)
        GeminiKeyPool.reset_quota()

        async def worker(idx):
            # Concurrent acquire
            await GeminiRateLimiter.acquire(keys[idx % 2], model="gemini-3.5-flash-lite", estimated_tokens=500)
            status = GeminiKeyPool.get_pool_status()
            self.assertIsNotNone(status)
            return idx

        async def run_pool():
            tasks = [worker(i) for i in range(12)]
            results = await asyncio.gather(*tasks)
            self.assertEqual(len(results), 12)

        asyncio.run(run_pool())

    def _ok_session(self, calls):
        """A mock Gemini session that answers every request and records (key, model)."""
        class Resp:
            status = 200
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "Μετάφραση έτοιμη."}]}, "finishReason": "STOP"}]}

            async def text(self):
                return ""

        def post(url, *a, **kw):
            calls.append((kw.get("headers", {}).get("x-goog-api-key"), url.split("/models/")[1].split(":")[0]))
            return Resp()

        session = MagicMock()
        session.post.side_effect = post
        return session

    def test_11_requests_take_the_keys_in_turn(self):
        """Parallel batches spread over the pool: each request starts on the next usable key."""
        keys = ["AQ.Turn1", "AQ.Turn2", "AQ.Turn3"]
        GeminiKeyPool.set_keys(keys)
        self.assertEqual([GeminiKeyPool.next_key() for _ in range(4)], keys + ["AQ.Turn1"])
        GeminiKeyPool.mark_key_exhausted("AQ.Turn2", 3600)
        self.assertEqual([GeminiKeyPool.next_key() for _ in range(3)], ["AQ.Turn3", "AQ.Turn1", "AQ.Turn3"])
        GeminiKeyPool.reset_quota()
        GeminiKeyPool.set_keys(keys)
        calls = []
        with patch("backend.ai_polisher._get_available_models", AsyncMock(return_value=["gemini-3.5-flash"])):
            for i in range(3):
                asyncio.run(_call_gemini_api(f"Κείμενο {i}", "AQ.Turn1", "Οδηγίες", session=self._ok_session(calls),
                                             bypass_cache=True))
        self.assertEqual([k for k, _ in calls], keys, "three requests, three keys")

    def test_12_best_model_on_every_key_before_a_weaker_one(self):
        """Key 1 used up the best model's daily allowance: the request uses the best model on key 2, not a weaker
        model on key 1. Only when no key has it left does a weaker model take over."""
        keys = ["AQ.Best1", "AQ.Best2", "AQ.Best3"]
        GeminiKeyPool.set_keys(keys)
        GeminiKeyPool.mark_model_exhausted("AQ.Best1", "gemini-3.5-flash", 3600)
        ranked = ["gemini-3.5-flash", "gemini-flash-latest"]
        self.assertEqual(GeminiKeyPool.key_for_better_model(ranked, "gemini-flash-latest", {"AQ.Best1"}), "AQ.Best2")
        self.assertIsNone(GeminiKeyPool.key_for_better_model(ranked, "gemini-3.5-flash", {"AQ.Best2"}))
        calls = []
        models = AsyncMock(return_value=["gemini-3.5-flash", "gemini-flash-latest"])
        with patch("backend.ai_polisher._get_available_models", models):
            asyncio.run(_call_gemini_api("Κείμενο", "AQ.Best1", "Οδηγίες", session=self._ok_session(calls),
                                         bypass_cache=True))
            self.assertEqual(calls, [("AQ.Best2", "gemini-3.5-flash")], "the best model, on the key that still has it")
            # every key spent on the best model: then the next model does the work
            for k in keys:
                GeminiKeyPool.mark_model_exhausted(k, "gemini-3.5-flash", 3600)
            calls.clear()
            asyncio.run(_call_gemini_api("Κείμενο 2", "AQ.Best1", "Οδηγίες", session=self._ok_session(calls),
                                         bypass_cache=True))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "gemini-flash-latest")

    def test_10_live_diagnostics_minimal(self):
        """Live diagnostic mode: tests configured real keys with a single 1-word call."""
        keys = GeminiKeyPool.get_keys()
        if not keys or all(k.startswith(("AQ.Test", "AIzaTest", "AQ.Sim", "AQ.Exh", "AQ.Conc")) for k in keys):
            print("   Live diagnostics skipped (no production Gemini API keys configured in test environment).")
            return

        import aiohttp
        async def run_live_diag():
            async with aiohttp.ClientSession() as session:
                for idx, k in enumerate(keys, 1):
                    masked = mask_api_key(k)
                    # Test lightweight models list
                    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={k}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        self.assertEqual(resp.status, 200, f"Key #{idx} ({masked}) failed authentication!")
                        data = await resp.json()
                        models = [
                            m.get("name", "").replace("models/", "")
                            for m in data.get("models", [])
                            if "generateContent" in m.get("supportedGenerationMethods", [])
                        ]
                        self.assertGreater(len(models), 0, f"Key #{idx} ({masked}) has no generative models!")

        asyncio.run(run_live_diag())
        print(f"   Live diagnostics: all {len(keys)} configured production keys verified active and healthy.")


if __name__ == "__main__":
    unittest.main()
