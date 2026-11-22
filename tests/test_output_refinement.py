"""
test_output_refinement.py - Test suite for the Automatic Final Output Refinement stage
(backend/output_refiner.py and its integration in main._run_translation / tts_engine.generate_audiobook).

Covers:
 1. Automatic triggering at the end of the translation and audiobook workflows (and only then).
 2. Detection + correction of deliberately introduced issues (stutters, accents, final-nu, hyphenation,
    spacing, unambiguous calques, article agreement, Latin homoglyphs).
 3. No-op on clean output, meaning safety (ambiguous phrasing / emphatic repetition left untouched),
    layout/language awareness (poetry whitespace, French punctuation spacing), idempotency.
 4. Empty / malformed / unreadable inputs.
 5. Failure safety: exceptions, write failures, re-export failures, TTS re-synthesis timeouts,
    corrupt re-assembly -> original output preserved byte-for-byte.
 6. Format preservation: in-place DOCX outputs are inspected only, never regenerated.
 7. Audiobook inspection: headers, empty chunks, missing sections, truncation, MP3-in-M4B fallback,
    automatic healing of failed sections, metadata added only when missing.
 8. Disabled stage => pipeline behaves exactly as before; settings toggle + per-job override.
 9. API: /api/refine/config, /api/refine (text, job translation, job audiobook), path traversal
    rejection, running-job rejection, /api/settings toggle, report exposed via /api/status.
10. The stage performs no network/API calls.
"""

import sys
sys.path.insert(0, ".")
import os
import json
import time
import socket
import asyncio
import tempfile
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest import mock

from backend import output_refiner
from backend.output_refiner import (
    inspect_text_quality,
    refine_text_content,
    refine_translation_output,
    inspect_audiobook_quality,
    refine_audiobook_output,
    refine_audiobook_output_async,
    is_refinement_enabled,
    build_refinement_report,
)
from backend.job_manager import create_job, get_job, update_job, cleanup_test_jobs
from backend.settings_manager import save_setting, load_settings, save_settings

API_BASE = "http://127.0.0.1:8000/api"
MP3_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 414   # one MPEG-1 Layer III frame (128 kbps, 44.1 kHz)
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "temp" / "outputs"


def _ensure_server():
    try:
        with urllib.request.urlopen(f"{API_BASE}/health", timeout=0.8):
            return
    except Exception:
        pass
    import threading
    import uvicorn
    from backend.main import app
    threading.Thread(target=uvicorn.run, args=(app,),
                     kwargs={"host": "127.0.0.1", "port": 8000, "log_level": "error"}, daemon=True).start()
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{API_BASE}/health", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)


def _api(method: str, path: str, data=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(f"{API_BASE}{path}", data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def _new_test_job(name="test_refine_job.txt", ftype="txt"):
    job = create_job("", name, ftype)
    out_dir = OUTPUT_ROOT / job.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return job, out_dir


class _RefinementTestBase(unittest.TestCase):
    def setUp(self):
        self._settings_snapshot = load_settings()
        self._env_snapshot = os.environ.pop("FINAL_REFINEMENT_ENABLED", None)
        save_setting("final_refinement_enabled", True)

    def tearDown(self):
        save_settings(self._settings_snapshot)
        if self._env_snapshot is not None:
            os.environ["FINAL_REFINEMENT_ENABLED"] = self._env_snapshot
        cleanup_test_jobs()


# ===========================================================================
# 1. Text inspection & deterministic refinement
# ===========================================================================

class TestTextRefinement(_RefinementTestBase):

    def test_stutters_removed_greek_and_english(self):
        out, _, corr = refine_text_content("Και και τότε είπε ότι ότι θα θα πάει στο στο σπίτι.", "greek")
        self.assertEqual(out, "Και τότε είπε ότι θα πάει στο σπίτι.")
        self.assertTrue(corr)
        out_en, _, _ = refine_text_content("The the book was on on the the table and and it was great.", "english")
        self.assertEqual(out_en, "The book was on the table and it was great.")
        out_tri, _, _ = refine_text_content("Ήρθε και και και έφυγε.", "greek")
        self.assertEqual(out_tri, "Ήρθε και έφυγε.")

    def test_emphatic_repetition_is_preserved(self):
        text = "«Όχι όχι», ψιθύρισε. Σιγά σιγά έφυγε. Τρέχα τρέχα, έλα έλα!"
        out, _, corr = refine_text_content(text, "greek")
        self.assertEqual(out, text)
        self.assertEqual(corr, [])

    def test_monosyllable_accents_and_final_nu(self):
        out, _, _ = refine_text_content("Έτρεξε γιά να πάει σέ ένα μέρος μέ τό αυτοκίνητο.", "greek")
        self.assertEqual(out, "Έτρεξε για να πάει σε ένα μέρος με το αυτοκίνητο.")
        out2, _, _ = refine_text_content("Γιά σένα. δε μπορώ να το πιστέψω, αλλά δεν θέλω να φύγω.", "greek")
        self.assertTrue(out2.startswith("Για σένα."))
        self.assertIn("δεν μπορώ", out2)
        self.assertIn("δε θέλω", out2)
        # legitimate accented interrogatives must stay
        keep = "Πού πας; Πώς είσαι;"
        self.assertEqual(refine_text_content(keep, "greek")[0], keep)

    def test_hyphenation_spacing_and_blank_lines(self):
        bad = "Αυτή είναι μια πλημ- \nμύρα που κατέκλυσε   , την πόλη .\n\n\n\n\nΝέα παράγραφος."
        out, _, corr = refine_text_content(bad, "greek")
        self.assertEqual(out, "Αυτή είναι μια πλημμύρα που κατέκλυσε, την πόλη.\n\nΝέα παράγραφος.")
        self.assertGreaterEqual(len(corr), 3)

    def test_unambiguous_calques_fixed_ambiguous_only_reported(self):
        out, issues, _ = refine_text_content("Πήγε για σίγουρα. Πάρε μια ματιά! Ο οδηγός μου κάνει νόημα.", "greek")
        self.assertIn("Πήγε σίγουρα.", out)
        self.assertIn("Ρίξε μια ματιά!", out)
        # 'κάνει νόημα' also means 'signals' -> reported, never rewritten
        self.assertIn("κάνει νόημα", out)
        self.assertTrue(any(i.snippet == "κάνει νόημα" and not i.auto_fixable for i in issues))

        ambiguous = "Ήταν ικανός να σκοτώσει. Στο τέλος της ημέρας γύρισε σπίτι."
        out_a, issues_a, corr_a = refine_text_content(ambiguous, "greek")
        self.assertEqual(out_a, ambiguous)
        self.assertEqual(corr_a, [])
        self.assertTrue(any(i.category == "phrasing" for i in issues_a))

    def test_english_article_agreement(self):
        out, _, _ = refine_text_content("It took a hour. A honest man ate a apple.", "english")
        self.assertEqual(out, "It took an hour. An honest man ate an apple.")

    def test_clean_output_is_untouched(self):
        clean = (
            "============================================================\nPAGE 1\n"
            "============================================================\n\n"
            "«Καλημέρα», είπε ο Γιάννης με ένα ζεστό χαμόγελο.\n\n"
            "Η ημέρα ήταν λαμπερή και ο αέρας μύριζε θάλασσα.\n\n* * *\n\n"
            "============================================================\nPAGE 2\n"
            "============================================================\n\n"
            "Προχώρησαν κατά μήκος της ακτής χωρίς καμία βιασύνη."
        )
        out, _, corr = refine_text_content(clean, "greek")
        self.assertEqual(out, clean)
        self.assertEqual(corr, [])

    def test_page_markers_and_paragraphs_preserved(self):
        text = "=== PAGE 1 ===\nΚαι και τότε γιά λίγο.\n\n=== PAGE 2 ===\nΤο το τέλος.\n\n=== PAGE 3 ===\nΤέλος."
        out, _, _ = refine_text_content(text, "greek")
        for n in (1, 2, 3):
            self.assertIn(f"=== PAGE {n} ===", out)
        self.assertIn("Και τότε για λίγο.", out)
        self.assertEqual(len([l for l in out.split("\n") if l.strip()]),
                         len([l for l in text.split("\n") if l.strip()]))

    def test_layout_and_language_awareness(self):
        poem = "Στίχος ένα ,\n\n\n\nΣτίχος δύο"
        self.assertEqual(refine_text_content(poem, "greek", style="poetry")[0], poem)
        fr = "Bonjour ! Comment ça va ? Très bien , merci ."
        self.assertEqual(refine_text_content(fr, "french")[0], "Bonjour ! Comment ça va ? Très bien, merci.")
        code_like = "Το .NET κοστίζει 3 .5 ευρώ. Περίμενε ..."
        self.assertEqual(refine_text_content(code_like, "greek")[0], code_like)

    def test_idempotent(self):
        bad = "Και και γιά σίγουρα, δε μπορώ .\n\n\n\nΤέλος."
        once, _, _ = refine_text_content(bad, "greek")
        twice, _, corr2 = refine_text_content(once, "greek")
        self.assertEqual(once, twice)
        self.assertEqual(corr2, [])

    def test_structure_and_omission_detection(self):
        text = "=== PAGE 1 ===\nΚείμενο.\n=== PAGE 3 ===\n\n=== PAGE 3 ===\nΆλλο."
        issues = inspect_text_quality(text, "greek")
        descs = " | ".join(i.description for i in issues)
        self.assertIn("Non-sequential page gap", descs)
        self.assertIn("Duplicate page marker", descs)
        self.assertIn("is empty", descs)
        untranslated = ("Κεφάλαιο 1\n\nThis whole paragraph was never translated into the target language "
                        "and the reader would notice it immediately.")
        self.assertTrue(any(i.category == "omission" for i in inspect_text_quality(untranslated, "greek")))
        self.assertTrue(any("Unbalanced" in i.description for i in inspect_text_quality("«Γεια σου, είπε.", "greek")))

    def test_safety_guard_reverts_structural_damage(self):
        text = "=== PAGE 1 ===\nΚαι και τότε.\n=== PAGE 2 ===\nΤέλος."
        with mock.patch("backend.typography.apply_final_nu_rules", side_effect=lambda s: s.replace("=== PAGE 2 ===", "")):
            out, issues, corr = refine_text_content(text, "greek")
        self.assertEqual(out, text)
        self.assertEqual(corr, [])

    def test_failing_step_is_skipped_not_fatal(self):
        with mock.patch("backend.typography.apply_final_nu_rules", side_effect=RuntimeError("boom")):
            out, _, _ = refine_text_content("Και και τότε.", "greek")
        self.assertEqual(out, "Και τότε.")

    def test_empty_malformed_inputs(self):
        self.assertEqual(refine_text_content("")[0], "")
        self.assertEqual(refine_text_content("   \n ")[0], "   \n ")
        self.assertIsNone(refine_text_content(None)[0])
        self.assertEqual(inspect_text_quality(None), [])
        garbage = "\x00\x01�� ### ))) ((( ​"
        out, _, _ = refine_text_content(garbage, "greek")
        self.assertEqual(out, garbage)
        refine_text_content("x" * 200000, "unknown-lang")  # must not raise


# ===========================================================================
# 2. refine_translation_output (file stage)
# ===========================================================================

class TestTranslationFileStage(_RefinementTestBase):

    def _run(self, **kw):
        return asyncio.run(refine_translation_output(job_id="test_refine_file", **kw))

    def test_txt_and_reexported_docx_are_updated_atomically(self):
        from backend.exporter import export_text
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            txt = td / "sample_translated_greek.txt"
            content = "=== PAGE 1 ===\nΚαι και ο πρόεδρος ήρθε γιά σίγουρα.\n\n=== PAGE 2 ===\nΤέλος."
            txt.write_text(content, encoding="utf-8")
            docx = Path(export_text(content, td, "docx", txt.stem))
            res = self._run(output_path=str(txt), final_exported_path=str(docx), target_lang="greek", output_format="docx")
            self.assertEqual(res.status, "refined")
            self.assertGreater(res.modifications_count, 0)
            self.assertGreaterEqual(res.quality_score_after, res.quality_score_before)
            new_txt = txt.read_text(encoding="utf-8")
            self.assertIn("Και ο πρόεδρος ήρθε σίγουρα.", new_txt)
            from docx import Document
            doc_text = "\n".join(p.text for p in Document(str(docx)).paragraphs)
            self.assertIn("ήρθε σίγουρα", doc_text)
            self.assertNotIn("Και και", doc_text)
            leftovers = [p.name for p in td.iterdir() if "refine" in p.name]
            self.assertEqual(leftovers, [], "no staging files may be left behind")

    def test_format_preserved_docx_is_never_regenerated(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            txt = td / "book_translated_greek.txt"
            txt.write_text("Και και τότε έφυγε.", encoding="utf-8")
            docx = td / "book_translated_greek.docx"
            docx.write_bytes(b"PK\x03\x04 original format-preserved docx bytes")
            before_doc, before_txt = docx.read_bytes(), txt.read_text(encoding="utf-8")
            res = self._run(output_path=str(txt), final_exported_path=str(docx), output_format="docx",
                            allow_reexport=False)
            self.assertEqual(res.status, "inspected")
            self.assertEqual(docx.read_bytes(), before_doc)
            self.assertEqual(txt.read_text(encoding="utf-8"), before_txt)
            self.assertTrue(res.issues_detected)

    def test_reexport_failure_rolls_back_everything(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            txt = td / "x_translated_greek.txt"
            txt.write_text("Και και τότε.", encoding="utf-8")
            pdf = td / "x_translated_greek.pdf"
            pdf.write_bytes(b"%PDF-1.4 original")
            with mock.patch("backend.exporter.export_text", side_effect=RuntimeError("disk full")):
                res = self._run(output_path=str(txt), final_exported_path=str(pdf), output_format="pdf")
            self.assertEqual(res.status, "error")
            self.assertTrue(res.reverted)
            self.assertEqual(txt.read_text(encoding="utf-8"), "Και και τότε.")
            self.assertEqual(pdf.read_bytes(), b"%PDF-1.4 original")
            self.assertEqual([p.name for p in td.iterdir() if "refine" in p.name], [])

    def test_document_swap_failure_rolls_back_text(self):
        from backend.exporter import export_text
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            txt = td / "y_translated_greek.txt"
            txt.write_text("Και και τότε.", encoding="utf-8")
            docx = Path(export_text("Και και τότε.", td, "docx", txt.stem))
            original_doc = docx.read_bytes()
            real_replace = os.replace

            def _replace(src, dst):
                if str(dst).endswith(".docx"):
                    raise PermissionError("file locked by Word")
                return real_replace(src, dst)
            with mock.patch("backend.output_refiner.os.replace", side_effect=_replace):
                res = self._run(output_path=str(txt), final_exported_path=str(docx), output_format="docx")
            self.assertEqual(res.status, "error")
            self.assertEqual(txt.read_text(encoding="utf-8"), "Και και τότε.")
            self.assertEqual(docx.read_bytes(), original_doc)

    def test_text_write_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as td:
            txt = Path(td) / "z_translated_greek.txt"
            txt.write_text("Και και τότε.", encoding="utf-8")
            with mock.patch("backend.output_refiner._atomic_write_text", side_effect=OSError("read-only")):
                res = self._run(output_path=str(txt), final_exported_path=str(txt), output_format="txt")
            self.assertEqual(res.status, "error")
            self.assertEqual(txt.read_text(encoding="utf-8"), "Και και τότε.")

    def test_missing_empty_and_undecodable_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self.assertEqual(self._run(output_path=str(td / "missing.txt")).status, "skipped")
            empty = td / "empty.txt"
            empty.write_text("", encoding="utf-8")
            res_e = self._run(output_path=str(empty))
            self.assertEqual(res_e.status, "verified_clean")
            self.assertTrue(any(i.category == "omission" for i in res_e.issues_detected))
            bad = td / "bad.txt"
            bad.write_bytes(b"\xff\xfe\xfa invalid utf-8 \x80\x81")
            res_b = self._run(output_path=str(bad))
            self.assertEqual(res_b.status, "error")
            self.assertEqual(bad.read_bytes(), b"\xff\xfe\xfa invalid utf-8 \x80\x81")

    def test_disabled_is_pass_through(self):
        with tempfile.TemporaryDirectory() as td:
            txt = Path(td) / "d_translated_greek.txt"
            txt.write_text("Και και τότε.", encoding="utf-8")
            res = self._run(output_path=str(txt), enabled=False)
            self.assertEqual(res.status, "skipped")
            self.assertEqual(txt.read_text(encoding="utf-8"), "Και και τότε.")
            save_setting("final_refinement_enabled", False)
            self.assertEqual(self._run(output_path=str(txt)).status, "skipped")
            self.assertEqual(txt.read_text(encoding="utf-8"), "Και και τότε.")

    def test_stage_makes_no_network_calls(self):
        with tempfile.TemporaryDirectory() as td:
            txt = Path(td) / "n_translated_greek.txt"
            txt.write_text("Και και τότε γιά λίγο.", encoding="utf-8")
            async def _inner():
                # patch only once the loop exists (Windows loops use a local socketpair internally)
                with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network used")), \
                     mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network used")):
                    return await refine_translation_output(job_id="test_refine_net", output_path=str(txt),
                                                           api_key="AIza-fake-key-for-test")
            res = asyncio.run(_inner())
            self.assertEqual(res.status, "refined")


# ===========================================================================
# 3. Configuration
# ===========================================================================

class TestConfiguration(_RefinementTestBase):

    def test_toggle_override_and_env(self):
        self.assertTrue(is_refinement_enabled())
        save_setting("final_refinement_enabled", False)
        self.assertFalse(is_refinement_enabled())
        self.assertTrue(is_refinement_enabled(True))      # per-request override wins
        save_setting("final_refinement_enabled", "off")
        self.assertFalse(is_refinement_enabled())
        save_setting("final_refinement_enabled", True)
        self.assertFalse(is_refinement_enabled(False))
        os.environ["FINAL_REFINEMENT_ENABLED"] = "false"
        try:
            self.assertFalse(is_refinement_enabled())
        finally:
            os.environ.pop("FINAL_REFINEMENT_ENABLED", None)

    def test_unreadable_settings_default_to_enabled(self):
        with mock.patch("backend.output_refiner.get_setting", side_effect=OSError("locked")):
            self.assertTrue(is_refinement_enabled())

    def test_report_is_json_safe(self):
        _, issues, corr = refine_text_content("Και και τότε.", "greek")
        res = output_refiner.TranslationRefinementResult("j", "refined", "a", "b", issues_detected=issues,
                                                         corrections_applied=corr)
        rep = build_refinement_report(res)
        json.dumps(rep)
        self.assertEqual(rep["status"], "refined")
        self.assertEqual(rep["corrections"], corr)


# ===========================================================================
# 4. Audiobook inspection & refinement
# ===========================================================================

class TestAudiobookStage(_RefinementTestBase):

    def test_inspection_invalid_files(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ok, issues, _ = inspect_audiobook_quality(str(td / "none.mp3"))
            self.assertFalse(ok)
            self.assertIn("not found", issues[0].description)
            (td / "empty.mp3").write_bytes(b"")
            self.assertFalse(inspect_audiobook_quality(str(td / "empty.mp3"))[0])
            (td / "corrupt.mp3").write_bytes(b"NOT AN AUDIO FILE AT ALL 1234567890")
            ok, issues, _ = inspect_audiobook_quality(str(td / "corrupt.mp3"))
            self.assertFalse(ok)
            self.assertTrue(any("corrupted" in i.description for i in issues))

    def test_missing_sections_and_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chunks = []
            for i in (0, 1, 3):
                c = td / f"chunk_{i:06d}.mp3"
                c.write_bytes(MP3_FRAME * 3)
                chunks.append(str(c))
            final = td / "book.mp3"
            final.write_bytes(MP3_FRAME * 9)
            ok, issues, meta = inspect_audiobook_quality(str(final), chunks, expected_indices=[0, 1, 2, 3])
            self.assertFalse(ok)
            self.assertEqual(meta["missing_indices"], [2])
            # name-based inference when indices are not supplied
            self.assertEqual(inspect_audiobook_quality(str(final), chunks)[2]["missing_indices"], [2])
            # legitimately silent segment (index 2 excluded by caller) is not an error
            ok2, _, _ = inspect_audiobook_quality(str(final), chunks, expected_indices=[0, 1, 3])
            self.assertTrue(ok2)
            # truncated final file
            final.write_bytes(MP3_FRAME * 4)
            ok3, issues3, _ = inspect_audiobook_quality(str(final), chunks, expected_indices=[0, 1, 3])
            self.assertFalse(ok3)
            self.assertTrue(any("truncated" in i.description for i in issues3))

    def test_mp3_in_m4b_fallback_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            m4b = Path(td) / "book.m4b"
            m4b.write_bytes(MP3_FRAME * 10)
            ok, issues, _ = inspect_audiobook_quality(str(m4b))
            self.assertTrue(ok)
            self.assertTrue(any(i.severity == "info" and "ffmpeg" in i.description for i in issues))

    def test_metadata_added_only_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "tagless.mp3"
            audio.write_bytes(MP3_FRAME * 5)
            res = refine_audiobook_output("test_audio_meta", str(audio), book_title="Τίτλος Βιβλίου")
            self.assertTrue(res.is_valid)
            self.assertEqual(res.status, "healed")
            from mutagen.id3 import ID3
            self.assertEqual(str(ID3(str(audio)).get("TIT2")), "Τίτλος Βιβλίου")
            snapshot = audio.read_bytes()
            res2 = refine_audiobook_output("test_audio_meta", str(audio), book_title="Άλλος")
            self.assertEqual(res2.status, "verified_clean")
            self.assertEqual(audio.read_bytes(), snapshot, "already-tagged audio must not be rewritten")

    def test_healing_resynthesises_and_reassembles(self):
        from backend.tts_engine import _concatenate_mp3s
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chunks = []
            for i in range(3):
                c = td / f"chunk_{i:06d}.mp3"
                c.write_bytes(b"" if i == 1 else MP3_FRAME * 3)
                chunks.append(str(c))
            final = td / "book.mp3"
            asyncio.run(_concatenate_mp3s(chunks, str(final)))
            self.assertEqual(final.stat().st_size, len(MP3_FRAME) * 6)

            async def resynth(idx):
                (td / f"chunk_{idx:06d}.mp3").write_bytes(MP3_FRAME * 3)
                return True

            res = asyncio.run(refine_audiobook_output_async(
                "test_heal", str(final), chunks, 3, [0, 1, 2], resynthesize_chunk=resynth,
                reassemble=lambda files, dest: _concatenate_mp3s(files, dest),
            ))
            self.assertTrue(res.healed)
            self.assertTrue(res.is_valid)
            self.assertEqual(res.missing_chunk_indices, [])
            self.assertGreaterEqual(final.stat().st_size, len(MP3_FRAME) * 9)

    def test_healing_failures_keep_original_audio(self):
        from backend.tts_engine import _concatenate_mp3s
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chunks = []
            for i in range(3):
                c = td / f"chunk_{i:06d}.mp3"
                c.write_bytes(b"" if i == 1 else MP3_FRAME * 3)
                chunks.append(str(c))
            final = td / "book.mp3"
            asyncio.run(_concatenate_mp3s(chunks, str(final)))
            original = final.read_bytes()

            async def timeout_resynth(idx):
                raise asyncio.TimeoutError("edge-tts timed out")

            res = asyncio.run(refine_audiobook_output_async(
                "test_heal_fail", str(final), chunks, 3, [0, 1, 2], resynthesize_chunk=timeout_resynth,
                reassemble=lambda files, dest: _concatenate_mp3s(files, dest),
            ))
            # metadata may be added, but no section was recovered
            self.assertFalse(any("Re-synthesised" in c for c in res.corrections_applied))
            self.assertEqual(res.status, "warning")
            self.assertEqual(res.missing_chunk_indices, [1])
            # audio payload untouched (only a missing ID3v2 header may have been prepended)
            self.assertTrue(final.read_bytes().endswith(original))

            # re-assembly that produces garbage must be rejected
            async def ok_resynth(idx):
                (td / f"chunk_{idx:06d}.mp3").write_bytes(MP3_FRAME * 3)
                return True

            async def corrupt_reassemble(files, dest):
                Path(dest).write_bytes(b"garbage")

            before = final.read_bytes()
            res2 = asyncio.run(refine_audiobook_output_async(
                "test_heal_corrupt", str(final), chunks, 3, [0, 1, 2],
                resynthesize_chunk=ok_resynth, reassemble=corrupt_reassemble,
            ))
            self.assertFalse(any("Re-synthesised" in c for c in res2.corrections_applied))
            self.assertEqual(res2.missing_chunk_indices, [1])
            self.assertEqual(final.read_bytes(), before)
            self.assertEqual([p.name for p in td.iterdir() if p.name.startswith(".book.")], [])

    def test_disabled_audio_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "a.mp3"
            audio.write_bytes(MP3_FRAME * 3)
            res = refine_audiobook_output("test_audio_off", str(audio), enabled=False)
            self.assertEqual(res.status, "skipped")
            self.assertEqual(audio.read_bytes(), MP3_FRAME * 3)

    def test_sync_wrapper_refuses_inside_event_loop(self):
        async def _inner():
            with self.assertRaises(RuntimeError):
                refine_audiobook_output("test_loop", "x.mp3")
        asyncio.run(_inner())


# ===========================================================================
# 5. Workflow integration (automatic trigger at the correct point)
# ===========================================================================

class TestWorkflowIntegration(_RefinementTestBase):

    def _translation_job(self, fmt="docx", ftype="pdf", text="=== PAGE 1 ===\nΚαι και τότε ήρθε γιά λίγο."):
        from backend.main import _job_output_dir
        job, _ = _new_test_job("test_refine_flow.pdf", ftype)
        src = OUTPUT_ROOT.parent / "uploads" / f"test_refine_src_{job.job_id}.txt"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("source", encoding="utf-8")
        out_dir = _job_output_dir(job.job_id)
        output_path = str(out_dir / f"{src.stem}_translated_greek.txt")
        update_job(job.job_id, output_format=fmt, layout_mode="standard", status="running", file_path=str(src))

        async def fake_translate_document(job_id, file_path, file_type, source_lang, target_lang, output_path, style=None, **kw):
            Path(output_path).write_text(text, encoding="utf-8")
            return output_path
        return job, src, output_path, fake_translate_document

    def test_translation_refined_after_export_before_completion(self):
        import backend.main as main_mod
        job, src, output_path, fake_td = self._translation_job()
        seen = {}
        real_refine = output_refiner.refine_translation_output

        async def spy(**kw):
            j = get_job(job.job_id)
            seen["status"] = j.status
            seen["export_exists"] = Path(kw["final_exported_path"]).exists()
            seen["allow_reexport"] = kw.get("allow_reexport")
            return await real_refine(**kw)

        try:
            with mock.patch.object(main_mod, "translate_document", side_effect=fake_td), \
                 mock.patch("backend.output_refiner.refine_translation_output", side_effect=spy):
                asyncio.run(main_mod._run_translation(job.job_id, str(src), "pdf", "english", "greek", output_path))
            j = get_job(job.job_id)
            self.assertEqual(seen, {"status": "running", "export_exists": True, "allow_reexport": True})
            self.assertEqual(j.status, "done")
            self.assertTrue(j.output_path.endswith(".docx") and Path(j.output_path).exists())
            self.assertEqual(j.refinement_report["status"], "refined")
            self.assertIn("Και τότε ήρθε για λίγο.", Path(output_path).read_text(encoding="utf-8"))
        finally:
            src.unlink(missing_ok=True)

    def test_translation_disabled_behaves_as_before(self):
        import backend.main as main_mod
        save_setting("final_refinement_enabled", False)
        job, src, output_path, fake_td = self._translation_job(fmt="txt")
        try:
            with mock.patch.object(main_mod, "translate_document", side_effect=fake_td), \
                 mock.patch("backend.output_refiner.refine_translation_output") as never:
                asyncio.run(main_mod._run_translation(job.job_id, str(src), "pdf", "english", "greek", output_path))
            never.assert_not_called()
            j = get_job(job.job_id)
            self.assertEqual(j.status, "done")
            self.assertEqual(Path(output_path).read_text(encoding="utf-8"), "=== PAGE 1 ===\nΚαι και τότε ήρθε γιά λίγο.")
            self.assertEqual(j.refinement_report, {"status": "skipped"})
        finally:
            src.unlink(missing_ok=True)

    def test_refinement_crash_does_not_fail_job(self):
        import backend.main as main_mod
        job, src, output_path, fake_td = self._translation_job(fmt="txt")
        try:
            with mock.patch.object(main_mod, "translate_document", side_effect=fake_td), \
                 mock.patch("backend.output_refiner.refine_translation_output", side_effect=RuntimeError("model unavailable")):
                asyncio.run(main_mod._run_translation(job.job_id, str(src), "pdf", "english", "greek", output_path))
            j = get_job(job.job_id)
            self.assertEqual(j.status, "done")
            self.assertIsNone(j.error)
            self.assertTrue(Path(j.output_path).exists())
        finally:
            src.unlink(missing_ok=True)

    def test_per_job_override_disables_stage(self):
        import backend.main as main_mod
        job, src, output_path, fake_td = self._translation_job(fmt="txt")
        update_job(job.job_id, final_refinement=False)
        try:
            with mock.patch.object(main_mod, "translate_document", side_effect=fake_td):
                asyncio.run(main_mod._run_translation(job.job_id, str(src), "pdf", "english", "greek", output_path))
            self.assertIn("Και και", Path(output_path).read_text(encoding="utf-8"))
        finally:
            src.unlink(missing_ok=True)

    def test_in_place_docx_flow_is_inspect_only(self):
        import backend.main as main_mod
        job, src, output_path, _ = self._translation_job(fmt="docx", ftype="docx")
        original_docx = b"PK\x03\x04 format preserved docx"

        async def fake_in_place(fp, out_docx, s, t, prog, style=None, segment_translator=None):
            Path(out_docx).write_bytes(original_docx)
            return "Και και τότε."
        try:
            with mock.patch.object(main_mod, "translate_docx_in_place", side_effect=fake_in_place):
                asyncio.run(main_mod._run_translation(job.job_id, str(src), "docx", "english", "greek", output_path))
            j = get_job(job.job_id)
            self.assertEqual(j.status, "done")
            self.assertEqual(Path(j.output_path).read_bytes(), original_docx)
            self.assertEqual(j.refinement_report["status"], "inspected")
        finally:
            src.unlink(missing_ok=True)

    def test_audiobook_generation_triggers_stage_and_heals(self):
        import backend.tts_engine as tts
        job, out_dir = _new_test_job("test_refine_audio.txt", "txt")
        txt = out_dir / "test_refine_audio_translated_greek.txt"
        paragraphs = [f"Παράγραφος {i}. " + ("Αυτό είναι ένα δοκιμαστικό κείμενο. " * 30) for i in range(4)]
        txt.write_text("\n\n".join(paragraphs), encoding="utf-8")
        out_mp3 = out_dir / "test_refine_audio.mp3"
        calls = {}

        async def fake_tts(text, voice, output_path, **kw):
            n = calls.get(output_path, 0)
            calls[output_path] = n + 1
            # chunk 1 fails on its first attempt (simulated transient edge-tts outage)
            if output_path.endswith("chunk_000001.mp3") and n == 0:
                Path(output_path).write_bytes(b"")
            else:
                Path(output_path).write_bytes(MP3_FRAME * 3)

        with mock.patch.object(tts, "_tts_chunk_with_retry", side_effect=fake_tts):
            result = asyncio.run(tts.generate_audiobook(
                job_id=job.job_id, file_path=str(txt), file_type="txt", language="greek",
                voice_name="Nestoras (Male)", output_path=str(out_mp3), translated_text_path=str(txt),
            ))
        j = get_job(job.job_id)
        self.assertEqual(result, str(out_mp3))
        self.assertEqual(j.status, "done")
        self.assertGreaterEqual(len(calls), 2, "text must be split into several sections")
        self.assertEqual(j.refinement_report["status"], "healed")
        self.assertEqual(j.refinement_report["missing_sections"], [])
        self.assertEqual(out_mp3.stat().st_size >= len(calls) * len(MP3_FRAME) * 3, True)
        self.assertFalse((out_dir / f"tts_tmp_{job.job_id}").exists(), "temp chunks must be cleaned up")

    def test_audiobook_disabled_behaves_as_before(self):
        import backend.tts_engine as tts
        save_setting("final_refinement_enabled", False)
        job, out_dir = _new_test_job("test_refine_audio_off.txt", "txt")
        txt = out_dir / "t_translated_greek.txt"
        txt.write_text("Ένα σύντομο κείμενο.", encoding="utf-8")
        out_mp3 = out_dir / "t.mp3"

        async def fake_tts(text, voice, output_path, **kw):
            Path(output_path).write_bytes(MP3_FRAME * 2)

        with mock.patch.object(tts, "_tts_chunk_with_retry", side_effect=fake_tts), \
             mock.patch("backend.output_refiner.refine_audiobook_output_async") as never:
            asyncio.run(tts.generate_audiobook(
                job_id=job.job_id, file_path=str(txt), file_type="txt", language="greek",
                voice_name="Nestoras (Male)", output_path=str(out_mp3), translated_text_path=str(txt),
            ))
        never.assert_not_called()
        j = get_job(job.job_id)
        self.assertEqual(j.status, "done")
        self.assertEqual(j.current_step, "Audiobook ready!")


# ===========================================================================
# 6. HTTP API
# ===========================================================================

class TestRefinementAPI(_RefinementTestBase):
    @classmethod
    def setUpClass(cls):
        _ensure_server()

    def test_config_endpoint(self):
        status, data = _api("GET", "/refine/config")
        self.assertEqual(status, 200)
        self.assertIn("translation", data["supported_modes"])
        self.assertIn("audiobook", data["supported_modes"])
        self.assertFalse(data["uses_external_api"])

    def test_settings_toggle(self):
        status, _ = _api("POST", "/settings", {"final_refinement_enabled": False})
        self.assertEqual(status, 200)
        self.assertFalse(is_refinement_enabled())
        self.assertFalse(_api("GET", "/settings")[1]["final_refinement_enabled"])
        _api("POST", "/settings", {"final_refinement_enabled": True})
        self.assertTrue(is_refinement_enabled())

    def test_direct_text(self):
        status, data = _api("POST", "/refine", {"text": "Και και ήρθε γιά σίγουρα.", "target_lang": "greek"})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "refined")
        self.assertEqual(data["refined_text"], "Και ήρθε σίγουρα.")
        status2, data2 = _api("POST", "/refine", {"text": "Όλα καλά εδώ."})
        self.assertEqual(data2["status"], "verified_clean")
        self.assertEqual(data2["refined_text"], "Όλα καλά εδώ.")

    def test_job_translation_and_status_report(self):
        job, out_dir = _new_test_job()
        txt = out_dir / "test_refine_job_translated_greek.txt"
        txt.write_text("Ήρθε και και έφυγε γιά λίγο.", encoding="utf-8")
        update_job(job.job_id, output_path=str(txt), output_format="txt", mode="translate", status="done", target_lang="greek")
        status, data = _api("POST", "/refine", {"job_id": job.job_id})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["status"], "refined")
        self.assertEqual(txt.read_text(encoding="utf-8"), "Ήρθε και έφυγε για λίγο.")
        s_status, s_data = _api("GET", f"/status/{job.job_id}")
        self.assertEqual(s_status, 200)
        self.assertEqual(s_data["refinement_report"]["status"], "refined")

    def test_job_audiobook(self):
        job, out_dir = _new_test_job("test_refine_audio_api.txt")
        mp3 = out_dir / "test_refine_audio_api.mp3"
        mp3.write_bytes(MP3_FRAME * 6)
        update_job(job.job_id, output_path=str(mp3), mode="audiobook", status="done")
        status, data = _api("POST", "/refine", {"job_id": job.job_id, "mode": "audiobook"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["mode"], "audiobook")
        self.assertTrue(data["result"]["is_valid"])

    def test_path_traversal_and_foreign_files_rejected(self):
        job, out_dir = _new_test_job()
        with tempfile.TemporaryDirectory() as td:
            outside = Path(td) / "victim.mp3"
            outside.write_bytes(MP3_FRAME * 3)
            status, _ = _api("POST", "/refine", {"job_id": job.job_id, "mode": "audiobook", "file_path": str(outside)})
            self.assertEqual(status, 400)
            self.assertEqual(outside.read_bytes(), MP3_FRAME * 3, "files outside the job folder must never be modified")
            status2, _ = _api("POST", "/refine", {"job_id": job.job_id, "mode": "audiobook", "file_path": "../../../config/x.mp3"})
            self.assertIn(status2, (400, 404))
        status3, _ = _api("POST", "/refine", {"file_path": str(out_dir / "x.mp3"), "mode": "audiobook"})
        self.assertEqual(status3, 400)
        status4, _ = _api("POST", "/refine", {"job_id": "../etc", "mode": "translation"})
        self.assertEqual(status4, 400)

    def test_running_job_rejected_and_disabled_skips(self):
        job, out_dir = _new_test_job()
        (out_dir / "test_refine_job_translated_greek.txt").write_text("Και και.", encoding="utf-8")
        update_job(job.job_id, status="running")
        status, _ = _api("POST", "/refine", {"job_id": job.job_id})
        self.assertEqual(status, 409)
        status2, data2 = _api("POST", "/refine", {"text": "Και και.", "enabled": False})
        self.assertEqual(status2, 200)
        self.assertEqual(data2["status"], "skipped")


if __name__ == "__main__":
    unittest.main()



class TestGeminiCallImprovements(unittest.TestCase):
    """Adaptive request timeout, size-aware rate-limit estimate and optional cache gate in _call_gemini_api."""

    class _Resp:
        def __init__(self, text):
            self.status, self._text = 200, text
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def json(self, content_type=None):
            if self._text is None:
                return {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]}
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": self._text}]}}]}
        async def text(self):
            return ""

    class _Sess:
        def __init__(self, reply):
            self.reply, self.posts = reply, []
        def post(self, url, **kw):
            self.posts.append(kw)
            return TestGeminiCallImprovements._Resp(self.reply)
        def get(self, url, **kw):
            return TestGeminiCallImprovements._Resp(None)
        async def close(self):
            pass

    def setUp(self):
        import backend.ai_polisher as ap
        ap.reset_model_cache()
        ap._CACHED_API_KEY_HASH = None

    def test_timeout_scales_with_payload(self):
        import backend.ai_polisher as ap
        import uuid
        short, long_ = self._Sess("Σύντομο."), self._Sess("Μεγάλο.")
        asyncio.run(ap._call_gemini_api(f"Μικρό {uuid.uuid4()}", "REAL_KEY_T1", "Sys", session=short, bypass_cache=True))
        asyncio.run(ap._call_gemini_api("Α" * 24000 + str(uuid.uuid4()), "REAL_KEY_T1", "Sys", session=long_, bypass_cache=True))
        t_short = short.posts[0]["timeout"].total
        t_long = long_.posts[0]["timeout"].total
        self.assertTrue(45.0 <= t_short < 46.0, t_short)   # was a fixed 25 s before
        self.assertGreater(t_long, 120.0)
        self.assertLessEqual(t_long, 180.0)

    def test_cache_gate_allows_caching_non_greek_output(self):
        import backend.ai_polisher as ap
        import uuid
        content = f"English summary source {uuid.uuid4()}"
        reply = "This is a short English summary of the book with several plain words in it today."
        s1 = self._Sess(reply)
        asyncio.run(ap._call_gemini_api(content, "REAL_KEY_C1", "Summarise", session=s1))
        asyncio.run(ap._call_gemini_api(content, "REAL_KEY_C1", "Summarise", session=s1))
        self.assertEqual(len(s1.posts), 2, "default Greek gate must not cache English output (unchanged behaviour)")
        content2 = f"English summary source {uuid.uuid4()}"
        s2 = self._Sess(reply)
        gate = lambda o: bool(o.strip())
        asyncio.run(ap._call_gemini_api(content2, "REAL_KEY_C1", "Summarise", session=s2, cache_gate=gate))
        out = asyncio.run(ap._call_gemini_api(content2, "REAL_KEY_C1", "Summarise", session=s2, cache_gate=gate))
        self.assertEqual(len(s2.posts), 1, "with a cache gate the second identical call is served from cache")
        self.assertEqual(out, reply)
