"""
glossary.py - Custom Terminology and Categorized Glossary Manager.
Provides regex-based boundary replacements for domain-specific terminology
with distinct categorization (Technical, Literary, General).
"""

import os
import json
import re
import time
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"
GLOSSARY_FILE = CONFIG_DIR / "glossary.json"
_glossary_lock = threading.RLock()

CATEGORIES_META: Dict[str, Dict[str, str]] = {
    "technical": {
        "name": "Τεχνικοί Όροι (Technical)",
        "icon": "💻",
        "description": "Πληροφορική, AI, Machine Learning, Data Science, Software Engineering",
    },
    "literary": {
        "name": "Λογοτεχνικοί Όροι (Literary)",
        "icon": "📚",
        "description": "Ποίηση, Πεζογραφία, Αφηγηματολογία, Ρητορικά Σχήματα, Δράμα",
    },
    "general": {
        "name": "Γενικοί / Προσαρμοσμένοι Όροι (General)",
        "icon": "⚙️",
        "description": "Υποδομές, Γενική Ορολογία, Προσαρμοσμένοι όροι χρήστη",
    },
}

DEFAULT_GENERAL_GLOSSARY: Dict[str, str] = {
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


def _read_raw_file() -> Dict[str, Any]:
    """Reads glossary file from disk, migrating legacy flat format if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not GLOSSARY_FILE.exists():
        raw = {
            "_version": 2,
            "categories": CATEGORIES_META,
            "terms": {
                "technical": {},
                "literary": {},
                "general": dict(DEFAULT_GENERAL_GLOSSARY),
            },
        }
        _write_raw_file(raw)
        return raw

    try:
        data = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Check if this is the categorized v2 format
            if "terms" in data and isinstance(data["terms"], dict):
                return data

            # Legacy flat format: migrate into categorized structure
            logger.info("Migrating legacy flat glossary format to categorized v2 structure.")
            tech = {}
            lit = {}
            gen = {}
            for k, v in data.items():
                if k.startswith("_"):
                    continue
                # Simple heuristic if migrating old custom entries
                gen[k] = v

            migrated = {
                "_version": 2,
                "categories": CATEGORIES_META,
                "terms": {
                    "technical": tech,
                    "literary": lit,
                    "general": gen,
                },
            }
            _write_raw_file(migrated)
            return migrated
    except Exception as e:
        logger.warning(f"Could not read glossary file: {e}")

    return {
        "_version": 2,
        "categories": CATEGORIES_META,
        "terms": {
            "technical": {},
            "literary": {},
            "general": dict(DEFAULT_GENERAL_GLOSSARY),
        },
    }


def _write_raw_file(data: Dict[str, Any]) -> None:
    """Atomically writes categorized glossary structure to JSON file under lock."""
    with _glossary_lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = CONFIG_DIR / f"glossary_{os.getpid()}_{threading.get_ident()}.tmp"
        try:
            tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            for attempt in range(4):
                try:
                    os.replace(tmp_file, GLOSSARY_FILE)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink(missing_ok=True)
                except Exception:
                    pass


# IT / infrastructure terms that must NEVER be auto-substituted into literary fiction, poetry, or comics
_IT_GENERAL_BLOCKLIST = frozenset({
    "server room", "file server", "in-house applications", "in house applications",
    "ups", "online double conversion", "double conversion", "backup", "data loss",
    "power outage", "voltage fluctuations",
})


def load_glossary(category: Optional[str] = None, style: Optional[str] = None) -> Dict[str, str]:
    """
    Loads glossary terms as a flat source->target dictionary.
    If category is specified ('technical', 'literary', 'general'), returns only that subset.
    If style is specified ('literature', 'poetry', 'audiobook', 'comic'), excludes technical/IT terms
    so DevOps/Kubernetes vocabulary cannot corrupt literary prose or dialogue.
    If neither is specified (or category is 'all'), merges all categories.
    """
    data = _read_raw_file()
    raw_terms = data.get("terms")
    terms_by_cat = raw_terms if isinstance(raw_terms, dict) else {}

    def _safe_cat(name: str) -> Dict[str, str]:
        val = terms_by_cat.get(name)
        return val if isinstance(val, dict) else {}

    if category and category.lower() not in ("all", "*"):
        cat_key = category.lower()
        if cat_key == "literature":
            cat_key = "literary"
        return dict(_safe_cat(cat_key))

    style_low = (style or "").lower()
    if style_low in ("literature", "audiobook", "poetry", "comic", "graphic_novel"):
        merged: Dict[str, str] = {}
        for k, v in _safe_cat("general").items():
            if k.lower() not in _IT_GENERAL_BLOCKLIST:
                merged[k] = v
        merged.update(_safe_cat("literary"))
        return merged

    # Merge all categories (literary, general, technical)
    merged = {}
    for cat_name in ("literary", "general", "technical"):
        merged.update(_safe_cat(cat_name))
    return merged


def load_categorized_glossary() -> Dict[str, Any]:
    """
    Returns full categorized glossary metadata, category list with item counts,
    and a structured list of terms for the UI table.
    """
    data = _read_raw_file()
    raw_terms = data.get("terms")
    terms_by_cat = raw_terms if isinstance(raw_terms, dict) else {}

    tech_terms = terms_by_cat.get("technical") if isinstance(terms_by_cat.get("technical"), dict) else {}
    lit_terms = terms_by_cat.get("literary") if isinstance(terms_by_cat.get("literary"), dict) else {}
    gen_terms = terms_by_cat.get("general") if isinstance(terms_by_cat.get("general"), dict) else {}

    total_count = len(tech_terms) + len(lit_terms) + len(gen_terms)

    categories_list = [
        {"id": "all", "name": "Όλοι οι Όροι (All)", "icon": "🌐", "count": total_count},
        {"id": "technical", "name": "Τεχνικοί Όροι (Technical)", "icon": "💻", "count": len(tech_terms)},
        {"id": "literary", "name": "Λογοτεχνικοί Όροι (Literary)", "icon": "📚", "count": len(lit_terms)},
        {"id": "general", "name": "Γενικοί / Προσαρμοσμένοι (General)", "icon": "⚙️", "count": len(gen_terms)},
    ]

    items: List[Dict[str, str]] = []
    # Add technical terms
    for src, tgt in tech_terms.items():
        items.append({"source": src, "target": tgt, "category": "technical"})
    # Add literary terms
    for src, tgt in lit_terms.items():
        items.append({"source": src, "target": tgt, "category": "literary"})
    # Add general terms
    for src, tgt in gen_terms.items():
        items.append({"source": src, "target": tgt, "category": "general"})

    return {
        "categories": categories_list,
        "counts": {
            "all": total_count,
            "technical": len(tech_terms),
            "literary": len(lit_terms),
            "general": len(gen_terms),
        },
        "terms": items,
        "flat": load_glossary(),
    }


def set_term(source: str, target: str, category: str = "general") -> Dict[str, str]:
    """
    Adds or updates a glossary term under the specified category.
    Removes the term from other categories to avoid conflicts.
    Returns the full updated flat glossary.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Source term cannot be empty.")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("Target term cannot be empty.")
    source = source.strip()
    target = target.strip()

    cat = (category or "general").lower()
    if cat not in CATEGORIES_META:
        cat = "general"

    with _glossary_lock:
        data = _read_raw_file()
        terms = data.get("terms")
        if not isinstance(terms, dict):
            terms = {}
            data["terms"] = terms
        for c_name in ("technical", "literary", "general"):
            if not isinstance(terms.get(c_name), dict):
                terms[c_name] = {}
            # If term existed elsewhere, remove it first
            if source in terms[c_name] and c_name != cat:
                del terms[c_name][source]

        terms[cat][source] = target
        _write_raw_file(data)
        return load_glossary()


def delete_term(source: str) -> Dict[str, str]:
    """
    Deletes a glossary term from whichever category it belongs to.
    Returns the full updated flat glossary.
    """
    if not isinstance(source, str) or not source.strip():
        return load_glossary()
    source = source.strip()
    with _glossary_lock:
        data = _read_raw_file()
        terms = data.get("terms")
        if not isinstance(terms, dict):
            return load_glossary()
        modified = False

        for c_name in ("technical", "literary", "general"):
            cat_dict = terms.get(c_name)
            if isinstance(cat_dict, dict) and source in cat_dict:
                del cat_dict[source]
                modified = True

        if modified:
            _write_raw_file(data)

        return load_glossary()


def _build_term_regex(term: str) -> re.Pattern:
    """
    Builds regex pattern supporting terms with leading/trailing non-word symbols (e.g. C++, .NET)
    including inside parentheses/quotes like '(.NET)', while refusing to match fragments inside
    hyphenated compounds (e.g. 'pod' inside 'pod-man', 'royalty' inside 'royalty-free').
    """
    escaped = re.escape(term)
    prefix = r"(?<![\w-])" if bool(re.search(r"^\w", term)) else r"(?<![\w.-])"
    suffix = r"(?![\w-])" if bool(re.search(r"\w$", term)) else r"(?![\w+#-])"
    flags = re.IGNORECASE if term.islower() else 0
    return re.compile(rf"{prefix}{escaped}{suffix}", flags)


def _is_english_citation_line(line: str) -> bool:
    """Detects English-language academic citation/bibliography lines that should not be partially glossary-patched."""
    s = line.strip()
    if len(s) < 25:
        return False
    latin_cnt = len(re.findall(r"[A-Za-z]", s))
    greek_cnt = len(re.findall(r"[\u0370-\u03ff]", s))
    if latin_cnt < 15 or latin_cnt < greek_cnt * 3:
        return False
    # Typical citation cues: year (1998) / 2004. / Journal / pp. / Vol. / et al. / doi / ISBN
    return bool(re.search(r"\b(?:19\d{2}|20\d{2})\b|\bet al\.|\bJournal\b|\bpp\.\s*\d|\bdoi:|:\s*\d+\s*[-–]\s*\d+", s))


def _apply_terms_single_pass(text: str, active_terms: list[tuple[str, str, re.Pattern]]) -> str:
    """
    Applies glossary terms idempotently without recursive double-substitution or regex-escape crashes:
    1. Protects already-substituted target phrases (e.g. 'Αίθουσα Διακομιστών (Server Room)') so
       repeated calls to apply_glossary() never nest parentheses.
    2. Replaces each match with an inert placeholder token first, then expands placeholders once at the end.
    3. Uses a lambda replacement so backslashes in target strings (e.g. 'C:\\temp', '\\1') never raise re.error.
    """
    placeholders: list[str] = []

    def _stash(value: str) -> str:
        idx = len(placeholders)
        placeholders.append(value)
        return f"\x00GLOSS_{idx}\x00"

    # Protect already-present parenthetical target strings so re-applying glossary is 100% idempotent
    for _, replacement, _ in active_terms:
        if "(" in replacement and replacement in text:
            text = text.replace(replacement, _stash(replacement))

    text_lower = text.lower()
    for term, replacement, pattern in active_terms:
        if term.lower() not in text_lower:
            continue
        def _repl(_, _rep=replacement):
            return _stash(_rep)
        new_text = pattern.sub(_repl, text)
        if new_text != text:
            text = new_text
            text_lower = text.lower()

    if placeholders:
        for idx in range(len(placeholders) - 1, -1, -1):
            text = text.replace(f"\x00GLOSS_{idx}\x00", placeholders[idx])
    return text


def apply_glossary(
    text: str,
    target_lang: str = "greek",
    category: Optional[str] = None,
    style: Optional[str] = None,
) -> str:
    """
    Applies glossary replacements to text using word-boundary substitutions.
    Sorted by term length descending so longer phrases match first.
    Includes fast substring pre-filtering for high performance across 1000+ terms.
    When style is literary/comic/audiobook/poetry, excludes technical/IT categories and skips
    English-only bibliographic citation lines.
    """
    if not text or not isinstance(target_lang, str) or target_lang.lower() not in ("greek", "el"):
        return text

    glossary = load_glossary(category=category, style=style)
    if not glossary:
        return text

    # Sort terms by length descending to prevent sub-string overlap
    sorted_terms = sorted(glossary.keys(), key=len, reverse=True)
    full_lower = text.lower()
    active_terms = [
        (t, glossary[t], _build_term_regex(t))
        for t in sorted_terms
        if t and glossary.get(t) and t.lower() in full_lower
    ]
    if not active_terms:
        return text

    protect_citations = (style or "").lower() in ("literature", "audiobook", "poetry", "natural")
    if not protect_citations:
        return _apply_terms_single_pass(text, active_terms)

    out_lines = []
    for line in text.split("\n"):
        if _is_english_citation_line(line):
            out_lines.append(line)
            continue
        out_lines.append(_apply_terms_single_pass(line, active_terms))
    return "\n".join(out_lines)
