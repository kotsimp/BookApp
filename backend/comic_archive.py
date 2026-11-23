"""
comic_archive.py - Reads RAR comic archives (.cbr) by turning them into CBZ at upload, and writes .cbr exports.

Python has no RAR decoder, so a decoder that is already on the computer does that part:
* 7-Zip when installed: it reads every RAR generation and file names in any script;
* otherwise bsdtar (libarchive), built into Windows 10/11 and macOS, "libarchive-tools" on Linux. On Windows it
  cannot read names outside the system's code page.
Both only stream to a pipe and never write files themselves, so names inside an untrusted archive cannot reach the
file system, and the size limits below hold whatever the archive claims.

Writing needs no RAR compressor: comic pages are JPEG, which does not shrink further, so an export stores them as
they are, in the RAR 4 layout that every RAR reader knows (also the older readers that cannot open RAR 5).
"""

import contextlib
import functools
import logging
import os
import posixpath
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
import zlib
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

RAR_MAGIC = b"Rar!\x1a\x07"
RAR5_MAGIC = RAR_MAGIC + b"\x01\x00"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UNPACKED_BYTES = 2 * 1024 ** 3
MAX_PAGES = 5000
CONVERT_TIMEOUT = 300.0


class ComicArchiveError(ValueError):
    """The archive cannot be read; the message is meant for the user."""


class _DecoderFailed(Exception):
    """This decoder could not read the archive (the other one still may)."""


def is_rar(head: bytes) -> bool:
    return head.startswith(RAR_MAGIC)


def _rar4_block(kind: int, flags: int, body: bytes) -> bytes:
    """One RAR 4 block: CRC-16 (the low half of CRC-32) of type, flags, size and body; then those."""
    rest = struct.pack("<BHH", kind, flags, 7 + len(body)) + body
    return struct.pack("<H", zlib.crc32(rest) & 0xFFFF) + rest


class RarWriter:
    """
    Writes a RAR 4 archive of stored files to an open binary file, one file at a time (RARLAB's technote for
    RAR 2.9-4.x: marker block, archive header, a file header plus data per file, end-of-archive block).
    Names are plain ASCII file names without folders, as the app's page names are.
    """

    _NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

    def __init__(self, fileobj, when: Optional[float] = None):
        self.fileobj = fileobj
        t = time.localtime(when)
        year = min(max(t.tm_year, 1980), 2107)
        self.dos_time = ((year - 1980) << 25 | t.tm_mon << 21 | t.tm_mday << 16
                         | t.tm_hour << 11 | t.tm_min << 5 | t.tm_sec // 2)
        fileobj.write(RAR_MAGIC + b"\x00" + _rar4_block(0x73, 0, bytes(6)))

    def add(self, name: str, data: bytes) -> None:
        if not self._NAME_RE.fullmatch(name or "") or len(name) > 255:
            raise ValueError(f"not a plain file name: {name!r}")
        if len(data) >= 2 ** 32:
            raise ValueError(f"{name}: 4 GB or more")
        raw = name.encode("ascii")
        # long block (data follows), stored (0x30), made on Windows (2) with the archive attribute, RAR 2.0 to extract
        header = struct.pack("<IIBIIBBHI", len(data), len(data), 2, zlib.crc32(data), self.dos_time,
                             20, 0x30, len(raw), 0x20)
        self.fileobj.write(_rar4_block(0x74, 0x8000, header + raw))
        self.fileobj.write(data)

    def close(self) -> None:
        self.fileobj.write(_rar4_block(0x7B, 0x4000, b""))


@functools.lru_cache(maxsize=None)
def find_7zip() -> Optional[str]:
    candidates = [shutil.which("7zz"), shutil.which("7z")]
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        if os.environ.get(var):
            candidates.append(str(Path(os.environ[var]) / "7-Zip" / "7z.exe"))
    return next((str(Path(c).resolve()) for c in candidates if c and Path(c).is_file()), None)


@functools.lru_cache(maxsize=None)
def find_bsdtar() -> Optional[str]:
    candidates = [shutil.which("bsdtar")]
    if os.name == "nt":
        candidates.append(str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"))
    candidates.append(shutil.which("tar"))
    for tool in candidates:
        if not tool or not Path(tool).is_file():
            continue
        tool = str(Path(tool).resolve())
        try:
            shown = subprocess.run([tool, "--version"], capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        if b"bsdtar" in shown.stdout:  # GNU tar cannot read RAR
            return tool
    return None


class _Pages:
    """Collects the pages into a CBZ, within the limits."""

    def __init__(self, zf: zipfile.ZipFile):
        self.zf, self.count, self.unpacked = zf, 0, 0
        self._used: set = set()

    def claim(self, raw_name: str, size: int) -> Optional[str]:
        """The page's harmless name that keeps its order, or None for what is not a page."""
        self.unpacked += size
        if self.unpacked > MAX_UNPACKED_BYTES or self.count >= MAX_PAGES:
            raise ComicArchiveError("Το αρχείο CBR είναι υπερβολικά μεγάλο όταν αποσυμπιεστεί.")
        name = raw_name.encode("utf-8", "replace").decode("utf-8").replace("\\", "/")
        parts = [re.sub(r'[<>:"|?*\x00-\x1f]', "_", p) for p in name.split("/") if p.strip(". ")]
        if not parts or "__MACOSX" in parts or parts[-1].startswith("."):
            return None
        stem, suffix = posixpath.splitext("/".join(parts))
        if suffix.lower() not in IMAGE_SUFFIXES:
            return None
        name, number = stem + suffix, 1
        while name.lower() in self._used:
            number += 1
            name = f"{stem}_{number}{suffix}"
        self._used.add(name.lower())
        return name

    def store(self, name: Optional[str], stream, size: int) -> None:
        """Moves exactly `size` bytes of `stream` into the page (or nowhere, when it is not one)."""
        page = self.zf.open(name, "w", force_zip64=True) if name else None
        try:
            left = size
            while left:
                data = stream.read(min(left, 1024 * 1024))
                if not data:
                    raise _DecoderFailed("the stream ended inside a file")
                if page:
                    page.write(data)
                left -= len(data)
        finally:
            if page:
                page.close()
        if name:
            self.count += 1


def _stream(command: List[str], work: str, consume: Callable) -> None:
    env = {name: value for name, value in os.environ.items() if "API_KEY" not in name.upper()}  # no keys for tools
    if os.name != "nt" and "UTF-8" not in env.get("LC_ALL", "").upper():
        env["LC_ALL"] = "C.UTF-8"  # otherwise libarchive refuses non-ASCII names
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=errors)
        watchdog = threading.Timer(CONVERT_TIMEOUT, proc.kill)
        watchdog.start()
        finished = False
        try:
            consume(proc.stdout)
            finished = True
        except (tarfile.TarError, EOFError) as e:
            raise _DecoderFailed(str(e)) from e
        finally:
            if not finished:
                proc.kill()
            proc.stdout.close()
            code = proc.wait()
            watchdog.cancel()
        if code != 0:
            errors.seek(0)
            raise _DecoderFailed(f"exit code {code}: {errors.read()[-300:].decode('utf-8', 'replace').strip()}")


def _with_7zip(tool: str, work: str, pages: _Pages, rar5: bool) -> None:
    kind = "-trar5" if rar5 else "-trar"  # never let 7-Zip guess another format for an untrusted file
    try:
        listing = subprocess.run([tool, "l", "-slt", "-sccUTF-8", "-p-", kind, "in.rar"], cwd=work,
                                 capture_output=True, stdin=subprocess.DEVNULL, timeout=CONVERT_TIMEOUT)
    except subprocess.SubprocessError as e:
        raise _DecoderFailed(str(e)) from e
    if listing.returncode != 0:
        raise _DecoderFailed(f"7-Zip list: exit code {listing.returncode}")
    shown = listing.stdout.decode("utf-8", "replace").replace("\r\n", "\n").partition("\n----------\n")[2]
    entries: List[dict] = []
    for line in shown.split("\n"):
        key, found, value = line.partition(" = ")
        if not found:
            key, value = line.rstrip(" ="), ""
        if key == "Path":
            entries.append({})
        if entries:
            entries[-1][key] = value
    files: List[Tuple[Optional[str], int]] = []
    for entry in entries:
        if entry.get("Encrypted") == "+":
            raise _DecoderFailed("password protected")
        if entry.get("Folder") == "+" or entry.get("Symbolic Link") or entry.get("Hard Link"):
            continue  # these put nothing on the stream
        if not entry.get("Size", "").isdigit():
            raise _DecoderFailed("unreadable file list")
        files.append((pages.claim(entry["Path"], int(entry["Size"])), int(entry["Size"])))

    def consume(out) -> None:
        for name, size in files:  # stdout holds the files' bytes in the order of the list
            pages.store(name, out, size)
        if out.read(1):
            raise _DecoderFailed("more data than the file list announces")

    _stream([tool, "x", "-so", "-bd", "-p-", kind, "in.rar"], work, consume)


def _with_bsdtar(tool: str, work: str, pages: _Pages, rar5: bool) -> None:
    def consume(out) -> None:
        with tarfile.open(fileobj=out, mode="r|") as stream:
            for member in stream:
                if not member.isfile():
                    continue
                name = pages.claim(member.name, member.size)
                if name:
                    pages.store(name, stream.extractfile(member), member.size)
        out.read()  # let the tool finish writing its padding

    _stream([tool, "--format=pax", "-cf", "-", "@in.rar"], work, consume)


@contextlib.contextmanager
def _work_dir(parent: Path):
    """A temporary folder whose cleanup never fails a conversion (TemporaryDirectory can do that from 3.10 on only)."""
    path = tempfile.mkdtemp(prefix=".cbr-", dir=parent)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def rar_to_cbz(src, dest) -> int:
    """Writes the pages of the RAR archive `src` to the CBZ `dest` and returns their number."""
    seven_zip, bsdtar = find_7zip(), find_bsdtar()
    decoders = [(fn, tool) for fn, tool in ((_with_7zip, seven_zip), (_with_bsdtar, bsdtar)) if tool]
    if not decoders:
        raise ComicArchiveError(
            "Τα αρχεία CBR (RAR) χρειάζονται το 7-Zip ή το bsdtar (σε Linux: πακέτο 'libarchive-tools'). "
            "Εναλλακτικά μετατρέψτε το κόμικ σε CBZ."
        )
    src, dest = Path(src), Path(dest)
    with _work_dir(dest.parent) as work:
        plain = Path(work) / "in.rar"  # a plain name: the decoders mishandle some characters in paths
        shutil.copyfile(src, plain)
        with open(plain, "rb") as f:
            rar5 = f.read(8) == RAR5_MAGIC
        staged = Path(work) / "out.cbz"
        for decode, tool in decoders:
            try:
                with zipfile.ZipFile(staged, "w", zipfile.ZIP_STORED) as zf:
                    pages = _Pages(zf)
                    decode(tool, work, pages, rar5)
            except _DecoderFailed as e:
                logger.warning(f"CBR: {Path(tool).name} could not read the archive ({e}).")
                continue
            if pages.count:
                os.replace(staged, dest)
                return pages.count
            break  # readable, but without any page
    hint = "" if seven_zip else " Αν το κόμικ έχει ονόματα αρχείων σε άλλη γλώσσα, εγκαταστήστε το δωρεάν 7-Zip."
    raise ComicArchiveError(
        "Το αρχείο CBR δεν μπόρεσε να διαβαστεί: είναι κατεστραμμένο, κλειδωμένο με κωδικό ή χωρίς εικόνες." + hint
    )
