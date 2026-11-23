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
import zipfile
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# What a book says about itself (subjects, BISAC codes): certain, where the text alone is a guess
_POETRY_SUBJECT_RE = re.compile(
    r"\b(?:poetry|poems?|verses?|sonnets?|haiku|lyric poetry)\b|\bPOE\d{6}\b|ποίηση|ποιήματ|ποιητικ|στίχοι", re.I)
_FICTION_SUBJECT_RE = re.compile(
    r"\b(?:fiction|novels?|novellas?|short stories)\b|\bFIC\d{6}\b|μυθιστόρημα|διηγήματ|νουβέλ|πεζογραφ", re.I)
_NON_FICTION_RE = re.compile(r"\bnon[-\s]?fiction\b|μη μυθοπλασ", re.I)
# a book about poetry or novels ('Poetry -- History and criticism') is not one
_ABOUT_RE = re.compile(r"criticism|interpretation|study and teaching|κριτικ|μελέτ|ερμηνε", re.I)
_MAX_METADATA_BYTES = 2_000_000


def book_subjects(file_path: str, file_type: str) -> List[str]:
    """
    What the file says about itself: EPUB dc:subject and dc:type, PDF subject and keywords, DOCX subject, keywords
    and category. Never raises: an unreadable file says nothing.
    """
    try:
        kind = (file_type or "").strip().lower()
        found: List[str] = []
        if kind == "pdf":
            import pymupdf
            with pymupdf.open(file_path) as doc:
                meta = doc.metadata or {}
            found = [meta.get("subject") or "", meta.get("keywords") or ""]
        elif kind in ("epub", "docx"):
            from lxml import etree
            parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
            with zipfile.ZipFile(file_path) as z:
                def read(name: str) -> bytes:
                    if z.getinfo(name).file_size > _MAX_METADATA_BYTES:
                        raise ValueError(f"{name} is too large to be metadata")
                    return z.read(name)

                if kind == "epub":
                    container = etree.fromstring(read("META-INF/container.xml"), parser)
                    opf = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
                    root, wanted = etree.fromstring(read(opf), parser), ("subject", "type")
                else:
                    root, wanted = etree.fromstring(read("docProps/core.xml"), parser), ("subject", "keywords", "category")
            found = [(e.text or "") for e in root.iter() if isinstance(e.tag, str)
                     and etree.QName(e).localname in wanted and etree.QName(e).namespace != "http://www.idpf.org/2007/opf"]
        return [" ".join(s.split())[:200] for s in found if s and s.strip()][:20]
    except Exception as e:
        logger.debug(f"No subjects read from {file_path}: {e}")
        return []


def _genre_from_subjects(subjects: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    said = " | ".join(s for s in (subjects or []) if isinstance(s, str) and not _ABOUT_RE.search(s))[:2000]
    plain = _NON_FICTION_RE.sub(" ", said)
    if _POETRY_SUBJECT_RE.search(plain):
        return {"genre": "poetry", "suggested_style": "poetry", "glossary_category": "literary", "confidence": 1.0,
                "reason": f"The book describes itself as poetry ({said[:80]})."}
    if _FICTION_SUBJECT_RE.search(plain):
        return {"genre": "literature", "suggested_style": "literature", "glossary_category": "literary",
                "confidence": 1.0, "reason": f"The book describes itself as fiction ({said[:80]})."}
    return None


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


def _is_wrapped_prose(lines: list) -> bool:
    """
    Short lines a narrow page made: most continue mid-sentence in lower case, few end on punctuation, sentences
    begin inside lines, and a line stops where the next word did not fit.
    """
    if len(lines) < 4:
        return False
    followers = lines[1:]
    continuing = sum(1 for line in followers if line[:1].islower())
    end_stopped = sum(1 for line in lines if re.search(r"[.,;:!?·…»]$", line))
    inner_sentences = sum(1 for line in lines if re.search(r"[.!?;»][ \t]+[«—A-ZΑ-ΩΆΈΉΊΌΎΏ]", line))
    if continuing < 0.5 * len(followers) or end_stopped > 0.45 * len(lines) or not inner_sentences:
        return False
    width = sorted(len(line) for line in lines)[int(0.9 * (len(lines) - 1))] * 0.9
    filled = sum(1 for line, below in zip(lines, followers) if len(line) + 1 + len(below.split()[0]) > width)
    return filled >= 0.6 * len(followers)


def detect_genre_and_style(sample_text: str, file_type: str = "", subjects: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Analyzes document text sample (e.g. first 5,000 characters) and returns:
    - genre: literature, poetry, technical, formal, comic, natural
    - suggested_style: matching AI Polish style
    - glossary_category: technical, literature, or general
    - confidence: float 0.0 to 1.0
    - reason: explanation of detected cues
    """
    safe_text = sample_text or ""
    safe_type = (file_type or "").strip().lower()
    if safe_type in ("cbz", "cbr", "zip") or "[Comic Page" in safe_text:
        return {
            "genre": "comic",
            "suggested_style": "literature",
            "glossary_category": "literary",
            "confidence": 1.0,
            "reason": "Graphic novel / comic archive detected.",
        }
    told = _genre_from_subjects(subjects)
    if told:
        return told

    clean = safe_text.strip()
    if not clean:
        return {
            "genre": "literature",
            "suggested_style": "literature",
            "glossary_category": "general",
            "confidence": 0.5,
            "reason": "Default fallback for empty or minimal sample.",
        }

    raw_lines = [line.strip() for line in clean.split("\n") if line.strip()]
    # Filter structural markers (PAGE headers, === dividers, bullet lists, TOC lines ending in page numbers)
    lines = [
        l for l in raw_lines
        if not l.startswith("=")
        and not re.match(r"^PAGE\s+\d+$", l, re.IGNORECASE)
    ]
    total_lines = len(lines)

    # 1. Check for Poetry: High proportion of short verse lines (excluding bullet lists & TOC entries)
    non_list_lines = [
        l for l in lines
        if not re.match(r"^([-•*]\s+|\d+[.)]\s+)", l)
        and not re.search(r"(\.{3,}\s*\d+|\s{2,}\d{1,4})$", l)
    ]
    if (len(non_list_lines) >= 4 and len(non_list_lines) / max(1, total_lines) >= 0.7
            and not _is_wrapped_prose(non_list_lines)):
        short_lines = [l for l in non_list_lines if 5 <= len(l) <= 60]
        ratio_short = len(short_lines) / max(1, len(non_list_lines))
        # Check if line breaks are frequent without full-stop endings
        non_period_endings = [l for l in short_lines if not l.endswith((".", "!", "?", ";"))]
        ratio_enjambment = len(non_period_endings) / max(1, len(short_lines))

        if ratio_short > 0.65 and ratio_enjambment > 0.40:
            return {
                "genre": "poetry",
                "suggested_style": "poetry",
                "glossary_category": "literary",
                "confidence": round(min(0.95, ratio_short * 1.1), 2),
                "reason": f"Detected poetic verse structure: {len(short_lines)}/{len(non_list_lines)} short rhythmic lines.",
            }

    # 2. Tokenize lower-case words (2+ chars so acronyms like 'ip', 'ai', 'os' match) + multi-word phrases
    clean_lower = clean.lower()
    words = re.findall(r"\b[\wΆ-ώa-zA-Z]{2,}\b", clean_lower)
    total_words = max(1, len(words))

    def _count_keyword_hits(keywords: set[str]) -> int:
        single_hits = sum(1 for w in words if w in keywords)
        phrase_hits = sum(clean_lower.count(kw) for kw in keywords if " " in kw)
        return single_hits + phrase_hits

    tech_matches = _count_keyword_hits(TECHNICAL_KEYWORDS)
    formal_matches = _count_keyword_hits(FORMAL_KEYWORDS)
    lit_matches = _count_keyword_hits(LITERATURE_KEYWORDS)

    # Count dialogue cues (em-dash/guillemet/quote; avoid counting short Markdown bullet lists)
    dialogue_lines = [
        l for l in lines
        if re.match(r"^([—–]|«|\")", l) or (re.match(r"^-\s+", l) and re.search(r"[.,;!?\u0370-\u03ff]", l))
    ]
    dialogue_ratio = len(dialogue_lines) / max(1, total_lines)

    # Scoring
    tech_score = (tech_matches / total_words) * 100
    formal_score = (formal_matches / total_words) * 100
    lit_score = ((lit_matches / total_words) * 100) + (dialogue_ratio * 15)

    if tech_score > formal_score and tech_score > lit_score and tech_score > 1.2:
        return {
            "genre": "technical",
            "suggested_style": "technical",
            "glossary_category": "technical",
            "confidence": round(min(0.95, 0.6 + tech_score * 0.1), 2),
            "reason": f"Detected technical keywords ({tech_matches} occurrences, tech score: {tech_score:.1f}).",
        }

    if formal_score > lit_score and formal_score > 1.0:
        return {
            "genre": "formal",
            "suggested_style": "formal",
            "glossary_category": "general",
            "confidence": round(min(0.95, 0.6 + formal_score * 0.1), 2),
            "reason": f"Detected administrative and formal document terminology ({formal_matches} matches).",
        }

    if dialogue_ratio > 0.15 or lit_score > 1.0:
        return {
            "genre": "literature",
            "suggested_style": "literature",
            "glossary_category": "literary",
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
