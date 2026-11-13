# Test 4: Parsers module
print("=== Test 4: Parsers ===")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.parsers import split_into_chunks, _clean_text

# Test split_into_chunks
text = "Short text"
chunks = split_into_chunks(text, 100)
assert len(chunks) == 1
assert chunks[0] == text
print("  Short text chunk: OK")

# Multi-paragraph splitting
paras = "\n\n".join([f"Paragraph {i} with some text content here." for i in range(20)])
chunks = split_into_chunks(paras, 200)
assert len(chunks) > 1
for c in chunks:
    assert len(c) <= 200, f"Chunk too long: {len(c)}"
print(f"  Multi-paragraph split: OK ({len(chunks)} chunks)")

# Test _clean_text
dirty = "Hello\x00world\n\n\n\n\ntest"
clean = _clean_text(dirty)
assert "\x00" not in clean
assert "\n\n\n" not in clean
print("  Clean text: OK")

# Empty text
chunks = split_into_chunks("", 100)
assert chunks == [""] or chunks == []
print("  Empty text: OK")

print("  ALL PARSER TESTS PASSED")
