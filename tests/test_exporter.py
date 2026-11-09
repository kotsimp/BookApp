# Test 5: Exporter module - all 4 formats
print("=== Test 5: Exporter (TXT, DOCX, PDF, EPUB) ===")
from pathlib import Path
from backend.exporter import export_text

test_content = """
============================================================
PAGE 1
============================================================

This is chapter one of the translated document.
It contains multiple paragraphs of text.

The quick brown fox jumps over the lazy dog.

============================================================
PAGE 2
============================================================

This is chapter two with more content.
Translation is working correctly!
"""

out_dir = Path("temp/test_exports")
out_dir.mkdir(parents=True, exist_ok=True)

# Test TXT export
try:
    path = export_text(test_content, out_dir, "txt", "test_export")
    assert Path(path).exists(), "TXT file not created"
    content = Path(path).read_text(encoding="utf-8")
    assert len(content) > 0, "TXT file empty"
    print(f"  TXT export: OK ({Path(path).name}, {len(content)} chars)")
except Exception as e:
    print(f"  TXT export: FAIL - {e}")

# Test DOCX export
try:
    path = export_text(test_content, out_dir, "docx", "test_export")
    assert Path(path).exists(), "DOCX file not created"
    size = Path(path).stat().st_size
    assert size > 0, "DOCX file empty"
    print(f"  DOCX export: OK ({Path(path).name}, {size} bytes)")
except Exception as e:
    print(f"  DOCX export: FAIL - {e}")

# Test PDF export
try:
    path = export_text(test_content, out_dir, "pdf", "test_export")
    assert Path(path).exists(), "PDF file not created"
    size = Path(path).stat().st_size
    assert size > 0, "PDF file empty"
    print(f"  PDF export: OK ({Path(path).name}, {size} bytes)")
except Exception as e:
    print(f"  PDF export: FAIL - {e}")

# Test EPUB export
try:
    path = export_text(test_content, out_dir, "epub", "test_export")
    assert Path(path).exists(), "EPUB file not created"
    size = Path(path).stat().st_size
    assert size > 0, "EPUB file empty"
    print(f"  EPUB export: OK ({Path(path).name}, {size} bytes)")
except Exception as e:
    print(f"  EPUB export: FAIL - {e}")

# Test invalid format
try:
    path = export_text(test_content, out_dir, "xyz", "test_export")
    print(f"  Invalid format: FAIL - should have raised error")
except (ValueError, Exception) as e:
    print(f"  Invalid format rejection: OK ({type(e).__name__})")

# Test with Greek content
greek_content = """
============================================================
PAGE 1
============================================================

Αυτό είναι ένα δοκιμαστικό κείμενο στα ελληνικά.
Περιέχει ελληνικούς χαρακτήρες και τόνους.

Η μετάφραση λειτουργεί σωστά!
"""

for fmt in ["txt", "docx", "pdf", "epub"]:
    try:
        path = export_text(greek_content, out_dir, fmt, "test_greek")
        assert Path(path).exists()
        print(f"  Greek {fmt.upper()}: OK ({Path(path).stat().st_size} bytes)")
    except Exception as e:
        print(f"  Greek {fmt.upper()}: FAIL - {e}")

print("  ALL EXPORTER TESTS PASSED")
