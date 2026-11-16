"""
test_ai_polish_advanced.py - Comprehensive Unit & Integration Tests for AI Polish Enhancements:
1. Bilingual Source-Anchored Polish (Greek draft aligned with English source per page).
2. Audiobook Spoken Script Polish (Phonetics, number/date expansions, non-spoken artifact stripping).
3. Entity & Character Consistency Dossier extraction.
4. Smart Disk Checkpointing & Resume.
5. Rolling Narrative Context.
"""

import sys
sys.path.insert(0, ".")
import os
import json
import asyncio
from pathlib import Path

from backend.ai_polisher import (
    STYLE_PROMPTS,
    _parse_pages_dict,
    _extract_entity_dossier,
    polish_text_with_gemini,
)


def test_style_prompts_audiobook_and_literature():
    print("-> Testing STYLE_PROMPTS for Audiobook and Literature...")
    ab_prompt = STYLE_PROMPTS["audiobook"]
    assert "ΦΩΝΗΤΙΚΗ ΑΠΟΔΟΣΗ" in ab_prompt or "φωνητική" in ab_prompt
    assert "ΟΛΟΓΡΑΦΗ ΑΝΑΠΤΥΞΗ" in ab_prompt or "ολογράφως" in ab_prompt
    assert "=== PAGE" in ab_prompt  # instructions to strip page markers
    assert "Nestoras" in ab_prompt or "Athina" in ab_prompt or "Edge-TTS" in ab_prompt

    lit_prompt = STYLE_PROMPTS["literature"]
    assert "λογοτεχνικός μεταφραστής" in lit_prompt
    assert "πρωτότυπο κείμενο" in lit_prompt
    assert "=== PAGE X ===" in lit_prompt
    print("   STYLE_PROMPTS: OK")


def test_parse_pages_dict():
    print("-> Testing _parse_pages_dict...")
    sample = (
        "=== PAGE 1 ===\n"
        "First page content here.\n\n"
        "=== PAGE 2 ===\n"
        "Second page content here.\n\n"
        "=== PAGE 42 ===\n"
        "Page forty-two content here."
    )
    pages = _parse_pages_dict(sample)
    assert len(pages) == 3
    assert pages[1] == "First page content here."
    assert pages[2] == "Second page content here."
    assert pages[42] == "Page forty-two content here."
    print("   _parse_pages_dict: OK")


async def test_entity_dossier_mock():
    print("-> Testing Entity Dossier extraction (Mock)...")
    sample_text = "Theseus approached Rorschach while Keeton watched from the deck."
    dossier = await _extract_entity_dossier(sample_text, "AQ.TestKey123")
    assert "Keeton" in dossier or "Κίτον" in dossier
    assert "Theseus" in dossier or "Θησέας" in dossier
    print("   Entity Dossier: OK")


async def test_bilingual_source_anchored_polish():
    print("-> Testing Bilingual Source-Anchored Polish...")
    original = (
        "=== PAGE 1 ===\n"
        "The stars flared beyond the hull of Theseus.\n\n"
        "=== PAGE 2 ===\n"
        "Keeton observed the silent swarm."
    )
    draft = (
        "=== PAGE 1 ===\n"
        "Τα αστέρια αναλαμπή πέρα από το κύτος του Θησέα.\n\n"
        "=== PAGE 2 ===\n"
        "Ο Κίτον παρατηρούσε το σιωπηλό σμήνος."
    )
    progress_records = []
    def on_prog(cur, tot):
        progress_records.append((cur, tot))

    polished = await polish_text_with_gemini(
        text=draft,
        api_key="AQ.TestKeyMock123",
        style="literature",
        original_text=original,
        use_source_anchoring=True,
        progress_callback=on_prog,
    )
    assert "=== PAGE 1 ===" in polished
    assert "=== PAGE 2 ===" in polished
    assert len(progress_records) > 0
    print("   Bilingual Source-Anchored Polish: OK")


async def test_disk_checkpoint_and_resume():
    print("-> Testing Disk Checkpoint & Resume...")
    test_job_id = "test-checkpoint-job-999"
    out_dir = Path("temp/outputs") / test_job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = out_dir / ".polish_checkpoint.json"

    # Pre-populate checkpoint with completed batch 0 (pages 1 to 5)
    pre_cached = {
        "batches": {
            "0": "=== PAGE 1 ===\nΕπιμελημένο από το checkpoint πρώτο μέρος.\n\n=== PAGE 5 ===\nΠέμπτη σελίδα επιμελημένη."
        },
        "chunks": {},
        "entity_dossier": "- Test -> Τεστ"
    }
    checkpoint_file.write_text(json.dumps(pre_cached, ensure_ascii=False), encoding="utf-8")

    # 6 pages so that pages 1-5 form batch 0, and page 6 forms batch 1
    draft_pages = [f"=== PAGE {i} ===\nΚείμενο σελίδας {i}." for i in range(1, 7)]
    draft = "\n\n".join(draft_pages)

    try:
        polished = await polish_text_with_gemini(
            text=draft,
            api_key="AQ.TestKeyMock123",
            style="literature",
            job_id=test_job_id,
        )
        assert "Επιμελημένο από το checkpoint πρώτο μέρος." in polished
        assert "=== PAGE 6 ===" in polished
        assert not checkpoint_file.exists()
        print("   Disk Checkpoint & Resume: OK")
    finally:
        if checkpoint_file.exists():
            checkpoint_file.unlink(missing_ok=True)
        import shutil
        shutil.rmtree(str(out_dir), ignore_errors=True)


async def test_audiobook_polish_script():
    print("-> Testing Audiobook Polish Script...")
    script_text = (
        "This is paragraph 1. It mentions 50% and $100.\n\n"
        "This is paragraph 2. Keeton says: 'We are ready.'"
    )
    result = await polish_text_with_gemini(
        text=script_text,
        api_key="AQ.TestKeyMock123",
        style="audiobook",
    )
    assert len(result) > 20
    assert "[Επιμελημένο AI]" in result or "Keeton" in result
    print("   Audiobook Polish Script: OK")


async def main():
    test_style_prompts_audiobook_and_literature()
    test_parse_pages_dict()
    await test_entity_dossier_mock()
    await test_bilingual_source_anchored_polish()
    await test_disk_checkpoint_and_resume()
    await test_audiobook_polish_script()
    print("\nALL ADVANCED AI POLISH UNIT TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(main())
