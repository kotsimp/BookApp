"""
ai_polisher.py - AI-Powered Translation Proofreading & Refinement using Gemini API.
Polishes machine-translated Greek text into natural, grammatically flawless,
and stylistically appropriate language (formal administrative, technical, or natural).
"""

import os
import re
import logging
import asyncio
import aiohttp
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

STYLE_PROMPTS = {
    "literature": (
        "Είσαι βραβευμένος λογοτεχνικός μεταφραστής και επιμελητής εκδόσεων με εξειδίκευση στη σύγχρονη ξένη λογοτεχνία και την επιστημονική φαντασία (sci-fi / fiction). "
        "Βελτίωσε και επιμελήσου την ακόλουθη ελληνική μετάφραση ώστε να αποκτήσει εξαιρετική λογοτεχνική ποιότητα, φυσικότητα και ατμοσφαιρικό βάθος: "
        "1. Εξάλειψε τις μηχανικές/κατά λέξη μεταφράσεις, τις αγγλικούρες και τις συντακτικές αδεξιότητες (π.χ. 'να διαχειριστής' -> 'να διαχειριστείς/να αντιμετωπίσεις'). "
        "2. Χρησιμοποίησε πλούσιο, εκφραστικό ελληνικό λεξιλόγιο, διατηρώντας το ύφος, την ένταση και τον λογοτεχνικό ρυθμό του συγγραφέα. "
        "3. Διόρθωσε γραμματικά, συντακτικά και πτωτικά λάθη, αποδίδοντας τους διαλόγους με ζωντάνια και φυσικότητα. "
        "4. Διατήρησε ΑΠΑΡΑΛΛΑΧΤΗ τη δομή των παραγράφων και όλους τους δείκτες σελίδων (π.χ. === PAGE X ===) ακριβώς στις θέσεις τους. "
        "5. Μην προσθέτεις εισαγωγικά σχόλια, επεξηγήσεις ή σημειώσεις. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το διορθωμένο λογοτεχνικό κείμενο."
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
        "You are an expert audiobook script editor. Prepare the following text (keep its original language — Greek stays Greek, English stays English; do NOT translate) "
        "so that a neural text-to-speech voice reads it with natural human storytelling flow: "
        "1. Expand abbreviations into full spoken words (e.g., π.χ. -> για παράδειγμα, κ.λπ. -> και λοιπά, αρ. πρωτ. -> αριθμός πρωτοκόλλου, e.g. -> for example, etc. -> et cetera). "
        "2. Remove non-spoken artifacts such as footnote numbers [1], page markers (=== PAGE X ===), raw URLs, and broken line-wrap hyphens. "
        "3. Smooth awkward parentheses, slashes, and dense clauses using natural commas and periods so the narrator breathes and pauses naturally. "
        "4. Preserve all paragraph and verse breaks and keep the exact meaning. Return ONLY the polished spoken script with no commentary."
    ),
}

# Cached discoveries to avoid querying Google ModelService on every single page
_CACHED_WORKING_MODEL: Optional[str] = None
_CACHED_AVAILABLE_MODELS: Optional[list[str]] = None

EXCLUDE_PATTERNS = [
    "-tts", "-image", "-audio", "-transcribe", "clip", "banana",
    "robotics", "customtools", "computer-use", "argon",
    "lyria", "deep-research", "antigravity", "veo", "imagen", "embedding",
]

PREFERRED_FLASH_MODELS = [
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash-002",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-pro-latest",
    "gemini-2.5-pro",
    "gemini-1.5-pro",
]


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
                    # Skip audio/image/specialized models
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
    progress_callback: Optional[Callable[[int, int], Any]] = None,
) -> str:
    """
    Polishes and proofreads translated text using Google's Gemini API.
    Splits into manageable chunks/pages if multiple pages are present,
    reporting real-time progress through progress_callback.
    """
    from backend.settings_manager import get_setting
    key = api_key or os.environ.get("GEMINI_API_KEY") or get_setting("gemini_api_key")
    if not key:
        raise ValueError("Missing Gemini API Key. Please provide a key in settings.")

    system_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS.get("literature" if style == "literature" else "formal"))
    # Semaphore of 2 with pacing to respect Gemini Free Tier 15 RPM limits cleanly
    sem = asyncio.Semaphore(2)
    client_timeout = aiohttp.ClientTimeout(total=60)

    async def _run_progress(done_count: int, total_count: int) -> None:
        if not progress_callback:
            return
        try:
            res = progress_callback(done_count, total_count)
            if asyncio.iscoroutine(res):
                await res
        except Exception as ex:
            logger.warning(f"Progress callback error: {ex}")

    # If document has multiple pages marked by dividers, group into smart multi-page batches
    page_sections = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
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
            # This turns 340 requests into ~50, reducing API calls by 80% and giving Gemini broader narrative context
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

            async def _polish_batch(b_idx: int, batch_items: list[tuple[str, str]]) -> None:
                nonlocal completed, first_error
                batch_text = "\n\n".join(
                    f"{m}\n\n{c}" if m else c for m, c in batch_items
                )
                async with sem:
                    try:
                        polished = await _call_gemini_api(batch_text.strip(), key, system_instruction, session=session)
                        polished_batches[b_idx] = polished
                    except PermissionError:
                        raise
                    except Exception as ex:
                        if first_error is None:
                            first_error = ex
                        logger.warning(f"Batch {b_idx + 1}/{total_batches} polish failed (keeping original text): {ex}")
                        polished_batches[b_idx] = batch_text
                    # Pacing delay between batches
                    await asyncio.sleep(1.5)

                completed += 1
                await _run_progress(completed, total_batches)

            await asyncio.gather(*(_polish_batch(i, b) for i, b in enumerate(batches)))
            if all(not p for p in polished_batches) and first_error is not None:
                raise first_error
            return "\n\n".join(p for p in polished_batches if p)

        # For un-paginated text (e.g. Audiobook / DOCX), chunk long inputs (~6000 chars) and polish
        if len(text) > 4000:
            from backend.parsers import split_into_chunks
            chunks = split_into_chunks(text, 6000)
            total_chunks = max(1, len(chunks))
            polished_chunks = list(chunks)
            completed = 0
            succeeded = 0
            first_error: Optional[Exception] = None

            async def _polish_chunk(c_idx: int, c_text: str) -> None:
                nonlocal completed, succeeded, first_error
                async with sem:
                    try:
                        polished_chunks[c_idx] = await _call_gemini_api(c_text, key, system_instruction, session=session)
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

            await asyncio.gather(*(_polish_chunk(i, c) for i, c in enumerate(chunks)))
            if succeeded == 0 and first_error is not None:
                raise first_error
            return "\n\n".join(p for p in polished_chunks if p)

        await _run_progress(1, 1)
        return await _call_gemini_api(text, key, system_instruction, session=session)


async def _call_gemini_api(
    content_text: str,
    api_key: str,
    system_prompt: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    """Invokes Gemini generateContent with auto-discovery prioritizing ultra-fast Flash models."""
    if api_key.startswith("AQ.Test") or api_key.startswith("AIzaTest"):
        logger.info("Test API key detected - returning mock polished text.")
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
            for attempt in range(4):
                try:
                    async with session.post(url, json=payload, headers=headers) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            cand_list = result.get("candidates", [])
                            if not cand_list:
                                break
                            polished = cand_list[0]["content"]["parts"][0]["text"].strip()
                            _CACHED_WORKING_MODEL = model
                            logger.info(f"Gemini API success using model: {model}")
                            return polished
                        elif resp.status in (401, 403):
                            err_text = await resp.text()
                            raise PermissionError(f"Gemini API authentication error ({resp.status}): {err_text}")
                        elif resp.status == 404:
                            logger.debug(f"Model {model} returned 404, trying next...")
                            break
                        elif resp.status in (429, 500, 502, 503, 504):
                            err_text = await resp.text()
                            last_error = f"Gemini API error ({resp.status}): {err_text}"
                            logger.warning(f"Model {model} transient error (attempt {attempt + 1}/4): {last_error}")
                            if attempt < 3:
                                wait_time = 12.0 * (attempt + 1) if resp.status == 429 else 2.0 * (attempt + 1)
                                logger.info(f"Backing off for {wait_time:.1f}s before retrying {model}...")
                                await asyncio.sleep(wait_time)
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
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Call to {model} failed (attempt {attempt + 1}/4): {e}")
                    if attempt < 3:
                        await asyncio.sleep(2.0 * (attempt + 1))

        raise RuntimeError(last_error or "All Gemini candidate models failed.")
    finally:
        if owns_session:
            await session.close()
