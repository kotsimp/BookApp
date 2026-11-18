"""
tests/test_new_api_endpoints.py - Automated HTTP Integration Suite for Modern Endpoints.
Tests:
1. POST /api/detect-genre (with sample_text, text, empty text, various literary genres).
2. GET /api/tts/preview (instant audio sample generation for Nestoras and Athina).
3. GET /api/cache/stats (database cache hit/miss statistics).
4. POST /api/admin/cleanup (storage cleaner garbage collector trigger).
"""

import unittest
import urllib.request
import urllib.error
import json
import os
import sys
import time
import threading
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(BASE_DIR))

API_BASE = "http://127.0.0.1:8000/api"


def ensure_server():
    try:
        req = urllib.request.Request(f"{API_BASE}/cache/stats")
        with urllib.request.urlopen(req, timeout=0.8):
            return
    except Exception:
        pass
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
            req = urllib.request.Request(f"{API_BASE}/cache/stats")
            with urllib.request.urlopen(req, timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)


def http_get(path):
    req = urllib.request.Request(f"{API_BASE}{path}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.headers.get_content_type(), resp.read()


def http_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestNewAPIEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ensure_server()

    def test_detect_genre_endpoint(self):
        print("-> 1. Testing POST /api/detect-genre with various payloads...")
        
        # 1a. Payload with sample_text (Technical text with Docker/API keywords)
        tech_sample = "Ο διακομιστής API και η βάση δεδομένων SQL τρέχουν σε περιβάλλον Docker container."
        status, data = http_post_json("/detect-genre", {"sample_text": tech_sample})
        self.assertEqual(status, 200)
        self.assertIn("genre", data)
        self.assertIn("suggested_style", data)
        self.assertEqual(data["genre"], "technical")
        self.assertEqual(data["suggested_style"], "technical")

        # 1b. Payload with alternate field name 'text' (Literature with narrative and dialogue)
        lit_sample = "— «Δεν φοβάμαι», ψιθύρισε η Μαρία κοιτάζοντας το σκοτάδι. Η νύχτα ήταν παγωμένη."
        status, data = http_post_json("/detect-genre", {"text": lit_sample})
        self.assertEqual(status, 200)
        self.assertEqual(data["genre"], "literature")
        self.assertEqual(data["suggested_style"], "literature")

        # 1c. Payload with comics file_type
        status, data = http_post_json("/detect-genre", {"sample_text": "POW! BAM!", "file_type": "cbz"})
        self.assertEqual(status, 200)
        self.assertEqual(data["genre"], "comic")
        self.assertEqual(data["glossary_category"], "literary")

        # 1d. Empty text fallback
        status, data = http_post_json("/detect-genre", {"text": ""})
        self.assertEqual(status, 200)
        self.assertEqual(data["genre"], "literature")

        print("   POST /api/detect-genre: OK")

    def test_tts_preview_endpoint(self):
        print("-> 2. Testing GET /api/tts/preview for voice auditions...")
        
        # Test default voice (Nestoras)
        status, ctype, audio_bytes = http_get("/tts/preview?voice=el-GR-NestorasNeural")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "audio/mpeg")
        self.assertGreater(len(audio_bytes), 1000, "Preview audio stream must not be empty")

        # Test Athina voice
        status, ctype, audio_bytes_athina = http_get("/tts/preview?voice=el-GR-AthinaNeural")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "audio/mpeg")
        self.assertGreater(len(audio_bytes_athina), 1000)

        print("   GET /api/tts/preview: OK")

    def test_cache_stats_endpoint(self):
        print("-> 3. Testing GET /api/cache/stats...")
        status, ctype, body = http_get("/cache/stats")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json")
        stats = json.loads(body.decode("utf-8"))
        self.assertIn("cached_entries", stats)
        self.assertIn("total_hits", stats)
        self.assertIsInstance(stats["cached_entries"], int)
        self.assertIsInstance(stats["total_hits"], int)
        print(f"   GET /api/cache/stats: OK ({stats})")

    def test_admin_cleanup_endpoint(self):
        print("-> 4. Testing POST /api/admin/cleanup...")
        status, res = http_post_json("/admin/cleanup", {"max_age_hours": 48, "dry_run": True})
        self.assertEqual(status, 200)
        self.assertIn("files_deleted", res)
        self.assertIn("bytes_freed_mb", res)
        self.assertIn("dry_run", res)
        self.assertTrue(res["dry_run"])
        print("   POST /api/admin/cleanup: OK")


if __name__ == "__main__":
    unittest.main()
