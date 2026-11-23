"""
_sandbox_guard.py - Test suites only run inside the sandbox of run_all_tests.py.
Run directly they would share the real database, files, API keys and port 8000 (some suites clear all jobs).
"""
import os
import sys


def require_sandbox() -> None:
    if os.environ.get("BOOKAPP_TEST_MODE") != "1":
        sys.exit(
            "BookApp tests run only in an isolated sandbox, so they cannot delete your jobs or API keys.\n"
            "Use:  python run_all_tests.py [--fast] [suite names]   e.g.  python run_all_tests.py test_output_refinement"
        )


require_sandbox()

try:
    import _offline_translation
except ImportError:
    from tests import _offline_translation

_offline_translation.install()  # the suites must not spend the free services' daily allowance
