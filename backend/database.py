"""
database.py - Persistent SQLite Database & Translation Cache for BookApp.
Provides:
1. Persistent job storage across server restarts (data/bookapp.db).
2. Content-hash based Translation & AI Polish semantic cache (SHA256).
3. Thread-safe operations using SQLite WAL (Write-Ahead-Logging) mode and thread-locking.
"""

import json
import time
import hashlib
import sqlite3
import threading
import logging
from pathlib import Path
from typing import Optional, Any, Dict, List

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "bookapp.db"

_db_lock = threading.RLock()


def _get_connection() -> sqlite3.Connection:
    """Returns a SQLite connection configured with WAL mode and row factory."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db() -> None:
    """Initializes database schema if tables do not exist."""
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        file_path TEXT,
                        file_name TEXT,
                        file_type TEXT,
                        status TEXT,
                        mode TEXT,
                        progress INTEGER,
                        current_step TEXT,
                        total_chunks INTEGER,
                        done_chunks INTEGER,
                        created_at REAL,
                        updated_at REAL,
                        output_path TEXT,
                        output_format TEXT,
                        layout_mode TEXT,
                        error TEXT,
                        metadata_json TEXT
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS translation_cache (
                        cache_key TEXT PRIMARY KEY,
                        source_text TEXT,
                        translated_text TEXT,
                        source_lang TEXT,
                        target_lang TEXT,
                        engine TEXT,
                        created_at REAL,
                        hits INTEGER DEFAULT 1
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cache_key ON translation_cache(cache_key);
                """)
        finally:
            conn.close()


# Initialize schema on module import
init_db()


# ---------------------------------------------------------------------------
# Job Persistence Operations
# ---------------------------------------------------------------------------

def db_save_job(job_dict: Dict[str, Any]) -> None:
    """Inserts or updates a job record in the database."""
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO jobs (
                        job_id, file_path, file_name, file_type, status, mode,
                        progress, current_step, total_chunks, done_chunks,
                        created_at, updated_at, output_path, output_format,
                        layout_mode, error, metadata_json
                    ) VALUES (
                        :job_id, :file_path, :file_name, :file_type, :status, :mode,
                        :progress, :current_step, :total_chunks, :done_chunks,
                        :created_at, :updated_at, :output_path, :output_format,
                        :layout_mode, :error, :metadata_json
                    )
                    ON CONFLICT(job_id) DO UPDATE SET
                        file_path=excluded.file_path,
                        file_name=excluded.file_name,
                        file_type=excluded.file_type,
                        status=excluded.status,
                        mode=excluded.mode,
                        progress=excluded.progress,
                        current_step=excluded.current_step,
                        total_chunks=excluded.total_chunks,
                        done_chunks=excluded.done_chunks,
                        updated_at=excluded.updated_at,
                        output_path=excluded.output_path,
                        output_format=excluded.output_format,
                        layout_mode=excluded.layout_mode,
                        error=excluded.error,
                        metadata_json=excluded.metadata_json;
                """, {
                    "job_id": job_dict.get("job_id"),
                    "file_path": job_dict.get("file_path", ""),
                    "file_name": job_dict.get("file_name", ""),
                    "file_type": job_dict.get("file_type", ""),
                    "status": job_dict.get("status", "idle"),
                    "mode": job_dict.get("mode", ""),
                    "progress": int(job_dict.get("progress") or 0),
                    "current_step": job_dict.get("current_step") or "",
                    "total_chunks": int(job_dict.get("total_chunks") or 0),
                    "done_chunks": int(job_dict.get("done_chunks") or 0),
                    "created_at": float(job_dict.get("created_at") or time.time()),
                    "updated_at": float(job_dict.get("updated_at") or time.time()),
                    "output_path": job_dict.get("output_path"),
                    "output_format": job_dict.get("output_format"),
                    "layout_mode": job_dict.get("layout_mode", "standard"),
                    "error": job_dict.get("error"),
                    "metadata_json": json.dumps(job_dict.get("metadata", {}), ensure_ascii=False) if isinstance(job_dict.get("metadata"), dict) else job_dict.get("metadata_json", "{}"),
                })
        except Exception as e:
            logger.warning(f"Error persisting job {job_dict.get('job_id')} to DB: {e}")
        finally:
            conn.close()


def db_get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single job by job_id from the database."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.warning(f"Error fetching job {job_id} from DB: {e}")
            return None
        finally:
            conn.close()


def db_list_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    """Returns most recent jobs from the database."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"Error listing jobs from DB: {e}")
            return []
        finally:
            conn.close()


def db_delete_job(job_id: str) -> bool:
    """Deletes a job from the database."""
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                res = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
                return res.rowcount > 0
        except Exception as e:
            logger.warning(f"Error deleting job {job_id} from DB: {e}")
            return False
        finally:
            conn.close()


def db_clear_all_jobs() -> int:
    """Deletes all job records from the SQLite jobs table (preserves translation cache)."""
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                res = conn.execute("DELETE FROM jobs")
                return res.rowcount
        except Exception as e:
            logger.warning(f"Error clearing all jobs from DB: {e}")
            return 0
        finally:
            conn.close()


def db_reset_orphaned_running_jobs() -> int:
    """Resets any stale 'running' or 'queued' jobs left over after a server restart to 'idle' so they can resume cleanly."""
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                res = conn.execute(
                    "UPDATE jobs SET status = 'idle', current_step = 'Ready to resume (saved checkpoint)' WHERE status IN ('running', 'queued')"
                )
                return res.rowcount
        except Exception as e:
            logger.warning(f"Error resetting orphaned running jobs in DB: {e}")
            return 0
        finally:
            conn.close()


def db_cleanup_old_jobs(max_age_seconds: int = 86400 * 7) -> int:
    """Deletes job records older than max_age_seconds (default 7 days)."""
    with _db_lock:
        conn = _get_connection()
        try:
            cutoff = time.time() - max_age_seconds
            with conn:
                res = conn.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
                return res.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning old jobs from DB: {e}")
            return 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Semantic Translation & Polish Cache Operations
# ---------------------------------------------------------------------------

def compute_cache_key(source_text: str, source_lang: str, target_lang: str, engine: str, extra: str = "") -> str:
    """Computes a SHA256 cache key for text and translation/polish parameters."""
    normalized = (source_text or "").strip()
    payload = f"{(source_lang or '').lower()}->{(target_lang or '').lower()}::{(engine or '').lower()}::{extra or ''}::{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def db_get_cached_translation(cache_key: str) -> Optional[str]:
    """Retrieves cached translation if available and increments hit counter."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT translated_text FROM translation_cache WHERE cache_key = ?",
                (cache_key,)
            )
            row = cursor.fetchone()
            if row:
                with conn:
                    conn.execute(
                        "UPDATE translation_cache SET hits = hits + 1 WHERE cache_key = ?",
                        (cache_key,)
                    )
                return row[0]
            return None
        except Exception as e:
            logger.warning(f"Error reading translation cache: {e}")
            return None
        finally:
            conn.close()


def db_set_cached_translation(
    cache_key: str,
    source_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
    engine: str,
) -> None:
    """Stores a translation result into the cache."""
    if not source_text.strip() or not translated_text.strip():
        return
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO translation_cache (
                        cache_key, source_text, translated_text, source_lang,
                        target_lang, engine, created_at, hits
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        translated_text = excluded.translated_text,
                        hits = hits + 1;
                """, (
                    cache_key, source_text.strip(), translated_text.strip(),
                    source_lang.lower(), target_lang.lower(), engine.lower(),
                    time.time()
                ))
        except Exception as e:
            logger.warning(f"Error writing translation cache: {e}")
        finally:
            conn.close()


def db_get_cache_stats() -> Dict[str, Any]:
    """Returns statistics about the translation cache."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(hits), 0) FROM translation_cache;")
            count, total_hits = cursor.fetchone()
            return {"cached_entries": count, "total_hits": total_hits}
        except Exception as e:
            return {"cached_entries": 0, "total_hits": 0, "error": str(e)}
        finally:
            conn.close()
