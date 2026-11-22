"""
TTS Engine - generates audiobooks using Microsoft edge-tts neural voices.
Supports Greek (el-GR) and English (en-US) with multiple voice options.
"""

import asyncio
import json
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

# Max chars per TTS request (~1200 chars allows fast concurrent synthesis while staying well within edge-tts limits)
TTS_CHUNK_SIZE = 1200
# Number of concurrent edge-tts requests
TTS_CONCURRENCY = 4

# Narration style prosody defaults (rate, pitch)
DEFAULT_RATES = {
    "literature": "-12%",
    "poetry": "-20%",
    "slow_pauses": "-18%",
    "standard": "+0%",
    "fast": "+15%",
}
DEFAULT_PITCHES = {
    "literature": "-1Hz",
    "poetry": "-2Hz",
    "slow_pauses": "-1Hz",
    "standard": "+0Hz",
    "fast": "+0Hz",
}


def split_into_voice_segments(
    text: str,
    default_voice_code: str,
    dialogue_voice_code: Optional[str] = None,
) -> list[tuple[str, str]]:
    """
    Splits text into (chunk_text, voice_code) segments.
    Supports:
    1. Explicit tags: [Nestoras]: ..., [Athina]: ..., [VoiceName]: ...
    2. Automatic dialogue alternation: Dialogue lines (starting with '—' or enclosed in «...»)
       are routed to dialogue_voice_code, narration is routed to default_voice_code.
    """
    if not text or not str(text).strip():
        return []

    alias_map = {
        "nestoras": "el-GR-NestorasNeural",
        "athina": "el-GR-AthinaNeural",
        "aria": "en-US-AriaNeural",
        "guy": "en-US-GuyNeural",
        "jenny": "en-US-JennyNeural",
        "davis": "en-US-DavisNeural",
        "sonia": "en-GB-SoniaNeural",
        "ryan": "en-GB-RyanNeural",
        "narrator": default_voice_code,
        "αφηγητής": default_voice_code,
    }
    if dialogue_voice_code:
        alias_map["dialogue"] = dialogue_voice_code
        alias_map["διάλογος"] = dialogue_voice_code

    segments = []
    lines = text.split("\n")

    current_voice = default_voice_code
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_lines:
                current_lines.append("")
            continue

        # 1. Explicit speaker tag: e.g. [Athina]: ... or [Nestoras]: ...
        tag_match = re.match(r"^\[([a-zA-Z\u0370-\u03ff\s]+)\]\s*:\s*(.*)$", stripped)
        if tag_match:
            speaker_tag = tag_match.group(1).strip().lower()
            speech_content = tag_match.group(2).strip()
            target_voice = alias_map.get(speaker_tag, default_voice_code)

            if target_voice != current_voice and current_lines:
                chunk_str = "\n".join(current_lines).strip()
                if chunk_str:
                    segments.append((chunk_str, current_voice))
                current_lines = []

            current_voice = target_voice
            current_lines.append(speech_content)
            continue

        # 2. Dialogue alternation
        if dialogue_voice_code and dialogue_voice_code != default_voice_code:
            is_dialogue = stripped.startswith(("—", "–", "-", "«", '"')) or ("«" in stripped and "»" in stripped)
            target_voice = dialogue_voice_code if is_dialogue else default_voice_code

            if target_voice != current_voice and current_lines:
                chunk_str = "\n".join(current_lines).strip()
                if chunk_str:
                    segments.append((chunk_str, current_voice))
                current_lines = []

            current_voice = target_voice
            current_lines.append(stripped)
            continue

        current_lines.append(stripped)

    if current_lines:
        chunk_str = "\n".join(current_lines).strip()
        if chunk_str:
            segments.append((chunk_str, current_voice))

    # Break oversized segments into TTS_CHUNK_SIZE
    final_segments = []
    for seg_text, seg_voice in segments:
        if len(seg_text) > TTS_CHUNK_SIZE:
            sub_chunks = split_into_chunks(seg_text, max_chars=TTS_CHUNK_SIZE)
            for sc in sub_chunks:
                if sc.strip():
                    final_segments.append((sc, seg_voice))
        else:
            final_segments.append((seg_text, seg_voice))

    return final_segments


def tag_audiobook_file(
    audio_path: str,
    title: str = "",
    author: str = "",
    cover_image_path: Optional[str] = None,
) -> None:
    """Embeds ID3v2 metadata (Title, Artist, Album, Genre, Cover Art) into MP3 using mutagen."""
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, APIC, ID3NoHeaderError

        try:
            audio = ID3(audio_path)
        except ID3NoHeaderError:
            audio = ID3()

        if title:
            audio.add(TIT2(encoding=3, text=title))
            audio.add(TALB(encoding=3, text=title))
        if author:
            audio.add(TPE1(encoding=3, text=author))
        audio.add(TCON(encoding=3, text="Audiobook"))

        if cover_image_path and Path(cover_image_path).exists():
            try:
                cover_bytes = Path(cover_image_path).read_bytes()
                mime = "image/png" if cover_image_path.lower().endswith(".png") else "image/jpeg"
                audio.add(APIC(
                    encoding=3,
                    mime=mime,
                    type=3,
                    desc="Cover",
                    data=cover_bytes,
                ))
            except Exception as ex:
                logger.warning(f"Could not embed cover art: {ex}")

        audio.save(audio_path, v2_version=3)
    except Exception as e:
        logger.warning(f"Tagging audio file failed (non-critical): {e}")


async def synthesize_voice_preview(
    voice_code: str,
    text: Optional[str] = None,
) -> str:
    """Synthesizes a short 2-3 second voice preview MP3 atomically with timeout and returns its path."""
    import uuid
    if not voice_code or not re.match(r"^[A-Za-z0-9_-]{3,80}$", voice_code):
        raise ValueError(f"Invalid voice code: {voice_code!r}")
    base_temp = Path(__file__).resolve().parent.parent / "temp" / "previews"
    base_temp.mkdir(parents=True, exist_ok=True)
    out_file = base_temp / f"preview_{voice_code}.mp3"
    tmp_file = base_temp / f"preview_{voice_code}_{uuid.uuid4().hex[:8]}.tmp"

    sample_text = text or (
        "Γεια σας! Αυτή είναι μια δοκιμή εκφώνησης για το BookApp."
        if voice_code.startswith("el")
        else "Hello! This is a preview of the neural voice narration for BookApp."
    )

    communicate = edge_tts.Communicate(sample_text, voice_code, rate="-10%")
    try:
        await asyncio.wait_for(communicate.save(str(tmp_file)), timeout=30.0)
        for attempt in range(4):
            try:
                os.replace(tmp_file, out_file)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))
    finally:
        if tmp_file.exists():
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:
                pass
    return str(out_file)


def compute_chapter_marks(parts: list[tuple[str, str]]) -> list[dict]:
    """
    Chapter start times from the synthesised parts: [(part_text, part_mp3_path), ...] in playback order.
    A heading at the start of a part starts the chapter at the part's start; a heading inside a part is placed
    proportionally to its character offset within that part.
    """
    from backend.exporter import _is_chapter_heading
    marks: list[dict] = []
    t_ms = 0.0
    for text, path in parts:
        try:
            from mutagen.mp3 import MP3
            dur_ms = float(MP3(path).info.length or 0.0) * 1000.0
        except Exception:
            dur_ms = 0.0
        if dur_ms <= 0:
            # Unreadable header: estimate from size at edge-tts' 48 kbit/s so later chapter marks don't shift
            try:
                dur_ms = Path(path).stat().st_size * 8 / 48.0
            except OSError:
                dur_ms = 0.0
        if dur_ms <= 0:
            continue
        offset = 0
        for line in (text or "").split("\n"):
            stripped = line.strip()
            if stripped and _is_chapter_heading(stripped):
                start = t_ms + dur_ms * (offset / max(len(text), 1))
                if not marks or start - marks[-1]["start_ms"] > 1000:
                    marks.append({"start_ms": int(start), "title": stripped[:80]})
            offset += len(line) + 1
        t_ms += dur_ms
    if marks and marks[0]["start_ms"] > 1000:
        marks.insert(0, {"start_ms": 0, "title": "Εισαγωγή"})
    if marks:
        marks[-1]["end_ms"] = int(t_ms)
    return marks if len(marks) >= 2 else []


def _ffmeta_escape(v: str) -> str:
    return "".join("\\" + c if c in "=;#\\\n" else c for c in str(v))


def build_ffmetadata(chapters: list[dict], title: str = "", author: str = "") -> str:
    """FFMETADATA1 document with one [CHAPTER] block per chapter (millisecond timebase)."""
    total_end = max((c.get("end_ms", 0) for c in chapters), default=0)
    lines = [";FFMETADATA1", f"title={_ffmeta_escape(title or 'Audiobook')}", f"artist={_ffmeta_escape(author or 'BookApp')}"]
    for i, ch in enumerate(chapters):
        start = int(ch["start_ms"])
        end = int(chapters[i + 1]["start_ms"]) if i + 1 < len(chapters) else int(ch.get("end_ms") or total_end or start + 1)
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={max(end, start + 1)}",
                  f"title={_ffmeta_escape(ch['title'])}"]
    return "\n".join(lines) + "\n"


class M4BExportError(RuntimeError):
    """The M4B conversion failed; no .m4b file was written."""


class M4BUnavailableError(M4BExportError):
    """There is no ffmpeg to encode M4B with."""


def find_ffmpeg() -> Optional[str]:
    """ffmpeg from PATH, otherwise the binary bundled with the imageio-ffmpeg package."""
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        logger.debug(f"No bundled ffmpeg: {e}")
        return None


def is_mp4_file(path) -> bool:
    """True for a real MP4/M4B container (not MP3 data saved with an .m4b name)."""
    try:
        with open(path, "rb") as f:
            return f.read(12)[4:8] == b"ftyp"
    except OSError:
        return False


async def export_audiobook_m4b(
    mp3_path: str,
    m4b_path: str,
    title: str = "",
    author: str = "",
    cover_image_path: Optional[str] = None,
    chapters: Optional[list[dict]] = None,
) -> str:
    """
    Exports a real AAC .m4b with chapter metadata (when chapters are known), optional cover art, and timeout.
    Raises M4BExportError on failure: MP3 data is never saved under the .m4b name.
    """
    import subprocess
    import uuid
    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        raise M4BUnavailableError(
            "Η εξαγωγή M4B χρειάζεται το FFmpeg, που δεν βρέθηκε στον υπολογιστή του BookApp. "
            "Εκτελέστε 'pip install -r requirements.txt' ή εγκαταστήστε το FFmpeg. Το MP3 παραμένει διαθέσιμο."
        )

    dest = Path(m4b_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    staged = dest.with_name(f".{dest.stem}.{token}.part")  # not *.m4b: downloads must not pick up a partial file
    meta_file = None
    if chapters:
        meta_file = dest.with_name(f".{dest.stem}.{token}.ffmeta.txt")
        meta_file.write_text(build_ffmetadata(chapters, title, author), encoding="utf-8")

    def build_cmd(with_cover: bool) -> list[str]:
        # All inputs must precede the output options (-map, -c:v, ...)
        cmd = [ffmpeg_bin, "-y", "-i", mp3_path]
        if with_cover:
            cmd.extend(["-i", str(cover_image_path)])
        if meta_file is not None:
            meta_idx = 2 if with_cover else 1
            cmd.extend(["-i", str(meta_file), "-map_metadata", str(meta_idx), "-map_chapters", str(meta_idx)])
        cmd.extend(["-map", "0:a:0"])
        if with_cover:
            cmd.extend(["-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic"])
        cmd.extend([
            "-c:a", "aac", "-b:a", "64k",
            "-metadata", f"title={title or 'Audiobook'}",
            "-metadata", f"artist={author or 'BookApp'}",
            "-metadata", "genre=Audiobook",
            "-f", "ipod",
            str(staged),
        ])
        return cmd

    # AAC encoding time grows with length
    size_mb = Path(mp3_path).stat().st_size / (1024 * 1024) if Path(mp3_path).exists() else 0
    ff_timeout = max(300, int(300 + size_mb * 4))

    def convert() -> None:
        has_cover = bool(cover_image_path and Path(cover_image_path).exists())
        last_error = None
        try:
            # An unreadable cover (EMF, GIF...) must not cost the whole audiobook: retry without it
            for with_cover in ([True, False] if has_cover else [False]):
                try:
                    subprocess.run(build_cmd(with_cover), capture_output=True, stdin=subprocess.DEVNULL,
                                   check=True, timeout=ff_timeout)
                    os.replace(staged, dest)
                    return
                except (subprocess.SubprocessError, OSError) as e:
                    last_error = e
                    detail = (getattr(e, "stderr", None) or b"")[-600:].decode("utf-8", "replace")
                    logger.warning(f"ffmpeg M4B conversion failed (cover={with_cover}): {e} {detail}")
            raise M4BExportError("Η μετατροπή σε M4B απέτυχε. Το MP3 παραμένει διαθέσιμο.") from last_error
        finally:
            staged.unlink(missing_ok=True)
            if meta_file is not None:
                meta_file.unlink(missing_ok=True)

    await asyncio.to_thread(convert)
    return m4b_path


def _resolve_voice_code(language: str, voice_name: Optional[str], fallback_default: bool = True) -> Optional[str]:
    lang_norm = (language or "english").strip().lower()
    if lang_norm in ("el", "gr"):
        lang_norm = "greek"
    elif lang_norm == "en":
        lang_norm = "english"
    lang_map = VOICES.get(lang_norm, {})
    if voice_name:
        # Exact display-name match
        if voice_name in lang_map:
            return lang_map[voice_name]
        # Raw Edge-TTS voice code match (e.g. 'el-GR-AthinaNeural')
        for code in lang_map.values():
            if code.lower() == voice_name.strip().lower():
                return code
        # Case-insensitive display-name match
        vn_low = voice_name.strip().lower()
        for label, code in lang_map.items():
            if label.lower() == vn_low:
                return code
    if not fallback_default:
        return None
    if lang_map:
        return next(iter(lang_map.values()))
    return "en-US-AriaNeural"


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
    pitch: Optional[str] = None,
    volume: Optional[str] = None,
    dialogue_voice: Optional[str] = None,
    ai_polish: bool = False,
    api_key: Optional[str] = None,
    quota_behavior: str = "wait",
) -> str:
    """
    Generates an MP3 or M4B audiobook from a document or pre-translated text file.
    Supports single or multi-voice dramatization (dialogue vs narrator).

    Args:
        job_id: Job identifier for progress updates
        file_path: Original document path
        file_type: 'pdf', 'docx', or 'epub'
        language: 'english' or 'greek'
        voice_name: Display name from VOICES dict (e.g. 'Nestoras (Male)')
        output_path: Path to write final .mp3 or .m4b
        translated_text_path: If set, read text from this file instead of parsing document
        dialogue_voice: Optional second voice for character speech/dialogues

    Returns:
        output_path of the generated audiobook
    """
    # Resolve primary and dialogue voice codes (case-insensitive & supports raw Edge-TTS codes)
    lang_norm = (language or "english").strip().lower()
    if lang_norm in ("el", "gr"):
        lang_norm = "greek"
    elif lang_norm == "en":
        lang_norm = "english"
    voice_code = _resolve_voice_code(lang_norm, voice_name, fallback_default=True)
    dialogue_voice_code = _resolve_voice_code(lang_norm, dialogue_voice, fallback_default=False) if dialogue_voice else None

    from backend.job_manager import is_job_cancelled
    if is_job_cancelled(job_id):
        raise asyncio.CancelledError("Audiobook generation was cancelled before starting.")

    update_job(job_id,
               status="running",
               current_step="Reading document...",
               progress=0)

    # Get text to convert
    if translated_text_path and Path(translated_text_path).exists():
        # Read from pre-translated file (strip standalone page markers without removing prose like 'PAGE 42')
        with open(translated_text_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        raw = re.sub(r"={3,}[^\n\r]*?={3,}", "", raw)
        raw = re.sub(r"(?m)^\s*PAGE\s+\d+\s*$", "", raw)
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

    # Determine prosody and style (rate, pitch, volume, pause style)
    style = (narration_style or "literature").lower()
    effective_rate = rate if rate else DEFAULT_RATES.get(style, "-12%")
    effective_pitch = pitch if pitch else DEFAULT_PITCHES.get(style, "-1Hz")
    effective_volume = volume if volume else ("+5%" if style == "poetry" else "+0%")

    if ai_polish:
        from backend.ai_polisher import polish_text_with_gemini
        from backend.gemini_key_pool import resolve_gemini_api_key

        resolved_key = resolve_gemini_api_key(api_key)
        polish_style = "poetry" if style == "poetry" else "audiobook"
        if not resolved_key:
            if quota_behavior == "fallback":
                logger.info(f"[{job_id}] No Gemini API key provided -> Defaulting to free neural TTS without Gemini polish.")
                update_job(job_id, current_step="ℹ️ Δωρεάν μοντέλο: Εκφώνηση με νευρωνικές φωνές Edge-TTS...")
                from backend.typography import format_greek_typography
                from backend.glossary import apply_glossary
                raw_text = format_greek_typography(apply_glossary(raw_text, "greek", style=polish_style))
            else:
                err_msg = "Gemini API key is required for AI Audiobook Polish. Επιλέξτε 'Αυτόματη μετάβαση σε Δωρεάν Μοντέλο' για εκφώνηση χωρίς κλειδί."
                update_job(job_id, status="error", error=err_msg)
                raise ValueError(err_msg)
        else:
            update_job(job_id, current_step="✨ AI polishing script for spoken narration...", progress=5)

            def _polish_prog(cur: int, tot: int):
                pct = 5 + int((cur / max(tot, 1)) * 15)
                update_job(job_id, current_step=f"✨ AI polishing audio script ({cur}/{tot})...", progress=pct)

            try:
                raw_text = await polish_text_with_gemini(
                    raw_text,
                    api_key=resolved_key,
                    style=polish_style,
                    job_id=job_id,
                    progress_callback=_polish_prog,
                    target_lang=lang_norm,
                    quota_behavior=quota_behavior,
                )
            except Exception as p_err:
                from backend.ai_polisher import DailyQuotaExhaustedError
                if isinstance(p_err, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                    logger.warning(f"[{job_id}] Gemini quota exhausted during audiobook script polish. Proceeding with unpolished text (fallback)...")
                    update_job(job_id, current_step="⚠️ Όριο Gemini: Συνέχιση εκφώνησης με αρχικό κείμενο...")
                else:
                    raise

    voice_segments = split_into_voice_segments(
        raw_text,
        default_voice_code=voice_code,
        dialogue_voice_code=dialogue_voice_code,
    )
    if not voice_segments:
        voice_segments = [(c, voice_code) for c in split_into_chunks(raw_text, TTS_CHUNK_SIZE)]
    total_chunks = len(voice_segments)

    start_progress = 25 if ai_polish else 10
    diag_str = f" + {dialogue_voice}" if dialogue_voice else ""
    update_job(job_id,
               total_chunks=total_chunks,
               done_chunks=0,
               progress=start_progress,
               current_step=f"🎙️ Generating neural audio in {total_chunks} parts using {voice_name}{diag_str} ({style})...")

    logger.info(
        f"[{job_id}] TTS: {total_chunks} chunks, voice={voice_code}{diag_str}, "
        f"style={style}, rate={effective_rate}, pitch={effective_pitch}, source={text_source}"
    )

    # Generate audio for each chunk concurrently (preserving order)
    temp_dir = Path(output_path).parent / f"tts_tmp_{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(TTS_CONCURRENCY)
    completed = 0
    ticker_stop = asyncio.Event()

    async def _progress_ticker():
        while not ticker_stop.is_set():
            try:
                await asyncio.sleep(2.0)
                if ticker_stop.is_set():
                    break
                from backend.job_manager import get_job
                j = get_job(job_id)
                if j and j.status == "running":
                    cur_prog = j.progress or start_progress
                    if cur_prog < 88:
                        update_job(
                            job_id,
                            progress=min(88, cur_prog + 2),
                            current_step=f"🎙️ Synthesizing audio (part {min(completed + 1, total_chunks)}/{total_chunks})...",
                        )
            except Exception:
                pass

    ticker_task = asyncio.create_task(_progress_ticker())

    async def _process_chunk(idx: int, item: tuple[str, str]) -> Optional[str]:
        nonlocal completed
        chunk, chunk_voice = item
        from backend.job_manager import is_job_cancelled
        if is_job_cancelled(job_id):
            raise asyncio.CancelledError("Audiobook generation was cancelled.")
        if not chunk.strip():
            completed += 1
            return None
        chunk_path = temp_dir / f"chunk_{idx:06d}.mp3"
        async with sem:
            if is_job_cancelled(job_id):
                raise asyncio.CancelledError("Audiobook generation was cancelled.")
            await _tts_chunk_with_retry(
                chunk,
                chunk_voice,
                str(chunk_path),
                rate=effective_rate,
                pitch=effective_pitch,
                volume=effective_volume,
                narration_style=style,
            )
        completed += 1
        pct = start_progress + int((completed / total_chunks) * (88 - start_progress))
        update_job(
            job_id,
            current_step=f"🎙️ Generated audio part {completed} of {total_chunks}...",
            done_chunks=completed,
            progress=pct,
        )
        return str(chunk_path)

    try:
        try:
            results = await asyncio.gather(*(_process_chunk(i, item) for i, item in enumerate(voice_segments)))
        except asyncio.CancelledError:
            logger.info(f"[{job_id}] Audiobook generation was cancelled.")
            update_job(job_id, status="cancelled", current_step="🛑 Cancelled by user.")
            raise
        finally:
            ticker_stop.set()
            ticker_task.cancel()
            try:
                await ticker_task
            except (asyncio.CancelledError, Exception):
                pass

        chunk_files = [p for p in results if p]

        from backend.job_manager import is_job_cancelled
        if is_job_cancelled(job_id):
            update_job(job_id, status="cancelled", current_step="🛑 Cancelled by user.")
            raise asyncio.CancelledError("Audiobook generation was cancelled by user.")

        # Concatenate all chunks into final MP3 / M4B
        update_job(job_id,
                   current_step="Assembling final audiobook...",
                   progress=92)

        # Detect cover image if available
        cover_img = None
        out_parent = Path(output_path).parent
        for cname in ("cover_image.jpg", "cover_image.png", "cover.jpg", "cover.png"):
            cand_cov = out_parent / cname
            if cand_cov.exists():
                cover_img = str(cand_cov)
                break
        book_title = Path(file_path).stem if file_path else "Audiobook"

        # Chapter marks (for M4B players) from the synthesised parts; saved next to the output so an MP3 converted
        # to M4B later (download endpoint) gets the same chapters.
        part_records = [(voice_segments[i][0], r) for i, r in enumerate(results) if r]
        chapters = await asyncio.to_thread(compute_chapter_marks, part_records)
        if chapters:
            try:
                Path(output_path).with_suffix(".chapters.json").write_text(
                    json.dumps(chapters, ensure_ascii=False), encoding="utf-8")
            except Exception as ch_err:
                logger.debug(f"[{job_id}] Chapter marks not saved: {ch_err}")

        if output_path.lower().endswith(".m4b"):
            temp_cat_mp3 = temp_dir / "full_concat.mp3"
            await _concatenate_mp3s(chunk_files, str(temp_cat_mp3))
            await export_audiobook_m4b(
                str(temp_cat_mp3),
                output_path,
                title=book_title,
                author="BookApp",
                cover_image_path=cover_img,
                chapters=chapters,
            )
        else:
            await _concatenate_mp3s(chunk_files, output_path)
            await asyncio.to_thread(
                tag_audiobook_file,
                output_path,
                title=book_title,
                author="BookApp",
                cover_image_path=cover_img,
            )

        # Automatic Final Output Refinement & Quality-Control stage (independent, non-fatal).
        # Runs before the temp dir is removed so failed sections can be re-synthesised and re-assembled.
        try:
            from backend.job_manager import get_job as _get_job
            from backend.output_refiner import (
                refine_audiobook_output_async, is_refinement_enabled, build_refinement_report,
            )
            _job = _get_job(job_id)
            if is_refinement_enabled(getattr(_job, "final_refinement", None) if _job else None):
                update_job(job_id, current_step="🔍 Τελικός έλεγχος ποιότητας ηχητικού βιβλίου...", progress=98)

                # Sections that must produce audio (segments that clean to empty text are legitimately silent)
                expected_indices = [
                    i for i, (seg_text, _v) in enumerate(voice_segments)
                    if seg_text.strip() and _clean_tts_text(seg_text, narration_style=style)
                ]

                async def _resynthesize(idx: int) -> bool:
                    if is_job_cancelled(job_id):
                        return False
                    seg_text, seg_voice = voice_segments[idx]
                    target = temp_dir / f"chunk_{idx:06d}.mp3"
                    await _tts_chunk_with_retry(
                        seg_text, seg_voice, str(target),
                        rate=effective_rate, pitch=effective_pitch, volume=effective_volume,
                        narration_style=style,
                    )
                    return target.exists() and target.stat().st_size > 0

                async def _reassemble(files: list[str], dest: str) -> None:
                    if dest.lower().endswith(".m4b"):
                        heal_mp3 = temp_dir / "full_concat_refined.mp3"
                        await _concatenate_mp3s(files, str(heal_mp3))
                        await export_audiobook_m4b(str(heal_mp3), dest, title=book_title,
                                                   author="BookApp", cover_image_path=cover_img, chapters=chapters)
                    else:
                        await _concatenate_mp3s(files, dest)
                        await asyncio.to_thread(tag_audiobook_file, dest, title=book_title, author="BookApp",
                                                cover_image_path=cover_img)

                audio_refine_res = await refine_audiobook_output_async(
                    job_id=job_id,
                    output_path=output_path,
                    chunk_files=chunk_files,
                    expected_chunks=total_chunks,
                    expected_indices=expected_indices,
                    language=language,
                    book_title=book_title,
                    cover_image_path=cover_img,
                    enabled=True,
                    resynthesize_chunk=_resynthesize,
                    reassemble=_reassemble,
                )
                update_job(job_id, refinement_report=build_refinement_report(audio_refine_res))
            else:
                update_job(job_id, refinement_report={"status": "skipped"})
        except asyncio.CancelledError:
            raise
        except Exception as ref_err:
            logger.warning(f"[{job_id}] Final audiobook refinement failed ({ref_err}); original audio preserved.", exc_info=True)
    finally:
        # Always clean up temp directory (even on concatenation/M4B/disk errors)
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    update_job(job_id,
               status="done",
               progress=100,
               current_step="Audiobook ready!",
               output_path=output_path,
               done_chunks=total_chunks)

    logger.info(f"[{job_id}] Audiobook complete → {output_path}")
    return output_path


def _clean_tts_text(text: str, narration_style: str = "literature") -> str:
    """Prepares text for TTS, preserving natural breath pauses, elisions, and poetic rhythm without unnatural voids."""
    if not text:
        return ""

    # Remove bullet symbols and non-pronounceable markers that cause edge-tts Athina to fail
    text = re.sub(r"[•▪▫◦■□✓➢❖✔✉]", " ", text)
    text = re.sub(r"[\ue000-\uf8ff]", " ", text)

    # Normalize Greek ano teleia (·) to comma for smooth natural breathing pause without TTS stutter
    text = text.replace("·", ",")

    # Normalize typographical single quotes and Greek elision marks (’, ʼ, `, ´) to standard apostrophe
    text = re.sub(r"[’ʼ`´]", "'", text)

    style = (narration_style or "literature").lower()

    if style == "poetry":
        # In poetry, preserve verse lines (\n) and stanzas (\n\n) so the neural TTS engine
        # recites line-by-line with authentic poetic cadence and natural verse breathing,
        # without flattening verses into continuous prose or adding artificial double ellipses.
        stanzas = re.split(r"\n\s*\n+", text.strip())
        formatted_stanzas = []
        for stanza in stanzas:
            lines = [ln.strip() for ln in stanza.splitlines() if ln.strip()]
            if not lines:
                continue
            formatted_stanzas.append("\n".join(lines))
        text = "\n\n".join(formatted_stanzas)
        # Convert inline parenthetical dashes to pause commas without breaking numeric ranges (1990–2000) or line-opening dialogue dashes
        text = re.sub(r"(?<=[^\d\n])[ \t]*[—–][ \t]*(?=[^\d])", ", ", text)
    elif style in ("literature", "slow_pauses"):
        # Preserve paragraph/chapter breaks as natural sentence pauses so narration doesn't rush or drag
        paragraphs = re.split(r"\n\s*\n+", text.strip())
        formatted = []
        for para in paragraphs:
            p = re.sub(r"[\r\n]+", " ", para).strip()
            if not p:
                continue
            # Do not append extra period after closing quote/paren that already follows sentence punctuation (e.g. '«Γεια σου!»')
            tail_clean = p.rstrip('»"”\')]}')
            if p[-1] not in ".!?;:…" and not (tail_clean and tail_clean[-1] in ".!?;:…"):
                p += "."
            formatted.append(p)
        # For relaxed pauses, a single gentle ' ... ' gives a dignified break; for literature, standard sentence cadence
        sep = " ... " if style == "slow_pauses" else " "
        text = sep.join(formatted)
        text = re.sub(r"(?<=[^\d\n])[ \t]*[—–][ \t]*(?=[^\d])", ", ", text)
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
    rate: str = "-12%",
    pitch: str = "-1Hz",
    volume: str = "+0%",
    narration_style: str = "literature",
    timeout_seconds: float = 60.0,
):
    """Generates TTS for a text chunk with retry logic and timeout, maintaining consistent voice throughout."""
    clean_text = _clean_tts_text(text, narration_style=narration_style)
    if not clean_text:
        Path(output_path).write_bytes(b"")
        return

    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(clean_text, voice, rate=rate, pitch=pitch, volume=volume)
            await asyncio.wait_for(communicate.save(output_path), timeout=timeout_seconds)
            if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                return
            await asyncio.sleep(0.5 * (attempt + 1))
        except Exception as e:
            wait = (attempt + 1) * 1.0
            logger.warning(f"TTS attempt {attempt+1} failed ({voice}): {e}. Retrying in {wait}s...")
            # On retry, aggressively clean any exotic punctuation while keeping text
            if attempt >= 0:
                cleaned_retry = re.sub(r"[^\w\s\.,;:!?\-«»'\"()–—%$€]", " ", clean_text)
                cleaned_retry = re.sub(r"\s+", " ", cleaned_retry).strip()
                if cleaned_retry:
                    clean_text = cleaned_retry
            await asyncio.sleep(wait)

    # If all retries fail, create a silent placeholder without mixing voices
    logger.error(f"TTS failed after retries for chunk with {voice}. Writing empty file.")
    Path(output_path).write_bytes(b"")


async def _concatenate_mp3s(chunk_files: list[str], output_path: str):
    """Concatenates MP3 files by streamed binary concatenation (fast, zero memory overhead, no re-encoding)."""
    import shutil
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Filter out empty files
    valid_files = [f for f in chunk_files if Path(f).exists() and Path(f).stat().st_size > 0]

    if not valid_files:
        raise RuntimeError("No valid audio chunks to concatenate.")

    # Streamed binary concatenation works for CBR MP3s (edge-tts output). Runs in a worker thread: a full audiobook
    # can be hundreds of MB, and copying it on the event loop would freeze the server (SSE progress, other requests).
    def _concat_sync() -> None:
        with open(output_path, "wb") as out_f:
            for chunk_file in valid_files:
                with open(chunk_file, "rb") as in_f:
                    shutil.copyfileobj(in_f, out_f, length=1024 * 1024)

    await asyncio.to_thread(_concat_sync)


def get_available_voices() -> dict:
    """Returns the VOICES dict for the frontend."""
    return VOICES
