"""
run_all_tests.py - Bulletproof Unified Master Test Suite Runner.
Features:
1. Auto-discovers and executes all 28 test suites in tests/.
2. Snapshots & restores config/settings.json safely (NEVER overwrites or deletes user API keys).
3. Auto-launches a temporary Uvicorn backend if localhost:8000 is not already running.
4. Supports '--fast' flag to run all static, unit, regression, benchmark, and mock-API suites in seconds.
"""

import sys
import glob
import time
import shutil
import subprocess
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

SLOW_EXTERNAL_NETWORK_SUITES = {
    "test_api.py",
    "test_translator.py",
    "test_format_preservation.py",
    "test_dynamic_download.py",
    "test_editor_glossary_ai.py",
}


def _is_server_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False


def _start_temp_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "error"],
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

    # Snapshot user's config/settings.json so tests can NEVER lose or overwrite user API keys
    settings_file = BASE_DIR / "config" / "settings.json"
    settings_backup = settings_file.read_bytes() if settings_file.exists() else None

    temp_server = None
    if not _is_server_up():
        print("⚙️  No server detected on port 8000 — starting temporary Uvicorn test server...")
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
        # Always restore user settings untouched
        if settings_backup is not None:
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            settings_file.write_bytes(settings_backup)
        elif settings_file.exists():
            try:
                settings_file.unlink(missing_ok=True)
            except Exception:
                pass

        if temp_server is not None:
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
    print(f"  User Settings    : Protected & Restored 🛡️")
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
    run_suite()
