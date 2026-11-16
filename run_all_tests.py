"""
run_all_tests.py - Unified Master Test Suite Runner.
Discovers and executes all test suites in the tests/ directory,
reporting live status, execution timings, and detailed diagnostic logs on failure.
"""

import sys
import glob
import subprocess
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))


def run_suite():
    test_files = sorted(glob.glob("tests/test_*.py"))
    if not test_files:
        print("❌ No test files found in tests/")
        sys.exit(1)

    print("=" * 70)
    print(f"🚀 Running BookApp Automated Test Suite ({len(test_files)} test suites)")
    print("=" * 70)

    passed = []
    failed = []
    total_start = time.time()

    for idx, tf in enumerate(test_files, 1):
        rel_name = Path(tf).name
        print(f"[{idx:02d}/{len(test_files):02d}] {rel_name:<36} ... ", end="", flush=True)

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

    total_dur = time.time() - total_start
    print("\n" + "=" * 70)
    print("📊 TEST SUITE SUMMARY")
    print("=" * 70)
    print(f"  Total Suites Run : {len(test_files)}")
    print(f"  Passed           : {len(passed)} ✅")
    print(f"  Failed           : {len(failed)} {'❌' if failed else ''}")
    print(f"  Total Duration   : {total_dur:.2f}s")
    print("=" * 70)

    if failed:
        print("\n❌ FAILURES ENCOUNTERED:")
        for name, dur, err in failed:
            print(f"\n--- {name} ({dur:.2f}s) ---")
            lines = err.splitlines()
            # Print last 25 lines of failure output
            print("\n".join(lines[-25:]))
        print("=" * 70)
        sys.exit(1)
    else:
        print("\n🎉 ALL TESTS IN THE TEST SUITE PASSED SUCCESSFULLY!\n")
        sys.exit(0)


if __name__ == "__main__":
    run_suite()
