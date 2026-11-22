"""
backend/api/refine.py - Final Output Refinement endpoints (APIRouter included by backend.main).
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.common import _validate_job_id, _job_output_dir
from backend.job_manager import get_job, update_job

logger = logging.getLogger(__name__)
router = APIRouter()

class RefinementRequest(BaseModel):
    job_id: Optional[str] = None
    text: Optional[str] = None
    file_path: Optional[str] = None
    target_lang: Optional[str] = None   # defaults to the job's target language (or 'greek' for direct text)
    source_lang: Optional[str] = None
    mode: str = "auto"  # 'auto', 'translation', 'audiobook'
    style: Optional[str] = None
    layout_mode: Optional[str] = None
    output_format: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None



# ---------------------------------------------------------------------------
# Output Refinement & Quality Control Endpoints
# ---------------------------------------------------------------------------

@router.get("/api/refine/config")
async def get_refine_config():
    """Returns configuration and operational status of the Final Output Refinement stage."""
    from backend.output_refiner import is_refinement_enabled, REFINER_VERSION, MAX_AUDIO_HEAL_CHUNKS
    return {
        "enabled": is_refinement_enabled(),
        "version": REFINER_VERSION,
        "supported_modes": ["translation", "audiobook"],
        "uses_external_api": False,
        "max_audio_heal_chunks": MAX_AUDIO_HEAL_CHUNKS,
        "pipeline_stages": [
            "structural_integrity",
            "omission_detection",
            "orthography_and_accents",
            "grammar_and_morphology",
            "calque_detection_and_safe_remediation",
            "repetition_and_stutter_filtering",
            "formatting_normalization",
            "audio_container_and_stream_validation",
            "audio_sequence_continuity_verification",
            "audio_missing_section_healing",
            "metadata_verification",
        ],
    }


def _resolve_job_output_file(job_id: str, file_path: Optional[str], suffixes: tuple) -> Optional[Path]:
    """Resolves a file strictly inside the job's own output directory (prevents path traversal)."""
    out_d = _job_output_dir(job_id).resolve()
    if file_path:
        cand = Path(file_path)
        if not cand.is_absolute():
            cand = out_d / cand
        try:
            cand = cand.resolve()
        except OSError:
            return None
        if out_d not in cand.parents or not cand.is_file() or cand.suffix.lower() not in suffixes:
            raise HTTPException(400, "file_path must reference an output file of the given job.")
        return cand
    job = get_job(job_id)
    if job and job.output_path and Path(job.output_path).suffix.lower() in suffixes:
        cand = Path(job.output_path).resolve()
        if out_d in cand.parents and cand.is_file():
            return cand
    cands = [
        f for f in out_d.iterdir()
        if f.is_file() and f.suffix.lower() in suffixes and not f.name.endswith("_original.txt")
    ]
    # Prefer translation outputs, newest first
    cands.sort(key=lambda f: ("_translated_" in f.name, f.stat().st_mtime), reverse=True)
    return cands[0] if cands else None


def _job_output_is_reexportable(job) -> bool:
    """False for outputs produced by format-preserving flows (comics, in-place DOCX/EPUB)."""
    if not job:
        return False
    fmt = (getattr(job, "output_format", "") or "").lower()
    ftype = (getattr(job, "file_type", "") or "").lower()
    if (getattr(job, "layout_mode", "") or "").lower() in ("comic", "graphic_novel") or fmt in ("cbz", "cbr"):
        return False
    if not getattr(job, "ai_polish", False) and (
        (ftype == "docx" and fmt in ("docx", "doc")) or (ftype == "epub" and fmt == "epub")
    ):
        return False
    return True


@router.post("/api/refine")
async def refine_output_endpoint(req: RefinementRequest):
    """
    On-demand Final Output Refinement & Quality Control.
    - ``text``: refine a text snippet (nothing is written to disk).
    - ``job_id``: refine/inspect that job's translation, or validate its audiobook (``mode='audiobook'``).
    Files are only ever resolved inside the job's own output directory.
    """
    from dataclasses import asdict
    from backend.output_refiner import (
        refine_text_content, refine_translation_output, refine_audiobook_output_async,
        is_refinement_enabled, build_refinement_report, MAX_DIRECT_TEXT_CHARS,
    )

    if not is_refinement_enabled(req.enabled):
        return {"status": "skipped", "message": "Final refinement stage is disabled."}

    req_mode = (req.mode or "auto").strip().lower()
    if req_mode not in ("auto", "translation", "audiobook"):
        raise HTTPException(400, "mode must be 'auto', 'translation' or 'audiobook'.")

    # 1. Direct text (stateless)
    if req.text is not None and req_mode != "audiobook":
        if len(req.text) > MAX_DIRECT_TEXT_CHARS:
            raise HTTPException(413, "Text too large for direct refinement.")
        refined_txt, issues, corrections = refine_text_content(
            req.text, target_lang=req.target_lang or "greek", source_lang=req.source_lang or "english",
            style=req.style or req.layout_mode,
        )
        return {
            "status": "refined" if corrections else "verified_clean",
            "mode": "translation",
            "original_text": req.text,
            "refined_text": refined_txt,
            "issues_detected": [asdict(i) for i in issues],
            "corrections_applied": corrections,
            "modifications_count": len(corrections),
        }

    if not req.job_id:
        raise HTTPException(400, "Provide either 'text' or 'job_id' for refinement.")
    _validate_job_id(req.job_id)
    job = get_job(req.job_id)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found.")
    if job.status == "running":
        raise HTTPException(409, "Job is still running; refinement runs automatically when it finishes.")

    audio_suffixes = (".mp3", ".m4b")
    is_audio = req_mode == "audiobook" or (
        req_mode == "auto" and (
            (req.file_path or "").lower().endswith(audio_suffixes)
            or (not req.file_path and (job.mode == "audiobook" or (job.output_path or "").lower().endswith(audio_suffixes)))
        )
    )

    # 2. Audiobook validation (inspection + missing-metadata repair; chunks are gone after generation)
    if is_audio:
        target_audio = _resolve_job_output_file(req.job_id, req.file_path, audio_suffixes)
        if not target_audio:
            raise HTTPException(404, "Audiobook file not found for refinement.")
        res = await refine_audiobook_output_async(
            job_id=req.job_id, output_path=str(target_audio), language=req.target_lang or "greek",
            book_title=Path(job.file_name or "Audiobook").stem, enabled=True,
        )
        update_job(req.job_id, refinement_report=build_refinement_report(res))
        return {"status": res.status, "mode": "audiobook", "result": asdict(res)}

    # 3. Translation output of a job
    text_p = _resolve_job_output_file(req.job_id, req.file_path if (req.file_path or "").lower().endswith(".txt") else None, (".txt",))
    if text_p and text_p.name.endswith("_original.txt"):
        text_p = None
    if not text_p:
        raise HTTPException(404, f"No translation text output found for job '{req.job_id}'.")
    final_p = job.output_path if job.output_path and Path(job.output_path).exists() else str(text_p)
    res_trans = await refine_translation_output(
        job_id=req.job_id,
        output_path=str(text_p),
        final_exported_path=final_p,
        source_lang=req.source_lang or getattr(job, "source_lang", "english"),
        target_lang=req.target_lang or getattr(job, "target_lang", "greek"),
        layout_mode=req.layout_mode or getattr(job, "layout_mode", "standard") or "standard",
        output_format=req.output_format or job.output_format,
        enabled=True,
        allow_reexport=_job_output_is_reexportable(job),
    )
    update_job(req.job_id, refinement_report=build_refinement_report(res_trans))
    return {"status": res_trans.status, "mode": "translation", "result": asdict(res_trans)}
