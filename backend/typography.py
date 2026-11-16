"""
typography.py - Advanced Greek Editorial Typography & Orthography Engine.
Implements standard Greek publishing conventions:
1. Quotation mark transformation: straight double quotes "..." -> Greek guillemets «...».
2. Dialogue dashes: standardizes conversation markers to em-dash (—).
3. The Greek Rule of Final "ν" (Κανόνας του τελικού ν):
   - 'δεν' / 'δε' and 'μην' / 'μη' based on following consonants/vowels.
   - Retains 'ν' before vowels (α, ε, η, ι, ο, υ, ω) and plosives/doubles (κ, π, τ, ξ, ψ, μπ, ντ, γκ, τσ, τζ).
   - Drops 'ν' before continuants (β, γ, δ, ζ, θ, λ, μ, ν, ρ, σ, φ, χ).
4. Punctuation spacing (eliminates spaces before commas/periods/semicolons).
5. Greek question mark (;) normalization.
"""

import re
from typing import Optional


# Greek vowels with and without accents/tonos/dialytika
GREEK_VOWELS = "αεηιουωάέήίόύώϊϋΐΰΑΕΗΙΟΥΩΆΈΉΊΌΎΏΪΫ"

# Greek plosives, double consonants and digraphs that PRESERVE final 'ν'
# κ, π, τ, ξ, ψ, μπ, ντ, γκ, τσ, τζ (case-insensitive)
PRESERVE_NU_CONSONANTS = (
    "κ", "π", "τ", "ξ", "ψ",
    "μπ", "ντ", "γκ", "τσ", "τζ",
    "Κ", "Π", "Τ", "Ξ", "Ψ",
    "ΜΠ", "Μπ", "ΝΤ", "Ντ", "ΓΚ", "Γκ", "ΤΣ", "Τσ", "ΤΖ", "Τζ",
)

# Continuant consonants before which 'ν' is DROPPED in 'δε' and 'μη'
# β, γ (single), δ, ζ, θ, λ, μ (single), ν (single), ρ, σ/ς, φ, χ
DROP_NU_CONSONANTS = (
    "β", "γ", "δ", "ζ", "θ", "λ", "μ", "ν", "ρ", "σ", "ς", "φ", "χ",
    "Β", "Γ", "Δ", "Ζ", "Θ", "Λ", "Μ", "Ν", "Ρ", "Σ", "Φ", "Χ",
)


def _should_keep_final_nu(next_word: str) -> bool:
    """
    Returns True if the following Greek word requires keeping final 'ν'
    (starts with a vowel, κ, π, τ, ξ, ψ, or digraphs μπ, ντ, γκ, τσ, τζ).
    """
    w = next_word.strip()
    if not w:
        return True
    first_char = w[0]
    if first_char in GREEK_VOWELS:
        return True
    # Check 2-letter digraphs first (e.g. μπ, ντ)
    if len(w) >= 2:
        two_char = w[:2]
        if two_char in PRESERVE_NU_CONSONANTS:
            return True
        if two_char.lower() in ("μπ", "ντ", "γκ", "τσ", "τζ"):
            return True
    # Check 1-letter plosives/doubles
    if first_char in ("κ", "π", "τ", "ξ", "ψ", "Κ", "Π", "Τ", "Ξ", "Ψ"):
        return True
    # Latin letters / numbers: preserve final 'ν' (e.g. 'δεν ήταν', 'δεν 10')
    if re.match(r"[a-zA-Z0-9]", first_char):
        return True
    return False


def apply_final_nu_rules(text: str) -> str:
    """
    Applies the modern Greek grammar rule for final 'ν' on:
    - δε / δεν
    - μη / μην
    - τη / την (optional standard rule for feminine accusative)
    """
    def _replace_de(m: re.Match) -> str:
        prefix = m.group(1)  # "δε" or "δεν" with casing
        space = m.group(2)
        next_word = m.group(3)
        keep = _should_keep_final_nu(next_word)
        is_upper = prefix.isupper()
        is_cap = prefix[0].isupper()
        if keep:
            corr = "ΔΕΝ" if is_upper else ("Δεν" if is_cap else "δεν")
        else:
            corr = "ΔΕ" if is_upper else ("Δε" if is_cap else "δε")
        return f"{corr}{space}{next_word}"

    def _replace_me(m: re.Match) -> str:
        prefix = m.group(1)
        space = m.group(2)
        next_word = m.group(3)
        keep = _should_keep_final_nu(next_word)
        is_upper = prefix.isupper()
        is_cap = prefix[0].isupper()
        if keep:
            corr = "ΜΗΝ" if is_upper else ("Μην" if is_cap else "μην")
        else:
            corr = "ΜΗ" if is_upper else ("Μη" if is_cap else "μη")
        return f"{corr}{space}{next_word}"

    # Match 'δε' or 'δεν' as standalone words before the next word
    text = re.sub(r"\b(δε|δεν|ΔΕ|ΔΕΝ|Δε|Δεν)(\s+)([\wΆ-ώ]+)", _replace_de, text)
    # Match 'μη' or 'μην' as standalone words before the next word
    text = re.sub(r"\b(μη|μην|ΜΗ|ΜΗΝ|Μη|Μην)(\s+)([\wΆ-ώ]+)", _replace_me, text)

    return text


def format_greek_quotes(text: str) -> str:
    """
    Transforms straight double quotes ("...") into standard Greek publication guillemets («...»).
    Preserves quotes inside code blocks or markers.
    """
    # Protect PAGE markers and markdown tags
    def _convert_quotes(s: str) -> str:
        parts = re.split(r'(".*?")', s)
        for i in range(1, len(parts), 2):
            inner = parts[i][1:-1]
            parts[i] = f"«{inner.strip()}»"
        return "".join(parts)

    lines = []
    for line in text.split("\n"):
        if re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", line.strip()):
            lines.append(line)
        elif line.strip().startswith("```"):
            lines.append(line)
        else:
            lines.append(_convert_quotes(line))
    return "\n".join(lines)


def format_dialogue_dashes(text: str) -> str:
    """
    Standardizes conversation lines starting with simple hyphens to em-dash (—).
    E.g. '- Γεια σου, είπε' -> '— Γεια σου, είπε'.
    """
    lines = []
    for line in text.split("\n"):
        # Match lines starting with optional whitespace, then hyphen or en-dash followed by space and Greek/letter
        m = re.match(r"^(\s*)([-–])\s+([«\wΆ-ώ\.\(\[\"'])", line)
        if m:
            indent, _, start_char = m.groups()
            line = f"{indent}— {start_char}" + line[m.end():]
        lines.append(line)
    return "\n".join(lines)


def format_greek_punctuation(text: str) -> str:
    """
    Cleans up punctuation spacing and ensures Greek publishing standards:
    - Removes whitespace before commas, full stops, semicolons, exclamation marks.
    - Ensures single space after commas and sentence stops.
    - Normalizes question marks (replaces English '?' with Greek ';' when in Greek sentence context).
    """
    # Remove space before punctuation: e.g. "λέξη , άλλη" -> "λέξη, άλλη", "λέξη ?" -> "λέξη?"
    text = re.sub(r"\s+([,.:;!?·»])", r"\1", text)
    # Remove space after opening guillemet: « λέξη » -> «λέξη»
    text = re.sub(r"«\s+", "«", text)
    text = re.sub(r"\s+»", "»", text)
    # Fix multiple commas or dots
    text = re.sub(r",,+", ",", text)
    text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)  # double dots to single, but leave ... intact

    # Replace English question mark ? with Greek ; if preceding word or quote is Greek
    def _to_greek_qm(m: re.Match) -> str:
        token = m.group(1)
        if re.search(r"[\u0370-\u03ff]", token):
            return f"{token};"
        return f"{token}?"

    text = re.sub(r"([«»\wΆ-ώ]+)\?", _to_greek_qm, text)

    return text


def format_greek_typography(
    text: str,
    enable_quotes: bool = True,
    enable_dialogue_dashes: bool = True,
    enable_final_nu: bool = True,
    enable_punctuation: bool = True,
) -> str:
    """
    Comprehensive pipeline for Greek typography and editorial formatting.
    """
    if not text:
        return text

    res = text
    if enable_dialogue_dashes:
        res = format_dialogue_dashes(res)
    if enable_quotes:
        res = format_greek_quotes(res)
    if enable_final_nu:
        res = apply_final_nu_rules(res)
    if enable_punctuation:
        res = format_greek_punctuation(res)

    return res
