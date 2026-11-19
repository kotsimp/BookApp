"""
clean_test_jobs.py - Helper utility to clean all test-generated jobs from BookApp.
Can be executed directly or imported by test suites.
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.job_manager import cleanup_test_jobs


def run():
    deleted = cleanup_test_jobs()
    print(f"Cleaned up {len(deleted)} test jobs from database, memory, and disk.")
    if deleted:
        print(f"Purged Job IDs: {deleted}")
    return len(deleted)


if __name__ == "__main__":
    run()
