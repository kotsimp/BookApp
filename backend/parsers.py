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


def parse_pdf(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for each page of a PDF.
    Tries multiple extraction modes for best text coverage.
    """
    import pymupdf  # fitz

    with pymupdf.open(file_path) as doc:
        total_pages = len(doc)
        logger.info(f"PDF has {total_pages} pages: {file_path}")
        for page_num in range(total_pages):
            page = doc[page_num]
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

def parse_docx(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for paragraph blocks of a DOCX.
    Groups paragraphs into ~500-word "virtual pages" for progress reporting.
    """
    from docx import Document

    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

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
    total_words = sum(len(p.text.split()) for p in doc.paragraphs if p.text.strip())
    return max(1, total_words // 300)


# ---------------------------------------------------------------------------
# EPUB Parsing via EbookLib + BeautifulSoup
# ---------------------------------------------------------------------------

def parse_epub(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for each chapter of an EPUB.
    """
    from ebooklib import epub, ITEM_DOCUMENT
    from bs4 import BeautifulSoup

    book = epub.read_epub(file_path)
    items = [item for item in book.get_items() if item.get_type() == ITEM_DOCUMENT]
    total = len(items)

    for idx, item in enumerate(items, 1):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        text = _clean_text(text)
        if text.strip():
            yield {"page": idx, "text": text, "total": total}


def count_epub_chapters(file_path: str) -> int:
    from ebooklib import epub, ITEM_DOCUMENT
    book = epub.read_epub(file_path)
    return sum(1 for item in book.get_items() if item.get_type() == ITEM_DOCUMENT)


# ---------------------------------------------------------------------------
# Unified Entry Point
# ---------------------------------------------------------------------------

def parse_document(file_path: str, file_type: str) -> Generator[dict, None, None]:
    """
    Unified parser. file_type: 'pdf', 'docx', 'epub'
    Yields: {page: int, text: str, total: int}
    """
    if file_type == "pdf":
        yield from parse_pdf(file_path)
    elif file_type == "docx":
        yield from parse_docx(file_path)
    elif file_type == "epub":
        yield from parse_epub(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def count_pages(file_path: str, file_type: str) -> int:
    """Returns estimated page/chapter count for progress tracking."""
    if file_type == "pdf":
        return count_pdf_pages(file_path)
    elif file_type == "docx":
        return count_docx_pages(file_path)
    elif file_type == "epub":
        return count_epub_chapters(file_path)
    return 1


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

    # Replace multiple newlines with double newline (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove null bytes and other control chars except newline/tab
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()


def split_into_chunks(text: str, max_chars: int = 4500) -> list[str]:
    """
    Splits text into chunks ≤ max_chars, splitting at sentence/paragraph
    boundaries to preserve translation quality.
    """
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
            # If single paragraph is too long, split by sentences
            if len(para) > max_chars:
                sentences = re.split(r'(?<=[.!?])\s+', para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_chars:
                        current = current + " " + sent if current else sent
                    else:
                        if current:
                            chunks.append(current.strip())
                        current = sent
            else:
                current = para

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if c.strip()]
