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


# Common Greek determiners, articles, and prepositions after which 'μη' is a
# privative/nominal modifier ('το μη επανδρωμένο', 'για μη εμπορική χρήση')
# and MUST NEVER take final 'ν'.
_NON_VERBAL_PRECEDING_WORDS = frozenset({
    "ο", "η", "το", "οι", "τα", "του", "της", "των", "τον", "την", "τους", "τις",
    "ένας", "ενας", "μια", "μία", "ένα", "ενα", "ενός", "ενος", "μιας", "μίας",
    "στον", "στην", "στη", "στο", "στους", "στις", "στα",
    "σε", "από", "απο", "με", "για", "προς", "κατά", "κατα", "υπό", "υπο",
    "επί", "επι", "περί", "περι", "δια", "χωρίς", "χωρις", "ως", "σαν",
    "κάθε", "καθε", "κάποιος", "κάποια", "κάποιο", "άλλος", "άλλη", "άλλο",
    "άλλων", "άλλες", "άλλα", "τέτοιος", "τέτοια", "τέτοιο", "τέτοιες", "τέτοιας",
    "αυτός", "αυτή", "αυτό", "αυτοί", "αυτές", "αυτά", "αυτού", "αυτής", "αυτών",
    "εκείνος", "εκείνη", "εκείνο", "εκείνοι", "εκείνες", "εκείνα",
    "πιο", "πολύ", "πολυ", "εντελώς", "απολύτως", "σχεδόν", "κυρίως",
    "αρχικά", "τελικά", "γενικά", "ειδικά", "όχι", "οχι", "είναι", "ειναι",
    "ήταν", "ηταν", "είναι", "γίνει", "μένει", "παραμένει",
})

# Suffixes of Greek adjectives, passive participles, adverbs, and abstract nouns
# that take privative 'μη' (NEVER verbal 'μην').
_NON_VERBAL_ME_SUFFIX_RE = re.compile(
    r"(?:"
    r"μέν(?:ος|η|ο|οι|ες|α|ου|ης|ων|ους|ο|ε)|"
    r"μεν(?:ος|η|ο|οι|ες|α|ου|ης|ων|ους)|"
    r"ικ(?:ός|ή|ό|οί|ές|ά|ού|ής|ών|ούς|ος|η|ο|οι|ες|α|ου|ης|ων|ους)|"
    r"τικ(?:ός|ή|ό|οί|ές|ά|ού|ής|ών|ούς|ος|η|ο|οι|ες|α)|"
    r"(?:πτ|κτ|στ|χτ|θτ|ντ)(?:ός|ή|ό|οί|ές|ά|ού|ής|ών|ούς)|"
    r"αί(?:ος|α|ο|οι|ες|ου|ας|ων|ους)|"
    r"ιν(?:ος|η|ο|οι|ες|α|ου|ης|ων|ους)|"
    r"ητ(?:ος|η|ο|οι|ες|α|ου|ης|ων|ους)|"
    r"ιμ(?:ος|η|ο|οι|ες|α|ου|ης|ων|ους)|"
    r"ώδ(?:ης|ες|εις|ους)|"
    r"αρίθμ\w*|ανθρώπιν\w*|απαραίτητ\w*|ευαίσθητ\w*|αποδεκτ\w*|εμπορικ\w*|"
    r"επανδρωμ\w*|επεμβατ\w*|επέμβασ\w*|παραβίασ\w*|εξουσιοδοτ\w*|τροποποιημ\w*|"
    r"αποκλειστικ\w*|καθοδηγητ\w*|περιφερειακ\w*|ακουστικ\w*|εικονικ\w*|πειστικ\w*|"
    r"κερδοσκοπ\w*|βιώσιμ\w*|συμβατ\w*|επιτρεπτ\w*|υποχρεωτ\w*|οργανικ\w*|ενεργ\w*|"
    r"αναστρέψιμ\w*|ανεξάρτητ\w*|αμφισβητ\w*|εξαρτημ\w*"
    r")$",
    re.IGNORECASE,
)

# Abstract nouns in -ση/-σης/-ξη/-ξης/-ψη/-ψης/-τητα/-τητας (length >= 6)
_ABSTRACT_NOUN_SUFFIX_RE = re.compile(
    r"(?:σης|σής|ση|ξης|ξής|ξη|ψης|ψής|ψη|τητας|τητα|μοί|μός|μού)$",
    re.IGNORECASE,
)


def _is_privative_me(prev_word: str, next_word: str) -> bool:
    """
    Returns True when 'μη' is used as a privative/nominal/adjectival modifier
    ('μη απαραίτητα', 'μη επανδρωμένος', 'μη εμπορική', 'μη επέμβασης', 'ΜΗ ΠΑΡΑΒΙΑΣΗΣ')
    rather than a verbal negation ('μην έρθεις', 'μην πας').
    In Modern Greek, privative 'μη' NEVER takes final 'ν'.
    """
    pw = prev_word.strip().lower()
    nw = next_word.strip()
    if not nw:
        return False
    if pw in _NON_VERBAL_PRECEDING_WORDS:
        return True
    nw_low = nw.lower()
    if _NON_VERBAL_ME_SUFFIX_RE.search(nw_low):
        return True
    if len(nw_low) >= 6 and _ABSTRACT_NOUN_SUFFIX_RE.search(nw_low):
        return True
    # Title-cased noun/adjective following 'Μη'/'μη' (e.g. 'Μη Εμπορική', 'μη Ανεληγμένες')
    if len(nw) >= 4 and nw[0].isupper() and not nw.isupper():
        return True
    return False


def apply_final_nu_rules(text: str) -> str:
    """
    Applies the modern Greek grammar rule for final 'ν' on:
    - δε / δεν
    - μη / μην (strictly respecting privative 'μη' before adjectives/participles/nouns/adverbs)
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
        # Look behind up to 24 chars to inspect the immediately preceding word
        start_pos = m.start()
        before = text[max(0, start_pos - 24):start_pos].rstrip()
        prev_m = re.search(r"([\wΆ-ώ]+)$", before)
        prev_word = prev_m.group(1) if prev_m else ""

        if _is_privative_me(prev_word, next_word):
            keep = False
        else:
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


def fix_broken_hyphens(text: str) -> str:
    """
    Rejoins Greek words split by line-break hyphens (e.g. 'υποσχέ- θηκαν' -> 'υποσχέθηκαν',
    'εσωτερι-\\nκά' -> 'εσωτερικά', 'ΠΛΗΜ-\\nΜΥΡΙΣΕΙ' -> 'ΠΛΗΜΜΥΡΙΣΕΙ').
    Avoids touching legitimate dialogue pauses or repeated-word emphasis ('εσύ-\\n\\nεσύ').
    """
    if not text:
        return text
    # Single-newline or single-space hyphenation inside a Greek word (not double newline)
    def _join_hyphen(m: re.Match) -> str:
        left, right = m.group(1), m.group(2)
        # Skip repeated words like "εσύ- εσύ" or "όχι- όχι"
        if left.lower() == right.lower():
            return m.group(0)
        # Join if both halves are lowercase-ending/starting OR both ALL CAPS
        if (left[-1].islower() and right[0].islower()) or (left.isupper() and right.isupper()):
            return f"{left}{right}"
        return m.group(0)

    return re.sub(
        r"([\u0370-\u03ff]{2,})-(?:[ \t]*\r?\n[ \t]*|[ \t]+)([\u0370-\u03ff]{2,})",
        _join_hyphen,
        text,
    )


def fix_greek_elision_apostrophes(text: str) -> str:
    """
    Restores missing apostrophes in common Greek elisions before vowels
    (e.g. 'Σ ΑΥΤΗΝ' -> \"Σ' ΑΥΤΗΝ\", 'ΓΙ ΑΥΤΟ' -> \"ΓΙ' ΑΥΤΟ\", 'ΑΠ ΑΥΤΟ' -> \"ΑΠ' ΑΥΤΟ\").
    """
    if not text:
        return text
    vowel_start = r"[αεηιουωάέήίόύώΑΕΗΙΟΥΩΆΈΉΊΌΎΏ]"
    # Match standalone elided prepositions/pronouns followed by space + vowel-initial Greek word
    text = re.sub(
        rf"\b(σ|Σ|γι|Γι|ΓΙ|απ|Απ|ΑΠ|μ|Μ|τ|Τ|θ|Θ)\s+({vowel_start}[\u0370-\u03ff]+)",
        lambda m: f"{m.group(1)}' {m.group(2)}"
        if m.group(1).lower() in ("σ", "γι", "απ")
        or (m.group(1).lower() == "μ" and m.group(2).lower().startswith(("αρέσ", "αρεσ", "άφησ", "αφησ", "έκα", "εκα", "έχει", "εχει")))
        else m.group(0),
        text,
    )
    return text


def format_greek_punctuation(text: str) -> str:
    """
    Cleans up punctuation spacing and ensures Greek publishing standards:
    - Removes whitespace before commas, full stops, semicolons, exclamation marks.
    - Ensures single space after commas and sentence stops.
    - Normalizes question marks (replaces English '?' with Greek ';' when in Greek sentence context,
      including '?!', '?!!', '??!!', and '...?').
    """
    # Remove horizontal spaces/tabs before punctuation (never collapse newlines!)
    text = re.sub(r"[ \t]+([,.:;!?·»])", r"\1", text)
    # Remove horizontal space after opening guillemet / before closing guillemet
    text = re.sub(r"«[ \t]+", "«", text)
    text = re.sub(r"[ \t]+»", "»", text)
    # Fix multiple commas or dots
    text = re.sub(r",,+", ",", text)
    text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)  # double dots to single, but leave ... intact

    # Replace English question mark ? (including ?!, ??!!, ...?) with Greek ; when in Greek context
    has_greek_in_doc = bool(re.search(r"[\u0370-\u03ff]", text))

    def _to_greek_qm(m: re.Match) -> str:
        token = m.group(1)
        qmarks = m.group(2)
        if re.search(r"[\u0370-\u03ff]", token):
            return f"{token}{qmarks.replace('?', ';')}"
        return m.group(0)

    text = re.sub(r"([«»\"'\.\wΆ-ώ]+)([?!]+)", _to_greek_qm, text)
    # Also handle standalone comic interjections like "??!!" or "?!!" when document is Greek
    if has_greek_in_doc:
        text = re.sub(
            r"(?<=^)(?P<lead>[\s«\"'—–\-]*)(?P<qm>\?+[!?]*)(?P<trail>[\s»\"']*$)",
            lambda m: f"{m.group('lead')}{m.group('qm').replace('?', ';')}{m.group('trail')}",
            text,
            flags=re.MULTILINE,
        )

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

    res = fix_broken_hyphens(text)
    res = fix_greek_elision_apostrophes(res)
    if enable_dialogue_dashes:
        res = format_dialogue_dashes(res)
    if enable_quotes:
        res = format_greek_quotes(res)
    if enable_final_nu:
        res = apply_final_nu_rules(res)
    if enable_punctuation:
        res = format_greek_punctuation(res)

    return res
