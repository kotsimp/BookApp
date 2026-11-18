# Test 5: Exporter module - all 4 formats
print("=== Test 5: Exporter (TXT, DOCX, PDF, EPUB) ===")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
path = export_text(test_content, out_dir, "txt", "test_export")
assert Path(path).exists(), "TXT file not created"
content = Path(path).read_text(encoding="utf-8")
assert len(content) > 0, "TXT file empty"
print(f"  TXT export: OK ({Path(path).name}, {len(content)} chars)")

# Test DOCX export
path = export_text(test_content, out_dir, "docx", "test_export")
assert Path(path).exists(), "DOCX file not created"
size = Path(path).stat().st_size
assert size > 0 and Path(path).read_bytes().startswith(b"PK"), "DOCX file invalid"
print(f"  DOCX export: OK ({Path(path).name}, {size} bytes)")

# Test PDF export
path = export_text(test_content, out_dir, "pdf", "test_export")
assert Path(path).exists(), "PDF file not created"
size = Path(path).stat().st_size
assert size > 0 and Path(path).read_bytes().startswith(b"%PDF"), "PDF file invalid"
print(f"  PDF export: OK ({Path(path).name}, {size} bytes)")

# Test EPUB export
path = export_text(test_content, out_dir, "epub", "test_export")
assert Path(path).exists(), "EPUB file not created"
size = Path(path).stat().st_size
assert size > 0 and Path(path).read_bytes().startswith(b"PK"), "EPUB file invalid"
print(f"  EPUB export: OK ({Path(path).name}, {size} bytes)")

# Test invalid format
rejected = False
try:
    export_text(test_content, out_dir, "xyz", "test_export")
except ValueError as e:
    rejected = True
    print(f"  Invalid format rejection: OK ({type(e).__name__})")
assert rejected, "Invalid format 'xyz' should have raised ValueError"

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
    path = export_text(greek_content, out_dir, fmt, "test_greek")
    assert Path(path).exists(), f"Greek {fmt} file not created"
    assert Path(path).stat().st_size > 0, f"Greek {fmt} file empty"
    print(f"  Greek {fmt.upper()}: OK ({Path(path).stat().st_size} bytes)")

print("  ALL EXPORTER TESTS PASSED")
