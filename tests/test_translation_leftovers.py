"""
test_translation_leftovers.py - what an AI book translation must not leave behind, and the book layout around it.

Verifies:
1. An AI answer that echoes the source's prose untranslated is refused and the passage is split and retried; it is
   never written into the book. Reference lists, names and short quotations copied on purpose are not mistaken for it.
2. Pages still carrying source prose, and Greek words with letters of another alphabet, are reported in the job's
   final message.
3. Polytonic slips ('δῶθε', 'ἴσως') become monotonic; a polytonic source keeps its accents.
4. Dialogue switched to dashes where the source uses quotation marks earns a retry that says so.
5. Words with letters of another alphabet are repaired by one small AI request whose answers are validated.
6. The maximum-quality revision is merged page by page: an odd page keeps the first pass, the rest is revised.
7. A contents page loses the original edition's page numbers, its titles open chapters, and the literature PDF prints
   the new page numbers and carries bookmarks.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import re
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend.ai_polisher as ap
from backend.job_manager import create_job, cleanup_test_jobs

FIRST_EN = "The storm had passed by the time the ferry reached the island, and nobody on board said a word."
FIRST_EL = "Η καταιγίδα είχε περάσει ώσπου το φέρι να φτάσει στο νησί, και κανείς στο κατάστρωμα δεν μίλησε."
PROSE_EN = ("The lighthouse keeper walked down to the harbour every morning and counted the boats that had come back "
            "during the night, while the gulls argued over the nets and the baker's boy waited for him at the corner "
            "with warm bread and the latest news from the village square.")
PROSE_EL = ("Ο φαροφύλακας κατέβαινε κάθε πρωί στο λιμάνι και μετρούσε τις βάρκες που είχαν γυρίσει τη νύχτα, ενώ οι "
            "γλάροι μάλωναν πάνω από τα δίχτυα και το παιδί του φούρναρη τον περίμενε στη γωνία με ζεστό ψωμί.")
REFERENCES = ("Smith, J. 2004. A Study of Coastal Navigation in the Northern Seas. Journal of Maritime History 12: 45-67.\n"
              "Brown, K. and Lee, M. 2001. Tides, Winds and the Small Harbour Economy. Coastal Review 3: 1-20.")


class TestUntranslatedEcho(unittest.TestCase):

    def tearDown(self):
        cleanup_test_jobs()

    def test_echoed_prose_is_refused_but_references_and_quotes_are_not(self):
        given = f"=== PAGE 1 ===\n{FIRST_EN}\n\n{PROSE_EN}"
        echoed = f"=== PAGE 1 ===\n{FIRST_EL}\n\n{PROSE_EN}"
        self.assertTrue(ap._answer_problem(echoed, given, True, translating=True).startswith("untranslated"))
        self.assertEqual(ap._answer_problem(f"=== PAGE 1 ===\n{FIRST_EL}\n\n{PROSE_EL}", given, True,
                                            translating=True), "")
        # a reference list stays in its own language on purpose
        self.assertEqual(ap._answer_problem(f"{PROSE_EL}\n{REFERENCES}", f"{PROSE_EN}\n{REFERENCES}", True,
                                            translating=True), "")
        # a short quotation kept in English is no echo
        quote = "the lighthouse keeper walked down to the harbour every morning"
        self.assertEqual(ap._copied_source_prose(f"{PROSE_EL} «{quote}»", PROSE_EN), 0)
        # polishing a Greek draft is judged by the other rules
        self.assertEqual(ap._answer_problem(PROSE_EL, PROSE_EL, True), "")

    def test_direct_translation_splits_an_echoed_page_until_it_is_translated(self):
        calls = []

        async def fake(content, api_key, system_prompt, session=None, temperature=0.25, **kw):
            m = re.search(r"<TEXT_TO_TRANSLATE>\n(.*?)\n</TEXT_TO_TRANSLATE>", content, re.S)
            body = m.group(1) if m else content
            calls.append(body)
            if FIRST_EN in body and PROSE_EN in body:
                return body  # the model will not translate the whole page and hands it back unchanged
            marker = re.match(r"(=== PAGE \d+ ===)\n", body)
            return "\n".join(([marker.group(1)] if marker else [])
                             + ([FIRST_EL] if FIRST_EN in body else []) + ([PROSE_EL] if PROSE_EN in body else []))

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "test_leftovers_direct.txt"
            src.write_text(f"{FIRST_EN}\n\n{PROSE_EN}", encoding="utf-8")
            out = Path(td) / "test_leftovers_direct_translated.txt"
            job = create_job(str(src), src.name, "txt")
            with mock.patch.object(ap, "_call_gemini_api", new=fake):
                asyncio.run(ap.translate_and_polish_direct_with_gemini(job.job_id, str(src), "txt", "english",
                                                                        "greek", str(out), "REAL_KEY"))
            text = out.read_text(encoding="utf-8")
        self.assertGreater(len(calls), 1, "the echoed page must be split and retried")
        self.assertNotIn("lighthouse", text)
        self.assertIn("φαροφύλακας", text)
        self.assertIn("καταιγίδα", text)

    def test_leftover_pages_and_words_are_reported(self):
        original = (f"=== PAGE 1 ===\n{FIRST_EN}\n\n=== PAGE 2 ===\n{PROSE_EN}\n\n"
                    f"=== PAGE 3 ===\n{FIRST_EN}\n{REFERENCES}")
        translated = (f"=== PAGE 1 ===\n{FIRST_EL}\n\n=== PAGE 2 ===\n{PROSE_EN}\n\n"
                      f"=== PAGE 3 ===\nΔεν ήξερε ποгда θα γυρίσει.\n{REFERENCES}")
        self.assertEqual(ap.find_untranslated_pages(translated, original), [2])
        notes = ap.translation_leftover_notes(translated, original)
        self.assertEqual(len(notes), 2, notes)
        self.assertIn("pages 2 of the original", notes[0])
        self.assertIn("ποгда", notes[1])
        self.assertEqual(ap.translation_leftover_notes(f"=== PAGE 1 ===\n{FIRST_EL}", original), [])
        self.assertEqual(ap.translation_leftover_notes(translated, original, greek_target=False), [])

    def test_job_notes_from_main(self):
        import backend.main as main_mod
        self.assertEqual(main_mod._revision_notes({"status": "revised", "changed_lines": 3}), [])
        self.assertIn("did not complete", main_mod._revision_notes({"status": "error", "reason": "x"})[0])
        self.assertIn("2 page(s) kept", main_mod._revision_notes({"status": "revised", "kept_pages": 2})[0])
        with tempfile.TemporaryDirectory() as td:
            orig = Path(td) / "book_original.txt"
            orig.write_text(f"=== PAGE 1 ===\n{PROSE_EN}", encoding="utf-8")
            self.assertEqual(len(main_mod._leftover_notes(f"=== PAGE 1 ===\n{PROSE_EN}", orig, "greek")), 1)
            self.assertEqual(main_mod._leftover_notes(f"=== PAGE 1 ===\n{PROSE_EN}", orig, "english"), [])
            self.assertEqual(main_mod._leftover_notes("x", Path(td) / "missing.txt", "greek"), [])


class TestScriptSlips(unittest.TestCase):

    def test_polytonic_slips_become_monotonic(self):
        out = ap.sanitize_ai_output("Πήγαινε πέρα δῶθε. Ἴσως να ῥούφηξε λίγο αέρα.")
        self.assertIn("δώθε", out)
        self.assertIn("Ίσως", out)
        self.assertIn("ρούφηξε", out)
        self.assertIsNone(re.search(r"[ἀ-῿]", out))
        self.assertEqual(ap.to_monotonic("ᾠδή"), "ωδή")
        # a polytonic source (an ancient quotation) keeps its accents
        ancient = "Ἐν ἀρχῇ ἦν ὁ λόγος."
        self.assertIn("ἀρχῇ", ap.sanitize_ai_output(ancient, source_text=ancient))

    def test_presentation_forms_count_as_another_alphabet(self):
        self.assertEqual(ap._exotic_greek_tokens("Ο Κﺍﺭλ ήρθε. Η Μεγάλη Φαρμακεﻭτική."), ["Κﺍﺭλ", "Φαρμακεﻭτική"])

    def test_dialogue_switched_to_dashes_is_flagged(self):
        source = '"Where are you going?" she asked.\n"Out," he said.\n"When will you be back?"\n"Later."'
        dashes = "— Πού πας; ρώτησε.\n— Έξω, είπε.\n— Πότε θα γυρίσεις;\n— Αργότερα."
        quotes = "«Πού πας;» ρώτησε.\n«Έξω», είπε.\n«Πότε θα γυρίσεις;»\n«Αργότερα»."
        issues = ap.detect_greek_output_issues(dashes, source_text=source)
        self.assertTrue(any(i.startswith("dialogue_dashes") for i in issues), issues)
        self.assertEqual(ap.detect_greek_output_issues(quotes, source_text=source), [])
        # a source that writes its dialogue with dashes may keep them
        self.assertEqual(ap.detect_greek_output_issues(dashes, source_text=dashes), [])
        self.assertIn("ΔΙΟΡΘΩΣΗ ΔΙΑΛΟΓΩΝ", ap._quality_retry_hint(issues, dashes, source, True))
        self.assertEqual(ap._quality_retry_hint(issues, dashes, source, False), "")

    def test_corrupted_words_are_repaired_with_validated_answers(self):
        text = "Δεν ήξερε ποгда θα γυρίσει. Ίσות να μην ερχόταν ποτέ. Το Σпиρ ήταν ψηλό."
        seen = []

        async def fake(content, api_key, system_prompt, session=None, temperature=0.25, **kw):
            seen.append(content)
            return "1. πότε\n2. ίσως\n3. Spire tower"

        with mock.patch.object(ap, "_call_gemini_api", new=fake):
            fixed, left = asyncio.run(ap.repair_mixed_script_words(text, "REAL_KEY"))
        self.assertEqual(fixed, "Δεν ήξερε πότε θα γυρίσει. Ίσως να μην ερχόταν ποτέ. Το Σпиρ ήταν ψηλό.")
        self.assertEqual(left, ["Σпиρ"], "an answer that is not one Greek word is not used")
        self.assertIn("[[ποгда]]", seen[0])

        async def down(*a, **kw):
            raise ap.DailyQuotaExhaustedError("quota")

        with mock.patch.object(ap, "_call_gemini_api", new=down):
            same, left = asyncio.run(ap.repair_mixed_script_words(text, "REAL_KEY"))
        self.assertEqual((same, len(left)), (text, 3))
        self.assertEqual(asyncio.run(ap.repair_mixed_script_words("Καθαρό κείμενο.", "REAL_KEY")),
                         ("Καθαρό κείμενο.", []))


class TestRevisionMerge(unittest.TestCase):
    PAGE1 = "Η Άννα κοίταξε τη θάλασσα για πολλή ώρα. " * 8
    PAGE2 = "Ο Πέτρος έδεσε τη βάρκα και ανέβηκε στο μονοπάτι. " * 8
    DRAFT = f"=== PAGE 1 ===\n{PAGE1}\n\n=== PAGE 2 ===\n{PAGE2}\n"

    def test_missing_or_implausible_page_keeps_the_first_pass(self):
        new1 = self.PAGE1.replace("κοίταξε", "αγνάντευε")
        merged, kept = ap.merge_revised_pages(self.DRAFT, f"=== PAGE 1 ===\n{new1}")
        self.assertEqual(kept, [2])
        self.assertIn("αγνάντευε", merged)
        self.assertIn(f"=== PAGE 2 ===\n{self.PAGE2}", merged)
        merged, kept = ap.merge_revised_pages(self.DRAFT, f"=== PAGE 1 ===\n{new1}\n\n=== PAGE 2 ===\nΟ Πέτρος.")
        self.assertEqual(kept, [2], "a page cut to a stub is not a revision")
        self.assertIn(self.PAGE2, merged)

    def test_layout_and_duplicate_markers(self):
        draft = "Τίτλος\n\n=== PAGE 1 ===\n\n=== PAGE 1 ===\n" + self.PAGE1 + "\n\n=== PAGE 2 ===\n" + self.PAGE2
        revised = "Τίτλος\n\n=== PAGE 1 ===\n" + self.PAGE1.upper() + "\n\n=== PAGE 2 ===\n" + self.PAGE2
        merged, kept = ap.merge_revised_pages(draft, revised)
        self.assertEqual(kept, [])
        self.assertEqual(merged, draft.replace(self.PAGE1, self.PAGE1.upper()))
        self.assertEqual(ap.collapse_empty_duplicate_markers(draft).count("=== PAGE 1 ==="), 1)


class TestContentsPage(unittest.TestCase):
    TEXT = (
        "=== PAGE 1 ===\nThe Quiet Harbour\n\nAnna Field\n\n"
        "=== PAGE 2 ===\nPrologue\n3\nLow Tide\n5\nHigh Water\n9\nAcknowledgments\n12\n\n"
        "=== PAGE 3 ===\nPrologue\nIt began with a storm that nobody had forecast.\n\n"
        "=== PAGE 4 ===\nLow Tide\nThe boats were late that year, and the nets came back empty.\n\n"
        "=== PAGE 5 ===\nThe harbour master wrote it all down in his book.\n\n"
        "=== PAGE 6 ===\nHigh Water\nWhen the sea finally rose, it rose at night.\n"
    )

    def test_contents_entries_lose_old_numbers_and_name_chapters(self):
        from backend.exporter import _prepare_literature_chapters, _contents_page
        chapters = _prepare_literature_chapters(self.TEXT, default_title="test_book")
        toc = [c for c in chapters if c.get("toc")]
        self.assertEqual(len(toc), 1)
        self.assertEqual(toc[0]["title"], "Contents")
        self.assertEqual(toc[0]["paragraphs"], ["Prologue", "Low Tide", "High Water", "Acknowledgments"])
        titles = [c["title"] for c in chapters]
        self.assertEqual(titles[-3:], ["Prologue", "Low Tide", "High Water"])
        body = " ".join(p for c in chapters for p in c["paragraphs"])
        self.assertNotRegex(body, r"\b(3|5|9|12)\b")
        # prose with a few numbers is no contents page
        self.assertIsNone(_contents_page(["He was born in 1970", "and left in 1988.", "It rained."]))
        self.assertIsNotNone(_contents_page(["Πρόλογος .......... 7", "Μέρος Πρώτο 15", "Επίλογος 230"]))

    def test_literature_pdf_prints_new_page_numbers_and_bookmarks(self):
        import pymupdf
        from backend.exporter import export_text
        with tempfile.TemporaryDirectory() as td:
            path = export_text(self.TEXT, Path(td), "pdf", "test_contents", layout="literature")
            doc = pymupdf.open(path)
            try:
                toc = {title: page for _lvl, title, page in doc.get_toc()}
                self.assertEqual(set(toc) >= {"Contents", "Prologue", "Low Tide", "High Water"}, True, toc)
                lines = [ln.strip() for ln in doc[toc["Contents"] - 1].get_text().splitlines() if ln.strip()]
                for title in ("Prologue", "Low Tide", "High Water"):
                    self.assertIn(str(toc[title]), lines, f"{title} must show its page in this edition")
                self.assertGreater(toc["High Water"], toc["Low Tide"])
            finally:
                doc.close()


if __name__ == "__main__":
    unittest.main()
