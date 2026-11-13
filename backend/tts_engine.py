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

# Max chars per TTS request (2000 chars reduces WebSocket round-trips while staying well within edge-tts limits)
TTS_CHUNK_SIZE = 2000
# Number of concurrent edge-tts requests
TTS_CONCURRENCY = 4


async def generate_audiobook(
    job_id: str,
    file_path: str,
    file_type: str,
    language: str,
    voice_name: str,
    output_path: str,
    translated_text_path: Optional[str] = None,
    narration_style: str = "literature",
    rate: Optional[str] = None,
    ai_polish: bool = False,
    api_key: Optional[str] = None,
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
        raw_text = raw.strip()
        text_source = "translated_file"
    else:
        # Parse directly from document
        pages = list(parse_document(file_path, file_type))
        raw_text = "\n\n".join(p["text"] for p in pages).strip()
        text_source = "document"

    if not raw_text:
        update_job(job_id, status="error", error="No text found to convert to audio.")
        raise ValueError("No text found to convert to audio.")

    if ai_polish:
        from backend.ai_polisher import polish_text_with_gemini
        from backend.settings_manager import get_setting

        resolved_key = (api_key or "").strip() or (get_setting("gemini_api_key", "") or "").strip()
        if not resolved_key:
            err_msg = "Gemini API key is required for AI Audiobook Polish."
            update_job(job_id, status="error", error=err_msg)
            raise ValueError(err_msg)

        update_job(job_id, current_step="✨ AI polishing script for spoken narration...", progress=5)

        def _polish_prog(cur: int, tot: int):
            pct = 5 + int((cur / max(tot, 1)) * 15)
            update_job(job_id, current_step=f"✨ AI polishing audio script ({cur}/{tot})...", progress=pct)

        raw_text = await polish_text_with_gemini(
            raw_text,
            api_key=resolved_key,
            style="audiobook",
            progress_callback=_polish_prog,
        )

    text_chunks = split_into_chunks(raw_text, TTS_CHUNK_SIZE)
    total_chunks = len(text_chunks)

    # Determine prosody (rate, pitch, pause style)
    style = (narration_style or "literature").lower()
    default_rates = {
        "literature": "-15%",
        "slow_pauses": "-30%",
        "poetry": "-25%",
        "standard": "-5%",
    }
    default_pitches = {
        "literature": "-2Hz",
        "slow_pauses": "-3Hz",
        "poetry": "-3Hz",
        "standard": "+0Hz",
    }
    effective_rate = rate if rate else default_rates.get(style, "-15%")
    effective_pitch = default_pitches.get(style, "-2Hz")

    update_job(job_id,
               total_chunks=total_chunks,
               done_chunks=0,
               current_step=f"Generating audio in {total_chunks} parts using {voice_name} ({style})...")

    logger.info(
        f"[{job_id}] TTS: {total_chunks} chunks, voice={voice_code}, "
        f"style={style}, rate={effective_rate}, pitch={effective_pitch}, source={text_source}"
    )

    # Generate audio for each chunk concurrently (preserving order)
    temp_dir = Path(output_path).parent / f"tts_tmp_{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(TTS_CONCURRENCY)
    completed = 0

    async def _process_chunk(idx: int, chunk: str) -> Optional[str]:
        nonlocal completed
        if not chunk.strip():
            completed += 1
            return None
        chunk_path = temp_dir / f"chunk_{idx:06d}.mp3"
        async with sem:
            await _tts_chunk_with_retry(
                chunk,
                voice_code,
                str(chunk_path),
                rate=effective_rate,
                pitch=effective_pitch,
                narration_style=style,
            )
        completed += 1
        update_job(
            job_id,
            current_step=f"Generated audio part {completed} of {total_chunks}...",
            done_chunks=completed,
            progress=int((completed / total_chunks) * 85),
        )
        return str(chunk_path)

    results = await asyncio.gather(*(_process_chunk(i, c) for i, c in enumerate(text_chunks)))
    chunk_files = [p for p in results if p]

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


def _clean_tts_text(text: str, narration_style: str = "literature") -> str:
    """Prepares text for TTS, preserving natural breath pauses for literature, slow_pauses, or poetry."""
    # Remove bullet symbols and non-pronounceable markers that cause edge-tts Athina to fail
    text = re.sub(r"[•▪▫◦■□✓➢❖✔✉]", " ", text)
    text = re.sub(r"[\ue000-\uf8ff]", " ", text)
    style = (narration_style or "literature").lower()

    if style == "poetry":
        # Preserve stanza breaks (longer pause) AND individual verse line breaks (gentle pause)
        stanzas = re.split(r"\n\s*\n+", text.strip())
        formatted_stanzas = []
        for stanza in stanzas:
            lines = [ln.strip() for ln in stanza.splitlines() if ln.strip()]
            if not lines:
                continue
            verse_parts = []
            for ln in lines:
                if ln[-1] not in ".!?;:…,":
                    ln += ","
                verse_parts.append(ln)
            stanza_str = " ".join(verse_parts)
            if stanza_str[-1] == ",":
                stanza_str = stanza_str[:-1] + "."
            formatted_stanzas.append(stanza_str)
        text = " ... ... ".join(formatted_stanzas)
        text = re.sub(r"\s*[—–]\s*", ", ", text)
    elif style in ("literature", "slow_pauses"):
        # Preserve paragraph/chapter breaks as natural sentence pauses so narration doesn't rush
        paragraphs = re.split(r"\n\s*\n+", text.strip())
        formatted = []
        for para in paragraphs:
            p = re.sub(r"[\r\n]+", " ", para).strip()
            if not p:
                continue
            if p[-1] not in ".!?;:…":
                p += "."
            if style == "slow_pauses":
                p = re.sub(r"([.!?])\s+", r"\1 ... ", p)
            formatted.append(p)
        sep = " ... ... " if style == "slow_pauses" else " ... "
        text = sep.join(formatted)
        text = re.sub(r"\s*[—–]\s*", ", ", text)
    else:
        text = re.sub(r"[\r\n]+", " ", text)

    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


async def _tts_chunk_with_retry(
    text: str,
    voice: str,
    output_path: str,
    retries: int = 3,
    rate: str = "-15%",
    pitch: str = "-2Hz",
    narration_style: str = "literature",
):
    """Generates TTS for a text chunk with retry logic, maintaining consistent voice throughout."""
    clean_text = _clean_tts_text(text, narration_style=narration_style)
    if not clean_text:
        Path(output_path).write_bytes(b"")
        return

    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(clean_text, voice, rate=rate, pitch=pitch)
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
