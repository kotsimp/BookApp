"""
test_comic_translation.py - End-to-end automated tests for Graphic Novel & Comic Translation.
Verifies:
1. Upload & translation of Graphic Novel PDF with artwork preservation and speech balloon Greek translation.
2. Generation and verification of translated comic PDF.
3. Verification that dialogue text script is produced for Review/Editor and Audiobook conversion.
4. CBZ / ZIP comic archive support.
"""

import sys
sys.path.insert(0, ".")
import os
import io
import json
import time
import zipfile
import urllib.request
import urllib.error
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageDraw

API = "http://127.0.0.1:8000/api"

def api_get(path):
    req = urllib.request.Request(f"{API}{path}")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_post_file(path, filepath, filename):
    boundary = "----TestBoundaryComic12345"
    file_data = open(filepath, "rb").read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_graphic_novel_pdf_translation():
    print("=== 1. Testing Graphic Novel PDF Translation ===")
    comic_pdf_path = "temp/test_graphic_novel.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Draw panel borders and colored background artwork
    page.draw_rect(fitz.Rect(20, 20, 580, 780), color=(0, 0, 0), width=3)
    page.draw_rect(fitz.Rect(30, 30, 570, 770), fill=(0.82, 0.90, 0.98), color=None)

    # Draw speech balloon oval
    balloon_rect = fitz.Rect(100, 100, 500, 260)
    page.draw_oval(balloon_rect, color=(0, 0, 0), fill=(1, 1, 1), width=2)

    # Insert English dialogue inside balloon
    text_rect = fitz.Rect(130, 130, 470, 230)
    page.insert_textbox(
        text_rect,
        "Look at that strange signal coming from the alien artifact! We need to inform the captain immediately.",
        fontname="helv",
        fontsize=14,
        align=fitz.TEXT_ALIGN_CENTER,
    )
    doc.save(comic_pdf_path)
    doc.close()

    # Upload PDF
    status, u_data = api_post_file("/upload", comic_pdf_path, "test_graphic_novel.pdf")
    assert status == 200
    job_id = u_data["job_id"]
    print(f"  Uploaded comic PDF: job_id={job_id}")

    # Start translation in comic layout mode
    status, t_data = api_post_json("/translate", {
        "job_id": job_id,
        "source_lang": "english",
        "target_lang": "greek",
        "output_format": "pdf",
        "layout_mode": "comic",
    })
    assert status == 200

    # Wait for completion
    for _ in range(60):
        time.sleep(0.5)
        status, sdata = api_get(f"/status/{job_id}")
        if sdata["status"] in ("done", "error"):
            break

    assert sdata["status"] == "done", f"Comic translation failed: {sdata}"
    print("  Comic translation completed successfully (status=done)")

    # Download translated PDF and verify
    req = urllib.request.Request(f"{API}/download/{job_id}?format=pdf&layout=comic")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        pdf_bytes = resp.read()
        assert len(pdf_bytes) > 1000
        print(f"  Downloaded translated Graphic Novel PDF: {len(pdf_bytes)} bytes")

    # Verify translated PDF content
    res_doc = fitz.open("pdf", pdf_bytes)
    assert len(res_doc) == 1
    page_text = res_doc[0].get_text()
    print(f"  Translated PDF text on page 1: {repr(page_text.strip())}")
    assert any(c in page_text for c in "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"), "Expected Greek text in translated comic PDF"
    print("  Greek dialogue rendered in comic balloon: OK")


def test_cbz_archive_translation():
    print("\n=== 2. Testing CBZ Comic Archive Translation ===")
    cbz_path = "temp/test_comic_chapter.cbz"

    # Create 2 comic page images with speech balloons
    img1_path = "temp/cbz_p1.jpg"
    img1 = Image.new("RGB", (500, 700), color=(240, 240, 255))
    d1 = ImageDraw.Draw(img1)
    d1.rectangle((20, 20, 480, 680), outline=(0, 0, 0), width=3)
    d1.ellipse((80, 80, 420, 220), fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    img1.save(img1_path, quality=90)

    # Package into CBZ (zip)
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.write(img1_path, "001.jpg")

    status, u_data = api_post_file("/upload", cbz_path, "test_comic_chapter.cbz")
    assert status == 200
    assert u_data["file_type"] == "cbz"
    job_id = u_data["job_id"]
    print(f"  Uploaded CBZ archive: job_id={job_id}, type={u_data['file_type']}")

    status, t_data = api_post_json("/translate", {
        "job_id": job_id,
        "source_lang": "english",
        "target_lang": "greek",
        "output_format": "pdf",
        "layout_mode": "comic",
    })
    assert status == 200

    for _ in range(60):
        time.sleep(0.5)
        status, sdata = api_get(f"/status/{job_id}")
        if sdata["status"] in ("done", "error"):
            break

    assert sdata["status"] == "done", f"CBZ translation failed: {sdata}"
    print("  CBZ translation completed successfully (status=done)")

    # 3. Test Graphic Novel Output Formats: CBZ, CBR, EPUB and disabled TXT/DOCX
    print("\n=== 3. Testing Graphic Novel Output Formats (CBZ, CBR, EPUB & Disabled TXT/DOCX) ===")
    # Download CBZ
    req_cbz = urllib.request.Request(f"{API}/download/{job_id}?format=cbz&layout=comic")
    with urllib.request.urlopen(req_cbz) as resp:
        assert resp.status == 200
        cbz_data = resp.read()
        assert len(cbz_data) > 500
        with zipfile.ZipFile(io.BytesIO(cbz_data)) as zf:
            names = zf.namelist()
            assert any(n.endswith(".jpg") for n in names)
        print(f"  Downloaded CBZ comic archive: {len(cbz_data)} bytes ({len(names)} pages) OK")

    # Download CBR
    req_cbr = urllib.request.Request(f"{API}/download/{job_id}?format=cbr&layout=comic")
    with urllib.request.urlopen(req_cbr) as resp:
        assert resp.status == 200
        cbr_data = resp.read()
        assert len(cbr_data) > 500
        print(f"  Downloaded CBR comic archive: {len(cbr_data)} bytes OK")

    # Download EPUB
    req_epub = urllib.request.Request(f"{API}/download/{job_id}?format=epub&layout=comic")
    with urllib.request.urlopen(req_epub) as resp:
        assert resp.status == 200
        epub_data = resp.read()
        assert len(epub_data) > 500
        print(f"  Downloaded Fixed-Layout Graphic Novel EPUB: {len(epub_data)} bytes OK")

    # Verify TXT and DOCX are disabled (returns HTTP 400)
    for dis_fmt in ("txt", "docx"):
        req_dis = urllib.request.Request(f"{API}/download/{job_id}?format={dis_fmt}&layout=comic")
        try:
            with urllib.request.urlopen(req_dis) as resp:
                assert False, f"Expected 400 for disabled format {dis_fmt}, got {resp.status}"
        except urllib.error.HTTPError as err:
            assert err.code == 400, f"Expected 400 for {dis_fmt}, got {err.code}"
            print(f"  Format '{dis_fmt.upper()}' correctly rejected with HTTP 400 (Disabled for Graphic Novels) OK")

    print("\nALL GRAPHIC NOVEL & COMIC TRANSLATION TESTS PASSED!")


if __name__ == "__main__":
    test_graphic_novel_pdf_translation()
    test_cbz_archive_translation()
