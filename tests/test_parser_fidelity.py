"""
test_parser_fidelity.py - The parsers drop nothing the reader sees and keep the reading order.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf

from backend import parsers

BODY = "The road went down to the sea and nobody spoke for a long while after that."
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006"
MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml"


class TempCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class TestPdf(TempCase):
    def pdf(self, pages):
        """pages: lists of (x, y, text, font size); body lines are added to every page."""
        path = self.dir / "book.pdf"
        with pymupdf.open() as doc:
            for lines in pages:
                page = doc.new_page(width=500, height=800)
                for x, y, text, size in lines:
                    page.insert_text((x, y), text, fontsize=size)
                for k in range(8):
                    page.insert_text((50, 200 + 20 * k), BODY, fontsize=11)
            doc.save(str(path))
        return {p["page"]: p["text"] for p in parsers.parse_pdf(str(path))}

    def test_short_lines_at_the_top_are_content(self):
        samples = ["The Silent Harbour", "Are you coming", "14 March 1921", "II", "A Night in Patras", "Anna Petrou"]
        got = self.pdf([[(50, 80, text, 11)] for text in samples])
        for n, text in enumerate(samples, 1):
            self.assertIn(text, got[n])

    def test_chapter_titles_survive(self):
        got = self.pdf([[(50, 80, f"Chapter {n}", 11)] for n in range(1, 8)])
        for n in range(1, 8):
            self.assertIn(f"Chapter {n}", got[n])
        got = self.pdf([[(50, 80, "The Silent Harbour", 20)]] + [[(50, 30, "The Silent Harbour", 9)]] * 5)
        self.assertIn("The Silent Harbour", got[1])
        self.assertNotIn("The Silent Harbour", got[3])

    def test_running_headers_footers_and_numbers_are_removed(self):
        pages = [[(50, 30, "ANNA PETROU" if n % 2 else "THE SILENT HARBOUR", 9),
                  (240, 780, str(n), 9), (340, 780, f"Draft page {n} of 30", 9)] for n in range(1, 31)]
        for n, text in self.pdf(pages).items():
            self.assertEqual(" ".join(text.split()), " ".join([BODY] * 8), f"page {n}")

    def test_centred_page_number_inside_the_margin(self):
        for n, text in self.pdf([[(240, 728, str(n + 40), 11)] for n in range(5)]).items():
            self.assertEqual(" ".join(text.split()), " ".join([BODY] * 8), f"page {n}")

    def labelled(self, pages, first_label):
        """pages as in pdf(); the PDF's own page labels count from first_label."""
        path = self.dir / "labelled.pdf"
        with pymupdf.open() as doc:
            for lines in pages:
                page = doc.new_page(width=500, height=800)
                for x, y, text, size in lines:
                    page.insert_text((x, y), text, fontsize=size)
                for k in range(8):
                    page.insert_text((50, 200 + 20 * k), BODY, fontsize=11)
            doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": first_label}])
            doc.save(str(path))
        return {p["page"]: p["text"] for p in parsers.parse_pdf(str(path))}

    def test_the_page_labels_of_the_pdf_decide(self):
        # folios at the head; a chapter opens with its folio at the foot, where no neighbour has a number
        pages = [[(450, 40, str(20 + n), 9)] for n in range(1, 9)]
        pages[3] = [(50, 80, "Chapter Two", 16), (240, 780, "24", 9)]
        got = self.labelled(pages, 21)
        self.assertIn("Chapter Two", got[4])
        for n, text in got.items():
            self.assertEqual(" ".join(text.replace("Chapter Two", "").split()), " ".join([BODY] * 8), f"page {n}")

    def test_labels_that_are_not_the_printed_numbers_change_nothing(self):
        pages = [[(240, 780, str(n), 9)] for n in range(1, 9)]
        for n, text in self.labelled(pages, 101).items():
            self.assertEqual(" ".join(text.split()), " ".join([BODY] * 8), f"page {n}")

    def test_with_labels_a_second_counting_series_is_the_book_s(self):
        # numbered poems, one per page at the head, counting with the pages; the folio at the foot is the label
        pages = [[(50, 60, str(n), 11), (240, 780, str(40 + n), 9)] for n in range(1, 9)]
        for n, text in self.labelled(pages, 41).items():
            self.assertEqual(text.split()[0], str(n), f"page {n}")
            self.assertNotIn(str(40 + n), text.split(), f"page {n}")

    def test_ligatures_and_soft_hyphens(self):
        self.assertEqual(parsers._clean_text(f"e{chr(0xFB03)}cient repre{chr(0xAD)}\nsentation"), "efficient representation")


def run(text):
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def para(inner):
    return f"<w:p>{inner}</w:p>"


def cell_table(inner):
    return f"<w:tbl><w:tr><w:tc>{inner}</w:tc></w:tr></w:tbl>"


class TestDocx(TempCase):
    def test_everything_visible_in_reading_order(self):
        body = [
            para(run("one")),
            cell_table(para(run("two")) + cell_table(para(run("three"))) + para(run("four"))),
            f"<w:sdt><w:sdtContent>{para(run('five'))}{cell_table(para(run('six')))}</w:sdtContent></w:sdt>",
            para(f'<w:ins w:id="1">{run("seven")}</w:ins><w:del w:id="2"><w:r><w:delText>deleted</w:delText></w:r></w:del>'),
            para(f'<w:fldSimple w:instr="REF x">{run("eight")}</w:fldSimple>'),
            para(f'<w:smartTag w:element="place">{run("nine")}</w:smartTag>'),
            para(f"<w:r><w:pict><v:shape><v:textbox><w:txbxContent>{para(run('ten'))}</w:txbxContent>"
                 "</v:textbox></v:shape></w:pict></w:r>"),
            para("<w:r><w:t>well</w:t><w:noBreakHyphen/><w:t>known</w:t></w:r>"),
        ]
        ns = f'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="{REL}"'
        path = self.dir / "book.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml",
                       f'<Types xmlns="{PKG}/content-types">'
                       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                       f'<Override PartName="/word/document.xml" ContentType="{MAIN}.document.main+xml"/>'
                       f'<Override PartName="/word/footnotes.xml" ContentType="{MAIN}.footnotes+xml"/></Types>')
            z.writestr("_rels/.rels", f'<Relationships xmlns="{PKG}/relationships"><Relationship Id="r" '
                                      f'Type="{REL}/officeDocument" Target="word/document.xml"/></Relationships>')
            z.writestr("word/_rels/document.xml.rels", f'<Relationships xmlns="{PKG}/relationships"><Relationship Id="f" '
                                                       f'Type="{REL}/footnotes" Target="footnotes.xml"/></Relationships>')
            z.writestr("word/footnotes.xml", f'<w:footnotes {ns}><w:footnote w:id="2">{para(run("note"))}</w:footnote></w:footnotes>')
            z.writestr("word/document.xml",
                       f'<w:document {ns} xmlns:v="urn:schemas-microsoft-com:vml"><w:body>{"".join(body)}<w:sectPr/></w:body></w:document>')
        words = " ".join(p["text"] for p in parsers.parse_docx(str(path))).split()
        self.assertEqual(words, "one two three four five six seven eight nine ten well-known note".split())


class TestEpubText(unittest.TestCase):
    def test_inline_markup_does_not_break_sentences(self):
        html = ('<html><head><title>T</title><style>p{}</style></head><body><p><span class="cap">O</span>nce upon\n'
                ' a <em>very</em> <a href="#n">long</a> time<sup>1</sup>.</p><!--hidden--><p>Next<br/>line</p>'
                "<table><tr><td>A</td><td>B</td></tr></table><pre>code\nsample</pre></body></html>")
        self.assertEqual(parsers._html_to_text(html),
                         "Once upon a very long time1.\n\nNext\nline\n\nA\n\nB\n\ncode\nsample")

    def test_unclosed_br_keeps_the_rest(self):
        self.assertEqual(parsers._html_to_text("<p>first<br>second<br>third</p>"), "first\nsecond\nthird")


if __name__ == "__main__":
    unittest.main()
