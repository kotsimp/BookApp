# exporter.py - Export translated text to various formats

import os
import re
from pathlib import Path


# TXT
def export_txt(text: str, out_path: Path) -> Path:
    out_path.write_text(text, encoding="utf-8")
    return out_path


# DOCX (requires python-docx)
def export_docx(text: str, out_path: Path) -> Path:
    from docx import Document
    doc = Document()
    for para in text.split("\n\n"):
        p = para.strip()
        if p:
            doc.add_paragraph(p)
    doc.save(str(out_path))
    return out_path


# PDF (uses pymupdf which supports full Unicode / Greek)
def export_pdf(text: str, out_path: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()

    # Locate Unicode TrueType font for Greek support
    candidate_fonts = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    font_path = next((f for f in candidate_fonts if os.path.exists(f)), None)

    # Split text into sections by PAGE markers if present
    sections = re.split(r"={3,}\s*PAGE\s+\d+\s*={3,}", text)
    pages_content = [s.strip() for s in sections if s.strip()]
    if not pages_content:
        pages_content = [text.strip()]

    margin = 45.0
    width = 595.0   # A4 width
    height = 842.0  # A4 height
    line_height = 15.0
    max_lines = int((height - 2 * margin) / line_height)

    for section in pages_content:
        paras = section.split("\n")
        lines = []
        for para in paras:
            words = para.split(" ")
            current_line = ""
            for w in words:
                if len(current_line) + len(w) + 1 <= 80:
                    current_line = current_line + " " + w if current_line else w
                else:
                    lines.append(current_line)
                    current_line = w
            if current_line:
                lines.append(current_line)
            lines.append("")  # Blank line between paragraphs

        # Flow lines across pages
        for i in range(0, max(len(lines), 1), max_lines):
            chunk = lines[i:i + max_lines]
            page = doc.new_page(width=width, height=height)
            if font_path:
                page.insert_font(fontname="unicode_font", fontfile=font_path)
                fname = "unicode_font"
            else:
                fname = "helv"

            y = margin + 12
            for l in chunk:
                if l.strip():
                    page.insert_text(pymupdf.Point(margin, y), l, fontsize=10.5, fontname=fname)
                y += line_height

    doc.save(str(out_path))
    doc.close()
    return out_path


# EPUB (requires EbookLib)
def export_epub(text: str, out_path: Path, title: str = "Translated Book") -> Path:
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier(str(out_path.stem))
    book.set_title(title)
    book.set_language("el")

    # Create chapters per PAGE marker if present
    sections = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text)
    spine = []

    if len(sections) > 1:
        # Alternating: [pre, page_num, content, page_num, content, ...]
        i = 1
        while i < len(sections):
            pnum = sections[i]
            pcontent = sections[i+1] if i + 1 < len(sections) else ""
            c = epub.EpubHtml(title=f"Page {pnum}", file_name=f"page_{pnum}.xhtml", lang="el")
            body_html = f"<h2>Page {pnum}</h2>"
            for p in pcontent.strip().split("\n\n"):
                if p.strip():
                    body_html += f"<p>{p.strip()}</p>"
            c.content = body_html
            book.add_item(c)
            spine.append(c)
            i += 2
    else:
        c1 = epub.EpubHtml(title="Content", file_name="chap_01.xhtml", lang="el")
        body_html = f"<h1>{title}</h1>"
        for para in text.split("\n\n"):
            if para.strip():
                body_html += f"<p>{para.strip()}</p>"
        c1.content = body_html
        book.add_item(c1)
        spine.append(c1)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    epub.write_epub(str(out_path), book, {})
    return out_path


# Helper dispatch
def export_text(text: str, out_dir: Path, fmt: str, base_name: str) -> Path:
    """Export `text` to `fmt` inside `out_dir`.
    Returns the absolute path to the generated file.
    """
    fmt = fmt.lower()
    out_path = out_dir / f"{base_name}.{fmt}"
    if fmt == "txt":
        return export_txt(text, out_path)
    if fmt in ("doc", "docx"):
        return export_docx(text, out_path)
    if fmt == "pdf":
        return export_pdf(text, out_path)
    if fmt == "epub":
        return export_epub(text, out_path, title=base_name)
    raise ValueError(f"Unsupported format: {fmt}")
