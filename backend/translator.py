"""
Translator Engine - fast chunked English <-> Greek translation.
Uses Google's direct GTX client API for high-speed, reliable translations without 429 bot-blocking,
with deep_translator as an automatic fallback.
"""

import asyncio
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

# Circuit-breaker timestamp when Google GTX returns 429 Too Many Requests
_GTX_COOLDOWN_UNTIL = 0.0


def _translate_gtx(text: str, source_lang: str, target_lang: str) -> str:
    """Translates text using Google's direct GTX endpoint via POST (no URI length limits)."""
    if not text.strip():
        return text
    src_code = LANG_CODES.get(source_lang, "en")
    tgt_code = LANG_CODES.get(target_lang, "el")

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
        data = json.loads(raw)
        return "".join(part[0] for part in data[0] if part and part[0])


async def _translate_gtx_async(
    session: aiohttp.ClientSession,
    text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """Async HTTP keep-alive Google GTX translation."""
    src_code = LANG_CODES.get(source_lang, "en")
    tgt_code = LANG_CODES.get(target_lang, "el")
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
        data = await resp.json(content_type=None)
        return "".join(part[0] for part in data[0] if part and part[0])


async def _translate_mymemory_async(
    session: aiohttp.ClientSession,
    text: str,
    source_lang: str,
    target_lang: str,
) -> Optional[str]:
    """Fast free fallback via MyMemory API when Google GTX rate-limits (max ~500 chars per call)."""
    if len(text) > 480:
        return None
    src_code = LANG_CODES.get(source_lang, "en")
    tgt_code = LANG_CODES.get(target_lang, "el")
    params = {"q": text, "langpair": f"{src_code}|{tgt_code}"}
    try:
        async with session.get(
            "https://api.mymemory.translated.net/get",
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                tr = (data.get("responseData") or {}).get("translatedText", "")
                if tr and "MYMEMORY WARNING" not in tr.upper():
                    return tr
    except Exception:
        pass
    return None


async def _translate_with_retry(
    text: str,
    source_lang: str,
    target_lang: str,
    deep_trans: Optional[GoogleTranslator] = None,
    retries: int = 3,
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    """Translates text with SQLite cache, keep-alive GTX POST, 429 circuit-breaker, and fast fallbacks."""
    global _GTX_COOLDOWN_UNTIL
    if not text.strip():
        return text

    # Check SQLite semantic translation cache first
    cache_key = None
    _db_set_cached = None
    try:
        from backend.database import compute_cache_key, db_get_cached_translation, db_set_cached_translation
        _db_set_cached = db_set_cached_translation
        cache_key = compute_cache_key(text, source_lang, target_lang, engine="google")
        cached_res = db_get_cached_translation(cache_key)
        if cached_res is not None:
            return cached_res
    except Exception as ex:
        logger.debug(f"Cache check skipped: {ex}")

    loop = asyncio.get_running_loop()
    now = time.time()

    # 1. Direct GTX client API via POST (skipped immediately during 429 cooldown)
    if now >= _GTX_COOLDOWN_UNTIL:
        for attempt in range(retries):
            try:
                if session is not None:
                    result = await _translate_gtx_async(session, text, source_lang, target_lang)
                else:
                    result = await loop.run_in_executor(None, _translate_gtx, text, source_lang, target_lang)
                if result and result.strip():
                    # Validate that text was actually translated if target is Greek
                    if target_lang == "greek" and len(re.findall(r"[\u0370-\u03ff]", result)) == 0 and len(re.findall(r"[a-zA-Z]", text)) > 30:
                        logger.warning(f"GTX returned untranslated text on attempt {attempt+1}/{retries}, retrying...")
                        await asyncio.sleep(0.6 * (attempt + 1))
                        continue
                    if cache_key and _db_set_cached:
                        try:
                            _db_set_cached(cache_key, text, result, source_lang, target_lang, engine="google")
                        except Exception:
                            pass
                    return result
            except Exception as e:
                err_str = str(e)
                logger.warning(f"GTX translation attempt {attempt+1}/{retries} error: {e}")
                if "429" in err_str:
                    # Trigger fast 20s circuit-breaker after 2nd 429 so we don't stall 14s per chunk
                    if attempt >= 1:
                        _GTX_COOLDOWN_UNTIL = time.time() + 20.0
                        break
                    await asyncio.sleep(0.8)
                else:
                    await asyncio.sleep(0.5 * (attempt + 1))

    # 2. Fast MyMemory fallback for short chunks when GTX is rate-limited
    if session is not None and len(text) <= 480:
        mm_res = await _translate_mymemory_async(session, text, source_lang, target_lang)
        if mm_res:
            if cache_key and _db_set_cached:
                try:
                    _db_set_cached(cache_key, text, mm_res, source_lang, target_lang, engine="google")
                except Exception:
                    pass
            return mm_res

    # 3. Fallback to deep_translator (only if not actively in Google 429 cooldown)
    if time.time() >= _GTX_COOLDOWN_UNTIL:
        if deep_trans is None:
            try:
                src_c = LANG_CODES.get(source_lang, "en")
                tgt_c = LANG_CODES.get(target_lang, "el")
                deep_trans = GoogleTranslator(source=src_c, target=tgt_c)
            except Exception:
                pass

        if deep_trans:
            try:
                logger.info("Attempting fallback via deep_translator...")
                result = await loop.run_in_executor(None, deep_trans.translate, text)
                if result and result.strip():
                    if cache_key and _db_set_cached:
                        try:
                            _db_set_cached(cache_key, text, result, source_lang, target_lang, engine="google")
                        except Exception:
                            pass
                    return result
            except Exception as e:
                logger.error(f"Fallback translation error: {e}")
                if "too many requests" in str(e).lower() or "429" in str(e):
                    _GTX_COOLDOWN_UNTIL = time.time() + 20.0

    # 4. Automatic Gemini Flash failover when Google Translate is rate-limited (429) and an API key exists
    try:
        import os
        from backend.settings_manager import get_setting
        gemini_key = (get_setting("gemini_api_key", "") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if gemini_key and not gemini_key.startswith(("AQ.Test", "AIzaTest")):
            from backend.ai_polisher import _call_gemini_api
            tgt_label = "Greek" if target_lang.lower().startswith(("gr", "el")) else "English"
            src_label = "English" if source_lang.lower().startswith("en") else "Greek"
            prompt = (
                f"Translate the following text accurately and naturally from {src_label} to {tgt_label}. "
                f"Preserve paragraph structure and punctuation. Return ONLY the translated text without comments."
            )
            gem_res = await _call_gemini_api(text, gemini_key, prompt, session=session, temperature=0.2)
            if gem_res and gem_res.strip():
                if cache_key and _db_set_cached:
                    try:
                        _db_set_cached(cache_key, text, gem_res, source_lang, target_lang, engine="google")
                    except Exception:
                        pass
                return gem_res.strip()
    except Exception as gem_err:
        logger.warning(f"Gemini automatic failover failed: {gem_err}")

    logger.error("All translation retries failed for chunk. Returning original text.")
    return text


async def translate_document(
    job_id: str,
    file_path: str,
    file_type: str,
    source_lang: str,
    target_lang: str,
    output_path: str,
    progress_callback: Optional[Callable] = None,
    style: Optional[str] = None,
) -> str:
    """
    Translates a document file from source_lang to target_lang.
    Writes output as a UTF-8 text file with page markers.
    Returns the output path.
    """
    src_code = LANG_CODES.get(source_lang, "en")
    tgt_code = LANG_CODES.get(target_lang, "el")
    fallback_translator = GoogleTranslator(source=src_code, target=tgt_code)

    update_job(job_id,
               status="running",
               current_step="Reading document...",
               progress=0)

    # Collect all pages
    pages = list(parse_document(file_path, file_type))
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
    completed_pages = 0
    sem = asyncio.Semaphore(4)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)

    async with aiohttp.ClientSession(connector=connector) as session:
        async def _translate_page(idx: int, page_data: dict):
            nonlocal completed_pages
            if is_job_cancelled(job_id):
                raise asyncio.CancelledError("Translation cancelled by user.")

            page_num = page_data["page"]
            page_text = page_data["text"]

            if not page_text.strip():
                page_results[idx] = f"\n{'='*60}\nPAGE {page_num}\n{'='*60}\n"
            else:
                chunks = split_into_chunks(page_text, CHUNK_SIZE)
                translated_chunks = []
                async with sem:
                    for chunk in chunks:
                        if is_job_cancelled(job_id):
                            raise asyncio.CancelledError("Translation cancelled by user.")
                        if not chunk.strip():
                            translated_chunks.append(chunk)
                            continue
                        translated = await _translate_with_retry(
                            chunk,
                            source_lang,
                            target_lang,
                            deep_trans=fallback_translator,
                            session=session,
                        )
                        translated_chunks.append(translated)
                        if len(chunks) > 1:
                            await asyncio.sleep(RATE_LIMIT_DELAY)

                translated_page = "\n\n".join(translated_chunks)
                page_results[idx] = f"\n{'='*60}\nPAGE {page_num}\n{'='*60}\n\n{translated_page}"

            completed_pages += 1
            update_job(job_id,
                       current_step=f"Translating page {completed_pages} of {total_pages}...",
                       done_chunks=completed_pages,
                       progress=int((completed_pages / total_pages) * 90))

        await asyncio.gather(*(_translate_page(i, p) for i, p in enumerate(pages)))

    output_lines = page_results

    # Write output file
    update_job(job_id, current_step="Writing translated file...", progress=95)
    output_text = "\n".join(output_lines)
    from backend.glossary import apply_glossary
    output_text = apply_glossary(output_text, target_lang, style=style)
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
