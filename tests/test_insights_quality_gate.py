"""
test_insights_quality_gate.py - the Book Insights quality checks never reject a faithful text, and still reject an
invented one.

A text written only from the book can still differ from it on the surface: a Greek name changes its ending with its
case (Νίκος, του Νίκου, τον Νίκο), a number is written with another thousands separator (1,200 / 1.200 / 1 200), the
text is in the other language, a long text names more people. Once the checks rejected such texts: an extended
synopsis of a Greek book failed every time. The stand-in Gemini of the other suites copied the book's own forms, so
it could not show this.

Covers:
* numbers in every thousands style, in the book and in the text, both ways; decimals; invented numbers still caught;
* Greek names in their cases, the book having one form and the text another, both ways; invented names still caught;
* the whole pipeline with a stand-in that writes like a real model (names in other cases, the other number style,
  the top of each length range): every summary and synopsis, Greek and English, from a Greek and an English book,
  read whole or from notes, all succeed; the same with invented names and numbers is rejected, with its reasons;
* the other kinds that check names (one chapter, the story so far, the blurb, the timeline) and the rest, from a
  Greek book in Greek and an English book in English;
* every message any check can produce (read from the code) reaches the reader as a reason, in Greek and English.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import ast
import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import test_book_insights_more as more
except ImportError:
    from tests import test_book_insights_more as more

from backend import book_insights as bi
from backend import insights_more as im

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# One story, as a Greek and an English book, and as a model would retell it
# ---------------------------------------------------------------------------

# The books name their people in one form only (mostly the nominative) and write numbers in their own style
GR_BOOK = [
    "Ο Νίκος Αλεξίου γεννήθηκε στη Ρόδο το 1922 και δούλεψε στο λιμάνι του Πειραιά.",
    "Η Λένα, η αδελφή του, έμενε στη Θεσσαλονίκη, όπου ο άντρας της ο Άρης είχε ένα μαγαζί.",
    "Το 1941 ο Νίκος έχασε τη δουλειά του, όταν έκλεισαν 1.200 θέσεις στο λιμάνι.",
    "Ο Δήμος, ο παλιός του φίλος, έγραψε από την Κρήτη ότι στο Ηράκλειο υπήρχε δουλειά.",
    "Ο εφοπλιστής Αλέξανδρος Παπαδόπουλος αγόρασε το ναυπηγείο για 3.400.000 δραχμές.",
    "Η Ζωή, η κόρη του φίλου του, κρατούσε ημερολόγιο από το 1938 ως το 1946.",
    "Τον χειμώνα απεργούσαν 45.000 εργάτες σε όλη τη χώρα.",
    "Στο τέλος ο Νίκος και η Λένα γύρισαν μαζί στην Αθήνα.",
]
EN_BOOK = [
    "Nikos Alexiou was born on Rhodes in 1922 and worked at the harbour of Piraeus.",
    "Lena, his sister, lived in Thessaloniki, where her husband Aris kept a shop.",
    "In 1941 Nikos lost his job when 1,200 posts at the harbour were closed.",
    "Dimos, his old friend, wrote from Crete that there was work in Heraklion.",
    "The shipowner Alexandros Papadopoulos bought the shipyard for 3,400,000 drachmas.",
    "Zoe, the daughter of his friend, kept a diary from 1938 to 1946.",
    "That winter 45,000 workers went on strike across the country.",
    "In the end Nikos and Lena went back to Athens together.",
]
# Faithful retellings: every fact is the book's, but the names are in other cases (του Νίκου, τον Άρη, του Δήμου,
# της Ζωής, της Λένας) and the numbers in the other language's style or with a space (45 000)
GR_TOLD = [
    "Η ιστορία του Νίκου Αλεξίου ξεκινά στη Ρόδο, όπου γεννιέται το 1922.",
    "Η αδελφή του Νίκου, η Λένα, ζει στη Θεσσαλονίκη μαζί με τον Άρη.",
    "Το 1941 κλείνουν 1.200 θέσεις στο λιμάνι και ο Νίκος μένει χωρίς δουλειά.",
    "Ένα γράμμα του Δήμου από την Κρήτη μιλά για δουλειά στο Ηράκλειο.",
    "Το ναυπηγείο περνά στον Αλέξανδρο Παπαδόπουλο για 3.400.000 δραχμές.",
    "Το ημερολόγιο της Ζωής καλύπτει τα χρόνια από το 1938 ως το 1946.",
    "Η απεργία των 45 000 εργατών σημαδεύει τον χειμώνα.",
    "Η ζωή της Λένας αλλάζει, και στο τέλος επιστρέφει στην Αθήνα μαζί με τον Νίκο.",
]
EN_TOLD = [
    "The story of Nikos Alexiou begins on Rhodes, where he is born in 1922.",
    "Nikos's sister Lena lives in Thessaloniki with Aris.",
    "In 1941 the harbour closes 1,200 posts and Nikos is left without work.",
    "A letter from Dimos on Crete speaks of work in Heraklion.",
    "The shipyard passes to Alexandros Papadopoulos for 3 400 000 drachmas.",
    "Zoe's diary covers the years from 1938 to 1946.",
    "The strike of 45,000 workers marks the winter.",
    "In the end Lena returns to Athens with Nikos.",
]
GR_ONE = ("Ο Νίκος Αλεξίου, που γεννιέται στη Ρόδο το 1922, χάνει τη δουλειά του το 1941, όταν κλείνουν 1.200 θέσεις "
          "στο λιμάνι, και στο τέλος γυρίζει με τη Λένα στην Αθήνα.")
EN_ONE = ("Nikos Alexiou, born on Rhodes in 1922, loses his job in 1941 when 1,200 harbour posts close, and in the "
          "end returns to Athens with his sister Lena.")
# More than any text may hold, even the longest
GR_INVENTED = ("Στην ιστορία μπαίνουν και ο Σταυρίδης, ο Κοβάλσκι, ο Μαυρογένης, ο Τσιτσάνης, ο Ραγκούσης, ο Βλαχάκης, "
               "ο Ζερβός, ο Μπενάκης και ο Καλλέργης, στα χρόνια 1453, 1571, 1669, 1797, 1866 και 1897.")
EN_INVENTED = ("The story also brings in Kowalski, Thorne, Brannagh, Valdez, Hargreave, Pemberton, Ashworth, "
               "Whitlock and Fairbanks, in the years 1453, 1571, 1669, 1797, 1866 and 1897.")
INVENTED_NAME = {"greek": "Κοβάλσκι", "english": "Kowalski"}  # among the first six, which the reason lists


def book(sentences, n_words: int) -> str:
    """Chapters of twelve paragraphs; every paragraph has three of the sentences, so every chapter has all of them."""
    out, words, i = [], 0, 0
    greek = sentences is GR_BOOK
    while words < n_words:
        if i % 12 == 0:
            out.append(f"Κεφάλαιο {i // 12 + 1}" if greek else f"Chapter {i // 12 + 1}")
        para = " ".join(sentences[(i + k) % len(sentences)] for k in range(3))
        out.append(para)
        words += len(para.split())
        i += 1
    return "\n\n".join(out)


def retelling(pool, n_words: int, headings=None) -> str:
    """n_words of the pool (as the checks count them), in paragraphs of four sentences; with headings, a section
    every few paragraphs."""
    sentences, words, i = [], 0, 0
    while words < n_words:
        s = pool[i % len(pool)]
        sentences.append(s)
        words += bi.count_words(s)
        i += 1
    paras = [" ".join(sentences[k:k + 4]) for k in range(0, len(sentences), 4)]
    if not headings:
        return "\n\n".join(paras)
    blocks, per = [], max(1, len(paras) // len(headings))
    for k, p in enumerate(paras):
        if k % per == 0 and k // per < len(headings):
            blocks.append(f"## {headings[k // per]}")
        blocks.append(p)
    return "\n\n".join(blocks)


class FaithfulGemini:
    """Writes like a real model: only the book's facts, but in its own words and forms, at the top of each range."""

    def __init__(self):
        self.mode = "faithful"
        self.calls = 0

    async def __call__(self, content, api_key, system_prompt, session=None, temperature=0.25, exclude_models=None,
                       bypass_cache=False, meta_out=None, cache_gate=None, prefer_models=None):
        sp = system_prompt
        self.calls += 1
        if "research notes" in sp:
            return "- " + " ".join(content.split()[:250])
        if "proofreader" in sp:
            return content
        assert "TASK:" in sp, sp[:200]
        greek = "Modern Greek" in sp
        if "ONE-SENTENCE" in sp:
            text = GR_ONE if greek else EN_ONE
        else:
            hi = int(re.search(r"(\d+)-(\d+) words", sp).group(2))
            heads = None
            if "SYNOPSIS" in sp or "EXTENDED SUMMARY" in sp:
                heads = (["Θέμα και αφετηρία", "Δομή", "Πρόσωπα", "Θέματα", "Κατάληξη"] if greek
                         else ["Subject and premise", "Structure", "Characters", "Themes", "Ending"])
            text = retelling(GR_TOLD if greek else EN_TOLD, hi, heads)
        if self.mode == "invent":
            text += "\n\n" + (GR_INVENTED if greek else EN_INVENTED)
        return text


def run(coro):
    return asyncio.run(coro)


# ===========================================================================
# The checks on their own
# ===========================================================================

class NumberStyleTests(unittest.TestCase):
    @staticmethod
    def styles(n: int):
        s = f"{n:,}"
        return {"plain": str(n), "comma": s, "greek": s.replace(",", "."), "space": s.replace(",", " "),
                "no-break space": s.replace(",", " "), "thin space": s.replace(",", " "),
                "narrow space": s.replace(",", " "), "apostrophe": s.replace(",", "'")}

    def test_a_number_of_the_book_in_any_style(self):
        for n in (150, 1200, 2387, 45000, 3400000, 12500000):
            styles = self.styles(n)
            invented = self.styles(int("9" + str(n)[1:]) if str(n)[0] != "9" else n + 1)
            for book_style, in_book in styles.items():
                source = f"Στο λιμάνι έφτασαν {in_book} άνθρωποι, είπε ο φύλακας. " * 2
                for text_style, in_text in styles.items():
                    with self.subTest(n=n, book=book_style, text=text_style):
                        self.assertEqual(bi._unknown_numbers(f"Έφτασαν {in_text} άνθρωποι.", source), [])
                        if book_style == "space" and text_style == "space":
                            continue  # "1 200" in a book can't be told from "1" and "200": the parts are its own
                        self.assertTrue(bi._unknown_numbers(f"Έφτασαν {invented[text_style]} άνθρωποι.", source),
                                        "a number the book does not have is still caught")

    def test_decimals_dates_and_numbers_side_by_side(self):
        self.assertEqual(bi._unknown_numbers("Διένυσαν 147,5 χιλιόμετρα και 12,75 μίλια.",
                                             "They covered 147.5 kilometres and 12.75 miles."), [])
        self.assertEqual(bi._unknown_numbers("Στις 12.05.1999 κόστιζε 1.234,56 ευρώ.",
                                             "On 12/05/1999 it cost 1,234.56 euro."), [])
        self.assertEqual(bi._unknown_numbers("Το 1922 300 στρατιώτες χάθηκαν.", "In 1922, 300 soldiers were lost."), [])
        self.assertEqual(bi._unknown_numbers("Το 1922 300 στρατιώτες χάθηκαν.", "In 1922 the army lost men."), ["300"])
        self.assertEqual(bi._unknown_numbers("Από το 1940 ως το 1944.", "From 1940 to 1944."), [])


class GreekNameFormTests(unittest.TestCase):
    # a name and its other forms (genitive, accusative, vocative, plural); the accent may move (Αλεξάνδρου)
    FORMS = [
        ("Νίκος", ["Νίκου", "Νίκο", "Νίκε"]), ("Γιώργος", ["Γιώργου", "Γιώργο", "Γιώργη"]), ("Δήμος", ["Δήμου"]),
        ("Αλέξανδρος", ["Αλεξάνδρου", "Αλέξανδρο", "Αλέξανδρε"]), ("Παπαδόπουλος", ["Παπαδόπουλου",
         "Παπαδόπουλοι", "Παπαδόπουλων", "Παπαδόπουλους"]), ("Γιάννης", ["Γιάννη"]), ("Θανάσης", ["Θανάση"]),
        ("Μιχάλης", ["Μιχάλη"]), ("Άρης", ["Άρη"]), ("Χάρης", ["Χάρη"]), ("Πάρης", ["Πάρη"]),
        ("Ιωάννης", ["Ιωάννη", "Ιωάννου"]), ("Σωκράτης", ["Σωκράτη", "Σωκράτους"]),
        ("Περικλής", ["Περικλή", "Περικλέους"]), ("Ηρακλής", ["Ηρακλή", "Ηρακλέους"]),
        ("Λουκάς", ["Λουκά"]), ("Οδυσσέας", ["Οδυσσέα"]), ("Δίας", ["Δία"]), ("Ίων", ["Ίωνα"]),
        ("Μαρία", ["Μαρίας"]), ("Λένα", ["Λένας"]), ("Λία", ["Λίας"]), ("Άννα", ["Άννας"]),
        ("Κατερίνα", ["Κατερίνας"]), ("Ελένη", ["Ελένης"]), ("Νίκη", ["Νίκης"]), ("Ζωή", ["Ζωής"]),
        ("Ηρώ", ["Ηρώς"]), ("Αθήνα", ["Αθήνας"]), ("Θεσσαλονίκη", ["Θεσσαλονίκης"]), ("Κρήτη", ["Κρήτης"]),
        ("Ιθάκη", ["Ιθάκης"]), ("Ευρώπη", ["Ευρώπης"]), ("Ελλάδα", ["Ελλάδας", "Ελλάδος"]),
        ("Πειραιάς", ["Πειραιά"]), ("Ηράκλειο", ["Ηρακλείου"]), ("Ρόδος", ["Ρόδου", "Ρόδο"]), ("Τζον", ["Τζον"]),
    ]

    def test_a_name_of_the_book_in_any_case(self):
        for name, forms in self.FORMS:
            for form in forms:
                for in_book, in_text in ((name, form), (form, name)):
                    with self.subTest(book=in_book, text=in_text):
                        source = f"Στην αρχή ήρθε ο {in_book} και έμεινε. Ύστερα έφυγε ο {in_book} για πάντα."
                        self.assertEqual(bi._unknown_names(f"Η ιστορία δείχνει ότι ο {in_text} έφυγε.", source), [])

    def test_a_name_the_book_does_not_have_is_still_caught(self):
        source = "Στην αρχή ήρθε ο Νίκος με τη Μαρία. Ο Μάρκος έμεινε στην Αθήνα."
        for name in ("Κοβάλσκι", "Σταυρίδης", "Νικολάου", "Μαρκόπουλος", "Αθανασίου"):
            with self.subTest(name=name):
                self.assertEqual(bi._unknown_names(f"Η ιστορία δείχνει ότι ο {name} έφυγε.", source), [name])

    def test_english_possessives(self):
        source = "Nikos waited at the harbour. The Captain left. Lena sailed."
        self.assertEqual(bi._unknown_names("They met Nikos's sister, Lena’s friend and the Captain's men.", source), [])
        self.assertEqual(bi._unknown_names("They met Nikos's sister and Kowalski's men.", source), ["Kowalski's"])


# ===========================================================================
# The whole pipeline
# ===========================================================================

class SummaryPipelineTests(unittest.TestCase):
    """Every summary and synopsis, through generate_insight: what the model wrote is normalised, refined (Greek),
    proofread and checked exactly as for a real book."""

    BOOKS = {
        ("greek", "whole"): book(GR_BOOK, 6000), ("english", "whole"): book(EN_BOOK, 6000),
        ("greek", "notes"): book(GR_BOOK, 20000), ("english", "notes"): book(EN_BOOK, 20000),
    }

    def setUp(self):
        self.fake = FaithfulGemini()
        self.patch = mock.patch("backend.ai_polisher._call_gemini_api", self.fake)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def make(self, text, insight_type, language):
        return run(bi.generate_insight(text, insight_type, language, "fake-key", title="Το λιμάνι",
                                       session=object()))

    def test_the_books(self):
        self.assertLess(len(self.BOOKS[("greek", "whole")]), bi.SINGLE_PASS_CHARS, "read whole")
        self.assertGreater(len(self.BOOKS[("greek", "notes")]), bi.SINGLE_PASS_CHARS, "read from notes")
        self.assertEqual(bi.detect_language(self.BOOKS[("greek", "whole")]), "greek")
        self.assertEqual(bi.detect_language(self.BOOKS[("english", "whole")]), "english")
        # the retellings really do differ from the book where the checks once failed
        gr_book, gr_told = " ".join(GR_BOOK), " ".join(GR_TOLD)
        for form in ("Νίκου", "Άρη", "Δήμου", "Ζωής", "Λένας", "45 000"):
            self.assertRegex(gr_told, rf"(?<!\w){form}(?!\w)")
            self.assertNotRegex(gr_book, rf"(?<!\w){form}(?!\w)")

    def test_a_faithful_text_is_never_rejected(self):
        for (source_lang, read), text in self.BOOKS.items():
            for insight_type in bi.INSIGHT_TYPES:
                for language in bi.OUTPUT_LANGUAGES:
                    with self.subTest(book=source_lang, read=read, type=insight_type, language=language):
                        try:
                            rec = self.make(text, insight_type, language)
                        except bi.InsightsError as e:
                            self.fail(f"rejected: {e.detail} -> {bi.rejection_reasons(e.detail)}")
                        self.assertEqual(rec["from_notes"], read == "notes")
                        self.assertEqual(rec["language"], language)
                        lo, hi = rec["target_words"]
                        if insight_type != "one_sentence":
                            self.assertGreaterEqual(rec["word_count"], hi * 0.9, "the top of its range")

    def test_an_invented_text_is_still_rejected_and_says_why(self):
        self.fake.mode = "invent"
        for source_lang in ("greek", "english"):
            text = self.BOOKS[(source_lang, "whole")]
            for insight_type in ("short_summary", "extended_synopsis"):
                for language in bi.OUTPUT_LANGUAGES:
                    with self.subTest(book=source_lang, type=insight_type, language=language):
                        with self.assertRaises(bi.InsightsError) as ctx:
                            self.make(text, insight_type, language)
                        self.assertEqual(ctx.exception.code, "ai_output_rejected")
                        reasons = ctx.exception.to_dict()["reasons"]
                        self.assertIn("Αριθμοί που δεν υπάρχουν στο βιβλίο: 1453, 1571, 1669, 1797, 1866.", reasons)
                        if source_lang == language:  # names are checked in the book's own language
                            self.assertTrue(any(r.startswith("Ονόματα που δεν υπάρχουν στο βιβλίο:")
                                                and INVENTED_NAME[language] in r for r in reasons), reasons)


class FaithfulMoreGemini(more.FakeGemini):
    """The other suite's stand-in, its texts written like a real model's (see GR_TOLD / EN_TOLD)."""

    def lines(self, greek: bool, n: int) -> str:
        pool = GR_TOLD if greek else EN_TOLD
        return " ".join(pool[i % len(pool)] for i in range(n))


class MoreKindsTests(unittest.TestCase):
    """The kinds that check names against the book (one chapter, the story so far, the blurb, the timeline) and the
    rest, in the book's own language, where the name check applies."""

    KINDS = [("chapter", {"chapter": 2}), ("recap", {"until": 2}), ("blurb", {}), ("timeline", {}),
             ("chapter_summaries", {}), ("study_guide", {})]

    def setUp(self):
        self.fake = FaithfulMoreGemini()
        self.patch = mock.patch("backend.ai_polisher._call_gemini_api", self.fake)
        self.patch.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_a_faithful_text_is_never_rejected(self):
        for language, sentences in (("greek", GR_BOOK), ("english", EN_BOOK)):
            path = self.dir / f"{language}.txt"
            path.write_text(book(sentences, 4000), encoding="utf-8")
            for kind, extra in self.KINDS:
                with self.subTest(language=language, kind=kind):
                    self.fake.reset()
                    out = self.dir / f"out-{language}-{kind}"
                    out.mkdir()
                    try:
                        rec = run(im.generate_extra(str(path), "txt", kind, language, "fake-key", title="Το λιμάνι",
                                                    job_output_dir=out, **extra))
                    except bi.InsightsError as e:
                        self.fail(f"rejected: {e.detail} -> {bi.rejection_reasons(e.detail)}")
                    self.assertEqual(rec["language"], language)
                    self.assertTrue(rec["text"].strip())


# ===========================================================================
# Every rejection says why, in Greek and in English
# ===========================================================================

def _render(node) -> list:
    """The texts an expression can be: a string, an f-string (placeholders as 12, or 7%), or a choice of two."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        out = ""
        for part in node.values:
            if isinstance(part, ast.Constant):
                out += str(part.value)
            else:
                spec = ast.unparse(part.format_spec) if part.format_spec is not None else ""
                out += "7%" if "%" in spec else "12"
        return [out]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [a + b for a in _render(node.left) for b in _render(node.right)]
    if isinstance(node, ast.IfExp):
        return _render(node.body) + _render(node.orelse)
    return []


def rejection_messages() -> list:
    """Every message a check appends to `critical` or `problems`, returns from language_problems / validate_output,
    or raises as the detail of ai_output_rejected, in book_insights.py and insights_more.py."""
    found = set()
    for path in (ROOT / "backend" / "book_insights.py", ROOT / "backend" / "insights_more.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                values = []
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id in ("critical", "problems")):
                    values = node.args[:1]
                elif (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "InsightsError"
                      and len(node.args) > 1 and getattr(node.args[0], "value", None) == "ai_output_rejected"):
                    values = node.args[1:2]
                elif isinstance(node, ast.Return) and fn.name in ("language_problems", "validate_output") and node.value:
                    values = [n for n in ast.walk(node.value) if isinstance(n, ast.List)]
                elif isinstance(node, (ast.Assign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if any(isinstance(t, ast.Name) and t.id in ("critical", "problems") for t in targets):
                        values = [n for n in ast.walk(node.value) if isinstance(n, ast.List)]
                for v in values:
                    for item in (v.elts if isinstance(v, ast.List) else [v]):
                        found.update(_render(item))
    return sorted(found)


class RejectionReasonTests(unittest.TestCase):
    def test_every_rejection_says_why(self):
        messages = rejection_messages()
        self.assertGreater(len(messages), 25, "the checks' messages are found in the code")
        for must in ("output too short: 12 words (target 12-12)", "numbers not found in the source: 12",
                     "names not found in the book: 12", "the text is not in Greek", "no events found",
                     "too similar to the existing synopsis", "prompt text leaked"):
            self.assertIn(must, messages)
        for message in messages:
            with self.subTest(message=message):
                self.assertEqual(len(bi.rejection_reasons(message)), 1,
                                 "a check without a reason: add it to _REASON_RULES and its English to i18n.js")

    def test_every_reason_reads_in_english_too(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js not available in PATH")
        reasons = sorted({r for m in rejection_messages() for r in bi.rejection_reasons(m)}) + ["Αιτία:"]
        harness = r"""
const fs = require('fs'); const vm = require('vm');
const ctx = vm.createContext({ console, MutationObserver: class { observe() {} }, CustomEvent: class {},
  localStorage: { getItem: () => null, setItem() {} }, navigator: { language: 'el-GR' },
  document: { documentElement: {}, addEventListener() {}, querySelectorAll: () => [], dispatchEvent() {} },
  window: { alert() {}, confirm() { return true; }, prompt() {} }, NodeFilter: {} });
vm.runInContext(fs.readFileSync('frontend/i18n.js', 'utf8') + ';globalThis.I18N = I18N;', ctx);
const texts = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(texts.map((t) => [ctx.I18N.text(t, 'en'), ctx.I18N.text(ctx.I18N.text(t, 'en'), 'el')])));
"""
        res = subprocess.run([node, "-e", harness], input=json.dumps(reasons), capture_output=True, text=True,
                             encoding="utf-8", timeout=30, cwd=str(ROOT))
        self.assertEqual(res.returncode, 0, res.stderr)
        for greek, (english, back) in zip(reasons, json.loads(res.stdout)):
            with self.subTest(reason=greek):
                self.assertFalse(re.search(r"[Ͱ-Ͽ]", english), f"no English pair in i18n.js: {greek} -> {english}")
                self.assertEqual(back, greek)


if __name__ == "__main__":
    unittest.main()
