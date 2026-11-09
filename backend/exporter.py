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
    from docx.shared import Pt

    # Map Wingdings / Symbol Private Use Area (PUA) bullet characters to standard Unicode
    pua_map = {
        "\uf0b7": "• ",  # Wingdings round bullet
        "\uf0a7": "• ",  # Wingdings square bullet
        "\uf076": "✓ ",  # Checkmark
        "\uf0d8": "➢ ",  # Arrow
        "\uf0fc": "✔ ",  # Heavy check
        "\uf0e0": "✉ ",  # Envelope
        "\uf0a8": "❖ ",
        "\uf02d": "-",
    }
    for pua, repl in pua_map.items():
        text = text.replace(pua, repl)
    text = re.sub(r"[\ue000-\uf8ff]", "• ", text)

    doc = Document()

    # Split by PAGE markers to replace ASCII dividers with real Word page breaks
    sections = re.split(r"={3,}\s*PAGE\s+\d+\s*={3,}", text)
    pages = [s.strip() for s in sections if s.strip()]
    if not pages:
        pages = [text.strip()]

    header_prefixes = ("ΠΡΟΣ:", "ΑΠΟ:", "ΘΕΜΑ:", "Συνημμένο:", "TO:", "FROM:", "SUBJECT:", "DATE:", "Ημερομηνία:")

    for p_idx, page_content in enumerate(pages):
        if p_idx > 0 and len(doc.paragraphs) > 0:
            doc.add_page_break()

        for block in page_content.split("\n\n"):
            b = block.strip()
            if not b:
                continue

            lines = b.split("\n")
            for line in lines:
                l = line.strip()
                if not l:
                    continue

                # Native bullet points
                if l.startswith("• ") or l.startswith("- ") or l.startswith("* "):
                    bullet_text = re.sub(r"^[•\-\*]\s*", "", l)
                    doc.add_paragraph(bullet_text, style="List Bullet")
                # Main titles (short, uppercase)
                elif l.isupper() and len(l) < 60:
                    p = doc.add_paragraph()
                    run = p.add_run(l)
                    run.bold = True
                    run.font.size = Pt(13)
                # Form headers like ΠΡΟΣ: / ΘΕΜΑ:
                elif any(l.startswith(k) for k in header_prefixes):
                    p = doc.add_paragraph()
                    parts = l.split(":", 1)
                    r1 = p.add_run(parts[0] + ":")
                    r1.bold = True
                    if len(parts) > 1:
                        p.add_run(parts[1])
                else:
                    doc.add_paragraph(l)

    doc.save(str(out_path))
    return out_path


# PDF (uses pymupdf which supports full Unicode / Greek with styled headings)
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
    sections = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text)
    pages_data = []

    if len(sections) > 1:
        i = 1
        while i < len(sections):
            pnum = sections[i]
            pcontent = sections[i+1] if i + 1 < len(sections) else ""
            pages_data.append((f"Page {pnum}", pcontent.strip()))
            i += 2
    else:
        pages_data.append(("", text.strip()))

    margin = 48.0
    width = 595.0   # A4 width
    height = 842.0  # A4 height
    content_bottom = height - margin - 20.0

    def is_heading(line: str) -> bool:
        s = line.strip()
        if not s or len(s) > 75:
            return False
        # Starts with common heading markers
        keywords = ("ΚΕΦΑΛΑΙΟ", "CHAPTER", "ΘΕΜΑ:", "ΠΡΟΣ:", "ΑΠΟ:", "ΥΠΗΡΕΣΙΑΚΟ", "ΕΝΟΤΗΤΑ", "SECTION", "TITLE")
        if any(s.upper().startswith(k) for k in keywords):
            return True
        # Or short uppercase line
        if s.isupper() and len(s) < 50:
            return True
        return False

    for header_title, content in pages_data:
        page = doc.new_page(width=width, height=height)
        fname = "unicode_font" if font_path else "helv"
        if font_path:
            page.insert_font(fontname="unicode_font", fontfile=font_path)

        y = margin

        # If page header exists, render subtle header
        if header_title:
            page.insert_text(pymupdf.Point(margin, y), header_title, fontsize=10.0, fontname=fname, color=(0.4, 0.4, 0.4))
            y += 18.0

        paras = content.split("\n")
        for para in paras:
            p_strip = para.strip()
            if not p_strip:
                y += 8.0
                continue

            heading = is_heading(p_strip)
            font_size = 13.5 if heading else 10.5
            line_height = 18.0 if heading else 14.5
            color = (0.05, 0.05, 0.15) if heading else (0.1, 0.1, 0.1)

            # Extra space before headings
            if heading and y > margin + 20:
                y += 6.0

            # Wrap paragraph words to fit printable width (~500pt)
            words = p_strip.split(" ")
            line_words = []
            for w in words:
                test_line = " ".join(line_words + [w])
                # Approx 75 chars for 10.5pt, 55 chars for 13.5pt
                max_chars = 55 if heading else 75
                if len(test_line) <= max_chars:
                    line_words.append(w)
                else:
                    if y + line_height > content_bottom:
                        # Page break
                        page = doc.new_page(width=width, height=height)
                        if font_path:
                            page.insert_font(fontname="unicode_font", fontfile=font_path)
                        y = margin

                    line_str = " ".join(line_words)
                    page.insert_text(pymupdf.Point(margin, y), line_str, fontsize=font_size, fontname=fname, color=color)
                    y += line_height
                    line_words = [w]

            if line_words:
                if y + line_height > content_bottom:
                    page = doc.new_page(width=width, height=height)
                    if font_path:
                        page.insert_font(fontname="unicode_font", fontfile=font_path)
                    y = margin
                line_str = " ".join(line_words)
                page.insert_text(pymupdf.Point(margin, y), line_str, fontsize=font_size, fontname=fname, color=color)
                y += line_height

            # Paragraph gap
            y += 4.0

    # Add page numbers to all pages
    total_pages = len(doc)
    for p_no, pg in enumerate(doc, 1):
        footer = f"{p_no} / {total_pages}"
        pg.insert_text(pymupdf.Point(width - margin - 35, height - margin + 15), footer, fontsize=9.0, fontname=fname, color=(0.5, 0.5, 0.5))

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
