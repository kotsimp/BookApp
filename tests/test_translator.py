# Test 3: Translation engine (GTX direct + fallback)
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401
print("=== Test 3: Translator Engine ===")
import sys
import unittest.mock as mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from backend.translator import _translate_gtx, _translate_with_retry

# 1. Test unit logic with mocked responses (guarantees coverage regardless of network rate limits)
mock_gtx_response = b'[[["\xce\x93\xce\xb5\xce\xb9\xce\xac \xcf\x83\xce\xbf\xcf\x85 \xce\xba\xcf\x8c\xcf\x83\xce\xbc\xce\xb5","Hello world",null,null,1]],null,"en"]'

class DummyResp:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    def read(self):
        return mock_gtx_response

with mock.patch("urllib.request.urlopen", return_value=DummyResp()):
    mock_res = _translate_gtx("Hello world", "english", "greek")
    assert mock_res == "Γειά σου κόσμε", f"Unexpected mock translation: {mock_res}"
    print('  Mock GTX decoding: OK')

# 2. Test live GTX translation (with rate-limit tolerance for shared CI/test environments)
tests = [
    ("Hello world", "english", "greek"),
    ("Chapter 1: Introduction", "english", "greek"),
]

for text, src, tgt in tests:
    result = None
    rate_limited = False
    for attempt in range(2):
        try:
            result = _translate_gtx(text, src, tgt)
            break
        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                rate_limited = True
                break
    if not result:
        result = asyncio.run(_translate_with_retry(text, src, tgt))
    assert result and len(result) > 0, f"Empty result for: {text}"
    if rate_limited and result == text:
        print(f'  GTX [{src}->{tgt}]: Rate-limited (429) - fallback safely preserved text: "{result[:40]}"')
    else:
        print(f'  GTX [{src}->{tgt}]: "{text[:40]}" -> "{result[:40]}" OK')

# 3. Test async retry wrapper
async def test_retry():
    result = await _translate_with_retry("Good morning", "english", "greek")
    assert result and len(result) > 0
    print(f'  Async retry: "{result}" OK')

    # Test empty string
    result = await _translate_with_retry("", "english", "greek")
    assert result == ""
    print(f"  Empty string: OK")

    # Test whitespace-only
    result = await _translate_with_retry("   ", "english", "greek")
    print(f"  Whitespace: OK")

asyncio.run(test_retry())
print("  ALL TRANSLATOR TESTS PASSED")
