"""
conftest.py - Pytest fixtures ensuring automatic test job isolation and cleanup.
Purges all test-generated jobs from in-memory cache, SQLite database, and disk directories
before and after test sessions and test cases so Session History remains pristine.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

from backend.job_manager import cleanup_test_jobs

try:
    import pytest

    @pytest.fixture(autouse=True, scope="session")
    def auto_cleanup_test_jobs_session():
        """Runs cleanup at session start and end."""
        cleanup_test_jobs()
        yield
        cleanup_test_jobs()

    @pytest.fixture(autouse=True, scope="function")
    def auto_cleanup_test_jobs_function():
        """Ensures each test function leaves no lingering test jobs in Session History."""
        yield
        cleanup_test_jobs()

except ImportError:
    pass
