"""
book_names.py - The names a translation gave the people, places and terms of a book, kept with the book.

The translation's register of names (its "entity dossier") says how the AI was told to write each name. The names the
finished translation really uses are kept in the job's book_names.json, with the user's own corrections from the
editor (✏️ Review & Edit) on top. They carry the book's spellings into the next book of a series (backend/series.py)
and become suggestions for the Glossary (backend/glossary_learning.py).

book_names.json: {"version": 1, "source_lang", "target_lang", "updated",
                  "names": [{"source": "Keeton", "target": "Κίτον", "origin": "translation" | "edit" | "comic"}]}

The checkpoints that hold a dossier are deleted when a translation succeeds, so the dossier is copied to the job's
.entity_dossier.json as soon as it is made (record_dossier), while the translation runs. JSON, not .txt: the code that
looks for a job's translation takes any .txt file of its folder when it finds no "_translated_" one.
"""

import contextvars
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

FILE_NAME = "book_names.json"
DOSSIER_FILE = ".entity_dossier.json"
MAX_NAMES = 400

_GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]")
_LINE_RE = re.compile(r"^\s*(?:[-*•–]\s*|\d+[.)]\s+)?(.+?)\s*(?:->|→|=>)\s*(.+?)\s*$")
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_EDGE_CHARS = "*_`\"'«»“”‘’ "

# The job a translation runs for: where record_dossier() keeps its register (set by backend.main for each run)
_DOSSIER_SINK: contextvars.ContextVar[Optional[Path]] = contextvars.ContextVar("bookapp_dossier_sink", default=None)


def is_greek_lang(lang: Optional[str]) -> bool:
    return (lang or "").strip().lower() in ("greek", "el")


def _name_key(word: str) -> str:
    from backend.book_insights import _name_key as key
    return key(word)


def _clean(text: str) -> str:
    return " ".join(text.strip().strip(_EDGE_CHARS).split())


# ---------------------------------------------------------------------------
# The dossier
# ---------------------------------------------------------------------------

def begin_job(out_dir: Path) -> contextvars.Token:
    """For the translation run of the job whose files are in `out_dir`: record_dossier() writes there."""
    return _DOSSIER_SINK.set(Path(out_dir))


def end_job(token: contextvars.Token) -> None:
    _DOSSIER_SINK.reset(token)


def record_dossier(dossier: str, out_dir: Optional[Path] = None) -> None:
    """Keeps a translation's register of names with its job (never fails the translation)."""
    target = Path(out_dir) if out_dir else _DOSSIER_SINK.get()
    if not target or not (dossier or "").strip():
        return
    try:
        target.mkdir(parents=True, exist_ok=True)
        tmp = target / f"{DOSSIER_FILE}.{uuid.uuid4().hex[:8]}.tmp"
        tmp.write_text(json.dumps({"entity_dossier": dossier.strip()}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target / DOSSIER_FILE)
    except OSError as e:
        logger.debug(f"The register of names could not be kept: {e}")


def saved_dossier(out_dir: Path) -> str:
    """The register of the job's last translation, also from a checkpoint of a run that stopped."""
    parts = []
    for cp in (DOSSIER_FILE, ".direct_ai_checkpoint.json", ".polish_checkpoint.json"):
        p = Path(out_dir) / cp
        if p.is_file():
            try:
                found = json.loads(p.read_text(encoding="utf-8")).get("entity_dossier")
            except (OSError, ValueError, AttributeError):
                found = None
            if isinstance(found, str) and found.strip():
                parts.append(found)
    return "\n".join(parts)


def parse_dossier(text: str) -> List[Tuple[str, str]]:
    """'- Keeton -> Κίτον (αρσενικό: ο Κίτον)' lines as (Keeton, Κίτον); notes, style rules and phrases are left out."""
    pairs: List[Tuple[str, str]] = []
    seen = set()
    for line in (text or "").splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        src = _clean(re.split(r"\s*[(\[]", m.group(1), maxsplit=1)[0])
        dst = _clean(re.split(r"\s*[(\[]|\s+[—–-]\s|[,;:/]", m.group(2), maxsplit=1)[0])
        if not src or not dst or src.casefold() == dst.casefold() or src.casefold() in seen:
            continue
        if len(src) > 60 or len(dst) > 60 or len(src.split()) > 5 or len(dst.split()) > 6:
            continue
        if re.search(r"[.!?;:…]", src + dst) or "," in src or not _WORD_RE.search(src) or not _WORD_RE.search(dst):
            continue  # a phrase or a sentence, not a name
        seen.add(src.casefold())
        pairs.append((src, dst))
    return pairs


# small words a name may hold in lower case ("Isle of Skye", "Ludwig van Beethoven", "Λόφος του Φιλοπάππου")
_CONNECTORS = frozenset({"of", "the", "de", "da", "di", "du", "del", "della", "des", "la", "le", "les", "von", "van",
                         "der", "den", "y", "al", "el", "bin", "ibn", "ben", "του", "της", "των", "ο", "η", "το", "οι"})


def name_like(text: str) -> bool:
    """A name, not a phrase or a common noun: every word but the small ones starts with a capital. The AI's register
    also holds fixed phrases and objects ("In the cold rain", "lantern"), which are no names to carry on."""
    words = _WORD_RE.findall(text or "")
    significant = [w for w in words if w.lower() not in _CONNECTORS]
    return bool(significant) and len(words) <= 6 and all(w[:1].isupper() for w in significant)


def _script_fits(src: str, dst: str, target_greek: bool) -> bool:
    """English -> Greek in a translation into Greek, Greek -> English in one into English."""
    if target_greek:
        return bool(_GREEK_RE.search(dst)) and not _GREEK_RE.search(src)
    return bool(_GREEK_RE.search(src)) and not _GREEK_RE.search(dst) and bool(_LATIN_RE.search(dst))


def text_keys(text: str) -> set:
    """Every word of a text as a name key: no accents or Greek case ending ("Θησέα" and "Θησέας" are one)."""
    return {_name_key(w) for w in set(_WORD_RE.findall(text or ""))}


def occurs(name: str, keys: set) -> bool:
    """The whole name is in the text, in any of its Greek cases."""
    words = _WORD_RE.findall(name or "")
    long_words = [w for w in words if len(w) >= 3]
    if not long_words:
        return bool(words) and all(w.lower() in keys for w in words)
    return all(_name_key(w) in keys for w in long_words)


def names_used(dossier: str, original: str, translated: str, target_lang: str) -> List[Tuple[str, str]]:
    """The dossier's names that the original has and the translation writes as the dossier says."""
    greek = is_greek_lang(target_lang)
    src_keys = text_keys(original) if original else None
    dst_keys = text_keys(translated)
    found = []
    for src, dst in parse_dossier(dossier):
        if not _script_fits(src, dst, greek) or not name_like(src) or dst.endswith(("-", "‐")):
            continue
        if src_keys is not None and not occurs(src, src_keys):
            continue
        if occurs(dst, dst_keys):
            found.append((src, dst))
    return found


# ---------------------------------------------------------------------------
# book_names.json
# ---------------------------------------------------------------------------

def load(out_dir: Path) -> Dict:
    p = Path(out_dir) / FILE_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"names": []}
    if not isinstance(data, dict) or not isinstance(data.get("names"), list):
        return {"names": []}
    data["names"] = [n for n in data["names"] if isinstance(n, dict) and isinstance(n.get("source"), str)
                     and isinstance(n.get("target"), str) and n["source"].strip() and n["target"].strip()]
    return data


def save(out_dir: Path, names: Iterable[Dict], source_lang: str, target_lang: str) -> Dict:
    out_dir = Path(out_dir)
    kept, seen = [], set()
    for n in names:
        key = n["source"].casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append({"source": n["source"], "target": n["target"], "origin": n.get("origin") or "translation"})
    data = {"version": 1, "source_lang": (source_lang or "").lower(), "target_lang": (target_lang or "").lower(),
            "updated": time.time(), "names": kept[:MAX_NAMES]}
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f".{FILE_NAME}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, out_dir / FILE_NAME)
    finally:
        tmp.unlink(missing_ok=True)
    return data


def names_map(out_dir: Path) -> Dict[str, str]:
    """{original name: its spelling in the translation} (the user's corrections included)."""
    return {n["source"]: n["target"] for n in load(out_dir).get("names", [])}


def original_text(out_dir: Path) -> str:
    originals = sorted(Path(out_dir).glob("*_original.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    return originals[0].read_text(encoding="utf-8", errors="replace") if originals else ""


def refresh(out_dir: Path, translated: str, source_lang: str, target_lang: str) -> Dict:
    """After a translation: the names of its dossier that the text uses. The user's corrections of the same
    translation language stay (a translation into another language starts afresh)."""
    old = load(out_dir)
    same_language = (old.get("target_lang") or "") == (target_lang or "").lower()
    kept = [n for n in old["names"] if same_language and n.get("origin") in ("edit", "comic")]
    taken = {n["source"].casefold() for n in kept}
    found = names_used(saved_dossier(out_dir), original_text(out_dir), translated, target_lang)
    names = kept + [{"source": s, "target": t, "origin": "translation"} for s, t in found if s.casefold() not in taken]
    return save(out_dir, names, source_lang, target_lang)


def save_comic_names(out_dir: Path, chosen: Dict[str, str], source_lang: str, target_lang: str) -> None:
    """A graphic novel's names (one spelling each, chosen across its pages): its text is part of the pictures."""
    try:
        greek = is_greek_lang(target_lang)
        names = [{"source": " ".join(s.split()), "target": " ".join(t.split()), "origin": "comic"}
                 for s, t in (chosen or {}).items()
                 if isinstance(s, str) and isinstance(t, str) and s.strip() and t.strip()
                 and s.casefold() != t.casefold() and _script_fits(s, t, greek) and name_like(s)]
        old = [n for n in load(out_dir)["names"] if n.get("origin") == "edit"]
        save(out_dir, old + names, source_lang, target_lang)
    except Exception as e:  # never fails the translation
        logger.debug(f"The graphic novel's names could not be kept: {e}")


# ---------------------------------------------------------------------------
# What the editor teaches: a name written another way everywhere
# ---------------------------------------------------------------------------

def _similar(a: str, b: str) -> bool:
    import difflib
    fa = "".join(c for c in unicodedata.normalize("NFD", a.lower()) if not unicodedata.combining(c))
    fb = "".join(c for c in unicodedata.normalize("NFD", b.lower()) if not unicodedata.combining(c))
    return fa != fb and difflib.SequenceMatcher(None, fa, fb).ratio() >= 0.5


def _swap_ending(nominative: str, form: str, new_form: str) -> str:
    """The nominative of `new_form` ("Θισέα" of "Θησέας"/"Θησέα" -> "Θισέας"): the same ending change."""
    n = 0
    while n < min(len(nominative), len(form)) and nominative[n] == form[n]:
        n += 1
    form_end, nom_end = form[n:], nominative[n:]
    if form_end and not new_form.endswith(form_end):
        return new_form
    return (new_form[: len(new_form) - len(form_end)] if form_end else new_form) + nom_end


def renamed_in_edit(old_text: str, new_text: str, names: Dict[str, str]) -> List[Tuple[str, str, str]]:
    """[(original name, spelling before, spelling now)] for names the user wrote another way in every place:
    a word of the name's spelling gone from the text, and one like it (not there before) in as many places."""
    old_words, new_words = Counter(_WORD_RE.findall(old_text or "")), Counter(_WORD_RE.findall(new_text or ""))
    if old_words == new_words:
        return []
    risen = {w: new_words[w] - old_words.get(w, 0) for w in new_words if new_words[w] > old_words.get(w, 0)}
    if not risen:
        return []
    gone_by_key: Dict[str, List[str]] = {}  # the words no longer in the text, by name key
    for w in old_words:
        if new_words.get(w, 0) == 0 and w[:1].isupper():
            gone_by_key.setdefault(_name_key(w), []).append(w)
    changes = []
    for source, target in names.items():
        words = _WORD_RE.findall(target)
        new_target = target
        for word in words:
            if len(word) < 3:
                continue
            # the name's forms ("Θησέας", "Θησέα", "Θησέα") that are all gone now
            forms = gone_by_key.get(_name_key(word), [])
            if not forms or sum(old_words[f] for f in forms) < 2:
                continue
            gone = sum(old_words[f] for f in forms)
            best = max(forms, key=lambda f: old_words[f])
            candidates = [w for w, n in risen.items() if _similar(w, best) and n * 2 >= old_words[best]
                          and old_words.get(w, 0) == 0 and w[:1].isupper() == best[:1].isupper()]
            if not candidates:
                continue
            replacement = max(candidates, key=lambda w: (risen[w], -abs(len(w) - len(best))))
            if sum(risen[w] for w in candidates) * 2 < gone:
                continue
            new_target = new_target.replace(word, _swap_ending(word, best, replacement), 1)
        if new_target != target:
            changes.append((source, target, new_target))
    return changes


def learn_from_edit(out_dir: Path, old_text: str, new_text: str, source_lang: str,
                    target_lang: str) -> List[Tuple[str, str, str]]:
    """Keeps the user's new spellings of the book's names (origin 'edit'); returns them."""
    data = load(out_dir)
    if data.get("target_lang") and data["target_lang"] != (target_lang or "").lower():
        return []
    current = {n["source"]: n["target"] for n in data["names"]}
    changes = renamed_in_edit(old_text, new_text, current)
    if changes:
        new = {s: t for s, _, t in changes}
        names = [{"source": n["source"], "target": new[n["source"]], "origin": "edit"} if n["source"] in new else n
                 for n in data["names"]]
        save(out_dir, names, source_lang or data.get("source_lang") or "", target_lang)
    return changes


def english_greek(source: str, target: str, target_lang: str) -> Tuple[str, str]:
    """A pair as the Glossary keeps it, English -> Greek, whichever way the book was translated."""
    return (source, target) if is_greek_lang(target_lang) else (target, source)
