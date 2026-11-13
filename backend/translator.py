"""
Translator Engine - fast chunked English <-> Greek translation.
Uses Google's direct GTX client API for high-speed, reliable translations without 429 bot-blocking,
with deep_translator as an automatic fallback.
"""

import asyncio
import logging
import urllib.request
import urllib.parse
import json
import re
from pathlib import Path
from typing import Callable, Optional

from deep_translator import GoogleTranslator
from backend.parsers import parse_document, split_into_chunks
from backend.job_manager import update_job

logger = logging.getLogger(__name__)

# Language codes for Google Translate
LANG_CODES = {
    "english": "en",
    "greek": "el",
}

# Maximum characters per translation request (keep <= 2500 for safety and zero timeouts)
CHUNK_SIZE = 2500

# Inter-chunk delay in seconds
RATE_LIMIT_DELAY = 0.25


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


async def _translate_with_retry(
    text: str,
    source_lang: str,
    target_lang: str,
    deep_trans: Optional[GoogleTranslator] = None,
    retries: int = 4,
) -> str:
    """Translates text with GTX POST, exponential backoff, validation, and deep_translator fallback."""
    if not text.strip():
        return text

    loop = asyncio.get_event_loop()

    # 1. Direct GTX client API via POST
    for attempt in range(retries):
        try:
            result = await loop.run_in_executor(None, _translate_gtx, text, source_lang, target_lang)
            if result and result.strip():
                # Validate that text was actually translated if target is Greek
                if target_lang == "greek" and len(re.findall(r"[\u0370-\u03ff]", result)) == 0 and len(re.findall(r"[a-zA-Z]", text)) > 30:
                    logger.warning(f"GTX returned untranslated text on attempt {attempt+1}/{retries}, retrying...")
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return result
        except Exception as e:
            logger.warning(f"GTX translation attempt {attempt+1}/{retries} error: {e}")
            await asyncio.sleep(1.0 * (attempt + 1))

    # 2. Fallback to deep_translator
    if deep_trans:
        try:
            logger.info("Attempting fallback via deep_translator...")
            result = await loop.run_in_executor(None, deep_trans.translate, text)
            if result and result.strip():
                return result
        except Exception as e:
            logger.error(f"Fallback translation error: {e}")

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
               current_step=f"Translating {total_pages} pages...")

    output_lines = []

    for idx, page_data in enumerate(pages):
        page_num = page_data["page"]
        page_text = page_data["text"]

        update_job(job_id,
                   current_step=f"Translating page {page_num} of {total_pages}...",
                   done_chunks=idx,
                   progress=int((idx / total_pages) * 90))

        if not page_text.strip():
            # Empty page
            output_lines.append(f"\n{'='*60}")
            output_lines.append(f"PAGE {page_num}")
            output_lines.append(f"{'='*60}\n")
            continue

        # Split page text into API-safe chunks
        chunks = split_into_chunks(page_text, CHUNK_SIZE)
        translated_chunks = []

        for chunk in chunks:
            if not chunk.strip():
                translated_chunks.append(chunk)
                continue

            translated = await _translate_with_retry(
                chunk,
                source_lang,
                target_lang,
                deep_trans=fallback_translator,
            )
            translated_chunks.append(translated)

            # Brief delay between chunks
            if len(chunks) > 1:
                await asyncio.sleep(RATE_LIMIT_DELAY)

        translated_page = "\n\n".join(translated_chunks)

        # Write page marker
        output_lines.append(f"\n{'='*60}")
        output_lines.append(f"PAGE {page_num}")
        output_lines.append(f"{'='*60}\n")
        output_lines.append(translated_page)

    # Write output file
    update_job(job_id, current_step="Writing translated file...", progress=95)
    output_text = "\n".join(output_lines)
    from backend.glossary import apply_glossary
    output_text = apply_glossary(output_text, target_lang)

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
