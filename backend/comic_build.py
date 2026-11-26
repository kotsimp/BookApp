"""
backend/comic_build.py - A comic's EPUB, CBZ or CBR made in a process of its own.

Drawing a page (PyMuPDF) holds Python's lock for the whole page. In a thread of the server that stalled its main loop
page after page: every request crawled, and a download sent in 64 KB pieces stayed on "Downloading…" in the e-reader
(live, KOReader). In a child process the server only waits, and a build that runs out of memory takes only itself
down.

    python -m backend.comic_build <epub|cbz|cbr> <source.pdf> <target> [--title T] [--direction ltr|rtl]
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Union

BASE_DIR = Path(__file__).resolve().parent.parent
BUILD_TIMEOUT = 30 * 60  # seconds: a very long comic on a small server, with room to spare


def build_in_child(kind: str, source: Union[str, Path], target: Union[str, Path], title: str = "Graphic Novel",
                   reading_direction: str = "ltr") -> Path:
    """Makes the file in a child process and waits for it (in a worker thread: waiting does not hold the lock).
    The file appears complete or not at all, as the exporters write it."""
    kind = (kind or "").lower()
    if kind not in ("epub", "cbz", "cbr"):
        raise ValueError(f"Unknown comic format '{kind}'.")
    cmd = [sys.executable, "-m", "backend.comic_build", kind, str(source), str(target),
           "--title", title or "Graphic Novel",
           "--direction", "rtl" if (reading_direction or "").lower() == "rtl" else "ltr"]
    try:
        done = subprocess.run(cmd, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Making {Path(target).name} took longer than {BUILD_TIMEOUT // 60} minutes.") from e
    if done.returncode != 0 or not Path(target).is_file():
        detail = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [f"exit {done.returncode}"]
        raise RuntimeError(f"Making {Path(target).name} failed: {detail[0]}")
    return Path(target)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.comic_build", description=__doc__.split("\n\n")[0])
    parser.add_argument("kind", choices=("epub", "cbz", "cbr"))
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--title", default="Graphic Novel")
    parser.add_argument("--direction", default="ltr", choices=("ltr", "rtl"))
    args = parser.parse_args(argv)
    from backend.exporter import export_comic_archive, export_comic_epub
    if args.kind == "epub":
        export_comic_epub(args.source, args.target, title=args.title, reading_direction=args.direction)
    else:
        export_comic_archive(args.source, args.target, format=args.kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
