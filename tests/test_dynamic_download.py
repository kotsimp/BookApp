import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import urllib.request
import json
import time

API = 'http://127.0.0.1:8000/api'


def ensure_server():
    try:
        with urllib.request.urlopen(f'{API}/health', timeout=0.8):
            return
    except Exception:
        pass
    import threading
    import uvicorn
    from backend.main import app
    t = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": 8000, "log_level": "error"},
        daemon=True,
    )
    t.start()
    for _ in range(40):
        try:
            with urllib.request.urlopen(f'{API}/health', timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)


ensure_server()

from docx import Document

Path("temp").mkdir(parents=True, exist_ok=True)
doc = Document()
doc.add_paragraph("Hello world. This is a format test for dynamic on-demand conversion.")
test_file = "temp/test_format.docx"
doc.save(test_file)

boundary = '----TestBoundary123'
file_bytes = Path(test_file).read_bytes()
body = (
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="file"; filename="test_format.docx"\r\n'
    f'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n'
).encode('utf-8') + file_bytes + f'\r\n--{boundary}--\r\n'.encode('utf-8')

req = urllib.request.Request(f'{API}/upload', data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
with urllib.request.urlopen(req) as resp:
    assert resp.status == 200
    upload_res = json.loads(resp.read().decode())
job_id = upload_res['job_id']
print('Uploaded job:', job_id)

try:
    # Translate to docx
    req = urllib.request.Request(
        f'{API}/translate',
        data=json.dumps({'job_id': job_id, 'source_lang': 'english', 'target_lang': 'greek', 'output_format': 'docx'}).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200

    # Wait for completion
    final_status = None
    for _ in range(60):
        time.sleep(0.5)
        with urllib.request.urlopen(f'{API}/status/{job_id}') as r:
            s = json.loads(r.read().decode())
            final_status = s['status']
            if final_status in ('done', 'error', 'cancelled'):
                break
    assert final_status == 'done', f"Expected status 'done', got {final_status!r}"
    print('Translation done!')

    # 1. Download default docx
    with urllib.request.urlopen(f'{API}/download/{job_id}') as r:
        data = r.read()
        assert r.status == 200 and data.startswith(b'PK') and len(data) > 500
        print('Default download:', r.headers.get('Content-Type'), len(data))

    # 2. Download dynamic PDF
    with urllib.request.urlopen(f'{API}/download/{job_id}?format=pdf') as r:
        data = r.read()
        assert r.status == 200 and data.startswith(b'%PDF') and len(data) > 500
        print('Dynamic PDF download:', r.headers.get('Content-Type'), len(data))

    # 3. Download dynamic EPUB
    with urllib.request.urlopen(f'{API}/download/{job_id}?format=epub') as r:
        data = r.read()
        assert r.status == 200 and data.startswith(b'PK') and len(data) > 500
        print('Dynamic EPUB download:', r.headers.get('Content-Type'), len(data))

    # 4. Download dynamic TXT
    with urllib.request.urlopen(f'{API}/download/{job_id}?format=txt') as r:
        data = r.read()
        assert r.status == 200 and len(data.decode('utf-8').strip()) > 0
        print('Dynamic TXT download:', r.headers.get('Content-Type'), len(data))

    # 5. Download dynamic M4B (on-demand audiobook conversion)
    from backend.main import create_job, update_job, OUTPUT_DIR
    ab_job = create_job("", "test_audio.mp3", "mp3")
    ab_out_dir = OUTPUT_DIR / ab_job.job_id
    ab_out_dir.mkdir(parents=True, exist_ok=True)
    mock_mp3 = ab_out_dir / "test_audio.mp3"
    mock_mp3.write_bytes(b'ID3\x03\x00\x00\x00\x00\x00\x00' + b'\xff\xfb\x90\x00' * 50)
    update_job(ab_job.job_id, status="done", output_format="mp3")
    try:
        with urllib.request.urlopen(f'{API}/download/{ab_job.job_id}?format=m4b') as r:
            data = r.read()
            assert r.status == 200 and len(data) > 0
            assert 'audio/mp4' in r.headers.get('Content-Type', '')
            print('Dynamic M4B download:', r.headers.get('Content-Type'), len(data))
    finally:
        try:
            urllib.request.urlopen(urllib.request.Request(f'{API}/jobs/{ab_job.job_id}', method='DELETE'))
        except Exception:
            pass

    print('ALL TESTS PASSED SUCCESSFULLY!')
finally:
    try:
        urllib.request.urlopen(urllib.request.Request(f'{API}/jobs/{job_id}', method='DELETE'))
    except Exception:
        pass
    if os.path.exists(test_file):
        os.remove(test_file)
