"""
genre_detector.py - Automatic Document Genre, Tone & Style Detection Engine.
Analyzes document text samples to auto-detect:
- Literature / Fiction (novels, stories, dialogues)
- Poetry / Spoken Verse (short lines, stanzas, rhythmic structure)
- Technical / Computing (APIs, code, engineering terms, specifications)
- Formal / Administrative (laws, government orders, ministerial decisions, contracts)
- Graphic Novels / Comics (visual panels, balloon transcripts)
Auto-selects optimal Polish Style and Glossary Category for one-click setup.
"""

import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


TECHNICAL_KEYWORDS = {
    "api", "server", "database", "python", "javascript", "docker", "cloud",
    "ram", "cpu", "network", "bandwidth", "ip", "dns", "http", "https",
    "architecture", "framework", "component", "algorithm", "compiler",
    "ups", "router", "switch", "gateway", "firmware", "protocol", "sql",
    "διακομιστής", "βάση δεδομένων", "πρωτόκολλο", "μνήμη", "επεξεργαστής",
    "αλγόριθμος", "υποδομή", "παράμετρος", "λογισμικό", "υλικό",
}

FORMAL_KEYWORDS = {
    "υπουργείο", "άρθρο", "νόμος", "απόφαση", "εφημερίδα της κυβερνήσεως",
    "προεδρικό διάταγμα", "εγκύκλιος", "διατάξεις", "αρμοδιότητα", "διοίκηση",
    "σύμβαση", "συμβαλλόμενοι", "παράγραφος", "τροποποίηση", "δημοσίευση",
    "ministry", "article", "directive", "regulation", "pursuant to", "decree",
    "official gazette", "contract", "parties hereto", "clause", "stipulated",
}

LITERATURE_KEYWORDS = {
    "ψιθύρισε", "κοίταξε", "έγνεψε", "χαμογέλασε", "σκοτάδι", "φως",
    "καρδιά", "μάτια", "ανάσα", "φωνή", "σιωπή", "ουρανός", "νύχτα",
    "whispered", "gazed", "nodded", "smiled", "darkness", "shadow",
    "heart", "eyes", "breath", "voice", "silence", "sky", "night",
}


def detect_genre_and_style(sample_text: str, file_type: str = "") -> Dict[str, Any]:
    """
    Analyzes document text sample (e.g. first 5,000 characters) and returns:
    - genre: literature, poetry, technical, formal, comic, natural
    - suggested_style: matching AI Polish style
    - glossary_category: technical, literature, or general
    - confidence: float 0.0 to 1.0
    - reason: explanation of detected cues
    """
    if file_type.lower() in ("cbz", "cbr", "zip") or "[Comic Page" in sample_text:
        return {
            "genre": "comic",
            "suggested_style": "literature",
            "glossary_category": "literature",
            "confidence": 1.0,
            "reason": "Graphic novel / comic archive detected.",
        }

    clean = sample_text.strip()
    if not clean:
        return {
            "genre": "literature",
            "suggested_style": "literature",
            "glossary_category": "general",
            "confidence": 0.5,
            "reason": "Default fallback for empty or minimal sample.",
        }

    lines = [line.strip() for line in clean.split("\n") if line.strip()]
    total_lines = len(lines)

    # 1. Check for Poetry: High proportion of short lines (e.g. 10 - 55 chars) + stanzas
    if total_lines >= 4:
        short_lines = [l for l in lines if 5 <= len(l) <= 60 and not l.startswith("=")]
        ratio_short = len(short_lines) / max(1, total_lines)
        # Check if line breaks are frequent without full-stop endings
        non_period_endings = [l for l in short_lines if not l.endswith((".", "!", "?", ";"))]
        ratio_enjambment = len(non_period_endings) / max(1, len(short_lines))

        if ratio_short > 0.65 and ratio_enjambment > 0.40:
            return {
                "genre": "poetry",
                "suggested_style": "poetry",
                "glossary_category": "literature",
                "confidence": round(min(0.95, ratio_short * 1.1), 2),
                "reason": f"Detected poetic verse structure: {len(short_lines)}/{total_lines} short rhythmic lines.",
            }

    # 2. Tokenize lower-case words for keyword density
    words = re.findall(r"\b[\wΆ-ώa-zA-Z]{3,}\b", clean.lower())
    total_words = max(1, len(words))

    tech_matches = sum(1 for w in words if w in TECHNICAL_KEYWORDS)
    formal_matches = sum(1 for w in words if w in FORMAL_KEYWORDS)
    lit_matches = sum(1 for w in words if w in LITERATURE_KEYWORDS)

    # Count dialogue cues (lines starting with dialogue dash —, -, or quotation marks «, ")
    dialogue_lines = [
        l for l in lines
        if re.match(r"^([—–-]|«|\")", l)
    ]
    dialogue_ratio = len(dialogue_lines) / max(1, total_lines)

    # Scoring
    tech_score = (tech_matches / total_words) * 100
    formal_score = (formal_matches / total_words) * 100
    lit_score = ((lit_matches / total_words) * 100) + (dialogue_ratio * 15)

    if tech_score > formal_score and tech_score > 1.2:
        return {
            "genre": "technical",
            "suggested_style": "technical",
            "glossary_category": "technical",
            "confidence": round(min(0.95, 0.6 + tech_score * 0.1), 2),
            "reason": f"Detected technical keywords ({tech_matches} occurrences, tech score: {tech_score:.1f}).",
        }

    if formal_score > 1.0:
        return {
            "genre": "formal",
            "suggested_style": "formal",
            "glossary_category": "technical",
            "confidence": round(min(0.95, 0.6 + formal_score * 0.1), 2),
            "reason": f"Detected administrative and formal document terminology ({formal_matches} matches).",
        }

    if dialogue_ratio > 0.15 or lit_score > 1.0:
        return {
            "genre": "literature",
            "suggested_style": "literature",
            "glossary_category": "literature",
            "confidence": round(min(0.95, 0.65 + dialogue_ratio * 0.5), 2),
            "reason": f"Detected literary dialogue structures and narrative verbs ({len(dialogue_lines)} dialogue cues).",
        }

    # Default to natural / literature
    return {
        "genre": "literature",
        "suggested_style": "natural",
        "glossary_category": "general",
        "confidence": 0.70,
        "reason": "Standard prose structure with balanced vocabulary.",
    }
