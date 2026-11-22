"""
format_preserver.py - Translates documents in-place while preserving rich formatting:
- DOCX: Preserves font family, font size, bold, italic, underline, alignment, paragraph styles, headings, tables, and colors.
- EPUB: Preserves HTML structure, headings (h1-h6), CSS stylesheets, styling tags (strong, em, span), images, and chapter hierarchy.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable, List, Awaitable

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


SegmentTranslator = Callable[[List[str]], Awaitable[List[str]]]


async def _translate_units(
    units: List[str],
    source_lang: str,
    target_lang: str,
    segment_translator: Optional[SegmentTranslator],
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Translates collected units. With a segment_translator (AI) they go in context-preserving batches; otherwise
    each unit is translated by the free engine exactly as before."""
    if segment_translator is not None:
        out = await segment_translator(units)
        if len(out) != len(units):
            raise RuntimeError("segment translator returned a misaligned result")
        return out
    out: List[str] = []
    for i, u in enumerate(units):
        if progress:
            progress(i, len(units))
        out.append(await _translate_with_retry(u, source_lang, target_lang) if u.strip() else u)
        await asyncio.sleep(0.04)  # yield to the event loop
    return out


async def translate_docx_in_place(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    style: Optional[str] = None,
    segment_translator: Optional[SegmentTranslator] = None,
) -> str:
    """
    Translates a .docx file in-place, preserving paragraph styles, headings,
    fonts, font sizes, bold/italic, alignment, tables, and embedded images.
    Units are collected first, translated (free engine or AI segment batches), then written back in place.
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

    # 1. Collect translation units
    units: List[str] = []
    plan = []
    for p in active_paragraphs:
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
            # Uniform styling: translate the full paragraph for best grammatical quality
            units.append(_sanitize_pua(p.text.strip()))
            plan.append(("para", p, runs_with_text, len(units) - 1))
        else:
            # Mixed styling (e.g. bold header + normal body): one unit per run, kept in place
            run_units = []
            for r in p.runs:
                if not r.text.strip():
                    continue
                sanitized_run = _sanitize_pua(r.text)
                leading_ws = len(sanitized_run) - len(sanitized_run.lstrip())
                trailing_ws = len(sanitized_run) - len(sanitized_run.rstrip())
                units.append(sanitized_run.strip())
                run_units.append((r, leading_ws, trailing_ws, len(units) - 1))
            plan.append(("runs", p, run_units, None))

    total = len(active_paragraphs)

    def _prog(done, n):
        if progress_callback:
            progress_callback(min(total, int(done * total / max(n, 1))), total,
                              f"Translating paragraph {min(total, int(done * total / max(n, 1))) + 1} of {total} (preserving styles)...")

    # 2. Translate
    translated = await _translate_units(units, source_lang, target_lang, segment_translator, _prog)
    translated = [_postprocess_translated_fragment(t, target_lang, style=style) for t in translated]

    # 3. Write back in place
    all_translated_lines = []
    for kind, p, data, idx in plan:
        if kind == "para":
            tr = translated[idx]
            runs_with_text = data
            if runs_with_text:
                target_run = runs_with_text[0]
                target_run.text = tr
                target_r_xml = target_run._r
                for r in p.runs:
                    if r._r is not target_r_xml:
                        _clear_run_text_preserving_media(r)
            elif p.runs:
                first_r_xml = p.runs[0]._r
                p.runs[0].text = tr
                for r in p.runs:
                    if r._r is not first_r_xml:
                        _clear_run_text_preserving_media(r)
            else:
                p.text = tr
            all_translated_lines.append(tr)
        else:
            parts = []
            for r, lead, trail, ridx in data:
                tr = translated[ridx]
                r.text = (" " * lead) + tr + (" " * trail)
                parts.append(tr)
            all_translated_lines.append(" ".join(parts))

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
    segment_translator: Optional[SegmentTranslator] = None,
) -> str:
    """
    Translates an .epub file in-place, preserving HTML structure, tags (h1-h6, p, em, strong),
    CSS links, styling, comments, and images without double-translating nested tags.
    Text nodes are collected first, translated (free engine or AI segment batches), then written back.
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
    block_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "dt", "dd", "blockquote"}

    units: List[str] = []
    nodes = []          # (NavigableString, lead, trail, unit index)
    blocks = []         # list of unit-index lists, one per block tag (for the plain-text backup)
    soups = []          # (item, soup) to serialise after write-back

    def _collect(node, acc):
        for child in list(node.children):
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                raw_s = str(child)
                if not raw_s.strip():
                    continue
                lead = raw_s[: len(raw_s) - len(raw_s.lstrip())]
                trail = raw_s[len(raw_s.rstrip()):]
                units.append(raw_s.strip())
                nodes.append((child, lead, trail, len(units) - 1))
                acc.append(len(units) - 1)
            elif getattr(child, "name", None) and child.name not in ("script", "style", "img", "svg", "br", "hr"):
                # Recurse into inline elements (em, strong, a, span); nested block tags are visited separately
                if child.name not in block_tags:
                    _collect(child, acc)

    # 1. Collect
    for item in doc_items:
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup.find_all(list(block_tags)):
            if not tag.get_text(strip=True):
                continue
            acc: List[int] = []
            _collect(tag, acc)
            if acc:
                blocks.append(acc)
        soups.append((item, soup))

    def _prog(done, n):
        if progress_callback:
            d = min(total_docs, int(done * total_docs / max(n, 1)))
            progress_callback(d, total_docs, f"Translating chapter {min(total_docs, d + 1)} of {total_docs} (preserving HTML/CSS)...")

    # 2. Translate
    translated = await _translate_units(units, source_lang, target_lang, segment_translator, _prog)
    translated = [_postprocess_translated_fragment(t, target_lang, style=style) for t in translated]

    # 3. Write back
    for child, lead, trail, idx in nodes:
        child.replace_with(f"{lead}{translated[idx]}{trail}")
    for item, soup in soups:
        item.set_content(str(soup).encode("utf-8"))
    all_translated_lines = [" ".join(translated[i] for i in b) for b in blocks]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book, {})
    logger.info(f"Saved format-preserved EPUB to {output_path}")

    return "\n\n".join(all_translated_lines)
