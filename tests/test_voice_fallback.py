"""
test_voice_fallback.py - A refused or cut voice request never leaves gaps in an audiobook; Resume re-uses parts.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
from edge_tts.exceptions import NoAudioReceived

from backend import job_manager
from backend.database import db_delete_job
from backend import tts_engine as tts

FRAME = b"\xff\xf3\x64\xc4" + b"\x00" * 140
NESTORAS = "el-GR-NestorasNeural"
ARIA, JENNY = "en-US-AriaNeural", "en-US-JennyNeural"
EN_TEXT = "The sea is calm today and the harbour is full of small wooden boats. " * 30
TEXT = "Η θάλασσα είναι ήρεμη σήμερα και το λιμάνι γεμάτο καΐκια. " * 30


REFUSED = "αβγδεζηθικλμ"


def service(limits, refused=REFUSED):
    """limits: voice -> longest text it answers; others always answer. `refused` gets audio from nobody."""
    spoken = []

    class Communicate:
        def __init__(self, text, voice, **_kw):
            self.text, self.voice = text, voice

        async def save(self, path):
            if (refused and refused in self.text) or len(self.text) > limits.get(self.voice, 10 ** 6):
                raise NoAudioReceived("no audio")
            spoken.append((self.voice, self.text))
            Path(path).write_bytes(FRAME * 2)

    return Communicate, spoken


_sleep = asyncio.sleep


async def no_wait(*_a, **_k):
    await _sleep(0.002)  # asyncio.sleep is patched process-wide: it must still yield, or the progress ticker spins


class TestVoiceFallback(unittest.TestCase):
    def narrate(self, limits, text=TEXT[:1100], voice=NESTORAS):
        fake, spoken = service(limits)
        state = tts.TtsState()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "part.mp3"
            with mock.patch.object(tts.edge_tts, "Communicate", fake), mock.patch.object(tts.asyncio, "sleep", no_wait):
                asyncio.run(tts._tts_chunk_with_retry(text, voice, str(out), state=state))
            size = out.stat().st_size
        return spoken, state, size

    def same_words(self, spoken, text):
        self.assertEqual(" ".join(" ".join(t for _, t in spoken).split()), " ".join(tts._clean_tts_text(text).split()))

    def test_shorter_requests_keep_the_chosen_voice(self):
        for limit in (520, 200, 80):
            spoken, state, size = self.narrate({NESTORAS: limit})
            self.assertGreater(size, 0)
            self.assertEqual({v for v, _ in spoken}, {NESTORAS})
            self.same_words(spoken, TEXT[:1100])
            self.assertEqual(state.substituted, {})

    def test_same_language_substitute_is_reported(self):
        spoken, state, size = self.narrate({ARIA: 0}, EN_TEXT[:1100], ARIA)
        self.assertGreater(size, 0)
        self.assertEqual({v for v, _ in spoken}, {JENNY})
        self.assertEqual(state.substituted, {(ARIA, JENNY): 1})

    def test_greek_has_one_voice_and_no_substitute(self):
        self.assertEqual(list(tts.VOICES["greek"].values()), [NESTORAS])
        spoken, state, size = self.narrate({NESTORAS: 0})
        self.assertEqual((spoken, size, state.substituted), ([], 0, {}))

    def test_a_short_outage_is_waited_out(self):
        calls = []

        class Communicate:
            def __init__(self, text, _voice, **_kw):
                self.text = text

            async def save(self, path):
                calls.append(self.text)
                if len(calls) < 3:
                    raise NoAudioReceived("busy")
                Path(path).write_bytes(FRAME * 2)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "part.mp3"
            with mock.patch.object(tts.edge_tts, "Communicate", Communicate), mock.patch.object(tts.asyncio, "sleep", no_wait):
                used = asyncio.run(tts._tts_chunk_with_retry(TEXT[:1100], NESTORAS, str(out)))
            self.assertEqual((used, len(calls), len(set(calls))), (NESTORAS, 3, 1), "repeats ask for the whole part")

    def offline_book(self, failing_calls):
        calls, spoken = [], []

        class Communicate:
            def __init__(self, text, voice, **_kw):
                self.text, self.voice = text, voice

            async def save(self, path):
                calls.append(self.voice)
                if len(calls) <= failing_calls:
                    raise aiohttp.ClientConnectionError("no network")
                spoken.append(self.voice)
                Path(path).write_bytes(FRAME * 2)

        with mock.patch(f"{__name__}.service", lambda *_a, **_k: (Communicate, spoken)):
            job, _spoken, exists = self.book({}, EN_TEXT * 8, "english", "Aria (Female)")
        return job, calls, spoken, exists

    def test_a_dropped_connection_is_waited_out_in_the_chosen_voice(self):
        job, calls, spoken, exists = self.offline_book(4 * tts.TTS_CONCURRENCY)  # every attempt of the parts under way
        self.assertEqual((job.status, exists, set(calls), set(spoken)), ("done", True, {ARIA}, {ARIA}))

    def test_a_long_outage_never_changes_the_voice(self):
        job, calls, _spoken, exists = self.offline_book(10 ** 6)
        self.assertEqual((job.status, exists, set(calls)), ("error", False, {ARIA}))
        self.assertIn("press Resume", job.error)

    def test_nothing_to_speak_is_silent_without_requests(self):
        for text in ("* * *", "—", "東京の夜"):
            spoken, _state, size = self.narrate({}, text=text)
            self.assertEqual((spoken, size), ([], 0))

    def book(self, limits, text, language="greek", voice_name="Nestoras (Male)"):
        fake, spoken = service(limits)
        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "book.txt", Path(td) / "book.mp3"
            src.write_text(text, encoding="utf-8")
            job = job_manager.create_job(str(src), "book.txt", "txt")
            with mock.patch.object(tts.edge_tts, "Communicate", fake), mock.patch.object(tts.asyncio, "sleep", no_wait):
                try:
                    asyncio.run(tts.generate_audiobook(
                        job_id=job.job_id, file_path=str(src), file_type="txt", language=language,
                        voice_name=voice_name, output_path=str(out), translated_text_path=str(src)))
                except RuntimeError:
                    pass
            exists = out.exists()
        saved = job_manager.get_job(job.job_id)
        job_manager._jobs.pop(job.job_id, None)
        db_delete_job(job.job_id)
        return saved, spoken, exists

    def test_a_failed_part_fails_the_book(self):
        job, spoken, exists = self.book({}, TEXT + "\n\n" + f"{REFUSED}. " * 90)
        self.assertTrue(spoken, "the other parts are narrated")
        self.assertEqual(job.status, "error")
        self.assertIn("could not be narrated", job.error)
        self.assertFalse(exists, "an audiobook with holes must not be offered as finished")

    def test_a_substituted_book_says_so(self):
        job, spoken, exists = self.book({ARIA: 0}, EN_TEXT, "english", "Aria (Female)")
        self.assertEqual(job.status, "done")
        self.assertTrue(exists and spoken)
        self.assertIn("read by Jenny", job.current_step)

    def test_a_job_saved_with_athina_is_read_by_nestoras(self):
        job, spoken, exists = self.book({}, TEXT, voice_name="Athina (Female)")
        self.assertTrue(exists)
        self.assertEqual({v for v, _ in spoken}, {NESTORAS})
        self.assertIn("no longer offered, so Nestoras reads instead", job.current_step)

    def test_resume_narrates_only_what_is_missing(self):
        text = TEXT + "\n\n" + f"{REFUSED}. " * 90
        with tempfile.TemporaryDirectory() as td:
            src, out = Path(td) / "book.txt", Path(td) / "book.mp3"
            src.write_text(text, encoding="utf-8")
            job = job_manager.create_job(str(src), "book.txt", "txt")

            def run(refused, rate=None):
                fake, spoken = service({}, refused)
                with mock.patch.object(tts.edge_tts, "Communicate", fake), mock.patch.object(tts.asyncio, "sleep", no_wait):
                    try:
                        asyncio.run(tts.generate_audiobook(
                            job_id=job.job_id, file_path=str(src), file_type="txt", language="greek", rate=rate,
                            voice_name="Nestoras (Male)", output_path=str(out), translated_text_path=str(src)))
                    except tts.NarrationError:
                        pass
                return [t for _, t in spoken]

            try:
                wanted = [tts._clean_tts_text(t) for t, _ in tts.split_into_voice_segments(text.strip(), NESTORAS)]
                good = [t for t in wanted if REFUSED not in t]
                first = run(REFUSED)
                self.assertTrue(good and set(good) <= set(first))
                self.assertFalse(out.exists())
                self.assertIn("press Resume", job_manager.get_job(job.job_id).error)
                self.assertEqual(sorted(run(None)), sorted(t for t in wanted if REFUSED in t))
                self.assertEqual(job_manager.get_job(job.job_id).status, "done")
                self.assertEqual(out.read_bytes().count(FRAME), 2 * len(wanted))
                self.assertFalse((Path(td) / ".tts_parts").exists(), "kept parts go when the book is complete")
                out.unlink()
                run(REFUSED)
                self.assertEqual(sorted(set(run(None, "+10%"))), sorted(set(wanted)), "other pacing: narrated again")
            finally:
                job_manager._jobs.pop(job.job_id, None)
                db_delete_job(job.job_id)

    def test_a_skipped_script_is_reported(self):
        job, _spoken, exists = self.book({}, TEXT + "\n\n" + "東京の夜。" * 260)
        self.assertEqual(job.status, "done")
        self.assertTrue(exists)
        self.assertIn("cannot read were skipped", job.current_step)

    def test_a_narration_failure_is_not_a_quota_stop(self):
        from backend import main
        with mock.patch("backend.ai_polisher.is_gemini_quota_exhausted", return_value=True):
            self.assertFalse(main._is_quota_failure(tts.NarrationError("no audio"), True))

    def test_retired_voice(self):
        for name in ("Davis (Male)", "en-US-DavisNeural"):
            self.assertEqual(tts._resolve_voice_code("english", name), "en-US-BrianNeural")
        for name in ("Athina (Female)", "el-GR-AthinaNeural"):
            self.assertEqual(tts._resolve_voice_code("greek", name), NESTORAS)
        self.assertEqual(tts.split_into_voice_segments("[Athina]: Γεια σου.", NESTORAS), [("Γεια σου.", NESTORAS)])


class TestCutAudio(unittest.TestCase):
    """The real edge-tts client on a fake socket: it keeps partial audio without any error."""

    def synthesize(self, audio_bytes, turn_end):
        message = lambda kind, data: types.SimpleNamespace(type=kind, data=data)
        header = b"X-RequestId:1\r\nContent-Type:audio/mpeg\r\nPath:audio\r\n"
        events = [message(aiohttp.WSMsgType.TEXT, "X-RequestId:1\r\nPath:turn.start\r\n\r\n{}")]
        for at in range(0, audio_bytes, 720):
            data = b"\x01" * min(720, audio_bytes - at)
            events.append(message(aiohttp.WSMsgType.BINARY, len(header).to_bytes(2, "big") + header + data))
        if turn_end:
            events.append(message(aiohttp.WSMsgType.TEXT, "X-RequestId:1\r\nPath:turn.end\r\n\r\n{}"))

        class Socket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def send_str(self, _data):
                pass

            async def __aiter__(self):
                for event in events:
                    yield event

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "part.mp3"
            error = None
            with mock.patch.object(aiohttp.ClientSession, "ws_connect", lambda *_a, **_k: Socket()):
                try:
                    asyncio.run(tts._synthesize(TEXT[:600], NESTORAS, str(out), {"rate": "-12%"}))
                except tts.IncompleteAudio as e:
                    error = e
            self.assertEqual([p.name for p in Path(td).iterdir()], [] if error else ["part.mp3"])
        return error

    def test_complete_audio_is_kept(self):
        self.assertIsNone(self.synthesize(600 * 370, True))

    def test_a_closed_stream_is_not_a_finished_part(self):
        self.assertIsNotNone(self.synthesize(600 * 370, False))

    def test_an_impossibly_short_recording_is_refused(self):
        self.assertIsNotNone(self.synthesize(4320, True))


if __name__ == "__main__":
    unittest.main()
