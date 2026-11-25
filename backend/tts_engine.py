"""
TTS Engine - generates audiobooks using Microsoft edge-tts neural voices.
Supports Greek (el-GR) and English (en-US) with multiple voice options.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

import edge_tts
from edge_tts.exceptions import NoAudioReceived
from backend.parsers import parse_document, split_into_chunks
from backend.job_manager import update_job

logger = logging.getLogger(__name__)

# Available voices grouped by language
VOICES = {
    "greek": {
        "Nestoras (Male)": "el-GR-NestorasNeural",
    },
    "english": {
        "Aria (Female)": "en-US-AriaNeural",
        "Guy (Male)": "en-US-GuyNeural",
        "Jenny (Female)": "en-US-JennyNeural",
        "Brian (Male)": "en-US-BrianNeural",
        "Emma (Female)": "en-GB-SoniaNeural",
        "Ryan (Male)": "en-GB-RyanNeural",
    },
}

# Saved jobs and settings may still name these: Davis was retired by Microsoft (Brian reads), and Athina was removed
# because Microsoft's service refuses most of that voice's requests (Nestoras reads)
_RETIRED_VOICES = {
    "en-us-davisneural": "en-US-BrianNeural", "davis (male)": "en-US-BrianNeural", "davis": "en-US-BrianNeural",
    "el-gr-athinaneural": "el-GR-NestorasNeural", "athina (female)": "el-GR-NestorasNeural", "athina": "el-GR-NestorasNeural",
}
# Who reads a part that a voice refuses (the service answers "no audio"). Greek has a single voice, so no substitute.
_FALLBACK_VOICES = {
    "en-US-AriaNeural": "en-US-JennyNeural",
    "en-US-JennyNeural": "en-US-AriaNeural",
    "en-GB-SoniaNeural": "en-US-AriaNeural",
    "en-US-GuyNeural": "en-US-BrianNeural",
    "en-US-BrianNeural": "en-US-GuyNeural",
    "en-GB-RyanNeural": "en-US-GuyNeural",
}
_TTS_PIECE_STEPS = ((500, 3), (160, 4), (60, 5))  # (characters per request, attempts) after a whole part was refused
_RETRY_WAITS = (1.5, 5.0, 12.0)                   # between the attempts of a whole part
_OUTAGE_PAUSE = 30.0                              # before the second round of a voice that has no substitute
_MIN_BYTES_PER_LETTER = 40                        # normal speech is over 250 at 48 kbit/s

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
    1. Explicit tags: [Nestoras]: ..., [Aria]: ..., [VoiceName]: ...
    2. Automatic dialogue alternation: Dialogue lines (starting with '—' or enclosed in «...»)
       are routed to dialogue_voice_code, narration is routed to default_voice_code.
    """
    if not text or not str(text).strip():
        return []

    alias_map = {
        "nestoras": "el-GR-NestorasNeural",
        "athina": "el-GR-NestorasNeural",
        "aria": "en-US-AriaNeural",
        "guy": "en-US-GuyNeural",
        "jenny": "en-US-JennyNeural",
        "davis": "en-US-BrianNeural",
        "brian": "en-US-BrianNeural",
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

        # 1. Explicit speaker tag: e.g. [Nestoras]: ... or [Aria]: ...
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
    voice_code = _RETIRED_VOICES.get(voice_code.lower(), voice_code)
    tmp_file = base_temp / f"preview_{voice_code}_{uuid.uuid4().hex[:8]}.tmp"

    sample_text = text or (
        "Γεια σας! Αυτή είναι μια δοκιμή εκφώνησης για το BookApp."
        if voice_code.startswith("el")
        else "Hello! This is a preview of the neural voice narration for BookApp."
    )

    # one file per voice and text, so two previews cannot hand each other's audio out
    out_file = base_temp / f"preview_{voice_code}_{hashlib.sha256(sample_text.encode('utf-8')).hexdigest()[:10]}.mp3"
    try:
        for try_no in range(5):
            try:
                await _synthesize(sample_text, voice_code, str(tmp_file), {"rate": "-10%"}, timeout=45.0)
                break
            except (NoAudioReceived, IncompleteAudio):  # a busy voice usually answers on a repeat
                if try_no == 4:
                    raise
                await asyncio.sleep(0.5 * (try_no + 1))
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


_SENTENCE_END_RE = re.compile(r"(?<=[.!?…;»\"”])\s+")
_PAGE_MARKER_LINE_RE = re.compile(r"^\s*(?:={3,}\s*PAGE\s+\d+\s*={3,}|={6,}|PAGE\s+\d+)\s*$", re.IGNORECASE)
_PAUSE_WEIGHT = 12  # characters' worth of time for the pause at the end of a sentence


def _part_duration_ms(path: str) -> float:
    try:
        from mutagen.mp3 import MP3
        dur_ms = float(MP3(path).info.length or 0.0) * 1000.0
    except Exception:
        dur_ms = 0.0
    if dur_ms <= 0:  # an unreadable header: from the size at edge-tts' 48 kbit/s, so later times do not shift
        try:
            dur_ms = Path(path).stat().st_size * 8 / 48.0
        except OSError:
            dur_ms = 0.0
    return dur_ms


def compute_read_along(parts: list[tuple[str, str]]) -> list[dict]:
    """
    The book's sentences with their times, for reading along: [{"s": start_ms, "e": end_ms, "t": text, "p": 1 when the
    sentence opens a paragraph}], from the synthesised parts [(part_text, part_mp3_path), ...] in playback order.
    Each part's real duration is measured; inside a part, a sentence's share follows its length plus a short pause.
    """
    segments: list[dict] = []
    t_ms = 0.0
    for text, path in parts:
        dur_ms = _part_duration_ms(path)
        if dur_ms <= 0:
            continue
        sentences: list[tuple[str, bool]] = []
        for para in re.split(r"\n\s*\n|\n", text or ""):
            if not para.strip() or _PAGE_MARKER_LINE_RE.match(para) or not any(ch.isalpha() for ch in para):
                continue
            pieces: list[str] = []
            for piece in _SENTENCE_END_RE.split(para.strip()):
                if pieces and piece[:1].islower():  # «Πού πάμε;» ρώτησε: the sentence goes on
                    pieces[-1] += " " + piece
                elif piece.strip():
                    pieces.append(piece.strip())
            sentences += [(s, k == 0) for k, s in enumerate(pieces)]
        weights = [len(s) + _PAUSE_WEIGHT for s, _ in sentences]
        total = sum(weights)
        start = t_ms
        for (sentence, opens), weight in zip(sentences, weights):
            end = start + dur_ms * weight / total
            segments.append({"s": round(start), "e": round(end), "t": sentence, "p": 1 if opens else 0})
            start = end
        t_ms += dur_ms
    return segments


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
        dur_ms = _part_duration_ms(path)
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
        retired = _RETIRED_VOICES.get(voice_name.strip().lower())
        if retired in lang_map.values():
            return retired
        # Exact display-name match
        if voice_name in lang_map:
            return lang_map[voice_name]
        # Raw Edge-TTS voice code match (e.g. 'el-GR-NestorasNeural')
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
    if dialogue_voice_code == voice_code:
        dialogue_voice_code = None
    labels = {code: label for group in VOICES.values() for label, code in group.items()}
    retired_notices = [
        f"{asked} is no longer offered, so {labels.get(used, used).split(' ')[0]} reads instead"
        for asked, used in {name: _RETIRED_VOICES.get(name.strip().lower())
                            for name in (voice_name, dialogue_voice) if name}.items()
        if used and used in VOICES.get(lang_norm, {}).values()
    ]

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
                if lang_norm == "greek":
                    from backend.typography import format_greek_typography
                    from backend.glossary import apply_glossary
                    raw_text = format_greek_typography(apply_glossary(raw_text, "greek", style=polish_style, translated=True))
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
    if voice_code.lower().startswith("el"):
        # an English speaker tag in a Greek book: that voice cannot read Greek, so the narrator does
        voice_segments = [
            (seg, voice_code if not code.lower().startswith("el") and any("Ͱ" <= ch <= "Ͽ" for ch in seg) else code)
            for seg, code in voice_segments
        ]
    total_chunks = len(voice_segments)

    # Finished parts survive a failure, a cancel or a restart, so Resume narrates only what is missing. The file name
    # covers everything that shapes the sound: change the text, voice or pacing and the part is narrated again.
    parts_dir = Path(output_path).parent / ".tts_parts"

    def kept_part(idx: int) -> Path:
        seg_text, seg_voice = voice_segments[idx]
        spec = json.dumps([_clean_tts_text(seg_text, narration_style=style), seg_voice,
                           effective_rate, effective_pitch, effective_volume], ensure_ascii=False)
        return parts_dir / f"{hashlib.sha256(spec.encode('utf-8')).hexdigest()}.audio"

    reusable = sum(1 for i in range(total_chunks) if _has_bytes(kept_part(i))) if parts_dir.is_dir() else 0
    start_progress = 25 if ai_polish else 10
    diag_str = f" + {labels.get(dialogue_voice_code, dialogue_voice_code)}" if dialogue_voice_code else ""
    resumed_str = f" ({reusable} already narrated)" if reusable else ""
    update_job(job_id,
               total_chunks=total_chunks,
               done_chunks=0,
               progress=start_progress,
               current_step=f"🎙️ Generating neural audio in {total_chunks} parts{resumed_str} using "
                            f"{labels.get(voice_code, voice_code)}{diag_str} ({style})...")

    logger.info(
        f"[{job_id}] TTS: {total_chunks} chunks, voice={voice_code}{diag_str}, "
        f"style={style}, rate={effective_rate}, pitch={effective_pitch}, source={text_source}"
    )

    # Generate audio for each chunk concurrently (preserving order)
    temp_dir = Path(output_path).parent / f"tts_tmp_{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(TTS_CONCURRENCY)
    tts_state = TtsState(cancelled=lambda: is_job_cancelled(job_id))
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
                    # creep towards the next finished part only: a part can take over a minute
                    below_next = start_progress + int((min(completed + 1, total_chunks) / total_chunks) * (88 - start_progress)) - 1
                    if cur_prog < below_next:
                        update_job(
                            job_id,
                            progress=cur_prog + 1,
                            current_step=f"🎙️ Synthesizing audio (part {min(completed + 1, total_chunks)}/{total_chunks})...",
                        )
            except Exception:
                pass

    ticker_task = asyncio.create_task(_progress_ticker())

    async def _narrate_part(idx: int) -> None:
        seg_text, seg_voice = voice_segments[idx]
        target = temp_dir / f"chunk_{idx:06d}.mp3"
        used = await _tts_chunk_with_retry(
            seg_text,
            seg_voice,
            str(target),
            rate=effective_rate,
            pitch=effective_pitch,
            volume=effective_volume,
            narration_style=style,
            state=tts_state,
        )
        if used == seg_voice and _has_bytes(target):  # a substitute's recording is never kept as this voice's
            _link_or_copy(target, kept_part(idx))

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
        kept = kept_part(idx)
        if not (_has_bytes(kept) and _link_or_copy(kept, chunk_path)):
            async with sem:
                if is_job_cancelled(job_id):
                    raise asyncio.CancelledError("Audiobook generation was cancelled.")
                await _narrate_part(idx)
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
            from backend.async_utils import gather_or_cancel
            results = await gather_or_cancel(_process_chunk(i, item) for i, item in enumerate(voice_segments))
        except asyncio.CancelledError:
            # only the user's Cancel is a cancellation; a server shutdown leaves the job resumable
            if is_job_cancelled(job_id):
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
        # Sections that must produce audio (a scene break, or a script the voice cannot read, is legitimately silent)
        expected_indices = [
            i for i, (seg_text, seg_voice) in enumerate(voice_segments)
            if seg_text.strip() and is_speakable(_clean_tts_text(seg_text, narration_style=style), seg_voice)
        ]

        from backend.job_manager import is_job_cancelled
        if is_job_cancelled(job_id):
            update_job(job_id, status="cancelled", current_step="🛑 Cancelled by user.")
            raise asyncio.CancelledError("Audiobook generation was cancelled by user.")

        if expected_indices and not any(_has_bytes(temp_dir / f"chunk_{i:06d}.mp3") for i in expected_indices):
            error = _not_narrated([i + 1 for i in expected_indices], total_chunks)
            update_job(job_id, status="error", error=error)
            raise NarrationError(error)  # nothing to assemble: no connection, or the service is down

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
        marks_file = Path(output_path).with_suffix(".chapters.json")
        try:
            if chapters:
                marks_file.write_text(json.dumps(chapters, ensure_ascii=False), encoding="utf-8")
            else:
                marks_file.unlink(missing_ok=True)  # the marks of an earlier recording are wrong for this one
        except Exception as ch_err:
            logger.warning(f"[{job_id}] Chapter marks not saved: {ch_err}")

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

                async def _resynthesize(idx: int) -> bool:
                    if is_job_cancelled(job_id):
                        return False
                    await _narrate_part(idx)
                    return _has_bytes(temp_dir / f"chunk_{idx:06d}.mp3")

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

        silent = []
        for i in expected_indices:
            part = temp_dir / f"chunk_{i:06d}.mp3"
            if not part.is_file() or part.stat().st_size == 0:
                silent.append(i + 1)
        if silent:
            # never hand out a book with holes in it as finished
            Path(output_path).unlink(missing_ok=True)
            error = _not_narrated(silent, total_chunks)
            update_job(job_id, status="error", error=error)
            raise NarrationError(error)

        # Reading along: every sentence's time in the finished recording (after any re-narrated parts)
        sync_file = Path(output_path).with_suffix(".sync.json")
        try:
            final_parts = [(voice_segments[i][0], str(temp_dir / f"chunk_{i:06d}.mp3")) for i in range(total_chunks)
                           if _has_bytes(temp_dir / f"chunk_{i:06d}.mp3")]
            segments = await asyncio.to_thread(compute_read_along, final_parts)
            if segments:
                sync_file.write_text(json.dumps({"version": 1, "segments": segments}, ensure_ascii=False,
                                                separators=(",", ":")), encoding="utf-8")
            else:
                sync_file.unlink(missing_ok=True)
        except Exception as sync_err:
            logger.warning(f"[{job_id}] Read-along times not saved: {sync_err}")
    finally:
        # Always clean up temp directory (even on concatenation/M4B/disk errors); finished parts stay for Resume
        shutil.rmtree(temp_dir, ignore_errors=True)

    shutil.rmtree(parts_dir, ignore_errors=True)  # the book is complete
    final_step = "Audiobook ready!"
    notices = list(retired_notices)
    unreadable = sum(1 for text, code in voice_segments
                     if any(ch.isalpha() for ch in text) and not is_speakable(text, code))
    if unreadable:
        notices.append(f"{unreadable} part(s) in a script this voice cannot read were skipped")
    if tts_state.substituted:
        names = {code: label.split(" ")[0] for group in VOICES.values() for label, code in group.items()}
        swaps = "; ".join(f"{count} part(s) read by {names.get(used, used)}, because {names.get(wanted, wanted)} returned no audio"
                          for (wanted, used), count in tts_state.substituted.items())
        notices.append(swaps)
    if notices:
        final_step = f"⚠️ Audiobook ready! {'; '.join(notices)}."
        logger.warning(f"[{job_id}] {final_step}")

    update_job(job_id,
               status="done",
               progress=100,
               current_step=final_step,
               output_path=output_path,
               done_chunks=total_chunks)

    logger.info(f"[{job_id}] Audiobook complete → {output_path}")
    return output_path


def _clean_tts_text(text: str, narration_style: str = "literature") -> str:
    """Prepares text for TTS, preserving natural breath pauses, elisions, and poetic rhythm without unnatural voids."""
    if not text:
        return ""
    from backend.exporter import _plain_emphasis
    text = _plain_emphasis(text)  # '**word**' is formatting, not two asterisks to read out

    # Remove bullet symbols and non-pronounceable markers that edge-tts refuses
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


class NarrationError(RuntimeError):
    """Parts of the book got no audio: a failure of the voice service, whatever the Gemini quota is."""


def _not_narrated(silent: list, total: int) -> str:
    shown = ", ".join(map(str, silent[:8]))
    return (f"{len(silent)} of {total} parts could not be narrated (parts {shown}): the voice service "
            "returned no complete audio. The finished parts are kept: press Resume in a few minutes.")


class IncompleteAudio(RuntimeError):
    """The service closed the stream before the end of the text."""


class TtsState:
    """What one narration learned about its voices."""

    def __init__(self, cancelled=None):
        self.cancelled = cancelled or (lambda: False)
        self.failures: dict[str, int] = {}      # consecutive parts a voice failed completely
        self.refused: dict[str, bool] = {}      # whether the voice said no the last time, or could not be reached
        self.substituted: dict[tuple[str, str], int] = {}


def _readable_chars(voice: str) -> str:
    return r"[0-9A-Za-zÀ-ɏͰ-Ͽἀ-῿]" if voice.lower().startswith("el") else r"[0-9A-Za-zÀ-ɏ]"


def is_speakable(text: str, voice: str) -> bool:
    """False for text without anything the voice can read (scene breaks, a quotation in another script)."""
    return bool(re.search(_readable_chars(voice), text or ""))


def _has_bytes(path) -> bool:
    try:
        return Path(path).stat().st_size > 0
    except OSError:
        return False


def _replace_file(src: Path, dest: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(src, dest)
            return
        except PermissionError:  # a virus scanner can hold a new file for a moment
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _link_or_copy(src: Path, dest: Path) -> bool:
    staged = dest.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, staged)
        except OSError:
            shutil.copyfile(src, staged)
        _replace_file(staged, dest)
        return True
    except OSError as e:
        logger.warning(f"Could not re-use a narrated part ({e}).")
        return False
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass


def _write_audio(path: str, data: bytes) -> None:
    """Never writes into an existing file: a narrated part may share its bytes (hard link) with the copy kept for Resume."""
    Path(path).unlink(missing_ok=True)
    Path(path).write_bytes(data)


async def _synthesize(text: str, voice: str, path: str, prosody: dict, timeout: Optional[float] = None) -> None:
    """
    Writes the complete audio of `text` to `path`, or raises. edge-tts keeps whatever arrived when the service closes
    the stream early and reports nothing: only a stream ended by the service's "turn.end" counts as complete.
    The default limit grows with the text, because the Greek service delivers at about the speed of speech.
    """
    staged = Path(f"{path}.part")
    communicate = edge_tts.Communicate(text, voice, **prosody)
    try:
        await asyncio.wait_for(communicate.save(str(staged)), timeout=timeout or 90.0 + 0.3 * len(text))
        if not _has_bytes(staged):
            raise NoAudioReceived("No audio was received.")
        size = staged.stat().st_size
        stream = getattr(communicate, "state", None)
        if isinstance(stream, dict):
            ended = stream.get("cumulative_audio_bytes")  # counts only the audio of finished turns
            letters = len(re.findall(_readable_chars(voice), text))
            if (ended is not None and ended != size) or (letters >= 80 and size < _MIN_BYTES_PER_LETTER * letters):
                raise IncompleteAudio(f"{size} bytes for {len(text)} characters")
        _replace_file(staged, Path(path))
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass


async def _narrate_in_pieces(text: str, voice: str, output_path: str, prosody: dict, timeout: Optional[float],
                             state: TtsState, step: int = 0) -> Optional[bytes]:
    """Audio of `text` made from shorter requests; None when a piece gets no audio at the smallest size either."""
    size, attempts = _TTS_PIECE_STEPS[step]
    smallest = step + 1 == len(_TTS_PIECE_STEPS)
    piece_file = Path(f"{output_path}.piece")
    audio = bytearray()
    try:
        for piece in split_into_chunks(text, size):
            if not is_speakable(piece, voice):
                continue
            got = None
            for attempt in range(attempts):
                if attempt:
                    await asyncio.sleep(1.0 * attempt)
                if state.cancelled():
                    return None
                request = piece
                if smallest and attempt + 1 == attempts:  # the last resort: without exotic symbols
                    plain = re.sub(r"[^\w\s\.,;:!?\-«»'\"()–—%$€]", " ", piece)
                    request = re.sub(r"\s+", " ", plain).strip() or piece
                try:
                    await _synthesize(request, voice, str(piece_file), prosody, timeout)
                    got = piece_file.read_bytes()
                    break
                except Exception as e:
                    logger.info(f"TTS piece attempt {attempt + 1}/{attempts} failed ({voice}, {len(piece)} chars): {e}")
            if got is None and not smallest:
                got = await _narrate_in_pieces(piece, voice, output_path, prosody, timeout, state, step + 1)
            if got is None:
                return None
            audio += got
        return bytes(audio) or None
    finally:
        piece_file.unlink(missing_ok=True)


async def _tts_chunk_with_retry(
    text: str,
    voice: str,
    output_path: str,
    retries: int = 4,
    rate: str = "-12%",
    pitch: str = "-1Hz",
    volume: str = "+0%",
    narration_style: str = "literature",
    timeout_seconds: Optional[float] = None,
    state: Optional["TtsState"] = None,
) -> Optional[str]:
    """
    Generates TTS for a text chunk and returns the voice that read it. A refused chunk is asked again, then in
    shorter pieces, then (English) read by another voice of the same language, recorded in ``state``. None and an
    empty file mean failure (or text with nothing to speak).
    """
    clean_text = _clean_tts_text(text, narration_style=narration_style)
    if not is_speakable(clean_text, voice):
        _write_audio(output_path, b"")
        return None
    state = state or TtsState()
    prosody = {"rate": rate, "pitch": pitch, "volume": volume}

    async def whole(voice_code: str) -> tuple[bool, bool]:
        """(succeeded, the service refused or cut the audio)"""
        refused = False
        for attempt in range(retries):
            if attempt:
                await asyncio.sleep(_RETRY_WAITS[min(attempt, len(_RETRY_WAITS)) - 1])
            if state.cancelled():
                break
            try:
                await _synthesize(clean_text, voice_code, output_path, prosody, timeout_seconds)
                return True, False
            except Exception as e:
                refused = refused or isinstance(e, (NoAudioReceived, IncompleteAudio))
                logger.warning(f"TTS attempt {attempt + 1}/{retries} failed ({voice_code}, {len(clean_text)} chars): "
                               f"{type(e).__name__}: {e}")
        return False, refused

    substitute = _FALLBACK_VOICES.get(voice)
    refused = state.refused.get(voice, True)
    if state.failures.get(voice, 0) < 3:
        for round_no in range(2 if retries > 1 else 1):
            if round_no:
                await asyncio.sleep(_OUTAGE_PAUSE)
            if state.cancelled():
                break
            done, refused = await whole(voice)
            if not done:
                if state.cancelled():
                    break
                if not refused:
                    continue  # no connection, or no answer in time: ask again later, shorter would not help
                audio = await _narrate_in_pieces(clean_text, voice, output_path, prosody, timeout_seconds, state)
                if not audio:
                    if substitute:
                        break
                    continue
                _write_audio(output_path, audio)
            state.failures.pop(voice, None)
            return voice
        if not state.cancelled():
            state.failures[voice] = state.failures.get(voice, 0) + 1
            state.refused[voice] = refused  # only a voice that says no is replaced by another

    if refused and substitute and not state.cancelled() and is_speakable(clean_text, substitute):
        done, _ = await whole(substitute)
        if done:
            key = (voice, substitute)
            state.substituted[key] = state.substituted.get(key, 0) + 1
            logger.warning(f"{voice} returned no audio for a part; it was read by {substitute}.")
            return substitute

    # If all retries fail, leave an empty file: the caller retries it or reports the failure
    logger.error(f"TTS failed after retries for chunk with {voice}. Writing empty file.")
    _write_audio(output_path, b"")
    return None


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
