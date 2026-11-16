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
        "Είσαι κορυφαίος λογοτεχνικός μεταφραστής και επιμελητής εκδόσεων με εξειδίκευση στη σύγχρονη ξένη λογοτεχνία και την επιστημονική φαντασία (sci-fi / speculative fiction). "
        "Βελτίωσε και επιμελήσου την ακόλουθη ελληνική μετάφραση ώστε να αποκτήσει εξαιρετική λογοτεχνική ποιότητα, φυσικότητα και ατμοσφαιρικό βάθος: "
        "1. Εξάλειψε τις μηχανικές/κατά λέξη μεταφράσεις, τις αγγλικούρες και τις συντακτικές αδεξιότητες (π.χ. 'να διαχειριστής' -> 'να διαχειριστείς/να αντιμετωπίσεις'). "
        "2. Χρησιμοποίησε πλούσιο, εκφραστικό ελληνικό λεξιλόγιο, διατηρώντας το ύφος, την ένταση και τον λογοτεχνικό ρυθμό του συγγραφέα. "
        "3. Διόρθωσε γραμματικά, συντακτικά και πτωτικά λάθη, αποδίδοντας τους διαλόγους με ζωντάνια και φυσικότητα. "
        "4. Εάν παρέχεται το πρωτότυπο κείμενο αναφοράς, συμβουλέψου το για να επιλύσεις τυχόν μεταφραστικές παρανοήσεις ή αμφισημίες του προσχεδίου. "
        "5. Διατήρησε ΑΠΑΡΑΛΛΑΧΤΗ τη δομή των παραγράφων και όλους τους δείκτες σελίδων (π.χ. === PAGE X ===) ακριβώς στις θέσεις τους. "
        "6. Μην προσθέτεις εισαγωγικά σχόλια, επεξηγήσεις ή σημειώσεις. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το διορθωμένο λογοτεχνικό κείμενο."
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
}

# Cached discoveries to avoid querying Google ModelService on every single page
_CACHED_WORKING_MODEL: Optional[str] = None
_CACHED_AVAILABLE_MODELS: Optional[list[str]] = None


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
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
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
    sem = asyncio.Semaphore(2)
    client_timeout = aiohttp.ClientTimeout(total=60)

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

    # Parse original text pages for source anchoring if provided
    orig_pages: dict[int, str] = {}
    if original_text and use_source_anchoring:
        orig_pages = _parse_pages_dict(original_text)

    # If document has multiple pages marked by dividers, group into smart multi-page batches
    page_sections = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
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

            # Smart Multi-Page Batching: group ~5 pages (or ~10,000 chars) per Gemini call
            batches = []
            curr_b = []
            curr_chars = 0
            MAX_BATCH_CHARS = 10000
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
                        polished = await _call_gemini_api(prompt_content.strip(), key, batch_instruction, session=session)
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
                    # Pacing delay between batches
                    await asyncio.sleep(1.5)

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

            return "\n\n".join(final_batches)

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
                        polished_chunks[c_idx] = await _call_gemini_api(chunk_content, key, system_instruction, session=session)
                        checkpoint_data["chunks"][str(c_idx)] = polished_chunks[c_idx]
                        _save_checkpoint()
                        succeeded += 1
                    except PermissionError:
                        raise
                    except Exception as ex:
                        if first_error is None:
                            first_error = ex
                        logger.warning(f"Chunk {c_idx + 1}/{total_chunks} polish failed (keeping original chunk): {ex}")
                    await asyncio.sleep(1.5)
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

            return "\n\n".join(p for p in polished_chunks if p)

        await _run_progress(1, 1)
        single_input = text
        if original_text and use_source_anchoring:
            single_input = (
                f"--- ΠΡΩΤΟΤΥΠΟ ΚΕΙΜΕΝΟ ΑΝΑΦΟΡΑΣ (SOURCE REFERENCE) ---\n{original_text}\n\n"
                f"--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n{text}"
            )
        return await _call_gemini_api(single_input, key, system_instruction, session=session)


async def _call_gemini_api(
    content_text: str,
    api_key: str,
    system_prompt: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    """Invokes Gemini generateContent with auto-discovery prioritizing ultra-fast Flash models."""
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        logger.info("Test API key detected - returning mock polished text.")
        if "--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n" in content_text:
            draft_part = content_text.split("--- ΠΡΟΣΧΕΔΙΟ ΕΛΛΗΝΙΚΗΣ ΜΕΤΑΦΡΑΣΗΣ ΠΡΟΣ ΕΠΙΜΕΛΕΙΑ (DRAFT TO POLISH) ---\n")[-1]
            return f"[Επιμελημένο AI]: {draft_part.strip()}"
        return f"[Επιμελημένο AI]: {content_text}"

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
            "temperature": 0.2,
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
            # Keep attempts tight (max 2) with fast 15s timeout to failover instantly to other flash models
            max_attempts = 2
            for attempt in range(max_attempts):
                try:
                    req_timeout = aiohttp.ClientTimeout(total=15)
                    async with session.post(url, json=payload, headers=headers, timeout=req_timeout) as resp:
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
                                await asyncio.sleep(2.0)
                                continue
                            break
                        else:
                            err_text = await resp.text()
                            last_error = f"Gemini API error ({resp.status}): {err_text}"
                            if resp.status == 400 and "API_KEY_INVALID" in err_text:
                                raise PermissionError(last_error)
                            logger.warning(f"Model {model} failed: {last_error}")
                            break
                except PermissionError:
                    raise
                except asyncio.TimeoutError:
                    logger.warning(f"Model {model} timed out after 15s. Switching immediately to next candidate...")
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
