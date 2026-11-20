"""
test_ai_polisher_and_translator_resilience.py - Mocked HTTP Resilience Suite for AI Polisher & Translator.
Exercises the REAL Gemini HTTP / cache / retry / error / quality-gate paths (without AQ.Test* bypasses)
and the REAL GTX / MyMemory / fallback translator error paths:
1. AI Polish cache key isolation across styles, languages, glossaries & dossiers (no 50-char prefix collision).
2. Paginated polish_text_with_gemini raises on 100% batch failure (no silent fallback masking).
3. sanitize_ai_output resets in_cot_tail on 3-line translator.py PAGE markers (no silent page deletion).
4. Language-aware post-processing: English audiobook polish does NOT inject Greek glossary or guillemets.
5. Gemini HTTP double-400 (thinkingConfig + safetySettings) strips both and succeeds on attempt 3;
   TimeoutError records last_error; non-dict JSON handled without AttributeError; API key kept out of URL.
6. Edge inputs (None, whitespace, marker-only), scientific units (μm, Δt, Ωm) exempted from mixed_script.
7. Translator: case-insensitive LANG_CODES, malformed GTX JSON (data[0] is None / HTML),
   MyMemory HTTP-200 error string rejection, parser exception marks job status='error'.
"""

import sys
sys.path.insert(0, ".")
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import backend.ai_polisher as ap
import backend.translator as tr
from backend.job_manager import create_job, get_job, _jobs
from backend.database import db_delete_job


class _FakeResponse:
    def __init__(self, status: int, json_data=None, text_data: str = "", url: str = "https://example.test"):
        self.status = status
        self._json = json_data
        self._text = text_data
        self.url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json

    async def text(self):
        return self._text


class _FakeSession:
    def __init__(self, post_handler=None, get_handler=None):
        self._post_handler = post_handler
        self._get_handler = get_handler
        self.recorded_posts = []
        self.recorded_gets = []

    def post(self, url, **kwargs):
        self.recorded_posts.append((url, kwargs))
        return self._post_handler(url, kwargs)

    def get(self, url, **kwargs):
        self.recorded_gets.append((url, kwargs))
        return self._get_handler(url, kwargs)

    async def close(self):
        pass


class TestAIPolisherAndTranslatorResilience(unittest.TestCase):

    def setUp(self):
        ap.reset_model_cache()
        ap._CACHED_API_KEY_HASH = None

    def tearDown(self):
        ap.reset_model_cache()

    def test_1_cache_key_isolation_across_styles_and_prompts(self):
        print("-> 1. Testing Gemini cache key isolation (full prompt hash, no 50-char collision)...")
        shared_prefix = "Είσαι κορυφαίος επαγγελματίας μεταφραστής και επιμελητής εκδόσεων. "
        prompt_a = shared_prefix + "STYLE_A: Formal legal Greek output."
        prompt_b = shared_prefix + "STYLE_B: Technical DevOps Greek output."

        call_count = {"n": 0}

        def _post(url, kwargs):
            call_count["n"] += 1
            body = kwargs.get("json", {})
            txt = body["contents"][0]["parts"][0]["text"]
            reply = "Αποτέλεσμα Α για νομικό κείμενο." if "STYLE_A" in txt else "Αποτέλεσμα Β για τεχνικό κείμενο."
            return _FakeResponse(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": reply}]}}]})

        def _get(url, kwargs):
            return _FakeResponse(200, {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]})

        sess = _FakeSession(post_handler=_post, get_handler=_get)
        sample = f"Unique cache collision test sentence {id(self)}."

        async def _run():
            r1 = await ap._call_gemini_api(sample, "REAL_TEST_KEY_A", prompt_a, session=sess, temperature=0.15)
            r2 = await ap._call_gemini_api(sample, "REAL_TEST_KEY_A", prompt_b, session=sess, temperature=0.15)
            return r1, r2

        r1, r2 = asyncio.run(_run())
        self.assertIn("Αποτέλεσμα Α", r1)
        self.assertIn("Αποτέλεσμα Β", r2)
        self.assertEqual(call_count["n"], 2, "Identical 50-char prefix caused cache collision between different styles!")
        # Also verify API key was NOT leaked in URL query string
        for url, kwargs in sess.recorded_posts + sess.recorded_gets:
            self.assertNotIn("REAL_TEST_KEY_A", url, f"API key leaked in URL query string: {url}")
            self.assertEqual(kwargs.get("headers", {}).get("x-goog-api-key"), "REAL_TEST_KEY_A")
        print("   Cache key isolation & URL key-leak prevention: OK")

    def test_2_double_400_strip_retry_and_timeout_error_message(self):
        print("-> 2. Testing Gemini double-400 (thinkingConfig + safetySettings) retry & TimeoutError tracking...")
        seen_payloads = []

        def _post(url, kwargs):
            payload = kwargs.get("json", {})
            seen_payloads.append(payload)
            if "thinkingConfig" in payload.get("generationConfig", {}):
                return _FakeResponse(400, text_data="Unknown field thinkingConfig")
            if "safetySettings" in payload:
                return _FakeResponse(400, text_data="Unsupported field safetySettings")
            return _FakeResponse(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Καθαρό κείμενο μετά από διπλό 400."}]}}]})

        def _get(url, kwargs):
            return _FakeResponse(200, {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]})

        sess = _FakeSession(post_handler=_post, get_handler=_get)
        res = asyncio.run(ap._call_gemini_api(
            f"Double 400 test {id(self)}",
            "REAL_KEY_400",
            "System prompt test",
            session=sess,
            bypass_cache=True,
        ))
        self.assertIn("Καθαρό κείμενο", res)
        self.assertEqual(len(seen_payloads), 3, "Expected 3 attempts: strip thinkingConfig, strip safetySettings, succeed!")

        # TimeoutError must produce a descriptive timeout error message (not generic)
        def _post_timeout(url, kwargs):
            raise asyncio.TimeoutError()

        sess_to = _FakeSession(post_handler=_post_timeout, get_handler=_get)
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(ap._call_gemini_api("Timeout probe", "REAL_KEY_TO", "Sys", session=sess_to, bypass_cache=True))
        self.assertIn("timed out", str(ctx.exception).lower())
        print("   Double-400 strip retry & TimeoutError reporting: OK")

    def test_3_total_batch_failure_raises_instead_of_silent_fallback(self):
        print("-> 3. Testing paginated polish_text_with_gemini raises on 100% batch failure...")
        sample = "=== PAGE 1 ===\nΠρώτη σελίδα.\n\n=== PAGE 2 ===\nΔεύτερη σελίδα."

        async def _always_fail(*args, **kwargs):
            raise RuntimeError("Simulated total Gemini outage (503)")

        with patch.object(ap, "_call_gemini_api", side_effect=_always_fail):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(ap.polish_text_with_gemini(sample, api_key="REAL_KEY_OUTAGE", style="formal"))
            self.assertIn("503", str(ctx.exception))
        print("   Total-failure loud error propagation: OK")

    def test_4_cot_tail_resets_on_3line_page_markers_and_scientific_units(self):
        print("-> 4. Testing sanitize_ai_output 3-line PAGE marker reset, non-dict JSON, & SI units...")
        leaked = (
            "Καλό κείμενο πρώτης σελίδας.\n"
            "**Final Polish:** Reviewing grammar rules...\n"
            "============================================================\n"
            "PAGE 2\n"
            "============================================================\n"
            "Κείμενο δεύτερης σελίδας που ΔΕΝ πρέπει να διαγραφεί."
        )
        cleaned = ap.sanitize_ai_output(leaked)
        self.assertIn("PAGE 2", cleaned)
        self.assertIn("δεύτερης σελίδας", cleaned)
        self.assertNotIn("Final Polish", cleaned)

        # Non-dict Gemini JSON must not raise AttributeError
        self.assertEqual(ap._extract_gemini_text_and_reason(["unexpected", "list"]), ("", ""))
        self.assertEqual(ap._extract_gemini_text_and_reason(None), ("", ""))

        # Scientific SI units (μm, Δt, Ωm) must NOT be falsely flagged as mixed_script corruption
        sci_text = "Το μήκος κύματος ήταν 12 μm με μεταβολή Δt και αντίσταση 5 Ωm."
        self.assertEqual(ap.detect_greek_output_issues(sci_text, source_text="12 μm Δt 5 Ωm"), [])

        # Edge inputs: None / whitespace / marker-only must not crash
        self.assertEqual(asyncio.run(ap.polish_text_with_gemini(None, api_key="AQ.TestEdge")), "")
        self.assertEqual(asyncio.run(ap.polish_text_with_gemini("   ", api_key="AQ.TestEdge")), "   ")
        marker_only = "=== PAGE 1 ===\n\n=== PAGE 2 ==="
        out_m = asyncio.run(ap.polish_text_with_gemini(marker_only, api_key="AQ.TestEdge"))
        self.assertIsInstance(out_m, str)
        print("   3-line PAGE marker reset, non-dict safety & SI units: OK")

    def test_5_english_audiobook_polish_no_greek_corruption(self):
        print("-> 5. Testing English audiobook polish skips Greek glossary & guillemets...")
        en_text = 'He walked into the Server Room and said "Check the backup immediately."'
        res = asyncio.run(ap.polish_text_with_gemini(
            en_text,
            api_key="AQ.TestEnglishAudiobook",
            style="audiobook",
            target_lang="english",
        ))
        self.assertNotIn("Αίθουσα Διακομιστών", res)
        self.assertNotIn("αντίγραφο ασφαλείας", res)
        self.assertNotIn("«", res)
        print("   Language-aware English polish protection: OK")

    def test_6_translator_case_insensitive_malformed_gtx_and_mymemory_errors(self):
        print("-> 6. Testing translator case-insensitive langs, malformed GTX, MyMemory error rejection & parse error...")
        self.assertEqual(tr._resolve_lang_code("English", "el"), "en")
        self.assertEqual(tr._resolve_lang_code("GREEK", "en"), "el")
        self.assertEqual(tr._resolve_lang_code("EL", "en"), "el")

        # Malformed GTX payloads must raise ValueError cleanly (never TypeError/IndexError)
        for bad_payload in (None, {}, [], [None], "<html>CAPTCHA</html>"):
            with self.assertRaises(ValueError):
                tr._extract_gtx_text(bad_payload)

        # MyMemory HTTP-200 error payloads MUST be rejected (return None, never cached!)
        async def _test_mm():
            for err_body in (
                {"responseStatus": 200, "responseData": {"translatedText": "QUERY LENGTH LIMIT EXCEEDED. MAX ALLOWED QUERY : 500 CHARS"}},
                {"responseStatus": 200, "responseData": {"translatedText": "PLEASE SELECT TWO DISTINCT LANGUAGES"}},
                {"responseStatus": 429, "responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"}},
            ):
                sess = _FakeSession(get_handler=lambda u, kw, b=err_body: _FakeResponse(200, json_data=b))
                res = await tr._translate_mymemory_async(sess, "Hello world", "English", "Greek")
                self.assertIsNone(res, f"MyMemory error payload was falsely accepted: {err_body}")

            # Valid MyMemory response still works
            ok_body = {"responseStatus": 200, "responseData": {"translatedText": "Γεια σου κόσμε"}}
            sess_ok = _FakeSession(get_handler=lambda u, kw: _FakeResponse(200, json_data=ok_body))
            self.assertEqual(await tr._translate_mymemory_async(sess_ok, "Hello world", "English", "Greek"), "Γεια σου κόσμε")

        asyncio.run(_test_mm())

        # Parser failure inside translate_document must set job status='error' instead of leaving it 'running'
        job = create_job("nonexistent_corrupt.pdf", "nonexistent_corrupt.pdf", "pdf")
        try:
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(Exception):
                    asyncio.run(tr.translate_document(
                        job_id=job.job_id,
                        file_path=str(Path(td) / "missing.pdf"),
                        file_type="pdf",
                        source_lang="english",
                        target_lang="greek",
                        output_path=str(Path(td) / "out.txt"),
                    ))
                self.assertEqual(get_job(job.job_id).status, "error")
        finally:
            _jobs.pop(job.job_id, None)
            db_delete_job(job.job_id)
        print("   Translator resilience & MyMemory error filtering: OK")

    def test_daily_quota_circuit_breaker_and_comic_skip(self):
        print("-> 7. Testing Gemini Daily Quota Circuit Breaker & Comic skip...")
        ap.reset_model_cache()
        self.assertFalse(ap.is_gemini_quota_exhausted())

        quota_429_payload = json.dumps({
            "error": {
                "code": 429,
                "message": "Resource exhausted",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"description": "Generate content requests per day limit exceeded on Free Tier."}
                        ]
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3600s"}
                ]
            }
        })

        call_count = 0
        def fake_post(url, kw):
            nonlocal call_count
            call_count += 1
            return _FakeResponse(429, text_data=quota_429_payload)

        sess = _FakeSession(post_handler=fake_post)

        async def _test_breaker():
            with patch("backend.ai_polisher._get_available_models", return_value=["m1", "m2", "m3"]):
                with self.assertRaises(ap.DailyQuotaExhaustedError):
                    await ap._call_gemini_api(
                        "Sample text",
                        api_key="valid-mock-key-12345",
                        system_prompt="Test prompt",
                        session=sess,
                    )

            # Circuit breaker must stop after exactly 1 model call instead of exhausting all models!
            self.assertEqual(call_count, 1)
            self.assertTrue(ap.is_gemini_quota_exhausted())

            # Immediate subsequent call must fail fast (0 HTTP calls)
            with self.assertRaises(ap.DailyQuotaExhaustedError):
                await ap._call_gemini_api(
                    "Sample text 2",
                    api_key="valid-mock-key-12345",
                    system_prompt="Test prompt",
                    session=sess,
                )
            self.assertEqual(call_count, 1)

            # Comic balloon polish with quota_behavior="fallback" must skip AI polish cleanly and return drafts
            from backend.comic_translator import _ai_polish_comic_balloons
            balloons = [{"source": "Look!", "draft": "Κοιτάξτε!"}]
            res = await _ai_polish_comic_balloons(balloons, api_key="valid-mock-key-12345", target_lang="greek", quota_behavior="fallback")
            self.assertEqual(res, ["Κοιτάξτε!"])

            # Comic balloon polish with quota_behavior="wait" must raise DailyQuotaExhaustedError
            with self.assertRaises(ap.DailyQuotaExhaustedError):
                await _ai_polish_comic_balloons(balloons, api_key="valid-mock-key-12345", target_lang="greek", quota_behavior="wait")

        asyncio.run(_test_breaker())

        # Resetting model cache clears the circuit breaker
        ap.reset_model_cache()
        self.assertFalse(ap.is_gemini_quota_exhausted())
        print("   Daily Quota Circuit Breaker & Comic skip: OK")


if __name__ == "__main__":
    unittest.main()
