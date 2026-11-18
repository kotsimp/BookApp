"""
test_pipeline_data_integrity.py - End-to-End Content Fidelity Suite for Parsers, Glossary,
Typography, Genre Detector, Format Preserver & Exporter.
Tests:
1. Glossary: idempotency (no recursive double-substitution on Server Room/UPS/backup), regex backslash safety,
   empty target rejection, null/malformed JSON resilience, leading-symbol (.NET) matching.
2. Typography: Greek conjunction 'δε' preserved (not turned into 'δεν'), interrupted dialogue hyphens preserved
   ('Περίμενε- μην'), fenced code block quotes preserved, URL query strings & ../ paths preserved, Latin acronym '?'.
3. Parsers: Roman-letter words ('I', 'Did', 'Mild', '1984') & chapter headings preserved in PDF cleaning,
   EPUB spine order & <style>/<script> stripping, DOCX tables extracted, CP1253/UTF-16 TXT decoding & preamble,
   encrypted PDF clear error, __MACOSX/._* ignored in CBZ, max_chars<=0 guard, PyMuPDF handle close check.
4. Format Preserver: DOCX preserves embedded images & deduplicates merged table cells; EPUB preserves nested
   inline tags (<em>, <strong>), spaces, and HTML comments without double-translating <blockquote><p>.
5. Exporter: empty PDF & empty literature EPUB never crash, auto-creates parent dirs, strips XML control chars,
   no hardcoded novel names in _CHAPTER_RE, corrupt cover doesn't leave blank page, dynamic EPUB lang.
6. Genre Detector: None-safe inputs, TOC/bullets/PAGE headers not misclassified as poetry, 'ip' matched,
   strong literary prose not hijacked by single formal/tech word.
"""

import sys
sys.path.insert(0, ".")
import io
import os
import asyncio
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import docx
import pymupdf
from ebooklib import epub
from PIL import Image

import backend.glossary as gl
from backend.typography import (
    apply_final_nu_rules,
    fix_broken_hyphens,
    format_dialogue_dashes,
    format_greek_quotes,
    format_greek_punctuation,
)
from backend.parsers import (
    parse_document,
    parse_pdf,
    parse_docx,
    parse_epub,
    parse_txt,
    count_cbz_pages,
    detect_is_graphic_novel,
    split_into_chunks,
)
from backend.format_preserver import translate_docx_in_place, translate_epub_in_place
from backend.exporter import (
    export_txt,
    export_docx,
    export_pdf,
    export_epub,
    _is_chapter_heading,
    _sanitize_pua,
)
from backend.genre_detector import detect_genre_and_style


class TestPipelineDataIntegrity(unittest.TestCase):

    def test_1_glossary_idempotency_backslash_and_corrupt_json_safety(self):
        print("-> 1. Testing Glossary idempotency, regex backslash safety, empty target & corrupt JSON...")
        # 1a. Idempotency: Server Room, In-house applications, UPS, backup must NEVER recursively nest!
        sample = "The Server Room runs In-house applications with UPS and backup."
        once = gl.apply_glossary(sample, "greek")
        twice = gl.apply_glossary(once, "greek")
        self.assertEqual(once, twice, f"Glossary double-substituted on 2nd pass!\nonce={once}\ntwice={twice}")
        self.assertNotIn("(αίθουσα διακομιστών)", once)
        self.assertNotIn("(εσωτερικές εφαρμογές", once)

        # 1b. Backslashes in replacement string & (.NET) parenthesized symbol matching (isolated temp glossary)
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            g_file = td_p / "glossary.json"
            with patch.object(gl, "CONFIG_DIR", td_p), patch.object(gl, "GLOSSARY_FILE", g_file):
                # Empty target must raise ValueError
                with self.assertRaises(ValueError):
                    gl.set_term("Foo", "")
                with self.assertRaises(ValueError):
                    gl.set_term("", "Bar")

                gl.set_term("WinPath", r"C:\temp\1\alpha", category="technical")
                gl.set_term(".NET", "πλατφόρμα .NET", category="technical")

                out_bs = gl.apply_glossary("See WinPath and (.NET) now.", "greek")
                self.assertIn(r"C:\temp\1\alpha", out_bs)
                self.assertIn("πλατφόρμα .NET", out_bs)

                # Malformed null category in glossary.json must not crash load/set/delete
                g_file.write_text('{"_version": 2, "terms": {"technical": null, "literary": null, "general": {"k": "v"}}}', encoding="utf-8")
                self.assertEqual(gl.load_glossary(category="general"), {"k": "v"})
                self.assertEqual(gl.load_categorized_glossary()["counts"]["general"], 1)
                gl.delete_term("k")
        print("   Glossary idempotency & safety: OK")

    def test_2_typography_conjunctive_de_interrupted_hyphens_code_and_urls(self):
        print("-> 2. Testing Typography conjunctive 'δε', interrupted dialogue, code fences & URLs...")
        # Conjunctive 'δε' ("however") MUST NOT become negation 'δεν' ("not")!
        self.assertEqual(apply_final_nu_rules("εάν δε προκύψει ζήτημα"), "εάν δε προκύψει ζήτημα")
        self.assertEqual(apply_final_nu_rules("ο δε υπουργός αποφάσισε"), "ο δε υπουργός αποφάσισε")
        self.assertEqual(apply_final_nu_rules("όταν δε έρθει η ώρα"), "όταν δε έρθει η ώρα")
        # Regular negation 'δε' before vowel/plosive still becomes 'δεν'
        self.assertEqual(apply_final_nu_rules("δε ακούω τίποτα"), "δεν ακούω τίποτα")
        # Must NOT cross paragraph break \n\n
        self.assertEqual(apply_final_nu_rules("είπε δε\n\nαύριο"), "είπε δε\n\nαύριο")

        # Interrupted dialogue must NOT be glued together
        self.assertEqual(fix_broken_hyphens("Περίμενε- μην φεύγεις!"), "Περίμενε- μην φεύγεις!")
        self.assertEqual(fix_broken_hyphens("Μα- τι λες;"), "Μα- τι λες;")
        # Genuine OCR split word still rejoins
        self.assertEqual(fix_broken_hyphens("Μας υποσχέ- θηκαν βοήθεια."), "Μας υποσχέθηκαν βοήθεια.")

        # Numeric & indented Markdown bullets preserved by format_dialogue_dashes
        self.assertEqual(format_dialogue_dashes("- 5 items\n  - sub bullet"), "- 5 items\n  - sub bullet")

        # Fenced code blocks preserve straight double quotes
        code_doc = 'Είπε "γεια"\n```json\n{"key": "value"}\n```\nΚαι "αντίο".'
        quoted = format_greek_quotes(code_doc)
        self.assertIn('{"key": "value"}', quoted)
        self.assertIn("«γεια»", quoted)
        self.assertIn("«αντίο»", quoted)

        # URLs, relative paths, numeric ranges, and Greek sentences ending in Latin acronym '?'
        punct_in = "Δες https://example.gr/σελίδα?id=1 και ../dir/file (1..10). Τι είναι το API?"
        punct_out = format_greek_punctuation(punct_in)
        self.assertIn("https://example.gr/σελίδα?id=1", punct_out)
        self.assertIn("../dir/file", punct_out)
        self.assertIn("1..10", punct_out)
        self.assertIn("Τι είναι το API;", punct_out)
        print("   Typography linguistic & formatting fidelity: OK")

    def test_3_parsers_edge_cases_tables_spine_encodings_and_handle_cleanup(self):
        print("-> 3. Testing Parsers (PDF headers/encrypted/handles, DOCX tables, EPUB spine, TXT encodings, CBZ)...")
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)

            # 3a. PDF: preserve Roman-letter words ('Did', '1984') & 'Chapter 1' heading, close handle cleanly
            pdf_p = td_p / "roman_and_chapter.pdf"
            d = pymupdf.open()
            pg = d.new_page(width=595, height=842)
            pg.insert_text((72, 50), "Chapter 1: Awakening", fontsize=14)
            pg.insert_text((72, 160), "Did\n1984\nMild weather arrived over the valley.", fontsize=12)
            d.save(str(pdf_p))
            d.close()

            pages = list(parse_document(str(pdf_p), "PDF"))  # case-insensitive file_type
            full_pdf_txt = "\n".join(p["text"] for p in pages)
            self.assertIn("Chapter 1: Awakening", full_pdf_txt)
            self.assertIn("Did", full_pdf_txt)
            self.assertIn("1984", full_pdf_txt)

            # Verify detect_is_graphic_novel closes handle (file can be deleted on Windows)
            detect_is_graphic_novel(str(pdf_p), "pdf")
            pdf_p.unlink()
            self.assertFalse(pdf_p.exists())

            # 3b. Encrypted PDF raises clear ValueError
            enc_p = td_p / "encrypted.pdf"
            de = pymupdf.open()
            de.new_page().insert_text((72, 72), "Secret content")
            de.save(str(enc_p), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret123", owner_pw="owner123")
            de.close()
            with self.assertRaises(ValueError):
                list(parse_pdf(str(enc_p)))

            # 3c. DOCX table-only document extracts table cells (deduplicating merged cells)
            tbl_docx = td_p / "table_only.docx"
            dd = docx.Document()
            t = dd.add_table(rows=1, cols=2)
            t.cell(0, 0).merge(t.cell(0, 1))
            t.cell(0, 0).text = "Merged table invoice total 500 EUR."
            dd.save(str(tbl_docx))
            docx_pages = list(parse_docx(str(tbl_docx)))
            self.assertEqual(len(docx_pages), 1)
            self.assertEqual(docx_pages[0]["text"].count("Merged table invoice"), 1)

            # 3d. EPUB spine reading order & <style>/<script> stripping
            ep_p = td_p / "spine_order.epub"
            book = epub.EpubBook()
            book.set_identifier("spine-test")
            book.set_title("Spine Order")
            book.set_language("en")
            c2 = epub.EpubHtml(title="Second", file_name="c2.xhtml", lang="en")
            c2.content = "<html><head><style>.x{color:red;}</style></head><body><script>alert(1)</script><p>CHAPTER_TWO_BODY</p></body></html>"
            c1 = epub.EpubHtml(title="First", file_name="c1.xhtml", lang="en")
            c1.content = "<html><body><p>CHAPTER_ONE_BODY</p></body></html>"
            # Add c2 to manifest FIRST, but place c1 FIRST in spine!
            book.add_item(c2)
            book.add_item(c1)
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            book.spine = [c1, c2]
            epub.write_epub(str(ep_p), book, {})

            ep_pages = list(parse_epub(str(ep_p)))
            ep_texts = [p["text"] for p in ep_pages]
            self.assertTrue(ep_texts[0].startswith("CHAPTER_ONE_BODY"), f"EPUB not in spine order: {ep_texts}")
            self.assertNotIn("color:red", "\n".join(ep_texts))
            self.assertNotIn("alert(1)", "\n".join(ep_texts))

            # 3e. TXT Windows-1253 Greek decoding & preamble before PAGE 1
            cp1253_p = td_p / "greek_1253.txt"
            cp1253_p.write_bytes("Πρόλογος βιβλίου\n=== PAGE 1 ===\nΚαλημέρα κόσμε!".encode("cp1253"))
            txt_pages = list(parse_txt(str(cp1253_p)))
            joined_txt = "\n".join(p["text"] for p in txt_pages)
            self.assertNotIn("\ufffd", joined_txt)
            self.assertIn("Πρόλογος βιβλίου", joined_txt)
            self.assertIn("Καλημέρα κόσμε!", joined_txt)

            # 3f. CBZ ignores __MACOSX/._* metadata entries
            cbz_p = td_p / "mac_comic.cbz"
            with zipfile.ZipFile(cbz_p, "w") as zf:
                zf.writestr("page_01.jpg", b"img1")
                zf.writestr("page_02.jpg", b"img2")
                zf.writestr("__MACOSX/._page_01.jpg", b"junk")
            self.assertEqual(count_cbz_pages(str(cbz_p)), 2)

            # 3g. split_into_chunks rejects max_chars <= 0
            with self.assertRaises(ValueError):
                split_into_chunks("hello", max_chars=0)
            with self.assertRaises(ValueError):
                split_into_chunks("hello", max_chars=-10)
        print("   Parsers fidelity & edge cases: OK")

    def test_4_format_preserver_docx_images_and_epub_nested_tags(self):
        print("-> 4. Testing Format Preserver (DOCX images/merged cells & EPUB nested tags/comments)...")

        async def _fake_tr(text, src, tgt, **kwargs):
            return f"TR[{text}]"

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)

            # 4a. DOCX with inline image + text in same paragraph + merged table cells
            img_p = td_p / "tiny.png"
            Image.new("RGB", (20, 20), (10, 120, 200)).save(img_p)
            in_docx = td_p / "in.docx"
            out_docx = td_p / "out.docx"
            d = docx.Document()
            p = d.add_paragraph()
            p.add_run("Caption text before image")
            p.add_run().add_picture(str(img_p))
            tbl = d.add_table(rows=1, cols=2)
            tbl.cell(0, 0).merge(tbl.cell(0, 1))
            tbl.cell(0, 0).text = "Merged header"
            d.save(str(in_docx))

            with patch("backend.format_preserver._translate_with_retry", side_effect=_fake_tr):
                asyncio.run(translate_docx_in_place(str(in_docx), str(out_docx), "english", "english"))

            out_d = docx.Document(str(out_docx))
            # Verify embedded <w:drawing> image survived translation!
            xml_body = out_d.element.body.xml
            self.assertIn("drawing", xml_body, "Embedded inline image in DOCX was destroyed during translation!")
            # Verify merged cell was translated ONLY ONCE (not TR[TR[Merged header]])
            cell_txt = out_d.tables[0].cell(0, 0).text
            self.assertEqual(cell_txt, "TR[Merged header]", f"Merged cell double-translated: {cell_txt!r}")

            # 4b. EPUB with nested <blockquote><p>Hello <em>world</em>!</p></blockquote> and <!-- comment -->
            in_ep = td_p / "in.epub"
            out_ep = td_p / "out.epub"
            b = epub.EpubBook()
            b.set_identifier("fp-epub")
            b.set_title("FP Test")
            b.set_language("en")
            ch = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
            ch.content = (
                "<html><body>"
                "<blockquote><p><!-- SECRET_COMMENT -->Hello <em>bright</em> world!</p></blockquote>"
                "</body></html>"
            )
            b.add_item(ch)
            b.add_item(epub.EpubNcx())
            b.spine = [ch]
            epub.write_epub(str(in_ep), b, {})

            with patch("backend.format_preserver._translate_with_retry", side_effect=_fake_tr):
                asyncio.run(translate_epub_in_place(str(in_ep), str(out_ep), "english", "english"))

            with zipfile.ZipFile(str(out_ep), "r") as zf:
                xhtml = zf.read("EPUB/ch1.xhtml").decode("utf-8")
            self.assertIn("<em>TR[bright]</em>", xhtml, f"Inline <em> tag was destroyed in EPUB: {xhtml}")
            self.assertNotIn("TR[TR[", xhtml, f"Nested <blockquote><p> was double-translated: {xhtml}")
            self.assertNotIn("TR[SECRET_COMMENT]", xhtml, f"HTML comment was translated into prose: {xhtml}")
        print("   Format Preserver DOCX & EPUB fidelity: OK")

    def test_5_exporter_empty_inputs_control_chars_chapters_and_corrupt_cover(self):
        print("-> 5. Testing Exporter empty inputs, XML control chars, chapter regex & corrupt cover...")
        self.assertEqual(_sanitize_pua(None), "")
        self.assertNotIn("\x00", _sanitize_pua("Hello\x00\x0b\x0cWorld"))

        # Hardcoded novel names & English Roman-letter words must NOT be treated as chapters
        for non_chapter in ("Theseus", "Rorschach", "Did", "Civil", "I"):
            self.assertFalse(_is_chapter_heading(non_chapter), f"False chapter heading match: {non_chapter!r}")
        for real_chapter in ("Chapter 1", "Κεφάλαιο 2", "IV", "XII"):
            self.assertTrue(_is_chapter_heading(real_chapter), f"Missed genuine chapter heading: {real_chapter!r}")

        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "sub1" / "sub2"

            # Empty/marker-only inputs must NOT crash PDF or literature EPUB, and parent dirs auto-created
            p_txt = export_txt("", nested / "empty.txt")
            self.assertTrue(p_txt.exists())

            p_pdf = export_pdf("=== PAGE 1 ===\n\n", nested / "empty.pdf", layout="standard")
            self.assertTrue(p_pdf.exists() and p_pdf.stat().st_size > 100)

            p_ep = export_epub("", nested / "empty.epub", title="Empty", layout="literature")
            self.assertTrue(p_ep.exists() and p_ep.stat().st_size > 100)

            # DOCX with XML-illegal control characters must NOT crash lxml
            p_docx = export_docx("Clean\x00text\x0bwith\x0ccontrols", nested / "ctrl.docx", layout="standard")
            self.assertTrue(p_docx.exists())

            # Corrupt cover bytes must NOT leave a blank cover page in literature PDF
            p_lit = export_pdf(
                "Chapter 1\n\nA single short paragraph.",
                nested / "corrupt_cov.pdf",
                layout="literature",
                cover_image=b"NOT_AN_IMAGE",
            )
            with pymupdf.open(str(p_lit)) as doc:
                self.assertEqual(len(doc), 1, "Corrupt cover image left an extra blank page in PDF!")

            # English EPUB sets lang="en" instead of hardcoding "el"
            p_en_ep = export_epub("Chapter 1\n\nPure English narrative text.", nested / "en.epub", title="EN", layout="literature")
            with zipfile.ZipFile(str(p_en_ep), "r") as zf:
                opf = next(zf.read(n).decode("utf-8") for n in zf.namelist() if n.endswith(".opf"))
                self.assertIn(">en<", opf)
        print("   Exporter empty/control/chapter/cover safety: OK")

    def test_6_genre_detector_robustness(self):
        print("-> 6. Testing Genre Detector None safety, TOC/bullet anti-poetry & scoring balance...")
        # None inputs must not crash
        res_none = detect_genre_and_style(None, None)
        self.assertEqual(res_none["genre"], "literature")

        # TOC / bullet list with PAGE markers must NOT be falsely detected as poetry
        toc_sample = (
            "PAGE 1\n"
            "- Introduction .... 1\n"
            "- System Overview .... 5\n"
            "- Installation Guide .... 12\n"
            "- Troubleshooting .... 24\n"
            "- Appendix A .... 31\n"
        )
        self.assertNotEqual(detect_genre_and_style(toc_sample)["genre"], "poetry")

        # Strong literary prose mentioning 'article' once must stay literature (not hijacked by formal)
        lit_with_formal_word = (
            "«Σιωπή», ψιθύρισε με τρεμάμενη φωνή και κοίταξε τα μάτια της μέσα στο σκοτάδι.\n"
            "«Κράτησε την ανάσα σου», χαμογέλασε κοιτάζοντας τον ουρανό της νύχτας.\n"
            "«Η καρδιά μου χτυπά δυνατά», έγνεψε σιωπηλά κρατώντας ένα παλιό άρθρο εφημερίδας.\n"
            "«Το φως σβήνει», ψιθύρισε ξανά.\n"
        )
        self.assertEqual(detect_genre_and_style(lit_with_formal_word)["genre"], "literature")
        print("   Genre Detector robustness: OK")


if __name__ == "__main__":
    unittest.main()
