"""Importing the suites as a package (unittest -m, pytest) also requires the sandbox."""
from tests import _sandbox_guard  # noqa: F401
