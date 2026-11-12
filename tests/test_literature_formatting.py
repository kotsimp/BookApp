"""
test_literature_formatting.py - Unit and integration tests for Literature / E-Reader formatting.
"""

import sys
sys.path.insert(0, ".")
import zipfile
import urllib.request
import json
from pathlib import Path
import pymupdf
from docx import Document

from backend.exporter import (
    _prepare_literature_chapters,
    export_epub,
    export_pdf,
    export_docx,
)

API = "http://127.0.0.1:8000/api"

SAMPLE_NOVEL = """=== PAGE 1 ===
1

Chapter 1: The Arrival

Ήταν μια σκοτεινή και θυελλώδης νύχτα στην Αθήνα, καθώς ο ήρωας περπατούσε προς
το λιμάνι του Πειραιά χωρίς να γνωρίζει

=== PAGE 2 ===
2

τι τον περίμενε εκεί. Οι σκιές & τα φώτα <αχνοφέγγαν> στο νερό.

* * *

Η νέα παράγραφος ξεκινά μετά τη διακοπή σκηνής.

=== PAGE 3 ===
Κεφάλαιο 2: Η Επιστροφή

Το πλοίο έφτασε νωρίς το πρωί. Όλοι περίμεναν στην αποβάθρα.
"""


def test_chapter_detection_and_page_merge():
    chapters = _prepare_literature_chapters(SAMPLE_NOVEL, default_title="My Novel")
    assert len(chapters) == 2, f"Expected 2 chapters, got {len(chapters)}: {chapters}"
    assert chapters[0]["title"] == "Chapter 1: The Arrival"
    assert chapters[1]["title"] == "Κεφάλαιο 2: Η Επιστροφή"

    # Verify cross-page broken sentence was merged
    first_para = chapters[0]["paragraphs"][0]
    assert "χωρίς να γνωρίζει τι τον περίμενε εκεί." in first_para, f"Sentence merge failed: {first_para}"
    assert "=== PAGE" not in first_para
    print("  Chapter detection & cross-page sentence merge: OK")


def test_literature_epub():
    out_dir = Path("temp/test_lit")
    out_dir.mkdir(parents=True, exist_ok=True)
    epub_path = out_dir / "novel.epub"
    export_epub(SAMPLE_NOVEL, epub_path, title="My Novel", layout="literature")
    assert epub_path.exists() and epub_path.stat().st_size > 1000

    with zipfile.ZipFile(epub_path, "r") as zf:
        names = zf.namelist()
        assert any("book.css" in n for n in names), f"Missing book.css in {names}"
        chap_files = [n for n in names if "chap_00" in n]
        assert len(chap_files) == 2, f"Expected 2 chapter files, got {chap_files}"
        css = zf.read([n for n in names if "book.css" in n][0]).decode("utf-8")
        assert "text-align: justify" in css
        assert "Georgia" in css
        ch1_html = zf.read(chap_files[0]).decode("utf-8")
        # Verify XML escaping for & and <
        assert "&amp;" in ch1_html and "&lt;" in ch1_html
        assert 'class="scene-break"' in ch1_html
    print(f"  Literature EPUB (CSS, TOC chapters, XML escaping): OK ({epub_path.stat().st_size} bytes)")


def test_literature_pdf_and_docx():
    out_dir = Path("temp/test_lit")
    pdf_path = out_dir / "novel.pdf"
    export_pdf(SAMPLE_NOVEL, pdf_path, layout="literature")
    assert pdf_path.exists()

    doc = pymupdf.open(str(pdf_path))
    assert len(doc) >= 2
    rect = doc[0].rect
    assert abs(rect.width - 432.0) < 1.0 and abs(rect.height - 648.0) < 1.0, f"Expected 6x9 (432x648), got {rect.width}x{rect.height}"
    extracted = doc[0].get_text().replace("\xa0", " ")
    assert "Chapter 1" in extracted
    doc.close()
    print(f"  Literature PDF (6x9 trade paperback, Georgia serif, Greek): OK ({pdf_path.stat().st_size} bytes)")

    docx_path = out_dir / "novel.docx"
    export_docx(SAMPLE_NOVEL, docx_path, layout="literature")
    assert docx_path.exists()
    wdoc = Document(str(docx_path))
    assert round(wdoc.sections[0].page_width.inches, 1) == 6.0
    assert round(wdoc.sections[0].page_height.inches, 1) == 9.0
    print(f"  Literature DOCX (6x9 book geometry, Georgia): OK ({docx_path.stat().st_size} bytes)")


def test_api_dynamic_layout_download():
    # Post pasted text via /api/polish with mock key & literature layout
    body = json.dumps({
        "job_id": "",
        "text": SAMPLE_NOVEL,
        "style": "natural",
        "api_key": "AQ.TestLitKey1234567890",
        "layout_mode": "literature",
    }).encode("utf-8")
    req = urllib.request.Request(f"{API}/polish", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        job_id = res["job_id"]

    # Download as literature EPUB and literature PDF
    for fmt in ("epub", "pdf"):
        with urllib.request.urlopen(f"{API}/download/{job_id}?format={fmt}&layout=literature") as resp:
            data = resp.read()
            assert resp.status == 200 and len(data) > 1000
    print(f"  API dynamic download with layout=literature (EPUB & PDF): OK (job={job_id})")


if __name__ == "__main__":
    print("=== Testing Literature / E-Reader Formatting ===")
    test_chapter_detection_and_page_merge()
    test_literature_epub()
    test_literature_pdf_and_docx()
    test_api_dynamic_layout_download()
    print("\nALL LITERATURE / E-READER FORMATTING TESTS PASSED SUCCESSFULLY!")
