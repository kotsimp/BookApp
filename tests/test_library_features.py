"""
tests/test_library_features.py - The user's library: the names a translation used, what the Glossary learns, series,
the EPUB's Characters page, reading-position sync (KOReader / Readest) and backups.

1. Names: the dossier's lines, the names the translation really writes, names written another way in the editor, the
   register kept with the book while the translation runs.
2. The Glossary learns: suggestions, the Glossary's own spelling, ordinary words, dismissed ones, "accept all".
3. Series: the order of the books, the names of the books before (the nearest wins), the run's Glossary overlay (the
   user's Glossary wins), the AI's register brought in line.
4. The Characters page: after the cover and contents, in the spine, nav and NCX; the translation's spelling and the
   first description; escaped; the copy follows the option, the list and the names.
5. Reading sync: KOReader's fingerprint, sync passwords (only a hash kept), positions per book, the /kosync server.
6. Backups: one user's books in a ZIP; restored under a new id; refused when it is no backup, holds a path out of a
   book's folders or does not fit on the disk.
7. The endpoints, against the sandbox server.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
import hashlib
import io
import json
import os
import re
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

from backend import backup, book_names, epub_extras, glossary, glossary_learning, reading_sync, series

import test_bilingual_opds_readalong as opds  # its translated test book (its test classes are not collected here)

API = "http://127.0.0.1:8000/api"
ROOT = "http://127.0.0.1:8000"

DOSSIER = """(Α) ΜΗΤΡΩΟ ΟΝΟΜΑΤΩΝ & ΟΡΟΛΟΓΙΑΣ
- Keeton -> Κίτον (αρσενικό: ο Κίτον)
- **Theseus** -> Θησέας (αρσενικό: ο Θησέας, το πλοίο)
- Susan James -> Σούζαν Τζέιμς (θηλυκό: η Σούζαν)
- Rorschach -> Ρόρσαχ (ουδέτερο)
- Will -> Γουίλ (αρσενικό)
- Good morning, sir -> Καλημέρα, κύριε
- Narrative tense -> past
(Β) ΦΥΛΛΟ ΥΦΟΥΣ
- Αφήγηση σε τρίτο πρόσωπο, αόριστος.
"""
ORIGINAL = ("=== PAGE 1 ===\nKeeton looked at the Theseus. Susan James waved at him. Will had to wait.\n\n"
            "=== PAGE 2 ===\nKeeton said he will come back. The Theseus sailed at dawn; Susan James stayed.")
TRANSLATED = ("=== PAGE 1 ===\nΟ Κίτον κοίταξε τον Θησέα. Η Σούζαν Τζέιμς του κούνησε το χέρι. Ο Γουίλ έπρεπε να "
              "περιμένει.\n\n=== PAGE 2 ===\nΟ Κίτον είπε πως θα γυρίσει. Ο Θησέας σάλπαρε την αυγή· η Σούζαν "
              "Τζέιμς έμεινε.")


def _http(method, url, data=None, headers=None, raw=None):
    """(status, headers, body) of a request, also for an error status."""
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    hdrs = dict(headers or {})
    if data is not None and raw is None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _json(method, url, data=None, headers=None, raw=None):
    status, _, body = _http(method, url, data, headers, raw)
    try:
        return status, json.loads(body.decode("utf-8") or "null")
    except ValueError:
        return status, body


def koreader_fingerprint(data: bytes) -> str:
    """KOReader's own partial MD5, written out again: 1 KB at 0, then at 1024 * 4^i."""
    md5 = hashlib.md5()
    for i in range(-1, 11):
        offset = 0 if i < 0 else 1024 * 4 ** i
        if offset >= len(data):
            break
        md5.update(data[offset:offset + 1024])
    return md5.hexdigest()


class _TempStores(unittest.TestCase):
    """Each module's store and the Glossary in a folder of their own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(series, "STORE", self.dir / "series.json"),
            mock.patch.object(glossary_learning, "STORE", self.dir / "suggestions.json"),
            mock.patch.object(reading_sync, "STORE", self.dir / "reading_sync.json"),
            mock.patch.object(glossary, "CONFIG_DIR", self.dir / "config"),
            mock.patch.object(glossary, "GLOSSARY_FILE", self.dir / "config" / "glossary.json"),
        ]
        for p in self.patches:
            p.start()
        reading_sync._FINGERPRINTS.clear()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def book(self, name: str, translated: str = TRANSLATED, original: str = ORIGINAL, dossier: str = DOSSIER) -> Path:
        out = self.dir / "outputs" / name
        out.mkdir(parents=True)
        (out / "book_original.txt").write_text(original, encoding="utf-8")
        (out / "book_translated_greek.txt").write_text(translated, encoding="utf-8")
        if dossier:
            book_names.record_dossier(dossier, out)
        return out


# ---------------------------------------------------------------------------
# 1. Names
# ---------------------------------------------------------------------------

class NamesTests(_TempStores):
    def test_the_dossier_lines(self):
        pairs = book_names.parse_dossier(DOSSIER)
        self.assertEqual(pairs[:5], [("Keeton", "Κίτον"), ("Theseus", "Θησέας"), ("Susan James", "Σούζαν Τζέιμς"),
                                     ("Rorschach", "Ρόρσαχ"), ("Will", "Γουίλ")], "notes and markup are left out")
        self.assertNotIn("Good morning, sir", dict(pairs), "a phrase is no name")
        self.assertFalse(any("Αφήγηση" in s for s, _ in pairs), "the style sheet is no name")

    def test_the_names_the_translation_writes(self):
        found = dict(book_names.names_used(DOSSIER, ORIGINAL, TRANSLATED, "greek"))
        self.assertEqual(found.get("Theseus"), "Θησέας", "found in another case (τον Θησέα)")
        self.assertIn("Susan James", found)
        self.assertNotIn("Rorschach", found, "a name the original does not have")
        self.assertNotIn("Narrative tense", found, "not Greek: no rendering")
        other = TRANSLATED.replace("Κίτον", "Κήτον")
        self.assertNotIn("Keeton", dict(book_names.names_used(DOSSIER, ORIGINAL, other, "greek")),
                         "a spelling the translation does not use")
        # a live run: the register also held fixed phrases and objects, which are no names to carry on
        noisy = DOSSIER + ("- In the cold rain -> Στην κρύα βροχή\n- and nobody said a word -> και κανείς δεν μίλησε\n"
                           "- lantern -> φανάρι\n- old -> γέρο-\n- the Weave -> η Ύφανση\n- Isle of Skye -> Νήσος Σκάι\n")
        orig = ORIGINAL + " In the cold rain, and nobody said a word, the lantern of old Keeton, the Weave, Isle of Skye."
        tr = TRANSLATED + " Στην κρύα βροχή και κανείς δεν μίλησε· το φανάρι του γέρο-Κίτον, η Ύφανση, Νήσος Σκάι."
        found = dict(book_names.names_used(noisy, orig, tr, "greek"))
        for phrase in ("In the cold rain", "and nobody said a word", "lantern", "old"):
            self.assertNotIn(phrase, found)
        self.assertEqual((found["the Weave"], found["Isle of Skye"]), ("η Ύφανση", "Νήσος Σκάι"), "small words allowed")
        # a translation into English: the register runs Greek -> English
        found = book_names.names_used("- Νίκος -> Nikos (male)\n- Ελένη -> Eleni", "Ο Νίκος και η Ελένη.",
                                      "Nikos and Eleni.", "english")
        self.assertEqual(found, [("Νίκος", "Nikos"), ("Ελένη", "Eleni")])
        self.assertEqual(book_names.english_greek("Νίκος", "Nikos", "english"), ("Nikos", "Νίκος"))

    def test_a_name_written_another_way_everywhere(self):
        names = {"Keeton": "Κίτον", "Theseus": "Θησέας", "Susan James": "Σούζαν Τζέιμς"}
        new = TRANSLATED.replace("Κίτον", "Κήτον").replace("Θησέα", "Θισέα")  # Θησέας too: "Θησέα" is in it
        changes = book_names.renamed_in_edit(TRANSLATED, new, names)
        self.assertIn(("Keeton", "Κίτον", "Κήτον"), changes)
        self.assertIn(("Theseus", "Θησέας", "Θισέας"), changes, "the nominative of the new spelling")
        once = TRANSLATED.replace("Κίτον", "Κήτον", 1)
        self.assertEqual(book_names.renamed_in_edit(TRANSLATED, once, names), [], "one place only: a local fix")
        reworded = TRANSLATED.replace("σάλπαρε", "έφυγε")
        self.assertEqual(book_names.renamed_in_edit(TRANSLATED, reworded, names), [])
        self.assertEqual(book_names.renamed_in_edit(TRANSLATED, TRANSLATED, names), [])

    def test_the_names_list_of_a_book(self):
        out = self.book("b1")
        data = book_names.refresh(out, TRANSLATED, "english", "greek")
        self.assertEqual({n["source"]: n["target"] for n in data["names"]}.get("Keeton"), "Κίτον")
        new = TRANSLATED.replace("Κίτον", "Κήτον")
        self.assertEqual(book_names.learn_from_edit(out, TRANSLATED, new, "english", "greek"),
                         [("Keeton", "Κίτον", "Κήτον")])
        book_names.refresh(out, new, "english", "greek")  # translated again: the user's spelling stays
        names = {n["source"]: n for n in book_names.load(out)["names"]}
        self.assertEqual((names["Keeton"]["target"], names["Keeton"]["origin"]), ("Κήτον", "edit"))
        book_names.refresh(out, "Keeton and Theseus.", "greek", "english")  # into another language: afresh
        self.assertNotIn("Keeton", book_names.names_map(out))

    def test_the_register_is_kept_while_the_translation_runs(self):
        out = self.dir / "job"
        book_names.record_dossier("- A -> Α")  # no translation running: nowhere to keep it
        self.assertFalse(out.exists())
        token = book_names.begin_job(out)
        try:
            book_names.record_dossier(DOSSIER)
        finally:
            book_names.end_job(token)
        self.assertIn("Keeton", book_names.saved_dossier(out))
        (out / ".direct_ai_checkpoint.json").write_text(json.dumps({"entity_dossier": "- Bates -> Μπέιτς"}),
                                                       encoding="utf-8")
        self.assertIn("Μπέιτς", book_names.saved_dossier(out), "a run that stopped: its checkpoint")


# ---------------------------------------------------------------------------
# 2. The Glossary learns
# ---------------------------------------------------------------------------

class GlossaryLearningTests(_TempStores):
    def test_suggestions_after_a_translation(self):
        glossary.set_term("Susan James", "Σούζαν Τζαίημς", "general")   # the Glossary writes her another way
        glossary.set_term("Theseus", "Θησέας", "general")               # already as the book has it
        out = self.book("b1")
        glossary_learning.learn_from_translation("u1", "job-1", "Blindsight", out, TRANSLATED, "english", "greek")
        items = {s["source"]: s for s in glossary_learning.listing("u1")}
        self.assertEqual(items["Keeton"]["target"], "Κίτον")
        self.assertEqual(items["Keeton"]["books"], [{"job_id": "job-1", "title": "Blindsight"}])
        self.assertNotIn("Theseus", items, "the Glossary already writes it so")
        self.assertEqual(items["Susan James"]["glossary"], "Σούζαν Τζαίημς")
        self.assertTrue(items["Will"]["ordinary_word"], "the book also has 'will'")
        self.assertFalse(items["Keeton"]["ordinary_word"])
        self.assertEqual(glossary_learning.listing("u2"), [], "each user their own")
        added = glossary_learning.accept("u1", None)
        self.assertEqual(added, [("Keeton", "Κίτον")], "accept all: not the ones with a warning")
        self.assertEqual(glossary.load_glossary(category="general")["Keeton"], "Κίτον")
        left = {s["source"] for s in glossary_learning.listing("u1")}
        self.assertEqual(left, {"Susan James", "Will"})
        self.assertEqual(glossary_learning.accept("u1", ["will"]), [("Will", "Γουίλ")], "one by one, any case")

    def test_dismissed_ones_are_not_offered_again(self):
        glossary_learning.add("u1", [("Keeton", "Κίτον", "translation")], "j1", "One")
        self.assertEqual(glossary_learning.dismiss("u1", ["Keeton"]), 1)
        glossary_learning.add("u1", [("Keeton", "Κίτον", "translation")], "j2", "Two")
        self.assertEqual(glossary_learning.listing("u1"), [])
        glossary_learning.add("u1", [("Keeton", "Κήτον", "translation")], "j3", "Three")
        self.assertEqual([s["target"] for s in glossary_learning.listing("u1")], ["Κήτον"], "another spelling")

    def test_the_users_correction_comes_first(self):
        out = self.book("b1")
        glossary_learning.learn_from_translation("", "j1", "One", out, TRANSLATED, "english", "greek")
        new = TRANSLATED.replace("Κίτον", "Κήτον")
        changes = glossary_learning.learn_from_edit("", "j1", "One", out, TRANSLATED, new, "english", "greek")
        self.assertEqual(changes, [("Keeton", "Κίτον", "Κήτον")])
        first = glossary_learning.listing("")[0]
        self.assertEqual((first["source"], first["target"], first["origin"]), ("Keeton", "Κήτον", "edit"))
        # a later translation's spelling does not replace the user's
        glossary_learning.add("", [("Keeton", "Κίτον", "translation")], "j2", "Two")
        self.assertEqual({s["source"]: s["target"] for s in glossary_learning.listing("")}["Keeton"], "Κήτον")

    def test_a_deleted_book(self):
        glossary_learning.add("u1", [("Keeton", "Κίτον", "translation"), ("Bates", "Μπέιτς", "translation")], "j1", "One")
        glossary_learning.add("u1", [("Bates", "Μπέιτς", "translation")], "j2", "Two")
        glossary_learning.forget_book("j1")
        items = {s["source"]: s for s in glossary_learning.listing("u1")}
        self.assertNotIn("Keeton", items)
        self.assertEqual(items["Bates"]["books"], [{"job_id": "j2", "title": "Two"}])

    def test_a_comic_offers_names_as_prose_writes_them(self):
        out = self.dir / "comic"
        book_names.save_comic_names(out, {"FRODO": "Φρόντο", "SAM": "ΣΑΜ"}, "english", "greek")
        self.assertEqual(book_names.names_map(out), {"FRODO": "Φρόντο", "SAM": "ΣΑΜ"}, "the series keeps both")
        glossary_learning.learn_from_comic("u1", "c1", "Comic", out, "greek")
        self.assertEqual([(s["source"], s["target"]) for s in glossary_learning.listing("u1")], [("Frodo", "Φρόντο")],
                         "capitals without accents are not offered")


# ---------------------------------------------------------------------------
# 3. Series
# ---------------------------------------------------------------------------

class SeriesTests(_TempStores):
    def test_the_order_of_the_books(self):
        s = series.create("u1", "  The   Expanse ")
        self.assertEqual(s["name"], "The Expanse")
        self.assertEqual(series.create("u1", "the expanse")["id"], s["id"], "one series per name")
        series.place("u1", "b2", s["id"])
        series.place("u1", "b1", s["id"], position=1)
        series.place("u1", "b3", s["id"])
        self.assertEqual(series.list_series("u1")[0]["books"], ["b1", "b2", "b3"])
        other = series.create("u1", "Other")
        series.place("u1", "b2", other["id"])
        self.assertEqual(series.find("b2", "u1")[1], other["id"], "a book is in one series")
        self.assertEqual(series.earlier_books("b3", "u1"), ["b1"])
        series.set_order("u1", s["id"], ["b3", "x", "b1", "b3"])
        listed = {x["id"]: x for x in series.list_series("u1", alive=lambda b: b != "b1")}
        self.assertEqual(listed[s["id"]]["books"], ["b3"], "deleted books are left out")
        self.assertEqual(series.list_series("u2"), [], "each user their own")
        series.forget_book("b3")
        self.assertEqual(series.find("b3"), None)
        series.delete("u1", s["id"])
        self.assertEqual([x["name"] for x in series.list_series("u1")], ["Other"])
        for bad in ("", "x" * 81):
            with self.assertRaises(series.SeriesError):
                series.create("u1", bad)
        with self.assertRaises(series.SeriesError) as ctx:
            series.rename("u1", "0" * 12, "Nope")
        self.assertEqual(ctx.exception.status, 404)

    def test_the_names_of_the_books_before(self):
        s = series.create("", "Firefall")["id"]
        first = self.book("b1")
        book_names.save(first, [{"source": "Keeton", "target": "Κίτον"}, {"source": "Bates", "target": "Μπέιτς"}],
                        "english", "greek")
        second = self.book("b2")
        book_names.save(second, [{"source": "Keeton", "target": "Κήτον", "origin": "edit"}], "english", "greek")
        insights = second / "insights"
        insights.mkdir()
        (insights / "characters_greek.json").write_text(json.dumps({"data": {
            "people": [{"name": "Bates", "name_out": "Μπέητς"}, {"name": "Sascha", "name_out": "Σάσα"}],
            "terms": [{"term": "logbook", "term_out": "ημερολόγιο πλοίου"}]}}), encoding="utf-8")
        greek_to_english = self.book("b3")
        book_names.save(greek_to_english, [{"source": "Νίκος", "target": "Nick"}], "greek", "english")
        for b in ("b1", "b2", "b3", "b4"):
            series.place("", b, s)
        terms = series.series_terms("b4", self.dir / "outputs")
        self.assertEqual(terms["Keeton"], "Κήτον", "the nearest book before wins (here the user's correction)")
        self.assertEqual(terms["Bates"], "Μπέιτς", "a translation's spelling wins over a characters list's")
        self.assertEqual(terms["Sascha"], "Σάσα")
        self.assertNotIn("logbook", terms, "a list's common terms are no names")
        self.assertEqual(terms["Nick"], "Νίκος", "English -> Greek, as the Glossary keeps it")
        self.assertEqual(series.series_terms("b1", self.dir / "outputs"), {}, "the first book has none before it")
        self.assertNotIn("Nick", series.series_terms("b2", self.dir / "outputs"), "only the books before")

    def test_a_translation_run_lends_its_names_to_the_glossary(self):
        glossary.set_term("Keeton", "Κίτον", "literary")
        self.assertNotIn("Bates", glossary.load_glossary(style="literature"))
        token = glossary.use_job_terms({"keeton": "Κήτον", "Bates": "Μπέιτς"})
        try:
            terms = glossary.load_glossary(style="literature")
            self.assertEqual(terms["Bates"], "Μπέιτς")
            self.assertEqual(terms["Keeton"], "Κίτον")
            self.assertNotIn("keeton", terms, "the user's Glossary wins, whatever the capitals")
            self.assertNotIn("Bates", glossary.load_glossary(category="general"), "the Glossary window: its own")
        finally:
            glossary.reset_job_terms(token)
        self.assertNotIn("Bates", glossary.load_glossary(style="literature"), "only while that run lasts")

    def test_the_register_takes_the_glossarys_spelling(self):
        glossary.set_term("Keeton", "Κήτον", "literary")
        aligned = glossary.align_dossier(DOSSIER, "literature", "greek")
        self.assertIn("- Keeton -> Κήτον (αρσενικό: ο Κήτον)", aligned)
        self.assertIn("- **Theseus** -> Θησέας", aligned, "other lines as they were")
        glossary.set_term("Nick", "Νίκος", "literary")
        english = glossary.align_dossier("- Νίκος -> Nikos (male)", "literature", "english")
        self.assertEqual(english, "- Νίκος -> Nick (male)", "into English: by the Greek")


# ---------------------------------------------------------------------------
# 4. The Characters page
# ---------------------------------------------------------------------------

RECORD = {"insight_type": "characters", "language": "greek", "data": {
    "people": [
        {"name": "Keeton", "name_out": "Κήτον", "role": "Ο αφηγητής, που στο τέλος αποδεικνύεται προδότης.",
         "intro": "Ο αφηγητής, γλωσσολόγος του πληρώματος <και> «συνθέτης».", "relations": ""},
        {"name": "Susan James", "name_out": "Σούζαν Τζέιμς", "role": "Γλωσσολόγος με πολλές προσωπικότητες."},
    ],
    "terms": [{"term": "Theseus", "term_out": "Θησέας", "definition": "Το πλοίο της αποστολής.", "intro": ""}],
}}


class CharactersPageTests(_TempStores):
    def setUp(self):
        super().setUp()
        from backend.exporter import export_epub
        self.out = self.dir / "outputs" / "job"
        self.out.mkdir(parents=True)
        from PIL import Image
        cover = io.BytesIO()
        Image.new("RGB", (60, 90), (120, 140, 160)).save(cover, "JPEG")
        self.epub = Path(export_epub("=== PAGE 1 ===\nΚεφάλαιο 1\n\nΟ Κίτον.\n\n=== PAGE 2 ===\nΚεφάλαιο 2\n\nΤέλος.",
                                     self.out / "book_translated_greek.epub", title="Τυφλή όραση",
                                     cover_image=cover.getvalue()))

    def record(self, rec=RECORD):
        (self.out / "insights").mkdir(exist_ok=True)
        (self.out / "insights" / "characters_greek.json").write_text(json.dumps(rec, ensure_ascii=False),
                                                                    encoding="utf-8")

    def test_the_page_after_the_cover_and_contents(self):
        lang, people, terms = "greek", [{"name": "Κήτον", "original": "Keeton", "about": "Α <β> & «γ»."}], []
        made = epub_extras.add_page(self.epub, self.dir / "copy.epub", epub_extras.page_xhtml(lang, people, terms),
                                    "Πρόσωπα")
        with zipfile.ZipFile(made) as z:
            first = z.infolist()[0]
            self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
            container = z.read("META-INF/container.xml").decode()
            opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
            opf = z.read(opf_path).decode()
            spine = re.findall(r'<itemref idref="([^"]+)"', opf)
            self.assertEqual(spine[spine.index(epub_extras.PAGE_ID) - 1], "nav", spine)
            self.assertLess(spine.index("cover"), spine.index(epub_extras.PAGE_ID), "after the cover")
            self.assertTrue(spine[spine.index(epub_extras.PAGE_ID) + 1].startswith("chapter"), "before chapter 1")
            self.assertIn(f'href="{epub_extras.PAGE_FILE}"', opf)
            base = os.path.dirname(opf_path)
            page = z.read(f"{base}/{epub_extras.PAGE_FILE}" if base else epub_extras.PAGE_FILE).decode()
            ET.fromstring(page.split("\n", 2)[2])  # well-formed XHTML (after the XML and DOCTYPE lines)
            self.assertIn("Α &lt;β&gt; &amp; «γ».", page)
            self.assertIn('lang="el"', page)
            nav = z.read(f"{base}/nav.xhtml").decode()
            self.assertRegex(nav, r'<ol[^>]*><li><a href="bookapp-characters.xhtml">Πρόσωπα</a></li>')
            ncx = z.read(f"{base}/toc.ncx").decode()
            self.assertIn(f'<navPoint id="{epub_extras.PAGE_ID}" playOrder="1">', ncx)
            orders = [int(n) for n in re.findall(r'playOrder="(\d+)"', ncx)]
            self.assertEqual(sorted(orders), list(range(1, len(orders) + 1)), "the play order stays a sequence")
            self.assertEqual(z.testzip(), None)
        with self.assertRaises(ValueError):
            epub_extras.add_page(made, self.dir / "twice.epub", "x", "Πρόσωπα")

    def test_the_translations_spelling_and_the_first_description(self):
        self.assertIsNone(epub_extras.entries(self.out, "greek"), "no 👥 list yet")
        self.record()
        book_names.save(self.out, [{"source": "Keeton", "target": "Κίτον"}], "english", "greek")
        lang, people, terms = epub_extras.entries(self.out, "greek")
        self.assertEqual(lang, "greek")
        self.assertEqual(people[0]["name"], "Κίτον", "as the translation writes him")
        self.assertEqual(people[0]["original"], "Keeton")
        self.assertNotIn("προδότης", people[0]["about"], "no later turn of the story")
        self.assertEqual(people[1]["about"], "Γλωσσολόγος με πολλές προσωπικότητες.", "an older list: its role")
        self.assertEqual(terms[0]["about"], "Το πλοίο της αποστολής.")
        self.assertIsNone(epub_extras.entries(self.out, "english"), "the list in the translation's language")

    def test_the_copy_follows_the_option_the_list_and_the_names(self):
        self.record()
        self.assertEqual(epub_extras.served_epub(self.out, self.epub, "greek"), self.epub, "off by default")
        epub_extras.set_options(self.out, True)
        served = epub_extras.served_epub(self.out, self.epub, "greek")
        self.assertEqual(served, self.out / "extras" / self.epub.name)
        self.assertTrue(self.epub.read_bytes() != served.read_bytes(), "a copy: the EPUB itself stays")
        stamp = served.stat().st_mtime
        self.assertEqual(epub_extras.served_epub(self.out, self.epub, "greek").stat().st_mtime, stamp, "made once")
        time.sleep(0.05)
        later = dict(RECORD, data=dict(RECORD["data"], people=RECORD["data"]["people"][:1]))
        self.record(later)
        os.utime(self.out / "insights" / "characters_greek.json", (stamp + 5, stamp + 5))
        served = epub_extras.served_epub(self.out, self.epub, "greek")
        with zipfile.ZipFile(served) as z:
            page = next(z.read(n).decode() for n in z.namelist() if n.endswith(epub_extras.PAGE_FILE))
        self.assertNotIn("Σούζαν", page, "made again from the new list")
        epub_extras.set_options(self.out, False)
        self.assertEqual(epub_extras.served_epub(self.out, self.epub, "greek"), self.epub)


# ---------------------------------------------------------------------------
# 5. Reading sync
# ---------------------------------------------------------------------------

class ReadingSyncTests(_TempStores):
    def test_koreaders_fingerprint(self):
        for size in (300, 5000, 3 * 1024 * 1024 + 17):
            data = os.urandom(size)
            path = self.dir / f"f{size}.epub"
            path.write_bytes(data)
            self.assertEqual(reading_sync.partial_md5(path), koreader_fingerprint(data), size)
        self.assertEqual(reading_sync.name_md5("book.epub"), hashlib.md5(b"book.epub").hexdigest())

    def test_sync_passwords(self):
        self.assertFalse(reading_sync.status("u1")["exists"])
        first = reading_sync.new_password("u1")
        key = hashlib.md5(first.encode()).hexdigest()
        self.assertTrue(reading_sync.check_key("u1", key))
        self.assertTrue(reading_sync.check_key("u1", key.upper()), "as the apps send it")
        self.assertFalse(reading_sync.check_key("u2", key), "another user's")
        self.assertFalse(reading_sync.check_key("u1", hashlib.md5(b"wrong").hexdigest()))
        stored = reading_sync.STORE.read_text(encoding="utf-8")
        self.assertNotIn(first, stored, "the password is not kept")
        self.assertNotIn(key, stored, "nor what the apps send")
        second = reading_sync.new_password("u1")
        self.assertFalse(reading_sync.check_key("u1", key), "a new password stops the old one")
        self.assertTrue(reading_sync.check_key("u1", hashlib.md5(second.encode()).hexdigest()))
        reading_sync.remove_password("u1")
        self.assertFalse(reading_sync.check_key("u1", hashlib.md5(second.encode()).hexdigest()))

    def test_positions_by_book(self):
        path = self.dir / "book.epub"
        path.write_bytes(os.urandom(9000))
        reading_sync.note_file("u1", "job-1", "epub", path, "Book.epub")
        doc = reading_sync.partial_md5(path)
        reading_sync.save_progress("u1", doc, "/body/DocFragment[3]", 0.25, "Kobo", "d1")
        time.sleep(0.05)  # a later position (the clock of some systems moves in 15 ms steps)
        reading_sync.save_progress("u1", reading_sync.name_md5("Book.epub"), "/x", 0.40, "iPhone", "d2")
        reading_sync.save_progress("u1", "f" * 32, "/y", 0.9, "Kobo", "d1")  # a book from elsewhere
        pos = reading_sync.book_positions("u1")
        self.assertEqual(list(pos), ["job-1"])
        self.assertEqual((pos["job-1"]["percentage"], pos["job-1"]["device"]), (0.40, "iPhone"), "the latest")
        self.assertEqual(reading_sync.book_positions("u2"), {})
        self.assertEqual(reading_sync.get_progress("u1", doc)["progress"], "/body/DocFragment[3]")
        exported = reading_sync.export_for("u1", {"job-1"})
        self.assertEqual(len(exported["files"]), 2)
        self.assertEqual(reading_sync.import_for("u9", exported, {"job-1": "job-9"}), 2)
        self.assertEqual(reading_sync.book_positions("u9")["job-9"]["percentage"], 0.40)
        # a live run: another user's copy of the same file (one backup restored by two users) used to take the
        # fingerprint over, and u1's position no longer counted for u1's book
        self.assertEqual(reading_sync.book_positions("u1")["job-1"]["percentage"], 0.40, "u1's book is still u1's")
        reading_sync.forget_book("job-9")
        self.assertEqual(reading_sync.book_positions("u9"), {})
        self.assertIn("job-1", reading_sync.book_positions("u1"))

    def test_the_same_file_for_two_users(self):
        path = self.dir / "shared.epub"
        path.write_bytes(os.urandom(5000))
        reading_sync.note_file("bob", "bob-book", "epub", path)
        reading_sync.note_file("carol", "carol-copy", "epub", path)
        doc = reading_sync.partial_md5(path)
        reading_sync.save_progress("bob", doc, "/a", 0.6, "Kobo", "k")
        reading_sync.save_progress("carol", doc, "/b", 0.1, "Phone", "p")
        self.assertEqual(reading_sync.book_positions("bob"), {"bob-book": mock.ANY})
        self.assertEqual(reading_sync.book_positions("bob")["bob-book"]["percentage"], 0.6)
        self.assertEqual(reading_sync.book_positions("carol")["carol-copy"]["percentage"], 0.1)
        self.assertEqual(reading_sync.export_for("bob", {"carol-copy"})["files"], {}, "not someone else's book")


# ---------------------------------------------------------------------------
# 6. Backups
# ---------------------------------------------------------------------------

def _zip(entries: dict, manifest=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if manifest is not None:
            z.writestr(backup.MANIFEST, json.dumps(manifest))
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


class BackupFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def restore(self, data: bytes):
        path = self.dir / f"{uuid.uuid4().hex}.zip"
        path.write_bytes(data)
        task = {"step": "", "progress": 0}
        with mock.patch.object(backup, "_dirs", return_value=(self.dir / "uploads", self.dir / "outputs")):
            return backup.restore(task, "u1", path)

    def test_files_that_are_no_backup(self):
        jid = str(uuid.uuid4())
        good = {"format": backup.FORMAT, "version": 1, "jobs": []}
        cases = [
            (b"not a zip", "έγκυρο ZIP"),
            (_zip({"a.txt": "x"}), "λείπει το bookapp-backup.json"),
            (_zip({}, {"format": "other"}), "δεν είναι αντίγραφο"),
            (_zip({}, dict(good, version=99)), "νεότερη έκδοση"),
            (_zip({f"jobs/{jid}/output/../../../evil.txt": "x"}, good), "άγνωστη εγγραφή"),
            (_zip({f"jobs/{jid}/output//etc/passwd": "x"}, good), "άγνωστη εγγραφή"),
            (_zip({f"jobs/{jid}/output/a\\..\\b.txt": "x"}, good), "άγνωστη εγγραφή"),
            (_zip({"jobs/not-a-job/output/a.txt": "x"}, good), "άγνωστη εγγραφή"),
            (_zip({f"jobs/{jid}/settings/a.txt": "x"}, good), "άγνωστη εγγραφή"),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(backup.BackupError) as ctx:
                    self.restore(data)
                self.assertIn(message, str(ctx.exception))
        self.assertFalse(any(self.dir.rglob("evil.txt")), "nothing was written")
        self.assertFalse((self.dir / "outputs").exists())

    def test_a_backup_that_does_not_fit_on_the_disk(self):
        jid = str(uuid.uuid4())
        data = _zip({f"jobs/{jid}/output/a.txt": "x" * 1000},
                    {"format": backup.FORMAT, "version": 1, "jobs": [{"job_id": jid, "file_name": "a.pdf"}]})
        free = mock.Mock(free=backup.DISK_MARGIN + 10)
        with mock.patch.object(backup.shutil, "disk_usage", return_value=free):
            with self.assertRaises(backup.BackupError) as ctx:
                self.restore(data)
        self.assertIn("αρκετός χώρος", str(ctx.exception))

    def test_a_record_from_a_backup(self):
        raw = {"job_id": "x", "file_name": "Book.pdf", "file_type": "PDF", "status": "running", "progress": "250",
               "created_at": "bad", "metadata": {"owner": "someone-else", "target_lang": "english",
                                                "reading_direction": "sideways", "ai_polish": 1,
                                                "gemini_usage": "not a dict", "sample_range": [3, 9]}}
        rec = backup._record(raw, "new-id", "u1", "/up/new-id/Book.pdf", None)
        self.assertEqual(rec["job_id"], "new-id")
        self.assertEqual(rec["metadata"]["owner"], "u1", "the user who restores it")
        self.assertEqual((rec["status"], rec["progress"]), ("idle", 100), "a run in the backup is not running here")
        self.assertEqual(rec["file_type"], "pdf")
        self.assertEqual(rec["metadata"]["reading_direction"], "ltr")
        self.assertIsNone(rec["metadata"]["gemini_usage"])
        self.assertEqual(rec["metadata"]["sample_range"], [3, 9])
        self.assertTrue(rec["metadata"]["ai_polish"])


# ---------------------------------------------------------------------------
# 7. The endpoints (the sandbox server)
# ---------------------------------------------------------------------------

def _wait_task(task_id: str, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, task = _json("GET", f"{API}/backup/{task_id}")
        assert status == 200, task
        if task["state"] != "running":
            return task
        time.sleep(0.3)
    raise AssertionError("the task did not finish")


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.job_id = opds._translated_job(cls.dir, "library_book.pdf")
        cls.other_id = opds._translated_job(cls.dir, "library_book_two.pdf")
        from backend.api.common import OUTPUT_DIR
        cls.out = OUTPUT_DIR / cls.job_id

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_series(self):
        status, made = _json("POST", f"{API}/series", {"name": "Lighthouse Saga"})
        self.assertEqual(status, 200, made)
        sid = made["id"]
        self.assertEqual(_json("POST", f"{API}/series", {"name": " "})[0], 400)
        self.assertEqual(_json("PUT", f"{API}/jobs/{self.other_id}/series", {"series_id": sid})[0], 200)
        status, placed = _json("PUT", f"{API}/jobs/{self.job_id}/series", {"series_id": sid, "position": 1})
        self.assertEqual([b["job_id"] for b in placed["series"]["books"]], [self.job_id, self.other_id])
        # the first book's summary is shown with the second
        insights = self.out / "insights"
        insights.mkdir(exist_ok=True)
        (insights / "short_summary_greek.json").write_text(json.dumps({"text": "Ο φύλακας του φάρου."}),
                                                          encoding="utf-8")
        book_names.save(self.out, [{"source": "Keeton", "target": "Κίτον"}], "english", "greek")
        status, mine = _json("GET", f"{API}/jobs/{self.other_id}/series?language=greek")
        self.assertEqual((mine["series"]["name"], mine["position"], mine["books"]), ("Lighthouse Saga", 2, 2))
        self.assertEqual(mine["earlier"][0]["summary"]["text"], "Ο φύλακας του φάρου.")
        self.assertEqual(mine["names_from_earlier"], 1)
        jobs = {j["job_id"]: j for j in _json("GET", f"{API}/jobs")[1]}
        self.assertEqual(jobs[self.other_id]["series"]["position"], 2, "the History shows it")
        status, renamed = _json("PUT", f"{API}/series/{sid}", {"name": "Saga", "books": [self.other_id, self.job_id]})
        self.assertEqual((renamed["name"], [b["job_id"] for b in renamed["books"]]), ("Saga", [self.other_id, self.job_id]))
        self.assertEqual(_json("PUT", f"{API}/series/{sid}", {})[0], 400)
        self.assertIn("Saga", [s["name"] for s in _json("GET", f"{API}/series")[1]["series"]])
        self.assertEqual(_json("PUT", f"{API}/jobs/{self.job_id}/series", {"series_id": None})[1], {"series": None})
        self.assertEqual(_json("DELETE", f"{API}/series/{sid}")[0], 200)
        self.assertEqual(_json("DELETE", f"{API}/series/{sid}")[0], 404)
        self.assertEqual(_json("GET", f"{API}/jobs/{self.other_id}/series")[1]["series"], None)
        (insights / "short_summary_greek.json").unlink()
        (self.out / book_names.FILE_NAME).unlink()

    def test_the_characters_page_in_the_download(self):
        status, opts = _json("GET", f"{API}/jobs/{self.job_id}/epub-options")
        self.assertEqual((status, opts["characters"], opts["available"]), (200, False, False))
        (self.out / "insights").mkdir(exist_ok=True)
        (self.out / "insights" / "characters_greek.json").write_text(json.dumps(RECORD, ensure_ascii=False),
                                                                    encoding="utf-8")
        status, opts = _json("PUT", f"{API}/jobs/{self.job_id}/epub-options", {"characters": True})
        self.assertEqual((opts["characters"], opts["available"], opts["people"], opts["terms"]), (True, True, 2, 1))
        try:
            status, headers, body = _http("GET", f"{API}/download/{self.job_id}?format=epub")
            self.assertEqual(status, 200)
            self.assertIn("library_book", headers.get("content-disposition", ""), "the book's own name")
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                self.assertTrue(any(n.endswith(epub_extras.PAGE_FILE) for n in z.namelist()))
            status, _, bilingual = _http("GET", f"{API}/download/{self.job_id}/bilingual?format=epub")
            with zipfile.ZipFile(io.BytesIO(bilingual)) as z:
                self.assertTrue(any(n.endswith(epub_extras.PAGE_FILE) for n in z.namelist()), "the bilingual too")
        finally:
            _json("PUT", f"{API}/jobs/{self.job_id}/epub-options", {"characters": False})
            (self.out / "insights" / "characters_greek.json").unlink()
        _, _, body = _http("GET", f"{API}/download/{self.job_id}?format=epub")
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertFalse(any(n.endswith(epub_extras.PAGE_FILE) for n in z.namelist()))

    def test_the_sync_server(self):
        status, made = _json("POST", f"{API}/connections/sync")
        self.assertEqual((status, made["path"]), (200, "/kosync"))
        key = hashlib.md5(made["password"].encode()).hexdigest()
        auth = {"x-auth-user": "reader", "x-auth-key": key, "Accept": "application/vnd.koreader.v1+json"}
        self.assertTrue(_json("GET", f"{API}/connections")[1]["sync"]["exists"])
        self.assertEqual(_json("GET", f"{ROOT}/kosync/healthcheck")[1], {"state": "OK"})
        self.assertEqual(_json("GET", f"{ROOT}/kosync/users/auth", headers=auth), (200, {"authorized": "OK"}))
        self.assertEqual(_json("GET", f"{ROOT}/kosync//users/auth", headers=auth)[0], 200, "a server address with '/'")
        wrong = dict(auth, **{"x-auth-key": hashlib.md5(b"nope").hexdigest()})
        self.assertEqual(_json("GET", f"{ROOT}/kosync/users/auth", headers=wrong)[1]["code"], 2001)
        self.assertEqual(_json("POST", f"{ROOT}/kosync/users/create", {"username": "reader", "password": key})[0], 201)
        self.assertEqual(_json("POST", f"{ROOT}/kosync/users/create", {"username": "x", "password": "y"})[0], 402)
        status, headers, _ = _http("OPTIONS", f"{ROOT}/kosync/syncs/progress",
                                   headers={"Origin": "https://web.readest.com", "Access-Control-Request-Method": "PUT"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), "*")
        self.assertIn("x-auth-key", headers.get("access-control-allow-headers", ""))
        # the book downloaded from BookApp, then read in the app
        _, _, epub = _http("GET", f"{API}/download/{self.job_id}?format=epub")
        doc = koreader_fingerprint(epub)
        self.assertEqual(_json("GET", f"{ROOT}/kosync/syncs/progress/{doc}", headers=auth), (200, {}), "nothing yet")
        sent = {"document": doc, "progress": "/body/DocFragment[2]/body/p[3]/text().0", "percentage": 0.5,
                "device": "Kobo Libra", "device_id": "K1"}
        status, put = _json("PUT", f"{ROOT}/kosync/syncs/progress", sent,
                            headers=dict(auth, Origin="tauri://localhost"))
        self.assertEqual((status, put["document"]), (200, doc), "an app's own origin is no website")
        status, got = _json("GET", f"{ROOT}/kosync/syncs/progress/{doc}", headers=auth)
        self.assertEqual((got["progress"], got["percentage"], got["device"]), (sent["progress"], 0.5, "Kobo Libra"))
        self.assertIsInstance(got["timestamp"], int)
        self.assertEqual(_json("PUT", f"{ROOT}/kosync/syncs/progress", {"progress": "x"}, headers=auth)[1]["code"], 2004)
        self.assertEqual(_json("PUT", f"{ROOT}/kosync/syncs/progress", sent, headers=wrong)[0], 401)
        status, pos = _json("GET", f"{API}/jobs/{self.job_id}/reading-position")
        self.assertEqual(pos["position"]["percentage"], 0.5)
        self.assertEqual((pos["unit"], pos["until"]), ("page", 2), "half of three pages of text: page 2")
        jobs = {j["job_id"]: j for j in _json("GET", f"{API}/jobs")[1]}
        self.assertEqual(jobs[self.job_id]["reading"]["percentage"], 0.5, "the History shows it")
        self.assertEqual(_json("GET", f"{API}/jobs/{self.other_id}/reading-position")[1], {"position": None})
        self.assertEqual(_json("DELETE", f"{API}/connections/sync")[0], 200)
        self.assertEqual(_json("GET", f"{ROOT}/kosync/users/auth", headers=auth)[0], 401, "removed")

    def test_glossary_suggestions(self):
        glossary_learning.add("", [("Lampkeeper", "Φαροφύλακας", "translation"), ("Gale", "Θύελλα", "edit")],
                              self.job_id, "library_book")
        status, data = _json("GET", f"{API}/glossary/suggestions")
        found = {s["source"]: s for s in data["suggestions"]}
        self.assertEqual(found["Gale"]["origin"], "edit")
        self.assertEqual(_json("POST", f"{API}/glossary/suggestions/accept", {})[0], 400)
        try:
            status, done = _json("POST", f"{API}/glossary/suggestions/accept", {"sources": ["Lampkeeper"]})
            self.assertEqual(done["added"], 1)
            self.assertEqual(_json("GET", f"{API}/glossary")[1].get("Lampkeeper"), "Φαροφύλακας")
            self.assertEqual(_json("POST", f"{API}/glossary/suggestions/dismiss", {"sources": ["Gale"]})[1],
                             {"dismissed": 1})
            self.assertEqual(_json("POST", f"{API}/glossary/suggestions/dismiss", {})[0], 400)
            left = {s["source"] for s in _json("GET", f"{API}/glossary/suggestions")[1]["suggestions"]}
            self.assertFalse({"Lampkeeper", "Gale"} & left)
        finally:
            _http("DELETE", f"{API}/glossary/Lampkeeper")

    def test_backup_and_restore(self):
        mp3 = self.out / "library_book_audiobook.mp3"
        mp3.write_bytes(b"ID3" + b"\0" * 2000)
        try:
            status, started = _json("POST", f"{API}/backup", {"include_audio": False})
            self.assertEqual(status, 200, started)
            task = _wait_task(started["task_id"])
            self.assertEqual(task["state"], "done", task)
            status, headers, data = _http("GET", f"{API}/backup/{started['task_id']}/download")
            self.assertEqual(status, 200)
            self.assertIn("BookApp-backup-", headers.get("content-disposition", ""))
        finally:
            mp3.unlink()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            manifest = json.loads(z.read(backup.MANIFEST))
        mine = [n for n in names if n.startswith(f"jobs/{self.job_id}/")]
        self.assertTrue(any(n.startswith(f"jobs/{self.job_id}/upload/") for n in mine), mine)
        self.assertTrue(any(n.endswith("_translated_greek.txt") for n in mine), mine)
        self.assertFalse(any(n.endswith(".mp3") for n in mine), "audiobooks only when asked for")
        self.assertIn(self.job_id, [j["job_id"] for j in manifest["jobs"]])
        self.assertEqual(set(manifest), {"format", "version", "created", "audio", "jobs", "series", "reading",
                                         "glossary"}, "books, series, positions and terms: no keys or accounts")
        # restored as it is: the books are already here
        task = self.restore(data)
        self.assertIn("library_book.pdf", task["result"]["already_here"])
        # the same book from another server: a new id, its files and record
        new_id = str(uuid.uuid4())
        rec = next(j for j in manifest["jobs"] if j["job_id"] == self.job_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as out:
            out.writestr(backup.MANIFEST, json.dumps(dict(manifest, jobs=[dict(rec, job_id=new_id)],
                                                          series=[{"name": "Moved", "books": [new_id]}])))
            for n in mine:
                out.writestr(n.replace(self.job_id, new_id, 1), src.read(n))
        task = self.restore(buf.getvalue())
        self.assertEqual((task["result"]["restored"], task["result"]["series"]), (1, 1), task)
        status, info = _json("GET", f"{API}/status/{new_id}")
        self.assertEqual((status, info["status"], info["file_name"]), (200, "done", "library_book.pdf"))
        self.assertTrue(info["has_translation"])
        self.assertEqual(_http("GET", f"{API}/download/{new_id}?format=epub")[0], 200, "it downloads")
        self.assertIn("Moved", [s["name"] for s in _json("GET", f"{API}/series")[1]["series"]])
        # not a backup
        status, started = _json("POST", f"{API}/backup/restore", raw=b"not a zip",
                                headers={"Content-Type": "application/zip"})
        self.assertEqual(_wait_task(started["task_id"])["error"], "Το αρχείο δεν είναι έγκυρο ZIP.")
        self.assertEqual(_json("POST", f"{API}/backup/restore", raw=b"", headers={"Content-Type": "application/zip"})[0],
                         400)
        self.assertEqual(_json("GET", f"{API}/backup/{'0' * 32}")[0], 404)
        self.assertEqual(_json("GET", f"{API}/backup/{'0' * 32}/download")[0], 404)
        _http("DELETE", f"{API}/jobs/{new_id}")

    def restore(self, data: bytes) -> dict:
        status, started = _json("POST", f"{API}/backup/restore", raw=data, headers={"Content-Type": "application/zip"})
        self.assertEqual(status, 200, started)
        task = _wait_task(started["task_id"])
        self.assertEqual(task["state"], "done", task)
        return task


# ---------------------------------------------------------------------------
# 8. The page (library.js, in Node with a small stand-in for the page)
# ---------------------------------------------------------------------------

LIBRARY_HARNESS = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = {};
function el(id) {
  if (!els[id]) {
    els[id] = { id, style: {}, textContent: '', innerHTML: '', value: '', disabled: false, checked: false, children: [],
      dataset: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
      append(...nodes) { for (const n of nodes) { this.children.push(n); this.textContent += n.textContent || ''; } } };
  }
  return els[id];
}
const responses = {};
const sent = [];
const ctx = vm.createContext({
  console, setInterval: () => 1, clearInterval() {}, Promise, JSON, Math, Number, String, Boolean, Date, Array, Set,
  encodeURIComponent,
  document: { getElementById: el, createElement: () => ({ textContent: '', setAttribute() {}, append() {} }),
              createTextNode: (t) => ({ textContent: t }) },
  window: { location: { origin: 'http://nas:8000' }, confirm: () => true, prompt: () => 'Saga' },
  navigator: {},
  API: 'http://nas:8000/api',
  state: { tr: { jobId: 'job-2' } },
  insState: { jobId: 'job-2' },
  toasts: [],
  fetch: async (url, opts = {}) => {
    sent.push([opts.method || 'GET', url, opts.body || null]);
    const key = Object.keys(responses).filter((k) => url.includes(k)).sort((a, b) => b.length - a.length)[0];
    const body = key ? responses[key] : {};
    return { ok: true, status: 200, json: async () => body };
  },
});
vm.runInContext(`
  function toast(m) { toasts.push(m); }
  function escHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  async function parseApiError(res, fb) { return fb; }
  function saveFile() {}
  function refreshHistory() {}
  async function loadGlossary() {}
  function setDevicesStatus(id, text) { document.getElementById(id).textContent = text; }
  function loadHistoryJobIntoInsights() {}
`, ctx);
vm.runInContext(fs.readFileSync('frontend/library.js', 'utf8'), ctx);
const i18n = vm.createContext({ console, MutationObserver: class { observe() {} }, CustomEvent: class {},
  localStorage: { getItem: () => null, setItem() {} }, navigator: { language: 'el-GR' },
  document: { documentElement: {}, addEventListener() {}, querySelectorAll: () => [], dispatchEvent() {} },
  window: { alert() {}, confirm() { return true; }, prompt() {} }, NodeFilter: {} });
vm.runInContext(fs.readFileSync('frontend/i18n.js', 'utf8') + ';globalThis.I18N = I18N;', i18n);
const en = (s) => i18n.I18N.text(s, 'en');
const english = (s) => { const t = en(s); assert.notStrictEqual(t, s, 'no English for: ' + s); return t; };

(async () => {
  // the book's series, under its file
  responses['/series'] = { series: [{ id: 'aaaaaaaaaaaa', name: 'Saga <b>', books: [] }] };
  responses['/jobs/job-2/series'] = { series: { id: 'aaaaaaaaaaaa', name: 'Saga <b>' }, position: 2, books: 2,
    earlier: [], names_from_earlier: 7 };
  await ctx.refreshBookSeries();
  assert.strictEqual(el('tr-series-row').style.display, '');
  assert.ok(el('tr-series-select').innerHTML.includes('Saga &lt;b&gt;'), 'names are escaped');
  assert.strictEqual(el('tr-series-select').value, 'aaaaaaaaaaaa');
  assert.strictEqual(el('tr-series-position').value, '2');
  assert.strictEqual(english(el('tr-series-note').textContent), '7 names from the earlier books are written the same way in this one.');
  ctx.state.tr.jobId = null;
  await ctx.refreshBookSeries();
  assert.strictEqual(el('tr-series-row').style.display, 'none', 'no book, no row');
  ctx.state.tr.jobId = 'job-2';
  // moving it to another place: the series and the place are sent
  el('tr-series-position').value = '1';
  await ctx.onBookSeriesChange();
  const put = sent.filter(([m, u]) => m === 'PUT' && u.endsWith('/jobs/job-2/series')).pop();
  assert.deepStrictEqual(JSON.parse(put[2]), { series_id: 'aaaaaaaaaaaa', position: 1 });

  // the Characters page option
  el('tr-layout-mode').value = 'literature';
  ctx.showEpubCharacters({ characters: true, available: true, people: 12, terms: 3, language: 'greek' });
  assert.strictEqual(el('tr-epub-characters').checked, true);
  assert.strictEqual(english(el('tr-epub-characters-note').textContent), 'From 👥 Characters & terms: 12 characters, 3 terms.');
  ctx.showEpubCharacters({ characters: false, available: false, language: 'english' });
  assert.strictEqual(el('tr-epub-characters').disabled, true, 'nothing to put on the page yet');
  english(el('tr-epub-characters-note').textContent);
  el('tr-layout-mode').value = 'comic';
  ctx.showEpubCharacters({ characters: false, available: true, people: 1, terms: 0 });
  assert.strictEqual(el('tr-epub-extras').style.display, 'none', "a graphic novel's EPUB is its pages");

  // Glossary suggestions: book text is escaped, the marks say why one is left out of "accept all"
  ctx.renderGlossarySuggestions({ safe: 1, suggestions: [
    { source: 'Will', target: 'Γουίλ', origin: 'translation', ordinary_word: true, glossary: '', books: [{ job_id: 'j', title: 'Book <i>' }] },
    { source: '<img src=x onerror=1>', target: 'Κίτον', origin: 'edit', ordinary_word: false, glossary: 'Κήτον', books: [] }] });
  const rows = el('glossary-suggestions-tbody').innerHTML;
  assert.ok(!rows.includes('<img'), 'escaped');
  assert.ok(rows.includes('Book &lt;i&gt;'));
  assert.ok(rows.includes('⚠️') && rows.includes('✏️') && rows.includes('↔️'));
  assert.strictEqual(el('glossary-suggestions-count').textContent, '2');
  assert.strictEqual(el('glossary-accept-all-btn').disabled, false);

  // the reading position and the books before, in Book Insights
  responses['/jobs/job-2/reading-position'] = { position: { percentage: 0.42, device: 'Kobo' }, until: 120, unit: 'page' };
  responses['/jobs/job-2/series?language'] = { series: { id: 'a', name: 'Saga' }, position: 3, earlier: [
    { job_id: 'j1', title: 'One', summary: { text: 'Line <1>\nLine 2' } }, { job_id: 'j2', title: 'Two', summary: null }] };
  await ctx.refreshInsightsLibrary('job-2');
  assert.strictEqual(english(el('ins-recap-position-note').textContent), '📍 You have read 42% (page 120).');
  assert.strictEqual(el('ins-recap-position').style.display, '');
  el('ins-recap-until').value = '1';
  ctx.useReadingPosition();
  assert.strictEqual(el('ins-recap-until').value, '120');
  assert.strictEqual(el('ins-series').style.display, '');
  assert.ok(el('ins-series-books').innerHTML.includes('Line &lt;1&gt;<br>Line 2'));
  assert.ok(el('ins-series-books').innerHTML.includes('loadHistoryJobIntoInsights'), 'a book without a summary opens');
  english('χωρίς περίληψη ακόμη');

  // 📲 Devices: the sync password
  ctx.showSyncState({ exists: true, created: 1700000000, last_sync: 1700003600 }, 'maria');
  assert.ok(el('sync-status').textContent.startsWith('Υπάρχει κωδικός από'));
  english(el('sync-status').textContent);
  responses['/connections/sync'] = { path: '/kosync', username: 'maria', password: 'aa-bb-cc-dd' };
  await ctx.newSyncPassword();
  assert.strictEqual(el('sync-server').value, 'http://nas:8000/kosync');
  assert.strictEqual(el('sync-password').value, 'aa-bb-cc-dd');
  english(el('sync-status').textContent);

  for (const s of ['✅ Επαναφέρθηκαν 3 βιβλία. 1 υπήρχαν ήδη. 4 όροι μπήκαν στο Γλωσσάρι.',
                   '✅ Έτοιμο: 5 βιβλία, 12.5 MB. 1 βιβλία που μεταφράζονται τώρα έμειναν έξω.',
                   'Δεν υπάρχει αρκετός χώρος στον δίσκο: χρειάζονται 900 MB, υπάρχουν 120 MB.',
                   '📚 Το βιβλίο μπήκε στη σειρά.', '⬆️ Ανέβασμα: 40%', '· βιβλίο 3']) english(s);
  process.stdout.write('OK');
})().catch((e) => { process.stdout.write(String(e && e.stack || e)); process.exit(1); });
"""


class PageTests(unittest.TestCase):
    def test_the_library_on_the_page(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js not available in PATH")
        res = subprocess.run([node, "-e", LIBRARY_HARNESS], capture_output=True, text=True, encoding="utf-8",
                             timeout=60)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)

    def test_the_page_holds_the_controls(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        for needle in ('<script src="library.js', 'id="sync-section"', 'onclick="newSyncPassword()"',
                       'id="tr-series-row"', 'onclick="openSeriesModal()"', 'onclick="openBackupModal()"',
                       'id="tr-epub-characters"', 'id="glossary-suggestions"', 'id="ins-recap-position"',
                       'id="series-modal"', 'id="backup-modal"', 'id="restore-file"'):
            self.assertIn(needle, html)
        self.assertLess(html.index('<script src="insights.js'), html.index('<script src="library.js'),
                        "library.js uses insights.js")


if __name__ == "__main__":
    unittest.main(verbosity=2)
