"""
Translator Engine - chunked English <-> Greek translation using Google Translate
via the deep_translator library (no API key required).
"""

import asyncio
import time
import logging
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

# Maximum characters per translation request (Google limit is 5000, use 4500 for safety)
CHUNK_SIZE = 4500

# Delay between API calls in seconds to avoid rate limiting
# Google's unofficial limit: 5 req/sec, 200k/day
RATE_LIMIT_DELAY = 1.2  # wait 1.2s between each chunk to stay well under 5 req/sec

# If a whole page fails, pause before moving on
PAGE_PAUSE = 2.0


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

    source_lang / target_lang: 'english' or 'greek'
    """
    src_code = LANG_CODES.get(source_lang, "en")
    tgt_code = LANG_CODES.get(target_lang, "el")

    translator = GoogleTranslator(source=src_code, target=tgt_code)

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

        # Split page text into API-safe chunks
        chunks = split_into_chunks(page_text, CHUNK_SIZE)
        translated_chunks = []
        any_failed = False

        for chunk in chunks:
            if not chunk.strip():
                translated_chunks.append(chunk)
                continue

            translated = await _translate_with_retry(translator, chunk)
            if translated == chunk:
                # This means translation may have failed (returned original)
                any_failed = True
            translated_chunks.append(translated)

            # Respect rate limit
            await asyncio.sleep(RATE_LIMIT_DELAY)

        translated_page = "\n\n".join(translated_chunks)

        # If the page had failures, add a note in the output
        if any_failed and len(chunks) > 0:
            logger.warning(f"[{job_id}] Page {page_num}: some chunks may not have been translated.")

        # Extra pause between pages to let rate limit cool down
        if idx < total_pages - 1:
            await asyncio.sleep(PAGE_PAUSE)

        # Write page marker
        output_lines.append(f"\n{'='*60}")
        output_lines.append(f"PAGE {page_num}")
        output_lines.append(f"{'='*60}\n")
        output_lines.append(translated_page)

    # Write output file
    update_job(job_id, current_step="Writing translated file...", progress=95)
    output_text = "\n".join(output_lines)

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


async def _translate_with_retry(translator: GoogleTranslator, text: str, retries: int = 5) -> str:
    """Translates text with exponential backoff retry on failure."""
    for attempt in range(retries):
        try:
            # deep_translator is synchronous; run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, translator.translate, text)
            if result:
                return result
            # Empty result — treat as soft failure, retry
            await asyncio.sleep(2.0)
        except Exception as e:
            wait = min((2 ** attempt) * 1.5, 30.0)  # cap backoff at 30s
            logger.warning(f"Translation attempt {attempt+1}/{retries} failed: {e}. Retrying in {wait:.1f}s...")
            await asyncio.sleep(wait)

    logger.error(f"All {retries} translation retries failed for chunk. Returning original text.")
    return text
