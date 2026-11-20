# exporter.py - Export translated text to various formats (Standard & Literature/E-Reader)

import html
import io
import os
import re
from pathlib import Path
from typing import Optional, Union


def extract_cover_image(file_path: Optional[Union[str, Path]]) -> Optional[bytes]:
    """
    Extracts the original cover image from an input book (PDF, DOCX, or EPUB).
    Returns raw image bytes (JPEG/PNG) or None if no cover is found.
    """
    if not file_path:
        return None
    p = Path(file_path)
    if not p.exists():
        return None

    ext = p.suffix.lower()

    if ext == ".pdf":
        try:
            import pymupdf
            with pymupdf.open(str(p)) as doc:
                if len(doc) == 0:
                    return None
                p0 = doc[0]
                imgs = p0.get_images()
                text_len = len(p0.get_text().strip())
                # A cover page typically has images and little/no textual prose (< 150 chars),
                # or has an image covering most of the page.
                if imgs or text_len < 150:
                    pix = p0.get_pixmap(dpi=150)
                    return pix.tobytes("jpeg")
        except Exception:
            pass

    elif ext == ".docx":
        try:
            import docx
            doc = docx.Document(str(p))
            for rel in doc.part.rels.values():
                if "image" in rel.target_ref:
                    return rel.target_part.blob
        except Exception:
            pass

    elif ext == ".epub":
        try:
            import ebooklib
            from ebooklib import epub
            book = epub.read_epub(str(p))
            for it in book.get_items():
                name_l = it.get_name().lower()
                if "cover" in name_l and getattr(it, "content", None):
                    if it.get_type() in (ebooklib.ITEM_COVER, ebooklib.ITEM_IMAGE) or name_l.endswith((".jpg", ".jpeg", ".png")):
                        return it.content
            # Fallback: check first image item in the epub
            for it in book.get_items():
                if it.get_type() == ebooklib.ITEM_IMAGE and getattr(it, "content", None):
                    return it.content
        except Exception:
            pass

    return None


_PUA_MAP = {
    "\uf0b7": "• ",  # Wingdings round bullet
    "\uf0a7": "• ",  # Wingdings square bullet
    "\uf076": "✓ ",  # Checkmark
    "\uf0d8": "➢ ",  # Arrow
    "\uf0fc": "✔ ",  # Heavy check
    "\uf0e0": "✉ ",  # Envelope
    "\uf0a8": "❖ ",
    "\uf02d": "-",
}

_CHAPTER_RE = re.compile(
    r"^(?:"
    r"(?:chapter|chap\.|part|book|prologue|epilogue|preface|introduction|afterword|acknowledgments|notes\s*and\s*references|license)"
    r"(?:\s+[\w\d\.\-]+(?:\s*[:\-–—]\s*.+)?)?"
    r"|(?:κ[εέ]φ[αά]λαιο|κεφ\.|μ[εέ]ρος|βιβλ[ιί]ο|πρ[οό]λογος|επ[ιί]λογος|εισαγωγ[ηή]|ευχαριστ[ιί]ες|σημει[ώω]σεις(?:\s*και\s*παραπομπ[εέ]ς)?|[αά]δεια)"
    r"(?:\s+[\w\d\.\-]+(?:\s*[:\-–—]\s*.+)?)?"
    r")$",
    re.IGNORECASE,
)
_STRICT_ROMAN_CHAPTER_RE = re.compile(r"^(?:X{0,3})(?:IX|IV|V?I{0,3})$")

_SCENE_BREAK_RE = re.compile(r"^(?:\*\s*\*\s*\*+|---\s*|~~~\s*|•\s*•\s*•+)$")


_EXPORT_HTML_TAG_RE = re.compile(
    r"</?(?:i|b|em|strong|u|s|span|p|br|div|font|sup|sub|small|big|mark|del|ins)\b[^>]*>",
    re.IGNORECASE,
)
_EXPORT_SPECIAL_TOKEN_RE = re.compile(
    r"<(?:/?(?:bos|eos|pad|unk|sep|cls|mask|start_of_turn|end_of_turn)|\|[^|\n]{1,32}\|)>",
    re.IGNORECASE,
)
_EMPHASIS_TOKEN_RE = re.compile(
    r"(\*\*[^*\n]+?\*\*|(?<!\*)\*(?!\s)[^*\n]+?(?<!\s)\*(?!\*))"
)
_XML_ILLEGAL_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_INVISIBLE_GARBAGE_RE = re.compile(r"[\ufffd\u00ad\ufeff\u200b-\u200f\u202a-\u202e\u2060-\u206f]")
_EXOTIC_SPACE_RE = re.compile(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]")
_UNICODE_PUNCT_NORMALIZE = {
    "\u2010": "-",   # hyphen
    "\u2011": "-",   # non-breaking hyphen
    "\u2012": "–",   # figure dash
    "\u2212": "-",   # minus sign
    "\u2032": "'",   # prime
    "\u2033": '"',   # double prime
    "\u2028": "\n",  # line separator
    "\u2029": "\n\n",  # paragraph separator
}
_PDF_GLYPH_FALLBACKS = {
    "•": "-",
    "—": "-",
    "–": "-",
    "…": "...",
    "«": '"',
    "»": '"',
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "×": "x",
    "÷": "/",
    "±": "+/-",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "→": "->",
    "←": "<-",
    "↔": "<->",
    "✓": "v",
    "✔": "v",
    "➢": ">",
    "❖": "*",
    "✉": "",
}


def _sanitize_pua(text: str) -> str:
    """
    Map Wingdings / Symbol Private Use Area (PUA) characters to standard Unicode,
    normalize exotic Unicode spaces/dashes, strip XML-illegal / replacement / zero-width
    control characters, stray inline HTML tags, LLM special tokens, and broken Greek hyphens.
    """
    if not text:
        return ""
    for pua, repl in _PUA_MAP.items():
        text = text.replace(pua, repl)
    text = re.sub(r"[\ue000-\uf8ff]", "• ", text)
    for ch, repl in _UNICODE_PUNCT_NORMALIZE.items():
        if ch in text:
            text = text.replace(ch, repl)
    text = _EXOTIC_SPACE_RE.sub(" ", text)
    text = _INVISIBLE_GARBAGE_RE.sub("", text)
    text = _XML_ILLEGAL_CTRL_RE.sub("", text)
    text = _EXPORT_SPECIAL_TOKEN_RE.sub("", text)
    text = _EXPORT_HTML_TAG_RE.sub("", text)
    try:
        from backend.typography import fix_broken_hyphens, sanitize_editorial_pass
        text = fix_broken_hyphens(text)
        text = sanitize_editorial_pass(text)
    except Exception:
        pass
    return text


def _sanitize_for_pdf_font(text: str, font_obj) -> str:
    """
    Replaces or strips any character not present in font_obj so PyMuPDF never renders
    hollow tofu/missing-glyph boxes (□ / \\x00) in exported PDFs.
    """
    if not text or font_obj is None or not hasattr(font_obj, "has_glyph"):
        return text or ""
    out: list[str] = []
    changed = False
    for ch in text:
        if ch.isspace() or font_obj.has_glyph(ord(ch)):
            out.append(ch)
        else:
            changed = True
            fb = _PDF_GLYPH_FALLBACKS.get(ch, "")
            if fb:
                safe_fb = "".join(c for c in fb if c.isspace() or font_obj.has_glyph(ord(c)))
                if safe_fb:
                    out.append(safe_fb)
    return "".join(out) if changed else text


def _split_oversized_token(token: str, font_obj, fontsize: float, max_w: float) -> list[str]:
    """
    Splits a single unbroken token (such as a long URL) that exceeds max_w into
    margin-safe chunks, preferring natural delimiters ('/', '?', '&', '=', '-', '_', '.')
    before falling back to clean character boundaries so text never clips past the right margin.
    """
    if not token or max_w <= 10.0:
        return [token] if token else []
    if font_obj.text_length(token, fontsize=fontsize) <= max_w:
        return [token]

    parts: list[str] = []
    rem = token
    break_chars = "/?&=-_.:"
    while rem:
        if font_obj.text_length(rem, fontsize=fontsize) <= max_w:
            parts.append(rem)
            break
        # Binary search for the longest prefix that fits within max_w
        lo, hi = 1, len(rem)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font_obj.text_length(rem[:mid], fontsize=fontsize) <= max_w:
                lo = mid
            else:
                hi = mid - 1
        cut = max(1, lo)
        # Prefer breaking right after a natural URL/token separator in the second half of the chunk
        best_sep = -1
        for idx in range(cut - 1, max(0, cut // 2 - 1), -1):
            if rem[idx] in break_chars:
                best_sep = idx + 1
                break
        if best_sep > 0:
            cut = best_sep
        parts.append(rem[:cut])
        rem = rem[cut:]
    return parts


def _split_emphasis_runs(text: str) -> list[tuple[str, bool, bool]]:
    """
    Splits a paragraph into (segment_text, is_bold, is_italic) tuples for real typographic rendering
    of markdown *italic* and **bold** spans without ever leaving raw asterisks in exported books.
    """
    if not text or "*" not in text:
        return [(text, False, False)] if text else []
    runs: list[tuple[str, bool, bool]] = []
    pos = 0
    for m in _EMPHASIS_TOKEN_RE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False, False))
        tok = m.group(1)
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            runs.append((tok[2:-2], True, False))
        elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
            runs.append((tok[1:-1], False, True))
        else:
            runs.append((tok, False, False))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False, False))
    return runs


def _emphasis_to_html(text: str) -> str:
    """Escapes HTML and converts *italic* / **bold** markdown spans into <em> / <strong> tags."""
    out = []
    for seg, is_bold, is_italic in _split_emphasis_runs(text):
        esc = html.escape(seg)
        if is_bold:
            out.append(f"<strong>{esc}</strong>")
        elif is_italic:
            out.append(f"<em>{esc}</em>")
        else:
            out.append(esc)
    return "".join(out)


def _is_chapter_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if _CHAPTER_RE.match(s):
        return True
    # Match genuine uppercase Roman numerals II..XXXIX as chapter headings (never English words like 'I', 'Did', 'Civil')
    if len(s) >= 2 and s.isupper() and _STRICT_ROMAN_CHAPTER_RE.match(s):
        return True
    return False


def _is_scene_break(line: str) -> bool:
    return bool(_SCENE_BREAK_RE.match(line.strip()))


def _prepare_literature_chapters(text: str, default_title: str = "Book") -> list[dict]:
    """
    Cleans PDF page-break artifacts, running headers/footers, merges sentences broken
    across pages, isolates chapter headings & epigraphs/quotes, and groups paragraphs
    into semantic chapters for e-readers, tablets & printed books.
    Returns list of {"title": str, "paragraphs": list[str]}.
    """
    text = _sanitize_pua(text)

    # Split by === PAGE X === markers and seamlessly merge sentences broken across pages
    raw_pages = re.split(r"={3,}\s*PAGE\s+\d+\s*={3,}", text)
    merged_blocks: list[str] = []

    for page_chunk in raw_pages:
        chunk = page_chunk.strip()
        if not chunk:
            continue

        lines = [ln.strip() for ln in chunk.splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()

        # Strip running headers at top of page (e.g. standalone page number, or Author\nPageNumber\nTitle)
        while lines and re.match(r"^\s*(?:[-–—]?\s*\d{1,4}\s*[-–—]?|[ivxlcdm]+)\s*$", lines[0], re.IGNORECASE):
            lines.pop(0)

        if len(lines) >= 3 and lines[1].isdigit() and len(lines[0]) < 50 and len(lines[2]) < 50:
            if not _is_chapter_heading(lines[0]) and not _is_chapter_heading(lines[2]):
                lines = lines[3:]
        elif len(lines) >= 2 and lines[1].isdigit() and len(lines[0]) < 50 and not _is_chapter_heading(lines[0]):
            lines = lines[2:]
        elif len(lines) >= 2 and lines[0].isdigit() and len(lines[1]) < 50 and not _is_chapter_heading(lines[1]):
            lines = lines[2:]

        # Strip running footers at bottom of page
        while lines and re.match(r"^\s*(?:[-–—]?\s*\d{1,4}\s*[-–—]?|[ivxlcdm]+)\s*$", lines[-1], re.IGNORECASE):
            lines.pop()

        if not lines:
            continue

        # Split into distinct paragraphs, isolating chapter headings, scene breaks & epigraphs
        paras = []
        curr = []
        for line in lines:
            if not line:
                if curr:
                    paras.append(" ".join(curr))
                    curr = []
                continue

            if _is_chapter_heading(line) or _is_scene_break(line):
                if curr:
                    paras.append(" ".join(curr))
                    curr = []
                paras.append(line)
                continue

            # Epigraph attributions (e.g. "—Ted Bundy", "—Susanne Vega")
            if line.startswith(("—", "–", "--")) and len(line) < 80:
                if curr:
                    paras.append(" ".join(curr))
                    curr = []
                paras.append(line)
                continue

            if not curr:
                curr.append(line)
                continue

            prev_l = curr[-1]
            prev_closed = prev_l[-1] in '.!?»"”…'
            starts_dialogue = line.startswith(("«", '"', "“", "—", "- ", "– "))
            if prev_closed and (starts_dialogue or (len(line) > 2 and line[0].isupper())):
                paras.append(" ".join(curr))
                curr = [line]
            else:
                curr.append(line)

        if curr:
            paras.append(" ".join(curr))

        # Check if first block of this page continues the last block of the previous page
        for para in paras:
            if (
                merged_blocks
                and not _is_chapter_heading(para)
                and not _is_chapter_heading(merged_blocks[-1])
                and not _is_scene_break(para)
                and not _is_scene_break(merged_blocks[-1])
            ):
                prev = merged_blocks[-1].rstrip()
                nxt = para.lstrip()
                prev_ends_sentence = prev[-1] in '.!?»"”…)]:;'
                nxt_starts_lower = bool(nxt) and (nxt[0].islower() or (len(nxt) > 1 and nxt[0] in '«"\'“' and nxt[1].islower()))
                if not prev_ends_sentence and nxt_starts_lower:
                    merged_blocks[-1] = prev + " " + nxt
                    continue
            merged_blocks.append(para)

    # Group into chapters
    chapters: list[dict] = []
    current_chapter = {"title": default_title, "paragraphs": []}

    for blk in merged_blocks:
        if _is_chapter_heading(blk):
            if current_chapter["paragraphs"]:
                chapters.append(current_chapter)
            current_chapter = {"title": blk, "paragraphs": []}
        else:
            current_chapter["paragraphs"].append(blk)

    if current_chapter["paragraphs"] or not chapters:
        chapters.append(current_chapter)

    # Filter out fake chapters (like TOC entries or empty title pages)
    cleaned_chapters = []
    for idx, ch in enumerate(chapters):
        body_text = " ".join(ch["paragraphs"]).strip()
        if not body_text:
            continue
        words = body_text.split()
        # If the chapter body is essentially just page numbers or TOC artifact
        if len(body_text) < 150 and (body_text.isdigit() or all(w.isdigit() or w in (".", "...", ":", "-") for w in words)):
            continue
        # If front-matter chapter before the first real chapter has no sentence ending
        if idx == 0 and len(chapters) > 1 and len(body_text) < 150 and not any(body_text.endswith(p) for p in ('.', '!', '?')):
            continue
        cleaned_chapters.append(ch)

    return cleaned_chapters if cleaned_chapters else chapters


# TXT
def export_txt(text: str, out_path: Path) -> Path:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(text or "", encoding="utf-8")
    return Path(out_path)


# DOCX (requires python-docx)
def export_docx(text: str, out_path: Path, layout: str = "standard", cover_image: Optional[bytes] = None) -> Path:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    text = _sanitize_pua(text)
    doc = Document()

    if layout == "literature":
        # 6" x 9" trade-paperback / e-reader friendly page geometry
        for section in doc.sections:
            section.page_width = Inches(6.0)
            section.page_height = Inches(9.0)
            section.top_margin = Inches(0.75)
            section.bottom_margin = Inches(0.75)
            section.left_margin = Inches(0.75)
            section.right_margin = Inches(0.75)

        normal_style = doc.styles["Normal"]
        normal_style.font.name = "Georgia"
        normal_style.font.size = Pt(11.5)

        # Validate cover image BEFORE inserting a cover page so corrupt bytes never leave a blank page
        if cover_image:
            valid_cover = False
            try:
                import pymupdf
                pix = pymupdf.Pixmap(cover_image)
                valid_cover = pix.width > 0 and pix.height > 0
            except Exception:
                valid_cover = False
            if valid_cover:
                try:
                    cp = doc.add_paragraph()
                    cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cp.paragraph_format.space_before = Pt(0)
                    cp.paragraph_format.space_after = Pt(0)
                    c_run = cp.add_run()
                    c_run.add_picture(io.BytesIO(cover_image), width=Inches(4.5))
                    doc.add_page_break()
                except Exception:
                    pass

        chapters = _prepare_literature_chapters(text, default_title=out_path.stem)
        for ch_idx, ch in enumerate(chapters):
            if ch_idx > 0:
                doc.add_page_break()

            if ch["title"] and (len(chapters) > 1 or ch["title"] != out_path.stem):
                h = doc.add_paragraph()
                h.alignment = WD_ALIGN_PARAGRAPH.CENTER
                h.paragraph_format.space_before = Pt(24)
                h.paragraph_format.space_after = Pt(18)
                run = h.add_run(ch["title"])
                run.bold = True
                run.font.name = "Georgia"
                run.font.size = Pt(16)

            is_first = True
            for para in ch["paragraphs"]:
                if _is_scene_break(para):
                    sb = doc.add_paragraph("* * *")
                    sb.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    sb.paragraph_format.space_before = Pt(12)
                    sb.paragraph_format.space_after = Pt(12)
                    is_first = True
                    continue

                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                p.paragraph_format.line_spacing = 1.4
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.first_line_indent = Inches(0) if is_first else Inches(0.28)
                for seg, is_bold, is_italic in _split_emphasis_runs(para):
                    run = p.add_run(seg)
                    run.font.name = "Georgia"
                    run.font.size = Pt(11.5)
                    if is_bold:
                        run.bold = True
                    if is_italic:
                        run.italic = True
                is_first = False

        doc.save(str(out_path))
        return out_path

    # Standard / Administrative layout
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

            for line in b.split("\n"):
                l = line.strip()
                if not l:
                    continue

                if l.startswith("• ") or l.startswith("- ") or l.startswith("* "):
                    bullet_text = re.sub(r"^[•\-\*]\s*", "", l)
                    doc.add_paragraph(bullet_text, style="List Bullet")
                elif l.isupper() and len(l) < 60:
                    p = doc.add_paragraph()
                    run = p.add_run(l)
                    run.bold = True
                    run.font.size = Pt(13)
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


# PDF (uses pymupdf which supports full Unicode / Greek)
def _export_literature_pdf(text: str, out_path: Path, cover_image: Optional[bytes] = None) -> Path:
    import pymupdf

    doc = pymupdf.open()
    serif_candidates = [
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/pala.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    italic_candidates = [
        "C:/Windows/Fonts/georgiai.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/palai.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        "C:/Windows/Fonts/ariali.ttf",
    ]
    bold_candidates = [
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/palab.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    font_path = next((f for f in serif_candidates if os.path.exists(f)), None)
    italic_font_path = next((f for f in italic_candidates if os.path.exists(f)), font_path)
    bold_font_path = next((f for f in bold_candidates if os.path.exists(f)), font_path)

    # 6" x 9" trade paperback size (ideal for iPad & e-readers)
    width = 432.0
    height = 648.0
    margin_x = 46.0
    margin_top = 52.0
    content_bottom = height - 52.0
    max_line_w = width - 2 * margin_x

    # Insert cover image as page 0 if valid (validate before creating page to avoid blank page on corrupt bytes)
    has_cover_page = False
    if cover_image:
        try:
            pix = pymupdf.Pixmap(cover_image)
            if pix.width > 0 and pix.height > 0:
                cov_page = doc.new_page(width=width, height=height)
                cov_page.insert_image(pymupdf.Rect(0, 0, width, height), stream=cover_image)
                has_cover_page = True
        except Exception:
            pass

    fname = "book_serif" if font_path else "helv"
    fname_it = "book_serif_it" if italic_font_path else fname
    fname_bd = "book_serif_bd" if bold_font_path else fname
    font_obj = pymupdf.Font(fontfile=font_path) if font_path else pymupdf.Font("helv")
    font_obj_it = pymupdf.Font(fontfile=italic_font_path) if italic_font_path else font_obj
    font_obj_bd = pymupdf.Font(fontfile=bold_font_path) if bold_font_path else font_obj

    def new_book_page():
        pg = doc.new_page(width=width, height=height)
        if font_path:
            pg.insert_font(fontname=fname, fontfile=font_path)
        if italic_font_path:
            pg.insert_font(fontname=fname_it, fontfile=italic_font_path)
        if bold_font_path:
            pg.insert_font(fontname=fname_bd, fontfile=bold_font_path)
        return pg, margin_top

    chapters = _prepare_literature_chapters(text, default_title=out_path.stem)

    for ch_idx, ch in enumerate(chapters):
        page, y = new_book_page()

        # Chapter title
        if ch["title"] and (len(chapters) > 1 or ch["title"] != out_path.stem):
            y += 28.0
            title_size = 15.5
            safe_title = _sanitize_for_pdf_font(ch["title"], font_obj)
            title_w = font_obj.text_length(safe_title, fontsize=title_size)
            tx = max(margin_x, (width - title_w) / 2.0)
            page.insert_text(pymupdf.Point(tx, y), safe_title, fontsize=title_size, fontname=fname, color=(0.1, 0.1, 0.1))
            y += 32.0

        body_size = 11.0
        line_height = 16.5
        indent = 16.0
        is_first = True

        for para in ch["paragraphs"]:
            if _is_scene_break(para):
                if y + 28.0 > content_bottom:
                    page, y = new_book_page()
                y += 8.0
                sb_text = "* * *"
                sb_w = font_obj.text_length(sb_text, fontsize=body_size)
                page.insert_text(pymupdf.Point((width - sb_w) / 2.0, y), sb_text, fontsize=body_size, fontname=fname, color=(0.3, 0.3, 0.3))
                y += 20.0
                is_first = True
                continue

            def _word_font(st: str):
                if st == "i":
                    return fname_it, font_obj_it
                if st == "b":
                    return fname_bd, font_obj_bd
                return fname, font_obj

            # Tokenize paragraph into styled words (word, style_code: 'r'|'i'|'b'),
            # sanitizing unsupported glyphs and wrapping oversized tokens (e.g. long URLs)
            styled_words: list[tuple[str, str]] = []
            for seg, is_bold, is_italic in _split_emphasis_runs(para):
                st = "b" if is_bold else ("i" if is_italic else "r")
                _, fobj_seg = _word_font(st)
                safe_seg = _sanitize_for_pdf_font(seg, fobj_seg)
                for w in safe_seg.split():
                    for piece in _split_oversized_token(w, fobj_seg, body_size, max_line_w - indent):
                        styled_words.append((piece, st))

            def _measure_styled_line(items: list[tuple[str, str]]) -> float:
                total_w = 0.0
                space_w = font_obj.text_length(" ", fontsize=body_size)
                for idx_w, (w_txt, w_st) in enumerate(items):
                    _, fobj_w = _word_font(w_st)
                    total_w += fobj_w.text_length(w_txt, fontsize=body_size)
                    if idx_w > 0:
                        total_w += space_w
                return total_w

            def _draw_styled_line(target_page, start_x: float, y_pos: float, items: list[tuple[str, str]]):
                # Merge consecutive words of identical style for clean text extraction & kerning
                if not items:
                    return
                groups: list[tuple[str, str]] = []
                for w_txt, w_st in items:
                    if groups and groups[-1][1] == w_st:
                        groups[-1] = (groups[-1][0] + " " + w_txt, w_st)
                    else:
                        groups.append((w_txt, w_st))
                cx = start_x
                space_w = font_obj.text_length(" ", fontsize=body_size)
                for g_idx, (g_txt, g_st) in enumerate(groups):
                    if g_idx > 0:
                        cx += space_w
                    fn_g, fo_g = _word_font(g_st)
                    target_page.insert_text(pymupdf.Point(cx, y_pos), g_txt, fontsize=body_size, fontname=fn_g, color=(0.12, 0.12, 0.12))
                    cx += fo_g.text_length(g_txt, fontsize=body_size)

            line_words: list[tuple[str, str]] = []
            first_line = True

            for w_item in styled_words:
                curr_indent = (0.0 if is_first else indent) if first_line else 0.0
                avail_w = max_line_w - curr_indent
                if not line_words or _measure_styled_line(line_words + [w_item]) <= avail_w:
                    line_words.append(w_item)
                else:
                    if y + line_height > content_bottom:
                        page, y = new_book_page()
                    _draw_styled_line(page, margin_x + curr_indent, y, line_words)
                    y += line_height
                    line_words = [w_item]
                    first_line = False

            if line_words:
                curr_indent = (0.0 if is_first else indent) if first_line else 0.0
                if y + line_height > content_bottom:
                    page, y = new_book_page()
                _draw_styled_line(page, margin_x + curr_indent, y, line_words)
                y += line_height

            y += 4.5
            is_first = False

    if len(doc) == 0:
        blank_pg = doc.new_page(width=width, height=height)
        if font_path:
            blank_pg.insert_font(fontname="book_serif", fontfile=font_path)

    # Centered book-style page numbers (skip cover page if present)
    for p_no, pg in enumerate(doc, 1):
        if has_cover_page and p_no == 1:
            continue
        display_num = p_no - 1 if has_cover_page else p_no
        footer = f"- {display_num} -"
        fw = font_obj.text_length(footer, fontsize=9.0)
        pg.insert_text(pymupdf.Point((width - fw) / 2.0, height - 28.0), footer, fontsize=9.0, fontname=fname, color=(0.45, 0.45, 0.45))

    try:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
    finally:
        doc.close()
    return out_path


def export_pdf(text: str, out_path: Path, layout: str = "standard", cover_image: Optional[bytes] = None) -> Path:
    if layout == "literature":
        return _export_literature_pdf(text, out_path, cover_image=cover_image)

    import pymupdf

    doc = pymupdf.open()
    try:
        candidate_fonts = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        font_path = next((f for f in candidate_fonts if os.path.exists(f)), None)

        sections = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text or "")
        pages_data = []

        if len(sections) > 1:
            i = 1
            while i < len(sections):
                pnum = sections[i]
                pcontent = sections[i + 1] if i + 1 < len(sections) else ""
                pages_data.append((f"Page {pnum}", pcontent.strip()))
                i += 2
        else:
            pages_data.append(("", (text or "").strip()))

        margin = 48.0
        width = 595.0   # A4 width
        height = 842.0  # A4 height
        content_bottom = height - margin - 20.0

        def is_heading(line: str) -> bool:
            s = line.strip()
            if not s or len(s) > 85:
                return False
            if s.isupper() and len(s) > 3:
                return True
            if s.startswith(("ΘΕΜΑ:", "ΠΡΟΣ:", "ΑΠΟ:", "SUBJECT:", "TO:", "FROM:", "Συνημμένο:", "Ημερομηνία:")):
                return True
            return False

        fname = "unicode_font" if font_path else "helv"
        font_obj = pymupdf.Font(fontfile=font_path) if font_path else pymupdf.Font("helv")

        for section_title, section_body in pages_data:
            if not section_body:
                continue

            page = doc.new_page(width=width, height=height)
            if font_path:
                page.insert_font(fontname="unicode_font", fontfile=font_path)
            y = margin

            if section_title:
                page.insert_text(pymupdf.Point(margin, y), section_title, fontsize=9.0, fontname=fname, color=(0.5, 0.5, 0.5))
                y += 18.0

            for raw_line in section_body.split("\n"):
                line = _sanitize_for_pdf_font(_sanitize_pua(raw_line), font_obj).strip()
                if not line:
                    y += 7.0
                    continue

                heading = is_heading(line)
                font_size = 12.5 if heading else 10.5
                line_height = 17.5 if heading else 14.5
                color = (0.05, 0.05, 0.2) if heading else (0.1, 0.1, 0.1)

                max_w = width - 2 * margin
                words: list[str] = []
                for raw_w in line.split():
                    words.extend(_split_oversized_token(raw_w, font_obj, font_size, max_w))
                line_words = []

                for w in words:
                    test_str = " ".join(line_words + [w])
                    if not line_words or font_obj.text_length(test_str, fontsize=font_size) <= max_w:
                        line_words.append(w)
                    else:
                        if y + line_height > content_bottom:
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

                y += 4.0

        # Ensure PyMuPDF never crashes with "cannot save with zero pages" on empty inputs
        if len(doc) == 0:
            blank_pg = doc.new_page(width=width, height=height)
            if font_path:
                blank_pg.insert_font(fontname="unicode_font", fontfile=font_path)

        total_pages = len(doc)
        for p_no, pg in enumerate(doc, 1):
            footer = f"{p_no} / {total_pages}"
            pg.insert_text(pymupdf.Point(width - margin - 35, height - margin + 15), footer, fontsize=9.0, fontname=fname, color=(0.5, 0.5, 0.5))

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
    finally:
        doc.close()
    return out_path


# EPUB (requires EbookLib)
def export_epub(text: str, out_path: Path, title: str = "Translated Book", layout: str = "standard", cover_image: Optional[bytes] = None) -> Path:
    from ebooklib import epub

    safe_text = text or ""
    epub_lang = "el" if re.search(r"[\u0370-\u03ff]", safe_text) else "en"

    book = epub.EpubBook()
    book.set_identifier(str(out_path.stem))
    book.set_title(title)
    book.set_language(epub_lang)

    has_cover = False
    if cover_image:
        try:
            # Set cover in EPUB
            book.set_cover("cover.jpg", cover_image)
            has_cover = True
        except Exception:
            pass

    if layout == "literature":
        book_css = """
body {
    font-family: Georgia, "Times New Roman", Palatino, serif;
    line-height: 1.55;
    margin: 5% 6%;
}
h1.chapter-title {
    text-align: center;
    font-weight: normal;
    font-size: 1.45em;
    letter-spacing: 0.04em;
    margin-top: 2.2em;
    margin-bottom: 1.5em;
    page-break-before: always;
}
p {
    text-align: justify;
    text-indent: 1.4em;
    margin: 0 0 0.35em 0;
}
p.first-para {
    text-indent: 0;
}
p.scene-break {
    text-align: center;
    text-indent: 0;
    margin: 1.4em 0;
    letter-spacing: 0.3em;
}
"""
    else:
        book_css = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
    margin: 4% 5%;
}
h2 {
    margin-top: 1.5em;
    margin-bottom: 0.8em;
}
p {
    margin: 0 0 0.8em 0;
}
"""

    css_item = epub.EpubItem(
        uid="style_book",
        file_name="style/book.css",
        media_type="text/css",
        content=book_css.encode("utf-8"),
    )
    book.add_item(css_item)

    chapters_items = []

    if layout == "literature":
        chapters = _prepare_literature_chapters(safe_text, default_title=title)
        for idx, ch in enumerate(chapters, 1):
            ch_title = ch["title"] or f"Chapter {idx}"
            c = epub.EpubHtml(title=ch_title, file_name=f"chap_{idx:03d}.xhtml", lang=epub_lang)
            c.add_item(css_item)

            parts = []
            if len(chapters) > 1 or ch_title != title:
                parts.append(f'<h1 class="chapter-title">{html.escape(ch_title)}</h1>')

            is_first = True
            for para in ch["paragraphs"]:
                if _is_scene_break(para):
                    parts.append('<p class="scene-break">* * *</p>')
                    is_first = True
                else:
                    cls = ' class="first-para"' if is_first else ""
                    parts.append(f"<p{cls}>{_emphasis_to_html(para)}</p>")
                    is_first = False

            c.content = "\n".join(parts) or "<p>&#160;</p>"
            book.add_item(c)
            chapters_items.append(c)
    else:
        sections = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", _sanitize_pua(safe_text))
        if len(sections) > 1:
            seen_fnames = set()
            i = 1
            sec_idx = 0
            while i < len(sections):
                sec_idx += 1
                pnum = sections[i]
                pcontent = sections[i + 1] if i + 1 < len(sections) else ""
                fname_xhtml = f"page_{pnum}.xhtml"
                if fname_xhtml in seen_fnames:
                    fname_xhtml = f"page_{pnum}_{sec_idx}.xhtml"
                seen_fnames.add(fname_xhtml)
                c = epub.EpubHtml(title=f"Page {pnum}", file_name=fname_xhtml, lang=epub_lang)
                c.add_item(css_item)
                body_html = f"<h2>Page {html.escape(pnum)}</h2>"
                for p in pcontent.strip().split("\n\n"):
                    if p.strip():
                        body_html += f"<p>{html.escape(p.strip())}</p>"
                c.content = body_html
                book.add_item(c)
                chapters_items.append(c)
                i += 2
        else:
            c1 = epub.EpubHtml(title=title, file_name="chap_01.xhtml", lang=epub_lang)
            c1.add_item(css_item)
            body_html = f"<h1>{html.escape(title)}</h1>"
            for para in _sanitize_pua(safe_text).split("\n\n"):
                if para.strip():
                    body_html += f"<p>{html.escape(para.strip())}</p>"
            c1.content = body_html
            book.add_item(c1)
            chapters_items.append(c1)

    book.toc = tuple(chapters_items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = (["cover"] if has_cover else []) + ["nav"] + chapters_items
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book, {})
    return out_path


def export_comic_archive(
    pdf_path: Union[str, Path],
    out_path: Union[str, Path],
    format: str = "cbz",
    dpi: int = 150,
) -> Path:
    """
    Renders pages of a translated comic PDF as images and packages them into a CBZ or CBR archive.
    """
    import zipfile
    import pymupdf

    pdf_p = Path(pdf_path)
    if not pdf_p.exists():
        raise FileNotFoundError(f"Source comic PDF not found: {pdf_path}")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(str(pdf_p))
    try:
        with zipfile.ZipFile(str(out_p), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=dpi)
                img_bytes = pix.tobytes("jpeg")
                zf.writestr(f"page_{i+1:04d}.jpg", img_bytes)
    finally:
        doc.close()
    return out_p


def export_comic_epub(
    pdf_path: Union[str, Path],
    out_path: Union[str, Path],
    title: str = "Graphic Novel",
    dpi: int = 150,
    reading_direction: str = "ltr",
) -> Path:
    """
    Creates a pre-paginated fixed-layout EPUB containing rendered full-bleed comic pages.
    Supports standard LTR or Japanese Manga RTL page progression.
    """
    import pymupdf
    from ebooklib import epub

    pdf_p = Path(pdf_path)
    if not pdf_p.exists():
        raise FileNotFoundError(f"Source comic PDF not found: {pdf_path}")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(str(pdf_p))
    try:
        book = epub.EpubBook()
        book.set_identifier(f"comic-{pdf_p.stem}")
        book.set_title(title)
        book.set_language("el")
        book.add_author("BookApp Comic Engine")
        if reading_direction.lower() == "rtl":
            book.set_direction("rtl")
            try:
                book.add_metadata(None, "meta", "rtl", {"property": "page-progression-direction"})
            except Exception:
                pass

        spine = ["nav"]
        chapters = []

        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("jpeg")
            img_name = f"images/page_{i+1:04d}.jpg"
            img_item = epub.EpubItem(
                uid=f"img_{i+1}",
                file_name=img_name,
                media_type="image/jpeg",
                content=img_bytes,
            )
            book.add_item(img_item)

            w = int(page.rect.width)
            h = int(page.rect.height)
            html_content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Page {i+1}</title>
  <meta name="viewport" content="width={w}, height={h}"/>
  <style>
    body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; text-align: center; }}
    img {{ max-width: 100%; max-height: 100%; width: auto; height: auto; display: block; margin: auto; }}
  </style>
</head>
<body>
  <img src="{img_name}" alt="Page {i+1}"/>
</body>
</html>"""
            c = epub.EpubHtml(title=f"Page {i+1}", file_name=f"page_{i+1:04d}.xhtml", lang="el")
            c.content = html_content
            book.add_item(c)
            spine.append(c)
            chapters.append(c)

        book.spine = spine
        book.toc = tuple(chapters)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        epub.write_epub(str(out_p), book, {})
    finally:
        doc.close()
    return out_p


# Helper dispatch
def export_text(
    text: str,
    out_dir: Path,
    fmt: str,
    base_name: str,
    layout: str = "standard",
    cover_image: Optional[bytes] = None,
) -> Path:
    """Export `text` to `fmt` inside `out_dir` using `layout` ('standard' or 'literature').
    If `cover_image` is provided (or if a saved cover image exists in `out_dir`), it is included
    in literature-formatted outputs (DOCX, PDF, EPUB).
    Returns the absolute path to the generated file.
    """
    # Look for cached cover in out_dir if not explicitly passed
    if cover_image is None and out_dir.exists():
        for cov_candidate in ("cover_image.jpg", "cover_image.png", "cover.jpg", "cover.png"):
            cov_file = out_dir / cov_candidate
            if cov_file.exists():
                try:
                    cover_image = cov_file.read_bytes()
                    break
                except Exception:
                    pass

    fmt = fmt.lower()
    out_path = out_dir / f"{base_name}.{fmt}"

    if fmt in ("cbz", "cbr"):
        candidates = list(out_dir.glob("*_translated_*.pdf")) or list(out_dir.glob("*.pdf"))
        if candidates:
            return export_comic_archive(candidates[0], out_path, format=fmt)
        raise ValueError(f"No comic PDF found in {out_dir} to build {fmt.upper()} archive.")

    if fmt == "txt":
        return export_txt(text, out_path)
    if fmt in ("doc", "docx"):
        return export_docx(text, out_path, layout=layout, cover_image=cover_image)
    if fmt == "pdf":
        return export_pdf(text, out_path, layout=layout, cover_image=cover_image)
    if fmt == "epub":
        if layout == "comic":
            candidates = list(out_dir.glob("*_translated_*.pdf")) or list(out_dir.glob("*.pdf"))
            if candidates:
                return export_comic_epub(candidates[0], out_path, title=base_name)
        return export_epub(text, out_path, title=base_name, layout=layout, cover_image=cover_image)
    raise ValueError(f"Unsupported format: {fmt}")
