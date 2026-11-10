"""
ai_polisher.py - AI-Powered Translation Proofreading & Refinement using Gemini API.
Polishes machine-translated Greek text into natural, grammatically flawless,
and stylistically appropriate language (formal administrative, technical, or natural).
"""

import os
import re
import json
import logging
import aiohttp
from typing import Optional

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
}


async def polish_text_with_gemini(
    text: str,
    api_key: Optional[str] = None,
    style: str = "formal",
    original_text: Optional[str] = None,
) -> str:
    """
    Polishes and proofreads translated text using Google's Gemini API.
    Splits into manageable chunks if text is very large.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("Missing Gemini API Key. Please provide a key in settings.")

    system_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["formal"])

    # If document has multiple pages marked by dividers, polish section by section
    page_sections = re.split(r"(={3,}\s*PAGE\s+\d+\s*={3,})", text)
    if len(page_sections) > 1:
        polished_parts = []
        for part in page_sections:
            if re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", part.strip()):
                polished_parts.append(part)
            elif part.strip():
                polished = await _call_gemini_api(part.strip(), key, system_instruction)
                polished_parts.append(polished)
            else:
                polished_parts.append(part)
        return "\n\n".join(polished_parts)

    return await _call_gemini_api(text, key, system_instruction)


_CACHED_WORKING_MODEL: Optional[str] = None


async def _get_available_models(api_key: str, session: aiohttp.ClientSession) -> list[str]:
    """Queries Gemini ModelService to get the exact list of supported models for this API key."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                models = data.get("models", [])
                valid_models = [
                    m["name"].replace("models/", "")
                    for m in models
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                logger.info(f"Discovered {len(valid_models)} Gemini models: {valid_models}")
                return valid_models
            else:
                err = await resp.text()
                logger.warning(f"Could not list models ({resp.status}): {err}")
    except Exception as e:
        logger.warning(f"Error querying Gemini ModelService: {e}")
    return []


async def _call_gemini_api(content_text: str, api_key: str, system_prompt: str) -> str:
    """Invokes Gemini generateContent with auto-discovery of supported models and resilient fallback."""
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

    async with aiohttp.ClientSession() as session:
        # 1. Determine candidate models
        candidates = []
        if _CACHED_WORKING_MODEL:
            candidates.append(_CACHED_WORKING_MODEL)

        discovered = await _get_available_models(api_key, session)
        if discovered:
            # Sort with preferred flash models first
            preferences = [
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-2.0-flash-exp",
                "gemini-1.5-flash-002",
                "gemini-1.5-flash-latest",
                "gemini-1.5-flash",
                "gemini-2.5-pro",
                "gemini-1.5-pro",
            ]
            for pref in preferences:
                if pref in discovered and pref not in candidates:
                    candidates.append(pref)
            for m in discovered:
                if m not in candidates:
                    candidates.append(m)

        # Fallback list if discovery returned nothing
        fallback_list = [
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-1.5-flash-002",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash",
            "gemini-pro",
        ]
        for fb in fallback_list:
            if fb not in candidates:
                candidates.append(fb)

        last_error = None
        for model in candidates:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
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
                        logger.info(f"Model {model} returned 404, trying next candidate...")
                        continue
                    else:
                        err_text = await resp.text()
                        last_error = f"Gemini API error ({resp.status}): {err_text}"
                        logger.warning(f"Model {model} failed: {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Call to {model} failed: {e}")

        raise RuntimeError(last_error or "All Gemini candidate models failed.")
