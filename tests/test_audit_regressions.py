"""
test_audit_regressions.py - Regression guards for bugs found in the full codebase audit (2026-11).

1. Smart Batch Queue: the quota pause flag was assigned as a function-local variable (missing `global`), so
   is_queue_paused_for_quota() stayed False and a quota-paused queue never auto-resumed.
2. Saving new Gemini keys did not reset the global (persisted) quota circuit breaker, so translations kept failing
   with "quota exhausted" until the old reset time even with a fresh key.
3. CORS allowed every origin: any website open in the browser could read /api/settings (incl. API keys) or send
   JSON/DELETE requests to the local app. Only local development origins (and explicit BOOKAPP_CORS_ORIGINS) may.
4. Pillow (PIL) was imported by the comic translator but missing from requirements.txt (fresh installs/Docker broke).
5. An undefined name (DailyQuotaExhaustedError) in a comic except-clause turned any AI-polish error into NameError.
   Guarded generically: no undefined names anywhere in the backend (pyflakes, when available).
"""

import sys
sys.path.insert(0, ".")
import ast
import json
import time
import socket
import asyncio
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class TestQueueQuotaPause(unittest.TestCase):

    def tearDown(self):
        from backend import queue_manager as qm
        from backend.job_manager import cleanup_test_jobs
        qm.clear_queue()
        qm._queue_paused = False
        qm._queue_paused_for_quota = False
        cleanup_test_jobs()

    def test_quota_error_marks_queue_paused_for_quota(self):
        from backend import queue_manager as qm
        from backend.job_manager import create_job
        from backend.ai_polisher import DailyQuotaExhaustedError
        job = create_job("", "test_audit_queue.pdf", "pdf")
        qm.clear_queue()
        # explicit key: without one, add_to_queue correctly downgrades "wait" to "fallback"
        qm.add_to_queue(job.job_id, quota_behavior="wait", api_key="AQ.TestQueueQuotaKey")

        async def failing_runner(item):
            raise DailyQuotaExhaustedError("⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API")

        async def run():
            qm.start_queue(failing_runner)
            task = qm._queue_task
            if task is not None:
                await asyncio.wait_for(asyncio.shield(task), timeout=15)

        asyncio.run(run())
        self.assertTrue(qm.is_queue_paused_for_quota(), "quota-paused queue must report paused_for_quota (auto-resume)")
        self.assertTrue(qm.get_queue_state()["paused_for_quota"])


class TestNewKeysResetCircuitBreaker(unittest.TestCase):

    def setUp(self):
        from backend.settings_manager import load_settings
        self._snapshot = load_settings()

    def tearDown(self):
        from backend.settings_manager import save_settings
        from backend import ai_polisher as ap
        save_settings(self._snapshot)
        ap._GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL = 0.0

    def _assert_reset_by(self, call):
        from backend import ai_polisher as ap
        ap.trip_gemini_quota_exhaustion(3600.0)
        self.assertTrue(ap.is_gemini_quota_exhausted())
        with mock.patch("backend.gemini_key_pool.GeminiKeyPool.set_keys", side_effect=lambda k: k), \
             mock.patch("backend.gemini_key_pool.GeminiKeyPool.get_keys", return_value=["test-new-key"]), \
             mock.patch("backend.gemini_key_pool.GeminiKeyPool.get_active_key", return_value="test-new-key"), \
             mock.patch("backend.gemini_key_pool.GeminiKeyPool.get_pool_status", return_value={}):
            asyncio.run(call())
            self.assertFalse(ap.is_gemini_quota_exhausted(), "saving new keys must reset the quota circuit breaker")

    def test_settings_endpoint_resets_breaker(self):
        import backend.main as m
        self._assert_reset_by(lambda: m.update_app_settings(m.SettingsRequest(gemini_api_keys=["test-new-key"])))

    def test_pool_endpoint_resets_breaker(self):
        import backend.main as m
        self._assert_reset_by(lambda: m.update_gemini_pool_keys({"keys": ["test-new-key"]}))


class TestCorsPolicy(unittest.TestCase):
    _port = None

    @classmethod
    def setUpClass(cls):
        import uvicorn
        from backend.main import app
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls._port = s.getsockname()[1]
        s.close()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls._port, log_level="error", lifespan="off"))
        threading.Thread(target=server.run, daemon=True).start()
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls._port}/api/health", timeout=0.5)
                return
            except Exception:
                time.sleep(0.1)

    def _acao(self, origin, method="GET"):
        headers = {"Origin": origin}
        if method == "OPTIONS":
            headers.update({"Access-Control-Request-Method": "DELETE"})
        req = urllib.request.Request(f"http://127.0.0.1:{self._port}/api/health", headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.headers.get("access-control-allow-origin")
        except urllib.error.HTTPError as e:
            return e.headers.get("access-control-allow-origin")

    def test_foreign_origins_are_not_allowed(self):
        for origin in ("https://evil.example", "http://localhost.evil.example", "null"):
            self.assertIsNone(self._acao(origin), origin)
            self.assertIsNone(self._acao(origin, "OPTIONS"), f"preflight {origin}")

    def test_local_dev_origins_are_allowed(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:3000"):
            self.assertEqual(self._acao(origin), origin)


class TestDependencyAndStaticIntegrity(unittest.TestCase):

    IMPORT_TO_PACKAGE = {
        "PIL": "pillow", "docx": "python-docx", "bs4": "beautifulsoup4", "ebooklib": "ebooklib",
        "edge_tts": "edge-tts", "deep_translator": "deep-translator", "pymupdf": "pymupdf", "fitz": "pymupdf",
        "mutagen": "mutagen", "aiofiles": "aiofiles", "aiohttp": "aiohttp", "fastapi": "fastapi",
        "pydantic": "pydantic", "uvicorn": "uvicorn", "multipart": "python-multipart",
    }

    def test_every_third_party_import_is_declared(self):
        reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        declared = {line.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip()
                    for line in reqs.splitlines() if line.strip() and not line.startswith("#")}
        missing = []
        for f in sorted((ROOT / "backend").glob("*.py")):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module.split(".")[0]]
                for n in names:
                    if n in sys.stdlib_module_names or n == "backend":
                        continue
                    pkg = self.IMPORT_TO_PACKAGE.get(n, n).lower()
                    if pkg not in declared:
                        missing.append(f"{f.name}: {n} -> {pkg}")
        self.assertEqual(missing, [], "third-party imports missing from requirements.txt")

    def test_no_undefined_names_in_backend(self):
        try:
            from pyflakes import api as pf_api, reporter as pf_reporter
        except ImportError:
            self.skipTest("pyflakes not installed (dev tool)")
        import io
        out, err = io.StringIO(), io.StringIO()
        for f in sorted((ROOT / "backend").glob("*.py")):
            pf_api.check(f.read_text(encoding="utf-8"), str(f), pf_reporter.Reporter(out, err))
        undefined = [ln for ln in out.getvalue().splitlines() if "undefined name" in ln]
        self.assertEqual(undefined, [])


if __name__ == "__main__":
    unittest.main()
