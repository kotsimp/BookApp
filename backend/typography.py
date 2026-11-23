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


def _should_keep_final_nu(next_word: str) -> bool:
    """
    Returns True if the following Greek word requires keeping final 'ν'
    (starts with a vowel, κ, π, τ, ξ, ψ, or digraphs μπ, ντ, γκ, τσ, τζ).
    """
    w = next_word.strip()
    if not w:
        return True
    first_char = w[0]
    if first_char in GREEK_VOWELS or ("\u1f00" <= first_char <= "\u1fff"):
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
    "ήταν", "ηταν", "γίνει", "μένει", "παραμένει",
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


# Words after which standalone 'δε' is the conjunction "however/moreover" (NOT negation 'δεν')
_CONJUNCTIVE_DE_PRECEDING_WORDS = frozenset({
    "εάν", "εαν", "αν", "όταν", "οταν", "ενώ", "ενω", "όπως", "οπως",
    "επειδή", "επειδη", "καθώς", "καθως", "άλλωστε", "αλλωστε", "εξάλλου",
    "ο", "η", "το", "οι", "τα", "του", "της", "των", "τον", "την", "τους", "τις",
    "αυτός", "αυτή", "αυτό", "εκείνος", "εκείνη", "εκείνο", "εγώ", "εσύ", "εμείς",
    "έτι", "ετι", "ου", "μήτε", "ούτε",
})


# A verb is negated, never one of these: 'στην περίπτωση δε αυτή' must not become a negation
_DE_NEVER_NEGATES = frozenset({
    "αυτή", "αυτό", "αυτός", "αυτοί", "αυτές", "αυτά", "αυτών", "αυτήν", "αυτόν",
    "εκείνος", "εκείνη", "εκείνο", "εκείνοι", "εκείνες", "η", "ο", "οι",
})


def apply_final_nu_rules(text: str) -> str:
    """
    Applies the modern Greek grammar rule for final 'ν' on:
    - δε / δεν (preserving conjunctive 'δε' = "however/moreover" in formal/legal/literary Greek)
    - μη / μην (strictly respecting privative 'μη' before adjectives/participles/nouns/adverbs)
    """
    def _replace_de(m: re.Match) -> str:
        prefix = m.group(1)  # "δε" or "δεν" with casing
        space = m.group(2)
        next_word = m.group(3)
        # Preserve conjunctive 'δε' ("however/moreover") e.g. "εάν δε προκύψει", "ο δε υπουργός", "δε και"
        if prefix.lower() == "δε":
            start_pos = m.start()
            before = text[max(0, start_pos - 24):start_pos].rstrip()
            prev_m = re.search(r"([\wΆ-ώ\u1f00-\u1fff]+)$", before)
            prev_word = prev_m.group(1).lower() if prev_m else ""
            if (prev_word in _CONJUNCTIVE_DE_PRECEDING_WORDS or next_word.lower() == "και"
                    or next_word.lower() in _DE_NEVER_NEGATES):
                return m.group(0)
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
        prev_m = re.search(r"([\wΆ-ώ\u1f00-\u1fff]+)$", before)
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

    # Match within the same line only ([ \t]+) so paragraph/stanza breaks are never crossed
    text = re.sub(r"\b(δε|δεν|ΔΕ|ΔΕΝ|Δε|Δεν)([ \t]+)([\wΆ-ώ\u1f00-\u1fff]+)", _replace_de, text)
    text = re.sub(r"\b(μη|μην|ΜΗ|ΜΗΝ|Μη|Μην)([ \t]+)([\wΆ-ώ\u1f00-\u1fff]+)", _replace_me, text)

    return text


def format_greek_quotes(text: str) -> str:
    """
    Transforms straight double quotes ("...") into standard Greek publication guillemets («...»).
    Preserves quotes inside fenced code blocks (``` ... ```) and PAGE markers.
    """
    def _convert_quotes(s: str) -> str:
        parts = re.split(r'(".*?")', s)
        for i in range(1, len(parts), 2):
            inner = parts[i][1:-1]
            parts[i] = f"«{inner.strip()}»"
        return "".join(parts)

    lines = []
    in_code_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            lines.append(line)
        elif in_code_fence or re.match(r"^={3,}\s*PAGE\s+\d+\s*={3,}$", stripped):
            lines.append(line)
        else:
            lines.append(_convert_quotes(line))
    return "\n".join(lines)


def format_dialogue_dashes(text: str) -> str:
    """
    Standardizes conversation lines starting with simple hyphens to em-dash (—).
    E.g. '- Γεια σου, είπε' -> '— Γεια σου, είπε'.
    Preserves Markdown numeric/indented bullet items (e.g. '- 5', '  - subitem').
    """
    lines = []
    for line in text.split("\n"):
        # Skip indented Markdown sub-bullets (2+ leading spaces) and numeric bullet items ('- 5')
        if re.match(r"^[ \t]{2,}[-–]\s+", line) or re.match(r"^\s*[-–]\s+\d+", line):
            lines.append(line)
            continue
        # Match lines starting with optional single space, then hyphen or en-dash followed by dialogue start
        m = re.match(r"^(\s*)([-–])\s+([«A-Za-zΆ-ώ\.\(\[\"'])", line)
        if m:
            indent, _, start_char = m.groups()
            line = f"{indent}— {start_char}" + line[m.end():]
        lines.append(line)
    return "\n".join(lines)


# Standalone Greek function/dialogue words that must NOT be glued onto a preceding interrupted word ('Περίμενε- μην')
_STANDALONE_NEXT_WORDS = frozenset({
    "μην", "μη", "δεν", "δε", "τι", "να", "και", "μα", "ότι", "οτι", "που", "πού",
    "αλλά", "αλλα", "για", "με", "σε", "από", "απο", "πώς", "πως", "όχι", "οχι",
    "ναι", "έλα", "ελα", "πες", "ποιος", "ποια", "ποιο", "εγώ", "εσύ", "αυτός",
})


# Latin look-alikes of Greek letters, to recognise short corrupted words ('kαι', 'τo')
_LOOKALIKES = str.maketrans("aeiknoptuvyABEHIKMNOPTXYZ", "αεικνορτυνυΑΒΕΗΙΚΜΝΟΡΤΧΥΖ")
_SHORT_GREEK_WORDS = frozenset(
    "και το τα τη να αν οι τι σε με θα δε μη μα ως απ τον την των τις της του μου σου μας σας πως που στο στα στη "
    "δεν μην ναι".split()
)


def is_mostly_greek(text: str) -> bool:
    greek = len(re.findall(r"[Ͱ-Ͽ]", text or ""))
    return greek > 0 and greek >= len(re.findall(r"[A-Za-z]", text))


def is_corrupt_greek_word(word: str) -> bool:
    """
    True for a Greek word with Latin letters leaked into it. False for symbols that mix both scripts on purpose
    (TNFα, NFκB, kΩ, MΩ, ΔΔCt, β2AR).
    """
    greek = len(re.findall(r"[Ͱ-Ͽ]", word))
    latin = len(re.findall(r"[A-Za-z]", word))
    if not greek or not latin or any(c.isdigit() for c in word):
        return False
    if len(word) <= 3:
        return word.translate(_LOOKALIKES).lower() in _SHORT_GREEK_WORDS
    return greek >= 2 and greek > latin


def fix_broken_hyphens(text: str) -> str:
    """
    Rejoins Greek words split by line-break hyphens (e.g. 'υποσχέ- θηκαν' -> 'υποσχέθηκαν',
    'εσωτερι-\\nκά' -> 'εσωτερικά', 'ΠΛΗΜ-\\nΜΥΡΙΣΕΙ' -> 'ΠΛΗΜΜΥΡΙΣΕΙ').
    Avoids touching legitimate dialogue interruptions ('Περίμενε- μην φεύγεις!') or repeated words ('εσύ- εσύ').
    """
    if not text:
        return text

    def _join_hyphen(m: re.Match) -> str:
        left, sep, right = m.group(1), m.group(2), m.group(3)
        # Skip repeated words like "εσύ- εσύ" or "όχι- όχι"
        if left.lower() == right.lower():
            return m.group(0)
        # For inline space (not newline), refuse to glue interrupted dialogue before standalone words
        if "\n" not in sep and right.lower() in _STANDALONE_NEXT_WORDS:
            return m.group(0)
        # Join if both halves are lowercase-ending/starting OR both ALL CAPS
        if (left[-1].islower() and right[0].islower()) or (left.isupper() and right.isupper()):
            return f"{left}{right}"
        return m.group(0)

    return re.sub(
        r"([\u0370-\u03ff]{2,})-([ \t]*\r?\n[ \t]*|[ \t]+)([\u0370-\u03ff]{2,})",
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
    def _elide(m: re.Match) -> str:
        head, word = m.group(1), m.group(2)
        low, next_low = head.lower(), word.lower()
        if low == "σ":
            # the letter/symbol sigma: 'το Σ είναι το άθροισμα', '3 σ απόκλιση'
            before = text[max(0, m.start() - 20):m.start()]
            if next_low in _SIGMA_PREDICATES or re.search(
                r"(?:(?:^|\W)(?:το|του|γράμμα|σύμβολο|παράμετρος|μεταβλητή)|\d|=)[ \t]*$", before, re.IGNORECASE
            ):
                return m.group(0)
            return f"{head}' {word}"
        if low in ("γι", "απ") or (low == "μ" and next_low.startswith(
                ("αρέσ", "αρεσ", "άφησ", "αφησ", "έκα", "εκα", "έχει", "εχει"))):
            return f"{head}' {word}"
        return m.group(0)

    text = re.sub(rf"\b(σ|Σ|γι|Γι|ΓΙ|απ|Απ|ΑΠ|μ|Μ|τ|Τ|θ|Θ)[ \t]+({vowel_start}[Ͱ-Ͽ]+)", _elide, text)
    return text


_SIGMA_PREDICATES = frozenset({
    "είναι", "ήταν", "ισούται", "ορίζεται", "υπολογίζεται", "αντιστοιχεί", "εκτιμάται", "εκφράζει", "αυξάνεται",
    "ελαττώνεται", "ονομάζεται",
})


def format_greek_punctuation(text: str) -> str:
    """
    Cleans up punctuation spacing and ensures Greek publishing standards:
    - Removes whitespace before commas, full stops, semicolons, exclamation marks.
    - Ensures single space after commas and sentence stops.
    - Normalizes question marks (replaces English '?' with Greek ';' when in Greek sentence context,
      including '?!', '?!!', '??!!', and '...?').
    """
    # Protect URLs so query strings (?id=1) and relative paths (../) are never mangled
    url_stash: list[str] = []

    def _stash_url(m: re.Match) -> str:
        idx = len(url_stash)
        url_stash.append(m.group(0))
        return f"\x00URL_{idx}\x00"

    text = re.sub(r"(?:https?://|\bwww\.)[^\s<>\"'»]+", _stash_url, text)

    # Remove horizontal spaces/tabs before punctuation (never collapse newlines, never glue '.NET' or '.5')
    text = re.sub(r"[ \t]+([,:;!?·»]|\.(?!\w))", r"\1", text)
    # Remove horizontal space after opening guillemet / before closing guillemet
    text = re.sub(r"«[ \t]+", "«", text)
    text = re.sub(r"[ \t]+»", "»", text)
    # Fix multiple commas or accidental double periods (preserve ../ paths, 1..10 ranges, and ... ellipses)
    text = re.sub(r",,+", ",", text)
    text = re.sub(r"(?<=[^\.\d/])\.\.(?![\./\d])", ".", text)

    # Replace English question mark ? (including ?!, ??!!, ...?) with Greek ; when in Greek context
    has_greek_in_doc = bool(re.search(r"[\u0370-\u03ff]", text))

    def _to_greek_qm(m: re.Match) -> str:
        token = m.group(1)
        qmarks = m.group(2)
        if re.search(r"[\u0370-\u03ff]", token):
            return f"{token}{qmarks.replace('?', ';')}"
        # Also convert '?' after Latin acronyms/closing parens inside a Greek line (e.g. "Τι είναι το API?"),
        # only where the sentence can end ('int?[]', 'page?id=1' are code)
        if not re.match(r"[\s»\"'”’\)\]\.,…«—:;]|$", text[m.end():]):
            return m.group(0)
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_prefix = text[line_start:m.start()]
        if re.search(r"[\u0370-\u03ff]", line_prefix):
            return f"{token}{qmarks.replace('?', ';')}"
        return m.group(0)

    text = re.sub(r"([«»\"'\.\)\]\wΆ-ώ]+)([?!]+)", _to_greek_qm, text)
    # Also handle standalone comic interjections like "??!!" or "?!!" when document is Greek
    if has_greek_in_doc:
        text = re.sub(
            r"(?<=^)(?P<lead>[\s«\"'—–\-]*)(?P<qm>\?+[!?]*)(?P<trail>[\s»\"']*$)",
            lambda m: f"{m.group('lead')}{m.group('qm').replace('?', ';')}{m.group('trail')}",
            text,
            flags=re.MULTILINE,
        )

    for idx, orig_url in enumerate(url_stash):
        text = text.replace(f"\x00URL_{idx}\x00", orig_url)

    return text


# Scientific and SI units that should never be altered by homoglyph substitutions
_SCI_UNIT_RE = re.compile(r"^[μµΔΩαβγλσπρ][A-Za-z]{1,2}\d*$")


def clean_script_glitches_and_foreign_artifacts(text: str) -> str:
    """
    Cleans up subword cross-lingual script bleed, foreign words, and exotic token leaks:
    - Polish letters (ł, ś) in Greek verbs/words ('μπορούσłεś' -> 'μπορούσες', 'αναζητούłεś' -> 'αναζητούσες')
    - Micro sign (µ U+00B5) inside or prefixing Greek words -> μ (U+03BC)
    - Hebrew letter leaks (ד, ט, ם) -> ντ/τ/ν ('γανטωμένη' -> 'γαντωμένη', 'Αם' -> 'Αν')
    - Armenian letter leaks (ի, տ) -> ι/τ ('Γիου' -> 'Γιου', 'γανտρωμένο' -> 'γαντωμένο')
    - Georgian/Arabic/Devanagari/Ge'ez letter leaks
    - Vietnamese word leaks ('lần' / 'λầνες' -> 'φορές', 'trọng' / 'τρọνgος' -> 'άτρωτος')
    - Latin lookalikes and programming/code leaks ('Ta' -> 'Τα', 'iterrows' -> 'ίσως', 'podría' -> 'μπορούσε')
    - Subword Latin homoglyphs in Greek words (k -> κ, pt -> πτ, an -> αν, for -> φορ, etc.)
    """
    if not text:
        return text

    url_stash: list[str] = []

    def _stash_url(m: re.Match) -> str:
        idx = len(url_stash)
        url_stash.append(m.group(0))
        return f"\x00URL_{idx}\x00"

    text = re.sub(r"https?://[^\s<>\"'»]+", _stash_url, text)

    # 1. Polish glyphs bleed inside Greek words (e.g. 'μπορούσłεś', 'αναζητούłεś')
    text = re.sub(r"([α-ωΑ-Ωά-ώΆ-Ώ]+σ)łεś\b", r"\1ες", text)
    text = re.sub(r"([α-ωΑ-Ωά-ώΆ-Ώ]+)łεś\b", r"\1σες", text)
    text = re.sub(r"\bμπορούσłεś\b", "μπορούσες", text)
    text = re.sub(r"\bαναζητούłεś\b", "αναζητούσες", text)
    text = re.sub(r"(?<=[α-ωΑ-Ωά-ώΆ-Ώ])ł(?=[α-ωΑ-Ωά-ώΆ-Ώ])", "ε", text)
    text = re.sub(r"(?<=[α-ωΑ-Ωά-ώΆ-Ώ])ś\b", "ς", text)
    text = re.sub(r"(?<=[α-ωΑ-Ωά-ώΆ-Ώ])ś(?=[α-ωΑ-Ωά-ώΆ-Ώ])", "σ", text)

    # 2. Micro sign (U+00B5) inside or adjacent to Greek words
    text = re.sub(r"\u00B5(?=[α-ωΑ-Ωά-ώΆ-Ώ\-])", "μ", text)
    text = re.sub(r"(?<=[α-ωΑ-Ωά-ώΆ-Ώ])\u00B5", "μ", text)

    # 3. Hebrew letters leaking into Greek words
    text = text.replace("Κούρτσווייל", "Κούρτσβαϊλ")
    text = re.sub(r"\bΑם\b", "Αν", text)
    text = re.sub(r"σαדλπὸιντ", "σάντλποϊντ", text)
    text = re.sub(r"γανטωμέν([α-ωά-ώ]+)", r"γαντωμέν\1", text)

    # 4. Armenian letters leaking into Greek words
    text = text.replace("Γիου", "Γιου")
    text = text.replace("γανտρωμένο", "γαντωμένο")

    # 5. Georgian letters leaking into Greek words
    text = re.sub(r"ζαρ[\u10D0-\u10FF]+ότιοι", "ζάργκοναυτες", text)
    text = re.sub(r"(?<=[α-ωΑ-Ωά-ώΆ-Ώ])[\u10D0-\u10FF]+|[\u10D0-\u10FF]+(?=[α-ωΑ-Ωά-ώΆ-Ώ])", "", text)

    # 6. Arabic letters leaking into Greek words
    text = re.sub(r"Ταγματάρχه", "Ταγματάρχη", text)
    text = re.sub(r"Α‌هایς", "Άλλοι", text)

    # 7. Devanagari & Ge'ez letters leaking into Greek words
    text = text.replace("ॲλήθευε", "αλήθευε")
    text = text.replace("μπορούσህ", "μπορούσες")

    # 8. Vietnamese words/letters leaking into Greek
    text = text.replace("λầνες", "φορές")
    text = re.sub(r"(?<=ερικές )lần\b", "φορές", text)
    text = text.replace("ά trọng", "άτρωτος")
    text = text.replace("α trọng", "άτρωτος")
    text = text.replace("τρọνgος", "άτρωτος")
    text = re.sub(r"\b[ÍΊ]σως\b", "Ίσως", text)
    text = re.sub(r"\b[íί]σως\b", "ίσως", text)
    text = text.replace("﹢", "+")
    text = re.sub(r"(^|[.,;:!?\s«»—–\-])‘τοι([,.:;!?\s«»—–\-]|$)", r"\1έτσι\2", text)
    text = text.replace("\u2010", "-")

    # 9. Standalone Latin lookalikes in Greek context
    # Isolated 'Ta' -> 'Τα'
    text = re.sub(r"(^|[.,;:!?\s«»—–\-])Ta(?=[ \t]+[α-ωά-ώΑ-ΩΆ-Ώ])", r"\1Τα", text)

    # 10. Specific corrupted tokens & code leaks
    text = text.replace("αντιΗρισμού", "αντιπερισπασμού")
    text = text.replace("επιβΑνες", "επιβλαβείς")
    text = text.replace("αδοσυμεντεδ", "μη καταγεγραμμένων")
    text = re.sub(r"\bpodría(?= να\b)", "μπορούσε", text)
    text = re.sub(r"\bΉ iterrows ίσως\b", "Ή ίσως", text)
    text = re.sub(r"\bστην hull του\b", "στο κύτος του", text)
    text = re.sub(r"\bστο hull του\b", "στο κύτος του", text)
    text = re.sub(r"\bΤο riven φουσκωτό\b", "Το σχισμένο φουσκωτό", text)
    text = re.sub(r"\bτην Gang\b(?![ \t]*[A-Za-z&])", "τη Συμμορία", text)
    text = re.sub(r"\bτης Gang\b(?![ \t]*[A-Za-z&])", "της Συμμορίας", text)
    text = re.sub(r"\bΗ Gang\b(?![ \t]*[A-Za-z&])", "Η Συμμορία", text)
    text = re.sub(r"\bτην εμπιστοσύνη, Major\b", "την εμπιστοσύνη, Ταγματάρχη", text)
    text = re.sub(r"\bhangover μυαλά\b", "απρόσεκτα και μεθυσμένα μυαλά", text)
    text = re.sub(r"\bout εκεί έξω\b", "εκεί έξω", text)

    # 11. Subword Latin homoglyphs in Greek words
    def _fix_subword(m: re.Match) -> str:
        w = m.group(0)
        if "http" in w or "@" in w or _SCI_UNIT_RE.match(w) or not is_corrupt_greek_word(w):
            return w
        # Multi-letter subwords
        w = (
            w.replace("k", "κ")
            .replace("pt", "πτ")
            .replace("an", "αν")
            .replace("for", "φορ")
            .replace("ti", "τι")
            .replace("ka", "κα")
            .replace("to", "το")
            .replace("en", "εν")
            .replace("on", "ον")
            .replace("ri", "ρι")
            .replace("el", "ει")
            .replace("A", "Α")
            .replace("B", "Β")
            .replace("E", "Ε")
            .replace("H", "Η")
            .replace("I", "Ι")
            .replace("K", "Κ")
            .replace("M", "Μ")
            .replace("N", "Ν")
            .replace("O", "Ο")
            .replace("P", "Ρ")
            .replace("T", "Τ")
            .replace("X", "Χ")
            .replace("Y", "Υ")
            .replace("Z", "Ζ")
        )
        return w

    text = re.sub(
        r"(?<![A-Za-z0-9_\u0370-\u03ff])(?=[^\s]*[\u0370-\u03ff])(?=[^\s]*[A-Za-z])[^\s,;.:!?«»\"'()\[\]—–\-/\\*<>]+(?![A-Za-z0-9_\u0370-\u03ff])",
        _fix_subword,
        text,
    )

    for idx, orig_url in enumerate(url_stash):
        text = text.replace(f"\x00URL_{idx}\x00", orig_url)

    return text


def fix_literary_calques_and_glitches(text: str) -> str:
    """
    Corrects glaring literal machine translation idioms (comedy calques) and false friends:
    - 'κατινιάσει τα πέταλα' -> 'τινάξει τα πέταλα' (kicked the bucket)
    - 'άλωσε το πληκτρολόγιο' -> 'άρπαξε το πληκτρολόγιο' (took up the keyboard)
    - 'αλόγους της Παναγίας' -> 'αλογάκι της Παναγίας' (praying mantis)
    - 'το σκιασμένο πάνθηρα' -> 'το σκιασμένο πλαίσιο' (shaded panel)
    - 'για ζήση' -> 'για βιοπορισμό' (for a living)
    - 'να το λείψω' -> 'να ζήσω χωρίς αυτό' (do without it)
    - 'ανθρωπάκια της κάψουλας' -> 'άνθρωποι των λοβών' (pod people)
    - 'Είναι μια παρθένη, Σουζ' -> 'Είναι μια παραίσθηση, Σουζ' (form constant / hallucination)
    - 'σπερματική παρατήρηση' -> 'θεμελιώδης παρατήρηση' (seminal observation)
    - 'κουζίνα προμήθειες' -> 'προμήθειες της κουζίνας' (galley supplies)
    - 'Πέζαμε προς έναν τοιχώματα' -> 'Πέφταμε προς έναν τοίχο'
    """
    if not text:
        return text

    replacements = (
        (r"κατινιάσει τα πέταλα", "τινάξει τα πέταλα"),
        (r"άλωσε το πληκτρολόγιο", "άρπαξε το πληκτρολόγιο"),
        (r"αλόγους της Παναγίας", "αλογάκι της Παναγίας"),
        (r"το σκιασμένο πάνθηρα", "το σκιασμένο πλαίσιο"),
        (r"για ζήση\b", "για βιοπορισμό"),
        (r"(?<=μπορούσα )να το λείψω\b(?!\s+αυτ)", "να ζήσω χωρίς αυτό"),
        (r"ανθρωπάκια της κάψουλας", "άνθρωποι των λοβών"),
        (r"ανθρωπάκι της κάψουλας", "ανθρωπάκι των λοβών"),
        (r"Ανθρωπάκι της κάψουλας", "Ανθρωπάκι των λοβών"),
        (r"Είναι μια παρθένη, Σουζ", "Είναι μια παραίσθηση, Σουζ"),
        (r"σπερματική παρατήρηση", "θεμελιώδης παρατήρηση"),
        (r"κουζίνα προμήθειες", "προμήθειες της κουζίνας"),
        (r"Πέζαμε προς έναν τοιχώματα", "Πέφταμε προς έναν τοίχο"),
    )

    # 'άνθρωπος της κάψουλας' alone may be an astronaut: a calque only next to the 'pod people' diminutive
    if re.search(r"ανθρωπάκια? της κάψουλας|ανθρωπάκι της κάψουλας", text, re.IGNORECASE):
        text = re.sub(r"άνθρωπο(ς?) της κάψουλας", r"άνθρωπο\1 των λοβών", text)
    for pat, rep in replacements:
        text = re.sub(pat, rep, text)

    return text


def fix_double_accents_and_orthography(text: str) -> str:
    """
    Normalizes words with double accents that are OCR/Unicode or MT tone glitches
    (e.g. 'σκύλί' -> 'σκυλί', 'βαθύνόμενο' -> 'βαθαινόμενο', 'κύλούσαν' -> 'κυλούσαν').
    Strictly preserves legitimate Greek enclitic double-accentuation
    (e.g. 'το όνομά μου', 'κάνοντάς τα').
    """
    if not text:
        return text

    known_fixes = {
        "σκύλί": "σκυλί",
        "κύλούσαν": "κυλούσαν",
        "Ξστρίμώχτηκα": "Στριμώχτηκα",
        "βαθύνόμενο": "βαθαινόμενο",
        "Χαλάρώστε": "Χαλαρώστε",
        "Ανόξική": "Ανοξική",
        "τρέμουλιάζει": "τρεμουλιάζει",
        "αιώρούμενη": "αιωρούμενη",
        "Άπλώς": "Απλώς",
        "Σέρνικόμουν": "Σερνόμουν",
        "έσφυρηλάτησαν": "σφυρηλάτησαν",
        "παράταιρά": "παράταιρα",
        "υποχωρήτικά": "υποχωρητικά",
        "ενόςραδιενεργού": "ενός ραδιενεργού",
        "Τιναχτήκαπίσω": "Τιναχτήκαμε πίσω",
    }
    for bad, good in known_fixes.items():
        text = re.sub(rf"(?<!\w){re.escape(bad)}(?!\w)", good, text)

    # General algorithmic rule for double accents on non-enclitic words
    accent_chars = "άέήίόύώΆΈΉΊΌΎΏ"
    accent_map = {
        "ά": "α", "έ": "ε", "ή": "η", "ί": "ι", "ό": "ο", "ύ": "υ", "ώ": "ω",
        "Ά": "Α", "Έ": "Ε", "Ή": "Η", "Ί": "Ι", "Ό": "Ο", "Ύ": "Υ", "Ώ": "Ω",
    }

    def _fix_double_acc(m: re.Match) -> str:
        w = m.group(0)
        acc_indices = [i for i, c in enumerate(w) if c in accent_chars]
        if len(acc_indices) <= 1:
            return w
        tail = text[m.end():m.end() + 15]
        # Legitimate enclitic rule: antepenult accent + ultima accent before clitic pronoun
        if re.match(r"^\s+(?:(?:μου|μού|σου|σού|του|τού|της|τής|μας|μάς|σας|σάς|τους|τούς|με|σε|τον|την|τη|το|τα|τις|τες)\b"
                    r"|[μστ]['’])", tail, re.IGNORECASE):
            return w
        if not text[m.end():].strip():
            return w  # the end of a fragment: the pronoun may follow in the next formatting run or chunk
        chars = list(w)
        # If accents are separated by an intervening unaccented vowel (antepenult + ultima orphan enclitic),
        # the secondary orphan accent is on the ultima.
        # Otherwise (consecutive syllables), the first accent is the spurious OCR/tone glitch.
        vowels = "αεηιουωάέήίόύώϊϋΐΰΑΕΗΙΟΥΩΆΈΉΊΌΎΏ"
        has_intervening = any(c in vowels for c in w[acc_indices[0] + 1 : acc_indices[-1]])
        target_idx = acc_indices[-1] if has_intervening else acc_indices[0]
        chars[target_idx] = accent_map.get(chars[target_idx], chars[target_idx])
        return "".join(chars)

    text = re.sub(r"\b[α-ωΑ-Ωά-ώΆ-Ώϊϋΐΰ]{2,}\b", _fix_double_acc, text)
    return text


def fix_stutters_and_duplicate_tokens(text: str) -> str:
    """
    Removes machine translation duplicate word stutters and repeated section headers:
    - 'ο Σπίντελ ο Σπίντελ' -> 'ο Σπίντελ'
    - 'μια διασπασμένη μια διασπασμένη' -> 'μια διασπασμένη'
    - 'Παραπομπές\\n\\nΠαραπομπές' -> 'Παραπομπές'
    - 'μας μας' / 'μου μου' / 'τους τους' -> 'μας' / 'μου' / 'τους'
    """
    if not text:
        return text

    text = re.sub(r"\b([Οο]\s+Σπίντελ)\s+[Οο]\s+Σπίντελ\b", r"\1", text)
    text = re.sub(r"\b([Μμ]ια\s+διασπασμένη)\s+[Μμ]ια\s+διασπασμένη\b", r"\1", text)
    text = re.sub(r"(?m)^([ \t]*Παραπομπές)[ \t]*\n+[ \t]*Παραπομπές[ \t]*$", r"\1", text)

    # A doubled clitic is correct Greek ('η μητέρα μου μου είπε', 'της της έδωσε', 'πες το το βράδυ', 'πάρ' την την
    # Κυριακή'), so only a triple, or the never-doubled 'των', is a stutter.
    text = re.sub(r"\b(μας|μου|τους|της|τον|την|το)(?:[ \t]+\1\b){2,}", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(των)[ \t]+\1\b", r"\1", text, flags=re.IGNORECASE)

    return text


def sanitize_translated_urls(text: str) -> str:
    """
    Restores original URL paths that were erroneously translated into Greek
    (e.g. '.../βαμπίρ.htm' -> '.../vampires.htm').
    """
    if not text:
        return text

    text = re.sub(
        r"https?://www\.(?:ριfters|rifters)\.com/blindsight/βαμπ(?:[^\s<>»).,;]|\.(?=\w))*",
        "http://www.rifters.com/blindsight/vampires.htm",
        text,
    )
    text = text.replace("://www.ριfters.com", "://www.rifters.com")
    text = re.sub(
        r"https?://hctv\.humnet\.ucla\.edu/[^\s<>]*(?:ευρετήριο|VowειsανdCονsονανts)[^\s<>]*",
        "http://hctv.humnet.ucla.edu/departments/linguistics/VowelsandConsonants/index.html",
        text,
    )
    return text


def sanitize_editorial_pass(text: str, target_lang: str = "greek") -> str:
    """
    Complete Sanitization & Scripted Editorial Pass:
    Chains all editorial cleanup passes to ensure publication-grade Greek text:
    1. URL normalization and protection.
    2. Foreign script, tokenizer glitches & homoglyph normalization.
    3. Comedic calques, machine translation false friends & literal idiom fixes.
    4. Double accent and orthography correction.
    5. Duplicate word stutters and header cleanup.
    """
    if not text:
        return text
    if isinstance(target_lang, str) and target_lang.lower() not in ("greek", "el"):
        return text

    res = sanitize_translated_urls(text)
    res = clean_script_glitches_and_foreign_artifacts(res)
    res = fix_literary_calques_and_glitches(res)
    res = fix_double_accents_and_orthography(res)
    res = fix_stutters_and_duplicate_tokens(res)
    res = sanitize_translated_urls(res)
    return res


def format_greek_typography(
    text: str,
    enable_quotes: bool = True,
    enable_dialogue_dashes: bool = True,
    enable_final_nu: bool = True,
    enable_punctuation: bool = True,
    enable_editorial_sanitization: bool = True,
) -> str:
    """
    Comprehensive pipeline for Greek typography and editorial formatting.
    """
    if not text:
        return text

    res = fix_broken_hyphens(text)
    res = fix_greek_elision_apostrophes(res)
    if enable_editorial_sanitization:
        res = sanitize_editorial_pass(res)
    if enable_dialogue_dashes:
        res = format_dialogue_dashes(res)
    if enable_quotes:
        res = format_greek_quotes(res)
    if enable_final_nu:
        res = apply_final_nu_rules(res)
    if enable_punctuation:
        res = format_greek_punctuation(res)

    return res
