# Test 3: Translation engine (GTX direct + fallback)
print("=== Test 3: Translator Engine ===")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from backend.translator import _translate_gtx, _translate_with_retry

# Test GTX direct translation
tests = [
    ("Hello world", "english", "greek"),
    ("Chapter 1: Introduction", "english", "greek"),
    ("This is a longer paragraph with multiple sentences. It should translate accurately. Testing punctuation!", "english", "greek"),
]

for text, src, tgt in tests:
    result = _translate_gtx(text, src, tgt)
    assert result and len(result) > 0, f"Empty result for: {text}"
    assert result != text, f"Result same as input (not translated): {text}"
    print(f'  GTX [{src}->{tgt}]: "{text[:40]}" -> "{result[:40]}" OK')

# Test async retry wrapper
async def test_retry():
    result = await _translate_with_retry("Good morning", "english", "greek")
    assert result and result != "Good morning"
    print(f'  Async retry: "Good morning" -> "{result}" OK')

    # Test empty string
    result = await _translate_with_retry("", "english", "greek")
    assert result == ""
    print(f"  Empty string: OK")

    # Test whitespace-only
    result = await _translate_with_retry("   ", "english", "greek")
    print(f"  Whitespace: OK")

asyncio.run(test_retry())
print("  ALL TRANSLATOR TESTS PASSED")
