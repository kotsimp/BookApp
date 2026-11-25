"""
notify.py - A message to the user's phone when a long job finishes, through ntfy (https://ntfy.sh or a self-hosted
ntfy server). The user installs the ntfy app and subscribes to a private topic name; BookApp publishes to it.

Sent from a background thread, so a slow or unreachable ntfy server never delays a job. Only the job's file name and
outcome are sent: never the book's text.
"""

import json
import logging
import re
import threading
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

TOPIC_RE = re.compile(r"[A-Za-z0-9_-]{6,64}")
TIMEOUT_S = 10


def normalize_server(url: str) -> Optional[str]:
    """'https://ntfy.example.org' from what the user typed, or None when it is not a plain http(s) server address."""
    url = (url or "").strip()
    if not url:
        return "https://ntfy.sh"
    parts = urlsplit(url if "://" in url else f"https://{url}")
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment \
            or parts.username or parts.password:
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def send(server: str, topic: str, title: str, message: str, click: str = "", priority: int = 3) -> None:
    """Publishes one message (JSON, so Greek titles travel intact). Raises on failure."""
    payload = {"topic": topic, "title": title, "message": message, "priority": priority}
    if click:
        payload["click"] = click
    req = urllib.request.Request(
        f"{server.rstrip('/')}/", data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "BookApp"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        resp.read()


_TEXT = {
    "el": {
        "translate_done": "✅ Η μετάφραση ολοκληρώθηκε",
        "audiobook_done": "🎧 Το ηχοβιβλίο είναι έτοιμο",
        "quota": "⏳ Σταμάτησε στο ημερήσιο όριο Gemini",
        "quota_body": "συνεχίζει όταν ανανεωθεί το όριο (ή πατήστε ▶️ Συνέχεια)",
        "translate_error": "⚠️ Η μετάφραση σταμάτησε",
        "audiobook_error": "⚠️ Το ηχοβιβλίο σταμάτησε",
        "sample": "δείγμα, σελίδες",
        "test_title": "🔔 BookApp",
        "test_body": "Οι ειδοποιήσεις λειτουργούν. Θα έρχεται μήνυμα όταν τελειώνει μια μετάφραση ή ένα ηχοβιβλίο.",
    },
    "en": {
        "translate_done": "✅ Translation finished",
        "audiobook_done": "🎧 Audiobook ready",
        "quota": "⏳ Stopped at the Gemini daily limit",
        "quota_body": "it continues when the limit renews (or press ▶️ Resume)",
        "translate_error": "⚠️ Translation stopped",
        "audiobook_error": "⚠️ Audiobook stopped",
        "sample": "sample, pages",
        "test_title": "🔔 BookApp",
        "test_body": "Notifications work. A message will come when a translation or an audiobook finishes.",
    },
}


def texts(lang: str) -> dict:
    return _TEXT["en" if (lang or "").lower().startswith("en") else "el"]


def job_message(job, lang: str = "el") -> Optional[tuple[str, str, int]]:
    """(title, message, priority) for a job that just finished or stopped; None when there is nothing to say."""
    from backend.job_manager import is_quota_error
    t = texts(lang)
    kind = "audiobook" if job.mode == "audiobook" else "translate"
    name = f"«{job.file_name}»" if job.file_name else "BookApp"
    if job.status == "done":
        extra = ""
        sample = getattr(job, "sample_range", None)
        if kind == "translate" and sample:
            extra = f" · {t['sample']} {sample[0]}–{sample[1]}"
        return t[f"{kind}_done"], f"{name}{extra}", 3
    if job.status == "error":
        if is_quota_error(job.error):
            return t["quota"], f"{name}: {t['quota_body']}", 3
        return t[f"{kind}_error"], f"{name}: {(job.error or '').strip()[:240]}", 4
    return None


def job_finished(job) -> None:
    """Announces a finished or stopped job to its owner's phone, if they set up notifications."""
    from backend.connections import ntfy_settings
    settings = ntfy_settings(getattr(job, "owner", "") or "")
    if not settings["enabled"]:
        return
    found = job_message(job, settings.get("lang") or "el")
    if not found:
        return
    title, message, priority = found

    def _run():
        try:
            send(settings["server"], settings["topic"], title, message, click=settings.get("app_url") or "",
                 priority=priority)
        except Exception as e:  # the phone not hearing about a job must never matter to the job
            logger.warning(f"ntfy notification for job {job.job_id} not sent: {e}")

    threading.Thread(target=_run, name="ntfy", daemon=True).start()
