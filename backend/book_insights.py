"""
book_insights.py - Book Insights: AI summaries, synopses and their audio versions.

Reuses existing infrastructure only:
* Text extraction   -> backend.parsers.parse_document (PDF / DOCX / EPUB / TXT)
* AI generation     -> backend.ai_polisher._call_gemini_api (4-key pool, rotation, rate limiting,
                       quota circuit breaker, SQLite response cache, output sanitising)
* Greek post-edit   -> backend.output_refiner.refine_text_content (conservative, local)
* Export            -> backend.exporter.export_text (PDF / TXT) + python-docx headings (DOCX)
* Audio             -> backend.tts_engine chunk helpers (edge-tts) WITHOUT touching job state,
                       validated by backend.output_refiner.inspect_audiobook_quality

Generation never mutates the translation/audiobook job: results live in
temp/outputs/<job_id>/insights/ (a sub-folder, so existing download fallbacks never pick them up).

Large documents use map-reduce: the book is split into sections, each condensed into faithful
notes (cached, shared by every insight type and language), and the final text is written from the
notes. Every final text is machine-checked (language, length, sentence count, structure, numbers
and names absent from the source, similarity to the paired summary/synopsis) and regenerated once
if defective; output that still fails a critical check is never shown as a success.
"""

import re
import json
import time
import uuid
import asyncio
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INSIGHTS_VERSION = "1.1"                     # bump when prompts/checks change: invalidates stored results
WORDS_PER_PAGE = 250                         # standard manuscript page
MIN_SYNOPSIS_WORDS = int(WORDS_PER_PAGE * 1.5)   # 1.5 pages of meaningful text
MIN_SUMMARY_WORDS = 80                       # below this a summary would be unreliable
SINGLE_PASS_CHARS = 90_000                   # documents up to ~22k words are sent in one request
SECTION_CHARS = 45_000                       # map step section size for longer documents
MAX_NOTES_CHARS = 120_000                    # notes are condensed again above this
MAX_CONCURRENT_GENERATIONS = 2
TTS_STYLE = "standard"

INSIGHT_TYPES: Dict[str, Dict[str, Any]] = {
    "one_sentence":      {"kind": "summary",  "min": 20,   "max": 40,   "ratio": None},
    "short_summary":     {"kind": "summary",  "min": 150,  "max": 300,  "ratio": 0.35},
    "extended_summary":  {"kind": "summary",  "min": 500,  "max": 1000, "ratio": 0.50},
    "standard_synopsis": {"kind": "synopsis", "min": 800,  "max": 1200, "ratio": 0.60},
    "extended_synopsis": {"kind": "synopsis", "min": 1500, "max": 2500, "ratio": 0.85},
}
BASIC_TYPES = {"summary": "short_summary", "synopsis": "standard_synopsis"}
OUTPUT_LANGUAGES = ("greek", "english")
EXPORT_FORMATS = ("pdf", "docx", "txt")

TYPE_LABELS = {
    "greek": {
        "one_sentence": "Περίληψη μίας πρότασης", "short_summary": "Σύντομη περίληψη",
        "extended_summary": "Εκτενής περίληψη", "standard_synopsis": "Σύνοψη",
        "extended_synopsis": "Εκτενής σύνοψη",
    },
    "english": {
        "one_sentence": "One-sentence summary", "short_summary": "Short summary",
        "extended_summary": "Extended summary", "standard_synopsis": "Synopsis",
        "extended_synopsis": "Extended synopsis",
    },
}


class InsightsError(Exception):
    """Error with a stable code and a message written for ordinary users."""

    MESSAGES = {
        "unsupported_format": "Αυτός ο τύπος αρχείου δεν υποστηρίζεται για Book Insights. Χρησιμοποιήστε PDF, DOCX, EPUB ή TXT με κείμενο (όχι κόμικ/εικόνες).",
        "extraction_failed": "Δεν ήταν δυνατή η ανάγνωση κειμένου από το έγγραφο. Το αρχείο μπορεί να είναι κατεστραμμένο ή προστατευμένο.",
        "insufficient_text": "Το έγγραφο δεν περιέχει αρκετό αναγνώσιμο κείμενο για αξιόπιστη περίληψη. Αν είναι σαρωμένο (εικόνες), δεν υπάρχει εξαγώγιμο κείμενο.",
        "too_short": "Το έγγραφο είναι πολύ μικρό για σύνοψη: χρειάζεται τουλάχιστον ~1,5 σελίδα ουσιαστικού κειμένου.",
        "language_detection_failed": "Δεν ήταν δυνατός ο εντοπισμός της γλώσσας του εγγράφου. Επιλέξτε γλώσσα εξόδου στην Προχωρημένη Λειτουργία.",
        "no_api_key": "Για τα Book Insights απαιτείται κλειδί Google Gemini API. Προσθέστε ένα δωρεάν κλειδί από το κουμπί «🔑 Gemini API Key».",
        "quota_exhausted": "Εξαντλήθηκε το ημερήσιο όριο του Gemini API. Δοκιμάστε αργότερα ή προσθέστε άλλο κλειδί.",
        "rate_limited": "Πάρα πολλά αιτήματα προς το Gemini αυτή τη στιγμή. Περιμένετε λίγο και δοκιμάστε ξανά.",
        "auth_failed": "Το κλειδί Gemini API απορρίφθηκε. Ελέγξτε ότι είναι σωστό στις Ρυθμίσεις.",
        "network_error": "Πρόβλημα σύνδεσης με την υπηρεσία AI. Ελέγξτε τη σύνδεσή σας στο διαδίκτυο και δοκιμάστε ξανά.",
        "ai_failed": "Η δημιουργία κειμένου από το AI απέτυχε. Δοκιμάστε ξανά σε λίγο.",
        "ai_output_rejected": "Το AI παρήγαγε κείμενο που δεν πέρασε τον έλεγχο ποιότητας (π.χ. λάθος γλώσσα ή στοιχεία που δεν υπάρχουν στο βιβλίο), οπότε δεν εμφανίζεται. Δοκιμάστε ξανά.",
        "audio_failed": "Η δημιουργία ήχου απέτυχε. Ελέγξτε τη σύνδεσή σας και δοκιμάστε ξανά.",
        "audio_unsupported_language": "Ο ήχος είναι διαθέσιμος μόνο για ελληνικό ή αγγλικό κείμενο.",
        "export_failed": "Η αποθήκευση του αρχείου απέτυχε. Δοκιμάστε άλλη μορφή ή ελέγξτε τον ελεύθερο χώρο στον δίσκο.",
        "not_generated": "Δεν υπάρχει ακόμη αυτό το κείμενο. Δημιουργήστε το πρώτα.",
        "invalid_request": "Μη έγκυρη επιλογή.",
    }

    def __init__(self, code: str, detail: str = "", http_status: int = 400):
        self.code = code
        self.user_message = self.MESSAGES.get(code, self.MESSAGES["ai_failed"])
        self.detail = detail
        self.http_status = http_status
        super().__init__(f"{code}: {detail or self.user_message}")

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.user_message}


# ---------------------------------------------------------------------------
# Text extraction & analysis
# ---------------------------------------------------------------------------

_TEXT_CACHE: Dict[str, Tuple[float, str]] = {}
_TEXT_CACHE_MAX = 3
_SUPPORTED_TYPES = {"pdf", "docx", "epub", "txt"}

_WORD_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|['’\-])*[^\W\d_]|[^\W\d_]{2,}", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")


def extract_document_text(file_path: str, file_type: str) -> str:
    """Extracts plain text with the app's existing parsers (cached per file path + mtime)."""
    ft = (file_type or "").lower().lstrip(".")
    if ft not in _SUPPORTED_TYPES:
        raise InsightsError("unsupported_format", f"file_type={ft}")
    p = Path(file_path or "")
    if not p.is_file():
        raise InsightsError("extraction_failed", "source file missing", http_status=404)
    key = str(p.resolve())
    mtime = p.stat().st_mtime
    cached = _TEXT_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        from backend.parsers import parse_document
        parts = [pg.get("text", "") for pg in parse_document(str(p), ft)]
    except Exception as e:
        raise InsightsError("extraction_failed", str(e))
    text = "\n\n".join(t.strip() for t in parts if t and t.strip())
    if len(_TEXT_CACHE) >= _TEXT_CACHE_MAX:
        _TEXT_CACHE.pop(next(iter(_TEXT_CACHE)))
    _TEXT_CACHE[key] = (mtime, text)
    return text


def meaningful_text(text: str) -> str:
    """Drops lines that carry no content: page numbers, URLs, repeated running headers/footers."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    counts: Dict[str, int] = {}
    for ln in lines:
        if ln and len(ln) < 80:
            counts[ln] = counts.get(ln, 0) + 1
    kept = []
    for ln in lines:
        if not ln:
            kept.append("")
            continue
        if re.fullmatch(r"[\W\d_]+", ln):                      # numbers / punctuation only
            continue
        # running header/footer: short, repeated, and not shaped like a sentence (real repeated lines are kept)
        if (counts.get(ln, 0) >= 3 and len(ln.split()) <= 8 and len(ln) < 80
                and not re.search(r"[.!?;…»\"]$", ln)):
            continue
        kept.append(_URL_RE.sub(" ", ln))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


_EN_STOPWORDS = {"the", "and", "of", "to", "in", "is", "that", "it", "was", "for", "with", "as", "his", "her",
                 "on", "be", "at", "by", "this", "had", "not", "are", "but", "from", "they", "you", "which", "an"}


def detect_language(text: str) -> Optional[str]:
    """Returns 'greek', 'english', 'other' (another Latin-script language) or None if undeterminable."""
    sample = (text or "")[:20000]
    greek = sum(1 for ch in sample if "Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿")
    latin = sum(1 for ch in sample if ch.isascii() and ch.isalpha())
    other_letters = sum(1 for ch in sample if ch.isalpha()) - greek - latin
    total = greek + latin + max(other_letters, 0)
    if total < 50:
        return None
    if greek / total >= 0.5:
        return "greek"
    if latin / total >= 0.5:
        words = [w.lower() for w in re.findall(r"[A-Za-z]+", sample)]
        if words and sum(1 for w in words if w in _EN_STOPWORDS) / len(words) >= 0.06:
            return "english"
        return "other"
    return None


def analyze_text(text: str) -> Dict[str, Any]:
    """Length/language eligibility used by both the UI and the generator."""
    clean = meaningful_text(text)
    words = count_words(clean)
    lang = detect_language(clean)
    pages = round(words / WORDS_PER_PAGE, 1)
    can_summary = words >= MIN_SUMMARY_WORDS
    can_synopsis = words >= MIN_SYNOPSIS_WORDS
    reasons = {}
    if not can_summary:
        reasons["summary"] = InsightsError.MESSAGES["insufficient_text"]
    if not can_synopsis:
        reasons["synopsis"] = (
            f"{InsightsError.MESSAGES['too_short']} Το έγγραφο έχει περίπου {words} λέξεις "
            f"(~{pages} σελίδες)· απαιτούνται τουλάχιστον {MIN_SYNOPSIS_WORDS}."
        )
    return {
        "meaningful_words": words,
        "estimated_pages": pages,
        "detected_language": lang,
        "can_summary": can_summary,
        "can_synopsis": can_synopsis,
        "min_summary_words": MIN_SUMMARY_WORDS,
        "min_synopsis_words": MIN_SYNOPSIS_WORDS,
        "reasons": reasons,
    }


def target_word_range(insight_type: str, source_words: int) -> Tuple[int, int]:
    """Guideline range, scaled down for short sources so the model is never pushed to pad/invent."""
    spec = INSIGHT_TYPES[insight_type]
    lo, hi = spec["min"], spec["max"]
    if spec["ratio"] is None:
        return lo, hi
    cap = int(source_words * spec["ratio"])
    if cap < hi:
        hi = max(cap, 40 if spec["kind"] == "summary" else 80)
        lo = min(lo, max(int(hi * 0.6), 25))
    return lo, hi


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_LANG_NAMES = {"greek": "Modern Greek (monotonic orthography)", "english": "English"}

_COMMON_RULES = (
    "STRICT RULES:\n"
    "1. Use ONLY information that is explicitly present in the source. Never invent names, events, dates, numbers, "
    "quotations or conclusions. If something is unclear in the source, leave it out.\n"
    "2. Preserve the original meaning, context and the author's position; do not add opinions, praise or criticism.\n"
    "3. Fiction: preserve plot, main characters, their relationships and the key developments, in order. "
    "Non-fiction: preserve the main arguments, key concepts, evidence and conclusions.\n"
    "4. No repetition, no filler, no meta-commentary (do not write 'This summary...', 'Here is...', word counts or notes).\n"
    "5. Write every proper name in the script of the output language, transliterated consistently (always the same "
    "form for the same person or place). Translate chapter and section titles into the output language.\n"
    "6. Keep every event at its correct point in the work; never merge separate events or attribute an action to the "
    "wrong person or moment.\n"
    "7. Condense: the output must always be much shorter than the source; never retell it sentence by sentence.\n"
)


def _language_instruction(language: str) -> str:
    if language == "greek":
        return ("Write the entire output in Modern Greek (monotonic orthography) with flawless spelling, accentuation "
                "and grammar, regardless of the source language. Write all names in Greek script "
                "(e.g. 'Lena' -> 'Λένα'); do not leave Latin-script words in the text except inside «» quotes.")
    if language in _LANG_NAMES:
        return f"Write the entire output in {_LANG_NAMES[language]}, regardless of the source language."
    return "Write the entire output in the SAME language as the source text."


def build_prompt(insight_type: str, language: str, lo: int, hi: int, from_notes: bool, title: str) -> str:
    src = ("The source below consists of faithful, ordered notes covering the WHOLE document, section by section."
           if from_notes else "The source below is the full text of the document.")
    head = f"You are an expert literary and academic editor. Document title: \"{title}\".\n{src}\n{_language_instruction(language)}\n"
    if insight_type == "one_sentence":
        task = ("TASK: Write a ONE-SENTENCE SUMMARY: exactly one grammatical sentence of {lo}-{hi} words capturing the "
                "central subject and the essential point or outcome of the document. No heading, no line breaks, no list.")
    elif insight_type == "short_summary":
        task = ("TASK: Write a SHORT SUMMARY of about {lo}-{hi} words: a concise condensation of the essential "
                "information and central ideas (or the core plot arc), in 1-3 well-formed paragraphs. No headings.")
    elif insight_type == "extended_summary":
        task = ("TASK: Write an EXTENDED SUMMARY of about {lo}-{hi} words covering the main arguments or plot, key "
                "concepts, important details, the document's structure and its conclusions. Organise it in paragraphs "
                "under 2-5 short Markdown headings ('## Heading').")
    elif insight_type == "standard_synopsis":
        task = ("TASK: Write a STANDARD SYNOPSIS of about {lo}-{hi} words. A synopsis is NOT a summary: it is a "
                "structured overview of the whole work that follows its progression from beginning to end. Use Markdown "
                "headings ('## Heading') for: subject/genre and premise; structure (parts/chapters and how the work "
                "progresses); main themes; important developments (fiction: characters, relationships, turning points "
                "and the ending; non-fiction: line of argument, key concepts and evidence); conclusions.")
    elif insight_type == "extended_synopsis":
        task = ("TASK: Write an EXTENDED SYNOPSIS of about {lo}-{hi} words: a substantially more detailed examination "
                "than a standard synopsis. Use Markdown headings ('## ' for sections, '### ' for parts/chapters) to "
                "cover: subject and premise; the structure chapter by chapter (or part by part) in order; how the "
                "arguments or plot progress; characters/key figures and their relationships, or key concepts and "
                "evidence; main themes and how they develop; the ending or conclusions.")
    else:
        raise InsightsError("invalid_request", insight_type)
    return head + task.format(lo=lo, hi=hi) + "\n" + _COMMON_RULES


_NOTES_PROMPT = (
    "You are preparing faithful research notes from ONE SECTION of a longer document, so that a summary and a synopsis "
    "of the whole document can be written later. Write the notes in the SAME language as the section. Use concise "
    "bullet points, in the order they appear: chapter/section titles; events or arguments; characters or key figures "
    "and their relationships; concepts, evidence, names, dates and numbers exactly as written; conclusions or turning "
    "points. Use ONLY what the section says; never add interpretation or information. Maximum ~700 words. "
    "No introduction or closing remarks."
)


_GREEK_PROOFREAD_PROMPT = (
    "You are a professional Greek proofreader. Correct ONLY spelling, accentuation, grammar, syntax and awkward "
    "phrasing in the Modern Greek text below, and transliterate any remaining Latin-script proper names or titles into "
    "Greek consistently. Do NOT add, remove, reorder or reinterpret information. Keep every Markdown heading ('## ', "
    "'### '), bullet and paragraph break exactly where it is. Return only the corrected text."
)


# ---------------------------------------------------------------------------
# Gemini access (reuses the app's pool, rate limiter, circuit breaker and cache)
# ---------------------------------------------------------------------------

def _classify_ai_error(e: BaseException) -> InsightsError:
    from backend.ai_polisher import DailyQuotaExhaustedError
    msg = str(e).lower()
    if isinstance(e, InsightsError):
        return e
    if isinstance(e, DailyQuotaExhaustedError) or "quota" in msg or "resource_exhausted" in msg or "εξαντλήθηκε" in msg:
        return InsightsError("quota_exhausted", str(e), http_status=429)
    if "429" in msg or ("rate" in msg and "limit" in msg):
        return InsightsError("rate_limited", str(e), http_status=429)
    if isinstance(e, PermissionError) or "authentication" in msg or "api key not valid" in msg or "401" in msg or "403" in msg:
        return InsightsError("auth_failed", str(e), http_status=401)
    try:
        import aiohttp
        if isinstance(e, (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError)):
            return InsightsError("network_error", str(e), http_status=503)
    except Exception:
        pass
    if isinstance(e, (asyncio.TimeoutError, ConnectionError, OSError)) or "timeout" in msg or "cannot connect" in msg:
        return InsightsError("network_error", str(e), http_status=503)
    return InsightsError("ai_failed", str(e), http_status=502)


async def _ai(content: str, system_prompt: str, api_key: str, session, temperature: float = 0.3,
              bypass_cache: bool = False) -> str:
    from backend.ai_polisher import _call_gemini_api
    try:
        out = await _call_gemini_api(content, api_key, system_prompt, session=session,
                                     temperature=temperature, bypass_cache=bypass_cache)
    except Exception as e:
        raise _classify_ai_error(e) from e
    if not out or not out.strip():
        raise InsightsError("ai_failed", "empty response", http_status=502)
    return out


def split_sections(text: str, max_chars: int = SECTION_CHARS) -> List[str]:
    """Splits on paragraph boundaries into sections of at most ~max_chars."""
    sections, buf, size = [], [], 0
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > max_chars:  # pathological giant paragraph
            sections.append(para[:max_chars])
            para = para[max_chars:]
        if size + len(para) > max_chars and buf:
            sections.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        sections.append("\n\n".join(buf))
    return sections


async def build_source_material(text: str, api_key: str, session,
                                progress: Optional[Callable[[int, str], None]] = None) -> Tuple[str, bool]:
    """Returns (material, from_notes). Short documents are used verbatim; long ones are condensed to notes."""
    if len(text) <= SINGLE_PASS_CHARS:
        return text, False
    sections = split_sections(text)
    notes: List[Optional[str]] = [None] * len(sections)
    sem = asyncio.Semaphore(2)
    done = 0

    async def _one(i: int, sec: str):
        nonlocal done
        async with sem:
            notes[i] = await _ai(sec, _NOTES_PROMPT, api_key, session, temperature=0.1)
        done += 1
        if progress:
            progress(10 + int(60 * done / len(sections)), f"Ανάλυση ενότητας {done}/{len(sections)}…")

    await asyncio.gather(*(_one(i, s) for i, s in enumerate(sections)))
    material = "\n\n".join(f"### Section {i + 1} of {len(sections)}\n{n.strip()}" for i, n in enumerate(notes))
    if len(material) > MAX_NOTES_CHARS:  # second-level condensation for very long books
        groups = split_sections(material, MAX_NOTES_CHARS // 3)
        condensed = []
        for gi, g in enumerate(groups):
            condensed.append(await _ai(g, _NOTES_PROMPT, api_key, session, temperature=0.1))
            if progress:
                progress(70 + int(10 * (gi + 1) / len(groups)), "Συμπύκνωση σημειώσεων…")
        material = "\n\n".join(f"### Part {i + 1}\n{c.strip()}" for i, c in enumerate(condensed))
    return material, True


# ---------------------------------------------------------------------------
# Output normalisation & quality checks
# ---------------------------------------------------------------------------

_META_LINE_RE = re.compile(
    r"^\s*(?:\*\*)?(?:word\s*count|λέξεις|αριθμός λέξεων|note|σημείωση|here is|ακολουθεί|this (?:summary|synopsis))\b.*$",
    re.IGNORECASE,
)


def normalize_output(text: str, language: str) -> str:
    out = (text or "").replace("\r\n", "\n").strip()
    out = "\n".join(ln for ln in out.split("\n") if not _META_LINE_RE.match(ln))
    out = re.sub(r"^\s*#{1}\s+", "## ", out, flags=re.MULTILINE)          # single '#' -> '##'
    out = re.sub(r"^\s*#{4,}\s+", "### ", out, flags=re.MULTILINE)
    out = re.sub(r"^\s*\*\*([^*\n]{2,80})\*\*\s*$", r"## \1", out, flags=re.MULTILINE)  # bold-only line -> heading
    out = re.sub(r"^\s*[*•]\s+", "- ", out, flags=re.MULTILINE)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if language == "english":  # AI stutters such as 'Mechanical Mechanical' (Greek reduplication is left alone)
        out = re.sub(r"\b([A-Za-z]{4,})\s+\1\b", r"\1", out, flags=re.IGNORECASE)
    if language == "greek":
        try:
            from backend.output_refiner import refine_text_content
            out = refine_text_content(out, target_lang="greek")[0] or out
        except Exception as e:
            logger.debug(f"Greek refinement of insight skipped: {e}")
    return out


def _heading_count(text: str) -> int:
    return len(re.findall(r"^#{2,3}\s", text, flags=re.MULTILINE))


async def _proofread_greek(text: str, api_key: str, session) -> str:
    """One conservative proofreading pass; kept only if structure and length are preserved."""
    try:
        fixed = normalize_output(await _ai(text, _GREEK_PROOFREAD_PROMPT, api_key, session, temperature=0.1), "greek")
    except InsightsError as e:
        if e.code in ("quota_exhausted", "rate_limited", "auth_failed"):
            raise
        logger.warning(f"Greek proofreading skipped: {e}")
        return text
    w0, w1 = _plain_words(text), _plain_words(fixed)
    if _heading_count(fixed) != _heading_count(text) or not (0.85 * w0 <= w1 <= 1.15 * w0):
        logger.warning("Greek proofreading changed structure/length; keeping the unproofread draft.")
        return text
    return fixed


def _latin_share_outside_quotes(text: str) -> float:
    body = re.sub(r"«[^»]*»", " ", text)
    all_words = _WORD_RE.findall(body)
    latin = [w for w in all_words if re.fullmatch(r"[A-Za-z'’\-]+", w)]
    return len(latin) / max(len(all_words), 1)


def _plain_words(text: str) -> int:
    body = re.sub(r"^#{2,3}\s+.*$", "", text, flags=re.MULTILINE)
    return count_words(body)


def _sentence_count(text: str) -> int:
    s = re.sub(r"\s+", " ", text.strip())
    return len(re.findall(r"[.!?;…](?=\s+[\"«(]?[A-ZΑ-ΩΆΈΉΊΌΎΏ])", s)) + 1


def _shingles(text: str, n: int = 3) -> set:
    w = [x.lower() for x in _WORD_RE.findall(text)]
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def similarity(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _unknown_numbers(output: str, source: str) -> List[str]:
    src_nums = set(re.findall(r"\d+", source.replace(",", "").replace(".", "")))
    # 3+ digits only (years, amounts): chapter numbers like "12" may be spelled out in the source
    out_nums = re.findall(r"\b\d{3,}\b", output.replace(",", ""))
    return sorted({n for n in out_nums if n not in src_nums})


def _unknown_names(output: str, source: str) -> List[str]:
    """Capitalised tokens (not sentence-initial, not in headings) that never occur in the source."""
    src_words = {w.lower() for w in _WORD_RE.findall(source)}
    prefixes = {w[:5] for w in src_words if len(w) >= 5}
    unknown = set()
    for line in output.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        line = re.sub(r"\*\*[^*]+\*\*", " ", line)   # bold labels act as headings
        for m in re.finditer(r"(?<=[^\s.!?;:«\"(\-—])\s+([A-ZΑ-ΩΆΈΉΊΌΎΏ][\w’'-]{2,})", line):
            tok = m.group(1).strip("’'-").lower()
            if tok in src_words or (len(tok) >= 5 and tok[:5] in prefixes):
                continue
            unknown.add(m.group(1))
    return sorted(unknown)


def validate_output(text: str, insight_type: str, language: str, lo: int, hi: int,
                    source: str, source_language: Optional[str]) -> Tuple[List[str], List[str]]:
    """Returns (critical_problems, warnings). Critical problems block display."""
    critical, warnings = [], []
    if not text or count_words(text) < 5:
        return ["empty or near-empty output"], warnings
    letters = [ch for ch in text if ch.isalpha()]
    greek_share = sum(1 for ch in letters if "Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿") / max(len(letters), 1)
    if language == "greek" and greek_share < 0.6:
        critical.append("output is not in Greek")
    if language == "english" and greek_share > 0.2:
        critical.append("output is not in English")
    if language == "greek" and greek_share >= 0.6:
        latin = _latin_share_outside_quotes(text)
        if latin > 0.04:
            critical.append(f"{latin:.0%} of the words are in Latin script; names and titles must be written in Greek")
        elif latin > 0.01:
            warnings.append("a few Latin-script words remain")
    if re.search(r"</?(?:SOURCE|DOCUMENT|TEXT)[^>]*>|ΚΕΙΜΕΝΟ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ|STRICT RULES|TASK:", text):
        critical.append("prompt text leaked into output")

    words = _plain_words(text)
    if insight_type == "one_sentence":
        if "\n" in text.strip() or _sentence_count(text) != 1:
            critical.append("one-sentence summary is not exactly one sentence")
        if not (15 <= words <= 50):
            critical.append(f"one-sentence summary has {words} words (target {lo}-{hi})")
    else:
        if words < lo * 0.6:
            critical.append(f"output too short: {words} words (target {lo}-{hi})")
        elif words < lo * 0.85 or words > hi * 1.25:
            warnings.append(f"length {words} words is outside the guideline {lo}-{hi}")
        if words > hi * 1.8:
            critical.append(f"output far too long: {words} words (target {lo}-{hi})")
        src_words = count_words(source)
        if src_words and words > 0.9 * src_words:
            critical.append(f"output ({words} words) is almost as long as the source ({src_words}); it must condense")
    headings = len(re.findall(r"^#{2,3}\s+\S", text, flags=re.MULTILINE))
    if INSIGHT_TYPES[insight_type]["kind"] == "synopsis" and headings < 2:
        warnings.append("synopsis has fewer than two section headings")

    nums = _unknown_numbers(text, source)
    if len(nums) >= 2:
        critical.append(f"numbers not found in the source: {', '.join(nums[:5])}")
    elif nums:
        warnings.append(f"number not found in the source: {nums[0]}")
    if source_language == language or (source_language == "other" and language not in OUTPUT_LANGUAGES):
        names = _unknown_names(text, source)
        if len(names) > 3:
            critical.append(f"names not found in the source: {', '.join(names[:6])}")
        elif names:
            warnings.append(f"unverified names: {', '.join(names)}")
    return critical, warnings


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def insights_dir(job_output_dir: Path) -> Path:
    d = Path(job_output_dir) / "insights"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stem(insight_type: str, language: str) -> str:
    return f"{insight_type}_{language}"


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def save_insight(job_output_dir: Path, record: Dict[str, Any]) -> None:
    d = insights_dir(job_output_dir)
    stem = _stem(record["insight_type"], record["language"])
    # A new text invalidates audio/exports made from an older version
    for old in d.glob(f"*{stem}.*"):
        if old.suffix.lower() in (".mp3", ".pdf", ".docx", ".txt"):
            try:
                old.unlink()
            except OSError:
                pass
    _write_json_atomic(d / f"{stem}.json", record)


def load_insight(job_output_dir: Path, insight_type: str, language: str) -> Optional[Dict[str, Any]]:
    p = Path(job_output_dir) / "insights" / f"{_stem(insight_type, language)}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_insights(job_output_dir: Path) -> List[Dict[str, Any]]:
    d = Path(job_output_dir) / "insights"
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
                out.append({k: rec.get(k) for k in ("insight_type", "kind", "language", "word_count", "created_at", "audio_file")})
            except Exception:
                continue
    return out


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

async def generate_insight(
    text: str,
    insight_type: str,
    language: Optional[str],
    api_key: str,
    title: str = "Document",
    job_output_dir: Optional[Path] = None,
    progress: Optional[Callable[[int, str], None]] = None,
    session=None,
) -> Dict[str, Any]:
    """Generates, checks and (optionally) stores one insight. Raises InsightsError on failure."""
    if insight_type not in INSIGHT_TYPES:
        raise InsightsError("invalid_request", f"unknown type {insight_type}")
    spec = INSIGHT_TYPES[insight_type]
    clean = meaningful_text(text)
    info = analyze_text(clean)
    if not info["can_summary"]:
        raise InsightsError("insufficient_text", f"{info['meaningful_words']} words", http_status=422)
    if spec["kind"] == "synopsis" and not info["can_synopsis"]:
        raise InsightsError("too_short", f"{info['meaningful_words']} words", http_status=422)
    src_lang = info["detected_language"]
    out_lang = (language or "").strip().lower() or None
    if out_lang in (None, "auto"):
        if src_lang is None:
            raise InsightsError("language_detection_failed", http_status=422)
        out_lang = src_lang if src_lang in OUTPUT_LANGUAGES else "other"
    elif out_lang not in OUTPUT_LANGUAGES:
        raise InsightsError("invalid_request", f"language {out_lang}")
    if not (api_key or "").strip():
        raise InsightsError("no_api_key", http_status=401)

    source_hash = _text_hash(clean)
    if job_output_dir is not None:
        existing = load_insight(job_output_dir, insight_type, out_lang)
        if (existing and existing.get("source_hash") == source_hash and existing.get("text")
                and existing.get("version") == INSIGHTS_VERSION):
            if progress:
                progress(100, "Έτοιμο (αποθηκευμένο αποτέλεσμα)")
            existing["reused"] = True
            return existing

    lo, hi = target_word_range(insight_type, info["meaningful_words"])
    owns_session = session is None
    if owns_session:
        import aiohttp
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240))
    try:
        if progress:
            progress(5, "Προετοιμασία κειμένου…")
        material, from_notes = await build_source_material(clean, api_key, session, progress)
        prompt = build_prompt(insight_type, out_lang, lo, hi, from_notes, title)

        paired = None
        if job_output_dir is not None:
            other_kind_types = [t for t, s in INSIGHT_TYPES.items() if s["kind"] != spec["kind"]]
            for t in other_kind_types:
                rec = load_insight(job_output_dir, t, out_lang)
                if rec and rec.get("text"):
                    paired = rec["text"]
                    break

        last_critical: List[str] = []
        result_text, warnings = "", []
        for attempt in range(2):
            if progress:
                progress(82 if attempt == 0 else 90, "Συγγραφή κειμένου…" if attempt == 0 else "Διόρθωση & επανέλεγχος…")
            p = prompt
            if attempt and last_critical:
                p += ("\nYOUR PREVIOUS ATTEMPT WAS REJECTED BECAUSE: " + "; ".join(last_critical) +
                      ". Fix these problems and follow every rule exactly.")
            raw = await _ai(material, p, api_key, session, temperature=0.3 if attempt == 0 else 0.15,
                            bypass_cache=attempt > 0)
            candidate = normalize_output(raw, out_lang)
            if out_lang == "greek":
                if progress:
                    progress(88 if attempt == 0 else 94, "Γλωσσική επιμέλεια ελληνικού κειμένου…")
                candidate = await _proofread_greek(candidate, api_key, session)
            critical, warns = validate_output(candidate, insight_type, out_lang, lo, hi, clean, src_lang)
            if paired and similarity(candidate, paired) > 0.6:
                critical.append("too similar to the existing " + ("synopsis" if spec["kind"] == "summary" else "summary"))
            if not critical:
                result_text, warnings = candidate, warns
                break
            last_critical = critical
            logger.warning(f"Book Insights '{insight_type}' attempt {attempt + 1} rejected: {critical}")
        if not result_text:
            raise InsightsError("ai_output_rejected", "; ".join(last_critical), http_status=502)
    finally:
        if owns_session:
            await session.close()

    record = {
        "version": INSIGHTS_VERSION,
        "insight_type": insight_type,
        "kind": spec["kind"],
        "language": out_lang,
        "source_language": src_lang,
        "title": title,
        "label": TYPE_LABELS.get(out_lang, TYPE_LABELS["english"])[insight_type],
        "text": result_text,
        "word_count": _plain_words(result_text),
        "target_words": [lo, hi],
        "warnings": warnings,
        "from_notes": from_notes,
        "source_words": info["meaningful_words"],
        "source_hash": source_hash,
        "text_hash": _text_hash(result_text),
        "created_at": time.time(),
        "audio_file": None,
    }
    if job_output_dir is not None:
        save_insight(job_output_dir, record)
    if progress:
        progress(100, "Έτοιμο")
    return record


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def markdown_to_plain(text: str) -> str:
    out = []
    for ln in text.split("\n"):
        m = re.match(r"^#{2,3}\s+(.*)$", ln)
        if m:
            out.extend(["", m.group(1).strip(), ""])
            continue
        ln = re.sub(r"^\s*-\s+", "• ", ln)
        out.append(re.sub(r"\*\*(.+?)\*\*", r"\1", ln))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _safe_name(s: str) -> str:
    return (re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_") or "document")[:60]


def export_insight(record: Dict[str, Any], job_output_dir: Path, fmt: str) -> Path:
    fmt = (fmt or "").strip().lower()
    if fmt == "doc":
        fmt = "docx"
    if fmt not in EXPORT_FORMATS:
        raise InsightsError("invalid_request", f"format {fmt}")
    d = insights_dir(job_output_dir)
    base = f"{_safe_name(record.get('title') or 'document')}_{_stem(record['insight_type'], record['language'])}"
    heading = f"{record.get('label', '')}: {record.get('title', '')}".strip(": ")
    try:
        if fmt == "docx":
            from docx import Document
            doc = Document()
            doc.add_heading(heading, level=1)
            for block in re.split(r"\n\s*\n", record["text"]):
                for ln in block.split("\n"):
                    m = re.match(r"^(#{2,3})\s+(.*)$", ln)
                    if m:
                        doc.add_heading(m.group(2).strip(), level=2 if len(m.group(1)) == 2 else 3)
                    elif re.match(r"^\s*-\s+", ln):
                        doc.add_paragraph(re.sub(r"\*\*(.+?)\*\*", r"\1", re.sub(r"^\s*-\s+", "", ln)), style="List Bullet")
                    elif ln.strip():
                        doc.add_paragraph(re.sub(r"\*\*(.+?)\*\*", r"\1", ln.strip()))
            out = d / f"{base}.docx"
            tmp = d / f".{base}.{uuid.uuid4().hex[:6]}.docx.part"
            doc.save(str(tmp))
            tmp.replace(out)
            return out
        from backend.exporter import export_text
        plain = f"{heading}\n\n{markdown_to_plain(record['text'])}"
        out = Path(export_text(plain, d, fmt, base, layout="standard", cover_image=None))
        if not out.is_file() or out.stat().st_size == 0:
            raise RuntimeError("empty export")
        return out
    except InsightsError:
        raise
    except Exception as e:
        logger.error(f"Book Insights export ({fmt}) failed: {e}")
        raise InsightsError("export_failed", str(e), http_status=500)


# ---------------------------------------------------------------------------
# Audio (reuses edge-tts helpers; never touches job state)
# ---------------------------------------------------------------------------

def speech_text(text: str) -> str:
    """The exact final text, minus Markdown markers; headings become their own spoken sentences."""
    lines = []
    for ln in text.split("\n"):
        m = re.match(r"^#{2,3}\s+(.*)$", ln)
        if m:
            h = m.group(1).strip()
            lines.append(h if re.search(r"[.!?;:…]$", h) else h + ".")
            continue
        ln = re.sub(r"^\s*-\s+", "", ln)
        lines.append(re.sub(r"\*\*(.+?)\*\*", r"\1", ln))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


async def synthesize_insight_audio(record: Dict[str, Any], job_output_dir: Path,
                                   voice_name: Optional[str] = None,
                                   progress: Optional[Callable[[int, str], None]] = None) -> Path:
    language = record.get("language")
    if language not in OUTPUT_LANGUAGES:
        raise InsightsError("audio_unsupported_language")
    from backend import tts_engine as tts
    from backend.parsers import split_into_chunks
    from backend.output_refiner import inspect_audiobook_quality

    d = insights_dir(job_output_dir)
    stem = _stem(record["insight_type"], language)
    out = d / f"{_safe_name(record.get('title') or 'document')}_{stem}.mp3"
    if record.get("audio_file") and record.get("audio_text_hash") == record.get("text_hash") and (d / record["audio_file"]).is_file():
        return d / record["audio_file"]

    spoken = speech_text(record["text"])
    chunks = [c for c in split_into_chunks(spoken, tts.TTS_CHUNK_SIZE) if c.strip()]
    if not chunks:
        raise InsightsError("audio_failed", "nothing to speak")
    voice = tts._resolve_voice_code(language, voice_name, fallback_default=True)
    tmp_dir = d / f".tts_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir()
    sem = asyncio.Semaphore(tts.TTS_CONCURRENCY)
    done = 0

    async def _one(i: int, chunk: str) -> str:
        nonlocal done
        path = tmp_dir / f"chunk_{i:06d}.mp3"
        async with sem:
            await tts._tts_chunk_with_retry(chunk, voice, str(path),
                                            rate=tts.DEFAULT_RATES[TTS_STYLE], pitch=tts.DEFAULT_PITCHES[TTS_STYLE],
                                            narration_style=TTS_STYLE)
        done += 1
        if progress:
            progress(5 + int(85 * done / len(chunks)), f"Εκφώνηση τμήματος {done}/{len(chunks)}…")
        return str(path)

    try:
        files = await asyncio.gather(*(_one(i, c) for i, c in enumerate(chunks)))
        failed = [f for f in files if not Path(f).is_file() or Path(f).stat().st_size == 0]
        if failed:  # a silent gap would make the audio differ from the text -> fail loudly
            raise InsightsError("audio_failed", f"{len(failed)} of {len(files)} parts failed", http_status=503)
        staged = tmp_dir / "final.mp3"
        await tts._concatenate_mp3s(files, str(staged))
        tts.tag_audiobook_file(str(staged), title=f"{record.get('label', '')} - {record.get('title', '')}",
                               author="BookApp")
        ok, issues, _ = inspect_audiobook_quality(str(staged), files, expected_indices=list(range(len(files))))
        if not ok:
            raise InsightsError("audio_failed", "; ".join(i.description for i in issues), http_status=503)
        staged.replace(out)
    except InsightsError:
        raise
    except Exception as e:
        raise InsightsError("audio_failed", str(e), http_status=503)
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    record["audio_file"] = out.name
    record["audio_text_hash"] = record.get("text_hash")
    _write_json_atomic(d / f"{stem}.json", record)
    if progress:
        progress(100, "Ο ήχος είναι έτοιμος")
    return out


# ---------------------------------------------------------------------------
# Background tasks with duplicate-request protection
# ---------------------------------------------------------------------------

@dataclass
class InsightTask:
    task_id: str
    job_id: str
    action: str                 # 'generate' | 'audio'
    insight_type: str
    language: Optional[str]
    status: str = "queued"      # queued | running | done | error
    progress: int = 0
    step: str = "Σε αναμονή…"
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, str]] = None
    created_at: float = field(default_factory=time.time)

    def public(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in ("task_id", "job_id", "action", "insight_type", "language",
                                              "status", "progress", "step", "result", "error")}


_TASKS: Dict[str, InsightTask] = {}
_ACTIVE: Dict[Tuple[str, str, str, str], str] = {}
_GEN_SEM: Optional[asyncio.Semaphore] = None
_MAX_TASKS = 200


def _sem() -> asyncio.Semaphore:
    global _GEN_SEM
    if _GEN_SEM is None:
        _GEN_SEM = asyncio.Semaphore(MAX_CONCURRENT_GENERATIONS)
    return _GEN_SEM


def get_task(task_id: str) -> Optional[InsightTask]:
    return _TASKS.get(task_id)


def _prune():
    if len(_TASKS) <= _MAX_TASKS:
        return
    finished = sorted((t for t in _TASKS.values() if t.status in ("done", "error")), key=lambda t: t.created_at)
    for t in finished[: len(_TASKS) - _MAX_TASKS]:
        _TASKS.pop(t.task_id, None)


def start_task(job_id: str, action: str, insight_type: str, language: Optional[str],
               runner: Callable[[InsightTask], Any]) -> Tuple[InsightTask, bool]:
    """Starts a background task, or returns the already-running identical one (duplicate=True)."""
    key = (job_id, action, insight_type, language or "auto")
    existing_id = _ACTIVE.get(key)
    if existing_id and existing_id in _TASKS and _TASKS[existing_id].status in ("queued", "running"):
        return _TASKS[existing_id], True
    task = InsightTask(task_id=uuid.uuid4().hex, job_id=job_id, action=action,
                       insight_type=insight_type, language=language)
    _TASKS[task.task_id] = task
    _ACTIVE[key] = task.task_id
    _prune()

    async def _wrapper():
        try:
            async with _sem():
                task.status = "running"
                task.result = await runner(task)
                task.status, task.progress, task.step = "done", 100, "Έτοιμο"
        except InsightsError as e:
            logger.warning(f"Book Insights task {task.task_id} ({action}/{insight_type}) failed: {e}")
            task.status, task.error = "error", e.to_dict()
        except Exception as e:  # never leave a task hanging in 'running'
            logger.error(f"Book Insights task {task.task_id} crashed: {e}", exc_info=True)
            task.status, task.error = "error", _classify_ai_error(e).to_dict()
        finally:
            if _ACTIVE.get(key) == task.task_id:
                _ACTIVE.pop(key, None)

    asyncio.get_running_loop().create_task(_wrapper())
    return task, False
