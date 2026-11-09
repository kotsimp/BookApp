"""
format_preserver.py - Translates documents in-place while preserving rich formatting:
- DOCX: Preserves font family, font size, bold, italic, underline, alignment, paragraph styles, headings, tables, and colors.
- EPUB: Preserves HTML structure, headings (h1-h6), CSS stylesheets, styling tags (strong, em, span), images, and chapter hierarchy.
"""

import os
import re
import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable

from backend.translator import _translate_with_retry

logger = logging.getLogger(__name__)


def _sanitize_pua(text: str) -> str:
    """Map Wingdings / Symbol Private Use Area (PUA) bullet characters to standard Unicode."""
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
    return re.sub(r"[\ue000-\uf8ff]", "• ", text)


async def translate_docx_in_place(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    """
    Translates a .docx file in-place, preserving paragraph styles, headings,
    fonts, font sizes, bold/italic, alignment, tables, and images.
    Returns the full translated text (useful for .txt backup or audiobook generation).
    """
    import docx

    doc = docx.Document(input_path)

    # Collect all paragraphs to translate (both main body and inside table cells)
    paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    paragraphs.append(p)

    active_paragraphs = [p for p in paragraphs if p.text.strip()]
    total = len(active_paragraphs)
    all_translated_lines = []

    for idx, p in enumerate(active_paragraphs):
        if progress_callback:
            progress_callback(idx, total, f"Translating paragraph {idx+1} of {total} (preserving styles)...")

        runs_with_text = [r for r in p.runs if r.text.strip()]

        has_mixed_styles = False
        if len(runs_with_text) > 1:
            first_b = runs_with_text[0].bold
            first_i = runs_with_text[0].italic
            for r in runs_with_text[1:]:
                if r.bold != first_b or r.italic != first_i:
                    has_mixed_styles = True
                    break

        if not has_mixed_styles or len(runs_with_text) <= 1:
            # Uniform styling: translate full text for best grammatical quality
            orig_text = _sanitize_pua(p.text.strip())
            translated = await _translate_with_retry(orig_text, source_lang, target_lang)
            translated = _sanitize_pua(translated)
            if p.runs:
                p.runs[0].text = translated
                for r in p.runs[1:]:
                    r.text = ""
            else:
                p.text = translated
            all_translated_lines.append(translated)
        else:
            # Mixed styling (e.g. bold header + normal body): translate each run in-place
            para_translated_parts = []
            for r in p.runs:
                if not r.text.strip():
                    continue
                sanitized_run = _sanitize_pua(r.text)
                leading_ws = len(sanitized_run) - len(sanitized_run.lstrip())
                trailing_ws = len(sanitized_run) - len(sanitized_run.rstrip())
                tr_text = await _translate_with_retry(sanitized_run.strip(), source_lang, target_lang)
                tr_text = _sanitize_pua(tr_text)
                r.text = (" " * leading_ws) + tr_text + (" " * trailing_ws)
                para_translated_parts.append(tr_text)
            all_translated_lines.append(" ".join(para_translated_parts))

        # Yield to event loop briefly
        await asyncio.sleep(0.04)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    logger.info(f"Saved format-preserved DOCX to {output_path}")

    return "\n\n".join(all_translated_lines)


async def translate_epub_in_place(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    """
    Translates an .epub file in-place, preserving HTML structure, tags (h1-h6, p, em, strong),
    CSS links, styling, and images.
    Returns the full translated text.
    """
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup, NavigableString

    book = epub.read_epub(input_path)
    book.set_language("el" if target_lang == "greek" else "en")

    doc_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
    total_docs = len(doc_items)
    all_translated_lines = []

    for d_idx, item in enumerate(doc_items):
        if progress_callback:
            progress_callback(d_idx, total_docs, f"Translating chapter {d_idx+1} of {total_docs} (preserving HTML/CSS)...")

        soup = BeautifulSoup(item.get_content(), "html.parser")
        tags_to_translate = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "dt", "dd", "blockquote"])

        for tag in tags_to_translate:
            orig_text = tag.get_text(strip=True)
            if not orig_text:
                continue

            if len(tag.find_all()) == 0:
                tr = await _translate_with_retry(orig_text, source_lang, target_lang)
                tag.string = tr
                all_translated_lines.append(tr)
            else:
                for child in list(tag.children):
                    if isinstance(child, NavigableString) and child.strip():
                        tr = await _translate_with_retry(str(child).strip(), source_lang, target_lang)
                        child.replace_with(tr)
                        all_translated_lines.append(tr)
                    elif hasattr(child, "get_text") and child.get_text(strip=True):
                        tr = await _translate_with_retry(child.get_text(strip=True), source_lang, target_lang)
                        child.string = tr
                        all_translated_lines.append(tr)

            await asyncio.sleep(0.03)

        item.set_content(str(soup).encode("utf-8"))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book, {})
    logger.info(f"Saved format-preserved EPUB to {output_path}")

    return "\n\n".join(all_translated_lines)
