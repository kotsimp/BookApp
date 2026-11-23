"""
test_interruptions_and_free_engine.py - Regression guards for:
* Smart Resume data, queue persistence across restarts, the quota banner, glossary terms containing "/";
* the free engine: no fuzzy translation-memory matches, no untranslated text reported as a translation.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import job_manager, main, queue_manager as qm, translator


def run(coro):
    return asyncio.run(coro)


class Case(unittest.TestCase):

    def setUp(self):
        self.reset()
        self.jobs = []

    def tearDown(self):
        self.reset()
        qm.save_queue()
        for jid in self.jobs:
            run(main.delete_job(jid))

    @staticmethod
    def reset():
        qm._queue_items.clear()
        qm._queue_paused = qm._queue_paused_for_quota = qm._queue_auto_start = False
        qm._queue_task = None

    def job(self, name="novel.pdf", **fields):
        job = job_manager.create_job("", name, "pdf")
        self.jobs.append(job.job_id)
        if fields:
            job_manager.update_job(job.job_id, **fields)
        return job.job_id

    def restart(self):
        self.reset()
        job_manager._jobs.clear()
        job_manager._active_tasks.clear()
        job_manager.cleanup_old_jobs()
        qm.restore_queue()


class TestSmartResume(Case):

    def listed(self, jid):
        return next(j for j in run(main.all_jobs(include_tests=True)) if j["job_id"] == jid)

    def test_interrupted_job_is_resumable_with_progress(self):
        jid = self.job(mode="translate", status="running", done_chunks=3, total_chunks=9)
        self.restart()
        row = self.listed(jid)
        self.assertEqual((row["resumable"], row["done_chunks"], row["total_chunks"]), (True, 3, 9))

    def test_interrupted_before_first_chunk_is_resumable(self):
        jid = self.job(mode="audiobook", status="running")
        self.restart()
        self.assertTrue(self.listed(jid)["resumable"])

    def test_finished_running_and_cancelled_are_not_offered(self):
        for status in ("done", "running", "cancelled", "queued", "waiting_quota"):
            self.assertFalse(self.listed(self.job(mode="translate", status=status, done_chunks=2))["resumable"], status)
        self.assertFalse(self.listed(self.job())["resumable"], "a fresh upload has nothing to resume")

    def test_shutdown_is_not_a_user_cancel(self):
        jid = self.job(mode="translate", status="running")
        job_manager.mark_interrupted(jid)
        self.assertTrue(self.listed(jid)["resumable"])
        other = self.job(mode="translate", status="running")
        job_manager.cancel_job(other)
        job_manager.mark_interrupted(other)
        self.assertEqual(job_manager.get_job(other).status, "cancelled")

    def test_only_quota_stops_resume_automatically(self):
        self.assertTrue(self.listed(self.job(mode="translate", status="error", error="429 quota"))["quota_stopped"])
        self.assertFalse(self.listed(self.job(mode="translate", status="error", error="damaged file"))["quota_stopped"])

    def test_audiobook_settings_survive_restart(self):
        options = {"language": "greek", "voice_name": "Athina (Female)", "rate": "-20%"}
        jid = self.job(mode="audiobook", audiobook_options=options)
        self.restart()
        self.assertEqual(run(main.job_status(jid))["audiobook_options"], options)


class TestQueueSurvivesRestart(Case):

    def test_waiting_item_waits_then_resumes(self):
        first, second = self.job("one.pdf"), self.job("two.pdf")
        qm.add_to_queue(first, api_key="SECRET-KEY-VALUE", quota_behavior="wait")
        qm.add_to_queue(second, api_key="SECRET-KEY-VALUE", quota_behavior="wait")
        qm._queue_items[0].status = "waiting_quota"
        qm._queue_paused = qm._queue_paused_for_quota = True
        job_manager.update_job(first, status="waiting_quota")
        qm.save_queue()
        self.assertNotIn("SECRET-KEY-VALUE", qm._state_file().read_text(encoding="utf-8"))

        self.restart()
        self.assertEqual([i.status for i in qm._queue_items], ["waiting_quota", "queued"])
        self.assertTrue(qm.is_queue_paused_for_quota())
        with mock.patch.object(qm, "start_queue") as start:
            self.assertTrue(qm.resume_queue_after_quota(mock.AsyncMock()))
        start.assert_called_once()
        self.assertEqual([i.status for i in qm._queue_items], ["queued", "queued"])

    def test_running_item_comes_back_paused(self):
        jid = self.job()
        qm.add_to_queue(jid)
        qm._queue_items[0].status = "running"
        job_manager.update_job(jid, status="running")
        qm.save_queue()
        self.restart()
        state = qm.get_queue_state()
        self.assertEqual((state["items"][0]["status"], state["paused"], state["is_running"]), ("queued", True, False))

    def test_waiting_job_from_older_version_is_adopted(self):
        jid = self.job(status="waiting_quota", mode="translate")
        qm.save_queue()
        self.restart()
        self.assertEqual([(i.job_id, i.status) for i in qm._queue_items], [(jid, "waiting_quota")])

    def test_removed_waiting_item_stays_removed(self):
        jid = self.job()
        qm.add_to_queue(jid)
        qm._queue_items[0].status = "waiting_quota"
        job_manager.update_job(jid, status="waiting_quota")
        qm.remove_from_queue(jid)
        self.restart()
        self.assertEqual(qm._queue_items, [])


class TestWaitWithRealQuotaMessages(Case):

    def test_real_messages_pause_the_queue(self):
        from backend.ai_polisher import DailyQuotaExhaustedError
        real = (
            "⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). Έτοιμο ξανά στις 10:00:00.",
            "All Gemini candidate models are in cooldown across configured keys.",
            "Η μετάφραση Vision AI σταμάτησε λόγω εξάντλησης του ημερήσιου ορίου του Gemini Free Tier.",
        )
        for message in real:
            self.reset()
            first, second = self.job(), self.job()
            for jid in (first, second):
                qm.add_to_queue(jid, api_key="AQ.TestKey", quota_behavior="wait")

            async def stops_like_the_pipeline(item):
                job_manager.update_job(item.job_id, status="error", error=str(DailyQuotaExhaustedError(message)))

            run(qm._process_queue_loop(stops_like_the_pipeline))
            self.assertEqual([i.status for i in qm._queue_items], ["waiting_quota", "queued"], message)
            self.assertTrue(qm.is_queue_paused_for_quota(), message)

    def test_ordinary_errors_do_not_pause(self):
        self.assertFalse(job_manager.is_quota_error("Το αρχείο υπερβαίνει το μέγιστο όριο των 250 MB."))


class TestQuotaBanner(Case):

    def message(self, *modes):
        self.reset()
        for mode in modes:
            qm.add_to_queue(self.job(), api_key="AQ.TestKey", quota_behavior=mode)
        info = {"exhausted": True, "message": "x", "cooldown_time_str": "5λ"}
        with mock.patch("backend.ai_polisher.get_gemini_quota_info", return_value=info):
            return qm.get_queue_state()["gemini_quota_message"]

    def test_message_matches_the_choice(self):
        self.assertNotIn("χωρίς AI", self.message("wait", "wait"))
        self.assertIn("χωρίς AI", self.message("fallback"))
        mixed = self.message("wait", "fallback")
        self.assertIn("περιμένουν", mixed)
        self.assertIn("χωρίς AI", mixed)


class TestFreeEngine(Case):

    def test_fuzzy_memory_match_is_rejected(self):
        body = {"responseStatus": 200, "responseData": {"translatedText": "Πρώτη πρόταση:"}, "matches": [
            {"segment": "Second line:", "translation": "Πρώτη πρόταση:", "match": 0.96, "created-by": "Public_Corpora"},
            {"segment": "second line", "translation": "δεύτερη γραμμή", "match": 0.85, "created-by": "MT!"},
        ]}

        class Response:
            status = 200

            async def json(self, **_):
                return body

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        session = mock.Mock()
        session.get = lambda *a, **k: Response()
        got = run(translator._translate_mymemory_async(session, "second line", "english", "greek"))
        self.assertEqual(got, "δεύτερη γραμμή")
        body["matches"].pop()
        self.assertIsNone(run(translator._translate_mymemory_async(session, "second line", "english", "greek")))

    def test_outage_raises_instead_of_returning_source(self):
        with mock.patch.object(translator, "RETRY_ROUND_DELAYS", (0.01,)), \
                mock.patch.object(translator, "_translate_attempt", mock.AsyncMock(return_value=None)) as attempt:
            with self.assertRaises(translator.TranslationUnavailableError):
                run(translator._translate_with_retry("Some English text", "english", "greek"))
        self.assertEqual(attempt.await_count, 2)

    def test_short_outage_is_waited_out(self):
        with mock.patch.object(translator, "RETRY_ROUND_DELAYS", (0.01,)), \
                mock.patch.object(translator, "_translate_attempt", mock.AsyncMock(side_effect=[None, "κείμενο"])):
            self.assertEqual(run(translator._translate_with_retry("text", "english", "greek")), "κείμενο")


class TestInterruptionAndQuotaEdges(Case):

    def test_late_cancellation_keeps_a_finished_job(self):
        jid = self.job(mode="translate", status="done")
        job_manager.mark_interrupted(jid)
        self.assertEqual(job_manager.get_job(jid).status, "done")

    def test_429_is_a_status_not_part_of_a_file_name(self):
        for text in ("Cannot read report_14290.docx", "Cannot read report-429.pdf", "Cannot read quota.docx"):
            self.assertFalse(job_manager.is_quota_error(text), text)
        for text in ("Gemini API error (429): slow down", "HTTP 429 Too Many Requests", "RESOURCE_EXHAUSTED"):
            self.assertTrue(job_manager.is_quota_error(text), text)

    def test_own_failures_are_not_relabelled_as_quota(self):
        with mock.patch("backend.ai_polisher.is_gemini_quota_exhausted", return_value=True):
            self.assertFalse(main._is_quota_failure(ValueError("damaged file"), True))
            self.assertFalse(main._is_quota_failure(RuntimeError("no audio"), False))
            self.assertFalse(main._is_quota_failure(translator.TranslationUnavailableError("outage"), True))
            self.assertTrue(main._is_quota_failure(RuntimeError("batch failed"), True))

    def test_automatic_attempts_back_off(self):
        import time
        with mock.patch.object(qm, "_quota_paused_at", time.time()):
            self.assertFalse(qm.quota_retry_due())
        with mock.patch.object(qm, "_quota_paused_at", 0.0):
            self.assertTrue(qm.quota_retry_due())

    def test_files_behind_a_removed_waiting_file_continue(self):
        first, second = self.job("a.pdf"), self.job("b.pdf")
        qm.add_to_queue(first)
        qm.add_to_queue(second)
        qm._queue_items[0].status = "waiting_quota"
        qm._queue_paused = qm._queue_paused_for_quota = True
        qm.remove_from_queue(first)
        with mock.patch.object(qm, "start_queue") as start:
            self.assertTrue(qm.resume_queue_after_quota(mock.AsyncMock()))
        start.assert_called_once()

    def test_resume_without_body_keeps_each_files_settings(self):
        jid = self.job("a.pdf")
        qm.add_to_queue(jid, output_format="epub", layout_mode="literature", ai_polish=True)
        before = (qm._queue_items[0].output_format, qm._queue_items[0].layout_mode, qm._queue_items[0].ai_polish,
                  qm._queue_items[0].quota_behavior)
        with mock.patch.object(qm, "start_queue", return_value={}):
            run(main.start_batch_queue(None))
        item = qm._queue_items[0]
        self.assertEqual((item.output_format, item.layout_mode, item.ai_polish, item.quota_behavior), before)


class TestFreeEngineLimits(Case):

    def test_nothing_to_translate_is_returned_as_is(self):
        with mock.patch.object(translator, "_translate_attempt", mock.AsyncMock(return_value=None)) as attempt:
            self.assertEqual(run(translator._translate_with_retry(" 12 • ", "english", "greek")), " 12 • ")
        attempt.assert_not_awaited()

    def test_long_text_is_split_without_loss(self):
        text = "\n\n".join(f"Paragraph {n}. " + "Word and more words here. " * 30 for n in range(20)).strip()
        sizes = []

        async def limited(part, *_a, **_k):
            sizes.append(len(part))
            return part.upper() if len(part) <= 5000 else None

        with mock.patch.object(translator, "_translate_attempt", limited):
            out = run(translator._translate_with_retry(text, "english", "greek"))
        self.assertGreater(len(sizes), 1)
        self.assertEqual(" ".join(out.split()), " ".join(text.upper().split()))
        self.assertEqual(out.count("\n\n"), 19)


class TestGlossarySlash(Case):

    def test_route_accepts_slashes(self):
        import re
        route = next(r for r in main.app.routes if "/api/glossary/" in getattr(r, "path", ""))
        self.assertTrue(re.match(route.path_regex, "/api/glossary/AI/ML"))


if __name__ == "__main__":
    unittest.main()
