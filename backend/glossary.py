"""
glossary.py - Custom Terminology and Glossary Manager.
Provides regex-based boundary replacements for domain-specific terminology
(e.g., technical, administrative, educational).
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
GLOSSARY_FILE = CONFIG_DIR / "glossary.json"

# Default pre-populated glossary entries for Greek administrative & technical documents
DEFAULT_GLOSSARY: Dict[str, str] = {
    "Server Room": "Αίθουσα Διακομιστών (Server Room)",
    "server room": "αίθουσα διακομιστών",
    "File Server": "Διακομιστής Αρχείων (File Server)",
    "file server": "διακομιστής αρχείων",
    "in-house applications": "εσωτερικές εφαρμογές (in-house applications)",
    "In-house applications": "Εσωτερικές εφαρμογές (in-house applications)",
    "in house applications": "εσωτερικές εφαρμογές",
    "UPS": "Σύστημα Αδιάλειπτης Τροφοδοσίας (UPS)",
    "online double conversion": "online διπλής μετατροπής",
    "double conversion": "διπλής μετατροπής",
    "backup": "αντίγραφο ασφαλείας (backup)",
    "data loss": "απώλεια δεδομένων",
    "power outage": "διακοπή ρεύματος",
    "voltage fluctuations": "διακυμάνσεις τάσης",
}


def load_glossary() -> Dict[str, str]:
    """Loads glossary rules from file or returns default."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not GLOSSARY_FILE.exists():
        save_glossary(DEFAULT_GLOSSARY)
        return dict(DEFAULT_GLOSSARY)
    try:
        data = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning(f"Could not read glossary file: {e}")
    return dict(DEFAULT_GLOSSARY)


def save_glossary(glossary: Dict[str, str]):
    """Saves glossary rules to JSON file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    GLOSSARY_FILE.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")


def set_term(source: str, target: str):
    """Adds or updates a glossary term."""
    source = source.strip()
    target = target.strip()
    if not source:
        raise ValueError("Source term cannot be empty.")
    glossary = load_glossary()
    glossary[source] = target
    save_glossary(glossary)
    return glossary


def delete_term(source: str):
    """Deletes a glossary term."""
    glossary = load_glossary()
    if source in glossary:
        del glossary[source]
        save_glossary(glossary)
    return glossary


def apply_glossary(text: str, target_lang: str = "greek") -> str:
    """
    Applies glossary replacements to text using word-boundary substitutions.
    Sorted by term length descending so longer phrases match first.
    """
    if not text or target_lang.lower() not in ("greek", "el"):
        return text

    glossary = load_glossary()
    # Sort terms by length descending to prevent sub-string overlap
    sorted_terms = sorted(glossary.keys(), key=len, reverse=True)

    for term in sorted_terms:
        replacement = glossary[term]
        # Match term on word boundaries (case-sensitive or insensitive as defined)
        pattern = re.compile(rf"\b{re.escape(term)}\b")
        text = pattern.sub(replacement, text)

    return text
