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
import logging
import asyncio
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
        "3. ΖΩΝΤΑΝΙΑ ΔΙΑΛΟΓΩΝ & ΣΤΙΞΗ: "
        "   - Απόδωσε τους διαλόγους με προφορική ζωντάνια και φυσικότητα. Διατήρησε τις παύλες διαλόγων (—) ή τα εισαγωγικά («...») σύμφωνα με τις ελληνικές εκδοτικές συμβάσεις. "
        "   - Διόρθωσε όλα τα γραμματικά, συντακτικά και πτωτικά λάθη. "
        "4. ΔΙΑΤΗΡΗΣΗ ΔΟΜΗΣ & ΔΕΙΚΤΩΝ: "
        "   - Διατήρησε ΑΠΑΡΑΛΛΑΧΤΗ τη δομή των παραγράφων, τα κενά σκηνών (π.χ. * * *) και όλους τους δείκτες σελίδων (π.χ. === PAGE X ===) ακριβώς στις θέσεις τους. "
        "5. Μην προσθέτεις εισαγωγικά σχόλια, προοίμια ή επεξηγηματικές σημειώσεις. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το διορθωμένο λογοτεχνικό κείμενο."
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


EXCLUDE_PATTERNS = [
    "-tts", "-image", "-audio", "-transcribe", "clip", "banana",
    "robotics", "customtools", "computer-use", "argon",
    "lyria", "deep-research", "antigravity", "veo", "imagen", "embedding",
]

PREFERRED_FLASH_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash-002",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-pro-latest",
    "gemini-2.5-pro",
    "gemini-1.5-pro",
]


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
    Extracts a concise glossary of recurring characters, places, and sci-fi/technical terms
    to ensure uniform transliteration across all batches of a book or long document.
    """
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        return "- Keeton -> Κίτον\n- Theseus -> Θησέας\n- Rorschach -> Ρόρσαχ"

    prompt = (
        "Είσαι έμπειρος επιμελητής εκδόσεων και λογοτεχνικός μεταφραστής. Αναλύοντας το παρακάτω δείγμα κειμένου, "
        "εντόπισε τα κυριότερα επαναλαμβανόμενα κύρια ονόματα (χαρακτήρες, διαστημόπλοια, εξωγήινες οντότητες, "
        "τοπωνύμια) και εξειδικευμένους όρους. Δημιούργησε ένα συνοπτικό Μητρώο Ονομάτων & Ορολογίας (Entity Dossier) "
        "με την ορθή, ενιαία απόδοσή τους στα Ελληνικά (φωνητική μεταγραφή ή απόδοση). "
        "Μορφή κάθε γραμμής: '- Original Name -> Ελληνική Απόδοση'. "
        "Περιόρισε το μητρώο στους 20-30 πιο κρίσιμους όρους. Μην προσθέτεις εισαγωγικά σχόλια."
    )
    try:
        sample = sample_text[:18000]
        dossier = await _call_gemini_api(sample, api_key, prompt, session=session)
        if dossier and len(dossier.strip()) > 10:
            logger.info(f"Generated Entity Dossier ({len(dossier)} chars)")
            return dossier.strip()
    except Exception as ex:
        logger.warning(f"Entity dossier extraction skipped: {ex}")
    return ""


async def _get_available_models(api_key: str, session: aiohttp.ClientSession) -> list[str]:
    """Queries Gemini ModelService to get supported text-generation models for this API key."""
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        return ["gemini-flash-latest", "gemini-2.5-flash-lite"]

    global _CACHED_AVAILABLE_MODELS
    if _CACHED_AVAILABLE_MODELS:
        return _CACHED_AVAILABLE_MODELS

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
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
) -> str:
    """
    Polishes and proofreads translated text using Google's Gemini API.
    Supports multi-page smart batching, bilingual source-anchored verification,
    character consistency dossier, rolling narrative context, and disk checkpointing.
    """
    from backend.settings_manager import get_setting
    key = api_key or os.environ.get("GEMINI_API_KEY") or get_setting("gemini_api_key")
    if not key:
        raise ValueError("Missing Gemini API Key. Please provide a key in settings.")

    base_system_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["formal"])
    sem = asyncio.Semaphore(5)
    client_timeout = aiohttp.ClientTimeout(total=90)

    # Disk Checkpoint setup
    checkpoint_file: Optional[Path] = None
    checkpoint_data: dict[str, Any] = {"batches": {}, "chunks": {}}
    if job_id:
        out_dir = Path("temp/outputs") / job_id
        if out_dir.exists():
            checkpoint_file = out_dir / ".polish_checkpoint.json"
            if checkpoint_file.is_file():
                try:
                    loaded = json.loads(checkpoint_file.read_text(encoding="utf-8"))
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
            try:
                checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False), encoding="utf-8")
            except Exception as ex:
                logger.warning(f"Could not write polish checkpoint: {ex}")

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

        # Inject contextually-relevant user glossary rules
        from backend.glossary import load_glossary, apply_glossary
        glossary_items = load_glossary()
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

            # Smart Multi-Page Batching: group ~5 pages (or ~7,500 chars) per Gemini call for optimal latency
            batches = []
            curr_b = []
            curr_chars = 0
            MAX_BATCH_CHARS = 7500
            MAX_BATCH_PAGES = 5

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

            total_batches = max(1, len(batches))
            polished_batches = ["" for _ in batches]
            completed = 0
            first_error: Optional[Exception] = None

            # Pre-fill batches already present in checkpoint
            cached_batches = checkpoint_data.get("batches", {})
            for b_idx in range(total_batches):
                b_str = str(b_idx)
                if b_str in cached_batches and cached_batches[b_str].strip():
                    polished_batches[b_idx] = cached_batches[b_str]
                    completed += 1

            if completed > 0:
                await _run_progress(completed, total_batches)

            async def _polish_batch(b_idx: int, batch_items: list[tuple[str, str]]) -> None:
                nonlocal completed, first_error
                if polished_batches[b_idx]:
                    return  # Already restored from checkpoint

                draft_batch_text = "\n\n".join(
                    f"{m}\n\n{c}" if m else c for m, c in batch_items
                )

                # Bilingual Source Anchoring: align original pages for this batch
                source_batch_parts = []
                if orig_pages and use_source_anchoring:
                    for m, _ in batch_items:
                        pm = re.match(r"^={3,}\s*PAGE\s+(\d+)\s*={3,}$", m)
                        if pm:
                            pn = int(pm.group(1))
                            if pn in orig_pages:
                                source_batch_parts.append(f"=== PAGE {pn} ===\n{orig_pages[pn]}")

                # Build input content with source reference and rolling context
                content_components = []
                if b_idx > 0:
                    prev_draft = batches[b_idx - 1][-1][1]
                    paras = [p.strip() for p in prev_draft.split("\n\n") if p.strip()]
                    if paras:
                        snippet = paras[-1][:350]
                        content_components.append(
                            f"--- ΠΡΟΗΓΟΥΜΕΝΟ ΑΠΟΣΠΑΣΜΑ (ΜΟΝΟ ΓΙΑ ΣΥΝΕΧΕΙΑ & ΡΟΗ - ΜΗΝ ΤΟ ΣΥΜΠΕΡΙΛΑΒΕΙΣ ΣΤΗΝ ΕΞΟΔΟ) ---\n[... {snippet}]"
                        )

                if source_batch_parts:
                    orig_source_block = "\n\n".join(source_batch_parts)
                    content_components.append(
                        f"--- ΠΡΩΤΟΤΥΠΟ ΚΕΙΜΕΝΟ ΑΝΑΦΟΡΑΣ (SOURCE REFERENCE) ---\n{orig_source_block}"
                    )
                    content_components.append(
                        f"--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n{draft_batch_text}"
                    )
                else:
                    content_components.append(draft_batch_text)

                prompt_content = "\n\n".join(content_components)

                batch_instruction = system_instruction
                if source_batch_parts:
                    batch_instruction += (
                        "\n\n--- ΟΔΗΓΙΑ ΔΙΓΛΩΣΣΗΣ ΕΠΑΛΗΘΕΥΣΗΣ ---\n"
                        "Σου παρέχεται το Πρωτότυπο Κείμενο Αναφοράς καθώς και το Προσχέδιο Ελληνικής Μετάφρασης. "
                        "Χρησιμοποίησε το πρωτότυπο κείμενο για να διορθώσεις τυχόν παρανοήσεις, αγγλισμούς ή παραλείψεις του προσχεδίου. "
                        "Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το τελικό διορθωμένο ελληνικό κείμενο, διατηρώντας ΑΠΑΡΑΛΛΑΧΤΟΥΣ όλους τους δείκτες σελίδων === PAGE X ===."
                    )

                async with sem:
                    try:
                        polished = await _call_gemini_api(prompt_content.strip(), key, batch_instruction, session=session, temperature=target_temp)
                        polished_batches[b_idx] = polished
                        checkpoint_data["batches"][str(b_idx)] = polished
                        _save_checkpoint()
                    except PermissionError:
                        raise
                    except Exception as ex:
                        if first_error is None:
                            first_error = ex
                        logger.warning(f"Batch {b_idx + 1}/{total_batches} polish failed (keeping original text): {ex}")
                        polished_batches[b_idx] = draft_batch_text

                completed += 1
                await _run_progress(completed, total_batches)

            # Process remaining batches
            pending_batches = [(i, b) for i, b in enumerate(batches) if not polished_batches[i]]
            if pending_batches:
                await asyncio.gather(*(_polish_batch(i, b) for i, b in pending_batches))

            if all(not p for p in polished_batches) and first_error is not None:
                raise first_error

            final_batches = []
            for b_idx, p in enumerate(polished_batches):
                if p and p.strip():
                    final_batches.append(p.strip())
                else:
                    orig_fallback = "\n\n".join(
                        f"{m}\n\n{c}" if m else c for m, c in batches[b_idx]
                    )
                    final_batches.append(orig_fallback)

            # Clean up checkpoint on complete success
            if checkpoint_file and checkpoint_file.exists():
                try:
                    checkpoint_file.unlink(missing_ok=True)
                except Exception:
                    pass

            return apply_glossary("\n\n".join(final_batches), "greek")

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

            async def _polish_chunk(c_idx: int, c_text: str) -> None:
                nonlocal completed, succeeded, first_error
                if str(c_idx) in cached_chunks and cached_chunks[str(c_idx)].strip():
                    return

                chunk_content = c_text
                if c_idx > 0:
                    prev_chunk = chunks[c_idx - 1]
                    paras = [p.strip() for p in prev_chunk.split("\n\n") if p.strip()]
                    if paras:
                        snippet = paras[-1][:250]
                        chunk_content = (
                            f"--- ΠΡΟΗΓΟΥΜΕΝΟ ΑΠΟΣΠΑΣΜΑ (ΜΟΝΟ ΓΙΑ ΣΥΝΕΧΕΙΑ & ΡΟΗ - ΜΗΝ ΤΟ ΣΥΜΠΕΡΙΛΑΒΕΙΣ) ---\n[... {snippet}]\n\n"
                            + chunk_content
                        )

                async with sem:
                    try:
                        polished_chunks[c_idx] = await _call_gemini_api(chunk_content, key, system_instruction, session=session, temperature=target_temp)
                        checkpoint_data["chunks"][str(c_idx)] = polished_chunks[c_idx]
                        _save_checkpoint()
                        succeeded += 1
                    except PermissionError:
                        raise
                    except Exception as ex:
                        if first_error is None:
                            first_error = ex
                        logger.warning(f"Chunk {c_idx + 1}/{total_chunks} polish failed (keeping original chunk): {ex}")
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

            final_res = apply_glossary("\n\n".join(p for p in polished_chunks if p), "greek")
            from backend.typography import format_greek_typography
            return format_greek_typography(final_res)

        await _run_progress(1, 1)
        single_input = text
        if original_text and use_source_anchoring:
            single_input = (
                f"--- ΠΡΩΤΟΤΥΠΟ ΚΕΙΜΕΝΟ ΑΝΑΦΟΡΑΣ (SOURCE REFERENCE) ---\n{original_text}\n\n"
                f"--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n{text}"
            )
        polished_single = await _call_gemini_api(single_input, key, system_instruction, session=session, temperature=target_temp)
        from backend.typography import format_greek_typography
        return format_greek_typography(apply_glossary(polished_single, "greek"))


# Alias for concise invocation
polish_text = polish_text_with_gemini


async def _call_gemini_api(
    content_text: str,
    api_key: str,
    system_prompt: str,
    session: Optional[aiohttp.ClientSession] = None,
    temperature: float = 0.25,
) -> str:
    """Invokes Gemini generateContent with cache, auto-discovery prioritizing ultra-fast Flash models."""
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        logger.info("Test API key detected - returning mock polished text.")
        if "--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n" in content_text:
            draft_part = content_text.split("--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n")[-1]
            return f"[Επιμελημένο AI]: {draft_part.strip()}"
        return f"[Επιμελημένο AI]: {content_text}"

    # Check cache first
    cache_key = None
    try:
        from backend.database import compute_cache_key, db_get_cached_translation, db_set_cached_translation
        cache_key = compute_cache_key(content_text, "draft", "greek", engine="gemini_polish", extra=f"{system_prompt[:50]}:{temperature}")
        cached_result = db_get_cached_translation(cache_key)
        if cached_result is not None:
            logger.info("Retrieved AI polished chunk directly from SQLite cache.")
            return cached_result
    except Exception as ex:
        logger.debug(f"Polish cache check skipped: {ex}")

    global _CACHED_WORKING_MODEL

    payload = {
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
            "maxOutputTokens": 8192,
        }
    }

    # Reuse caller's session if provided, otherwise open a temporary one
    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45))
    try:
        candidates = []

        # If a fast working model was already cached (and is not slow gemma), try it first
        if _CACHED_WORKING_MODEL and not _CACHED_WORKING_MODEL.startswith("gemma"):
            candidates.append(_CACHED_WORKING_MODEL)

        discovered = await _get_available_models(api_key, session)
        if discovered:
            # 1. Preferred Flash models first
            for pref in PREFERRED_FLASH_MODELS:
                if pref in discovered and pref not in candidates:
                    candidates.append(pref)

            # 2. Other non-gemma models
            for m in discovered:
                if not m.startswith("gemma") and m not in candidates:
                    candidates.append(m)

            # 3. Gemma models as last resort
            for m in discovered:
                if m.startswith("gemma") and m not in candidates:
                    candidates.append(m)
        else:
            for fb in PREFERRED_FLASH_MODELS:
                if fb not in candidates:
                    candidates.append(fb)

        last_error = None
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        for model in candidates:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            # Build model-specific payload: disable hidden thinking tokens on 2.5 Flash for 3x-4x speedup
            use_no_thinking = ("2.5-flash" in model or "flash-latest" in model) and "pro" not in model
            req_payload = payload
            if use_no_thinking:
                req_payload = {
                    "contents": payload["contents"],
                    "generationConfig": {
                        **payload["generationConfig"],
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                }

            max_attempts = 2
            for attempt in range(max_attempts):
                try:
                    req_timeout = aiohttp.ClientTimeout(total=45)
                    async with session.post(url, json=req_payload, headers=headers, timeout=req_timeout) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            cand_list = result.get("candidates", [])
                            if not cand_list:
                                break
                            parts = cand_list[0].get("content", {}).get("parts", [])
                            if not parts:
                                logger.warning(f"Model {model} candidate returned no content parts (finishReason: {cand_list[0].get('finishReason')})")
                                break
                            polished = parts[0].get("text", "").strip()
                            if not polished:
                                break
                            _CACHED_WORKING_MODEL = model
                            logger.info(f"Gemini API success using model: {model}")
                            if cache_key:
                                try:
                                    from backend.database import db_set_cached_translation
                                    db_set_cached_translation(cache_key, content_text, polished, "draft", "greek", engine="gemini_polish")
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
                            # High demand / server overloaded: Fail over immediately to the next candidate model
                            err_text = await resp.text()
                            last_error = f"Gemini API error ({resp.status}): {err_text}"
                            logger.info(f"Model {model} overloaded/unavailable ({resp.status}). Immediately trying next candidate...")
                            if _CACHED_WORKING_MODEL == model:
                                _CACHED_WORKING_MODEL = None
                            break
                        elif resp.status == 429:
                            err_text = await resp.text()
                            last_error = f"Gemini API error (429): {err_text}"
                            logger.warning(f"Model {model} rate limited (attempt {attempt + 1}/{max_attempts}): {last_error}")
                            if attempt < max_attempts - 1:
                                await asyncio.sleep(2.5)
                                continue
                            break
                        else:
                            err_text = await resp.text()
                            # If model rejected thinkingConfig, retry cleanly without it
                            if resp.status == 400 and "thinking" in err_text.lower() and req_payload is not payload:
                                req_payload = payload
                                continue
                            last_error = f"Gemini API error ({resp.status}): {err_text}"
                            if resp.status == 400 and "API_KEY_INVALID" in err_text:
                                raise PermissionError(last_error)
                            logger.warning(f"Model {model} failed: {last_error}")
                            break
                except PermissionError:
                    raise
                except asyncio.TimeoutError:
                    logger.warning(f"Model {model} timed out after 45s. Switching immediately to next candidate...")
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
        f"Μην παραλείπεις καμία παράγραφο ή πρόταση. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ τη μετάφραση χωρίς σχόλια."
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

    # Group pages into ~7,500-char / max 5-page batches
    batches: list[list[tuple[int, str]]] = []
    curr_b: list[tuple[int, str]] = []
    curr_chars = 0
    MAX_BATCH_CHARS = 7500
    MAX_BATCH_PAGES = 5

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

        # Inject matching glossary terms
        glossary_items = load_glossary()
        if glossary_items:
            lower_src = full_original.lower()
            matched = [(k, v) for k, v in glossary_items.items() if k.lower() in lower_src][:50]
            if matched:
                g_lines = "\n".join(f"- {k} -> {v}" for k, v in matched)
                system_instruction += (
                    "\n\n--- ΓΛΩΣΣΑΡΙΟ ΧΡΗΣΤΗ (GLOSSARY RULES) ---\n"
                    f"{g_lines}\n"
                )

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

            batch_src = "\n\n".join(f"=== PAGE {pn} ===\n{txt}" for pn, txt in b_items)
            content_parts = []
            if b_idx > 0:
                prev_txt = batches[b_idx - 1][-1][1]
                if prev_txt:
                    content_parts.append(
                        f"--- ΠΡΟΗΓΟΥΜΕΝΟ ΑΠΟΣΠΑΣΜΑ (ΜΟΝΟ ΓΙΑ ΣΥΝΕΧΕΙΑ - ΜΗΝ ΤΟ ΜΕΤΑΦΡΑΣΕΙΣ ΞΑΝΑ) ---\n[... {prev_txt[-300:]}]"
                    )
            content_parts.append(batch_src)
            prompt_text = "\n\n".join(content_parts)

            async with sem:
                if is_job_cancelled(job_id):
                    raise asyncio.CancelledError("Translation cancelled by user.")
                try:
                    translated_b = await _call_gemini_api(
                        prompt_text,
                        api_key,
                        system_instruction,
                        session=session,
                        temperature=target_temp,
                    )
                    results[b_idx] = translated_b
                    checkpoint_data["batches"][str(b_idx)] = translated_b
                    _save_cp()
                except PermissionError:
                    raise
                except Exception as ex:
                    logger.warning(f"[{job_id}] Direct AI batch {b_idx+1}/{total_batches} failed: {ex}")
                    # Fallback to standard translator for just this batch
                    from backend.translator import _translate_with_retry
                    fallback_parts = []
                    for pn, txt in b_items:
                        tr_p = await _translate_with_retry(txt, source_lang, target_lang) if txt else ""
                        fallback_parts.append(f"=== PAGE {pn} ===\n{tr_p}")
                    results[b_idx] = "\n\n".join(fallback_parts)

            completed += 1
            pages_done += len(b_items)
            pct = 8 + int((completed / total_batches) * 85)
            update_job(
                job_id,
                done_chunks=completed,
                total_chunks=total_batches,
                done_pages=pages_done,
                total_pages=total_pages,
                progress=pct,
                current_step=f"Single-Pass AI Translation & Polish: batch {completed}/{total_batches} ({pages_done}/{total_pages} pages)...",
            )

        await asyncio.gather(*(_worker(i, b) for i, b in enumerate(batches)))

    if checkpoint_file.exists():
        try:
            checkpoint_file.unlink(missing_ok=True)
        except Exception:
            pass

    final_text = "\n\n".join(r.strip() for r in results if r and r.strip())
    final_text = apply_glossary(final_text, target_lang)
    if target_lang.lower() in ("greek", "el"):
        from backend.typography import format_greek_typography
        final_text = format_greek_typography(final_text)

    Path(output_path).write_text(final_text, encoding="utf-8")
    update_job(job_id, progress=95, current_step="Finalizing AI translated document...", output_path=output_path)
    logger.info(f"[{job_id}] Single-Pass Direct AI Translation complete -> {output_path}")
    return output_path
