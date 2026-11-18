"""
Document Parsers - extracts plain text from PDF, DOCX, and EPUB files.
Returns text in manageable chunks suitable for translation and TTS.
"""

import re
import logging
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PDF Parsing via PyMuPDF
# ---------------------------------------------------------------------------

def _extract_page_text(page) -> str:
    """
    Tries multiple PyMuPDF extraction modes in order of preference,
    returning the richest result. Falls back to block-level extraction.
    """
    # 1. Try "text" mode first
    text = page.get_text("text") or ""
    if len(text.strip()) > 50:
        return text

    # 2. Try extracting from blocks (handles some complex PDFs better)
    blocks_text = ""
    try:
        blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,block_no,block_type)
        # Sort blocks by vertical position (top to bottom) then horizontal
        blocks = sorted(blocks, key=lambda b: (round(b[1] / 20), b[0]))
        lines = []
        for b in blocks:
            if b[6] == 0:  # block_type 0 = text block
                t = b[4].strip()
                if t:
                    lines.append(t)
        blocks_text = "\n\n".join(lines)
    except Exception:
        pass

    if len(blocks_text.strip()) > len(text.strip()):
        return blocks_text

    # 3. Try "html" stripped version
    try:
        from bs4 import BeautifulSoup
        html = page.get_text("html") or ""
        soup = BeautifulSoup(html, "html.parser")
        html_text = soup.get_text(separator="\n", strip=True)
        if len(html_text.strip()) > len(text.strip()):
            return html_text
    except Exception:
        pass

    # 4. Try "rawdict" to get every span
    try:
        raw = page.get_text("rawdict")
        span_texts = []
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if t:
                        span_texts.append(t)
        rawdict_text = " ".join(span_texts)
        if len(rawdict_text.strip()) > len(text.strip()):
            return rawdict_text
    except Exception:
        pass

    return text


# Strict Roman numeral pattern (1..399, excluding single 'I' and English words like Did/Mild/Vivid/Civil/Mix/Dim)
_ROMAN_PAGE_NUM_RE = re.compile(
    r"^(?:M{0,3})(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$"
)
_CHAPTER_HEADING_GUARD_RE = re.compile(
    r"^(?:chapter|chap\.|part|book|prologue|epilogue|preface|introduction|afterword|κεφάλαιο|κεφ\.|μέρος|πρόλογος|επίλογος|εισαγωγή)\b",
    re.IGNORECASE,
)


def _is_standalone_page_number(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # Dash-enclosed page number (e.g. "- 12 -", "— 1984 —")
    if re.match(r"^[-–—]\s*\d{1,4}\s*[-–—]$", s):
        return True
    # Plain 1-3 digit page number (avoid stripping 4-digit years like '1984')
    if re.match(r"^\d{1,3}$", s):
        return True
    # Valid Roman numeral of length >= 2 (lowercase or ALL-CAPS only, never Title-case English words like 'Did'/'Mild'/'Civil')
    if len(s) >= 2 and (s.islower() or s.isupper()) and _ROMAN_PAGE_NUM_RE.match(s.upper()):
        if s.lower() not in {"did", "dim", "mix", "mid", "lid", "mild", "vivid", "livid", "civil", "civic", "mimic"}:
            return True
    return False


def _clean_page_blocks(page) -> str:
    """
    Extracts text blocks from a PyMuPDF page while stripping running headers and footers
    (such as author names, book titles, and page numbers at the top/bottom margins).
    """
    blocks = page.get_text("blocks")
    h = page.rect.height
    body_blocks = []

    for b in blocks:
        if b[6] != 0:  # Skip image blocks
            continue
        t = b[4].strip()
        if not t:
            continue
        y0, y1 = b[1], b[3]
        is_top = h > 0 and y0 < (h * 0.12)
        is_bottom = h > 0 and y1 > (h * 0.88)
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]

        if is_top:
            # 1. Pure page numbers or numbers enclosed in dashes/spaces at top
            while lines and _is_standalone_page_number(lines[0]):
                lines.pop(0)

            # 2. Triplet header: Author\nPageNumber\nTitle (e.g. Peter Watts\n6\nBlindsight)
            if len(lines) >= 3 and lines[1].isdigit() and len(lines[0]) < 50 and len(lines[2]) < 50:
                lines = lines[3:]
            # 3. Pair header: Title\nPageNumber or PageNumber\nTitle
            elif len(lines) >= 2 and lines[1].isdigit() and len(lines[0]) < 50 and not lines[0].endswith((".", "!", "?", ";", ":", "»", '"', "”")):
                lines = lines[2:]
            elif len(lines) >= 2 and lines[0].isdigit() and len(lines[1]) < 50 and not lines[1].endswith((".", "!", "?", ";", ":", "»", '"', "”")):
                lines = lines[2:]
            # 4. Standalone short header block (< 55 chars) with no sentence-ending punctuation
            #    (never strip genuine chapter/section headings!)
            elif (
                len(lines) == 1
                and len(lines[0]) < 55
                and not lines[0].endswith((".", "!", "?", ";", ":", "»", '"', "”"))
                and not lines[0][0].islower()
                and not _CHAPTER_HEADING_GUARD_RE.match(lines[0])
            ):
                lines = []

        if is_bottom:
            # Strip running footers at bottom (e.g. page numbers)
            while lines and _is_standalone_page_number(lines[-1]):
                lines.pop()

        if lines:
            body_blocks.append("\n".join(lines))

    return "\n\n".join(body_blocks)


def parse_pdf(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for each page of a PDF.
    Tries multiple extraction modes for best text coverage, stripping running headers/footers.
    """
    import pymupdf  # fitz

    with pymupdf.open(file_path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF file is password-protected / encrypted and cannot be read without a password.")
        total_pages = len(doc)
        logger.info(f"PDF has {total_pages} pages: {file_path}")
        for page_num in range(total_pages):
            page = doc[page_num]
            # Try block extraction with header/footer removal first
            text = _clean_page_blocks(page)
            if not text.strip():
                text = _extract_page_text(page)
            text = _clean_text(text)
            char_count = len(text.strip())
            logger.info(f"  Page {page_num + 1}: extracted {char_count} chars")
            if char_count > 0:
                yield {"page": page_num + 1, "text": text, "total": total_pages}


def count_pdf_pages(file_path: str) -> int:
    import pymupdf
    with pymupdf.open(file_path) as doc:
        return len(doc)


# ---------------------------------------------------------------------------
# DOCX Parsing via python-docx
# ---------------------------------------------------------------------------

def _extract_docx_paragraphs_and_tables(doc) -> list[str]:
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    seen_tcs = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tc_id = id(cell._tc)
                if tc_id in seen_tcs:
                    continue
                seen_tcs.add(tc_id)
                for p in cell.paragraphs:
                    if p.text.strip():
                        paragraphs.append(p.text)
    return paragraphs


def parse_docx(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for paragraph and table blocks of a DOCX.
    Groups paragraphs into ~300-word "virtual pages" for progress reporting.
    """
    from docx import Document

    doc = Document(file_path)
    paragraphs = _extract_docx_paragraphs_and_tables(doc)

    # Group into virtual pages of ~300 words
    virtual_page = []
    word_count = 0
    page_num = 0
    total_words = sum(len(p.split()) for p in paragraphs)
    total_pages = max(1, total_words // 300)

    for para in paragraphs:
        virtual_page.append(para)
        word_count += len(para.split())
        if word_count >= 300:
            page_num += 1
            text = "\n\n".join(virtual_page)
            yield {"page": page_num, "text": _clean_text(text), "total": total_pages}
            virtual_page = []
            word_count = 0

    # Flush remaining
    if virtual_page:
        page_num += 1
        text = "\n\n".join(virtual_page)
        yield {"page": page_num, "text": _clean_text(text), "total": max(total_pages, page_num)}


def count_docx_pages(file_path: str) -> int:
    from docx import Document
    doc = Document(file_path)
    paragraphs = _extract_docx_paragraphs_and_tables(doc)
    total_words = sum(len(p.split()) for p in paragraphs)
    return max(1, total_words // 300)


# ---------------------------------------------------------------------------
# EPUB Parsing via EbookLib + BeautifulSoup
# ---------------------------------------------------------------------------

def _get_epub_spine_items(book):
    from ebooklib import ITEM_DOCUMENT
    ordered = []
    seen_ids = set()
    for spine_entry in getattr(book, "spine", []) or []:
        item_id = spine_entry[0] if isinstance(spine_entry, (tuple, list)) else spine_entry
        if item_id in seen_ids:
            continue
        item = book.get_item_with_id(item_id)
        if item is not None and item.get_type() == ITEM_DOCUMENT:
            ordered.append(item)
            seen_ids.add(item_id)
    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT and item.get_id() not in seen_ids:
            ordered.append(item)
            seen_ids.add(item.get_id())
    return ordered


def parse_epub(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for each chapter of an EPUB in spine reading order,
    stripping <style> and <script> blocks cleanly.
    """
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(file_path)
    items = _get_epub_spine_items(book)
    total = max(1, len(items))

    for idx, item in enumerate(items, 1):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for junk in soup(["style", "script"]):
            junk.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = _clean_text(text)
        if text.strip():
            yield {"page": idx, "text": text, "total": total}


def count_epub_chapters(file_path: str) -> int:
    from ebooklib import epub
    book = epub.read_epub(file_path)
    return max(1, len(_get_epub_spine_items(book)))


# ---------------------------------------------------------------------------
# Unified Entry Point
# ---------------------------------------------------------------------------

def count_cbz_pages(file_path: str) -> int:
    """Returns image page count inside a CBZ/ZIP comic archive (excluding macOS metadata)."""
    import zipfile
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            img_exts = {".jpg", ".jpeg", ".png", ".webp"}
            count = sum(
                1 for n in zf.namelist()
                if Path(n).suffix.lower() in img_exts
                and not n.startswith(".")
                and not Path(n).name.startswith(".")
                and "__MACOSX/" not in n.replace("\\", "/")
            )
            return max(count, 1)
    except Exception:
        return 1


def _read_text_with_encoding_fallback(file_path: str) -> str:
    raw = Path(file_path).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        for enc in ("cp1253", "iso-8859-7", "cp1252"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


def parse_txt(file_path: str) -> Generator[dict, None, None]:
    """Parses a plain text file, respecting PAGE markers (preserving preamble) and encodings."""
    content = _read_text_with_encoding_fallback(file_path)
    clean = _clean_text(content)
    sections = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", clean)
    if len(sections) > 1:
        preamble = sections[0].strip()
        total = (len(sections) - 1) // 2 + (1 if preamble else 0)
        if preamble:
            yield {"page": 0, "text": preamble, "total": total}
        for i in range(1, len(sections), 2):
            pnum = int(sections[i])
            text = sections[i + 1].strip()
            yield {"page": pnum, "text": text, "total": total}
    else:
        pages = split_into_chunks(clean, max_chars=2000)
        total = max(len(pages), 1)
        for i, p_text in enumerate(pages):
            yield {"page": i + 1, "text": p_text, "total": total}


def parse_document(file_path: str, file_type: str) -> Generator[dict, None, None]:
    """
    Unified parser. file_type: 'pdf', 'docx', 'epub', 'cbz', 'cbr', 'txt' (case-insensitive)
    Yields: {page: int, text: str, total: int}
    """
    ft = (file_type or "").strip().lower().lstrip(".")
    if ft == "pdf":
        yield from parse_pdf(file_path)
    elif ft == "docx":
        yield from parse_docx(file_path)
    elif ft == "epub":
        yield from parse_epub(file_path)
    elif ft in ("cbz", "cbr", "zip"):
        total = count_cbz_pages(file_path)
        for i in range(total):
            yield {"page": i + 1, "text": f"[Comic Page {i+1}]", "total": total}
    elif ft == "txt":
        yield from parse_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def count_pages(file_path: str, file_type: str) -> int:
    """Returns estimated page/chapter count for progress tracking."""
    ft = (file_type or "").strip().lower().lstrip(".")
    try:
        if ft == "txt":
            content = _read_text_with_encoding_fallback(file_path)
            return max(1, len(content) // 2000)
        if ft == "pdf":
            return count_pdf_pages(file_path)
        elif ft == "docx":
            return count_docx_pages(file_path)
        elif ft == "epub":
            return count_epub_chapters(file_path)
        elif ft in ("cbz", "cbr", "zip"):
            return count_cbz_pages(file_path)
    except Exception:
        return 1
    return 1


COMIC_FILENAME_PATTERNS = (
    "graphic novel", "graphic_novel", "comic", "manga", "humanoids",
    "marvel", "dark horse", "image comics", "bande dessinee", "asterix",
    "tintin", "sanctum", "vertigo", "dc comics", "webtoon", "manhwa",
)


def detect_is_graphic_novel(file_path: str, file_type: str, file_name: str = "") -> dict:
    """
    Automatically detects whether an uploaded file is a Graphic Novel / Comic
    (including scanned image PDFs, digital comic PDFs with overlaid balloons,
    CBZ/CBR archives, and fixed-layout comic EPUBs).
    Returns: {"is_comic": bool, "is_scanned": bool, "reason": str}
    """
    ft = (file_type or "").lower()
    fname_lower = (file_name or Path(file_path).name).lower()

    if ft in ("cbz", "cbr", "zip"):
        return {
            "is_comic": True,
            "is_scanned": True,
            "reason": f"Comic archive format ({ft.upper()})",
        }

    filename_hint = any(k in fname_lower for k in COMIC_FILENAME_PATTERNS)

    if ft == "pdf":
        try:
            import pymupdf as fitz
            with fitz.open(file_path) as doc:
                total = len(doc)
                if total == 0:
                    return {"is_comic": False, "is_scanned": False, "reason": ""}

                # Sample up to 8 representative pages (prefer interior pages when total > 2)
                if total <= 8:
                    sample_indices = list(range(total))
                else:
                    step = max(1, (total - 1) // 7)
                    sample_indices = [min(total - 1, 1 + i * step) for i in range(8)]
                    sample_indices = sorted(set(sample_indices))

                full_image_pages = 0
                total_chars = 0
                sampled_count = len(sample_indices)

                for idx in sample_indices:
                    page = doc[idx]
                    txt = (page.get_text("text") or "").strip()
                    total_chars += len(txt)

                    page_area = max(1.0, page.rect.width * page.rect.height)
                    max_img_cov = 0.0
                    for img_info in page.get_images(full=True):
                        xref = img_info[0]
                        try:
                            for rect in page.get_image_rects(xref):
                                cov = (rect.width * rect.height) / page_area
                                if cov > max_img_cov:
                                    max_img_cov = cov
                        except Exception:
                            pass
                    if max_img_cov >= 0.60:
                        full_image_pages += 1

            avg_chars = total_chars / max(1, sampled_count)
            full_img_ratio = full_image_pages / max(1, sampled_count)
            is_scanned = (avg_chars < 35 and full_img_ratio >= 0.60)

            if is_scanned:
                return {
                    "is_comic": True,
                    "is_scanned": True,
                    "reason": f"Scanned image-based PDF detected ({int(full_img_ratio*100)}% full-page artwork, Vision AI mode)",
                }
            if filename_hint and (full_img_ratio >= 0.40 or avg_chars < 300):
                return {
                    "is_comic": True,
                    "is_scanned": False,
                    "reason": "Graphic novel / comic PDF detected (artwork + speech balloons)",
                }
            if full_img_ratio >= 0.65 and avg_chars < 220:
                return {
                    "is_comic": True,
                    "is_scanned": False,
                    "reason": f"Digital graphic novel PDF detected ({int(full_img_ratio*100)}% full-page artwork with dialogue blocks)",
                }
        except Exception as e:
            logger.debug(f"PDF graphic novel detection check skipped: {e}")

    elif ft == "epub" and filename_hint:
        try:
            from ebooklib import epub, ITEM_DOCUMENT
            from bs4 import BeautifulSoup
            book = epub.read_epub(file_path)
            docs = [it for it in book.get_items() if it.get_type() == ITEM_DOCUMENT][:8]
            if docs:
                img_only = 0
                for d in docs:
                    soup = BeautifulSoup(d.get_content(), "html.parser")
                    if soup.find("img") and len(soup.get_text(strip=True)) < 80:
                        img_only += 1
                if img_only / len(docs) >= 0.6:
                    return {
                        "is_comic": True,
                        "is_scanned": True,
                        "reason": "Fixed-layout Graphic Novel EPUB detected",
                    }
        except Exception:
            pass

    return {"is_comic": False, "is_scanned": False, "reason": ""}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Remove excessive whitespace, control characters, and proprietary Wingdings PUA symbols."""
    # Map common Wingdings/Symbol Private Use Area (PUA) characters to standard Unicode
    pua_map = {
        '\uf0b7': '• ',  # Wingdings round bullet
        '\uf0a7': '• ',  # Wingdings square bullet
        '\uf076': '✓ ',  # Checkmark
        '\uf0d8': '➢ ',  # Arrow
        '\uf0fc': '✔ ',  # Heavy checkmark
        '\uf0e0': '✉ ',  # Envelope
        '\uf0a8': '❖ ',
        '\uf02d': '-',
    }
    for pua, repl in pua_map.items():
        text = text.replace(pua, repl)
    # Replace any remaining Private Use Area characters with a standard bullet
    text = re.sub(r'[\ue000-\uf8ff]', '• ', text)

    # Standardize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # De-hyphenate line-wrapped words: e.g. "repre-\nsentation" -> "representation", "δια-\nδικασία" -> "διαδικασία"
    text = re.sub(r'([a-zA-Z\u0370-\u03FF\u1F00-\u1FFF])-[\n]+\s*([a-zA-Z\u0370-\u03FF\u1F00-\u1FFF])', r'\1\2', text)

    # Replace multiple newlines with double newline (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove null bytes and other control chars except newline/tab
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()


def split_into_chunks(text: str, max_chars: int = 4500) -> list[str]:
    """
    Splits text into chunks <= max_chars, splitting at sentence/paragraph
    or clause boundaries to preserve grammatical coherence and translation quality.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    # Try splitting by paragraphs first
    paragraphs = text.split('\n\n')
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = current + "\n\n" + para if current else para
        else:
            if current:
                chunks.append(current.strip())
                current = ""

            # If single paragraph is too long, split by sentences
            if len(para) > max_chars:
                # Include Greek question mark (; / \u037e), ellipsis (…), and quotes
                sentences = re.split(r'(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»"”\'\)\]]))\s+', para)
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_chars:
                        current = current + " " + sent if current else sent
                    else:
                        if current:
                            chunks.append(current.strip())
                            current = ""

                        # If single sentence is still longer than max_chars, split by clause boundaries
                        if len(sent) > max_chars:
                            clauses = re.split(r'(?<=[,:;—–])\s+', sent)
                            for clause in clauses:
                                if len(current) + len(clause) + 1 <= max_chars:
                                    current = current + " " + clause if current else clause
                                else:
                                    if current:
                                        chunks.append(current.strip())
                                        current = ""
                                    if len(clause) > max_chars:
                                        words = clause.split(' ')
                                        for word in words:
                                            if len(current) + len(word) + 1 <= max_chars:
                                                current = current + " " + word if current else word
                                            else:
                                                if current:
                                                    chunks.append(current.strip())
                                                    current = ""
                                                if len(word) > max_chars:
                                                    for i in range(0, len(word), max_chars):
                                                        sub_w = word[i : i + max_chars]
                                                        if len(sub_w) == max_chars:
                                                            chunks.append(sub_w)
                                                        else:
                                                            current = sub_w
                                                else:
                                                    current = word
                                    else:
                                        current = clause
                        else:
                            current = sent
            else:
                current = para

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if c.strip()]
