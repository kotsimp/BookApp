"""
insights_more.py - More Book Insights, next to the summaries and synopses of book_insights.py (which stay as they are):

* characters   - the people (and, for non-fiction or invented worlds, the key terms) with roles, relations and the page
                 where each first appears; the names can go to the Glossary with their Greek spelling
* chapter_summaries - a few sentences per chapter (EPUB chapters, chapter headings, or equal parts of the book)
* recap        - "the story so far" up to a page (or chapter) the reader chooses: written only from the text up to there
* blurb        - a back-cover text that gives nothing away (also the book's description in the e-reader catalogue)
* quotes       - memorable passages, each checked word for word against the book, with its page
* study_guide  - themes, discussion questions, a quiz and its answers
* timeline     - the main events in the order they happen in the story, with their pages
* ask_book     - a question answered from the book, with the pages it rests on

Built on book_insights: the same Gemini access (key pool, cache), notes for long books, Greek proofreading, records in
the job's insights/ folder, PDF/DOCX/TXT export and narration.
"""

import asyncio
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend import book_insights as bi
from backend.book_insights import InsightsError, OUTPUT_LANGUAGES

logger = logging.getLogger(__name__)

EXTRA_VERSION = "1.2"   # bump when prompts/checks change: stored results are made again
# ...or one kind's own version, so only its stored results are made again (drop these when EXTRA_VERSION moves on)
KIND_VERSIONS = {"characters": "1.2-c2"}  # c2: the work's own pages only, no authors or quoted writers


def record_version(insight_type: str) -> str:
    return KIND_VERSIONS.get(insight_type, EXTRA_VERSION)
SECTION_CHARS = 45_000  # one request's share of a long book (as the notes of book_insights)
CHAPTER_BATCH_CHARS = 120_000
CHAPTER_MAX_CHARS = 110_000  # a longer chapter (a part of a novel)
PIECE_CHARS = 60_000  # ... is summarised in pieces of about this size, cut where pages end
ASK_FULL_CHARS = 350_000  # a book up to this size goes whole with a question; a longer one by its relevant parts
MAX_PEOPLE = 40
MAX_TERMS = 40
MAX_QUOTES = 12
MAX_EVENTS = 40
QA_KEEP = 30

EXTRA_TYPES: Dict[str, Dict[str, str]] = {
    "characters": {"kind": "characters"},
    "chapter_summaries": {"kind": "chapters"},
    "chapter": {"kind": "chapter"},  # one chapter in detail (with `chapter`: its number in detect_chapters)
    "recap": {"kind": "recap"},
    "blurb": {"kind": "blurb"},
    "quotes": {"kind": "quotes"},
    "study_guide": {"kind": "study"},
    "timeline": {"kind": "timeline"},
}

LABELS = {
    "greek": {"characters": "Πρόσωπα & όροι", "chapter_summaries": "Περίληψη ανά κεφάλαιο", "chapter": "Κεφάλαιο",
              "recap": "Η ιστορία ως τώρα", "blurb": "Οπισθόφυλλο", "quotes": "Αξιομνημόνευτα αποσπάσματα",
              "study_guide": "Οδηγός μελέτης", "timeline": "Χρονολόγιο"},
    "english": {"characters": "Characters & terms", "chapter_summaries": "Chapter by chapter", "chapter": "Chapter",
                "recap": "The story so far", "blurb": "Back-cover blurb", "quotes": "Memorable quotes",
                "study_guide": "Study guide", "timeline": "Timeline"},
}
# headings and page labels in each output language ("other" = the book's own language: English labels)
WORDS = {
    "greek": {"people": "Πρόσωπα", "terms": "Όροι", "relations": "Σχέσεις", "page": "σ.", "chapter": "κεφ.",
              "pages": "Σελίδες", "chapters": "Κεφάλαια", "part": "Μέρος"},
    "english": {"people": "People", "terms": "Terms", "relations": "Relations", "page": "p.", "chapter": "ch.",
                "pages": "Pages", "chapters": "Chapters", "part": "Part"},
}


def _words(lang: str) -> Dict[str, str]:
    return WORDS["greek" if lang == "greek" else "english"]


def _label(insight_type: str, lang: str) -> str:
    return LABELS["greek" if lang == "greek" else "english"][insight_type]


# ---------------------------------------------------------------------------
# The book page by page
# ---------------------------------------------------------------------------

_PAGES_CACHE: Dict[str, Tuple[tuple, List[Tuple[int, str]]]] = {}
_MARK_RE = re.compile(r"^⟦PAGE (\d+)⟧$", re.MULTILINE)


def extract_pages(file_path: str, file_type: str) -> Tuple[List[Tuple[int, str]], str]:
    """[(page number, meaningful text)] with the parsers' own page numbers, and the unit those numbers count:
    'chapter' for an EPUB (its numbers are its chapters, or sections), else 'page'. Cached per file version."""
    ft = (file_type or "").lower().lstrip(".")
    if ft not in ("pdf", "docx", "epub", "txt"):
        raise InsightsError("unsupported_format", f"file_type={ft}")
    p = Path(file_path or "")
    if not p.is_file():
        raise InsightsError("extraction_failed", "source file missing", http_status=404)
    from backend.scan_reader import sidecar_path
    side = sidecar_path(str(p))
    version = (p.stat().st_mtime, side.stat().st_mtime if side.exists() else 0)
    key = str(p.resolve())
    cached = _PAGES_CACHE.get(key)
    if cached and cached[0] == version:
        return cached[1], ("chapter" if ft == "epub" else "page")
    try:
        from backend.parsers import parse_document
        raw = [(int(pg.get("page") or 0), pg.get("text") or "") for pg in parse_document(str(p), ft)]
    except Exception as e:
        raise InsightsError("extraction_failed", str(e))
    # running headers are found across the whole book, so the pages go through meaningful_text together
    joined = "\n\n".join(f"⟦PAGE {n}⟧\n{t}" for n, t in raw if t.strip())
    clean = bi.meaningful_text(joined)
    parts = _MARK_RE.split(clean)
    pages = [(int(parts[i]), parts[i + 1].strip()) for i in range(1, len(parts), 2) if parts[i + 1].strip()]
    if len(_PAGES_CACHE) >= 3:
        _PAGES_CACHE.pop(next(iter(_PAGES_CACHE)))
    _PAGES_CACHE[key] = (version, pages)
    return pages, ("chapter" if ft == "epub" else "page")


def marked(pages: List[Tuple[int, str]]) -> str:
    """The pages as the prompts give them: each page opened by [[N]]."""
    return "\n\n".join(f"[[{n}]]\n{t}" for n, t in pages)


def page_sections(pages: List[Tuple[int, str]], max_chars: int = SECTION_CHARS) -> List[List[Tuple[int, str]]]:
    """Consecutive pages in groups of at most ~max_chars (a longer page is a group of its own)."""
    groups: List[List[Tuple[int, str]]] = []
    size = 0
    for page in pages:
        if groups and size + len(page[1]) <= max_chars:
            groups[-1].append(page)
            size += len(page[1])
        else:
            groups.append([page])
            size = len(page[1])
    return groups


def _ref(lang: str, unit: str, a: int, b: Optional[int] = None) -> str:
    w = _words(lang)[unit]
    return f"{w} {a}" if b is None or b == a else f"{w} {a}–{b}"


# ---------------------------------------------------------------------------
# Answers, language and names
# ---------------------------------------------------------------------------

def parse_json(raw: str) -> Dict[str, Any]:
    """The JSON object inside a model's answer (code fences and stray text around it are ignored)."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    data = json.loads(s[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("the answer is not a JSON object")
    return data


def _greek_share(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    return sum(1 for ch in letters if "Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿") / max(len(letters), 1)


def language_problems(text: str, lang: str) -> List[str]:
    """Whether `text` (what the model wrote, not quotations of the book) is in the output language."""
    if not text or len(text) < 20:
        return []
    share = _greek_share(text)
    if lang == "greek":
        if share < 0.6:
            return ["the text is not in Greek"]
        if bi._latin_share_outside_quotes(text) > 0.06:
            return ["names and titles must be written in Greek"]
    if lang == "english" and share > 0.2:
        return ["the text is not in English"]
    return []


def _leak(text: str) -> bool:
    return bool(re.search(r"</?(?:SOURCE|DOCUMENT|TEXT)[^>]*>|STRICT RULES|TASK:", text or ""))


_ITALIC_RE = re.compile(r"(?<![*\w])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![*\w])")


def tidy(text: str, lang: str, unit: str) -> str:
    """A page cited the way the prompt marks pages ([[12]]) reads as the reader's page reference (σ. 12 / p. 12),
    and *italics*, which the page and the exports do not draw, lose their asterisks (**bold** stays)."""
    word = _words(lang)[unit]
    text = re.sub(r"\(\s*\[\[(\d+)\]\]\s*\)", lambda m: f"({word} {m.group(1)})", text or "")
    text = re.sub(r"\[\[(\d+)\]\]", lambda m: f"({word} {m.group(1)})", text)
    return _ITALIC_RE.sub(r"\1", text)


def _fold(s: str) -> str:
    """For finding a passage of the book: one form for quotes, dashes, accents' composition and spaces."""
    s = unicodedata.normalize("NFC", s or "").replace("­", "")
    s = re.sub(r"[“”„«»\"]", '"', s)
    s = re.sub(r"[‘’‚′`]", "'", s)
    s = re.sub(r"[‐‑‒–—―]", "-", s)
    s = re.sub(r"-\s*\n\s*", "", s)  # a word hyphenated at a line end
    s = re.sub(r"\s+", " ", s)
    return s.strip().casefold()


def _occurs(name: str, folded_book: str) -> bool:
    """A name of the book: found as written, or every word of it found (a full name split across the text)."""
    f = _fold(name).strip("\"' .,")
    if len(f) < 2:
        return False
    if f in folded_book:
        return True
    words = [w for w in re.findall(r"\w+", f) if len(w) >= 3]
    return bool(words) and all(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", folded_book) for w in words)


def _first_page(name: str, pages: List[Tuple[int, str]]) -> Optional[int]:
    f = _fold(name).strip("\"' .,")
    for n, t in pages:
        if f and f in _fold(t):
            return n
    word = max(re.findall(r"\w+", f) or [""], key=len)
    if len(word) >= 3:
        for n, t in pages:
            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", _fold(t)):
                return n
    return None


def _lang_rule(lang: str) -> str:
    if lang == "greek":
        return ("Write all your own text in Modern Greek (monotonic orthography) with flawless spelling and grammar. "
                "Write names and titles in Greek script, as a Greek translation of the book would (e.g. 'Lena' -> 'Λένα').")
    if lang == "english":
        return "Write all your own text in English."
    return "Write all your own text in the same language as the book."


# ---------------------------------------------------------------------------
# One generation
# ---------------------------------------------------------------------------

@dataclass
class _Ctx:
    pages: List[Tuple[int, str]]
    unit: str
    full: str
    lang: str
    src_lang: Optional[str]
    api_key: str
    session: Any
    title: str
    words: int
    until: Optional[int] = None
    progress: Optional[Callable[[int, str], None]] = None
    outline: List[Tuple[str, int]] = field(default_factory=list)  # a PDF's bookmarks (chapter by chapter)
    chapter: Optional[int] = None  # one chapter: its number in detect_chapters
    warnings: List[str] = field(default_factory=list)

    def step(self, pct: int, text: str) -> None:
        if self.progress:
            self.progress(pct, text)

    def head(self) -> str:
        unit = "chapter (or section)" if self.unit == "chapter" else "page"
        return (f"You are an expert literary and academic editor. Book title: \"{self.title}\". In the text, [[N]] "
                f"opens {unit} N. {_lang_rule(self.lang)}\n")


async def _json_call(ctx: _Ctx, content: str, prompt: str, temperature: float = 0.2) -> Dict[str, Any]:
    """A JSON answer; one more try (not from the cache) when the first cannot be read."""
    last: Optional[Exception] = None
    for attempt in range(2):
        raw = await bi._ai(content, prompt, ctx.api_key, ctx.session, temperature=temperature,
                           bypass_cache=attempt > 0)
        try:
            return parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            last = e
            logger.warning(f"Book Insights: unreadable JSON answer (attempt {attempt + 1}): {e}")
    raise InsightsError("ai_output_rejected", f"unreadable answer: {last}", http_status=502)


async def _text_call(ctx: _Ctx, material: str, prompt: str, check: Callable[[str], List[str]],
                     temperature: float = 0.3) -> str:
    """A Markdown text, checked; written once more with the reasons when the check rejects it."""
    problems: List[str] = []
    for attempt in range(2):
        p = prompt
        if attempt and problems:
            p += "\nYOUR PREVIOUS ATTEMPT WAS REJECTED BECAUSE: " + "; ".join(problems) + ". Fix this."
        raw = await bi._ai(material, p, ctx.api_key, ctx.session, temperature=temperature if attempt == 0 else 0.15,
                           bypass_cache=attempt > 0)
        text = tidy(bi.normalize_output(raw, ctx.lang), ctx.lang, ctx.unit)
        if ctx.lang == "greek":
            text = await bi._proofread_greek(text, ctx.api_key, ctx.session)
        problems = check(text)
        if not problems:
            return text
        logger.warning(f"Book Insights text rejected: {problems}")
    raise InsightsError("ai_output_rejected", "; ".join(problems), http_status=502)


def _common_checks(text: str, ctx: _Ctx, source: str, min_words: int = 20, names: bool = True) -> List[str]:
    """`names`: capitalised words must be the book's. Off for a study guide, whose theme titles are capitalised."""
    problems = []
    if bi.count_words(text) < min_words:
        problems.append("the text is too short")
    if _leak(text):
        problems.append("prompt text leaked into the answer")
    problems += language_problems(text, ctx.lang)
    if names and ctx.src_lang == ctx.lang:
        names = bi._unknown_names(text, source)
        if len(names) > 3:
            problems.append(f"names not found in the book: {', '.join(names[:6])}")
    return problems


async def _material(ctx: _Ctx, text: str, pct: int = 10) -> Tuple[str, bool]:
    def _prog(p: int, step: str) -> None:
        ctx.step(pct + int((p - 10) * 0.7), step)
    return await bi.build_source_material(text, ctx.api_key, ctx.session, _prog)


async def _each(ctx: _Ctx, items: List[Any], ask: Callable[[Any], Any], label: str, start: int, span: int,
                skip_rejected: bool = False) -> List[Any]:
    """`await ask(item)` for every item (the sections or chapter groups of a book), a few at a time as the key pool
    allows (bi.SECTION_PARALLEL...): the answers in the items' order, so they are merged exactly as one by one.
    skip_rejected: an item whose answer is unreadable gives None instead of stopping the run. Any other error stops
    it, and the requests still running are cancelled. Progress counts the items done: label.format(done, total)."""
    from backend.async_utils import gather_or_cancel
    from backend.gemini_key_pool import parallel_requests
    sem = asyncio.Semaphore(parallel_requests(bi.SECTION_PARALLEL, bi.SECTION_PARALLEL_MAX, ctx.api_key))
    done = 0
    ctx.step(start, label.format(0, len(items)))

    async def one(item: Any) -> Any:
        nonlocal done
        async with sem:
            try:
                result = await ask(item)
            except InsightsError as e:
                if not (skip_rejected and e.code == "ai_output_rejected"):
                    raise
                result = None
        done += 1
        ctx.step(start + int(span * done / len(items)), label.format(done, len(items)))
        return result

    return await gather_or_cancel(one(item) for item in items)


# ---- characters and terms ----

_CHARACTERS_TASK = (
    "TASK: from THIS PART of the book, list the PEOPLE who appear (characters, or real persons in non-fiction) and the "
    "KEY TERMS (concepts, places, institutions, invented words) a reader needs. Use ONLY what this part says.\n"
    "Return ONLY a JSON object: {\"people\": [{\"name\": \"the name exactly as written in the text\", "
    "\"name_out\": \"the name in the output language and script\", \"role\": \"who they are, one sentence\", "
    "\"relations\": \"their relations to other people, or empty\"}], \"terms\": [{\"term\": \"exactly as written\", "
    "\"term_out\": \"in the output language\", \"definition\": \"one sentence\"}]}. At most 25 people and 25 terms; "
    "leave out passing mentions. Leave out the book's author (unless they take part in it, as in a memoir) and people "
    "who are only quoted or cited (epigraphs, sources). Ships, planets, places, objects and organisations are terms, "
    "not people. No other text."
)

# Notes and references name the sources, not the people of the book
_NOT_STORY_RE = re.compile(r"^(?:(?:end)?notes?\b.*|references?\b.*|bibliography|sources|further reading|appendix\b.*"
                           r"|σημειωσεις\b.*|βιβλιογραφια|παραπομπες\b.*|παραρτημα\b.*)$")
_CONNECTORS = {"of", "the", "de", "da", "di", "du", "la", "le", "von", "van", "der", "του", "της", "των"}


def is_attribution(line: str) -> bool:
    """An epigraph's attribution ("—Ted Bundy", "— Ian Anderson, Catfish Rising", "—1 Samuel 10:6"): a quoted
    writer, not a person of the book. A line of dialogue ("— Ναι.", "— Πού πας; ρώτησε") is none."""
    s = line.strip()
    if len(s) < 3 or len(s) > 90 or s[0] not in "—–―" or re.search(r"[.!?;…—–]$", s):
        return False
    name, _, source = s[1:].strip().partition(",")
    words, source = name.split(), source.strip()
    if not 1 <= len(words) <= 6 or len(source) > 60:
        return False
    if source and not (source[0].isupper() or source[0].isdigit() or source[0] in "*_«\"“'‘"):
        return False  # "— Ελένη, άκουσέ με": a name called in dialogue, not a work's title
    return all(w[0].isupper() or w[0].isdigit() or w.casefold() in _CONNECTORS for w in words)


def story_pages(pages: List[Tuple[int, str]], unit: str,
                outline: Optional[List[Tuple[str, int]]] = None) -> List[Tuple[int, str]]:
    """The pages of the work itself, for the people in it: those of the chapters detect_chapters finds (no title
    page, contents, acknowledgments or licence) other than notes and references, without epigraph attributions.
    The whole book when those hold less than half of its text."""
    from backend.exporter import _toc_key
    covered: set = set()
    for c in detect_chapters(pages, unit, outline):
        if not (c["title"] and _NOT_STORY_RE.match(_toc_key(c["title"]))):
            covered.update(range(c["first"], c["last"] + 1))
    kept = [(n, t) for n, t in pages if n in covered]
    if sum(len(t) for _, t in kept) < 0.5 * sum(len(t) for _, t in pages):
        kept = pages
    return [(n, "\n".join(ln for ln in t.split("\n") if not is_attribution(ln))) for n, t in kept]


def _fold_short_names(store: Dict[str, Dict[str, Any]], key: str, out_key: str, text_keys: Tuple[str, ...]) -> None:
    """A short form ("Szpindel", "Isaac", "Major") goes into the one fullest name that holds all its words ("Isaac
    Szpindel", "Major Amanda Bates"); with two such names ("John" of "John Smith" and "John Doe") it stays. The
    short forms are kept as `aka` [(name, its spelling in the output language)], for the Glossary."""
    words = {k: set(e[key].casefold().split()) for k, e in store.items()}
    for k in sorted(store, key=lambda k: len(words[k])):
        holders = [o for o in store if o != k and words[k] < words[o]]
        fullest = [o for o in holders if not any(words[o] < words[h] for h in holders)]
        if len(fullest) != 1:
            continue
        short, full = store.pop(k), store[fullest[0]]
        full.setdefault("aka", []).append((short[key], short[out_key]))
        full["aka"] += short.pop("aka", [])
        full[out_key] = full[out_key] or ""
        for t in text_keys:  # the fullest description wins
            if len(short[t]) > len(full[t]):
                full[t] = short[t]
        words.pop(k)


async def _characters(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    pages = story_pages(ctx.pages, ctx.unit, ctx.outline)
    sections = page_sections(pages)
    people: Dict[str, Dict[str, str]] = {}
    terms: Dict[str, Dict[str, str]] = {}
    answers = await _each(ctx, sections, lambda sec: _json_call(ctx, marked(sec), ctx.head() + _CHARACTERS_TASK),
                          "Πρόσωπα και όροι: ενότητα {}/{}…", 10, 70, skip_rejected=True)
    for i, found in enumerate(answers):  # merged in the book's order, as one by one
        if found is None:
            ctx.warnings.append(f"section {i + 1} could not be read")
            continue
        for kind, store, key, out_key, text_keys in (("people", people, "name", "name_out", ("role", "relations")),
                                                     ("terms", terms, "term", "term_out", ("definition",))):
            for item in found.get(kind) or []:
                if not isinstance(item, dict):
                    continue
                source = str(item.get(key) or "").strip()
                if not source:
                    continue
                entry = store.setdefault(source.casefold(), {key: source, out_key: "", **{k: "" for k in text_keys}})
                entry[out_key] = entry[out_key] or str(item.get(out_key) or "").strip()
                for k in text_keys:  # the fullest description wins
                    value = str(item.get(k) or "").strip()
                    if len(value) > len(entry[k]):
                        entry[k] = value
    for name in [k for k in people if k in terms]:  # a ship, a planet or a place named both ways: a term
        del people[name]
    for store, key, out_key, text_keys in ((people, "name", "name_out", ("role", "relations")),
                                           (terms, "term", "term_out", ("definition",))):
        _fold_short_names(store, key, out_key, text_keys)
    folded = _fold("\n\n".join(t for _, t in pages))  # named in the work itself, not only in its front or back matter
    kept_people, kept_terms = [], []
    for store, kept, key, limit in ((people, kept_people, "name", MAX_PEOPLE), (terms, kept_terms, "term", MAX_TERMS)):
        for entry in store.values():
            names = [entry[key]] + [a for a, _ in entry.get("aka", [])]
            if not any(_occurs(n, folded) for n in names):  # never a name the book does not have
                continue
            firsts = [p for p in (_first_page(n, pages) for n in names) if p is not None]
            entry["first"] = min(firsts) if firsts else None
            kept.append(entry)
        kept.sort(key=lambda e: (e["first"] is None, e["first"] or 0))
        del kept[limit:]
    if not kept_people and not kept_terms:
        raise InsightsError("ai_output_rejected", "no people or terms found in the book", http_status=502)

    def own(items: List[Dict[str, Any]]) -> str:
        return " ".join(" ".join((i.get("role", ""), i.get("relations", ""), i.get("definition", ""))) for i in items)

    def off_language(text: str) -> float:  # how far a description is from the output language
        if ctx.lang == "greek":
            return bi._latin_share_outside_quotes(text) + (1 - _greek_share(text))
        return _greek_share(text)

    entries = kept_people + kept_terms
    if language_problems(own(entries), ctx.lang):
        # Descriptions in the wrong language or with names in Latin script (a weaker model, at times) are left out,
        # worst first, until the rest pass; the names stay. A list rejected as a whole would be rejected again on
        # every new try, since the section answers are cached.
        blanked = 0
        for item in sorted(entries, key=lambda i: off_language(own([i])), reverse=True):
            if not language_problems(own(entries), ctx.lang):
                break
            for k in ("role", "relations", "definition"):
                if k in item:
                    item[k] = ""
            blanked += 1
        ctx.warnings.append(f"{blanked} description(s) in another language or script left out")
    problems = language_problems(own(entries), ctx.lang)
    if problems:
        raise InsightsError("ai_output_rejected", "; ".join(problems), http_status=502)
    w = _words(ctx.lang)

    def line(name: str, out: str, desc: str, first: Optional[int]) -> str:
        shown = f"**{out or name}**" + (f" ({name})" if out and out.casefold() != name.casefold() else "")
        where = f" · {_ref(ctx.lang, ctx.unit, first)}" if first else ""
        return f"- {shown} — {desc.rstrip('.')}.{where}" if desc else f"- {shown}{where}"

    blocks = []
    if kept_people:
        rows = [line(p["name"], p["name_out"], p["role"] + (f" {w['relations']}: {p['relations']}"
                                                            if p["relations"] else ""), p["first"])
                for p in kept_people]
        blocks.append(f"## {w['people']}\n" + "\n".join(rows))
    if kept_terms:
        rows = [line(t["term"], t["term_out"], t["definition"], t["first"]) for t in kept_terms]
        blocks.append(f"## {w['terms']}\n" + "\n".join(rows))
    return "\n\n".join(blocks), {"people": kept_people, "terms": kept_terms}


# ---- chapter by chapter ----

def pdf_outline(file_path: str, file_type: str) -> List[Tuple[str, int]]:
    """A PDF's bookmarks as [(title, page)], as deep as they go while they stay a chapter list (at most 80);
    [] for other files or a PDF without bookmarks."""
    if (file_type or "").lower().lstrip(".") != "pdf":
        return []
    try:
        import pymupdf
        with pymupdf.open(file_path) as doc:
            toc = doc.get_toc(simple=True)
    except Exception as e:
        logger.debug(f"No PDF bookmarks: {e}")
        return []
    entries = [(int(level), str(title).strip(), int(page)) for level, title, page in toc
               if str(title).strip() and int(page) > 0]
    if not entries:
        return []
    depth = min(level for level, _, _ in entries)
    while (any(level == depth + 1 for level, _, _ in entries)
           and sum(1 for level, _, _ in entries if level <= depth + 1) <= 80):
        depth += 1
    return [(title, page) for level, title, page in entries if level <= depth]


def _listed_titles(pages: List[Tuple[int, str]]) -> Tuple[Optional[int], List[Tuple[str, int]]]:
    """A contents list near the start, with or without page numbers: (its page, [(title, page it opens)]) when at
    least three of its short lines come back later as lines of their own, in order. Else (None, [])."""
    from backend.exporter import _TOC_LINE_RE, _toc_key
    keys = [{_toc_key(ln) for ln in t.split("\n") if 0 < len(ln.strip()) <= 90} for _, t in pages]
    for idx, (n, t) in enumerate(pages[:max(10, len(pages) // 20)]):
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        titles = []
        for ln in lines:
            m = _TOC_LINE_RE.match(ln)
            title = m.group("title").rstrip(" .") if m else ln
            if len(title) <= 80 and not re.fullmatch(r"\d{1,4}", title) and not re.search(r"[.!?;,…]$", title):
                titles.append(title)
        if len(titles) < 3 or len(titles) < 0.6 * len(lines):
            continue
        found: List[Tuple[str, int]] = []
        start = idx + 1
        for title in titles:
            key = _toc_key(title)
            hit = next((j for j in range(start, len(pages)) if key in keys[j]), None)
            if hit is not None:
                found.append((title, pages[hit][0]))
                start = hit
        # the titles open pages across the book, not lines that come back near each other (a poem's refrain)
        opened = sorted({p for _, p in found})
        if len(opened) >= 3 and opened[-1] - opened[0] >= (pages[-1][0] - n) / 3:
            return n, found
    return None, []


# Front and back matter: no chapter of the work. Compared accent-free in lower case.
_NOT_A_CHAPTER_RE = re.compile(
    r"^(?:cover|title page|copyright|(?:table of )?contents|dedication|acknowledg(?:e)?ments?|index|about the author"
    r"|also by\b.*|(?:creative commons )?licen[cs](?:e|ing)\b.*|εξωφυλλο|περιεχομενα|αφιερωση|ευχαριστιες"
    r"|ευρετηριο|αδεια\b.*|σχετικα με τον συγγραφεα)$"
)


def _split_long(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A chapter longer than CHAPTER_MAX_CHARS as pieces of about PIECE_CHARS, cut where a page ends (or, in an
    EPUB chapter, where a sentence ends), so its middle is summarised too."""
    units = c.get("units") or []
    if len(c["text"]) <= CHAPTER_MAX_CHARS or not units:
        return [c]
    target = len(c["text"]) / -(-len(c["text"]) // PIECE_CHARS)
    groups: List[List[Tuple[int, str]]] = [[]]
    size = 0
    for i, (page, ln) in enumerate(units):
        groups[-1].append((page, ln))
        size += len(ln) + 1
        nxt = units[i + 1][0] if i + 1 < len(units) else None
        if size >= target and nxt is not None and (nxt != page or (c["first"] == c["last"]
                                                                  and re.search(r"[.!?…\"”»]$", ln.strip()))):
            groups.append([])
            size = 0
    groups = [g for g in groups if g]
    if len(groups) < 2:
        return [c]
    return [{"title": c["title"], "first": c["first"] if k == 1 else g[0][0], "last": g[-1][0], "piece": (k, len(groups)),
             "text": "\n".join(ln for _, ln in g).strip()} for k, g in enumerate(groups, 1)]


def detect_chapters(pages: List[Tuple[int, str]], unit: str,
                    outline: Optional[List[Tuple[str, int]]] = None) -> List[Dict[str, Any]]:
    """[{n, title (None: an untitled part), first, last, text, piece?}] in order. EPUB: its chapters; else the
    PDF's bookmarks (outline), the titles of a contents list and the chapter headings; a book without them is cut
    into equal parts. Front and back matter is left out; a very long chapter comes in pieces (piece = (k, of))."""
    from backend.exporter import _is_chapter_heading, _toc_key
    chapters: List[Dict[str, Any]] = []
    if unit == "chapter":
        for n, t in pages:
            first_line = t.strip().split("\n", 1)[0].strip()
            title = first_line if len(first_line) <= 80 and not re.search(r"[.!?;…]$", first_line) else None
            lines = [(n, ln) for ln in t.split("\n")]
            if chapters and len(chapters[-1]["text"]) < 400:  # a cover or title page joins the next chapter
                chapters[-1].update(text=chapters[-1]["text"] + "\n\n" + t, last=n, title=chapters[-1]["title"] or title)
                chapters[-1]["units"] += lines
                continue
            chapters.append({"title": title, "first": n, "last": n, "text": t, "units": lines})
        # a contents, copyright or navigation page at the end is no chapter
        chapters = [c for c in chapters if len(c["text"].strip()) >= 300] or chapters
    else:
        contents_page, listed = _listed_titles(pages)
        marks: Dict[int, List[Tuple[str, str]]] = {}
        for title, page in (outline or listed):
            marks.setdefault(page, []).append((_toc_key(title), title))
        lead: List[str] = []
        lead_first: Optional[int] = None

        def start(title: str, n: int) -> None:
            chapters.append({"title": title, "first": n, "last": n, "text": "", "units": []})

        for n, t in pages:
            lines = t.split("\n")
            wanted = [k for k, _ in marks.get(n, [])]
            heads = []
            for ln in lines:
                key = _toc_key(ln) if n != contents_page and 0 < len(ln.strip()) <= 90 else ""
                if key and key in wanted:
                    wanted.remove(key)
                    heads.append(True)
                else:
                    heads.append(n != contents_page and _is_chapter_heading(ln))
            if marks.get(n) and not any(heads):  # bookmarked, but no line of the page is its title
                start(marks[n][0][1], n)
            for ln, head in zip(lines, heads):
                if head:
                    start(ln.strip(), n)
                    continue
                if chapters:
                    chapters[-1]["text"] += ln + "\n"
                    chapters[-1]["units"].append((n, ln))
                    chapters[-1]["last"] = n
                else:
                    lead.append(ln)
                    lead_first = lead_first or n
        lead_text = "\n".join(lead).strip()
        if chapters and len(lead_text) >= 1500:  # text before the first heading that is more than a title page
            chapters.insert(0, {"title": None, "first": lead_first, "last": chapters[0]["first"], "text": lead_text})
        chapters = [c for c in chapters if len(c["text"].strip()) >= 200]
    chapters = [c for c in chapters
                if not (c["title"] and _NOT_A_CHAPTER_RE.match(_toc_key(c["title"])))] or chapters
    chapters = [piece for c in chapters for piece in _split_long(c)]
    if len(chapters) < 2:
        total = sum(len(t) for _, t in pages)
        parts = max(2, min(12, round(total / 25_000)))
        per = max(1, -(-len(pages) // parts))
        chapters = [{"title": None, "first": grp[0][0], "last": grp[-1][0], "text": "\n\n".join(t for _, t in grp)}
                    for grp in (pages[i:i + per] for i in range(0, len(pages), per))]
    for i, c in enumerate(chapters, 1):
        c["n"] = i
        c.pop("units", None)
    return chapters


_CHAPTERS_TASK = (
    "TASK: summarise EACH chapter below in 2-4 sentences: what happens or what is argued in it. Chapters are opened "
    "by <<CH n>> and their title (if any); a title ending in (k/m) is part k of m of a long chapter: summarise that "
    "part. Use ONLY what each chapter says; never mention later chapters.\n"
    "Return ONLY a JSON object: {\"chapters\": [{\"n\": n, \"title\": \"the chapter's title in the output language, "
    "or a short title of your own when it has none\", \"summary\": \"...\"}]}, one entry for each <<CH n>>, in order. "
    "No other text."
)


def _chapter_text(c: Dict[str, Any]) -> str:
    text = c["text"].strip()
    if len(text) > CHAPTER_MAX_CHARS:  # its beginning and its end
        text = text[:CHAPTER_MAX_CHARS * 6 // 10] + "\n[…]\n" + text[-CHAPTER_MAX_CHARS * 4 // 10:]
    piece = f" ({c['piece'][0]}/{c['piece'][1]})" if c.get("piece") else ""
    return f"<<CH {c['n']}>> {c['title'] or ''}{piece}\n{text}"


async def _chapter_summaries(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    chapters = detect_chapters(ctx.pages, ctx.unit, ctx.outline)
    batches: List[List[Dict[str, Any]]] = []
    size = 0
    for c in chapters:
        length = min(len(c["text"]), CHAPTER_MAX_CHARS)
        if batches and size + length <= CHAPTER_BATCH_CHARS:
            batches[-1].append(c)
            size += length
        else:
            batches.append([c])
            size = length
    async def summarise(batch: List[Dict[str, Any]]) -> Dict[int, Dict[str, str]]:
        got: Dict[int, Dict[str, str]] = {}
        for attempt in range(2):  # a chapter the answer left out is asked once more
            wanted = [c for c in batch if c["n"] not in got]
            if not wanted:
                break
            data = await _json_call(ctx, "\n\n".join(_chapter_text(c) for c in wanted), ctx.head() + _CHAPTERS_TASK,
                                    temperature=0.2 if attempt == 0 else 0.1)
            for item in data.get("chapters") or []:
                try:
                    n = int(item.get("n"))
                except (TypeError, ValueError, AttributeError):
                    continue
                summary = str(item.get("summary") or "").strip()
                if summary and any(c["n"] == n for c in wanted):
                    got[n] = {"title": str(item.get("title") or "").strip(), "summary": summary}
        return got

    found: Dict[int, Dict[str, str]] = {}
    for got in await _each(ctx, batches, summarise, "Κεφάλαια: {}/{}…", 10, 75):  # merged in the book's order
        found.update(got)
    missing = [c["n"] for c in chapters if c["n"] not in found]
    if len(missing) > len(chapters) // 2:
        raise InsightsError("ai_output_rejected", f"{len(missing)} of {len(chapters)} chapters were not summarised",
                            http_status=502)
    if missing:
        ctx.warnings.append(f"{len(missing)} chapter(s) without a summary: {', '.join(map(str, missing[:10]))}")
    problems = language_problems(" ".join(v["summary"] for v in found.values()), ctx.lang)
    if problems:
        raise InsightsError("ai_output_rejected", "; ".join(problems), http_status=502)
    w = _words(ctx.lang)

    def bare(t: str) -> str:  # without the "(k/m)" the model may have copied
        return re.sub(r"\s*[(\[][^()\[\]]*[)\]]\s*$", "", t or "").strip()

    # The pieces of a long chapter share one title: the model's most frequent one in the output language
    # (asked separately, it may write "Θησέας" for one piece and "Theseus" for the next).
    piece_title: Dict[int, str] = {}
    group: List[Dict[str, Any]] = []
    for c in chapters + [{}]:
        if group and (not c.get("piece") or c["piece"][0] == 1):
            names = [bare(found.get(p["n"], {}).get("title", "")) for p in group]
            names = [t for t in names if t]
            fitting = [t for t in names if (_greek_share(t) >= 0.5) == (ctx.lang == "greek")] or names
            chosen = max(fitting, key=fitting.count) if fitting else (group[0]["title"] or w["part"])
            piece_title.update((p["n"], chosen) for p in group)
            group = []
        if c.get("piece"):
            group.append(c)
    blocks, rows = [], []
    for c in chapters:
        got = found.get(c["n"], {})
        title = got.get("title") or c["title"] or f"{w['part']} {c['n']}"
        if c.get("piece"):  # the part's number is ours
            title = f"{piece_title[c['n']]} ({c['piece'][0]}/{c['piece'][1]})"
        ref = _ref(ctx.lang, ctx.unit, c["first"], c["last"])
        blocks.append(f"## {c['n']}. {title}\n{got.get('summary', '—')} ({ref})")
        rows.append({"n": c["n"], "title": title, "first": c["first"], "last": c["last"],
                     "summary": got.get("summary", "")})
    return "\n\n".join(blocks), {"chapters": rows}


# ---- one chapter in detail ----

_CHAPTER_TASK = (
    "TASK: write a detailed account of the ONE chapter below (opened by <<CH n>> and its title, if any): what happens "
    "or what is argued in it, in order; who appears and what they do; its key moments, revelations or ideas; and how "
    "it ends. 3-5 paragraphs, about 250-450 words (less for a short chapter). Use ONLY this chapter and never mention "
    "what comes after it. Begin with one line: '## ' and the chapter's title in the output language (a short title of "
    "your own when it has none), then the text. No other headings."
)


async def _chapter(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    """One chapter of the list that "Chapter by chapter" uses (its pieces included), in detail."""
    chapters = detect_chapters(ctx.pages, ctx.unit, ctx.outline)
    c = next((c for c in chapters if c["n"] == ctx.chapter), None)
    if c is None:
        raise InsightsError("invalid_request", f"chapter {ctx.chapter} of {len(chapters)}")
    ctx.step(15, "Κεφάλαιο: ανάγνωση…")
    least = max(20, min(80, bi.count_words(c["text"]) // 4))
    text = await _text_call(ctx, _chapter_text(c), ctx.head() + _CHAPTER_TASK,
                            lambda t: _common_checks(t, ctx, c["text"], min_words=least))
    first, _, rest = text.strip().partition("\n")
    own = re.sub(r"^#+\s*", "", first).strip() if first.lstrip().startswith("#") else ""
    body = rest.strip() if own else text.strip()
    w = _words(ctx.lang)
    title = re.sub(r"\s*[(\[][^()\[\]]*[)\]]\s*$", "", own).strip() or c["title"] or f"{w['part']} {c['n']}"
    if c.get("piece"):  # the part's number is ours
        title = f"{title} ({c['piece'][0]}/{c['piece'][1]})"
    ref = _ref(ctx.lang, ctx.unit, c["first"], c["last"])
    return (f"## {c['n']}. {title}\n{body}\n\n({ref})",
            {"chapter": {"n": c["n"], "title": title, "first": c["first"], "last": c["last"]}})


# ---- the story so far ----

async def _recap(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    text = "\n\n".join(t for _, t in ctx.pages)
    material, from_notes = await _material(ctx, text)
    lo, hi = 150, 400
    if ctx.words < 900:
        hi = max(80, ctx.words // 3)
        lo = max(40, hi // 2)
    where = _ref("english", ctx.unit, ctx.until)
    prompt = (ctx.head() + ("The source is faithful notes of the book up to that point.\n" if from_notes else "")
              + f"TASK: write 'THE STORY SO FAR': a recap of about {lo}-{hi} words of everything the reader has read "
              f"up to the end of the source ({where}), so that they can pick the book up again. Say where things "
              f"stand, who is who, and what is still open. Never guess or hint at what happens after this point. "
              f"Paragraphs, no headings.\n" + bi._COMMON_RULES)
    result = await _text_call(ctx, material, prompt,
                              lambda t: _common_checks(t, ctx, text, min_words=min(lo // 2, 60)))
    return result, {"until": ctx.until, "from_notes": from_notes}


# ---- back-cover blurb ----

async def _blurb(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    material, from_notes = await _material(ctx, ctx.full)
    prompt = (ctx.head() + ("The source is faithful notes of the whole book.\n" if from_notes else "")
              + "TASK: write a BACK-COVER BLURB of 80-130 words that makes a reader want to read the book WITHOUT "
              "revealing the ending, the twists or the outcome: the premise, the main character(s) or subject, and "
              "what is at stake, then stop. No headings, no reviews or praise, no title line.\n" + bi._COMMON_RULES)

    def check(t: str) -> List[str]:
        problems = _common_checks(t, ctx, ctx.full, min_words=40)
        if bi.count_words(t) > 220:
            problems.append("the blurb is too long")
        return problems

    return await _text_call(ctx, material, prompt, check), {"from_notes": from_notes}


# ---- memorable quotes ----

_QUOTES_TASK = (
    "TASK: choose up to 5 memorable, meaningful passages from THIS PART of the book (1-3 sentences each). Copy each "
    "passage EXACTLY, character for character, in the book's own language: never translate, shorten or join it. "
    "Give the [[N]] number of the page it is on, and one sentence in the output language on why it matters.\n"
    "Return ONLY a JSON object: {\"quotes\": [{\"quote\": \"...\", \"page\": N, \"note\": \"...\"}]}. No other text."
)


def verify_quote(quote: str, cited: Optional[int], pages: List[Tuple[int, str]]) -> Optional[int]:
    """The page a quote is really on (it must be in the book word for word), or None."""
    q = _fold(quote).strip("\"' ")
    if len(q) < 20:
        return None
    order = sorted(range(len(pages)), key=lambda k: abs(pages[k][0] - (cited or 0)) if cited else k)
    folded = {k: _fold(pages[k][1]) for k in order}
    for k in order:
        if q in folded[k]:
            return pages[k][0]
        if k + 1 < len(pages) and q in folded[k] + " " + folded[k + 1]:  # across a page break
            return pages[k][0]
    return None


async def _quotes(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    sections = page_sections(ctx.pages)
    verified: List[Dict[str, Any]] = []
    rejected = 0
    answers = await _each(ctx, sections, lambda sec: _json_call(ctx, marked(sec), ctx.head() + _QUOTES_TASK),
                          "Αποσπάσματα: ενότητα {}/{}…", 10, 75, skip_rejected=True)
    for sec, data in zip(sections, answers):  # in the book's order
        if data is None:
            continue
        for item in data.get("quotes") or []:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote") or "").strip().strip("«»\"“”")
            try:
                cited = int(item.get("page"))
            except (TypeError, ValueError):
                cited = None
            page = verify_quote(quote, cited, sec) or verify_quote(quote, cited, ctx.pages)
            if page is None:
                rejected += 1
                continue
            if any(_fold(quote) == _fold(v["quote"]) for v in verified):
                continue
            verified.append({"quote": quote, "page": page, "note": str(item.get("note") or "").strip()})
    if not verified:
        raise InsightsError("ai_output_rejected", "no passage was found word for word in the book", http_status=502)
    if rejected:
        ctx.warnings.append(f"{rejected} passage(s) left out: not found word for word in the book")
    verified.sort(key=lambda q: q["page"])
    if len(verified) > MAX_QUOTES:  # spread over the whole book
        step = len(verified) / MAX_QUOTES
        verified = [verified[int(i * step)] for i in range(MAX_QUOTES)]
    problems = language_problems(" ".join(q["note"] for q in verified), ctx.lang)
    if problems:
        raise InsightsError("ai_output_rejected", "; ".join(problems), http_status=502)
    rows = [f"- **«{q['quote']}»** ({_ref(ctx.lang, ctx.unit, q['page'])})" + (f" — {q['note']}" if q["note"] else "")
            for q in verified]
    return "\n".join(rows), {"quotes": verified}


# ---- study guide ----

async def _study_guide(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    material, from_notes = await _material(ctx, ctx.full)
    prompt = (ctx.head() + ("The source is faithful notes of the whole book.\n" if from_notes else "")
              + "TASK: write a STUDY GUIDE for this book in Markdown with exactly these four sections, their titles "
              "translated into the output language: '## Themes' (4-6 themes, each with 2-3 sentences on how the book "
              "develops it), '## Discussion questions' (8-10 open questions for a reading group or a class), '## Quiz' "
              "(8 short numbered questions on the facts of the book) and '## Answers' (the quiz answers, numbered "
              "the same). Use ONLY the book.\n" + bi._COMMON_RULES)

    def check(t: str) -> List[str]:
        problems = _common_checks(t, ctx, ctx.full, min_words=120, names=False)
        if bi._heading_count(t) < 4:
            problems.append("the guide needs its four sections")
        return problems

    return await _text_call(ctx, material, prompt, check, temperature=0.4), {"from_notes": from_notes}


# ---- timeline ----

_EVENTS_TASK = (
    "TASK: list the main EVENTS of THIS PART of the book in the order they are told (at most 15): one sentence each, "
    "with the [[N]] page and the in-story time if the text states it (a date, year, age, season or 'years earlier'). "
    "Use ONLY what the text says.\nReturn ONLY a JSON object: {\"events\": [{\"page\": N, \"when\": \"as stated, or "
    "empty\", \"event\": \"...\"}]}. No other text."
)
_ORDER_TASK = (
    "TASK: below are events of a book as JSON, in the order the book tells them. Return them in the order they HAPPEN "
    "in the story (use the 'when' notes; keep the told order where unsure), merge duplicates, keep at most 40, and "
    "keep each event's page and wording. Return ONLY a JSON object: {\"events\": [{\"page\": N, \"when\": \"...\", "
    "\"event\": \"...\"}]}. No other text."
)


def _events(data: Dict[str, Any], page_numbers: set) -> List[Dict[str, Any]]:
    out = []
    for item in data.get("events") or []:
        if not isinstance(item, dict) or not str(item.get("event") or "").strip():
            continue
        try:
            page = int(item.get("page"))
        except (TypeError, ValueError):
            page = None
        out.append({"page": page if page in page_numbers else None, "when": str(item.get("when") or "").strip(),
                    "event": str(item["event"]).strip()})
    return out


async def _timeline(ctx: _Ctx) -> Tuple[str, Dict[str, Any]]:
    numbers = {n for n, _ in ctx.pages}
    sections = page_sections(ctx.pages)
    told: List[Dict[str, Any]] = []
    for data in await _each(ctx, sections, lambda sec: _json_call(ctx, marked(sec), ctx.head() + _EVENTS_TASK),
                            "Γεγονότα: ενότητα {}/{}…", 10, 65):  # in the order the book tells them
        told += _events(data, numbers)
    if not told:
        raise InsightsError("ai_output_rejected", "no events found", http_status=502)
    ctx.step(85, "Χρονολογική σειρά…")
    ordered = _events(await _json_call(ctx, json.dumps({"events": told}, ensure_ascii=False),
                                       ctx.head() + _ORDER_TASK, temperature=0.1), numbers)
    if len(ordered) < max(1, min(len(told), MAX_EVENTS) // 2):  # an ordering that lost events: the told order
        ctx.warnings.append("the events are in the order the book tells them")
        ordered = told
    ordered = ordered[:MAX_EVENTS]
    own = " ".join(e["event"] + " " + e["when"] for e in ordered)
    problems = language_problems(own, ctx.lang)
    if ctx.src_lang == ctx.lang:
        names = bi._unknown_names(own, ctx.full)
        if len(names) > 3:
            problems.append(f"names not found in the book: {', '.join(names[:6])}")
    if problems:
        raise InsightsError("ai_output_rejected", "; ".join(problems), http_status=502)
    rows = []
    for e in ordered:
        when = f"**{e['when']}** — " if e["when"] else ""
        ref = f" ({_ref(ctx.lang, ctx.unit, e['page'])})" if e["page"] else ""
        rows.append(f"- {when}{e['event'].rstrip()}{ref}")
    return "\n".join(rows), {"events": ordered}


_GENERATORS = {
    "characters": _characters, "chapter_summaries": _chapter_summaries, "chapter": _chapter, "recap": _recap,
    "blurb": _blurb, "quotes": _quotes, "study_guide": _study_guide, "timeline": _timeline,
}


def resolve_language(language: Optional[str], src_lang: Optional[str]) -> str:
    out = (language or "").strip().lower() or "auto"
    if out == "auto":
        if src_lang is None:
            raise InsightsError("language_detection_failed", http_status=422)
        return src_lang if src_lang in OUTPUT_LANGUAGES else "other"
    if out not in OUTPUT_LANGUAGES:
        raise InsightsError("invalid_request", f"language {out}")
    return out


async def generate_extra(
    file_path: str,
    file_type: str,
    insight_type: str,
    language: Optional[str],
    api_key: str,
    title: str = "Document",
    job_output_dir: Optional[Path] = None,
    progress: Optional[Callable[[int, str], None]] = None,
    until: Optional[int] = None,
    session=None,
    chapter: Optional[int] = None,
) -> Dict[str, Any]:
    """Makes, checks and stores one of the EXTRA_TYPES. Raises InsightsError. `until`: the recap's last page;
    `chapter`: the number of the one chapter (as listed by detect_chapters)."""
    if insight_type == "chapter" and (chapter is None or chapter < 1):
        raise InsightsError("invalid_request", "choose a chapter")
    if insight_type not in EXTRA_TYPES:
        raise InsightsError("invalid_request", f"unknown type {insight_type}")
    pages, unit = extract_pages(file_path, file_type)
    if insight_type == "recap":
        if not pages or until is None or until < pages[0][0]:
            raise InsightsError("invalid_request", f"recap needs a page from {pages[0][0] if pages else 1}")
        pages = [p for p in pages if p[0] <= until]
    full = "\n\n".join(t for _, t in pages)
    info = bi.analyze_text(full)
    if not info["can_summary"]:
        raise InsightsError("insufficient_text", f"{info['meaningful_words']} words", http_status=422)
    src_lang = info["detected_language"]
    out_lang = resolve_language(language, src_lang)
    if not (api_key or "").strip():
        raise InsightsError("no_api_key", http_status=401)

    source_hash = bi._text_hash(f"{insight_type}|{until}|{full}" + (f"|{chapter}" if insight_type == "chapter" else ""))
    if job_output_dir is not None:
        existing = bi.load_insight(job_output_dir, insight_type, out_lang)
        if (existing and existing.get("source_hash") == source_hash and existing.get("text")
                and existing.get("version") == record_version(insight_type)):
            if progress:
                progress(100, "Έτοιμο (αποθηκευμένο αποτέλεσμα)")
            existing["reused"] = True
            return existing

    owns_session = session is None
    if owns_session:
        import aiohttp
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240))
    ctx = _Ctx(pages=pages, unit=unit, full=full, lang=out_lang, src_lang=src_lang, api_key=api_key, session=session,
               title=title, words=info["meaningful_words"], until=until, progress=progress,
               outline=pdf_outline(file_path, file_type)
               if insight_type in ("characters", "chapter_summaries", "chapter") else [],
               chapter=chapter)
    try:
        ctx.step(5, "Προετοιμασία κειμένου…")
        text, data = await _GENERATORS[insight_type](ctx)
        text = tidy(text, out_lang, unit)
    finally:
        if owns_session:
            await session.close()

    record = {
        "version": record_version(insight_type),
        "insight_type": insight_type,
        "kind": EXTRA_TYPES[insight_type]["kind"],
        "language": out_lang,
        "source_language": src_lang,
        "title": title,
        "label": _label(insight_type, out_lang) + (f" ({_ref(out_lang, unit, until)})" if until else "")
                 + (f" {data['chapter']['n']}: {data['chapter']['title']}" if data.get("chapter") else ""),
        "text": text,
        "data": data,
        "unit": unit,
        "until": until,
        "chapter": chapter,
        "word_count": bi._plain_words(text),
        "warnings": ctx.warnings,
        "source_words": info["meaningful_words"],
        "source_hash": source_hash,
        "text_hash": bi._text_hash(text),
        "created_at": time.time(),
        "audio_file": None,
    }
    if job_output_dir is not None:
        bi.save_insight(job_output_dir, record)
    if progress:
        progress(100, "Έτοιμο")
    return record


# ---------------------------------------------------------------------------
# Questions to the book
# ---------------------------------------------------------------------------

_STOP = {"the", "and", "what", "who", "why", "how", "when", "where", "does", "did", "was", "were", "with", "that",
         "this", "from", "about", "into", "which", "their", "there", "have", "has", "for", "are", "την", "τον", "της",
         "του", "των", "τους", "και", "που", "πως", "πώς", "γιατί", "ποιος", "ποια", "ποιο", "ποιοι", "είναι", "ήταν",
         "στην", "στον", "στο", "στα", "από", "για", "με", "μια", "ένα", "ένας", "κάνει", "έκανε", "λέει"}


def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


def _spread(pages: List[Tuple[int, str]], budget: int) -> List[Tuple[int, str]]:
    """Pages evenly spread over the whole book, within the budget (never only its first or last pages)."""
    share = budget / max(1, sum(len(t) for _, t in pages))
    chosen, acc, size = [], 0.5, 0  # centred: the first pick half a step in
    for n, t in pages:
        acc += share
        if acc >= 1 and size + len(t) <= budget:
            chosen.append((n, t))
            size += len(t)
            acc -= 1
    return chosen or pages[:1]


def relevant_pages(question: str, pages: List[Tuple[int, str]], budget: int = ASK_FULL_CHARS,
                   terms: Optional[List[str]] = None) -> List[Tuple[int, str]]:
    """The whole book when it fits; else the pages that share the most words with the question and with `terms`
    (search words in the book's own language, see search_terms), with their neighbours, in book order, within the
    budget. When no page shares a word, pages spread over the whole book."""
    if sum(len(t) for _, t in pages) <= budget:
        return pages
    words_asked = re.findall(r"\w{3,}", question) + [w for t in terms or [] for w in re.findall(r"\w{3,}", str(t))]
    keys = {_strip_accents(w.casefold())[:6] for w in words_asked if w.casefold() not in _STOP}
    if not keys:
        return _spread(pages, budget)
    scored = []
    for k, (n, t) in enumerate(pages):
        words = [_strip_accents(w.casefold())[:6] for w in re.findall(r"\w{3,}", t)]
        hits = sum(1 for w in words if w in keys)
        scored.append((hits / (1 + len(words) ** 0.5), k))
    if max(score for score, _ in scored) <= 0:  # e.g. a Greek question about an English book, without search words
        return _spread(pages, budget)
    chosen: set = set()
    size = 0
    for score, k in sorted(scored, reverse=True):
        if score <= 0 and chosen:
            break
        for j in (k - 1, k, k + 1):  # a passage often runs on from the page before or after
            if 0 <= j < len(pages) and j not in chosen and size + len(pages[j][1]) <= budget:
                chosen.add(j)
                size += len(pages[j][1])
        if size >= budget * 0.95:
            break
    return [pages[j] for j in sorted(chosen)]


_SEARCH_TASK = (
    "TASK: a reader asks the QUESTION below about a book written in {book}. List the words to look for in the "
    "book's text to find the passages that answer it: the question's names, nouns and verbs in {book} (translated "
    "when the question is in another language), with likely synonyms and other forms. Return ONLY a JSON object: "
    "{{\"terms\": [\"...\"]}}, at most 25 single words or names. No other text."
)


async def search_terms(question: str, book_language: str, api_key: str, session) -> List[str]:
    """Words to look for in a long book, in its own language: a Greek question about an English book shares no word
    with it. One small request to a light model; [] when it fails (then the question's own words are used)."""
    from backend.ai_polisher import _call_gemini_api
    from backend.scan_reader import LIGHT_MODELS_FIRST
    book = {"english": "English", "greek": "Greek"}.get(book_language or "", (book_language or "its language").title())
    try:
        raw = await _call_gemini_api(f"QUESTION: {question}", api_key, _SEARCH_TASK.format(book=book), session=session,
                                     temperature=0.0, prefer_models=LIGHT_MODELS_FIRST,
                                     cache_gate=lambda o: bool(o and o.strip()))
        terms = parse_json(raw).get("terms") or []
    except Exception as e:
        logger.info(f"Ask the book: no search words, the question's own are used ({e})")
        return []
    return [str(t).strip() for t in terms if isinstance(t, (str, int)) and str(t).strip()][:25]


def _qa_path(job_output_dir: Path) -> Path:
    return bi.insights_dir(job_output_dir) / "qa.json"


def list_questions(job_output_dir: Path) -> List[Dict[str, Any]]:
    path = Path(job_output_dir) / "insights" / "qa.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def delete_questions(job_output_dir: Path, question: Optional[str] = None) -> int:
    """Removes the question with this text, or every question when none is given; returns how many were removed.
    No await between the read and the write, so a question being answered at the same time is never lost."""
    history = list_questions(job_output_dir)
    keep = [] if question is None else [r for r in history if r.get("question") != question]
    removed = len(history) - len(keep)
    if removed:
        if keep:
            bi._write_json_atomic(_qa_path(job_output_dir), keep)
        else:
            _qa_path(job_output_dir).unlink(missing_ok=True)
    return removed


def _question_language(question: str, language: Optional[str]) -> str:
    if (language or "").lower() in OUTPUT_LANGUAGES:
        return language.lower()
    return "greek" if _greek_share(question) >= 0.5 else "english"


async def ask_book(
    file_path: str,
    file_type: str,
    question: str,
    language: Optional[str],
    api_key: str,
    title: str = "Document",
    job_output_dir: Optional[Path] = None,
    progress: Optional[Callable[[int, str], None]] = None,
    session=None,
) -> Dict[str, Any]:
    """An answer from the book, citing its pages; kept with the job's earlier questions (newest first)."""
    question = re.sub(r"\s+", " ", question or "").strip()
    if not (3 <= len(question) <= 500):
        raise InsightsError("invalid_request", "a question of 3-500 characters")
    if not (api_key or "").strip():
        raise InsightsError("no_api_key", http_status=401)
    pages, unit = extract_pages(file_path, file_type)
    info = bi.analyze_text("\n\n".join(t for _, t in pages))
    if not info["can_summary"]:
        raise InsightsError("insufficient_text", f"{info['meaningful_words']} words", http_status=422)
    lang = _question_language(question, language)
    whole = sum(len(t) for _, t in pages) <= ASK_FULL_CHARS
    # A long book goes by its parts related to the question, with its chapter overview when one was made
    overview = ""
    if not whole and job_output_dir is not None:
        for lg in dict.fromkeys((lang, "greek", "english")):
            rec = bi.load_insight(job_output_dir, "chapter_summaries", lg)
            if rec and rec.get("text"):
                overview = rec["text"][:ASK_FULL_CHARS // 10]
                break
    w = _words(lang)
    cite = f"({w[unit]} N)"
    prompt = (f"You answer a reader's question about the book \"{title}\" using ONLY the book text below. In the "
              f"text, [[N]] opens {'chapter (or section)' if unit == 'chapter' else 'page'} N"
              + ("" if whole else "; only the parts most related to the question are given")
              + (". An overview of every chapter, written earlier from the whole book with its pages, comes first "
                 "between <OVERVIEW> tags: use it to place the passages, and the book text for the details"
                 if overview else "")
              + f". {_lang_rule(lang)}\nAnswer clearly in 1-3 short paragraphs and cite the pages you rely on as "
              f"{cite}. If the book does not answer the question, say so plainly in one sentence and do not guess. "
              f"Never use knowledge from outside the book. No headings.\n\nQUESTION: {question}")
    owns_session = session is None
    if owns_session:
        import aiohttp
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240))
    try:
        if whole:
            chosen = pages
        else:
            if progress:
                progress(10, "Αναζήτηση των σχετικών σελίδων…")
            terms = await search_terms(question, info.get("detected_language") or "", api_key, session)
            chosen = relevant_pages(question, pages, ASK_FULL_CHARS - len(overview), terms)
        content = (f"<OVERVIEW>\n{overview}\n</OVERVIEW>\n\n" if overview else "") + marked(chosen)
        if progress:
            progress(20, "Αναζήτηση της απάντησης στο βιβλίο…")
        raw = await bi._ai(content, prompt, api_key, session, temperature=0.2)
        answer = tidy(bi.normalize_output(raw, lang), lang, unit)
        problems = language_problems(answer, lang) + (["prompt text leaked"] if _leak(answer) else [])
        if problems:
            raw = await bi._ai(content, prompt + "\nYOUR PREVIOUS ANSWER WAS REJECTED BECAUSE: "
                               + "; ".join(problems) + ".", api_key, session, temperature=0.1, bypass_cache=True)
            answer = tidy(bi.normalize_output(raw, lang), lang, unit)
            if language_problems(answer, lang) or _leak(answer):
                raise InsightsError("ai_output_rejected", "; ".join(problems), http_status=502)
    finally:
        if owns_session:
            await session.close()
    numbers = {n for n, _ in pages}
    # every page of a citation: "(σ. 179, 209, 223)", "(p. 11–36)", "(σ. 4 και 9)"
    groups = re.findall(rf"{re.escape(w[unit])}\s*(\d+(?:\s*(?:,|–|-|και|and)\s*\d+)*)", answer)
    cited = sorted({int(n) for g in groups for n in re.findall(r"\d+", g) if int(n) in numbers})
    record = {"question": question, "answer": answer, "language": lang, "unit": unit, "pages": cited,
              "whole_book": whole, "created_at": time.time()}
    if job_output_dir is not None:
        history = [r for r in list_questions(job_output_dir) if r.get("question") != question]
        bi._write_json_atomic(_qa_path(job_output_dir), [record, *history][:QA_KEEP])
    if progress:
        progress(100, "Έτοιμο")
    return record


def glossary_items(record: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(source, Greek) pairs of a characters record for the Glossary: names and terms whose Greek form differs."""
    data = record.get("data") or {}
    pairs = []
    for key, out_key, items in (("name", "name_out", data.get("people") or []),
                                ("term", "term_out", data.get("terms") or [])):
        for item in items:
            forms = [(item.get(key), item.get(out_key))] + [tuple(a) for a in item.get("aka") or [] if len(a) == 2]
            for src, dst in forms:  # the name, and its short forms ("Szpindel" of "Isaac Szpindel")
                src, dst = str(src or "").strip(), str(dst or "").strip()
                if (src and dst and src.casefold() != dst.casefold() and _greek_share(dst) >= 0.6
                        and (src, dst) not in pairs):
                    pairs.append((src, dst))
    return pairs
