"""
test_data_safety_and_preservation.py - Regression guards for five fixed bugs:
1. Startup cleanup deleted user jobs (names like book*/test_*, and anything older than 24 hours / 7 days).
2. Editor, AI Polish, cover changes, layout downloads and /api/refine rebuilt format-preserved DOCX/EPUB/comics from text.
3. The web UI never sent quota_behavior='wait' for audiobooks.
4. "M4B" was a renamed MP3 without ffmpeg (and, with cover + chapters, even with ffmpeg).
5. Unvalidated request fields: stored XSS in the batch queue and path traversal through language names.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import docx
from docx.shared import RGBColor
from ebooklib import epub
from fastapi import HTTPException
from PIL import Image

from backend import database, format_preserver, format_sync, job_manager, main, storage_cleaner, tts_engine
from backend.exporter import export_text

MP3_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 413
NODE_SETUP = "const escHtml = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;');\n"


def run(coro):
    return asyncio.run(coro)


def jpeg(color=(200, 20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 120), color).save(buf, "JPEG")
    return buf.getvalue()


async def upper_case(units):
    return [u.upper() for u in units]


def make_docx(path: Path) -> None:
    d = docx.Document()
    d.core_properties.comments = "author's own document"
    d.add_heading("The harbour", 1)
    p = d.add_paragraph()
    p.add_run("The captain ")
    bold = p.add_run("never slept")
    bold.bold = True
    bold.font.color.rgb = RGBColor(0xC0, 0x10, 0x10)
    p.add_run(" during storms.")
    d.add_paragraph("A second paragraph, with detail.")
    d.add_picture(io.BytesIO(jpeg()))
    table = d.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "Left cell"
    table.cell(0, 1).text = "Right cell"
    d.add_paragraph("The last paragraph.")
    d.save(str(path))


def make_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("original-id")
    book.set_title("Harbour")
    book.set_language("en")
    ch = epub.EpubHtml(title="One", file_name="one.xhtml")
    ch.content = ('<h1 id="top">The harbour</h1><p class="lead">The captain <em>never slept</em> during storms.</p>'
                  '<p>A second paragraph, with detail.</p><ul><li>Left item</li><li>Right item</li></ul>'
                  '<p>The last paragraph.</p>')
    book.add_item(ch)
    book.add_item(epub.EpubItem(uid="css", file_name="book.css", media_type="text/css", content=b"p.lead{color:red}"))
    book.add_item(epub.EpubItem(uid="img", file_name="pic.jpg", media_type="image/jpeg", content=jpeg()))
    book.toc = (ch,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [ch]
    epub.write_epub(str(path), book, {})


def docx_text(path: Path) -> str:
    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for r in t.rows:
            parts.extend(c.text for c in r.cells)
    return "\n".join(parts)


def epub_text(path: Path) -> str:
    from bs4 import BeautifulSoup
    with zipfile.ZipFile(path) as z:
        return BeautifulSoup(z.read("EPUB/one.xhtml"), "xml").get_text()


class JobCase(unittest.TestCase):

    def setUp(self):
        self.jobs = []

    def tearDown(self):
        for jid in self.jobs:
            run(main.delete_job(jid))

    def new_job(self, name="novel.pdf", kind="pdf", **fields):
        job = job_manager.create_job("", name, kind)
        self.jobs.append(job.job_id)
        up = main.UPLOAD_DIR / job.job_id
        up.mkdir(parents=True, exist_ok=True)
        src = up / name
        src.write_bytes(b"x")
        job_manager.update_job(job.job_id, file_path=str(src), **fields)
        out = main.OUTPUT_DIR / job.job_id
        out.mkdir(parents=True, exist_ok=True)
        return job, src, out

    def translated(self, kind="docx", marked=True):
        job, src, out = self.new_job(f"harbour.{kind}", kind, status="done", output_format=kind, target_lang="greek",
                                     layout_mode="standard")
        doc = out / f"harbour_translated_greek.{kind}"
        (make_docx if kind == "docx" else make_epub)(src)
        translate = format_preserver.translate_docx_in_place if kind == "docx" else format_preserver.translate_epub_in_place
        text = run(translate(str(src), str(doc), "greek", "english", segment_translator=upper_case))
        txt = out / "harbour_translated_greek.txt"
        txt.write_text(text, encoding="utf-8")
        if marked:
            format_sync.mark_output(doc, True)
        job_manager.update_job(job.job_id, output_path=str(doc))
        return job, out, txt, doc, text

    def save(self, job, text):
        return run(main.update_job_text(job.job_id, main.UpdateTextRequest(translated_text=text)))

    def download(self, job, fmt, layout=None):
        req = mock.Mock(method="GET")
        return run(main.download_output(req, job.job_id, format=fmt, layout=layout))


class TestNoDataLossOnRestart(JobCase):

    NAMES = ("Bookkeeping.pdf", "book.pdf", "test_results.docx", "temp_notes.epub", "path_to_freedom.pdf")

    def test_startup_keeps_old_and_test_like_named_jobs(self):
        long_ago = time.time() - 90 * 86400
        created = []
        for name in self.NAMES:
            job, src, out = self.new_job(name, status="done", created_at=long_ago)
            result = out / "result.pdf"
            result.write_bytes(b"result")
            for p in (src.parent, out):
                os.utime(p, (long_ago, long_ago))
            created.append((job.job_id, src, result))
            job_manager._jobs.pop(job.job_id)  # as after a process restart

        with mock.patch.dict(os.environ, {"BOOKAPP_TEST_MODE": "0"}):
            job_manager.cleanup_old_jobs()
            self.assertEqual(job_manager.cleanup_test_jobs(), [])
            self.assertEqual(database.db_delete_test_jobs(), [])
            listed = {j["job_id"] for j in run(main.all_jobs())}
        for jid, src, result in created:
            self.assertIn(jid, listed)
            self.assertIsNotNone(database.db_get_job(jid))
            self.assertTrue(src.exists() and result.exists(), f"files of {src.name} were deleted")

    def test_cleaner_keeps_unrecorded_outputs_and_fails_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            recovered, empty, upload = root / "outputs" / "lost", root / "outputs" / "empty", root / "uploads" / "orphan"
            for d in (recovered, empty, upload):
                d.mkdir(parents=True)
            (recovered / "x.epub").write_bytes(b"work")
            old = time.time() - 60 * 86400
            for d in (recovered, empty, upload):
                os.utime(d, (old, old))
            with mock.patch.object(storage_cleaner, "TEMP_DIR", root):
                with mock.patch.object(storage_cleaner, "_known_job_ids", return_value=None):
                    storage_cleaner.clean_temp_storage(24)
                    self.assertTrue(empty.exists() and upload.exists(), "deleted although the job list was unknown")
                storage_cleaner.clean_temp_storage(24)
            self.assertTrue((recovered / "x.epub").exists(), "recoverable output deleted")
            self.assertFalse(empty.exists() or upload.exists(), "true orphans should still be removed")

    def test_history_is_not_limited_to_100_jobs(self):
        ids = [self.new_job(f"novel{i}.pdf")[0].job_id for i in range(105)]
        for jid in ids:
            job_manager._jobs.pop(jid)
        self.assertTrue(set(ids) <= {j.job_id for j in job_manager.list_jobs()})


class TestFormattingPreserved(JobCase):

    def test_docx_edit_keeps_runs_table_and_image(self):
        job, _out, txt, doc, text = self.translated("docx")
        new = text.replace("NEVER SLEPT", "RARELY SLEPT").replace("RIGHT CELL", "EAST CELL")
        self.assertEqual(self.save(job, new)["updated_in_place"], [doc.name])
        d = docx.Document(str(doc))
        runs = d.paragraphs[1].runs
        self.assertEqual([r.text for r in runs], ["THE CAPTAIN ", "RARELY SLEPT", " DURING STORMS."])
        self.assertTrue(runs[1].bold)
        self.assertEqual(str(runs[1].font.color.rgb), "C01010")
        self.assertEqual(d.paragraphs[0].style.name, "Heading 1")
        self.assertEqual(d.tables[0].style.name, "Table Grid")
        self.assertEqual(d.tables[0].cell(0, 1).text, "EAST CELL")
        self.assertEqual(len(d.inline_shapes), 1)
        self.assertEqual(txt.read_text(encoding="utf-8"), new)

    def test_docx_paragraphs_added_and_removed(self):
        job, _out, _txt, doc, text = self.translated("docx")
        p = text.split("\n\n")
        p[1:1] = ["BODY UNDER THE TITLE."]
        p.remove("A SECOND PARAGRAPH, WITH DETAIL.")
        self.save(job, "\n\n".join(p))
        d = docx.Document(str(doc))
        self.assertEqual(d.paragraphs[1].text, "BODY UNDER THE TITLE.")
        self.assertNotIn("Heading", d.paragraphs[1].style.name)
        self.assertNotIn("SECOND PARAGRAPH", docx_text(doc))
        self.assertEqual(len(d.inline_shapes), 1)

    def test_docx_text_appended_after_table_goes_to_body_and_stays_editable(self):
        job, _out, _txt, doc, text = self.translated("docx")
        steps = [text + "\n\nAN AFTERWORD."]
        steps.append(steps[-1].replace("AN AFTERWORD", "THE AFTERWORD"))
        steps.append(steps[-1] + "\n\nAND A POSTSCRIPT.")
        steps.append(steps[-1].replace("RIGHT CELL", "EAST CELL"))
        for step in steps:
            self.save(job, step)
        d = docx.Document(str(doc))
        self.assertEqual([p.text for p in d.paragraphs[-2:]], ["THE AFTERWORD.", "AND A POSTSCRIPT."])
        self.assertEqual([c.text for c in d.tables[0].rows[0].cells], ["LEFT CELL", "EAST CELL"])

    def test_epub_edit_keeps_markup_css_and_images(self):
        job, _out, _txt, doc, text = self.translated("epub")
        with zipfile.ZipFile(doc) as z:
            before = {n: z.read(n) for n in z.namelist()}
        self.save(job, text.replace("NEVER SLEPT", "RARELY SLEPT"))
        with zipfile.ZipFile(doc) as z:
            self.assertEqual(z.infolist()[0].filename, "mimetype")
            self.assertEqual(z.infolist()[0].compress_type, zipfile.ZIP_STORED)
            after = {n: z.read(n) for n in z.namelist()}
        self.assertEqual([n for n in before if before[n] != after[n]], ["EPUB/one.xhtml"])
        page = after["EPUB/one.xhtml"].decode("utf-8")
        self.assertIn("<em>RARELY SLEPT</em>", page)
        self.assertIn('class="lead"', page)
        self.assertEqual(page.count("<?xml"), 1)
        epub.read_epub(str(doc))

    def test_successive_random_edits_stay_in_sync(self):
        key = lambda s: "".join(s.split())
        for kind, reader in (("docx", docx_text), ("epub", epub_text)):
            for seed in range(40):
                rng = random.Random(seed)
                job, _out, txt, doc, text = self.translated(kind)
                for step in range(4):
                    paras = format_sync.split_paragraphs(text)
                    i = rng.randrange(1, len(paras) - (2 if kind == "epub" else 0))  # EPUB: last 2 are navigation
                    words = paras[i].split()
                    action = rng.choice(("word", "append", "drop", "insert") if len(paras) > 3 else ("word", "append"))
                    marker = f"NEW{seed}X{step}"
                    if action == "word":
                        words[rng.randrange(len(words))] = marker
                        paras[i] = " ".join(words)
                    elif action == "append":
                        paras[i] += " " + marker
                    elif action == "drop":
                        paras.pop(i)
                    else:
                        paras.insert(i + (rng.random() < 0.3), marker + " INSERTED.")
                    new = "\n\n".join(paras)
                    try:
                        self.save(job, new)
                    except HTTPException as e:
                        self.assertEqual(e.status_code, 409)  # a refusal must leave the text untouched
                        self.assertEqual(format_sync.split_paragraphs(txt.read_text(encoding="utf-8")),
                                         format_sync.split_paragraphs(text))
                        self.fail(f"{kind} seed {seed} step {step}: ordinary {action} edit was refused")
                    text = new
                    content = key(reader(doc))
                    for p in (paras[:-2] if kind == "epub" else paras):
                        self.assertIn(key(p), content, f"{kind} seed {seed} step {step} ({action})")

    def test_edit_that_cannot_be_placed_changes_nothing(self):
        job, _out, txt, doc, text = self.translated("docx")
        txt.write_text(text.replace("THE LAST", "A DRIFTED"), encoding="utf-8")
        before = (txt.read_bytes(), doc.read_bytes())
        with self.assertRaises(HTTPException) as err:
            self.save(job, text.replace("THE LAST", "THE FINAL"))
        self.assertEqual(err.exception.status_code, 409)
        self.assertEqual((txt.read_bytes(), doc.read_bytes()), before)

    def test_epub_navigation_entries_do_not_block_edits(self):
        job, _out, txt, doc, text = self.translated("epub")
        new = "\n\n".join(p + "!" for p in format_sync.split_paragraphs(text)) + "\n\nAN AFTERWORD."
        self.save(job, new)
        self.assertIn("THE LAST PARAGRAPH.!", epub_text(doc))
        self.assertIn("AN AFTERWORD.", epub_text(doc))
        self.assertEqual(txt.read_text(encoding="utf-8"), new)

    def test_cover_changes_do_not_rebuild_document(self):
        for kind in ("docx", "epub"):
            job, _out, _txt, doc, _text = self.translated(kind)
            before = doc.read_bytes()

            class Upload:
                async def read(self):
                    return jpeg((1, 2, 250))

            self.assertIn(doc.name, run(main.upload_cover_image(job.job_id, Upload()))["preserved_files"])
            self.assertEqual(doc.read_bytes(), before)
            run(main.delete_cover_image(job.job_id))
            self.assertEqual(doc.read_bytes(), before)

    def test_layout_change_download_serves_preserved_file(self):
        job, _out, _txt, doc, _text = self.translated("docx")
        before = doc.read_bytes()
        for fmt in ("docx", "doc"):
            self.assertEqual(Path(self.download(job, fmt, "literature").path), doc)
        self.assertEqual(doc.read_bytes(), before)

    def test_ai_polish_patches_document_in_place(self):
        job, _out, _txt, doc, text = self.translated("docx")

        async def fake_polish(**_kw):
            return text.replace("NEVER SLEPT", "HARDLY SLEPT")

        with mock.patch("backend.ai_polisher.polish_text_with_gemini", fake_polish):
            run(main.polish_translation(main.PolishRequest(job_id=job.job_id, bilingual_mode=False, final_refinement=False)))
        d = docx.Document(str(doc))
        self.assertIn("HARDLY SLEPT", docx_text(doc))
        self.assertTrue(d.paragraphs[1].runs[1].bold)
        self.assertEqual(len(d.inline_shapes), 1)

    def test_refine_never_reexports_preserved_output(self):
        from backend.api.refine import _job_output_is_reexportable
        job, _out, txt, _doc, _text = self.translated("docx")
        job_manager.update_job(job.job_id, ai_polish=True, output_format="pdf")
        self.assertFalse(_job_output_is_reexportable(job_manager.get_job(job.job_id), txt))

    def test_outputs_from_before_the_marker_are_recognised(self):
        for kind in ("docx", "epub"):
            job, out, _txt, doc, _text = self.translated(kind, marked=False)
            self.assertEqual(format_sync.protected_files(job_manager.get_job(job.job_id), out), {doc})
            export_text("Plain regenerated text.", out, kind, doc.stem)
            self.assertEqual(format_sync.protected_files(job_manager.get_job(job.job_id), out), set())

    def test_document_generated_from_python_docx_upload_stays_editable(self):
        job, src, out = self.new_job("plain.docx", "docx", status="done", output_format="docx", target_lang="greek")
        d = docx.Document()
        d.add_paragraph("Written by python-docx.")
        d.save(str(src))
        self.save(job, "=== PAGE 1 ===\nFirst version.")
        self.save(job, "=== PAGE 1 ===\nSecond version.")
        self.assertIn("Second version.", docx_text(out / "plain_translated_greek.docx"))

    def test_refine_keeps_text_in_sync_when_last_download_was_txt(self):
        from backend import output_refiner
        with tempfile.TemporaryDirectory() as td:
            txt = Path(td) / "x_translated_greek.txt"
            txt.write_text("Και και τότε , έφυγε.", encoding="utf-8")
            before = txt.read_bytes()
            run(output_refiner.refine_translation_output("sync", str(txt), str(txt), output_format="txt",
                                                         enabled=True, allow_reexport=False))
            self.assertEqual(txt.read_bytes(), before)

    def test_generated_documents_are_still_reexported(self):
        job, _src, out = self.new_job("novel.pdf", status="done", output_format="docx", target_lang="greek")
        (out / "novel_translated_greek.txt").write_text("Old words.", encoding="utf-8")
        doc = export_text("Old words.", out, "docx", "novel_translated_greek")
        self.save(job, "New words.")
        self.assertIn("New words.", docx_text(doc))

    def test_comic_artwork_survives_editor_and_cover(self):
        job, _src, out = self.new_job("comic.cbz", "cbz", status="done", output_format="pdf", layout_mode="comic")
        art = out / "comic_translated_greek.pdf"
        art.write_bytes(b"%PDF artwork")
        (out / "comic_translated_greek.txt").write_text("HELLO", encoding="utf-8")
        self.assertTrue(self.save(job, "HELLO THERE")["artwork_unchanged"])

        class Upload:
            async def read(self):
                return jpeg()

        run(main.upload_cover_image(job.job_id, Upload()))
        self.assertEqual(art.read_bytes(), b"%PDF artwork")


def js_slice(start: str, end: str) -> str:
    src = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    a = src.index(start)
    return src[a:src.index(end, a)]


def node(script: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "case.js"
        f.write_text(script, encoding="utf-8")
        res = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    if res.returncode:
        raise AssertionError(res.stderr)
    return res.stdout


class TestAudiobookWaitForReset(unittest.TestCase):

    def sent(self, has_key: bool, choice: str) -> str:
        return node(
            "const el = () => ({ value: '0', style: {}, classList: { remove() {}, add() {} }, checked: false });\n"
            "const els = { 'ab-narration-style': { value: 'literature:-12%' } };\n"
            "global.document = { getElementById: id => els[id] || el(),\n"
            f"  querySelector: () => ({{ value: '{choice}' }}) }};\n"
            "const state = { ab: { jobId: 'j1' }, selectedVoice: 'v' };\n"
            "const API = '/api', currentAppMode = 'advanced';\n"
            "const getClientApiKey = () => null;\n"
            f"const hasGeminiKey = () => {str(has_key).lower()};\n"
            "const setStatusBadge = () => {}, connectSSE = () => {}, toast = () => {};\n"
            "const showError = (p, m) => { throw new Error(m); };\n"
            "global.fetch = async (u, o) => { console.log(JSON.parse(o.body).quota_behavior); return { ok: true }; };\n"
            + js_slice("async function startAudiobook", "// ── SSE Progress Stream")
            + "\nstartAudiobook();"
        ).strip()

    def test_wait_is_sent_when_a_key_is_stored(self):
        self.assertEqual(self.sent(True, "wait"), "wait")
        self.assertEqual(self.sent(True, "fallback"), "fallback")
        self.assertEqual(self.sent(False, "wait"), "fallback")


class TestRealM4B(JobCase):

    def test_real_container_with_cover_and_chapters(self):
        from mutagen.mp4 import MP4
        with tempfile.TemporaryDirectory() as td:
            mp3, cover, m4b = Path(td) / "a.mp3", Path(td) / "cover.jpg", Path(td) / "a.m4b"
            mp3.write_bytes(MP3_FRAME * 400)
            cover.write_bytes(jpeg())
            chapters = [{"start_ms": 0, "title": "Αρχή", "end_ms": 5000}, {"start_ms": 5000, "title": "Τέλος", "end_ms": 10000}]
            run(tts_engine.export_audiobook_m4b(str(mp3), str(m4b), title="Λιμάνι", cover_image_path=str(cover), chapters=chapters))
            self.assertTrue(tts_engine.is_mp4_file(m4b))
            info = MP4(str(m4b))
            self.assertTrue(info.info.codec.startswith("mp4a"))
            self.assertEqual([c.title for c in info.chapters], ["Αρχή", "Τέλος"])
            self.assertTrue(info.tags.get("covr"))
            self.assertEqual(sorted(p.name for p in Path(td).iterdir()), ["a.m4b", "a.mp3", "cover.jpg"])

    def test_unreadable_cover_does_not_lose_audiobook(self):
        with tempfile.TemporaryDirectory() as td:
            mp3, cover, m4b = Path(td) / "a.mp3", Path(td) / "cover.jpg", Path(td) / "a.m4b"
            mp3.write_bytes(MP3_FRAME * 50)
            cover.write_bytes(b"not an image")
            run(tts_engine.export_audiobook_m4b(str(mp3), str(m4b), cover_image_path=str(cover)))
            self.assertTrue(tts_engine.is_mp4_file(m4b))

    def test_without_ffmpeg_fails_honestly(self):
        job, _src, out = self.new_job(status="done")
        (out / "a.mp3").write_bytes(MP3_FRAME * 50)
        with mock.patch.object(tts_engine, "find_ffmpeg", return_value=None):
            with self.assertRaises(HTTPException) as err:
                self.download(job, "m4b")
        self.assertEqual(err.exception.status_code, 501)
        self.assertEqual(list(out.glob("*.m4b")), [])

    def test_fake_m4b_from_older_versions_is_replaced(self):
        job, _src, out = self.new_job(status="done")
        (out / "a.mp3").write_bytes(MP3_FRAME * 50)
        (out / "a.m4b").write_bytes(MP3_FRAME * 50)
        self.assertTrue(tts_engine.is_mp4_file(self.download(job, "m4b").path))


class TestInputValidationAndEscaping(JobCase):

    EVIL = '<img src=x onerror=alert(1)>'

    def rejected(self, coro):
        with self.assertRaises(HTTPException) as err:
            run(coro)
        self.assertEqual(err.exception.status_code, 400)

    def test_queue_rejects_bad_fields(self):
        job = self.new_job()[0]
        for field in ("output_format", "layout_mode", "reading_direction", "quota_behavior", "target_lang", "source_lang"):
            self.rejected(main.add_batch_queue_item(main.QueueAddRequest(job_id=job.job_id, **{field: self.EVIL})))
            self.rejected(main.start_batch_queue(main.QueueStartRequest(**{field: self.EVIL})))

    def test_languages_cannot_escape_the_output_folder(self):
        from backend.api import insights
        job = self.new_job()[0]
        for bad in ("../../../../evil", "x/../../evil", "..\\..\\evil", "greek\x00"):
            self.rejected(main.start_translation(
                main.TranslateRequest(job_id=job.job_id, source_lang="english", target_lang=bad), mock.Mock()))
            self.rejected(main.start_audiobook(
                main.AudiobookRequest(job_id=job.job_id, language=bad, voice_name="v"), mock.Mock()))
            self.rejected(insights.insights_export(insights.InsightsExportRequest(
                job_id=job.job_id, insight_type="short_summary", language=bad, format="txt")))
            self.rejected(insights.insights_audio(insights.InsightsAudioRequest(
                job_id=job.job_id, insight_type="short_summary", language=bad)))

    def test_layout_is_validated_wherever_it_is_stored(self):
        job = self.new_job()[0]
        self.rejected(main.download_output(mock.Mock(method="GET"), job.job_id, layout=self.EVIL))
        self.rejected(main.polish_translation(main.PolishRequest(job_id=job.job_id, text="x", layout_mode=self.EVIL)))

    def test_queue_escapes_every_server_value(self):
        evil = '"><img src=x onerror=alert(1)>'
        item = {k: evil for k in ("job_id", "file_name", "output_format", "layout_mode", "reading_direction",
                                  "status", "current_step", "progress")}
        items = [dict(item, is_comic=True, has_output=True), dict(item, has_output=True, status="running")]
        html = node(
            NODE_SETUP
            + "const els = {};\n"
            "const el = () => ({ style: {}, classList: { add() {}, remove() {} }, setAttribute() {}, removeAttribute() {}, closest() { return null; } });\n"
            "global.document = { getElementById: id => (els[id] = els[id] || el()) };\n"
            "let _batchQueueState, _seenQuotaWarning = false; const MAX_BATCH_FILES = 20;\n"
            "const state = { tr: {} }, API = '/api';\n"
            "const syncPrimaryStartButtonWithQueue = () => {}, toast = () => {}, checkGlobalGeminiQuotaStatus = () => {};\n"
            + js_slice("function renderBatchQueue", "async function retryQueueItem")
            + f"\nrenderBatchQueue({{ items: {json.dumps(items)}, total_count: 2, done_count: 0, queued_count: 0 }});"
            "\nconsole.log(els['tr-queue-list'].innerHTML);"
        )
        self.assertIsNone(re.search(r"<img", html, re.IGNORECASE), "server value reached innerHTML unescaped")
        self.assertIn("&lt;img", html.lower())


if __name__ == "__main__":
    unittest.main()
