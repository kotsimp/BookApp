"""
test_book_insights_more.py - More Book Insights (backend/insights_more.py): characters & terms, chapter by chapter, the
story so far, the back-cover blurb, memorable quotes, the study guide, the timeline and questions to the book.

Gemini is replaced in-process (backend.ai_polisher._call_gemini_api) by a stand-in that answers each task like a model
would, including the mistakes the checks must catch: names that are not in the book, passages that are not word for
word, wrong pages, a chapter left out, the wrong language. A private uvicorn server in this process runs the API.

Covers: pages and their unit (PDF/TXT pages, EPUB chapters); chapter detection and the equal-parts fallback; every
type's content, structure, language and checks; invented names dropped; first pages computed from the book; quotes
verified word for word with their real page; a recap written only from the pages read; the timeline in story order,
and the told order when the ordering loses events; questions answered with cited pages, kept newest first; relevant
pages of a long book; stored results reused without requests; the Glossary from a characters record; the e-reader
catalogue's blurb; and through the API generation, export, glossary, questions, input checks, comics refused, and the
existing summaries unchanged.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import asyncio
import json
import re
import socket
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from backend import book_insights as bi
from backend import insights_more as im
from backend.job_manager import create_job, update_job, cleanup_test_jobs

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "temp" / "uploads"

STORY = [
    "Elena Markou keeps the old lighthouse of Port Avra and writes down every ship that passes the cape.",
    "Her brother Nikos returns from the city after many years and asks her to sell the lighthouse.",
    "The harbour council wants to replace the keeper with an automatic lamp before the winter of 1987.",
    "Elena refuses, because the lighthouse is the last thing that connects her with their father.",
    "During a violent storm a fishing boat loses its engine near the northern rocks.",
    "Nikos and Elena climb the tower together and keep the light burning through the night.",
    "The sailors are saved, and the council finally understands why a human keeper still matters.",
    "In the final chapter Nikos decides to stay in Port Avra and helps his sister repair the tower.",
]


def book_text(chapters: int = 4, paras_per_chapter: int = 8, headings: bool = True) -> str:
    out = []
    names = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"]
    for c in range(chapters):
        if headings:
            out.append(f"Chapter {names[c]}")
        for k in range(paras_per_chapter):
            i = c * paras_per_chapter + k
            out.append(" ".join(STORY[(i + j) % len(STORY)] for j in range(3)) + f" (Scene {c + 1}.{k + 1}.)")
    return "\n\n".join(out)


def write_book(text: str, folder: Path, name: str = "lighthouse.txt") -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The stand-in Gemini
# ---------------------------------------------------------------------------

GR_LINES = ["Η Ελένη Μάρκου φυλάει τον φάρο της Αύρας και ο αδελφός της ο Νίκος επιστρέφει από την πόλη.",
            "Το συμβούλιο θέλει αυτόματο φανό, όμως η Ελένη αρνείται να φύγει από τον πύργο.",
            "Στην καταιγίδα κρατούν μαζί το φως αναμμένο και οι ψαράδες σώζονται."]
EN_LINES = ["Elena Markou keeps the lighthouse of Port Avra while her brother Nikos returns from the city.",
            "The council wants an automatic lamp, but Elena refuses to leave the tower.",
            "In the storm they keep the light burning together and the sailors are saved."]


class FakeGemini:
    def __init__(self):
        self.reset()

    def reset(self):
        self.calls = []
        self.mode = "ok"
        self.dropped_chapter = False
        self.wrong_order = False

    def lines(self, greek: bool, n: int) -> str:
        pool = GR_LINES if greek else EN_LINES
        return " ".join(pool[i % len(pool)] for i in range(n))

    async def __call__(self, content, api_key, system_prompt, session=None, temperature=0.25, exclude_models=None,
                       bypass_cache=False, meta_out=None, cache_gate=None):
        from backend.ai_polisher import DailyQuotaExhaustedError
        assert cache_gate is not None and cache_gate("x") and not cache_gate("  ")
        sp = system_prompt
        self.calls.append((sp, content))
        if self.mode == "quota":
            raise DailyQuotaExhaustedError("⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier).")
        greek = "Modern Greek" in sp
        if self.mode == "wrong_lang":
            greek = not greek
        if "research notes" in sp:
            return "- " + " ".join(content.split()[:200])
        if "proofreader" in sp:
            return content
        if "list the PEOPLE" in sp:
            people = [{"name": "Elena Markou", "name_out": "Ελένη Μάρκου" if greek else "Elena Markou",
                       "role": "Η φύλακας του φάρου." if greek else "The keeper of the lighthouse.",
                       "relations": "Αδελφή του Νίκου." if greek else "Sister of Nikos."},
                      {"name": "Nikos", "name_out": "Νίκος" if greek else "Nikos",
                       "role": "Ο αδελφός της που επιστρέφει." if greek else "Her brother who returns.",
                       "relations": ""},
                      {"name": "Captain Zorbas", "name_out": "Καπετάν Ζορμπάς",
                       "role": "Ένας καπετάνιος." if greek else "A captain.", "relations": ""}]
            terms = [{"term": "harbour council", "term_out": "λιμενικό συμβούλιο" if greek else "harbour council",
                      "definition": "Η αρχή του λιμανιού." if greek else "The authority of the harbour."}]
            return "```json\n" + json.dumps({"people": people, "terms": terms}, ensure_ascii=False) + "\n```"
        if "summarise EACH chapter" in sp:
            out = []
            for n, title in re.findall(r"<<CH (\d+)>> ?([^\n]*)", content):
                if self.mode == "drop_chapter" and n == "2" and not self.dropped_chapter:
                    self.dropped_chapter = True
                    continue
                out.append({"n": int(n), "title": (f"Κεφάλαιο {n}" if greek else f"Chapter {n}"),
                            "summary": self.lines(greek, 2)})
            return json.dumps({"chapters": out}, ensure_ascii=False)
        if "THE STORY SO FAR" in sp or "BACK-COVER BLURB" in sp:
            return self.lines(greek, 4 if "BLURB" in sp else 6)
        if "memorable, meaningful passages" in sp:
            pages = re.findall(r"\[\[(\d+)\]\]\n([^\n]+)", content)
            quotes = []
            if pages:
                page, text = pages[0]
                sentence = re.split(r"(?<=\.) ", text)[0]
                quotes.append({"quote": sentence, "page": int(page), "note": "Δείχνει τον φάρο." if greek else "It shows the lighthouse."})
                quotes.append({"quote": "The lighthouse was the brightest star in the whole wide world.",
                               "page": int(page), "note": "Επινοημένο." if greek else "Invented."})
                if len(pages) > 1:
                    later = re.split(r"(?<=\.) ", pages[-1][1])[1]
                    quotes.append({"quote": later, "page": int(page), "note": "Σε άλλη σελίδα." if greek else "On another page."})
            return json.dumps({"quotes": quotes}, ensure_ascii=False)
        if "STUDY GUIDE" in sp:
            heads = ["Θέματα", "Ερωτήσεις συζήτησης", "Κουίζ", "Απαντήσεις"] if greek else \
                ["Themes", "Discussion questions", "Quiz", "Answers"]
            count = 2 if self.mode == "short_guide" else 4
            return "\n\n".join(f"## {h}\n{self.lines(greek, 5)}" for h in heads[:count])
        if "list the main EVENTS" in sp:
            pages = [int(p) for p in re.findall(r"\[\[(\d+)\]\]", content)]
            events = [{"page": p, "when": ("χειμώνας 1987" if greek else "winter 1987") if k == 0 else "",
                       "event": self.lines(greek, 1)} for k, p in enumerate(pages[:2])]
            return json.dumps({"events": events}, ensure_ascii=False)
        if "in the order they HAPPEN" in sp:
            events = json.loads(content)["events"]
            if self.mode == "lossy_order":  # an ordering that lost every event
                events = []
            return json.dumps({"events": list(reversed(events))}, ensure_ascii=False)
        if "answer a reader's question" in sp:
            page = (re.findall(r"\[\[(\d+)\]\]", content) or ["1"])[0]
            ref = "σ." if greek else "p."
            body = GR_LINES[0] if greek else EN_LINES[0]
            return f"{body} ({ref} {page})"
        if "SHORT SUMMARY" in sp:
            return "\n\n".join([self.lines(greek, 7), self.lines(greek, 6)])
        return self.lines(greek, 3)


FAKE = FakeGemini()


def run(coro):
    return asyncio.run(coro)


class ModuleTests(unittest.TestCase):
    def setUp(self):
        FAKE.reset()
        self.patch = mock.patch("backend.ai_polisher._call_gemini_api", FAKE)
        self.patch.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.book = write_book(book_text(), self.dir)
        self.out = self.dir / "out"
        self.out.mkdir()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def make(self, insight_type, language="greek", **kw):
        return run(im.generate_extra(str(self.book), "txt", insight_type, language, "fake-key",
                                     title="lighthouse", job_output_dir=self.out, **kw))

    # ---- the book page by page ----

    def test_pages_and_units(self):
        pages, unit = im.extract_pages(str(self.book), "txt")
        self.assertEqual(unit, "page")
        self.assertGreater(len(pages), 3)
        self.assertEqual([n for n, _ in pages], list(range(1, len(pages) + 1)))
        self.assertTrue(all("[[" not in t and "⟦" not in t for _, t in pages))
        from ebooklib import epub
        book = epub.EpubBook()
        book.set_identifier("x")
        book.set_title("Lighthouse")
        book.set_language("en")
        chapters = []
        for i in range(3):
            ch = epub.EpubHtml(title=f"C{i}", file_name=f"c{i}.xhtml", lang="en")
            ch.content = f"<h1>Chapter {i + 1}</h1>" + "".join(f"<p>{s}</p>" for s in STORY)
            book.add_item(ch)
            chapters.append(ch)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = chapters
        epub.write_epub(str(self.dir / "b.epub"), book)
        pages, unit = im.extract_pages(str(self.dir / "b.epub"), "epub")
        self.assertEqual(unit, "chapter")
        found = im.detect_chapters(pages, unit)
        self.assertEqual([c["title"] for c in found], ["Chapter 1", "Chapter 2", "Chapter 3"])
        with self.assertRaises(bi.InsightsError):
            im.extract_pages(str(self.dir / "b.cbz"), "cbz")

    def test_chapters_from_headings_or_equal_parts(self):
        pages, unit = im.extract_pages(str(self.book), "txt")
        chapters = im.detect_chapters(pages, unit)
        self.assertEqual([c["title"] for c in chapters], ["Chapter One", "Chapter Two", "Chapter Three", "Chapter Four"])
        self.assertTrue(all(c["first"] <= c["last"] for c in chapters))
        self.assertEqual([c["n"] for c in chapters], [1, 2, 3, 4])
        plain = write_book(book_text(chapters=6, headings=False), self.dir, "plain.txt")
        pages, unit = im.extract_pages(str(plain), "txt")
        parts = im.detect_chapters(pages, unit)
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(all(p["title"] is None for p in parts))
        self.assertEqual(sum(p["last"] - p["first"] + 1 for p in parts), len(pages), "every page in one part")

    # ---- each kind ----

    def test_characters_and_glossary(self):
        rec = self.make("characters")
        names = [p["name"] for p in rec["data"]["people"]]
        self.assertEqual(names, ["Elena Markou", "Nikos"], "a name the book does not have is dropped")
        self.assertEqual(rec["data"]["people"][0]["first"], 1)
        self.assertIn("- **Ελένη Μάρκου** (Elena Markou) — Η φύλακας του φάρου. Σχέσεις: Αδελφή του Νίκου. · σ. 1",
                      rec["text"])
        self.assertIn("## Πρόσωπα", rec["text"])
        self.assertIn("## Όροι", rec["text"])
        self.assertEqual(rec["label"], "Πρόσωπα & όροι")
        self.assertEqual(im.glossary_items(rec), [("Elena Markou", "Ελένη Μάρκου"), ("Nikos", "Νίκος"),
                                                  ("harbour council", "λιμενικό συμβούλιο")])
        stored = bi.load_insight(self.out, "characters", "greek")
        self.assertEqual(stored["text"], rec["text"])
        english = self.make("characters", "english")
        self.assertEqual(im.glossary_items(english), [], "no Greek spellings in an English list")

    def test_chapter_summaries_and_a_missed_chapter(self):
        FAKE.mode = "drop_chapter"
        rec = self.make("chapter_summaries")
        self.assertTrue(FAKE.dropped_chapter, "the stand-in left chapter 2 out once")
        self.assertEqual([c["n"] for c in rec["data"]["chapters"]], [1, 2, 3, 4])
        self.assertTrue(all(c["summary"] for c in rec["data"]["chapters"]), "the missed chapter is asked again")
        self.assertEqual(bi._heading_count(rec["text"]), 4)
        self.assertRegex(rec["text"], r"## 1\. Κεφάλαιο 1\n.+ \(σ\. 1(–\d+)?\)")
        self.assertEqual(rec["warnings"], [])

    def test_recap_reads_only_the_pages_read(self):
        pages, _ = im.extract_pages(str(self.book), "txt")
        rec = self.make("recap", until=2)
        self.assertEqual(rec["label"], "Η ιστορία ως τώρα (σ. 2)")
        given = [c for sp, c in FAKE.calls if "THE STORY SO FAR" in sp][0]
        scenes = lambda text: set(re.findall(r"\(Scene \d+\.\d+\.\)", text))  # noqa: E731  (unique per paragraph)
        self.assertTrue(scenes(pages[1][1]) & scenes(given), "the chosen page reaches the model")
        for _, later in pages[2:]:
            self.assertFalse((scenes(later) - scenes(pages[1][1])) & scenes(given),
                             "nothing after the chosen page reaches the model")
        self.assertEqual(rec["until"], 2)
        with self.assertRaises(bi.InsightsError):
            self.make("recap", until=None)
        with self.assertRaises(bi.InsightsError):
            self.make("recap", until=0)

    def test_blurb_and_the_catalogue_description(self):
        rec = self.make("blurb")
        self.assertGreater(bi.count_words(rec["text"]), 40)
        from backend.api import connections as api
        job = types.SimpleNamespace(job_id="lighthouse-job", target_lang="greek")
        (self.dir / "lighthouse-job").mkdir()
        bi.save_insight(self.dir / "lighthouse-job", rec)
        with mock.patch.object(api, "OUTPUT_DIR", self.dir):
            self.assertEqual(api._blurb(job), rec["text"])
            self.assertEqual(api._blurb(types.SimpleNamespace(job_id="none", target_lang="greek")), "")

    def test_quotes_are_word_for_word_with_their_page(self):
        pages, _ = im.extract_pages(str(self.book), "txt")
        rec = self.make("quotes")
        quotes = rec["data"]["quotes"]
        self.assertTrue(quotes)
        for q in quotes:
            page_text = dict(pages)[q["page"]]
            self.assertIn(im._fold(q["quote"]), im._fold(page_text), "every quote is on its page, word for word")
        self.assertTrue(all("brightest star" not in q["quote"] for q in quotes), "an invented passage is left out")
        self.assertTrue(any("not found word for word" in w for w in rec["warnings"]))
        self.assertIn("**«", rec["text"])
        self.assertIsNone(im.verify_quote("Too short.", 1, pages))
        self.assertEqual(im.verify_quote(" ".join(STORY[0].split()) + "  ", None, pages),
                         next(n for n, t in pages if STORY[0] in t))

    def test_study_guide_needs_its_four_sections(self):
        rec = self.make("study_guide")
        self.assertEqual(bi._heading_count(rec["text"]), 4)
        FAKE.reset()
        FAKE.mode = "short_guide"
        with self.assertRaises(bi.InsightsError) as ctx:
            self.make("study_guide", "english")
        self.assertEqual(ctx.exception.code, "ai_output_rejected")
        self.assertEqual(sum(1 for sp, _ in FAKE.calls if "STUDY GUIDE" in sp), 2, "written once more, then refused")

    def test_timeline_in_story_order(self):
        rec = self.make("timeline", "english")
        events = rec["data"]["events"]
        told = [c for sp, c in FAKE.calls if "in the order they HAPPEN" in sp]
        self.assertEqual(len(told), 1)
        self.assertEqual([e["page"] for e in events], [e["page"] for e in reversed(json.loads(told[0])["events"])])
        self.assertIn("- **winter 1987** — ", rec["text"])
        FAKE.reset()
        FAKE.mode = "lossy_order"
        rec = self.make("timeline", "greek")
        self.assertIn("the events are in the order the book tells them", rec["warnings"])

    def test_wrong_language_and_quota(self):
        FAKE.mode = "wrong_lang"
        with self.assertRaises(bi.InsightsError) as ctx:
            self.make("blurb")
        self.assertEqual(ctx.exception.code, "ai_output_rejected")
        FAKE.reset()
        FAKE.mode = "quota"
        with self.assertRaises(bi.InsightsError) as ctx:
            self.make("characters")
        self.assertEqual(ctx.exception.code, "quota_exhausted")

    def test_stored_results_are_reused(self):
        first = self.make("chapter_summaries", "english")
        calls = len(FAKE.calls)
        again = self.make("chapter_summaries", "english")
        self.assertTrue(again.get("reused"))
        self.assertEqual(len(FAKE.calls), calls, "no request for a result already made")
        self.assertEqual(again["text"], first["text"])
        recap2 = self.make("recap", "english", until=2)
        recap3 = self.make("recap", "english", until=3)
        self.assertFalse(recap3.get("reused"), "another page is another recap")
        self.assertNotEqual(recap2["source_hash"], recap3["source_hash"])

    def test_questions(self):
        rec = run(im.ask_book(str(self.book), "txt", "Γιατί αρνείται η Ελένη να πουλήσει τον φάρο;", "auto",
                              "fake-key", title="lighthouse", job_output_dir=self.out))
        self.assertEqual(rec["language"], "greek")
        self.assertEqual(rec["pages"], [1])
        self.assertIn("(σ. 1)", rec["answer"])
        self.assertTrue(rec["whole_book"])
        rec2 = run(im.ask_book(str(self.book), "txt", "Who is Nikos?", "auto", "fake-key", job_output_dir=self.out))
        self.assertEqual(rec2["language"], "english")
        history = im.list_questions(self.out)
        self.assertEqual([h["question"] for h in history], ["Who is Nikos?", "Γιατί αρνείται η Ελένη να πουλήσει τον φάρο;"])
        run(im.ask_book(str(self.book), "txt", "Who is Nikos?", "english", "fake-key", job_output_dir=self.out))
        self.assertEqual(len(im.list_questions(self.out)), 2, "the same question is kept once")
        with self.assertRaises(bi.InsightsError):
            run(im.ask_book(str(self.book), "txt", "?", "auto", "fake-key"))

    def test_relevant_pages_of_a_long_book(self):
        pages = [(n, ("Weather notes about clouds and rain. " * 40)) for n in range(1, 60)]
        pages[30] = (31, "The keeper Elena hid the logbook under the stairs of the lighthouse. " * 10)
        chosen = im.relevant_pages("Where did Elena hide the logbook?", pages, budget=6000)
        numbers = [n for n, _ in chosen]
        self.assertIn(31, numbers)
        self.assertEqual(numbers, sorted(numbers), "in book order")
        self.assertLessEqual(sum(len(t) for _, t in chosen), 6000)
        self.assertEqual(im.relevant_pages("anything", pages[:3], budget=10_000), pages[:3], "a short book goes whole")

    def test_existing_types_are_unchanged(self):
        self.assertEqual(list(bi.INSIGHT_TYPES), ["one_sentence", "short_summary", "extended_summary",
                                                  "standard_synopsis", "extended_synopsis"])
        self.assertFalse(set(bi.INSIGHT_TYPES) & set(im.EXTRA_TYPES))
        with self.assertRaises(bi.InsightsError):
            run(im.generate_extra(str(self.book), "txt", "short_summary", "greek", "k"))


# ---------------------------------------------------------------------------
# Through the API (a private server in this process, so the stand-in applies)
# ---------------------------------------------------------------------------

_PORT = None


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


def new_job(text: str, name="test_insights_more.txt", layout=None):
    job = create_job("", name, "txt")
    src = UPLOADS / job.job_id / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(text, encoding="utf-8")
    update_job(job.job_id, file_path=str(src), file_type="txt", **({"layout_mode": layout} if layout else {}))
    return job.job_id


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = mock.patch("backend.ai_polisher._call_gemini_api", FAKE)
        cls.patch.start()
        _start_server()
        cls.job = new_job(book_text())

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cleanup_test_jobs()

    def setUp(self):
        FAKE.reset()

    def generate(self, insight_type, language="greek", **extra):
        st, data = api("POST", "/insights/generate", {"job_id": self.job, "insight_type": insight_type,
                                                       "language": language, "api_key": "fake-key", **extra})
        self.assertEqual(st, 200, data)
        return wait_task(data["task_id"])

    def test_every_kind_through_the_api(self):
        for kind in ("characters", "chapter_summaries", "blurb", "quotes", "study_guide", "timeline"):
            t = self.generate(kind)
            self.assertEqual(t["status"], "done", (kind, t.get("error")))
            self.assertEqual(t["result"]["insight_type"], kind)
            self.assertTrue(t["result"]["text"])
        t = self.generate("recap", until=2)
        self.assertEqual(t["status"], "done", t.get("error"))
        st, listing = api("GET", f"/insights/{self.job}")
        kinds = {r["insight_type"] for r in listing["insights"]}
        self.assertTrue({"characters", "chapter_summaries", "recap", "blurb", "quotes", "study_guide", "timeline"} <= kinds)

    def test_export_glossary_and_checks(self):
        self.assertEqual(self.generate("characters")["status"], "done")
        st, data = api("POST", "/insights/export", {"job_id": self.job, "insight_type": "characters",
                                                     "language": "greek", "format": "pdf"})
        self.assertEqual(st, 200, data)
        st, pdf = api("GET", data["url"].replace("/api", "", 1), raw=True)
        self.assertEqual(st, 200)
        self.assertTrue(pdf.startswith(b"%PDF"))
        st, added = api("POST", "/insights/glossary", {"job_id": self.job, "language": "greek"})
        self.assertEqual(st, 200, added)
        self.assertEqual(added["added"], 3)
        st, glossary = api("GET", "/glossary")
        self.assertEqual(glossary.get("Elena Markou"), "Ελένη Μάρκου")
        st, only = api("POST", "/insights/glossary", {"job_id": self.job, "language": "greek", "sources": ["Nikos"]})
        self.assertEqual(only["added"], 1)
        st, err = api("POST", "/insights/glossary", {"job_id": self.job, "language": "english"})
        self.assertEqual(st, 404, "no English characters record yet")
        st, err = api("POST", "/insights/generate", {"job_id": self.job, "insight_type": "recap", "api_key": "k"})
        self.assertEqual(st, 400, "the story so far needs its page")
        st, err = api("POST", "/insights/generate", {"job_id": self.job, "insight_type": "poems", "api_key": "k"})
        self.assertEqual(st, 400)
        comic = new_job(book_text(), name="test_insights_comic.txt", layout="comic")
        st, err = api("POST", "/insights/generate", {"job_id": comic, "insight_type": "quotes", "api_key": "k"})
        self.assertEqual(st, 400, "comics have no text to quote")

    def test_questions_through_the_api(self):
        st, data = api("POST", "/insights/ask", {"job_id": self.job, "question": "Who keeps the lighthouse?",
                                                  "api_key": "fake-key"})
        self.assertEqual(st, 200, data)
        t = wait_task(data["task_id"])
        self.assertEqual(t["status"], "done", t.get("error"))
        self.assertIn("(p. 1)", t["result"]["answer"])
        st, listing = api("GET", f"/insights/{self.job}/questions")
        self.assertEqual(listing["questions"][0]["question"], "Who keeps the lighthouse?")
        st, err = api("POST", "/insights/ask", {"job_id": self.job, "question": "?", "api_key": "k"})
        self.assertEqual(st, 400)

    def test_analysis_gives_the_page_range(self):
        st, a = api("GET", f"/insights/{self.job}/analysis")
        self.assertEqual(st, 200)
        self.assertEqual((a["first_page"], a["unit"]), (1, "page"))
        self.assertGreater(a["last_page"], 3)

    def test_existing_summaries_still_work(self):
        st, data = api("POST", "/insights/generate", {"job_id": self.job, "insight_type": "summary",
                                                       "language": "english", "api_key": "fake-key"})
        self.assertEqual(st, 200, data)
        t = wait_task(data["task_id"])
        self.assertEqual(t["status"], "done", t.get("error"))
        self.assertEqual(t["result"]["insight_type"], "short_summary")


if __name__ == "__main__":
    unittest.main()
