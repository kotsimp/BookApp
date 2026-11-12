"""
TTS Engine - generates audiobooks using Microsoft edge-tts neural voices.
Supports Greek (el-GR) and English (en-US) with multiple voice options.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional

import edge_tts
from backend.parsers import parse_document, split_into_chunks
from backend.job_manager import update_job

logger = logging.getLogger(__name__)

# Available voices grouped by language
VOICES = {
    "greek": {
        "Nestoras (Male)": "el-GR-NestorasNeural",
        "Athina (Female)": "el-GR-AthinaNeural",
    },
    "english": {
        "Aria (Female)": "en-US-AriaNeural",
        "Guy (Male)": "en-US-GuyNeural",
        "Jenny (Female)": "en-US-JennyNeural",
        "Davis (Male)": "en-US-DavisNeural",
        "Emma (Female)": "en-GB-SoniaNeural",
        "Ryan (Male)": "en-GB-RyanNeural",
    },
}

# Max chars per TTS request (1200 chars ensures edge-tts WebSocket stays within safe buffer limits)
TTS_CHUNK_SIZE = 1200


async def generate_audiobook(
    job_id: str,
    file_path: str,
    file_type: str,
    language: str,
    voice_name: str,
    output_path: str,
    translated_text_path: Optional[str] = None,
) -> str:
    """
    Generates an MP3 audiobook from a document or pre-translated text file.

    Args:
        job_id: Job identifier for progress updates
        file_path: Original document path
        file_type: 'pdf', 'docx', or 'epub'
        language: 'english' or 'greek'
        voice_name: Display name from VOICES dict (e.g. 'Athina (Female)')
        output_path: Path to write final .mp3
        translated_text_path: If set, read text from this file instead of parsing document

    Returns:
        output_path of the generated MP3
    """
    # Resolve voice code
    voice_code = VOICES.get(language, {}).get(voice_name)
    if not voice_code:
        # Fallback to first available voice for the language
        voice_code = list(VOICES.get(language, {"": "en-US-AriaNeural"}).values())[0]

    update_job(job_id,
               status="running",
               current_step="Reading document...",
               progress=0)

    # Get text to convert
    if translated_text_path and Path(translated_text_path).exists():
        # Read from pre-translated file (strip page markers for cleaner audio)
        with open(translated_text_path, "r", encoding="utf-8") as f:
            raw = f.read()
        raw = re.sub(r"={3,}.*?={3,}", "", raw, flags=re.DOTALL)
        raw = re.sub(r"\bPAGE \d+\b", "", raw)
        text_chunks = split_into_chunks(raw.strip(), TTS_CHUNK_SIZE)
        total_chunks = len(text_chunks)
        text_source = "translated_file"
    else:
        # Parse directly from document
        pages = list(parse_document(file_path, file_type))
        # Flatten all page text
        all_text = "\n\n".join(p["text"] for p in pages)
        text_chunks = split_into_chunks(all_text, TTS_CHUNK_SIZE)
        total_chunks = len(text_chunks)
        text_source = "document"

    if not text_chunks:
        update_job(job_id, status="error", error="No text found to convert to audio.")
        raise ValueError("No text found to convert to audio.")

    update_job(job_id,
               total_chunks=total_chunks,
               done_chunks=0,
               current_step=f"Generating audio in {total_chunks} parts using {voice_name}...")

    logger.info(f"[{job_id}] TTS: {total_chunks} chunks, voice={voice_code}, source={text_source}")

    # Generate audio for each chunk in temp dir
    temp_dir = Path(output_path).parent / f"tts_tmp_{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    chunk_files = []

    for idx, chunk in enumerate(text_chunks):
        if not chunk.strip():
            continue

        chunk_path = temp_dir / f"chunk_{idx:06d}.mp3"
        update_job(job_id,
                   current_step=f"Generating audio part {idx+1} of {total_chunks}...",
                   done_chunks=idx,
                   progress=int((idx / total_chunks) * 85))

        await _tts_chunk_with_retry(chunk, voice_code, str(chunk_path))
        chunk_files.append(str(chunk_path))

    # Concatenate all chunks into final MP3
    update_job(job_id,
               current_step="Assembling final audiobook...",
               progress=90)

    await _concatenate_mp3s(chunk_files, output_path)

    # Cleanup temp files
    for f in chunk_files:
        try:
            os.remove(f)
        except Exception:
            pass
    try:
        temp_dir.rmdir()
    except Exception:
        pass

    update_job(job_id,
               status="done",
               progress=100,
               current_step="Audiobook ready!",
               output_path=output_path,
               done_chunks=total_chunks)

    logger.info(f"[{job_id}] Audiobook complete → {output_path}")
    return output_path


def _clean_tts_text(text: str) -> str:
    """Prepares text for TTS by removing redundant whitespace, symbols, and bullets."""
    # Remove bullet symbols and non-pronounceable markers that cause edge-tts Athina to fail
    text = re.sub(r"[•▪▫◦■□✓➢❖✔✉]", " ", text)
    text = re.sub(r"[\ue000-\uf8ff]", " ", text)
    # Replace newlines with spaces so edge-tts SSML parsing doesn't break
    text = re.sub(r"[\r\n]+", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


async def _tts_chunk_with_retry(text: str, voice: str, output_path: str, retries: int = 3):
    """Generates TTS for a text chunk with retry logic, maintaining consistent voice throughout."""
    clean_text = _clean_tts_text(text)
    if not clean_text:
        Path(output_path).write_bytes(b"")
        return

    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(clean_text, voice)
            await communicate.save(output_path)
            if Path(output_path).stat().st_size > 0:
                return
        except Exception as e:
            wait = (attempt + 1) * 1.0
            logger.warning(f"TTS attempt {attempt+1} failed ({voice}): {e}. Retrying in {wait}s...")
            # On retry, aggressively clean any exotic punctuation while keeping text
            if attempt >= 0:
                clean_text = re.sub(r"[^\w\s\.,;:!?\-«»'\"()–—]", " ", clean_text)
                clean_text = re.sub(r"\s+", " ", clean_text).strip()
            await asyncio.sleep(wait)

    # If all retries fail, create a silent placeholder without mixing voices
    logger.error(f"TTS failed after retries for chunk with {voice}. Writing empty file.")
    Path(output_path).write_bytes(b"")


async def _concatenate_mp3s(chunk_files: list[str], output_path: str):
    """Concatenates MP3 files by binary concatenation (fast, no re-encoding)."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Filter out empty files
    valid_files = [f for f in chunk_files if Path(f).exists() and Path(f).stat().st_size > 0]

    if not valid_files:
        raise RuntimeError("No valid audio chunks to concatenate.")

    # Simple binary concatenation works for CBR MP3s (edge-tts output)
    with open(output_path, "wb") as out_f:
        for chunk_file in valid_files:
            with open(chunk_file, "rb") as in_f:
                out_f.write(in_f.read())


def get_available_voices() -> dict:
    """Returns the VOICES dict for the frontend."""
    return VOICES
