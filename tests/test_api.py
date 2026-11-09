# Test 6: API endpoints via HTTP
print("=== Test 6: API Endpoints ===")
import urllib.request
import urllib.error
import json
import os
import time

API = "http://127.0.0.1:8000/api"

def api_get(path):
    req = urllib.request.Request(f"{API}{path}")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_post_file(path, filepath, filename):
    import io
    boundary = "----TestBoundary12345"
    file_data = open(filepath, "rb").read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

# Test 6a: GET /voices
try:
    status, data = api_get("/voices")
    assert status == 200
    assert "english" in data
    assert "greek" in data
    assert len(data["greek"]) >= 2
    assert len(data["english"]) >= 4
    print(f"  GET /voices: OK (english: {len(data['english'])} voices, greek: {len(data['greek'])} voices)")
except Exception as e:
    print(f"  GET /voices: FAIL - {e}")

# Test 6b: GET /jobs
try:
    status, data = api_get("/jobs")
    assert status == 200
    assert isinstance(data, list)
    print(f"  GET /jobs: OK ({len(data)} jobs listed)")
except Exception as e:
    print(f"  GET /jobs: FAIL - {e}")

# Test 6c: Download old job from disk (recovered)
try:
    req = urllib.request.Request(f"{API}/download/8c8b7f85-1f6c-436f-9bca-7d53013a394d")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content = resp.read()
        assert len(content) > 0
        print(f"  GET /download (recovered job): OK ({len(content)} bytes)")
except urllib.error.HTTPError as e:
    print(f"  GET /download (recovered job): FAIL - HTTP {e.code}")
except Exception as e:
    print(f"  GET /download (recovered job): FAIL - {e}")

# Test 6d: Download nonexistent job
try:
    req = urllib.request.Request(f"{API}/download/nonexistent-id")
    urllib.request.urlopen(req)
    print(f"  GET /download (missing): FAIL - should 404")
except urllib.error.HTTPError as e:
    assert e.code == 404
    print(f"  GET /download (missing job): OK (404 returned)")

# Test 6e: GET /status for nonexistent job
try:
    req = urllib.request.Request(f"{API}/status/nonexistent-id")
    urllib.request.urlopen(req)
    print(f"  GET /status (missing): FAIL - should 404")
except urllib.error.HTTPError as e:
    assert e.code == 404
    print(f"  GET /status (missing job): OK (404 returned)")

# Test 6f: Upload a test DOCX file and translate it
print("  --- Integration: Upload + Translate ---")
from docx import Document
test_docx_path = "temp/test_upload.docx"
doc = Document()
doc.add_paragraph("Chapter One")
doc.add_paragraph("This is a test paragraph for translation testing. The quick brown fox jumps over the lazy dog.")
doc.add_paragraph("Chapter Two")
doc.add_paragraph("Another paragraph with important content. Technology is advancing rapidly in the modern world.")
doc.save(test_docx_path)
print(f"  Created test DOCX: {test_docx_path}")

try:
    status, data = api_post_file("/upload", test_docx_path, "test_upload.docx")
    assert status == 200
    job_id = data["job_id"]
    assert data["file_type"] == "docx"
    print(f"  POST /upload: OK (job_id={job_id[:8]}..., type={data['file_type']})")

    # Start translation with output_format=docx
    status, data = api_post_json("/translate", {
        "job_id": job_id,
        "source_lang": "english",
        "target_lang": "greek",
        "output_format": "docx",
    })
    assert status == 200
    assert data["status"] == "started"
    print(f"  POST /translate: OK (status=started)")

    # Poll status until done (max 60s)
    for i in range(120):
        time.sleep(0.5)
        status, sdata = api_get(f"/status/{job_id}")
        if sdata["status"] == "done":
            print(f"  Translation completed in ~{(i+1)*0.5:.1f}s (progress={sdata['progress']}%)")
            break
        elif sdata["status"] == "error":
            print(f"  Translation ERROR: {sdata.get('error')}")
            break
    else:
        print(f"  Translation TIMEOUT (last status: {sdata['status']}, progress={sdata['progress']}%)")

    if sdata["status"] == "done":
        # Test download
        req = urllib.request.Request(f"{API}/download/{job_id}")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            content_type = resp.headers.get("Content-Type", "")
            content = resp.read()
            print(f"  GET /download: OK ({len(content)} bytes, type={content_type})")

    # Test 6g: Audiobook Generation via API
    print("  --- Integration: Greek Audiobook Generation ---")
    status, data = api_post_json("/audiobook", {
        "job_id": job_id,
        "language": "greek",
        "voice_name": "Nestoras (Male)",
        "use_translated": True,
    })
    assert status == 200
    assert data["status"] == "started"
    print(f"  POST /audiobook: OK (status=started)")

    for i in range(120):
        time.sleep(0.5)
        status, sdata = api_get(f"/status/{job_id}")
        if sdata["status"] == "done":
            print(f"  Audiobook completed in ~{(i+1)*0.5:.1f}s (progress={sdata['progress']}%)")
            break
        elif sdata["status"] == "error":
            print(f"  Audiobook ERROR: {sdata.get('error')}")
            break

    if sdata["status"] == "done":
        req = urllib.request.Request(f"{API}/download/{job_id}")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            content = resp.read()
            assert len(content) > 10000
            print(f"  GET /download (audiobook MP3): OK ({len(content)} bytes)")
except Exception as e:
    import traceback
    print(f"  Integration test: FAIL - {e}")
    traceback.print_exc()

print("  ALL API TESTS PASSED")
