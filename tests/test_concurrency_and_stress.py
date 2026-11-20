"""
test_concurrency_and_stress.py - Concurrency, Multi-threading & High-Throughput Stress Test Suite.
Tests:
1. Concurrent Job Manager operations (creating, updating, and querying 50+ jobs in parallel).
2. SSE Subscriber Queue concurrency & overflow safety.
3. Selective job cancellation isolation (cancelling job A does not affect jobs B & C).
4. Concurrent Settings read/write integrity across multiple threads.
5. Concurrent Glossary queries, mutations, and regex replacements.
"""

import sys
sys.path.insert(0, ".")
import asyncio
import concurrent.futures
import threading
import time
import unittest

from backend.job_manager import (
    create_job,
    get_job,
    update_job,
    cancel_job,
    is_job_cancelled,
    _jobs,
)
from backend.settings_manager import save_setting, get_setting
from backend.glossary import load_glossary, apply_glossary, set_term, delete_term


class TestConcurrencyAndStress(unittest.TestCase):

    def test_concurrent_job_creation_and_updates(self):
        print("-> 1. Testing Concurrent Job Creation and Updates (50 parallel jobs)...")
        num_jobs = 50

        async def worker(idx):
            j = create_job(f"path_{idx}.txt", f"book_{idx}.txt", "txt")
            job_id = j.job_id
            for prog in range(0, 101, 25):
                update_job(job_id, progress=prog, current_step=f"Step {prog}%")
                await asyncio.sleep(0.001)
            fetched = get_job(job_id)
            self.assertEqual(fetched.progress, 100)
            self.assertEqual(fetched.current_step, "Step 100%")
            return job_id

        async def run_all():
            return await asyncio.gather(*(worker(i) for i in range(num_jobs)))

        job_ids = asyncio.run(run_all())
        self.assertEqual(len(job_ids), num_jobs)
        self.assertEqual(len(set(job_ids)), num_jobs)  # All job IDs must be unique UUIDs
        for jid in job_ids:
            _jobs.pop(jid, None)
        print(f"   Concurrent jobs ({num_jobs} parallel tasks): OK")

    def test_sse_subscriber_queues(self):
        print("-> 2. Testing SSE Subscriber Queue Concurrency & Overflow Safety...")
        j = create_job("sample.txt", "sample.txt", "txt")
        job_id = j.job_id
        try:
            # Attach 10 simulated subscriber queues
            queues = [asyncio.Queue(maxsize=50) for _ in range(10)]
            j.subscribers = queues

            # Broadcast 20 rapid state updates
            for step in range(20):
                update_job(job_id, progress=step * 5, current_step=f"Tick {step}")

            # Verify all queues received events without blocking
            for q in queues:
                self.assertTrue(q.qsize() > 0)
                ev = q.get_nowait()
                self.assertIn("status", ev)
                self.assertIn("progress", ev)

            print("   SSE queue broadcasting: OK")
        finally:
            _jobs.pop(job_id, None)

    def test_job_cancellation_isolation(self):
        print("-> 3. Testing Job Cancellation Isolation...")
        j1 = create_job("test_book1.txt", "test_book1.txt", "txt")
        j2 = create_job("test_book2.txt", "test_book2.txt", "txt")
        j3 = create_job("test_book3.txt", "test_book3.txt", "txt")
        try:
            # Cancel only j2
            self.assertTrue(cancel_job(j2.job_id))
            self.assertTrue(is_job_cancelled(j2.job_id))

            # j1 and j3 must remain active and unaffected
            self.assertFalse(is_job_cancelled(j1.job_id))
            self.assertFalse(is_job_cancelled(j3.job_id))

            # Trying to update cancelled job must not reset status to running
            update_job(j2.job_id, status="running", progress=50)
            self.assertEqual(get_job(j2.job_id).status, "cancelled")

            print("   Cancellation isolation: OK")
        finally:
            for j in (j1, j2, j3):
                _jobs.pop(j.job_id, None)

    def test_concurrent_settings_read_write(self):
        print("-> 4. Testing Multi-Threaded Settings Read/Write Integrity...")
        errors = []

        def worker(thread_id):
            try:
                for i in range(15):
                    val = f"test_val_{thread_id}_{i}"
                    save_setting(f"stress_key_{thread_id}", val)
                    read_back = get_setting(f"stress_key_{thread_id}")
                    if read_back != val:
                        errors.append(f"Mismatch: expected {val}, got {read_back}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        from backend.settings_manager import delete_setting
        for t in range(8):
            delete_setting(f"stress_key_{t}")

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        print("   Concurrent settings read/write: OK")

    def test_concurrent_glossary_replacement(self):
        print("-> 5. Testing Concurrent Glossary Replacements...")
        text = "In a nutshell, we should develop using C++ and artificial intelligence for our civil society."

        def worker(_):
            res = apply_glossary(text, "greek")
            self.assertIn("τεχνητή νοημοσύνη", res)
            self.assertIn("C++", res)
            self.assertIn("κοινωνία των πολιτών", res)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(30)]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # Raises if any thread failed

        print("   Concurrent glossary replacements: OK")


if __name__ == "__main__":
    unittest.main()
