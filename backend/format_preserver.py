"""
format_preserver.py - Translates documents in-place while preserving rich formatting:
- DOCX: Preserves font family, font size, bold, italic, underline, alignment, paragraph styles, headings, tables, and colors.
- EPUB: Preserves HTML structure, headings (h1-h6), CSS stylesheets, styling tags (strong, em, span), images, and chapter hierarchy.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable

from backend.translator import _translate_with_retry
from backend.glossary import apply_glossary
from backend.exporter import _sanitize_pua

logger = logging.getLogger(__name__)


def _postprocess_translated_fragment(text: str, target_lang: str, style: Optional[str] = None) -> str:
    """Applies style-aware glossary and Greek typography cleanup to a translated fragment."""
    lang = (target_lang or "greek").strip().lower()
    out = apply_glossary(_sanitize_pua(text), lang, style=style)
    if lang in ("greek", "el"):
        from backend.typography import format_greek_typography
        out = format_greek_typography(out, enable_dialogue_dashes=False)
    return out


def _clear_run_text_preserving_media(run) -> None:
    """Clears only text (<w:t>) inside a run while preserving embedded images (<w:drawing>), breaks (<w:br>), and tabs."""
    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    has_media = any(
        child.tag in (f"{w_ns}drawing", f"{w_ns}pict", f"{w_ns}br", f"{w_ns}tab", f"{w_ns}object")
        for child in run._r
    )
    if not has_media:
        run.text = ""
    else:
        for t_el in run._r.findall(f"{w_ns}t"):
            t_el.text = ""


async def translate_docx_in_place(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    style: Optional[str] = None,
) -> str:
    """
    Translates a .docx file in-place, preserving paragraph styles, headings,
    fonts, font sizes, bold/italic, alignment, tables, and embedded images.
    Returns the full translated text (useful for .txt backup or audiobook generation).
    """
    import docx

    doc = docx.Document(input_path)

    # Collect all paragraphs to translate (deduplicating merged table cells by XML _tc id)
    paragraphs = list(doc.paragraphs)
    seen_tcs = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tc_id = id(cell._tc)
                if tc_id in seen_tcs:
                    continue
                seen_tcs.add(tc_id)
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
            translated = _postprocess_translated_fragment(translated, target_lang, style=style)
            if runs_with_text:
                target_run = runs_with_text[0]
                target_run.text = translated
                target_r_xml = target_run._r
                for r in p.runs:
                    if r._r is not target_r_xml:
                        _clear_run_text_preserving_media(r)
            elif p.runs:
                first_r_xml = p.runs[0]._r
                p.runs[0].text = translated
                for r in p.runs:
                    if r._r is not first_r_xml:
                        _clear_run_text_preserving_media(r)
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
                tr_text = _postprocess_translated_fragment(tr_text, target_lang, style=style)
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
    style: Optional[str] = "literature",
) -> str:
    """
    Translates an .epub file in-place, preserving HTML structure, tags (h1-h6, p, em, strong),
    CSS links, styling, comments, and images without double-translating nested tags.
    Returns the full translated text.
    """
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup, NavigableString, Comment

    lang_norm = (target_lang or "greek").strip().lower()
    book = epub.read_epub(input_path)
    book.set_language("el" if lang_norm in ("greek", "el") else "en")

    doc_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
    total_docs = len(doc_items)
    all_translated_lines = []
    block_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "dt", "dd", "blockquote"}

    async def _translate_text_nodes(node) -> list[str]:
        parts: list[str] = []
        for child in list(node.children):
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                raw_s = str(child)
                if not raw_s.strip():
                    continue
                lead = raw_s[: len(raw_s) - len(raw_s.lstrip())]
                trail = raw_s[len(raw_s.rstrip()) :]
                tr = await _translate_with_retry(raw_s.strip(), source_lang, target_lang)
                tr = _postprocess_translated_fragment(tr, target_lang, style=style)
                child.replace_with(f"{lead}{tr}{trail}")
                parts.append(tr)
            elif getattr(child, "name", None) and child.name not in ("script", "style", "img", "svg", "br", "hr"):
                # Recurse into inline elements (em, strong, a, span) without destroying them;
                # skip nested block tags because they are visited in the outer block list
                if child.name not in block_tags:
                    parts.extend(await _translate_text_nodes(child))
        return parts

    for d_idx, item in enumerate(doc_items):
        if progress_callback:
            progress_callback(d_idx, total_docs, f"Translating chapter {d_idx+1} of {total_docs} (preserving HTML/CSS)...")

        soup = BeautifulSoup(item.get_content(), "html.parser")
        tags_to_translate = soup.find_all(list(block_tags))

        for tag in tags_to_translate:
            if not tag.get_text(strip=True):
                continue
            translated_parts = await _translate_text_nodes(tag)
            if translated_parts:
                all_translated_lines.append(" ".join(translated_parts))
            await asyncio.sleep(0.03)

        item.set_content(str(soup).encode("utf-8"))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book, {})
    logger.info(f"Saved format-preserved EPUB to {output_path}")

    return "\n\n".join(all_translated_lines)
