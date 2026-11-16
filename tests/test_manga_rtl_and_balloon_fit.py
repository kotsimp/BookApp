"""
test_manga_rtl_and_balloon_fit.py - Unit & Functional Tests for Manga RTL Support & Comic Balloon Fit.
Tests:
1. Speech balloon clustering with standard LTR vs Manga RTL reading order.
2. Balloon fit-to-box font scale down.
3. Fixed-layout comic EPUB export with RTL page progression metadata.
"""

import sys
sys.path.insert(0, ".")
import unittest
from pathlib import Path
import pymupdf

from backend.comic_translator import _cluster_text_into_balloons
from backend.exporter import export_comic_epub


class TestMangaRTLAndBalloonFit(unittest.TestCase):

    def test_reading_order_ltr_vs_rtl(self):
        print("-> 1. Testing Speech Balloon Reading Order (LTR vs Manga RTL)...")
        # Define 2 text blocks at the same vertical height (y0=100, y1=150)
        # Block Left: x0=50, x1=150
        # Block Right: x0=400, x1=500
        block_left = (50, 100, 150, 150, "Left Balloon Speech", 0, 0)
        block_right = (400, 100, 500, 150, "Right Balloon Speech", 0, 0)
        blocks = [block_left, block_right]

        # In standard LTR: Left should come first
        clusters_ltr = _cluster_text_into_balloons(blocks, reading_direction="ltr")
        self.assertEqual(len(clusters_ltr), 2)
        self.assertEqual(clusters_ltr[0]["text"], "Left Balloon Speech")
        self.assertEqual(clusters_ltr[1]["text"], "Right Balloon Speech")

        # In Manga RTL: Right should come first!
        clusters_rtl = _cluster_text_into_balloons(blocks, reading_direction="rtl")
        self.assertEqual(len(clusters_rtl), 2)
        self.assertEqual(clusters_rtl[0]["text"], "Right Balloon Speech")
        self.assertEqual(clusters_rtl[1]["text"], "Left Balloon Speech")

        print("   Reading order LTR vs RTL: OK")

    def test_balloon_fit_to_box_scaling(self):
        print("-> 2. Testing Balloon Fit-to-Box Text Fitting...")
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        box = pymupdf.Rect(50, 50, 150, 90)  # Compact balloon box: 100x40 pt

        short_text = "Γεια σου!"
        long_text = "Αυτή είναι μια πολύ μεγάλη πρόταση διαλόγου που κανονικά δεν θα χωρούσε με μεγάλη γραμματοσειρά μέσα στο μικρό μπαλονάκι."

        # Short text fits at 12pt
        rc_short = page.insert_textbox(box, short_text, fontsize=12)
        self.assertGreaterEqual(rc_short, 0)

        # Long text scales down
        fitted = False
        chosen_fs = None
        for fs in [16, 14, 12, 10, 8, 7, 6, 5.5]:
            rc = page.insert_textbox(box, long_text, fontsize=fs)
            if rc >= 0:
                fitted = True
                chosen_fs = fs
                break

        self.assertTrue(fitted)
        self.assertLessEqual(chosen_fs, 8)
        print(f"   Fit-to-box scaling (scaled down to {chosen_fs}pt): OK")

    def test_comic_epub_rtl_export(self):
        print("-> 3. Testing Comic EPUB RTL Page Progression Export...")
        tmp_dir = Path("temp/test_manga_tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # Create 2-page mock comic PDF
        doc = pymupdf.open()
        p1 = doc.new_page(width=300, height=450)
        p1.draw_rect(pymupdf.Rect(20, 20, 280, 430), color=(1, 0, 0), fill=(1, 0.9, 0.9))
        p2 = doc.new_page(width=300, height=450)
        p2.draw_rect(pymupdf.Rect(20, 20, 280, 430), color=(0, 0, 1), fill=(0.9, 0.9, 1))

        pdf_path = tmp_dir / "manga_test.pdf"
        doc.save(str(pdf_path))
        doc.close()

        epub_path = tmp_dir / "manga_test.epub"
        out = export_comic_epub(pdf_path, epub_path, title="Manga Episode 1", reading_direction="rtl")

        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)

        # Check inside epub archive for rtl metadata
        import zipfile
        with zipfile.ZipFile(str(out), "r") as zf:
            opf_names = [n for n in zf.namelist() if n.endswith(".opf")]
            self.assertTrue(len(opf_names) > 0)
            opf_content = zf.read(opf_names[0]).decode("utf-8")
            self.assertIn("page-progression-direction", opf_content)

        print("   Comic EPUB RTL export: OK")


if __name__ == "__main__":
    unittest.main()
