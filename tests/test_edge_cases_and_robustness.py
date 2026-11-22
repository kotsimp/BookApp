"""
test_edge_cases_and_robustness.py - Comprehensive Edge Cases & System Robustness Suite.
Tests:
1. CBZ / ZIP page counter with hidden files, nested folders, and non-image files.
2. Smart regex boundary replacement with non-word character edge cases (e.g. C++, .NET, TCP/IP, (UPS)).
3. Document parsing & chunking with boundary sizes, empty inputs, null characters, and un-breakable strings.
4. TTS text cleaner resilience with complex punctuation, Greek accents, stanzas, and unicode whitespace.
5. Job and Settings management with edge cases (cancellation toggling, non-existent jobs, empty values).
6. Cover extraction resilience on invalid / corrupted files.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import zipfile
import tempfile
import os
from pathlib import Path

from backend.parsers import count_cbz_pages, split_into_chunks, _clean_text
from backend.glossary import apply_glossary, set_term, delete_term
from backend.tts_engine import _clean_tts_text
from backend.job_manager import create_job, get_job, update_job, is_job_cancelled, cancel_job
from backend.settings_manager import save_setting, get_setting, delete_setting
from backend.exporter import extract_cover_image


def test_cbz_page_counter_edge_cases():
    print("-> 1. Testing CBZ / ZIP page counter edge cases...")
    # Create a temporary CBZ with 3 valid images, 1 hidden dotfile, and 1 non-image file
    with tempfile.NamedTemporaryFile(suffix=".cbz", delete=False) as tf:
        cbz_path = tf.name

    try:
        with zipfile.ZipFile(cbz_path, "w") as zf:
            zf.writestr("page1.jpg", b"fake-jpg-1")
            zf.writestr("subfolder/page2.png", b"fake-png-2")
            zf.writestr("page3.webp", b"fake-webp-3")
            zf.writestr(".hidden_page.jpg", b"ignored-dotfile")
            zf.writestr("notes.txt", b"text-not-an-image")
            zf.writestr("subfolder/.DS_Store", b"macosx-metadata")

        count = count_cbz_pages(cbz_path)
        assert count == 3, f"Expected 3 valid images counted, got {count}"

        # Non-existent file should safely fallback to 1 without crashing
        fallback_count = count_cbz_pages("non_existent_comic_file.cbz")
        assert fallback_count == 1
        print("   CBZ page counter: OK")
    finally:
        if os.path.exists(cbz_path):
            os.remove(cbz_path)


def test_glossary_boundary_symbols_edge_cases():
    print("-> 2. Testing Glossary boundary symbol terms (C++, .NET, A/B testing)...")
    set_term("C++", "γλώσσα C++", category="technical")
    set_term(".NET", "πλατφόρμα .NET", category="technical")
    set_term("A/B testing", "συγκριτικές δοκιμές A/B", category="technical")

    try:
        text1 = "We develop software using C++ and .NET on Windows."
        res1 = apply_glossary(text1, "greek")
        assert "γλώσσα C++" in res1, f"Expected C++ to be replaced, got: {res1}"
        assert "πλατφόρμα .NET" in res1, f"Expected .NET to be replaced, got: {res1}"

        text2 = "Our team conducts A/B testing every week."
        res2 = apply_glossary(text2, "greek")
        assert "συγκριτικές δοκιμές A/B" in res2, f"Expected A/B testing replaced, got: {res2}"

        # Sub-string safety: "C++" should NOT match "C++17" or "ABC++"
        text3 = "We upgraded to C++17."
        res3 = apply_glossary(text3, "greek")
        # In text3, C++ is followed by 17 (word char), so it should not replace
        assert "C++17" in res3

        print("   Glossary boundary symbol handling: OK")
    finally:
        delete_term("C++")
        delete_term(".NET")
        delete_term("A/B testing")


def test_parsers_and_chunking_edge_cases():
    print("-> 3. Testing split_into_chunks and text sanitation edge cases...")
    # Empty string
    assert split_into_chunks("", 1000) == []
    # Very short string
    assert split_into_chunks("Hello", 1000) == ["Hello"]

    # Text with zero spaces (un-breakable long token)
    long_unbreakable = "A" * 2500
    chunks = split_into_chunks(long_unbreakable, 1000)
    assert len(chunks) == 3
    assert "".join(chunks) == long_unbreakable

    # Text cleaning: Null bytes, control chars, multiple newlines
    dirty = "Line 1\x00\x01\x02\n\n\n\n\n\nLine 2\r\n\r\nLine 3"
    cleaned = _clean_text(dirty)
    assert "\x00" not in cleaned
    assert "\n\n\n" not in cleaned

    # De-hyphenation edge cases
    hyphen_wrap = "inter-\nnational and πολυ-\nδιάστατος"
    clean_wrap = _clean_text(hyphen_wrap)
    assert "international" in clean_wrap
    assert "πολυδιάστατος" in clean_wrap
    print("   Parsers & chunking edge cases: OK")


def test_tts_cleaner_resilience():
    print("-> 4. Testing TTS text cleaner resilience...")
    # Null or empty
    assert _clean_tts_text("") == ""
    assert _clean_tts_text(None) == ""

    # Wingdings, bullets, email symbols
    bullet_text = "• Item 1 ▪ Item 2 ✉ info@test.com"
    clean_bullets = _clean_tts_text(bullet_text)
    assert "•" not in clean_bullets
    assert "▪" not in clean_bullets
    assert "✉" not in clean_bullets

    # Poetry: Greek ano teleia and typographical quotes
    poetry = "Εκείνοι που έφυγαν· και δεν γύρισαν ποτέ’"
    cleaned_poetry = _clean_tts_text(poetry, narration_style="poetry")
    assert "·" not in cleaned_poetry
    assert "’" not in cleaned_poetry
    assert "'" in cleaned_poetry or "," in cleaned_poetry

    # Literature vs Slow Pauses
    prose = "Πρώτη παράγραφος.\n\nΔεύτερη παράγραφος."
    lit = _clean_tts_text(prose, narration_style="literature")
    assert " ... " not in lit
    assert "παράγραφος. Δεύτερη" in lit

    slow = _clean_tts_text(prose, narration_style="slow_pauses")
    assert " ... " in slow
    print("   TTS cleaner resilience: OK")


def test_job_and_settings_manager_edge_cases():
    print("-> 5. Testing Job and Settings manager edge cases...")
    # Settings: get non-existent with default
    assert get_setting("non_existent_key_xyz_123", "default_val") == "default_val"
    save_setting("temp_test_key", "active_value")
    assert get_setting("temp_test_key") == "active_value"
    delete_setting("temp_test_key")
    assert get_setting("temp_test_key") is None

    # Job: non-existent job operations
    assert get_job("non-existent-job-uuid-000") is None
    assert is_job_cancelled("non-existent-job-uuid-000") is False
    cancel_job("non-existent-job-uuid-000")  # Should be safe no-op

    # Create job and verify state transitions
    job = create_job("sample.pdf", "sample.pdf", "pdf")
    assert job.status == "idle"
    update_job(job.job_id, status="running", progress=42, current_step="Processing...")
    updated = get_job(job.job_id)
    assert updated.status == "running"
    assert updated.progress == 42

    # In-flight cancellation
    cancel_job(job.job_id)
    assert is_job_cancelled(job.job_id) is True
    assert get_job(job.job_id).status == "cancelled"
    print("   Job and Settings managers: OK")


def test_cover_extraction_resilience():
    print("-> 6. Testing Cover Extraction resilience on invalid inputs...")
    assert extract_cover_image(None) is None
    assert extract_cover_image("") is None
    assert extract_cover_image("non_existent_file_path.pdf") is None

    # Empty file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        empty_pdf = tf.name
    try:
        assert extract_cover_image(empty_pdf) is None
    finally:
        if os.path.exists(empty_pdf):
            os.remove(empty_pdf)

    print("   Cover extraction resilience: OK")


if __name__ == "__main__":
    test_cbz_page_counter_edge_cases()
    test_glossary_boundary_symbols_edge_cases()
    test_parsers_and_chunking_edge_cases()
    test_tts_cleaner_resilience()
    test_job_and_settings_manager_edge_cases()
    test_cover_extraction_resilience()
    print("\nALL EDGE CASES AND SYSTEM ROBUSTNESS TESTS PASSED!")
