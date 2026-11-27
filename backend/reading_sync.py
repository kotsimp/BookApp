"""
reading_sync.py - Where each user is in their books: a reading-position sync server for KOReader and Readest.

Both apps speak the protocol of KOReader's own sync server ("kosync", backend/api/sync.py serves it at /kosync). A book
is known by a fingerprint of its file (an MD5 of 1 KB samples, as KOReader computes it) or of its file name. BookApp
notes the fingerprints of every file it hands out (downloads and the e-reader catalogue), for the user it hands it to,
so a position that user's apps send for one of them is the position in that book: shown with the book, and used by
"The story so far" (Book Insights). Per user: the same file can be several users' books (copies of one backup).

Each user signs in to sync with their BookApp user name and a sync password made in 📲 Devices (shown once; only a
hash of what the app sends is kept: the apps send the password's MD5, never the password itself).

data/reading_sync.json:
  {"accounts": {owner: {"key": sha256 of the password's MD5, "created"}},
   "files": {owner: {fingerprint: {"job_id", "kind", "seen"}}},
   "progress": {owner: {fingerprint: {"progress", "percentage", "device", "device_id", "timestamp"}}}}
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STORE = Path(__file__).resolve().parent.parent / "data" / "reading_sync.json"
_lock = threading.RLock()
MAX_FILES = 20000
MAX_PROGRESS_PER_USER = 3000
_FINGERPRINTS: Dict[str, tuple] = {}  # file path -> ((size, mtime), fingerprint)


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except FileNotFoundError:
        data = {}
    except Exception as e:
        from backend.series import keep_unreadable
        logger.warning(f"reading_sync.json unreadable, starting empty (a copy is kept as .corrupt): {e}")
        keep_unreadable(STORE)
        data = {}
    for key in ("accounts", "files", "progress"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    data["accounts"] = {o: a for o, a in data["accounts"].items() if isinstance(a, dict)}
    data["files"] = {o: {k: v for k, v in f.items() if isinstance(v, dict)}
                     for o, f in data["files"].items() if isinstance(f, dict) and "job_id" not in f}
    data["progress"] = {o: {k: v for k, v in p.items() if isinstance(v, dict)}
                        for o, p in data["progress"].items() if isinstance(p, dict)}
    return data


def _save(data: Dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_name(f".{STORE.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STORE)
    finally:
        tmp.unlink(missing_ok=True)
    if os.name == "posix":
        try:
            os.chmod(STORE, 0o600)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Fingerprints of books
# ---------------------------------------------------------------------------

def partial_md5(path: Path) -> str:
    """KOReader's fingerprint of a file: the MD5 of 1 KB read at 0, 1 KB, 4 KB, 16 KB, ... 1 GB (as far as the file
    goes). Readest computes the same."""
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        for i in range(-1, 11):
            f.seek(0 if i < 0 else 1024 << (2 * i))
            sample = f.read(1024)
            if not sample:
                break
            md5.update(sample)
    return md5.hexdigest()


def name_md5(file_name: str) -> str:
    """KOReader's other way to know a book: the MD5 of its file name."""
    return hashlib.md5(file_name.encode("utf-8")).hexdigest()


def note_file(owner: str, job_id: str, kind: str, path: Path, *names: str) -> None:
    """A file of the book `job_id` was handed out to `owner` under these file names: its fingerprint and theirs now
    name the book for that user's reading apps (never fails a download)."""
    try:
        path = Path(path)
        st = path.stat()
        cached = _FINGERPRINTS.get(str(path))
        if cached and cached[0] == (st.st_size, st.st_mtime):
            fingerprint = cached[1]
        else:
            fingerprint = partial_md5(path)
            _FINGERPRINTS[str(path)] = ((st.st_size, st.st_mtime), fingerprint)
        keys = {fingerprint} | {name_md5(n) for n in names if n}
        with _lock:
            data = _load()
            files = data["files"].setdefault(owner or "", {})
            if all(files.get(k, {}).get("job_id") == job_id and files[k].get("kind") == kind for k in keys):
                return
            for k in keys:
                files[k] = {"job_id": job_id, "kind": kind, "seen": time.time()}
            if len(files) > MAX_FILES:
                for k in sorted(files, key=lambda x: files[x].get("seen") or 0)[: len(files) - MAX_FILES]:
                    del files[k]
            _save(data)
    except Exception as e:
        logger.debug(f"Reading sync: fingerprint of {path} not noted: {e}")


def forget_book(job_id: str) -> None:
    forget_books({job_id})


def forget_books(job_ids) -> None:
    """Deleted books: their files no longer name a book (the positions stay with the apps' own fingerprints)."""
    gone = set(job_ids)
    with _lock:
        data = _load()
        changed = False
        for files in data["files"].values():
            for k in [k for k, v in files.items() if v.get("job_id") in gone]:
                del files[k]
                changed = True
        if changed:
            _save(data)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def _key_hash(md5_hex: str) -> str:
    return hashlib.sha256(md5_hex.strip().lower().encode("utf-8")).hexdigest()


def status(owner: str) -> Dict[str, Any]:
    with _lock:
        data = _load()
    acc = data["accounts"].get(owner or "") or {}
    mine = data["progress"].get(owner or "") or {}
    last = max((p.get("timestamp") or 0 for p in mine.values()), default=0)
    return {"exists": bool(acc.get("key")), "created": acc.get("created"), "last_sync": last or None}


def new_password(owner: str) -> str:
    """A new sync password for `owner` (shown once); the previous one stops working."""
    password = "-".join(secrets.token_hex(3) for _ in range(4))
    with _lock:
        data = _load()
        data["accounts"][owner or ""] = {"key": _key_hash(hashlib.md5(password.encode("utf-8")).hexdigest()),
                                         "created": time.time()}
        _save(data)
    return password


def remove_password(owner: str) -> None:
    with _lock:
        data = _load()
        if data["accounts"].pop(owner or "", None) is not None:
            _save(data)


def check_key(owner: str, key: str) -> bool:
    """Whether `key` (the MD5 of a password, as the apps send it) is the owner's sync password."""
    if not key or len(key) > 128:
        return False
    with _lock:
        acc = _load()["accounts"].get(owner or "") or {}
    stored = acc.get("key") or ""
    return bool(stored) and hmac.compare_digest(stored, _key_hash(key))


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def save_progress(owner: str, document: str, progress: str, percentage: float, device: str,
                  device_id: str) -> float:
    now = time.time()
    with _lock:
        data = _load()
        mine = data["progress"].setdefault(owner or "", {})
        mine[document] = {"progress": progress, "percentage": percentage, "device": device,
                          "device_id": device_id, "timestamp": now}
        if len(mine) > MAX_PROGRESS_PER_USER:
            for k in sorted(mine, key=lambda x: mine[x].get("timestamp") or 0)[: len(mine) - MAX_PROGRESS_PER_USER]:
                del mine[k]
        _save(data)
    return now


def get_progress(owner: str, document: str) -> Optional[Dict[str, Any]]:
    with _lock:
        found = (_load()["progress"].get(owner or "") or {}).get(document)
    return dict(found, document=document) if found else None


def book_positions(owner: str) -> Dict[str, Dict[str, Any]]:
    """{job_id: the latest position the owner's apps sent for any file of that book}."""
    with _lock:
        data = _load()
    out: Dict[str, Dict[str, Any]] = {}
    files = data["files"].get(owner or "") or {}
    for doc, pos in (data["progress"].get(owner or "") or {}).items():
        known = files.get(doc)
        if not known:
            continue
        jid = known.get("job_id")
        if jid and (jid not in out or (pos.get("timestamp") or 0) > (out[jid].get("timestamp") or 0)):
            out[jid] = {"percentage": pos.get("percentage"), "device": pos.get("device") or "",
                        "timestamp": pos.get("timestamp") or 0, "kind": known.get("kind") or ""}
    return out


def export_for(owner: str, job_ids: set) -> Dict[str, Any]:
    """The owner's positions in these books, with the fingerprints that name them (for a backup)."""
    with _lock:
        data = _load()
    files = {k: v for k, v in (data["files"].get(owner or "") or {}).items() if v.get("job_id") in job_ids}
    progress = {k: v for k, v in (data["progress"].get(owner or "") or {}).items() if k in files}
    return {"files": files, "progress": progress}


def import_for(owner: str, exported: Dict[str, Any], job_map: Dict[str, str]) -> int:
    """Positions of a backup, for its books under their new ids; a newer position already here is kept."""
    files = exported.get("files") if isinstance(exported, dict) else None
    progress = exported.get("progress") if isinstance(exported, dict) else None
    if not isinstance(files, dict) or not isinstance(progress, dict):
        return 0
    added = 0
    with _lock:
        data = _load()
        mine = data["progress"].setdefault(owner or "", {})
        known = data["files"].setdefault(owner or "", {})
        for doc, info in list(files.items())[:MAX_FILES]:
            if not isinstance(doc, str) or len(doc) > 64 or not isinstance(info, dict):
                continue
            new_id = job_map.get(str(info.get("job_id") or ""))
            if not new_id:
                continue
            known[doc] = {"job_id": new_id, "kind": str(info.get("kind") or "")[:20],
                                  "seen": float(info.get("seen") or time.time())}
            pos = progress.get(doc)
            if not isinstance(pos, dict):
                continue
            try:
                entry = {"progress": str(pos.get("progress") or "")[:2000],
                         "percentage": min(max(float(pos.get("percentage") or 0), 0.0), 1.0),
                         "device": str(pos.get("device") or "")[:100],
                         "device_id": str(pos.get("device_id") or "")[:100],
                         "timestamp": float(pos.get("timestamp") or 0)}
            except (TypeError, ValueError):
                continue
            if (mine.get(doc) or {}).get("timestamp", 0) < entry["timestamp"]:
                mine[doc] = entry
                added += 1
        _save(data)
    return added
