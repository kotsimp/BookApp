"""
One-click launcher for DocTranslate & AudioBook.
Creates a virtual environment, installs dependencies, and starts the server.
"""

import sys
import os
import subprocess
import venv
from pathlib import Path

BASE_DIR = Path(__file__).parent
VENV_DIR = BASE_DIR / ".venv"
REQUIREMENTS = BASE_DIR / "requirements.txt"


def run(cmd, **kwargs):
    print(f"  → {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def get_python():
    """Return the Python executable inside the venv."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def get_pip():
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def get_uvicorn():
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "uvicorn.exe"
    return VENV_DIR / "bin" / "uvicorn"


def main():
    print("\n" + "=" * 60)
    print("  📚  DocTranslate & AudioBook Generator")
    print("=" * 60 + "\n")

    # Check Python version
    if sys.version_info < (3, 9):
        print(f"❌ Python 3.9+ required. You have {sys.version}.")
        sys.exit(1)

    print(f"✅ Python {sys.version.split()[0]} detected.\n")

    # Create venv if needed
    if not VENV_DIR.exists():
        print("📦 Creating virtual environment...")
        venv.create(str(VENV_DIR), with_pip=True)
        print("✅ Virtual environment created.\n")
    else:
        print("✅ Virtual environment found.\n")

    # Upgrade pip via python -m pip (more reliable in venvs on Windows)
    run([str(get_python()), "-m", "pip", "install", "--upgrade", "pip", "-q"])

    # Install requirements - use resilient install for Python 3.15+ compatibility
    print("📦 Installing dependencies (this may take a minute on first run)...")
    core_pkgs = [
        "fastapi", "uvicorn", "python-multipart", "aiofiles",
        "pymupdf", "python-docx", "beautifulsoup4",
        "deep-translator", "edge-tts", "EbookLib",
    ]
    for pkg in core_pkgs:
        try:
            subprocess.run(
                [str(get_python()), "-m", "pip", "install", pkg, "-q"],
                check=True, capture_output=True
            )
            print(f"  ✓ {pkg}")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ {pkg} failed — {e.stderr.decode()[:80] if e.stderr else 'unknown error'}")
    print("✅ Dependencies installed.\n")

    # Create temp directories
    (BASE_DIR / "temp" / "uploads").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "temp" / "outputs").mkdir(parents=True, exist_ok=True)

    # Launch server
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"

    print(f"🚀 Starting server at {url}")
    print("   Press CTRL+C to stop.\n")
    print("=" * 60 + "\n")

    # Open browser after short delay
    import threading
    import time
    import webbrowser

    def open_browser():
        time.sleep(2.0)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    # Run uvicorn
    os.chdir(str(BASE_DIR))
    subprocess.run([
        str(get_uvicorn()),
        "backend.main:app",
        "--host", host,
        "--port", str(port),
        "--reload",
        "--log-level", "info",
    ])


if __name__ == "__main__":
    main()
