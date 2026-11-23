"""
format_preserver.py - Translates DOCX and EPUB documents in place, changing nothing but their text.

* DOCX: styles, fonts, runs, hyperlinks, tables (also nested), text boxes, images, breaks and sections stay;
  headers, footers, footnotes and endnotes are translated as well.
* EPUB: markup, attributes, CSS, SVG, images and navigation structure stay; navigation labels are translated too.

The package handling lives in backend.document_blocks, shared with backend.format_sync.
"""

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional, Callable, List, Awaitable, Dict

from backend.document_blocks import open_package
from backend import translator as _translator
from backend.translator import _translate_with_retry
from backend.glossary import apply_glossary
from backend.exporter import _sanitize_pua

logger = logging.getLogger(__name__)


def _postprocess_translated_fragment(
    text: str, target_lang: str, style: Optional[str] = None, explained: Optional[set] = None
) -> str:
    """Applies style-aware glossary and Greek typography cleanup to a translated fragment."""
    lang = (target_lang or "greek").strip().lower()
    out = apply_glossary(_sanitize_pua(text, editorial=False), lang, style=style, translated=True, explained=explained)
    if lang in ("greek", "el"):
        from backend.typography import format_greek_typography
        out = format_greek_typography(out, enable_dialogue_dashes=False)
    return out


SegmentTranslator = Callable[[List[str]], Awaitable[List[str]]]


async def _translate_units(
    units: List[str],
    source_lang: str,
    target_lang: str,
    segment_translator: Optional[SegmentTranslator],
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Translates collected units. With a segment_translator (AI) they go in context-preserving batches; otherwise
    each unit is translated by the free engine."""
    if segment_translator is not None:
        out = await segment_translator(units)
        if len(out) != len(units):
            raise RuntimeError("segment translator returned a misaligned result")
        return out
    out: List[str] = []
    ready: Dict[str, str] = {}
    batched = False
    for i, u in enumerate(units):
        if not batched and _translator.google_is_refusing():
            batched = True
            offset = i

            def batch_progress(done: int, total: int) -> None:
                if progress:
                    progress(offset + int(done / max(total, 1) * (len(units) - offset)), len(units))

            ready = await _translator.failover_in_batches(units[i:], source_lang, target_lang, batch_progress)
        if progress and not ready:
            progress(i, len(units))
        out.append(ready.get(u) or await _translate_with_retry(u, source_lang, target_lang))
        await asyncio.sleep(0.04)  # yield to the event loop
    return out


async def _translate_package(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Optional[Callable[[int, int, str], None]],
    style: Optional[str],
    segment_translator: Optional[SegmentTranslator],
    step_label: str,
    notes: Optional[list] = None,
) -> str:
    package = await asyncio.to_thread(open_package, input_path)
    kept = getattr(package, "kept_code", 0)
    if kept and notes is not None:
        notes.append(f"{kept} preformatted block(s) kept untranslated because they look like program "
                     "code: please check them.")

    # 1. Collect. A repeated text (heading + its table-of-contents entry, running headers) is translated once.
    units: List[str] = []
    index: Dict[str, int] = {}
    plan = []
    for block in package.body + package.extra:
        segments = block.segments()
        raws = ["".join(s.value for s in segment) for segment in segments]
        for k, (segment, raw) in enumerate(zip(segments, raws)):
            core = raw.strip()
            if not any(ch.isalpha() for ch in core):
                continue  # numbers, punctuation and page numbers stay as they are
            if len(core) == 1:
                # a lone letter that is a note mark or part of a symbol (storms^a, H2O) is not a word
                raised = bool(segment[0].fmt[2])
                glued_left = k > 0 and raws[k - 1][-1:].isalnum() and not raw[:1].isspace()
                glued_right = k + 1 < len(raws) and raws[k + 1][:1].isalnum() and not raw[-1:].isspace()
                if raised or glued_left or glued_right:
                    continue
            key = " ".join(_sanitize_pua(core, editorial=False).split())
            if key not in index:
                index[key] = len(units)
                units.append(key)
            lead = raw[:len(raw) - len(raw.lstrip())]
            trail = raw[len(raw.rstrip()):]
            plan.append((segment, lead, trail, index[key]))

    total = len(package.body)

    def _prog(done, n):
        if progress_callback:
            at = min(total, int(done * total / max(n, 1)))
            progress_callback(at, total, step_label.format(current=min(total, at + 1), total=total))

    # 2. Translate
    translated = await _translate_units(units, source_lang, target_lang, segment_translator, _prog)
    explained: set = set()  # each glossary term is explained once per document
    translated = [
        " ".join(_postprocess_translated_fragment(t, target_lang, style=style, explained=explained).split()) or units[i]
        for i, t in enumerate(translated)
    ]

    # 3. Write back, then save atomically
    def write_back() -> str:
        for segment, lead, trail, i in plan:
            package.set_segment(segment, f"{lead}{translated[i]}{trail}")
        package.set_language("el" if (target_lang or "").strip().lower() in ("greek", "el") else "en")
        text = "\n\n".join(t for t in (b.text for b in package.body) if t)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        staged = out.with_name(f".{uuid.uuid4().hex[:8]}.translate-tmp")
        try:
            staged.write_bytes(package.to_bytes())
            os.replace(staged, out)
        finally:
            staged.unlink(missing_ok=True)
        return text

    text = await asyncio.to_thread(write_back)
    logger.info(f"Saved format-preserved {Path(output_path).suffix.lstrip('.').upper()} to {output_path}")
    return re.sub(r"\n{3,}", "\n\n", text)


async def translate_docx_in_place(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    style: Optional[str] = None,
    segment_translator: Optional[SegmentTranslator] = None,
    notes: Optional[list] = None,
) -> str:
    """Translates a .docx in place. Returns the translated body text (for audiobooks, the editor and TXT export)."""
    return await _translate_package(
        input_path, output_path, source_lang, target_lang, progress_callback, style, segment_translator,
        "Translating paragraph {current} of {total} (preserving styles)...", notes,
    )


async def translate_epub_in_place(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    style: Optional[str] = "literature",
    segment_translator: Optional[SegmentTranslator] = None,
    notes: Optional[list] = None,
) -> str:
    """Translates an .epub in place. Returns the translated text in reading order."""
    return await _translate_package(
        input_path, output_path, source_lang, target_lang, progress_callback, style, segment_translator,
        "Translating block {current} of {total} (preserving HTML/CSS)...", notes,
    )
