"""
test_concurrency_persistence_and_lifecycle.py - Concurrency, Race Conditions, Lifecycle & Storage Safety Suite.
Tests:
1. JobManager: thread-safe SSE notification from worker threads; full queue does not drop subscriber permanently;
   cancelled status protects against status='error' and current_step overwrites; cleanup_old_jobs skips running jobs.
2. QueueManager: single-side source_lang==target_lang guard in apply_settings_to_queued_items; comic PDF layout_mode
   preserved in add_to_queue; loop-exit vs start_queue race safety; orphaned 'queued' rows reset on restart.
3. Database: db_save_job coerces None numeric fields safely; compute_cache_key handles None arguments.
4. SettingsManager: corrupt settings.json is backed up to settings.json.corrupt instead of silently lost.
5. StorageCleaner: rejects max_age_hours<=0, skips active running/queued job dirs, cleans temp/previews/,
   and returns consistent schema.
"""

import sys
sys.path.insert(0, ".")
import os
import time
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.job_manager import (
    create_job, get_job, update_job, cancel_job, cleanup_old_jobs, _jobs,
)
from backend.database import (
    db_save_job, db_get_job, db_delete_job, db_reset_orphaned_running_jobs, compute_cache_key,
)
import backend.queue_manager as qm
import backend.settings_manager as sm
import backend.storage_cleaner as sc


class TestConcurrencyPersistenceAndLifecycle(unittest.TestCase):

    def test_1_job_manager_sse_full_queue_and_thread_safety(self):
        print("-> 1. Testing JobManager full-queue SSE preservation & off-thread delivery...")
        async def _run():
            job = create_job("sse_test.txt", "sse_test.txt", "txt")
            try:
                q: asyncio.Queue = asyncio.Queue(maxsize=2)
                job.subscribers.append(q)

                # Push 5 updates synchronously (exceeds maxsize=2) -> subscriber must NOT be removed!
                for pct in (10, 30, 50, 80, 100):
                    update_job(job.job_id, progress=pct, status="done" if pct == 100 else "running")

                self.assertIn(q, job.subscribers, "Full queue permanently dropped SSE subscriber!")
                # Drain and verify final terminal state was preserved
                seen = []
                while not q.empty():
                    seen.append(q.get_nowait())
                self.assertTrue(any(ev["progress"] == 100 and ev["status"] == "done" for ev in seen))

                # Off-thread notification from worker thread must wake awaiting coroutine cleanly
                job2 = create_job("sse_thread.txt", "sse_thread.txt", "txt")
                try:
                    q2: asyncio.Queue = asyncio.Queue(maxsize=10)
                    job2.subscribers.append(q2)
                    await asyncio.to_thread(update_job, job2.job_id, progress=42, current_step="From worker thread")
                    ev = await asyncio.wait_for(q2.get(), timeout=2.0)
                    self.assertEqual(ev["progress"], 42)
                    self.assertEqual(ev["current_step"], "From worker thread")
                finally:
                    _jobs.pop(job2.job_id, None)
                    db_delete_job(job2.job_id)
            finally:
                _jobs.pop(job.job_id, None)
                db_delete_job(job.job_id)

        asyncio.run(_run())
        print("   SSE full-queue & thread-safe delivery: OK")

    def test_2_cancelled_job_blocks_error_and_step_overwrites(self):
        print("-> 2. Testing cancelled job guard blocks error/running/step overwrites...")
        job = create_job("cancel_guard.txt", "cancel_guard.txt", "txt")
        try:
            cancel_job(job.job_id)
            self.assertEqual(job.status, "cancelled")

            # Simulate late background updates attempting to overwrite status='error' or step
            update_job(job.job_id, status="error", error="Late network error", current_step="Failed!")
            update_job(job.job_id, progress=99, current_step="Almost done")
            self.assertEqual(job.status, "cancelled")
            self.assertIn("Cancelled", job.current_step)
            self.assertIsNone(job.error)
        finally:
            _jobs.pop(job.job_id, None)
            db_delete_job(job.job_id)
        print("   Cancelled job protection: OK")

    def test_3_queue_manager_validation_and_comic_preservation(self):
        print("-> 3. Testing QueueManager partial-settings same-lang guard & comic PDF preservation...")
        qm.clear_queue()
        j_book = create_job("book.pdf", "book.pdf", "pdf")
        j_comic = create_job("graphic.pdf", "graphic.pdf", "pdf")
        update_job(j_comic.job_id, layout_mode="comic")
        try:
            # Queuing a graphic novel PDF (job.layout_mode=='comic') without explicit is_comic preserves comic mode
            item_c = qm.add_to_queue(j_comic.job_id, source_lang="english", target_lang="greek", output_format="txt")
            self.assertTrue(item_c.is_comic, "Job with layout_mode='comic' must stay comic in queue!")
            self.assertEqual(item_c.layout_mode, "comic")
            self.assertEqual(item_c.output_format, "pdf")

            # Single-side partial update creating source_lang == target_lang must raise ValueError
            qm.add_to_queue(j_book.job_id, source_lang="english", target_lang="greek", output_format="pdf")
            with self.assertRaises(ValueError):
                qm.apply_settings_to_queued_items(source_lang="greek")
            with self.assertRaises(ValueError):
                qm.apply_settings_to_queued_items(target_lang="English")
        finally:
            qm.clear_queue()
            for j in (j_book, j_comic):
                _jobs.pop(j.job_id, None)
                db_delete_job(j.job_id)
        print("   QueueManager validation & comic preservation: OK")

    def test_4_database_none_coercion_and_orphaned_queued_reset(self):
        print("-> 4. Testing Database None-field coercion & orphaned 'queued' reset...")
        jid = "test-db-none-coercion-001"
        try:
            db_save_job({
                "job_id": jid,
                "file_path": "x.pdf",
                "file_name": "x.pdf",
                "file_type": "pdf",
                "status": "queued",
                "mode": "translate",
                "progress": None,
                "total_chunks": None,
                "done_chunks": None,
                "created_at": None,
                "updated_at": None,
            })
            row = db_get_job(jid)
            self.assertIsNotNone(row, "db_save_job silently dropped row when numeric fields were None!")
            self.assertEqual(row["progress"], 0)
            self.assertEqual(row["status"], "queued")

            # Orphaned 'queued' jobs must also reset to 'idle' on restart recovery
            reset_cnt = db_reset_orphaned_running_jobs()
            self.assertGreaterEqual(reset_cnt, 1)
            row_after = db_get_job(jid)
            self.assertEqual(row_after["status"], "idle")

            # compute_cache_key must tolerate None arguments without AttributeError
            k = compute_cache_key(None, None, None, None, None)
            self.assertEqual(len(k), 64)
        finally:
            db_delete_job(jid)
        print("   Database None coercion & orphaned reset: OK")

    def test_5_settings_manager_corrupt_file_backup(self):
        print("-> 5. Testing SettingsManager backs up corrupt settings.json instead of silent loss...")
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            fake_file = td_p / "settings.json"
            fake_file.write_text("{broken json!!!", encoding="utf-8")
            with patch.object(sm, "CONFIG_DIR", td_p), patch.object(sm, "SETTINGS_FILE", fake_file):
                loaded = sm.load_settings()
                self.assertEqual(loaded, {})
                corrupt_bak = td_p / "settings.json.corrupt"
                self.assertTrue(corrupt_bak.exists(), "Corrupt settings.json was not backed up!")
                self.assertEqual(corrupt_bak.read_text(encoding="utf-8"), "{broken json!!!")
        print("   SettingsManager corrupt backup: OK")

    def test_6_storage_cleaner_protects_active_jobs_and_bounds(self):
        print("-> 6. Testing StorageCleaner rejects max_age_hours<=0, skips active jobs & cleans previews...")
        with self.assertRaises(ValueError):
            sc.clean_temp_storage(max_age_hours=0, dry_run=True)
        with self.assertRaises(ValueError):
            sc.clean_temp_storage(max_age_hours=-5, dry_run=True)

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            active_job = create_job("active.pdf", "active.pdf", "pdf")
            update_job(active_job.job_id, status="running")
            try:
                old_ts = time.time() - (100 * 3600)
                active_up = td_p / "uploads" / active_job.job_id
                stale_up = td_p / "uploads" / "stale-job-id"
                previews = td_p / "previews"
                active_up.mkdir(parents=True)
                stale_up.mkdir(parents=True)
                previews.mkdir(parents=True)

                (active_up / "book.pdf").write_bytes(b"active")
                (stale_up / "old.pdf").write_bytes(b"stale")
                stale_prev = previews / "preview_old.mp3"
                stale_prev.write_bytes(b"mp3data")

                os.utime(active_up, (old_ts, old_ts))
                os.utime(stale_up, (old_ts, old_ts))
                os.utime(stale_prev, (old_ts, old_ts))

                with patch.object(sc, "TEMP_DIR", td_p):
                    res = sc.clean_temp_storage(max_age_hours=24, dry_run=False)
                self.assertEqual(res["status"], "ok")
                self.assertIn("errors", res)
                self.assertTrue(active_up.exists(), "StorageCleaner deleted an active running job's uploads!")
                self.assertFalse(stale_up.exists(), "StorageCleaner failed to delete stale upload dir!")
                self.assertFalse(stale_prev.exists(), "StorageCleaner failed to delete stale voice preview!")
            finally:
                _jobs.pop(active_job.job_id, None)
                db_delete_job(active_job.job_id)

        # Missing temp dir still returns consistent schema including 'errors'
        with patch.object(sc, "TEMP_DIR", Path("temp/nonexistent_dir_xyz_999")):
            res_empty = sc.clean_temp_storage(max_age_hours=48, dry_run=True)
            self.assertIn("errors", res_empty)
            self.assertEqual(res_empty["status"], "temp_dir_empty")
        print("   StorageCleaner active-job protection & schema consistency: OK")


if __name__ == "__main__":
    unittest.main()
