"""
comic_translator.py - Specialized Graphic Novel & Comic Book Translation Engine.
Translates speech balloons, narration captions, and dialogue in graphic novels
while preserving 100% of the underlying illustrations, artwork, panels, and colors.

Features:
- Speech balloon text clustering and auto-detection
- Vector-level non-destructive redaction (preserves background drawings)
- Automatic background color sampling (white, off-white, tinted balloons)
- Dynamic comic typography (auto-font sizing, centered alignment, Comic Sans font)
- Multimodal Gemini Vision fallback for image-based/scanned comics
- Dual output: High-resolution Translated Comic PDF + Text dialogue script
"""

import os
import re
import json
import shutil
import uuid
import logging
import asyncio
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Tuple

import pymupdf as fitz
from PIL import Image

from backend.job_manager import update_job, is_job_cancelled
from backend import translator as _translator
from backend.translator import _translate_with_retry
from backend.glossary import apply_glossary
from backend.exporter import _BookFont, _draw_pdf_text, _plain_emphasis

logger = logging.getLogger(__name__)

COMIC_FONTS = [
    "C:/Windows/Fonts/comic.ttf",        # Comic Sans MS (ideal for comics)
    "C:/Windows/Fonts/comicbd.ttf",      # Comic Sans MS Bold
    "C:/Windows/Fonts/segoeui.ttf",      # Segoe UI
    "C:/Windows/Fonts/arial.ttf",         # Arial
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

CONDENSED_COMIC_FONTS = [
    "C:/Windows/Fonts/arialn.ttf",       # Arial Narrow (ideal fallback for super-dense Greek balloons)
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _get_comic_font_path() -> Optional[str]:
    """Returns the best available comic font supporting Greek characters."""
    for p in COMIC_FONTS:
        if os.path.exists(p):
            return p
    return None


def _get_condensed_comic_font_path() -> Optional[str]:
    """Returns a narrow/condensed Unicode Greek font for dense speech balloons."""
    for p in CONDENSED_COMIC_FONTS:
        if os.path.exists(p):
            return p
    return _get_comic_font_path()


_GREEK_UPPER_TONOS_MAP = str.maketrans("ΆΈΉΊΌΎΏάέήίόύώΐΰ", "ΑΕΗΙΟΥΩΑΕΗΙΟΥΩΪΫ")


def sanitize_comic_dialogue(text: str, target_lang: str = "greek", source_text: str = "") -> str:
    """
    Cleans and standardizes translated comic speech balloon dialogue:
    - Removes stray HTML tags, LLM tokens, markdown asterisks (*...*), and stray trailing backslashes
    - Fixes broken hyphenated words ('ΠΛΗΜ- ΜΥΡΙΣΕΙ' -> 'ΠΛΗΜΜΥΡΙΣΕΙ')
    - Restores missing Greek elision apostrophes ('Σ ΑΥΤΗΝ' -> \"Σ' ΑΥΤΗΝ\", 'ΓΙ ΑΥΤΟ' -> \"ΓΙ' ΑΥΤΟ\")
    - Converts English '?' / '?!' / '??!!' to Greek ';' / ';!' / ';;!!'
    - Applies Greek final-nu rules and guillemets («...»)
    - Fixes stray lowercase letters inside ALL-CAPS comic balloons (e.g. 'ΕΝΑς' -> 'ΕΝΑΣ')
    ``source_text`` is the balloon's original: a note or tag that it contains is content and stays.
    """
    if not text or not text.strip():
        return ""
    s = text.strip()

    from backend.ai_polisher import sanitize_ai_output
    s = sanitize_ai_output(s, source_text=source_text)

    # Strip stray markdown emphasis asterisks (*word* or leading * in comic balloons)
    s = _plain_emphasis(s)  # emphasis only: '2*3*4' keeps its signs
    s = re.sub(r"(?:^|\s)\*(?=\S)", lambda m: m.group(0).replace("*", ""), s)
    # Strip stray unescaped trailing backslash from malformed JSON escapes
    s = re.sub(r"\\+\s*$", "", s)
    # Collapse accidental internal newlines inside a single balloon sentence into spaces
    s = re.sub(r"[ \t]*\r?\n[ \t]*", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    if target_lang.lower().startswith(("gr", "el")):
        from backend.typography import format_greek_typography
        # Format quotes, final-nu, elision apostrophes, broken hyphens, and Greek question marks
        s = format_greek_typography(
            s,
            enable_quotes=True,
            enable_dialogue_dashes=False,
            enable_final_nu=True,
            enable_punctuation=True,
        )
        # Convert standalone comic exclamation/question balloons like '??!!' or '?!' to Greek ';'
        if re.fullmatch(r'[«»"\'\s]*\?+[!?]*[«»"\'\s]*', s):
            s = s.replace("?", ";")
        # If the balloon is predominantly ALL-CAPS (>= 75% uppercase Greek letters),
        # fix stray lowercase characters like 'ΕΝΑς' -> 'ΕΝΑΣ'
        alpha_chars = [ch for ch in s if ch.isalpha()]
        if alpha_chars:
            upper_ratio = sum(1 for ch in alpha_chars if ch.isupper()) / len(alpha_chars)
            if upper_ratio >= 0.75:
                # Uppercase while preserving disjunctive 'Ή' and dialytika 'Ϊ', 'Ϋ'
                tokens = s.split(" ")
                fixed_tokens = []
                for tok in tokens:
                    if tok in ("ή", "Ή"):
                        fixed_tokens.append("Ή")
                    else:
                        # Map dialytika+tonos (ΐ/ΰ -> Ϊ/Ϋ) BEFORE .upper() to avoid NFD combining-accent decomposition
                        pre_mapped = tok.replace("ΐ", "Ϊ").replace("ΰ", "Ϋ")
                        up = pre_mapped.upper()
                        # Remove tonos on uppercase Greek letters except standalone 'Ή' and dialytika 'Ϊ'/'Ϋ'
                        fixed_tokens.append(up.translate(_GREEK_UPPER_TONOS_MAP))
                s = " ".join(fixed_tokens)

    return s.strip()


def _comic_items_have_corruption(items: List[Dict[str, Any]], target_lang: str = "greek") -> bool:
    """
    Detects mixed-script or exotic-script token corruption (e.g. Armenian 'ΚՈΠΩΣΗ',
    Cyrillic 'ΗΜΑΣΤАН', Latin-in-Greek 'Τous', 'ΣΥΡIAKΕΣ', 'AΠΟΣΤΟΛΗ') in Vision JSON output.
    """
    if not items or not target_lang.lower().startswith(("gr", "el")):
        return False
    from backend.ai_polisher import detect_greek_output_issues
    combined_tr = "\n".join(
        str(it.get("translated_text") or it.get("translation") or it.get("greek_text") or "")
        for it in items
        if isinstance(it, dict)
    )
    combined_src = "\n".join(
        str(it.get("original_text") or "")
        for it in items
        if isinstance(it, dict)
    )
    if not combined_tr.strip():
        return False
    issues = detect_greek_output_issues(combined_tr, source_text=combined_src)
    return any(i.startswith("mixed_script") or i == "cot_leak" for i in issues)


_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_GREEK_LETTER = re.compile(r"[Ͱ-Ͽἀ-῿]")


def _item_translation(item: Dict[str, Any]) -> str:
    return str(item.get("translated_text") or item.get("translation") or item.get("greek_text") or "")


def _comic_items_in_latin_letters(items: List[Dict[str, Any]], target_lang: str = "greek") -> bool:
    """
    True when a Greek answer is written in Latin letters ("Greeklish": 'APO DO ERXETAI TO SIMA?'). The mixed-script
    check misses it, since no Greek word holds a Latin letter. Latin words the original balloon also has (USS, KGB, a
    sound effect, a name kept as it is) don't count: only words the model made up do.
    """
    if not items or not target_lang.lower().startswith(("gr", "el")):
        return False
    page_words = page_latin = page_greek = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        text = _item_translation(item)
        source = {w.lower() for w in _LATIN_WORD.findall(str(item.get("original_text") or ""))}
        invented = [w for w in _LATIN_WORD.findall(text) if w.lower() not in source]
        latin, greek = sum(map(len, invented)), len(_GREEK_LETTER.findall(text))
        if len(invented) >= 3 and latin > greek:
            return True
        page_words, page_latin, page_greek = page_words + len(invented), page_latin + latin, page_greek + greek
    return page_words >= 3 and page_latin > page_greek


def _comic_items_problem(items: List[Dict[str, Any]], target_lang: str = "greek") -> str:
    """Why a Vision answer can't be used as it is ("" when it can)."""
    if _comic_items_in_latin_letters(items, target_lang):
        return "Latin letters instead of Greek"
    if _comic_items_have_corruption(items, target_lang):
        return "mixed-script corruption"
    return ""


def _comic_caps(text: str) -> str:
    """Comic lettering: capitals without tonos, dialytika kept (Ϊ, Ϋ)."""
    return text.replace("ΐ", "Ϊ").replace("ΰ", "Ϋ").upper().translate(_GREEK_UPPER_TONOS_MAP)


def _item_names(item: Any) -> List[Tuple[str, str]]:
    """The balloon's {"NAME IN THE ORIGINAL": "NAME IN THE TRANSLATION"} pairs, as Vision reported them."""
    names = item.get("names") if isinstance(item, dict) else None
    if isinstance(names, dict):
        pairs = list(names.items())
    elif isinstance(names, list):
        pairs = [tuple(p) for p in names if isinstance(p, (list, tuple)) and len(p) == 2]
    else:
        return []
    out = []
    for src, tgt in pairs:
        if isinstance(src, str) and isinstance(tgt, str):
            src, tgt = " ".join(src.split()), " ".join(tgt.split())
            if src and tgt and len(src) <= 60 and len(tgt) <= 60:
                out.append((src, tgt))
    return out


def _record_comic_names(votes: Dict[str, Dict[str, int]], spelled: Dict[str, str], items: Any) -> None:
    """Counts how a page wrote each name: votes[NAME][RENDERING] += 1, keeping the first spelling of each rendering."""
    for item in items or []:
        for src, tgt in _item_names(item):
            key, rendering = _comic_caps(src), _comic_caps(tgt)
            counts = votes.setdefault(key, {})
            counts[rendering] = counts.get(rendering, 0) + 1
            spelled.setdefault(rendering, tgt)


def _comic_name_choices(votes: Dict[str, Dict[str, int]], spelled: Dict[str, str],
                        glossary: Dict[str, str]) -> Dict[str, str]:
    """One rendering per name: the user's glossary first, otherwise the one used most (the earliest on a tie)."""
    chosen = {}
    for key, counts in votes.items():
        if key in glossary:
            chosen[key] = glossary[key]
        elif counts:
            top = max(counts, key=counts.get)  # max keeps the first of equal counts, which is the earliest page
            chosen[key] = spelled.get(top, top)
    return chosen


def _inflected_alike(a: str, b: str) -> bool:
    """ΔΙΟΙΚΗΤΑ / ΔΙΟΙΚΗΤΗΣ: the same word in another case, not another spelling of a name."""
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n >= 3 and len(a) - n <= 2 and len(b) - n <= 2


def _replace_name(text: str, old: str, new: str) -> str:
    """Replaces the whole name `old` with `new`, ignoring case and tonos; capitals stay capitals."""
    folded = "".join(_comic_caps(c) if len(_comic_caps(c)) == 1 else c for c in text)
    pattern = re.compile(r"(?<!\w)" + re.escape(_comic_caps(old)) + r"(?!\w)")
    out, last = [], 0
    for m in pattern.finditer(folded):
        span = text[m.start():m.end()]
        out += [text[last:m.start()], _comic_caps(new) if span == span.upper() else new]
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def _harmonize_comic_names(pages: Dict[int, List[Dict[str, Any]]], glossary: Dict[str, str]) -> int:
    """
    Pages are translated one by one, so a name can come out spelled three ways in one book. Every balloon that names
    someone gets the rendering of the glossary or of most pages. Spellings that only differ in their last letters are
    Greek cases (ΔΙΟΙΚΗΤΑ / ΔΙΟΙΚΗΤΗΣ) and stay. Changes the items in place; returns how many balloons changed.
    """
    votes: Dict[str, Dict[str, int]] = {}
    spelled: Dict[str, str] = {}
    for _p, items in sorted(pages.items()):
        _record_comic_names(votes, spelled, items)
    chosen = _comic_name_choices(votes, spelled, glossary)
    changed = 0
    for items in pages.values():
        for item in items or []:
            if not isinstance(item, dict):
                continue
            text = new = _item_translation(item)
            for src, tgt in _item_names(item):
                best = chosen.get(_comic_caps(src))
                if best and not _inflected_alike(_comic_caps(tgt), _comic_caps(best)):
                    new = _replace_name(new, tgt, best)
            if new != text:
                key = next(k for k in ("translated_text", "translation", "greek_text") if item.get(k))
                item[key] = new
                changed += 1
    return changed


def _wrap_text_to_width(
    text: str,
    font_obj: fitz.Font,
    fontsize: float,
    max_width: float,
    allow_word_break: bool = True,
) -> Optional[List[str]]:
    """
    Wraps text cleanly into lines fitting within max_width.
    When allow_word_break=False, returns None if any single word exceeds max_width so the caller
    can shrink the font slightly instead of hyphenating a word unnecessarily.
    """
    words = text.split()
    if not words:
        return []
    lines: List[str] = []
    curr = ""
    for w in words:
        cand = f"{curr} {w}".strip() if curr else w
        if font_obj.text_length(cand, fontsize=fontsize) <= max_width:
            curr = cand
            continue
        if curr:
            lines.append(curr)
            curr = ""
        # Check if single word fits on its own line
        if font_obj.text_length(w, fontsize=fontsize) <= max_width:
            curr = w
        elif not allow_word_break:
            return None
        else:
            # Break overlong single word cleanly so text NEVER overflows or disappears
            piece = ""
            for ch in w:
                test_p = piece + ch
                if font_obj.text_length(test_p + "-", fontsize=fontsize) <= max_width or not piece:
                    piece = test_p
                else:
                    lines.append(piece + "-")
                    piece = ch
            curr = piece
    if curr:
        lines.append(curr)
    return lines


def _balloon_font(path: Optional[str]) -> _BookFont:
    """The lettering font, with stand-ins for what it lacks (a kept Japanese sound effect, polytonic Greek)."""
    if path and os.path.exists(path):
        try:
            return _BookFont(fitz.Font(fontfile=path), serif=False)
        except Exception as ex:
            logger.debug(f"Cannot use comic font {path}: {ex}")
    return _BookFont(fitz.Font("helv"), serif=False, builtin=True)


_BALLOON_REACH = 20.0  # two balloons may grow towards each other by this much together


def _separate_text_areas(page: fitz.Page, rects: List[fitz.Rect]) -> List[Tuple[fitz.Rect, fitz.Rect]]:
    """
    For each balloon the area of its text and the limit up to which that may grow. Touching captions (common under
    old comic panels) split the strip they share, so neither is printed into the other. The covers over the original
    letters keep their full size.
    """
    areas = [fitz.Rect(r) for r in rects]
    for i, a in enumerate(areas):
        for b in areas[i + 1:]:
            shared = a & b
            if shared.is_empty or shared.get_area() > 0.5 * min(a.get_area(), b.get_area()):
                continue  # apart, or one inside the other
            if shared.width <= shared.height:
                left, right = (a, b) if a.x0 + a.x1 <= b.x0 + b.x1 else (b, a)
                middle = (shared.x0 + shared.x1) / 2.0
                left.x1, right.x0 = middle, middle
            else:
                upper, lower = (a, b) if a.y0 + a.y1 <= b.y0 + b.y1 else (b, a)
                middle = (shared.y0 + shared.y1) / 2.0
                upper.y1, lower.y0 = middle, middle

    limits = [fitz.Rect(0, 0, page.rect.width, page.rect.height) for _ in areas]
    for i, a in enumerate(areas):
        for j, b in enumerate(areas):
            if i == j:
                continue
            gap_x, gap_y = max(b.x0 - a.x1, a.x0 - b.x1), max(b.y0 - a.y1, a.y0 - b.y1)
            if max(gap_x, gap_y) < 0 or max(gap_x, gap_y) >= _BALLOON_REACH:
                continue  # nested, or too far away to be reached
            limit = limits[i]
            if gap_x >= gap_y:
                if b.x0 >= a.x1:
                    limit.x1 = min(limit.x1, a.x1 + gap_x / 2.0)
                else:
                    limit.x0 = max(limit.x0, a.x0 - gap_x / 2.0)
            elif b.y0 >= a.y1:
                limit.y1 = min(limit.y1, a.y1 + gap_y / 2.0)
            else:
                limit.y0 = max(limit.y0, a.y0 - gap_y / 2.0)
    return list(zip(areas, limits))


def _plan_balloon_layout(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    font_path: str,
    max_fontsize: float = 13.0,
    limit: Optional[fitz.Rect] = None,
) -> Optional[Tuple[str, str, fitz.Font, fitz.Rect, float, List[str], float]]:
    """
    Computes the optimal (font_path, font_name, font_obj, final_box, fontsize, lines, line_h)
    for a comic balloon. Prefers unbroken words first, then shrinks/condenses/expands so a
    balloon NEVER renders blank.
    """
    if not text or not text.strip():
        return None

    page_w, page_h = page.rect.width, page.rect.height
    condensed_path = _get_condensed_comic_font_path()
    primary_font = _balloon_font(font_path)
    condensed_font = (
        _balloon_font(condensed_path)
        if (condensed_path and os.path.exists(condensed_path) and condensed_path != font_path)
        else primary_font
    )

    # Candidate layout strategies: (font_path, font_name, font_obj, ex_x, ex_y, sizes, line_mult, allow_break)
    strategies = [
        (font_path, "comic", primary_font, 0.0, 0.0, [13, 12, 11, 10, 9.5, 9, 8.5, 8, 7.5, 7, 6.5, 6, 5.5, 5.0], 1.12, False),
        (font_path, "comic", primary_font, 4.0, 3.0, [6.5, 6.0, 5.5, 5.0, 4.5], 1.08, False),
        (condensed_path, "comic_narrow", condensed_font, 5.0, 4.0, [6.5, 6.0, 5.5, 5.0, 4.5, 4.0], 1.06, False),
        (condensed_path, "comic_narrow", condensed_font, 10.0, 8.0, [5.0, 4.5, 4.0, 3.5, 3.0], 1.04, False),
        # Allow hyphenated word breaks only if no unbroken-word layout fit
        (condensed_path, "comic_narrow", condensed_font, 10.0, 8.0, [5.0, 4.5, 4.0, 3.5, 3.0], 1.04, True),
    ]

    for fpath, fname, fobj, ex_x, ex_y, sizes, line_mult, allow_break in strategies:
        box = fitz.Rect(
            max(1.0, rect.x0 - ex_x),
            max(1.0, rect.y0 - ex_y),
            min(page_w - 1.0, rect.x1 + ex_x),
            min(page_h - 1.0, rect.y1 + ex_y),
        )
        if limit is not None:
            box &= limit
        inner_w = max(8.0, box.width - 3.0)
        inner_h = max(8.0, box.height - 2.0)
        for fs in sizes:
            if fs > max_fontsize:
                continue
            lines = _wrap_text_to_width(text, fobj, fs, inner_w, allow_word_break=allow_break)
            if lines is None:
                continue
            line_h = fs * line_mult
            total_h = len(lines) * line_h
            if total_h <= inner_h:
                return (fpath, fname, fobj, box, fs, lines, line_h)

    # Absolute last-resort guarantee: expand box height to hold 3.0pt condensed text so text NEVER vanishes
    fpath, fname, fobj = condensed_path, "comic_narrow", condensed_font
    fs = 3.0
    line_h = fs * 1.04
    box = fitz.Rect(
        max(1.0, rect.x0 - 10.0),
        max(1.0, rect.y0 - 6.0),
        min(page_w - 1.0, rect.x1 + 10.0),
        min(page_h - 1.0, rect.y1 + 6.0),
    )
    if limit is not None:
        box &= limit
    inner_w = max(10.0, box.width - 3.0)
    lines = _wrap_text_to_width(text, fobj, fs, inner_w, allow_word_break=True) or [text]
    needed_h = len(lines) * line_h + 3.0
    if needed_h > box.height:
        extra = (needed_h - box.height) / 2.0
        box = fitz.Rect(
            box.x0,
            max(1.0, box.y0 - extra),
            box.x1,
            min(page_h - 1.0, box.y1 + extra),
        )
    return (fpath, fname, fobj, box, fs, lines, line_h)


def _draw_planned_balloon_text(
    page: fitz.Page,
    plan: Tuple[str, str, fitz.Font, fitz.Rect, float, List[str], float],
    text_color: Tuple[float, float, float],
) -> None:
    """Draws horizontally & vertically centered Greek comic text for a precomputed balloon layout plan."""
    fpath, fname, fobj, final_box, fs, lines, line_h = plan
    if fpath and os.path.exists(fpath):
        try:
            page.insert_font(fontname=fname, fontfile=fpath)
        except Exception:
            pass
    total_h = len(lines) * line_h
    start_y = final_box.y0 + max(1.0, (final_box.height - total_h) / 2.0) + fs * 0.85
    use_fontname = fname if (fpath and os.path.exists(fpath)) else "helv"
    for idx, ln in enumerate(lines):
        lw = fobj.text_length(ln, fontsize=fs)
        tx = final_box.x0 + max(1.0, (final_box.width - lw) / 2.0)
        ty = start_y + idx * line_h
        _draw_pdf_text(page, fitz.Point(tx, ty), ln, fobj, fs, use_fontname, text_color)


def _fit_and_draw_balloon_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    font_path: str,
    bg_rgb: Tuple[float, float, float],
    text_color: Tuple[float, float, float],
    max_fontsize: float = 13.0,
    draw_bg: bool = True,
    limit: Optional[fitz.Rect] = None,
) -> bool:
    """Fits, centers, and draws Greek comic dialogue inside a single speech balloon."""
    plan = _plan_balloon_layout(page, rect, text, font_path, max_fontsize=max_fontsize, limit=limit)
    if plan is None:
        return False
    if draw_bg:
        page.draw_rect(plan[3], color=bg_rgb, fill=bg_rgb, overlay=True)
    _draw_planned_balloon_text(page, plan, text_color)
    return True


def _sample_balloon_bg_color(page: fitz.Page, rect: fitz.Rect) -> Tuple[float, float, float]:
    """
    Samples background color of the speech balloon around the text bbox.
    Defaults to pure white (1.0, 1.0, 1.0) if sampling fails or is inconclusive.
    """
    try:
        # Sample a 6x6 pixel area just outside the top-left of the text bounding box
        sample_x = max(2, int(rect.x0 - 3))
        sample_y = max(2, int(rect.y0 - 3))
        clip_rect = fitz.Rect(sample_x, sample_y, sample_x + 4, sample_y + 4)
        pix = page.get_pixmap(clip=clip_rect, dpi=72)
        if pix.width > 0 and pix.height > 0:
            samples = []
            for y in range(pix.height):
                for x in range(pix.width):
                    color = pix.pixel(x, y)
                    # Convert to normalized 0-1 float tuple
                    r, g, b = color[0] / 255.0, color[1] / 255.0, color[2] / 255.0
                    samples.append((r, g, b))
            if samples:
                # Average sampled pixels
                avg_r = sum(s[0] for s in samples) / len(samples)
                avg_g = sum(s[1] for s in samples) / len(samples)
                avg_b = sum(s[2] for s in samples) / len(samples)
                # If luminance is high (> 0.75), use the sampled tint; otherwise default to white
                luminance = 0.299 * avg_r + 0.587 * avg_g + 0.114 * avg_b
                if luminance > 0.65:
                    return (avg_r, avg_g, avg_b)
    except Exception as ex:
        logger.debug(f"Color sampling error: {ex}")
    return (1.0, 1.0, 1.0)


def _cluster_text_into_balloons(text_blocks: List[Any], reading_direction: str = "ltr") -> List[Dict[str, Any]]:
    """
    Groups contiguous lines of text into individual speech balloons.
    Supports standard LTR (left-to-right) or Manga RTL (right-to-left) ordering.
    """
    clusters: List[Dict[str, Any]] = []

    # Sort blocks: LTR -> top-to-bottom, left-to-right; RTL (Manga) -> top-to-bottom, right-to-left
    if reading_direction.lower() == "rtl":
        sorted_blocks = sorted(text_blocks, key=lambda b: (b[1], -b[2]))
    else:
        sorted_blocks = sorted(text_blocks, key=lambda b: (b[1], b[0]))

    for b in sorted_blocks:
        rect = fitz.Rect(b[:4])
        raw_text = b[4].strip()
        if not raw_text:
            continue

        merged = False
        for c in clusters:
            c_rect = c["rect"]
            # Check proximity: close vertically and overlapping horizontally
            v_gap = min(abs(rect.y0 - c_rect.y1), abs(c_rect.y0 - rect.y1))
            h_overlap = not (rect.x1 < c_rect.x0 or rect.x0 > c_rect.x1)

            # Accept lines in same balloon if vertical gap is under 22pt and they overlap horizontally
            if v_gap < 22 and h_overlap:
                c["rect"] = c_rect | rect  # Bounding box union
                c["text"] += " " + raw_text.replace("\n", " ")
                c["original_boxes"].append(rect)
                merged = True
                break

        if not merged:
            clusters.append({
                "rect": rect,
                "text": raw_text.replace("\n", " "),
                "original_boxes": [rect],
            })

    # Clean up and normalize texts
    for c in clusters:
        c["text"] = re.sub(r"\s+", " ", c["text"]).strip()

    return clusters


def _natural_sort_key(path_obj: Path):
    """Natural sort key so page_2.jpg comes before page_10.jpg."""
    # every folder too: in ch1/01, ch1/02, ch2/01 the file names alone repeat
    return [
        [int(p) if p.isdecimal() else p for p in re.split(r"(\d+)", part.lower())]
        for part in Path(path_obj).parts
    ]


def _open_page_image(path: Path) -> fitz.Document:
    """A comic page as a document. MuPDF has no WebP decoder: Pillow reads what MuPDF cannot."""
    if Path(path).suffix.lower() != ".webp":
        try:
            return fitz.open(str(path))
        except Exception as ex:
            logger.debug(f"MuPDF cannot read {Path(path).name} ({ex}); trying Pillow.")
    import io
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    buf = io.BytesIO()
    flat.save(buf, "JPEG", quality=94)
    return fitz.open("jpeg", buf.getvalue())


def _is_image_page(page: fitz.Page, text_blocks: List[Any], has_key: bool) -> bool:
    """
    A page whose balloons are part of a picture: no text, hidden OCR text over a scan, or (with a key, so that Vision
    can read it) a scan whose only text is a watermark or page number.
    """
    if not text_blocks:
        return True
    area = page.rect.get_area()
    if not any((fitz.Rect(info["bbox"]) & page.rect).get_area() >= 0.7 * area for info in page.get_image_info()):
        return False
    visible = sum(
        1
        for trace in page.get_texttrace()
        if trace.get("type") != 3 and trace.get("opacity", 1) > 0.01
        for char in trace.get("chars", ())
        if chr(char[0]).isalpha()
    )
    return visible == 0 or (has_key and visible < 25)


def _safe_extract_zip(zf, extract_dir: Path) -> None:
    """Safely extracts ZIP/CBZ archive preventing Zip Slip path traversal."""
    root_resolved = extract_dir.resolve()
    unpacked = 0
    for member in zf.infolist():
        if member.is_dir():
            continue
        unpacked += member.file_size
        if unpacked > 2 * 1024 ** 3:
            raise ValueError("The comic archive is too large when unpacked (over 2 GB).")
        target = (extract_dir / member.filename).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            raise ValueError(f"Unsafe Zip Slip entry detected in CBZ archive: {member.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member, "r") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)


async def _ai_polish_comic_balloons(
    balloons: List[Dict[str, str]],
    api_key: str,
    target_lang: str = "greek",
    quota_behavior: str = "wait",
) -> List[str]:
    """
    Polishes speech balloon dialogue using Gemini API specifically for Graphic Novels / Comics.
    Produces concise, natural, colloquial dialogue in target_lang tailored for comic balloons.
    """
    if not balloons or not api_key:
        return [b["draft"] for b in balloons]

    from backend.ai_polisher import is_gemini_quota_exhausted, DailyQuotaExhaustedError
    if is_gemini_quota_exhausted() and not (api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest")):
        if quota_behavior == "wait":
            raise DailyQuotaExhaustedError(
                "Εξαντλήθηκε το ημερήσιο όριο του Gemini API κατά το Comic AI Polish. Η εργασία σταμάτησε σε αναμονή ανανέωσης ορίου (quota_behavior='wait')."
            )
        logger.info("Gemini daily quota exhausted; using standard translated text for comic balloons without AI polish.")
        return [sanitize_comic_dialogue(b["draft"], target_lang) for b in balloons]

    lang_norm = (target_lang or "greek").strip().lower()
    is_greek = lang_norm in ("greek", "el")

    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        results = []
        for b in balloons:
            draft = b.get("draft", "")
            if not is_greek:
                results.append(f"[AI Polish]: {draft}")
            elif any(c in draft for c in "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"):
                results.append(f"[AI Polish]: {draft}")
            else:
                results.append(f"[AI Polish]: Κοιτάξτε αυτό το παράξενο σήμα! ({draft[:25]})")
        return results

    dialogue_inputs = [
        {"id": i + 1, "source": b["source"], "draft": b["draft"]}
        for i, b in enumerate(balloons) if b["draft"].strip()
    ]
    if not dialogue_inputs:
        return [b["draft"] for b in balloons]

    if is_greek:
        prompt = (
            "Είσαι έμπειρος επιμελητής και μεταφραστής εκδόσεων Graphic Novels, Comics και Manga. "
            "Βελτίωσε και επιμελήσου τους ακόλουθους διαλόγους μπαλονιών στα Ελληνικά ώστε να αποκτήσουν άψογη, φυσική και ζωντανή προφορική ροή: "
            "1. ΣΥΝΤΟΜΙΑ: Κράτησε τις ατάκες περιεκτικές και κοφτές ώστε να χωρούν άνετα στα μπαλόνια διαλόγου χωρίς να ξεχειλίζουν. "
            "2. ΖΩΝΤΑΝΙΑ & ΥΦΟΣ: Χρησιμοποίησε φυσικό, σύγχρονο προφορικό λόγο, διατηρώντας το χιούμορ, την ένταση, τα επιφωνήματα και τον ιδιαίτερο χαρακτήρα των ηρώων. "
            "3. ΕΞΑΛΕΙΨΗ ΑΓΓΛΙΣΜΩΝ: Απόδωσε ιδιωματισμούς με ισοδύναμες ελληνικές εκφράσεις και απέφυγε κατά λέξη μεταφράσεις. "
            "Σου δίνονται οι πρωτότυπες ατάκες (<SOURCE_REFERENCE>) και τα προσχέδιά τους (<DRAFT_TO_POLISH>), αριθμημένα ως ⟦n⟧. "
            "Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ όλες τις τελικές ατάκες με τους ίδιους δείκτες ⟦n⟧, μία ανά μπλοκ."
        )
    else:
        prompt = (
            f"You are an expert Graphic Novel, Comic, and Manga dialogue editor. "
            f"Polish the following speech balloon drafts in {target_lang.capitalize()} so they read naturally, idiomatically, and concisely inside speech bubbles. "
            f"Keep lines punchy, preserve character voice and exclamations. You receive the original lines "
            f"(<SOURCE_REFERENCE>) and their drafts (<DRAFT_TO_POLISH>), numbered ⟦n⟧. Return ONLY all the final lines, "
            f"in {target_lang.capitalize()}, with the same ⟦n⟧ markers, one per block."
        )

    from backend.ai_polisher import _answer_problem, _call_gemini_api
    from backend.ai_segment_translator import parse_segments

    ids = [d["id"] for d in dialogue_inputs]
    sources = "\n\n".join(f"⟦{d['id']}⟧ {' '.join(str(d['source']).split())}" for d in dialogue_inputs)
    drafts = "\n\n".join(f"⟦{d['id']}⟧ {' '.join(str(d['draft']).split())}" for d in dialogue_inputs)
    content = f"<SOURCE_REFERENCE>\n{sources}\n</SOURCE_REFERENCE>\n\n<DRAFT_TO_POLISH>\n{drafts}\n</DRAFT_TO_POLISH>"
    kept = [sanitize_comic_dialogue(b["draft"], target_lang, source_text=b.get("source", "")) for b in balloons]
    try:
        # the shared client: pool rotation, rate limits, cache, and only complete answers
        out = await _call_gemini_api(content, api_key, prompt, temperature=0.3,
                                     cache_gate=lambda o: len(parse_segments(o, ids)) == len(ids))
    except DailyQuotaExhaustedError:
        if quota_behavior == "wait":
            raise DailyQuotaExhaustedError(
                "Εξαντλήθηκε το ημερήσιο όριο του Gemini API κατά το Comic AI Polish. Η εργασία σταμάτησε σε αναμονή ανανέωσης ορίου (quota_behavior='wait')."
            )
        return kept
    except PermissionError:
        raise
    except Exception as ex:
        logger.warning(f"Comic AI polish skipped for this page: {ex}")
        return kept

    polished = parse_segments(out, ids)
    results = []
    for i, b in enumerate(balloons):
        line = polished.get(i + 1, "")
        if line and not _answer_problem(line, b["draft"], is_greek):
            line = sanitize_comic_dialogue(line, target_lang, source_text=b.get("source", ""))
        else:
            line = ""
        results.append(line or kept[i])
    return results


async def _translate_page_vector(
    page: fitz.Page,
    clusters: List[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
    font_path: str,
    api_key: Optional[str] = None,
    quota_behavior: str = "wait",
) -> List[str]:
    """
    Translates detected speech balloons on a digital PDF page,
    redacts the original text while preserving images, and typesets Greek dialogue.
    """
    page_dialogues = []

    # 1. Translate all balloon texts asynchronously
    translated_balloons = []
    ready: Dict[str, str] = {}
    batched = False
    for c in clusters:
        orig = c["text"]
        if not orig:
            translated_balloons.append("")
            continue
        try:
            if not batched and getattr(_translator, "google_is_refusing", lambda: False)():
                batched = True  # one request for the page's balloons instead of one each
                ready = await _translator.failover_in_batches([b["text"] for b in clusters if b["text"]],
                                                              source_lang, target_lang)
            tr = ready.get(orig) or await _translate_with_retry(orig, source_lang, target_lang)
            tr = apply_glossary(tr, target_lang, style="comic", translated=True)
            tr = sanitize_comic_dialogue(tr, target_lang, source_text=orig) or orig  # never an erased balloon
            translated_balloons.append(tr)
            page_dialogues.append(tr)
            # Gentle pacing to avoid rapid burst rate limits on public translation endpoints
            await asyncio.sleep(0.04)
        except Exception as ex:
            if isinstance(ex, getattr(_translator, "TranslationUnavailableError", ())):
                raise  # never leave balloons untranslated in a job reported as done
            logger.warning(f"Error translating balloon '{orig[:30]}': {ex}")
            translated_balloons.append(orig)
            page_dialogues.append(orig)

    # 1b. AI Polish comic dialogue with Gemini if API key available
    if api_key and translated_balloons:
        from backend.ai_polisher import DailyQuotaExhaustedError
        try:
            balloons_data = [{"source": c["text"], "draft": translated_balloons[i]} for i, c in enumerate(clusters)]
            polished_texts = await _ai_polish_comic_balloons(balloons_data, api_key, target_lang=target_lang, quota_behavior=quota_behavior)
            if polished_texts and len(polished_texts) == len(translated_balloons):
                translated_balloons = polished_texts
                page_dialogues = [t for t in translated_balloons if t.strip()]
        except DailyQuotaExhaustedError:
            raise
        except Exception as ex:
            logger.warning(f"AI Polish on comic page skipped: {ex}")

    # 2. Redact original text in balloons with matching background fill
    bg_colors = []
    for c in clusters:
        bg_col = _sample_balloon_bg_color(page, c["rect"])
        bg_colors.append(bg_col)
        for ob in c["original_boxes"]:
            # 2.5px padding to cleanly cover descenders and ascenders
            pad_box = fitz.Rect(ob.x0 - 2.5, ob.y0 - 2.5, ob.x1 + 2.5, ob.y1 + 2.5)
            page.add_redact_annot(pad_box, fill=bg_col)

    # Apply redactions - images=PDF_REDACT_IMAGE_NONE guarantees the illustrations stay untouched!
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    # 3. Typeset Greek translated text inside each balloon with guaranteed non-blank fit
    rooms = _separate_text_areas(page, [c["rect"] + (-3, -2, 3, 2) for c in clusters])
    for i, c in enumerate(clusters):
        greek_text = translated_balloons[i]
        if not greek_text.strip():
            continue

        target_box, limit = rooms[i]
        bg_col = bg_colors[i]
        luminance = 0.299 * bg_col[0] + 0.587 * bg_col[1] + 0.114 * bg_col[2]
        text_color = (1.0, 1.0, 1.0) if luminance < 0.4 else (0.05, 0.05, 0.05)

        _fit_and_draw_balloon_text(
            page,
            target_box,
            greek_text,
            font_path=font_path,
            bg_rgb=bg_col,
            text_color=text_color,
            max_fontsize=15.0,
            draw_bg=False,
            limit=limit,
        )

    return page_dialogues


_CACHED_VISION_MODEL: Optional[str] = None
_DEAD_VISION_MODELS: set[str] = set()


def reset_vision_model_cache() -> None:
    """Resets cached Gemini Vision model state (e.g. when user updates or deletes their API key)."""
    global _CACHED_VISION_MODEL
    _CACHED_VISION_MODEL = None
    _DEAD_VISION_MODELS.clear()

VISION_MODELS_PRIORITY = [
    # Full Flash models FIRST for accurate Greek spelling, grammar & zero mixed-script glitches
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    # Flash-Lite models as fallback
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]


def _extract_box_2d(item: Dict[str, Any]) -> Optional[List[float]]:
    """Normalizes box_2d / box / bbox / nested [[y1,x1,y2,x2]] into a clamped [0..1000] 4-number list."""
    if not isinstance(item, dict):
        return None
    raw = item.get("box_2d") or item.get("box") or item.get("bbox") or item.get("bounding_box")
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list):
        raw = raw[0]
    if isinstance(raw, list) and len(raw) == 4:
        try:
            vals = [max(0.0, min(1000.0, float(v))) for v in raw]
            ymin, xmin, ymax, xmax = vals
            if ymin > ymax:
                ymin, ymax = ymax, ymin
            if xmin > xmax:
                xmin, xmax = xmax, xmin
            if ymax - ymin < 2 or xmax - xmin < 2:
                return None
            return [ymin, xmin, ymax, xmax]
        except Exception:
            return None
    return None


def _hex_to_rgb01(hex_color: Optional[str]) -> Tuple[float, float, float]:
    """Converts '#rrggbb' to PyMuPDF 0..1 RGB tuple, defaulting to crisp white."""
    if not hex_color or not isinstance(hex_color, str):
        return (1.0, 1.0, 1.0)
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (1.0, 1.0, 1.0)
    try:
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
    except Exception:
        return (1.0, 1.0, 1.0)


def _parse_vision_json(text_resp: str) -> Optional[List[Dict[str, Any]]]:
    """
    Resilient JSON parser for Gemini Vision comic balloon responses.
    Handles markdown code fences, trailing commas, unescaped quotes, and partial/truncated arrays
    without ever crashing the comic translation pipeline.
    """
    if not text_resp or not text_resp.strip():
        return None
    cleaned = text_resp.strip()
    # Strip markdown ```json ... ``` fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # 1. Direct parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("balloons"), list):
            return parsed["balloons"]
    except Exception:
        pass

    # 2. Extract [...] slice and remove trailing commas
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        sub = cleaned[start : end + 1]
        sub_fixed = re.sub(r",\s*([}\]])", r"\1", sub)
        try:
            parsed = json.loads(sub_fixed)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    # 3. Object-by-object recovery for partially malformed/truncated JSON lists
    recovered: List[Dict[str, Any]] = []
    for m in re.finditer(r"\{[^{}]*\"(?:box_2d|box|bbox)\"\s*:\s*\[[^\]]+\][^{}]*\}", cleaned, flags=re.DOTALL):
        obj_str = re.sub(r",\s*\}", "}", m.group(0))
        try:
            obj = json.loads(obj_str)
            if isinstance(obj, dict) and _extract_box_2d(obj) is not None:
                recovered.append(obj)
        except Exception:
            # Regex fallback for box_2d + translated_text even if quotes inside string were unescaped
            bm = re.search(r'"(?:box_2d|box|bbox)"\s*:\s*\[?\s*\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]', obj_str)
            tm = re.search(r'"translated_text"\s*:\s*"(.*?)"\s*(?:,|\})', obj_str, flags=re.DOTALL)
            if bm and tm:
                recovered.append({
                    "box_2d": [int(bm.group(i)) for i in range(1, 5)],
                    "translated_text": tm.group(1).replace('\\"', '"').replace("\\n", "\n"),
                    "bg_color": "#ffffff",
                })
    return recovered if recovered else None


def _encode_comic_page_jpeg(page: fitz.Page, max_dim: int = 1400, quality: int = 82) -> bytes:
    """Renders a comic page to an optimized RGB JPEG (capped at max_dim) for fast, crisp Vision OCR."""
    import io
    pix = page.get_pixmap(dpi=130, colorspace=fitz.csRGB, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    if max(img.width, img.height) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


async def _detect_comic_balloons_vision_async(
    img_bytes: bytes,
    api_key: str,
    source_lang: str,
    target_lang: str,
    session=None,
    status_out: Optional[Dict[str, Any]] = None,
    known_names: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Calls Gemini Vision Flash asynchronously (rotating across live Gemini 3.x / Flash-Lite models,
    skipping 404 retired models, retrying 429/503 with backoff, and using SQLite SHA-256 cache)
    to detect & translate all speech balloons on a scanned comic page.
    ``known_names``: names the earlier pages (or the glossary) already rendered, so this page writes them the same way.
    An answer in Latin letters or with mixed scripts goes to the next model; an empty page is checked by a second one.
    """
    import base64
    import hashlib
    import aiohttp

    img_hash = hashlib.sha256(img_bytes).hexdigest()
    cache_key = None
    try:
        from backend.database import compute_cache_key, db_get_cached_translation
        cache_key = compute_cache_key(img_hash, source_lang, target_lang, engine="gemini_comic_vision_v2")
        cached = db_get_cached_translation(cache_key)
        if cached:
            parsed = json.loads(cached)
            # an answer saved before the Greeklish check existed is asked again, and the new one replaces it
            if isinstance(parsed, list) and len(parsed) > 0 and not _comic_items_problem(parsed, target_lang):
                if status_out is not None:
                    status_out["succeeded"] = True
                    status_out["error"] = ""
                return parsed
    except Exception:
        pass

    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    is_greek_target = target_lang.lower().startswith(("gr", "el"))
    tgt_name = "Greek" if is_greek_target else target_lang
    greek_rules = (
        "STRICT GREEK LOCALIZATION RULES:\n"
        "- Translate into natural, idiomatic, grammatically & orthographically flawless Modern Greek (correct gender agreement, declensions, and spelling — NO literal English calques and NO spelling typos).\n"
        "- Keep dialogue CONCISE so it fits comfortably inside each speech balloon.\n"
        "- Use CONSISTENT comic lettering: ALL CAPS Greek without tonos accents (keep only dialytika Ϊ/Ϋ and disjunctive Ή) whenever the original balloon is uppercase.\n"
        "- Use Greek question mark ';' (NEVER '?') and Greek guillemets '«...»' ONLY when quoting someone inside speech.\n"
        "- NEVER use markdown asterisks (*...*), HTML tags, or non-Greek letters (Latin/Cyrillic/Armenian) spliced inside Greek words.\n"
        "- Write every Greek word in the Greek alphabet: NEVER Greeklish (Greek words in Latin letters, e.g. 'KALIMERA').\n"
        if is_greek_target
        else ""
    )
    names_block = ""
    if known_names:
        listed = "\n".join(f"- {src} → {tgt}" for src, tgt in list(known_names.items())[:60])
        names_block = (
            "NAMES ALREADY USED IN THIS BOOK: write each one exactly like this whenever it appears on this page:\n"
            f"{listed}\n"
        )
    prompt = (
        "You are an expert graphic novel and comic book localization engine. "
        "Detect ALL dialogue text, speech balloons, thought bubbles, and narration caption boxes on this comic page. "
        f"{greek_rules}"
        f"{names_block}"
        "Return a STRICT JSON list of objects:\n"
        "[\n"
        "  {\n"
        "    \"box_2d\": [ymin, xmin, ymax, xmax],\n"
        "    \"original_text\": \"original dialogue\",\n"
        f"    \"translated_text\": \"natural, vivid {tgt_name} comic dialogue translation\",\n"
        "    \"bg_color\": \"#ffffff\",\n"
        "    \"names\": {\"NAME AS IN THE ORIGINAL\": \"THE SAME NAME AS WRITTEN IN translated_text\"}\n"
        "  }\n"
        "]\n"
        "Add \"names\" only to balloons that mention proper names of people, ships, places or organisations "
        "(never ranks, titles or ordinary words); leave it out otherwise.\n"
        "Coordinates MUST be normalized integers 0 to 1000 representing the exact bounding box of the text inside each balloon. "
        "If the page has ONLY artwork and NO text at all, return []."
    )

    from backend.ai_polisher import (
        _INTERRUPTED_REASONS, _LITERARY_SAFETY_SETTINGS, _extract_gemini_text_and_reason, is_gemini_quota_exhausted,
        trip_gemini_quota_exhaustion,
    )

    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        if status_out is not None:
            status_out["succeeded"] = True
            status_out["error"] = None
        return [
            {
                "box_2d": [100, 100, 300, 600],
                "original_text": "Hello world from test comic",
                "translated_text": "Γεια σου κόσμε από δοκιμαστικό κόμικ",
            }
        ]

    if is_gemini_quota_exhausted() and not (api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest")):
        if status_out is not None:
            status_out["succeeded"] = False
            status_out["error"] = "Gemini daily quota exhausted"
        return []

    base_payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
                {"text": prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json",
            "maxOutputTokens": 8192,
        },
        "safetySettings": _LITERARY_SAFETY_SETTINGS,
    }

    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))

    global _CACHED_VISION_MODEL
    vision_models = [m for m in VISION_MODELS_PRIORITY if m not in _DEAD_VISION_MODELS]
    if not vision_models:
        _DEAD_VISION_MODELS.clear()
        vision_models = list(VISION_MODELS_PRIORITY)
    if _CACHED_VISION_MODEL and _CACHED_VISION_MODEL in vision_models and "lite" not in _CACHED_VISION_MODEL.lower():
        vision_models = [_CACHED_VISION_MODEL] + [m for m in vision_models if m != _CACHED_VISION_MODEL]

    def _incomplete(text_resp: str, finish_reason: str, parsed: Optional[List[Dict[str, Any]]]) -> bool:
        if finish_reason == "MAX_TOKENS" or finish_reason in _INTERRUPTED_REASONS:
            return True
        boxes = len(re.findall(r'"(?:box_2d|box|bbox|bounding_box)"\s*:', text_resp))
        return parsed is not None and len(parsed) < boxes  # objects the lenient parser could not save

    detected_items: List[Dict[str, Any]] = []
    fallback_corrupted_items: Optional[List[Dict[str, Any]]] = None
    succeeded = False
    last_error = ""

    def _clean_items(items_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned_list = []
        for it in items_list:
            if not isinstance(it, dict):
                continue
            item_copy = dict(it)
            for tk in ("translated_text", "translation", "greek_text"):
                if isinstance(item_copy.get(tk), str) and item_copy[tk].strip():
                    item_copy[tk] = sanitize_comic_dialogue(
                        item_copy[tk], target_lang, source_text=str(item_copy.get("original_text") or ""))
            cleaned_list.append(item_copy)
        return cleaned_list

    empty_once = saw_text = False

    def _take(parsed: List[Dict[str, Any]], model: str) -> bool:
        """Keeps a complete answer, or says why the next model is asked (False)."""
        nonlocal detected_items, fallback_corrupted_items, succeeded, last_error, empty_once, saw_text
        global _CACHED_VISION_MODEL
        saw_text = saw_text or bool(parsed)
        if not parsed and not empty_once and len(vision_models) > 1:
            empty_once = True  # a page full of balloons sometimes comes back empty: a second model checks it
            last_error = f"{model}: no text found"
            return False
        problem = _comic_items_problem(parsed, target_lang)
        if problem:
            logger.warning(f"Vision model {model} answered with {problem}; trying next model...")
            if problem == "mixed-script corruption" and fallback_corrupted_items is None:
                fallback_corrupted_items = _clean_items(parsed)  # Greeklish is never kept, not even as a last resort
            last_error = f"{model}: {problem}"
            return False
        detected_items = _clean_items(parsed)
        succeeded = True
        if "lite" not in model.lower():
            _CACHED_VISION_MODEL = model
        if cache_key and detected_items:
            try:
                from backend.database import db_set_cached_translation
                db_set_cached_translation(
                    cache_key,
                    img_hash,
                    json.dumps(detected_items, ensure_ascii=False),
                    source_lang,
                    target_lang,
                    engine="gemini_comic_vision_v2",
                )
            except Exception:
                pass
        return True

    try:
        from backend.gemini_key_pool import GeminiKeyPool, mask_api_key, parse_gemini_error
        pool_keys = GeminiKeyPool.get_keys()
        initial_key = (api_key or "").strip()
        if not initial_key or (not initial_key.startswith(("AQ.Test", "AIzaTest")) and GeminiKeyPool.is_key_exhausted(initial_key)):
            initial_key = GeminiKeyPool.get_active_key() or initial_key
        allow_pool_rotation = (not (api_key or "").strip()) or (initial_key in pool_keys)
        api_key = initial_key

        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        # Up to 2 rounds so transient 429/503 spikes can recover cleanly
        tried_keys = {api_key}
        out_of_quota = False
        round_wait = 4.0
        attempt_round = 0
        while attempt_round < 2 and not succeeded and not out_of_quota:
            candidates = GeminiKeyPool.get_active_models_for_key(api_key, vision_models)
            if not candidates:  # every Vision model's own allowance is used up on this key
                next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=tried_keys) if allow_pool_rotation else None
                if not next_pool_key:
                    last_error = "quota of every Vision model is used up"
                    break
                api_key = next_pool_key
                tried_keys.add(api_key)
                headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
                continue
            attempt_round += 1
            rate_limited_round = False
            for model in candidates:
                if model in _DEAD_VISION_MODELS:
                    continue
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"  # key in header only
                m_low = model.lower()
                use_no_thinking = "2.5-flash" in m_low
                req_payload = (
                    {
                        **base_payload,
                        "generationConfig": {
                            **base_payload["generationConfig"],
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    }
                    if use_no_thinking
                    else dict(base_payload)
                )
                try:
                    async with session.post(url, json=req_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=45)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            from backend.ai_polisher import record_gemini_usage
                            record_gemini_usage(data)
                            text_resp, finish_reason = _extract_gemini_text_and_reason(data)
                            if not text_resp:
                                last_error = f"{model}: empty parts ({finish_reason})"
                                continue
                            parsed = _parse_vision_json(text_resp)
                            if _incomplete(text_resp, finish_reason, parsed):
                                last_error = f"{model}: incomplete answer ({finish_reason or 'damaged JSON'})"
                                continue  # the balloons after the cut would stay untranslated
                            if parsed is not None:
                                # Quality gate (Greeklish, mixed scripts, an empty page): _take decides
                                if _take(parsed, model):
                                    break
                                continue
                            else:
                                last_error = f"{model}: unparseable JSON"
                                logger.warning(f"Vision model {model} returned unparseable JSON; trying next model...")
                        elif resp.status == 404:
                            _DEAD_VISION_MODELS.add(model)
                            if _CACHED_VISION_MODEL == model:
                                _CACHED_VISION_MODEL = None
                            logger.info(f"Vision model {model} unavailable (404) — skipping for remaining pages.")
                        elif resp.status in (400, 401, 403):
                            err_detail = await resp.text()
                            if "API_KEY_INVALID" in err_detail or "not valid" in err_detail.lower() or resp.status in (401, 403):
                                if allow_pool_rotation:
                                    logger.warning(
                                        f"[Gemini Key Pool] Comic Vision key {mask_api_key(api_key)} auth error ({resp.status}): {err_detail[:120]}. "
                                        f"Marking key and rotating..."
                                    )
                                    GeminiKeyPool.mark_key_exhausted(api_key, 86400.0, reason=f"Auth error ({resp.status}): {err_detail[:120]}")
                                    next_pool_key = GeminiKeyPool.get_active_key(exclude_keys={api_key})
                                    if next_pool_key:
                                        logger.info(f"[Gemini Key Pool] Comic Vision rotated to next key {mask_api_key(next_pool_key)}")
                                        api_key = next_pool_key
                                        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
                                        continue
                                logger.error(f"Gemini API key is invalid across all pool keys: {err_detail}")
                                raise PermissionError("Το Gemini API Key είναι άκυρο. Ελέγξτε το κλειδί σας στις Ρυθμίσεις (Settings).")
                            if resp.status == 400 and ("thinking" in err_detail.lower() or "safety" in err_detail.lower()):
                                retry_payload = {
                                    "contents": base_payload["contents"],
                                    "generationConfig": {
                                        "temperature": 0.15,
                                        "responseMimeType": "application/json",
                                    },
                                }
                                async with session.post(url, json=retry_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=45)) as retry_resp:
                                    if retry_resp.status == 200:
                                        data = await retry_resp.json()
                                        text_resp, finish_reason = _extract_gemini_text_and_reason(data)
                                        parsed = _parse_vision_json(text_resp)
                                        if parsed is not None and not _incomplete(text_resp, finish_reason, parsed):
                                            if _take(parsed, model):
                                                break
                                            continue  # _take named the reason
                            last_error = f"{model}: HTTP {resp.status}"
                        elif resp.status in (429, 503):
                            rate_limited_round = True
                            err_detail = await resp.text()
                            info = parse_gemini_error(resp.status, err_detail)
                            category, delay = info.get("category"), info.get("retry_delay_sec")
                            why = ("daily quota used up" if category in ("QUOTA_EXCEEDED_DAILY_KEY", "QUOTA_EXCEEDED_DAILY_MODEL")
                                   else "not in this plan" if category == "MODEL_TIER_RESTRICTED"
                                   else "rate limit" if resp.status == 429 else "overloaded")
                            last_error = f"{model}: HTTP {resp.status} ({why})"  # "quota" means the daily reset
                            if category == "QUOTA_EXCEEDED_DAILY_KEY":
                                GeminiKeyPool.mark_key_exhausted(api_key, delay or 3600.0, reason=err_detail[:120])
                                next_pool_key = (GeminiKeyPool.get_active_key(exclude_keys=tried_keys)
                                                 if allow_pool_rotation else None)
                                if next_pool_key:
                                    logger.warning(f"[Gemini Key Pool] Comic Vision rotated to next key {mask_api_key(next_pool_key)}...")
                                    api_key = next_pool_key
                                    tried_keys.add(api_key)
                                    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
                                    continue
                                logger.warning("Gemini daily quota exhausted in comic Vision across all pool keys. Tripping circuit breaker.")
                                trip_gemini_quota_exhaustion(delay or 3600.0)
                                out_of_quota = True
                                break
                            if category in ("QUOTA_EXCEEDED_DAILY_MODEL", "MODEL_TIER_RESTRICTED"):
                                cooldown = delay if category == "QUOTA_EXCEEDED_DAILY_MODEL" and delay else 86400.0
                                GeminiKeyPool.mark_model_exhausted(api_key, model, cooldown, reason=err_detail[:120])
                            elif resp.status == 429:
                                # a per-minute limit: the next model now, a second round after the wait Google names
                                round_wait = max(round_wait, min(30.0, delay or 4.0))
                            if _CACHED_VISION_MODEL == model:
                                _CACHED_VISION_MODEL = None
                            await asyncio.sleep(0.3)
                            continue
                        else:
                            last_error = f"{model}: HTTP {resp.status}"
                except PermissionError:
                    raise
                except Exception as ex:
                    last_error = f"{model}: {str(ex) or type(ex).__name__}"  # a timeout has no message of its own
                    logger.debug(f"Vision model {model} attempt failed: {last_error}")
                    await asyncio.sleep(0.3)

            if not succeeded and not out_of_quota and rate_limited_round and attempt_round == 1:
                next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=tried_keys) if allow_pool_rotation else None
                if next_pool_key:  # the limits are per project: another key need not wait
                    api_key = next_pool_key
                    tried_keys.add(api_key)
                    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
                else:
                    await asyncio.sleep(round_wait)
    finally:
        if owns_session:
            await session.close()

    if not succeeded and fallback_corrupted_items is not None:
        detected_items = fallback_corrupted_items
        succeeded = True
    if not succeeded and empty_once and not saw_text:  # no second model could look, and none found text
        detected_items = []
        succeeded = True

    if status_out is not None:
        status_out["succeeded"] = succeeded
        status_out["error"] = last_error if not succeeded else ""

    if not succeeded and last_error:  # the caller logs the page number with it
        logger.debug(f"Gemini Vision failed on page after trying all models: {last_error}")

    return detected_items


def _render_vision_balloons_on_page(
    page: fitz.Page,
    detected_items: List[Dict[str, Any]],
    font_path: str,
    target_lang: str = "greek",
) -> List[str]:
    """
    Covers detected scanned balloon text with opaque matching background fill and renders centered
    Greek comic dialogue using a two-pass renderer (all background fills first, all text on top)
    so neighboring balloons can never paint over each other's text.
    """
    if not detected_items:
        return []

    page_dialogues: List[str] = []
    w, h = page.rect.width, page.rect.height
    balloons = []
    planned_balloons = []

    for item in detected_items:
        if not isinstance(item, dict):
            continue
        box = _extract_box_2d(item)
        if not box:
            continue
        raw_val = (
            item.get("translated_text")
            or item.get("translation")
            or item.get("greek_text")
            or ""
        )
        raw_greek_text = str(raw_val).strip() if not isinstance(raw_val, (list, dict)) else ""
        greek_text = sanitize_comic_dialogue(
            raw_greek_text, target_lang, source_text=str(item.get("original_text") or ""))
        if not greek_text:
            continue
        ymin, xmin, ymax, xmax = box
        # Slight padding so original raster letters inside the speech balloon are 100% covered
        pad_x = max(2.0, (xmax - xmin) / 1000.0 * w * 0.04)
        pad_y = max(2.0, (ymax - ymin) / 1000.0 * h * 0.04)
        rx0 = max(0.0, (xmin / 1000.0) * w - pad_x)
        ry0 = max(0.0, (ymin / 1000.0) * h - pad_y)
        rx1 = min(w, (xmax / 1000.0) * w + pad_x)
        ry1 = min(h, (ymax / 1000.0) * h + pad_y)
        rect = fitz.Rect(rx0, ry0, rx1, ry1)

        # Determine balloon background color (prefer Gemini bg_color or sampled edge color)
        bg_hex = item.get("bg_color")
        bg_rgb = _hex_to_rgb01(bg_hex) if bg_hex else _sample_balloon_bg_color(page, rect)
        # Choose contrasting text color (white text on dark narration boxes, black on light balloons)
        luminance = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
        text_color = (1.0, 1.0, 1.0) if luminance < 0.4 else (0.05, 0.05, 0.05)

        balloons.append((rect, greek_text, bg_rgb, text_color))

    # Pass 1: Plan every balloon's layout and draw all opaque background rectangles first
    rooms = _separate_text_areas(page, [b[0] for b in balloons])
    for (rect, greek_text, bg_rgb, text_color), (area, limit) in zip(balloons, rooms):
        plan = _plan_balloon_layout(page, area, greek_text, font_path, max_fontsize=13.0, limit=limit)
        if plan is None:
            continue

        # Cover both original text rect and planned text box
        cover_rect = rect | plan[3]
        page.draw_rect(cover_rect, color=bg_rgb, fill=bg_rgb, overlay=True)
        planned_balloons.append((plan, text_color))
        page_dialogues.append(greek_text)

    # Pass 2: Draw all balloon texts on top of all background fills
    for plan, text_color in planned_balloons:
        _draw_planned_balloon_text(page, plan, text_color)

    return page_dialogues


async def translate_comic_document(
    job_id: str,
    file_path: str,
    file_type: str,
    source_lang: str,
    target_lang: str,
    output_path: str,
    api_key: Optional[str] = None,
    reading_direction: str = "ltr",
    progress_callback: Optional[Callable] = None,
    quota_behavior: str = "wait",
    notes: Optional[List[str]] = None,
) -> str:
    """
    Main entry point for Graphic Novel / Comic translation.
    Takes a PDF or CBZ comic file, translates all dialogue in balloons while
    preserving 100% of the artwork, and outputs a translated PDF and dialogue text file.
    """
    update_job(job_id, status="running", current_step="Opening graphic novel...", progress=2)

    font_path = _get_comic_font_path()
    logger.info(f"[{job_id}] Translating graphic novel with comic font: {font_path}")

    # Resolve Gemini API Key for vision fallback if available
    from backend.gemini_key_pool import resolve_gemini_api_key
    resolved_api_key = resolve_gemini_api_key(api_key)

    # Handle CBZ files (convert image archive to temporary PDF)
    temp_pdf_to_clean: Optional[Path] = None
    temp_extract_dir_to_clean: Optional[Path] = None
    actual_pdf_path = file_path

    doc: Optional[fitz.Document] = None
    try:
        if file_type in ("cbz", "zip") or Path(file_path).suffix.lower() in (".cbz", ".zip"):
            import zipfile
            update_job(job_id, current_step="Extracting comic archive (CBZ)...", progress=5)
            extract_dir = Path("temp") / f"cbz_{job_id}"
            extract_dir.mkdir(parents=True, exist_ok=True)
            temp_extract_dir_to_clean = extract_dir

            with zipfile.ZipFile(file_path, "r") as zf:
                _safe_extract_zip(zf, extract_dir)

            # Find image files in natural numeric order (page_1, page_2, ..., page_10)
            img_extensions = {".jpg", ".jpeg", ".png", ".webp"}
            image_files = sorted(
                [
                    p for p in extract_dir.rglob("*")
                    if p.suffix.lower() in img_extensions
                    and not p.name.startswith(".")
                    and "__MACOSX" not in p.parts
                ],
                key=_natural_sort_key,
            )

            if not image_files:
                raise ValueError("No comic page images found in uploaded CBZ archive.")

            # Build PDF from extracted images (explicitly closing every PyMuPDF handle)
            cbz_pdf = fitz.open()
            try:
                for img_p in image_files:
                    with _open_page_image(img_p) as img_doc:
                        pdf_bytes = img_doc.convert_to_pdf()
                    with fitz.open("pdf", pdf_bytes) as page_pdf:
                        page_rect = page_pdf[0].rect
                        new_p = cbz_pdf.new_page(width=page_rect.width, height=page_rect.height)
                        new_p.show_pdf_page(page_rect, page_pdf, 0)

                temp_pdf_to_clean = Path("temp") / f"cbz_converted_{job_id}.pdf"
                cbz_pdf.save(str(temp_pdf_to_clean))
            finally:
                cbz_pdf.close()
            actual_pdf_path = str(temp_pdf_to_clean)

        # Open document with PyMuPDF
        doc = fitz.open(actual_pdf_path)
        total_pages = len(doc)
        if total_pages == 0:
            raise ValueError("Comic PDF contains 0 pages and cannot be translated.")

        # Check if this comic is primarily scanned/image-only
        has_vector_text = any(
            not _is_image_page(
                doc[i], [b for b in doc[i].get_text("blocks") if len(b) >= 5 and b[4].strip() and b[1] != b[3]], False)
            for i in range(min(5, total_pages))
        )
        if not has_vector_text and not resolved_api_key:
            raise ValueError(
                "This graphic novel / scanned comic contains image-only pages and requires a Gemini API key "
                "for Vision AI balloon detection and translation."
            )

        update_job(job_id, total_chunks=total_pages, done_chunks=0, current_step=f"Translating {total_pages} comic pages (parallel Vision engine)...")

        all_document_dialogues: List[Tuple[int, List[str]]] = [(i + 1, []) for i in range(total_pages)]
        vision_pages_to_process: List[Tuple[int, bytes]] = []
        completed_count = 0
        untranslated_pages: List[int] = []
        page_errors: Dict[int, str] = {}  # page number -> why Vision failed on it
        blank_pages: List[int] = []  # scanned pages where Vision found no text to place

        # Pass 1: Process vector text pages immediately and collect raster pages for parallel Vision AI
        for page_idx in range(total_pages):
            if is_job_cancelled(job_id):
                raise asyncio.CancelledError("Comic translation cancelled by user.")

            page = doc[page_idx]
            raw_blocks = page.get_text("blocks")
            text_blocks = [b for b in raw_blocks if len(b) >= 5 and b[4].strip() and b[1] != b[3]]

            if not _is_image_page(page, text_blocks, bool(resolved_api_key)):
                if not resolved_api_key and _is_image_page(page, text_blocks, True):
                    untranslated_pages.append(page_idx + 1)  # only its few words of text can be read without Vision
                clusters = _cluster_text_into_balloons(text_blocks, reading_direction=reading_direction)
                logger.info(f"[{job_id}] Page {page_idx + 1}: found {len(clusters)} speech balloons (dir={reading_direction}).")
                page_dialogues = await _translate_page_vector(
                    page, clusters, source_lang, target_lang, font_path, api_key=resolved_api_key, quota_behavior=quota_behavior
                )
                all_document_dialogues[page_idx] = (page_idx + 1, page_dialogues)
                completed_count += 1
                from backend.ai_polisher import is_gemini_quota_exhausted
                quota_note = " (⚠️ Χωρίς AI Polish: εξαντλήθηκε το ημερήσιο όριο Gemini)" if is_gemini_quota_exhausted() else ""
                update_job(
                    job_id,
                    current_step=f"Translating graphic novel page {completed_count} of {total_pages}{quota_note}...",
                    progress=int((completed_count / max(total_pages, 1)) * 92),
                    done_chunks=completed_count,
                    total_chunks=total_pages,
                )
            else:
                if resolved_api_key:
                    vision_pages_to_process.append((page_idx, _encode_comic_page_jpeg(page)))
                else:
                    logger.warning(f"[{job_id}] Page {page_idx + 1} is image-only and no Gemini API key was provided.")
                    untranslated_pages.append(page_idx + 1)
                    completed_count += 1

        # Pass 2: Execute Gemini Vision balloon detection 3 pages in parallel over a shared HTTP session
        # with real-time disk checkpointing and fail-loud protection if API fails across pages
        if vision_pages_to_process and resolved_api_key:
            import aiohttp
            out_dir_cp = Path(output_path).parent
            out_dir_cp.mkdir(parents=True, exist_ok=True)
            cp_file = out_dir_cp / ".comic_vision_checkpoint.json"
            cp_pages: Dict[str, Any] = {}
            cp_languages = f"{source_lang}>{target_lang}".lower()
            if cp_file.is_file():
                try:
                    loaded_cp = json.loads(cp_file.read_text(encoding="utf-8"))
                    if isinstance(loaded_cp, dict) and loaded_cp.get("_languages", cp_languages) == cp_languages:
                        cp_pages = loaded_cp  # balloons of another language pair are never reused
                except Exception:
                    pass
            cp_pages["_languages"] = cp_languages

            cp_lock = asyncio.Lock()

            async def _save_comic_cp():
                async with cp_lock:
                    tmp_cp = cp_file.with_name(f"{cp_file.stem}_{uuid.uuid4().hex[:8]}.tmp")
                    try:
                        tmp_cp.write_text(json.dumps(cp_pages, ensure_ascii=False), encoding="utf-8")
                        last_err = None
                        for attempt in range(4):
                            try:
                                os.replace(tmp_cp, cp_file)
                                last_err = None
                                break
                            except (PermissionError, OSError) as pe:
                                last_err = pe
                                await asyncio.sleep(0.04 * (attempt + 1))
                        if last_err is not None:
                            raise last_err
                    except Exception as cp_err:
                        logger.debug(f"Comic checkpoint write error (safe fallback): {cp_err}")
                    finally:
                        try:
                            tmp_cp.unlink(missing_ok=True)
                        except Exception:
                            pass

            vision_sem = asyncio.Semaphore(3)
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            vision_results: Dict[int, List[Dict[str, Any]]] = {}
            failed_vision_pages = 0
            last_vision_error = ""
            # One spelling per name: the glossary decides, otherwise the earlier pages (see _harmonize_comic_names)
            glossary_names: Dict[str, str] = {}
            if target_lang.lower().startswith(("gr", "el")):
                try:
                    from backend.glossary import load_glossary
                    glossary_names = {_comic_caps(" ".join(k.split())): v.strip()
                                      for k, v in load_glossary(style="comic").items()
                                      if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()}
                except Exception as gl_err:
                    logger.debug(f"[{job_id}] Glossary unavailable for comic names: {gl_err}")
            name_votes: Dict[str, Dict[str, int]] = {}
            name_spelled: Dict[str, str] = {}

            async with aiohttp.ClientSession(connector=connector) as session:
                async def _vision_worker(p_idx: int, img_bytes: bytes):
                    nonlocal completed_count, failed_vision_pages, last_vision_error
                    if is_job_cancelled(job_id):
                        raise asyncio.CancelledError("Comic translation cancelled by user.")

                    p_key = str(p_idx)
                    saved = cp_pages.get(p_key)
                    # an empty or Greeklish page from an earlier run is asked again
                    if isinstance(saved, list) and saved and not _comic_items_problem(saved, target_lang):
                        vision_results[p_idx] = saved
                        _record_comic_names(name_votes, name_spelled, saved)
                        completed_count += 1
                        return

                    st_info: Dict[str, Any] = {}
                    async with vision_sem:
                        if is_job_cancelled(job_id):
                            raise asyncio.CancelledError("Comic translation cancelled by user.")
                        items = await _detect_comic_balloons_vision_async(
                            img_bytes, resolved_api_key, source_lang, target_lang, session=session, status_out=st_info,
                            known_names=_comic_name_choices(name_votes, name_spelled, glossary_names),
                        )
                        vision_results[p_idx] = items
                        if st_info.get("succeeded"):
                            _record_comic_names(name_votes, name_spelled, items)
                            if items:  # a page found empty is asked again next time, in case it was a miss
                                cp_pages[p_key] = items
                                await _save_comic_cp()
                        else:
                            failed_vision_pages += 1
                            untranslated_pages.append(p_idx + 1)
                            page_errors[p_idx + 1] = st_info.get("error") or "no answer"
                            if st_info.get("error"):
                                last_vision_error = st_info["error"]
                            logger.warning(f"[{job_id}] Page {p_idx + 1} left untranslated: Vision AI failed "
                                           f"({page_errors[p_idx + 1]}).")
                    completed_count += 1
                    update_job(
                        job_id,
                        current_step=f"AI Vision translated graphic novel page {completed_count} of {total_pages}...",
                        progress=int((completed_count / max(total_pages, 1)) * 92),
                        done_chunks=completed_count,
                        total_chunks=total_pages,
                    )

                from backend.async_utils import gather_or_cancel
                await gather_or_cancel(_vision_worker(idx, img_b) for idx, img_b in vision_pages_to_process)

            total_vision_pages = len(vision_pages_to_process)
            total_detected_balloons = sum(len(v) for v in vision_results.values())
            if failed_vision_pages > 0 and (failed_vision_pages >= max(1, total_vision_pages // 2) or total_detected_balloons == 0):
                from backend.ai_polisher import is_gemini_quota_exhausted, DailyQuotaExhaustedError
                if is_gemini_quota_exhausted() or "quota" in (last_vision_error or "").lower():
                    if quota_behavior == "wait":
                        raise DailyQuotaExhaustedError(
                            f"Η μετάφραση Vision AI σταμάτησε λόγω εξάντλησης του ημερήσιου ορίου του Gemini Free Tier. "
                            f"Η πρόοδος ({completed_count} σελίδες) αποθηκεύτηκε σε checkpoint! "
                            f"(quota_behavior='wait')."
                        )
                    raise RuntimeError(
                        f"Η μετάφραση Vision AI σταμάτησε λόγω εξάντλησης του ημερήσιου ορίου του Gemini Free Tier. "
                        f"Η πρόοδος ({completed_count} σελίδες) αποθηκεύτηκε σε checkpoint! "
                        f"Αλλάξτε Gemini API key στις Ρυθμίσεις ή δοκιμάστε ξανά αργότερα."
                    )
                raise RuntimeError(
                    f"Η μετάφραση Vision AI απέτυχε σε {failed_vision_pages}/{total_vision_pages} σελίδες "
                    f"({last_vision_error or 'όριο αιτημάτων API 429'}). "
                    f"Η πρόοδος των επιτυχημένων σελίδων αποθηκεύτηκε — περιμένετε λίγα δευτερόλεπτα και πατήστε ξανά Start Translation για συνέχιση!"
                )

            if failed_vision_pages and quota_behavior == "wait":
                from backend.ai_polisher import is_gemini_quota_exhausted, DailyQuotaExhaustedError
                # "Wait" means no page may stay untranslated for lack of quota
                if is_gemini_quota_exhausted() or "quota" in (last_vision_error or "").lower():
                    raise DailyQuotaExhaustedError(
                        f"Η μετάφραση Vision AI σταμάτησε λόγω εξάντλησης του ημερήσιου ορίου του Gemini Free Tier. "
                        f"Απομένουν {failed_vision_pages} σελίδες· η πρόοδος αποθηκεύτηκε σε checkpoint!"
                    )

            # One spelling per name across the book, on copies: the checkpoint keeps what Vision answered
            render_pages = {p: [dict(i) for i in items if isinstance(i, dict)] for p, items in vision_results.items() if items}
            renamed = _harmonize_comic_names(render_pages, glossary_names)
            if renamed:
                logger.info(f"[{job_id}] One spelling per name: {renamed} balloon(s) adjusted.")

            # Apply detected redactions and Greek text rendering cleanly on the PDF document
            for p_idx, items in sorted(render_pages.items()):
                rendered_dialogues = _render_vision_balloons_on_page(doc[p_idx], items, font_path, target_lang=target_lang)
                all_document_dialogues[p_idx] = (p_idx + 1, rendered_dialogues)
            blank_pages.extend(sorted(
                p_idx + 1 for p_idx in vision_results
                if p_idx + 1 not in untranslated_pages and not all_document_dialogues[p_idx][1]
            ))

            if failed_vision_pages == 0 and cp_file.exists():
                try:
                    cp_file.unlink(missing_ok=True)
                except Exception:
                    pass

        # Save translated graphic novel PDF (always ensure out_dir exists!)
        stem = Path(file_path).stem
        out_dir = Path(output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        final_comic_pdf = out_dir / f"{stem}_translated_{target_lang}.pdf"
        from backend.pdf_text_names import fix_text_names
        fix_text_names(doc, "\n".join(t for _p, texts in all_document_dialogues for t in texts))
        doc.save(str(final_comic_pdf), garbage=3)  # stand-in fonts once, not on every page
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        if temp_pdf_to_clean and temp_pdf_to_clean.exists():
            try:
                temp_pdf_to_clean.unlink(missing_ok=True)
            except Exception:
                pass
        if temp_extract_dir_to_clean and temp_extract_dir_to_clean.exists():
            shutil.rmtree(temp_extract_dir_to_clean, ignore_errors=True)

    # Pre-generate CBZ archive as well for seamless instant download
    try:
        from backend.exporter import export_comic_archive
        final_comic_cbz = out_dir / f"{stem}_translated_{target_lang}.cbz"
        export_comic_archive(final_comic_pdf, final_comic_cbz, format="cbz")
    except Exception as cbz_err:
        logger.warning(f"Could not pre-generate CBZ comic archive: {cbz_err}")

    # Save translated dialogue script as text file (for editor review & audiobook generation)
    dialogue_script_lines = []
    for p_num, d_list in all_document_dialogues:
        dialogue_script_lines.append(f"\n{'='*50}\nPAGE {p_num}\n{'='*50}\n")
        if d_list:
            for d in d_list:
                dialogue_script_lines.append(f"— {d}\n")
        elif p_num in untranslated_pages:
            dialogue_script_lines.append("[Η σελίδα δεν μεταφράστηκε]\n")
        else:
            dialogue_script_lines.append("[Εικονογράφηση / Χωρίς κείμενο διαλόγου]\n")

    full_dialogue_text = "\n".join(dialogue_script_lines)
    Path(output_path).write_text(full_dialogue_text, encoding="utf-8")

    if untranslated_pages and notes is not None:
        pages_text = ", ".join(map(str, sorted(untranslated_pages)[:10])) + (" …" if len(untranslated_pages) > 10 else "")
        if resolved_api_key:
            errors = list(page_errors.values())
            why = f" ({max(set(errors), key=errors.count)[:140]})" if errors else ""  # the most common reason
            reason = f"Vision AI failed{why}; translate again to retry them"
        else:
            reason = "image-only pages need a Gemini API key"
        notes.append(f"{len(untranslated_pages)} page(s) left untranslated ({pages_text}): {reason}.")
    if blank_pages and notes is not None:
        shown = ", ".join(map(str, blank_pages[:10])) + (" …" if len(blank_pages) > 10 else "")
        notes.append(f"No text found on {len(blank_pages)} page(s) ({shown}): artwork only? "
                      f"If one of them has balloons, translate again to retry it.")

    update_job(
        job_id,
        status="running",
        progress=95,
        done_chunks=total_pages,
        total_chunks=total_pages,
        output_path=str(final_comic_pdf),
        current_step="Graphic novel translation complete! Preparing export...",
    )

    logger.info(f"[{job_id}] Graphic novel successfully translated: {final_comic_pdf}")
    return str(final_comic_pdf)
