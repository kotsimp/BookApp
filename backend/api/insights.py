"""
backend/api/insights.py - Book Insights endpoints (APIRouter included by backend.main).
"""

import re
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api.common import OUTPUT_DIR, MIME_MAP, _validate_job_id, _job_output_dir, _validate_language
from backend.job_manager import get_job

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Book Insights (summaries, synopses & audio versions) — backend/book_insights.py
# ---------------------------------------------------------------------------

from backend import book_insights as _book_insights_mod  # noqa: E402
_book_insights_mod.TASK_INDEX_PATH = OUTPUT_DIR / ".insights_tasks.json"


class InsightsGenerateRequest(BaseModel):
    job_id: str
    insight_type: str                     # one_sentence | short_summary | extended_summary | standard_synopsis |
                                          # extended_synopsis | summary (basic) | synopsis (basic)
    language: Optional[str] = None        # 'greek' | 'english' | None/'auto' (= document language)
    api_key: Optional[str] = None
    until: Optional[int] = None           # recap: the story so far up to this page (chapter, for an EPUB)


class InsightsAskRequest(BaseModel):
    job_id: str
    question: str
    language: Optional[str] = None        # 'greek' | 'english' | None/'auto' (= the question's language)
    api_key: Optional[str] = None


class InsightsGlossaryRequest(BaseModel):
    job_id: str
    language: str = "greek"               # the characters record whose names go to the Glossary
    sources: Optional[list[str]] = None   # only these names/terms (all when omitted)


class InsightsExportRequest(BaseModel):
    job_id: str
    insight_type: str
    language: str
    format: str                           # pdf | docx | doc | txt


class InsightsAudioRequest(BaseModel):
    job_id: str
    insight_type: str
    language: str
    voice_name: Optional[str] = None


def _insights_http_error(e) -> HTTPException:
    return HTTPException(getattr(e, "http_status", 400), detail=e.user_message)


def _insights_job(job_id: str):
    _validate_job_id(job_id)
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Το έγγραφο δεν βρέθηκε. Ανεβάστε το ξανά.")
    return job


async def _insights_source_text(job) -> str:
    from backend.book_insights import extract_document_text, InsightsError
    if (job.file_type or "").lower() in ("cbz", "cbr", "zip") or (getattr(job, "layout_mode", "") or "") == "comic":
        raise _insights_http_error(InsightsError("unsupported_format"))
    try:
        return await asyncio.to_thread(extract_document_text, job.file_path, job.file_type)
    except InsightsError as e:
        raise _insights_http_error(e)


def _insights_resolve_type(raw: str) -> str:
    from backend.book_insights import INSIGHT_TYPES, BASIC_TYPES, InsightsError
    from backend.insights_more import EXTRA_TYPES
    t = (raw or "").strip().lower()
    t = BASIC_TYPES.get(t, t)
    if t not in INSIGHT_TYPES and t not in EXTRA_TYPES:
        raise _insights_http_error(InsightsError("invalid_request"))
    return t


def _hidden_job(job_id: str) -> bool:
    """True for an existing job of another user (user accounts mode)."""
    from backend.job_manager import job_owner
    from backend.request_context import can_view_owner
    owner = job_owner(job_id)
    return owner is not None and not can_view_owner(owner)


def _insights_public_record(job_id: str, rec: dict) -> dict:
    pub = {k: v for k, v in rec.items() if k not in ("source_hash", "text_hash", "audio_text_hash")}
    if rec.get("audio_file"):
        pub["audio_url"] = f"/api/insights/{job_id}/files/{rec['audio_file']}"
    return pub


@router.get("/api/insights/tasks/{task_id}")
async def insights_task_status(task_id: str):
    """Progress / result of a Book Insights background task."""
    from backend.book_insights import get_task
    if not re.fullmatch(r"[0-9a-f]{32}", task_id or ""):
        raise HTTPException(400, "Invalid task id.")
    task = get_task(task_id)
    if task and _hidden_job(task.job_id):   # another user's task (user accounts mode)
        raise HTTPException(404, "Η εργασία δεν βρέθηκε.")
    if not task:
        from backend.book_insights import recover_task
        recovered = recover_task(task_id, _job_output_dir)
        if recovered and _hidden_job(recovered.get("job_id", "")):
            recovered = None
        if recovered:
            if recovered.get("result"):
                recovered["result"] = _insights_public_record(recovered["job_id"], recovered["result"])
            return recovered
        raise HTTPException(404, "Η εργασία δεν βρέθηκε (ίσως έγινε επανεκκίνηση του διακομιστή). Δοκιμάστε ξανά.")
    data = task.public()
    if data.get("result"):
        data["result"] = _insights_public_record(task.job_id, data["result"])
    return data


@router.get("/api/insights/{job_id}/analysis")
async def insights_analysis(job_id: str):
    """Meaningful-text length, detected language and summary/synopsis availability for a document."""
    from backend.book_insights import analyze_text, list_insights
    from backend.gemini_key_pool import resolve_gemini_api_key
    from backend.scan_reader import needs_reading, pages_to_read
    job = _insights_job(job_id)
    text = await _insights_source_text(job)
    info = await asyncio.to_thread(analyze_text, text)
    info["has_api_key"] = bool(resolve_gemini_api_key(None))
    info["file_name"] = job.file_name
    info["existing"] = list_insights(_job_output_dir(job_id))
    try:  # the page range for "the story so far" (chapters, for an EPUB)
        from backend.insights_more import extract_pages
        pages, unit = await asyncio.to_thread(extract_pages, job.file_path, job.file_type)
        info.update(first_page=pages[0][0] if pages else None, last_page=pages[-1][0] if pages else None, unit=unit)
    except Exception:
        info.update(first_page=None, last_page=None, unit="page")
    if await asyncio.to_thread(needs_reading, job.file_path, job.file_type, job.file_name or ""):
        # a scanned book: its text is read from the page images first (Gemini Vision), when a summary is asked for
        info["needs_scan_reading"] = True
        info["scan_pages"] = await asyncio.to_thread(pages_to_read, job.file_path)
        if info["has_api_key"]:
            info["can_summary"] = info["can_synopsis"] = True
    return info


@router.get("/api/insights/{job_id}")
async def insights_list(job_id: str):
    """Previously generated insights for a document (text included)."""
    from backend.book_insights import list_insights, load_insight
    _insights_job(job_id)
    out_dir = _job_output_dir(job_id)
    items = []
    for meta in list_insights(out_dir):
        rec = load_insight(out_dir, meta["insight_type"], meta["language"])
        if rec:
            items.append(_insights_public_record(job_id, rec))
    return {"job_id": job_id, "insights": items}


@router.post("/api/insights/generate")
async def insights_generate(req: InsightsGenerateRequest):
    """Starts summary/synopsis generation in the background. Identical in-flight requests are de-duplicated."""
    from backend.insights_more import EXTRA_TYPES
    if _insights_resolve_type(req.insight_type) in EXTRA_TYPES:
        return await _insights_generate_extra(req)
    from backend.book_insights import (
        start_task, generate_insight, analyze_text, InsightsError, INSIGHT_TYPES, OUTPUT_LANGUAGES,
    )
    from backend.gemini_key_pool import resolve_gemini_api_key
    job = _insights_job(req.job_id)
    insight_type = _insights_resolve_type(req.insight_type)
    lang = (req.language or "auto").strip().lower()
    if lang not in OUTPUT_LANGUAGES + ("auto",):
        raise _insights_http_error(InsightsError("invalid_request"))
    api_key = resolve_gemini_api_key(req.api_key)
    if not api_key:
        raise _insights_http_error(InsightsError("no_api_key", http_status=401))
    from backend.scan_reader import needs_reading, read_scanned_text
    text = await _insights_source_text(job)
    scanned = await asyncio.to_thread(needs_reading, job.file_path, job.file_type, job.file_name or "")

    def _check(info: dict) -> None:
        """Fail fast (before any API usage) when the document is ineligible."""
        if not info["can_summary"]:
            raise _insights_http_error(InsightsError("insufficient_text", http_status=422))
        if INSIGHT_TYPES[insight_type]["kind"] == "synopsis" and not info["can_synopsis"]:
            raise HTTPException(422, info["reasons"]["synopsis"])
        if lang == "auto" and info["detected_language"] is None:
            raise _insights_http_error(InsightsError("language_detection_failed", http_status=422))

    if not scanned:  # a scanned book is checked once its pages have been read
        _check(await asyncio.to_thread(analyze_text, text))

    out_dir = _job_output_dir(req.job_id)
    title = Path(job.file_name or "document").stem

    async def _run(task):
        def _prog(pct, step):
            task.progress, task.step = int(pct), step
        source = text
        if scanned:
            def _read_prog(done, total):
                _prog(int(done / max(total, 1) * 40), f"📖 Ανάγνωση σκαναρισμένων σελίδων (Gemini Vision): σελίδα {done} από {total}...")
            await read_scanned_text(job.file_path, api_key, progress=_read_prog)
            source = await _insights_source_text(job)
            info = await asyncio.to_thread(analyze_text, source)
            try:
                _check(info)
            except HTTPException as e:  # inside the task: reported as the task's error
                detail = e.detail if isinstance(e.detail, str) else (e.detail or {}).get("message", "")
                raise InsightsError("insufficient_text", detail or "")
        return await generate_insight(source, insight_type, None if lang == "auto" else lang, api_key,
                                      title=title, job_output_dir=out_dir, progress=_prog)

    task, duplicate = start_task(req.job_id, "generate", insight_type, lang, _run)
    return {"task_id": task.task_id, "status": task.status, "duplicate": duplicate, "insight_type": insight_type}


async def _scanned_book_read(job, api_key: str, task_progress) -> None:
    """A scanned book's pages are read first (Gemini Vision), as for summaries."""
    from backend.scan_reader import needs_reading, read_scanned_text
    if await asyncio.to_thread(needs_reading, job.file_path, job.file_type, job.file_name or ""):
        def _read_prog(done, total):
            task_progress(int(done / max(total, 1) * 40),
                          f"📖 Ανάγνωση σκαναρισμένων σελίδων (Gemini Vision): σελίδα {done} από {total}...")
        await read_scanned_text(job.file_path, api_key, progress=_read_prog)


async def _insights_generate_extra(req: InsightsGenerateRequest):
    """Characters and terms, chapter by chapter, the story so far, blurb, quotes, study guide, timeline."""
    from backend.book_insights import start_task, InsightsError, OUTPUT_LANGUAGES
    from backend.gemini_key_pool import resolve_gemini_api_key
    from backend.insights_more import generate_extra
    job = _insights_job(req.job_id)
    insight_type = _insights_resolve_type(req.insight_type)
    lang = (req.language or "auto").strip().lower()
    if lang not in OUTPUT_LANGUAGES + ("auto",):
        raise _insights_http_error(InsightsError("invalid_request"))
    if insight_type == "recap" and (req.until is None or req.until < 1):
        raise HTTPException(400, "Choose the page (or chapter) the story so far reaches.")
    api_key = resolve_gemini_api_key(req.api_key)
    if not api_key:
        raise _insights_http_error(InsightsError("no_api_key", http_status=401))
    await _insights_source_text(job)  # comics and unsupported files stop here, before any request
    out_dir = _job_output_dir(req.job_id)
    title = Path(job.file_name or "document").stem

    async def _run(task):
        def _prog(pct, step):
            task.progress, task.step = int(pct), step
        await _scanned_book_read(job, api_key, _prog)
        return await generate_extra(job.file_path, job.file_type, insight_type, None if lang == "auto" else lang,
                                    api_key, title=title, job_output_dir=out_dir, progress=_prog, until=req.until)

    task_lang = lang if insight_type != "recap" else f"{lang}@{req.until}"
    task, duplicate = start_task(req.job_id, "generate", insight_type, task_lang, _run)
    return {"task_id": task.task_id, "status": task.status, "duplicate": duplicate, "insight_type": insight_type}


@router.post("/api/insights/ask")
async def insights_ask(req: InsightsAskRequest):
    """A question answered from the book, citing its pages (one large Gemini request)."""
    import hashlib
    from backend.book_insights import start_task, InsightsError
    from backend.gemini_key_pool import resolve_gemini_api_key
    from backend.insights_more import ask_book
    job = _insights_job(req.job_id)
    question = " ".join((req.question or "").split())
    if not (3 <= len(question) <= 500):
        raise HTTPException(400, "Write a question of 3–500 characters.")
    api_key = resolve_gemini_api_key(req.api_key)
    if not api_key:
        raise _insights_http_error(InsightsError("no_api_key", http_status=401))
    await _insights_source_text(job)
    out_dir = _job_output_dir(req.job_id)
    title = Path(job.file_name or "document").stem

    async def _run(task):
        def _prog(pct, step):
            task.progress, task.step = int(pct), step
        await _scanned_book_read(job, api_key, _prog)
        return await ask_book(job.file_path, job.file_type, question, req.language, api_key, title=title,
                              job_output_dir=out_dir, progress=_prog)

    key = hashlib.sha256(question.casefold().encode("utf-8")).hexdigest()[:16]
    task, duplicate = start_task(req.job_id, "ask", key, (req.language or "auto").lower(), _run)
    return {"task_id": task.task_id, "status": task.status, "duplicate": duplicate}


@router.get("/api/insights/{job_id}/questions")
async def insights_questions(job_id: str):
    """The questions asked of this book and their answers, newest first."""
    from backend.insights_more import list_questions
    _insights_job(job_id)
    return {"job_id": job_id, "questions": list_questions(_job_output_dir(job_id))}


@router.post("/api/insights/glossary")
async def insights_to_glossary(req: InsightsGlossaryRequest):
    """The names and terms of a characters record go to the Glossary with their Greek spelling."""
    from backend.book_insights import load_insight, InsightsError
    from backend.glossary import set_term
    from backend.insights_more import glossary_items
    _insights_job(req.job_id)
    rec = load_insight(_job_output_dir(req.job_id), "characters", _validate_language(req.language))
    if not rec:
        raise _insights_http_error(InsightsError("not_generated", http_status=404))
    wanted = {s.casefold() for s in (req.sources or [])}
    pairs = [(src, dst) for src, dst in glossary_items(rec) if not wanted or src.casefold() in wanted]
    if not pairs:
        raise HTTPException(422, "There are no names or terms with a Greek spelling to add.")
    for src, dst in pairs:
        await asyncio.to_thread(set_term, src, dst, "general")
    return {"added": len(pairs), "terms": [{"source": s, "target": t} for s, t in pairs]}


@router.post("/api/insights/export")
async def insights_export(req: InsightsExportRequest):
    """Exports a generated insight to PDF, DOCX or TXT and returns its download URL."""
    from backend.book_insights import load_insight, export_insight, InsightsError
    _insights_job(req.job_id)
    insight_type = _insights_resolve_type(req.insight_type)
    rec = load_insight(_job_output_dir(req.job_id), insight_type, _validate_language(req.language))
    if not rec:
        raise _insights_http_error(InsightsError("not_generated", http_status=404))
    try:
        path = await asyncio.to_thread(export_insight, rec, _job_output_dir(req.job_id), req.format)
    except InsightsError as e:
        raise _insights_http_error(e)
    return {"file_name": path.name, "url": f"/api/insights/{req.job_id}/files/{path.name}"}


@router.post("/api/insights/audio")
async def insights_audio(req: InsightsAudioRequest):
    """Starts narration of the final insight text with the existing neural TTS voices."""
    from backend.book_insights import load_insight, synthesize_insight_audio, start_task, InsightsError
    _insights_job(req.job_id)
    insight_type = _insights_resolve_type(req.insight_type)
    lang = _validate_language(req.language)
    out_dir = _job_output_dir(req.job_id)
    rec = load_insight(out_dir, insight_type, lang)
    if not rec:
        raise _insights_http_error(InsightsError("not_generated", http_status=404))
    if lang not in ("greek", "english"):
        raise _insights_http_error(InsightsError("audio_unsupported_language"))

    async def _run(task):
        def _prog(pct, step):
            task.progress, task.step = int(pct), step
        record = load_insight(out_dir, insight_type, lang) or rec
        await synthesize_insight_audio(record, out_dir, voice_name=req.voice_name, progress=_prog)
        return record

    task, duplicate = start_task(req.job_id, "audio", insight_type, lang, _run)
    return {"task_id": task.task_id, "status": task.status, "duplicate": duplicate}


@router.get("/api/insights/{job_id}/files/{filename}")
async def insights_file(job_id: str, filename: str):
    """Downloads/streams an exported insight file or its audio (strictly inside the job's insights folder)."""
    _insights_job(job_id)
    if not re.fullmatch(r"[\w\-. ]{1,160}", filename or "", flags=re.UNICODE) or filename.startswith("."):
        raise HTTPException(400, "Invalid file name.")
    base = (_job_output_dir(job_id) / "insights").resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.is_file() or path.suffix.lower() not in (".pdf", ".docx", ".txt", ".mp3"):
        raise HTTPException(404, "Το αρχείο δεν βρέθηκε.")
    return FileResponse(str(path), media_type=MIME_MAP.get(path.suffix.lower(), "application/octet-stream"),
                        filename=path.name)
