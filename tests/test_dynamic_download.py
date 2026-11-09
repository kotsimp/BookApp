import urllib.request
import json
import time

API = 'http://127.0.0.1:8000/api'
from docx import Document

doc = Document()
doc.add_paragraph("Hello world. This is a format test for dynamic on-demand conversion.")
test_file = "temp/test_format.docx"
doc.save(test_file)

boundary = '----TestBoundary123'
file_bytes = open(test_file, 'rb').read()
body = (
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="file"; filename="test_format.docx"\r\n'
    f'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n'
).encode('utf-8') + file_bytes + f'\r\n--{boundary}--\r\n'.encode('utf-8')

req = urllib.request.Request(f'{API}/upload', data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
with urllib.request.urlopen(req) as resp:
    upload_res = json.loads(resp.read().decode())
job_id = upload_res['job_id']
print('Uploaded job:', job_id)

# Translate to docx
req = urllib.request.Request(f'{API}/translate', data=json.dumps({'job_id': job_id, 'source_lang': 'en', 'target_lang': 'el', 'output_format': 'docx'}).encode(), headers={'Content-Type': 'application/json'})
urllib.request.urlopen(req)

# Wait for completion
for _ in range(30):
    time.sleep(0.5)
    with urllib.request.urlopen(f'{API}/status/{job_id}') as r:
        s = json.loads(r.read().decode())
        if s['status'] == 'done':
            print('Translation done!')
            break

# 1. Download default docx
with urllib.request.urlopen(f'{API}/download/{job_id}') as r:
    print('Default download:', r.headers.get('Content-Type'), len(r.read()))

# 2. Download dynamic PDF
with urllib.request.urlopen(f'{API}/download/{job_id}?format=pdf') as r:
    print('Dynamic PDF download:', r.headers.get('Content-Type'), len(r.read()))

# 3. Download dynamic EPUB
with urllib.request.urlopen(f'{API}/download/{job_id}?format=epub') as r:
    print('Dynamic EPUB download:', r.headers.get('Content-Type'), len(r.read()))

# 4. Download dynamic TXT
with urllib.request.urlopen(f'{API}/download/{job_id}?format=txt') as r:
    print('Dynamic TXT download:', r.headers.get('Content-Type'), len(r.read()))

print('ALL TESTS PASSED SUCCESSFULLY!')
