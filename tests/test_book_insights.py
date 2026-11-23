"""
test_book_insights.py - Book Insights (summaries, synopses, audio) test suite.

All external services are mocked in-process (Gemini via backend.ai_polisher._call_gemini_api,
edge-tts via backend.tts_engine._tts_chunk_with_retry). A private uvicorn server is started in
this process on a free port so the mocks apply to real HTTP requests.

Covers: basic & advanced modes, every insight type, Greek/English output, word-count guidelines
and structure, PDF/DOCX/TXT export, minimum-length validation (below/at/above threshold),
language detection, extraction failures, unsupported formats, missing key, quota/network/auth/
generic AI failures, quality-gate retries and rejection (wrong language, fabricated names/numbers),
audio summary & synopsis (audio == final text), audio failure, duplicate/concurrent requests,
result caching, map-reduce for long books, file-endpoint path safety, and non-interference with
DocTranslate/Audiobook job state.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import re
import json
import time
import socket
import asyncio
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest import mock

from backend import book_insights as bi
from backend.job_manager import create_job, get_job, update_job, cleanup_test_jobs

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "temp" / "uploads"
OUTPUTS = ROOT / "temp" / "outputs"
MP3_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 414

# ---------------------------------------------------------------------------
# Sample documents
# ---------------------------------------------------------------------------

_EN_SENTENCES = [
    "Elena Markou keeps the old lighthouse of Port Avra and writes down every ship that passes the cape.",
    "Her brother Nikos returns from the city after many years and asks her to sell the lighthouse.",
    "The harbour council wants to replace the keeper with an automatic lamp before the winter of 1987.",
    "Elena refuses, because the lighthouse is the last thing that connects her with their father.",
    "During a violent storm a fishing boat loses its engine near the northern rocks.",
    "Nikos and Elena climb the tower together and keep the light burning through the night.",
    "The sailors are saved, and the council finally understands why a human keeper still matters.",
    "In the final chapter Nikos decides to stay in Port Avra and helps his sister repair the tower.",
]
_GR_SENTENCES = [
    "Η Ελένη Μάρκου φυλάει τον παλιό φάρο της Αύρας και καταγράφει κάθε πλοίο που περνά από τον κάβο.",
    "Ο αδελφός της ο Νίκος επιστρέφει από την πόλη ύστερα από χρόνια και της ζητά να πουλήσει τον φάρο.",
    "Το λιμενικό συμβούλιο θέλει να αντικαταστήσει τον φύλακα με αυτόματο φανό πριν από τον χειμώνα.",
    "Η Ελένη αρνείται, γιατί ο φάρος είναι ό,τι της έχει μείνει από τον πατέρα τους.",
    "Σε μια άγρια καταιγίδα ένα ψαροκάικο χάνει τη μηχανή του κοντά στα βόρεια βράχια.",
    "Ο Νίκος και η Ελένη ανεβαίνουν μαζί στον πύργο και κρατούν το φως αναμμένο όλη τη νύχτα.",
    "Οι ψαράδες σώζονται και το συμβούλιο καταλαβαίνει γιατί ο άνθρωπος φύλακας είναι ακόμη απαραίτητος.",
    "Στο τελευταίο κεφάλαιο ο Νίκος αποφασίζει να μείνει στην Αύρα και επισκευάζει τον πύργο με την αδελφή του.",
]


def make_doc(sentences, n_words: int, chapters: bool = True) -> str:
    out, words, chap = [], 0, 1
    i = 0
    while words < n_words:
        if chapters and i % 16 == 0:
            out.append(f"Chapter {['One', 'Two', 'Three', 'Four', 'Five', 'Six'][min(chap - 1, 5)]}" if sentences is _EN_SENTENCES
                       else f"Κεφάλαιο {chap}")
            chap += 1
        para = " ".join(sentences[(i + k) % len(sentences)] for k in range(3))
        out.append(para)
        words += len(para.split())
        i += 1
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Fake Gemini
# ---------------------------------------------------------------------------

_EN_SUMMARY_POOL = [
    "Elena Markou guards the lighthouse of Port Avra while the council plans to automate it.",
    "Her brother Nikos first wants to sell the tower, but a storm changes everything.",
    "Together they keep the light burning and the sailors of a fishing boat are saved.",
    "The story shows why the keeper still matters to the harbour and to the family.",
]
_EN_SYNOPSIS_POOL = [
    "The novel opens on the cape, where the keeper records each vessel in her logbook.",
    "Its chapters follow the return of the brother and the pressure of the harbour council.",
    "A central theme is memory, carried by the tower that their father once tended.",
    "The turning point arrives with the storm near the northern rocks and the stranded crew.",
    "In the closing chapters the siblings reconcile and begin repairing the old tower.",
]
_GR_SUMMARY_POOL = [
    "Η Ελένη Μάρκου φυλάει τον φάρο της Αύρας ενώ το συμβούλιο σχεδιάζει να τον αυτοματοποιήσει.",
    "Ο αδελφός της ο Νίκος θέλει αρχικά να πουλήσει τον πύργο, όμως μια καταιγίδα αλλάζει τα πάντα.",
    "Μαζί κρατούν το φως αναμμένο και οι ψαράδες σώζονται.",
    "Η ιστορία δείχνει γιατί ο φύλακας παραμένει σημαντικός για το λιμάνι και την οικογένεια.",
]
_GR_SYNOPSIS_POOL = [
    "Το μυθιστόρημα ξεκινά στον κάβο, όπου η φύλακας καταγράφει κάθε σκάφος στο ημερολόγιό της.",
    "Τα κεφάλαια ακολουθούν την επιστροφή του αδελφού και την πίεση του λιμενικού συμβουλίου.",
    "Κεντρικό θέμα είναι η μνήμη, που τη φέρει ο πύργος τον οποίο φρόντιζε κάποτε ο πατέρας τους.",
    "Η κορύφωση έρχεται με την καταιγίδα στα βόρεια βράχια και το ακινητοποιημένο πλήρωμα.",
    "Στα τελευταία κεφάλαια τα αδέλφια συμφιλιώνονται και αρχίζουν να επισκευάζουν τον πύργο.",
]


def _fill(pool, n_words):
    out, words, i = [], 0, 0
    while words < n_words:
        s = pool[i % len(pool)]
        out.append(s)
        words += len(s.split())
        i += 1
    paras = [" ".join(out[k:k + 4]) for k in range(0, len(out), 4)]
    return paras


class FakeGemini:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mode = "ok"
        self.calls = []
        self.delay = 0.0
        self._wrong_once_done = False

    async def __call__(self, content, api_key, system_prompt, session=None, temperature=0.25,
                       exclude_models=None, bypass_cache=False, meta_out=None, cache_gate=None):
        assert cache_gate is not None and cache_gate("x") and not cache_gate("  "), "insights must pass a cache gate"
        from backend.ai_polisher import DailyQuotaExhaustedError
        self.calls.append(system_prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.mode == "quota":
            raise DailyQuotaExhaustedError("⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier).")
        if self.mode == "network":
            import aiohttp
            raise aiohttp.ClientConnectionError("Cannot connect to host generativelanguage.googleapis.com")
        if self.mode == "auth":
            raise PermissionError("Gemini API authentication error (403): API key not valid")
        if self.mode == "generic":
            raise RuntimeError("All Gemini candidate models failed.")
        if "research notes" in system_prompt:
            return "- " + " ".join(content.split()[:250])
        if "proofreader" in system_prompt:
            return content

        greek = "Modern Greek" in system_prompt or (
            "SAME language" in system_prompt and re.search(r"[α-ω]", content[:400]))
        if self.mode == "wrong_lang_always" or (self.mode == "wrong_lang_once" and not self._wrong_once_done):
            self._wrong_once_done = True
            greek = not greek
        m = re.search(r"(\d+)-(\d+) words", system_prompt)
        lo, hi = (int(m.group(1)), int(m.group(2))) if m else (150, 300)
        target = (lo + hi) // 2
        if "ONE-SENTENCE" in system_prompt:
            base = _GR_SUMMARY_POOL[0] if greek else _EN_SUMMARY_POOL[0]
            base = base.rstrip(".") + (", και η απόφαση αυτή φέρνει αντιπαράθεση με τον αδελφό της που επιστρέφει από την πόλη"
                                       if greek else ", a plan that brings her into conflict with her brother who returns from the city")
            text = base + "."
        else:
            synopsis = "SYNOPSIS" in system_prompt
            pool = (_GR_SYNOPSIS_POOL if synopsis else _GR_SUMMARY_POOL) if greek else \
                   (_EN_SYNOPSIS_POOL if synopsis else _EN_SUMMARY_POOL)
            paras = _fill(pool, target)
            if synopsis or "EXTENDED SUMMARY" in system_prompt:
                heads = (["Θέμα", "Δομή", "Θέματα", "Εξελίξεις", "Κατάληξη"] if greek
                         else ["Premise", "Structure", "Themes", "Developments", "Ending"])
                blocks = []
                for k, p in enumerate(paras):
                    if k % max(1, len(paras) // 4) == 0:
                        blocks.append(f"## {heads[min(k // max(1, len(paras) // 4), 4)]}")
                    blocks.append(p)
                text = "\n\n".join(blocks)
            else:
                text = "\n\n".join(paras)
        if self.mode == "fabricate":
            text = text.replace(".", " near Captain Rodrigo Valdez, Admiral Kowalski, Senator Thorne and Lady Brannagh in 1642 and 1755.", 1)
        return text


FAKE = FakeGemini()
SPOKEN = []


async def fake_tts(text, voice, output_path, **kw):
    SPOKEN.append(text)
    if getattr(fake_tts, "fail", False) and len(SPOKEN) == 2:
        Path(output_path).write_bytes(b"")
        return
    Path(output_path).write_bytes(MP3_FRAME * 4)


# ---------------------------------------------------------------------------
# In-process server
# ---------------------------------------------------------------------------

_PORT = None
_PATCHERS = []


def _start_server():
    global _PORT
    if _PORT:
        return
    import uvicorn
    from backend.main import app
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _PORT = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error", lifespan="off"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/api/health", timeout=0.5)
            return
        except Exception:
            time.sleep(0.1)


def api(method, path, data=None, raw=False):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{_PORT}/api{path}", data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload.decode("utf-8")))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def wait_task(task_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        st, t = api("GET", f"/insights/tasks/{task_id}")
        if t.get("status") in ("done", "error"):
            return t
        time.sleep(0.1)
    raise AssertionError("task timed out")


def new_doc_job(text: str, name="test_insights_book.txt", ftype="txt"):
    job = create_job("", name, ftype)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    src = UPLOADS / job.job_id / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(text, encoding="utf-8")
    update_job(job.job_id, file_path=str(src), file_type=ftype)
    return job.job_id


def generate(job_id, insight_type, language=None, expect_ok=True):
    st, data = api("POST", "/insights/generate", {"job_id": job_id, "insight_type": insight_type,
                                                    "language": language, "api_key": "test-insights-key"})
    if st != 200:
        return st, data
    t = wait_task(data["task_id"])
    if expect_ok:
        assert t["status"] == "done", t
    return st, t


def words(text):
    return bi._plain_words(text)


class InsightsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for target, new in (("backend.ai_polisher._call_gemini_api", FAKE),
                            ("backend.tts_engine._tts_chunk_with_retry", fake_tts)):
            p = mock.patch(target, new)
            p.start()
            _PATCHERS.append(p)
        _start_server()
        cls.en_job = new_doc_job(make_doc(_EN_SENTENCES, 3000))
        cls.gr_job = new_doc_job(make_doc(_GR_SENTENCES, 3000), name="test_insights_greek.txt")

    @classmethod
    def tearDownClass(cls):
        while _PATCHERS:
            _PATCHERS.pop().stop()
        cleanup_test_jobs()

    def setUp(self):
        FAKE.reset()
        SPOKEN.clear()
        fake_tts.fail = False


# ===========================================================================
# Pure-logic tests
# ===========================================================================

class TestAnalysisAndLanguage(InsightsBase):

    def test_language_detection(self):
        self.assertEqual(bi.detect_language(make_doc(_EN_SENTENCES, 300)), "english")
        self.assertEqual(bi.detect_language(make_doc(_GR_SENTENCES, 300)), "greek")
        fr = "Le gardien du phare regarde la mer chaque soir. Elle écrit le nom des bateaux dans son cahier. " * 20
        self.assertEqual(bi.detect_language(fr), "other")
        self.assertIsNone(bi.detect_language("1234 5678 ---- !!!"))
        self.assertIsNone(bi.detect_language(""))

    def test_meaningful_text_ignores_noise(self):
        noisy = "\n".join(["RUNNING HEADER", "12", "Real words here form a sentence.", "http://x.example/abc"] * 5)
        clean = bi.meaningful_text(noisy)
        self.assertNotIn("RUNNING HEADER", clean)
        self.assertNotIn("http", clean)
        self.assertNotIn("\n12\n", f"\n{clean}\n")
        self.assertEqual(bi.count_words(clean), 25)

    def test_minimum_length_thresholds(self):
        below = " ".join(["word"] * (bi.MIN_SYNOPSIS_WORDS - 1))
        at = " ".join(["word"] * bi.MIN_SYNOPSIS_WORDS)
        tiny = " ".join(["word"] * (bi.MIN_SUMMARY_WORDS - 1))
        a_below, a_at, a_tiny = bi.analyze_text(below), bi.analyze_text(at), bi.analyze_text(tiny)
        self.assertTrue(a_below["can_summary"])
        self.assertFalse(a_below["can_synopsis"])
        self.assertIn("1,5", a_below["reasons"]["synopsis"])
        self.assertTrue(a_at["can_synopsis"])
        self.assertFalse(a_tiny["can_summary"])
        self.assertEqual(bi.MIN_SYNOPSIS_WORDS, 375)  # 1.5 pages x 250 words

    def test_target_ranges_scale_down_for_short_sources(self):
        self.assertEqual(bi.target_word_range("one_sentence", 50), (20, 40))
        self.assertEqual(bi.target_word_range("extended_synopsis", 100000), (1500, 2500))
        lo, hi = bi.target_word_range("extended_summary", 600)
        self.assertLessEqual(hi, 300)
        lo_s, hi_s = bi.target_word_range("standard_synopsis", 600)
        lo_e, hi_e = bi.target_word_range("extended_synopsis", 600)
        self.assertGreater(hi_e, hi_s)

    def test_validator_rules(self):
        src = make_doc(_EN_SENTENCES, 1000)
        one = "Elena Markou guards the lighthouse of Port Avra while the council plans to automate it, which brings her into conflict with her brother."
        self.assertEqual(bi.validate_output(one, "one_sentence", "english", 20, 40, src, "english")[0], [])
        two = "Elena guards the lighthouse. Nikos wants to sell it and the council agrees with him in the end of the story today."
        self.assertTrue(bi.validate_output(two, "one_sentence", "english", 20, 40, src, "english")[0])
        greek_out = " ".join(_GR_SUMMARY_POOL * 8)
        self.assertIn("output is not in English", bi.validate_output(greek_out, "short_summary", "english", 150, 300, src, "english")[0])
        fabricated = " ".join(_EN_SUMMARY_POOL * 8) + " He met Admiral Kowalski, Senator Thorne, Lady Brannagh and Captain Valdez in 1642 and 1755."
        crit = bi.validate_output(fabricated, "short_summary", "english", 150, 300, src, "english")[0]
        self.assertTrue(any("numbers not found" in c for c in crit))
        self.assertTrue(any("names not found" in c for c in crit))

    def test_greek_latin_script_and_condensation_checks(self):
        src = make_doc(_EN_SENTENCES, 1000)
        mixed = " ".join(_GR_SUMMARY_POOL * 6) + " " + " ".join(["Lena Orel and Viktor Hale"] * 6)
        crit = bi.validate_output(mixed, "short_summary", "greek", 150, 300, src, "english")[0]
        self.assertTrue(any("Latin script" in c for c in crit))
        quoted = " ".join(_GR_SUMMARY_POOL * 8) + " Το βιβλίο «The Clockmaker of Varena» τελειώνει εδώ."
        self.assertEqual(bi.validate_output(quoted, "short_summary", "greek", 150, 300, src, "english")[0], [])
        short_src = " ".join(_EN_SENTENCES * 3)
        retell = " ".join(_EN_SUMMARY_POOL * 12)
        crit2 = bi.validate_output(retell, "short_summary", "english", 50, 300, short_src, "english")[0]
        self.assertTrue(any("must condense" in c for c in crit2))

    def test_english_stutter_collapse_keeps_greek_reduplication(self):
        self.assertEqual(bi.normalize_output("## Mechanical Mechanical Defects", "english"), "## Mechanical Defects")
        self.assertIn("σιγά σιγά", bi.normalize_output("Έφυγε σιγά σιγά από τον πύργο.", "greek"))

    def test_proofread_guard_rejects_structural_changes(self):
        draft = "## Θέμα\n\n" + " ".join(_GR_SUMMARY_POOL * 3)

        async def run(reply):
            async def fake_ai(*a, **k):
                return reply
            with mock.patch.object(bi, "_ai", new=fake_ai):
                return await bi._proofread_greek(draft, "k", None)
        self.assertEqual(asyncio.run(run("Σύντομο.")), draft)              # length collapsed -> rejected
        self.assertEqual(asyncio.run(run(draft.replace("## Θέμα\n\n", ""))), draft)  # heading lost -> rejected
        fixed = draft.replace("φυλάει", "φυλάσσει")
        self.assertEqual(asyncio.run(run(fixed)), fixed)                  # genuine correction kept

    def test_frontend_markdown_renderer_is_xss_safe(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js not installed")
        js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        esc = re.search(r"function escHtml\(str\) \{[\s\S]*?\n\}", js).group(0)
        ins_js = (ROOT / "frontend" / "insights.js").read_text(encoding="utf-8")
        render = re.search(r"function renderInsightMarkdown\(md\) \{[\s\S]*?\n\}", ins_js).group(0)
        payload = "## <img src=x onerror=alert(1)>\n\n**bold** <script>alert(2)</script>\n\n- item <b>x</b>"
        script = f"{esc}\n{render}\nprocess.stdout.write(renderInsightMarkdown({json.dumps(payload)}));"
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20).stdout
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)
        self.assertIn("<h3>", out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<ul><li>", out)

    def test_speech_text_matches_written_text(self):
        md = "## Premise\n\nElena keeps the **light**.\n\n- First point\n- Second point"
        self.assertEqual(bi.speech_text(md), "Premise.\n\nElena keeps the light.\n\nFirst point\nSecond point")


# ===========================================================================
# Generation through the HTTP API
# ===========================================================================

class TestGeneration(InsightsBase):

    def test_basic_summary_auto_language(self):
        st, t = generate(self.en_job, "summary")
        rec = t["result"]
        self.assertEqual(rec["insight_type"], "short_summary")
        self.assertEqual(rec["language"], "english")
        self.assertTrue(150 * 0.85 <= rec["word_count"] <= 300 * 1.25, rec["word_count"])
        self.assertNotIn("##", rec["text"])
        st2, t2 = generate(self.gr_job, "summary")
        self.assertEqual(t2["result"]["language"], "greek")

    def test_basic_synopsis(self):
        st, t = generate(self.en_job, "synopsis")
        rec = t["result"]
        self.assertEqual(rec["insight_type"], "standard_synopsis")
        self.assertGreaterEqual(len(re.findall(r"^## ", rec["text"], re.M)), 2)
        self.assertTrue(800 * 0.85 <= rec["word_count"] <= 1200 * 1.25, rec["word_count"])

    def test_all_advanced_types_greek_and_english(self):
        counts = {}
        for lang in ("greek", "english"):
            for itype in bi.INSIGHT_TYPES:
                st, t = generate(self.en_job, itype, lang)
                self.assertEqual(st, 200)
                rec = t["result"]
                self.assertEqual(rec["language"], lang)
                lo, hi = rec["target_words"]
                if itype == "one_sentence":
                    self.assertEqual(bi._sentence_count(rec["text"]), 1)
                    self.assertTrue(20 <= rec["word_count"] <= 40 + 10, rec["word_count"])
                else:
                    self.assertGreaterEqual(rec["word_count"], lo * 0.85)
                    self.assertLessEqual(rec["word_count"], hi * 1.25)
                letters = [c for c in rec["text"] if c.isalpha()]
                greek_share = sum(1 for c in letters if "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿") / len(letters)
                self.assertGreater(greek_share, 0.6) if lang == "greek" else self.assertLess(greek_share, 0.2)
                counts[(lang, itype)] = rec["word_count"]
        for lang in ("greek", "english"):
            self.assertGreater(counts[(lang, "extended_synopsis")], counts[(lang, "standard_synopsis")])
            self.assertGreater(counts[(lang, "standard_synopsis")], counts[(lang, "short_summary")])
            self.assertGreater(counts[(lang, "extended_summary")], counts[(lang, "short_summary")])

    def test_summary_and_synopsis_are_different(self):
        _, s = generate(self.en_job, "short_summary", "english")
        _, y = generate(self.en_job, "standard_synopsis", "english")
        self.assertLess(bi.similarity(s["result"]["text"], y["result"]["text"]), 0.6)

    def test_results_are_cached_without_new_api_calls(self):
        generate(self.gr_job, "one_sentence", "english")
        n = len(FAKE.calls)
        _, t = generate(self.gr_job, "one_sentence", "english")
        self.assertTrue(t["result"].get("reused"))
        self.assertEqual(len(FAKE.calls), n)
        st, lst = api("GET", f"/insights/{self.gr_job}")
        self.assertTrue(any(i["insight_type"] == "one_sentence" for i in lst["insights"]))

    def test_long_document_uses_map_reduce(self):
        job = new_doc_job(make_doc(_EN_SENTENCES, 30000), name="test_insights_long.txt")
        _, t = generate(job, "short_summary", "english")
        self.assertTrue(t["result"]["from_notes"])
        notes_calls = [c for c in FAKE.calls if "research notes" in c]
        self.assertGreaterEqual(len(notes_calls), 3)

    def test_quality_gate_retries_then_succeeds(self):
        FAKE.mode = "wrong_lang_once"
        job = new_doc_job(make_doc(_EN_SENTENCES, 3000), name="test_insights_retry.txt")
        _, t = generate(job, "extended_summary", "greek")
        self.assertEqual(t["status"], "done")
        self.assertEqual(len([c for c in FAKE.calls if "REJECTED" in c]), 1)

    def test_defective_output_is_never_shown(self):
        for mode in ("wrong_lang_always", "fabricate"):
            FAKE.reset()
            FAKE.mode = mode
            job = new_doc_job(make_doc(_EN_SENTENCES, 2000), name=f"test_insights_{mode}.txt")
            st, t = generate(job, "short_summary", "english", expect_ok=False)
            self.assertEqual(t["status"], "error", mode)
            self.assertIsNone(t["result"])
            self.assertIn("ποιότητας", t["error"]["message"])
            st2, lst = api("GET", f"/insights/{job}")
            self.assertEqual(lst["insights"], [], "rejected text must not be stored")


class TestErrors(InsightsBase):

    def test_ai_failures_map_to_user_messages(self):
        expected = {"quota": "quota_exhausted", "network": "network_error", "auth": "auth_failed", "generic": "ai_failed"}
        for mode, code in expected.items():
            FAKE.reset()
            FAKE.mode = mode
            job = new_doc_job(make_doc(_EN_SENTENCES, 800), name=f"test_insights_err_{mode}.txt")
            st, t = generate(job, "short_summary", "english", expect_ok=False)
            self.assertEqual(t["status"], "error")
            self.assertEqual(t["error"]["code"], code)
            self.assertTrue(len(t["error"]["message"]) > 20)

    def test_no_api_key(self):
        with mock.patch("backend.gemini_key_pool.resolve_gemini_api_key", return_value=""):
            st, data = api("POST", "/insights/generate", {"job_id": self.en_job, "insight_type": "summary"})
            self.assertEqual(st, 401)
            self.assertIn("Gemini", data["detail"])
            st2, a = api("GET", f"/insights/{self.en_job}/analysis")
            self.assertFalse(a["has_api_key"])
        self.assertEqual(FAKE.calls, [])

    def test_too_short_and_insufficient_documents(self):
        short = new_doc_job(" ".join(_EN_SENTENCES * 2), name="test_insights_short.txt")   # ~150 words
        st, a = api("GET", f"/insights/{short}/analysis")
        self.assertTrue(a["can_summary"])
        self.assertFalse(a["can_synopsis"])
        st, data = api("POST", "/insights/generate", {"job_id": short, "insight_type": "synopsis", "api_key": "k"})
        self.assertEqual(st, 422)
        self.assertIn("1,5", data["detail"])
        st_ok, t = generate(short, "summary")
        self.assertEqual(t["status"], "done")
        tiny = new_doc_job("Only a few words here.", name="test_insights_tiny.txt")
        calls_before = len(FAKE.calls)
        st, data = api("POST", "/insights/generate", {"job_id": tiny, "insight_type": "summary", "api_key": "k"})
        self.assertEqual(st, 422)
        self.assertEqual(len(FAKE.calls), calls_before, "ineligible documents must not consume API calls")

    def test_language_detection_failure(self):
        job = new_doc_job(("Ж" * 6 + " ") * 400, name="test_insights_cyr.txt")
        st, data = api("POST", "/insights/generate", {"job_id": job, "insight_type": "summary", "api_key": "k"})
        self.assertEqual(st, 422)
        self.assertIn("γλώσσας", data["detail"])
        st2, t = generate(job, "short_summary", "english", expect_ok=False)  # explicit language still allowed
        self.assertEqual(st2, 200)

    def test_extraction_failure_and_unsupported_format(self):
        job = create_job("", "test_insights_broken.pdf", "pdf")
        bad = UPLOADS / job.job_id / "test_insights_broken.pdf"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
        update_job(job.job_id, file_path=str(bad))
        st, data = api("GET", f"/insights/{job.job_id}/analysis")
        self.assertIn(st, (400, 422))
        self.assertTrue(data.get("detail"))
        comic = create_job("", "test_insights_comic.cbz", "cbz")
        st2, data2 = api("GET", f"/insights/{comic.job_id}/analysis")
        self.assertEqual(st2, 400)
        self.assertIn("δεν υποστηρίζεται", data2["detail"])
        st3, _ = api("GET", "/insights/not-a-job/analysis")
        self.assertIn(st3, (400, 404))

    def test_invalid_options(self):
        for payload in ({"insight_type": "poem"}, {"insight_type": "summary", "language": "klingon"}):
            st, _ = api("POST", "/insights/generate", {"job_id": self.en_job, "api_key": "k", **payload})
            self.assertEqual(st, 400)


class TestExportAudioAndSafety(InsightsBase):

    def test_exports_pdf_docx_txt(self):
        generate(self.en_job, "standard_synopsis", "english")
        for fmt in ("pdf", "docx", "doc", "txt"):
            st, data = api("POST", "/insights/export", {"job_id": self.en_job, "insight_type": "standard_synopsis",
                                                         "language": "english", "format": fmt})
            self.assertEqual(st, 200, data)
            st2, raw = api("GET", data["url"][len("/api"):], raw=True)
            self.assertEqual(st2, 200)
            if fmt == "pdf":
                self.assertTrue(raw.startswith(b"%PDF"))
            elif fmt in ("docx", "doc"):
                self.assertTrue(raw.startswith(b"PK"))
                from docx import Document
                import io
                doc = Document(io.BytesIO(raw))
                self.assertTrue(any(p.style.name.startswith("Heading") for p in doc.paragraphs))
            else:
                txt = raw.decode("utf-8")
                self.assertIn("Premise", txt)          # heading kept as plain text
                self.assertIn("The novel opens on the cape", txt)
                self.assertNotIn("##", txt)
        st, _ = api("POST", "/insights/export", {"job_id": self.en_job, "insight_type": "extended_synopsis",
                                                 "language": "greek", "format": "rtf"})
        self.assertIn(st, (400, 404))

    def test_export_failure_is_reported(self):
        generate(self.en_job, "short_summary", "english")
        with mock.patch("backend.exporter.export_text", side_effect=OSError("disk full")):
            st, data = api("POST", "/insights/export", {"job_id": self.en_job, "insight_type": "short_summary",
                                                         "language": "english", "format": "pdf"})
        self.assertEqual(st, 500)
        self.assertIn("αποθήκευση", data["detail"])

    def _audio(self, itype, lang):
        _, t = generate(self.en_job, itype, lang)
        SPOKEN.clear()
        st, d = api("POST", "/insights/audio", {"job_id": self.en_job, "insight_type": itype, "language": lang})
        self.assertEqual(st, 200, d)
        return t["result"], wait_task(d["task_id"])

    def test_audio_summary_and_synopsis_match_final_text(self):
        for itype, lang in (("one_sentence", "english"), ("short_summary", "greek"), ("extended_summary", "english"),
                            ("standard_synopsis", "greek"), ("extended_synopsis", "english")):
            rec, task = self._audio(itype, lang)
            self.assertEqual(task["status"], "done", task)
            self.assertTrue(task["result"]["audio_url"].endswith(".mp3"))
            spoken = re.sub(r"\s+", " ", " ".join(SPOKEN)).strip()
            expected = re.sub(r"\s+", " ", bi.speech_text(rec["text"])).strip()
            self.assertEqual(spoken, expected, f"{itype}/{lang}: audio must narrate exactly the final text")
            st, raw = api("GET", task["result"]["audio_url"][len("/api"):], raw=True)
            self.assertEqual(st, 200)
            self.assertTrue(raw[:3] == b"ID3" or raw[:2] == b"\xff\xfb")

    def test_audio_failure_produces_no_file(self):
        generate(self.gr_job, "extended_synopsis", "greek")
        fake_tts.fail = True
        st, d = api("POST", "/insights/audio", {"job_id": self.gr_job, "insight_type": "extended_synopsis", "language": "greek"})
        t = wait_task(d["task_id"])
        self.assertEqual(t["status"], "error")
        self.assertEqual(t["error"]["code"], "audio_failed")
        self.assertEqual(list((OUTPUTS / self.gr_job / "insights").glob("*extended_synopsis_greek.mp3")), [])
        self.assertEqual(list((OUTPUTS / self.gr_job / "insights").glob(".tts_*")), [])

    def test_audio_requires_generated_text(self):
        job = new_doc_job(make_doc(_EN_SENTENCES, 900), name="test_insights_noaudio.txt")
        st, data = api("POST", "/insights/audio", {"job_id": job, "insight_type": "short_summary", "language": "english"})
        self.assertEqual(st, 404)

    def test_duplicate_and_concurrent_requests(self):
        FAKE.delay = 0.6
        job = new_doc_job(make_doc(_EN_SENTENCES, 1200), name="test_insights_dup.txt")
        body = {"job_id": job, "insight_type": "short_summary", "language": "english", "api_key": "k"}
        st1, a = api("POST", "/insights/generate", body)
        st2, b = api("POST", "/insights/generate", body)
        self.assertFalse(a["duplicate"])
        self.assertTrue(b["duplicate"])
        self.assertEqual(a["task_id"], b["task_id"])
        st3, c = api("POST", "/insights/generate", {**body, "insight_type": "standard_synopsis"})
        self.assertNotEqual(c["task_id"], a["task_id"])
        self.assertEqual(wait_task(a["task_id"])["status"], "done")
        self.assertEqual(wait_task(c["task_id"])["status"], "done")
        self.assertEqual(len([x for x in FAKE.calls if "SHORT SUMMARY" in x]), 1, "duplicate must not call the AI twice")

    def test_file_endpoint_rejects_traversal(self):
        for bad in ("..%2F..%2Fconfig%2Fsettings.json", ".hidden.mp3", "x.json", "missing.pdf"):
            st, _ = api("GET", f"/insights/{self.en_job}/files/{bad}")
            self.assertIn(st, (400, 404), bad)
        st, _ = api("GET", "/insights/tasks/../../etc")
        self.assertIn(st, (400, 404))

    def test_doc_translate_and_audiobook_state_untouched(self):
        update_job(self.en_job, status="done", mode="translate", output_path=None, progress=100, current_step="Exported PDF")
        before = get_job(self.en_job)
        snap = (before.status, before.mode, before.output_path, before.progress, before.current_step)
        generate(self.en_job, "extended_summary", "english")
        st, d = api("POST", "/insights/audio", {"job_id": self.en_job, "insight_type": "extended_summary", "language": "english"})
        wait_task(d["task_id"])
        after = get_job(self.en_job)
        self.assertEqual(snap, (after.status, after.mode, after.output_path, after.progress, after.current_step))
        # The translation download fallback must never serve insight files
        st, _ = api("GET", f"/download/{self.en_job}", raw=True)
        self.assertEqual(st, 404)


class TestInsightText(unittest.TestCase):
    def test_only_meta_lines_are_dropped(self):
        from backend import book_insights
        for line, language in (("Ακολουθεί η εξέγερση των εργατών και η ήττα τους.", "greek"),
                               ("Λέξεις και σιωπή είναι τα δύο θέματα του έργου.", "greek"),
                               ("Σημείωση και υστερόγραφο κλείνουν το μυθιστόρημα.", "greek"),
                               ("Here is where the story turns against the captain.", "english"),
                               ("Note the recurring image of the sea in every chapter.", "english")):
            self.assertIn(line, book_insights.normalize_output(f"Start of it.\n\n{line}", language))
        for line in ("Here is the summary:", "Word count: 245", "**Word count:** 245", "(245 words)",
                     "Ακολουθεί η περίληψη:", "Note: written from the notes.", "This synopsis covers the whole book."):
            self.assertEqual(book_insights.normalize_output(f"{line}\n\nThe text.", "english"), "The text.", line)

    def test_sections_keep_the_order_of_the_book(self):
        from backend import book_insights
        text = "first paragraph\n\n" + "giant " * 40 + "\n\nlast paragraph"
        sections = book_insights.split_sections(text, max_chars=100)
        self.assertEqual("".join("".join(sections).split()), "".join(text.split()))

    def test_a_leaked_request_label_is_rejected(self):
        from backend import book_insights
        text = "The captain counts the boats. " * 30 + "\n--- INPUT TEXT ---"
        critical, _warnings = book_insights.validate_output(text, "short_summary", "english", 100, 300, text * 5, "english")
        self.assertIn("prompt text leaked into output", critical)


if __name__ == "__main__":
    unittest.main()
