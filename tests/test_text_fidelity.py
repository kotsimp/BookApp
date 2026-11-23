"""
test_text_fidelity.py - Clean-up passes never change correct text, and AI boundary de-duplication never deletes text
the book really repeats.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import ai_polisher, exporter, output_refiner, typography
from backend.async_utils import gather_or_cancel

GREEK = (
    "Η μητέρα μου μου είπε να γυρίσω νωρίς.",
    "Οι γονείς τους τους περίμεναν στον σταθμό.",
    "Η αδελφή της της έδωσε το βιβλίο.",
    "Ο γιος του του έγραψε από το μέτωπο.",
    "Πες το το βράδυ στον παππού.",
    "Πάρ' την την Κυριακή τηλέφωνο.",
    "Μπήκαν ένα ένα στην αίθουσα.",
    "Ήξερε ότι ότι κι αν γίνει θα έρθει.",
    "Η μέθοδος iterrows διατρέχει τις γραμμές του πίνακα.",
    "Το βιβλίο της Gang of Four περιγράφει πρότυπα σχεδίασης.",
    "Στα ισπανικά η λέξη podría σημαίνει «θα μπορούσε».",
    "Η βιετναμέζικη λέξη lần σημαίνει φορά.",
    "Το κεφάλαιο ήταν δύσκολο και ήθελα να το λείψω αυτό.",
    "Ο άνθρωπος της κάψουλας γύρισε από το διάστημα.",
    "Είδε τον σκιασμένο πάνθηρα ανάμεσα στα δέντρα.",
    "Την έπιασε από το χέρι αφήνοντάς τη μόνη.",
    "Τις κοίταξε δείχνοντάς τες στον φύλακα.",
    "Η πρωτεΐνη TNFα ρυθμίζει τον παράγοντα NFκB.",
    "Η αντίσταση είναι 10 kΩ και η μόνωση 5 MΩ.",
    "Η μεταβολή ΔΔCt υπολογίζεται για κάθε γονίδιο.",
    "Το σ είναι η τυπική απόκλιση του δείγματος.",
    "Χρησιμοποιούμε το .NET για την εφαρμογή.",
    "Η σελίδα www.site.gr/book?id=12 έχει το βιβλίο.",
    "Στη C# ο τύπος int?[] δέχεται κενές τιμές.",
    "Η συνθήκη a<b και c>d ισχύει πάντα.",
    "Ψάχνουμε για σίγουρα αποτελέσματα.",
    "Η απάντηση δόθηκε στη σελίδα http://www.rifters.com/blindsight/notes.htm.",
    "Στην περίπτωση δε αυτή ισχύει εξαίρεση.",
)
ENGLISH = (
    "He said that that was the last train.",
    "She had had enough of the rain.",
    "They moved in in the spring.",
    "Who he is is none of your business.",
    "Log on on Monday morning.",
    "The method iterrows walks over the rows of a table.",
    "In Spanish the word podría means could.",
    "The protein TNFα regulates the factor NFκB.",
    "The test a<b and c>d is always true.",
)


class TestCleanersKeepCorrectText(unittest.TestCase):
    def test_greek(self):
        passes = {
            "typography": lambda s: typography.format_greek_typography(s, enable_dialogue_dashes=False),
            "AI sanitiser": ai_polisher.sanitize_ai_output,
            "refiner": lambda s: output_refiner.refine_text_content(s, "greek")[0],
            "export": exporter._sanitize_pua,
        }
        for text in GREEK:
            for name, clean in passes.items():
                self.assertEqual(clean(text), text, name)

    def test_english(self):
        passes = {
            "AI sanitiser": ai_polisher.sanitize_ai_output,
            "refiner": lambda s: output_refiner.refine_text_content(s, "english", "greek")[0],
            "export": exporter._sanitize_pua,
        }
        for text in ENGLISH:
            for name, clean in passes.items():
                self.assertEqual(clean(text), text, name)

    def test_what_the_book_contains_is_content(self):
        for source, output in (
            ("The <p> element starts a paragraph.", "Το στοιχείο <p> δηλώνει παράγραφο."),
            ("[Note: renamed in 1950.]", "[Σημείωση: μετονομάστηκε το 1950.]"),
            ("[Σημείωση: μετονομάστηκε το 1950.]", "[Note: renamed in 1950.]"),
            ("The token <eos> ends a sequence.", "Το σύμβολο <eos> τερματίζει μια ακολουθία."),
        ):
            self.assertEqual(ai_polisher.sanitize_ai_output(output, source_text=source), output)
        # leaks are still removed
        self.assertEqual(ai_polisher.sanitize_ai_output("Ο <i>Θησέας</i> ήρθε.", source_text="Theseus came."), "Ο Θησέας ήρθε.")
        self.assertEqual(ai_polisher.sanitize_ai_output("Ήρθε. [Σημείωση επιμελητή: έλεγχος]", source_text="He came."), "Ήρθε.")

    def test_real_corruption_is_still_repaired(self):
        self.assertEqual(typography.clean_script_glitches_and_foreign_artifacts("kαι Aυτό"), "και Αυτό")
        self.assertTrue(typography.is_corrupt_greek_word("ΣΥΡIAKΕΣ"))

    def test_heading_case_is_never_half_converted(self):
        for title, body in (("Το Σιωπηλό Λιμάνι", "Έφτασαν στο λιμάνι το βράδυ."),
                            ("Το Μεγάλο Φαράγγι", "Ήταν ένα μεγάλο ταξίδι."),
                            ("Στη Νέα Υόρκη", "Έμαθε τα νέα το πρωί. Είχε νέα δουλειά.")):
            text = f"{title}\n\n{body}"
            self.assertEqual(output_refiner.greek_sentence_case_headings(text), text)
        text = "Το Σιωπηλό Λιμάνι\n\nΤο σιωπηλό λιμάνι κοιμόταν."
        self.assertEqual(output_refiner.greek_sentence_case_headings(text).split("\n")[0], "Το σιωπηλό λιμάνι")

    def test_heading_keeps_names(self):
        text = "Ο Πέτρος και η Ελπίδα\n\nΕίχε μια ελπίδα ακόμα. Τότε η Ελπίδα έφυγε με τον Πέτρο."
        self.assertEqual(output_refiner.greek_sentence_case_headings(text), text)


def echo(prompt, *_a, **_k):
    body = re.search(r"<(DRAFT_TO_POLISH|TEXT_TO_POLISH)>\n(.*)\n</\1>", prompt, re.S)
    return body.group(2) if body else ""


class TestNoParagraphLoss(unittest.TestCase):
    CLAUSES = [f"Article Mark{i}. The tenant shall pay the fee number {i} to the landlord on the first working day "
               f"of each calendar month." for i in range(1, 181)]

    def polish(self, text):
        with mock.patch.object(ai_polisher, "_call_gemini_api", new=mock.AsyncMock(side_effect=echo)):
            return asyncio.run(ai_polisher.polish_text_with_gemini(
                text, api_key="AIzaFake-not-real", style="formal", target_lang="english"))

    def test_repetitive_book_unpaginated(self):
        self.assertEqual(re.findall(r"Mark(\d+)\.", self.polish("\n\n".join(self.CLAUSES))),
                         [str(i) for i in range(1, 181)])

    def test_repetitive_book_paginated(self):
        pages = "\n\n".join(f"=== PAGE {n // 6 + 1} ===\n\n" + "\n\n".join(self.CLAUSES[n:n + 6]) for n in range(0, 180, 6))
        self.assertEqual(re.findall(r"Mark(\d+)\.", self.polish(pages)), [str(i) for i in range(1, 181)])

    def test_a_real_echo_is_still_removed(self):
        before = "The captain studied the frozen chart of the northern sea for a very long while."
        after = "Nobody on the bridge dared to ask what the pale marks near the islands meant."
        dedup = ai_polisher._deduplicate_batch_boundary
        self.assertEqual(dedup(before, f"{before}\n\n{after}", source_prev=before, source_curr=after), after)
        self.assertEqual(dedup(before, before, source_prev=before, source_curr=before), before, "a repeated refrain")


class TestWorkersDoNotOutliveAFailure(unittest.TestCase):
    def test_gather_or_cancel(self):
        finished = []

        async def fail():
            raise RuntimeError("quota")

        async def slow():
            await asyncio.sleep(0.2)
            finished.append(True)

        async def run():
            with self.assertRaises(RuntimeError):
                await gather_or_cancel([fail(), slow()])
            await asyncio.sleep(0.3)

        asyncio.run(run())
        self.assertEqual(finished, [])


class TestGlossaryInTranslations(unittest.TestCase):
    TERMS = {"kernel": "πυρήνας λειτουργικού συστήματος (kernel)", "backup": "αντίγραφο ασφαλείας (backup)",
             "common sense": "κοινή λογική", "out of the blue": "εντελώς ξαφνικά", "break the ice": "σπάω τον πάγο",
             "artificial intelligence": "τεχνητή νοημοσύνη", "intelligence": "νοημοσύνη", "Frodo": "Φρόντο"}

    def apply(self, text):
        from backend import glossary
        with mock.patch.object(glossary, "load_glossary", return_value=dict(self.TERMS)):
            once = glossary.apply_glossary(text, "greek", translated=True)
            self.assertEqual(glossary.apply_glossary(once, "greek", translated=True), once, "idempotent")
        return once

    def test_links_titles_quotations_and_code_are_untouched(self):
        for text in ("Δείτε https://kernel.org/doc για λεπτομέρειες.", "Γράψτε στο backup@example.com σήμερα.",
                     "Τρέξτε το kernel.py και το /etc/backup τώρα.", "Εκτελέστε `sudo backup` τώρα.",
                     "Το βιβλίο «Common Sense» του Πέιν.", "Το έργο Common Sense του Πέιν.",
                     "Είπε: «It came out of the blue».", "Το τραγούδι «Break the Ice» ακουγόταν.",
                     "It came out of the blue, he said.", "Ο Linux kernel είναι γνωστός."):
            self.assertEqual(self.apply(text), text)

    def test_a_term_is_explained_without_breaking_the_grammar(self):
        self.assertEqual(self.apply("Άλλαξε το kernel του συστήματος. Η απόδοση του kernel ανέβηκε."),
                         "Άλλαξε το kernel (πυρήνας λειτουργικού συστήματος) του συστήματος. Η απόδοση του kernel ανέβηκε.")
        self.assertEqual(self.apply("Η αρχή της artificial intelligence είναι παλιά."),
                         "Η αρχή της artificial intelligence (τεχνητή νοημοσύνη) είναι παλιά.")

    def test_a_word_document_explains_a_term_once(self):
        import tempfile

        import docx
        from backend import format_preserver, glossary

        greek = [f"Στη γραμμή {i} άλλαξε πάλι το kernel του συστήματος." for i in range(6)]

        async def translate(units):
            return greek[: len(units)]

        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td, "in.docx"), Path(td, "out.docx")
            document = docx.Document()
            for i in range(6):
                document.add_paragraph(f"On line {i} the kernel of the system changed again.")
            document.save(str(src))
            with mock.patch.object(glossary, "load_glossary", return_value=dict(self.TERMS)):
                text = asyncio.run(format_preserver.translate_docx_in_place(
                    str(src), str(out), "english", "greek", segment_translator=translate))
        self.assertEqual(text.count("(πυρήνας λειτουργικού συστήματος)"), 1, text)

    def test_alone_on_a_line_and_names_are_replaced(self):
        self.assertEqual(self.apply("2. Common sense"), "2. Κοινή λογική")
        self.assertEqual(self.apply("Ο Frodo έφυγε."), "Ο Φρόντο έφυγε.")


if __name__ == "__main__":
    unittest.main()
