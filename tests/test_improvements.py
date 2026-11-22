"""
test_improvements.py - Guards for the Nov-2026 improvement batch.

1. Gemini usage accounting: per-job accumulator (incl. child tasks), cache hits, daily totals.
2. Slow-model memory: a model that timed out is tried last for a while; a success clears it.
3. Format-preserving AI translation: segment protocol parsing/alignment, fallback for dropped segments,
   DOCX/EPUB round-trips that keep bold/italic runs, tables and HTML tags, and the free path unchanged.
4. M4B chapters: chapter marks from parts, FFMETADATA generation/escaping, ffmpeg command wiring, sidecar.
5. Book Insights task recovery after a restart (saved result or "interrupted").
6. Greek sentence case for English-style Title Case headings (names kept).
7. Translation evaluation scorer (scripts/eval_translation_quality.py) and passages file.
8. No Gemini API key in comic request URLs.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import re
import time
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
MP3_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 414


class TestUsageAccounting(unittest.TestCase):

    def test_job_accumulator_counts_child_tasks_and_cache(self):
        import backend.ai_polisher as ap
        before = ap.get_daily_gemini_usage()

        async def run():
            with ap.track_gemini_usage() as usage:
                async def child():
                    ap.record_gemini_usage({"usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 40}})
                await asyncio.gather(child(), child())
                ap.record_gemini_usage(cached=True)
            ap.record_gemini_usage({"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 5}})  # outside
            return usage

        usage = asyncio.run(run())
        self.assertEqual(usage["requests"], 2)
        self.assertEqual(usage["cached"], 1)
        self.assertEqual(usage["prompt_tokens"], 200)
        self.assertEqual(usage["output_tokens"], 80)
        self.assertEqual(usage["total_tokens"], 280)
        after = ap.get_daily_gemini_usage()
        self.assertEqual(after["requests"] - before["requests"], 3)
        self.assertEqual(after["total_tokens"] - before["total_tokens"], 290)

    def test_usage_reaches_job_and_status(self):
        import backend.main as main_mod
        from backend.job_manager import create_job, get_job, update_job, cleanup_test_jobs
        job = create_job("", "test_usage_job.pdf", "pdf")
        src = ROOT / "temp" / "uploads" / f"test_usage_{job.job_id}.pdf"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"%PDF-1.4")
        out = str(main_mod._job_output_dir(job.job_id) / f"{src.stem}_translated_greek.txt")
        update_job(job.job_id, output_format="txt", status="running")

        async def fake_td(job_id, file_path, file_type, source_lang, target_lang, output_path, style=None, **kw):
            import backend.ai_polisher as ap
            ap.record_gemini_usage({"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 7}})
            Path(output_path).write_text("Κείμενο.", encoding="utf-8")
        try:
            with mock.patch.object(main_mod, "translate_document", side_effect=fake_td), \
                 mock.patch("backend.parsers.detect_is_graphic_novel", return_value={"is_comic": False, "is_scanned": False}):
                asyncio.run(main_mod._run_translation(job.job_id, str(src), "pdf", "english", "greek", out))
            j = get_job(job.job_id)
            self.assertEqual(j.gemini_usage["requests"], 1)
            self.assertEqual(j.gemini_usage["total_tokens"], 17)
            status = asyncio.run(main_mod.job_status(job.job_id))
            self.assertEqual(status["gemini_usage"]["requests"], 1)
        finally:
            src.unlink(missing_ok=True)
            cleanup_test_jobs()

    def test_daily_usage_exposed_by_gemini_status(self):
        import backend.main as main_mod
        info = asyncio.run(main_mod.get_gemini_status())
        self.assertIn("usage_today", info)
        self.assertIn("total_tokens", info["usage_today"])


class TestSlowModelMemory(unittest.TestCase):

    def test_timed_out_model_is_tried_last_until_success(self):
        import backend.ai_polisher as ap
        ap._MODEL_SLOW_UNTIL.clear()
        self.assertEqual(ap._deprioritize_slow_models(["a", "b", "c"]), ["a", "b", "c"])
        ap._MODEL_SLOW_UNTIL["a"] = time.time() + 60
        self.assertEqual(ap._deprioritize_slow_models(["a", "b", "c"]), ["b", "c", "a"])
        ap._MODEL_SLOW_UNTIL["a"] = time.time() - 1          # penalty expired
        self.assertEqual(ap._deprioritize_slow_models(["a", "b"]), ["a", "b"])
        ap._MODEL_SLOW_UNTIL.clear()


def _fake_gemini_translator(drop=None):
    async def fake(content, api_key, system, session=None, temperature=0.25, **kw):
        blocks = re.findall(r"⟦(\d+)⟧ (.*?)(?=\n\n⟦|\n</TEXT_TO_TRANSLATE>)", content, re.S)
        return "\n\n".join(f"⟦{n}⟧ ΕΛ[{t}]" for n, t in blocks if not (drop and int(n) in drop))
    return fake


class TestFormatPreservingAI(unittest.TestCase):

    def test_parse_segments(self):
        from backend.ai_segment_translator import parse_segments
        out = "⟦1⟧ Ένα\n\n⟦2⟧ Δύο\n\n⟦2⟧ Διπλό\n\n⟦4⟧ Τέσσερα"
        self.assertEqual(parse_segments(out, [1, 2, 3, 4]), {1: "Ένα", 4: "Τέσσερα"})

    def test_alignment_and_fallback(self):
        import backend.ai_segment_translator as st
        segs = ["Chapter One", "", "The bold part", " and the rest.", "12345"]

        async def fb(t):
            return f"FREE[{t}]"
        with mock.patch("backend.ai_polisher._call_gemini_api", new=_fake_gemini_translator(drop={2})):
            out = asyncio.run(st.translate_segments_with_gemini(segs, "english", "greek", "k", fallback_translate=fb))
        self.assertEqual(out[0], "ΕΛ[Chapter One]")
        self.assertEqual(out[1], "")
        self.assertEqual(out[2], "FREE[The bold part]", "dropped segment falls back individually")
        self.assertEqual(len(out), len(segs))

    def test_quota_fallback_vs_wait(self):
        import backend.ai_segment_translator as st
        from backend.ai_polisher import DailyQuotaExhaustedError

        async def quota(*a, **k):
            raise DailyQuotaExhaustedError("quota")

        async def fb(t):
            return f"FREE[{t}]"
        with mock.patch("backend.ai_polisher._call_gemini_api", new=quota):
            out = asyncio.run(st.translate_segments_with_gemini(["A", "B"], "english", "greek", "k",
                                                                quota_behavior="fallback", fallback_translate=fb))
            self.assertEqual(out, ["FREE[A]", "FREE[B]"])
            with self.assertRaises(DailyQuotaExhaustedError):
                asyncio.run(st.translate_segments_with_gemini(["A"], "english", "greek", "k", quota_behavior="wait",
                                                              fallback_translate=fb))

    def _docx(self, path):
        import docx
        d = docx.Document()
        d.add_heading("Chapter One", level=1)
        p = d.add_paragraph()
        r1 = p.add_run("Bold start")
        r1.bold = True
        p.add_run(" then normal text.")
        d.add_paragraph("A plain paragraph.")
        t = d.add_table(rows=1, cols=2)
        t.cell(0, 0).text = "Cell A"
        t.cell(0, 1).text = "Cell B"
        d.save(str(path))

    def test_docx_ai_in_place_keeps_formatting(self):
        import docx
        import backend.ai_segment_translator as st
        from backend.format_preserver import translate_docx_in_place
        from functools import partial
        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "in.docx", Path(td) / "out.docx"
            self._docx(src)
            seg = partial(st.translate_segments_with_gemini, source_lang="english", target_lang="greek", api_key="k")
            with mock.patch("backend.ai_polisher._call_gemini_api", new=_fake_gemini_translator()):
                text = asyncio.run(translate_docx_in_place(str(src), str(out), "english", "greek", segment_translator=seg))
            d = docx.Document(str(out))
            self.assertEqual(d.paragraphs[0].style.name, "Heading 1")
            self.assertIn("ΕΛ[Chapter One]", d.paragraphs[0].text)
            runs = [r for r in d.paragraphs[1].runs if r.text.strip()]
            self.assertTrue(runs[0].bold, "bold run stays bold")
            self.assertIn("ΕΛ[Bold start]", runs[0].text)
            self.assertFalse(runs[1].bold)
            self.assertIn("ΕΛ[Cell A]", d.tables[0].cell(0, 0).text)
            self.assertIn("ΕΛ[A plain paragraph.]", text)

    def test_docx_free_path_unchanged(self):
        import docx
        from backend.format_preserver import translate_docx_in_place
        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "in.docx", Path(td) / "out.docx"
            self._docx(src)

            async def free(t, s, tl, *a, **k):
                return f"GTX[{t}]"
            with mock.patch("backend.format_preserver._translate_with_retry", side_effect=free):
                asyncio.run(translate_docx_in_place(str(src), str(out), "english", "greek"))
            d = docx.Document(str(out))
            self.assertIn("GTX[Chapter One]", d.paragraphs[0].text)
            self.assertTrue([r for r in d.paragraphs[1].runs if r.text.strip()][0].bold)

    def test_epub_ai_in_place_keeps_html(self):
        from ebooklib import epub
        import backend.ai_segment_translator as st
        from backend.format_preserver import translate_epub_in_place
        from functools import partial
        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "in.epub", Path(td) / "out.epub"
            book = epub.EpubBook()
            book.set_identifier("id1")
            book.set_title("T")
            book.set_language("en")
            ch = epub.EpubHtml(title="C1", file_name="c1.xhtml", lang="en")
            ch.content = "<html><body><h1>Chapter One</h1><p>Hello <em>dear</em> world.</p></body></html>"
            book.add_item(ch)
            book.spine = ["nav", ch]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            epub.write_epub(str(src), book, {})
            seg = partial(st.translate_segments_with_gemini, source_lang="english", target_lang="greek", api_key="k")
            with mock.patch("backend.ai_polisher._call_gemini_api", new=_fake_gemini_translator()):
                asyncio.run(translate_epub_in_place(str(src), str(out), "english", "greek", segment_translator=seg))
            res = epub.read_epub(str(out))
            html = next(i for i in res.get_items() if i.get_name() == "c1.xhtml").get_content().decode("utf-8")
            self.assertIn("<h1>", html)
            self.assertIn("<em>ΕΛ[dear]</em>", html)
            self.assertIn("ΕΛ[Chapter One]", html)

    def test_pipeline_routes_docx_with_ai_polish_to_in_place(self):
        import backend.main as main_mod
        from backend.job_manager import create_job, get_job, update_job, cleanup_test_jobs
        job = create_job("", "test_ai_inplace.docx", "docx")
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "test_ai_inplace.docx"
            self._docx(src)
            out = str(main_mod._job_output_dir(job.job_id) / "test_ai_inplace_translated_greek.txt")
            update_job(job.job_id, output_format="docx", layout_mode="standard", status="running", max_quality=True)
            direct = mock.AsyncMock()
            try:
                with mock.patch("backend.ai_polisher._call_gemini_api", new=_fake_gemini_translator()), \
                     mock.patch("backend.ai_polisher.translate_and_polish_direct_with_gemini", direct), \
                     mock.patch("backend.gemini_key_pool.resolve_gemini_api_key", return_value="test-key"), \
                     mock.patch("backend.parsers.detect_is_graphic_novel", return_value={"is_comic": False, "is_scanned": False}):
                    asyncio.run(main_mod._run_translation(job.job_id, str(src), "docx", "english", "greek", out, True))
                j = get_job(job.job_id)
                direct.assert_not_called()
                self.assertEqual(j.status, "done", j.error)
                self.assertTrue(j.output_path.endswith(".docx"))
                import docx
                self.assertIn("ΕΛ[Chapter One]", docx.Document(j.output_path).paragraphs[0].text)
                self.assertEqual(j.revision_report["reason"], "format_preserved_output")
            finally:
                cleanup_test_jobs()


class TestM4BChapters(unittest.TestCase):

    def test_chapter_marks_and_ffmetadata(self):
        from backend.tts_engine import compute_chapter_marks, build_ffmetadata
        with tempfile.TemporaryDirectory() as td:
            parts = []
            texts = ["Κεφάλαιο 1\nΑρχή της ιστορίας.", "Συνέχεια.", "Κεφάλαιο 2\nΆλλο κομμάτι."]
            for i, t in enumerate(texts):
                f = Path(td) / f"c{i}.mp3"
                f.write_bytes(MP3_FRAME * 200)
                parts.append((t, str(f)))
            marks = compute_chapter_marks(parts)
            self.assertEqual([m["title"] for m in marks], ["Κεφάλαιο 1", "Κεφάλαιο 2"])
            self.assertEqual(marks[0]["start_ms"], 0)
            self.assertGreater(marks[1]["start_ms"], marks[0]["start_ms"])
            meta = build_ffmetadata(marks + [], "Βιβλίο; = #", "BookApp")
            self.assertTrue(meta.startswith(";FFMETADATA1"))
            self.assertEqual(meta.count("[CHAPTER]"), 2)
            self.assertIn("title=Βιβλίο\\; \\= \\#", meta)
            self.assertEqual(compute_chapter_marks(parts[1:2]), [], "no headings -> no chapters")

    def test_ffmpeg_command_includes_chapters(self):
        from backend import tts_engine as tts
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            meta = Path(cmd[cmd.index("-map_metadata") - 1])
            captured["meta"] = meta.read_text(encoding="utf-8")
            Path(cmd[-1]).write_bytes(b"\x00\x00\x00\x18ftypM4B ")
            return mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory() as td:
            mp3 = Path(td) / "a.mp3"
            mp3.write_bytes(MP3_FRAME * 10)
            chapters = [{"start_ms": 0, "title": "Αρχή"}, {"start_ms": 5000, "title": "Τέλος", "end_ms": 9000}]
            with mock.patch("shutil.which", return_value="ffmpeg"), mock.patch("subprocess.run", side_effect=fake_run):
                asyncio.run(tts.export_audiobook_m4b(str(mp3), str(Path(td) / "a.m4b"), title="T", chapters=chapters))
            cmd = captured["cmd"]
            self.assertIn("-map_chapters", cmd)
            self.assertEqual(cmd[cmd.index("-map_metadata") + 1], "1")
            self.assertIn("[CHAPTER]", captured["meta"])
            self.assertEqual(list(Path(td).glob(".*.ffmeta.txt")), [], "temporary metadata file removed")


class TestInsightsTaskRecovery(unittest.TestCase):

    def test_recovered_result_or_interrupted(self):
        import backend.book_insights as bi
        with tempfile.TemporaryDirectory() as td:
            old = bi.TASK_INDEX_PATH
            bi.TASK_INDEX_PATH = Path(td) / "idx.json"
            job_dir = Path(td) / "job"
            job_dir.mkdir()
            try:
                t1 = bi.InsightTask(task_id="a" * 32, job_id="job", action="generate", insight_type="short_summary",
                                    language="greek", status="running")
                bi._index_update(t1)
                interrupted = bi.recover_task("a" * 32, lambda j: job_dir)
                self.assertEqual(interrupted["status"], "error")
                self.assertEqual(interrupted["error"]["code"], "interrupted")
                bi.save_insight(job_dir, {"insight_type": "short_summary", "language": "greek", "text": "Κείμενο",
                                          "created_at": time.time()})
                done = bi.recover_task("a" * 32, lambda j: job_dir)
                self.assertEqual(done["status"], "done")
                self.assertEqual(done["result"]["text"], "Κείμενο")
                self.assertIsNone(bi.recover_task("b" * 32, lambda j: job_dir))
            finally:
                bi.TASK_INDEX_PATH = old


class TestHeadingSentenceCase(unittest.TestCase):

    def test_title_case_heading_converted_names_kept(self):
        from backend.output_refiner import refine_text_content
        t = ("=== PAGE 1 ===\nΚεφάλαιο Τρίτο: Το Γράμμα από τη Λισαβόνα\n\nΗ Μάρτα βρήκε το γράμμα.\n\n"
             "Ο Ντάνιελ Κουκ\n\nΜια Νύχτα στην Αθήνα\n\nΤέλος.")
        out = refine_text_content(t, "greek")[0]
        self.assertIn("Κεφάλαιο τρίτο: Το γράμμα από τη Λισαβόνα", out)
        self.assertIn("Ο Ντάνιελ Κουκ", out, "names are never lowered")
        self.assertIn("Μια Νύχτα στην Αθήνα", out, "words without lowercase evidence are kept")
        self.assertIn("Η Μάρτα βρήκε το γράμμα.", out)


class TestEvaluationScorer(unittest.TestCase):

    def test_scorer_rules(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import eval_translation_quality as ev
        passages = {p["id"]: p for p in ev.load_passages()}
        self.assertGreaterEqual(len(passages), 5)
        p = passages["dialogue_idioms"]
        good = ("=== PAGE 1 ===\nΚεφάλαιο τρίτο: Το γράμμα από τη Λισαβόνα\n\nΗ Μάρτα έβαλε το χέρι στην τσέπη του "
                "παλτού της και βρήκε το γράμμα που της είχε στείλει ο αδερφός της από τη Λισαβόνα. Δεν το είχε ανοίξει. "
                "Το κουβαλούσε τρεις μέρες, όπως κουβαλάς μια πέτρα που σκοπεύεις να πετάξεις.\n\n«Θα το διαβάσεις "
                "κάποια στιγμή», είπε ο Ντάνιελ, που ακουμπούσε στην κάσα της πόρτας με σταυρωμένα χέρια. «Κάθεται στην "
                "τσέπη σου από τη Δευτέρα».\n\n«Δεν βγάζει νόημα», είπε. «Έχει έντεκα χρόνια να μου γράψει. Γιατί "
                "τώρα;»\n\nΟ βραστήρας άρχισε να σφυρίζει στην κουζίνα και η Μάρτα κόντεψε να πεταχτεί από την "
                "τρομάρα της.")
        res = ev.score_translation(p["source"], good, p["checks"])
        self.assertTrue(res["passed"], res["failures"])
        bad = good.replace("Κεφάλαιο τρίτο: Το γράμμα", "Κεφάλαιο Τρίτο: Το Γράμμα").replace("Κάθεται", "Σαπίζει")
        res2 = ev.score_translation(p["source"], bad, p["checks"])
        self.assertFalse(res2["passed"])
        self.assertTrue(any("Τρίτο" in f for f in res2["failures"]))
        self.assertTrue(any("σαπίζει" in f.lower() for f in res2["failures"]), "lowercase rules match any case")
        res3 = ev.score_translation(p["source"], good.replace("\n\n«Δεν", " «Δεν"), p["checks"])
        self.assertTrue(any("paragraph count" in f for f in res3["failures"]))


class TestNoKeysInUrls(unittest.TestCase):

    def test_comic_requests_send_key_in_header_only(self):
        src = (ROOT / "backend" / "comic_translator.py").read_text(encoding="utf-8")
        self.assertNotIn("?key=", src)
        for f in (ROOT / "backend").glob("*.py"):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"generateContent\?key=", f.name)


if __name__ == "__main__":
    unittest.main()
