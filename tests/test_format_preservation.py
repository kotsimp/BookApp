# tests/test_format_preservation.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import docx
from backend.format_preserver import translate_docx_in_place
from backend.exporter import export_pdf

# 1. Test DOCX format preservation
print("=== Test 1: DOCX Format Preservation ===")
doc = docx.Document()
h = doc.add_heading("Project Overview", level=1)
p1 = doc.add_paragraph("This is the intro paragraph.")
r1 = p1.add_run(" Note: ")
r1.bold = True
r2 = p1.add_run("This text must be preserved with exact styling.")
r2.italic = True
r2.font.name = "Arial"

test_in_docx = "temp/test_in_format.docx"
test_out_docx = "temp/test_out_format.docx"
doc.save(test_in_docx)

txt_result = asyncio.run(translate_docx_in_place(
    test_in_docx, test_out_docx, "english", "greek"
))

# Inspect output docx
out_doc = docx.Document(test_out_docx)
print("  Output paragraphs count:", len(out_doc.paragraphs))
assert len(out_doc.paragraphs) >= 2
assert out_doc.paragraphs[0].style.name == "Heading 1"
assert any(r.bold for r in out_doc.paragraphs[1].runs)
assert any(r.italic for r in out_doc.paragraphs[1].runs)
print("  DOCX Heading 1 preserved: OK")
print("  DOCX Bold/Italic runs preserved: OK")
print("  DOCX in-place translation: PASSED!")

# 2. Test Rich PDF export
print("\n=== Test 2: Rich PDF Export with Headings ===")
test_pdf_out = Path("temp/test_rich_headings.pdf")
sample_text = """
============================================================
PAGE 1
============================================================

ΥΠΗΡΕΣΙΑΚΟ ΣΗΜΕΙΩΜΑ

ΠΡΟΣ: Διευθυντή Εκπαίδευσης
ΑΠΟ: Τμήμα Πληροφορικής
ΘΕΜΑ: Προμήθεια εξοπλισμού

Σας γνωρίζουμε ότι κρίνεται αναγκαία η προμήθεια και εγκατάσταση συστήματος αδιάλειπτης παροχής ενέργειας.

Η ανάγκη αυτή προκύπτει από τις πολλαπλές διακοπές ρεύματος.
"""
pdf_path = export_pdf(sample_text, test_pdf_out)
assert pdf_path.exists()
assert pdf_path.stat().st_size > 50000 # has embedded unicode font
print(f"  Rich PDF created: OK ({pdf_path.stat().st_size} bytes)")
print("  PDF export: PASSED!")

print("\nALL FORMAT PRESERVATION TESTS PASSED!")
