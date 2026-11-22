"""
run_all_tests.py - Bulletproof Unified Master Test Suite Runner.
Features:
1. Runs every suite in a throw-away copy of the project, on a free port, with an empty database and no API keys.
   Your jobs, files, settings and a running BookApp (port 8000) are never touched.
2. Auto-discovers and executes all test suites in tests/, against its own temporary Uvicorn backend.
3. '--fast' skips the suites that need the internet.
4. Names select suites:  python run_all_tests.py test_output_refinement test_book_insights
"""

import os
import re
import sys
import glob
import time
import shutil
import socket
import tempfile
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

IN_SANDBOX = os.environ.get("BOOKAPP_TEST_MODE") == "1"
PORT = int(os.environ.get("BOOKAPP_TEST_PORT", "0"))

SLOW_EXTERNAL_NETWORK_SUITES = {
    "test_api.py",
    "test_translator.py",
    "test_format_preservation.py",
    "test_dynamic_download.py",
    "test_editor_glossary_ai.py",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_in_sandbox() -> int:
    """Copies the code (never data/, temp/ or settings) to a temp folder and runs the suites there."""
    work = Path(tempfile.mkdtemp(prefix="bookapp-tests-"))
    sandbox = work / "app"
    ignore = shutil.ignore_patterns(
        ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "settings*.json*", "settings*.tmp", "*.log",
    )

    def ignore_top(folder, names):
        skipped = set(ignore(folder, names))
        if Path(folder).resolve() == BASE_DIR:
            skipped |= {"data", "temp"} & set(names)
        return skipped

    try:
        shutil.copytree(BASE_DIR, sandbox, ignore=ignore_top)
        for sub_dir in ("data", "temp/uploads", "temp/outputs"):
            (sandbox / sub_dir).mkdir(parents=True, exist_ok=True)
        port = _free_port()
        # The suites address the app's default port: point the copies at the sandbox's own port
        for test_file in (sandbox / "tests").glob("*.py"):
            test_file.write_bytes(re.sub(rb"\b8000\b", str(port).encode(), test_file.read_bytes()))

        env = dict(os.environ)
        for var in ("GEMINI_API_KEY", "GEMINI_API_KEYS", "GEMINI_QUOTA_EXHAUSTED_UNTIL", "BOOKAPP_PAIRING",
                    "BOOKAPP_TRUST_LOOPBACK", "FINAL_REFINEMENT_ENABLED"):
            env.pop(var, None)
        env.update(BOOKAPP_TEST_MODE="1", BOOKAPP_TEST_PORT=str(port), PYTHONIOENCODING="utf-8",
                   PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, str(sandbox / "run_all_tests.py"), *sys.argv[1:]],
                              cwd=str(sandbox), env=env).returncode
    finally:
        for _ in range(5):  # Windows releases file handles of the stopped server with a small delay
            shutil.rmtree(work, ignore_errors=True)
            if not work.exists():
                break
            time.sleep(0.5)


def _is_server_up() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False


def _start_temp_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "error"],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        if _is_server_up():
            return proc
        time.sleep(0.15)
    return proc


def run_suite():
    fast_mode = "--fast" in sys.argv
    test_files = sorted(glob.glob("tests/test_*.py"))
    if not test_files:
        print("❌ No test files found in tests/")
        sys.exit(1)

    if fast_mode:
        test_files = [tf for tf in test_files if Path(tf).name not in SLOW_EXTERNAL_NETWORK_SUITES]

    wanted = {Path(a).stem for a in sys.argv[1:] if not a.startswith("-")}
    if wanted:
        test_files = [tf for tf in test_files if Path(tf).stem in wanted]
        unknown = wanted - {Path(tf).stem for tf in test_files}
        if unknown:
            print(f"❌ Unknown suite(s): {', '.join(sorted(unknown))}")
            sys.exit(1)

    print(f"⚙️  Isolated sandbox on port {PORT} — your jobs, settings and running BookApp are not touched.")
    temp_server = _start_temp_server()

    mode_label = "FAST MODE" if fast_mode else "FULL SUITE"
    print("=" * 72)
    print(f"🚀 Running BookApp Bulletproof Test Suite [{mode_label}] ({len(test_files)} suites)")
    print("=" * 72)

    passed = []
    failed = []
    total_start = time.time()

    try:
        for idx, tf in enumerate(test_files, 1):
            rel_name = Path(tf).name
            print(f"[{idx:02d}/{len(test_files):02d}] {rel_name:<40} ... ", end="", flush=True)

            t0 = time.time()
            res = subprocess.run([sys.executable, tf], capture_output=True, text=True)
            dur = time.time() - t0

            if res.returncode == 0:
                passed.append((rel_name, dur))
                print(f"✅ PASS ({dur:.2f}s)")
            else:
                err_output = (res.stderr or res.stdout or "").strip()
                failed.append((rel_name, dur, err_output))
                print(f"❌ FAIL ({dur:.2f}s)")
    finally:
        temp_server.terminate()
        try:
            temp_server.wait(timeout=5)
        except Exception:
            temp_server.kill()

    total_dur = time.time() - total_start
    print("\n" + "=" * 72)
    print("📊 TEST SUITE SUMMARY")
    print("=" * 72)
    print(f"  Mode             : {mode_label}")
    print(f"  Total Suites Run : {len(test_files)}")
    print(f"  Passed           : {len(passed)} ✅")
    print(f"  Failed           : {len(failed)} {'❌' if failed else ''}")
    print(f"  Total Duration   : {total_dur:.2f}s")
    print("  User data        : Not touched (isolated sandbox) 🛡️")
    print("=" * 72)

    if failed:
        print("\n❌ FAILURES ENCOUNTERED:")
        for name, dur, err in failed:
            print(f"\n--- {name} ({dur:.2f}s) ---")
            lines = err.splitlines()
            print("\n".join(lines[-25:]))
        print("=" * 72)
        sys.exit(1)
    else:
        print("\n🎉 ALL TESTS IN THE BULLETPROOF TEST SUITE PASSED SUCCESSFULLY!\n")
        sys.exit(0)


if __name__ == "__main__":
    if IN_SANDBOX:
        run_suite()
    else:
        sys.exit(_run_in_sandbox())
