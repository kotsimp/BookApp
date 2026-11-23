"""
test_export_fidelity.py - Exporters drop no words of the book; comics never leave pages untranslated silently.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import io
import os
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docx
import pymupdf
from bs4 import BeautifulSoup
from PIL import Image

from backend import comic_translator, exporter, job_manager, parsers
from backend.database import db_delete_job

BODY = "The road went down to the sea and nobody spoke for a long while after that."
P = "=== PAGE {} ===\n"
CASES = (
    P.format(1) + "The Silent Harbour\n\nAnna Petrou\n\n" + P.format(2) + f"Chapter 1\n\n{BODY}",
    P.format(1) + f"Part One\n\nChapter 1\n\n{BODY}\n\nChapter 2\n\n{BODY}",
    P.format(1) + f"The Storm\n3\n\n{BODY}",
    P.format(1) + f"7\n\n{BODY}",
    P.format(1) + f"Anna Petrou\n12\nLondon\n\n{BODY}",
    P.format(1) + f"Mix\n\n{BODY}\n\n1984\n",
    "Dedication to my mother.\n\n" + P.format(1) + BODY,
    P.format(1) + f"The product 2*3*4 is twenty-four. {BODY}",
    P.format(1) + f"Tokyo is written 東京 , the syllables あいう and Seoul is 서울 . {BODY}",
)


def words(text):
    return re.findall(r"[^\W_]+", re.sub(r"=== PAGE \d+ ===", " ", text).lower())


def read(path):
    if path.suffix == ".docx":
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    if path.suffix == ".pdf":
        with pymupdf.open(str(path)) as d:
            return "\n".join(p.get_text() for p in d)
    with zipfile.ZipFile(path) as z:
        pages = [z.read(n) for n in z.namelist() if n.endswith(".xhtml") and "nav" not in n]
    return "\n".join(BeautifulSoup(p, "xml").find("body").get_text(" ") for p in pages)


class TestExporters(unittest.TestCase):
    def test_no_word_is_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            for text in CASES:
                for layout in ("standard", "literature"):
                    for fmt in ("pdf", "docx", "epub"):
                        pool = words(read(exporter.export_text(text, Path(td), fmt, "book", layout=layout)))
                        for word in words(text):
                            self.assertIn(word, pool, f"{layout} {fmt}: {text[:50]!r}")
                            pool.remove(word)

    def test_east_asian_text_stays_inside_the_margins(self):
        with tempfile.TemporaryDirectory() as td:
            for layout in ("standard", "literature"):
                pdf = exporter.export_text("東京の夜は静かです" * 40, Path(td), "pdf", "cjk", layout=layout)
                with pymupdf.open(str(pdf)) as doc:
                    shown = "".join("".join(p.get_text().split()) for p in doc)
                    self.assertEqual(shown.count("東京"), 40, layout)
                    for page in doc:
                        for word in page.get_text("words"):
                            self.assertLess(word[2], page.rect.width, layout)

    def test_every_script_is_written(self):
        # shaped text extracts as glyph forms, so these are compared as the pixels the renderer is asked to draw
        samples = ("Ἐν ἀρχῇ ἦν ὁ λόγος", "საქართველო", "Հայաստան", "ˈɡriːk", "∀∈⊕", "שלום", "สวัสดี")
        with tempfile.TemporaryDirectory() as td:
            for layout in ("standard", "literature"):
                for sample in samples:
                    pdf = exporter.export_text(f"Quote {sample} end.", Path(td), "pdf", "s", layout=layout)
                    with pymupdf.open(str(pdf)) as doc:
                        shown = "".join(p.get_text() for p in doc).replace(chr(0x4D9), chr(0x259))
                        for ch in sample.replace(" ", ""):
                            self.assertIn(ch, shown, f"{layout}: {sample}")
                        self.assertLess(pdf.stat().st_size, 1_500_000, f"{layout}: {sample}: fonts not subsetted")
                pdf = exporter.export_text("Quote السلام عليكم end.", Path(td), "pdf", "a", layout=layout)
                with pymupdf.open(str(pdf)) as doc:
                    glyphs = [c for c in doc[0].get_text() if ord(c) > 0x7F and not c.isspace()]  # ligatures join letters
                    self.assertGreaterEqual(len(glyphs), 8, f"{layout}: Arabic is drawn")

    def test_right_to_left_quotation_keeps_the_sentence_order(self):
        font = exporter._BookFont(pymupdf.Font("helv"))
        runs = font.runs("He said שלום עולם, then left.")
        self.assertEqual(runs[1], (font.SHAPED, "שלום עולם"))
        self.assertTrue(runs[2][1].lstrip().startswith(","))

    def test_a_polytonic_book_keeps_one_typeface(self):
        line = "ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς τὸν θεόν. "
        with tempfile.TemporaryDirectory() as td:
            pdf = exporter.export_text(line * 12, Path(td), "pdf", "poly", layout="literature")
            with pymupdf.open(str(pdf)) as doc:
                spans = [s for b in doc[0].get_text("dict")["blocks"] for ln in b.get("lines", ()) for s in ln["spans"]]
        body = {s["font"] for s in spans if "λόγος" in s["text"] or "ἀρχῇ" in s["text"]}
        self.assertEqual(len(body), 1, body)

    def test_page_numbers_are_still_removed(self):
        # the sentences run across the numbers: those count pages
        half = "and the road went down to the sea where nobody spoke for a long while, until the lights showed"
        text = "".join(f"{P.format(n)}{n + 40}\n\n{half}\n\n" for n in range(1, 5))
        shown = " ".join(" ".join(c["paragraphs"]) for c in exporter._prepare_literature_chapters(text))
        self.assertEqual(re.findall(r"\d+", shown), [])


ITALIC_FACES = {"ariali.ttf", "calibrii.ttf", "segoeuii.ttf", "georgiai.ttf", "timesi.ttf", "palai.ttf"}


def without_italic_faces():
    """The exporter sees no italic font file, like a Linux system with only the core DejaVu fonts."""
    real = os.path.exists

    def exists(path):
        name = os.path.basename(str(path))
        return False if name in ITALIC_FACES or re.search("italic|oblique", name, re.I) else real(path)

    return mock.patch.object(exporter.os.path, "exists", exists)


def leaning_texts(calls):
    """Records the text the exporter draws leaning (a regular face standing in for italics) into `calls`."""
    real = pymupdf.Page.insert_text

    def insert_text(page, point, text, *a, **k):
        morph = k.get("morph")
        if morph and abs(morph[1].c) > 0.05 and abs(morph[1].b) < 1e-9:
            calls.append(text)
        return real(page, point, text, *a, **k)

    return mock.patch.object(pymupdf.Page, "insert_text", insert_text)


class TestEmphasis(unittest.TestCase):
    def export(self, text):
        with tempfile.TemporaryDirectory() as td:
            for layout in ("standard", "literature"):
                for fmt in ("pdf", "docx", "epub"):
                    leaning = []
                    with leaning_texts(leaning):
                        path = exporter.export_text(P.format(1) + text, Path(td), fmt, "emphasis", layout=layout)
                    if fmt == "docx":
                        doc = docx.Document(str(path))
                        marked = [r.text for p in doc.paragraphs for r in p.runs if r.bold or r.italic]
                    elif fmt == "pdf":
                        with pymupdf.open(str(path)) as doc:
                            marked = [s["text"] for p in doc for b in p.get_text("dict")["blocks"]
                                      for ln in b.get("lines", ()) for s in ln["spans"]
                                      if re.search("bold|italic|oblique", s["font"], re.I)] + leaning
                    else:
                        with zipfile.ZipFile(path) as z:
                            pages = [BeautifulSoup(z.read(n), "xml") for n in z.namelist()
                                     if n.endswith(".xhtml") and "nav" not in n]
                        marked = [e.get_text() for soup in pages for e in soup.find_all(["em", "strong"])]
                    # not read(): it puts a space at every inline tag
                    shown = " ".join(s.get_text() for s in pages) if fmt == "epub" else read(path)
                    yield f"{layout} {fmt}", " ".join(shown.split()), " ".join(" ".join(marked).split())

    def test_markers_become_formatting(self):
        text = "It was **very late**. She read (*Odyssey*) again, twice."
        for where, shown, marked in self.export(text):
            self.assertIn("It was very late. She read (Odyssey) again, twice.", shown, where)
            self.assertIn("very late", marked, where)
            self.assertIn("Odyssey", marked, where)

    def test_italics_lean_where_no_italic_font_exists(self):
        text = P.format(1) + "It was **very late**. She read (*Odyssey*) again, twice."
        with tempfile.TemporaryDirectory() as td, without_italic_faces():
            for layout in ("standard", "literature"):
                leaning = []
                with leaning_texts(leaning):
                    pdf = exporter.export_text(text, Path(td), "pdf", f"lean-{layout}", layout=layout)
                self.assertEqual(" ".join(leaning).split(), ["Odyssey"], layout)
                self.assertIn("She read (Odyssey) again, twice.", " ".join(read(pdf).split()), layout)

    def test_a_family_with_every_face_is_preferred(self):
        with tempfile.TemporaryDirectory() as td:
            files = {n: Path(td) / n for n in ("A.ttf", "A-Bold.ttf", "B.ttf", "B-Italic.ttf", "B-Bold.ttf")}
            for path in files.values():
                path.write_bytes(b"")
            a = (str(files["A.ttf"]), str(Path(td) / "A-Italic.ttf"), str(files["A-Bold.ttf"]))
            b = (str(files["B.ttf"]), str(files["B-Italic.ttf"]), str(files["B-Bold.ttf"]))
            self.assertEqual(exporter._complete_family([a, b]), b)
            self.assertEqual(exporter._complete_family([a]), (a[0], None, a[2]))
            self.assertEqual(exporter._complete_family([(str(Path(td) / "none.ttf"), None, None)]), (None, None, None))

    def test_asterisks_of_the_book_are_text(self):
        for text in ("Then 2**10 is 1024 and 2 ** 3 is 8.", "Pass *args and **kwargs or **options here.",
                     "Copy *.txt and *.pdf files.", "The price* holds until noon.", "It had **** stars."):
            for where, shown, _marked in self.export(text):
                self.assertIn(text, shown, where)

    def test_narration_does_not_read_the_markers(self):
        from backend.tts_engine import _clean_tts_text
        self.assertEqual(_clean_tts_text("It was **very late**."), "It was very late.")
        self.assertIn("2**10", _clean_tts_text("Then 2**10 and 2 ** 3."))


class TestNumbersOfTheBook(unittest.TestCase):
    def shown(self, text):
        return [line for c in exporter._prepare_literature_chapters(text) for line in [c["title"]] + c["paragraphs"]]

    def test_chapter_numbers_and_years_stay(self):
        for labels in (("1", "2", "3", "4"), ("II", "III", "IV", "V"), ("1981", "1982", "1983", "1984")):
            text = "\n\n".join(P.format(n + 1) + f"{label}\n\n{BODY}" for n, label in enumerate(labels))
            self.assertTrue(set(labels) <= set(self.shown(text)), labels)

    def test_lines_beside_a_number_stay_unless_they_repeat(self):
        text = "\n\n".join(P.format(n) + f"Night {n}x\n{n + 20}\nShort true line {n}\n\n{BODY}" for n in range(1, 5))
        shown = " ".join(self.shown(text))
        for n in range(1, 5):
            self.assertIn(f"Night {n}x", shown)
            self.assertIn(f"Short true line {n}", shown)

    def test_a_numbered_poem_is_not_the_page_number(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "poems.pdf"
            doc = pymupdf.open()
            for n in range(1, 7):
                page = doc.new_page(width=420, height=595)
                for y, line in [(45, str(n)), (575, str(n + 40))] + [(y, BODY[:55]) for y in range(120, 460, 20)]:
                    page.insert_text((40, y), line, fontsize=11)
            doc.save(str(src))
            doc.close()
            pages = [p["text"].split() for p in parsers.parse_pdf(str(src))]
        for n, found in enumerate(pages, 1):
            self.assertIn(str(n), found)
            self.assertNotIn(str(n + 40), found)


class TestComicPages(unittest.TestCase):
    def test_failed_page_is_reported_and_checkpoint_keeps_the_language(self):
        async def detect(_img, *_a, status_out=None, **_k):
            if self.calls:
                status_out["error"] = "blocked"
                items = []
            else:
                status_out["succeeded"] = True
                items = [{"box_2d": [100, 100, 300, 700], "original_text": "Hello", "translated_text": "Γεια"}]
            self.calls += 1
            return items

        self.calls = 0
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "riders.pdf"
            doc = pymupdf.open()
            for shade in (250, 230, 210, 190, 170):
                img = io.BytesIO()
                Image.new("RGB", (300, 400), (shade, shade, shade)).save(img, "JPEG")
                doc.new_page(width=300, height=400).insert_image(pymupdf.Rect(0, 0, 300, 400), stream=img.getvalue())
            doc.save(str(src))
            doc.close()
            job = job_manager.create_job(str(src), "riders.pdf", "pdf")
            notes = []

            async def detect_one_failure(img, *a, **k):
                # exactly one page fails: below the threshold that fails the whole job
                self.calls = 1 if len(seen) == 2 else 0
                seen.append(1)
                return await detect(img, *a, **k)

            seen = []
            try:
                with mock.patch.object(comic_translator, "_detect_comic_balloons_vision_async", detect_one_failure):
                    asyncio.run(comic_translator.translate_comic_document(
                        job.job_id, str(src), "pdf", "english", "greek", str(Path(td) / "out" / "riders.txt"),
                        api_key="AIzaFake-not-real", quota_behavior="fallback", notes=notes))
                saved = json.loads((Path(td) / "out" / ".comic_vision_checkpoint.json").read_text(encoding="utf-8"))
            finally:
                job_manager._jobs.pop(job.job_id, None)
                db_delete_job(job.job_id)
        self.assertEqual(len(notes), 1)
        self.assertIn("1 page(s) left untranslated", notes[0])
        self.assertEqual(saved["_languages"], "english>greek")


COPIED = (
    "Ο καπετάνιος μέτρησε τις βάρκες στο ήσυχο λιμάνι πριν από την καταιγίδα· κανείς δεν μίλησε.",
    "«Πού πας;» ρώτησε η Ελένη, κι εκείνος είπε: «Απ' το λιμάνι, ως το e-mail του».",
    "The captain counted the boats; nobody spoke. \"Don't,\" she said, it's a well-known fact.",
    "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν.",
)
# characters that only twin a glyph of the book's own characters: copied text must never hold them
TWINS = "\u00a0\u00ad\u037e\u0387\ua78f\u201b\u2219\u02b9\u02ba" + "".join(chr(c) for c in range(0x1F71, 0x1F7E, 2))  # oxia = tonos


def copied(pdf) -> str:
    """The text a reader copies: line ends become spaces, nothing else is normalised."""
    with pymupdf.open(str(pdf)) as doc:
        return re.sub(r"[ \n]+", " ", " ".join(p.get_text() for p in doc))


class TestCopiedText(unittest.TestCase):
    """Copying, searching and reading an exported PDF back give the characters of the book."""

    def test_book_pdfs_copy_as_written(self):
        with tempfile.TemporaryDirectory() as td:
            for layout in ("standard", "literature"):
                shown = copied(exporter.export_text("\n\n".join(COPIED), Path(td), "pdf", "b", layout=layout))
                for paragraph in COPIED:
                    self.assertIn(paragraph, shown, layout)
                self.assertEqual([f"U+{ord(c):04X}" for c in shown if c in TWINS], [], layout)

    def test_every_book_font_names_its_glyphs_as_written(self):
        from backend.pdf_text_names import fix_text_names
        text = " ".join(COPIED[:3]) + " Καλά νέα: ήρθε, είδε, όλα ωραία. Ά Έ Ή Ί Ό Ύ Ώ 5 μm"
        fonts = [f for f in ("C:/Windows/Fonts/pala.ttf", "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/arial.ttf",
                             "C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/comic.ttf", "C:/Windows/Fonts/georgia.ttf",
                             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                             "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                             "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf") if Path(f).exists()]
        if not fonts:
            self.skipTest("no TrueType font with Greek on this computer")
        for path in fonts:
            with pymupdf.open() as doc:
                page = doc.new_page(width=4000)
                page.insert_font(fontname="f", fontfile=path)
                page.insert_text((20, 50), text, fontname="f", fontsize=9)
                fix_text_names(doc, text)
                doc.subset_fonts()
                again = pymupdf.open("pdf", doc.tobytes(garbage=3))
            shown = again[0].get_text().strip()
            self.assertEqual(shown, text, Path(path).name)

    def test_the_names_map_reads_ranges_and_arrays(self):
        from backend.pdf_text_names import _parse_tounicode, _write_tounicode
        names = _parse_tounicode("2 beginbfrange\n<0003> <0005> <0041>\n<0010> <0011> [<00660069> <D835DC00>]\n"
                                 "endbfrange\n1 beginbfchar\n<0020> <03AC>\nendbfchar")
        self.assertEqual(names, {3: "A", 4: "B", 5: "C", 0x10: "fi", 0x11: "\U0001d400", 0x20: "ά"})
        self.assertEqual(_parse_tounicode(_write_tounicode(names).decode("ascii")), names)


if __name__ == "__main__":
    unittest.main()
