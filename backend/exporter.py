# exporter.py - Export translated text to various formats

import os
from pathlib import Path

# TXT

def export_txt(text: str, out_path: Path) -> Path:
    out_path.write_text(text, encoding="utf-8")
    return out_path

# DOCX (requires python-docx)
def export_docx(text: str, out_path: Path) -> Path:
    from docx import Document
    doc = Document()
    # Simple paragraph for whole text – split by double newlines for sections
    for para in text.split("\n\n"):
        doc.add_paragraph(para)
    doc.save(str(out_path))
    return out_path

# PDF (requires fpdf2)
def export_pdf(text: str, out_path: Path) -> Path:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", size=12)
    # Split text into lines respecting width
    for line in text.splitlines():
        pdf.multi_cell(w=0, h=6, txt=line, align="L")
    pdf.output(str(out_path))
    return out_path

# EPUB (requires EbookLib)
def export_epub(text: str, out_path: Path, title: str = "Translated Book") -> Path:
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier(str(out_path.stem))
    book.set_title(title)
    book.set_language("en")
    # Create a single chapter with all text
    c1 = epub.EpubHtml(title="Content", file_name="chap_01.xhtml", lang="en")
    # Convert newlines to paragraphs
    html_content = f"<h1>{title}</h1>"
    for para in text.split("\n\n"):
        html_content += f"<p>{para}</p>"
    c1.content = html_content
    book.add_item(c1)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [c1]
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
