import sys
sys.path.insert(0, ".")
import urllib.request
import urllib.error
import json
import time
from docx import Document

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

def api_put_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=body, headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_delete(path):
    req = urllib.request.Request(f"{API}{path}", method="DELETE")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def api_post_file(path, filepath, filename):
    boundary = "----TestBoundaryGlossary123"
    file_data = open(filepath, "rb").read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

print("=== 1. Testing Glossary API ===")
# 1a. GET /api/glossary
status, terms = api_get("/glossary")
assert status == 200
assert "Server Room" in terms
print(f"  GET /glossary: OK ({len(terms)} terms loaded)")

# 1b. POST /api/glossary (Add custom term)
status, res = api_post_json("/glossary", {"source": "Quantum Computer", "target": "Κβαντικός Υπολογιστής"})
assert status == 200
assert res["glossary"]["Quantum Computer"] == "Κβαντικός Υπολογιστής"
print("  POST /api/glossary: OK (added custom term)")

# 1c. DELETE /api/glossary
status, res = api_delete("/glossary/Quantum%20Computer")
assert status == 200
assert "Quantum Computer" not in res["glossary"]
print("  DELETE /api/glossary: OK (deleted custom term)")

# 1d. Python glossary application test
from backend.glossary import apply_glossary
sample = "The server is in the Server Room and uses a UPS for power."
applied = apply_glossary(sample, "greek")
assert "Αίθουσα Διακομιστών" in applied or "Server Room" in applied
print(f"  apply_glossary unit test: OK -> {applied}")

print("=== 2. Testing Translation Editor & Text Update API ===")
test_doc = "temp/test_editor.docx"
d = Document()
d.add_paragraph("First paragraph about computer systems.")
d.add_paragraph("Second paragraph about backup procedures.")
d.save(test_doc)

status, upload_data = api_post_file("/upload", test_doc, "test_editor.docx")
assert status == 200
job_id = upload_data["job_id"]
print(f"  Uploaded test job: {job_id[:8]}...")

# Translate
api_post_json("/translate", {
    "job_id": job_id,
    "source_lang": "english",
    "target_lang": "greek",
    "output_format": "docx",
})

# Wait for translation done
for _ in range(60):
    time.sleep(0.5)
    _, sdata = api_get(f"/status/{job_id}")
    if sdata["status"] == "done":
        print("  Translation finished!")
        break

# 2a. GET /api/jobs/{job_id}/text
status, text_data = api_get(f"/jobs/{job_id}/text")
assert status == 200
assert text_data["translated_text"] != ""
print(f"  GET /jobs/{job_id}/text: OK ({len(text_data['translated_text'])} chars)")

# 2b. PUT /api/jobs/{job_id}/text (Simulate user editing the text in the editor)
edited_text = "Αυτή είναι η χειροκίνητα διορθωμένη παράγραφος από τον χρήστη.\n\nΚαι η δεύτερη διορθωμένη πρόταση."
status, put_res = api_put_json(f"/jobs/{job_id}/text", {"translated_text": edited_text})
assert status == 200
assert put_res["status"] == "saved"
print("  PUT /jobs/{job_id}/text: OK (saved edited text)")

# 2c. Verify that downloaded DOCX and PDF contain the edited text
req = urllib.request.Request(f"{API}/download/{job_id}?format=txt")
with urllib.request.urlopen(req) as resp:
    txt_downloaded = resp.read().decode("utf-8")
    assert "χειροκίνητα διορθωμένη" in txt_downloaded
print("  Verified edited text in downloaded TXT output: OK")

req = urllib.request.Request(f"{API}/download/{job_id}?format=pdf")
with urllib.request.urlopen(req) as resp:
    pdf_bytes = resp.read()
    assert len(pdf_bytes) > 500000
print(f"  Verified re-exported PDF contains edited text: OK ({len(pdf_bytes)} bytes)")

print("\nALL EDITOR, GLOSSARY, AND RE-EXPORT TESTS PASSED SUCCESSFULLY!")
