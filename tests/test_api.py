# Test 6: API endpoints via HTTP
print("=== Test 6: API Endpoints ===")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

def api_delete(path):
    req = urllib.request.Request(f"{API}{path}", method="DELETE")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_post_file(path, filepath, filename):
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

# Test 6c: Download old job from disk (recovered) and delete it
recovered_id = "test-recovered-job"
recovered_dir = os.path.join("temp", "outputs", recovered_id)
os.makedirs(recovered_dir, exist_ok=True)
recovered_file = os.path.join(recovered_dir, "recovered.txt")
with open(recovered_file, "w", encoding="utf-8") as f:
    f.write("Recovered job output")
try:
    req = urllib.request.Request(f"{API}/download/{recovered_id}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content = resp.read()
        assert content == b"Recovered job output"
        print(f"  GET /download (recovered job): OK ({len(content)} bytes)")
    del_status, del_data = api_delete(f"/jobs/{recovered_id}")
    assert del_status == 200 and del_data["deleted"] == recovered_id
    print("  DELETE /jobs/{job_id}: OK")
finally:
    if os.path.exists(recovered_dir):
        import shutil
        shutil.rmtree(recovered_dir, ignore_errors=True)

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
    assert data.get("detected_language") == "english"
    print(f"  POST /upload: OK (job_id={job_id[:8]}..., type={data['file_type']}, lang={data['detected_language']})")

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

    # Test 6f-2: Greek -> English translation + English Audiobook
    print("  --- Integration: Greek -> English + English Audiobook ---")
    gr_docx_path = "temp/test_upload_greek.docx"
    gr_doc = Document()
    gr_doc.add_paragraph("Κεφάλαιο Πρώτο")
    gr_doc.add_paragraph("Αυτό είναι ένα δοκιμαστικό έγγραφο για μετάφραση από ελληνικά σε αγγλικά.")
    gr_doc.save(gr_docx_path)

    status, data = api_post_file("/upload", gr_docx_path, "test_upload_greek.docx")
    assert status == 200
    assert data.get("detected_language") == "greek"
    gr_job_id = data["job_id"]
    status, data = api_post_json("/translate", {
        "job_id": gr_job_id,
        "source_lang": "greek",
        "target_lang": "english",
        "output_format": "docx",
    })
    assert status == 200
    for i in range(60):
        time.sleep(0.5)
        status, sdata = api_get(f"/status/{gr_job_id}")
        if sdata["status"] in ("done", "error"):
            break
    assert sdata["status"] == "done", f"Greek->English translation failed: {sdata}"
    print(f"  Greek->English translation: OK")

    status, data = api_post_json("/audiobook", {
        "job_id": gr_job_id,
        "language": "english",
        "voice_name": "Aria (Female, US)",
        "use_translated": True,
    })
    assert status == 200
    for i in range(120):
        time.sleep(0.5)
        status, sdata = api_get(f"/status/{gr_job_id}")
        if sdata["status"] in ("done", "error"):
            break
    assert sdata["status"] == "done", f"English audiobook failed: {sdata}"
    req = urllib.request.Request(f"{API}/download/{gr_job_id}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        en_mp3 = resp.read()
        assert len(en_mp3) > 10000
        print(f"  GET /download (English audiobook MP3): OK ({len(en_mp3)} bytes)")
    api_delete(f"/jobs/{job_id}")
    api_delete(f"/jobs/{gr_job_id}")
    for tmp_f in (test_docx_path, gr_docx_path):
        if os.path.exists(tmp_f):
            os.remove(tmp_f)
except Exception as e:
    import traceback
    print(f"  Integration test: FAIL - {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 6g: DELETE /api/settings/gemini_api_key (restore original key if present)
_, prev_settings = api_get("/settings")
prev_key = prev_settings.get("gemini_api_key", "")
try:
    api_post_json("/settings", {"gemini_api_key": "temp-test-key-123"})
    del_status, del_data = api_delete("/settings/gemini_api_key")
    assert del_status == 200 and del_data["status"] == "deleted"
    _, after_settings = api_get("/settings")
    assert after_settings.get("gemini_api_key", "") == ""
    print("  DELETE /settings/gemini_api_key: OK")
finally:
    if prev_key:
        api_post_json("/settings", {"gemini_api_key": prev_key})

print("  ALL API TESTS PASSED")
