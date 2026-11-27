"""
backup.py - A user's books in one ZIP file, and back: to keep them safe or to move them to another server.

The ZIP holds bookapp-backup.json (the books' records, their series, the reading positions and the Glossary) and each
book's files: jobs/<job id>/upload/... (the uploaded document) and jobs/<job id>/output/... (translations, Book
Insights, covers, the names list; audiobooks unless left out).

Restoring adds the books to the signed-in user's. A book already here (the same id, the same user) is left as it is;
one whose id another user's book has comes in under a new id. Glossary terms are added where the Glossary has none for
that word. The ZIP is checked before anything is written: only the paths above, no path out of a book's folders,
sizes within the free disk space. API keys, user accounts and server settings are never part of a backup.

Both run in a thread of their own; their progress is a task (task_status), as they can take minutes for a large
library and a reverse proxy would not wait that long for one request.
"""

import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "temp" / "backups"
MANIFEST = "bookapp-backup.json"
FORMAT = "bookapp-backup"
VERSION = 1
KEEP_SECONDS = 24 * 3600
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
DISK_MARGIN = 200 * 1024 * 1024
MAX_RESTORE_BYTES = int(float(os.environ.get("BOOKAPP_MAX_RESTORE_GB", "50")) * 1024 ** 3)
AUDIO_SUFFIXES = {".mp3", ".m4b", ".m4a", ".wav", ".ogg", ".opus", ".aac"}
STORED_SUFFIXES = {".pdf", ".epub", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".cbz", ".cbr", ".zip", ".gz"} | AUDIO_SUFFIXES
SKIPPED_DIRS = {"extras"}  # made again from the rest when needed
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

_TASKS: Dict[str, Dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()


class BackupError(ValueError):
    """A backup file that cannot be restored, with the reason the user sees."""


def _dirs() -> Tuple[Path, Path]:
    from backend.api.common import OUTPUT_DIR, UPLOAD_DIR
    return UPLOAD_DIR, OUTPUT_DIR


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def _new_task(kind: str, owner: str) -> Dict[str, Any]:
    task = {"id": uuid.uuid4().hex, "kind": kind, "owner": owner or "", "state": "running", "progress": 0,
            "step": "", "error": None, "result": None, "file": None, "file_name": None, "started": time.time()}
    with _TASKS_LOCK:
        for tid in [t for t, v in _TASKS.items() if time.time() - v["started"] > KEEP_SECONDS]:
            _TASKS.pop(tid, None)
        _TASKS[task["id"]] = task
    return task


def task_status(task_id: str, owner: str) -> Optional[Dict[str, Any]]:
    """The task, for its own user only."""
    with _TASKS_LOCK:
        task = _TASKS.get(task_id)
    if not task or task["owner"] != (owner or ""):
        return None
    out = {k: task[k] for k in ("id", "kind", "state", "progress", "step", "error", "result", "file_name")}
    out["size"] = Path(task["file"]).stat().st_size if task.get("file") and Path(task["file"]).is_file() else None
    return out


def task_file(task_id: str, owner: str) -> Optional[Tuple[Path, str]]:
    with _TASKS_LOCK:
        task = _TASKS.get(task_id)
    if not task or task["owner"] != (owner or "") or task["state"] != "done" or not task.get("file"):
        return None
    path = Path(task["file"])
    return (path, task["file_name"]) if path.is_file() else None


def _run(task: Dict[str, Any], work: Callable[[Dict[str, Any]], Any]) -> None:
    def target():
        try:
            task["result"] = work(task)
            task["progress"], task["state"] = 100, "done"
        except BackupError as e:
            task["state"], task["error"] = "error", str(e)
        except Exception as e:
            logger.error(f"Backup task {task['kind']} failed: {e}", exc_info=True)
            task["state"], task["error"] = "error", f"{type(e).__name__}: {e}"
    threading.Thread(target=target, name=f"bookapp-{task['kind']}", daemon=True).start()


def _clean_old_files() -> None:
    if not BACKUP_DIR.is_dir():
        return
    with _TASKS_LOCK:
        busy = {t["file"] for t in _TASKS.values() if t["state"] == "running" and t.get("file")}
    for f in BACKUP_DIR.iterdir():
        try:
            if f.is_file() and str(f) not in busy and time.time() - f.stat().st_mtime > KEEP_SECONDS:
                f.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def owner_jobs(owner: str, admin: bool, everyone: bool) -> List[Any]:
    """The user's books (an administrator's also those from before accounts; all of them with accounts off)."""
    from backend.job_manager import list_jobs
    return [j for j in list_jobs()
            if everyone or (j.owner or "") == (owner or "") or (admin and not j.owner)]


def _book_files(job_id: str, include_audio: bool) -> List[Tuple[Path, str]]:
    """[(file, its name in the ZIP)] of one book."""
    upload_dir, output_dir = _dirs()
    found = []
    for base, part in ((upload_dir / job_id, "upload"), (output_dir / job_id, "output")):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(base)
            if rel.parts[0] in SKIPPED_DIRS or path.name.endswith(".tmp") or path.name.endswith(".part"):
                continue
            if not include_audio and path.suffix.lower() in AUDIO_SUFFIXES:
                continue
            found.append((path, f"jobs/{job_id}/{part}/{rel.as_posix()}"))
    return found


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _glossary_terms() -> Dict[str, Dict[str, str]]:
    from backend.glossary import _read_raw_file
    terms = _read_raw_file().get("terms") or {}
    return {c: dict(v) for c, v in terms.items() if isinstance(v, dict)}


def build_backup(task: Dict[str, Any], owner: str, jobs: List[Any], include_audio: bool) -> Dict[str, Any]:
    from backend.job_manager import _job_to_db_dict
    from backend import reading_sync, series
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _clean_old_files()
    kept, skipped = [], []
    for job in jobs:
        # a running book is left out; so is a folder found on disk under a name that is no job id (restore refuses it)
        busy = job.status in ("running", "queued") or not _UUID_RE.fullmatch(job.job_id or "")
        (skipped if busy else kept).append(job)
    files = {job.job_id: _book_files(job.job_id, include_audio) for job in kept}
    total = sum(_size(p) for fs in files.values() for p, _ in fs) or 1
    ids = {j.job_id for j in kept}
    records = []
    for job in kept:
        rec = _job_to_db_dict(job)
        rec["upload_name"] = Path(job.file_path or "").name
        records.append(rec)
    manifest = {
        "format": FORMAT, "version": VERSION, "created": time.time(), "audio": bool(include_audio),
        "jobs": records,
        "series": [{"name": s["name"], "books": [b for b in s["books"] if b in ids]}
                   for s in series.list_series(owner) if any(b in ids for b in s["books"])],
        "reading": reading_sync.export_for(owner, ids),
        "glossary": _glossary_terms(),
    }
    target = BACKUP_DIR / f"{task['id']}.zip"
    part = target.with_suffix(".zip.part")
    task["file"] = str(part)
    done = 0
    try:
        with zipfile.ZipFile(part, "w", allowZip64=True) as z:
            z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1), compress_type=zipfile.ZIP_DEFLATED)
            for job in kept:
                task["step"] = job.file_name or job.job_id
                for path, name in files[job.job_id]:
                    kind = zipfile.ZIP_STORED if path.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
                    try:
                        z.write(path, name, compress_type=kind)
                    except FileNotFoundError:
                        continue  # made again or removed meanwhile
                    done += _size(path)
                    task["progress"] = min(99, int(done * 100 / total))
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    task["file"] = str(target)
    task["file_name"] = f"BookApp-backup-{time.strftime('%Y-%m-%d')}.zip"
    return {"books": len(kept), "skipped": [j.file_name for j in skipped], "audio": bool(include_audio),
            "series": len(manifest["series"])}


def start_backup(owner: str, jobs: List[Any], include_audio: bool) -> str:
    task = _new_task("backup", owner)
    _run(task, lambda t: build_backup(t, owner, jobs, include_audio))
    return task["id"]


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _safe_parts(parts: List[str]) -> bool:
    if not parts or len(parts) > 12:
        return False
    for p in parts:
        if (not p or p in (".", "..") or len(p) > 255 or any(c in p for c in "\\:\x00")
                or p.split(".")[0].upper() in _RESERVED):
            return False
    return True


def _members(z: zipfile.ZipFile) -> Dict[str, List[Tuple[zipfile.ZipInfo, str, List[str]]]]:
    """{old job id: [(entry, "upload"|"output", path parts)]}; any other entry makes the file unusable."""
    by_job: Dict[str, List[Tuple[zipfile.ZipInfo, str, List[str]]]] = {}
    for info in z.infolist():
        name = info.filename
        if name == MANIFEST or name.endswith("/"):
            continue
        parts = name.split("/")
        if (len(parts) < 4 or parts[0] != "jobs" or not _UUID_RE.fullmatch(parts[1])
                or parts[2] not in ("upload", "output") or not _safe_parts(parts[3:])):
            raise BackupError(f"Το αρχείο δεν είναι αντίγραφο ασφαλείας του BookApp (άγνωστη εγγραφή: {name[:80]}).")
        by_job.setdefault(parts[1], []).append((info, parts[2], parts[3:]))
    return by_job


def _read_manifest(z: zipfile.ZipFile) -> Dict[str, Any]:
    try:
        info = z.getinfo(MANIFEST)
    except KeyError:
        raise BackupError("Το αρχείο δεν είναι αντίγραφο ασφαλείας του BookApp (λείπει το bookapp-backup.json).")
    if info.file_size > MAX_MANIFEST_BYTES:
        raise BackupError("Το bookapp-backup.json είναι πολύ μεγάλο.")
    try:
        manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise BackupError("Το bookapp-backup.json δεν διαβάζεται.")
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupError("Το αρχείο δεν είναι αντίγραφο ασφαλείας του BookApp.")
    if not isinstance(manifest.get("version"), int) or manifest["version"] > VERSION:
        raise BackupError("Το αντίγραφο φτιάχτηκε από νεότερη έκδοση του BookApp: ενημερώστε πρώτα την εφαρμογή.")
    if not isinstance(manifest.get("jobs"), list):
        raise BackupError("Το bookapp-backup.json δεν έχει λίστα βιβλίων.")
    return manifest


def _text(value: Any, limit: int = 500) -> str:
    return str(value if value is not None else "")[:limit]


def _number(value: Any, kind=int, default=0):
    try:
        return kind(value)
    except (TypeError, ValueError):
        return default


def _record(raw: Dict[str, Any], job_id: str, owner: str, file_path: str, output_path: Optional[str]) -> Dict:
    """A job record from a backup's, with its new id, owner and paths; every value of the right type."""
    from backend.job_manager import _job_from_db_row, _job_to_db_dict
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    status = _text(raw.get("status"), 20) or "idle"
    step = _text(raw.get("current_step"), 1000)
    if status in ("running", "queued"):
        status, step = "idle", "Restored from a backup"
    clean_meta = {
        "source_lang": _text(meta.get("source_lang"), 20) or "english",
        "target_lang": _text(meta.get("target_lang"), 20) or "greek",
        "reading_direction": "rtl" if meta.get("reading_direction") == "rtl" else "ltr",
        "quota_behavior": "fallback" if meta.get("quota_behavior") == "fallback" else "wait",
        "total_pages": _number(meta.get("total_pages")), "done_pages": _number(meta.get("done_pages")),
        "sample_range": meta.get("sample_range"),
        **{k: bool(meta.get(k)) for k in ("ai_polish", "max_quality", "scanned", "read_scanned_text")},
        **{k: meta.get(k) if isinstance(meta.get(k), dict) else None
           for k in ("refinement_report", "revision_report", "gemini_usage", "audiobook_options")},
        "final_refinement": meta.get("final_refinement") if isinstance(meta.get("final_refinement"), bool) else None,
        "owner": owner or "",
    }
    row = {
        "job_id": job_id, "file_path": file_path, "file_name": _text(raw.get("file_name"), 300),
        "file_type": _text(raw.get("file_type"), 10).lower(), "status": status, "mode": _text(raw.get("mode"), 20),
        "progress": max(0, min(100, _number(raw.get("progress")))), "current_step": step,
        "total_chunks": _number(raw.get("total_chunks")), "done_chunks": _number(raw.get("done_chunks")),
        "created_at": _number(raw.get("created_at"), float, time.time()),
        "updated_at": _number(raw.get("updated_at"), float, time.time()),
        "output_path": output_path, "output_format": _text(raw.get("output_format"), 10) or None,
        "layout_mode": _text(raw.get("layout_mode"), 20) or "standard", "error": raw.get("error") and _text(raw["error"], 2000),
        "metadata_json": json.dumps(clean_meta),
    }
    job = _job_from_db_row(row)
    return _job_to_db_dict(job)


def _extract(z: zipfile.ZipFile, members, base: Path, part: str) -> None:
    base_resolved = base.resolve()
    for info, where, parts in members:
        if where != part:
            continue
        dest = base.joinpath(*parts)
        if not str(dest.resolve()).startswith(str(base_resolved) + os.sep):
            raise BackupError("Το αρχείο έχει διαδρομή έξω από τον φάκελο του βιβλίου.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out, 1024 * 1024)  # never more than the entry's own size (zipfile stops there)
        mtime = time.mktime(info.date_time + (0, 0, -1)) if info.date_time[0] >= 1980 else time.time()
        os.utime(dest, (mtime, mtime))


def _merge_glossary(terms: Any) -> int:
    from backend.glossary import CATEGORIES_META, load_glossary, set_term
    if not isinstance(terms, dict):
        return 0
    have = {k.casefold() for k in load_glossary(category="all")}
    added = 0
    for category, items in terms.items():
        if category not in CATEGORIES_META or not isinstance(items, dict):
            continue
        for source, target in list(items.items())[:20000]:
            if (isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip()
                    and len(source) <= 200 and len(target) <= 500 and source.strip().casefold() not in have):
                set_term(source, target, category)
                have.add(source.strip().casefold())
                added += 1
    return added


def restore(task: Dict[str, Any], owner: str, zip_path: Path, admin: bool = False) -> Dict[str, Any]:
    from backend.database import db_delete_job, db_save_job
    from backend.job_manager import job_owner
    from backend import reading_sync, series
    upload_dir, output_dir = _dirs()
    try:
        with zipfile.ZipFile(zip_path) as z:
            task["step"] = "check"
            manifest = _read_manifest(z)
            by_job = _members(z)
            needed = sum(i.file_size for ms in by_job.values() for i, _, _ in ms)
            free = shutil.disk_usage(output_dir).free
            if needed > free - DISK_MARGIN:
                raise BackupError(f"Δεν υπάρχει αρκετός χώρος στον δίσκο: χρειάζονται {needed // 2**20} MB, "
                                  f"υπάρχουν {max(0, free - DISK_MARGIN) // 2**20} MB.")
            records = [r for r in manifest["jobs"] if isinstance(r, dict) and _UUID_RE.fullmatch(str(r.get("job_id")))]
            job_map: Dict[str, str] = {}
            restored, kept_here, renamed = [], [], 0
            done = 0
            for raw in records:
                old_id = raw["job_id"]
                title = _text(raw.get("file_name"), 300) or old_id
                task["step"] = title
                present = job_owner(old_id)
                if present is not None and (present == (owner or "") or (admin and present == "")):
                    kept_here.append(title)
                    job_map[old_id] = old_id
                    continue
                new_id = old_id
                if present is not None or (upload_dir / old_id).exists() or (output_dir / old_id).exists():
                    new_id = str(uuid.uuid4())
                    renamed += 1
                members = by_job.get(old_id, [])
                staging = [(upload_dir / f".restoring-{new_id}", "upload"), (output_dir / f".restoring-{new_id}", "output")]
                try:
                    for base, part in staging:
                        _extract(z, members, base, part)
                    upload_name = Path(_text(raw.get("upload_name"), 300)).name
                    final_up = upload_dir / new_id
                    file_path = ""
                    if upload_name and (staging[0][0] / upload_name).is_file():
                        file_path = str(final_up / upload_name)
                    elif staging[0][0].is_dir():
                        first = next((p for p in sorted(staging[0][0].iterdir()) if p.is_file()), None)
                        file_path = str(final_up / first.name) if first else ""
                    old_out = Path(_text(raw.get("output_path"), 1000)).name if raw.get("output_path") else ""
                    output_path = (str(output_dir / new_id / old_out)
                                   if old_out and (staging[1][0] / old_out).is_file() else None)
                    db_save_job(_record(raw, new_id, owner, file_path, output_path))
                    try:
                        for (base, _), final in zip(staging, (final_up, output_dir / new_id)):
                            if base.is_dir():
                                os.replace(base, final)
                    except OSError:
                        db_delete_job(new_id)
                        raise
                finally:
                    for base, _ in staging:
                        shutil.rmtree(base, ignore_errors=True)
                job_map[old_id] = new_id
                restored.append(title)
                done += sum(i.file_size for i, _, _ in members)
                task["progress"] = min(95, int(done * 100 / max(needed, 1)))
            task["step"] = "series"
            series_count = 0
            for s in manifest.get("series") or []:
                if not isinstance(s, dict) or not isinstance(s.get("books"), list):
                    continue
                books = [job_map[b] for b in s["books"] if isinstance(b, str) and b in job_map]
                if not books:
                    continue
                try:
                    sid = series.create(owner, s.get("name"))["id"]
                except series.SeriesError:
                    continue
                for b in books:
                    if not series.find(b, owner):
                        series.place(owner, b, sid)
                series_count += 1
            positions = reading_sync.import_for(owner, manifest.get("reading") or {}, job_map)
            glossary_added = _merge_glossary(manifest.get("glossary"))
    except zipfile.BadZipFile:
        raise BackupError("Το αρχείο δεν είναι έγκυρο ZIP.")
    finally:
        Path(zip_path).unlink(missing_ok=True)
    return {"restored": len(restored), "already_here": kept_here, "renamed": renamed, "series": series_count,
            "positions": positions, "glossary_added": glossary_added, "titles": restored[:50]}


def start_restore(owner: str, zip_path: Path, admin: bool = False) -> str:
    task = _new_task("restore", owner)
    _run(task, lambda t: restore(t, owner, zip_path, admin))
    return task["id"]


def restore_upload_path() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _clean_old_files()
    return BACKUP_DIR / f"restore-{uuid.uuid4().hex}.zip"
