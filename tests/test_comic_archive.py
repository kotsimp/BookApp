"""
test_comic_archive.py - .cbr uploads (RAR or ZIP inside) become readable CBZ; hostile archives stay harmless;
a .cbr export is a real RAR archive.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import io
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import UploadFile

import pymupdf

from backend import comic_archive, exporter, main, parsers


def jpeg(shade):
    buf = io.BytesIO()
    Image.new("RGB", (120, 160), (shade, shade, shade)).save(buf, "JPEG")
    return buf.getvalue()


def vint(number):
    out = b""
    while True:
        low, number = number & 0x7F, number >> 7
        if not number:
            return out + bytes([low])
        out += bytes([low | 0x80])


def rar5(files):
    """A minimal uncompressed RAR 5 fixture (names are UTF-8)."""
    def block(body):
        sized = vint(len(body)) + body
        return struct.pack("<I", zlib.crc32(sized)) + sized

    out = b"Rar!\x1a\x07\x01\x00" + block(vint(1) + vint(0) + vint(0))
    for name, data in files:
        raw = name.encode("utf-8")
        out += block(vint(2) + vint(2) + vint(len(data)) + vint(4) + vint(len(data)) + vint(0)
                     + struct.pack("<I", zlib.crc32(data)) + vint(0) + vint(0) + vint(len(raw)) + raw) + data
    return out + block(vint(5) + vint(0) + vint(0))


def rar4(files):
    """A minimal uncompressed RAR 4 fixture."""
    def head(kind, flags, body):
        rest = struct.pack("<BHH", kind, flags, 7 + len(body)) + body
        return struct.pack("<H", zlib.crc32(rest) & 0xFFFF) + rest

    out = b"Rar!\x1a\x07\x00" + head(0x73, 0, bytes(6))
    for name, data in files:
        raw = name.encode("ascii")
        out += head(0x74, 0x8000, struct.pack("<IIBIIBBHI", len(data), len(data), 2, zlib.crc32(data), 0x5B765000,
                                             20, 0x30, len(raw), 0x20) + raw) + data
    return out + head(0x7B, 0x4000, b"")


def comic_pdf(path, pages=3):
    with pymupdf.open() as doc:
        for n in range(pages):
            page = doc.new_page(width=300, height=420)
            page.insert_image(page.rect, stream=jpeg(60 + 40 * n))
            page.insert_text((30, 60), f"Page {n + 1}", fontsize=20)
        doc.save(str(path))
    return path


class TestRarExport(unittest.TestCase):
    """The layout every RAR reader knows: byte for byte the RAR 4 fixture that 7-Zip and bsdtar read below."""

    def test_the_writer_matches_the_rar4_layout(self):
        import time
        pages = [("page_0001.jpg", jpeg(40)), ("page_0002.jpg", jpeg(90))]
        out = io.BytesIO()
        writer = comic_archive.RarWriter(out, when=time.mktime((2025, 11, 22, 10, 0, 0, 0, 0, -1)))
        for name, data in pages:
            writer.add(name, data)
        writer.close()
        self.assertEqual(out.getvalue(), rar4(pages))

    def test_names_must_be_plain(self):
        writer = comic_archive.RarWriter(io.BytesIO())
        for bad in ("σελίδα.jpg", "../page.jpg", "a/b.jpg", ""):
            with self.assertRaises(ValueError, msg=bad):
                writer.add(bad, b"x")

    def test_a_cbr_export_is_rar_and_a_cbz_export_zip(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = comic_pdf(Path(td) / "comic.pdf")
            cbr = exporter.export_comic_archive(pdf, Path(td) / "out" / "comic.cbr", format="cbr")
            cbz = exporter.export_comic_archive(pdf, Path(td) / "out" / "comic.cbz", format="cbz")
            self.assertTrue(cbr.read_bytes().startswith(b"Rar!\x1a\x07\x00"))
            self.assertTrue(zipfile.is_zipfile(cbz))
            self.assertEqual(sorted(p.name for p in (Path(td) / "out").iterdir()), ["comic.cbr", "comic.cbz"])


class Decoder:
    """The same checks run once for each decoder."""
    only = ""

    def setUp(self):
        if not getattr(comic_archive, self.only)():
            self.skipTest(f"{self.only}: not installed")
        other = "find_bsdtar" if self.only == "find_7zip" else "find_7zip"
        patch = mock.patch.object(comic_archive, other, return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def convert(self, data):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "Κόμικ τεύχος 1.cbr"
            src.write_bytes(data)
            dest = Path(td) / "out.cbz"
            try:
                count = comic_archive.rar_to_cbz(src, dest)
            finally:
                left = [p.name for p in Path(td).iterdir() if p.name not in (src.name, dest.name)]
                self.assertEqual(left, [], "no working files are left")
            with zipfile.ZipFile(dest) as zf:
                return count, {n: zf.read(n) for n in zf.namelist()}

    def test_an_exported_cbr_reads_back_page_for_page(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = comic_pdf(Path(td) / "comic.pdf", pages=4)
            cbr = exporter.export_comic_archive(pdf, Path(td) / "comic.cbr", format="cbr")
            cbz = exporter.export_comic_archive(pdf, Path(td) / "comic.cbz", format="cbz")
            with zipfile.ZipFile(cbz) as zf:
                expected = {n: zf.read(n) for n in zf.namelist()}
            self.assertEqual(self.convert(cbr.read_bytes()), (4, expected))

    def test_both_rar_generations(self):
        pages = [("page_2.jpg", jpeg(100)), ("page_10.jpg", jpeg(150))]
        for build in (rar4, rar5):
            count, out = self.convert(build(pages + [("notes.txt", b"not a page")]))
            self.assertEqual((count, out), (2, dict(pages)), build.__name__)

    def test_greek_names(self):
        pages = [("Κεφάλαιο/σελίδα 1.jpg", jpeg(90)), ("Κεφάλαιο/σελίδα 2.png", jpeg(120))]
        self.assertEqual(self.convert(rar5(pages))[1], dict(pages))

    def test_names_cannot_leave_the_archive(self):
        count, out = self.convert(rar5([("../../outside.jpg", jpeg(10)), ("c:/evil.jpg", jpeg(20))]))
        self.assertEqual(count, 2)
        for name in out:
            self.assertFalse(name.startswith("/") or ".." in name.split("/") or ":" in name, name)

    def test_damaged_and_empty_archives_are_refused(self):
        damaged = bytearray(rar5([("p1.jpg", jpeg(50)), ("p2.jpg", jpeg(60))]))
        for bad in (bytes(damaged[:len(damaged) // 2]), rar5([("readme.txt", b"hello")]), b"Rar!\x1a\x07\x01\x00junk"):
            with self.assertRaises(comic_archive.ComicArchiveError):
                self.convert(bad)

    def test_unpacked_size_is_limited(self):
        with mock.patch.object(comic_archive, "MAX_UNPACKED_BYTES", 500), self.assertRaises(comic_archive.ComicArchiveError):
            self.convert(rar5([("p1.jpg", jpeg(50))]))

    def test_upload(self):
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as zf:
            zf.writestr("p1.jpg", jpeg(40))
            zf.writestr("p2.jpg", jpeg(80))
        cases = (rar4([("p1.jpg", jpeg(40)), ("p2.jpg", jpeg(80))]), zipped.getvalue())
        for data in cases:
            got = asyncio.run(main.upload_file(UploadFile(io.BytesIO(data), filename="issue.cbr")))
            job = main.get_job(got["job_id"])
            try:
                self.assertTrue(job.file_path.endswith("issue.cbz"))
                self.assertEqual((job.file_name, job.file_type), ("issue.cbr", "cbz"))
                self.assertTrue(got.get("is_comic"))
                self.assertEqual(parsers.count_cbz_pages(job.file_path), 2)
            finally:
                asyncio.run(main.delete_job(job.job_id))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(main.upload_file(UploadFile(io.BytesIO(b"neither rar nor zip"), filename="bad.cbr")))
        self.assertEqual(caught.exception.status_code, 400)


class TestWith7Zip(Decoder, unittest.TestCase):
    only = "find_7zip"

    def test_names_in_any_script(self):
        pages = [("漢字/ページ 1.jpg", jpeg(30)), ("漢字/ページ 2.jpg", jpeg(70))]
        self.assertEqual(self.convert(rar5(pages))[1], dict(pages))


class TestWithBsdtar(Decoder, unittest.TestCase):
    only = "find_bsdtar"


if __name__ == "__main__":
    unittest.main()
