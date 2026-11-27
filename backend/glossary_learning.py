"""
glossary_learning.py - The Glossary learns from the user's translations: suggestions to accept or dismiss.

After each translation, the names it used (backend/book_names.py) are offered for the Glossary, so the next books
write them the same way; a name the user wrote another way in the editor (✏️ Review & Edit) is offered with the new
spelling. Nothing goes into the Glossary unless the user accepts it, because the Glossary serves every book (and, with
user accounts, every user).

data/glossary_suggestions.json, by user id ("" with accounts off):
  {owner: {"items": {source casefolded: {"source", "target", "origin", "books": {job_id: title}, "seen",
                                         "ordinary_word"}},
           "dismissed": {source casefolded: target}}}

A suggestion is marked when the Glossary already writes the name another way (`glossary`), or when the name is also
an ordinary English word of the book ("Will", "Hope", "Mark"): a Glossary rule would then apply to the word too.
Such suggestions are left out of "accept all".
"""

import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE = Path(__file__).resolve().parent.parent / "data" / "glossary_suggestions.json"
_lock = threading.RLock()
MAX_ITEMS = 500
MAX_DISMISSED = 2000


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        from backend.series import keep_unreadable
        logger.warning(f"glossary_suggestions.json unreadable, starting empty (a copy is kept as .corrupt): {e}")
        keep_unreadable(STORE)
        return {}


def _save(data: Dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_name(f".{STORE.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STORE)
    finally:
        tmp.unlink(missing_ok=True)


def _mine(data: Dict[str, Any], owner: str) -> Dict[str, Any]:
    mine = data.get(owner or "")
    if not isinstance(mine, dict):
        mine = {}
        data[owner or ""] = mine
    for key in ("items", "dismissed"):
        if not isinstance(mine.get(key), dict):
            mine[key] = {}
    mine["items"] = {k: v for k, v in mine["items"].items() if isinstance(v, dict)}
    for item in mine["items"].values():
        if not isinstance(item.get("books"), dict):
            item["books"] = {}
    mine["dismissed"] = {k: v for k, v in mine["dismissed"].items() if isinstance(v, str)}
    return mine


def _glossary_lookup() -> Dict[str, Tuple[str, str]]:
    """{source casefolded: (source, target)} of the user's Glossary, every category: without the names a running
    translation borrows from its series (learning runs at the end of that translation)."""
    from backend import glossary
    token = glossary.use_job_terms({})
    try:
        return {k.casefold(): (k, v) for k, v in glossary.load_glossary(category="all").items()}
    finally:
        glossary.reset_job_terms(token)


def ordinary_words(english_text: str) -> set:
    """The words the English text also writes in small letters ("will", "hope"): names that are words too."""
    return {w for w in re.findall(r"(?<![\w'’-])([a-z][a-z'’-]*)(?![\w'’-])", english_text or "")}


def add(owner: str, pairs: Iterable[Tuple[str, str, str]], job_id: str, title: str, english_text: str = "") -> int:
    """Offers (English, Greek, origin) pairs from one book; returns how many are new or changed. Pairs the
    Glossary already has, or that the user dismissed with this spelling, are not offered again."""
    glossary = _glossary_lookup()
    words = ordinary_words(english_text)
    changed = 0
    with _lock:
        data = _load()
        mine = _mine(data, owner)
        items, dismissed = mine["items"], mine["dismissed"]
        for source, target, origin in pairs:
            source, target = " ".join(source.split()), " ".join(target.split())
            if not source or not target or len(source) > 120 or len(target) > 200:
                continue
            key = source.casefold()
            known = glossary.get(key)
            if known and known[1].casefold() == target.casefold():
                items.pop(key, None)
                continue
            if dismissed.get(key, "").casefold() == target.casefold() and origin != "edit":
                continue
            old = items.get(key)
            if old and old.get("origin") == "edit" and origin != "edit" and old.get("target") != target:
                continue  # the user's own correction is not replaced by a translation's spelling
            entry = old if old and old.get("target") == target else {"books": {}}
            entry.update({"source": source, "target": target, "seen": time.time(),
                          "origin": "edit" if origin == "edit" or entry.get("origin") == "edit" else origin,
                          "ordinary_word": " " not in source and source.lower() in words})
            entry["books"] = {**(entry.get("books") or {}), job_id: title}
            if entry is not old:
                changed += 1
            items[key] = entry
        if len(items) > MAX_ITEMS:  # the oldest go
            for key in sorted(items, key=lambda k: items[k].get("seen") or 0)[: len(items) - MAX_ITEMS]:
                del items[key]
        _save(data)
    return changed


def listing(owner: str, alive: Optional[Callable[[str], bool]] = None) -> List[Dict[str, Any]]:
    """The suggestions, the user's corrections first, then those of more books, newest first; each says whether
    the Glossary writes it another way and whether it is also an ordinary word. `alive(job_id)`: whether a book still
    exists; one only from books that are gone is left out."""
    glossary = _glossary_lookup()
    with _lock:
        data = _load()
        mine = _mine(data, owner)
        items = mine["items"]
        out, stale = [], []
        for key, item in items.items():
            known = glossary.get(key)
            if known and known[1].casefold() == str(item.get("target", "")).casefold():
                stale.append(key)
                continue
            books = item.get("books") or {}
            if alive is not None and books and not any(alive(j) for j in books):
                continue
            out.append({"source": item.get("source", ""), "target": item.get("target", ""),
                        "origin": item.get("origin") or "translation",
                        "books": [{"job_id": j, "title": t} for j, t in (item.get("books") or {}).items()],
                        "glossary": known[1] if known else "",
                        "ordinary_word": bool(item.get("ordinary_word")), "seen": item.get("seen") or 0})
        if stale:
            for key in stale:
                del items[key]
            _save(data)
    out.sort(key=lambda s: (s["origin"] != "edit", -len(s["books"]), -s["seen"]))
    return out


def safe_to_accept(item: Dict[str, Any]) -> bool:
    """For "accept all": neither another spelling in the Glossary nor an ordinary word."""
    return not item.get("glossary") and not item.get("ordinary_word")


def accept(owner: str, sources: Optional[List[str]],
           alive: Optional[Callable[[str], bool]] = None) -> List[Tuple[str, str]]:
    """Puts the chosen suggestions (all safe ones when `sources` is None) in the Glossary; returns them. Only those
    `listing` shows: "accept all" never takes one the user cannot see."""
    from backend.glossary import set_term
    chosen = listing(owner, alive)
    if sources is None:
        chosen = [s for s in chosen if safe_to_accept(s)]
    else:
        wanted = {s.casefold() for s in sources if isinstance(s, str)}
        chosen = [s for s in chosen if s["source"].casefold() in wanted]
    for s in chosen:
        set_term(s["source"], s["target"], "general")
    with _lock:
        data = _load()
        items = _mine(data, owner)["items"]
        for s in chosen:
            items.pop(s["source"].casefold(), None)
        _save(data)
    return [(s["source"], s["target"]) for s in chosen]


def dismiss(owner: str, sources: List[str]) -> int:
    """These suggestions go, and are not offered again with the same spelling."""
    with _lock:
        data = _load()
        mine = _mine(data, owner)
        gone = 0
        for source in sources or []:
            key = str(source).casefold()
            item = mine["items"].pop(key, None)
            if item:
                mine["dismissed"][key] = item.get("target", "")
                gone += 1
        if len(mine["dismissed"]) > MAX_DISMISSED:
            for key in list(mine["dismissed"])[: len(mine["dismissed"]) - MAX_DISMISSED]:
                del mine["dismissed"][key]
        _save(data)
    return gone


def forget_book(job_id: str) -> None:
    forget_books({job_id})


def forget_books(job_ids) -> None:
    """Deleted books are no longer named as a suggestion's source; a suggestion of no other book goes (a correction
    the user made stays: it is theirs)."""
    gone = set(job_ids)
    with _lock:
        data = _load()
        changed = False
        for mine in data.values():
            items = mine.get("items") if isinstance(mine, dict) else None
            if not isinstance(items, dict):
                continue
            for key in list(items):
                books = items[key].get("books") or {}
                if gone & set(books):
                    for jid in gone & set(books):
                        books.pop(jid)
                    changed = True
                    if not books and items[key].get("origin") != "edit":
                        del items[key]
        if changed:
            _save(data)


# ---------------------------------------------------------------------------
# After a translation, after an edit
# ---------------------------------------------------------------------------

def _english_text(source_lang: str, original: str, translated: str) -> str:
    return translated if (source_lang or "").lower() in ("greek", "el") else original


def learn_from_translation(owner: str, job_id: str, title: str, out_dir: Path, translated: str,
                           source_lang: str, target_lang: str) -> int:
    """The names a finished translation used become suggestions (and the book's own names list)."""
    from backend import book_names
    data = book_names.refresh(out_dir, translated, source_lang, target_lang)
    tl = data.get("target_lang") or target_lang
    pairs = [(*book_names.english_greek(n["source"], n["target"], tl), n.get("origin") or "translation")
             for n in data["names"]]
    original = book_names.original_text(out_dir)
    return add(owner, pairs, job_id, title, _english_text(source_lang, original, translated))


def learn_from_comic(owner: str, job_id: str, title: str, out_dir: Path, target_lang: str) -> int:
    """A graphic novel's names, for the Glossary as prose writes them: "FRODO" as "Frodo". A name lettered only in
    capitals has lost its accents ("ΦΡΟΝΤΟ"), so it is not offered (the series still keeps it)."""
    from backend import book_names
    data = book_names.load(out_dir)
    pairs = []
    for n in data["names"]:
        en, gr = book_names.english_greek(n["source"], n["target"], data.get("target_lang") or target_lang)
        if gr == gr.upper():
            continue
        pairs.append((en.title() if en == en.upper() else en, gr, n.get("origin") or "comic"))
    return add(owner, pairs, job_id, title)


def learn_from_edit(owner: str, job_id: str, title: str, out_dir: Path, old_text: str, new_text: str,
                    source_lang: str, target_lang: str) -> List[Tuple[str, str, str]]:
    """Names the user wrote another way everywhere in the editor: kept with the book, offered for the Glossary."""
    from backend import book_names
    changes = book_names.learn_from_edit(out_dir, old_text, new_text, source_lang, target_lang)
    if changes:
        pairs = [(*book_names.english_greek(src, new, target_lang), "edit") for src, _old, new in changes]
        original = book_names.original_text(out_dir)
        add(owner, pairs, job_id, title, _english_text(source_lang, original, new_text))
    return changes
