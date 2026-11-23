"""
auth.py - Optional user accounts with administrators (opt-in: BOOKAPP_AUTH=1). Off by default: nothing changes.

* Two roles. 'admin': manages users, Gemini API keys and settings, sees every job. 'user': own jobs only.
* The first administrator on a headless server: while no account exists, a one-time setup code is written to the
  server log and to data/setup_code.txt; open /setup in any browser and enter it. Alternatively, on the server:
  `python -m backend.auth create-admin NAME`. The same tool resets a forgotten password (recovery = server access).
* Passwords are stored only as salted scrypt hashes (Python standard library) in data/auth.db.
* Sessions: a random token in an HttpOnly cookie; only its SHA-256 hash is stored. "Keep me signed in" lasts 60 days
  and is renewed on every visit; otherwise the session ends with the browser (or after 12 idle hours).
* 5 wrong passwords lock that username for 15 minutes (20 per network address). The last active administrator can
  never be demoted, disabled or deleted. Administrative actions are recorded in an audit log.
"""

import os
import re
import sys
import time
import uuid
import hmac
import sqlite3
import secrets
import hashlib
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

logger = logging.getLogger(__name__)

SESSION_COOKIE = "bookapp_session"
REMEMBER_SECONDS = 60 * 24 * 3600          # "Keep me signed in": 60 days, renewed on every visit
BROWSER_SESSION_SECONDS = 12 * 3600        # otherwise: until the browser closes, at most 12 idle hours
RENEW_EVERY_SECONDS = 300                  # a session's expiry is pushed forward at most every 5 minutes
MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 256
MAX_FAILED_PER_USER = 5
MAX_FAILED_PER_IP = 20
MAX_FAILED_SETUP = 10
LOCKOUT_SECONDS = 15 * 60
MAX_SESSIONS_PER_USER = 30
AUDIT_KEEP = 2000
ROLES = ("admin", "user")

_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
_SETUP_CODE_RE = re.compile(r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024

# Reachable without signing in: health checks, the login/setup page and the endpoints it uses
OPEN_PATHS = frozenset({
    "/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/setup", "/api/auth/logout",
    "/login", "/setup", "/login.html", "/favicon.ico",
})
# A user who must change a temporary password can reach only these until it is changed
PASSWORD_CHANGE_PATHS = frozenset({"/api/auth/status", "/api/auth/me", "/api/auth/change-password", "/api/auth/logout"})
# Administrator-only endpoints: (method or '*', path, match as prefix)
_ADMIN_ONLY = (
    ("POST", "/api/settings", False),
    ("DELETE", "/api/settings/", True),
    ("*", "/api/gemini/pool", False),
    ("POST", "/api/gemini/reset-quota", False),
    ("*", "/api/admin/", True),
    ("*", "/api/jobs/tests/cleanup", False),
    ("*", "/api/debug/", True),
    ("*", "/api/pairing", True),
    ("*", "/api/auth/users", True),
    ("*", "/api/auth/audit", False),
)

_MESSAGES = {
    "bad_credentials": (401, "Λάθος όνομα χρήστη ή κωδικός."),
    "locked": (429, "Πολλές αποτυχημένες προσπάθειες. Δοκιμάστε ξανά σε {minutes} λεπτά."),
    "disabled": (403, "Ο λογαριασμός έχει απενεργοποιηθεί. Επικοινωνήστε με τον διαχειριστή."),
    "bad_username": (400, "Το όνομα χρήστη πρέπει να έχει 2–32 λατινικά γράμματα, αριθμούς ή . _ - (χωρίς κενά)."),
    "weak_password": (400, f"Ο κωδικός πρέπει να έχει τουλάχιστον {MIN_PASSWORD_LEN} χαρακτήρες "
                           f"(και όχι τον ίδιο χαρακτήρα ξανά και ξανά)."),
    "password_is_username": (400, "Ο κωδικός δεν μπορεί να είναι ίδιος με το όνομα χρήστη."),
    "same_password": (400, "Ο νέος κωδικός πρέπει να διαφέρει από τον τρέχοντα."),
    "wrong_current_password": (400, "Ο τρέχων κωδικός δεν είναι σωστός."),
    "username_taken": (409, "Υπάρχει ήδη χρήστης με αυτό το όνομα."),
    "not_found": (404, "Ο χρήστης δεν βρέθηκε."),
    "last_admin": (409, "Πρέπει να υπάρχει πάντα τουλάχιστον ένας ενεργός διαχειριστής."),
    "self_action": (409, "Δεν μπορείτε να απενεργοποιήσετε ή να διαγράψετε τον δικό σας λογαριασμό."),
    "bad_role": (400, "Άγνωστος ρόλος (επιτρέπονται: admin, user)."),
    "setup_done": (409, "Η αρχική ρύθμιση έχει ήδη ολοκληρωθεί. Συνδεθείτε με τον λογαριασμό σας."),
    "bad_setup_code": (403, "Λάθος κωδικός ρύθμισης. Θα τον βρείτε στο αρχείο καταγραφής (log) του διακομιστή "
                            "ή στο data/setup_code.txt."),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    disabled INTEGER NOT NULL DEFAULT 0,
    must_change INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    created_by TEXT,
    last_login REAL,
    password_changed_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen REAL NOT NULL,
    expires_at REAL NOT NULL,
    persistent INTEGER NOT NULL DEFAULT 0,
    user_agent TEXT,
    ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT,
    ip TEXT
);
"""

_lock = threading.RLock()
_schema_ready_for: Optional[str] = None
_failures: Dict[str, List[float]] = {}      # key -> [failed attempts, locked until, last failure]
_dummy_hash: Optional[str] = None

Actor = Union[Dict[str, Any], str, None]


class AuthError(Exception):
    """An account error with a user-facing (Greek) message and the HTTP status to answer with."""

    def __init__(self, code: str, **fmt: Any):
        self.code = code
        status, msg = _MESSAGES.get(code, (400, "Σφάλμα λογαριασμού."))
        self.http_status = status
        self.user_message = msg.format(**fmt) if fmt else msg
        super().__init__(self.user_message)


# ---------------------------------------------------------------------------
# Switches & request classification
# ---------------------------------------------------------------------------

def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def is_enabled() -> bool:
    return _truthy(os.environ.get("BOOKAPP_AUTH"))


def cookie_secure(scheme: str) -> bool:
    """Send the session cookie over HTTPS only (behind Caddy/nginx the proxy reports the original scheme)."""
    return scheme == "https" or _truthy(os.environ.get("BOOKAPP_COOKIE_SECURE"))


def is_open_path(path: str) -> bool:
    return path in OPEN_PATHS


def is_admin_path(method: str, path: str) -> bool:
    for m, p, prefix in _ADMIN_ONLY:
        if m != "*" and m != method:
            continue
        if path == p or (prefix and path.startswith(p)):
            return True
    return False


# ---------------------------------------------------------------------------
# Storage (data/auth.db, next to the jobs database)
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    from backend import database
    return Path(database.DB_DIR)


def _db_path() -> Path:
    return _data_dir() / "auth.db"


def _setup_code_path() -> Path:
    return _data_dir() / "setup_code.txt"


def _restrict_file(path: Path) -> None:
    """Owner-only permissions on Linux/macOS (password hashes, setup code)."""
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    global _schema_ready_for
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Autocommit mode with explicit BEGIN IMMEDIATE where several statements must succeed together (the same
    # behaviour on every Python version, whatever its sqlite3 transaction default)
    conn = sqlite3.connect(str(path), timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        if _schema_ready_for != str(path):
            with _lock:
                conn.executescript(_SCHEMA)
                conn.commit()
                _schema_ready_for = str(path)
            _restrict_file(path)
        yield conn
        if conn.in_transaction:
            conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                        maxmem=_SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt((password or "").encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r),
                            p=int(p), maxmem=_SCRYPT_MAXMEM, dklen=len(hash_hex) // 2)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _timing_dummy_hash() -> str:
    """Unknown usernames still cost one scrypt check, so response time does not reveal which names exist."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_hex(16))
    return _dummy_hash


def validate_username(name: Any) -> str:
    n = (name or "").strip() if isinstance(name, str) else ""
    if not _USERNAME_RE.fullmatch(n):
        raise AuthError("bad_username")
    return n


def validate_password(password: Any, username: str = "") -> str:
    if not isinstance(password, str) or not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
        raise AuthError("weak_password")
    if len(set(password)) < 4:
        raise AuthError("weak_password")
    if username and password.strip().lower() == username.strip().lower():
        raise AuthError("password_is_username")
    return password


def generate_temporary_password() -> str:
    """12 random characters in 3 groups (about 70 bits), without look-alike characters: e.g. 'Xk7p-M3qa-9Rtz'."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        raw = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in raw) and any(c.islower() for c in raw) and any(c.isupper() for c in raw):
            return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


# ---------------------------------------------------------------------------
# Brute-force protection
# ---------------------------------------------------------------------------

def _check_locked(*keys: str) -> None:
    now = time.time()
    with _lock:
        for k in keys:
            rec = _failures.get(k)
            if rec and rec[1] > now:
                raise AuthError("locked", minutes=max(1, int((rec[1] - now + 59) // 60)))


def _record_failure(key: str, limit: int) -> None:
    now = time.time()
    with _lock:
        rec = _failures.get(key)
        if not rec or (rec[1] and rec[1] <= now) or now - rec[2] > LOCKOUT_SECONDS:
            rec = [0, 0.0, now]          # a fresh window after a lock expired or after a quiet period
        rec[0] += 1
        rec[2] = now
        if rec[0] >= limit:
            rec[0], rec[1] = 0, now + LOCKOUT_SECONDS
        _failures[key] = rec
        if len(_failures) > 10000:
            for k in [k for k, r in _failures.items() if r[1] <= now and now - r[2] > LOCKOUT_SECONDS]:
                _failures.pop(k, None)


def _clear_failures(*keys: str) -> None:
    with _lock:
        for k in keys:
            _failures.pop(k, None)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def _actor_name(actor: Actor) -> str:
    if isinstance(actor, dict):
        return str(actor.get("username") or actor.get("id") or "")
    return str(actor or "")


def audit(actor: Actor, action: str, target: str = "", detail: str = "", ip: str = "") -> None:
    try:
        with _db() as c:
            c.execute("INSERT INTO audit (ts, actor, action, target, detail, ip) VALUES (?, ?, ?, ?, ?, ?)",
                      (time.time(), _actor_name(actor)[:64], action[:64], (target or "")[:64],
                       (detail or "")[:200], (ip or "")[:64]))
            c.execute("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - ?", (AUDIT_KEEP,))
    except Exception as e:  # the audit log must never break the action itself
        logger.warning("[Auth] Could not write audit entry '%s': %s", action, e)


def list_audit(limit: int = 100) -> List[Dict[str, Any]]:
    with _db() as c:
        rows = c.execute("SELECT ts, actor, action, target, detail, ip FROM audit ORDER BY id DESC LIMIT ?",
                         (max(1, min(int(limit), 500)),)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

_USER_COLS = "id, username, role, disabled, must_change, created_at, created_by, last_login"


def _public(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "disabled": bool(row["disabled"]),
        "must_change": bool(row["must_change"]),
        "created_at": row["created_at"],
        "created_by": row["created_by"] or "",
        "last_login": row["last_login"],
    }


def user_count() -> int:
    with _db() as c:
        return int(c.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def has_users() -> bool:
    return user_count() > 0


def setup_required() -> bool:
    return not has_users()


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    with _db() as c:
        row = c.execute(f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id or "",)).fetchone()
    return _public(row) if row else None


def get_user_by_name(username: str) -> Optional[Dict[str, Any]]:
    with _db() as c:
        row = c.execute(f"SELECT {_USER_COLS} FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
    return _public(row) if row else None


def list_users() -> List[Dict[str, Any]]:
    now = time.time()
    with _db() as c:
        rows = c.execute(f"SELECT {_USER_COLS} FROM users ORDER BY username COLLATE NOCASE").fetchall()
        counts = {r[0]: r[1] for r in c.execute(
            "SELECT user_id, COUNT(*) FROM sessions WHERE expires_at > ? GROUP BY user_id", (now,)).fetchall()}
    out = []
    for r in rows:
        u = _public(r)
        u["active_sessions"] = int(counts.get(u["id"], 0))
        out.append(u)
    return out


def usernames_by_id() -> Dict[str, str]:
    with _db() as c:
        return {r[0]: r[1] for r in c.execute("SELECT id, username FROM users").fetchall()}


def _active_admins(c: sqlite3.Connection, excluding: str = "") -> int:
    return int(c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0 AND id != ?",
                         (excluding,)).fetchone()[0])


def create_user(username: str, password: str, role: str = "user", must_change: bool = False, actor: Actor = None,
                ip: str = "", only_if_no_users: bool = False) -> Dict[str, Any]:
    username = validate_username(username)
    validate_password(password, username)
    if role not in ROLES:
        raise AuthError("bad_role")
    pw_hash = hash_password(password)
    uid = uuid.uuid4().hex
    now = time.time()
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        if only_if_no_users and c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise AuthError("setup_done")
        if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise AuthError("username_taken")
        c.execute("INSERT INTO users (id, username, password_hash, role, disabled, must_change, created_at, created_by, "
                  "password_changed_at) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
                  (uid, username, pw_hash, role, int(bool(must_change)), now, _actor_name(actor)[:64], now))
    audit(actor, "user_created", username, role, ip)
    if role == "admin":
        _clear_setup_code()
    return get_user(uid)


def set_role(actor: Actor, user_id: str, role: str, ip: str = "") -> Dict[str, Any]:
    if role not in ROLES:
        raise AuthError("bad_role")
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("not_found")
        if row["role"] == "admin" and role != "admin" and not row["disabled"] and _active_admins(c, user_id) == 0:
            raise AuthError("last_admin")
        c.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if row["role"] != role:
        audit(actor, "role_changed", row["username"], f"{row['role']} -> {role}", ip)
    return get_user(user_id)


def set_disabled(actor: Actor, user_id: str, disabled: bool, ip: str = "") -> Dict[str, Any]:
    if disabled and isinstance(actor, dict) and actor.get("id") == user_id:
        raise AuthError("self_action")
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("not_found")
        if disabled and row["role"] == "admin" and not row["disabled"] and _active_admins(c, user_id) == 0:
            raise AuthError("last_admin")
        c.execute("UPDATE users SET disabled = ? WHERE id = ?", (int(bool(disabled)), user_id))
        if disabled:
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    if bool(row["disabled"]) != bool(disabled):
        audit(actor, "user_disabled" if disabled else "user_enabled", row["username"], "", ip)
    return get_user(user_id)


def delete_user(actor: Actor, user_id: str, ip: str = "", detail: str = "") -> Dict[str, Any]:
    if isinstance(actor, dict) and actor.get("id") == user_id:
        raise AuthError("self_action")
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("not_found")
        if row["role"] == "admin" and not row["disabled"] and _active_admins(c, user_id) == 0:
            raise AuthError("last_admin")
        c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    audit(actor, "user_deleted", row["username"], detail, ip)
    return _public(row)


def set_password(user_id: str, new_password: str, must_change: bool = False,
                 keep_session_token: Optional[str] = None) -> None:
    """Stores a new password and signs the user out everywhere (except the session that made the change)."""
    user = get_user(user_id)
    if not user:
        raise AuthError("not_found")
    validate_password(new_password, user["username"])
    pw_hash = hash_password(new_password)
    keep = _token_hash(keep_session_token) if keep_session_token else ""
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE users SET password_hash = ?, must_change = ?, password_changed_at = ? WHERE id = ?",
                  (pw_hash, int(bool(must_change)), time.time(), user_id))
        c.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep))


def admin_reset_password(actor: Actor, user_id: str, ip: str = "") -> str:
    """A new temporary password (shown once to the admin); the user must change it at the next sign-in."""
    user = get_user(user_id)
    if not user:
        raise AuthError("not_found")
    temp = generate_temporary_password()
    set_password(user_id, temp, must_change=True)
    audit(actor, "password_reset", user["username"], "", ip)
    return temp


def change_own_password(user: Dict[str, Any], current_password: str, new_password: str,
                        session_token: Optional[str], ip: str = "") -> None:
    key = "u:" + user["username"].lower()
    _check_locked(key)
    with _db() as c:
        row = c.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row:
        raise AuthError("not_found")
    if not verify_password(current_password or "", row["password_hash"]):
        _record_failure(key, MAX_FAILED_PER_USER)
        raise AuthError("wrong_current_password")
    validate_password(new_password, user["username"])
    if verify_password(new_password, row["password_hash"]):
        raise AuthError("same_password")
    set_password(user["id"], new_password, must_change=False, keep_session_token=session_token)
    audit(user, "password_changed", user["username"], "", ip)


def sign_out_everywhere(actor: Actor, user_id: str, ip: str = "") -> int:
    user = get_user(user_id)
    if not user:
        raise AuthError("not_found")
    with _db() as c:
        n = c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount
    audit(actor, "signed_out_everywhere", user["username"], f"{n} sessions", ip)
    return n


# ---------------------------------------------------------------------------
# Sign-in & sessions
# ---------------------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def authenticate(username: str, password: str, ip: str = "") -> Dict[str, Any]:
    name = (username or "").strip()[:64]
    name_key, ip_key = "u:" + name.lower(), "ip:" + (ip or "?")
    _check_locked(name_key, ip_key)
    with _db() as c:
        row = c.execute(f"SELECT {_USER_COLS}, password_hash FROM users WHERE username = ?", (name,)).fetchone()
    ok = verify_password(password or "", row["password_hash"] if row else _timing_dummy_hash())
    if not row or not ok:
        _record_failure(name_key, MAX_FAILED_PER_USER)
        _record_failure(ip_key, MAX_FAILED_PER_IP)
        raise AuthError("bad_credentials")
    if row["disabled"]:
        raise AuthError("disabled")
    _clear_failures(name_key)
    return _public(row)


def create_session(user_id: str, persistent: bool, user_agent: str = "", ip: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires = now + (REMEMBER_SECONDS if persistent else BROWSER_SESSION_SECONDS)
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute("INSERT INTO sessions (token_hash, user_id, created_at, last_seen, expires_at, persistent, user_agent, "
                  "ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (_token_hash(token), user_id, now, now, expires, int(bool(persistent)), (user_agent or "")[:200],
                   (ip or "")[:64]))
        c.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash NOT IN (SELECT token_hash FROM sessions "
                  "WHERE user_id = ? ORDER BY last_seen DESC LIMIT ?)", (user_id, user_id, MAX_SESSIONS_PER_USER))
        c.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
    return token


def session_for_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    The session of a cookie token: {'user': {...}, 'persistent': bool, 'renewed': bool}, or None when the token is
    unknown, expired or belongs to a disabled account. Active sessions slide forward ('renewed' -> re-send cookie).
    """
    if not token or len(token) > 200:
        return None
    th = _token_hash(token)
    now = time.time()
    with _db() as c:
        row = c.execute(
            "SELECT s.last_seen AS s_last_seen, s.expires_at AS s_expires_at, s.persistent AS s_persistent, "
            "u.id, u.username, u.role, u.disabled, u.must_change, u.created_at, u.created_by, u.last_login "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (th,)).fetchone()
        if not row:
            return None
        if row["s_expires_at"] <= now or row["disabled"]:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
            return None
        renewed = False
        if now - row["s_last_seen"] >= RENEW_EVERY_SECONDS:
            span = REMEMBER_SECONDS if row["s_persistent"] else BROWSER_SESSION_SECONDS
            c.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE token_hash = ?", (now, now + span, th))
            renewed = True
    return {"user": _public(row), "persistent": bool(row["s_persistent"]), "renewed": renewed}


def revoke_session(token: Optional[str]) -> None:
    if not token:
        return
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


# ---------------------------------------------------------------------------
# First administrator: one-time setup code
# ---------------------------------------------------------------------------

def _normalise_setup_code(code: Any) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", str(code or "")).upper()
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 8 else raw


def ensure_setup_code() -> Optional[str]:
    """The one-time setup code while no account exists (kept in data/setup_code.txt across restarts), else None."""
    if has_users():
        _clear_setup_code()
        return None
    path = _setup_code_path()
    with _lock:
        try:
            existing = path.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        if _SETUP_CODE_RE.fullmatch(existing):
            return existing
        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(
            secrets.choice(alphabet) for _ in range(4))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code + "\n", encoding="utf-8")
        _restrict_file(path)
        return code


def announce_setup_code() -> Optional[str]:
    """Writes the setup instructions to the server log (journalctl / docker logs) while setup is pending."""
    code = ensure_setup_code()
    if code:
        bar = "=" * 72
        logger.warning(
            "\n%s\n BookApp FIRST-TIME SETUP: no user account exists yet.\n"
            " Open  http://<this-server>:8000/setup  (or https://<your-domain>/setup) in a browser\n"
            " and enter the setup code:   %s\n"
            " The code is also in data/setup_code.txt. Alternatively, on the server run:\n"
            "   python -m backend.auth create-admin <username>\n%s", bar, code, bar)
    return code


def _clear_setup_code() -> None:
    try:
        _setup_code_path().unlink(missing_ok=True)
    except OSError:
        pass


def complete_setup(code: str, username: str, password: str, ip: str = "") -> Dict[str, Any]:
    """Creates the first administrator when the setup code is right (only while no account exists)."""
    if has_users():
        raise AuthError("setup_done")
    _check_locked("setup")
    expected = ensure_setup_code()
    given = _normalise_setup_code(code)
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        _record_failure("setup", MAX_FAILED_SETUP)
        raise AuthError("bad_setup_code")
    validate_username(username)
    validate_password(password, username)
    user = create_user(username, password, role="admin", actor="setup", ip=ip, only_if_no_users=True)
    _clear_failures("setup")
    return user


# ---------------------------------------------------------------------------
# Command line (on the server):  python -m backend.auth <command>
# ---------------------------------------------------------------------------

def _cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    import getpass

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Greek messages on any console
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(
        prog="python -m backend.auth",
        description="Manage BookApp user accounts. Works whether the server is running or not; "
                    "run it from the BookApp folder with the same Python environment.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("create-admin", "create an administrator (asks for the password)"),
                       ("create-user", "create a regular user (asks for the password)"),
                       ("reset-password", "set a new password and sign that user out everywhere")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("username")
        sp.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    sp = sub.add_parser("make-admin", help="give a user administrator rights (and re-enable the account)")
    sp.add_argument("username")
    sub.add_parser("list-users", help="list all accounts")
    sub.add_parser("setup-code", help="show the first-time setup code (only while no account exists)")
    args = parser.parse_args(argv)

    def read_password() -> str:
        if args.password_stdin:
            return sys.stdin.readline().rstrip("\r\n")
        first = getpass.getpass("New password: ")
        if getpass.getpass("Repeat the password: ") != first:
            raise SystemExit("The passwords do not match. Nothing was changed.")
        return first

    actor = "server console"
    try:
        if args.command in ("create-admin", "create-user"):
            role = "admin" if args.command == "create-admin" else "user"
            validate_username(args.username)
            user = create_user(args.username, read_password(), role=role, actor=actor)
            print(f"Created {role} '{user['username']}'. Sign in at /login.")
        elif args.command == "reset-password":
            user = get_user_by_name(args.username)
            if not user:
                raise AuthError("not_found")
            set_password(user["id"], read_password(), must_change=False)
            audit(actor, "password_reset", user["username"])
            print(f"Password of '{user['username']}' changed; all of its sessions were signed out."
                  + (" Note: this account is disabled." if user["disabled"] else ""))
        elif args.command == "make-admin":
            user = get_user_by_name(args.username)
            if not user:
                raise AuthError("not_found")
            set_role(actor, user["id"], "admin")
            set_disabled(actor, user["id"], False)
            print(f"'{user['username']}' is now an active administrator.")
        elif args.command == "list-users":
            users = list_users()
            if not users:
                print("No accounts yet. Create the first administrator with: python -m backend.auth create-admin NAME")
            for u in users:
                last = time.strftime("%Y-%m-%d %H:%M", time.localtime(u["last_login"])) if u["last_login"] else "never"
                flags = (" (disabled)" if u["disabled"] else "") + (" (must change password)" if u["must_change"] else "")
                print(f"{u['username']:<32} {u['role']:<6} last sign-in: {last}{flags}")
        elif args.command == "setup-code":
            code = ensure_setup_code()
            print(f"Setup code: {code}  -> open /setup in a browser." if code
                  else "Setup is complete: accounts already exist (use reset-password if you are locked out).")
    except AuthError as e:
        print(f"Error: {e.user_message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
