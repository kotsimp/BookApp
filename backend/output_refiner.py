"""
output_refiner.py - Automatic Final Output Refinement & Quality-Control stage for BookApp.

An independent, modular stage that runs automatically as the LAST step of every successful
translation or audiobook generation. It never replaces the existing pipeline: it only inspects the
finished output and, where it is provably safe, applies conservative deterministic corrections.

Design principles
-----------------
* Non-destructive: every write goes to a staging file that is validated and then atomically swapped
  in with ``os.replace``. On any error the original output is left byte-for-byte untouched.
* Conservative: only unambiguous errors are auto-corrected (stutters of function words, accented
  monosyllables, final-nu, broken hyphenation, spacing before punctuation, ...). Constructions that
  *may* be legitimate (possible calques, unbalanced quotes, untranslated paragraphs, empty pages)
  are reported, never rewritten, so meaning is never changed and no information is added.
* No-op on clean output: if inspection finds nothing actionable, the text is returned unchanged.
* Format-aware: format-preserving outputs (in-place DOCX/EPUB, comics) are inspected only; they are
  never regenerated from plain text, which would destroy their original styling and artwork.
* Zero API cost by default: stage 1 is fully local. An optional stage 2 (AI refinement with Gemini,
  Advanced Mode only, explicitly opted into per job because it consumes extra tokens) is provided by
  ai_refine_translation_output() at the end of this module.
* Toggle: setting ``final_refinement_enabled`` (default True), env var ``FINAL_REFINEMENT_ENABLED``,
  or a per-request ``final_refinement`` override. When disabled the pipeline behaves exactly as before.
"""

import os
import re
import time
import asyncio
import shutil
import logging
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable

from backend.settings_manager import get_setting

logger = logging.getLogger(__name__)

REFINER_VERSION = "1.1.0"

# Layout modes in which whitespace / blank lines carry meaning and must not be normalised.
_WHITESPACE_SENSITIVE_LAYOUTS = {"poetry", "preserve", "comic", "graphic_novel", "verse"}

# Target languages whose typography *requires* a space before ; : ! ? (French, Breton, ...)
_SPACE_BEFORE_PUNCT_LANGS = {"french", "fr", "breton", "br"}

# Hard cap for direct-text refinement requests (characters) to avoid pathological regex costs.
MAX_DIRECT_TEXT_CHARS = 5_000_000

# Max chunks the audio healer will try to re-synthesise in one run (bounds network/API usage).
MAX_AUDIO_HEAL_CHUNKS = 25

# Minimum plausible size for a synthesised MP3 chunk (one MPEG frame is ~400 bytes at 128 kbps).
_MIN_CHUNK_BYTES = 32


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class RefinementIssue:
    category: str        # structure | grammar | phrasing | repetition | formatting | omission | file_io | audio_*
    description: str
    snippet: str = ""
    severity: str = "warning"   # info | warning | critical
    line_number: Optional[int] = None
    auto_fixable: bool = False


@dataclass
class TranslationRefinementResult:
    job_id: Optional[str]
    status: str          # refined | verified_clean | inspected | skipped | error
    original_text: str
    refined_text: str
    output_path: Optional[str] = None
    final_exported_path: Optional[str] = None
    issues_detected: List[RefinementIssue] = field(default_factory=list)
    issues_remaining: List[RefinementIssue] = field(default_factory=list)
    corrections_applied: List[str] = field(default_factory=list)
    modifications_count: int = 0
    original_char_count: int = 0
    refined_char_count: int = 0
    quality_score_before: float = 100.0
    quality_score_after: float = 100.0
    reverted: bool = False
    duration_ms: float = 0.0


@dataclass
class AudiobookRefinementResult:
    job_id: Optional[str]
    status: str          # verified_clean | healed | warning | skipped | error
    output_path: str
    format: str = "mp3"
    is_valid: bool = True
    duration_seconds: float = 0.0
    file_size_bytes: int = 0
    sample_rate: int = 0
    channels: int = 0
    bitrate: int = 0
    total_chunks_expected: int = 0
    total_chunks_verified: int = 0
    missing_chunk_indices: List[int] = field(default_factory=list)
    issues_detected: List[RefinementIssue] = field(default_factory=list)
    corrections_applied: List[str] = field(default_factory=list)
    healed: bool = False
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _coerce_bool(val: Any, default: bool = True) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off", ""):
            return False
    return default


def is_refinement_enabled(req_override: Optional[bool] = None) -> bool:
    """True if the final refinement stage should run. A per-request override wins over the setting."""
    if req_override is not None:
        return _coerce_bool(req_override)
    try:
        return _coerce_bool(get_setting("final_refinement_enabled", True), default=True)
    except Exception as e:  # unreadable settings must never block a job
        logger.warning(f"Could not read final_refinement_enabled setting ({e}); defaulting to enabled.")
        return True


def _norm_lang(lang: Optional[str]) -> str:
    return (lang or "").strip().lower()


def _is_greek(lang: str) -> bool:
    return lang in ("greek", "el", "ell", "gr")


def _is_english(lang: str) -> bool:
    return lang in ("english", "en", "eng") or lang.startswith("en-")


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_GR = "α-ωΑ-Ωάέήίόύώϊϋΐΰ"

# Unambiguous errors -> auto-corrected.
_SAFE_CALQUE_FIXES = [
    (re.compile(r"\bγια σίγουρα\b", re.IGNORECASE), "σίγουρα", "Literal calque 'για σίγουρα'"),
    (re.compile(r"\bπιάστηκε με κόκκινο χέρι\b", re.IGNORECASE), "πιάστηκε επ' αυτοφώρω", "Literal calque of 'caught red-handed'"),
    (re.compile(r"\bπάρε μια ματιά\b", re.IGNORECASE), "ρίξε μια ματιά", "Literal calque of 'take a look'"),
]

# Possibly-legitimate constructions -> reported only (rewriting could change meaning).
_ADVISORY_CALQUES = [
    (re.compile(r"\bκάνει νόημα\b", re.IGNORECASE), "Possible calque of 'makes sense' (also valid Greek for 'signals')"),
    (re.compile(r"\bήταν ικανός να\b", re.IGNORECASE), "Possibly wooden phrasing 'ήταν ικανός να' (consider 'μπορούσε να')"),
    (re.compile(r"\bστο τέλος της ημέρας\b", re.IGNORECASE), "Possible idiom calque 'at the end of the day'"),
    (re.compile(r"\bέκανε το μυαλό του\b", re.IGNORECASE), "Possible calque of 'made up his mind'"),
    (re.compile(r"\bνα διαχειριστής\b", re.IGNORECASE), "Likely verb/noun confusion 'να διαχειριστής'"),
    (re.compile(r"\bπάρε χρόνο\b", re.IGNORECASE), "Possible calque of 'take time'"),
]

# Function-word stutters only: repeated content words may be deliberate emphasis ("Όχι όχι", "σιγά σιγά").
_GREEK_FUNCTION_WORDS = (
    "και|το|τα|τη|την|της|του|των|τον|τις|τους|ο|η|οι|στο|στη|στην|στα|στον|στις|στους|"
    "για|με|σε|από|που|είναι|θα|να|ότι|πως|δε|δεν|μη|μην|ένα|μια|ένας"
)
_GREEK_STUTTER_PATTERN = re.compile(rf"(?<![{_GR}\w])({_GREEK_FUNCTION_WORDS})([ \t]+)\1(?![{_GR}\w])", re.IGNORECASE)

_ENGLISH_STUTTER_PATTERN = re.compile(
    r"\b(the|and|of|in|to|is|it|that|for|with|as|on|at|by|this|be|from|a|an)([ \t]+)\1\b",
    re.IGNORECASE,
)

# Monotonic Greek: these monosyllables never take an accent ("πού"/"πώς" are legitimate and excluded).
_MONOSYLLABLE_FIX = {"γιά": "για", "σέ": "σε", "μέ": "με", "τό": "το", "τά": "τα", "τόν": "τον", "τήν": "την", "νά": "να"}
_MONOSYLLABIC_ACCENT_PATTERN = re.compile(
    rf"(?<![{_GR}\w])(" + "|".join(_MONOSYLLABLE_FIX.keys()) + rf")(?![{_GR}\w])",
    re.IGNORECASE,
)

_PAGE_MARKER_REGEX = re.compile(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", re.IGNORECASE)
_PAGE_MARKER_LINE = re.compile(r"^\s*(?:={3,}\s*PAGE\s+\d+\s*={3,}|={3,}|PAGE\s+\d+)\s*$", re.IGNORECASE)

_SPACE_BEFORE_PUNCT = re.compile(r"(?<=\S)[ \t]+([,;:?!.])(?![.\w])")
_SPACE_BEFORE_PUNCT_FR = re.compile(r"(?<=\S)[ \t]+([,.])(?![.\w])")

_LATIN_SENTENCE = re.compile(r"[A-Za-z][A-Za-z'’\-]+")


# ---------------------------------------------------------------------------
# Translation inspection
# ---------------------------------------------------------------------------

_LINE_INDEX_CACHE: Dict[int, Tuple[str, List[int]]] = {}


def _line_of(text: str, pos: int) -> int:
    """1-based line number of ``pos``; newline offsets are indexed once per text (O(log n) per lookup)."""
    import bisect
    cached = _LINE_INDEX_CACHE.get(id(text))
    if cached is None or cached[0] is not text:
        _LINE_INDEX_CACHE.clear()  # keep at most one text alive
        cached = (text, [m.start() for m in re.finditer("\n", text)])
        _LINE_INDEX_CACHE[id(text)] = cached
    return bisect.bisect_left(cached[1], pos) + 1


def inspect_text_quality(
    text: Optional[str],
    target_lang: str = "greek",
    source_lang: str = "english",
    layout_mode: Optional[str] = None,
) -> List[RefinementIssue]:
    """Inspect text for structural, grammatical, phrasing, repetition, omission and formatting issues."""
    issues: List[RefinementIssue] = []
    if not text or not text.strip():
        return issues

    tgt = _norm_lang(target_lang)
    layout = _norm_lang(layout_mode) or "standard"

    # 1. Structure: page-marker continuity & empty translated pages (possible omissions)
    page_iter = list(_PAGE_MARKER_REGEX.finditer(text))
    if page_iter:
        nums = [int(m.group(1)) for m in page_iter]
        seen = set()
        for idx, pnum in enumerate(nums):
            if pnum in seen:
                issues.append(RefinementIssue("structure", f"Duplicate page marker: PAGE {pnum}",
                                              f"PAGE {pnum}", "warning", _line_of(text, page_iter[idx].start())))
            seen.add(pnum)
            if idx > 0 and pnum != nums[idx - 1] + 1 and pnum not in nums[:idx]:
                issues.append(RefinementIssue("structure", f"Non-sequential page gap: PAGE {nums[idx-1]} -> PAGE {pnum}",
                                              f"PAGE {pnum}", "warning", _line_of(text, page_iter[idx].start())))
        for idx, m in enumerate(page_iter):
            end = page_iter[idx + 1].start() if idx + 1 < len(page_iter) else len(text)
            body = re.sub(r"[=\s]", "", text[m.end():end])
            if not body:
                issues.append(RefinementIssue("omission", f"Translated page {m.group(1)} is empty (source page may be blank or translation dropped)",
                                              f"PAGE {m.group(1)}", "info", _line_of(text, m.start())))

    # 2. Dialogue quote balance (report only)
    if _is_greek(tgt):
        qo, qc = text.count("«"), text.count("»")
        if qo != qc:
            issues.append(RefinementIssue("structure", f"Unbalanced Greek quotes: {qo} '«' vs {qc} '»'",
                                          f"«={qo} »={qc}", "info"))
    for o, c, name in (("(", ")", "parentheses"), ("[", "]", "brackets")):
        if text.count(o) != text.count(c):
            issues.append(RefinementIssue("structure", f"Unbalanced {name}: {text.count(o)} '{o}' vs {text.count(c)} '{c}'",
                                          "", "info"))

    # 3. Language-specific checks
    if _is_greek(tgt):
        for pattern, replacement, desc in _SAFE_CALQUE_FIXES:
            for m in pattern.finditer(text):
                issues.append(RefinementIssue("phrasing", f"{desc} -> '{replacement}'", m.group(0), "warning",
                                              _line_of(text, m.start()), True))
        for pattern, desc in _ADVISORY_CALQUES:
            for m in pattern.finditer(text):
                issues.append(RefinementIssue("phrasing", desc, m.group(0), "info", _line_of(text, m.start())))
        for m in _GREEK_STUTTER_PATTERN.finditer(text):
            issues.append(RefinementIssue("repetition", f"Duplicated word: '{m.group(0)}'", m.group(0), "warning",
                                          _line_of(text, m.start()), True))
        for m in _MONOSYLLABIC_ACCENT_PATTERN.finditer(text):
            issues.append(RefinementIssue("grammar", f"Monosyllable must not be accented: '{m.group(0)}'", m.group(0),
                                          "warning", _line_of(text, m.start()), True))
        for m in re.finditer(rf"(?<![\w])[{_GR}]+[A-Za-z]+[{_GR}]*(?![\w])", text):
            issues.append(RefinementIssue("grammar", f"Latin characters inside Greek word: '{m.group(0)}'", m.group(0),
                                          "warning", _line_of(text, m.start()), True))
        for m in re.finditer(r"(?<![\w])(δε|μη)[ \t]+(?=[κπτξψ]|μπ|ντ|γκ|τσ|τζ|[αεηιουωάέήίόύώ])\w+", text, re.IGNORECASE):
            issues.append(RefinementIssue("grammar", f"Possible final-nu omission: '{m.group(0)}'", m.group(0),
                                          "info", _line_of(text, m.start()), True))
        # Omission check: whole paragraphs left in Latin script (likely untranslated)
        for para_m in re.finditer(r"[^\n]+", text):
            para = para_m.group(0).strip()
            if len(para) < 60 or _PAGE_MARKER_LINE.match(para):
                continue
            latin_words = _LATIN_SENTENCE.findall(para)
            greek_chars = len(re.findall(rf"[{_GR}]", para))
            if len(latin_words) >= 10 and greek_chars < 0.05 * len(para):
                issues.append(RefinementIssue("omission", "Paragraph appears untranslated (Latin script in Greek output)",
                                              para[:80], "warning", _line_of(text, para_m.start())))
    elif _is_english(tgt):
        for m in _ENGLISH_STUTTER_PATTERN.finditer(text):
            issues.append(RefinementIssue("repetition", f"Duplicated word: '{m.group(0)}'", m.group(0), "warning",
                                          _line_of(text, m.start()), True))
        for m in re.finditer(r"\b[aA]\s+(hour|honor|honour|honest|heir|apple|elephant|island|orange|umbrella)\b", text):
            issues.append(RefinementIssue("grammar", f"Article agreement: '{m.group(0)}' (should be 'an')", m.group(0),
                                          "warning", _line_of(text, m.start()), True))

    # 4. Universal formatting
    # (?<!\w) anchors at word start: keeps the scan linear on huge unbroken tokens (no O(n^2) backtracking)
    for m in re.finditer(r"(?<!\w)\w+-[ \t]*\n[ \t]*\w+", text):
        issues.append(RefinementIssue("formatting", "Word split across line break",
                                      m.group(0).replace("\n", " "), "info", _line_of(text, m.start()), True))
    punct_re = _SPACE_BEFORE_PUNCT_FR if tgt in _SPACE_BEFORE_PUNCT_LANGS else _SPACE_BEFORE_PUNCT
    if layout not in _WHITESPACE_SENSITIVE_LAYOUTS:
        for m in punct_re.finditer(text):
            issues.append(RefinementIssue("formatting", "Space before punctuation", m.group(0), "info",
                                          _line_of(text, m.start()), True))
        if re.search(r"\n[ \t]*\n[ \t]*\n[ \t]*\n", text):
            issues.append(RefinementIssue("formatting", "More than two consecutive blank lines", "", "info", None, True))

    _LINE_INDEX_CACHE.clear()  # release the reference to the inspected text
    return issues


# ---------------------------------------------------------------------------
# Deterministic refinement
# ---------------------------------------------------------------------------

def _preserve_case(orig: str, rep: str) -> str:
    if orig.isupper() and len(orig) > 1:
        return rep.upper()
    if orig[:1].isupper():
        return rep[:1].upper() + rep[1:]
    return rep


def refine_text_content(
    text: Optional[str],
    target_lang: str = "greek",
    source_lang: str = "english",
    style: Optional[str] = None,
) -> Tuple[Optional[str], List[RefinementIssue], List[str]]:
    """
    Conservatively refine text. Returns (refined_text, issues_detected, corrections_applied).
    Guarantees: unchanged text when nothing is auto-fixable; original text returned if any safety
    guard (page markers, paragraph count, length drift) fails.
    """
    if not text or not text.strip():
        return text, [], []

    tgt = _norm_lang(target_lang)
    layout = _norm_lang(style) or "standard"
    issues = inspect_text_quality(text, target_lang=tgt, source_lang=source_lang, layout_mode=layout)
    if not any(i.auto_fixable for i in issues):
        return text, issues, []

    refined = text
    corrections: List[str] = []

    def _step(label: str, fn: Callable[[str], str]):
        nonlocal refined
        try:
            new = fn(refined)
        except Exception as e:  # a single failing step must not abort the stage
            logger.warning(f"Refinement step '{label}' failed and was skipped: {e}")
            return
        if isinstance(new, str) and new != refined:
            refined = new
            corrections.append(label)

    from backend.typography import fix_broken_hyphens
    _step("Rejoined words split across line breaks", fix_broken_hyphens)

    if _is_greek(tgt):
        from backend.typography import clean_script_glitches_and_foreign_artifacts, apply_final_nu_rules

        _step("Normalized Latin homoglyphs inside Greek words", clean_script_glitches_and_foreign_artifacts)

        # Accents first, so later patterns (calques, stutters) match the normalised spelling
        _step("Removed accents from monosyllables",
              lambda s: _MONOSYLLABIC_ACCENT_PATTERN.sub(
                  lambda m: _preserve_case(m.group(0), _MONOSYLLABLE_FIX[m.group(0).lower()]), s))

        def _calques(s: str) -> str:
            for pattern, replacement, _ in _SAFE_CALQUE_FIXES:
                s = pattern.sub(lambda m, r=replacement: _preserve_case(m.group(0), r), s)
            return s
        _step("Replaced unambiguous literal calques", _calques)

        def _stutters(s: str) -> str:
            prev = None
            while prev != s:  # handle triples like "και και και"
                prev = s
                s = _GREEK_STUTTER_PATTERN.sub(lambda m: m.group(1), s)
            return s
        _step("Removed duplicated function words", _stutters)
        _step("Applied final-nu (τελικό -ν) rules", apply_final_nu_rules)

    elif _is_english(tgt):
        def _en_stutters(s: str) -> str:
            prev = None
            while prev != s:
                prev = s
                s = _ENGLISH_STUTTER_PATTERN.sub(lambda m: m.group(1), s)
            return s
        _step("Removed duplicated function words", _en_stutters)
        _step("Fixed indefinite article agreement (a -> an)",
              lambda s: re.sub(r"\b([aA])(\s+)(hour|honor|honour|honest|heir|apple|elephant|island|orange|umbrella)\b",
                               lambda m: ("An" if m.group(1) == "A" else "an") + m.group(2) + m.group(3), s))

    if layout not in _WHITESPACE_SENSITIVE_LAYOUTS:
        punct_re = _SPACE_BEFORE_PUNCT_FR if tgt in _SPACE_BEFORE_PUNCT_LANGS else _SPACE_BEFORE_PUNCT
        _step("Removed spaces before punctuation", lambda s: punct_re.sub(r"\1", s))
        _step("Collapsed excessive blank lines", lambda s: re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", s))

    if refined == text:
        return text, issues, []

    # --- Safety guards: never alter structure or meaningfully change length ---
    if _PAGE_MARKER_REGEX.findall(text) != _PAGE_MARKER_REGEX.findall(refined):
        logger.warning("Refinement altered page markers; reverting to original output.")
        return text, issues, []
    orig_lines = [ln for ln in text.split("\n") if ln.strip()]
    ref_lines = [ln for ln in refined.split("\n") if ln.strip()]
    hyphen_joins = len(re.findall(r"\w-[ \t]*\n[ \t]*\w", text))
    if not (len(orig_lines) - hyphen_joins <= len(ref_lines) <= len(orig_lines)):
        logger.warning("Refinement altered paragraph structure; reverting to original output.")
        return text, issues, []
    if len(text) > 100 and abs(len(refined) - len(text)) / len(text) > 0.10:
        logger.warning("Refinement changed length by >10%; reverting to original output.")
        return text, issues, []

    return refined, issues, corrections


def _quality_score(issues: List[RefinementIssue]) -> float:
    weights = {"critical": 10.0, "warning": 2.0, "info": 0.5}
    return round(max(0.0, 100.0 - sum(weights.get(i.severity, 1.0) for i in issues)), 1)


def summarize_issues(issues: List[RefinementIssue], limit: int = 10) -> List[Dict[str, Any]]:
    return [
        {"category": i.category, "severity": i.severity, "description": i.description, "line": i.line_number}
        for i in issues[:limit]
    ]


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, content: str) -> None:
    """Write via a sibling staging file (never *.txt, so download fallbacks can't pick it) then os.replace."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".refine-tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _commit_refined_text(job_id: Optional[str], text_src: Path, final_p: Optional[Path], original: str, refined: str,
                         fmt: str, is_rich: bool, layout_mode: str) -> Optional[str]:
    """
    Persists refined text (and re-exports the rich document) atomically.
    Returns None on success, otherwise a failure kind ('missing' | 'reexport' | 'write' | 'swap');
    on failure every file is left exactly as it was before the call.
    """
    staged_doc: Optional[Path] = None
    stage_dir: Optional[Path] = None
    if is_rich:
        if not final_p or not final_p.exists():
            logger.warning(f"[{job_id}] Exported document {final_p} missing; refinement not applied.")
            return "missing"
        try:
            from backend.exporter import export_text
            stage_dir = Path(tempfile.mkdtemp(prefix=".refine_", dir=str(final_p.parent)))
            cover = None  # make a cached cover visible to the exporter exactly as in the original export
            for cname in ("cover_image.jpg", "cover_image.png", "cover.jpg", "cover.png"):
                cp = final_p.parent / cname
                if cp.exists():
                    cover = cp.read_bytes()
                    break
            staged_doc = Path(export_text(refined, stage_dir, fmt, final_p.stem, layout=layout_mode, cover_image=cover))
            if not staged_doc.exists() or staged_doc.stat().st_size == 0:
                raise RuntimeError("re-export produced no file")
        except Exception as e:
            logger.warning(f"[{job_id}] Re-export after refinement failed ({e}); keeping original output untouched.")
            if stage_dir:
                shutil.rmtree(stage_dir, ignore_errors=True)
            return "reexport"

    # Commit: text first, then the document; roll text back if the document swap fails
    try:
        _atomic_write_text(text_src, refined)
    except Exception as e:
        logger.error(f"[{job_id}] Could not persist refined text ({e}); original output preserved.")
        if stage_dir:
            shutil.rmtree(stage_dir, ignore_errors=True)
        return "write"

    if staged_doc is not None:
        try:
            os.replace(staged_doc, final_p)
        except Exception as e:
            logger.error(f"[{job_id}] Could not swap in refined {fmt.upper()} ({e}); rolling back text.")
            try:
                _atomic_write_text(text_src, original)
            except Exception as rb:
                logger.error(f"[{job_id}] Text rollback failed: {rb}")
            return "swap"
        finally:
            if stage_dir:
                shutil.rmtree(stage_dir, ignore_errors=True)
    return None


# ---------------------------------------------------------------------------
# Translation output stage
# ---------------------------------------------------------------------------

async def refine_translation_output(
    job_id: Optional[str],
    output_path: str,
    final_exported_path: Optional[str] = None,
    source_lang: str = "english",
    target_lang: str = "greek",
    layout_mode: str = "standard",
    output_format: Optional[str] = None,
    api_key: Optional[str] = None,          # accepted for interface stability; the stage makes no API calls
    quota_behavior: str = "wait",           # idem
    enabled: Optional[bool] = None,
    allow_reexport: bool = True,
) -> TranslationRefinementResult:
    """
    Final refinement for a finished translation.

    * ``output_path`` is the plain-text translation (.txt).
    * ``final_exported_path`` is the user-facing document. It is regenerated from the refined text only
      when ``allow_reexport`` is True (i.e. the document was itself produced from that text by
      ``export_text``). Format-preserving outputs (in-place DOCX/EPUB, comics) must pass
      ``allow_reexport=False``: they are inspected and reported on, but never modified.
    * The text file and the exported document are kept consistent: if re-export fails, the text
      change is rolled back as well.
    """
    start = time.time()
    out_p = Path(output_path) if output_path else None
    final_p = Path(final_exported_path) if final_exported_path else out_p

    def _result(status: str, original: str = "", refined: Optional[str] = None, **kw) -> TranslationRefinementResult:
        return TranslationRefinementResult(
            job_id=job_id, status=status, original_text=original,
            refined_text=original if refined is None else refined,
            output_path=output_path, final_exported_path=str(final_p) if final_p else None,
            original_char_count=len(original), duration_ms=(time.time() - start) * 1000.0, **kw,
        )

    if not is_refinement_enabled(enabled):
        logger.info(f"[{job_id}] Final refinement disabled; output left untouched.")
        return _result("skipped")

    # Locate the text to refine
    text_src: Optional[Path] = None
    if out_p and out_p.is_file():
        text_src = out_p
    elif final_p and final_p.is_file() and final_p.suffix.lower() == ".txt":
        text_src = final_p
    if text_src is None:
        logger.info(f"[{job_id}] Final refinement: no plain-text output to inspect; skipped.")
        return _result("skipped", issues_detected=[RefinementIssue("file_io", "No text output found to refine", severity="info")])

    try:
        original = text_src.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"[{job_id}] Final refinement could not read {text_src.name}: {e}. Output preserved.")
        return _result("error", issues_detected=[RefinementIssue("file_io", f"Read failed: {e}", severity="critical")])

    if not original.strip():
        return _result("verified_clean", original,
                       issues_detected=[RefinementIssue("omission", "Translation output is empty", severity="warning")])

    refined, issues, corrections = refine_text_content(original, target_lang, source_lang, style=layout_mode)
    score_before = _quality_score(issues)

    fmt = (output_format or (final_p.suffix.lstrip(".") if final_p else "txt") or "txt").lower()
    if fmt == "doc":
        fmt = "docx"
    is_rich = fmt in ("pdf", "docx", "epub") and final_p is not None and final_p != text_src

    if refined == original or not corrections:
        status = "verified_clean"
        logger.info(f"[{job_id}] Final refinement: no corrections needed ({len(issues)} advisory notes).")
        return _result(status, original, issues_detected=issues, issues_remaining=issues,
                       quality_score_before=score_before, quality_score_after=score_before,
                       refined_char_count=len(original))

    if is_rich and not allow_reexport:
        # Format-preserved document: do not touch either file (keeps txt and document in sync).
        logger.info(f"[{job_id}] Final refinement: {len(corrections)} fixable issue group(s) found in a "
                    f"format-preserved {fmt.upper()}; reported only, files left untouched.")
        return _result("inspected", original, issues_detected=issues, issues_remaining=issues,
                       quality_score_before=score_before, quality_score_after=score_before,
                       refined_char_count=len(original))

    remaining = inspect_text_quality(refined, target_lang, source_lang, layout_mode)
    score_after = _quality_score(remaining)

    failure = _commit_refined_text(job_id, text_src, final_p, original, refined, fmt, is_rich, layout_mode)
    if failure is not None:
        return _result("error", original, issues_detected=issues, issues_remaining=issues,
                       quality_score_before=score_before, quality_score_after=score_before,
                       reverted=failure != "missing")

    logger.info(f"[{job_id}] Final refinement applied: {', '.join(corrections)} "
                f"(quality {score_before:.0f} -> {score_after:.0f}).")
    return _result("refined", original, refined,
                   issues_detected=issues, issues_remaining=remaining, corrections_applied=corrections,
                   modifications_count=len(corrections), refined_char_count=len(refined),
                   quality_score_before=score_before, quality_score_after=score_after)


# ---------------------------------------------------------------------------
# Audiobook inspection
# ---------------------------------------------------------------------------

def _chunk_index(path: str) -> Optional[int]:
    m = re.search(r"chunk_(\d+)\.mp3$", Path(path).name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _chunk_ok(path: str) -> bool:
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size >= _MIN_CHUNK_BYTES
    except OSError:
        return False


def inspect_audiobook_quality(
    audio_path: str,
    chunk_files: Optional[List[str]] = None,
    expected_chunks: Optional[int] = None,
    expected_indices: Optional[List[int]] = None,
) -> Tuple[bool, List[RefinementIssue], Dict[str, Any]]:
    """
    Inspect a finished audiobook: existence, container header, decodable duration, and (when chunk
    information is supplied) that every expected section was synthesised and assembled in order.

    ``expected_indices`` lists the segment indices that should have produced audio (segments whose text
    is legitimately empty must be excluded by the caller). When omitted, continuity is inferred from
    the chunk file names.
    """
    issues: List[RefinementIssue] = []
    meta: Dict[str, Any] = {"file_size": 0, "format": "", "duration": 0.0, "channels": 0,
                            "sample_rate": 0, "bitrate": 0, "valid_headers": False, "missing_indices": []}

    ap = Path(audio_path) if audio_path else None
    if ap is None or not ap.is_file():
        issues.append(RefinementIssue("audio_header", f"Audiobook file not found at: {audio_path}", severity="critical"))
        return False, issues, meta

    ext = ap.suffix.lower().lstrip(".")
    meta["format"] = ext
    size = ap.stat().st_size
    meta["file_size"] = size
    if size == 0:
        issues.append(RefinementIssue("audio_header", "Audiobook file is empty (0 bytes).", severity="critical"))
        return False, issues, meta

    # 1. Container header
    with open(ap, "rb") as f:
        head = f.read(16)
    def _looks_mp3(h: bytes) -> bool:
        return h.startswith(b"ID3") or (len(h) >= 2 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0)

    valid_header = False
    decode_as = ext
    if ext == "mp3":
        valid_header = _looks_mp3(head)
    elif ext in ("m4b", "m4a", "mp4"):
        valid_header = b"ftyp" in head[:12]
        if not valid_header and _looks_mp3(head):
            # tts_engine.export_audiobook_m4b falls back to a tagged MP3 copy when ffmpeg is unavailable
            valid_header = True
            decode_as = "mp3"
            issues.append(RefinementIssue("audio_header", "M4B file contains an MP3 stream (ffmpeg unavailable); playable but has no chapters.",
                                          severity="info"))
    if not valid_header:
        issues.append(RefinementIssue("audio_header", f"Invalid or corrupted {ext.upper()} container header.", severity="critical"))
    meta["valid_headers"] = valid_header

    # 2. Stream decoding (mutagen is optional at runtime; absence is not an error)
    try:
        if decode_as == "mp3":
            from mutagen.mp3 import MP3
            info = MP3(str(ap)).info
            meta.update(duration=float(info.length or 0.0), channels=int(getattr(info, "channels", 0) or 0),
                        sample_rate=int(getattr(info, "sample_rate", 0) or 0), bitrate=int(getattr(info, "bitrate", 0) or 0))
        elif decode_as in ("m4b", "m4a", "mp4"):
            from mutagen.mp4 import MP4
            info = MP4(str(ap)).info
            meta.update(duration=float(info.length or 0.0), bitrate=int(getattr(info, "bitrate", 0) or 0),
                        channels=int(getattr(info, "channels", 0) or 0), sample_rate=int(getattr(info, "sample_rate", 0) or 0))
        if valid_header and meta["duration"] <= 0.0:
            issues.append(RefinementIssue("audio_header", "Audio stream has zero playable duration.", severity="critical"))
    except ImportError:
        pass
    except Exception as e:
        issues.append(RefinementIssue("audio_header", f"Audio stream could not be decoded: {e}", severity="warning"))

    # 3. Section completeness & ordering
    if chunk_files is not None:
        present = {}
        for c in chunk_files:
            idx = _chunk_index(c)
            if idx is not None:
                present[idx] = c
        expected = sorted(set(expected_indices)) if expected_indices is not None else None

        if expected is None and expected_chunks is not None and len(chunk_files) != expected_chunks:
            issues.append(RefinementIssue("audio_sequence",
                                          f"Chunk count mismatch: expected {expected_chunks}, found {len(chunk_files)}",
                                          severity="warning"))

        missing: List[int] = []
        if expected is not None:
            missing = [i for i in expected if i not in present or not _chunk_ok(present[i])]
        else:
            idxs = sorted(present)
            for a, b in zip(idxs, idxs[1:]):
                missing.extend(range(a + 1, b))
            missing.extend(i for i in idxs if not _chunk_ok(present[i]))
            missing = sorted(set(missing))
        for i in missing:
            issues.append(RefinementIssue("audio_sequence", f"Missing or failed audio section: chunk {i}",
                                          f"chunk_{i:06d}.mp3", "critical"))
        meta["missing_indices"] = missing

        # Ordering is guaranteed by the caller passing chunks in index order; verify it.
        listed = [i for i in (_chunk_index(c) for c in chunk_files) if i is not None]
        if listed != sorted(listed):
            issues.append(RefinementIssue("audio_sequence", "Audio chunks are not in sequential order.", severity="critical"))

        # Truncation check: binary concatenation must contain at least all valid chunk bytes (MP3 only)
        if ext == "mp3":
            chunk_bytes = sum(Path(c).stat().st_size for c in chunk_files if _chunk_ok(c))
            if chunk_bytes and size < chunk_bytes:
                issues.append(RefinementIssue("audio_sequence",
                                              f"Final audio ({size} B) is smaller than its sections ({chunk_bytes} B): truncated.",
                                              severity="critical"))

    valid = valid_header and not any(i.severity == "critical" for i in issues)
    return valid, issues, meta


def _has_id3_title(path: str) -> bool:
    try:
        from mutagen.id3 import ID3
        return bool(ID3(path).get("TIT2"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Audiobook output stage
# ---------------------------------------------------------------------------

async def refine_audiobook_output_async(
    job_id: Optional[str],
    output_path: str,
    chunk_files: Optional[List[str]] = None,
    expected_chunks: Optional[int] = None,
    expected_indices: Optional[List[int]] = None,
    language: str = "greek",
    book_title: str = "Audiobook",
    cover_image_path: Optional[str] = None,
    enabled: Optional[bool] = None,
    resynthesize_chunk: Optional[Callable[[int], Awaitable[bool]]] = None,
    reassemble: Optional[Callable[[List[str], str], Awaitable[None]]] = None,
) -> AudiobookRefinementResult:
    """
    Final refinement for a finished audiobook.

    1. Inspects the assembled file and its sections.
    2. If sections are missing and the caller supplied ``resynthesize_chunk`` + ``reassemble``
       callbacks, retries the failed sections (bounded by MAX_AUDIO_HEAL_CHUNKS), re-assembles into a
       staging file, validates it, and only then atomically replaces the original.
    3. Adds ID3 metadata only if it is missing (no redundant rewrites).
    The original file is never replaced by anything that fails validation.
    """
    start = time.time()
    if not is_refinement_enabled(enabled):
        logger.info(f"[{job_id}] Final audiobook refinement disabled; output left untouched.")
        return AudiobookRefinementResult(job_id=job_id, status="skipped", output_path=output_path)

    valid, issues, meta = inspect_audiobook_quality(output_path, chunk_files, expected_chunks, expected_indices)
    corrections: List[str] = []
    healed = False
    missing = list(meta.get("missing_indices") or [])
    ext = meta.get("format") or Path(output_path).suffix.lower().lstrip(".")

    # --- Heal missing sections ---
    if missing and chunk_files is not None and resynthesize_chunk and reassemble and Path(output_path).exists():
        to_heal = missing[:MAX_AUDIO_HEAL_CHUNKS]
        recovered: List[int] = []
        for idx in to_heal:
            try:
                if await resynthesize_chunk(idx):
                    recovered.append(idx)
            except Exception as e:
                logger.warning(f"[{job_id}] Re-synthesis of chunk {idx} failed: {e}")
        if recovered:
            chunk_dir = Path(chunk_files[0]).parent if chunk_files else Path(output_path).parent
            all_idx = sorted(set([i for i in (_chunk_index(c) for c in chunk_files) if i is not None] + recovered))
            new_chunks = [str(chunk_dir / f"chunk_{i:06d}.mp3") for i in all_idx]
            out_p = Path(output_path)
            fd, staged = tempfile.mkstemp(prefix=f".{out_p.stem}.", suffix=out_p.suffix, dir=str(out_p.parent))
            os.close(fd)
            try:
                await reassemble(new_chunks, staged)
                ok, new_issues, new_meta = inspect_audiobook_quality(staged, new_chunks, None, expected_indices)
                if ok or len(new_meta.get("missing_indices") or []) < len(missing):
                    if Path(staged).stat().st_size >= meta.get("file_size", 0):
                        os.replace(staged, output_path)
                        corrections.append(f"Re-synthesised {len(recovered)} missing section(s) and re-assembled the audiobook")
                        healed = True
                        valid, issues, meta, chunk_files = ok, new_issues, new_meta, new_chunks
                        missing = list(new_meta.get("missing_indices") or [])
            except Exception as e:
                logger.warning(f"[{job_id}] Audiobook re-assembly failed ({e}); original audio kept.")
            finally:
                if os.path.exists(staged):
                    try:
                        os.unlink(staged)
                    except OSError:
                        pass

    # --- Metadata: only when absent ---
    if ext == "mp3" and meta.get("valid_headers") and not _has_id3_title(output_path):
        try:
            from backend.tts_engine import tag_audiobook_file
            tag_audiobook_file(output_path, title=book_title, author="BookApp", cover_image_path=cover_image_path)
            if _has_id3_title(output_path):
                corrections.append("Added missing ID3 metadata")
                healed = True
        except Exception as e:
            logger.warning(f"[{job_id}] Metadata repair skipped: {e}")

    if not valid:
        status = "error" if not meta.get("valid_headers") or not Path(output_path).exists() else "warning"
    else:
        status = "healed" if healed else "verified_clean"
    total_expected = len(expected_indices) if expected_indices is not None else (expected_chunks or len(chunk_files or []))
    verified = sum(1 for c in (chunk_files or []) if _chunk_ok(c))
    log = logger.info if status in ("verified_clean", "healed") else logger.warning
    log(f"[{job_id}] Audiobook refinement: status={status}, duration={meta.get('duration', 0.0):.1f}s, "
        f"size={meta.get('file_size', 0)}B, sections={verified}/{total_expected}, issues={len(issues)}")

    return AudiobookRefinementResult(
        job_id=job_id, status=status, output_path=output_path, format=ext, is_valid=valid,
        duration_seconds=meta.get("duration", 0.0), file_size_bytes=meta.get("file_size", 0),
        sample_rate=meta.get("sample_rate", 0), channels=meta.get("channels", 0), bitrate=meta.get("bitrate", 0),
        total_chunks_expected=total_expected, total_chunks_verified=verified,
        missing_chunk_indices=missing, issues_detected=issues, corrections_applied=corrections,
        healed=healed, duration_ms=(time.time() - start) * 1000.0,
    )


def refine_audiobook_output(
    job_id: Optional[str],
    output_path: str,
    chunk_files: Optional[List[str]] = None,
    expected_chunks: Optional[int] = None,
    language: str = "greek",
    book_title: str = "Audiobook",
    cover_image_path: Optional[str] = None,
    enabled: Optional[bool] = None,
    expected_indices: Optional[List[int]] = None,
) -> AudiobookRefinementResult:
    """Synchronous inspection/metadata variant (no re-synthesis). Safe to call outside an event loop."""
    import asyncio
    coro = refine_audiobook_output_async(job_id, output_path, chunk_files, expected_chunks, expected_indices,
                                         language, book_title, cover_image_path, enabled)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise RuntimeError("refine_audiobook_output() called inside a running event loop; await refine_audiobook_output_async().")


def build_refinement_report(result: Any) -> Dict[str, Any]:
    """Compact, JSON-safe summary stored on the job and shown to the UI."""
    issues = list(getattr(result, "issues_remaining", None) or getattr(result, "issues_detected", []) or [])
    return {
        "version": REFINER_VERSION,
        "status": getattr(result, "status", "unknown"),
        "corrections": list(getattr(result, "corrections_applied", []) or []),
        "issues_count": len(issues),
        "critical_count": sum(1 for i in issues if i.severity == "critical"),
        "issues": summarize_issues(issues),
        "quality_score": getattr(result, "quality_score_after", None),
        "missing_sections": list(getattr(result, "missing_chunk_indices", []) or []),
        "duration_ms": round(float(getattr(result, "duration_ms", 0.0) or 0.0), 1),
    }


# ---------------------------------------------------------------------------
# Stage 2 (optional, Advanced Mode): AI refinement with Gemini
# ---------------------------------------------------------------------------
#
# Runs AFTER the deterministic stage, only when explicitly requested (per job / per request) and a Gemini key is
# available. It consumes extra API tokens (≈ the size of the document in input AND output), which the UI warns about.
# Safety: the text is processed in paragraph-aligned chunks; page markers are never sent to the model; every chunk
# is checked (same paragraph count, length within ±15%, no new page markers, same script/language) and silently
# kept as the original if the check fails. Quota/auth errors stop the stage but keep the chunks already refined.

AI_REFINE_CHUNK_CHARS = 9000
AI_REFINE_CONCURRENCY = 2
AI_REFINE_VERSION = "1.0"

_AI_REFINE_LANG_NAMES = {
    "greek": "Modern Greek (monotonic orthography)", "el": "Modern Greek (monotonic orthography)",
    "english": "English", "en": "English", "french": "French", "fr": "French", "german": "German",
    "de": "German", "spanish": "Spanish", "es": "Spanish", "italian": "Italian", "it": "Italian",
}


def _ai_refine_prompt(target_lang: str, layout_mode: str) -> str:
    lang_name = _AI_REFINE_LANG_NAMES.get(_norm_lang(target_lang), target_lang or "the text's language")
    verse = ("This is POETRY/VERSE: keep every line break and stanza exactly; never merge or split lines.\n"
             if _norm_lang(layout_mode) in ("poetry", "verse") else "")
    return (
        f"You are the final copy-editor of a finished book translation written in {lang_name}. "
        "Make ONLY necessary corrections: grammar, spelling, accentuation, punctuation, agreement, awkward or overly "
        "literal (translationese) phrasing, and inconsistent rendering of the same name or term.\n"
        "STRICT RULES:\n"
        "1. Never add, remove, summarise, explain or reorder content; never change the meaning, facts, tone or style.\n"
        "2. Keep EXACTLY the same paragraphs: same number of paragraphs, separated by one blank line, in the same order.\n"
        "3. If a paragraph is already correct, return it unchanged. Prefer minimal edits.\n"
        "4. Keep dialogue punctuation, quotation marks, numbers, names and Markdown markers as they are unless wrong.\n"
        f"{verse}"
        "5. Output only the corrected text, with no comments, notes or headings of your own."
    )


def _split_for_ai(text: str, max_chars: int = AI_REFINE_CHUNK_CHARS) -> List[Tuple[str, bool]]:
    """Splits text into [(segment, refinable)] keeping page markers and blank-line separators verbatim."""
    segments: List[Tuple[str, bool]] = []
    pos = 0
    for m in _PAGE_MARKER_REGEX.finditer(text):
        segments.extend(_split_body(text[pos:m.start()], max_chars))
        segments.append((m.group(0), False))
        pos = m.end()
    segments.extend(_split_body(text[pos:], max_chars))
    return segments


def _split_body(body: str, max_chars: int) -> List[Tuple[str, bool]]:
    if not body:
        return []
    out: List[Tuple[str, bool]] = []
    parts = re.split(r"(\n[ \t]*\n)", body)          # [para, sep, para, sep, ...]
    buf = ""
    for i, part in enumerate(parts):
        is_sep = i % 2 == 1
        if not is_sep and buf and len(buf) + len(part) > max_chars:
            out.append((buf, True))
            buf = ""
        buf += part
    if buf:
        out.append((buf, True))
    # Separate leading/trailing whitespace from each refinable chunk so it is preserved exactly
    final: List[Tuple[str, bool]] = []
    for seg, ok in out:
        lead = seg[: len(seg) - len(seg.lstrip())]
        trail = seg[len(seg.rstrip()):]
        core = seg.strip()
        if lead:
            final.append((lead, False))
        if core:
            final.append((core, ok and bool(re.search(r"[^\W\d_]{2,}", core))))
        if trail:
            final.append((trail, False))
    return final


def estimate_ai_refinement_cost(text: str) -> Dict[str, int]:
    """Approximate extra Gemini usage (requests and tokens, input + output) of the AI refinement stage."""
    segs = [s for s, ok in _split_for_ai(text or "") if ok]
    chars = sum(len(s) for s in segs)
    # ~3 chars/token for Greek, ~4 for English: use 3 (conservative); input + output + prompt overhead
    tokens = int(chars / 3 * 2 + len(segs) * 350)
    return {"requests": len(segs), "estimated_tokens": tokens, "characters": chars}


def _chunk_is_safe(original: str, refined: str, target_lang: str) -> Tuple[bool, str]:
    if not refined or not refined.strip():
        return False, "empty"
    if _PAGE_MARKER_REGEX.search(refined) or "```" in refined:
        return False, "markup injected"
    paras_o = [p for p in re.split(r"\n[ \t]*\n", original) if p.strip()]
    paras_r = [p for p in re.split(r"\n[ \t]*\n", refined) if p.strip()]
    if len(paras_o) != len(paras_r):
        return False, f"paragraphs {len(paras_o)}->{len(paras_r)}"
    if len(original) >= 40 and not (0.85 <= len(refined) / len(original) <= 1.15):
        return False, f"length ratio {len(refined) / len(original):.2f}"
    if _is_greek(_norm_lang(target_lang)):
        def share(t):
            letters = [c for c in t if c.isalpha()]
            return sum(1 for c in letters if "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿") / max(len(letters), 1)
        if share(refined) < share(original) - 0.05:
            return False, "script drift"
    return True, ""


async def ai_refine_text(
    text: str,
    target_lang: str,
    api_key: str,
    layout_mode: str = "standard",
    progress: Optional[Callable[[int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    session=None,
) -> Tuple[str, Dict[str, Any]]:
    """Returns (refined_text, stats). Never raises for AI failures: unrefined chunks keep their original text."""
    from backend.ai_polisher import _call_gemini_api, DailyQuotaExhaustedError
    stats: Dict[str, Any] = {"chunks_total": 0, "chunks_refined": 0, "chunks_unchanged": 0, "chunks_rejected": 0,
                             "chunks_failed": 0, "stopped_reason": None, "rejections": []}
    segments = _split_for_ai(text)
    work = [i for i, (_, ok) in enumerate(segments) if ok]
    stats["chunks_total"] = len(work)
    if not work:
        return text, stats
    prompt = _ai_refine_prompt(target_lang, layout_mode)
    results = {i: segments[i][0] for i in range(len(segments))}
    sem = asyncio.Semaphore(AI_REFINE_CONCURRENCY)
    stop = asyncio.Event()
    done = 0

    async def _one(i: int):
        nonlocal done
        original = segments[i][0]
        async with sem:
            if stop.is_set() or (is_cancelled and is_cancelled()):
                return
            try:
                out = await _call_gemini_api(original, api_key, prompt, session=session, temperature=0.15,
                                             cache_gate=lambda o: bool(o and o.strip()))
            except (DailyQuotaExhaustedError, PermissionError) as e:
                stats["stopped_reason"] = "quota_exhausted" if isinstance(e, DailyQuotaExhaustedError) else "auth_failed"
                stats["chunks_failed"] += 1
                stop.set()
                return
            except Exception as e:
                stats["chunks_failed"] += 1
                logger.warning(f"AI refinement chunk failed ({e}); original kept.")
                return
        out = out.strip()
        ok, why = _chunk_is_safe(original, out, target_lang)
        if not ok:
            stats["chunks_rejected"] += 1
            if len(stats["rejections"]) < 10:
                stats["rejections"].append(why)
        elif out == original:
            stats["chunks_unchanged"] += 1
        else:
            results[i] = out
            stats["chunks_refined"] += 1
        done += 1
        if progress:
            progress(done, len(work))

    await asyncio.gather(*(_one(i) for i in work))
    if is_cancelled and is_cancelled():
        stats["stopped_reason"] = stats["stopped_reason"] or "cancelled"
    return "".join(results[i] for i in range(len(segments))), stats


async def ai_refine_translation_output(
    job_id: Optional[str],
    output_path: str,
    final_exported_path: Optional[str],
    target_lang: str,
    api_key: Optional[str],
    layout_mode: str = "standard",
    output_format: Optional[str] = None,
    allow_reexport: bool = True,
    progress: Optional[Callable[[int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """
    Optional AI refinement of a finished translation (Advanced Mode). Returns a JSON-safe report.
    Files are only replaced atomically after every check passed; any failure leaves the output untouched.
    """
    start = time.time()
    report: Dict[str, Any] = {"version": AI_REFINE_VERSION, "status": "skipped", "reason": None}
    final_p = Path(final_exported_path) if final_exported_path else None
    text_src = Path(output_path) if output_path else None
    if not (api_key or "").strip():
        report["reason"] = "no_api_key"
        return report
    if text_src is None or not text_src.is_file():
        report["reason"] = "no_text_output"
        return report
    fmt = (output_format or (final_p.suffix.lstrip(".") if final_p else "txt") or "txt").lower()
    fmt = "docx" if fmt == "doc" else fmt
    is_rich = fmt in ("pdf", "docx", "epub") and final_p is not None and final_p != text_src
    if is_rich and not allow_reexport:
        report["reason"] = "format_preserved_output"
        return report
    try:
        original = text_src.read_text(encoding="utf-8")
    except Exception as e:
        report.update(status="error", reason=f"read_failed: {e}")
        return report
    if not original.strip():
        report["reason"] = "empty_output"
        return report

    import aiohttp
    async with aiohttp.ClientSession() as session:
        refined, stats = await ai_refine_text(original, target_lang, api_key, layout_mode, progress, is_cancelled, session)
    report.update(stats)
    report["estimated_tokens"] = estimate_ai_refinement_cost(original)["estimated_tokens"]

    if is_cancelled and is_cancelled():
        report.update(status="cancelled")
        return report
    if refined != original:
        # Re-apply the deterministic stage to the AI output (cheap, idempotent) — guards still apply
        refined = refine_text_content(refined, target_lang=target_lang, style=layout_mode)[0] or refined
        if _PAGE_MARKER_REGEX.findall(refined) != _PAGE_MARKER_REGEX.findall(original):
            report.update(status="error", reason="page_markers_changed")
            return report
    if refined == original:
        report["status"] = "partial" if stats["stopped_reason"] else "verified_clean"
        report["duration_ms"] = round((time.time() - start) * 1000.0, 1)
        return report
    failure = _commit_refined_text(job_id, text_src, final_p, original, refined, fmt, is_rich, layout_mode)
    if failure is not None:
        report.update(status="error", reason=f"commit_{failure}")
        return report
    report["status"] = "partial" if stats["stopped_reason"] else "refined"
    report["duration_ms"] = round((time.time() - start) * 1000.0, 1)
    logger.info(f"[{job_id}] AI refinement: {stats['chunks_refined']}/{stats['chunks_total']} chunks improved, "
                f"{stats['chunks_rejected']} rejected by safety checks, {stats['chunks_failed']} failed.")
    return report
