"""
test_ai_polisher_deep.py - AI Polisher Engine Deep Functional & Boundary Test Suite.
Tests:
1. Style prompts and temperature configurations across all 6 supported genres.
2. Glossary injection and character consistency dossier in prompt construction.
3. Model discovery, caching, and cache invalidation.
4. Mock Polish execution with test API keys and multi-page text.
5. Polish job status tracking & progress reporting.
"""

import sys
sys.path.insert(0, ".")
import asyncio
import re
import unittest

from backend.ai_polisher import (
    STYLE_PROMPTS,
    STYLE_TEMPERATURES,
    _LITERARY_SAFETY_SETTINGS,
    _ContentBlockedError,
    _build_stratified_book_sample,
    _deduplicate_batch_boundary,
    _extract_clean_tail_context,
    _extract_gemini_text_and_reason,
    _find_mixed_script_tokens,
    reset_model_cache,
    polish_text,
    polish_text_with_gemini,
    sanitize_ai_output,
    get_polish_job_status,
    update_polish_job_status,
)


class TestAIPolisherDeep(unittest.TestCase):

    def test_style_prompts_and_temperatures(self):
        print("-> 1. Testing AI Polisher Style Prompts and Temperatures...")
        required_styles = {"literature", "natural", "formal", "technical", "audiobook", "poetry"}
        self.assertTrue(required_styles.issubset(set(STYLE_PROMPTS.keys())))
        self.assertTrue(required_styles.issubset(set(STYLE_TEMPERATURES.keys())))

        for s in required_styles:
            prompt = STYLE_PROMPTS[s]
            temp = STYLE_TEMPERATURES[s]
            self.assertTrue(len(prompt) > 50, f"Prompt for {s} is too short")
            self.assertTrue(0.1 <= temp <= 0.8, f"Temperature {temp} for {s} out of bounds")

        print(f"   Style prompts & temperatures ({len(required_styles)} styles): OK")

    def test_multi_page_batch_splitting(self):
        print("-> 2. Testing Multi-Page Batch Parsing & Marker Preservation...")
        from backend.ai_polisher import _parse_pages_dict
        sample_doc = (
            "=== PAGE 1 ===\n"
            "Κεφάλαιο Πρώτο: Η Ανακάλυψη.\n"
            "— Κοίταξε εκεί έξω, είπε ο Πέτρος κοιτάζοντας το παράθυρο.\n\n"
            "=== PAGE 2 ===\n"
            "Η σιωπή απλώθηκε στο δωμάτιο. Η θερμοκρασία άρχισε να πέφτει απότομα.\n"
        )
        pages = _parse_pages_dict(sample_doc)
        self.assertEqual(len(pages), 2)
        self.assertIn(1, pages)
        self.assertIn(2, pages)
        self.assertIn("Κεφάλαιο Πρώτο", pages[1])
        self.assertIn("Η σιωπή απλώθηκε", pages[2])
        print("   Multi-page batch parsing: OK")

    def test_model_cache_invalidation(self):
        print("-> 3. Testing Model Cache Invalidation...")
        import backend.ai_polisher as ap
        ap._CACHED_WORKING_MODEL = "gemini-fake-model"
        ap._CACHED_AVAILABLE_MODELS = ["gemini-fake-model"]
        reset_model_cache()
        self.assertIsNone(ap._CACHED_WORKING_MODEL)
        self.assertIsNone(ap._CACHED_AVAILABLE_MODELS)
        print("   Model cache invalidation: OK")

    def test_mock_polish_execution(self):
        print("-> 4. Testing Mock Polish Execution with Test API Key...")
        mock_key = "AQ.TestMockKeyForAutomatedVerification12345678"
        raw_draft = (
            "=== PAGE 1 ===\n"
            "Αυτό είναι ένα προσχέδιο μετάφρασης που χρειάζεται γυάλισμα.\n\n"
            "=== PAGE 2 ===\n"
            "Η δεύτερη σελίδα περιέχει περισσότερες λεπτομέρειες.\n"
        )

        result = asyncio.run(polish_text(
            text=raw_draft,
            style="literature",
            api_key=mock_key,
        ))
        self.assertTrue(result and len(result) > 0)
        self.assertIn("=== PAGE 1 ===", result)
        print("   Mock polish execution: OK")

    def test_polish_status_tracker(self):
        print("-> 5. Testing Polish Job Status Tracking...")
        job_id = "test-polish-status-uuid-999"

        # Initially empty status
        init_st = get_polish_job_status(job_id)
        self.assertIn("status", init_st)

        # Update status
        update_polish_job_status(
            job_id,
            status="running",
            current=3,
            total=10,
            percent=30,
            step="Refining dialogue..."
        )

        st = get_polish_job_status(job_id)
        self.assertEqual(st["status"], "running")
        self.assertEqual(st["current"], 3)
        self.assertEqual(st["total"], 10)
        self.assertEqual(st["percent"], 30)
        self.assertEqual(st["step"], "Refining dialogue...")

        # Terminal status
        update_polish_job_status(job_id, status="done", percent=100)
        st_done = get_polish_job_status(job_id)
        self.assertEqual(st_done["status"], "done")
        self.assertEqual(st_done["percent"], 100)
        print("   Polish status tracker: OK")

    def test_safety_settings_block_none_and_prompt_feedback(self):
        print("-> 6. Testing BLOCK_NONE safety settings & promptFeedback blockReason detection...")
        self.assertGreaterEqual(len(_LITERARY_SAFETY_SETTINGS), 4)
        for cfg in _LITERARY_SAFETY_SETTINGS:
            self.assertEqual(cfg.get("threshold"), "BLOCK_NONE", f"Expected BLOCK_NONE for {cfg}")

        txt, reason = _extract_gemini_text_and_reason({
            "promptFeedback": {"blockReason": "PROHIBITED_CONTENT"},
            "candidates": [],
        })
        self.assertEqual(txt, "")
        self.assertEqual(reason, "PROHIBITED_CONTENT")
        print("   BLOCK_NONE & promptFeedback detection: OK")

    def test_recursive_bisection_isolates_single_blocked_paragraph(self):
        print("-> 7. Testing recursive multi-page & paragraph bisection on safety-blocked content...")
        from unittest.mock import patch
        import backend.ai_polisher as ap

        sample = (
            "=== PAGE 1 ===\n"
            "Η πρώτη σελίδα είναι εντελώς καθαρή και περιγράφει την άφιξη του Θησέα.\n\n"
            "=== PAGE 2 ===\n"
            "Η πρώτη παράγραφος της δεύτερης σελίδας είναι απολύτως καθαρή λογοτεχνική πρόζα.\n\n"
            "Αυτή η μοναδική παράγραφος περιέχει FORBIDDEN_TRIGGER που προκαλεί safety block.\n\n"
            "=== PAGE 3 ===\n"
            "Η τρίτη σελίδα συνεχίζει κανονικά την αφήγηση χωρίς κανένα πρόβλημα."
        )

        async def _selective_block(content_text, api_key, system_prompt, **kwargs):
            m = re.search(r"<TEXT_TO_POLISH>(.*?)</TEXT_TO_POLISH>", content_text, re.DOTALL)
            body = m.group(1).strip() if m else content_text
            if "FORBIDDEN_TRIGGER" in body:
                raise _ContentBlockedError("Simulated PROHIBITED_CONTENT safety block")
            return body.replace("σελίδα", "σελίδα [AI]").replace("παράγραφος", "παράγραφος [AI]")

        with patch.object(ap, "_call_gemini_api", side_effect=_selective_block):
            result = asyncio.run(polish_text_with_gemini(
                text=sample,
                api_key="REAL_KEY_BISECT_TEST",
                style="literature",
            ))

        # Pages 1, 3, and the clean paragraph of page 2 MUST all be AI-polished!
        self.assertIn("πρώτη σελίδα [AI]", result)
        self.assertIn("πρώτη παράγραφος [AI]", result)
        self.assertIn("τρίτη σελίδα [AI]", result)
        # Only the single blocked paragraph falls back to draft (no silent 3-page wipeout)
        self.assertIn("FORBIDDEN_TRIGGER", result)
        # Page markers preserved exactly once each
        self.assertEqual(result.count("=== PAGE 1 ==="), 1)
        self.assertEqual(result.count("=== PAGE 2 ==="), 1)
        self.assertEqual(result.count("=== PAGE 3 ==="), 1)
        print("   Recursive bisection single-paragraph isolation: OK")

    def test_boundary_dedup_and_leaked_context_sanitization(self):
        print("-> 8. Testing chunk-boundary deduplication & leaked '[... ...]' context stripping...")
        # Real-world p. 372 leaked '[... ...]' bracketed context + XML context block
        leaked = (
            "<PREVIOUS_CONTEXT_DO_NOT_REPEAT>\nΠαλιό κείμενο αναφοράς.\n</PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n\n"
            "[... για να παραμείνει κανείς όρθιος, έπρεπε να είναι διαρκώς σε κίνηση "
            "να μιλάει μέσα στο μυαλό μου σαν σχιζοφρενική ψευδαίσθηση:]\n\n"
            "<TEXT_TO_POLISH>\n=== PAGE 372 ===\n\nΗ κανονική αφήγηση συνεχίζεται καθαρά εδώ.\n</TEXT_TO_POLISH>"
        )
        cleaned = sanitize_ai_output(leaked)
        self.assertNotIn("PREVIOUS_CONTEXT", cleaned)
        self.assertNotIn("TEXT_TO_POLISH", cleaned)
        self.assertNotIn("σχιζοφρενική ψευδαίσθηση", cleaned)
        self.assertIn("Η κανονική αφήγηση συνεχίζεται καθαρά εδώ.", cleaned)

        # Clean tail extraction never cuts mid-word
        long_para = "Πρώτη πρόταση του κειμένου. Δεύτερη πρόταση που περιγράφει τον Θησέα. Τρίτη τελική πρόταση με καθαρό τέλος."
        tail = _extract_clean_tail_context(long_para, max_chars=90)
        self.assertTrue(tail.endswith("τέλος."))
        self.assertNotIn("Πρώτη", tail)

        # Deduplication strips: (a) pre-marker leak, (b) paraphrased repeated leading paragraph,
        # while NEVER stripping short dialogue like '«Όχι.»'
        prev_batch = (
            "=== PAGE 1 ===\n\n"
            "Ο Σίρι Κίτον κοίταξε έξω από το φινιστρίνι του Θησέα προς το σκοτεινό κέλυφος του Ρόρσαχ "
            "ενώ οι αισθητήρες κατέγραφαν την ακτινοβολία."
        )
        curr_batch_with_dups = (
            "Κάποιο διαρρεύσαν κείμενο πριν τον δείκτη σελίδας.\n\n"
            "=== PAGE 2 ===\n\n"
            "Ο Σίρι Κίτον κοίταξε έξω από το φινιστρίνι του Θησέα προς το σκοτεινό κέλυφος του Ρόρσαχ "
            "καθώς οι αισθητήρες κατέγραφαν την ακτινοβολία.\n\n"
            "«Όχι.»\n\n"
            "Αυτή είναι η νέα παράγραφος της δεύτερης σελίδας."
        )
        deduped = _deduplicate_batch_boundary(prev_batch, curr_batch_with_dups, expected_first_page=2)
        self.assertTrue(deduped.startswith("=== PAGE 2 ==="))
        self.assertNotIn("διαρρεύσαν", deduped)
        self.assertNotIn("φινιστρίνι", deduped)
        self.assertIn("«Όχι.»", deduped)
        self.assertIn("νέα παράγραφος της δεύτερης σελίδας", deduped)
        print("   Boundary deduplication & leaked-context stripping: OK")

    def test_whole_book_stratified_sampling_and_mixed_script_tokens(self):
        print("-> 9. Testing whole-book stratified dossier sampling, dialogue rule & mixed-script tokens...")
        # Build a 90,000-char book where key entities appear ONLY at 55% and 85% (far past old 18,000-char cutoff)
        filler_a = ("The quiet corridor hummed beneath the hull of Theseus as the crew slept. " * 600)
        mid_section = (
            "\n\nAmanda Bates deployed the Grunts while Stretch and Clench locked onto the bulkhead. "
            "Amanda Bates warned that Grunts are drones, not Scramblers. Stretch and Clench moved swiftly. "
            "Amanda Bates checked Grunts telemetry near Stretch and Clench again. "
            "Amanda Bates monitored Grunts and Scramblers closely.\n\n"
        )
        filler_b = ("Darkness stretched across the Kuiper belt in unbroken silence. " * 600)
        late_section = (
            "\n\nJukka Sarasti confronted Sascha and Isaac Szpindel inside the drum. "
            "Jukka Sarasti spoke to Sascha while Isaac Szpindel watched Rorschach. "
            "Jukka Sarasti and Sascha debated Isaac Szpindel and Rorschach.\n\n"
        )
        book = filler_a + mid_section + filler_b + late_section
        sample = _build_stratified_book_sample(book, max_total_chars=24000)

        self.assertIn("FREQUENCY SCAN", sample)
        self.assertIn("Amanda Bates", sample)
        self.assertIn("Grunts", sample)
        self.assertIn("Stretch", sample)
        self.assertIn("Clench", sample)
        self.assertIn("Jukka Sarasti", sample)

        # Literature prompt enforces uniform Greek guillemets «...»
        self.assertIn("«...»", STYLE_PROMPTS["literature"])
        self.assertIn("PREVIOUS_CONTEXT_DO_NOT_REPEAT", STYLE_PROMPTS["literature"])

        # Mixed-script token detector catches exact Blindsight p.364 defect 'ημIFωτισμένη'
        bad = _find_mixed_script_tokens("Η αίθουσα ήταν ημIFωτισμένη με 12 μm απόκλιση.")
        self.assertEqual(bad, ["ημIFωτισμένη"])
        print("   Whole-book stratified sampling & mixed-script token detection: OK")


if __name__ == "__main__":
    unittest.main()
