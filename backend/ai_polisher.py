"""
ai_polisher.py - AI-Powered Translation Proofreading & Refinement using Gemini API.
Polishes machine-translated Greek text into natural, grammatically flawless,
and stylistically appropriate language (formal administrative, technical, natural, literature, audiobook).
Features bilingual source-anchoring, character/entity consistency dossier,
rolling narrative context, and smart disk checkpointing.
"""

import os
import re
import json
import time
import hashlib
import logging
import asyncio
import threading
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Callable, Any

import aiohttp

logger = logging.getLogger(__name__)

STYLE_PROMPTS = {
    "literature": (
        "Είσαι διακεκριμένος λογοτεχνικός μεταφραστής και επιμελητής εκδόσεων με εξειδίκευση στη σύγχρονη ξένη πεζογραφία και την επιστημονική φαντασία (sci-fi / speculative fiction). "
        "Βελτίωσε και επιμελήσου την ακόλουθη ελληνική μετάφραση ώστε να αποκτήσει εξαιρετική λογοτεχνική ποιότητα, φυσικότητα, ρυθμό και ατμοσφαιρικό βάθος: "
        "1. ΕΞΑΛΕΙΨΗ ΚΑΤΑ ΛΕΞΗ ΜΕΤΑΦΡΑΣΗΣ & ΑΓΓΛΙΣΜΩΝ: "
        "   - Εξάλειψε πλήρως μηχανικές αδεξιότητες, αγγλισμούς και ξύλινες δομές (π.χ. 'να διαχειριστής' -> 'να διαχειριστείς/να αντιμετωπίσεις', 'έκανε νόημα' -> 'έγνεψε', 'ήταν ικανός να' -> 'μπορούσε να'). "
        "   - ΜΗΝ μεταφράζεις ιδιωματισμούς κατά λέξη (idioms & metaphors). Απόδοσέ τους με ισοδύναμες, ζωντανές ελληνικές εκφράσεις που ταιριάζουν στο συγκείμενο. "
        "   - Εάν παρέχεται το πρωτότυπο κείμενο αναφοράς, συμβουλέψου το για να επιλύσεις τυχόν μεταφραστικές παρανοήσεις, αμφισημίες ή ψευδόφιλες λέξεις (false friends) του προσχεδίου. "
        "2. ΕΝΕΡΓΗΤΙΚΗ ΣΥΝΤΑΞΗ & ΛΟΓΟΤΕΧΝΙΚΗ ΡΟΗ: "
        "   - Προτίμησε την ενεργητική σύνταξη έναντι της βαριάς αγγλικής παθητικής φωνής. "
        "   - Μετάτρεψε δυσκίνητες μετοχικές φράσεις σε φυσικές χρονικές ή αιτιολογικές προτάσεις. "
        "   - Χρησιμοποίησε πλούσιο, εκφραστικό ελληνικό λεξιλόγιο, διατηρώντας το ύφος, την ένταση και τον λογοτεχνικό ρυθμό του συγγραφέα. "
        "3. ΖΩΝΤΑΝΙΑ ΔΙΑΛΟΓΩΝ, ΕΝΙΑΙΑ ΣΤΙΞΗ & ΣΥΝΕΠΕΙΑ ΓΕΝΟΥΣ/ΟΡΟΛΟΓΙΑΣ: "
        "   - Απόδωσε τους διαλόγους με προφορική ζωντάνια και φυσικότητα. "
        "   - Χρησιμοποίησε ΑΥΣΤΗΡΑ ΕΝΙΑΙΑ ελληνικά εισαγωγικά διαλόγου («...») για ΟΛΟΥΣ τους διαλόγους σε όλο το βιβλίο — ΜΗΝ εναλλάσσεις μεταξύ «...», παυλών διαλόγου (—) και αγγλικών εισαγωγικών (\"...\"). Χρησιμοποίησε την παύλα (—) μόνο για παρενθετικές φράσεις ή αποδόσεις επιγραφών. "
        "   - Διατήρησε απόλυτη συνέπεια στο γραμματικό γένος (ο/η/το) κάθε χαρακτήρα, πλοίου και οντότητας, καθώς και στα ονόματα και όρους του Μητρώου. ΜΗΝ συγχέεις διαφορετικές οντότητες ή όρους μεταξύ τους. "
        "   - Διόρθωσε όλα τα γραμματικά, συντακτικά και πτωτικά λάθη. "
        "4. ΔΙΑΤΗΡΗΣΗ ΔΟΜΗΣ, ΟΡΙΩΝ & ΔΕΙΚΤΩΝ: "
        "   - Διατήρησε ΑΠΑΡΑΛΛΑΧΤΗ τη δομή των παραγράφων, τα κενά σκηνών (π.χ. * * *) και όλους τους δείκτες σελίδων (π.χ. === PAGE X ===) ακριβώς στις θέσεις τους. "
        "   - Αν παρέχεται τμήμα <PREVIOUS_CONTEXT_DO_NOT_REPEAT>, χρησιμοποίησέ το ΑΠΟΚΛΕΙΣΤΙΚΑ για να γνωρίζεις τη συνέχεια/γένος/ύφος — ΜΗΝ το επαναλαμβάνεις, ΜΗΝ το μεταφράζεις και ΜΗΝ το συμπεριλαμβάνεις ΠΟΤΕ στην έξοδό σου. "
        "5. ΚΑΘΑΡΟΤΗΤΑ ΕΞΟΔΟΥ (ΑΥΣΤΗΡΟ): "
        "   - ΜΗΝ αφήνεις ποτέ ετικέτες HTML/XML (π.χ. <i>, </i>, <bos>, <TEXT_TO_POLISH>), αγκύλες αποσπάσματος ([... ...]), σημειώσεις επιμελητή (π.χ. [Σημείωση...]), σκέψεις/σχόλια ανάλυσης ή ξένους χαρακτήρες (λατινικούς, κυριλλικούς, εβραϊκούς κ.λπ.) μέσα σε ελληνικές λέξεις. "
        "   - Μην προσθέτεις εισαγωγικά σχόλια, προοίμια ή επεξηγηματικές σημειώσεις. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το διορθωμένο λογοτεχνικό κείμενο."
    ),
    "natural": (
        "Είσαι έμπειρος φιλόλογος και επιμελητής εκδόσεων. Βελτίωσε την ακόλουθη ελληνική μετάφραση "
        "ώστε να αποκτήσει απόλυτα φυσική ροή, εκφραστικό πλούτο και ομαλότητα σαν να γράφτηκε εξαρχής στα Ελληνικά: "
        "1. Εξομάλυνε τη σύνταξη και διόρθωσε κάθε γραμματική ατέλεια. "
        "2. Διατήρησε απόλυτα όλες τις παραγράφους, επικεφαλίδες και δομή του πρωτοτύπου, καθώς και τους δείκτες (π.χ. === PAGE X ===). "
        "3. Επίστρεψε ΜΟΝΟ το διορθωμένο κείμενο χωρίς σχόλια."
    ),
    "formal": (
        "Είσαι κορυφαίος επιμελητής κειμένων και μεταφραστής με εξειδίκευση σε επίσημα και υπηρεσιακά έγγραφα "
        "της ελληνικής δημόσιας διοίκησης. Βελτίωσε και επιμελήσου την ακόλουθη ελληνική μετάφραση: "
        "1. Εξάλειψε τις μηχανικές/κατά λέξη μεταφράσεις και προσάρμοσε το λεξιλόγιο σε άψογη υπηρεσιακή/διοικητική γλώσσα. "
        "2. Διόρθωσε γραμματικά, συντακτικά και πτωτικά λάθη. "
        "3. Διατήρησε ΑΠΑΡΑΛΛΑΧΤΗ τη δομή των παραγράφων, τις κουκίδες, τις επικεφαλίδες και τα διαχωριστικά (π.χ. === PAGE X ===). "
        "4. Μην προσθέτεις δικά σου εισαγωγικά σχόλια, επεξηγήσεις ή σημειώσεις. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το διορθωμένο κείμενο."
    ),
    "technical": (
        "Είσαι εξειδικευμένος τεχνικός μεταφραστής πληροφορικής και μηχανικής στα Ελληνικά. "
        "Βελτίωσε την ακόλουθη τεχνική μετάφραση: "
        "1. Χρησιμοποίησε ακριβή και καθιερωμένη ελληνική τεχνική ορολογία, διατηρώντας διεθνή ακρωνύμια (π.χ. UPS, Server, API). "
        "2. Διόρθωσε ασάφειες και λάθη σύνταξης. "
        "3. Διατήρησε επακριβώς όλες τις παραγράφους, λίστες, κωδικούς και δομή. "
        "4. Επίστρεψε ΜΟΝΟ το διορθωμένο τεχνικό κείμενο χωρίς κανένα άλλο σχόλιο."
    ),
    "audiobook": (
        "Είσαι έμπειρος επιμελητής σεναρίων και κειμένων για ηχογράφηση Audiobooks (Spoken Word & Neural TTS Script Editor). "
        "Προσάρμοσε το κείμενο ώστε μια νευρωνική φωνή εκφώνησης (όπως Nestoras/Athina στο Edge-TTS) να το απαγγείλει με άψογη, ανθρώπινη ροή, φυσικές ανάσες και σωστή προφορά: "
        "1. ΦΩΝΗΤΙΚΗ ΑΠΟΔΟΣΗ ΞΕΝΩΝ ΟΝΟΜΑΤΩΝ & ΟΡΩΝ: "
        "   - Μετέγραψε όλα τα ξένα κύρια ονόματα, πρόσωπα, τοπωνύμια, σκάφη και έννοιες σε ελληνικούς χαρακτήρες με βάση τη φυσική φωνητική προφορά τους (π.χ. Keeton -> Κίτον, Rorschach -> Ρόρσαχ, Sarasti -> Σαράστι, Cunningham -> Κάνινγχαμ, Theseus -> Θησέας, Siri -> Σίρι). "
        "   - Μετέγραψε λατινικά ακρωνύμια όπως προφέρονται στα ελληνικά (π.χ. DNA -> Ντι-Εν-Έι, AI -> Έι-Άι, NASA -> ΝΑΣΑ, GPS -> Τζι-Πι-Ες, PC -> Πι-Σι). "
        "2. ΠΛΗΡΗΣ ΟΛΟΓΡΑΦΗ ΑΝΑΠΤΥΞΗ ΑΡΙΘΜΩΝ ΚΑΙ ΣΥΝΤΟΜΟΓΡΑΦΙΩΝ: "
        "   - Ανέπτυξε όλους τους αριθμούς, έτη, ημερομηνίες, ποσοστά, μονάδες μέτρησης και νομίσματα σε πλήρεις λέξεις ανάλογα με τη γραμματική πτώση (π.χ. 'το 2006' -> 'το δύο χιλιάδες έξι', '50%' -> 'πενήντα τοις εκατό', '$100' -> 'εκατό δολάρια', '10 χλμ.' -> 'δέκα χιλιόμετρα'). "
        "   - Ανέπτυξε συντομογραφίες σε πλήρεις προφορικές φράσεις (π.χ. 'π.χ.' -> 'για παράδειγμα', 'δηλ.' -> 'δηλαδή', 'κ.λπ.' -> 'και λοιπά', 'αρ.' -> 'αριθμός', 'σελ.' -> 'σελίδα'). "
        "3. ΑΦΑΙΡΕΣΗ ΜΗ ΕΚΦΩΝΗΣΙΜΩΝ ΣΤΟΙΧΕΙΩΝ: "
        "   - Αφαίρεσε πλήρως δείκτες υποσημειώσεων (π.χ. [1], [14]), δείκτες σελίδων (=== PAGE X ===), συνδέσμους URLs, επικεφαλίδες σελίδων και περιττά τυπογραφικά σύμβολα. "
        "   - Αφαίρεσε τα ενωτικά σπασίματος λέξεων στο τέλος γραμμής. "
        "4. ΡΥΘΜΟΣ, ΑΝΑΣΕΣ ΚΑΙ ΣΤΙΞΗ ΑΠΑΓΓΕΛΙΑΣ: "
        "   - Αντικατάστησε αμήχανες παρενθέσεις, πλαγιοκαθέτους (/) και περίπλοκες δευτερεύουσες προτάσεις με κόμματα ή τελείες ώστε ο αφηγητής να παίρνει φυσικές ανάσες. "
        "   - Διατήρησε τις αλλαγές παραγράφων για να δημιουργούνται αυτόματα φυσικές παύσεις. "
        "   - Εάν το κείμενο εισόδου είναι στα Αγγλικά, εφάρμοσε τους αντίστοιχους αγγλικούς κανόνες ολογραφίας και ροής χωρίς να μεταφράσεις. Εάν είναι στα Ελληνικά, διατήρησε τα Ελληνικά. "
        "5. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το έτοιμο κείμενο εκφώνησης, χωρίς κανένα εισαγωγικό ή επεξηγηματικό σχόλιο."
    ),
    "poetry": (
        "Είσαι κορυφαίος φιλόλογος και επιμελητής ποιητικών και θεατρικών κειμένων για ηχογράφηση και θεατρική απαγγελία (Poetry & Spoken Word Recitation). "
        "Προσάρμοσε το ποιητικό κείμενο για νευρωνική απαγγελία (Edge-TTS) βελτιστοποιώντας την προσωδία, τη μουσικότητα και τον ρυθμό του ποιήματος: "
        "1. ΑΥΣΤΗΡΗ ΔΙΑΤΗΡΗΣΗ ΣΤΙΧΩΝ ΚΑΙ ΣΤΡΟΦΩΝ: "
        "   - Διατήρησε κάθε στίχο σε ξεχωριστή γραμμή και τα κενά διαστήματα μεταξύ των στροφών. ΜΗΝ ενώνεις ποτέ τους στίχους σε πεζές παραγράφους. "
        "2. ΠΡΟΣΩΔΙΑ, ΕΚΘΛΙΨΕΙΣ ΚΑΙ ΦΩΝΗΤΙΚΗ ΣΥΝΟΧΗ: "
        "   - Εξομάλυνε τις ποιητικές εκθλίψεις και αποκοπές ώστε να προφέρονται ως ενιαίες μουσικές λέξεις χωρίς αμήχανες παύσεις (π.χ. 'να ’ναι' -> 'να 'ναι' ή 'νάναι', 'σ’ εμπορεία' -> 'σ' εμπορεία', 'τ’ ωραίο' -> 'τ' ωραίο', 'δεν θα ’βγαινες' -> 'δεν θα 'βγαινες'). "
        "   - Μετέτρεψε την άνω τελεία (·) σε κόμμα (,) ώστε να εκφωνείται φυσική ενδιάμεση ανάσα χωρίς παράσιτα ή κομπιάσματα. "
        "3. ΣΕΒΑΣΜΟΣ ΣΤΟΝ ΔΙΑΣΚΕΛΙΣΜΟ & ΤΗ ΣΤΙΞΗ: "
        "   - ΜΗΝ προσθέτεις αυθαίρετα κόμματα στο τέλος στίχων όταν ο ποιητής δεν έχει βάλει στίξη (διασκελισμός). Ο στίχος πρέπει να ρέει ομαλά στον επόμενο χωρίς τεχνητές παύσεις. "
        "4. ΟΛΟΓΡΑΦΗ ΑΝΑΠΤΥΞΗ & ΦΩΝΗΤΙΚΗ ΚΑΘΑΡΟΤΗΤΑ: "
        "   - Ανέπτυξε τυχόν συντομογραφίες, έτη ή αριθμούς ολογράφως σε πλήρεις λέξεις ανάλογα με τη γραμματική πτώση. "
        "   - Αφαίρεσε αριθμούς υποσημειώσεων, τίτλους σελίδων και περιττά τυπογραφικά σύμβολα. "
        "5. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το καθαρό ποιητικό κείμενο για απαγγελία, χωρίς κανένα εισαγωγικό ή επεξηγηματικό σχόλιο."
    ),
}

STYLE_TEMPERATURES = {
    "literature": 0.35,
    "natural": 0.25,
    "audiobook": 0.25,
    "poetry": 0.25,
    "formal": 0.15,
    "technical": 0.15,
}

# Cached discoveries to avoid querying Google ModelService on every single page
_CACHED_WORKING_MODEL: Optional[str] = None
_CACHED_AVAILABLE_MODELS: Optional[list[str]] = None
_CACHED_API_KEY_HASH: Optional[str] = None
_CHECKPOINT_LOCK = threading.RLock()

POLISH_STATUS: dict[str, dict[str, Any]] = {}


def get_polish_job_status(job_id: str) -> dict[str, Any]:
    """Returns the current real-time progress dict of an AI Polish job."""
    return POLISH_STATUS.get(
        job_id,
        {"current": 0, "total": 1, "percent": 0, "status": "idle", "step": ""},
    )


def update_polish_job_status(job_id: str, **kwargs: Any) -> dict[str, Any]:
    """Updates real-time status of an AI Polish job."""
    st = POLISH_STATUS.setdefault(
        job_id,
        {"current": 0, "total": 1, "percent": 0, "status": "idle", "step": ""},
    )
    st.update(kwargs)
    return st


def reset_model_cache():
    """Invalidate cached Gemini model discovery list (e.g. when API key changes)."""
    global _CACHED_WORKING_MODEL, _CACHED_AVAILABLE_MODELS
    _CACHED_WORKING_MODEL = None
    _CACHED_AVAILABLE_MODELS = None
    reset_gemini_quota_exhaustion()


EXCLUDE_PATTERNS = [
    "-tts", "-image", "-audio", "-transcribe", "clip", "banana",
    "robotics", "customtools", "computer-use", "argon",
    "lyria", "deep-research", "antigravity", "veo", "imagen", "embedding",
]

PREFERRED_FLASH_MODELS = [
    # Full Flash models FIRST: dramatically higher Greek accuracy & zero multilingual subword bleed
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-2.0-flash",
    "gemini-pro-latest",
    # Flash-Lite models as secondary fallback only
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
]

# Permissive safety settings for literary/sci-fi/historical translation so fictional violence,
# mature prose, profanity, or body horror does not trigger spurious SAFETY/PROHIBITED_CONTENT refusals.
_LITERARY_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

_TRANSIENT_RETRY_DELAY = 2.0


class DailyQuotaExhaustedError(RuntimeError):
    """Raised when Gemini returns 429 quota exhaustion or requests per day limit exceeded."""


_GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL: float = 0.0


def is_gemini_quota_exhausted() -> bool:
    """Returns True if Gemini daily quota was tripped and is currently in cooldown."""
    global _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL
    now = time.time()
    if now < _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL:
        return True

    try:
        from backend.gemini_key_pool import GeminiKeyPool
        # If pool has keys configured and all are exhausted
        if GeminiKeyPool.get_keys() and not GeminiKeyPool.get_active_key():
            return True
    except Exception:
        pass

    try:
        from backend.settings_manager import get_setting
        persisted = float(get_setting("gemini_quota_exhausted_until", 0.0) or 0.0)
        _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL = persisted
        if now < persisted:
            return True
    except Exception:
        if now < _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL:
            return True
    return False


def trip_gemini_quota_exhaustion(cooldown_seconds: float = 3600.0) -> None:
    """Trip Gemini daily quota circuit breaker to fail-fast across all modules and processes."""
    global _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL
    target = time.time() + cooldown_seconds
    _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL = max(_GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL, target)
    try:
        from backend.settings_manager import save_setting
        save_setting("gemini_quota_exhausted_until", _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL)
    except Exception:
        pass


def reset_gemini_quota_exhaustion() -> None:
    """Reset the circuit breaker (e.g. if the user enters a new API key)."""
    global _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL
    _GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL = 0.0
    try:
        from backend.settings_manager import delete_setting
        delete_setting("gemini_quota_exhausted_until")
    except Exception:
        pass


def get_gemini_quota_info() -> dict[str, Any]:
    """Returns a dict with quota status, remaining seconds, exact reset clock time, and user-facing message."""
    pool_status: dict[str, Any] = {}
    try:
        from backend.gemini_key_pool import GeminiKeyPool
        pool_status = GeminiKeyPool.get_pool_status()
    except Exception:
        pass

    exhausted = is_gemini_quota_exhausted()
    if not exhausted:
        return {
            "exhausted": False,
            "remaining_seconds": 0,
            "reset_timestamp": 0.0,
            "reset_time_str": "",
            "cooldown_time_str": "",
            "message": None,
            "pool": pool_status,
        }

    now = time.time()
    earliest = pool_status.get("earliest_reset_timestamp", 0.0) if pool_status else 0.0
    reset_ts = earliest if earliest > now else max(_GEMINI_DAILY_QUOTA_EXHAUSTED_UNTIL, now + 1.0)
    rem_sec = int(max(1.0, reset_ts - now))

    import datetime
    reset_dt = datetime.datetime.fromtimestamp(reset_ts)
    reset_time_str = reset_dt.strftime("%H:%M:%S")
    rem_min = rem_sec // 60
    if rem_min > 60:
        time_str = f"{rem_min // 60}ώ {rem_min % 60}λ"
    elif rem_min >= 1:
        time_str = f"{rem_min}λ {rem_sec % 60}δ"
    else:
        time_str = f"{rem_sec}δ"

    msg = (
        f"Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Google Free Tier 15 RPM / 1500 RPD). "
        f"Έτοιμο ξανά στις {reset_time_str} (απομένουν ~{time_str}). "
        f"Μπορείτε να αλλάξετε API Key στις Ρυθμίσεις (Settings) για άμεση συνέχιση."
    )
    return {
        "exhausted": True,
        "remaining_seconds": rem_sec,
        "reset_timestamp": reset_ts,
        "reset_time_str": reset_time_str,
        "cooldown_time_str": time_str,
        "message": msg,
        "pool": pool_status,
    }


class _TruncatedOutputError(RuntimeError):
    """Raised when Gemini finishes with MAX_TOKENS so the caller can split the batch and retry."""


class _ContentBlockedError(RuntimeError):
    """Raised when Gemini returns an empty/blocked response (SAFETY, PROHIBITED_CONTENT, RECITATION)."""


_HTML_INLINE_TAG_RE = re.compile(
    r"</?(?:i|b|em|strong|u|s|span|p|br|div|font|sup|sub|small|big|mark|del|ins|a|h[1-6])\b[^>]*>",
    re.IGNORECASE,
)
_LLM_SPECIAL_TOKEN_RE = re.compile(
    r"<(?:/?(?:bos|eos|pad|unk|sep|cls|mask|start_of_turn|end_of_turn|thought|think)|\|[^|\n]{1,32}\|)>",
    re.IGNORECASE,
)
_LEAKED_PREV_CTX_BLOCK_RE = re.compile(
    r"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>.*?</PREVIOUS_CONTEXT_DO_NOT_REPEAT>",
    re.IGNORECASE | re.DOTALL,
)
_LEAKED_WRAPPER_TAG_RE = re.compile(
    r"</?(?:PREVIOUS_CONTEXT_DO_NOT_REPEAT|TEXT_TO_POLISH|DRAFT_TO_POLISH|SOURCE_REFERENCE|TEXT_TO_TRANSLATE)>",
    re.IGNORECASE,
)
_LEAKED_ELLIPSIS_BRACKET_RE = re.compile(
    r"(?:^|\n)\s*\[\.\.\.\s*[^\]]{8,600}\]\s*(?=\n|$)",
    re.DOTALL,
)
_EDITOR_NOTE_RE = re.compile(
    r"\[(?:Σημείωση\s+(?:επιμελητή|μεταφραστή|εκδότη)|Editor'?s?\s+note|Translator'?s?\s+note|Note)\s*:[^\]]*\]",
    re.IGNORECASE,
)
_COT_BLOCK_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\*\s*\*?(?:Refining|Drafting|Thinking|Analysis|Checking|Review|Verification)\s*:.*|"
    r"\d+\.\s*\*\*(?:Review|Final\s+Polish|Analyze|Translate|Check|Draft)[^*]*\*\*.*|"
    r"\*\*(?:Review\s+against|Final\s+Polish|Self-Check|Verification)\b.*|"
    r"\*\s*(?:No\s+introductory\s+notes|Page\s+markers|Glossary|Entity\s+Dossier|Tone|Style)[^?]*\?\s*Checked\.?.*|"
    r"Proceed\s+to\s+output\s+(?:pure\s+)?translated\s+text\.?.*"
    r")$",
    re.IGNORECASE,
)
_LEAKED_PROMPT_HEADER_RE = re.compile(
    r"^---\s*(?:ΠΡΟΗΓΟΥΜΕΝΟ\s+ΑΠΟΣΠΑΣΜΑ|ΠΡΩΤΟΤΥΠΟ\s+ΚΕΙΜΕΝΟ\s+ΑΝΑΦΟΡΑΣ|ΠΡΟΣΧΕΔΙΟ\s+ΕΛΛΗΝΙΚΗΣ\s+ΜΕΤΑΦΡΑΣΗΣ|ΚΕΙΜΕΝΟ\s+ΠΡΟΣ\s+ΕΠΙΜΕΛΕΙΑ)[^\n]*---\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Exotic scripts that should NEVER appear inside translated Greek prose unless present in source
_EXOTIC_SCRIPT_RE = re.compile(
    r"[\u0400-\u04ff\u0530-\u058f\u0590-\u05ff\u0600-\u06ff\u0900-\u0e7f\u2e80-\u9fff\uac00-\ud7af\ufffd]"
)
_GREEK_CHAR_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")
_SCI_UNIT_RE = re.compile(r"^[μµΔΩαβγλσπρ][A-Za-z]{1,2}\d*$")


def _extract_gemini_text_and_reason(result: dict) -> tuple[str, str]:
    """
    Extracts non-thought text and finishReason from a Gemini generateContent JSON payload.
    Strictly ignores Gemini 2.5/3.x 'thought: true' reasoning parts so chain-of-thought never leaks.
    """
    if not isinstance(result, dict):
        return "", ""
    prompt_fb = result.get("promptFeedback")
    block_reason = str(prompt_fb.get("blockReason") or "") if isinstance(prompt_fb, dict) else ""
    cand_list = result.get("candidates") or []
    if not cand_list or not isinstance(cand_list, list):
        return "", block_reason
    cand = cand_list[0] if isinstance(cand_list[0], dict) else {}
    finish_reason = str(cand.get("finishReason") or block_reason or "")
    parts = (cand.get("content") or {}).get("parts") or []
    text_parts = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        if p.get("thought") is True:
            continue
        t = p.get("text")
        if isinstance(t, str) and t:
            text_parts.append(t)
    return "".join(text_parts).strip(), finish_reason


def sanitize_ai_output(text: str) -> str:
    """
    Defensively removes LLM artifacts from generated/polished text:
    - HTML/XML inline tags ('εισπ</i>νευστική' -> 'εισπνευστική')
    - Special LLM tokens ('<bos>', '<eos>', '<|endoftext|>')
    - Echoed <PREVIOUS_CONTEXT_DO_NOT_REPEAT> blocks, wrapper XML tags, and '[... ...]' context echoes
    - Bracketed editor/translator meta-notes ('[Σημείωση επιμελητή: ...]')
    - Leaked chain-of-thought / self-review lines ('**Review against Rules...**', 'Proceed to output...')
    - Markdown code fences wrapping prose
    - Broken hyphenated Greek words ('υποσχέ- θηκαν' -> 'υποσχέθηκαν')
    """
    if not text:
        return text

    cleaned = text.strip()
    # Strip outer markdown code fence if the model wrapped the whole output
    cleaned = re.sub(r"^```(?:markdown|text|el|greek)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    # Strip echoed read-only previous context blocks, wrapper tags, and leaked '[... ...]' snippets
    cleaned = _LEAKED_PREV_CTX_BLOCK_RE.sub("", cleaned)
    cleaned = _LEAKED_WRAPPER_TAG_RE.sub("", cleaned)
    cleaned = _LEAKED_ELLIPSIS_BRACKET_RE.sub("\n", cleaned)

    # Strip LLM special tokens and leaked inline HTML tags
    cleaned = _LLM_SPECIAL_TOKEN_RE.sub("", cleaned)
    cleaned = _HTML_INLINE_TAG_RE.sub("", cleaned)
    cleaned = _EDITOR_NOTE_RE.sub("", cleaned)
    cleaned = _LEAKED_PROMPT_HEADER_RE.sub("", cleaned)

    # Remove Chain-of-Thought / self-review blocks (from first leaked review heading to end or per-line)
    out_lines: list[str] = []
    in_cot_tail = False
    for ln in cleaned.splitlines():
        if re.search(r"\*\*Review\s+against\s+Rules|\*\*Final\s+Polish\s*:\*\*|Proceed\s+to\s+output\s+(?:pure\s+)?translated\s+text", ln, re.IGNORECASE):
            in_cot_tail = True
            continue
        if in_cot_tail:
            # Stop skipping once a real page marker (1-line or 3-line translator format) resumes
            if re.match(r"^\s*={3,}\s*PAGE\s+\d+\s*={3,}\s*$", ln) or re.match(r"^\s*PAGE\s+\d+\s*$", ln) or re.match(r"^\s*={6,}\s*$", ln):
                in_cot_tail = False
                out_lines.append(ln)
            continue
        if _COT_BLOCK_LINE_RE.match(ln):
            continue
        out_lines.append(ln)
    cleaned = "\n".join(out_lines)

    # Collapse spaces left behind by removed editor notes (without breaking paragraph newlines)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    try:
        from backend.typography import fix_broken_hyphens
        cleaned = fix_broken_hyphens(cleaned)
    except Exception:
        pass

    return cleaned.strip()


def _find_mixed_script_tokens(text: str, source_text: str = "") -> list[str]:
    """Returns distinct tokens containing mixed Greek+Latin/exotic characters or stray exotic scripts."""
    if not text:
        return []
    src_has_exotic = bool(_EXOTIC_SCRIPT_RE.search(source_text or ""))
    bad_tokens: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"[^\s,;.:!?«»\"'()\[\]—–\-/\\*<>]+", text):
        tok = m.group(0)
        if _SCI_UNIT_RE.match(tok):
            continue
        has_gr = bool(_GREEK_CHAR_RE.search(tok))
        has_lat = bool(_LATIN_LETTER_RE.search(tok))
        has_ex = bool(_EXOTIC_SCRIPT_RE.search(tok))
        if (has_gr and (has_lat or has_ex)) or (has_ex and not src_has_exotic):
            if tok not in seen:
                seen.add(tok)
                bad_tokens.append(tok)
    return bad_tokens


def detect_greek_output_issues(
    text: str,
    source_text: str = "",
    expected_pages: Optional[list[int]] = None,
) -> list[str]:
    """
    Quality gate for Greek AI-translated/polished batches.
    Returns a list of issue codes (empty list means clean):
    - 'mixed_script': Greek words corrupted with Latin/Cyrillic/Hebrew/Arabic/Armenian/Bengali/CJK chars
    - 'cot_leak': leftover English reasoning / review chatter
    - 'missing_pages': expected '=== PAGE X ===' markers dropped
    - 'truncated': output severely shorter than source or cut off mid-word
    """
    issues: list[str] = []
    if not text or not text.strip():
        return ["empty"]

    # 1. Mixed-script / exotic-script corruption check (classic Flash-Lite failure mode)
    # Exempt standard SI / scientific units combining a Greek prefix with Latin unit letters (e.g. μm, μg, Δt, Ωm)
    src_has_exotic = bool(_EXOTIC_SCRIPT_RE.search(source_text or ""))
    mixed_count = 0
    exotic_count = 0
    for m in re.finditer(r"[^\s,;.:!?«»\"'()\[\]—–\-/\\*<>]+", text):
        tok = m.group(0)
        if _SCI_UNIT_RE.match(tok):
            continue
        has_gr = bool(_GREEK_CHAR_RE.search(tok))
        has_lat = bool(_LATIN_LETTER_RE.search(tok))
        has_ex = bool(_EXOTIC_SCRIPT_RE.search(tok))
        if has_gr and (has_lat or has_ex):
            mixed_count += 1
        elif has_ex and not src_has_exotic:
            exotic_count += 1
    if mixed_count >= 1 or exotic_count >= 1:
        issues.append(f"mixed_script({mixed_count}+{exotic_count})")

    # 2. Residual CoT / English meta-commentary check
    if re.search(
        r"Proceed\s+to\s+output\s+(?:pure\s+)?translated\s+text|Review\s+against\s+Rules\s+and\s+Dossier|No\s+introductory\s+notes\s+or\s+chatter\?",
        text,
        re.IGNORECASE,
    ):
        issues.append("cot_leak")

    # 3. Missing page markers check
    if expected_pages and len(expected_pages) >= 2:
        found_pages = {int(x) for x in re.findall(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text)}
        missing = [p for p in expected_pages if p not in found_pages]
        if missing:
            issues.append(f"missing_pages({missing})")

    # 4. Truncation check (severe length drop or mid-word cutoff)
    clean_src = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", source_text or "").strip()
    clean_out = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", text).strip()
    if len(clean_src) >= 400:
        ratio = len(clean_out) / max(1, len(clean_src))
        if ratio < 0.48:
            issues.append(f"truncated(ratio={ratio:.2f})")
        elif (
            ratio < 0.85
            and clean_src[-1] in '.!?»"”…):;'
            and clean_out
            and clean_out[-1] not in '.!?»"”…):;—-*'
            and bool(_GREEK_CHAR_RE.search(clean_out[-1]))
        ):
            issues.append(f"truncated_midword(ratio={ratio:.2f})")

    return issues


def _extract_clean_tail_context(text: str, max_chars: int = 240) -> str:
    """
    Extracts the last 1-2 complete sentences from the end of a preceding page/chunk
    without ever slicing mid-word or mid-sentence.
    """
    if not text:
        return ""
    stripped = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", text).strip()
    paras = [p.strip() for p in stripped.split("\n\n") if p.strip()]
    if not paras:
        return ""
    last_para = paras[-1]
    if len(last_para) <= max_chars:
        return last_para
    sentences = [
        s.strip()
        for s in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", last_para)
        if s.strip()
    ]
    if len(sentences) >= 2:
        tail = sentences[-1]
        if len(sentences[-2]) + 1 + len(tail) <= max_chars:
            tail = f"{sentences[-2]} {tail}"
        if len(tail) <= max_chars + 80:
            return tail
    # Fallback: take trailing words up to max_chars on a clean word boundary
    words = last_para.split()
    acc: list[str] = []
    acc_len = 0
    for w in reversed(words):
        if acc and acc_len + len(w) + 1 > max_chars:
            break
        acc.append(w)
        acc_len += len(w) + 1
    return " ".join(reversed(acc))


def _norm_dedup_text(s: str) -> str:
    """Normalizes prose for fuzzy boundary-duplication comparison."""
    s = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", s or "")
    s = re.sub(r"[^\w\sΆ-ώ\u0370-\u03ff\u1f00-\u1fff]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _is_near_duplicate_segment(seg_a: str, seg_b: str) -> bool:
    """Returns True if two substantial prose segments (>= 35 chars, >= 6 words) are duplicates or close paraphrases."""
    na = _norm_dedup_text(seg_a)
    nb = _norm_dedup_text(seg_b)
    if len(na) < 35 or len(nb) < 35:
        return False
    wa = na.split()
    wb = nb.split()
    if len(wa) < 6 or len(wb) < 6:
        return False
    if na == nb or na in nb or nb in na:
        return True
    len_ratio = len(na) / max(1, len(nb))
    if not (0.50 <= len_ratio <= 2.0):
        return False
    if SequenceMatcher(None, na, nb).ratio() >= 0.72:
        return True
    set_a, set_b = set(wa), set(wb)
    overlap = len(set_a & set_b) / max(1, min(len(set_a), len(set_b)))
    if overlap >= 0.78:
        return True
    return False


def _deduplicate_batch_boundary(
    prev_text: str,
    curr_text: str,
    expected_first_page: Optional[int] = None,
) -> str:
    """
    Eliminates chunk/batch boundary duplications deterministically:
    1. For paginated batches, strips any leaked preamble or echoed previous-batch context
       emitted BEFORE the first expected '=== PAGE K ===' marker.
    2. Strips up to 3 leading paragraphs (or a duplicated leading sentence) of curr_text
       when they duplicate or closely paraphrase the trailing paragraphs/sentences of prev_text.
    """
    if not curr_text or not curr_text.strip():
        return curr_text or ""

    res = curr_text.strip()

    # 1. Strip anything leaked before the first expected === PAGE K === marker
    leading_marker = ""
    if expected_first_page is not None:
        m = re.search(rf"={{3,}}\s*PAGE\s+{expected_first_page}\s*={{3,}}", res)
        if m:
            if m.start() > 0:
                leaked_prefix = res[:m.start()].strip()
                if leaked_prefix:
                    logger.info(
                        f"Stripped {len(leaked_prefix)} chars of pre-marker boundary leak before === PAGE {expected_first_page} ==="
                    )
                res = res[m.start():].lstrip()
            leading_marker = m.group(0)
            body = res[len(leading_marker):].lstrip()
        else:
            body = res
    else:
        # Check if curr_text starts with a generic page marker
        m_any = re.match(r"^(={3,}\s*PAGE\s+\d+\s*={3,})\s*", res)
        if m_any:
            leading_marker = m_any.group(1)
            body = res[m_any.end():].lstrip()
        else:
            body = res

    if not prev_text or not prev_text.strip() or not body:
        return f"{leading_marker}\n\n{body}".strip() if leading_marker else body

    prev_clean = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "", prev_text).strip()
    prev_paras = [p.strip() for p in prev_clean.split("\n\n") if p.strip()]
    prev_tail_paras = prev_paras[-3:]
    prev_tail_joined = " ".join(prev_tail_paras)

    curr_paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    dropped = 0
    while curr_paras and dropped < 3:
        first_p = curr_paras[0]
        # Never strip a page marker or scene break
        if re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", first_p) or first_p in ("* * *", "---"):
            break
        is_dup = any(_is_near_duplicate_segment(first_p, pp) for pp in prev_tail_paras)
        if not is_dup and len(_norm_dedup_text(first_p)) >= 40:
            # Also catch when Gemini merged/split the echoed tail across two paragraphs
            norm_first = _norm_dedup_text(first_p)
            norm_prev_tail = _norm_dedup_text(prev_tail_joined)
            if norm_first in norm_prev_tail:
                is_dup = True
        if is_dup:
            logger.info(f"Deduplicated repeated boundary paragraph ({len(first_p)} chars)")
            curr_paras.pop(0)
            dropped += 1
        else:
            break

    # Check if the first sentence of the first remaining paragraph duplicates the last sentence of prev_text
    if curr_paras and prev_tail_paras:
        first_p = curr_paras[0]
        if not re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", first_p):
            prev_sents = [
                s.strip()
                for s in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", prev_tail_paras[-1])
                if s.strip()
            ]
            curr_sents = [
                s.strip()
                for s in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", first_p)
                if s.strip()
            ]
            if prev_sents and len(curr_sents) >= 2 and _is_near_duplicate_segment(curr_sents[0], prev_sents[-1]):
                logger.info(f"Deduplicated repeated boundary leading sentence ({len(curr_sents[0])} chars)")
                curr_paras[0] = " ".join(curr_sents[1:]).strip()

    dedup_body = "\n\n".join(p for p in curr_paras if p).strip()
    if leading_marker:
        return f"{leading_marker}\n\n{dedup_body}".strip() if dedup_body else leading_marker
    return dedup_body


def _split_text_in_half_by_paragraphs(text: str) -> Optional[tuple[str, str]]:
    """
    Splits a single page/chunk cleanly into two balanced halves along paragraph (\n\n)
    or sentence boundaries for recursive safety/truncation recovery.
    Returns None if the text cannot be meaningfully split further.
    """
    s = (text or "").strip()
    if len(s) < 80:
        return None
    paras = [p.strip() for p in s.split("\n\n") if p.strip()]
    if len(paras) >= 2:
        total_len = sum(len(p) for p in paras)
        acc = 0
        split_idx = 1
        for i, p in enumerate(paras[:-1], 1):
            acc += len(p)
            split_idx = i
            if acc >= total_len / 2:
                break
        left = "\n\n".join(paras[:split_idx]).strip()
        right = "\n\n".join(paras[split_idx:]).strip()
        if left and right:
            return left, right
    # Single large paragraph: split on sentence boundary
    sents = [
        x.strip()
        for x in re.split(r"(?:(?<=[.!?;…\u037e])|(?<=[.!?;…\u037e][»\"”\'\)\]]))\s+", s)
        if x.strip()
    ]
    if len(sents) >= 2:
        mid = len(sents) // 2
        left = " ".join(sents[:mid]).strip()
        right = " ".join(sents[mid:]).strip()
        if left and right:
            return left, right
    return None


_COMMON_CAP_STOPWORDS = frozenset({
    "The", "This", "That", "These", "Those", "There", "Their", "They", "Then", "Than",
    "When", "Where", "What", "Which", "While", "Who", "Whom", "Whose", "Why", "How",
    "With", "Without", "Within", "From", "Into", "Onto", "Over", "Under", "After", "Before",
    "About", "Above", "Across", "Against", "Along", "Among", "Around", "Because", "Between",
    "Could", "Would", "Should", "Might", "Must", "Have", "Just", "Like", "Only", "Some",
    "Even", "Ever", "Every", "More", "Most", "Much", "Many", "Other", "Such", "Still",
    "Here", "Once", "Well", "Back", "Down", "Away", "Again", "Never", "Always", "Maybe",
    "Nothing", "Something", "Anything", "Everything", "Someone", "Anyone", "Everyone",
    "Chapter", "Part", "Book", "Page", "PAGE", "Prologue", "Epilogue", "Notes", "References",
    "Αλλά", "Όμως", "Ενώ", "Όταν", "Γιατί", "Αυτό", "Αυτή", "Αυτός", "Αυτά", "Αυτοί",
    "Εκεί", "Εδώ", "Μετά", "Πριν", "Πάνω", "Κάτω", "Μόνο", "Τώρα", "Τότε", "Ίσως",
    "Κάθε", "Όλα", "Όλοι", "Όλες", "Ποτέ", "Πάντα", "Κάτι", "Τίποτα", "Καθώς", "Όπως",
    "Επειδή", "Μέσα", "Έξω", "Πέρα", "Χωρίς", "Κεφάλαιο", "Μέρος", "Σελίδα",
})


def _build_stratified_book_sample(text: str, max_total_chars: int = 32000) -> str:
    """
    Builds a representative whole-book sample for Entity Dossier extraction by:
    1. Scanning the ENTIRE book for recurring capitalized names / multi-word proper nouns
       (catching characters, ships, drones, species introduced mid- or late-book).
    2. Taking up to 9 evenly spaced narrative slices spanning 0%..95% of the full text
       aligned on paragraph/newline boundaries.
    """
    if not text:
        return ""
    if len(text) <= max_total_chars:
        return text

    # 1. Fast whole-book recurring capitalized proper-noun scan
    cleaned_for_scan = re.sub(r"={3,}\s*PAGE\s+\d+\s*={3,}", "\n", text)
    # Capture 1-3 word capitalized phrases (Latin or Greek)
    raw_terms = re.findall(
        r"\b(?:[A-Z][a-zA-Z'\-]{2,}(?:\s+[A-Z][a-zA-Z'\-]{2,}){0,2}|[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]{2,}(?:\s+[Α-ΩΆΈΉΊΌΎΏ][α-ωάέήίόύώϊϋΐΰ]{2,}){0,2})\b",
        cleaned_for_scan,
    )
    counts: Counter = Counter()
    for term in raw_terms:
        if term in _COMMON_CAP_STOPWORDS:
            continue
        parts = term.split()
        if all(p in _COMMON_CAP_STOPWORDS for p in parts):
            continue
        if len(parts) > 1 and parts[0] in _COMMON_CAP_STOPWORDS:
            term = " ".join(parts[1:])
            if not term or term in _COMMON_CAP_STOPWORDS:
                continue
        counts[term] += 1

    top_entities = [f"{term} ({cnt}x)" for term, cnt in counts.most_common(75) if cnt >= 3]
    freq_header = ""
    if top_entities:
        freq_header = (
            "--- ΕΠΑΝΑΛΑΜΒΑΝΟΜΕΝΑ ΟΝΟΜΑΤΑ & ΟΡΟΙ ΣΕ ΟΛΟ ΤΟ ΒΙΒΛΙΟ (FREQUENCY SCAN) ---\n"
            + ", ".join(top_entities)
            + "\n\n"
        )

    # 2. Stratified excerpts across 0%..95% of the book
    num_slices = 9
    budget = max(8000, max_total_chars - len(freq_header))
    slice_len = budget // num_slices
    n = len(text)
    excerpts: list[str] = []
    for i in range(num_slices):
        frac = i / max(1, num_slices - 1) * 0.92
        start = int(n * frac)
        if start > 0:
            nl = text.find("\n", start, min(n, start + 400))
            if nl != -1:
                start = nl + 1
        end = min(n, start + slice_len)
        if end < n:
            nl_end = text.rfind("\n", start + slice_len // 2, end)
            if nl_end != -1:
                end = nl_end
        chunk = text[start:end].strip()
        if chunk:
            pct = int(round(frac * 100))
            excerpts.append(f"--- ΔΕΙΓΜΑ ΒΙΒΛΙΟΥ ({pct}%) ---\n{chunk}")

    return freq_header + "\n\n".join(excerpts)


def _parse_pages_dict(text: str) -> dict[int, str]:
    """Parses text containing '=== PAGE X ===' into a {page_num: text} mapping."""
    page_dict: dict[int, str] = {}
    if not text:
        return page_dict
    parts = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    curr_page = 0
    for part in parts:
        p_strip = part.strip()
        if not p_strip:
            continue
        m = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", p_strip)
        if m:
            curr_page = int(m.group(1))
        elif curr_page > 0:
            page_dict[curr_page] = p_strip
    return page_dict


async def _extract_entity_dossier(
    sample_text: str,
    api_key: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    """
    Extracts a comprehensive whole-book glossary of recurring characters, places, ships,
    species, drones, and sci-fi/technical terms using stratified sampling across the entire
    document so entities introduced mid-book maintain uniform transliteration and grammatical gender.
    """
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        return "- Keeton -> Κίτον (αρσενικό: ο Κίτον)\n- Theseus -> Θησέας (αρσενικό: ο Θησέας)\n- Rorschach -> Ρόρσαχ (ουδέτερο: το Ρόρσαχ)"

    prompt = (
        "Είσαι έμπειρος επιμελητής εκδόσεων και λογοτεχνικός μεταφραστής. Αναλύοντας τη λίστα συχνών ονομάτων και τα "
        "δείγματα από ΟΛΟΚΛΗΡΟ το βιβλίο παρακάτω, δημιούργησε ένα πλήρες Μητρώο Ονομάτων & Ορολογίας (Entity Dossier) "
        "με την ορθή, ΑΠΟΛΥΤΩΣ ΕΝΙΑΙΑ απόδοσή τους στα Ελληνικά. "
        "ΚΡΙΣΙΜΟΙ ΚΑΝΟΝΕΣ: "
        "1) Για ΚΑΘΕ χαρακτήρα, σκάφος, είδος ή οντότητα σημείωσε ρητά το ορθό γραμματικό γένος "
        "(π.χ. αρσενικό: ο ..., θηλυκό: η ..., ουδέτερο: το ...) ώστε να ΜΗΝ αλλάζει ποτέ στην πορεία του βιβλίου. "
        "2) ΜΗΝ συγχέεις ποτέ διαφορετικούς χαρακτήρες, εξωγήινα είδη, drones/εργαλεία ή ονοματεπώνυμα μεταξύ τους — "
        "κάθε διακριτή έννοια πρέπει να έχει τη δική της μοναδική, ακριβή ελληνική απόδοση (π.χ. διαφορετικός όρος για drones vs εξωγήινους). "
        "3) Περιέλαβε κύρια ονόματα χαρακτήρων (με πλήρες ονοματεπώνυμο όπου υπάρχει), σκάφη, τοπωνύμια, "
        "δίκτυα/τεχνολογικούς όρους, drones/εξοπλισμό και επαναλαμβανόμενους όρους επιστημονικής φαντασίας από όλο το βιβλίο. "
        "Μορφή κάθε γραμμής: '- Original Name -> Ελληνική Απόδοση (γένος/ρόλος, π.χ. αρσενικό: ο ..., drone, εξωγήινο είδος)'. "
        "Περιόρισε το μητρώο στους 35-60 πιο κρίσιμους όρους. Μην προσθέτεις εισαγωγικά σχόλια."
    )
    try:
        sample = _build_stratified_book_sample(sample_text, max_total_chars=32000)
        dossier = await _call_gemini_api(sample, api_key, prompt, session=session)
        if dossier and len(dossier.strip()) > 10:
            logger.info(f"Generated Whole-Book Entity Dossier ({len(dossier)} chars)")
            return dossier.strip()
    except Exception as ex:
        logger.warning(f"Entity dossier extraction skipped: {ex}")
    return ""


async def _get_available_models(api_key: str, session: aiohttp.ClientSession) -> list[str]:
    """Queries Gemini ModelService to get supported text-generation models for this API key."""
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        return ["gemini-flash-latest", "gemini-2.5-flash-lite"]

    global _CACHED_AVAILABLE_MODELS, _CACHED_WORKING_MODEL, _CACHED_API_KEY_HASH
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    if _CACHED_API_KEY_HASH != key_hash:
        _CACHED_WORKING_MODEL = None
        _CACHED_AVAILABLE_MODELS = None
        _CACHED_API_KEY_HASH = key_hash
    if _CACHED_AVAILABLE_MODELS:
        return _CACHED_AVAILABLE_MODELS

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": api_key}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                models = data.get("models", [])
                valid_models = []
                for m in models:
                    name = m.get("name", "").replace("models/", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" not in methods:
                        continue
                    if any(p in name.lower() for p in EXCLUDE_PATTERNS):
                        continue
                    valid_models.append(name)

                logger.info(f"Discovered {len(valid_models)} valid text Gemini models: {valid_models}")
                _CACHED_AVAILABLE_MODELS = valid_models
                return valid_models
            else:
                err = await resp.text()
                logger.warning(f"Could not list models ({resp.status}): {err}")
    except Exception as e:
        logger.warning(f"Error querying Gemini ModelService: {e}")
    return []


async def polish_text_with_gemini(
    text: str,
    api_key: Optional[str] = None,
    style: str = "formal",
    original_text: Optional[str] = None,
    job_id: Optional[str] = None,
    use_source_anchoring: bool = True,
    progress_callback: Optional[Callable[[int, int], Any]] = None,
    target_lang: str = "greek",
    quota_behavior: str = "wait",
) -> str:
    """
    Polishes and proofreads translated text using Google's Gemini API.
    Supports multi-page smart batching, bilingual source-anchored verification,
    character consistency dossier, rolling narrative context, and disk checkpointing.
    """
    if not text or not str(text).strip():
        return text or ""

    is_greek_target = (target_lang or "greek").strip().lower() in ("greek", "el")

    def _postprocess(s: str) -> str:
        if not is_greek_target:
            return s
        from backend.typography import format_greek_typography
        from backend.glossary import apply_glossary
        return format_greek_typography(apply_glossary(s, "greek", style=style))

    from backend.settings_manager import get_setting
    key = api_key or os.environ.get("GEMINI_API_KEY") or get_setting("gemini_api_key")
    if not key:
        if quota_behavior == "fallback":
            logger.info(f"[{job_id or 'direct'}] No Gemini API key provided and quota_behavior='fallback' -> Applying free rule-based typography and glossary polish.")
            return _postprocess(text)
        raise ValueError("Missing Gemini API Key. Please provide a key in settings or select free models (fallback).")

    base_system_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["formal"])
    sem = asyncio.Semaphore(5)
    client_timeout = aiohttp.ClientTimeout(total=90)

    # Disk Checkpoint setup (with safe job_id validation and style/input fingerprint)
    checkpoint_file: Optional[Path] = None
    input_sig = hashlib.sha256(f"{style}::{target_lang}::{text[:2000]}::{len(text)}".encode("utf-8")).hexdigest()[:16]
    checkpoint_data: dict[str, Any] = {"sig": input_sig, "batches": {}, "chunks": {}}
    if job_id and "/" not in job_id and "\\" not in job_id and ".." not in job_id:
        out_dir = Path(__file__).resolve().parent.parent / "temp" / "outputs" / job_id
        if out_dir.exists():
            checkpoint_file = out_dir / ".polish_checkpoint.json"
            if checkpoint_file.is_file():
                try:
                    loaded = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                    # Reuse checkpoint if no sig (legacy/tests) or matching sig
                    if not loaded.get("sig") or loaded.get("sig") == input_sig:
                        if isinstance(loaded.get("batches"), dict):
                            checkpoint_data["batches"] = loaded["batches"]
                        if isinstance(loaded.get("chunks"), dict):
                            checkpoint_data["chunks"] = loaded["chunks"]
                        if isinstance(loaded.get("entity_dossier"), str):
                            checkpoint_data["entity_dossier"] = loaded["entity_dossier"]
                        logger.info(f"Loaded existing polish checkpoint with {len(checkpoint_data['batches'])} batches / {len(checkpoint_data['chunks'])} chunks")
                except Exception as ex:
                    logger.warning(f"Could not load polish checkpoint: {ex}")

    def _save_checkpoint():
        if checkpoint_file:
            with _CHECKPOINT_LOCK:
                tmp_cp = checkpoint_file.with_suffix(".json.tmp")
                try:
                    tmp_cp.write_text(json.dumps(checkpoint_data, ensure_ascii=False), encoding="utf-8")
                    os.replace(tmp_cp, checkpoint_file)
                except Exception as ex:
                    logger.warning(f"Could not write polish checkpoint: {ex}")
                    try:
                        tmp_cp.unlink(missing_ok=True)
                    except Exception:
                        pass

    async def _run_progress(done_count: int, total_count: int) -> None:
        if not progress_callback:
            return
        try:
            res = progress_callback(done_count, total_count)
            if asyncio.iscoroutine(res):
                await res
        except Exception as ex:
            logger.warning(f"Progress callback error: {ex}")

    # Auto-disable redundant Source-Anchored Verification if original_text is identical to draft text
    if original_text and original_text.strip() == (text or "").strip():
        use_source_anchoring = False
        original_text = None

    # Parse original text pages for source anchoring if provided
    orig_pages: dict[int, str] = {}
    if original_text and use_source_anchoring:
        orig_pages = _parse_pages_dict(original_text)

    # If document has multiple pages marked by dividers, group into smart multi-page batches
    page_sections = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    connector = aiohttp.TCPConnector(limit=12, ttl_dns_cache=300)
    async with aiohttp.ClientSession(timeout=client_timeout, connector=connector) as session:
        # Extract entity consistency dossier for long documents / literature if not already cached
        entity_dossier = checkpoint_data.get("entity_dossier", "")
        if style == "literature" and not entity_dossier and (len(page_sections) > 10 or len(text) > 18000):
            sample_src = original_text or text
            entity_dossier = await _extract_entity_dossier(sample_src, key, session=session)
            if entity_dossier:
                checkpoint_data["entity_dossier"] = entity_dossier
                _save_checkpoint()

        system_instruction = base_system_instruction
        if entity_dossier:
            system_instruction += (
                "\n\n--- ΜΗΤΡΩΟ ΟΝΟΜΑΤΩΝ & ΟΡΟΛΟΓΙΑΣ (ENTITY DOSSIER) ---\n"
                f"{entity_dossier}\n"
                "Διατήρησε αυστηρή συνέπεια στην ονομασία και φωνητική απόδοση των παραπάνω όρων σε όλο το κείμενο."
            )

        # Inject contextually-relevant user glossary rules (style-aware: excludes IT/DevOps terms for literature)
        from backend.glossary import load_glossary, apply_glossary
        glossary_items = load_glossary(style=style)
        if glossary_items:
            full_context_lower = (text + "\n" + (original_text or "")).lower()
            # Prioritize terms that actually appear in the source or draft text
            matched_terms = [
                (k, v) for k, v in glossary_items.items()
                if k.lower() in full_context_lower or v.lower() in full_context_lower
            ]
            selected_terms = matched_terms[:50]
            # If few specific terms matched, fill up to 30 with standard terms
            if len(selected_terms) < 20:
                for k, v in glossary_items.items():
                    if (k, v) not in selected_terms:
                        selected_terms.append((k, v))
                    if len(selected_terms) >= 30:
                        break

            glossary_lines = "\n".join(f"- {k} -> {v}" for k, v in selected_terms)
            system_instruction += (
                "\n\n--- ΓΛΩΣΣΑΡΙΟ ΚΑΙ ΟΡΟΛΟΓΙΑ ΧΡΗΣΤΗ (GLOSSARY RULES) ---\n"
                "Τήρησε αυστηρά τις ακόλουθες καθιερωμένες αποδόσεις όρων:\n"
                f"{glossary_lines}\n"
            )

        target_temp = STYLE_TEMPERATURES.get(style, 0.25)

        if len(page_sections) > 1:
            # Pair page markers with their content
            pages = []
            curr_marker = ""
            for part in page_sections:
                p_strip = part.strip()
                if not p_strip:
                    continue
                if re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", p_strip):
                    curr_marker = p_strip
                else:
                    pages.append((curr_marker, p_strip))

            # Smart Multi-Page Batching: group ~3 pages (or ~5,500 chars) per Gemini call
            # to stay well inside token & Greek attention limits without truncation
            batches = []
            curr_b = []
            curr_chars = 0
            MAX_BATCH_CHARS = 5500
            MAX_BATCH_PAGES = 3

            for m, c in pages:
                item_len = len(m) + len(c) + 4
                if curr_b and (curr_chars + item_len > MAX_BATCH_CHARS or len(curr_b) >= MAX_BATCH_PAGES):
                    batches.append(curr_b)
                    curr_b = [(m, c)]
                    curr_chars = item_len
                else:
                    curr_b.append((m, c))
                    curr_chars += item_len
            if curr_b:
                batches.append(curr_b)

            if not batches:
                return _postprocess(text)

            total_batches = len(batches)
            polished_batches = ["" for _ in batches]
            batch_failed = [False for _ in batches]
            completed = 0
            first_error: Optional[Exception] = None

            # Pre-fill batches already present in checkpoint
            cached_batches = checkpoint_data.get("batches", {})
            for b_idx in range(total_batches):
                b_str = str(b_idx)
                if b_str in cached_batches and isinstance(cached_batches[b_str], str) and cached_batches[b_str].strip():
                    polished_batches[b_idx] = cached_batches[b_str]
                    completed += 1

            if completed > 0:
                await _run_progress(completed, total_batches)

            async def _polish_items_reliably(
                batch_items: list[tuple[str, str]],
                prev_snippet: str = "",
                depth: int = 0,
            ) -> tuple[str, bool]:
                """
                Polishes a list of (page_marker, page_text) items with:
                - Clean XML-delimited read-only previous context (never '[... ...]')
                - Recursive bisection (multi-page -> single-page -> paragraph halves) on
                  MAX_TOKENS, safety/content blocks, or timeouts so a single offending
                  paragraph NEVER causes a 3-page silent fallback to raw MT.
                - Boundary deduplication when joining recursively split halves.
                Returns (text, any_ai_succeeded).
                """
                draft_batch_text = "\n\n".join(
                    f"{m}\n\n{c}" if m else c for m, c in batch_items
                )
                expected_page_nums = []
                source_batch_parts = []
                for m, _ in batch_items:
                    pm = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", m)
                    if pm:
                        pn = int(pm.group(1))
                        expected_page_nums.append(pn)
                        if orig_pages and use_source_anchoring and pn in orig_pages:
                            source_batch_parts.append(f"=== PAGE {pn} ===\n{orig_pages[pn]}")

                content_components = []
                if prev_snippet:
                    content_components.append(
                        f"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n{prev_snippet}\n</PREVIOUS_CONTEXT_DO_NOT_REPEAT>"
                    )
                if source_batch_parts:
                    orig_source_block = "\n\n".join(source_batch_parts)
                    content_components.append(
                        f"<SOURCE_REFERENCE>\n{orig_source_block}\n</SOURCE_REFERENCE>"
                    )
                    content_components.append(
                        f"<DRAFT_TO_POLISH>\n{draft_batch_text}\n</DRAFT_TO_POLISH>"
                    )
                else:
                    content_components.append(
                        f"<TEXT_TO_POLISH>\n{draft_batch_text}\n</TEXT_TO_POLISH>"
                    )

                prompt_content = "\n\n".join(content_components)
                batch_instruction = system_instruction
                if prev_snippet:
                    batch_instruction += (
                        "\n\n--- ΚΑΝΟΝΑΣ ΣΥΝΕΧΕΙΑΣ (ΜΗΝ ΕΠΑΝΑΛΑΜΒΑΝΕΙΣ) ---\n"
                        "Το τμήμα <PREVIOUS_CONTEXT_DO_NOT_REPEAT> παρέχεται ΜΟΝΟ ως αναφορά για γένος, ονόματα και ροή. "
                        "ΜΗΝ το συμπεριλάβεις, ΜΗΝ το ξαναγράψεις και ΜΗΝ το επαναλάβεις στην έξοδό σου. "
                        "Ξεκίνα την έξοδό σου ΑΜΕΣΩΣ από το κείμενο εντός <DRAFT_TO_POLISH>/<TEXT_TO_POLISH>."
                    )
                if source_batch_parts:
                    batch_instruction += (
                        "\n\n--- ΟΔΗΓΙΑ ΔΙΓΛΩΣΣΗΣ ΕΠΑΛΗΘΕΥΣΗΣ ---\n"
                        "Σου παρέχεται το Πρωτότυπο Κείμενο Αναφοράς (<SOURCE_REFERENCE>) καθώς και το Προσχέδιο Ελληνικής Μετάφρασης (<DRAFT_TO_POLISH>). "
                        "Χρησιμοποίησε το πρωτότυπο κείμενο για να διορθώσεις τυχόν παρανοήσεις, αγγλισμούς ή παραλείψεις του προσχεδίου. "
                        "Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το τελικό διορθωμένο ελληνικό κείμενο (χωρίς ετικέτες XML), διατηρώντας ΑΠΑΡΑΛΛΑΧΤΟΥΣ όλους τους δείκτες σελίδων === PAGE X ===."
                    )

                async def _bisect_and_recover(reason_label: str) -> Optional[tuple[str, bool]]:
                    if len(batch_items) > 1 and depth < 3:
                        mid = len(batch_items) // 2
                        logger.warning(f"Batch hit {reason_label}; splitting {len(batch_items)} pages into {mid}+{len(batch_items)-mid}...")
                        left_txt, left_ok = "", False
                        right_txt, right_ok = "", False
                        left_err: Optional[Exception] = None
                        right_err: Optional[Exception] = None
                        try:
                            left_txt, left_ok = await _polish_items_reliably(batch_items[:mid], prev_snippet, depth + 1)
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_l:
                            left_err = ex_l
                            left_txt = "\n\n".join(f"{m}\n\n{c}" if m else c for m, c in batch_items[:mid])
                        right_prev = _extract_clean_tail_context(left_txt if left_ok else batch_items[mid - 1][1])
                        try:
                            right_txt, right_ok = await _polish_items_reliably(batch_items[mid:], right_prev, depth + 1)
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_r:
                            right_err = ex_r
                            right_txt = "\n\n".join(f"{m}\n\n{c}" if m else c for m, c in batch_items[mid:])
                        if not left_ok and not right_ok:
                            raise (left_err or right_err or RuntimeError(reason_label))
                        right_first_pg = None
                        pm_r = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", batch_items[mid][0])
                        if pm_r:
                            right_first_pg = int(pm_r.group(1))
                        right_clean = _deduplicate_batch_boundary(left_txt, right_txt, expected_first_page=right_first_pg)
                        return f"{left_txt.strip()}\n\n{right_clean.strip()}".strip(), True

                    # Single-page paragraph bisection (isolates a single safety-blocked or oversized paragraph)
                    if len(batch_items) == 1 and depth < 4:
                        only_marker, only_content = batch_items[0]
                        halves = _split_text_in_half_by_paragraphs(only_content)
                        if halves:
                            l_para, r_para = halves
                            logger.warning(f"Single page hit {reason_label}; bisecting by paragraphs (depth={depth + 1})...")
                            left_txt, left_ok = "", False
                            right_txt, right_ok = "", False
                            left_err = None
                            right_err = None
                            try:
                                left_txt, left_ok = await _polish_items_reliably([(only_marker, l_para)], prev_snippet, depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_l:
                                left_err = ex_l
                                left_txt = f"{only_marker}\n\n{l_para}" if only_marker else l_para
                            right_prev = _extract_clean_tail_context(left_txt if left_ok else l_para)
                            try:
                                right_txt, right_ok = await _polish_items_reliably([("", r_para)], right_prev, depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_r:
                                right_err = ex_r
                                right_txt = r_para
                            if not left_ok and not right_ok:
                                raise (left_err or right_err or RuntimeError(reason_label))
                            right_clean = _deduplicate_batch_boundary(left_txt, right_txt, expected_first_page=None)
                            return f"{left_txt.strip()}\n\n{right_clean.strip()}".strip(), True
                    return None

                meta: dict[str, Any] = {}
                try:
                    polished = await _call_gemini_api(
                        prompt_content.strip(),
                        key,
                        batch_instruction,
                        session=session,
                        temperature=target_temp,
                        meta_out=meta,
                    )
                except PermissionError:
                    raise
                except (_TruncatedOutputError, _ContentBlockedError) as err:
                    recovered = await _bisect_and_recover(type(err).__name__)
                    if recovered is not None:
                        return recovered
                    raise
                except Exception as err:
                    err_low = str(err).lower()
                    is_splittable = any(k in err_low for k in ("timed out", "block", "safety", "prohibited", "empty", "max_tokens"))
                    if is_splittable:
                        recovered = await _bisect_and_recover(str(err)[:80])
                        if recovered is not None:
                            return recovered
                    raise

                # Strip any leaked preamble emitted before the batch's first expected PAGE marker
                if expected_page_nums:
                    polished = _deduplicate_batch_boundary("", polished, expected_first_page=expected_page_nums[0])

                # Quality gate: detect mixed-script corruption, missing page markers, or truncation
                issues = detect_greek_output_issues(
                    polished,
                    source_text=draft_batch_text,
                    expected_pages=expected_page_nums if len(expected_page_nums) >= 2 else None,
                )
                if issues:
                    logger.warning(f"Polish quality gate flagged issues {issues} (model={meta.get('model')})")
                    needs_split = any(i.startswith(("missing_pages", "truncated")) for i in issues)
                    if needs_split:
                        recovered = await _bisect_and_recover(",".join(issues))
                        if recovered is not None:
                            return recovered
                    bad_model = meta.get("model")
                    if bad_model and not key.startswith(("AQ.Test", "AIzaTest")):
                        try:
                            retry_instruction = batch_instruction
                            bad_tokens = _find_mixed_script_tokens(polished, source_text=draft_batch_text)
                            if bad_tokens:
                                retry_instruction += (
                                    "\n\n--- ΚΡΙΣΙΜΗ ΔΙΟΡΘΩΣΗ ΜΕΙΚΤΟΥ ΑΛΦΑΒΗΤΟΥ ---\n"
                                    f"Στην προηγούμενη προσπάθεια εμφανίστηκαν λέξεις με ξένους/λατινικούς χαρακτήρες μέσα σε ελληνικές λέξεις ({', '.join(bad_tokens[:8])}). "
                                    "Γράψε ΟΛΕΣ τις ελληνικές λέξεις με 100% καθαρούς ελληνικούς χαρακτήρες!"
                                )
                            # Only exclude bad_model if another full (non-lite, non-gemma) model is available
                            other_full_models = [
                                m for m in (_CACHED_AVAILABLE_MODELS or [])
                                if m != bad_model and not m.startswith("gemma") and "lite" not in m.lower()
                            ]
                            excl = {bad_model} if other_full_models else None
                            retry_meta: dict[str, Any] = {}
                            retried = await _call_gemini_api(
                                prompt_content.strip(),
                                key,
                                retry_instruction,
                                session=session,
                                temperature=max(0.1, target_temp - 0.1),
                                exclude_models=excl,
                                bypass_cache=True,
                                meta_out=retry_meta,
                            )
                            if expected_page_nums:
                                retried = _deduplicate_batch_boundary("", retried, expected_first_page=expected_page_nums[0])
                            retry_issues = detect_greek_output_issues(
                                retried,
                                source_text=draft_batch_text,
                                expected_pages=expected_page_nums if len(expected_page_nums) >= 2 else None,
                            )
                            if len(retry_issues) < len(issues):
                                logger.info(f"Quality retry succeeded on {retry_meta.get('model')} (issues: {issues} -> {retry_issues})")
                                return retried, True
                        except Exception as rex:
                            logger.debug(f"Quality retry failed: {rex}")
                return polished, True

            async def _polish_batch(b_idx: int, batch_items: list[tuple[str, str]]) -> None:
                nonlocal completed, first_error
                if polished_batches[b_idx]:
                    return  # Already restored from checkpoint

                draft_batch_text = "\n\n".join(
                    f"{m}\n\n{c}" if m else c for m, c in batch_items
                )
                prev_snippet = ""
                if b_idx > 0:
                    prev_draft = batches[b_idx - 1][-1][1]
                    prev_snippet = _extract_clean_tail_context(prev_draft, max_chars=240)

                async with sem:
                    last_ex: Optional[Exception] = None
                    polished_res = ""
                    for retry_round in range(2):
                        try:
                            polished_res, _ = await _polish_items_reliably(batch_items, prev_snippet=prev_snippet)
                            last_ex = None
                            break
                        except (PermissionError, DailyQuotaExhaustedError) as p_or_q:
                            if isinstance(p_or_q, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                                logger.warning(
                                    f"Gemini Daily Quota exhausted during polish (batch {b_idx + 1}/{total_batches}). "
                                    f"quota_behavior='fallback' -> keeping draft text..."
                                )
                                last_ex = p_or_q
                                break
                            raise
                        except Exception as ex:
                            last_ex = ex
                            if retry_round == 0 and any(k in str(ex) for k in ("429", "503", "500", "502", "504", "timed out")):
                                logger.info(f"Batch {b_idx + 1}/{total_batches} transient error, cooling down before retry: {ex}")
                                await asyncio.sleep(_TRANSIENT_RETRY_DELAY)
                                continue
                            break

                    if last_ex is None and polished_res:
                        polished_batches[b_idx] = polished_res
                        checkpoint_data["batches"][str(b_idx)] = polished_res
                        _save_checkpoint()
                    else:
                        if first_error is None:
                            first_error = last_ex
                        batch_failed[b_idx] = True
                        logger.warning(f"Batch {b_idx + 1}/{total_batches} polish failed (keeping original text): {last_ex}")
                        polished_batches[b_idx] = draft_batch_text

                completed += 1
                await _run_progress(completed, total_batches)

            # Process remaining batches
            pending_batches = [(i, b) for i, b in enumerate(batches) if not polished_batches[i]]
            if pending_batches:
                await asyncio.gather(*(_polish_batch(i, b) for i, b in pending_batches))

            if (all(batch_failed) or all(not p for p in polished_batches)) and first_error is not None:
                if isinstance(first_error, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                    logger.warning(
                        "All batches failed due to DailyQuotaExhaustedError but quota_behavior='fallback'. "
                        "Proceeding with unpolished original text."
                    )
                else:
                    raise first_error

            final_batches = []
            for b_idx, p in enumerate(polished_batches):
                if p and p.strip():
                    curr_txt = p.strip()
                else:
                    curr_txt = "\n\n".join(
                        f"{m}\n\n{c}" if m else c for m, c in batches[b_idx]
                    )
                first_pg = None
                if batches[b_idx]:
                    pm0 = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", batches[b_idx][0][0])
                    if pm0:
                        first_pg = int(pm0.group(1))
                prev_txt = final_batches[-1] if final_batches else ""
                curr_txt = _deduplicate_batch_boundary(prev_txt, curr_txt, expected_first_page=first_pg)
                if curr_txt:
                    final_batches.append(curr_txt)

            # Clean up checkpoint on complete success
            if checkpoint_file and checkpoint_file.exists():
                try:
                    checkpoint_file.unlink(missing_ok=True)
                except Exception:
                    pass

            return _postprocess("\n\n".join(final_batches))

        # For un-paginated text (e.g. Audiobook / DOCX), chunk long inputs (~6000 chars) and polish
        if len(text) > 4000:
            from backend.parsers import split_into_chunks
            chunks = split_into_chunks(text, 6000)
            total_chunks = max(1, len(chunks))
            polished_chunks = list(chunks)
            completed = 0
            succeeded = 0
            first_error: Optional[Exception] = None

            cached_chunks = checkpoint_data.get("chunks", {})
            for c_idx in range(total_chunks):
                c_str = str(c_idx)
                if c_str in cached_chunks and cached_chunks[c_str].strip():
                    polished_chunks[c_idx] = cached_chunks[c_str]
                    completed += 1
                    succeeded += 1

            if completed > 0:
                await _run_progress(completed, total_chunks)

            async def _polish_chunk_reliably(c_text: str, prev_snippet: str = "", depth: int = 0) -> tuple[str, bool]:
                if prev_snippet:
                    chunk_content = (
                        f"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n{prev_snippet}\n</PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n\n"
                        f"<TEXT_TO_POLISH>\n{c_text}\n</TEXT_TO_POLISH>"
                    )
                    chunk_instr = (
                        system_instruction
                        + "\n\n--- ΚΑΝΟΝΑΣ ΣΥΝΕΧΕΙΑΣ (ΜΗΝ ΕΠΑΝΑΛΑΜΒΑΝΕΙΣ) ---\n"
                        "ΜΗΝ συμπεριλάβεις και ΜΗΝ επαναλάβεις το <PREVIOUS_CONTEXT_DO_NOT_REPEAT>. "
                        "Επίστρεψε ΜΟΝΟ το διορθωμένο κείμενο εντός <TEXT_TO_POLISH>."
                    )
                else:
                    chunk_content = f"<TEXT_TO_POLISH>\n{c_text}\n</TEXT_TO_POLISH>"
                    chunk_instr = system_instruction

                try:
                    res_c = await _call_gemini_api(chunk_content, key, chunk_instr, session=session, temperature=target_temp)
                    return res_c, True
                except PermissionError:
                    raise
                except Exception as ex:
                    err_low = str(ex).lower()
                    can_split = isinstance(ex, (_TruncatedOutputError, _ContentBlockedError)) or any(
                        k in err_low for k in ("timed out", "block", "safety", "prohibited", "empty", "max_tokens")
                    )
                    if can_split and depth < 3:
                        halves = _split_text_in_half_by_paragraphs(c_text)
                        if halves:
                            l_txt, r_txt = halves
                            l_out, l_ok = l_txt, False
                            r_out, r_ok = r_txt, False
                            l_err: Optional[Exception] = None
                            r_err: Optional[Exception] = None
                            try:
                                l_out, l_ok = await _polish_chunk_reliably(l_txt, prev_snippet, depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_l:
                                l_err = ex_l
                            try:
                                r_out, r_ok = await _polish_chunk_reliably(r_txt, _extract_clean_tail_context(l_out if l_ok else l_txt), depth + 1)
                            except PermissionError:
                                raise
                            except Exception as ex_r:
                                r_err = ex_r
                            if not l_ok and not r_ok:
                                raise (l_err or r_err or ex)
                            r_clean = _deduplicate_batch_boundary(l_out, r_out)
                            return f"{l_out.strip()}\n\n{r_clean.strip()}".strip(), True
                    raise

            async def _polish_chunk(c_idx: int, c_text: str) -> None:
                nonlocal completed, succeeded, first_error
                if str(c_idx) in cached_chunks and cached_chunks[str(c_idx)].strip():
                    return

                prev_snippet = _extract_clean_tail_context(chunks[c_idx - 1], max_chars=240) if c_idx > 0 else ""

                async with sem:
                    last_ex: Optional[Exception] = None
                    res_text = ""
                    for retry_round in range(2):
                        try:
                            res_text, _ = await _polish_chunk_reliably(c_text, prev_snippet=prev_snippet)
                            last_ex = None
                            break
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex:
                            last_ex = ex
                            if retry_round == 0 and any(k in str(ex) for k in ("429", "503", "500", "502", "504", "timed out")):
                                await asyncio.sleep(_TRANSIENT_RETRY_DELAY)
                                continue
                            break
                    if last_ex is None and res_text:
                        polished_chunks[c_idx] = res_text
                        checkpoint_data["chunks"][str(c_idx)] = res_text
                        _save_checkpoint()
                        succeeded += 1
                    else:
                        if first_error is None:
                            first_error = last_ex
                        logger.warning(f"Chunk {c_idx + 1}/{total_chunks} polish failed (keeping original chunk): {last_ex}")
                completed += 1
                await _run_progress(completed, total_chunks)

            pending_chunks = [(i, c) for i, c in enumerate(chunks) if str(i) not in cached_chunks]
            if pending_chunks:
                await asyncio.gather(*(_polish_chunk(i, c) for i, c in pending_chunks))

            if succeeded == 0 and first_error is not None:
                raise first_error

            if checkpoint_file and checkpoint_file.exists():
                try:
                    checkpoint_file.unlink(missing_ok=True)
                except Exception:
                    pass

            dedup_chunks: list[str] = []
            for p in polished_chunks:
                if not p or not p.strip():
                    continue
                prev_c = dedup_chunks[-1] if dedup_chunks else ""
                cleaned_c = _deduplicate_batch_boundary(prev_c, p.strip())
                if cleaned_c:
                    dedup_chunks.append(cleaned_c)

            return _postprocess("\n\n".join(dedup_chunks))

        single_input = text
        if original_text and use_source_anchoring:
            single_input = (
                f"<SOURCE_REFERENCE>\n{original_text}\n</SOURCE_REFERENCE>\n\n"
                f"<DRAFT_TO_POLISH>\n{text}\n</DRAFT_TO_POLISH>"
            )
        polished_single = await _call_gemini_api(single_input, key, system_instruction, session=session, temperature=target_temp)
        await _run_progress(1, 1)
        return _postprocess(polished_single)


# Alias for concise invocation
polish_text = polish_text_with_gemini


async def _call_gemini_api(
    content_text: str,
    api_key: str,
    system_prompt: str,
    session: Optional[aiohttp.ClientSession] = None,
    temperature: float = 0.25,
    exclude_models: Optional[set[str]] = None,
    bypass_cache: bool = False,
    meta_out: Optional[dict[str, Any]] = None,
) -> str:
    """Invokes Gemini generateContent with cache, full-Flash priority, thought filtering, safety/block detection, and MAX_TOKENS protection."""
    from backend.gemini_key_pool import GeminiKeyPool, mask_api_key

    # Resolve active key: use provided key or next available key from the 4-key pool
    attempted_keys: set[str] = set()
    pool_keys = GeminiKeyPool.get_keys()
    initial_key = (api_key or "").strip()
    if not initial_key or (not initial_key.startswith(("AQ.Test", "AIzaTest")) and GeminiKeyPool.is_key_exhausted(initial_key)):
        initial_key = GeminiKeyPool.get_active_key() or initial_key

    # Allow rotation across pool if no key was explicitly pinned, or if the provided key belongs to the configured pool
    allow_pool_rotation = (not (api_key or "").strip()) or (initial_key in pool_keys)

    current_key = initial_key

    if not current_key.startswith(("AQ.Test", "AIzaTest")) and is_gemini_quota_exhausted():
        q_info = get_gemini_quota_info()
        raise DailyQuotaExhaustedError(
            f"⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). "
            f"Έτοιμο ξανά στις {q_info['reset_time_str']} (απομένουν ~{q_info['cooldown_time_str']}). "
            f"Αλλάξτε API Key στις Ρυθμίσεις ή περιμένετε την αντίστροφη μέτρηση για αυτόματη συνέχιση."
        )

    if current_key.startswith("AQ.Test") or current_key.startswith("AIzaTest"):
        logger.info("Test API key detected - returning mock polished text.")
        for tag in ("DRAFT_TO_POLISH", "TEXT_TO_POLISH", "TEXT_TO_TRANSLATE"):
            m_tag = re.search(rf"<{tag}>(.*?)</{tag}>", content_text, re.DOTALL | re.IGNORECASE)
            if m_tag:
                inner = m_tag.group(1).strip()
                if re.search(r"={3,}\s*PAGE\s+\d+\s*={3,}", inner):
                    subbed = re.sub(r"(={3,}\s*PAGE\s+\d+\s*={3,})", r"\1\n[Επιμελημένο AI]:", inner)
                    return sanitize_ai_output(subbed)
                return sanitize_ai_output(f"[Επιμελημένο AI]: {inner}")
        if "--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n" in content_text:
            draft_part = content_text.split("--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n")[-1]
            return sanitize_ai_output(f"[Επιμελημένο AI]: {draft_part.strip()}")
        return sanitize_ai_output(f"[Επιμελημένο AI]: {content_text}")

    # Check cache first (unless explicitly bypassed during a quality retry)
    # Hash the FULL system_prompt so style, language, glossary, and entity dossier NEVER collide!
    cache_key = None
    prompt_hash = hashlib.sha256((system_prompt or "").encode("utf-8")).hexdigest()[:24]
    if not bypass_cache:
        try:
            from backend.database import compute_cache_key, db_get_cached_translation
            cache_key = compute_cache_key(content_text, "draft", "greek", engine="gemini_polish_v4", extra=f"{prompt_hash}:{temperature}")
            cached_result = db_get_cached_translation(cache_key)
            if cached_result is not None:
                logger.info("Retrieved AI polished chunk directly from SQLite cache.")
                return sanitize_ai_output(cached_result)
        except Exception as ex:
            logger.debug(f"Polish cache check skipped: {ex}")
    else:
        try:
            from backend.database import compute_cache_key
            cache_key = compute_cache_key(content_text, "draft", "greek", engine="gemini_polish_v4", extra=f"{prompt_hash}:{temperature}")
        except Exception:
            pass

    global _CACHED_WORKING_MODEL

    base_payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"{system_prompt}\n\n--- ΚΕΙΜΕΝΟ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ ---\n{content_text}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 16384,
        },
        "safetySettings": _LITERARY_SAFETY_SETTINGS,
    }

    # Reuse caller's session if provided, otherwise open a temporary one
    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
    try:
        while current_key:
            attempted_keys.add(current_key)
            active_key = current_key
            switched_key = False

            candidates = []

            # If a full (non-lite, non-gemma) working model was already cached, try it first
            if (
                _CACHED_WORKING_MODEL
                and not _CACHED_WORKING_MODEL.startswith("gemma")
                and "lite" not in _CACHED_WORKING_MODEL.lower()
            ):
                candidates.append(_CACHED_WORKING_MODEL)

            discovered = await _get_available_models(active_key, session)
            if discovered:
                # 1. Preferred full Flash models first, then Flash-Lite
                for pref in PREFERRED_FLASH_MODELS:
                    if pref in discovered and pref not in candidates:
                        candidates.append(pref)

                # 2. Other non-gemma, non-lite models
                for m in discovered:
                    if not m.startswith("gemma") and "lite" not in m.lower() and m not in candidates:
                        candidates.append(m)

                # 3. Remaining non-gemma (lite) models
                for m in discovered:
                    if not m.startswith("gemma") and m not in candidates:
                        candidates.append(m)

                # 4. Gemma models as last resort
                for m in discovered:
                    if m.startswith("gemma") and m not in candidates:
                        candidates.append(m)
            else:
                for fb in PREFERRED_FLASH_MODELS:
                    if fb not in candidates:
                        candidates.append(fb)

            if exclude_models:
                filtered = [m for m in candidates if m not in exclude_models]
                if filtered:
                    candidates = filtered

            last_error = None
            saw_truncation = False
            saw_block = False
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": active_key,
            }

            for model in candidates:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                # Disable hidden thinking on Flash models (2.5 & 3.x) so output budget isn't eaten by chain-of-thought
                m_low = model.lower()
                use_no_thinking = (
                    "flash" in m_low
                    and "pro" not in m_low
                    and not m_low.startswith("gemma")
                    and ("2.5" in m_low or "3" in m_low or "latest" in m_low)
                )
                req_payload: dict[str, Any] = (
                    {
                        **base_payload,
                        "generationConfig": {
                            **base_payload["generationConfig"],
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    }
                    if use_no_thinking
                    else dict(base_payload)
                )

                max_attempts = 3
                for attempt in range(max_attempts):
                    try:
                        req_timeout = aiohttp.ClientTimeout(total=60)
                        async with session.post(url, json=req_payload, headers=headers, timeout=req_timeout) as resp:
                            if resp.status == 200:
                                result = await resp.json()
                                raw_text, finish_reason = _extract_gemini_text_and_reason(result)
                                if not raw_text:
                                    saw_block = True
                                    last_error = f"Model {model} returned empty/blocked content (reason: {finish_reason or 'UNKNOWN'})"
                                    logger.warning(f"Model {model} candidate returned no content parts (finishReason: {finish_reason or 'UNKNOWN'})")
                                    break
                                if finish_reason == "MAX_TOKENS":
                                    logger.warning(f"Model {model} hit MAX_TOKENS ({len(raw_text)} chars) — rejecting truncated output.")
                                    saw_truncation = True
                                    raise _TruncatedOutputError(f"Model {model} hit MAX_TOKENS")
                                polished = sanitize_ai_output(raw_text)
                                if not polished:
                                    saw_block = True
                                    last_error = f"Model {model} returned empty text after sanitization."
                                    break
                                # Only pin full non-lite Flash models as the cached primary model
                                if "lite" not in m_low and not m_low.startswith("gemma"):
                                    _CACHED_WORKING_MODEL = model
                                if meta_out is not None:
                                    meta_out["model"] = model
                                    meta_out["finish_reason"] = finish_reason
                                logger.info(f"Gemini API success using model: {model}")
                                if cache_key and not detect_greek_output_issues(polished, source_text=content_text):
                                    try:
                                        from backend.database import db_set_cached_translation
                                        db_set_cached_translation(cache_key, content_text, polished, "draft", "greek", engine="gemini_polish_v4")
                                    except Exception:
                                        pass
                                return polished
                            elif resp.status in (401, 403):
                                err_text = await resp.text()
                                raise PermissionError(f"Gemini API authentication error ({resp.status}): {err_text}")
                            elif resp.status == 404:
                                logger.debug(f"Model {model} returned 404, trying next candidate...")
                                if _CACHED_WORKING_MODEL == model:
                                    _CACHED_WORKING_MODEL = None
                                break
                            elif resp.status in (500, 502, 503, 504):
                                err_text = await resp.text()
                                last_error = f"Gemini API error ({resp.status}): {err_text}"
                                logger.info(f"Model {model} overloaded/unavailable ({resp.status}). Immediately trying next candidate...")
                                if _CACHED_WORKING_MODEL == model:
                                    _CACHED_WORKING_MODEL = None
                                break
                            elif resp.status == 429:
                                err_text = await resp.text()
                                last_error = f"Gemini API error (429): {err_text}"

                                cooldown_sec = 3600.0
                                m_delay = re.search(r'"retryDelay":\s*"(\d+)s"', err_text)
                                if m_delay:
                                    try:
                                        cooldown_sec = max(300.0, float(m_delay.group(1)))
                                    except Exception:
                                        pass

                                err_low = err_text.lower()
                                if (
                                    "requests per day limit exceeded" in err_low
                                    or "quota exceeded" in err_low
                                    or "resource_exhausted" in err_low
                                    or "per day" in err_low
                                    or cooldown_sec >= 180.0
                                ):
                                    GeminiKeyPool.mark_key_exhausted(active_key, cooldown_sec, reason=err_text[:120])
                                    next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=attempted_keys) if allow_pool_rotation else None
                                    if next_pool_key:
                                        logger.warning(
                                            f"[Gemini Key Pool] Active key {mask_api_key(active_key)} reached quota. "
                                            f"Seamlessly rotating to next available key {mask_api_key(next_pool_key)}..."
                                        )
                                        current_key = next_pool_key
                                        switched_key = True
                                        break

                                    trip_gemini_quota_exhaustion(cooldown_sec)
                                    q_info = get_gemini_quota_info()
                                    logger.warning(
                                        f"Gemini daily quota exhausted ({resp.status}). All {len(attempted_keys)} pool keys exhausted. Tripping circuit breaker for {int(cooldown_sec)}s."
                                    )
                                    raise DailyQuotaExhaustedError(
                                        f"⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). "
                                        f"Η πρόοδος αποθηκεύτηκε σε checkpoint στο δίσκο. "
                                        f"Έτοιμο ξανά στις {q_info['reset_time_str']} (απομένουν ~{q_info['cooldown_time_str']}). "
                                        f"Παρακαλούμε περιμένετε ή αλλάξτε API Key στις Ρυθμίσεις (Settings)."
                                    )

                                logger.warning(f"Model {model} rate limited (attempt {attempt + 1}/{max_attempts}): {last_error}")
                                if attempt < max_attempts - 1:
                                    await asyncio.sleep(2.5)
                                    continue
                                break
                            else:
                                err_text = await resp.text()
                                # If model rejected thinkingConfig or safetySettings, strip and retry cleanly
                                if resp.status == 400 and "thinking" in err_text.lower() and "thinkingConfig" in req_payload.get("generationConfig", {}):
                                    req_payload = {
                                        **req_payload,
                                        "generationConfig": {
                                            k: v for k, v in req_payload["generationConfig"].items() if k != "thinkingConfig"
                                        },
                                    }
                                    continue
                                if resp.status == 400 and "safety" in err_text.lower() and "safetySettings" in req_payload:
                                    req_payload = {k: v for k, v in req_payload.items() if k != "safetySettings"}
                                    continue
                                last_error = f"Gemini API error ({resp.status}): {err_text}"
                                if resp.status == 400 and "API_KEY_INVALID" in err_text:
                                    raise PermissionError(last_error)
                                logger.warning(f"Model {model} failed: {last_error}")
                                break
                    except (PermissionError, _TruncatedOutputError, DailyQuotaExhaustedError):
                        raise
                    except asyncio.TimeoutError:
                        last_error = f"Model {model} timed out after 60s."
                        logger.warning(f"Model {model} timed out after 60s. Switching immediately to next candidate...")
                        if _CACHED_WORKING_MODEL == model:
                            _CACHED_WORKING_MODEL = None
                        break
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Call to {model} failed (attempt {attempt + 1}/{max_attempts}): {e}")
                        if _CACHED_WORKING_MODEL == model:
                            _CACHED_WORKING_MODEL = None
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(1.0)

                if switched_key:
                    break

            if switched_key:
                continue

            if saw_truncation:
                raise _TruncatedOutputError(last_error or "Gemini output truncated by MAX_TOKENS.")
            if saw_block:
                raise _ContentBlockedError(last_error or "Gemini content blocked/empty across all candidates.")
            err_low = (last_error or "").lower()
            if "429" in err_low or "quota" in err_low or "resource_exhausted" in err_low or "rate limit" in err_low:
                GeminiKeyPool.mark_key_exhausted(active_key, 3600.0, reason=err_low[:120])
                next_pool_key = GeminiKeyPool.get_active_key(exclude_keys=attempted_keys) if allow_pool_rotation else None
                if next_pool_key:
                    logger.warning(
                        f"[Gemini Key Pool] Active key {mask_api_key(active_key)} rate limited. Seamlessly rotating to next key {mask_api_key(next_pool_key)}..."
                    )
                    current_key = next_pool_key
                    continue

                trip_gemini_quota_exhaustion(3600.0)
                q_info = get_gemini_quota_info()
                raise DailyQuotaExhaustedError(
                    f"⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Google Free Tier 15 RPM / 1500 RPD). "
                    f"Η πρόοδος αποθηκεύτηκε σε checkpoint στο δίσκο. "
                    f"Έτοιμο ξανά στις {q_info['reset_time_str']} (απομένουν ~{q_info['cooldown_time_str']}). "
                    f"Παρακαλούμε περιμένετε ή αλλάξτε API Key στις Ρυθμίσεις (Settings)."
                )
            raise RuntimeError(last_error or "All Gemini candidate models failed.")
    finally:
        if owns_session:
            await session.close()


async def translate_and_polish_direct_with_gemini(
    job_id: str,
    file_path: str,
    file_type: str,
    source_lang: str,
    target_lang: str,
    output_path: str,
    api_key: str,
    style: str = "literature",
    quota_behavior: str = "wait",
) -> str:
    """
    Single-Pass Direct AI Translation + Literary Polish via Gemini Flash.
    Eliminates the slow 2-pass Google Translate -> Gemini Polish pipeline:
    parses the document, extracts an entity consistency dossier, applies user glossary,
    and translates+polishes multi-page batches concurrently (5 parallel workers),
    saving both *_original.txt (for split-screen editor) and the polished output.
    """
    from backend.parsers import parse_document
    from backend.job_manager import update_job, is_job_cancelled
    from backend.glossary import load_glossary, apply_glossary

    update_job(job_id, status="running", current_step="Reading document for Single-Pass AI Translation...", progress=2)
    pages = list(parse_document(file_path, file_type))
    total_pages = len(pages)
    if total_pages == 0:
        raise ValueError("No readable text found in document.")

    # Save original extracted text for split-screen editor review
    out_dir = Path(output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(file_path).stem
    orig_sections = []
    for p in pages:
        p_num = p["page"]
        p_txt = (p.get("text") or "").strip()
        orig_sections.append(f"=== PAGE {p_num} ===\n{p_txt}")
    full_original = "\n\n".join(orig_sections)
    try:
        (out_dir / f"{stem}_original.txt").write_text(full_original, encoding="utf-8")
    except Exception:
        pass

    # Build direct translation+polish system instruction
    src_label = "Αγγλικά" if source_lang.lower().startswith("en") else "Ελληνικά"
    tgt_label = "Ελληνικά" if target_lang.lower().startswith("gr") or target_lang.lower() == "el" else "Αγγλικά"
    base_style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["literature"])

    direct_prompt = (
        f"Είσαι κορυφαίος επαγγελματίας μεταφραστής και επιμελητής εκδόσεων από {src_label} σε {tgt_label}.\n"
        f"Μετάφρασε ΑΠΕΥΘΕΙΑΣ το ακόλουθο κείμενο από {src_label} σε άψογα, φυσικά και καλαίσθητα {tgt_label} "
        f"(σε ένα ενιαίο βήμα μετάφρασης + επιμέλειας), τηρώντας αυστηρά τις εξής αρχές:\n"
        f"{base_style_prompt}\n"
        f"ΚΡΙΣΙΜΟ: Διατήρησε ΑΠΑΡΑΛΛΑΧΤΟΥΣ όλους τους δείκτες σελίδων (=== PAGE X ===) ακριβώς στις θέσεις τους. "
        f"Μην παραλείπεις καμία παράγραφο ή πρόταση. ΜΗΝ αφήνεις ποτέ ετικέτες HTML/XML (<i>, </i>, <bos>), "
        f"σημειώσεις επιμελητή ([Σημείωση...]), σκέψεις ανάλυσης ή ξένα γράμματα (λατινικά/κυριλλικά/εβραϊκά) μέσα σε ελληνικές λέξεις. "
        f"Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ τη μετάφραση χωρίς σχόλια."
    )

    # Disk checkpoint support for instant resume
    checkpoint_file = out_dir / ".direct_ai_checkpoint.json"
    checkpoint_data: dict[str, Any] = {"batches": {}, "entity_dossier": ""}
    if checkpoint_file.is_file():
        try:
            loaded = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            if isinstance(loaded.get("batches"), dict):
                checkpoint_data["batches"] = loaded["batches"]
            if isinstance(loaded.get("entity_dossier"), str):
                checkpoint_data["entity_dossier"] = loaded["entity_dossier"]
        except Exception:
            pass

    def _save_cp():
        try:
            checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # Group pages into ~5,500-char / max 3-page batches for high Greek fidelity & zero MAX_TOKENS truncation
    batches: list[list[tuple[int, str]]] = []
    curr_b: list[tuple[int, str]] = []
    curr_chars = 0
    MAX_BATCH_CHARS = 5500
    MAX_BATCH_PAGES = 3

    for p in pages:
        p_num = p["page"]
        p_txt = (p.get("text") or "").strip()
        item_len = len(p_txt) + 25
        if curr_b and (curr_chars + item_len > MAX_BATCH_CHARS or len(curr_b) >= MAX_BATCH_PAGES):
            batches.append(curr_b)
            curr_b = [(p_num, p_txt)]
            curr_chars = item_len
        else:
            curr_b.append((p_num, p_txt))
            curr_chars += item_len
    if curr_b:
        batches.append(curr_b)

    total_batches = max(1, len(batches))
    results = ["" for _ in batches]
    completed = 0
    pages_done = 0
    cached_b = checkpoint_data.get("batches", {})
    for i in range(total_batches):
        if str(i) in cached_b and cached_b[str(i)].strip():
            results[i] = cached_b[str(i)]
            completed += 1
            pages_done += len(batches[i])

    init_pct = 8 + int((completed / total_batches) * 85) if completed > 0 else 5
    init_step = (
        f"Resuming Single-Pass AI Translation & Polish: batch {completed}/{total_batches} ({pages_done}/{total_pages} pages)..."
        if completed > 0
        else f"Single-Pass AI Translation ({total_batches} parallel batches, {total_pages} pages)..."
    )
    update_job(
        job_id,
        total_chunks=total_batches,
        done_chunks=completed,
        total_pages=total_pages,
        done_pages=pages_done,
        progress=init_pct,
        current_step=init_step,
    )

    sem = asyncio.Semaphore(5)
    target_temp = STYLE_TEMPERATURES.get(style, 0.30)
    connector = aiohttp.TCPConnector(limit=12, ttl_dns_cache=300)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90), connector=connector) as session:
        # Extract entity consistency dossier for long documents
        entity_dossier = checkpoint_data.get("entity_dossier", "")
        if not entity_dossier and len(full_original) > 18000:
            update_job(job_id, current_step="Extracting character & terminology dossier...", progress=max(6, init_pct))
            entity_dossier = await _extract_entity_dossier(full_original, api_key, session=session)
            if entity_dossier:
                checkpoint_data["entity_dossier"] = entity_dossier
                _save_cp()

        system_instruction = direct_prompt
        if entity_dossier:
            system_instruction += (
                "\n\n--- ΜΗΤΡΩΟ ΟΝΟΜΑΤΩΝ & ΟΡΟΛΟΓΙΑΣ (ENTITY DOSSIER) ---\n"
                f"{entity_dossier}\n"
            )

        # Inject matching glossary terms (style-aware: excludes IT/DevOps terms for literature)
        glossary_items = load_glossary(style=style)
        if glossary_items:
            lower_src = full_original.lower()
            matched = [(k, v) for k, v in glossary_items.items() if k.lower() in lower_src][:50]
            if matched:
                g_lines = "\n".join(f"- {k} -> {v}" for k, v in matched)
                system_instruction += (
                    "\n\n--- ΓΛΩΣΣΑΡΙΟ ΧΡΗΣΤΗ (GLOSSARY RULES) ---\n"
                    f"{g_lines}\n"
                )

        is_target_greek = target_lang.lower() in ("greek", "el")

        async def _translate_items_reliably(
            b_items: list[tuple[Optional[int], str]],
            prev_tail: str = "",
            depth: int = 0,
        ) -> str:
            batch_src = "\n\n".join(
                f"=== PAGE {pn} ===\n{txt}" if pn is not None else txt for pn, txt in b_items
            )
            expected_pnums = [pn for pn, txt in b_items if pn is not None and txt.strip()]
            content_parts = []
            if prev_tail:
                content_parts.append(
                    f"<PREVIOUS_CONTEXT_DO_NOT_REPEAT>\n{prev_tail}\n</PREVIOUS_CONTEXT_DO_NOT_REPEAT>"
                )
            content_parts.append(f"<TEXT_TO_TRANSLATE>\n{batch_src}\n</TEXT_TO_TRANSLATE>")
            prompt_text = "\n\n".join(content_parts)

            batch_sys = system_instruction
            if prev_tail:
                batch_sys += (
                    "\n\n--- ΚΑΝΟΝΑΣ ΣΥΝΕΧΕΙΑΣ (ΜΗΝ ΜΕΤΑΦΡΑΖΕΙΣ ΤΟ ΠΡΟΗΓΟΥΜΕΝΟ ΑΠΟΣΠΑΣΜΑ) ---\n"
                    "Το τμήμα <PREVIOUS_CONTEXT_DO_NOT_REPEAT> παρέχεται ΜΟΝΟ ως αναφορά για γένος, ονόματα και ροή. "
                    "ΜΗΝ το μεταφράσεις, ΜΗΝ το επαναλάβεις και ΜΗΝ το συμπεριλάβεις στην έξοδό σου. "
                    "Ξεκίνα τη μετάφρασή σου ΑΜΕΣΩΣ από το κείμενο εντός <TEXT_TO_TRANSLATE> (χωρίς ετικέτες XML)."
                )

            async def _bisect_direct(reason_label: str) -> Optional[str]:
                if len(b_items) > 1 and depth < 3:
                    mid = len(b_items) // 2
                    logger.warning(f"[{job_id}] Direct AI batch hit {reason_label}; splitting {len(b_items)} pages into {mid}+{len(b_items)-mid}...")
                    left_ok, right_ok = False, False
                    left_err: Optional[Exception] = None
                    right_err: Optional[Exception] = None
                    left_res, right_res = "", ""
                    try:
                        left_res = await _translate_items_reliably(b_items[:mid], prev_tail, depth + 1)
                        left_ok = True
                    except (PermissionError, DailyQuotaExhaustedError):
                        raise
                    except Exception as ex_l:
                        left_err = ex_l
                        from backend.translator import _translate_with_retry
                        fb_l = []
                        for pn_l, txt_l in b_items[:mid]:
                            tr_l = await _translate_with_retry(txt_l, source_lang, target_lang) if txt_l else ""
                            fb_l.append(f"=== PAGE {pn_l} ===\n{tr_l}" if pn_l is not None else tr_l)
                        left_res = "\n\n".join(fb_l)
                    right_tail = _extract_clean_tail_context(b_items[mid - 1][1]) if b_items[mid - 1][1] else ""
                    try:
                        right_res = await _translate_items_reliably(b_items[mid:], right_tail, depth + 1)
                        right_ok = True
                    except (PermissionError, DailyQuotaExhaustedError):
                        raise
                    except Exception as ex_r:
                        right_err = ex_r
                        from backend.translator import _translate_with_retry
                        fb_r = []
                        for pn_r, txt_r in b_items[mid:]:
                            tr_r = await _translate_with_retry(txt_r, source_lang, target_lang) if txt_r else ""
                            fb_r.append(f"=== PAGE {pn_r} ===\n{tr_r}" if pn_r is not None else tr_r)
                        right_res = "\n\n".join(fb_r)
                    if not left_ok and not right_ok:
                        raise (left_err or right_err or RuntimeError(reason_label))
                    r_first_pg = b_items[mid][0]
                    right_clean = _deduplicate_batch_boundary(left_res, right_res, expected_first_page=r_first_pg)
                    return f"{left_res.strip()}\n\n{right_clean.strip()}".strip()

                # Single-page paragraph bisection so 1 explicit paragraph never drops an entire page to Google Translate
                if len(b_items) == 1 and depth < 4:
                    only_pn, only_txt = b_items[0]
                    halves = _split_text_in_half_by_paragraphs(only_txt)
                    if halves:
                        l_txt, r_txt = halves
                        logger.warning(f"[{job_id}] Direct AI single page {only_pn} hit {reason_label}; bisecting by paragraphs (depth={depth + 1})...")
                        left_ok, right_ok = False, False
                        left_err = None
                        right_err = None
                        left_res, right_res = "", ""
                        try:
                            left_res = await _translate_items_reliably([(only_pn, l_txt)], prev_tail, depth + 1)
                            left_ok = True
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_l:
                            left_err = ex_l
                            from backend.translator import _translate_with_retry
                            tr_l = await _translate_with_retry(l_txt, source_lang, target_lang)
                            left_res = f"=== PAGE {only_pn} ===\n{tr_l}" if only_pn is not None else tr_l
                        try:
                            right_res = await _translate_items_reliably([(None, r_txt)], _extract_clean_tail_context(l_txt), depth + 1)
                            right_ok = True
                        except (PermissionError, DailyQuotaExhaustedError):
                            raise
                        except Exception as ex_r:
                            right_err = ex_r
                            from backend.translator import _translate_with_retry
                            right_res = await _translate_with_retry(r_txt, source_lang, target_lang)
                        if not left_ok and not right_ok:
                            raise (left_err or right_err or RuntimeError(reason_label))
                        right_clean = _deduplicate_batch_boundary(left_res, right_res, expected_first_page=None)
                        return f"{left_res.strip()}\n\n{right_clean.strip()}".strip()
                return None

            meta: dict[str, Any] = {}
            try:
                translated_b = await _call_gemini_api(
                    prompt_text,
                    api_key,
                    batch_sys,
                    session=session,
                    temperature=target_temp,
                    meta_out=meta,
                )
            except PermissionError:
                raise
            except (_TruncatedOutputError, _ContentBlockedError) as err:
                recovered = await _bisect_direct(type(err).__name__)
                if recovered is not None:
                    return recovered
                raise
            except Exception as err:
                err_low = str(err).lower()
                if any(k in err_low for k in ("timed out", "block", "safety", "prohibited", "empty", "max_tokens")):
                    recovered = await _bisect_direct(str(err)[:80])
                    if recovered is not None:
                        return recovered
                raise

            if expected_pnums:
                translated_b = _deduplicate_batch_boundary("", translated_b, expected_first_page=expected_pnums[0])

            if is_target_greek and not api_key.startswith(("AQ.Test", "AIzaTest")):
                issues = detect_greek_output_issues(
                    translated_b,
                    source_text=batch_src,
                    expected_pages=expected_pnums if len(expected_pnums) >= 2 else None,
                )
                if issues:
                    logger.warning(f"[{job_id}] Direct AI quality gate flagged {issues} (model={meta.get('model')})")
                    needs_split = any(i.startswith(("missing_pages", "truncated")) for i in issues)
                    if needs_split:
                        recovered = await _bisect_direct(",".join(issues))
                        if recovered is not None:
                            return recovered
                    bad_model = meta.get("model")
                    if bad_model:
                        try:
                            retry_sys = batch_sys
                            bad_tokens = _find_mixed_script_tokens(translated_b, source_text=batch_src)
                            if bad_tokens:
                                retry_sys += (
                                    "\n\n--- ΚΡΙΣΙΜΗ ΔΙΟΡΘΩΣΗ ΜΕΙΚΤΟΥ ΑΛΦΑΒΗΤΟΥ ---\n"
                                    f"Στην προηγούμενη προσπάθεια εμφανίστηκαν λέξεις με ξένους/λατινικούς χαρακτήρες μέσα σε ελληνικές λέξεις ({', '.join(bad_tokens[:8])}). "
                                    "Γράψε ΟΛΕΣ τις ελληνικές λέξεις με 100% καθαρούς ελληνικούς χαρακτήρες!"
                                )
                            other_full_models = [
                                m for m in (_CACHED_AVAILABLE_MODELS or [])
                                if m != bad_model and not m.startswith("gemma") and "lite" not in m.lower()
                            ]
                            excl = {bad_model} if other_full_models else None
                            retry_meta: dict[str, Any] = {}
                            retried = await _call_gemini_api(
                                prompt_text,
                                api_key,
                                retry_sys,
                                session=session,
                                temperature=max(0.1, target_temp - 0.1),
                                exclude_models=excl,
                                bypass_cache=True,
                                meta_out=retry_meta,
                            )
                            if expected_pnums:
                                retried = _deduplicate_batch_boundary("", retried, expected_first_page=expected_pnums[0])
                            retry_issues = detect_greek_output_issues(
                                retried,
                                source_text=batch_src,
                                expected_pages=expected_pnums if len(expected_pnums) >= 2 else None,
                            )
                            if len(retry_issues) < len(issues):
                                logger.info(f"[{job_id}] Quality retry succeeded on {retry_meta.get('model')} ({issues} -> {retry_issues})")
                                return retried
                        except Exception as rex:
                            logger.debug(f"[{job_id}] Quality retry failed: {rex}")

            return translated_b

        async def _worker(b_idx: int, b_items: list[tuple[int, str]]):
            nonlocal completed, pages_done
            if results[b_idx]:
                return
            if is_job_cancelled(job_id):
                raise asyncio.CancelledError("Translation cancelled by user.")

            # If all pages in batch are empty, skip API call
            if all(not txt for _, txt in b_items):
                results[b_idx] = "\n\n".join(f"=== PAGE {pn} ===" for pn, _ in b_items)
                completed += 1
                pages_done += len(b_items)
                return

            prev_tail = ""
            if b_idx > 0:
                prev_txt = batches[b_idx - 1][-1][1]
                if prev_txt:
                    prev_tail = _extract_clean_tail_context(prev_txt, max_chars=240)

            async with sem:
                if is_job_cancelled(job_id):
                    raise asyncio.CancelledError("Translation cancelled by user.")
                last_ex: Optional[Exception] = None
                translated_b = ""
                # Retry once after a short cooldown if transient 429/503 hit all models
                for retry_round in range(2):
                    try:
                        translated_b = await _translate_items_reliably(b_items, prev_tail=prev_tail)
                        last_ex = None
                        break
                    except (PermissionError, DailyQuotaExhaustedError) as p_or_q:
                        if isinstance(p_or_q, DailyQuotaExhaustedError) and quota_behavior == "fallback":
                            logger.warning(
                                f"[{job_id}] Gemini Daily Quota exhausted on batch {b_idx + 1}/{total_batches}. "
                                f"quota_behavior='fallback' -> Seamlessly switching this batch and subsequent batches to free translation engine..."
                            )
                            last_ex = p_or_q
                            break
                        raise
                    except Exception as ex:
                        last_ex = ex
                        if retry_round == 0 and any(k in str(ex) for k in ("429", "503", "500", "502", "504", "timed out")):
                            logger.info(f"[{job_id}] Direct AI batch {b_idx+1}/{total_batches} transient error, cooling down 4s before retry...")
                            await asyncio.sleep(4.0)
                            continue
                        break

                if last_ex is None and translated_b:
                    results[b_idx] = translated_b
                    checkpoint_data["batches"][str(b_idx)] = translated_b
                    _save_cp()
                else:
                    logger.warning(f"[{job_id}] Direct AI batch {b_idx+1}/{total_batches} failed: {last_ex}")
                    # Fallback to standard translator for just this batch
                    from backend.translator import _translate_with_retry
                    fallback_parts = []
                    for pn, txt in b_items:
                        tr_p = await _translate_with_retry(txt, source_lang, target_lang) if txt else ""
                        fallback_parts.append(f"=== PAGE {pn} ===\n{tr_p}")
                    results[b_idx] = "\n\n".join(fallback_parts)
                    checkpoint_data["batches"][str(b_idx)] = results[b_idx]
                    _save_cp()

            completed += 1
            pages_done += len(b_items)
            pct = 8 + int((completed / total_batches) * 85)
            step_msg = (
                f"Single-Pass AI Translation & Polish: batch {completed}/{total_batches} ({pages_done}/{total_pages} pages)..."
                if last_ex is None
                else f"⚠️ Όριο Gemini: Αυτόματη συνέχιση με δωρεάν μηχανή (batch {completed}/{total_batches})..."
            )
            update_job(
                job_id,
                done_chunks=completed,
                total_chunks=total_batches,
                done_pages=pages_done,
                total_pages=total_pages,
                progress=pct,
                current_step=step_msg,
            )

        await asyncio.gather(*(_worker(i, b) for i, b in enumerate(batches)))

    if checkpoint_file.exists():
        try:
            checkpoint_file.unlink(missing_ok=True)
        except Exception:
            pass

    dedup_results: list[str] = []
    for res_idx, r in enumerate(results):
        if not r or not r.strip():
            continue
        first_pn = batches[res_idx][0][0] if batches[res_idx] else None
        prev_r = dedup_results[-1] if dedup_results else ""
        cleaned_r = _deduplicate_batch_boundary(prev_r, r.strip(), expected_first_page=first_pn)
        if cleaned_r:
            dedup_results.append(cleaned_r)

    final_text = "\n\n".join(dedup_results)
    final_text = sanitize_ai_output(final_text)
    final_text = apply_glossary(final_text, target_lang, style=style)
    if target_lang.lower() in ("greek", "el"):
        from backend.typography import format_greek_typography
        final_text = format_greek_typography(final_text)

    Path(output_path).write_text(final_text, encoding="utf-8")
    update_job(job_id, progress=95, current_step="Finalizing AI translated document...", output_path=output_path)
    logger.info(f"[{job_id}] Single-Pass Direct AI Translation complete -> {output_path}")
    return output_path
