"""
test_target_language.py - English targets get English instructions, and an AI answer that changed the language or
lost text never replaces the book's text.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import ai_polisher, job_manager
from backend import translation_prompts as tp
from backend.database import db_delete_job

KEY = "key-for-offline-tests"
GREEK = re.compile("[Ͱ-Ͽ]")
TAGS = re.compile(r"<(TEXT_TO_POLISH|DRAFT_TO_POLISH|TEXT_TO_TRANSLATE)>\n(.*?)\n</\1>", re.S)


def body(content):
    found = TAGS.search(content)
    return found.group(2) if found else content


def to_greek(text):
    return re.sub(r"[A-Za-z]+", lambda m: "PAGE" if m.group() == "PAGE" else "λέξη", text)


def to_english(text):
    return re.sub("[Ͱ-Ͽ]+", "word", text)


def cut(text):
    return text[: max(1, len(text) // 3)]


def english(n, size=14):
    return "\n\n".join(f"On morning {n}-{i} the captain counted the boats in the quiet harbour before breakfast."
                       for i in range(size))


def greek(n, size=14):
    return "\n\n".join(f"Το πρωί {n}-{i} ο καπετάνιος μέτρησε τις βάρκες στο ήσυχο λιμάνι πριν από το πρωινό."
                       for i in range(size))


def paged(make, pages=4, size=14):
    return "\n\n".join(f"=== PAGE {n} ===\n\n{make(n, size)}" for n in range(1, pages + 1))


SHAPES = {"pages": lambda make: paged(make), "chunks": lambda make: make(1, 90), "short": lambda make: make(1, 6)}


class Offline(unittest.TestCase):
    def polish(self, text, answer, **kw):
        systems = []

        async def call(content, _key, system, *_a, **_k):
            systems.append(system)
            return answer(body(content))

        terms = {"captain": "καπετάνιος (captain)", "kernel": "πυρήνας (kernel)"}
        with mock.patch.object(ai_polisher, "_call_gemini_api", call), \
                mock.patch("backend.glossary.load_glossary", return_value=terms):
            out = asyncio.run(ai_polisher.polish_text_with_gemini(text, api_key=KEY, quota_behavior="fallback", **kw))
        return out, systems


class TestInstructions(Offline):
    def test_english_targets_get_no_greek_instructions(self):
        for style in ("audiobook", "poetry", "literature", "natural"):
            for shape, build in SHAPES.items():
                _out, systems = self.polish(build(english), lambda t: t, style=style, target_lang="english")
                for system in systems:
                    self.assertIsNone(GREEK.search(system), f"{style}/{shape}")

    def test_english_revision_asks_for_english(self):
        _out, systems = self.polish(paged(english), lambda t: t, style="natural", target_lang="english",
                                    original_text=paged(lambda n, size: "Η αρχή του κειμένου.\n\n" * size),
                                    system_prompt_override=tp.build_revision_prompt("english"))
        for system in systems:
            self.assertIsNone(GREEK.search(system))

    def test_glossary_points_towards_english(self):
        _out, systems = self.polish(english(1, 6), lambda t: t, style="natural", target_lang="english",
                                    original_text=greek(1, 6))
        self.assertIn("καπετάνιος -> captain", systems[0])
        self.assertNotIn("captain -> καπετάνιος", systems[0])
        self.assertNotIn("kernel", systems[0], "only terms the Greek source uses")


class TestAnswers(Offline):
    def words(self, text):
        return re.findall(r"[^\W_]+", re.sub(r"=== PAGE \d+ ===", " ", text))

    def test_an_answer_in_the_other_language_is_refused(self):
        for shape, build in SHAPES.items():
            for make, answer, target in ((english, to_greek, "english"), (greek, to_english, "greek")):
                text = build(make)
                out, _ = self.polish(text, answer, style="audiobook", target_lang=target)
                self.assertEqual(self.words(out), self.words(text), f"{shape} -> {target}")

    def test_a_shortened_answer_never_replaces_the_text(self):
        for shape, build in SHAPES.items():
            for make, target in ((english, "english"), (greek, "greek")):
                text = build(make)
                out, _ = self.polish(text, cut, style="natural", target_lang=target)
                self.assertEqual(self.words(out), self.words(text), f"{shape} -> {target}")

    def test_direct_translation_to_english_loses_nothing(self):
        pages = [{"page": n, "text": greek(n), "total": 3} for n in range(1, 4)]
        for name, answer in (("shortened", lambda t: cut(to_english(t))), ("still Greek", lambda t: t)):
            async def call(content, *_a, **_k):
                return answer(body(content))

            async def free(text, *_a, **_k):
                return to_english(text)

            with tempfile.TemporaryDirectory() as td:
                out = Path(td) / "book.txt"
                job = job_manager.create_job("", "book.docx", "docx")
                try:
                    with mock.patch.object(ai_polisher, "_call_gemini_api", call), \
                            mock.patch("backend.parsers.parse_document", return_value=pages), \
                            mock.patch("backend.translator._translate_with_retry", free), \
                            mock.patch("backend.glossary.load_glossary", return_value={}):
                        asyncio.run(ai_polisher.translate_and_polish_direct_with_gemini(
                            job_id=job.job_id, file_path=str(Path(td) / "book.docx"), file_type="docx",
                            source_lang="greek", target_lang="english", output_path=str(out), api_key=KEY,
                            quota_behavior="fallback"))
                    text = out.read_text(encoding="utf-8")
                finally:
                    job_manager._jobs.pop(job.job_id, None)
                    db_delete_job(job.job_id)
            self.assertIsNone(GREEK.search(text), name)
            for n in range(1, 4):
                for i in range(14):
                    self.assertIn(f"{n}-{i}", text, name)


if __name__ == "__main__":
    unittest.main()
