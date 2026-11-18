"""
test_translation_quality_fixes.py - Comprehensive regression tests for translation,
orthography, grammar, glossary, exporter, and comic balloon rendering quality fixes.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")

import pymupdf as fitz

from backend.ai_polisher import (
    PREFERRED_FLASH_MODELS,
    _extract_gemini_text_and_reason,
    detect_greek_output_issues,
    sanitize_ai_output,
)
from backend.comic_translator import (
    VISION_MODELS_PRIORITY,
    _comic_items_have_corruption,
    _render_vision_balloons_on_page,
    _get_comic_font_path,
    sanitize_comic_dialogue,
)
from backend.exporter import export_docx, export_epub, export_pdf, _split_emphasis_runs
from backend.glossary import apply_glossary, load_glossary
from backend.typography import (
    apply_final_nu_rules,
    fix_broken_hyphens,
    fix_greek_elision_apostrophes,
    format_greek_punctuation,
    format_greek_typography,
)


class TestTranslationQualityFixes(unittest.TestCase):
    def test_1_sanitize_html_special_tokens_editor_notes_and_cot(self):
        # Exact defects reported from Blindsight
        self.assertEqual(
            sanitize_ai_output("Ο Τζιμ είχε την εισπ</i>νευστική του συσκευή στο χέρι."),
            "Ο Τζιμ είχε την εισπνευστική του συσκευή στο χέρι.",
        )
        self.assertEqual(
            sanitize_ai_output("ήθελ<bos>α να βάλεις <i>Θησέας</i> μέσα."),
            "ήθελα να βάλεις Θησέας μέσα.",
        )
        self.assertEqual(
            sanitize_ai_output(
                "Ο Ρόμπερτ Παγκλίνο μίλησε. [Σημείωση επιμελητή: διατηρείται ο Ρόμπερτ Παγκλίνο σύμφωνα με το μητρώο]"
            ),
            "Ο Ρόμπερτ Παγκλίνο μίλησε.",
        )
        cot_leaked = (
            "=== PAGE 245 ===\n\n"
            "Αναλογιστείτε τη φύση της συνείδησης.\n"
            "* *Refining:* Αναλογιστείτε τη φύση...\n"
            "3. **Review against Rules and Dossier:**\n"
            "* No introductory notes or chatter? Checked.\n"
            "* Page markers preserved? Checked.\n"
            "4. **Final Polish:** Proceed to output pure translated text."
        )
        cleaned = sanitize_ai_output(cot_leaked)
        self.assertIn("Αναλογιστείτε τη φύση της συνείδησης.", cleaned)
        self.assertNotIn("Review against Rules", cleaned)
        self.assertNotIn("Final Polish", cleaned)
        self.assertNotIn("Proceed to output", cleaned)

    def test_2_extract_gemini_ignores_thought_parts_and_reads_finish_reason(self):
        payload = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Let me think carefully about translating this..."},
                            {"text": "Το διαστημόπλοιο Θησέας πλησίαζε το Ρόρσαχ."},
                        ]
                    },
                }
            ]
        }
        txt, reason = _extract_gemini_text_and_reason(payload)
        self.assertEqual(reason, "STOP")
        self.assertEqual(txt, "Το διαστημόπλοιο Θησέας πλησίαζε το Ρόρσαχ.")
        self.assertNotIn("Let me think", txt)

    def test_3_detect_greek_corruption_and_truncation(self):
        # Mixed-script Flash-Lite glitches from Blindsight & USS Nebraska
        for bad in [
            "Οι αστרוφυσικούς μελέτησαν το σήμα.",
            "Χρειάζемся περισσότερο χρόνο.",
            "ΕΚΤΟΣ ΑΠΟ ΛΙΓΗ ΚՈΠΩΣΗ!",
            "ΑΝ ΗΜΑΣΤАН ΣΤΗΝ ΕΠΙΦΑΝΕΙΑ.",
            "ΑΠΟΦΕΥΓΕΙΣ ΣΥΡIAKΕΣ ΝΑΡΚΕΣ.",
            "Ο δείκτης έδειχνε অবস্থার στο ταμπλό.",
        ]:
            issues = detect_greek_output_issues(bad, source_text="Clean English source sentence.")
            self.assertTrue(
                any(i.startswith("mixed_script") for i in issues),
                f"Expected mixed_script detection for: {bad} (got {issues})",
            )

        # Clean Greek with standalone acronyms/names MUST pass
        clean = "=== PAGE 1 ===\n\nΤο USS Nebraska εκτόξευσε το C-4 κοντά στον Θησέα.\n\n=== PAGE 2 ===\n\nΗ NASA επιβεβαίωσε το σήμα."
        self.assertEqual(
            detect_greek_output_issues(clean, source_text=clean, expected_pages=[1, 2]),
            [],
        )

        # Missing page marker MUST be flagged
        missing_pg_issues = detect_greek_output_issues(
            "=== PAGE 1 ===\n\nΜόνο η πρώτη σελίδα.",
            source_text="=== PAGE 1 ===\nPage one.\n\n=== PAGE 2 ===\nPage two.",
            expected_pages=[1, 2],
        )
        self.assertTrue(any(i.startswith("missing_pages") for i in missing_pg_issues))

        # Mid-word truncation MUST be flagged
        src_long = "This is a complete English sentence that has plenty of literary narrative content. " * 8
        out_trunc = "Αυτή είναι μια ελληνική πρόταση που κόπηκε απότομα στη μέ"
        trunc_issues = detect_greek_output_issues(out_trunc, source_text=src_long)
        self.assertTrue(any(i.startswith("truncated") for i in trunc_issues))

    def test_4_full_flash_models_prioritized_over_flash_lite(self):
        first_full = next(i for i, m in enumerate(PREFERRED_FLASH_MODELS) if "lite" not in m)
        first_lite = next(i for i, m in enumerate(PREFERRED_FLASH_MODELS) if "lite" in m)
        self.assertLess(first_full, first_lite)
        self.assertNotIn("lite", PREFERRED_FLASH_MODELS[0])

        v_first_full = next(i for i, m in enumerate(VISION_MODELS_PRIORITY) if "lite" not in m)
        v_first_lite = next(i for i, m in enumerate(VISION_MODELS_PRIORITY) if "lite" in m)
        self.assertLess(v_first_full, v_first_lite)
        self.assertNotIn("lite", VISION_MODELS_PRIORITY[0])

    def test_5_greek_privative_me_vs_verbal_min(self):
        # Privative 'μη' before adjectives, participles, adverbs, nouns MUST NOT take final 'ν'
        privative_cases = [
            ("μη απαραίτητα", "μη απαραίτητα"),
            ("μην απαραίτητα", "μη απαραίτητα"),
            ("μη επανδρωμένος", "μη επανδρωμένος"),
            ("μην επανδρωμένος", "μη επανδρωμένος"),
            ("μη επεμβατικές μέθοδοι", "μη επεμβατικές μέθοδοι"),
            ("μην επεμβατικές μέθοδοι", "μη επεμβατικές μέθοδοι"),
            ("μην αποδεκτή λύση", "μη αποδεκτή λύση"),
            ("Μην Εμπορική Χρήση", "Μη Εμπορική Χρήση"),
            ("μην εξουσιοδοτημένη πρόσβαση", "μη εξουσιοδοτημένη πρόσβαση"),
            ("μην τροποποιημένη έκδοση", "μη τροποποιημένη έκδοση"),
            ("μην αποκλειστική άδεια", "μη αποκλειστική άδεια"),
            ("μην ανθρώπινα όντα", "μη ανθρώπινα όντα"),
            ("μην επέμβασης", "μη επέμβασης"),
            ("ΜΗΝ ΠΑΡΑΒΙΑΣΗΣ", "ΜΗ ΠΑΡΑΒΙΑΣΗΣ"),
            ("το μην επανδρωμένο σκάφος", "το μη επανδρωμένο σκάφος"),
            ("μην ευαίσθητα δεδομένα", "μη ευαίσθητα δεδομένα"),
            ("μην πειστική απάντηση", "μη πειστική απάντηση"),
            ("μην ακουστικά σήματα", "μη ακουστικά σήματα"),
            ("μην εικονική πραγματικότητα", "μη εικονική πραγματικότητα"),
        ]
        for inp, exp in privative_cases:
            self.assertEqual(apply_final_nu_rules(inp), exp, f"Failed for: {inp}")

        # Verbal 'μην' MUST still work before vowels & plosives, and drop 'ν' before continuants
        self.assertEqual(apply_final_nu_rules("μη έρθεις"), "μην έρθεις")
        self.assertEqual(apply_final_nu_rules("μη πας"), "μην πας")
        self.assertEqual(apply_final_nu_rules("να μη το ξεχάσεις"), "να μην το ξεχάσεις")
        self.assertEqual(apply_final_nu_rules("μην χάνεις"), "μη χάνεις")
        self.assertEqual(apply_final_nu_rules("μην λες"), "μη λες")

    def test_6_hyphens_elisions_and_greek_question_marks(self):
        self.assertEqual(fix_broken_hyphens("Μας υποσχέ- θηκαν βοήθεια."), "Μας υποσχέθηκαν βοήθεια.")
        self.assertEqual(fix_broken_hyphens("ΕΧΕΙ ΠΛΗΜ-\nΜΥΡΙΣΕΙ Ο ΧΩΡΟΣ."), "ΕΧΕΙ ΠΛΗΜΜΥΡΙΣΕΙ Ο ΧΩΡΟΣ.")
        self.assertEqual(fix_greek_elision_apostrophes("Σ ΑΥΤΗΝ ΤΗ ΜΑΧΗ ΓΙ ΑΥΤΟ"), "Σ' ΑΥΤΗΝ ΤΗ ΜΑΧΗ ΓΙ' ΑΥΤΟ")
        self.assertEqual(format_greek_punctuation("ΤΙ ΕΙΝΑΙ ΑΥΤΟ?!"), "ΤΙ ΕΙΝΑΙ ΑΥΤΟ;!")
        self.assertEqual(format_greek_punctuation("ΠΟΥ ΠΑΜΕ;\n??!!"), "ΠΟΥ ΠΑΜΕ;\n;;!!")

    def test_7_glossary_does_not_corrupt_literature_or_hyphenated_compounds(self):
        # Technical/IT terms must NOT be loaded in literature or comic mode
        lit_g = load_glossary(style="literature")
        self.assertNotIn("pod", lit_g)
        self.assertNotIn("sandbox", lit_g)
        self.assertNotIn("backup", lit_g)

        # Hyphenated compounds MUST NOT be partially substituted even in default mode
        self.assertEqual(apply_glossary("He was a pod-man from birth.", "greek"), "He was a pod-man from birth.")
        self.assertEqual(apply_glossary("This is a royalty-free license.", "greek"), "This is a royalty-free license.")

        # Literature mode preserves English words like sandbox/pod/backup and academic citations
        lit_sample = (
            "Το pod-man και το sandbox έμειναν άθικτα.\n"
            "Libet, B. 1999. Does free will arise freely? Journal of Consciousness Studies 6: 47-57."
        )
        out = apply_glossary(lit_sample, "greek", style="literature")
        self.assertNotIn("Kubernetes", out)
        self.assertNotIn("περιβάλλον απομόνωσης", out)
        self.assertIn("Does free will arise freely?", out)

    def test_8_exporter_strips_html_and_renders_italics_cleanly(self):
        sample = (
            "=== PAGE 1 ===\n\n"
            "ΚΕΦΑΛΑΙΟ 1\n\n"
            "Ο Τζιμ είχε την εισπ</i>νευστική συσκευή στο *Θησέας*.\n\n"
            "* * *\n\n"
            "«*Τι περίμενες;*» ρώτησε και υποσχέ- θηκαν να γυρίσουν."
        )
        runs = _split_emphasis_runs("Στο *Θησέας* όλα ήταν ήσυχα.")
        self.assertEqual(runs, [("Στο ", False, False), ("Θησέας", False, True), (" όλα ήταν ήσυχα.", False, False)])

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            pdf_p = export_pdf(sample, td_p / "book.pdf", layout="literature")
            doc = fitz.open(str(pdf_p))
            pdf_text = "\n".join(pg.get_text() for pg in doc)
            doc.close()
            self.assertIn("εισπνευστική", pdf_text)
            self.assertNotIn("</i>", pdf_text)
            self.assertIn("Θησέας", pdf_text)
            self.assertNotIn("*Θησέας*", pdf_text)
            self.assertIn("υποσχέθηκαν", pdf_text)

            docx_p = export_docx(sample, td_p / "book.docx", layout="literature")
            import docx as pydocx
            d = pydocx.Document(str(docx_p))
            full_d = "\n".join(p.text for p in d.paragraphs)
            self.assertIn("εισπνευστική", full_d)
            self.assertNotIn("*Θησέας*", full_d)
            has_italic_run = any(r.italic and "Θησέας" in r.text for p in d.paragraphs for r in p.runs)
            self.assertTrue(has_italic_run, "Expected real italic run for Θησέας in DOCX")

            epub_p = export_epub(sample, td_p / "book.epub", title="Test", layout="literature")
            import zipfile
            with zipfile.ZipFile(str(epub_p), "r") as zf:
                xhtmls = "\n".join(zf.read(n).decode("utf-8", errors="ignore") for n in zf.namelist() if n.endswith(".xhtml"))
            self.assertIn("<em>Θησέας</em>", xhtmls)
            self.assertIn("εισπνευστική", xhtmls)
            self.assertNotIn("&lt;/i&gt;", xhtmls)

    def test_9_comic_dialogue_sanitizer_and_never_blank_balloons(self):
        # Dialogue sanitizer fixes actual USS Nebraska issues
        self.assertEqual(
            sanitize_comic_dialogue("*ΠΑΝΑΓΙΑ ΜΟΥ! ΕΝΑς ΤΡΕΛΟΣ Σ ΑΥΤΗΝ ΤΗ ΜΑΧΗ?!", "greek"),
            "ΠΑΝΑΓΙΑ ΜΟΥ! ΕΝΑΣ ΤΡΕΛΟΣ Σ' ΑΥΤΗΝ ΤΗ ΜΑΧΗ;!",
        )
        self.assertEqual(
            sanitize_comic_dialogue('ΓΙΑ ΤΑ ΒΙΒΛΙΑ ΙΣΤΟΡΙΑΣ\\', "greek"),
            "ΓΙΑ ΤΑ ΒΙΒΛΙΑ ΙΣΤΟΡΙΑΣ",
        )
        self.assertTrue(
            _comic_items_have_corruption([{"original_text": "fatigue", "translated_text": "ΕΚΤΟΣ ΑΠΟ ΛΙΓΗ ΚՈΠΩΣΗ"}], "greek")
        )
        self.assertTrue(
            _comic_items_have_corruption([{"original_text": "if we were", "translated_text": "ΑΝ ΗΜΑΣΤАН ΣΤΗΝ ΕΠΙΦΑΝΕΙΑ"}], "greek")
        )

        # Render dense USS Nebraska Page 7 & Page 61 balloons in tiny boxes -> MUST NOT BE BLANK!
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        items = [
            {
                # Page 7 dense balloon (~77x45pt)
                "box_2d": [113, 229, 170, 355],
                "translated_text": (
                    "ΑΦΟΥ ΕΧΑΣΑ ΤΡΙΑΚΟΣΙΟΥΣ ΑΝΤΡΕΣ ΚΑΙ ΤΟ ΜΙΣΟ ΜΟΥ ΠΡΟΣΩΠΟ Σ ΑΥΤΗΝ ΤΗ ΜΑΧΗ "
                    "ΓΙΑ ΝΑ ΚΑΤΑΛΑΒΟΥΜΕ ΕΝΑ ΚΤΙΡΙΟ ΠΟΥ ΘΑ ΜΠΟΡΟΥΣΑΜΕ ΝΑ ΕΙΧΑΜΕ ΚΑΨΕΙ ΣΕ ΔΥΟ ΛΕΠΤΑ! "
                    "ΓΙΝΟΜΑΙ ΚΑΤΑΝΟΗΤΟΣ, ΣΥΝΤΑΓΜΑΤΑΡΧΗ;"
                ),
                "bg_color": "#ffffff",
            },
            {
                # Page 61 tiny box (~34x13.5pt)
                "box_2d": [308, 317, 325, 373],
                "translated_text": "...ΤΟ ΕΣΩΤΕΡΙΚΟ ΤΟΥ ΑΔΥΤΟΥ.",
                "bg_color": "#ffffff",
            },
            {
                # Page 7 narrow balloon with long Greek word — must fit unbroken without hyphenation
                "box_2d": [600, 770, 622, 855],
                "translated_text": "ΣΤΟ ΘΗΣΑΥΡΟΦΥΛΑΚΙΟ.",
                "bg_color": "#ffffff",
            },
        ]
        rendered = _render_vision_balloons_on_page(page, items, _get_comic_font_path(), target_lang="greek")
        self.assertEqual(len(rendered), 3)
        page_text = page.get_text()
        doc.close()
        self.assertIn("ΤΡΙΑΚΟΣΙΟΥΣ", page_text, "Dense Page 7 comic balloon must NOT render blank!")
        self.assertIn("ΣΥΝΤΑΓΜΑΤΑΡΧΗ", page_text, "Dense Page 7 comic balloon must render completely!")
        self.assertIn("ΑΔΥΤΟΥ", page_text, "Tiny Page 61 comic balloon must NOT render blank!")
        self.assertIn("ΘΗΣΑΥΡΟΦΥΛΑΚΙΟ", page_text, "Long Greek word should fit unbroken by shrinking font!")

    def test_10_pdf_exporter_no_tofu_glyphs_and_wraps_long_urls_within_margins(self):
        long_url = "http://hctv.humnet.ucla.edu/departments/linguistics/VowelsandConsonants/vowels/chapter12/index_reference_page.html"
        sample = (
            "=== PAGE 1 ===\n\n"
            "ΚΕΦΑΛΑΙΟ 1\n\n"
            "Αυτό το κείμενο περιέχει \ufffd άκυρο σύμβολο, \u200b αόρατο κενό και 🚀 emoji που δεν έχει η Georgia.\n\n"
            f"Βιβλιογραφική παραπομπή: {long_url} (πρόσβαση 2006)."
        )
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            for layout in ("literature", "standard"):
                pdf_p = export_pdf(sample, td_p / f"clean_{layout}.pdf", layout=layout)
                doc = fitz.open(str(pdf_p))
                try:
                    full_txt = "\n".join(pg.get_text() for pg in doc)
                    # Zero missing-glyph tofu boxes (\x00 / \ufffd)
                    self.assertNotIn("\x00", full_txt, f"Missing-glyph tofu \\x00 leaked in {layout} PDF!")
                    self.assertNotIn("\ufffd", full_txt, f"Replacement char leaked in {layout} PDF!")
                    # Every drawn word bounding box MUST fit inside the page width (no right-margin URL clipping)
                    margin_limit = 432.0 - 44.0 if layout == "literature" else 595.0 - 46.0
                    for pg in doc:
                        for w in pg.get_text("words"):
                            x1 = w[2]
                            self.assertLessEqual(
                                x1,
                                margin_limit,
                                f"Token '{w[4]}' clipped past right margin ({x1:.1f} > {margin_limit}) in {layout} PDF!",
                            )
                finally:
                    doc.close()


if __name__ == "__main__":
    unittest.main()
