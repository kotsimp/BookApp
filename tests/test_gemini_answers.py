"""
test_gemini_answers.py - Only complete Gemini answers count, a blocked text costs one request per model, and the
request's own label is in the language of its instructions. Transport-level fake: nothing leaves the computer.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import ai_polisher, gemini_key_pool
from backend import translation_prompts as tp

MODELS = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-3.5-flash-lite"]
TEXT = "The captain counted the boats in the quiet harbour before the evening storm. " * 8


class Response:
    status = 200

    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def json(self, **_kw):
        return self.data


class Session:
    def __init__(self, reason, text):
        self.reason, self.text, self.sent = reason, text, []

    def post(self, url, json=None, **_kw):
        self.sent.append((url, json))
        parts = [{"text": self.text}] if self.text else []
        return Response({"candidates": [{"finishReason": self.reason, "content": {"parts": parts}}]})


async def no_wait(*_a, **_k):
    pass


class TestAnswers(unittest.TestCase):
    def ask(self, session, system="Translate into English."):
        async def models(*_a, **_k):
            return list(MODELS)

        with mock.patch.object(ai_polisher, "_get_available_models", models), \
                mock.patch.object(ai_polisher, "is_gemini_quota_exhausted", return_value=False), \
                mock.patch.object(gemini_key_pool.GeminiRateLimiter, "acquire", no_wait), \
                mock.patch.object(ai_polisher.asyncio, "sleep", no_wait):
            return asyncio.run(ai_polisher._call_gemini_api(
                TEXT, "key-for-offline-tests", system, session=session, bypass_cache=True, cache_gate=lambda _o: False))

    def test_a_complete_answer_is_used(self):
        self.assertEqual(self.ask(Session("STOP", TEXT)), TEXT.strip())

    def test_an_interrupted_answer_is_not_a_result(self):
        for reason in ("RECITATION", "SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "LANGUAGE", "OTHER"):
            with self.assertRaises(ai_polisher._ContentBlockedError, msg=reason):
                self.ask(Session(reason, TEXT[: int(len(TEXT) * 0.9)]))

    def test_a_block_costs_one_request_per_model(self):
        session = Session("SAFETY", "")
        with self.assertRaises(ai_polisher._ContentBlockedError):
            self.ask(session)
        self.assertEqual(len(session.sent), len(MODELS))

    def test_the_label_follows_the_language_of_the_instructions(self):
        for system, greek in (("Translate into English.", False), ("Μετάφρασε στα ελληνικά.", True)):
            session = Session("STOP", TEXT)
            self.ask(session, system)
            sent = session.sent[0][1]["contents"][0]["parts"][0]["text"]
            rest = sent.replace(system, "", 1).replace(TEXT, "")
            self.assertEqual(bool(re.search("[Ͱ-Ͽ]", rest)), greek, system)

    def test_a_long_register_of_names_does_not_flip_the_label(self):
        register = "\n".join(f"- Cunningham Hall {n} -> Κάνιγχαμ" for n in range(200))
        greek_job = tp.build_direct_translation_prompt("english", "greek") + tp.dossier_header("translation", "greek") + register
        english_job = tp.build_direct_translation_prompt("greek", "english") + "\n" + "Καπετάνιος Παπαδόπουλος\n" * 300
        for system, greek in ((greek_job, True), (english_job, False)):
            session = Session("STOP", TEXT)
            self.ask(session, system)
            sent = session.sent[0][1]["contents"][0]["parts"][0]["text"]
            rest = sent.replace(system, "", 1).replace(TEXT, "")
            self.assertEqual(bool(re.search("[Ͱ-Ͽ]", rest)), greek, system[:60])


class TestLimits(unittest.TestCase):
    """The shapes the API sends: every 429 carries the sentence about plan and billing."""

    MINUTE = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
    DAY = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"

    def category(self, violations, delay="21s"):
        body = {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing "
                          "details.", "status": "RESOURCE_EXHAUSTED", "details": [
                              {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                                  {"quotaId": qid, "quotaValue": value, "quotaDimensions": {"model": MODELS[0]}}
                                  for qid, value in violations]},
                              {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}}
        return gemini_key_pool.parse_gemini_error(429, json.dumps(body))["category"]

    def test_a_per_minute_limit_is_a_short_wait(self):
        self.assertEqual(self.category([(self.MINUTE, "15")]), "RATE_LIMIT_TRANSIENT")
        self.assertEqual(self.category([("GenerateContentInputTokensPerModelPerMinute-FreeTier", "250000")]),
                         "RATE_LIMIT_TRANSIENT")

    def test_a_daily_limit_decides_wherever_it_is_listed(self):
        for order in ([(self.DAY, "20"), (self.MINUTE, "15")], [(self.MINUTE, "15"), (self.DAY, "20")]):
            self.assertEqual(self.category(order), "QUOTA_EXCEEDED_DAILY_MODEL")

    def test_no_allowance_is_a_plan_restriction(self):
        self.assertEqual(self.category([(self.MINUTE, "0")]), "MODEL_TIER_RESTRICTED")


if __name__ == "__main__":
    unittest.main()
