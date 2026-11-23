"""
test_lossless_documents.py - Property tests for backend.document_blocks / format_preserver / format_sync.

Random DOCX/EPUB packages with nested tables, hyperlinks, text boxes, images, breaks, footnotes, inline markup, loose
container text and navigation must satisfy, exactly:
* translation changes text only: the markup skeleton and every other zip entry are identical;
* every translatable text is translated once, none is lost, duplicated or reordered;
* after any series of edits the document's blocks equal the edited paragraphs, in the same order.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import io
import os
import random
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree

from backend import format_preserver, format_sync
from backend.document_blocks import DocumentError, open_package

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
      'xmlns:v="urn:schemas-microsoft-com:vml"')
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WORDS = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa".split()


def key(text):
    return "".join(text.split())


class Gen:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.n = 0

    def phrase(self):
        self.n += 1
        # a unique word made of letters only, so that upper-casing is a reversible "translation"
        tag = "q" + "".join(chr(97 + int(d)) for d in str(self.n))
        return " ".join([tag] + self.r.sample(WORDS, self.r.randint(1, 5)))

    # ---- DOCX
    def run(self, text):
        props = self.r.choice(["", "<w:b/>", "<w:i/>", '<w:color w:val="C00000"/>', '<w:lang w:val="en-GB"/>',
                               '<w:rStyle w:val="Strong"/>', "<w:vanish/>", '<w:sz w:val="28"/>', '<w:b w:val="0"/>'])
        return f'<w:r>{f"<w:rPr>{props}</w:rPr>" if props else ""}<w:t xml:space="preserve">{text}</w:t></w:r>'

    def para(self, depth=0):
        parts = []
        for _ in range(self.r.randint(1, 4)):
            kind = self.r.choice(["run", "run", "run", "link", "br", "tab", "img", "note", "del", "split", "box",
                                  "links", "field", "ins", "sdt", "math", "comment"])
            p = self.phrase()
            if kind == "run":
                parts.append(self.run(p + " "))
            elif kind == "link":
                parts.append(f'<w:hyperlink w:anchor="a">{self.run(p)}</w:hyperlink>{self.run(" ")}')
            elif kind == "br":
                parts.append(f'<w:r><w:t>{p}</w:t><w:br/><w:t>{self.phrase()}</w:t></w:r>')
            elif kind == "tab":
                parts.append(f'<w:r><w:t>{p}</w:t><w:tab/><w:t>12</w:t></w:r>')
            elif kind == "img":
                parts.append(f'<w:r><w:t>{p}</w:t><w:pict><v:rect id="r{self.n}"/></w:pict></w:r>')
            elif kind == "note":
                parts.append(f'{self.run(p)}<w:r><w:footnoteReference w:id="1"/></w:r>')
            elif kind == "del":
                parts.append(f'{self.run(p + " ")}<w:del w:id="9"><w:r><w:delText>gone</w:delText></w:r></w:del>')
            elif kind == "split":  # one word over two runs with different formatting
                parts.append(f'<w:r><w:rPr><w:b/></w:rPr><w:t>{p[:2]}</w:t></w:r><w:r><w:t>{p[2:]}</w:t></w:r>')
            elif kind == "box" and depth == 0:
                inner = self.para(1)
                parts.append(f'<w:r><w:pict><v:shape><v:textbox><w:txbxContent>{inner}</w:txbxContent>'
                             f'</v:textbox></v:shape></w:pict></w:r>')
            elif kind == "links":
                parts.append(f'<w:hyperlink w:anchor="b">{self.run(p + " ")}</w:hyperlink>'
                             f'<w:hyperlink w:anchor="c">{self.run(self.phrase())}</w:hyperlink>')
            elif kind == "field":
                parts.append('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> REF x </w:instrText></w:r>'
                             f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>{self.run(p)}'
                             '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
            elif kind == "ins":
                parts.append(f'<w:ins w:id="3">{self.run(p + " ")}</w:ins>')
            elif kind == "sdt":
                parts.append(f'<w:sdt><w:sdtContent>{self.run(p + " ")}</w:sdtContent></w:sdt>')
            elif kind == "math":
                parts.append(f'{self.run(p + " ")}<m:oMath/>{self.run(" " + self.phrase())}')
            elif kind == "comment":
                parts.append(f'<w:commentRangeStart w:id="4"/>{self.run(p + " ")}<w:commentRangeEnd w:id="4"/>')
        style = self.r.choice(["", "", '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'])
        return f"<w:p>{style}{''.join(parts) or self.run(self.phrase())}</w:p>"

    def table(self, depth=0):
        cells = []
        for _ in range(self.r.randint(1, 3)):
            inner = self.table(1) if depth == 0 and self.r.random() < 0.25 else ""
            cells.append(f"<w:tc>{self.para(depth)}{inner}{self.para(depth) if inner else ''}</w:tc>")
        return f"<w:tbl><w:tr>{''.join(cells)}</w:tr></w:tbl>"

    def docx(self, path):
        body = [self.table() if self.r.random() < 0.3 else self.para() for _ in range(self.r.randint(3, 8))]
        files = {
            "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           f'<Relationship Id="r1" Type="{REL}/officeDocument" Target="word/document.xml"/></Relationships>',
            "word/document.xml": f"<w:document {NS}><w:body>{''.join(body)}<w:sectPr/></w:body></w:document>",
            "word/header1.xml": f"<w:hdr {NS}><w:p>{self.run(self.phrase())}</w:p></w:hdr>",
            "word/footnotes.xml": f'<w:footnotes {NS}><w:footnote w:id="1"><w:p>{self.run(self.phrase())}</w:p></w:footnote></w:footnotes>',
            "word/media/image1.bin": "untouched bytes",
        }
        with zipfile.ZipFile(path, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)

    # ---- EPUB
    def inline(self, depth=0):
        p = self.phrase()
        return self.r.choice([
            p + " ", f"<em>{p}</em> ", f'<a href="#x">{p}</a> ', f'<span class="c">{p}</span> ',
            f"{p}<br/>{self.phrase()} ", f'<span class="cap">{p[:1]}</span>{p[1:]} ', f"{p}&#160;",
            f'{p} <img src="i.png" alt="x"/> ', f"<b>{p} <i>{self.phrase()}</i></b> " if depth == 0 else p + " ",
            f'{p}<a href="#n"><sup>{self.phrase()}</sup></a> ', f'<a href="#a">{p}</a><a href="#b">{self.phrase()}</a> ',
            f'{p} <math xmlns="http://www.w3.org/1998/Math/MathML"/> {self.phrase()} ',
        ])

    def block(self, depth=0):
        text = "".join(self.inline() for _ in range(self.r.randint(1, 3)))
        choice = self.r.choice(range(12) if depth == 0 else range(4))
        return [
            lambda: f'<p class="b">{text}</p>', lambda: f"<h2>{text}</h2>", lambda: f'<div class="para">{text}</div>',
            lambda: f"<p>{text}</p>",
            lambda: f"<div>{text}{self.block(1)}{self.phrase()}</div>",
            lambda: f"<ul><li>{text}</li><li>{self.phrase()}{self.block(1)}</li></ul>",
            lambda: f"<table><tr><td>{text}</td><td>{self.phrase()}</td></tr></table>",
            lambda: f"<section>{text}</section>",
            lambda: f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><circle r="1"/></svg>{self.phrase()}',
            lambda: f"<div><p>{text}</p>{self.phrase()}</div>",
            lambda: f"<div>{self.phrase()}<p>{text}</p>{self.phrase()}<p>{self.phrase()}</p>{self.phrase()}</div>",
            lambda: f"<ul><li>{text}</li></ul>",
        ][choice]()

    def epub(self, path):
        x = 'xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
        pages = [f'<html {x}><head><title>t</title><link rel="stylesheet" href="s.css"/></head>'
                 f'<body class="m">\n  {"".join(self.block() + chr(10) for _ in range(self.r.randint(2, 6)))}</body></html>'
                 for _ in range(2)]
        files = {
            "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles>'
                                      '<rootfile full-path="O/b.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            "O/b.opf": '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest>'
                       '<item id="b" href="b.xhtml" media-type="application/xhtml+xml"/>'
                       '<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
                       '<item id="n" href="n.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
                       '<item id="t" href="t.ncx" media-type="application/x-dtbncx+xml"/>'
                       '</manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>',
            "O/a.xhtml": pages[0], "O/b.xhtml": pages[1],
            "O/n.xhtml": f'<html {x}><body><nav epub:type="toc"><ol><li><a href="a.xhtml">{self.phrase()}</a></li></ol></nav></body></html>',
            "O/t.ncx": f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap><navPoint><navLabel><text>{self.phrase()}</text>'
                       '</navLabel></navPoint></navMap></ncx>',
            "O/s.css": "p{color:red}",
        }
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            for name, data in files.items():
                z.writestr(name, data)


async def upper(units):
    return [u.upper() for u in units]


def skeleton(data: bytes):
    root = etree.fromstring(data)
    return [(str(el.tag), sorted((k, v) for k, v in el.attrib.items() if not k.endswith("}space"))) for el in root.iter()]


def all_text(data: bytes) -> str:
    root = etree.fromstring(data)
    for el in root.iter("{*}delText"):  # tracked deletions are not visible text
        el.text = ""
    return key("".join(root.itertext()))


def invalid_structure(path: Path) -> dict:
    """How often each way of corrupting a document occurs in it."""
    bad = {}

    def count(what, yes):
        bad[what] = bad.get(what, 0) + bool(yes)

    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name == "word/document.xml":
                root = etree.fromstring(z.read(name))
                for tc in root.iter(f"{w}tc"):
                    count("cell does not end with a paragraph", not len(tc) or tc[-1].tag != f"{w}p")
                for tbl in root.iter(f"{w}tbl"):
                    after = tbl.getnext()
                    count("tables touch", after is not None and after.tag == f"{w}tbl")
                kinds = [f.get(f"{w}fldCharType") for f in root.iter(f"{w}fldChar")]
                count("half a field", kinds.count("begin") != kinds.count("end"))
                starts = len(list(root.iter(f"{w}commentRangeStart")))
                count("half a comment", starts != len(list(root.iter(f"{w}commentRangeEnd"))))
            elif re.search(r"[ab]\.xhtml$", name):
                root = etree.fromstring(z.read(name))
                for ul in root.iter("{*}ul"):
                    count("empty list", not len(ul))
                for p in root.iter("{*}p"):
                    count("paragraph inside a paragraph", any(etree.QName(a).localname == "p" for a in p.iterancestors()))
    return bad


class TestLossless(unittest.TestCase):
    SEEDS = int(os.environ.get("BOOKAPP_FUZZ_SEEDS", "120"))

    def build(self, kind, seed, td):
        src, out = Path(td) / f"s{seed}.{kind}", Path(td) / f"o{seed}.{kind}"
        getattr(Gen(seed), kind)(src)
        translate = format_preserver.translate_docx_in_place if kind == "docx" else format_preserver.translate_epub_in_place
        text = asyncio.run(translate(str(src), str(out), "greek", "english", segment_translator=upper))
        return src, out, text

    def check_translation(self, kind):
        with tempfile.TemporaryDirectory() as td:
            for seed in range(self.SEEDS):
                src, out, text = self.build(kind, seed, td)
                with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
                    self.assertEqual(a.namelist(), b.namelist(), seed)
                    for name in a.namelist():
                        before, after = a.read(name), b.read(name)
                        if not name.endswith((".xml", ".xhtml", ".ncx", ".opf", ".rels")):
                            self.assertEqual(before, after, f"seed {seed}: {name}")
                            continue
                        self.assertEqual(skeleton(before), skeleton(after), f"seed {seed}: markup of {name} changed")
                        self.assertEqual(all_text(before).upper(), all_text(after).upper(),
                                         f"seed {seed}: text of {name} lost or reordered")
                body = [b.text for b in open_package(src).body]
                self.assertEqual([key(p) for p in format_sync.split_paragraphs(text)], [key(t.upper()) for t in body], seed)
                after = open_package(out)
                for block in after.body + after.extra:
                    self.assertFalse(any(c.islower() for c in block.text), f"seed {seed}: untranslated {block.text!r}")

    def test_docx_translation_is_lossless(self):
        self.check_translation("docx")

    def test_epub_translation_is_lossless(self):
        self.check_translation("epub")

    def check_edits(self, kind):
        with tempfile.TemporaryDirectory() as td:
            for seed in range(self.SEEDS):
                rng = random.Random(seed)
                _src, out, text = self.build(kind, seed, td)
                base = invalid_structure(out)
                txt = out.with_suffix(".txt")
                txt.write_text(text, encoding="utf-8")
                for step in range(5):
                    paras = format_sync.split_paragraphs(text)
                    done = []
                    # every second step saves several edits at once
                    for part in range(1 if step % 2 == 0 else rng.randint(2, 4)):
                        i = rng.randrange(len(paras))
                        mark = "Z" + "".join(chr(65 + int(d)) for d in f"{seed}{step}{part}")
                        words = paras[i].split(" ")
                        action = rng.choice(["word", "prefix", "suffix", "cut", "drop", "insert", "append", "many"])
                        done.append(action)
                        if action == "word":
                            words[rng.randrange(len(words))] = mark
                            paras[i] = " ".join(words)
                        elif action == "prefix":
                            paras[i] = f"{mark} {paras[i]}"
                        elif action == "suffix":
                            paras[i] += f" {mark}."
                        elif action == "cut" and len(words) > 2:
                            paras[i] = " ".join(words[1:])
                        elif action == "drop" and len(paras) > 2:
                            paras.pop(i)
                        elif action == "insert":
                            paras.insert(i, f"{mark} INSERTED {step}.")
                        elif action == "append":
                            paras.append(f"{mark} APPENDED.")
                        elif action == "many":
                            paras = [f"{p} {mark}{'X' * (k + 1)}" for k, p in enumerate(paras)]
                    text = "\n\n".join(paras)
                    where = f"{kind} seed {seed} step {step} ({'+'.join(done)})"
                    try:
                        format_sync.sync_text(txt, text, {out})
                    except format_sync.FormatSyncError as e:
                        self.fail(f"{where}: refused: {e}")
                    self.assertEqual([key(b.text) for b in open_package(out).body], [key(p) for p in paras], where)
                    for what, count in invalid_structure(out).items():
                        self.assertLessEqual(count, base.get(what, 0), f"{where}: {what}")

    def test_docx_edits_stay_exact(self):
        self.check_edits("docx")

    def test_epub_edits_stay_exact(self):
        self.check_edits("epub")

    def test_hostile_and_broken_packages(self):
        with tempfile.TemporaryDirectory() as td:
            secret = Path(td) / "secret.txt"
            secret.write_text("TOPSECRET", encoding="utf-8")
            doc = Path(td) / "xxe.docx"
            Gen(1).docx(doc)
            with zipfile.ZipFile(doc) as z:
                files = {n: z.read(n) for n in z.namelist()}
            files["word/document.xml"] = (
                f'<!DOCTYPE d [<!ENTITY x SYSTEM "{secret.as_uri()}">]><w:document {NS}><w:body><w:p><w:r>'
                '<w:t>hello &x;</w:t></w:r></w:p></w:body></w:document>').encode()
            with zipfile.ZipFile(doc, "w") as z:
                for name, data in files.items():
                    z.writestr(name, data)
            self.assertNotIn("TOPSECRET", "".join(b.text for b in open_package(doc).body))
            broken = Path(td) / "broken.epub"
            broken.write_bytes(b"not a zip")
            with self.assertRaises(DocumentError):
                open_package(broken)

    def test_tolerant_of_real_world_xhtml(self):
        with tempfile.TemporaryDirectory() as td:
            book = Path(td) / "messy.epub"
            Gen(2).epub(book)
            with zipfile.ZipFile(book) as z:
                files = {n: z.read(n) for n in z.namelist()}
            files["O/a.xhtml"] = b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>fish&nbsp;chips &mdash; tea</p></body></html>'
            files["O/b.xhtml"] = b"<html><body><p>unclosed line<br>second line</p></body></html>"
            with zipfile.ZipFile(book, "w") as z:
                for name, data in files.items():
                    z.writestr(name, data)
            texts = [b.text for b in open_package(book).body]
            self.assertIn("chips — tea", texts[0])
            self.assertIn("second line", texts[1])


class TestPreformatted(unittest.TestCase):
    POEM = "The sea was calm at night;\n    my boat was small and white.\n\nI never sailed again,"
    CODE = ("for item in items:\n    print(item)", "pip install requests", "x = the_value",
            "name    age\nAnna    41", "SELECT a FROM the_table")

    def book(self, body):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                       '<rootfiles><rootfile full-path="b.opf"/></rootfiles></container>')
            z.writestr("b.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="a.xhtml" '
                       'media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/></spine></package>')
            z.writestr("a.xhtml", f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>')
        return buf.getvalue()

    def test_poems_are_translated_with_their_layout_and_code_is_untouched(self):
        codes = "".join(f"<pre>{c}</pre>" for c in self.CODE)
        marked = '<pre class="language-text">the cat and the dog were here</pre><pre><code>the end of the file</code></pre>'
        body = f"<p>Before.</p><pre>{self.POEM}\n  <i>not of the sea</i></pre>{codes}{marked}<p>After.</p>"

        async def upper(units):
            return [u.upper() for u in units]

        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "in.epub", Path(td) / "out.epub"
            src.write_bytes(self.book(body))
            text = asyncio.run(format_preserver.translate_epub_in_place(
                str(src), str(out), "english", "greek", segment_translator=upper))
            with zipfile.ZipFile(out) as z:
                page = z.read("a.xhtml").decode("utf-8")
            self.assertIn("THE SEA WAS CALM AT NIGHT;\n    MY BOAT WAS SMALL AND WHITE.\n\nI NEVER SAILED AGAIN,\n  <i>NOT OF THE SEA</i>", page)
            self.assertIn("MY BOAT WAS SMALL AND WHITE.", text)
            for kept in codes.replace("</pre>", "</pre>|").split("|")[:-1] + [marked]:
                self.assertIn(kept, page)

            # the translated poem no longer looks like English prose, and is still editable
            edited = text.replace("BOAT", "SHIP {1}")
            data = format_sync.patch_document(out, text, edited)
            self.assertIn(b"    MY SHIP {1} WAS SMALL AND WHITE.", data)
            out.write_bytes(data)
            added = edited.replace("AFTER.", "NEW.\n\nAFTER.")
            self.assertIn(b"</pre>", format_sync.patch_document(out, edited, added).split(b"NEW.")[0])

    def test_the_book_marks_its_poems_and_code_kept_untranslated_is_reported(self):
        # a concrete poem and a verse of symbols that look like code; the book itself calls them poems
        marked = ('<section xmlns:epub="http://www.idpf.org/2007/ops" epub:type="z3998:poem">'
                  "<pre>x = the sea\n  y = the sky</pre></section>"
                  '<pre class="verse">a | b | c of the night</pre>')
        body = f"<p>Before.</p>{marked}<pre>for item in items:\n    print(item)</pre><pre>pip install requests</pre>"

        async def upper(units):
            return [u.upper() for u in units]

        notes = []
        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "in.epub", Path(td) / "out.epub"
            src.write_bytes(self.book(body))
            asyncio.run(format_preserver.translate_epub_in_place(
                str(src), str(out), "english", "greek", segment_translator=upper, notes=notes))
            with zipfile.ZipFile(out) as z:
                page = z.read("a.xhtml").decode("utf-8")
        self.assertIn("X = THE SEA\n  Y = THE SKY", page)
        self.assertIn("A | B | C OF THE NIGHT", page)
        self.assertIn("for item in items:\n    print(item)", page)
        self.assertEqual(len(notes), 1, notes)
        self.assertTrue(notes[0].startswith("2 "), notes)


if __name__ == "__main__":
    unittest.main()
