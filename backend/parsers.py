"""
Document Parsers - extracts plain text from PDF, DOCX, and EPUB files.
Returns text in manageable chunks suitable for translation and TTS.
"""

import re
import logging
from functools import lru_cache
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


_HEADER_WINDOW = 6  # pages to either side that are compared to find running headers and footers


def _page_number_value(line: str) -> int:
    """The number printed by a line that may be a page number ('12', '- 12 -', 'xiv'), else 0."""
    s = line.strip().strip("-–—").strip()
    if re.fullmatch(r"\d{1,4}", s):
        return int(s)
    if _is_standalone_page_number(line):
        values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        digits = [values.get(c, 0) for c in s.upper()]
        return sum(-v if i + 1 < len(digits) and v < digits[i + 1] else v for i, v in enumerate(digits))
    return 0


def _may_number_page(value: int, page_no: int) -> bool:
    """1981, 1982... on consecutive pages are years of a diary, unless the document really is about that long."""
    return bool(value) and (value < 1000 or abs(value - page_no) <= 300)


def _page_lines(page) -> list[dict]:
    """The text lines of a page in content order, with position, font size and margin."""
    import pymupdf

    height = page.rect.height
    out = []
    data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_BLOCKS)
    for block_no, block in enumerate(data.get("blocks", [])):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            y0, y1 = line["bbox"][1], line["bbox"][3]
            zone = "top" if 0 < height and y0 < height * 0.12 else ("bottom" if 0 < height and y1 > height * 0.88 else "")
            out.append({
                "block": block_no, "text": text, "y0": y0, "y1": y1, "zone": zone,
                "size": max(s.get("size", 0.0) for s in spans),
            })
    return out


def _same_running_line(line: dict, other: dict, pages_apart: int, page_no: int) -> bool:
    if other["zone"] != line["zone"] or abs(other["y0"] - line["y0"]) > 3 or abs(other["size"] - line["size"]) > 0.7:
        return False
    a, b = " ".join(line["text"].split()).casefold(), " ".join(other["text"].split()).casefold()
    if a == b:
        return True
    if _CHAPTER_HEADING_GUARD_RE.match(line["text"]):
        return False  # 'Chapter 1', 'Chapter 2' are headings
    if _page_number_value(line["text"]):
        return False  # numbers alone are judged as page numbers, not as running lines
    if re.sub(r"\d+", "#", a) != re.sub(r"\d+", "#", b):
        return False
    # the same words around a number that counts the pages ('Blindsight 6', 'Blindsight 7')
    return any(int(y) - int(x) == pages_apart and _may_number_page(int(x), page_no)
               for x, y in zip(re.findall(r"\d+", a), re.findall(r"\d+", b)))


def _labels_are_printed(doc, lines_of) -> bool:
    """
    True when the PDF's own page labels are the numbers printed in its margins (pages sampled across the book):
    then a page's label says which of its margin numbers is the page number.
    """
    try:
        if not doc.get_page_labels():
            return False
        total = len(doc)
        printed = matched = 0
        for i in sorted(set(range(0, total, max(1, total // 40)))):
            values = {_page_number_value(ln["text"]) for ln in lines_of(i) if ln["zone"] and len(ln["text"]) <= 100}
            values.discard(0)
            if values:
                printed += 1
                matched += _page_number_value(doc[i].get_label() or "") in values
        return matched >= 3 and matched >= 0.6 * printed
    except Exception as e:  # unreadable labels: the evidence below still decides
        logger.debug(f"PDF page labels not used: {e}")
        return False


def _clean_page_blocks(page, lines_of=None, labels_printed: bool = False) -> str:
    """
    Extracts a page's text without running headers, footers and page numbers.

    A margin line is removed only with evidence: it is repeated at the same place on neighbouring pages, or it is a
    number that counts the pages. A short line near the top alone proves nothing: it may be the book's or chapter's
    title, a line of dialogue or a date. Anything larger than the body text is a heading and always stays.
    When the PDF's page labels are its printed numbers (labels_printed), a number equal to the page's label is
    the page number, also where no neighbour proves it.
    """
    doc, number = page.parent, page.number
    if lines_of is None:
        lines_of = lru_cache(maxsize=None)(lambda i: _page_lines(doc[i]))
    lines = lines_of(number)
    if not lines:
        return ""

    margin = [ln for ln in lines if ln["zone"] and len(ln["text"]) <= 100]
    dropped: set[int] = set()
    if margin:
        first, last = max(0, number - _HEADER_WINDOW), min(len(doc), number + _HEADER_WINDOW + 1)
        near = [(i, lines_of(i)) for i in range(first, last) if i != number]

        # size of the running text: the size most characters around this page are set in
        weights: dict[float, int] = {}
        for other_lines in [lines] + [other for _, other in near]:
            for ln in other_lines:
                if not ln["zone"]:
                    size = round(ln["size"], 1)
                    weights[size] = weights.get(size, 0) + len(ln["text"])
        body_size = max(weights, key=weights.get) if weights else float("inf")
        small = [ln for ln in margin if ln["size"] <= body_size * 1.25]

        decorated, counting = [], []
        for ln in small:
            value = _page_number_value(ln["text"])
            if not value:
                continue
            if re.fullmatch(r"[-–—]\s*\d{1,4}\s*[-–—]", ln["text"]):
                decorated.append(ln)
            elif _may_number_page(value, number + 1) and any(
                other["zone"] == ln["zone"] and abs(other["y0"] - ln["y0"]) <= 4
                and (other_value := _page_number_value(other["text"])) and other_value - value == i - number
                for i, other_lines in near for other in other_lines
            ):
                counting.append(ln)
        # A page has one number. When more lines count up (a numbered poem and the folio), the others are the book's.
        numbers = decorated
        if not numbers and counting:
            foot = [ln for ln in counting if ln["zone"] == "bottom"]
            outer = max(foot, key=lambda ln: ln["y1"]) if foot else min(counting, key=lambda ln: ln["y0"])
            numbers = [ln for ln in counting
                       if ln["zone"] == outer["zone"] and _page_number_value(ln["text"]) == _page_number_value(outer["text"])]
        if labels_printed:  # the number that is the page's label is its folio; without one, the evidence above
            label = _page_number_value(page.get_label() or "")
            numbers = [ln for ln in small if label and _page_number_value(ln["text"]) == label] or numbers
        dropped.update(id(ln) for ln in numbers)

        for ln in small:
            if id(ln) in dropped:
                continue
            repeats = [i for i, other_lines in near
                       if any(_same_running_line(ln, other, i - number, number + 1) for other in other_lines)]
            if any(abs(i - number) <= 3 for i in repeats) and (len(repeats) >= 2 or numbers):
                dropped.add(id(ln))

    blocks: list[list[str]] = []
    block_no = None
    for ln in lines:
        if id(ln) in dropped:
            continue
        if ln["block"] != block_no:
            blocks.append([])
            block_no = ln["block"]
        blocks[-1].append(ln["text"])
    return "\n\n".join("\n".join(b) for b in blocks)


def parse_pdf(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for each page of a PDF.
    Tries multiple extraction modes for best text coverage, stripping running headers/footers.
    A scanned book whose pages Gemini Vision has read (backend.scan_reader) yields that text instead.
    """
    import pymupdf  # fitz
    from backend.scan_reader import read_pages

    scanned_text = read_pages(file_path)
    if scanned_text is not None:
        logger.info(f"Scanned PDF: using the text read from its {len(scanned_text)} page images: {file_path}")
        yield from scanned_text
        return

    with pymupdf.open(file_path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF file is password-protected / encrypted and cannot be read without a password.")
        total_pages = len(doc)
        logger.info(f"PDF has {total_pages} pages: {file_path}")
        lines_of = lru_cache(maxsize=4 * _HEADER_WINDOW)(lambda i: _page_lines(doc[i]))
        labels_printed = _labels_are_printed(doc, lines_of)
        for page_num in range(total_pages):
            page = doc[page_num]
            # Try block extraction with header/footer removal first
            text = _clean_page_blocks(page, lines_of, labels_printed)
            if not text.strip() and not lines_of(page_num):  # not a page that held only its header and number
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

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_M_TEXT = "{http://schemas.openxmlformats.org/officeDocument/2006/math}t"


def _docx_paragraph_texts(root) -> list[str]:
    """
    Every paragraph under `root` in reading order, as the reader sees it: tables where they stand (also nested), text
    boxes, content controls, fields, links and tracked insertions; no tracked deletions, no duplicate fallback copies.
    """
    hidden = {f"{_W}del", f"{_W}moveFrom", _MC_FALLBACK}
    not_text = hidden | {f"{_W}pPr", f"{_W}rPr", f"{_W}instrText", f"{_W}p"}  # a nested w:p is a paragraph of its own
    marks = {f"{_W}tab": "\t", f"{_W}ptab": "\t", f"{_W}br": "\n", f"{_W}cr": "\n", f"{_W}noBreakHyphen": "-"}

    def collect(el, out: list[str]) -> None:
        for child in el:
            tag = child.tag
            if tag in not_text:
                continue
            if tag in (f"{_W}t", _M_TEXT):
                out.append(child.text or "")
            elif tag in marks:
                out.append(marks[tag])
            else:
                collect(child, out)

    found = []
    for p in root.iter(f"{_W}p"):
        pieces: list[str] = []
        collect(p, pieces)
        text = "".join(pieces)
        if text.strip() and not any(a.tag in hidden for a in p.iterancestors()):
            found.append(text)
    return found


def _extract_docx_paragraphs_and_tables(doc) -> list[str]:
    """The body in reading order, then its footnotes and endnotes (they were silently lost on conversion)."""
    from lxml import etree

    paragraphs = _docx_paragraph_texts(doc.element.body)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    for kind in ("/footnotes", "/endnotes"):
        for rel in doc.part.rels.values():
            if rel.reltype.endswith(kind) and not rel.is_external:
                try:
                    paragraphs += _docx_paragraph_texts(etree.fromstring(rel.target_part.blob, parser))
                except etree.XMLSyntaxError as e:
                    logger.warning(f"Skipped unreadable {kind[1:]}: {e}")
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


_HTML_INLINE = frozenset(
    "a abbr acronym b bdi bdo big cite code data del dfn em font i ins kbd label mark q rp rt ruby s samp small span "
    "strike strong sub sup time tt u var wbr math mi mn mo mrow msup msub mtext msqrt semantics".split()
)


def _html_to_text(html) -> str:
    """Plain text of a page: a paragraph per block, inline markup never breaks a sentence or a word."""
    from bs4 import BeautifulSoup
    from bs4.element import CData, NavigableString, Tag

    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("body") or soup
    out: list[str] = []
    stack = [("node", root, False)]
    while stack:
        kind, node, verbatim = stack.pop()
        if kind == "text":
            out.append(node)
            continue
        if not isinstance(node, Tag):
            if type(node) in (NavigableString, CData):  # not comments, doctypes or processing instructions
                out.append(str(node) if verbatim else re.sub(r"[ \t\r\n\f]+", " ", str(node)))
            continue
        name = node.name.rsplit(":", 1)[-1].lower()
        if name in ("style", "script", "template", "title"):
            continue
        if name == "br":
            out.append("\n")  # an unclosed <br> may have swallowed the rest of the paragraph as children
        is_block = name != "br" and name not in _HTML_INLINE and name != "img"
        if is_block:
            out.append("\n\n")
            stack.append(("text", "\n\n", False))
        keep_lines = verbatim or name == "pre"
        stack.extend(("node", child, keep_lines) for child in reversed(node.contents))
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", "".join(out))
    text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_epub(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for each chapter of an EPUB in spine reading order,
    stripping <style> and <script> blocks cleanly.
    """
    from ebooklib import epub

    book = epub.read_epub(file_path)
    items = _get_epub_spine_items(book)
    total = max(1, len(items))

    for idx, item in enumerate(items, 1):
        text = _clean_text(_html_to_text(item.get_content()))
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

_LIGATURES = {0xFB00: "ff", 0xFB01: "fi", 0xFB02: "fl", 0xFB03: "ffi", 0xFB04: "ffl", 0xFB05: "st", 0xFB06: "st"}


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

    # PDF ligature glyphs ('efficient' stored with a single ffi character) break search, translation and speech
    for code, letters in _LIGATURES.items():
        text = text.replace(chr(code), letters)
    # A soft hyphen only marks where a word may break
    text = re.sub(chr(0xAD) + r'(?:\n[ \t]*)?', '', text)

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
