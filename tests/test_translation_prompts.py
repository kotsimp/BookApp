"""
test_translation_prompts.py - AI Polish / AI translation quality upgrade (backend/translation_prompts.py).

Verifies:
1. Prompts are generic (no title-specific terminology hard-coded from one novel).
2. Direct single-pass translation uses a dedicated translate-from-source prompt (not the polish prompt), with
   fidelity / anti-embellishment rules and the English->Greek fault checklist; English targets get English rules.
3. Polish is language-aware (English targets no longer receive Greek-only instructions).
4. Audiobook/poetry script prompts forbid paraphrasing and cover spoken-form rules (case agreement, Roman numerals,
   times, all-caps emphasis); poetry keeps verse lines.
5. The whole-book dossier is target-aware, adds a style sheet (tense, person, forms of address), and has a
   pronunciation mode used for Greek audiobook scripts with foreign names.
6. Direct-translation checkpoints carry a signature: stale checkpoints from other settings are discarded,
   matching ones are resumed.
7. sanitize_ai_output() normalises Unicode (NFC) so polytonic/decomposed accents become monotonic code points.
8. The final local refinement restores accents dropped from capitalised words ('Ηταν' -> 'Ήταν').
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend.ai_polisher as ap
from backend import translation_prompts as tp
from backend.job_manager import create_job, cleanup_test_jobs

_TITLE_SPECIFIC = ("synthesist", "scrambler", "σκράμπλερ", "Rorschach", "Ρόρσαχ", "Theseus", "συνθετιστής",
                   "ψηφιακή μεταφόρτωση", "Keeton", "Sarasti")


class _Capture:
    """Records system prompts sent to the (mocked) Gemini call and echoes the content back."""

    def __init__(self, reply=None):
        self.prompts, self.contents, self.kwargs = [], [], []
        self.reply = reply

    async def __call__(self, content, api_key, system_prompt, session=None, temperature=0.25, **kw):
        self.prompts.append(system_prompt)
        self.contents.append(content)
        self.kwargs.append(kw)
        if self.reply is not None:
            return self.reply(content, system_prompt)
        import re
        m = re.search(r"<TEXT_TO_(?:TRANSLATE|POLISH)>\n(.*?)\n</TEXT_TO_", content, re.S)
        return m.group(1) if m else content


class TestPromptLibrary(unittest.TestCase):

    def test_prompts_are_generic(self):
        everything = list(tp.STYLE_PROMPTS.values()) + [
            tp.build_direct_translation_prompt("english", "greek", s) for s in ("literature", "natural", "formal", "technical")
        ] + [tp.build_dossier_prompt("greek"), tp.build_dossier_prompt("english"), tp.ENGLISH_POLISH_PROMPT]
        for p in everything:
            for term in _TITLE_SPECIFIC:
                self.assertNotIn(term, p, f"title-specific term '{term}' must not be hard-coded in prompts")

    def test_direct_prompt_is_a_translation_prompt_with_fidelity_rules(self):
        p = tp.build_direct_translation_prompt("english", "greek", "literature")
        self.assertIn("Μετάφρασε ΑΠΕΥΘΕΙΑΣ από το πρωτότυπο", p)
        self.assertNotIn("Επιμελήσου την ακόλουθη ελληνική μετάφραση", p)   # no polish instructions inside
        for rule in ("ΠΙΣΤΟΤΗΤΑ", "«ωραιοποιείς»", "παραλείπουν το υποκείμενο", "κτητικών", "αόριστο άρθρο",
                     "ο οποίος", "ψευδόφιλα", "Title Case", "εσύ/εσείς", "=== PAGE X ===", "«...»"):
            self.assertIn(rule, p, rule)
        self.assertNotIn("ΔΙΑΛΟΓΟΙ:", tp.build_direct_translation_prompt("english", "greek", "technical"),
                         "the literary dialogue convention applies to literature only")
        en = tp.build_direct_translation_prompt("greek", "english", "literature")
        self.assertIn("into English", en)
        self.assertIn("FIDELITY", en)
        self.assertNotIn("ελληνικούς χαρακτήρες", en)

    def test_polish_prompt_is_language_aware(self):
        self.assertIs(tp.build_polish_prompt("literature", "greek"), tp.STYLE_PROMPTS["literature"])
        self.assertEqual(tp.build_polish_prompt("literature", "english"), tp.ENGLISH_POLISH_PROMPT)
        self.assertEqual(tp.build_polish_prompt("formal", "en"), tp.ENGLISH_POLISH_PROMPT)
        self.assertIs(tp.build_polish_prompt("audiobook", "english"), tp.STYLE_PROMPTS["audiobook"])
        lit = tp.STYLE_PROMPTS["literature"]
        self.assertIn("ΕΛΑΧΙΣΤΗ ΑΝΑΓΚΑΙΑ ΠΑΡΕΜΒΑΣΗ", lit)
        self.assertIn("πρωτότυπο κείμενο", lit)

    def test_audiobook_and_poetry_prompts(self):
        ab = tp.STYLE_PROMPTS["audiobook"]
        for rule in ("ΜΗΝ παραφράζεις", "ΦΩΝΗΤΙΚΗ ΑΠΟΔΟΣΗ", "ΟΛΟΓΡΑΦΗ ΑΝΑΠΤΥΞΗ", "πτώση", "βαθμοί Κελσίου",
                     "Κεφάλαιο IV", "10:30", "ΚΕΦΑΛΑΙΑ", "Μητρώο Προφοράς", "=== PAGE"):
            self.assertIn(rule, ab, rule)
        self.assertNotIn("περίπλοκες δευτερεύουσες προτάσεις", ab, "audiobook prompt must not invite restructuring")
        po = tp.STYLE_PROMPTS["poetry"]
        self.assertIn("ΜΗΝ ενώνεις", po)
        self.assertIn("ΧΩΡΙΣ να αλλάξεις", po)

    def test_dossier_prompts(self):
        el = tp.build_dossier_prompt("greek", "translation")
        self.assertIn("ΦΥΛΛΟ ΥΦΟΥΣ", el)
        self.assertIn("(εσύ)", el)
        en = tp.build_dossier_prompt("english", "translation")
        self.assertIn("STYLE SHEET", en)
        self.assertIn("into English", en)
        pr = tp.build_dossier_prompt("greek", "pronunciation")
        self.assertIn("ΜΗΤΡΩΟ ΠΡΟΦΟΡΑΣ", pr)
        self.assertIn("ΠΡΟΦΟΡΑΣ", tp.dossier_header("pronunciation"))
        self.assertIn("STYLE SHEET", tp.dossier_header("translation", "english"))

    def test_style_prompt_contract_unchanged(self):
        self.assertTrue({"literature", "natural", "formal", "technical", "audiobook", "poetry"} <= set(ap.STYLE_PROMPTS))
        self.assertIs(ap.STYLE_PROMPTS, tp.STYLE_PROMPTS)


class TestPipelineUsesNewPrompts(unittest.TestCase):

    def tearDown(self):
        cleanup_test_jobs()

    def test_dossier_extraction_mode_and_target(self):
        cap = _Capture(reply=lambda c, p: "- Whitfield -> Γουίτφιλντ\n- NASA -> Νάσα")
        with mock.patch.object(ap, "_call_gemini_api", new=cap):
            d1 = asyncio.run(ap._extract_entity_dossier("Text " * 50, "REAL_KEY", target_lang="greek", mode="pronunciation"))
            asyncio.run(ap._extract_entity_dossier("Text " * 50, "REAL_KEY", target_lang="english"))
        self.assertIn("Γουίτφιλντ", d1)
        self.assertIn("ΜΗΤΡΩΟ ΠΡΟΦΟΡΑΣ", cap.prompts[0])
        self.assertIn("STYLE SHEET", cap.prompts[1])
        self.assertTrue(all(k.get("cache_gate") for k in cap.kwargs))

    def test_polish_for_english_target_uses_english_prompt(self):
        cap = _Capture()
        with mock.patch.object(ap, "_call_gemini_api", new=cap):
            out = asyncio.run(ap.polish_text_with_gemini("The draft text that needs editing.", api_key="REAL_KEY",
                                                         style="literature", target_lang="english"))
        self.assertTrue(cap.prompts)
        self.assertIn("Copy-edit the following English translation", cap.prompts[0])
        self.assertNotIn("ελληνική μετάφραση", cap.prompts[0])
        self.assertIn("draft text", out)

    def test_greek_audiobook_script_gets_pronunciation_register(self):
        long_text = "\n\n".join(
            f"Ο Jonathan Whitfield έφτασε στο Houston για τη συνάντηση αριθμός {i}, όπως είχε υποσχεθεί στη NASA." * 3
            for i in range(120))
        cap = _Capture()
        with mock.patch.object(ap, "_call_gemini_api", new=cap):
            asyncio.run(ap.polish_text_with_gemini(long_text, api_key="REAL_KEY", style="audiobook", target_lang="greek"))
        self.assertTrue(any("ΜΗΤΡΩΟ ΠΡΟΦΟΡΑΣ" in p and "Είσαι επιμελητής εκφώνησης" in p for p in cap.prompts),
                        "a pronunciation register must be extracted for long Greek scripts with foreign names")
        script_prompts = [p for p in cap.prompts if "Spoken Word & Neural TTS" in p]
        self.assertTrue(script_prompts and all("(PRONUNCIATION REGISTER)" in p for p in script_prompts))

    def _direct(self, cap, out_dir: Path, src: Path, target="greek", style="literature"):
        job = create_job(str(src), "test_prompts_direct.txt", "txt")
        out = out_dir / "test_prompts_direct_translated.txt"
        with mock.patch.object(ap, "_call_gemini_api", new=cap):
            asyncio.run(ap.translate_and_polish_direct_with_gemini(job.job_id, str(src), "txt", "english", target,
                                                                    str(out), "REAL_KEY", style=style))
        return out.read_text(encoding="utf-8")

    def test_direct_translation_uses_translation_prompt_and_signed_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "test_prompts_direct.txt"
            src.write_text("Marta opened the letter.\n\nShe read it twice.", encoding="utf-8")
            # A stale checkpoint (other settings) must be ignored
            (td / ".direct_ai_checkpoint.json").write_text(json.dumps(
                {"sig": "deadbeefdeadbeef", "batches": {"0": "STALE BATCH FROM ANOTHER RUN"}, "entity_dossier": ""}),
                encoding="utf-8")
            cap = _Capture(reply=lambda c, p: "=== PAGE 1 ===\nΗ Μάρτα άνοιξε το γράμμα.\n\nΤο διάβασε δύο φορές.")
            text = self._direct(cap, td, src)
            self.assertNotIn("STALE", text)
            self.assertIn("Η Μάρτα άνοιξε το γράμμα", text)
            self.assertTrue(cap.prompts and "Μετάφρασε ΑΠΕΥΘΕΙΑΣ από το πρωτότυπο" in cap.prompts[0])

    def test_matching_checkpoint_is_resumed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "test_prompts_direct.txt"
            src.write_text("Marta opened the letter.", encoding="utf-8")
            # First run creates nothing persistent (checkpoint removed on success); build the matching signature
            import hashlib
            full = "=== PAGE 1 ===\nMarta opened the letter."
            sig = hashlib.sha256(f"{tp.PROMPT_VERSION}::literature::english::greek::{len(full)}::{full[:2000]}".encode()).hexdigest()[:16]
            (td / ".direct_ai_checkpoint.json").write_text(json.dumps(
                {"sig": sig, "batches": {"0": "=== PAGE 1 ===\nΑΠΟΘΗΚΕΥΜΕΝΗ ΠΑΡΤΙΔΑ"}, "entity_dossier": ""}), encoding="utf-8")
            cap = _Capture(reply=lambda c, p: "=== PAGE 1 ===\nΝΕΑ ΜΕΤΑΦΡΑΣΗ")
            text = self._direct(cap, td, src)
            self.assertIn("ΑΠΟΘΗΚΕΥΜΕΝΗ ΠΑΡΤΙΔΑ", text)
            self.assertEqual(cap.prompts, [], "resumed batch must not be re-translated")


class TestOutputCleanup(unittest.TestCase):

    def test_sanitizer_normalises_unicode(self):
        out = ap.sanitize_ai_output("Ο Νίκος. Ήταν εκεί. Ήταν εδώ.")
        self.assertEqual(out, "Ο Νίκος. Ήταν εκεί. Ήταν εδώ.")
        self.assertNotIn("́", out)

    def test_refiner_restores_dropped_capital_accents(self):
        from backend.output_refiner import refine_text_content
        out, _, corr = refine_text_content("Ο Ντάνιελ έγνεψε. Ηταν υπομονετικός. Οταν ήρθε, Ετσι είπε.", "greek")
        self.assertEqual(out, "Ο Ντάνιελ έγνεψε. Ήταν υπομονετικός. Όταν ήρθε, Έτσι είπε.")
        self.assertTrue(any("capitalised" in c for c in corr))
        keep = "ΗΤΑΝ ΕΚΕΙ. Η Ηρα και ο Ομηρος."   # all-caps and real names are untouched
        self.assertEqual(refine_text_content(keep, "greek")[0], keep)



# ===========================================================================
# Maximum-quality revision pass (second AI pass against the original)
# ===========================================================================

class TestMaxQualityRevision(unittest.TestCase):

    ORIGINAL = "=== PAGE 1 ===\nMarta leaned against the door frame.\n\n=== PAGE 2 ===\nShe nearly jumped out of her skin."
    DRAFT = "=== PAGE 1 ===\nΗ Μάρτα ακούμπησε στο κάσα της πόρτας.\n\n=== PAGE 2 ===\nΣχεδόν πετάχτηκε από τη θέση της."
    FIXED = {"κάσα": "Η Μάρτα ακούμπησε στην κάσα της πόρτας.", "θέση": "Κόντεψε να πεταχτεί από την τρομάρα της."}

    def tearDown(self):
        cleanup_test_jobs()

    def _files(self, td, draft=None):
        tr = Path(td) / "book_translated_greek.txt"
        orig = Path(td) / "book_original.txt"
        tr.write_text(draft or self.DRAFT, encoding="utf-8")
        orig.write_text(self.ORIGINAL, encoding="utf-8")
        return tr, orig

    def _reviser(self, transform=None, exc=None):
        seen = {"prompts": [], "contents": [], "policy": []}

        async def fake(content, api_key, system_prompt, session=None, temperature=0.25, **kw):
            seen["prompts"].append(system_prompt)
            seen["contents"].append(content)
            seen["policy"].append(ap._FULL_MODELS_ONLY.get())
            seen.setdefault("temps", []).append(temperature)
            if exc:
                raise exc
            import re
            m = re.search(r"<DRAFT_TO_POLISH>\n(.*?)\n</DRAFT_TO_POLISH>", content, re.S)
            draft = m.group(1) if m else content
            if transform:
                return transform(draft)
            for key, line in self.FIXED.items():
                draft = "\n".join(line if key in ln else ln for ln in draft.split("\n"))
            return draft
        return fake, seen

    def _run(self, fake, tr, orig, key="REAL_KEY"):
        with mock.patch.object(ap, "_call_gemini_api", new=fake):
            return asyncio.run(ap.revise_translation_against_source("test_rev", str(tr), str(orig), key, "greek", "literature"))

    def test_revision_prompt(self):
        p = tp.build_revision_prompt("greek")
        for rule in ("ΠΡΟΤΑΣΗ ΠΡΟΣ ΠΡΟΤΑΣΗ", "ΛΑΘΗ ΝΟΗΜΑΤΟΣ", "ΠΑΡΑΛΕΙΨΕΙΣ Ή ΠΡΟΣΘΗΚΕΣ", "ΓΡΑΜΜΑΤΙΚΗ ΣΥΜΦΩΝΙΑ",
                     "ΚΑΝΟΝΑΣ ΑΝΑΘΕΩΡΗΤΗ", "ΑΝΕΠΑΦΟ", "SOURCE_REFERENCE", "=== PAGE X ==="):
            self.assertIn(rule, p, rule)
        self.assertNotIn("κάσα", p)            # no examples taken from the evaluation passage
        self.assertNotIn("out of her skin", p)
        self.assertIn("SENTENCE BY SENTENCE", tp.build_revision_prompt("english"))

    def test_revision_applies_fixes_with_full_models_only(self):
        with tempfile.TemporaryDirectory() as td:
            tr, orig = self._files(td)
            fake, seen = self._reviser()
            rep = self._run(fake, tr, orig)
            self.assertEqual(rep["status"], "revised", rep)
            out = tr.read_text(encoding="utf-8")
            self.assertIn("στην κάσα", out)
            self.assertIn("Κόντεψε να πεταχτεί", out)
            self.assertIn("=== PAGE 2 ===", out)
            self.assertTrue(seen["prompts"] and all("ΚΑΝΟΝΑΣ ΑΝΑΘΕΩΡΗΤΗ" in p for p in seen["prompts"]))
            self.assertTrue(all("<SOURCE_REFERENCE>" in c and "Marta" in c for c in seen["contents"]))
            self.assertTrue(all(seen["policy"]), "revision calls must run under the full-models-only policy")
            self.assertTrue(all(t <= 0.15 for t in seen["temps"]))
            self.assertFalse(ap._FULL_MODELS_ONLY.get(), "policy must be reset afterwards")
            self.assertEqual([p.name for p in Path(td).iterdir() if "revision-tmp" in p.name], [])

    def test_guards_keep_first_pass(self):
        from backend.ai_polisher import DailyQuotaExhaustedError
        cases = [
            (dict(transform=lambda d: d.replace("=== PAGE 2 ===", "=== PAGE 3 ===")), "page_markers_changed"),
            (dict(transform=lambda d: d + "\n\n" + d + "\n\n" + d), None),          # length / page guard
            (dict(exc=DailyQuotaExhaustedError("no full model")), "quota_exhausted"),
            (dict(exc=PermissionError("bad key")), "auth_failed"),
        ]
        for kwargs, reason in cases:
            with tempfile.TemporaryDirectory() as td:
                tr, orig = self._files(td)
                fake, _ = self._reviser(**kwargs)
                rep = self._run(fake, tr, orig)
                self.assertEqual(rep["status"], "error", rep)
                if reason:
                    self.assertEqual(rep["reason"], reason)
                self.assertEqual(tr.read_text(encoding="utf-8"), self.DRAFT, "first-pass translation must be kept")
                self.assertFalse(ap._FULL_MODELS_ONLY.get())

    def test_skips_and_clean(self):
        with tempfile.TemporaryDirectory() as td:
            tr, orig = self._files(td)
            fake, seen = self._reviser(transform=lambda d: d)
            self.assertEqual(self._run(fake, tr, orig)["status"], "verified_clean")
            self.assertEqual(self._run(fake, tr, orig, key="")["reason"], "no_api_key")
            rep = self._run(fake, tr, Path(td) / "missing_original.txt")
            self.assertEqual(rep["reason"], "missing_files")

    def test_full_models_only_policy_filters_lite(self):
        class _Resp:
            def __init__(self, data): self.status, self._d = 200, data
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def json(self, content_type=None): return self._d
            async def text(self): return ""

        class _Sess:
            def __init__(self, models): self.models, self.urls = models, []
            def get(self, url, **kw):
                return _Resp({"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]} for m in self.models]})
            def post(self, url, **kw):
                self.urls.append(url)
                return _Resp({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Αναθεωρημένο κείμενο."}]}}]})
            async def close(self): pass

        import uuid
        ap.reset_model_cache(); ap._CACHED_API_KEY_HASH = None
        lite_only = _Sess(["gemini-2.5-flash-lite", "gemma-4-31b-it"])
        tok = ap._FULL_MODELS_ONLY.set(True)
        try:
            with self.assertRaises(ap.DailyQuotaExhaustedError):
                asyncio.run(ap._call_gemini_api(f"x {uuid.uuid4()}", "REAL_KEY_FM", "Sys", session=lite_only, bypass_cache=True))
            self.assertEqual(lite_only.urls, [], "no Lite/Gemma model may be called under the policy")
            ap.reset_model_cache(); ap._CACHED_API_KEY_HASH = None
            mixed = _Sess(["gemini-2.5-flash-lite", "gemini-2.5-flash"])
            asyncio.run(ap._call_gemini_api(f"y {uuid.uuid4()}", "REAL_KEY_FM2", "Sys", session=mixed, bypass_cache=True))
            self.assertTrue(mixed.urls and all("lite" not in u for u in mixed.urls))
        finally:
            ap._FULL_MODELS_ONLY.reset(tok)
            ap.reset_model_cache()

    def _pipeline(self, ai_polish, max_quality, key="test-key", revise_error=None):
        import backend.main as main_mod
        job = create_job("", "test_maxq_book.pdf", "pdf")
        out_dir = main_mod._job_output_dir(job.job_id)
        src = out_dir.parent.parent / "uploads" / f"test_maxq_{job.job_id}.pdf"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"%PDF-1.4")
        output_path = str(out_dir / f"{src.stem}_translated_greek.txt")
        from backend.job_manager import update_job, get_job
        update_job(job.job_id, output_format="txt", layout_mode="standard", status="running", max_quality=max_quality)
        calls = []

        async def fake_direct(job_id, file_path, file_type, source_lang, target_lang, output_path, api_key, style="literature", quota_behavior="wait"):
            Path(output_path).write_text(self.DRAFT, encoding="utf-8")
            (Path(output_path).parent / f"{Path(file_path).stem}_original.txt").write_text(self.ORIGINAL, encoding="utf-8")

        async def fake_revise(job_id, translated_path, original_path, api_key, **kw):
            calls.append((translated_path, original_path))
            if revise_error:
                raise revise_error
            Path(translated_path).write_text(self.DRAFT.replace("στο κάσα", "στην κάσα"), encoding="utf-8")
            return {"status": "revised", "changed_lines": 1}

        async def fake_td(job_id, file_path, file_type, source_lang, target_lang, output_path, style=None, **kw):
            Path(output_path).write_text(self.DRAFT, encoding="utf-8")

        try:
            with mock.patch("backend.ai_polisher.translate_and_polish_direct_with_gemini", side_effect=fake_direct), \
                 mock.patch("backend.ai_polisher.revise_translation_against_source", side_effect=fake_revise), \
                 mock.patch.object(main_mod, "translate_document", side_effect=fake_td), \
                 mock.patch("backend.gemini_key_pool.resolve_gemini_api_key", return_value=key), \
                 mock.patch("backend.parsers.detect_is_graphic_novel", return_value={"is_comic": False, "is_scanned": False}):
                asyncio.run(main_mod._run_translation(job.job_id, str(src), "pdf", "english", "greek", output_path, ai_polish))
        finally:
            src.unlink(missing_ok=True)
        return get_job(job.job_id), output_path, calls

    def test_pipeline_runs_revision_before_export_only_when_requested(self):
        job, out, calls = self._pipeline(ai_polish=True, max_quality=True)
        self.assertEqual(job.status, "done")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].endswith("_original.txt"))
        self.assertEqual(job.revision_report["status"], "revised")
        self.assertIn("στην κάσα", Path(job.output_path).read_text(encoding="utf-8"), "export must contain the revision")
        job2, _, calls2 = self._pipeline(ai_polish=True, max_quality=False)
        self.assertEqual(calls2, [])
        self.assertIsNone(job2.revision_report)
        job3, _, calls3 = self._pipeline(ai_polish=False, max_quality=True)
        self.assertEqual(calls3, [])
        self.assertEqual(job3.revision_report["reason"], "requires_ai_polish_and_key")

    def test_revision_crash_never_fails_job(self):
        job, out, calls = self._pipeline(ai_polish=True, max_quality=True, revise_error=RuntimeError("boom"))
        self.assertEqual(len(calls), 1, "the revision must have been attempted")
        self.assertEqual(job.status, "done")
        self.assertIsNone(job.error)
        self.assertEqual(job.revision_report, {"status": "error", "reason": "ai_failed"})
        self.assertIn("στο κάσα", Path(job.output_path).read_text(encoding="utf-8"), "first-pass translation exported")

    def test_refiner_article_final_nu(self):
        from backend.output_refiner import refine_text_content
        out, _, _ = refine_text_content("Ακουμπισμένος στη κάσα. Είδε τη πόρτα και τη Μαρία. Στη άκρη.", "greek")
        self.assertEqual(out, "Ακουμπισμένος στην κάσα. Είδε την πόρτα και τη Μαρία. Στην άκρη.")


if __name__ == "__main__":
    unittest.main()
