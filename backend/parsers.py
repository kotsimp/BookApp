"""
Document Parsers - extracts plain text from PDF, DOCX, and EPUB files.
Returns text in manageable chunks suitable for translation and TTS.
"""

import re
from pathlib import Path
from typing import Generator


# ---------------------------------------------------------------------------
# PDF Parsing via PyMuPDF
# ---------------------------------------------------------------------------

def parse_pdf(file_path: str) -> Generator[dict, None, None]:
    """
    Yields dicts: {page: int, text: str} for each page of a PDF.
    Handles large files efficiently via PyMuPDF's memory-mapped access.
    """
    import pymupdf  # fitz

    with pymupdf.open(file_path) as doc:
        total_pages = len(doc)
        for page_num in range(total_pages):
            page = doc[page_num]
            text = page.get_text("text")
            text = _clean_text(text)
            if text.strip():
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
    """Remove excessive whitespace and control characters."""
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
