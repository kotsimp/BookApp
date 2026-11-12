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
    "natural": (
        "Είσαι έμπειρος φιλόλογος και επιμελητής εκδόσεων. Βελτίωσε την ακόλουθη ελληνική μετάφραση "
        "ώστε να αποκτήσει απόλυτα φυσική ροή, εκφραστικό πλούτο και ομαλότητα σαν να γράφτηκε εξαρχής στα Ελληνικά: "
        "1. Εξομάλυνε τη σύνταξη και διόρθωσε κάθε γραμματική ατέλεια. "
        "2. Διατήρησε απόλυτα όλες τις παραγράφους, επικεφαλίδες και δομή του πρωτοτύπου. "
        "3. Επίστρεψε ΜΟΝΟ το διορθωμένο κείμενο."
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
    "robotics", "customtools", "computer-use", "argon"
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

    system_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["formal"])

    # If document has multiple pages marked by dividers, polish section by section
    page_sections = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    if len(page_sections) > 1:
        # Filter content pages to polish
        content_items = [
            (idx, part) for idx, part in enumerate(page_sections)
            if not re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", part.strip()) and part.strip()
        ]
        total_pages = max(1, len(content_items))
        polished_parts = list(page_sections)

        for current_idx, (orig_idx, part_text) in enumerate(content_items, start=1):
            if progress_callback:
                try:
                    res = progress_callback(current_idx, total_pages)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as ex:
                    logger.warning(f"Progress callback error: {ex}")

            logger.info(f"Polishing page {current_idx} of {total_pages}...")
            polished = await _call_gemini_api(part_text.strip(), key, system_instruction)
            polished_parts[orig_idx] = polished

        return "\n\n".join(polished_parts)

    if progress_callback:
        try:
            res = progress_callback(1, 1)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass

    return await _call_gemini_api(text, key, system_instruction)


async def _call_gemini_api(content_text: str, api_key: str, system_prompt: str) -> str:
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

    # Set 30s timeout so we never hang indefinitely on slow models
    client_timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
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
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        cand_list = result.get("candidates", [])
                        if not cand_list:
                            continue
                        polished = cand_list[0]["content"]["parts"][0]["text"].strip()
                        _CACHED_WORKING_MODEL = model
                        logger.info(f"Gemini API success using model: {model}")
                        return polished
                    elif resp.status == 404:
                        logger.debug(f"Model {model} returned 404, trying next...")
                        continue
                    else:
                        err_text = await resp.text()
                        last_error = f"Gemini API error ({resp.status}): {err_text}"
                        logger.warning(f"Model {model} failed: {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Call to {model} failed: {e}")

        raise RuntimeError(last_error or "All Gemini candidate models failed.")
