"""
test_standalone_ai_polish.py - Automated tests for standalone AI Polish (without translation).
Verifies:
1. Standalone document polish from uploaded DOCX without running translation.
2. Standalone polish from raw pasted text without any uploaded file.
3. Verification of generated formats (PDF, DOCX, TXT) and download availability.
4. Settings API persistence.
"""

import sys
sys.path.insert(0, ".")
import urllib.request
import urllib.error
import json
from pathlib import Path
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

def api_post_file(path, filepath, filename):
    boundary = "----TestBoundaryStandalonePolish123"
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


def run_tests():
    print("=== 1. Testing Persistent Settings API ===")
    status, res = api_post_json("/settings", {"gemini_api_key": "AQ.TestKeyAutoPersist123"})
    assert status == 200, f"Expected 200, got {status}"
    status, settings = api_get("/settings")
    assert status == 200
    assert settings.get("gemini_api_key") == "AQ.TestKeyAutoPersist123"
    print("  GET & POST /settings: OK (API key persisted successfully)")

    print("\n=== 2. Testing Standalone Polish on Uploaded Document (No Translation) ===")
    # Create sample Greek Word document
    doc = Document()
    doc.add_heading("ΥΠΗΡΕΣΙΑΚΟ ΣΗΜΕΙΩΜΑ", level=1)
    doc.add_paragraph("Θέμα: Προμήθεια εξοπλισμού πληροφορικής και συστημάτων αδιάλειπτης τροφοδοσίας.")
    doc.add_paragraph("Παρακαλούμε για την άμεση έγκριση της δαπάνης.")
    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)
    sample_docx = temp_dir / "sample_greek_doc.docx"
    doc.save(str(sample_docx))

    status, upload_res = api_post_file("/upload", str(sample_docx), "sample_greek_doc.docx")
    assert status == 200
    job_id = upload_res["job_id"]
    print(f"  Uploaded document without translation. Job ID: {job_id}")

    # Check that /jobs/{job_id}/text can extract document text before translation
    status, text_res = api_get(f"/jobs/{job_id}/text")
    assert status == 200
    assert "ΥΠΗΡΕΣΙΑΚΟ ΣΗΜΕΙΩΜΑ" in text_res["original_text"]
    assert "ΥΠΗΡΕΣΙΑΚΟ ΣΗΜΕΙΩΜΑ" in text_res["translated_text"]
    print("  GET /jobs/{job_id}/text (Pre-translation document text extraction): OK")

    # Mock the Gemini API call inside the server process or test via API
    # Call /api/polish directly with job_id
    # Note: We test passing explicit polished text to verify the full pipeline and output generation
    status, polish_res = api_post_json("/polish", {
        "job_id": job_id,
        "text": "=== PAGE 1 ===\nΥΠΗΡΕΣΙΑΚΟ ΣΗΜΕΙΩΜΑ\n\nΘέμα: Προμήθεια εξοπλισμού πληροφορικής και συστημάτων UPS.\n\nΠαρακαλούμε για την άμεση έγκριση.",
        "style": "formal",
        "api_key": "AQ.TestKeyAutoPersist123"
    })
    assert status == 200
    assert polish_res["status"] == "polished"
    print("  POST /api/polish (Standalone document polish): OK")

    # Verify download of polished document in TXT, DOCX, and PDF
    for fmt in ["txt", "docx", "pdf"]:
        req = urllib.request.Request(f"{API}/download/{job_id}?format={fmt}")
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            assert resp.status == 200
            assert len(content) > 50
            print(f"  Download polished output as {fmt.upper()}: OK ({len(content)} bytes)")

    print("\n=== 3. Testing Standalone Polish on Pasted Text (No File Uploaded) ===")
    pasted_greek = "Αυτό είναι ένα χειρόγραφο κείμενο προς γλωσσική επιμέλεια και διόρθωση."
    status, pasted_res = api_post_json("/polish", {
        "job_id": "",
        "text": pasted_greek,
        "style": "natural",
        "api_key": "AQ.TestKeyAutoPersist123"
    })
    assert status == 200
    new_job_id = pasted_res["job_id"]
    assert new_job_id, "Expected new job_id for pasted text"
    print(f"  POST /api/polish (Pasted text): OK (Generated Job ID: {new_job_id})")

    # Verify download of the polished pasted text
    req = urllib.request.Request(f"{API}/download/{new_job_id}?format=docx")
    with urllib.request.urlopen(req) as resp:
        content = resp.read()
        assert resp.status == 200
        assert len(content) > 1000
        print(f"  Download pasted text output as DOCX: OK ({len(content)} bytes)")

    print("\nALL STANDALONE AI POLISH TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
