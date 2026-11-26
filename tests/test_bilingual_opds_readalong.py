"""
tests/test_bilingual_opds_readalong.py - The bilingual edition, the e-reader catalogue (OPDS) and reading along with
an audiobook.

1. Bilingual: page markers of both styles, paragraph matching (joined, split, missing paragraphs, whole texts without
   markers), the PDF / DOCX / EPUB files, and the download endpoint (formats, comics, not yet translated).
2. OPDS: secret links (only a hash kept, a new one stops the old), open paths for reading apps, the Atom feed, book
   downloads and the 404 of unknown or removed links.
3. Reading along: sentence times from the parts' durations, and the endpoint ignoring times of an older recording.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import json
import os
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import pymupdf as fitz

from backend import bilingual, connections

API = "http://127.0.0.1:8000/api"
ROOT = "http://127.0.0.1:8000"
ATOM = "{http://www.w3.org/2005/Atom}"

ORIGINAL = ("=== PAGE 1 ===\nChapter One\n\nThe ship sailed at dawn. The sea was grey.\n\nShe watched the harbour.\n\n"
            "=== PAGE 2 ===\n\"Where are we going?\" he asked.\n\n\"North,\" she said.\n\nThey said nothing more.")
TRANSLATED = ("\n" + "=" * 60 + "\nPAGE 1\n" + "=" * 60 + "\n\nΚεφάλαιο Πρώτο\n\nΤο πλοίο σάλπαρε την αυγή. Η θάλασσα "
              "ήταν γκρίζα.\n\nΕκείνη κοίταζε το λιμάνι.\n\n=== PAGE 2 ===\n«Πού πάμε;» ρώτησε. «Βόρεια», είπε εκείνη."
              "\n\nΔεν είπαν τίποτε άλλο.")


class BilingualTests(unittest.TestCase):
    def test_page_markers_of_both_styles(self):
        pages = bilingual.split_pages(TRANSLATED)
        self.assertEqual([p for p, _ in pages], [1, 2])
        self.assertIn("Κεφάλαιο Πρώτο", pages[0][1])
        self.assertEqual(bilingual.split_pages("Before\n=== PAGE 3 ===\nX")[0], (None, "Before\n"))

    def test_paragraphs_matched_page_by_page(self):
        passages = bilingual.bilingual_passages(ORIGINAL, TRANSLATED)
        self.assertEqual([(len(s), len(t)) for s, t in passages], [(1, 1), (1, 1), (1, 1), (2, 1), (1, 1)])
        self.assertEqual(passages[3][0][1], "\"North,\" she said.")
        self.assertTrue(passages[3][1][0].startswith("«Πού πάμε;»"))

    def test_missing_and_split_paragraphs(self):
        src = ["A short line.", "A much longer paragraph " * 8, "An ending."]
        tgt = ["Μια σύντομη γραμμή.", "Μια πολύ μεγαλύτερη παράγραφος " * 4, "Μια πολύ μεγαλύτερη παράγραφος " * 4,
               "Ένα τέλος."]
        groups = bilingual.align(src, tgt)
        self.assertEqual([(len(s), len(t)) for s, t in groups], [(1, 1), (1, 2), (1, 1)])
        self.assertEqual(sum(len(s) for s, _ in groups), 3)
        self.assertEqual(sum(len(t) for _, t in groups), 4)
        groups = bilingual.align(["One.", "Two two two two.", "Three."], ["Ένα.", "Τρία."])
        self.assertEqual(sum(len(s) for s, _ in groups), 3, "every paragraph is kept")
        self.assertEqual(bilingual.align([], ["Μόνο μετάφραση."]), [([], ["Μόνο μετάφραση."])])

    def test_whole_text_without_markers(self):
        src = [f"Paragraph {i}. " + "x" * (40 + i % 90) for i in range(400)]
        tgt = [f"Παράγραφος {i}. " + "χ" * int((40 + i % 90) * 1.1) for i in range(400)]
        tgt[50:52] = [tgt[50] + " " + tgt[51]]
        passages = bilingual.bilingual_passages("\n\n".join(src), "\n\n".join(tgt))
        self.assertEqual([(len(s), len(t)) for s, t in passages if (len(s), len(t)) != (1, 1)], [(2, 1)])
        self.assertTrue(passages[-1][0][0].startswith("Paragraph 399."))
        self.assertTrue(passages[-1][1][0].startswith("Παράγραφος 399."))

    def test_exported_files(self):
        passages = bilingual.bilingual_passages(ORIGINAL, TRANSLATED)
        with tempfile.TemporaryDirectory() as td:
            pdf = bilingual.export_bilingual_pdf(passages, Path(td) / "b.pdf", "Το πλοίο", "sub", "english", "greek")
            with fitz.open(pdf) as doc:
                text = "".join(page.get_text() for page in doc)
            self.assertIn("The ship sailed at dawn.", text)
            self.assertIn("Το πλοίο σάλπαρε την αυγή.", text)
            self.assertLess(text.index("The ship sailed"), text.index("Το πλοίο σάλπαρε"), "the original first")
            self.assertLess(pdf.stat().st_size, 400_000, "only the letters used are embedded (live: 1.3 MB before)")
            self.assertNotIn("\xa0", text, "copied text has the book's own spaces")
            from docx import Document
            docx = bilingual.export_bilingual_docx(passages, Path(td) / "b.docx", "T", "sub", "english", "greek")
            paras = [p.text for p in Document(str(docx)).paragraphs]
            self.assertIn("She watched the harbour.", paras)
            self.assertEqual(paras[paras.index("She watched the harbour.") + 1], "Εκείνη κοίταζε το λιμάνι.")
            from ebooklib import epub, ITEM_DOCUMENT
            ep = bilingual.export_bilingual_epub(passages, Path(td) / "b.epub", "T", "sub", "english", "greek")
            html = "".join(i.get_content().decode("utf-8") for i in epub.read_epub(str(ep)).get_items()
                           if i.get_type() == ITEM_DOCUMENT)
            self.assertIn('class="src" lang="en"', html)
            self.assertIn("Δεν είπαν τίποτε άλλο.", html)


class ConnectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(connections, "STORE", Path(self.tmp.name) / "connections.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_secret_links(self):
        self.assertFalse(connections.opds_status("u1")["exists"])
        first = connections.new_opds_token("u1")
        self.assertEqual(connections.owner_for_opds_token(first), "u1")
        self.assertNotIn(first, connections.STORE.read_text(encoding="utf-8"), "only the token's hash is kept")
        second = connections.new_opds_token("u1")
        self.assertIsNone(connections.owner_for_opds_token(first), "a new link stops the old one")
        self.assertEqual(connections.owner_for_opds_token(second), "u1")
        other = connections.new_opds_token("")
        self.assertEqual(connections.owner_for_opds_token(other), "")
        connections.remove_opds_token("u1")
        self.assertIsNone(connections.owner_for_opds_token(second))
        self.assertIsNone(connections.owner_for_opds_token(""))
        self.assertIsNone(connections.owner_for_opds_token("x" * 500))

    def test_open_paths_for_reading_apps(self):
        from backend import auth, device_pairing
        self.assertTrue(auth.is_open_path("/opds/abc/"))
        self.assertTrue(device_pairing.is_open_path("/opds/abc/book/x/epub"))
        self.assertFalse(auth.is_open_path("/opdsx"))
        self.assertFalse(auth.is_open_path("/api/connections"))

class CatalogueContentTests(unittest.TestCase):
    """Which books a catalogue link lists: finished translations of its own user."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, job_id, owner, mode="translate", status="done", translated=True):
        if translated:
            (self.out / job_id).mkdir()
            (self.out / job_id / f"{job_id}_translated_greek.txt").write_text("Κείμενο.", encoding="utf-8")
        return types.SimpleNamespace(job_id=job_id, owner=owner, mode=mode, status=status, target_lang="greek",
                                     source_lang="english", file_name=f"{job_id}.pdf", file_type="pdf",
                                     layout_mode="standard", updated_at=time.time(), sample_range=None)

    def _titles(self, token_owner, users, jobs):
        from backend import auth
        from backend.api import connections as api
        from backend.request_context import reset_current_user
        with mock.patch.object(api, "OUTPUT_DIR", self.out), \
                mock.patch("backend.connections.owner_for_opds_token", return_value=token_owner), \
                mock.patch.object(auth, "is_enabled", return_value=bool(users)), \
                mock.patch.object(auth, "get_user", side_effect=lambda uid: users.get(uid)), \
                mock.patch("backend.job_manager.list_jobs", return_value=jobs):
            ctx, own = api._catalogue_user("token")
            try:
                feed = api._feed("token", own)
            finally:
                reset_current_user(ctx)
        root = ET.fromstring(feed)
        return sorted(e.findtext(f"{ATOM}title") for e in root.findall(f"{ATOM}entry"))

    def test_translations_stay_listed_after_an_audiobook(self):
        jobs = [self._job("narrated", "", mode="audiobook"), self._job("plain", ""),
                self._job("running", "", status="running"), self._job("untranslated", "", translated=False)]
        self.assertEqual(self._titles("", {}, jobs), ["narrated", "plain"])

    def test_links_end_in_a_file_name_with_its_extension(self):
        """Live finding (KOReader, a comic): KOReader takes a download's format and file name from the link's
        extension (the text after the last dot of the whole address) before its media type. Links ended in ".../cbz",
        so its file type could not be told. Now each ends in the book's file name with the right extension."""
        from backend.api import connections as api
        comic = self._job("nebraska", "")
        comic.file_name = "USS Nebraska (Sanctum Vol 01 - Humanoids Graphic Novel) -- Xavier Dorison & Christophe Bec.pdf"
        comic.layout_mode = "comic"
        book = self._job("book", "")
        book.file_name = "Ο Φάρος.epub"
        with mock.patch.object(api, "OUTPUT_DIR", self.out):
            entries = {j.job_id: ET.fromstring('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/">'
                                               f'{api._entry(j, "/opds/t/")}</feed>') for j in (comic, book)}

        def acquisitions(job_id):
            return [(l.get("type"), "http://192.168.1.20:8000" + l.get("href")) for l in entries[job_id].iter(f"{ATOM}link")
                    if l.get("rel") == "http://opds-spec.org/acquisition"]

        def koreader_suffix(href):  # util.getFileNameSuffix on the absolute link: after its last dot
            return href.rsplit(".", 1)[-1] if "." in href else ""

        comic_links = acquisitions("nebraska")
        self.assertEqual([(t, koreader_suffix(h)) for t, h in comic_links],
                         [("application/vnd.comicbook+zip", "cbz"), ("application/epub+zip", "epub"),
                          ("application/pdf", "pdf")],
                         "EPUB too: some reading apps (an iPhone one, live finding) open EPUB only")
        self.assertTrue(comic_links[0][1].endswith(
            "/book/nebraska/cbz/USS_Nebraska_Sanctum_Vol_01_Humanoids_Graphic_Novel_Xavier_Dorison_Christophe_Bec.cbz"))
        self.assertEqual([koreader_suffix(h) for _, h in acquisitions("book")], ["epub", "pdf", "epub"])
        self.assertIn("/book/book/bilingual-epub/", acquisitions("book")[2][1])
        self.assertTrue(acquisitions("book")[0][1].endswith("/%CE%9F_%CE%A6%CE%AC%CF%81%CE%BF%CF%82.epub"),
                        "a Greek title, encoded")

    def test_each_user_sees_only_their_own_books(self):
        users = {"u-admin": {"id": "u-admin", "username": "a", "role": "admin", "disabled": False},
                 "u-reader": {"id": "u-reader", "username": "r", "role": "user", "disabled": False}}
        jobs = [self._job("admins", "u-admin"), self._job("readers", "u-reader"), self._job("before-accounts", "")]
        self.assertEqual(self._titles("u-admin", users, jobs), ["admins", "before-accounts"])
        self.assertEqual(self._titles("u-reader", users, jobs), ["readers"])
        users["u-reader"]["disabled"] = True
        with self.assertRaises(Exception):
            self._titles("u-reader", users, jobs)


class ComicDownloadTests(unittest.TestCase):
    """A comic's CBZ renders every page (seconds to a minute on a small server): longer than an e-reader waits for a
    download to start. It is made in a child process (drawing a page holds Python's lock: in a thread of the server
    it stalled every request, downloads too, and KOReader stayed on "Downloading…"), once per file, and in advance
    when the catalogue is opened; a reader checking the file first (HEAD) waits for the one being made."""

    def setUp(self):
        import asyncio
        from starlette.requests import Request
        self.asyncio = asyncio
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.job = types.SimpleNamespace(job_id="comic1", owner="", mode="translate", status="done",
                                         target_lang="greek", source_lang="english", file_name="Nebraska.pdf",
                                         file_type="pdf", file_path="", layout_mode="comic", output_path=None,
                                         sample_range=None, reading_direction="ltr", updated_at=time.time())
        d = self.out / "comic1"
        d.mkdir()
        doc = fitz.open()
        for n in range(3):
            doc.new_page().insert_text((72, 72), f"Page {n + 1}")
        doc.save(str(d / "Nebraska_translated_greek.pdf"))
        doc.close()
        (d / "Nebraska_translated_greek.txt").write_text("Κείμενο.", encoding="utf-8")
        self.request = lambda method: Request({"type": "http", "method": method, "headers": [], "query_string": b"",
                                               "path": "/"})

    def tearDown(self):
        self.tmp.cleanup()

    def patches(self):
        from backend import main
        return (mock.patch.object(main, "OUTPUT_DIR", self.out), mock.patch.object(main, "get_job", return_value=self.job),
                mock.patch.object(main, "update_job"), mock.patch.object(main, "_validate_job_id"))

    def test_a_cbz_is_made_once_off_the_main_loop(self):
        from backend import main, comic_build
        from fastapi import HTTPException
        real, calls = comic_build.build_in_child, []

        def counted(*args, **kwargs):  # the real child process
            calls.append(args[2])
            return real(*args, **kwargs)

        async def scenario():
            out_dir, job, update, valid = self.patches()
            with out_dir, job, update, valid, mock.patch.object(comic_build, "build_in_child", counted):
                with self.assertRaises(HTTPException) as nothing:  # nothing made nor being made: as before
                    await main.download_output(self.request("HEAD"), "comic1", format="cbz")
                self.assertEqual(nothing.exception.status_code, 404)
                get = self.asyncio.ensure_future(main.download_output(self.request("GET"), "comic1", format="cbz"))
                await self.asyncio.sleep(0.05)
                ticks = 0
                head = self.asyncio.ensure_future(main.download_output(self.request("HEAD"), "comic1", format="cbz"))
                while not get.done():  # the loop runs while the pages are rendered
                    ticks += 1
                    await self.asyncio.sleep(0.02)
                first, checked = await get, await head
                again = await main.download_output(self.request("GET"), "comic1", format="cbz")
                return first, checked, again, ticks

        first, checked, again, ticks = self.asyncio.run(scenario())
        self.assertEqual(len(calls), 1, "made once for both requests")
        self.assertGreater(ticks, 3, "not on the main loop")
        self.assertEqual(Path(first.path).name, "Nebraska_translated_greek.cbz")
        self.assertEqual(checked.path, first.path, "the HEAD waited for the file being made")
        self.assertEqual(again.path, first.path)
        import zipfile
        with zipfile.ZipFile(first.path) as z:
            self.assertEqual(sorted(z.namelist()), ["page_0001.jpg", "page_0002.jpg", "page_0003.jpg"])

    def test_opening_the_catalogue_makes_the_cbz_in_advance(self):
        from backend.api import connections as api
        from backend import main
        with mock.patch.object(api, "OUTPUT_DIR", self.out):
            todo = api._comics_to_prepare([self.job])
            self.assertEqual([(s.name, f.name) for _, s, f in todo],
                             [("Nebraska_translated_greek.pdf", "Nebraska_translated_greek.epub"),
                              ("Nebraska_translated_greek.pdf", "Nebraska_translated_greek.cbz")], "EPUB first")
            self.asyncio.run(api._prepare_comics(todo))
            self.assertTrue((self.out / "comic1" / "Nebraska_translated_greek.cbz").is_file())
            import zipfile
            with zipfile.ZipFile(self.out / "comic1" / "Nebraska_translated_greek.epub") as z:
                self.assertEqual(z.read("mimetype"), b"application/epub+zip")
                self.assertEqual(len([n for n in z.namelist() if n.endswith(".jpg")]), 3, "a picture per page")
            self.assertEqual(api._comics_to_prepare([self.job]), [], "made: nothing more to do")
            book = types.SimpleNamespace(**{**vars(self.job), "layout_mode": "standard", "job_id": "book1"})
            self.assertEqual(api._comics_to_prepare([book]), [], "only comics")
            pdf = self.out / "comic1" / "Nebraska_translated_greek.pdf"
            os.utime(pdf, (time.time() + 60, time.time() + 60))
            self.assertEqual(len(api._comics_to_prepare([self.job])), 2, "a newer translation: both made again")
        self.assertEqual(main._FILE_BUILDS, {}, "no build left behind")

    def test_the_server_keeps_answering_while_a_comic_is_made(self):
        """In a thread, each page drawn stopped the main loop for its whole time (0.28 s here, more on a small
        server); in a child process the loop keeps its pace."""
        from backend import main
        d = self.out / "comic1"
        ComicPageSizeTests.make_pdf(d / "Nebraska_translated_greek.pdf", [(2000, 3000, 72)] * 4, detail=True)

        async def scenario():
            out_dir, job, update, valid = self.patches()
            with out_dir, job, update, valid:
                build = self.asyncio.ensure_future(main.download_output(self.request("GET"), "comic1", format="epub"))
                worst = 0.0
                while not build.done():
                    t = time.perf_counter()
                    await self.asyncio.sleep(0.01)
                    worst = max(worst, time.perf_counter() - t - 0.01)
                return await build, worst

        served, worst = self.asyncio.run(scenario())
        self.assertEqual(Path(served.path).name, "Nebraska_translated_greek.epub")
        self.assertLess(worst, 0.12, f"the main loop stalled {worst:.2f} s while the pages were drawn")

    def test_a_file_made_too_large_before_is_made_again(self):
        """Pages used to be rendered at 150 dpi of a page sized by the scan's pixels: 3107x4775 px or more, an EPUB
        of 600 MB or more that an e-reader never finished downloading (live). Such a file is made again."""
        import io
        import zipfile
        from PIL import Image
        from backend import main, exporter
        from backend.api import connections as api
        d = self.out / "comic1"
        old = d / "Nebraska_translated_greek.epub"
        img = io.BytesIO()
        Image.new("RGB", (3107, 40), (255, 255, 255)).save(img, "JPEG")
        with zipfile.ZipFile(old, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            z.writestr("EPUB/images/page_0001.jpg", img.getvalue())
        os.utime(old, (time.time() + 60, time.time() + 60))  # newer than the translation: only its size is wrong
        self.assertTrue(exporter.comic_file_outdated(old))
        with mock.patch.object(api, "OUTPUT_DIR", self.out):
            self.assertIn("Nebraska_translated_greek.epub", [f.name for _, _, f in api._comics_to_prepare([self.job])])

        async def download():
            out_dir, job, update, valid = self.patches()
            with out_dir, job, update, valid:
                return await main.download_output(self.request("GET"), "comic1", format="epub")

        served = self.asyncio.run(download())
        self.assertEqual(Path(served.path), old, "made again under its own name")
        self.assertFalse(exporter.comic_file_outdated(old))
        with zipfile.ZipFile(old) as z:
            self.assertEqual(len([n for n in z.namelist() if n.endswith(".jpg")]), 3)
        (d / "broken.cbz").write_bytes(b"not a zip")
        self.assertTrue(exporter.comic_file_outdated(d / "broken.cbz"), "a file that cannot be read is made again")
        self.assertFalse(exporter.comic_file_outdated(d / "Nebraska_translated_greek.pdf"))


class ComicPageSizeTests(unittest.TestCase):
    """A comic's CBZ / EPUB pages keep their scan's own resolution (1600-2560 px on the long side), whatever
    resolution the scan says it has; a page with no picture is rendered at 150 dpi as before."""

    @staticmethod
    def make_pdf(path, scans, detail=False):
        import io
        from PIL import Image, ImageDraw
        doc = fitz.open()
        for w, h, dpi in scans:  # as the comic translator builds a PDF from a CBZ's images
            buf = io.BytesIO()
            img = Image.new("RGB", (w, h), (200, 180, 160))
            if detail:  # line art, as slow to draw and to compress as a real page
                draw = ImageDraw.Draw(img)
                for k in range(0, w, 23):
                    draw.line([(k, 0), (w - k, h)], fill=((k * 7) % 255, (k * 3) % 255, (k * 5) % 255), width=3)
            img.save(buf, "JPEG", **({"dpi": (dpi, dpi)} if dpi else {}))
            with fitz.open("jpg", buf.getvalue()) as img_doc:
                pdf_bytes = img_doc.convert_to_pdf()
            with fitz.open("pdf", pdf_bytes) as page_pdf:
                r = page_pdf[0].rect
                doc.new_page(width=r.width, height=r.height).show_pdf_page(r, page_pdf, 0)
        doc.new_page(width=612, height=792).insert_text((72, 72), "Vector art only")
        doc.save(str(path))
        doc.close()

    def test_pages_keep_their_scan_resolution(self):
        import zipfile
        from PIL import Image
        from backend import exporter
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "Comic_translated_greek.pdf"
            self.make_pdf(pdf, [(1800, 2800, 72), (1200, 1800, 300), (600, 900, 72), (1988, 3056, None)])
            cbz = exporter.export_comic_archive(pdf, Path(td) / "c.cbz", format="cbz")
            epub = exporter.export_comic_epub(pdf, Path(td) / "c.epub", title="Comic")
            for archive in (cbz, epub):
                with zipfile.ZipFile(archive) as z:
                    names = sorted(n for n in z.namelist() if n.endswith(".jpg"))
                    sizes = []
                    for n in names:
                        with z.open(n) as f, Image.open(f) as im:
                            sizes.append(max(im.size))
                self.assertEqual(len(sizes), 5, archive)
                self.assertEqual(sizes[0], 2560, "a large scan tagged 72 dpi: at most 2560, not 5833")
                self.assertAlmostEqual(sizes[1], 1800, delta=2, msg="a scan tagged 300 dpi: its own 1800, not 900")
                self.assertEqual(sizes[2], 1600, "a small scan: enlarged so its balloons stay readable")
                self.assertEqual(sizes[3], 2560, "an untagged scan: at most 2560, not 4775")
                self.assertAlmostEqual(sizes[4], 1650, delta=2, msg="vector art: 150 dpi, as before")
                self.assertFalse(exporter.comic_file_outdated(archive))
            self.assertLess(Path(epub).stat().st_size, 6_000_000)

    def test_an_epub_is_complete_or_not_there(self):
        from backend import exporter
        from ebooklib import epub as ebooklib_epub
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "Comic_translated_greek.pdf"
            self.make_pdf(pdf, [(600, 900, 72)])
            target = Path(td) / "Comic_translated_greek.epub"

            def cut_short(name, book, options):  # a restart in the middle of writing
                Path(name).write_bytes(b"PK\x03\x04 half")
                raise OSError("stopped")

            with mock.patch.object(ebooklib_epub, "write_epub", cut_short):
                with self.assertRaises(OSError):
                    exporter.export_comic_epub(pdf, target)
            self.assertEqual(list(Path(td).iterdir()), [pdf], "no broken EPUB, no part file left")
            exporter.export_comic_epub(pdf, target)
            self.assertTrue(target.is_file())


class ReadAlongTests(unittest.TestCase):
    def test_sentence_times(self):
        from backend.tts_engine import compute_read_along
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.mp3"
            b = Path(td) / "b.mp3"
            a.write_bytes(b"\x00" * 6000)    # 1 s at 48 kbit/s (an unreadable header: timed from its size)
            b.write_bytes(b"\x00" * 12000)   # 2 s
            segs = compute_read_along([
                ("=== PAGE 1 ===\nFirst sentence here. Second one!\n\nA new paragraph.", str(a)),
                ("«Πού πάμε;» ρώτησε. Τέλος.", str(b)),
            ])
        self.assertEqual([s["t"] for s in segs], ["First sentence here.", "Second one!", "A new paragraph.",
                                                  "«Πού πάμε;» ρώτησε.", "Τέλος."])
        self.assertEqual([s["p"] for s in segs], [1, 0, 1, 1, 0])
        self.assertEqual(segs[0]["s"], 0)
        self.assertEqual(segs[3]["s"], 1000, "the second part starts where the first one ends")
        self.assertEqual(segs[-1]["e"], 3000)
        for prev, cur in zip(segs, segs[1:]):
            self.assertEqual(prev["e"], cur["s"])
        self.assertGreater(segs[0]["e"] - segs[0]["s"], segs[1]["e"] - segs[1]["s"], "a longer sentence lasts longer")


# ---------------------------------------------------------------------------
# Through the sandbox server
# ---------------------------------------------------------------------------

def _post_file(filepath: Path, filename: str) -> dict:
    boundary = "----BilingualOpdsBoundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + filepath.read_bytes() + \
        f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _request(url: str, data: dict = None, method: str = None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, resp.headers, resp.read()


def _translated_job(tmp: Path, name: str) -> str:
    pdf = tmp / "book.pdf"
    doc = fitz.open()
    pages = [  # different on every page: lines repeated on each page are running headers to the parser
        "The lighthouse keeper looked at the sea.\n\nNothing moved on the water that morning.",
        "By noon the wind had turned to the north.\n\nHe climbed the stairs to light the lamp early.",
        "The storm reached the island at dusk.\n\nAll night the beam swept over the waves.",
    ]
    for text in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(60, 60, 535, 780), text, fontsize=11)
    doc.save(str(pdf))
    doc.close()
    job_id = _post_file(pdf, name)["job_id"]
    _request(f"{API}/translate", {"job_id": job_id, "source_lang": "english", "target_lang": "greek",
                                  "output_format": "pdf", "ai_polish": False})
    deadline = time.time() + 90
    while time.time() < deadline:
        info = json.loads(_request(f"{API}/status/{job_id}")[2])
        if info["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert info["status"] == "done", {k: info.get(k) for k in ("error", "current_step", "file_type", "total_pages")}
    return job_id


class ApiTests(unittest.TestCase):
    """Against the sandbox server that run_all_tests.py starts."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.job_id = _translated_job(Path(cls.tmp.name), "lighthouse.pdf")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_bilingual_download(self):
        status, headers, body = _request(f"{API}/download/{self.job_id}/bilingual?format=pdf")
        self.assertEqual(status, 200)
        self.assertIn("lighthouse_bilingual.pdf", headers.get("content-disposition", ""))
        with fitz.open("pdf", body) as doc:
            text = "".join(p.get_text() for p in doc)
        self.assertIn("The lighthouse keeper looked at the sea.", text)
        self.assertRegex(text, "[α-ω]{3,}", "the translation is there too")
        for fmt in ("docx", "epub"):
            self.assertEqual(_request(f"{API}/download/{self.job_id}/bilingual?format={fmt}")[0], 200)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _request(f"{API}/download/{self.job_id}/bilingual?format=txt")
        self.assertEqual(ctx.exception.code, 400)
        fresh = _post_file(Path(self.tmp.name) / "book.pdf", "untranslated.pdf")["job_id"]
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _request(f"{API}/download/{fresh}/bilingual?format=pdf")
        self.assertEqual(ctx.exception.code, 404)
        # the status says whether a translation exists (History opens a narrated translation in the Translation tab)
        self.assertTrue(json.loads(_request(f"{API}/status/{self.job_id}")[2])["has_translation"])
        self.assertFalse(json.loads(_request(f"{API}/status/{fresh}")[2])["has_translation"])

    def test_opds_catalogue(self):
        _, _, raw = _request(f"{API}/connections/opds", {})
        path = json.loads(raw)["path"]
        self.assertRegex(path, r"^/opds/[A-Za-z0-9_-]{20,}/$")
        status, headers, feed = _request(ROOT + path)
        self.assertEqual(status, 200)
        self.assertIn("application/atom+xml", headers.get("content-type", ""))
        root = ET.fromstring(feed)
        entry = next(e for e in root.findall(f"{ATOM}entry") if e.findtext(f"{ATOM}id") == f"urn:uuid:{self.job_id}")
        self.assertEqual(entry.findtext(f"{ATOM}title"), "lighthouse")
        links = {l.get("type") + "|" + (l.get("title") or ""): l.get("href") for l in entry.findall(f"{ATOM}link")
                 if l.get("rel") == "http://opds-spec.org/acquisition"}
        self.assertIn("application/epub+zip|EPUB", links)
        self.assertIn("application/pdf|PDF", links)
        self.assertTrue(links["application/epub+zip|EPUB"].endswith("/epub/lighthouse.epub"), links)
        self.assertTrue(links["application/pdf|PDF"].endswith("/pdf/lighthouse.pdf"), links)
        epub_status, epub_headers, epub_body = _request(ROOT + links["application/epub+zip|EPUB"])
        self.assertEqual(epub_status, 200)
        self.assertTrue(epub_body.startswith(b"PK"), "an EPUB is a ZIP file")
        old_style = _request(ROOT + path + f"book/{self.job_id}/epub")  # a link of an earlier version
        self.assertEqual(old_style[0], 200)
        self.assertTrue(old_style[2].startswith(b"PK"))
        bilingual_link = next(h for k, h in links.items() if "Bilingual" in k)
        self.assertEqual(_request(ROOT + bilingual_link)[0], 200)
        status_info = json.loads(_request(f"{API}/connections")[2])
        self.assertTrue(status_info["opds"]["exists"])
        for bad in (ROOT + "/opds/not-a-real-token/", ROOT + path + f"book/{self.job_id}/cbz"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                _request(bad)
            self.assertEqual(ctx.exception.code, 404, bad)
        _request(f"{API}/connections/opds", method="DELETE")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _request(ROOT + path)
        self.assertEqual(ctx.exception.code, 404, "a removed link stops working")

    def test_read_along_endpoint(self):
        from backend.api.common import OUTPUT_DIR
        out_dir = OUTPUT_DIR / self.job_id
        audio = out_dir / "lighthouse_audiobook_greek.mp3"
        sync = audio.with_suffix(".sync.json")
        audio.write_bytes(b"\x00" * 1000)
        sync.write_text(json.dumps({"version": 1, "segments": [{"s": 0, "e": 900, "t": "Ένα.", "p": 1}]}),
                        encoding="utf-8")
        try:
            segs = json.loads(_request(f"{API}/jobs/{self.job_id}/read-along")[2])["segments"]
            self.assertEqual(segs[0]["t"], "Ένα.")
            later = time.time() + 120
            os.utime(audio, (later, later))  # a newer recording: the old times no longer fit it
            self.assertEqual(json.loads(_request(f"{API}/jobs/{self.job_id}/read-along")[2])["segments"], [])
        finally:
            audio.unlink(missing_ok=True)
            sync.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
