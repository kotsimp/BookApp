"""
ai_polisher.py - AI-Powered Translation Proofreading & Refinement using Gemini API.
Polishes machine-translated Greek text into natural, grammatically flawless,
and stylistically appropriate language (formal administrative, technical, natural, literature, audiobook).
Features bilingual source-anchoring, character/entity consistency dossier,
rolling narrative context, and smart disk checkpointing.
"""

import os
import re
import unicodedata
import json
import time
import hashlib
import logging
import asyncio
import threading
import contextvars
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Callable, Any

import aiohttp

from backend.async_utils import gather_or_cancel

logger = logging.getLogger(__name__)

# Prompts live in backend/translation_prompts.py (versioned, language-aware, generic — no title-specific terms)
from backend import translation_prompts as _prompts  # noqa: E402
from backend.translation_prompts import (  # noqa: E402
    PROMPT_VERSION, build_polish_prompt, build_direct_translation_prompt, build_dossier_prompt, dossier_header,
)

STYLE_PROMPTS = _prompts.STYLE_PROMPTS  # public re-export (existing callers/tests import it from here)

# Context-scoped model policy: when True, _call_gemini_api only uses full (non-Lite, non-Gemma) models. Used by the
# maximum-quality revision pass, where a weaker fallback model can introduce errors instead of removing them.
_FULL_MODELS_ONLY: contextvars.ContextVar[bool] = contextvars.ContextVar("gemini_full_models_only", default=False)


# Models that recently timed out are tried LAST for a while (not removed: they stay as fallbacks). Without this,
# every request re-waited the full timeout on the same slow model before reaching a responsive one.
_MODEL_SLOW_UNTIL: dict[str, float] = {}
SLOW_MODEL_PENALTY_S = 600.0
OVERLOADED_MODEL_PENALTY_S = 120.0  # a 500/503 answer: overloads pass quickly


def _deprioritize_slow_models(candidates: list[str]) -> list[str]:
    now = time.time()
    fast = [m for m in candidates if _MODEL_SLOW_UNTIL.get(m, 0.0) <= now]
    slow = [m for m in candidates if _MODEL_SLOW_UNTIL.get(m, 0.0) > now]
    return fast + slow


def _is_full_model(name: str) -> bool:
    n = (name or "").lower()
    return "lite" not in n and not n.startswith("gemma") and ("flash" in n or "pro" in n)


# ---------------------------------------------------------------------------
# Gemini usage accounting (per job + per day)
# ---------------------------------------------------------------------------
# A pipeline opens an accumulator with `track_gemini_usage()`; every Gemini call made inside it (including child
# asyncio tasks, which inherit the context) adds its usageMetadata. A daily total is kept for the settings view.
_USAGE_ACC: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("gemini_usage_acc", default=None)
_DAILY_USAGE: dict[str, Any] = {"date": "", "requests": 0, "cached": 0, "prompt_tokens": 0, "output_tokens": 0}
_DAILY_USAGE_BY_USER: dict[str, dict[str, Any]] = {}  # user accounts mode: today's usage per user id
_USAGE_LOCK = threading.Lock()


def new_usage_accumulator() -> dict[str, Any]:
    return {"requests": 0, "cached": 0, "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class track_gemini_usage:
    """Context manager: `with track_gemini_usage() as usage: ...` collects usage of all Gemini calls inside."""

    def __init__(self, acc: Optional[dict] = None):
        self.acc = acc if acc is not None else new_usage_accumulator()
        self._token = None

    def __enter__(self) -> dict:
        self._token = _USAGE_ACC.set(self.acc)
        return self.acc

    def __exit__(self, *exc) -> bool:
        _USAGE_ACC.reset(self._token)
        return False


def record_gemini_usage(response_json: Optional[dict] = None, cached: bool = False) -> None:
    """Adds one Gemini response (or a cache hit) to the active job accumulator and the daily total."""
    meta = (response_json or {}).get("usageMetadata") or {}
    p_tok = int(meta.get("promptTokenCount") or 0)
    o_tok = int(meta.get("candidatesTokenCount") or 0)
    today = time.strftime("%Y-%m-%d")
    with _USAGE_LOCK:
        if _DAILY_USAGE["date"] != today:
            _DAILY_USAGE.update(date=today, requests=0, cached=0, prompt_tokens=0, output_tokens=0)
            _DAILY_USAGE_BY_USER.clear()
        targets = [_DAILY_USAGE]
        acc = _USAGE_ACC.get()
        if acc is not None:
            targets.append(acc)
        from backend.request_context import current_user_id
        uid = current_user_id()
        if uid:
            targets.append(_DAILY_USAGE_BY_USER.setdefault(
                uid, {"requests": 0, "cached": 0, "prompt_tokens": 0, "output_tokens": 0}))
        for t in targets:
            if cached:
                t["cached"] = t.get("cached", 0) + 1
            else:
                t["requests"] = t.get("requests", 0) + 1
                t["prompt_tokens"] = t.get("prompt_tokens", 0) + p_tok
                t["output_tokens"] = t.get("output_tokens", 0) + o_tok
            if "total_tokens" in t:
                t["total_tokens"] = t["prompt_tokens"] + t["output_tokens"]


def get_daily_gemini_usage_by_user() -> dict[str, dict[str, Any]]:
    """Today's Gemini usage per user id (user accounts mode), for the administrators' Users panel."""
    with _USAGE_LOCK:
        if _DAILY_USAGE["date"] != time.strftime("%Y-%m-%d"):
            return {}
        return {uid: dict(u, total_tokens=u["prompt_tokens"] + u["output_tokens"])
                for uid, u in _DAILY_USAGE_BY_USER.items()}


def get_daily_gemini_usage() -> dict[str, Any]:
    with _USAGE_LOCK:
        if _DAILY_USAGE["date"] != time.strftime("%Y-%m-%d"):
            return {"date": time.strftime("%Y-%m-%d"), "requests": 0, "cached": 0, "prompt_tokens": 0,
                    "output_tokens": 0, "total_tokens": 0}
        d = dict(_DAILY_USAGE)
        d["total_tokens"] = d["prompt_tokens"] + d["output_tokens"]
        return d

STYLE_TEMPERATURES = {
    "literature": 0.35,
    "natural": 0.25,
    "audiobook": 0.25,
    "poetry": 0.25,
    "formal": 0.15,
    "technical": 0.15,
}

# Cached discoveries to avoid querying Google ModelService on every single page
_CACHED_WORKING_MODEL: Optional[str] = None
_CACHED_AVAILABLE_MODELS: Optional[list[str]] = None  # the models of the key used last
_CACHED_API_KEY_HASH: Optional[str] = None
_MODELS_BY_KEY: dict[str, list[str]] = {}  # key hash -> its text models: requests take the pool's keys in turn
_CHECKPOINT_LOCK = threading.RLock()

POLISH_STATUS: dict[str, dict[str, Any]] = {}


def get_polish_job_status(job_id: str) -> dict[str, Any]:
    """Returns the current real-time progress dict of an AI Polish job."""
    return POLISH_STATUS.get(
        job_id,
        {"current": 0, "total": 1, "percent": 0, "status": "idle", "step": ""},
    )


def update_polish_job_status(job_id: str, **kwargs: Any) -> dict[str, Any]:
    """Updates real-time status of an AI Polish job."""
    st = POLISH_STATUS.setdefault(
        job_id,
        {"current": 0, "total": 1, "percent": 0, "status": "idle", "step": ""},
    )
    st.update(kwargs)
    return st


def reset_model_cache():
    """Invalidate cached Gemini model discovery list (e.g. when API key changes)."""
    global _CACHED_WORKING_MODEL, _CACHED_AVAILABLE_MODELS
    _CACHED_WORKING_MODEL = None
    _CACHED_AVAILABLE_MODELS = None
    _MODELS_BY_KEY.clear()
    reset_gemini_quota_exhaustion()


EXCLUDE_PATTERNS = [
    "-tts", "-image", "-audio", "-transcribe", "clip", "banana",
    "robotics", "customtools", "computer-use", "argon",
    "lyria", "deep-research", "antigravity", "veo", "imagen", "embedding",
]

PREFERRED_FLASH_MODELS = [
    # Full Flash models (high translation quality, small daily free limit)
    "gemini-3.5-flash",
    "gemini-flash-latest",
    # High-throughput Flash-Lite models (fallback)
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    # Preview and tier-limited models (with automatic per-model cooldown tracking)
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3-flash-preview",
    "gemini-pro-latest",
]

# Permissive safety settings for literary/sci-fi/historical translation so fictional violence,
# mature prose, profanity, or body horror does not trigger spurious SAFETY/PROHIBITED_CONTENT refusals.
_LITERARY_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

_TRANSIENT_RETRY_DELAY = 2.0


class DailyQuotaExhaustedError(RuntimeError):
    """Raised when Gemini returns 429 quota exhaustion or requests per day limit exceeded."""


_GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL: float = 0.0


def is_gemini_quota_exhausted() -> bool:
    """Returns True if Gemini daily quota was tripped and is currently in cooldown."""
    global _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL
    now = time.time()
    if now < _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL:
        return True

    try:
        from backend.gemini_key_pool import GeminiKeyPool
        # If pool has keys configured and all are exhausted
        if GeminiKeyPool.get_keys() and not GeminiKeyPool.get_active_key():
            return True
    except Exception:
        pass

    try:
        from backend.settings_manager import get_setting
        persisted = float(get_setting("gemini_quota_exhausted_until", 0.0) or 0.0)
        _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL = persisted
        if now < persisted:
            return True
    except Exception:
        if now < _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL:
            return True
    return False


def trip_gemini_quota_exhaustion(cooldown_seconds: float = 3600.0) -> None:
    """Trip Gemini daily quota circuit breaker to fail-fast across all modules and processes."""
    global _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL
    target = time.time() + cooldown_seconds
    _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL = max(_GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL, target)
    try:
        from backend.settings_manager import save_setting
        save_setting("gemini_quota_exhausted_until", _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL)
    except Exception:
        pass


def reset_gemini_quota_exhaustion() -> None:
    """Reset the circuit breaker (e.g. if the user enters a new API key)."""
    global _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL
    _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL = 0.0
    try:
        from backend.settings_manager import delete_setting
        delete_setting("gemini_quota_exhausted_until")
    except Exception:
        pass
    try:
        from backend.gemini_key_pool import _KEY_COOLDOWNS, _pool_lock
        with _pool_lock:
            _KEY_COOLDOWNS.clear()
    except Exception:
        pass


def get_gemini_quota_info() -> dict[str, Any]:
    """Returns a dict with quota status, remaining seconds, exact reset clock time, and user-facing message."""
    pool_status: dict[str, Any] = {}
    try:
        from backend.gemini_key_pool import GeminiKeyPool
        pool_status = GeminiKeyPool.get_pool_status()
    except Exception:
        pass

    exhausted = is_gemini_quota_exhausted()
    if not exhausted:
        return {
            "exhausted": False,
            "remaining_seconds": 0,
            "reset_timestamp": 0.0,
            "reset_time_str": "",
            "cooldown_time_str": "",
            "message": None,
            "pool": pool_status,
        }

    now = time.time()
    earliest = pool_status.get("earliest_reset_timestamp", 0.0) if pool_status else 0.0
    reset_ts = earliest if earliest > now else max(_GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL, now + 1.0)
    rem_sec = int(max(1.0, reset_ts - now))

    import datetime
    reset_dt = datetime.datetime.fromtimestamp(reset_ts)
    reset_time_str = reset_dt.strftime("%H:%M:%S")
    rem_min = rem_sec // 60
    if rem_min > 60:
        time_str = f"{rem_min // 60}ώ {rem_min % 60}λ"
    elif rem_min >= 1:
        time_str = f"{rem_min}λ {rem_sec % 60}δ"
    else:
        time_str = f"{rem_sec}δ"

    msg = (
        f"Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). "
        f"Έτοιμο ξανά στις {reset_time_str} (απομένουν ~{time_str}). "
        f"Μπορείτε να αλλάξετε API Key στις Ρυθμίσεις (Settings) για άμεση συνέχιση."
    )
    return {
        "exhausted": True,
        "remaining_seconds": rem_sec,
        "reset_timestamp": reset_ts,
        "reset_time_str": reset_time_str,
        "cooldown_time_str": time_str,
        "message": msg,
        "pool": pool_status,
    }


# Any of these ends an answer early, also when part of the text has already arrived
_INTERRUPTED_REASONS = frozenset({
    "SAFETY", "PROHIBITED_CONTENT", "RECITATION", "BLOCKLIST", "SPII", "LANGUAGE", "OTHER", "MALFORMED_RESPONSE",
})


class _TruncatedOutputError(RuntimeError):
    """Raised when Gemini finishes with MAX_TOKENS so the caller can split the batch and retry."""


class _ContentBlockedError(RuntimeError):
    """Raised when Gemini returns an empty/blocked response (SAFETY, PROHIBITED_CONTENT, RECITATION)."""


# A real tag: name, then only name=value attributes ("a<b and c>d" is a comparison, not a tag)
_HTML_INLINE_TAG_RE = re.compile(
    r"</?(i|b|em|strong|u|s|span|p|br|div|font|sup|sub|small|big|mark|del|ins|a|h[1-6])"
    r"(?:\s+[A-Za-z_:][\w:.-]*\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+))*\s*/?>",
    re.IGNORECASE,
)
# The book's own bracketed notes, in either language
_SOURCE_NOTE_RE = re.compile(r"\[\s*(?:Σημ|Σ\.\s?τ\.|Note\b|N\.\s?[BT]|Editor|Translator|Ed\.|Tr\.)", re.IGNORECASE)
_LLM_SPECIAL_TOKEN_RE = re.compile(
    r"<(?:/?(?:bos|eos|pad|unk|sep|cls|mask|start_of_turn|end_of_turn|thought|think)|\|[^|\n]{1,32}\|)>",
    re.IGNORECASE,
)
_LEAKED_PREV_CTX_BLOCK_RE = re.compile(
    r"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>.*?</PREVIOUS_CONTEXT_DO_NOT_REPEAT>",
    re.IGNORECASE | re.DOTALL,
)
_LEAKED_WRAPPER_TAG_RE = re.compile(
    r"</?(?:PREVIOUS_CONTEXT_DO_NOT_REPEAT|TEXT_TO_POLISH|DRAFT_TO_POLISH|SOURCE_REFERENCE|TEXT_TO_TRANSLATE)>",
    re.IGNORECASE,
)
_LEAKED_ELLIPSIS_BRACKET_RE = re.compile(
    r"(?:^|\n)\s*\[\.\.\.\s*[^\]]{8,600}\]\s*(?=\n|$)",
    re.DOTALL,
)
_EDITOR_NOTE_RE = re.compile(
    r"\[(?:Σημείωση(?:\s+(?:επιμελητή|μεταφραστή|εκδότη))?|Editor'?s?\s+note|Translator'?s?\s+note|Note)\s*:[^\]]*\]",
    re.IGNORECASE,
)
_COT_BLOCK_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\*\s*\*?(?:Refining|Drafting|Thinking|Analysis|Checking|Review|Verification)\s*:.*|"
    r"\d+\.\s*\*\*(?:Review|Final\s+Polish|Analyze|Translate|Check|Draft)[^*]*\*\*.*|"
    r"\*\*(?:Review\s+against|Final\s+Polish|Self-Check|Verification)\b.*|"
    r"\*\s*(?:No\s+introductory\s+notes|Page\s+markers|Glossary|Entity\s+Dossier|Tone|Style)[^?]*\?\s*Checked\.?.*|"
    r"Proceed\s+to\s+output\s+(?:pure\s+)?translated\s+text\.?.*"
    r")$",
    re.IGNORECASE,
)
_LEAKED_PROMPT_HEADER_RE = re.compile(
    r"^---\s*(?:ΠΡΟΗΓΟΥΜΕΝΟ\s+ΑΠΟΣΠΑΣΜΑ|ΠΡΩΤΟΤΥΠΟ\s+ΚΕΙΜΕΝΟ\s+ΑΝΑΦΟΡΑΣ|ΠΡΟΣΧΕΔΙΟ\s+ΕΛΛΗΝΙΚΗΣ\s+ΜΕΤΑΦΡΑΣΗΣ|ΚΕΙΜΕΝΟ\s+ΠΡΟΣ\s+ΕΠΙΜΕΛΕΙΑ|INPUT\s+TEXT)[^\n]*---\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Exotic scripts that should NEVER appear inside translated Greek prose unless present in source
# (incl. the Hebrew/Arabic presentation forms a model emits as '\u039a\ufe8d\ufead\u03bb', '\u03a6\u03b1\u03c1\u03bc\u03b1\u03ba\u03b5\ufeed\u03c4\u03b9\u03ba\u03ae')
_EXOTIC_SCRIPT_RE = re.compile(
    r"[\u0400-\u052f\u0530-\u058f\u0590-\u05ff\u0600-\u08ff\u0900-\u0e7f\u10a0-\u10ff\u2e80-\u9fff\uac00-\ud7af"
    r"\ufb1d-\ufdff\ufe70-\ufefc\ufffd]"
)
_GREEK_CHAR_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")
_SCI_UNIT_RE = re.compile(r"^[μµΔΩαβγλσπρ][A-Za-z]{1,2}\d*$")

_MIXED_HOMOGLYPHS = {
    'a': 'α', 'A': 'Α', 'b': 'β', 'B': 'Β', 'c': 'σ', 'C': 'Σ', 'd': 'δ', 'D': 'Δ',
    'e': 'ε', 'E': 'Ε', 'h': 'η', 'H': 'Η', 'i': 'ι', 'I': 'Ι', 'k': 'κ', 'K': 'Κ',
    'l': 'λ', 'm': 'μ', 'M': 'Μ', 'n': 'ν', 'N': 'Ν', 'o': 'ο', 'O': 'Ο', 'p': 'ρ',
    'P': 'Ρ', 'r': 'ρ', 's': 'σ', 't': 'τ', 'T': 'Τ', 'u': 'υ', 'v': 'ν', 'w': 'ω',
    'x': 'χ', 'X': 'Χ', 'y': 'υ', 'Y': 'Υ', 'z': 'ζ'
}


def fix_mixed_script_words(text: str, source_text: str = "") -> str:
    """
    Repairs subword token bleed where Latin letters leaked inside Greek words. Scientific symbols (TNFα, NFκB, kΩ)
    and tokens the source itself contains are left alone.
    """
    if not text:
        return text
    from backend.typography import is_corrupt_greek_word

    def _repair_tok(match):
        w = match.group(0)
        if "http" in w or "@" in w or _SCI_UNIT_RE.match(w):
            return w
        if not is_corrupt_greek_word(w) or (source_text and w in source_text):
            return w
        # Common multi-letter subwords
        w = w.replace('ka', 'κα').replace('ri', 'ρι').replace('el', 'ει').replace('ANES', 'ανες')
        out = []
        for ch in w:
            out.append(_MIXED_HOMOGLYPHS.get(ch, ch))
        res = ''.join(out)
        res = re.sub(r'σ(?=[.,;:!?\s]|$)', 'ς', res)
        return res

    pat = re.compile(r'(?<![A-Za-z0-9_\u0370-\u03ff])(?=[^\s]*[\u0370-\u03ff])(?=[^\s]*[A-Za-z])[^\s,;.:!?«»"\'()\[\]—–\-/\\*<>]+(?![A-Za-z0-9_\u0370-\u03ff])')
    return pat.sub(_repair_tok, text)


_POLYTONIC_RE = re.compile(r"[ἀ-῿]")
# breathings and the iota subscript go; the circumflex and grave become the modern accent
_MONOTONIC_MARKS = {"̓": "", "̔": "", "̓": "", "ͅ": "", "͂": "́", "̀": "́"}


def to_monotonic(text: str) -> str:
    """Polytonic letters a model slipped into modern Greek ('ῥούφηξε', 'δῶθε', 'ἴσως'), written monotonic."""
    if not text or not _POLYTONIC_RE.search(text):
        return text

    def _one(m: "re.Match[str]") -> str:
        decomposed = unicodedata.normalize("NFD", m.group(0))
        base, marks = decomposed[0], [_MONOTONIC_MARKS.get(c, c) for c in decomposed[1:]]
        if not base.isalpha():
            return "" if unicodedata.category(m.group(0)) == "Sk" else m.group(0)  # a spacing breathing mark
        kept = ("̈" if "̈" in marks else "") + ("́" if "́" in marks else "")
        return unicodedata.normalize("NFC", base + kept)

    return _POLYTONIC_RE.sub(_one, text)


_PROSE_WORD_RE = re.compile(r"^[\"“‘'(«]?[A-Za-z][A-Za-z'’\-]*[.,;:!?\"”’')»…]*$")


def _letters(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower())


def _copied_source_prose(answer: str, given: str, min_words: int = 25) -> int:
    """
    Length in words of the longest run of the source's prose that `answer` copied unchanged, or 0.
    Names, short quotations and reference lists stay out: a run needs `min_words` plain words in a row, mostly in
    lower case as running prose is, and its opening words must occur word for word in `given`.
    """
    body = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", " ", answer or "")
    source = " " + " ".join(w for w in map(_letters, (given or "").split()) if w) + " "
    best = 0
    run: list[str] = []

    def close() -> None:
        nonlocal best
        if len(run) >= max(min_words, best + 1):
            lower = sum(1 for w in run if w.lstrip("\"“‘'(«")[:1].islower())
            probe = " " + " ".join(w for w in map(_letters, run[:12]) if w) + " "
            if lower >= 0.6 * len(run) and probe in source:
                best = len(run)
        run.clear()

    for tok in body.split():
        if _PROSE_WORD_RE.match(tok):
            run.append(tok)
        else:
            close()
    close()
    return best


def _split_marked_pages(text: str) -> list[tuple[Optional[int], str]]:
    """[(page number or None for text before the first marker, body), ...] in order, duplicates kept."""
    parts = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text or "")
    out: list[tuple[Optional[int], str]] = [(None, parts[0])] if parts[0].strip() else []
    out += [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]
    return out


def find_untranslated_pages(translated: str, original: str, min_words: int = 25) -> list[int]:
    """Pages of a translation that still carry a passage of the original's prose, copied unchanged."""
    source: dict[int, list[str]] = {}
    for pn, body in _split_marked_pages(original):
        if pn is not None:
            source.setdefault(pn, []).append(body)
    found = set()
    for pn, body in _split_marked_pages(translated):
        if pn is None or not body.strip():
            continue
        # text may drift across a page break: the neighbouring pages count as the same source
        ref = "\n".join("\n".join(source.get(p, [])) for p in (pn - 1, pn, pn + 1))
        if ref.strip() and _copied_source_prose(body, ref, min_words):
            found.add(pn)
    return sorted(found)


_EMPTY_DUPLICATE_MARKER_RE = re.compile(r"={3,}\s*PAGE\s+(\d+)\s*={3,}\s*(?=={3,}\s*PAGE\s+\1\s*={3,})")


def collapse_empty_duplicate_markers(text: str) -> str:
    """'=== PAGE 14 ===' left empty right before another '=== PAGE 14 ===' (a split page's seam) is dropped."""
    return _EMPTY_DUPLICATE_MARKER_RE.sub("", text or "")


def _quality_retry_hint(issues: list[str], answer: str, source: str, greek_target: bool) -> str:
    """What the retry after a flagged answer is told about the previous attempt's faults."""
    if not greek_target:
        return ""
    hint = ""
    bad_tokens = _find_mixed_script_tokens(answer, source_text=source)
    if bad_tokens:
        hint += (
            "\n\n--- ΚΡΙΣΙΜΗ ΔΙΟΡΘΩΣΗ ΜΕΙΚΤΟΥ ΑΛΦΑΒΗΤΟΥ ---\n"
            f"Στην προηγούμενη προσπάθεια εμφανίστηκαν λέξεις με ξένους/λατινικούς χαρακτήρες μέσα σε ελληνικές λέξεις "
            f"({', '.join(bad_tokens[:8])}). Γράψε ΟΛΕΣ τις ελληνικές λέξεις με 100% καθαρούς ελληνικούς χαρακτήρες!"
        )
    if any(i.startswith("dialogue_dashes") for i in issues):
        hint += (
            "\n\n--- ΚΡΙΣΙΜΗ ΔΙΟΡΘΩΣΗ ΔΙΑΛΟΓΩΝ ---\n"
            "Στην προηγούμενη προσπάθεια οι διάλογοι γράφτηκαν με παύλες (—). Το πρωτότυπο βάζει τους διαλόγους σε "
            "εισαγωγικά: γράψε ΚΑΘΕ διάλογο μέσα σε «...», όπως σε όλο το υπόλοιπο βιβλίο."
        )
    if any(i.startswith("untranslated") for i in issues):
        hint += (
            "\n\n--- ΚΡΙΣΙΜΗ ΔΙΟΡΘΩΣΗ: ΑΜΕΤΑΦΡΑΣΤΟ ΚΕΙΜΕΝΟ ---\n"
            "Στην προηγούμενη προσπάθεια ένα τμήμα έμεινε στη γλώσσα του πρωτοτύπου. Μετάφρασε ΟΛΟ το κείμενο στα "
            "Ελληνικά, και τα σκληρά ή βίαια σημεία του κειμένου, πιστά και χωρίς παραλείψεις."
        )
    return hint


def _extract_gemini_text_and_reason(result: dict) -> tuple[str, str]:
    """
    Extracts non-thought text and finishReason from a Gemini generateContent JSON payload.
    Strictly ignores Gemini 2.5/3.x 'thought: true' reasoning parts so chain-of-thought never leaks.
    """
    if not isinstance(result, dict):
        return "", ""
    prompt_fb = result.get("promptFeedback")
    block_reason = str(prompt_fb.get("blockReason") or "") if isinstance(prompt_fb, dict) else ""
    cand_list = result.get("candidates") or []
    if not cand_list or not isinstance(cand_list, list):
        return "", block_reason
    cand = cand_list[0] if isinstance(cand_list[0], dict) else {}
    finish_reason = str(cand.get("finishReason") or block_reason or "")
    parts = (cand.get("content") or {}).get("parts") or []
    text_parts = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        if p.get("thought") is True:
            continue
        t = p.get("text")
        if isinstance(t, str) and t:
            text_parts.append(t)
    return "".join(text_parts).strip(), finish_reason


def clean_transcription(text: str) -> str:
    """A page's text as Gemini read it from a picture: only the wrappers a model adds are removed (code fences, special
    tokens). The translation sanitiser would also drop things that are the book's own, such as a bracketed note."""
    cleaned = unicodedata.normalize("NFC", text or "").strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = _LLM_SPECIAL_TOKEN_RE.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def sanitize_ai_output(text: str, source_text: str = "") -> str:
    """
    Defensively removes LLM artifacts from generated/polished text:
    - HTML/XML inline tags ('εισπ</i>νευστική' -> 'εισπνευστική')
    - Special LLM tokens ('<bos>', '<eos>', '<|endoftext|>')
    - Echoed <PREVIOUS_CONTEXT_DO_NOT_REPEAT> blocks, wrapper XML tags, and '[... ...]' context echoes
    - Bracketed editor/translator meta-notes ('[Σημείωση...: ...]')
    - Leaked chain-of-thought / self-review lines ('**Review against Rules...**', 'Proceed to output...')
    - Subword token bleed (mixed Greek/Latin chars repaired)
    - Markdown code fences wrapping prose
    - Broken hyphenated Greek words ('υποσχέ- θηκαν' -> 'υποσχέθηκαν')

    ``source_text`` is what the model was given: whatever of the above the book itself contains is content
    (a book about HTML, a translator's note) and is kept.
    """
    if not text:
        return text
    src = source_text or ""

    # NFC: models sometimes emit polytonic-block or decomposed accents (e.g. U+1FCB 'Ή', 'Η'+U+0301) that look right
    # but break search, glossary matching, PDF fonts and TTS; NFC maps them to the standard monotonic code points.
    cleaned = unicodedata.normalize("NFC", text).strip()
    # Polytonic letters ('ῥ', 'δῶθε') are a model's slip in modern Greek, unless the source itself is polytonic
    if not _POLYTONIC_RE.search(src):
        cleaned = to_monotonic(cleaned)
    # Strip outer markdown code fence if the model wrapped the whole output
    if "```" not in src:
        cleaned = re.sub(r"^```(?:markdown|text|el|greek)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    # Strip echoed read-only previous context blocks, wrapper tags, and leaked '[... ...]' snippets
    cleaned = _LEAKED_PREV_CTX_BLOCK_RE.sub("", cleaned)
    cleaned = _LEAKED_WRAPPER_TAG_RE.sub("", cleaned)
    if "[..." not in src and "[…" not in src:
        cleaned = _LEAKED_ELLIPSIS_BRACKET_RE.sub("\n", cleaned)

    # Strip LLM special tokens and leaked inline HTML tags
    src_tokens = {t.lower() for t in _LLM_SPECIAL_TOKEN_RE.findall(src)}
    cleaned = _LLM_SPECIAL_TOKEN_RE.sub(lambda m: m.group(0) if m.group(0).lower() in src_tokens else "", cleaned)
    src_tags = {m.group(1).lower() for m in _HTML_INLINE_TAG_RE.finditer(src)}
    cleaned = _HTML_INLINE_TAG_RE.sub(lambda m: m.group(0) if m.group(1).lower() in src_tags else "", cleaned)
    if not _SOURCE_NOTE_RE.search(src):
        cleaned = _EDITOR_NOTE_RE.sub("", cleaned)
    cleaned = _LEAKED_PROMPT_HEADER_RE.sub("", cleaned)

    # Repair any mixed-script subword token bleed
    cleaned = fix_mixed_script_words(cleaned, src)

    # Remove Chain-of-Thought / self-review blocks (from first leaked review heading to end or per-line)
    cot_start = re.compile(
        r"\*\*Review\s+against\s+Rules|\*\*Final\s+Polish\s*:\*\*|Proceed\s+to\s+output\s+(?:pure\s+)?translated\s+text",
        re.IGNORECASE,
    )
    src_reviews = bool(src) and (bool(cot_start.search(src)) or any(_COT_BLOCK_LINE_RE.match(ln) for ln in src.splitlines()))
    if not src_reviews:
        out_lines: list[str] = []
        in_cot_tail = False
        for ln in cleaned.splitlines():
            if cot_start.search(ln):
                in_cot_tail = True
                continue
            if in_cot_tail:
                # Stop skipping once a real page marker (1-line or 3-line translator format) resumes
                if re.match(r"^\s*={3,}\s*PAGE\s+\d+\s*={3,}\s*$", ln) or re.match(r"^\s*PAGE\s+\d+\s*$", ln) or re.match(r"^\s*={6,}\s*$", ln):
                    in_cot_tail = False
                    out_lines.append(ln)
                continue
            if _COT_BLOCK_LINE_RE.match(ln):
                continue
            out_lines.append(ln)
        cleaned = "\n".join(out_lines)

    # Collapse spaces left behind by removed editor notes (without breaking paragraph newlines or the book's indents)
    indented = bool(re.search(r"(?m)^[ \t]{2,}\S", src))
    cleaned = re.sub(r"(?<=\S)[ \t]{2,}" if indented else r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    try:
        from backend.typography import fix_broken_hyphens, sanitize_editorial_pass, is_mostly_greek
        cleaned = fix_broken_hyphens(cleaned)
        if is_mostly_greek(cleaned):  # the Greek editorial rules would rewrite words of other languages
            cleaned = sanitize_editorial_pass(cleaned)
    except Exception as ex:
        logger.warning(f"Editorial sanitising skipped: {ex}")

    return cleaned.strip()


def _find_mixed_script_tokens(text: str, source_text: str = "") -> list[str]:
    """Returns distinct tokens containing mixed Greek+Latin/exotic characters or stray exotic scripts."""
    if not text:
        return []
    src_has_exotic = bool(_EXOTIC_SCRIPT_RE.search(source_text or ""))
    bad_tokens: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"[^\s,;.:!?«»\"'()\[\]—–\-/\\*<>]+", text):
        tok = m.group(0)
        if _SCI_UNIT_RE.match(tok):
            continue
        has_gr = bool(_GREEK_CHAR_RE.search(tok))
        has_lat = bool(_LATIN_LETTER_RE.search(tok))
        has_ex = bool(_EXOTIC_SCRIPT_RE.search(tok))
        if (has_gr and (has_lat or has_ex)) or (has_ex and not src_has_exotic):
            if source_text and tok in source_text:
                continue
            if tok not in seen:
                seen.add(tok)
                bad_tokens.append(tok)
    return bad_tokens


class _BadAnswerError(RuntimeError):
    """The model's answer lost text or changed the language: it must not replace the book's text."""


def _script_counts(text: str) -> tuple[int, int]:
    body = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", text or "")
    return len(_GREEK_CHAR_RE.findall(body)), len(_LATIN_LETTER_RE.findall(body))


def _answer_problem(
    answer: str,
    given: str,
    greek_target: bool,
    expected_pages: Optional[list[int]] = None,
    translating: bool = False,
) -> str:
    """Why this answer may not replace `given`, or "". Lesser issues only earn a retry."""
    for issue in detect_greek_output_issues(answer, source_text=given, expected_pages=expected_pages,
                                            greek_target=greek_target):
        if issue.startswith(("empty", "missing_pages", "truncated")):
            return issue
    greek, latin = _script_counts(answer)
    given_greek, given_latin = _script_counts(given)
    # halved batches get too short for the gate's 400-character rule, and a cut there loses text just the same
    if given_greek + given_latin >= 60 and greek + latin < 0.45 * (given_greek + given_latin):
        return f"truncated(letters={greek + latin}/{given_greek + given_latin})"
    if not greek_target and greek >= 20 and greek > latin and (translating or given_latin > given_greek):
        return "wrong_language(greek)"
    if greek_target and not translating and latin >= 20 and latin > greek and given_greek > given_latin:
        return "wrong_language(latin)"
    if greek_target and translating:
        # a model that will not translate a passage (often a violent or crude one) echoes it back unchanged
        copied = _copied_source_prose(answer, given)
        if copied:
            return f"untranslated(copied_words={copied})"
    return ""


def _continuity_rule(greek_target: bool, translating: bool = False) -> str:
    if not greek_target:
        verb = "translate" if translating else "edit"
        return ("\n\n--- CONTINUITY RULE ---\n"
                "<PREVIOUS_CONTEXT_DO_NOT_REPEAT> is given only for names, gender and flow. Do not "
                f"{verb}, repeat or output it: begin with the text that follows it, without XML tags.")
    if translating:
        return ("\n\n--- ΚΑΝΟΝΑΣ ΣΥΝΕΧΕΙΑΣ (ΜΗΝ ΜΕΤΑΦΡΑΖΕΙΣ ΤΟ ΠΡΟΗΓΟΥΜΕΝΟ ΑΠΟΣΠΑΣΜΑ) ---\n"
                "Το τμήμα <PREVIOUS_CONTEXT_DO_NOT_REPEAT> παρέχεται ΜΟΝΟ ως αναφορά για γένος, ονόματα και ροή. "
                "ΜΗΝ το μεταφράσεις, ΜΗΝ το επαναλάβεις και ΜΗΝ το συμπεριλάβεις στην έξοδό σου. "
                "Ξεκίνα τη μετάφρασή σου ΑΜΕΣΩΣ από το κείμενο εντός <TEXT_TO_TRANSLATE> (χωρίς ετικέτες XML).")
    return ("\n\n--- ΚΑΝΟΝΑΣ ΣΥΝΕΧΕΙΑΣ (ΜΗΝ ΕΠΑΝΑΛΑΜΒΑΝΕΙΣ) ---\n"
            "Το τμήμα <PREVIOUS_CONTEXT_DO_NOT_REPEAT> παρέχεται ΜΟΝΟ ως αναφορά για γένος, ονόματα και ροή. "
            "ΜΗΝ το συμπεριλάβεις, ΜΗΝ το ξαναγράψεις και ΜΗΝ το επαναλάβεις στην έξοδό σου. "
            "Ξεκίνα την έξοδό σου ΑΜΕΣΩΣ από το κείμενο εντός <DRAFT_TO_POLISH>/<TEXT_TO_POLISH>.")


def glossary_towards_english(items: dict, greek_source: str, limit: int = 50) -> list[tuple[str, str]]:
    """The glossary is English -> Greek. For an English target: the pairs whose Greek the source uses, reversed."""
    low = (greek_source or "").lower()
    pairs = []
    for term, value in items.items():
        bare = re.sub(r"\s*\([^()]*\)\s*$", "", str(value)).strip()
        key = bare.lower()
        if (len(key) >= 4 and _GREEK_CHAR_RE.search(key) and key in low
                and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", low)):
            pairs.append((bare, term))
            if len(pairs) >= limit:
                break
    return pairs


def english_glossary_rules(items: dict, greek_source: str) -> str:
    pairs = glossary_towards_english(items, greek_source)
    if not pairs:
        return ""
    lines = "\n".join(f"- {greek} -> {english}" for greek, english in pairs)
    return f"\n\n--- GLOSSARY (use where the meaning matches) ---\n{lines}\n"


def detect_greek_output_issues(
    text: str,
    source_text: str = "",
    expected_pages: Optional[list[int]] = None,
    greek_target: bool = True,
) -> list[str]:
    """
    Quality gate for AI-translated/polished batches (``greek_target=False`` skips the Greek-script checks).
    Returns a list of issue codes (empty list means clean):
    - 'mixed_script': Greek words corrupted with Latin/Cyrillic/Hebrew/Arabic/Armenian/Bengali/CJK chars
    - 'cot_leak': leftover English reasoning / review chatter
    - 'missing_pages': expected '=== PAGE X ===' markers dropped
    - 'truncated': output severely shorter than source or cut off mid-word
    """
    issues: list[str] = []
    if not text or not text.strip():
        return ["empty"]

    # 1. Mixed-script / exotic-script corruption check (classic Flash-Lite failure mode)
    # Exempt standard SI / scientific units combining a Greek prefix with Latin unit letters (e.g. μm, μg, Δt, Ωm)
    src_has_exotic = bool(_EXOTIC_SCRIPT_RE.search(source_text or ""))
    mixed_count = 0
    exotic_count = 0
    for m in re.finditer(r"[^\s,;.:!?«»\"'()\[\]—–\-/\\*<>]+", text):
        tok = m.group(0)
        if _SCI_UNIT_RE.match(tok):
            continue
        has_gr = bool(_GREEK_CHAR_RE.search(tok))
        has_lat = bool(_LATIN_LETTER_RE.search(tok))
        has_ex = bool(_EXOTIC_SCRIPT_RE.search(tok))
        if source_text and (has_gr or has_ex) and tok in source_text:
            continue  # the book's own symbol (TNFα, kΩ) or quotation
        if has_gr and (has_lat or has_ex):
            mixed_count += 1
        elif has_ex and not src_has_exotic:
            exotic_count += 1
    if mixed_count >= 1 or exotic_count >= 1:
        issues.append(f"mixed_script({mixed_count}+{exotic_count})")

    # 2. Residual CoT / English meta-commentary check
    if re.search(
        r"Proceed\s+to\s+output\s+(?:pure\s+)?translated\s+text|Review\s+against\s+Rules\s+and\s+Dossier|No\s+introductory\s+notes\s+or\s+chatter\?",
        text,
        re.IGNORECASE,
    ):
        issues.append("cot_leak")

    # 2b. Dialogue switched to dashes where the source puts its dialogue in quotation marks
    if greek_target and source_text:
        dash_line = r"(?m)^\s*[—–]\s?\S"
        src_quoted = len(re.findall(r'(?m)^\s*["“«]', source_text))
        extra_dashes = len(re.findall(dash_line, text)) - len(re.findall(dash_line, source_text))
        out_quoted = len(re.findall(r"(?m)^\s*«", text))
        if src_quoted >= 3 and extra_dashes >= 3 and out_quoted < src_quoted / 2:
            issues.append(f"dialogue_dashes({extra_dashes})")

    # 3. Missing page markers check
    if expected_pages and len(expected_pages) >= 2:
        found_pages = {int(x) for x in re.findall(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text)}
        missing = [p for p in expected_pages if p not in found_pages]
        if missing:
            issues.append(f"missing_pages({missing})")

    # 4. Truncation check (severe length drop or mid-word cutoff)
    clean_src = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", source_text or "").strip()
    clean_out = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", text).strip()
    # dot leaders, rules and padding are not text: losing them is no truncation
    src_len, out_len = (len(re.sub(r"([^\w])\1{2,}", r"\1", t)) for t in (clean_src, clean_out))
    if src_len >= 400:
        ratio = out_len / max(1, src_len)
        if ratio < 0.48:
            issues.append(f"truncated(ratio={ratio:.2f})")
        elif (
            ratio < 0.85
            and clean_src[-1] in '.!?»"”…):;'
            and clean_out
            and clean_out[-1] not in '.!?»"”…):;—-*'
            and bool(_GREEK_CHAR_RE.search(clean_out[-1]))
        ):
            issues.append(f"truncated_midword(ratio={ratio:.2f})")

    # 5. Untranslated English passages check
    clean_out_words = [w for w in clean_out.split() if w.strip()]
    if greek_target and len(clean_out_words) >= 15:
        greek_chars = len(_GREEK_CHAR_RE.findall(clean_out))
        latin_chars = len(_LATIN_LETTER_RE.findall(clean_out))
        if latin_chars > greek_chars and greek_chars < 50:
            issues.append(f"untranslated_english(greek={greek_chars},latin={latin_chars})")
        max_consec_latin = 0
        cur_consec_latin = 0
        for w in clean_out_words:
            if re.match(r"^[A-Za-z]+[.,;:!?\"'«»—–-]?$", w) and not _SCI_UNIT_RE.match(w):
                cur_consec_latin += 1
                if cur_consec_latin > max_consec_latin:
                    max_consec_latin = cur_consec_latin
            else:
                cur_consec_latin = 0
        if max_consec_latin >= 12:
            issues.append(f"untranslated_passage(max_consec_latin={max_consec_latin})")

    return issues


def _extract_clean_tail_context(text: str, max_chars: int = 240) -> str:
    """
    Extracts the last 1-2 complete sentences from the end of a preceding page/chunk
    without ever slicing mid-word or mid-sentence.
    """
    if not text:
        return ""
    stripped = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", text).strip()
    paras = [p.strip() for p in stripped.split("\n\n") if p.strip()]
    if not paras:
        return ""
    last_para = paras[-1]
    if len(last_para) <= max_chars:
        return last_para
    sentences = [
        s.strip()
        for s in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", last_para)
        if s.strip()
    ]
    if len(sentences) >= 2:
        tail = sentences[-1]
        if len(sentences[-2]) + 1 + len(tail) <= max_chars:
            tail = f"{sentences[-2]} {tail}"
        if len(tail) <= max_chars + 80:
            return tail
    # Fallback: take trailing words up to max_chars on a clean word boundary
    words = last_para.split()
    acc: list[str] = []
    acc_len = 0
    for w in reversed(words):
        if acc and acc_len + len(w) + 1 > max_chars:
            break
        acc.append(w)
        acc_len += len(w) + 1
    return " ".join(reversed(acc))


def _norm_dedup_text(s: str) -> str:
    """Normalizes prose for fuzzy boundary-duplication comparison."""
    s = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", s or "")
    s = re.sub(r"[^\w\sΆ-ώ\u0370-\u03ff\u1f00-\u1fff]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _is_near_duplicate_segment(seg_a: str, seg_b: str) -> bool:
    """Returns True if two substantial prose segments (>= 35 chars, >= 6 words) are duplicates or close paraphrases."""
    na = _norm_dedup_text(seg_a)
    nb = _norm_dedup_text(seg_b)
    if len(na) < 35 or len(nb) < 35:
        return False
    wa = na.split()
    wb = nb.split()
    if len(wa) < 6 or len(wb) < 6:
        return False
    if na == nb or na in nb or nb in na:
        return True
    len_ratio = len(na) / max(1, len(nb))
    if not (0.50 <= len_ratio <= 2.0):
        return False
    if SequenceMatcher(None, na, nb).ratio() >= 0.72:
        return True
    set_a, set_b = set(wa), set(wb)
    overlap = len(set_a & set_b) / max(1, min(len(set_a), len(set_b)))
    if overlap >= 0.78:
        return True
    return False


def _prose_paragraphs(text: str) -> list[str]:
    """Paragraphs without page markers."""
    body = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "\n\n", text or "")
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def _deduplicate_batch_boundary(
    prev_text: str,
    curr_text: str,
    expected_first_page: Optional[int] = None,
    source_prev: str = "",
    source_curr: str = "",
) -> str:
    """
    Eliminates chunk/batch boundary duplications deterministically:
    1. For paginated batches, strips any leaked preamble or echoed previous-batch context
       emitted BEFORE the first expected '=== PAGE K ===' marker.
    2. Strips up to 3 leading paragraphs (or a duplicated leading sentence) of curr_text
       when they duplicate or closely paraphrase the trailing paragraphs/sentences of prev_text.

    With ``source_prev``/``source_curr`` (what the model was given) only echoes are removed, never text the book
    really repeats (contract clauses, refrains, similar list items): an echo is either an exact repeat that the source
    does not have, or makes the output longer than its source.
    """
    if not curr_text or not curr_text.strip():
        return curr_text or ""

    res = curr_text.strip()

    # 1. Strip anything leaked before the first expected === PAGE K === marker
    leading_marker = ""
    if expected_first_page is not None:
        m = re.search(rf"={{3,}}\s*PAGE\s+{expected_first_page}\s*={{3,}}", res)
        if m:
            if m.start() > 0:
                leaked_prefix = res[:m.start()].strip()
                if leaked_prefix:
                    logger.info(
                        f"Stripped {len(leaked_prefix)} chars of pre-marker boundary leak before === PAGE {expected_first_page} ==="
                    )
                res = res[m.start():].lstrip()
            leading_marker = m.group(0)
            body = res[len(leading_marker):].lstrip()
        else:
            body = res
    else:
        # Check if curr_text starts with a generic page marker
        m_any = re.match(r"^(={3,}\s*PAGE\s+\d+\s*={3,})\s*", res)
        if m_any:
            leading_marker = m_any.group(1)
            body = res[m_any.end():].lstrip()
        else:
            body = res

    if not prev_text or not prev_text.strip() or not body:
        return f"{leading_marker}\n\n{body}".strip() if leading_marker else body

    prev_clean = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", prev_text).strip()
    prev_paras = [p.strip() for p in prev_clean.split("\n\n") if p.strip()]
    prev_tail_paras = prev_paras[-3:]
    prev_tail_joined = " ".join(prev_tail_paras)

    curr_paras = [p.strip() for p in body.split("\n\n") if p.strip()]

    src_paras = _prose_paragraphs(source_curr)
    extra_paras = len(_prose_paragraphs(body)) - len(src_paras)
    source_repeats = False
    if src_paras and source_prev:
        src_tail = _prose_paragraphs(source_prev)[-3:]
        first_src = _norm_dedup_text(src_paras[0])
        sentence_end = r"(?<=[.!?;…])\s+"
        source_repeats = (
            any(_is_near_duplicate_segment(src_paras[0], pp) for pp in src_tail)
            or (len(first_src) >= 40 and first_src in _norm_dedup_text(" ".join(src_tail)))
            or (bool(src_tail) and _is_near_duplicate_segment(
                re.split(sentence_end, src_paras[0])[0], re.split(sentence_end, src_tail[-1])[-1]))
        )

    dropped = 0
    while curr_paras and dropped < 3:
        first_p = curr_paras[0]
        # Never strip a page marker or scene break
        if re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", first_p) or first_p in ("* * *", "---"):
            break
        is_dup = any(_is_near_duplicate_segment(first_p, pp) for pp in prev_tail_paras)
        if not is_dup and len(_norm_dedup_text(first_p)) >= 40:
            # Also catch when Gemini merged/split the echoed tail across two paragraphs
            norm_first = _norm_dedup_text(first_p)
            norm_prev_tail = _norm_dedup_text(prev_tail_joined)
            if norm_first in norm_prev_tail:
                is_dup = True
        if is_dup and src_paras:
            norm_p = _norm_dedup_text(first_p)
            exact = len(norm_p) >= 35 and f" {norm_p} " in f" {_norm_dedup_text(prev_tail_joined)} "
            is_dup = (exact and dropped < extra_paras) if source_repeats else (exact or dropped < extra_paras)
        if is_dup:
            logger.info(f"Deduplicated repeated boundary paragraph ({len(first_p)} chars)")
            curr_paras.pop(0)
            dropped += 1
        else:
            break

    # Check if the first sentence of the first remaining paragraph duplicates the last sentence of prev_text
    if curr_paras and prev_tail_paras:
        first_p = curr_paras[0]
        if not re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", first_p):
            prev_sents = [
                s.strip()
                for s in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", prev_tail_paras[-1])
                if s.strip()
            ]
            curr_sents = [
                s.strip()
                for s in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", first_p)
                if s.strip()
            ]
            is_echo = bool(prev_sents) and len(curr_sents) >= 2 and _is_near_duplicate_segment(curr_sents[0], prev_sents[-1])
            if is_echo and src_paras:
                is_echo = not source_repeats and _norm_dedup_text(curr_sents[0]) == _norm_dedup_text(prev_sents[-1])
            if is_echo:
                logger.info(f"Deduplicated repeated boundary leading sentence ({len(curr_sents[0])} chars)")
                curr_paras[0] = " ".join(curr_sents[1:]).strip()

    dedup_body = "\n\n".join(p for p in curr_paras if p).strip()
    if leading_marker:
        return f"{leading_marker}\n\n{dedup_body}".strip() if dedup_body else leading_marker
    return dedup_body


def _split_text_in_half_by_paragraphs(text: str) -> Optional[tuple[str, str]]:
    """
    Splits a single page/chunk cleanly into two balanced halves along paragraph (\n\n)
    or sentence boundaries for recursive safety/truncation recovery.
    Returns None if the text cannot be meaningfully split further.
    """
    s = (text or "").strip()
    if len(s) < 80:
        return None
    paras = [p.strip() for p in s.split("\n\n") if p.strip()]
    if len(paras) >= 2:
        total_len = sum(len(p) for p in paras)
        acc = 0
        split_idx = 1
        for i, p in enumerate(paras[:-1], 1):
            acc += len(p)
            split_idx = i
            if acc >= total_len / 2:
                break
        left = "\n\n".join(paras[:split_idx]).strip()
        right = "\n\n".join(paras[split_idx:]).strip()
        if left and right:
            return left, right
    # Single large paragraph: split on sentence boundary
    sents = [
        x.strip()
        for x in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", s)
        if x.strip()
    ]
    if len(sents) >= 2:
        mid = len(sents) // 2
        left = " ".join(sents[:mid]).strip()
        right = " ".join(sents[mid:]).strip()
        if left and right:
            return left, right
    return None


_COMMON_CAP_STOPWORDS = frozenset({
    "The", "This", "That", "These", "Those", "There", "Their", "They", "Then", "Than",
    "When", "Where", "What", "Which", "While", "Who", "Whom", "Whose", "Why", "How",
    "With", "Without", "Within", "From", "Into", "Onto", "Over", "Under", "After", "Before",
    "About", "Above", "Across", "Against", "Along", "Among", "Around", "Because", "Between",
    "Could", "Would", "Should", "Might", "Must", "Have", "Just", "Like", "Only", "Some",
    "Even", "Ever", "Every", "More", "Most", "Much", "Many", "Other", "Such", "Still",
    "Here", "Once", "Well", "Back", "Down", "Away", "Again", "Never", "Always", "Maybe",
    "Nothing", "Something", "Anything", "Everything", "Someone", "Anyone", "Everyone",
    "Chapter", "Part", "Book", "Page", "PAGE", "Prologue", "Epilogue", "Notes", "References",
    "Αλλά", "Όμως", "Ενώ", "Όταν", "Γιατί", "Αυτό", "Αυτή", "Αυτός", "Αυτά", "Αυτοί",
    "Εκεί", "Εδώ", "Μετά", "Πριν", "Πάνω", "Κάτω", "Μόνο", "Τώρα", "Τότε", "Ίσως",
    "Κάθε", "Όλα", "Όλοι", "Όλες", "Ποτέ", "Πάντα", "Κάτι", "Τίποτα", "Καθώς", "Όπως",
    "Επειδή", "Μέσα", "Έξω", "Πέρα", "Χωρίς", "Κεφάλαιο", "Μέρος", "Σελίδα",
})


def _build_stratified_book_sample(text: str, max_total_chars: int = 32000) -> str:
    """
    Builds a representative whole-book sample for Entity Dossier extraction by:
    1. Scanning the ENTIRE book for recurring capitalized names / multi-word proper nouns
       (catching characters, ships, drones, species introduced mid- or late-book).
    2. Taking up to 9 evenly spaced narrative slices spanning 0%..95% of the full text
       aligned on paragraph/newline boundaries.
    """
    if not text:
        return ""
    if len(text) <= max_total_chars:
        return text

    # 1. Fast whole-book recurring capitalized proper-noun scan
    cleaned_for_scan = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "\n", text)
    # Capture 1-3 word capitalized phrases (Latin or Greek)
    raw_terms = re.findall(
        r"\b(?:[A-Z][a-zA-Z'\-]{2,}(?:\s+[A-Z][a-zA-Z'\-]{2,}){0,2}|[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]{2,}(?:\s+[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]{2,}){0,2})\b",
        cleaned_for_scan,
    )
    counts: Counter = Counter()
    for term in raw_terms:
        if term in _COMMON_CAP_STOPWORDS:
            continue
        parts = term.split()
        if all(p in _COMMON_CAP_STOPWORDS for p in parts):
            continue
        if len(parts) > 1 and parts[0] in _COMMON_CAP_STOPWORDS:
            term = " ".join(parts[1:])
            if not term or term in _COMMON_CAP_STOPWORDS:
                continue
        counts[term] += 1

    top_entities = [f"{term} ({cnt}x)" for term, cnt in counts.most_common(75) if cnt >= 3]
    freq_header = ""
    if top_entities:
        freq_header = (
            "--- ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΑ ΟΝΟΜΑΤΑ & ΟΡΟΙ ΣΕ ΟΛΟ ΤΟ ΒΙΒΛΙΟ (FREQUENCY SCAN) ---\n"
            + ", ".join(top_entities)
            + "\n\n"
        )

    # 2. Stratified excerpts across 0%..95% of the book
    num_slices = 9
    budget = max(8000, max_total_chars - len(freq_header))
    slice_len = budget // num_slices
    n = len(text)
    excerpts: list[str] = []
    for i in range(num_slices):
        frac = i / max(1, num_slices - 1) * 0.92
        start = int(n * frac)
        if start > 0:
            nl = text.find("\n", start, min(n, start + 400))
            if nl != -1:
                start = nl + 1
        end = min(n, start + slice_len)
        if end < n:
            nl_end = text.rfind("\n", start + slice_len // 2, end)
            if nl_end != -1:
                end = nl_end
        chunk = text[start:end].strip()
        if chunk:
            pct = int(round(frac * 100))
            excerpts.append(f"--- ΔΕΙΓΜΑ ΒΙΒΛΙΟΥ ({pct}%) ---\n{chunk}")

    return freq_header + "\n\n".join(excerpts)


def _parse_pages_dict(text: str) -> dict[int, str]:
    """Parses text containing '=== PAGE X ===' into a {page_num: text} mapping."""
    page_dict: dict[int, str] = {}
    if not text:
        return page_dict
    parts = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    curr_page = 0
    for part in parts:
        p_strip = part.strip()
        if not p_strip:
            continue
        m = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", p_strip)
        if m:
            curr_page = int(m.group(1))
        elif curr_page > 0:
            page_dict[curr_page] = p_strip
    return page_dict


async def _extract_entity_dossier(
    sample_text: str,
    api_key: str,
    session: Optional[aiohttp.ClientSession] = None,
    target_lang: str = "greek",
    mode: str = "translation",
) -> str:
    """
    Extracts a whole-book register using stratified sampling across the entire document, so entities introduced
    mid-book keep one rendering and gender. mode='translation' adds a style sheet (narrative tense/person, register,
    forms of address); mode='pronunciation' builds a fixed phonetic register for audiobook narration.
    """
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        return "- Keeton -> Κίτον (αρσενικό: ο Κίτον)\n- Theseus -> Θησέας (αρσενικό: ο Θησέας)\n- Rorschach -> Ρόρσαχ (ουδέτερο: το Ρόρσαχ)"

    prompt = build_dossier_prompt(target_lang=target_lang, mode=mode)
    try:
        sample = _build_stratified_book_sample(sample_text, max_total_chars=32000)
        dossier = await _call_gemini_api(sample, api_key, prompt, session=session, temperature=0.1,
                                         cache_gate=lambda o: bool(o and len(o.strip()) > 10))
        if dossier and len(dossier.strip()) > 10:
            logger.info(f"Generated whole-book {mode} dossier ({len(dossier)} chars)")
            return dossier.strip()
    except Exception as ex:
        logger.warning(f"Entity dossier extraction skipped: {ex}")
    return ""


async def _get_available_models(api_key: str, session: aiohttp.ClientSession) -> list[str]:
    """Queries Gemini ModelService to get supported text-generation models for this API key."""
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        return ["gemini-flash-latest", "gemini-2.5-flash-lite"]

    global _CACHED_AVAILABLE_MODELS, _CACHED_API_KEY_HASH
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    # each key is listed once: requests take the pool's keys in turn, so a single cached list would be re-read
    # on every request
    known = _MODELS_BY_KEY.get(key_hash)
    if known:
        _CACHED_AVAILABLE_MODELS, _CACHED_API_KEY_HASH = known, key_hash
        return known

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": api_key}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                models = data.get("models", [])
                valid_models = []
                for m in models:
                    name = m.get("name", "").replace("models/", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" not in methods:
                        continue
                    if any(p in name.lower() for p in EXCLUDE_PATTERNS):
                        continue
                    valid_models.append(name)

                logger.info(f"Discovered {len(valid_models)} valid text Gemini models: {valid_models}")
                if valid_models:
                    _MODELS_BY_KEY[key_hash] = valid_models
                _CACHED_AVAILABLE_MODELS, _CACHED_API_KEY_HASH = valid_models, key_hash
                return valid_models
            else:
                err = await resp.text()
                logger.warning(f"Could not list models ({resp.status}): {err}")
    except Exception as e:
        logger.warning(f"Error querying Gemini ModelService: {e}")
    return []


async def polish_text_with_gemini(
    text: str,
    api_key: Optional[str] = None,
    style: str = "formal",
    original_text: Optional[str] = None,
    job_id: Optional[str] = None,
    use_source_anchoring: bool = True,
    progress_callback: Optional[Callable[[int, int], Any]] = None,
    target_lang: str = "greek",
    quota_behavior: str = "wait",
    system_prompt_override: Optional[str] = None,
    temperature_override: Optional[float] = None,
) -> str:
    """
    Polishes and proofreads translated text using Google's Gemini API.
    ``system_prompt_override`` / ``temperature_override`` let callers reuse the whole batching, source-anchoring,
    dossier, checkpoint and quality-gate machinery with a different task (e.g. the maximum-quality revision pass).
    Supports multi-page smart batching, bilingual source-anchored verification,
    character consistency dossier, rolling narrative context, and disk checkpointing.
    """
    if not text or not str(text).strip():
        return text or ""

    is_greek_target = (target_lang or "greek").strip().lower() in ("greek", "el")

    def _postprocess(s: str) -> str:
        if not is_greek_target:
            return s
        from backend.typography import format_greek_typography
        from backend.glossary import apply_glossary
        return format_greek_typography(apply_glossary(s, "greek", style=style, translated=True))

    from backend.gemini_key_pool import resolve_gemini_api_key
    key = resolve_gemini_api_key(api_key)
    if not key:
        if quota_behavior == "fallback":
            logger.info(f"[{job_id or 'direct'}] No Gemini API key provided and quota_behavior='fallback' -> Applying free rule-based typography and glossary polish.")
            return _postprocess(text)
        raise ValueError("Missing Gemini API Key. Please provide a key in settings or select free models (fallback).")

    base_system_instruction = system_prompt_override or build_polish_prompt(style, target_lang)
    sem = asyncio.Semaphore(5)
    client_timeout = aiohttp.ClientTimeout(total=90)

    # Disk Checkpoint setup (with safe job_id validation and style/input fingerprint)
    checkpoint_file: Optional[Path] = None
    prompt_sig = hashlib.sha256(base_system_instruction.encode("utf-8")).hexdigest()[:8]  # not work of older prompts
    input_sig = hashlib.sha256(
        f"{PROMPT_VERSION}::{prompt_sig}::{style}::{target_lang}::{text[:2000]}::{len(text)}".encode("utf-8")
    ).hexdigest()[:16]
    narration = style in ("audiobook", "poetry")  # those prompts remove page markers on purpose
    input_full = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]  # an edit past the first 2,000 chars
    checkpoint_data: dict[str, Any] = {"sig": input_sig, "full": input_full, "batches": {}, "chunks": {}}
    if job_id and "/" not in job_id and "\\" not in job_id and ".." not in job_id:
        out_dir = Path(__file__).resolve().parent.parent / "temp" / "outputs" / job_id
        if out_dir.exists():
            checkpoint_file = out_dir / ".polish_checkpoint.json"
            if checkpoint_file.is_file():
                try:
                    loaded = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                    # Reuse checkpoint if no sig (legacy/tests) or matching sig
                    if (not loaded.get("sig") or loaded.get("sig") == input_sig) and loaded.get("full", input_full) == input_full:
                        if isinstance(loaded.get("batches"), dict):
                            checkpoint_data["batches"] = loaded["batches"]
                        if isinstance(loaded.get("chunks"), dict):
                            checkpoint_data["chunks"] = loaded["chunks"]
                        if isinstance(loaded.get("entity_dossier"), str):
                            checkpoint_data["entity_dossier"] = loaded["entity_dossier"]
                        logger.info(f"Loaded existing polish checkpoint with {len(checkpoint_data['batches'])} batches / {len(checkpoint_data['chunks'])} chunks")
                except Exception as ex:
                    logger.warning(f"Could not load polish checkpoint: {ex}")

    def _save_checkpoint():
        if checkpoint_file:
            with _CHECKPOINT_LOCK:
                tmp_cp = checkpoint_file.with_suffix(".json.tmp")
                try:
                    tmp_cp.write_text(json.dumps(checkpoint_data, ensure_ascii=False), encoding="utf-8")
                    os.replace(tmp_cp, checkpoint_file)
                except Exception as ex:
                    logger.warning(f"Could not write polish checkpoint: {ex}")
                    try:
                        tmp_cp.unlink(missing_ok=True)
                    except Exception:
                        pass

    async def _run_progress(done_count: int, total_count: int) -> None:
        if not progress_callback:
            return
        try:
            res = progress_callback(done_count, total_count)
            if asyncio.iscoroutine(res):
                await res
        except Exception as ex:
            logger.warning(f"Progress callback error: {ex}")

    # Auto-disable redundant Source-Anchored Verification if original_text is identical to draft text
    if original_text and original_text.strip() == (text or "").strip():
        use_source_anchoring = False
        original_text = None

    # Parse original text pages for source anchoring if provided
    orig_pages: dict[int, str] = {}
    if original_text and use_source_anchoring:
        orig_pages = _parse_pages_dict(original_text)

    # If document has multiple pages marked by dividers, group into smart multi-page batches
    page_sections = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    connector = aiohttp.TCPConnector(limit=12, ttl_dns_cache=300)
    async with aiohttp.ClientSession(timeout=client_timeout, connector=connector) as session:
        # Extract entity consistency dossier for long documents / literature if not already cached
        entity_dossier = checkpoint_data.get("entity_dossier", "")
        # Literature: names + style sheet. Greek audiobook/poetry scripts: fixed pronunciation register, so a foreign
        # name is spoken identically in every batch.
        dossier_mode = "pronunciation" if style in ("audiobook", "poetry") else "translation"
        wants_dossier = style == "literature" or (dossier_mode == "pronunciation" and is_greek_target
                                                  and bool(re.search(r"[A-Za-z]{3,}", text)))
        if wants_dossier and not entity_dossier and (len(page_sections) > 10 or len(text) > 18000):
            sample_src = original_text or text
            entity_dossier = await _extract_entity_dossier(sample_src, key, session=session,
                                                           target_lang=target_lang, mode=dossier_mode)
            if entity_dossier:
                checkpoint_data["entity_dossier"] = entity_dossier
                _save_checkpoint()

        system_instruction = base_system_instruction
        if entity_dossier:
            system_instruction += dossier_header(dossier_mode, target_lang) + f"{entity_dossier}\n"

        # Inject contextually-relevant user glossary rules (style-aware: excludes IT/DevOps terms for literature)
        from backend.glossary import load_glossary
        glossary_items = load_glossary(style=style)
        if glossary_items and not is_greek_target:
            if not narration:
                system_instruction += english_glossary_rules(glossary_items, original_text or "")
        elif glossary_items:
            full_context_lower = (text + "\n" + (original_text or "")).lower()
            # Prioritize terms that actually appear in the source or draft text
            matched_terms = [
                (k, v) for k, v in glossary_items.items()
                if k.lower() in full_context_lower or v.lower() in full_context_lower
            ]
            selected_terms = matched_terms[:50]
            # If few specific terms matched, fill up to 30 with standard terms
            if len(selected_terms) < 20:
                for k, v in glossary_items.items():
                    if (k, v) not in selected_terms:
                        selected_terms.append((k, v))
                    if len(selected_terms) >= 30:
                        break

            glossary_lines = "\n".join(f"- {k} -> {v}" for k, v in selected_terms)
            system_instruction += (
                "\n\n--- ΓΛΩΣΣΑΡΙΟ ΚΑΙ ΟΡΟΛΟΓΙΑ ΧΡΗΣΤΗ (GLOSSARY RULES) ---\n"
                "Τήρησε αυστηρά τις ακόλουθες καθιερωμένες αποδόσεις όρων:\n"
                f"{glossary_lines}\n"
            )

        target_temp = temperature_override if temperature_override is not None else STYLE_TEMPERATURES.get(style, 0.25)

        if len(page_sections) > 1:
            # Pair page markers with their content
            pages = []
            curr_marker = ""
            for part in page_sections:
                p_strip = part.strip()
                if not p_strip:
                    continue
                if re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", p_strip):
                    curr_marker = p_strip
                else:
                    pages.append((curr_marker, p_strip))

            # Smart Multi-Page Batching: group ~3 pages (or ~5,500 chars) per Gemini call
            # to stay well inside token & Greek attention limits without truncation
            batches = []
            curr_b = []
            curr_chars = 0
            MAX_BATCH_CHARS = 5500
            MAX_BATCH_PAGES = 3

            for m, c in pages:
                item_len = len(m) + len(c) + 4
                if curr_b and (curr_chars + item_len > MAX_BATCH_CHARS or len(curr_b) >= MAX_BATCH_PAGES):
                    batches.append(curr_b)
                    curr_b = [(m, c)]
                    curr_chars = item_len
                else:
                    curr_b.append((m, c))
                    curr_chars += item_len
            if curr_b:
                batches.append(curr_b)

            if not batches:
                return _postprocess(text)

            total_batches = len(batches)
            polished_batches = ["" for _ in batches]
            batch_failed = [False for _ in batches]
            completed = 0
            first_error: Optional[Exception] = None

            # Pre-fill batches already present in checkpoint
            cached_batches = checkpoint_data.get("batches", {})
            for b_idx in range(total_batches):
                b_str = str(b_idx)
                if b_str in cached_batches and isinstance(cached_batches[b_str], str) and cached_batches[b_str].strip():
                    polished_batches[b_idx] = cached_batches[b_str]
                    completed += 1

            if completed > 0:
                await _run_progress(completed, total_batches)

            async def _polish_items_reliably(
                batch_items: list[tuple[str, str]],
                prev_snippet: str = "",
                depth: int = 0,
            ) -> tuple[str, bool]:
                """
                Polishes a list of (page_marker, page_text) items with:
                - Clean XML-delimited read-only previous context (never '[... ...]')
                - Recursive bisection (multi-page -> single-page -> paragraph halves) on
                  MAX_TOKENS, safety/content blocks, or timeouts so a single offending
                  paragraph NEVER causes a 3-page silent fallback to raw MT.
                - Boundary deduplication when joining recursively split halves.
                Returns (text, any_ai_succeeded).
                """
                draft_batch_text = "\n\n".join(
                    f"{m}\n\n{c}" if m else c for m, c in batch_items
                )
                expected_page_nums = []
                source_batch_parts = []
                for m, _ in batch_items:
                    pm = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", m)
                    if pm:
                        pn = int(pm.group(1))
                        expected_page_nums.append(pn)
                        if orig_pages and use_source_anchoring and pn in orig_pages:
                            source_batch_parts.append(f"=== PAGE {pn} ===\n{orig_pages[pn]}")

                content_components = []
                if prev_snippet:
                    content_components.append(
                        f"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n{prev_snippet}\n</PREVIOUS_CONTEXT_DO_NOT_REPEAT>"
                    )
                if source_batch_parts:
                    orig_source_block = "\n\n".join(source_batch_parts)
                    content_components.append(
                        f"<SOURCE_REFERENCE>\n{orig_source_block}\n</SOURCE_REFERENCE>"
                    )
                    content_components.append(
                        f"<DRAFT_TO_POLISH>\n{draft_batch_text}\n</DRAFT_TO_POLISH>"
                    )
                else:
                    content_components.append(
                        f"<TEXT_TO_POLISH>\n{draft_batch_text}\n</TEXT_TO_POLISH>"
                    )

                prompt_content = "\n\n".join(content_components)
                batch_instruction = system_instruction
                if prev_snippet:
                    batch_instruction += _continuity_rule(is_greek_target)
                if source_batch_parts and not is_greek_target:
                    batch_instruction += (
                        "\n\n--- BILINGUAL CHECK ---\n"
                        "You receive the original (<SOURCE_REFERENCE>) and the English translation (<DRAFT_TO_POLISH>). "
                        "Use the original to correct misreadings, calques or omissions of the draft. Return only the "
                        "corrected English text (no XML tags), with every page marker === PAGE X === unchanged."
                    )
                elif source_batch_parts:
                    batch_instruction += (
                        "\n\n--- ΟΔΗΓΙΑ ΔΙΓΛΩΣΣΗΣ ΕΠΑΛΗΘΕΥΣΗΣ ---\n"
                        "Σου παρέχεται το Πρωτότυπο Κείμενο Αναφοράς (<SOURCE_REFERENCE>) καθώς και το Προσχέδιο Ελληνικής Μετάφρασης (<DRAFT_TO_POLISH>). "
                        "Χρησιμοποίησε το πρωτότυπο κείμενο για να διορθώσεις τυχόν παρανοήσεις, αγγλισμούς ή παραλείψεις του προσχεδίου. "
                        "Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το τελικό διορθωμένο ελληνικό κείμενο (χωρίς ετικέτες XML), διατηρώντας ΑΠΑΡΑΛΛΑΧΤΟΥΣ όλους τους δείκτες σελίδων === PAGE X ===."
                    )

                async def _bisect_and_recover(reason_label: str) -> Optional[tuple[str, bool]]:
                    if len(batch_items) > 1 and depth < 3:
                        mid = len(batch_items) // 2
                        logger.warning(f"Batch hit {reason_label}; splitting {len(batch_items)} pages into {mid}+{len(batch_items)-mid}...")
                        left_txt, left_ok = "", False
                        right_txt, right_ok = "", False
                        left_err: Optional[Exception] = None
                        right_err: Optional[Exception] = None
                        try:
                            left_txt, left_ok = await _polish_items_reliably(batch_items[:mid], prev_snippet, depth + 1)
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_l:
                            left_err = ex_l
                            left_txt = "\n\n".join(f"{m}\n\n{c}" if m else c for m, c in batch_items[:mid])
                        right_prev = _extract_clean_tail_context(left_txt if left_ok else batch_items[mid - 1][1])
                        try:
                            right_txt, right_ok = await _polish_items_reliably(batch_items[mid:], right_prev, depth + 1)
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_r:
                            right_err = ex_r
                            right_txt = "\n\n".join(f"{m}\n\n{c}" if m else c for m, c in batch_items[mid:])
                        if not left_txt.strip() and not right_txt.strip():
                            raise (left_err or right_err or RuntimeError(reason_label))
                        right_first_pg = None
                        pm_r = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", batch_items[mid][0])
                        if pm_r:
                            right_first_pg = int(pm_r.group(1))
                        right_clean = _deduplicate_batch_boundary(
                            left_txt, right_txt, expected_first_page=right_first_pg,
                            source_prev="\n\n".join(c for _, c in batch_items[:mid]),
                            source_curr="\n\n".join(c for _, c in batch_items[mid:]),
                        )
                        return f"{left_txt.strip()}\n\n{right_clean.strip()}".strip(), True

                    # Single-page paragraph bisection (isolates a single safety-blocked or oversized paragraph)
                    if len(batch_items) == 1 and depth < 4:
                        only_marker, only_content = batch_items[0]
                        halves = _split_text_in_half_by_paragraphs(only_content)
                        if halves:
                            l_para, r_para = halves
                            logger.warning(f"Single page hit {reason_label}; bisecting by paragraphs (depth={depth + 1})...")
                            left_txt, left_ok = "", False
                            right_txt, right_ok = "", False
                            left_err = None
                            right_err = None
                            try:
                                left_txt, left_ok = await _polish_items_reliably([(only_marker, l_para)], prev_snippet, depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_l:
                                left_err = ex_l
                                left_txt = f"{only_marker}\n\n{l_para}" if only_marker else l_para
                            right_prev = _extract_clean_tail_context(left_txt if left_ok else l_para)
                            try:
                                right_txt, right_ok = await _polish_items_reliably([("", r_para)], right_prev, depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_r:
                                right_err = ex_r
                                right_txt = r_para
                            if not left_ok and not right_ok:
                                raise (left_err or right_err or RuntimeError(reason_label))
                            right_clean = _deduplicate_batch_boundary(
                                left_txt, right_txt, expected_first_page=None, source_prev=l_para, source_curr=r_para)
                            return f"{left_txt.strip()}\n\n{right_clean.strip()}".strip(), True
                    return None

                meta: dict[str, Any] = {}
                try:
                    polished = await _call_gemini_api(
                        prompt_content.strip(),
                        key,
                        batch_instruction,
                        session=session,
                        temperature=target_temp,
                        meta_out=meta,
                        cache_gate=lambda out: not detect_greek_output_issues(
                            out, source_text=draft_batch_text, greek_target=is_greek_target)
                        and not _answer_problem(out, draft_batch_text, is_greek_target),
                    )
                except PermissionError:
                    raise
                except (_TruncatedOutputError, _ContentBlockedError) as err:
                    recovered = await _bisect_and_recover(type(err).__name__)
                    if recovered is not None:
                        return recovered
                    raise
                except Exception as err:
                    err_low = str(err).lower()
                    is_splittable = any(k in err_low for k in ("timed out", "block", "safety", "prohibited", "empty", "max_tokens"))
                    if is_splittable:
                        recovered = await _bisect_and_recover(str(err)[:80])
                        if recovered is not None:
                            return recovered
                    raise

                # Strip any leaked preamble emitted before the batch's first expected PAGE marker
                if expected_page_nums:
                    polished = _deduplicate_batch_boundary("", polished, expected_first_page=expected_page_nums[0])

                # Quality gate: detect mixed-script corruption, missing page markers, or truncation
                issues = detect_greek_output_issues(
                    polished,
                    source_text=draft_batch_text,
                    expected_pages=expected_page_nums if len(expected_page_nums) >= 2 else None,
                    greek_target=is_greek_target,
                )
                if issues:
                    logger.warning(f"Polish quality gate flagged issues {issues} (model={meta.get('model')})")
                    needs_split = any(i.startswith(("missing_pages", "truncated")) for i in issues)
                    if needs_split:
                        recovered = await _bisect_and_recover(",".join(issues))
                        if recovered is not None:
                            return recovered
                    bad_model = meta.get("model")
                    if bad_model and not key.startswith(("AQ.Test", "AIzaTest")):
                        try:
                            retry_instruction = batch_instruction + _quality_retry_hint(
                                issues, polished, draft_batch_text, is_greek_target)
                            # Only exclude bad_model if another full (non-lite, non-gemma) model is available
                            other_full_models = [
                                m for m in (_CACHED_AVAILABLE_MODELS or [])
                                if m != bad_model and not m.startswith("gemma") and "lite" not in m.lower()
                            ]
                            excl = {bad_model} if other_full_models else None
                            retry_meta: dict[str, Any] = {}
                            retried = await _call_gemini_api(
                                prompt_content.strip(),
                                key,
                                retry_instruction,
                                session=session,
                                temperature=max(0.1, target_temp - 0.1),
                                exclude_models=excl,
                                bypass_cache=True,
                                meta_out=retry_meta,
                            )
                            if expected_page_nums:
                                retried = _deduplicate_batch_boundary("", retried, expected_first_page=expected_page_nums[0])
                            retry_issues = detect_greek_output_issues(
                                retried,
                                source_text=draft_batch_text,
                                expected_pages=expected_page_nums if len(expected_page_nums) >= 2 else None,
                                greek_target=is_greek_target,
                            )
                            if len(retry_issues) < len(issues):
                                logger.info(f"Quality retry succeeded on {retry_meta.get('model')} (issues: {issues} -> {retry_issues})")
                                polished = retried
                        except Exception as rex:
                            logger.debug(f"Quality retry failed: {rex}")
                if not key.startswith(("AQ.Test", "AIzaTest")):
                    problem = _answer_problem(
                        polished, draft_batch_text, is_greek_target,
                        expected_pages=None if narration or len(expected_page_nums) < 2 else expected_page_nums)
                    if problem:
                        if problem.startswith(("missing_pages", "truncated")):
                            recovered = await _bisect_and_recover(problem)
                            if recovered is not None:
                                return recovered
                        raise _BadAnswerError(f"Unusable polish answer: {problem}")
                return polished, True

            async def _polish_batch(b_idx: int, batch_items: list[tuple[str, str]]) -> None:
                nonlocal completed, first_error
                if polished_batches[b_idx]:
                    return  # Already restored from checkpoint

                draft_batch_text = "\n\n".join(
                    f"{m}\n\n{c}" if m else c for m, c in batch_items
                )
                prev_snippet = ""
                if b_idx > 0:
                    prev_draft = batches[b_idx - 1][-1][1]
                    prev_snippet = _extract_clean_tail_context(prev_draft, max_chars=240)

                async with sem:
                    last_ex: Optional[Exception] = None
                    polished_res = ""
                    for retry_round in range(2):
                        try:
                            polished_res, _ = await _polish_items_reliably(batch_items, prev_snippet=prev_snippet)
                            last_ex = None
                            break
                        except (PermissionError, DailyQuotaExhaustedError) as p_or_q:
                            if isinstance(p_or_q, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                                logger.warning(
                                    f"Gemini Daily Quota exhausted during polish (batch {b_idx + 1}/{total_batches}). "
                                    f"quota_behavior='fallback' -> keeping draft text..."
                                )
                                last_ex = p_or_q
                                break
                            raise
                        except Exception as ex:
                            last_ex = ex
                            if retry_round == 0 and any(k in str(ex) for k in ("429", "503", "500", "502", "504", "timed out")):
                                logger.info(f"Batch {b_idx + 1}/{total_batches} transient error, cooling down before retry: {ex}")
                                await asyncio.sleep(_TRANSIENT_RETRY_DELAY)
                                continue
                            break

                    if last_ex is None and polished_res:
                        polished_batches[b_idx] = polished_res
                        checkpoint_data["batches"][str(b_idx)] = polished_res
                        _save_checkpoint()
                    else:
                        if first_error is None:
                            first_error = last_ex
                        batch_failed[b_idx] = True
                        logger.warning(f"Batch {b_idx + 1}/{total_batches} polish failed (keeping original text): {last_ex}")
                        polished_batches[b_idx] = draft_batch_text

                completed += 1
                await _run_progress(completed, total_batches)

            # Process remaining batches
            pending_batches = [(i, b) for i, b in enumerate(batches) if not polished_batches[i]]
            if pending_batches:
                await gather_or_cancel(_polish_batch(i, b) for i, b in pending_batches)

            if (all(batch_failed) or all(not p for p in polished_batches)) and first_error is not None:
                if isinstance(first_error, _BadAnswerError):
                    logger.warning(f"Every polish answer was unusable ({first_error}): the text stays as it was.")
                elif isinstance(first_error, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                    logger.warning(
                        "All batches failed due to DailyQuotaExhaustedError but quota_behavior='fallback'. "
                        "Proceeding with unpolished original text."
                    )
                else:
                    raise first_error

            final_batches = []
            for b_idx, p in enumerate(polished_batches):
                if p and p.strip():
                    curr_txt = p.strip()
                else:
                    curr_txt = "\n\n".join(
                        f"{m}\n\n{c}" if m else c for m, c in batches[b_idx]
                    )
                first_pg = None
                if batches[b_idx]:
                    pm0 = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", batches[b_idx][0][0])
                    if pm0:
                        first_pg = int(pm0.group(1))
                prev_txt = final_batches[-1] if final_batches else ""
                curr_txt = _deduplicate_batch_boundary(
                    prev_txt, curr_txt, expected_first_page=first_pg,
                    source_prev="\n\n".join(c for _, c in batches[b_idx - 1]) if b_idx else "",
                    source_curr="\n\n".join(c for _, c in batches[b_idx]),
                )
                if curr_txt:
                    final_batches.append(curr_txt)

            # Clean up checkpoint on complete success
            if checkpoint_file and checkpoint_file.exists():
                try:
                    checkpoint_file.unlink(missing_ok=True)
                except Exception:
                    pass

            return _postprocess("\n\n".join(final_batches))

        # For un-paginated text (e.g. Audiobook / DOCX), chunk long inputs (~6000 chars) and polish
        if len(text) > 4000:
            from backend.parsers import split_into_chunks
            chunks = split_into_chunks(text, 6000)
            total_chunks = max(1, len(chunks))
            polished_chunks = list(chunks)
            completed = 0
            succeeded = 0
            first_error: Optional[Exception] = None

            cached_chunks = checkpoint_data.get("chunks", {})
            for c_idx in range(total_chunks):
                c_str = str(c_idx)
                if c_str in cached_chunks and cached_chunks[c_str].strip():
                    polished_chunks[c_idx] = cached_chunks[c_str]
                    completed += 1
                    succeeded += 1

            if completed > 0:
                await _run_progress(completed, total_chunks)

            async def _polish_chunk_reliably(c_text: str, prev_snippet: str = "", depth: int = 0) -> tuple[str, bool]:
                if prev_snippet:
                    chunk_content = (
                        f"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n{prev_snippet}\n</PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n\n"
                        f"<TEXT_TO_POLISH>\n{c_text}\n</TEXT_TO_POLISH>"
                    )
                    chunk_instr = system_instruction + _continuity_rule(is_greek_target)
                else:
                    chunk_content = f"<TEXT_TO_POLISH>\n{c_text}\n</TEXT_TO_POLISH>"
                    chunk_instr = system_instruction

                try:
                    res_c = await _call_gemini_api(
                        chunk_content, key, chunk_instr, session=session, temperature=target_temp,
                        cache_gate=lambda out: not detect_greek_output_issues(
                            out, source_text=c_text, greek_target=is_greek_target)
                        and not _answer_problem(out, c_text, is_greek_target),
                    )
                    if not key.startswith(("AQ.Test", "AIzaTest")):
                        problem = _answer_problem(res_c, c_text, is_greek_target)
                        if problem:
                            raise _BadAnswerError(f"Unusable polish answer: {problem}")
                    return res_c, True
                except PermissionError:
                    raise
                except Exception as ex:
                    err_low = str(ex).lower()
                    can_split = isinstance(ex, (_TruncatedOutputError, _ContentBlockedError)) or any(
                        k in err_low for k in ("timed out", "block", "safety", "prohibited", "empty", "max_tokens")
                    ) or (isinstance(ex, _BadAnswerError) and "truncated" in err_low)
                    if can_split and depth < 3:
                        halves = _split_text_in_half_by_paragraphs(c_text)
                        if halves:
                            l_txt, r_txt = halves
                            l_out, l_ok = l_txt, False
                            r_out, r_ok = r_txt, False
                            l_err: Optional[Exception] = None
                            r_err: Optional[Exception] = None
                            try:
                                l_out, l_ok = await _polish_chunk_reliably(l_txt, prev_snippet, depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_l:
                                l_err = ex_l
                            try:
                                r_out, r_ok = await _polish_chunk_reliably(r_txt, _extract_clean_tail_context(l_out if l_ok else l_txt), depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_r:
                                r_err = ex_r
                            if not l_ok and not r_ok:
                                raise (l_err or r_err or ex)
                            r_clean = _deduplicate_batch_boundary(l_out, r_out, source_prev=l_txt, source_curr=r_txt)
                            return f"{l_out.strip()}\n\n{r_clean.strip()}".strip(), True
                    raise

            async def _polish_chunk(c_idx: int, c_text: str) -> None:
                nonlocal completed, succeeded, first_error
                if str(c_idx) in cached_chunks and cached_chunks[str(c_idx)].strip():
                    return

                prev_snippet = _extract_clean_tail_context(chunks[c_idx - 1], max_chars=240) if c_idx > 0 else ""

                async with sem:
                    last_ex: Optional[Exception] = None
                    res_text = ""
                    for retry_round in range(2):
                        try:
                            res_text, _ = await _polish_chunk_reliably(c_text, prev_snippet=prev_snippet)
                            last_ex = None
                            break
                        except (PermissionError, DailyQuotaExhaustedError) as p_or_q:
                            if isinstance(p_or_q, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                                logger.warning(
                                    f"Gemini Daily Quota exhausted during chunk polish ({c_idx + 1}/{total_chunks}). "
                                    f"quota_behavior='fallback' -> keeping draft text..."
                                )
                                last_ex = p_or_q
                                break
                            raise
                        except Exception as ex:
                            last_ex = ex
                            if retry_round == 0 and any(k in str(ex) for k in ("429", "503", "500", "502", "504", "timed out")):
                                await asyncio.sleep(_TRANSIENT_RETRY_DELAY)
                                continue
                            break
                    if last_ex is None and res_text:
                        polished_chunks[c_idx] = res_text
                        checkpoint_data["chunks"][str(c_idx)] = res_text
                        _save_checkpoint()
                        succeeded += 1
                    else:
                        if first_error is None:
                            first_error = last_ex
                        logger.warning(f"Chunk {c_idx + 1}/{total_chunks} polish failed (keeping original chunk): {last_ex}")
                completed += 1
                await _run_progress(completed, total_chunks)

            pending_chunks = [(i, c) for i, c in enumerate(chunks) if str(i) not in cached_chunks]
            if pending_chunks:
                await gather_or_cancel(_polish_chunk(i, c) for i, c in pending_chunks)

            if succeeded == 0 and first_error is not None:
                if isinstance(first_error, _BadAnswerError):
                    logger.warning(f"Every polish answer was unusable ({first_error}): the text stays as it was.")
                elif isinstance(first_error, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                    logger.warning(
                        "All chunks failed due to DailyQuotaExhaustedError but quota_behavior='fallback'. "
                        "Proceeding with unpolished original text."
                    )
                else:
                    raise first_error

            if checkpoint_file and checkpoint_file.exists():
                try:
                    checkpoint_file.unlink(missing_ok=True)
                except Exception:
                    pass

            dedup_chunks: list[str] = []
            for c_idx, p in enumerate(polished_chunks):
                if not p or not p.strip():
                    continue
                prev_c = dedup_chunks[-1] if dedup_chunks else ""
                cleaned_c = _deduplicate_batch_boundary(
                    prev_c, p.strip(), source_prev=chunks[c_idx - 1] if c_idx else "", source_curr=chunks[c_idx])
                if cleaned_c:
                    dedup_chunks.append(cleaned_c)

            return _postprocess("\n\n".join(dedup_chunks))

        single_input = text
        if original_text and use_source_anchoring:
            single_input = (
                f"<SOURCE_REFERENCE>\n{original_text}\n</SOURCE_REFERENCE>\n\n"
                f"<DRAFT_TO_POLISH>\n{text}\n</DRAFT_TO_POLISH>"
            )
        try:
            polished_single = await _call_gemini_api(
                single_input, key, system_instruction, session=session, temperature=target_temp,
                cache_gate=lambda out: not detect_greek_output_issues(out, source_text=text, greek_target=is_greek_target)
                and not _answer_problem(out, text, is_greek_target),
            )
            if not key.startswith(("AQ.Test", "AIzaTest")):
                problem = _answer_problem(polished_single, text, is_greek_target)
                if problem:
                    logger.warning(f"Unusable polish answer ({problem}): the text stays as it was.")
                    polished_single = text
        except DailyQuotaExhaustedError:
            if quota_behavior == "fallback":
                logger.warning(
                    f"[{job_id or 'direct'}] Gemini Daily Quota exhausted on single chunk polish. "
                    f"quota_behavior='fallback' -> keeping draft text..."
                )
                polished_single = text
            else:
                raise
        await _run_progress(1, 1)
        return _postprocess(polished_single)


# Alias for concise invocation
polish_text = polish_text_with_gemini


async def _call_gemini_api(
    content_text: str,
    api_key: str,
    system_prompt: str,
    session: Optional[aiohttp.ClientSession] = None,
    temperature: float = 0.25,
    exclude_models: Optional[set[str]] = None,
    bypass_cache: bool = False,
    meta_out: Optional[dict[str, Any]] = None,
    cache_gate: Optional[Callable[[str], bool]] = None,
    image: Optional[tuple[str, bytes]] = None,
    prefer_models: Optional[list[str]] = None,
) -> str:
    """Invokes Gemini generateContent with cache, full-Flash priority, thought filtering, safety/block detection, and MAX_TOKENS protection.

    ``cache_gate``: optional predicate deciding whether a successful output may be cached. By default only
    outputs passing the Greek translation quality gate are cached, which rejects legitimately short or
    non-Greek outputs (summaries, notes, English text); callers producing those pass their own gate.
    ``image``: (mime type, bytes) sent with the request, such as a scanned page to read. Its answer is the page's own
    text, so it gets only a light cleaning instead of the translation sanitiser.
    ``prefer_models``: models tried before the usual order when the key has them (e.g. Flash-Lite for easy work).
    """
    import base64

    clean_answer = sanitize_ai_output if image is None else (lambda t, source_text="": clean_transcription(t))
    image_hash = hashlib.sha256(image[1]).hexdigest() if image is not None else ""
    cache_source = content_text if image is None else f"{content_text}\n#image:{image_hash}"
    from backend.gemini_key_pool import GeminiKeyPool, GeminiRateLimiter, parse_gemini_error, mask_api_key

    # Resolve active key: use provided key or next available key from the 4-key pool
    attempted_keys: set[str] = set()
    pool_keys = GeminiKeyPool.get_keys()
    initial_key = (api_key or "").strip()
    if not initial_key or (not initial_key.startswith(("AQ.Test", "AIzaTest")) and GeminiKeyPool.is_key_exhausted(initial_key)):
        initial_key = GeminiKeyPool.get_active_key() or initial_key

    # Allow rotation across pool if no key was explicitly pinned, or if the provided key belongs to the configured pool
    allow_pool_rotation = (not (api_key or "").strip()) or (initial_key in pool_keys)
    if allow_pool_rotation and len(pool_keys) > 1 and not initial_key.startswith(("AQ.Test", "AIzaTest")):
        # requests take the pool's keys in turn: parallel batches use every key's pace and daily allowance
        initial_key = GeminiKeyPool.next_key() or initial_key

    current_key = initial_key

    if not current_key.startswith(("AQ.Test", "AIzaTest")) and is_gemini_quota_exhausted():
        q_info = get_gemini_quota_info()
        raise DailyQuotaExhaustedError(
            f"⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). "
            f"Έτοιμο ξανά στις {q_info['reset_time_str']} (απομένουν ~{q_info['cooldown_time_str']}). "
            f"Αλλάξτε API Key στις Ρυθμίσεις ή περιμένετε την αντίστροφη μέτρηση για αυτόματη συνέχιση."
        )

    if current_key.startswith("AQ.Test") or current_key.startswith("AIzaTest"):
        logger.info("Test API key detected - returning mock polished text.")
        if image is not None:
            return f"The text of a scanned page ({image_hash[:8]}). It was a bright cold day in April."
        for tag in ("DRAFT_TO_POLISH", "TEXT_TO_POLISH", "TEXT_TO_TRANSLATE"):
            m_tag = re.search(rf"<{tag}>(.*?)</{tag}>", content_text, re.DOTALL | re.IGNORECASE)
            if m_tag:
                inner = m_tag.group(1).strip()
                if "⟦" in inner:   # numbered segments (format-preserving AI): mark every segment
                    return re.sub(r"(⟦\d+⟧)\s*", r"\1 [Επιμελημένο AI]: ", inner)
                if re.search(r"={3,}\s*PAGE\s+\d+\s*={3,}", inner):
                    subbed = re.sub(r"(={3,}\s*PAGE\s+\d+\s*={3,})", r"\1\n[Επιμελημένο AI]:", inner)
                    return sanitize_ai_output(subbed)
                return sanitize_ai_output(f"[Επιμελημένο AI]: {inner}")
        if "--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n" in content_text:
            draft_part = content_text.split("--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n")[-1]
            return sanitize_ai_output(f"[Επιμελημένο AI]: {draft_part.strip()}")
        return sanitize_ai_output(f"[Επιμελημένο AI]: {content_text}")

    # Check cache first (unless explicitly bypassed during a quality retry)
    # Hash the FULL system_prompt so style, language, glossary, and entity dossier NEVER collide!
    cache_key = None
    prompt_hash = hashlib.sha256((system_prompt or "").encode("utf-8")).hexdigest()[:24]
    if not bypass_cache:
        try:
            from backend.database import compute_cache_key, db_get_cached_translation
            cache_key = compute_cache_key(cache_source, "draft", "greek", engine="gemini_polish_v5",
                                          extra=f"{prompt_hash}:{temperature}{':full' if _FULL_MODELS_ONLY.get() else ''}")
            cached_result = db_get_cached_translation(cache_key)
            if cached_result is not None:
                logger.info("Retrieved AI polished chunk directly from SQLite cache.")
                record_gemini_usage(cached=True)
                return clean_answer(cached_result, source_text=content_text)
        except Exception as ex:
            logger.debug(f"Polish cache check skipped: {ex}")
    else:
        try:
            from backend.database import compute_cache_key
            cache_key = compute_cache_key(cache_source, "draft", "greek", engine="gemini_polish_v5",
                                          extra=f"{prompt_hash}:{temperature}{':full' if _FULL_MODELS_ONLY.get() else ''}")
        except Exception:
            pass

    global _CACHED_WORKING_MODEL

    # Size-aware pacing & timeout: a fixed 25 s timeout made long batches (up to 16k output tokens) time out on
    # full Flash models and silently fall back to weaker Lite models; a fixed 1.5k-token estimate under-counted TPM.
    payload_chars = len(system_prompt or "") + len(content_text or "")
    est_tokens = max(500, min(60_000, payload_chars // 2))          # ~input + comparable output
    req_timeout_s = float(max(45.0, min(180.0, 45.0 + len(content_text or "") / 120.0)))
    if image is not None:
        est_tokens += 3000           # the picture (Gemini counts it in tiles) and a full page of text back
        req_timeout_s = max(req_timeout_s, 90.0)

    # the instructions open the prompt; the book's own names and terms are appended below them
    prompt_greek, prompt_latin = _script_counts((system_prompt or "")[:600])
    label = "ΚΕΙΜΕΝΟ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ" if prompt_greek > prompt_latin else "INPUT TEXT"
    user_parts: list[dict[str, Any]] = [{"text": f"{system_prompt}\n\n--- {label} ---\n{content_text}"}]
    if image is not None:
        user_parts = [
            {"text": f"{system_prompt}\n\n{content_text}"},
            {"inlineData": {"mimeType": image[0], "data": base64.b64encode(image[1]).decode("ascii")}},
        ]
    base_payload = {
        "contents": [
            {
                "role": "user",
                "parts": user_parts,
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 16384,
        },
        "safetySettings": _LITERARY_SAFETY_SETTINGS,
    }

    # Reuse caller's session if provided, otherwise open a temporary one
    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
    try:
        while current_key:
            attempted_keys.add(current_key)
            active_key = current_key
            switched_key = False

            # Models in order of preference. The model that worked last is no longer put first: that kept every key on
            # a fallback once the first key had used up the best model's daily allowance. An overloaded or timing-out
            # model is tried last for a while instead (_deprioritize_slow_models).
            candidates = []
            discovered = await _get_available_models(active_key, session)

            if discovered:
                # 1. Preferred full Flash models first, then Flash-Lite
                for pref in PREFERRED_FLASH_MODELS:
                    if pref in discovered and pref not in candidates:
                        candidates.append(pref)

                # 2. Other valid Gemini models (exclude research, embedding, and non-generative models)
                _EXCLUDED_MODELS = ("gemma", "hydrogen", "neon", "carbon", "robotics", "computer-use", "custom", "embedding", "aqa", "imagen")
                for m in discovered:
                    m_low = m.lower()
                    if any(bad in m_low for bad in _EXCLUDED_MODELS):
                        continue
                    if m not in candidates:
                        candidates.append(m)
            else:
                for fb in PREFERRED_FLASH_MODELS:
                    if fb not in candidates:
                        candidates.append(fb)

            if prefer_models:
                first = [m for m in prefer_models if m in candidates]
                candidates = first + [m for m in candidates if m not in first]

            if exclude_models:
                filtered = [m for m in candidates if m not in exclude_models]
                if filtered:
                    candidates = filtered

            if _FULL_MODELS_ONLY.get():
                candidates = [m for m in candidates if _is_full_model(m)]
            candidates = _deprioritize_slow_models(candidates)
            ranked = list(candidates)

            # Filter out candidate models that are currently cooling down for this specific key
            candidates = GeminiKeyPool.get_active_models_for_key(active_key, candidates)

            # The strongest model first on every key: when it reached its daily limit here but not on another key,
            # that key is used rather than a weaker model here
            if allow_pool_rotation:
                better_key = GeminiKeyPool.key_for_better_model(
                    ranked, candidates[0] if candidates else None, exclude_keys=attempted_keys)
                if better_key:
                    logger.info(
                        f"[Gemini Key Pool] Key {mask_api_key(active_key)} has used its daily allowance of a better "
                        f"model than {candidates[0] if candidates else 'any left'}: continuing on key "
                        f"{mask_api_key(better_key)}.")
                    current_key = better_key
                    continue

            if not candidates:
                if allow_pool_rotation:
                    next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=attempted_keys)
                    if next_pool_key:
                        logger.warning(
                            f"[Gemini Key Pool] All candidate models cooling down for key {mask_api_key(active_key)}. "
                            f"Rotating to next key {mask_api_key(next_pool_key)}..."
                        )
                        current_key = next_pool_key
                        continue
                raise DailyQuotaExhaustedError("All Gemini candidate models are in cooldown across configured keys.")

            last_error = None
            saw_truncation = False
            saw_block = False
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": active_key,
            }

            for model in candidates:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                # Disable hidden thinking on Flash models (2.5 & 3.x) so output budget isn't eaten by chain-of-thought
                m_low = model.lower()
                use_no_thinking = (
                    "flash" in m_low
                    and "pro" not in m_low
                    and "lite" not in m_low
                    and not m_low.startswith("gemma")
                    and ("2.5" in m_low or "3" in m_low or "latest" in m_low)
                )
                req_payload: dict[str, Any] = (
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

                max_attempts = 3
                for attempt in range(max_attempts):
                    try:
                        # Smoothly pace requests to conform to per-key and per-model RPM/TPM limits
                        await GeminiRateLimiter.acquire(active_key, model=model, estimated_tokens=est_tokens)

                        req_timeout = aiohttp.ClientTimeout(total=req_timeout_s, sock_connect=15)
                        async with session.post(url, json=req_payload, headers=headers, timeout=req_timeout) as resp:
                            if resp.status == 200:
                                result = await resp.json()
                                raw_text, finish_reason = _extract_gemini_text_and_reason(result)
                                if not raw_text or finish_reason in _INTERRUPTED_REASONS:
                                    saw_block = True
                                    last_error = f"Model {model} returned empty/blocked content (reason: {finish_reason or 'UNKNOWN'})"
                                    logger.warning(
                                        f"Model {model} gave no complete answer (finishReason: {finish_reason or 'UNKNOWN'}, "
                                        f"{len(raw_text)} chars). Trying the next candidate...")
                                    break  # the same model would answer the same: one request each
                                if finish_reason == "MAX_TOKENS":
                                    logger.warning(f"Model {model} hit MAX_TOKENS ({len(raw_text)} chars) — rejecting truncated output.")
                                    saw_truncation = True
                                    raise _TruncatedOutputError(f"Model {model} hit MAX_TOKENS")
                                polished = clean_answer(raw_text, source_text=content_text)
                                if not polished:
                                    saw_block = True
                                    last_error = f"Model {model} returned empty text after sanitization."
                                    break
                                # Cache working model
                                if "lite" not in m_low and not m_low.startswith("gemma"):
                                    _CACHED_WORKING_MODEL = model
                                if meta_out is not None:
                                    meta_out["model"] = model
                                    meta_out["finish_reason"] = finish_reason
                                logger.info(f"Gemini API success using model: {model}")
                                record_gemini_usage(result)
                                _MODEL_SLOW_UNTIL.pop(model, None)
                                cacheable = (
                                    cache_gate(polished) if cache_gate is not None
                                    else image is not None
                                    or not detect_greek_output_issues(polished, source_text=content_text)
                                )
                                if cache_key and cacheable:
                                    try:
                                        from backend.database import db_set_cached_translation
                                        db_set_cached_translation(cache_key, cache_source, polished, "draft", "greek", engine="gemini_polish_v5")
                                    except Exception:
                                        pass
                                return polished
                            elif resp.status in (401, 403):
                                err_text = await resp.text()
                                if allow_pool_rotation:
                                    GeminiKeyPool.mark_key_exhausted(active_key, 86400.0, reason=f"Auth error ({resp.status}): {err_text[:120]}")
                                    next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=attempted_keys)
                                    if next_pool_key:
                                        logger.warning(
                                            f"[Gemini Key Pool] Active key {mask_api_key(active_key)} failed auth ({resp.status}). "
                                            f"Seamlessly rotating to next key {mask_api_key(next_pool_key)}..."
                                        )
                                        current_key = next_pool_key
                                        switched_key = True
                                        break
                                raise PermissionError(f"Gemini API authentication error ({resp.status}): {err_text}")
                            elif resp.status == 404:
                                logger.debug(f"Model {model} returned 404, trying next candidate...")
                                if _CACHED_WORKING_MODEL == model:
                                    _CACHED_WORKING_MODEL = None
                                break
                            elif resp.status in (500, 502, 503, 504):
                                err_text = await resp.text()
                                last_error = f"Gemini API error ({resp.status}): {err_text}"
                                logger.info(f"Model {model} overloaded/unavailable ({resp.status}). Immediately trying next candidate...")
                                if _CACHED_WORKING_MODEL == model:
                                    _CACHED_WORKING_MODEL = None
                                # tried last for a while, so the next requests do not each meet the overload first
                                _MODEL_SLOW_UNTIL[model] = time.time() + OVERLOADED_MODEL_PENALTY_S
                                break
                            elif resp.status == 429:
                                err_text = await resp.text()
                                last_error = f"Gemini API error (429): {err_text}"
                                parsed_err = parse_gemini_error(429, err_text)
                                cat = parsed_err.get("category")

                                # 1. Model-specific daily quota exhaustion (e.g. limit: 20 on gemini-3.8-flash)
                                if cat == "QUOTA_EXCEEDED_DAILY_MODEL":
                                    exh_mod = parsed_err.get("model") or model
                                    cooldown_mod = parsed_err.get("retry_delay_sec") or 86400.0
                                    GeminiKeyPool.mark_model_exhausted(
                                        active_key, exh_mod, cooldown_seconds=cooldown_mod, reason=err_text[:120]
                                    )
                                    from backend.gemini_key_pool import record_model_daily_limit
                                    record_model_daily_limit(exh_mod, parsed_err.get("quota_value"))
                                    logger.warning(
                                        f"[Gemini Key Pool] Model '{exh_mod}' reached daily quota limit ({parsed_err.get('quota_value', 'daily')} requests) "
                                        f"on key {mask_api_key(active_key)}. Seamlessly falling back to next candidate model on SAME key..."
                                    )
                                    if _CACHED_WORKING_MODEL == model:
                                        _CACHED_WORKING_MODEL = None
                                    break

                                # 2. Model tier restriction (e.g. plan/billing requirement)
                                if cat == "MODEL_TIER_RESTRICTED":
                                    GeminiKeyPool.mark_model_exhausted(active_key, model, cooldown_seconds=86400.0, reason="Tier restricted")
                                    logger.info(f"Model {model} unavailable on current key tier ({resp.status}). Trying next candidate model on SAME key...")
                                    if _CACHED_WORKING_MODEL == model:
                                        _CACHED_WORKING_MODEL = None
                                    break

                                # 3. Transient per-minute rate limit (RPM burst / retryDelay <= 60s)
                                if cat == "RATE_LIMIT_TRANSIENT":
                                    delay_sec = parsed_err.get("retry_delay_sec") or (2.0 * (attempt + 1))
                                    GeminiRateLimiter.record_retry_after(active_key, model=model, delay_seconds=delay_sec)
                                    if attempt < max_attempts - 1:
                                        wait_time = max(0.1, min(30.0, delay_sec + 0.1 if delay_sec < 1.0 else delay_sec + 0.5))
                                        logger.warning(
                                            f"Model {model} transient rate limit (attempt {attempt + 1}/{max_attempts}). "
                                            f"Backing off for {wait_time:.1f}s before retry..."
                                        )
                                        await asyncio.sleep(wait_time)
                                        continue
                                    # If transient attempts exhausted on this model, advance to next model on same key
                                    break

                                # 4. Key-wide daily quota exhaustion
                                cooldown_sec = parsed_err.get("retry_delay_sec") or 3600.0
                                GeminiKeyPool.mark_key_exhausted(active_key, cooldown_sec, reason=err_text[:120])
                                next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=attempted_keys) if allow_pool_rotation else None
                                if next_pool_key:
                                    logger.warning(
                                        f"[Gemini Key Pool] Active key {mask_api_key(active_key)} exhausted quota ({resp.status}). "
                                        f"Seamlessly rotating to next available key {mask_api_key(next_pool_key)}..."
                                    )
                                    current_key = next_pool_key
                                    switched_key = True
                                    break

                                cooldown_to_trip = cooldown_sec
                                try:
                                    pool_st = GeminiKeyPool.get_pool_status()
                                    if pool_st.get("total_keys", 0) > 0:
                                        earliest_ts = pool_st.get("earliest_reset_timestamp", 0.0)
                                        if earliest_ts > time.time():
                                            cooldown_to_trip = max(5.0, earliest_ts - time.time())
                                except Exception:
                                    pass
                                trip_gemini_quota_exhaustion(cooldown_to_trip)
                                q_info = get_gemini_quota_info()
                                logger.warning(
                                    f"Gemini daily quota exhausted ({resp.status}). All {len(attempted_keys)} pool keys exhausted. Tripping circuit breaker for {int(cooldown_sec)}s."
                                )
                                raise DailyQuotaExhaustedError(
                                    f"⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). "
                                    f"Η πρόοδος αποθηκεύτηκε σε checkpoint στο δίσκο. "
                                    f"Έτοιμο ξανά στις {q_info['reset_time_str']} (απομένουν ~{q_info['cooldown_time_str']}). "
                                    f"Παρακαλούμε περιμένετε ή αλλάξτε API Key στις Ρυθμίσεις (Settings)."
                                )
                            else:
                                err_text = await resp.text()
                                if resp.status == 400 and "thinkingConfig" in req_payload.get("generationConfig", {}):
                                    req_payload = {
                                        **req_payload,
                                        "generationConfig": {
                                            k: v for k, v in req_payload["generationConfig"].items() if k != "thinkingConfig"
                                        },
                                    }
                                    continue
                                if resp.status == 400 and "safety" in err_text.lower() and "safetySettings" in req_payload:
                                    req_payload = {k: v for k, v in req_payload.items() if k != "safetySettings"}
                                    continue
                                last_error = f"Gemini API error ({resp.status}): {err_text}"
                                if resp.status == 400 and "API_KEY_INVALID" in err_text:
                                    if allow_pool_rotation:
                                        GeminiKeyPool.mark_key_exhausted(active_key, 86400.0, reason=f"Invalid API Key: {err_text[:120]}")
                                        next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=attempted_keys)
                                        if next_pool_key:
                                            logger.warning(
                                                f"[Gemini Key Pool] Active key {mask_api_key(active_key)} is invalid. "
                                                f"Seamlessly rotating to next key {mask_api_key(next_pool_key)}..."
                                            )
                                            current_key = next_pool_key
                                            switched_key = True
                                            break
                                    raise PermissionError(last_error)
                                logger.warning(f"Model {model} failed: {last_error}")
                                break
                    except (PermissionError, _TruncatedOutputError, DailyQuotaExhaustedError):
                        raise
                    except asyncio.TimeoutError:
                        last_error = f"Model {model} timed out after {req_timeout_s:.0f}s."
                        logger.warning(f"Model {model} timed out after {req_timeout_s:.0f}s. Switching immediately to next candidate...")
                        _MODEL_SLOW_UNTIL[model] = time.time() + SLOW_MODEL_PENALTY_S
                        if _CACHED_WORKING_MODEL == model:
                            _CACHED_WORKING_MODEL = None
                        break
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Call to {model} failed (attempt {attempt + 1}/{max_attempts}): {e}")
                        if _CACHED_WORKING_MODEL == model:
                            _CACHED_WORKING_MODEL = None
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(1.0)

                if switched_key:
                    break

            if switched_key:
                continue

            if saw_truncation:
                raise _TruncatedOutputError(last_error or "Gemini output truncated by MAX_TOKENS.")
            if saw_block:
                raise _ContentBlockedError(last_error or "Gemini content blocked/empty across all candidates.")

            # If all candidates on this key failed, attempt failover to next key in pool
            if allow_pool_rotation:
                next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=attempted_keys)
                if next_pool_key:
                    logger.warning(
                        f"[Gemini Key Pool] All candidate models failed on key {mask_api_key(active_key)}. "
                        f"Seamlessly rotating to next key {mask_api_key(next_pool_key)}..."
                    )
                    current_key = next_pool_key
                    continue

            raise RuntimeError(last_error or "All Gemini candidate models failed.")
    finally:
        if owns_session:
            await session.close()


async def translate_and_polish_direct_with_gemini(
    job_id: str,
    file_path: str,
    file_type: str,
    source_lang: str,
    target_lang: str,
    output_path: str,
    api_key: str,
    style: str = "literature",
    quota_behavior: str = "wait",
    page_range: Optional[tuple[int, int]] = None,
) -> str:
    """
    Single-Pass Direct AI Translation + Literary Polish via Gemini Flash.
    Eliminates the slow 2-pass Google Translate -> Gemini Polish pipeline:
    parses the document, extracts an entity consistency dossier, applies user glossary,
    and translates+polishes multi-page batches concurrently (5 parallel workers),
    saving both *_original.txt (for split-screen editor) and the polished output.

    ``page_range`` (first, last): a sample. Only the batches holding those pages are translated (whole batches, so it
    may end a page or two later; the job's sample_range gives the pages done). Names, glossary and batches are those of
    the whole book and the checkpoint is kept, so translating the whole book afterwards reuses the sample's batches.
    """
    from backend.parsers import parse_document
    from backend.job_manager import update_job, is_job_cancelled
    from backend.glossary import load_glossary, apply_glossary

    update_job(job_id, status="running", current_step="Reading document for Single-Pass AI Translation...", progress=2)
    pages = list(parse_document(file_path, file_type))
    total_pages = len(pages)
    if total_pages == 0:
        raise ValueError("No readable text found in document.")

    # Save original extracted text for split-screen editor review
    out_dir = Path(output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(file_path).stem
    orig_sections = []
    for p in pages:
        p_num = p["page"]
        p_txt = (p.get("text") or "").strip()
        orig_sections.append(f"=== PAGE {p_num} ===\n{p_txt}")
    full_original = "\n\n".join(orig_sections)
    try:
        (out_dir / f"{stem}_original.txt").write_text(full_original, encoding="utf-8")
    except Exception:
        pass

    # Dedicated translate-from-source prompt (previously the Greek *polish* prompt was wrapped inside a translation
    # task, giving the model contradictory instructions; English targets also received Greek-only rules).
    direct_prompt = build_direct_translation_prompt(source_lang, target_lang, style)

    # Disk checkpoint support for instant resume
    checkpoint_file = out_dir / ".direct_ai_checkpoint.json"
    # Signature: a checkpoint left by an interrupted run is reused only for the same source, languages, style and
    # prompt version (otherwise restarting with another target language/style silently mixed old batches in).
    direct_sig = hashlib.sha256(
        f"{PROMPT_VERSION}::{style}::{source_lang}::{target_lang}::{len(full_original)}::{full_original[:2000]}".encode("utf-8")
    ).hexdigest()[:16]
    direct_full = hashlib.sha256(full_original.encode("utf-8")).hexdigest()[:16]
    checkpoint_data: dict[str, Any] = {"sig": direct_sig, "full": direct_full, "batches": {}, "entity_dossier": ""}
    if checkpoint_file.is_file():
        try:
            loaded = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            if loaded.get("sig") not in (None, direct_sig) or loaded.get("full", direct_full) != direct_full:
                logger.info(f"[{job_id}] Discarding stale direct-translation checkpoint (different source/settings).")
                loaded = {}
            if isinstance(loaded.get("batches"), dict):
                checkpoint_data["batches"] = loaded["batches"]
            if isinstance(loaded.get("entity_dossier"), str):
                checkpoint_data["entity_dossier"] = loaded["entity_dossier"]
        except Exception:
            pass

    def _save_cp():
        try:
            checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # Group pages into ~5,500-char / max 3-page batches for high Greek fidelity & zero MAX_TOKENS truncation
    batches: list[list[tuple[int, str]]] = []
    curr_b: list[tuple[int, str]] = []
    curr_chars = 0
    MAX_BATCH_CHARS = 5500
    MAX_BATCH_PAGES = 3

    for p in pages:
        p_num = p["page"]
        p_txt = (p.get("text") or "").strip()
        item_len = len(p_txt) + 25
        if curr_b and (curr_chars + item_len > MAX_BATCH_CHARS or len(curr_b) >= MAX_BATCH_PAGES):
            batches.append(curr_b)
            curr_b = [(p_num, p_txt)]
            curr_chars = item_len
        else:
            curr_b.append((p_num, p_txt))
            curr_chars += item_len
    if curr_b:
        batches.append(curr_b)

    run = list(range(len(batches)))
    if page_range:
        lo, hi = page_range
        run = [i for i, b in enumerate(batches) if any(lo <= pn <= hi for pn, _ in b)]
        if not run:
            raise ValueError(f"Pages {lo}–{hi} hold no text to translate.")
        total_pages = sum(len(batches[i]) for i in run)
        update_job(job_id, sample_range=[batches[run[0]][0][0], batches[run[-1]][-1][0]])

    total_batches = max(1, len(run))
    results = ["" for _ in batches]
    completed = 0
    pages_done = 0
    cached_b = checkpoint_data.get("batches", {})
    for i in run:
        if str(i) in cached_b and cached_b[str(i)].strip():
            results[i] = cached_b[str(i)]
            completed += 1
            pages_done += len(batches[i])

    init_pct = 8 + int((completed / total_batches) * 85) if completed > 0 else 5
    init_step = (
        f"Resuming Single-Pass AI Translation & Polish: batch {completed}/{total_batches} ({pages_done}/{total_pages} pages)..."
        if completed > 0
        else f"Single-Pass AI Translation ({total_batches} parallel batches, {total_pages} pages)..."
    )
    update_job(
        job_id,
        total_chunks=total_batches,
        done_chunks=completed,
        total_pages=total_pages,
        done_pages=pages_done,
        progress=init_pct,
        current_step=init_step,
    )

    sem = asyncio.Semaphore(5)
    target_temp = STYLE_TEMPERATURES.get(style, 0.30)
    connector = aiohttp.TCPConnector(limit=12, ttl_dns_cache=300)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90), connector=connector) as session:
        # Extract entity consistency dossier for long documents
        entity_dossier = checkpoint_data.get("entity_dossier", "")
        if not entity_dossier and len(full_original) > 18000:
            update_job(job_id, current_step="Extracting character & terminology dossier...", progress=max(6, init_pct))
            entity_dossier = await _extract_entity_dossier(full_original, api_key, session=session,
                                                           target_lang=target_lang, mode="translation")
            if entity_dossier:
                checkpoint_data["entity_dossier"] = entity_dossier
                _save_cp()

        system_instruction = direct_prompt
        if entity_dossier:
            system_instruction += dossier_header("translation", target_lang) + f"{entity_dossier}\n"

        # Inject matching glossary terms (style-aware: excludes IT/DevOps terms for literature)
        glossary_items = load_glossary(style=style)
        if glossary_items and target_lang.lower() not in ("greek", "el"):
            system_instruction += english_glossary_rules(glossary_items, full_original)
        elif glossary_items:
            lower_src = full_original.lower()
            matched = [(k, v) for k, v in glossary_items.items() if k.lower() in lower_src][:50]
            if matched:
                g_lines = "\n".join(f"- {k} -> {v}" for k, v in matched)
                system_instruction += (
                    "\n\n--- ΓΛΩΣΣΑΡΙΟ ΧΡΗΣΤΗ (GLOSSARY RULES) ---\n"
                    f"{g_lines}\n"
                )

        is_target_greek = target_lang.lower() in ("greek", "el")

        async def _translate_items_reliably(
            b_items: list[tuple[Optional[int], str]],
            prev_tail: str = "",
            depth: int = 0,
        ) -> str:
            batch_src = "\n\n".join(
                f"=== PAGE {pn} ===\n{txt}" if pn is not None else txt for pn, txt in b_items
            )
            expected_pnums = [pn for pn, txt in b_items if pn is not None and txt.strip()]
            content_parts = []
            if prev_tail:
                content_parts.append(
                    f"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n{prev_tail}\n</PREVIOUS_CONTEXT_DO_NOT_REPEAT>"
                )
            content_parts.append(f"<TEXT_TO_TRANSLATE>\n{batch_src}\n</TEXT_TO_TRANSLATE>")
            prompt_text = "\n\n".join(content_parts)

            batch_sys = system_instruction
            if prev_tail:
                batch_sys += _continuity_rule(is_target_greek, translating=True)

            async def _bisect_direct(reason_label: str) -> Optional[str]:
                if len(b_items) > 1 and depth < 3:
                    mid = len(b_items) // 2
                    logger.warning(f"[{job_id}] Direct AI batch hit {reason_label}; splitting {len(b_items)} pages into {mid}+{len(b_items)-mid}...")
                    left_err: Optional[Exception] = None
                    right_err: Optional[Exception] = None
                    left_res, right_res = "", ""
                    try:
                        left_res = await _translate_items_reliably(b_items[:mid], prev_tail, depth + 1)
                    except (PermissionError, DailyQuotaExhaustedError):
                        raise
                    except Exception as ex_l:
                        left_err = ex_l
                        from backend.translator import _translate_with_retry
                        fb_l = []
                        for pn_l, txt_l in b_items[:mid]:
                            tr_l = await _translate_with_retry(txt_l, source_lang, target_lang) if txt_l else ""
                            fb_l.append(f"=== PAGE {pn_l} ===\n{tr_l}" if pn_l is not None else tr_l)
                        left_res = "\n\n".join(fb_l)
                    right_tail = _extract_clean_tail_context(b_items[mid - 1][1]) if b_items[mid - 1][1] else ""
                    try:
                        right_res = await _translate_items_reliably(b_items[mid:], right_tail, depth + 1)
                    except (PermissionError, DailyQuotaExhaustedError):
                        raise
                    except Exception as ex_r:
                        right_err = ex_r
                        from backend.translator import _translate_with_retry
                        fb_r = []
                        for pn_r, txt_r in b_items[mid:]:
                            tr_r = await _translate_with_retry(txt_r, source_lang, target_lang) if txt_r else ""
                            fb_r.append(f"=== PAGE {pn_r} ===\n{tr_r}" if pn_r is not None else tr_r)
                        right_res = "\n\n".join(fb_r)
                    if not left_res.strip() and not right_res.strip():
                        raise (left_err or right_err or RuntimeError(reason_label))
                    r_first_pg = b_items[mid][0]
                    right_clean = _deduplicate_batch_boundary(
                        left_res, right_res, expected_first_page=r_first_pg,
                        source_prev="\n\n".join(t for _, t in b_items[:mid]),
                        source_curr="\n\n".join(t for _, t in b_items[mid:]),
                    )
                    return f"{left_res.strip()}\n\n{right_clean.strip()}".strip()

                # Single-page paragraph bisection so 1 explicit paragraph never drops an entire page to Google Translate
                if len(b_items) == 1 and depth < 4:
                    only_pn, only_txt = b_items[0]
                    halves = _split_text_in_half_by_paragraphs(only_txt)
                    if halves:
                        l_txt, r_txt = halves
                        logger.warning(f"[{job_id}] Direct AI single page {only_pn} hit {reason_label}; bisecting by paragraphs (depth={depth + 1})...")
                        left_err = None
                        right_err = None
                        left_res, right_res = "", ""
                        try:
                            left_res = await _translate_items_reliably([(only_pn, l_txt)], prev_tail, depth + 1)
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_l:
                            left_err = ex_l
                            from backend.translator import _translate_with_retry
                            tr_l = await _translate_with_retry(l_txt, source_lang, target_lang)
                            left_res = f"=== PAGE {only_pn} ===\n{tr_l}" if only_pn is not None else tr_l
                        try:
                            right_res = await _translate_items_reliably([(None, r_txt)], _extract_clean_tail_context(l_txt), depth + 1)
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_r:
                            right_err = ex_r
                            from backend.translator import _translate_with_retry
                            right_res = await _translate_with_retry(r_txt, source_lang, target_lang)
                        if not left_res.strip() and not right_res.strip():
                            raise (left_err or right_err or RuntimeError(reason_label))
                        right_clean = _deduplicate_batch_boundary(
                            left_res, right_res, expected_first_page=None, source_prev=l_txt, source_curr=r_txt)
                        return f"{left_res.strip()}\n\n{right_clean.strip()}".strip()
                return None

            meta: dict[str, Any] = {}
            try:
                translated_b = await _call_gemini_api(
                    prompt_text,
                    api_key,
                    batch_sys,
                    session=session,
                    temperature=target_temp,
                    meta_out=meta,
                    cache_gate=lambda out: not detect_greek_output_issues(
                        out, source_text=batch_src, greek_target=is_target_greek)
                    and not _answer_problem(out, batch_src, is_target_greek, translating=True),
                )
            except PermissionError:
                raise
            except (_TruncatedOutputError, _ContentBlockedError) as err:
                recovered = await _bisect_direct(type(err).__name__)
                if recovered is not None:
                    return recovered
                raise
            except Exception as err:
                err_low = str(err).lower()
                if any(k in err_low for k in ("timed out", "block", "safety", "prohibited", "empty", "max_tokens")):
                    recovered = await _bisect_direct(str(err)[:80])
                    if recovered is not None:
                        return recovered
                raise

            if expected_pnums:
                translated_b = _deduplicate_batch_boundary("", translated_b, expected_first_page=expected_pnums[0])

            if is_target_greek and not api_key.startswith(("AQ.Test", "AIzaTest")):
                issues = detect_greek_output_issues(
                    translated_b,
                    source_text=batch_src,
                    expected_pages=expected_pnums if len(expected_pnums) >= 2 else None,
                )
                if issues:
                    logger.warning(f"[{job_id}] Direct AI quality gate flagged {issues} (model={meta.get('model')})")
                    needs_split = any(i.startswith(("missing_pages", "truncated")) for i in issues)
                    if needs_split:
                        recovered = await _bisect_direct(",".join(issues))
                        if recovered is not None:
                            return recovered
                    bad_model = meta.get("model")
                    if bad_model:
                        try:
                            retry_sys = batch_sys + _quality_retry_hint(issues, translated_b, batch_src, True)
                            other_full_models = [
                                m for m in (_CACHED_AVAILABLE_MODELS or [])
                                if m != bad_model and not m.startswith("gemma") and "lite" not in m.lower()
                            ]
                            excl = {bad_model} if other_full_models else None
                            retry_meta: dict[str, Any] = {}
                            retried = await _call_gemini_api(
                                prompt_text,
                                api_key,
                                retry_sys,
                                session=session,
                                temperature=max(0.1, target_temp - 0.1),
                                exclude_models=excl,
                                bypass_cache=True,
                                meta_out=retry_meta,
                            )
                            if expected_pnums:
                                retried = _deduplicate_batch_boundary("", retried, expected_first_page=expected_pnums[0])
                            retry_issues = detect_greek_output_issues(
                                retried,
                                source_text=batch_src,
                                expected_pages=expected_pnums if len(expected_pnums) >= 2 else None,
                            )
                            if len(retry_issues) < len(issues):
                                logger.info(f"[{job_id}] Quality retry succeeded on {retry_meta.get('model')} ({issues} -> {retry_issues})")
                                translated_b = retried
                        except Exception as rex:
                            logger.debug(f"[{job_id}] Quality retry failed: {rex}")

            if not api_key.startswith(("AQ.Test", "AIzaTest")):
                problem = _answer_problem(
                    translated_b, batch_src, is_target_greek,
                    expected_pages=expected_pnums if len(expected_pnums) >= 2 else None, translating=True)
                if problem:
                    # a passage echoed untranslated is often one paragraph the model balks at: smaller pieces pass
                    if problem.startswith(("missing_pages", "truncated", "untranslated")):
                        recovered = await _bisect_direct(problem)
                        if recovered is not None:
                            return recovered
                    raise _BadAnswerError(f"Unusable translation answer: {problem}")  # the caller's fallback translates
            return translated_b

        from backend import translator as _free_engine
        # looked up at run time: () matches nothing if the files were updated under a still-running older server
        TranslationUnavailableError = getattr(_free_engine, "TranslationUnavailableError", ())

        async def _worker(b_idx: int, b_items: list[tuple[int, str]]):
            nonlocal completed, pages_done
            if results[b_idx]:
                return
            if is_job_cancelled(job_id):
                raise asyncio.CancelledError("Translation cancelled by user.")

            # If all pages in batch are empty, skip API call
            if all(not txt for _, txt in b_items):
                results[b_idx] = "\n\n".join(f"=== PAGE {pn} ===" for pn, _ in b_items)
                completed += 1
                pages_done += len(b_items)
                return

            prev_tail = ""
            if b_idx > 0:
                prev_txt = batches[b_idx - 1][-1][1]
                if prev_txt:
                    prev_tail = _extract_clean_tail_context(prev_txt, max_chars=240)

            async with sem:
                if is_job_cancelled(job_id):
                    raise asyncio.CancelledError("Translation cancelled by user.")
                last_ex: Optional[Exception] = None
                translated_b = ""
                # Retry once after a short cooldown if transient 429/503 hit all models
                for retry_round in range(2):
                    try:
                        translated_b = await _translate_items_reliably(b_items, prev_tail=prev_tail)
                        last_ex = None
                        break
                    except TranslationUnavailableError:
                        raise  # the free engine was the fallback already: asking it again only delays the error
                    except (PermissionError, DailyQuotaExhaustedError) as p_or_q:
                        if isinstance(p_or_q, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                            logger.warning(
                                f"[{job_id}] Gemini Daily Quota exhausted on batch {b_idx + 1}/{total_batches}. "
                                f"quota_behavior='fallback' -> Seamlessly switching this batch and subsequent batches to free translation engine..."
                            )
                            last_ex = p_or_q
                            break
                        raise
                    except Exception as ex:
                        last_ex = ex
                        if retry_round == 0 and any(k in str(ex) for k in ("429", "503", "500", "502", "504", "timed out")):
                            logger.info(f"[{job_id}] Direct AI batch {b_idx+1}/{total_batches} transient error, cooling down 4s before retry...")
                            await asyncio.sleep(4.0)
                            continue
                        break

                if last_ex is None and translated_b:
                    results[b_idx] = translated_b
                    checkpoint_data["batches"][str(b_idx)] = translated_b
                    _save_cp()
                else:
                    logger.warning(f"[{job_id}] Direct AI batch {b_idx+1}/{total_batches} failed: {last_ex}")
                    # Fallback to standard translator for just this batch
                    from backend.translator import _translate_with_retry
                    fallback_parts = []
                    for pn, txt in b_items:
                        tr_p = await _translate_with_retry(txt, source_lang, target_lang) if txt else ""
                        fallback_parts.append(f"=== PAGE {pn} ===\n{tr_p}")
                    results[b_idx] = "\n\n".join(fallback_parts)
                    checkpoint_data["batches"][str(b_idx)] = results[b_idx]
                    _save_cp()

            completed += 1
            pages_done += len(b_items)
            pct = 8 + int((completed / total_batches) * 85)
            step_msg = (
                f"Single-Pass AI Translation & Polish: batch {completed}/{total_batches} ({pages_done}/{total_pages} pages)..."
                if last_ex is None
                else f"⚠️ Όριο Gemini: Αυτόματη συνέχιση με δωρεάν μηχανή (batch {completed}/{total_batches})..."
            )
            update_job(
                job_id,
                done_chunks=completed,
                total_chunks=total_batches,
                done_pages=pages_done,
                total_pages=total_pages,
                progress=pct,
                current_step=step_msg,
            )

        await gather_or_cancel(_worker(i, batches[i]) for i in run)

    if checkpoint_file.exists() and not page_range:  # a sample's batches wait for the whole book
        try:
            checkpoint_file.unlink(missing_ok=True)
        except Exception:
            pass

    dedup_results: list[str] = []
    for res_idx, r in enumerate(results):
        if not r or not r.strip():
            continue
        first_pn = batches[res_idx][0][0] if batches[res_idx] else None
        prev_r = dedup_results[-1] if dedup_results else ""
        cleaned_r = _deduplicate_batch_boundary(
            prev_r, r.strip(), expected_first_page=first_pn,
            source_prev="\n\n".join(t for _, t in batches[res_idx - 1]) if res_idx else "",
            source_curr="\n\n".join(t for _, t in batches[res_idx]),
        )
        if cleaned_r:
            dedup_results.append(cleaned_r)

    final_text = collapse_empty_duplicate_markers("\n\n".join(dedup_results))
    final_text = sanitize_ai_output(final_text, source_text=full_original)
    final_text = apply_glossary(final_text, target_lang, style=style, translated=True)
    if target_lang.lower() in ("greek", "el"):
        from backend.typography import format_greek_typography
        final_text = format_greek_typography(final_text)
        if not api_key.startswith(("AQ.Test", "AIzaTest")) and _exotic_greek_tokens(final_text, full_original):
            update_job(job_id, current_step="Correcting words with letters of another alphabet...", progress=94)
            final_text, _left = await repair_mixed_script_words(final_text, api_key, source_text=full_original)

    Path(output_path).write_text(final_text, encoding="utf-8")
    update_job(job_id, progress=95, current_step="Finalizing AI translated document...", output_path=output_path)
    logger.info(f"[{job_id}] Single-Pass Direct AI Translation complete -> {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Maximum-quality revision pass (opt-in, Advanced Mode)
# ---------------------------------------------------------------------------

REVISION_TEMPERATURE = 0.15

_REPAIR_WORDS_PROMPT_EL = (
    "Είσαι διορθωτής ελληνικών κειμένων. Σε κάθε αριθμημένη γραμμή, η λέξη μέσα σε [[ ]] αλλοιώθηκε: μπήκαν μέσα της "
    "γράμματα άλλου αλφαβήτου (λατινικά, κυριλλικά, εβραϊκά, αραβικά, κινεζικά κ.λπ.). Γράψε τη σωστή ελληνική λέξη, "
    "με τον τόνο της, που ταιριάζει στη θέση της στην πρόταση. Απάντησε ΜΟΝΟ με γραμμές της μορφής «N. λέξη», μία "
    "για κάθε αριθμό, χωρίς σχόλια."
)
_TOKEN_EDGE = r"\s,;.:!?«»\"'()\[\]—–\-/\\*<>"


def _exotic_greek_tokens(text: str, source_text: str = "") -> list[str]:
    """Greek words carrying letters of another alphabet ('ποгда', 'Ίσות', 'κ临床')."""
    return [t for t in _find_mixed_script_tokens(text, source_text=source_text)
            if _GREEK_CHAR_RE.search(t) and _EXOTIC_SCRIPT_RE.search(t)]


async def repair_mixed_script_words(
    text: str,
    api_key: str,
    source_text: str = "",
    session: Optional[aiohttp.ClientSession] = None,
    max_words: int = 60,
) -> tuple[str, list[str]]:
    """
    Greek words still carrying letters of another alphabet after the batch retries, corrected by one small AI request
    that sees each word in its sentence. Only a whole Greek word of similar length replaces a corrupted one; anything
    else leaves it as it is. Returns (text, corrupted words left as they were).
    """
    tokens = _exotic_greek_tokens(text, source_text)
    if not tokens or not (api_key or "").strip():
        return text, tokens
    todo = tokens[:max_words]
    lines = []
    for n, tok in enumerate(todo, 1):
        at = text.find(tok)
        start = max(text.rfind("\n", 0, at) + 1, at - 160)
        end = text.find("\n", at + len(tok))
        end = min(len(text) if end < 0 else end, at + len(tok) + 160)
        lines.append(f"{n}. " + " ".join((text[start:at] + f"[[{tok}]]" + text[at + len(tok):end]).split()))
    try:
        answer = await _call_gemini_api("\n".join(lines), api_key, _REPAIR_WORDS_PROMPT_EL, session=session,
                                        temperature=0.1, cache_gate=lambda _out: True)
    except Exception as ex:  # quota, key or network: the words stay as they are and are reported
        logger.warning(f"Corrupted-word repair skipped ({ex}); {len(tokens)} word(s) left as they are.")
        return text, tokens
    fixes: dict[str, str] = {}
    for m in re.finditer(r"(?m)^\s*(\d+)[.)]\s*(.+?)\s*$", answer or ""):
        n = int(m.group(1))
        if not 1 <= n <= len(todo):
            continue
        tok, word = todo[n - 1], m.group(2).strip().strip("«»\"'“”[]")
        if not re.fullmatch(r"[Ͱ-Ͽ]+(?:['’][Ͱ-Ͽ]+)?", word):
            continue
        if not 0.5 * len(tok) <= len(word) <= 2 * len(tok) + 2:
            continue
        if tok[:1].isupper() and word[:1].islower():
            word = word[:1].upper() + word[1:]
        fixes[tok] = word
    for tok, word in fixes.items():
        text = re.sub(rf"(?<![^{_TOKEN_EDGE}]){re.escape(tok)}(?![^{_TOKEN_EDGE}])", lambda _m, w=word: w, text)
    if fixes:
        logger.info(f"Repaired {len(fixes)} word(s) with letters of another alphabet.")
    return text, [t for t in tokens if t not in fixes]


def translation_leftover_notes(translated: str, original: str, greek_target: bool = True) -> list[str]:
    """What the finished translation still carries that the reader would notice, for the job's final message."""
    if not greek_target or not translated:
        return []
    notes = []
    pages = find_untranslated_pages(translated, original or "")
    if pages:
        shown = ", ".join(map(str, pages[:10])) + (" …" if len(pages) > 10 else "")
        notes.append(f"{len(pages)} page(s) still contain text in the original language (pages {shown} of the "
                     f"original): translate again to retry them.")
    words = _exotic_greek_tokens(translated, original or "")
    if words:
        notes.append(f"{len(words)} word(s) contain letters of another alphabet ({', '.join(words[:5])}): "
                     f"please check them.")
    return notes


def _revised_page_ok(old: str, new: str, greek_target: bool) -> bool:
    old_s, new_s = old.strip(), new.strip()
    if not new_s:
        return False
    ratio = len(new_s) / max(len(old_s), 1)
    if len(old_s) >= 200 and not 0.6 <= ratio <= 1.6:
        return False
    if len(new_s) > 3 * len(old_s) + 100:
        return False
    return not _answer_problem(new_s, old_s, greek_target)


def merge_revised_pages(draft: str, revised: str, greek_target: bool = True) -> tuple[str, list[int]]:
    """
    The revision taken page by page: each page of `draft` gets its revised text when the revision returned that page
    exactly once and plausibly; any other page keeps the draft. One odd page (a duplicated or lost marker) no longer
    costs the whole revision. Returns (merged text, page numbers that kept the draft).
    """
    revised_by_page: dict[Optional[int], list[str]] = {}
    for pn, body in _split_marked_pages(revised):
        if body.strip():
            revised_by_page.setdefault(pn, []).append(body)
    draft_pages = _split_marked_pages(draft)
    filled = Counter(pn for pn, body in draft_pages if body.strip())
    out: list[str] = []
    kept: list[int] = []
    for pn, body in draft_pages:
        new = body
        if body.strip():
            candidates = revised_by_page.get(pn, [])
            if filled[pn] == 1 and len(candidates) == 1 and _revised_page_ok(body, candidates[0], greek_target):
                lead = body[:len(body) - len(body.lstrip())]
                tail = body[len(body.rstrip()):]
                new = lead + candidates[0].strip() + tail
            elif pn is not None:
                kept.append(pn)
        out.append(new if pn is None else f"=== PAGE {pn} ==={new}")
    return "".join(out), kept


async def revise_translation_against_source(
    job_id: Optional[str],
    translated_path: str,
    original_path: str,
    api_key: str,
    target_lang: str = "greek",
    style: str = "literature",
    quota_behavior: str = "wait",
    progress_callback: Optional[Callable[[int, int], Any]] = None,
) -> dict[str, Any]:
    """
    Second, independent revision of a finished AI translation against the original (translate -> revise).
    Reuses polish_text_with_gemini (page-aligned <SOURCE_REFERENCE>/<DRAFT_TO_POLISH> batches, dossier, checkpoints,
    per-batch quality gates) with the reviser prompt. The translation file is replaced atomically only if the revised
    text keeps every page marker and a plausible length; any failure keeps the first-pass translation untouched.
    Returns a JSON-safe report.
    """
    from backend.translation_prompts import build_revision_prompt
    started = time.time()
    report: dict[str, Any] = {"status": "skipped", "reason": None}
    tp_ = Path(translated_path)
    op_ = Path(original_path)
    if not (api_key or "").strip():
        report["reason"] = "no_api_key"
        return report
    if not tp_.is_file() or not op_.is_file():
        report["reason"] = "missing_files"
        return report
    draft = tp_.read_text(encoding="utf-8")
    original = op_.read_text(encoding="utf-8")
    if not draft.strip() or not original.strip():
        report["reason"] = "empty_text"
        return report

    policy_token = _FULL_MODELS_ONLY.set(True)   # never revise with a weaker fallback model
    try:
        revised = await polish_text_with_gemini(
            draft,
            api_key=api_key,
            style=style,
            original_text=original,
            job_id=f"{job_id}_revision" if job_id else None,
            use_source_anchoring=True,
            progress_callback=progress_callback,
            target_lang=target_lang,
            quota_behavior=quota_behavior,
            system_prompt_override=build_revision_prompt(target_lang),
            temperature_override=REVISION_TEMPERATURE,
        )
    except DailyQuotaExhaustedError as e:
        # Includes "no full model available": all full models cooling down on every key
        report.update(status="error", reason="quota_exhausted", detail=str(e)[:200])
        return report
    except PermissionError as e:
        report.update(status="error", reason="auth_failed", detail=str(e)[:200])
        return report
    except Exception as e:
        logger.warning(f"[{job_id}] Revision pass failed ({e}); keeping the first-pass translation.")
        report.update(status="error", reason="ai_failed", detail=str(e)[:200])
        return report
    finally:
        _FULL_MODELS_ONLY.reset(policy_token)

    if not revised or not revised.strip():
        report.update(status="error", reason="empty_revision")
        return report
    greek_target = target_lang.lower() in ("greek", "el", "gr")
    revised, kept_pages = merge_revised_pages(draft, revised, greek_target=greek_target)
    if kept_pages:
        logger.warning(f"[{job_id}] Revision: {len(kept_pages)} page(s) keep the first pass "
                       f"(missing, duplicated or implausible in the revision): {kept_pages[:20]}")
        report.update(kept_pages=len(kept_pages), kept_page_list=kept_pages[:30])
        filled_pages = sum(1 for pn, body in _split_marked_pages(draft) if pn is not None and body.strip())
        if len(kept_pages) >= filled_pages:
            report.update(status="error", reason="revision_unusable")
            return report
    if greek_target and not api_key.startswith(("AQ.Test", "AIzaTest")):
        revised, _left = await repair_mixed_script_words(revised, api_key, source_text=original)
    ratio = len(revised) / max(len(draft), 1)
    if not (0.8 <= ratio <= 1.25):
        report.update(status="error", reason=f"length_ratio_{ratio:.2f}")
        return report
    if " ".join(revised.split()) == " ".join(draft.split()):   # whitespace-only differences are not revisions
        report.update(status="verified_clean", duration_s=round(time.time() - started, 1))
        return report

    tmp = tp_.with_name(f".{tp_.name}.revision-tmp")
    try:
        tmp.write_text(revised, encoding="utf-8")
        os.replace(tmp, tp_)
    except Exception as e:
        logger.error(f"[{job_id}] Could not save revised translation ({e}); first-pass translation kept.")
        report.update(status="error", reason="write_failed")
        return report
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    import difflib
    changed = sum(1 for a, b in zip(draft.split("\n"), revised.split("\n")) if a != b)
    report.update(status="revised", changed_lines=changed,
                  similarity=round(difflib.SequenceMatcher(None, draft[:20000], revised[:20000]).quick_ratio(), 3),
                  duration_s=round(time.time() - started, 1))
    logger.info(f"[{job_id}] Maximum-quality revision applied ({changed} lines changed).")
    return report
