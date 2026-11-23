"""
test_free_engine_failover.py - Google's refusal is respected, MyMemory stays inside its limit, Gemini stands in with
few requests, and nothing is ever handed out shortened or untranslated.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import re
import sys
import tempfile
import time
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import ai_polisher, format_preserver, job_manager, translator
from backend.database import db_delete_job

_sleep = asyncio.sleep


async def no_wait(*_a, **_k):
    await _sleep(0)


def greek(text):
    """A stand-in translation: every English word becomes a Greek one, all other characters stay."""
    return re.sub(r"[A-Za-z]+", "λέξη", text)


class Gemini:
    def __init__(self, answer=greek):
        self.calls = []
        self.answer = answer

    async def __call__(self, content, *_a, **_k):
        self.calls.append(content)
        body = content.replace("<TEXT_TO_TRANSLATE>\n", "").replace("\n</TEXT_TO_TRANSLATE>", "")
        return self.answer(body)


class Refused(unittest.TestCase):
    def setUp(self):
        self.google = []
        self.memory = []
        self.tag = uuid.uuid4().hex  # the translation cache is persistent

        def refuse(*_a, **_k):
            self.google.append(time.time())
            raise urllib.error.HTTPError("https://translate.googleapis.com", 429, "Too Many Requests", {}, None)

        async def refuse_async(*_a, **_k):
            refuse()

        async def memory(_session, text, *_a):
            self.memory.append(text)
            return self.memory_answer(text)

        self.memory_answer = lambda _text: None
        patches = [
            mock.patch.multiple(translator, _GTX_COOLDOWN_UNTIL=0.0, _GTX_REFUSALS=0, _MYMEMORY_PAUSED_UNTIL=0.0),
            mock.patch.object(translator, "_translate_gtx", refuse),
            mock.patch.object(translator, "_translate_gtx_async", refuse_async),
            mock.patch.object(translator, "GoogleTranslator", side_effect=RuntimeError("429 too many requests")),
            mock.patch.object(translator, "_translate_mymemory_async", memory),
            mock.patch.object(translator.asyncio, "sleep", no_wait),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def with_key(self, gemini):
        for patch in (mock.patch.object(translator, "_failover_key", return_value="test-key"),
                      mock.patch.object(ai_polisher, "_call_gemini_api", gemini)):
            patch.start()
            self.addCleanup(patch.stop)
        return gemini

    def without_key(self):
        patch = mock.patch.object(translator, "_failover_key", return_value="")
        patch.start()
        self.addCleanup(patch.stop)

    def sentences(self, count, start=0):
        return [f"The keeper counted boat number {i} of run {self.tag} before the storm arrived."
                for i in range(start, start + count)]

    def translate(self, text):
        return asyncio.run(translator._translate_with_retry(text, "english", "greek"))


class TestGoogleRefusal(Refused):
    def test_the_pause_grows_and_is_respected(self):
        self.without_key()
        self.memory_answer = greek
        self.translate(self.sentences(1)[0])
        self.assertEqual(len(self.google), 2)
        self.assertGreater(translator._GTX_COOLDOWN_UNTIL - time.time(), 55)
        self.translate(self.sentences(1, 1)[0])
        self.assertEqual(len(self.google), 2, "no request while the pause lasts")
        translator._GTX_COOLDOWN_UNTIL = 0.0
        self.translate(self.sentences(1, 2)[0])
        self.assertGreater(translator._GTX_COOLDOWN_UNTIL - time.time(), 115)

    def test_a_passing_refusal_is_waited_out(self):
        self.without_key()
        start = time.time()
        clock = [start]
        translator._MYMEMORY_PAUSED_UNTIL = start + 7200

        def google(text, *_a, **_k):
            if clock[0] < start + 30:
                raise urllib.error.HTTPError("https://translate.googleapis.com", 429, "Too Many Requests", {}, None)
            return greek(text)

        async def wait(seconds=0, *_a, **_k):
            clock[0] += seconds
            await _sleep(0)

        sentence = self.sentences(1, 7)[0]
        with mock.patch.object(translator, "_translate_gtx", google), \
                mock.patch.object(translator.asyncio, "sleep", wait), \
                mock.patch.object(translator.time, "time", lambda: clock[0]):
            self.assertEqual(self.translate(sentence), greek(sentence))

    def test_fails_at_once_when_every_engine_refuses_for_long(self):
        self.without_key()
        translator._GTX_REFUSALS = 1  # refused before: this pause outlasts every retry
        translator._MYMEMORY_PAUSED_UNTIL = time.time() + 7200
        with mock.patch.object(translator, "_translate_attempt", wraps=translator._translate_attempt) as attempt:
            with self.assertRaises(translator.TranslationUnavailableError) as caught:
                self.translate(" ".join(self.sentences(20)))
        self.assertEqual(attempt.await_count, 1)
        self.assertEqual(self.memory, [])
        self.assertFalse(job_manager.is_quota_error(str(caught.exception)), "nothing may auto-resume on this")


class TestMyMemory(Refused):
    def test_long_text_is_sent_within_the_limit_and_joined_exactly(self):
        self.without_key()
        self.memory_answer = greek
        s = self.sentences(24)
        text = " ".join(s[:10]) + "\n\n" + "\n".join(s[10:18]) + "\n\n" + " ".join(s[18:])
        self.assertEqual(self.translate(text), greek(text))
        self.assertTrue(self.memory and max(map(len, self.memory)) <= 480)

    def test_finished_pieces_are_not_paid_for_twice(self):
        self.without_key()
        text = "\n".join(self.sentences(20))
        self.memory_answer = lambda piece: greek(piece) if len(self.memory) < 3 else None
        self.assertIsNone(asyncio.run(translator._translate_attempt(text, "english", "greek")))
        done = self.memory[:2]
        del self.memory[:]
        self.memory_answer = greek
        self.assertEqual(self.translate(text), greek(text))
        self.assertFalse(set(done) & set(self.memory))


class TestGeminiStandsIn(Refused):
    def test_document_paragraphs_go_in_batches(self):
        gemini = self.with_key(Gemini())
        units = self.sentences(50)
        out = asyncio.run(format_preserver._translate_units(units, "english", "greek", None))
        self.assertEqual(out, [greek(u) for u in units])
        self.assertLessEqual(len(gemini.calls), 2, "not one request per paragraph")

    def test_pages_go_in_batches_with_their_paragraphs(self):
        gemini = self.with_key(Gemini())
        s = self.sentences(128)
        pages = [{"page": n + 1, "text": " ".join(s[16 * n:16 * n + 8]) + "\n\n" + " ".join(s[16 * n + 8:16 * n + 16])}
                 for n in range(8)]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "book.txt"
            job = job_manager.create_job("", "book.txt", "txt")
            try:
                with mock.patch.object(translator, "parse_document", return_value=pages), \
                        mock.patch("backend.glossary.apply_glossary", lambda text, *_a, **_k: text):
                    used = None

                    async def run():
                        nonlocal used
                        used = translator.start_engine_tracking()
                        await translator.translate_document(job.job_id, "unused", "txt", "english", "greek", str(out))

                    asyncio.run(run())
            finally:
                job_manager._jobs.pop(job.job_id, None)
                db_delete_job(job.job_id)
            text = out.read_text(encoding="utf-8")
        self.assertLessEqual(len(gemini.calls), 3, "not one request per page")
        self.assertEqual(text.count("λέξη"), sum(len(re.findall(r"[A-Za-z]+", p["text"])) for p in pages))
        for i in range(1, 9):
            self.assertIn(f"PAGE {i}\n", text)
        self.assertEqual(used, {"gemini"})

    def test_a_shortened_answer_is_not_a_translation(self):
        self.with_key(Gemini(lambda _body: "Περίληψη του κειμένου."))
        with self.assertRaises(translator.TranslationUnavailableError):
            self.translate(" ".join(self.sentences(12)))

    def test_an_answer_left_in_greek_is_not_an_english_translation(self):
        self.with_key(Gemini(lambda body: body))
        text = greek(" ".join(self.sentences(4, 11))) + f" {uuid.uuid4().int}"
        with self.assertRaises(translator.TranslationUnavailableError):
            asyncio.run(translator._translate_with_retry(text, "greek", "english"))

    def test_long_text_prefers_gemini_to_the_small_allowance(self):
        gemini = self.with_key(Gemini())
        self.memory_answer = greek
        text = " ".join(self.sentences(12))
        self.assertEqual(self.translate(text), greek(text))
        self.assertEqual((len(gemini.calls), self.memory), (1, []))


if __name__ == "__main__":
    unittest.main()
