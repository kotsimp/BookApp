"""
series.py - Books of a series: the names of the earlier books go on into the next one.

data/series.json: {owner: {series_id: {"name": "...", "books": [job_id, ...], "created": time}}} ("" is the owner when
user accounts are off). A book is in one series at most; its place in the list is its place in the series.

While a book of a series is translated, the names its earlier books were translated with (backend/book_names.py,
the user's corrections included, then the Greek names of their 👥 Characters & terms) are added to the Glossary for
that run (backend.glossary.use_job_terms): the AI is told to write them the same way, and its own register of names
is brought in line (backend.glossary.align_dossier). The user's Glossary still wins.
"""

import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE = Path(__file__).resolve().parent.parent / "data" / "series.json"
_lock = threading.RLock()

MAX_SERIES = 200
MAX_BOOKS = 300
MAX_TERMS = 400
NAME_MAX = 80
_ID_RE = re.compile(r"[0-9a-f]{12}")


class SeriesError(ValueError):
    """A request about series that cannot be done: `status` is its HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return {o: m for o, m in data.items() if isinstance(m, dict)} if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"series.json unreadable, starting empty (a copy is kept as series.json.corrupt): {e}")
        keep_unreadable(STORE)
        return {}


def keep_unreadable(store: Path) -> None:
    """The next save replaces an unreadable store: its content is kept next to it first (as the Glossary does)."""
    try:
        store.with_name(store.name + ".corrupt").write_bytes(store.read_bytes())
    except OSError as e:
        logger.warning(f"Could not keep a copy of {store.name}: {e}")


def _save(data: Dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_name(f".{STORE.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STORE)
    finally:
        tmp.unlink(missing_ok=True)


def _owned(data: Dict[str, Any], owner: str) -> Dict[str, Any]:
    mine = data.get(owner or "")
    if not isinstance(mine, dict):
        mine = {}
        data[owner or ""] = mine
    return mine


def clean_name(name: Any) -> str:
    text = " ".join(str(name or "").split())
    if not text or len(text) > NAME_MAX:
        raise SeriesError(f"Γράψτε ένα όνομα σειράς (έως {NAME_MAX} χαρακτήρες).")
    return text


def valid_id(series_id: Any) -> bool:
    return isinstance(series_id, str) and bool(_ID_RE.fullmatch(series_id))


def list_series(owner: str, alive: Optional[Callable[[str], bool]] = None) -> List[Dict[str, Any]]:
    """The owner's series, by name, each with its books in order (deleted books left out)."""
    with _lock:
        mine = dict(_load().get(owner or "") or {})
    out = []
    for sid, entry in mine.items():
        if not valid_id(sid) or not isinstance(entry, dict):
            continue
        books = [b for b in entry.get("books") or [] if isinstance(b, str) and (alive is None or alive(b))]
        out.append({"id": sid, "name": str(entry.get("name") or ""), "books": books,
                    "created": entry.get("created") or 0})
    return sorted(out, key=lambda s: s["name"].casefold())


def create(owner: str, name: Any) -> Dict[str, Any]:
    name = clean_name(name)
    with _lock:
        data = _load()
        mine = _owned(data, owner)
        same = next((sid for sid, e in mine.items() if isinstance(e, dict)
                     and str(e.get("name") or "").casefold() == name.casefold()), None)
        if same:
            return {"id": same, "name": mine[same]["name"], "books": list(mine[same].get("books") or [])}
        if len(mine) >= MAX_SERIES:
            raise SeriesError("Έχετε ήδη πολλές σειρές: διαγράψτε κάποια πρώτα.", 409)
        sid = secrets.token_hex(6)
        mine[sid] = {"name": name, "books": [], "created": time.time()}
        _save(data)
    return {"id": sid, "name": name, "books": []}


def _entry(mine: Dict[str, Any], series_id: str) -> Dict[str, Any]:
    entry = mine.get(series_id) if valid_id(series_id) else None
    if not isinstance(entry, dict):
        raise SeriesError("Η σειρά δεν βρέθηκε.", 404)
    entry["books"] = [b for b in entry.get("books") or [] if isinstance(b, str)]
    return entry


def rename(owner: str, series_id: str, name: Any) -> Dict[str, Any]:
    name = clean_name(name)
    with _lock:
        data = _load()
        entry = _entry(_owned(data, owner), series_id)
        entry["name"] = name
        _save(data)
        return {"id": series_id, "name": name, "books": list(entry["books"])}


def set_order(owner: str, series_id: str, books: List[str]) -> Dict[str, Any]:
    """The books in a new order (or fewer of them): only books already in the series."""
    with _lock:
        data = _load()
        entry = _entry(_owned(data, owner), series_id)
        present = set(entry["books"])
        order = []
        for b in books or []:
            if isinstance(b, str) and b in present and b not in order:
                order.append(b)
        entry["books"] = order
        _save(data)
        return {"id": series_id, "name": entry["name"], "books": order}


def delete(owner: str, series_id: str) -> None:
    """The series goes; its books stay."""
    with _lock:
        data = _load()
        mine = _owned(data, owner)
        _entry(mine, series_id)
        del mine[series_id]
        _save(data)


def place(owner: str, job_id: str, series_id: Optional[str], position: Optional[int] = None) -> Optional[Dict]:
    """Puts a book in a series at `position` (1 = the first book; the end when omitted), or in none (None).
    A book is in one series only: it leaves any other of the owner's series."""
    with _lock:
        data = _load()
        mine = _owned(data, owner)
        target = _entry(mine, series_id) if series_id else None
        for entry in mine.values():
            if isinstance(entry, dict) and job_id in (entry.get("books") or []):
                entry["books"] = [b for b in entry["books"] if b != job_id]
        result = None
        if target is not None:
            if len(target["books"]) >= MAX_BOOKS:
                raise SeriesError("Η σειρά έχει ήδη πάρα πολλά βιβλία.", 409)
            at = len(target["books"]) if not position else max(0, min(int(position) - 1, len(target["books"])))
            target["books"].insert(at, job_id)
            result = {"id": series_id, "name": target["name"], "books": list(target["books"])}
        _save(data)
        return result


def forget_book(job_id: str) -> None:
    forget_books({job_id})


def forget_books(job_ids) -> None:
    """Deleted books leave every series (the series stay)."""
    gone = set(job_ids)
    with _lock:
        data = _load()
        changed = False
        for mine in data.values():
            if not isinstance(mine, dict):
                continue
            for entry in mine.values():
                if isinstance(entry, dict) and gone & set(entry.get("books") or []):
                    entry["books"] = [b for b in entry["books"] if b not in gone]
                    changed = True
        if changed:
            _save(data)


def find(job_id: str, owner: Optional[str] = None) -> Optional[Tuple[str, str, Dict[str, Any], int]]:
    """(owner, series id, series, the book's index in it) of the series holding the book; that owner's first."""
    with _lock:
        data = _load()
    first = [owner or ""] if owner is not None else []
    owners = first + [o for o in data if o not in first]
    for o in owners:
        mine = data.get(o)
        if not isinstance(mine, dict):
            continue
        for sid, entry in mine.items():
            books = entry.get("books") if isinstance(entry, dict) else None
            if valid_id(sid) and isinstance(books, list) and job_id in books:
                return o, sid, entry, books.index(job_id)
    return None


def earlier_books(job_id: str, owner: Optional[str] = None) -> List[str]:
    found = find(job_id, owner)
    return list(found[2]["books"][: found[3]]) if found else []


def series_terms(job_id: str, outputs: Path, owner: Optional[str] = None) -> Dict[str, str]:
    """The names of the book's earlier books in its series, English -> Greek (the Glossary's way round). The book
    nearest before this one wins; names the translations used (with the user's corrections) win over the Greek
    names of a 👥 Characters & terms list."""
    from backend.book_insights import load_insight
    from backend.book_names import english_greek, load, name_like, rendered_as_name
    from backend.insights_more import glossary_items
    characters: Dict[str, str] = {}
    translated: Dict[str, str] = {}
    for jid in earlier_books(job_id, owner):
        out_dir = Path(outputs) / jid
        if not out_dir.is_dir():
            continue
        try:
            rec = load_insight(out_dir, "characters", "greek")
            for src, dst in glossary_items(rec) if rec else []:
                if name_like(src) and rendered_as_name(dst):  # its names, not its common terms ("logbook")
                    characters[src] = dst
            names = load(out_dir)
            for n in names["names"]:
                en, gr = english_greek(n["source"], n["target"], names.get("target_lang") or "greek")
                translated[en] = gr
        except Exception as e:  # one unreadable book never stops the next one's translation
            logger.debug(f"Series names of {jid} skipped: {e}")
    merged = dict(characters)
    folded = {k.casefold(): k for k in merged}
    for en, gr in translated.items():
        if en.casefold() in folded:
            merged.pop(folded[en.casefold()], None)
        merged[en] = gr
        folded[en.casefold()] = en
    return dict(list(merged.items())[-MAX_TERMS:])
