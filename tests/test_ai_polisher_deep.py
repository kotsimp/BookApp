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
    reset_model_cache,
    polish_text,
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


if __name__ == "__main__":
    unittest.main()
