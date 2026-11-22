"""
test_database_and_cache.py - Unit & Functional Tests for SQLite Database, Persistence & Semantic Cache.
Tests:
1. Schema initialization and index creation.
2. Job persistence, retrieval, listing, and updates.
3. Cache key computation, hit counters, and semantic cache operations.
4. JobManager integration with SQLite across mock memory restarts.
5. Temp storage cleanup routine.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import time
import unittest
from pathlib import Path

from backend.database import (
    init_db,
    db_save_job,
    db_get_job,
    db_list_jobs,
    db_delete_job,
    compute_cache_key,
    db_get_cached_translation,
    db_set_cached_translation,
    db_get_cache_stats,
)
from backend.job_manager import create_job, update_job, get_job, _jobs
from backend.storage_cleaner import clean_temp_storage


class TestDatabaseAndCache(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_job_persistence_crud(self):
        print("-> 1. Testing SQLite Job CRUD Operations...")
        test_id = f"test-db-job-{int(time.time()*1000)}"
        job_data = {
            "job_id": test_id,
            "file_path": "/fake/path/book.pdf",
            "file_name": "book.pdf",
            "file_type": "pdf",
            "status": "running",
            "mode": "translate",
            "progress": 45,
            "current_step": "Translating page 4...",
            "total_chunks": 10,
            "done_chunks": 4,
            "created_at": time.time(),
            "updated_at": time.time(),
            "output_path": None,
            "output_format": "pdf",
            "layout_mode": "literature",
            "error": None,
            "metadata": {"author": "Test Author", "pages": 10},
        }

        db_save_job(job_data)
        saved = db_get_job(test_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["job_id"], test_id)
        self.assertEqual(saved["status"], "running")
        self.assertEqual(saved["progress"], 45)
        self.assertEqual(saved["layout_mode"], "literature")

        # Update
        job_data["status"] = "done"
        job_data["progress"] = 100
        job_data["output_path"] = "/fake/path/book_translated.pdf"
        db_save_job(job_data)

        updated = db_get_job(test_id)
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["progress"], 100)
        self.assertEqual(updated["output_path"], "/fake/path/book_translated.pdf")

        # List
        all_jobs = db_list_jobs(limit=50)
        self.assertTrue(any(j["job_id"] == test_id for j in all_jobs))

        # Delete
        deleted = db_delete_job(test_id)
        self.assertTrue(deleted)
        self.assertIsNone(db_get_job(test_id))
        print("   SQLite Job CRUD: OK")

    def test_semantic_translation_cache(self):
        print("-> 2. Testing Semantic Translation Cache & Hit Counter...")
        src_text = "The stars whispered secrets across the quiet void of space."
        src_lang = "english"
        tgt_lang = "greek"
        engine = "google"

        key = compute_cache_key(src_text, src_lang, tgt_lang, engine)
        self.assertIsInstance(key, str)
        self.assertEqual(len(key), 64)  # SHA-256 length

        # Initially not in cache
        init_val = db_get_cached_translation(key)
        # (Could have been cached in earlier run or test, so let's use a unique text)
        unique_src = f"Unique sentence {time.time()} - The clock ticked softly."
        unique_key = compute_cache_key(unique_src, src_lang, tgt_lang, engine)
        self.assertIsNone(db_get_cached_translation(unique_key))

        expected_trans = "Το ρολόι χτυπούσε απαλά."
        db_set_cached_translation(unique_key, unique_src, expected_trans, src_lang, tgt_lang, engine)

        # Retrieve from cache
        cached = db_get_cached_translation(unique_key)
        self.assertEqual(cached, expected_trans)

        # Second hit
        cached_2 = db_get_cached_translation(unique_key)
        self.assertEqual(cached_2, expected_trans)

        stats = db_get_cache_stats()
        self.assertGreaterEqual(stats["cached_entries"], 1)
        self.assertGreaterEqual(stats["total_hits"], 2)
        print(f"   Semantic Cache (Entries: {stats['cached_entries']}, Hits: {stats['total_hits']}): OK")

    def test_job_manager_sqlite_sync_and_restart(self):
        print("-> 3. Testing JobManager SQLite Synchronization across Restarts...")
        job = create_job("test_doc.docx", "test_doc.docx", "docx")
        job_id = job.job_id

        update_job(job_id, status="running", progress=50, current_step="Polishing...")

        # Verify it exists in memory
        self.assertIn(job_id, _jobs)
        self.assertEqual(get_job(job_id).progress, 50)

        # Simulate server restart by clearing in-memory cache
        del _jobs[job_id]
        self.assertNotIn(job_id, _jobs)

        # get_job should seamlessly restore it from SQLite
        restored = get_job(job_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.job_id, job_id)
        self.assertEqual(restored.status, "running")
        self.assertEqual(restored.progress, 50)
        self.assertEqual(restored.current_step, "Polishing...")

        # Clean up test job from memory and SQLite
        _jobs.pop(job_id, None)
        db_delete_job(job_id)
        self.assertIsNone(db_get_job(job_id))
        print("   JobManager SQLite Sync & Restart Recovery: OK")

    def test_storage_cleaner_routine(self):
        print("-> 4. Testing Storage Cleaner Routine...")
        # Run cleaner with 1000 hours cutoff to test execution without deleting recent valid files
        res = clean_temp_storage(max_age_hours=1000, dry_run=True)
        self.assertIn("files_deleted", res)
        self.assertIn("bytes_freed_mb", res)
        self.assertTrue(res["dry_run"])
        print(f"   Storage Cleaner: OK (Scanned temp storage, {res['files_deleted']} candidate files)")


if __name__ == "__main__":
    unittest.main()
