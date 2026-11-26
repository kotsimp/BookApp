"""
Translator Engine - chunked English <-> Greek translation without AI polish.
Engines, in order: Google's public endpoint (it has refused most clients since September 2026; a refusal is respected
with a growing pause), MyMemory (requests of at most 500 characters and a small daily allowance), deep_translator,
and Gemini when a key is saved (batched while Google refuses).
"""

import asyncio
import contextvars
import html
import logging
import time
import urllib.request
import urllib.parse
import urllib.error
import json
import re
from pathlib import Path
from typing import Callable, Optional

import aiohttp
from deep_translator import GoogleTranslator
from backend.parsers import parse_document, split_into_chunks
from backend.job_manager import update_job, is_job_cancelled

logger = logging.getLogger(__name__)

# Language codes for Google Translate
LANG_CODES = {
    "english": "en",
    "greek": "el",
}

# Maximum characters per translation request (4000 reduces HTTP round-trips by ~40%)
CHUNK_SIZE = 4000

# Inter-chunk delay in seconds (lightweight pacing)
RATE_LIMIT_DELAY = 0.08

# Circuit-breaker: no request goes to Google until then. Each further refusal doubles the pause.
_GTX_COOLDOWN_UNTIL = 0.0
_GTX_REFUSALS = 0
_GTX_PAUSE = (60.0, 900.0)  # first, longest

# MyMemory's free allowance is small; when it is used up the service says how long to wait
_MYMEMORY_PAUSED_UNTIL = 0.0
_MYMEMORY_LIMIT = 480  # characters per request (the service refuses more than 500)

_FAILOVER_BATCH_CHARS = 12000  # few requests: the free Gemini allowance is counted per request

_ENGINES: contextvars.ContextVar[Optional[set]] = contextvars.ContextVar("translation_engines", default=None)

# Waits between rounds when every engine is unavailable for a moment
RETRY_ROUND_DELAYS = (5.0, 21.0, 30.0, 45.0)


_MAX_ENGINE_CHARS = 4800  # the fallback engines refuse more


def _split_keeping_separators(text: str, limit: int) -> list[str]:
    """Pieces of at most `limit` characters that join back to exactly `text`, cut at the best boundary."""
    pieces = []
    while len(text) > limit:
        window, cut = text[:limit], limit
        for sep in ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "):
            at = window.rfind(sep, limit // 2)
            if at > 0:
                cut = at + len(sep)
                break
        pieces.append(text[:cut])
        text = text[cut:]
    return pieces + [text]


class TranslationUnavailableError(RuntimeError):
    """No engine could translate the text. Untranslated text must never be passed off as a translation."""


def start_engine_tracking() -> set:
    """The returned set collects the engines that translate for the current job."""
    used: set = set()
    _ENGINES.set(used)
    return used


def _used(engine: str) -> None:
    used = _ENGINES.get()
    if used is not None:
        used.add(engine)


def google_is_refusing() -> bool:
    return time.time() < _GTX_COOLDOWN_UNTIL


def _note_google_refusal() -> None:
    global _GTX_COOLDOWN_UNTIL, _GTX_REFUSALS
    if google_is_refusing():
        return  # requests that were under way together count once
    _GTX_REFUSALS += 1
    first, longest = _GTX_PAUSE
    _GTX_COOLDOWN_UNTIL = time.time() + min(longest, first * 2 ** min(_GTX_REFUSALS - 1, 8))


def _note_google_answer() -> None:
    global _GTX_REFUSALS
    _GTX_REFUSALS = 0


def _note_mymemory_limit(headers) -> None:
    global _MYMEMORY_PAUSED_UNTIL
    try:
        seconds = float(headers.get("Retry-After"))
    except (AttributeError, TypeError, ValueError):
        seconds = 3600.0
    _MYMEMORY_PAUSED_UNTIL = time.time() + min(86400.0, max(60.0, seconds))


def _failover_key() -> str:
    """The Gemini key that may stand in for the free engines, or ""."""
    try:
        from backend.gemini_key_pool import resolve_gemini_api_key
        key = resolve_gemini_api_key()
        if not key or key.startswith(("AQ.Test", "AIzaTest")):
            return ""
        from backend.ai_polisher import is_gemini_quota_exhausted
        return "" if is_gemini_quota_exhausted() else key
    except Exception as ex:
        logger.debug(f"Gemini failover check error: {ex}")
        return ""


def _untranslated(result: str, text: str, target_lang: str) -> bool:
    if target_lang.lower() in ("english", "en"):
        in_greek = len(re.findall(r"[Ͱ-Ͽἀ-῿]", result))
        return in_greek >= 20 and in_greek > len(re.findall(r"[a-zA-Z]", result))
    return (target_lang.lower() in ("greek", "el", "gr") and not re.search(r"[Ͱ-Ͽ]", result)
            and len(re.findall(r"[a-zA-Z]", text)) > 30)


def _unusable(result: str, text: str, target_lang: str) -> bool:
    """An AI answer that stayed in the source language, or lost much of the text."""
    return _untranslated(result, text, target_lang) or (len(text) > 200 and len(result.strip()) < 0.5 * len(text))


def _cached(text: str, source_lang: str, target_lang: str) -> Optional[str]:
    try:
        from backend.database import compute_cache_key, db_get_cached_translation
        return db_get_cached_translation(compute_cache_key(text, source_lang, target_lang, engine="google_v2"))
    except Exception as ex:
        logger.debug(f"Cache check skipped: {ex}")
        return None


def _remember(text: str, result: str, source_lang: str, target_lang: str) -> None:
    try:
        from backend.database import compute_cache_key, db_set_cached_translation
        key = compute_cache_key(text, source_lang, target_lang, engine="google_v2")  # v1 may hold fuzzy matches
        db_set_cached_translation(key, text, result, source_lang, target_lang, engine="google")
    except Exception as ex:
        logger.debug(f"Cache write skipped: {ex}")


async def _in_pieces(text: str, limit: int, translate_piece) -> Optional[str]:
    """`text` translated piece by piece with its line breaks kept; None as soon as a piece fails."""
    out = []
    for piece in _split_keeping_separators(text, limit):
        body = piece.strip()
        if any(ch.isalpha() for ch in body):
            done = await translate_piece(body)
            if done is None:
                return None
            piece = piece[:len(piece) - len(piece.lstrip())] + done.strip() + piece[len(piece.rstrip()):]
        out.append(piece)
    return "".join(out)


async def failover_in_batches(
    texts: list[str],
    source_lang: str,
    target_lang: str,
    progress: Optional[Callable[[int, int], None]] = None,
) -> dict[str, str]:
    """
    While Google refuses and a Gemini key is saved: translates many texts in a few requests. Returns text ->
    translation for what succeeded; whatever is absent goes through the normal route, which fails loudly.
    """
    if not google_is_refusing():
        return {}
    key = _failover_key()
    if not key:
        return {}
    todo = [t for t in dict.fromkeys(texts)
            if any(ch.isalpha() for ch in t) and _cached(t, source_lang, target_lang) is None]
    if len(todo) < 2:
        return {}

    from backend.ai_segment_translator import translate_segments_with_gemini
    from backend.ai_polisher import DailyQuotaExhaustedError

    async def leave_out(_text: str) -> str:
        return ""

    try:
        out = await translate_segments_with_gemini(
            todo, source_lang, target_lang, key, style="natural", quota_behavior="fallback", progress=progress,
            fallback_translate=leave_out, max_batch_chars=_FAILOVER_BATCH_CHARS,
        )
    except (DailyQuotaExhaustedError, PermissionError) as e:
        logger.warning(f"Batched Gemini failover is unavailable: {e}")
        return {}
    ready = {}
    for text, result in zip(todo, out):
        if result.strip() and not _unusable(result, text, target_lang):
            ready[text] = result.strip()
            _remember(text, ready[text], source_lang, target_lang)
    if ready:
        _used("gemini")
    return ready


def _resolve_lang_code(lang: Optional[str], default: str) -> str:
    if not lang:
        return default
    norm = lang.strip().lower()
    if norm in ("en", "english"):
        return "en"
    if norm in ("el", "gr", "greek"):
        return "el"
    return LANG_CODES.get(norm, default)


def _extract_gtx_text(data) -> str:
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise ValueError("Malformed GTX response payload")
    return "".join(part[0] for part in data[0] if isinstance(part, list) and part and isinstance(part[0], str))


def _translate_gtx(text: str, source_lang: str, target_lang: str) -> str:
    """Translates text using Google's direct GTX endpoint via POST (no URI length limits)."""
    if not text.strip():
        return text
    src_code = _resolve_lang_code(source_lang, "en")
    tgt_code = _resolve_lang_code(target_lang, "el")

    data = urllib.parse.urlencode({
        "client": "gtx",
        "sl": src_code,
        "tl": tgt_code,
        "dt": "t",
        "q": text,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://translate.googleapis.com/translate_a/single",
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
        parsed = json.loads(raw)
        return _extract_gtx_text(parsed)


async def _translate_gtx_async(
    session: aiohttp.ClientSession,
    text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """Async HTTP keep-alive Google GTX translation."""
    src_code = _resolve_lang_code(source_lang, "en")
    tgt_code = _resolve_lang_code(target_lang, "el")
    form = {
        "client": "gtx",
        "sl": src_code,
        "tl": tgt_code,
        "dt": "t",
        "q": text,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    async with session.post(
        "https://translate.googleapis.com/translate_a/single",
        data=form,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as resp:
        if resp.status == 429:
            raise urllib.error.HTTPError(str(resp.url), 429, "Too Many Requests", {}, None)
        if resp.status != 200:
            raise RuntimeError(f"GTX HTTP {resp.status}")
        parsed = await resp.json(content_type=None)
        return _extract_gtx_text(parsed)


_MYMEMORY_ERROR_MARKERS = (
    "MYMEMORY WARNING",
    "QUERY LENGTH LIMIT EXCEEDED",
    "PLEASE SELECT TWO DISTINCT LANGUAGES",
    "INVALID TARGET LANGUAGE",
    "INVALID SOURCE LANGUAGE",
    "NO QUERY SPECIFIED",
)


async def _translate_mymemory_async(
    session: aiohttp.ClientSession,
    text: str,
    source_lang: str,
    target_lang: str,
) -> Optional[str]:
    """Fast free fallback via MyMemory API when Google GTX rate-limits (max ~500 chars per call)."""
    if len(text) > _MYMEMORY_LIMIT:
        return None
    src_code = _resolve_lang_code(source_lang, "en")
    tgt_code = _resolve_lang_code(target_lang, "el")
    params = {"q": text, "langpair": f"{src_code}|{tgt_code}"}
    try:
        async with session.get(
            "https://api.mymemory.translated.net/get",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            headers = getattr(resp, "headers", None)
            if resp.status == 429:
                _note_mymemory_limit(headers)
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if not isinstance(data, dict):
                    return None
                resp_status = data.get("responseStatus", 200)
                if str(resp_status) == "429" or data.get("quotaFinished") is True:
                    _note_mymemory_limit(headers)
                if str(resp_status) != "200":
                    return None
                tr = (data.get("responseData") or {}).get("translatedText", "")
                matches = data.get("matches")
                if isinstance(matches, list):
                    # translatedText is the best *fuzzy* translation-memory hit ("Second line:" -> "Πρώτη πρόταση:").
                    # Only machine translation of exactly this text, or an identical human match, is a translation.
                    same = [m for m in matches if isinstance(m, dict) and m.get("translation")
                            and str(m.get("segment", "")).split() == text.split()]
                    machine = [m for m in same if str(m.get("created-by", "")).startswith("MT")]
                    human = [m for m in same if float(m.get("match") or 0) >= 0.99]
                    best = machine or human
                    if not best:
                        return None
                    tr = best[0]["translation"]
                if isinstance(tr, str) and tr.strip():
                    if "&" in tr and not re.search(r"&#?\w+;", text):
                        tr = html.unescape(tr)  # the service escapes quotes and apostrophes
                    tr_up = tr.upper()
                    if "MYMEMORY WARNING" in tr_up:
                        _note_mymemory_limit(headers)
                    cut_short = len(text) > 80 and len(tr) < 0.3 * len(text)
                    if not cut_short and not any(m in tr_up for m in _MYMEMORY_ERROR_MARKERS):
                        return tr
    except Exception:
        pass
    return None


async def _translate_with_retry(
    text: str,
    source_lang: str,
    target_lang: str,
    retries: int = 3,
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    """
    Translates text, waiting out short outages. Raises TranslationUnavailableError rather than returning the
    source text: the job stops with a clear error, and finished parts are cached for Resume.
    """
    if text and not any(ch.isalpha() for ch in text):
        return text  # numbers, punctuation, invisible characters: nothing to translate
    if text and len(text) > _MAX_ENGINE_CHARS:
        async def piecewise(body: str) -> str:
            return await _translate_with_retry(body, source_lang, target_lang, retries=retries, session=session)

        return await _in_pieces(text, _MAX_ENGINE_CHARS, piecewise)
    delays = (0.0,) + tuple(RETRY_ROUND_DELAYS)
    for round_no, delay in enumerate(delays):
        if delay:
            await asyncio.sleep(delay)
        result = await _translate_attempt(text, source_lang, target_lang, retries=retries, session=session)
        if result is not None:
            return result
        last_try = time.time() + sum(delays[round_no + 1:])
        if min(_GTX_COOLDOWN_UNTIL, _MYMEMORY_PAUSED_UNTIL) > last_try and not _failover_key():
            break  # every engine refuses beyond the last retry (a first, short pause is waited out)
    raise TranslationUnavailableError(
        "Η δωρεάν μετάφραση δεν είναι διαθέσιμη τώρα: η Google αρνείται τα αιτήματα και το MyMemory δέχεται μόνο λίγο "
        "κείμενο την ημέρα. Προσθέστε δωρεάν κλειδί Gemini ή δοκιμάστε αργότερα. Δεν αποθηκεύτηκε αμετάφραστο κείμενο· "
        "πατήστε Συνέχιση (όσα μεταφράστηκαν διατηρούνται)."
    )


async def _translate_attempt(
    text: str,
    source_lang: str,
    target_lang: str,
    retries: int = 3,
    session: Optional[aiohttp.ClientSession] = None,
) -> Optional[str]:
    """One round over all engines: SQLite cache, keep-alive GTX POST, 429 circuit-breaker, fast fallbacks."""
    if not text.strip():
        return text

    # Check SQLite semantic translation cache first
    cached_res = _cached(text, source_lang, target_lang)
    if cached_res is not None:
        return cached_res

    loop = asyncio.get_running_loop()
    unchanged = []  # answers identical in script to the source (names, code, references)

    # 1. Direct GTX client API via POST (skipped while Google's refusal pause lasts)
    if not google_is_refusing():
        for attempt in range(retries):
            try:
                if session is not None:
                    result = await _translate_gtx_async(session, text, source_lang, target_lang)
                else:
                    result = await loop.run_in_executor(None, _translate_gtx, text, source_lang, target_lang)
                if result and result.strip():
                    _note_google_answer()
                    # Validate that text was actually translated if target is Greek
                    if _untranslated(result, text, target_lang):
                        unchanged.append(result)
                        logger.warning(f"GTX returned untranslated text on attempt {attempt+1}/{retries}, retrying...")
                        await asyncio.sleep(0.6 * (attempt + 1))
                        continue
                    _remember(text, result, source_lang, target_lang)
                    return result
            except Exception as e:
                logger.warning(f"GTX translation attempt {attempt+1}/{retries} error: {e}")
                if "429" in str(e):
                    # Pause Google after the 2nd refusal so chunks don't stall or keep hammering it
                    if attempt >= 1:
                        _note_google_refusal()
                        break
                    await asyncio.sleep(0.8)
                else:
                    await asyncio.sleep(0.5 * (attempt + 1))

    # 2. MyMemory: at once for short text; for long text (piece by piece) only when Gemini cannot take it
    async def via_mymemory() -> Optional[str]:
        async def translate_piece(body: str) -> Optional[str]:
            hit = _cached(body, source_lang, target_lang)
            if hit is not None:
                return hit
            if time.time() < _MYMEMORY_PAUSED_UNTIL:
                return None
            if session is not None:
                got = await _translate_mymemory_async(session, body, source_lang, target_lang)
            else:
                async with aiohttp.ClientSession() as own_session:
                    got = await _translate_mymemory_async(own_session, body, source_lang, target_lang)
            if not got or not got.strip() or any(m in got.upper() for m in _MYMEMORY_ERROR_MARKERS):
                return None
            _remember(body, got, source_lang, target_lang)  # kept even if a later piece fails: the allowance is small
            _used("mymemory")
            if len(body) < len(text.strip()):
                await asyncio.sleep(0.3)
            return got

        try:
            out = await _in_pieces(text, _MYMEMORY_LIMIT, translate_piece)
        except Exception as mm_err:
            logger.debug(f"MyMemory fallback failed: {mm_err}")
            return None
        if out is not None:
            _remember(text, out, source_lang, target_lang)
        return out

    is_short = len(text) <= _MYMEMORY_LIMIT
    if is_short:
        mm_res = await via_mymemory()
        if mm_res is not None:
            return mm_res

    # 3. Fallback to deep_translator (only outside Google's refusal pause)
    if not google_is_refusing():
        try:
            logger.info("Attempting fallback via deep_translator...")
            src_c = _resolve_lang_code(source_lang, "en")
            tgt_c = _resolve_lang_code(target_lang, "el")
            # Create a dedicated instance per executor thread to eliminate concurrent mutation races
            def _run_deep_trans(t):
                return GoogleTranslator(source=src_c, target=tgt_c).translate(t)
            result = await loop.run_in_executor(None, _run_deep_trans, text)
            if result and result.strip() and not _untranslated(result, text, target_lang):
                _remember(text, result, source_lang, target_lang)
                return result
        except Exception as e:
            logger.error(f"Fallback translation error: {e}")
            if "too many requests" in str(e).lower() or "429" in str(e):
                _note_google_refusal()

    # 4. Automatic Gemini Flash failover when Google refuses and an API key exists
    gemini_key = _failover_key()
    if gemini_key:
        try:
            from backend.ai_polisher import _call_gemini_api, DailyQuotaExhaustedError
            tgt_label = "Modern Greek (δημοτική)" if target_lang.lower().startswith(("gr", "el")) else "English"
            src_label = "English" if source_lang.lower().startswith("en") else "Greek"
            prompt = (
                f"Translate the following text accurately and naturally from {src_label} to {tgt_label}. "
                f"Preserve paragraph structure and punctuation. Return ONLY the translated text without comments."
            )
            try:
                gem_res = await _call_gemini_api(text, gemini_key, prompt, session=session, temperature=0.2)
                if gem_res and gem_res.strip() and not _unusable(gem_res, text, target_lang):
                    _remember(text, gem_res, source_lang, target_lang)
                    _used("gemini")
                    return gem_res.strip()
            except DailyQuotaExhaustedError as dq_err:
                logger.warning(f"Gemini failover skipped (daily quota exhausted): {dq_err}")
        except Exception as ex:
            logger.warning(f"Gemini automatic failover failed: {ex}")

    if not is_short:
        mm_res = await via_mymemory()
        if mm_res is not None:
            return mm_res

    # 5. Last recovery attempt for a passing failure (never during Google's refusal pause)
    if (not google_is_refusing() and target_lang.lower() in ("greek", "el", "gr")
            and len(re.findall(r"[a-zA-Z]", text)) > 25):
        logger.warning("All fast translation services busy; cooling down 2.5s for final recovery attempt...")
        await asyncio.sleep(2.5)
        try:
            res_final = await loop.run_in_executor(None, _translate_gtx, text, source_lang, target_lang)
            if res_final and res_final.strip() and re.search(r"[Ͱ-Ͽ]", res_final):
                return res_final
        except Exception:
            pass

    if len(unchanged) >= retries:
        return unchanged[-1]  # the engine itself answered every time that this needs no translation
    logger.error("All translation engines failed for this chunk.")
    return None


async def translate_document(
    job_id: str,
    file_path: str,
    file_type: str,
    source_lang: str,
    target_lang: str,
    output_path: str,
    style: Optional[str] = None,
    page_range: Optional[tuple] = None,
) -> str:
    """
    Translates a document file from source_lang to target_lang.
    Writes output as a UTF-8 text file with page markers.
    ``page_range`` (first, last): only those pages (a sample); every translated passage is cached, so the whole book
    later reuses them.
    Returns the output path.
    """

    update_job(job_id,
               status="running",
               current_step="Reading document...",
               progress=0)

    # Collect all pages (mark job as error if parser fails)
    try:
        pages = list(parse_document(file_path, file_type))
    except Exception as parse_err:
        update_job(job_id, status="error", error=f"Failed to read document: {parse_err}")
        raise
    if page_range:
        lo, hi = page_range
        pages = [p for p in pages if lo <= int(p.get("page") or 0) <= hi]
        if not any((p.get("text") or "").strip() for p in pages):
            raise ValueError(f"Pages {lo}–{hi} hold no text to translate.")
        update_job(job_id, sample_range=[pages[0]["page"], pages[-1]["page"]])
    total_pages = len(pages)

    if total_pages == 0:
        update_job(job_id, status="error", error="No readable text found in document.")
        raise ValueError("No readable text found in document.")

    # Check if document has suspicious lack of text (e.g. scanned image PDF)
    total_chars = sum(len(p.get("text", "").strip()) for p in pages)
    avg_chars_per_page = total_chars / max(total_pages, 1)
    if avg_chars_per_page < 30:
        logger.warning(
            f"[{job_id}] Document has very little extracted text (avg {avg_chars_per_page:.1f} chars/page). "
            f"This is likely an image-only or scanned PDF."
        )

    update_job(job_id,
               total_chunks=total_pages,
               done_chunks=0,
               current_step=f"Translating {total_pages} pages (parallel engine)...")

    page_results = ["" for _ in range(total_pages)]
    page_chunks = [split_into_chunks(p["text"], CHUNK_SIZE) if p["text"].strip() else [] for p in pages]
    completed_pages = 0
    reached = 0  # progress never moves backwards
    prepared: dict[str, str] = {}
    batched = False
    batch_lock = asyncio.Lock()
    sem = asyncio.Semaphore(4)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)

    def batch_progress(done: int, total: int) -> None:
        nonlocal reached
        if is_job_cancelled(job_id):
            raise asyncio.CancelledError("Translation cancelled by user.")
        reached = max(reached, int(done / max(total, 1) * 85))
        update_job(job_id, progress=reached,
                   current_step=f"Google refuses requests: Gemini translates in batches ({done}/{total})...")

    async with aiohttp.ClientSession(connector=connector) as session:
        async def _translate_page(idx: int, page_data: dict):
            nonlocal completed_pages, batched, reached
            if is_job_cancelled(job_id):
                raise asyncio.CancelledError("Translation cancelled by user.")

            page_num = page_data["page"]
            page_text = page_data["text"]

            if not page_text.strip():
                page_results[idx] = f"\n{'='*60}\nPAGE {page_num}\n{'='*60}\n"
            else:
                chunks = page_chunks[idx]
                translated_chunks = []
                async with sem:
                    for chunk in chunks:
                        if is_job_cancelled(job_id):
                            raise asyncio.CancelledError("Translation cancelled by user.")
                        if not chunk.strip():
                            translated_chunks.append(chunk)
                            continue
                        if not batched and google_is_refusing():
                            async with batch_lock:
                                if not batched:
                                    prepared.update(await failover_in_batches(
                                        [c for cs in page_chunks for c in cs], source_lang, target_lang, batch_progress))
                                    batched = True
                        translated = prepared.get(chunk) or await _translate_with_retry(
                            chunk,
                            source_lang,
                            target_lang,
                            session=session,
                        )
                        translated_chunks.append(translated)
                        if len(chunks) > 1:
                            await asyncio.sleep(RATE_LIMIT_DELAY)

                translated_page = "\n\n".join(translated_chunks)
                page_results[idx] = f"\n{'='*60}\nPAGE {page_num}\n{'='*60}\n\n{translated_page}"

            completed_pages += 1
            reached = max(reached, int((completed_pages / total_pages) * 90))
            update_job(job_id,
                       current_step=f"Translating page {completed_pages} of {total_pages}...",
                       done_chunks=completed_pages,
                       progress=reached)

        # The first page with text goes alone: if Google refuses, the others then go to Gemini in batches
        first = next((i for i, cs in enumerate(page_chunks) if cs), 0)
        await _translate_page(first, pages[first])
        tasks = [asyncio.create_task(_translate_page(i, p)) for i, p in enumerate(pages) if i != first]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    output_lines = page_results

    # Write output file
    update_job(job_id, current_step="Writing translated file...", progress=95)
    output_text = "\n".join(output_lines)
    from backend.glossary import apply_glossary
    output_text = apply_glossary(output_text, target_lang, style=style, translated=True)
    if target_lang.lower() in ("greek", "el"):
        from backend.typography import format_greek_typography
        output_text = format_greek_typography(output_text)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    update_job(job_id,
               status="running",
               progress=95,
               current_step="Preparing document...",
               output_path=output_path,
               done_chunks=total_pages)

    logger.info(f"[{job_id}] Translation complete → {output_path}")
    return output_path
