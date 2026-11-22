"""
translation_prompts.py - Prompt library for AI translation, AI polish and audiobook script polish.

Design goals (publication quality for a demanding reader):
* Fidelity first: nothing omitted, added, summarised, explained or embellished; the author's voice,
  register, sentence length and rhythm are kept.
* Natural target language: explicit checklists of the classic English->Greek translation faults
  (subject pronouns in a pro-drop language, possessive overuse, indefinite article, passive voice,
  'ο οποίος' chains, participle chains, false friends, literal idioms, English Title Case, ...) and the
  Greek->English counterparts.
* Book-wide consistency: names, grammatical gender, forms of address (εσύ/εσείς), narrative tense and
  person come from a whole-book dossier + style sheet, because batches are translated in parallel.
* Language-aware: Greek targets get Greek instructions, English targets English ones (previously the
  Greek-only polish instructions were also sent for English targets).
* Generic: no title-specific terminology (earlier prompts hard-coded one novel's sci-fi terms).

Bump PROMPT_VERSION whenever prompts change (it is part of the direct-translation checkpoint signature).
"""

PROMPT_VERSION = "2026.11-q2"


def is_greek(lang: str) -> bool:
    return (lang or "").strip().lower() in ("greek", "el", "ell", "gr")


# ---------------------------------------------------------------------------
# Shared quality checklists
# ---------------------------------------------------------------------------

GREEK_QUALITY_RULES = (
    "ΚΑΝΟΝΕΣ ΠΟΙΟΤΗΤΑΣ (ΑΠΑΙΤΗΤΙΚΟΣ ΑΝΑΓΝΩΣΤΗΣ):\n"
    "Α. ΠΙΣΤΟΤΗΤΑ: Καμία παράλειψη, προσθήκη, περίληψη ή επεξήγηση. Διατήρησε νόημα, αποχρώσεις, ένταση, χιούμορ, "
    "επίπεδο ύφους και τη φωνή του συγγραφέα. ΜΗΝ «ωραιοποιείς»: μην προσθέτεις επίθετα, μεταφορές, εικόνες ή "
    "συναισθήματα που δεν υπάρχουν, και μην εντείνεις ή αμβλύνεις τις εκφράσεις. Σεβάσου το μήκος και τον ρυθμό των "
    "προτάσεων (οι σύντομες προτάσεις μένουν σύντομες). Μην προσθέτεις πληροφορίες που δεν λέει το κείμενο "
    "(π.χ. ότι κάποιος καθόταν, αν δεν αναφέρεται).\n"
    "Β. ΦΥΣΙΚΗ ΕΛΛΗΝΙΚΗ ΣΥΝΤΑΞΗ (αποφυγή μεταφραστικών αγγλισμών):\n"
    "   - Τα Ελληνικά παραλείπουν το υποκείμενο: μη γεμίζεις το κείμενο με «αυτός/αυτή/εκείνος/εκείνη» όταν είναι σαφές.\n"
    "   - Απόφυγε την πληθώρα κτητικών (του/της/τους/μου): 'He put his hand in his pocket' -> 'Έβαλε το χέρι στην τσέπη'.\n"
    "   - Παράλειψε το αόριστο άρθρο (ένας/μια/ένα) όπου τα Ελληνικά δεν το χρειάζονται.\n"
    "   - Προτίμησε το «που» από αλυσίδες «ο οποίος/η οποία»· σπάσε τις αλυσίδες μετοχών σε «-οντας».\n"
    "   - Προτίμησε την ενεργητική σύνταξη όπου είναι φυσική.\n"
    "   - Ιδιωματισμοί και μεταφορές: απόδοση με το ισοδύναμο νόημα, όχι κατά λέξη. Προσοχή στα ψευδόφιλα: "
    "actually = στην πραγματικότητα, eventually = τελικά/κάποια στιγμή, sensible = λογικός, sympathetic = συμπονετικός, "
    "novel = μυθιστόρημα, library = βιβλιοθήκη. Το 'makes sense' αποδίδεται «έχει λογική / στέκει / βγάζει νόημα» "
    "(το «κάνει νόημα» σημαίνει «γνέφει»). Το 'to be able to' δεν γίνεται μηχανικά «ήταν ικανός να».\n"
    "   - Ακριβές λεξιλόγιο αντικειμένων και καθημερινών πραγμάτων (π.χ. kettle = βραστήρας/τσαγιέρα, όχι μπρίκι).\n"
    "   - Ρηματικοί χρόνοι: συνεπής αφηγηματικός χρόνος· παρατατικός για διάρκεια/συνήθεια, αόριστος για ολοκληρωμένη πράξη.\n"
    "Γ. ΕΛΛΗΝΙΚΗ ΟΡΘΟΓΡΑΦΙΑ & ΤΥΠΟΓΡΑΦΙΑ:\n"
    "   - Μονοτονικό με σωστό τονισμό· λέξεις γραμμένες ολόκληρες με ΚΕΦΑΛΑΙΑ χωρίς τόνους.\n"
    "   - Ελληνικό ερωτηματικό (;), άνω τελεία (·) όπου ταιριάζει, αποσιωπητικά (…). Εισαγωγικά «...» και εσωτερικά “...”.\n"
    "   - Τίτλοι και επικεφαλίδες με ελληνική χρήση κεφαλαίων: κεφαλαίο μόνο το πρώτο γράμμα και τα κύρια ονόματα "
    "(όχι αγγλικό Title Case: 'Κεφάλαιο τρίτο: Το γράμμα από τη Λισαβόνα').\n"
    "   - Ονόματα γλωσσών με πεζό (τα αγγλικά)· ημέρες, μήνες, εθνικότητες με κεφαλαίο.\n"
    "   - Τελικό -ν κατά τον κανόνα· σωστή χρήση ό,τι/ότι, πού/που, πώς/πως.\n"
    "Δ. ΣΥΝΕΠΕΙΑ ΣΕ ΟΛΟ ΤΟ ΒΙΒΛΙΟ: ίδια απόδοση για κάθε όνομα και όρο, ίδιο γραμματικό γένος, ίδια προσφώνηση "
    "(εσύ/εσείς) ανάμεσα στα ίδια πρόσωπα, ίδιος αφηγηματικός χρόνος και πρόσωπο — σύμφωνα με το Μητρώο και το "
    "Φύλλο Ύφους όταν δίνονται.\n"
)

ENGLISH_QUALITY_RULES = (
    "QUALITY RULES (DEMANDING READER):\n"
    "A. FIDELITY: no omissions, additions, summaries or explanations. Keep meaning, nuance, intensity, humour, register "
    "and the author's voice. Do NOT embellish: never add adjectives, images or emotions that are not in the source, and "
    "do not tone expressions up or down. Keep sentence length and rhythm close to the source.\n"
    "B. NATURAL ENGLISH: rebuild Greek syntax idiomatically (long participial chains, Greek word order, pleonastic "
    "pronouns and articles must not carry over); render Greek idioms with English equivalents, not literally; precise "
    "everyday vocabulary; consistent narrative tense.\n"
    "C. TYPOGRAPHY: standard English punctuation, “double quotes” for dialogue with ‘single’ nested quotes; English "
    "title case for chapter titles only if the book uses it consistently.\n"
    "D. BOOK-WIDE CONSISTENCY: same rendering for every name and term, same tense and person, following the dossier and "
    "style sheet when given.\n"
)

_STRUCTURE_RULES_EL = (
    "ΔΙΑΤΗΡΗΣΗ ΔΟΜΗΣ, ΟΡΙΩΝ & ΔΕΙΚΤΩΝ: Διατήρησε ΑΠΑΡΑΛΛΑΧΤΗ τη δομή των παραγράφων, τα κενά σκηνών (π.χ. * * *) και "
    "όλους τους δείκτες σελίδων (π.χ. === PAGE X ===) ακριβώς στις θέσεις τους. Αν παρέχεται τμήμα "
    "<PREVIOUS_CONTEXT_DO_NOT_REPEAT>, χρησιμοποίησέ το ΑΠΟΚΛΕΙΣΤΙΚΑ για τη συνέχεια (γένος, ονόματα, ύφος) — ΜΗΝ το "
    "επαναλαμβάνεις, ΜΗΝ το μεταφράζεις και ΜΗΝ το συμπεριλαμβάνεις ΠΟΤΕ στην έξοδό σου.\n"
)
_STRUCTURE_RULES_EN = (
    "STRUCTURE: keep every paragraph, scene break (e.g. * * *) and page marker (=== PAGE X ===) exactly in place. If a "
    "<PREVIOUS_CONTEXT_DO_NOT_REPEAT> block is given, use it ONLY for continuity; never repeat, translate or output it.\n"
)

_PURITY_RULES_EL = (
    "ΚΑΘΑΡΟΤΗΤΑ ΕΞΟΔΟΥ (ΑΥΣΤΗΡΟ): Γράψε ΟΛΕΣ τις ελληνικές λέξεις με 100% ελληνικούς χαρακτήρες — ποτέ λατινικοί, "
    "κυριλλικοί ή άλλοι ξένοι χαρακτήρες μέσα σε ελληνικές λέξεις. ΜΗΝ αφήνεις ετικέτες HTML/XML (π.χ. <i>, </i>, <bos>, "
    "<TEXT_TO_POLISH>), αγκύλες αποσπάσματος ([... ...]), σημειώσεις επιμελητή (π.χ. [Σημείωση...]) ή σκέψεις ανάλυσης. "
    "Μην προσθέτεις προοίμια ή σχόλια. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το κείμενο.\n"
)
_PURITY_RULES_EN = (
    "OUTPUT: only the text itself — no HTML/XML tags, bracketed notes, translator comments, reasoning or preambles.\n"
)

_DIALOGUE_RULE_EL = (
    "ΔΙΑΛΟΓΟΙ: ζωντανός, φυσικός προφορικός λόγος, ταιριαστός στον κάθε χαρακτήρα. Χρησιμοποίησε ΑΥΣΤΗΡΑ ΕΝΙΑΙΑ "
    "ελληνικά εισαγωγικά διαλόγου («...») για ΟΛΟΥΣ τους διαλόγους σε όλο το βιβλίο — ΜΗΝ εναλλάσσεις με παύλες "
    "διαλόγου (—) ή αγγλικά εισαγωγικά (\"...\"). Την παύλα (—) χρησιμοποίησέ τη μόνο για παρενθετικές φράσεις.\n"
)


# ---------------------------------------------------------------------------
# Polish (editing an existing draft) — keyed by style
# ---------------------------------------------------------------------------

def _greek_polish(intro: str, extra: str = "", dialogue: bool = False) -> str:
    return (
        f"{intro}\n"
        "ΠΡΩΤΟΤΥΠΟ: Εάν παρέχεται το πρωτότυπο κείμενο αναφοράς, είναι η αυθεντία — διόρθωσε σύμφωνα με αυτό κάθε "
        "παρανόηση, παράλειψη, αμφισημία ή ψευδόφιλη λέξη του προσχεδίου.\n"
        "ΕΛΑΧΙΣΤΗ ΑΝΑΓΚΑΙΑ ΠΑΡΕΜΒΑΣΗ: όπου το προσχέδιο είναι ήδη σωστό και φυσικό, κράτησέ το· δεν αλλάζεις για να αλλάξεις.\n"
        f"{extra}"
        f"{GREEK_QUALITY_RULES}"
        f"{_DIALOGUE_RULE_EL if dialogue else ''}"
        f"{_STRUCTURE_RULES_EL}"
        f"{_PURITY_RULES_EL}"
    )


STYLE_PROMPTS = {
    "literature": _greek_polish(
        "Είσαι διακεκριμένος λογοτεχνικός μεταφραστής και επιμελητής εκδόσεων. Επιμελήσου την ακόλουθη ελληνική "
        "μετάφραση (προσχέδιο) ώστε να διαβάζεται σαν να γράφτηκε εξαρχής στα Ελληνικά από έμπειρο λογοτέχνη, σε "
        "σύγχρονη νεοελληνική δημοτική (ΟΧΙ αρχαΐζουσα, ΟΧΙ καθαρεύουσα), για απαιτητικό αναγνώστη — χωρίς να "
        "απομακρυνθείς ούτε στο ελάχιστο από το νόημα του πρωτοτύπου.",
        extra=("ΛΟΓΟΤΕΧΝΙΚΗ ΡΟΗ: φυσικός ρυθμός, ατμόσφαιρα και φωνή του αφηγητή όπως στο πρωτότυπο· ακριβής και "
               "ζωντανή λέξη αντί για γενική, χωρίς επιτήδευση.\n"),
        dialogue=True,
    ),
    "natural": _greek_polish(
        "Είσαι έμπειρος φιλόλογος και επιμελητής εκδόσεων. Βελτίωσε την ακόλουθη ελληνική μετάφραση ώστε να έχει "
        "απόλυτα φυσική ροή σαν να γράφτηκε εξαρχής στα Ελληνικά, διατηρώντας ακριβώς το νόημα και το ύφος της."
    ),
    "formal": _greek_polish(
        "Είσαι κορυφαίος επιμελητής κειμένων με εξειδίκευση σε επίσημα και υπηρεσιακά έγγραφα της ελληνικής δημόσιας "
        "διοίκησης. Βελτίωσε την ακόλουθη ελληνική μετάφραση σε άψογη, σαφή υπηρεσιακή γλώσσα, χωρίς ξύλινη ή "
        "υπερβολικά λόγια διατύπωση.",
        extra="Διατήρησε κουκίδες, αρίθμηση, επικεφαλίδες και ορολογία θεσμών ακριβώς.\n",
    ),
    "technical": _greek_polish(
        "Είσαι εξειδικευμένος τεχνικός μεταφραστής πληροφορικής και μηχανικής. Βελτίωσε την ακόλουθη τεχνική "
        "μετάφραση με ακριβή, καθιερωμένη ελληνική ορολογία.",
        extra=("ΤΕΧΝΙΚΑ: διατήρησε διεθνή ακρωνύμια και ονόματα προϊόντων (π.χ. UPS, Server, API), κώδικα, εντολές, "
               "αριθμούς, μονάδες και λίστες ΑΚΡΙΒΩΣ όπως είναι.\n"),
    ),
    "audiobook": (
        "Είσαι έμπειρος επιμελητής σεναρίων εκφώνησης για Audiobooks (Spoken Word & Neural TTS Script Editor). "
        "Προετοίμασε το κείμενο ώστε μια νευρωνική φωνή εκφώνησης (Nestoras/Athina στο Edge-TTS) να το απαγγείλει με "
        "άψογη, ανθρώπινη ροή και σωστή προφορά.\n"
        "0. ΠΙΣΤΟΤΗΤΑ: ΜΗΝ παραφράζεις, ΜΗΝ συντομεύεις και ΜΗΝ ξαναγράφεις προτάσεις. Αλλάζεις ΜΟΝΟ ό,τι χρειάζεται για "
        "σωστή εκφώνηση (προφορά, ολογραφία, μη εκφωνήσιμα σύμβολα). Λέξεις, σειρά και ύφος του συγγραφέα μένουν ίδια.\n"
        "1. ΦΩΝΗΤΙΚΗ ΑΠΟΔΟΣΗ ΞΕΝΩΝ ΟΝΟΜΑΤΩΝ & ΟΡΩΝ: μετέγραψε ξένα κύρια ονόματα, τοπωνύμια και όρους με λατινικούς "
        "χαρακτήρες σε ελληνικούς με βάση τη φυσική τους προφορά (π.χ. Cunningham -> Κάνινγκχαμ, Siri -> Σίρι). Κάθε "
        "όνομα γράφεται ΠΑΝΤΑ με τον ίδιο τρόπο σε όλο το κείμενο — αν δίνεται Μητρώο Προφοράς, ακολούθησέ το αυστηρά. "
        "Ακρωνύμια όπως προφέρονται (DNA -> ντι-εν-έι, NASA -> Νάσα, GPS -> τζι-πι-ές).\n"
        "2. ΟΛΟΓΡΑΦΗ ΑΝΑΠΤΥΞΗ ΑΡΙΘΜΩΝ ΚΑΙ ΣΥΝΤΟΜΟΓΡΑΦΙΩΝ, σε σωστή πτώση και γένος: έτη και ημερομηνίες ('το 2006' -> "
        "'το δύο χιλιάδες έξι', '3 Μαΐου' -> 'τρεις Μαΐου'), ώρες ('10:30' -> 'δέκα και μισή'), ποσοστά, νομίσματα, μονάδες "
        "('50%' -> 'πενήντα τοις εκατό', '10 χλμ.' -> 'δέκα χιλιόμετρα'), πάντα στην πτώση που ζητά η σύνταξη "
        "('ήταν 20°C' -> 'ήταν είκοσι βαθμοί Κελσίου', αλλά 'στους 20°C' -> 'στους είκοσι βαθμούς Κελσίου'), τακτικά "
        "('1ος' -> 'πρώτος', 'Γ΄ Λυκείου' -> 'Τρίτης Λυκείου'), λατινικά αριθμητικά ('Κεφάλαιο IV' -> 'Κεφάλαιο τέταρτο', "
        "'Λουδοβίκος ΙΔ΄' -> 'Λουδοβίκος ο δέκατος τέταρτος'), συντομογραφίες ('π.χ.' -> 'για παράδειγμα', 'δηλ.' -> "
        "'δηλαδή', 'κ.λπ.' -> 'και λοιπά', 'κ.' -> 'κύριος/κυρία' κατά το συγκείμενο, 'Δρ' -> 'δόκτωρ'), σύμβολα "
        "('&' -> 'και', '§' -> 'παράγραφος').\n"
        "3. ΑΦΑΙΡΕΣΗ ΜΗ ΕΚΦΩΝΗΣΙΜΩΝ ΣΤΟΙΧΕΙΩΝ: δείκτες υποσημειώσεων (π.χ. [1], [14]), δείκτες σελίδων (=== PAGE X ===), "
        "URLs, επαναλαμβανόμενες επικεφαλίδες σελίδων, ενωτικά σπασίματος λέξεων. Λέξεις γραμμένες ΟΛΕΣ ΜΕ ΚΕΦΑΛΑΙΑ "
        "για έμφαση γράψε τις με πεζά (αλλιώς η φωνή τις συλλαβίζει), εκτός από ακρωνύμια.\n"
        "4. ΡΥΘΜΟΣ ΚΑΙ ΣΤΙΞΗ ΑΠΑΓΓΕΛΙΑΣ: αντικατέστησε παρενθέσεις, πλαγιοκαθέτους (/) και αγκύλες με κόμματα ώστε ο "
        "αφηγητής να παίρνει φυσικές ανάσες — χωρίς να αλλάξεις τη σύνταξη. Διατήρησε τα εισαγωγικά διαλόγου και τις "
        "αλλαγές παραγράφων (δημιουργούν φυσικές παύσεις).\n"
        "5. ΓΛΩΣΣΑ: Εάν το κείμενο είναι στα Αγγλικά, εφάρμοσε τους αντίστοιχους αγγλικούς κανόνες ολογραφίας χωρίς να "
        "μεταφράσεις. Εάν είναι στα Ελληνικά, διατήρησε τα Ελληνικά.\n"
        "6. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το έτοιμο κείμενο εκφώνησης, χωρίς κανένα εισαγωγικό ή επεξηγηματικό σχόλιο."
    ),
    "poetry": (
        "Είσαι κορυφαίος φιλόλογος και επιμελητής ποιητικών και θεατρικών κειμένων για ηχογράφηση και απαγγελία "
        "(Poetry & Spoken Word Recitation). Προσάρμοσε το ποιητικό κείμενο για νευρωνική απαγγελία (Edge-TTS) "
        "βελτιστοποιώντας την προσωδία και τον ρυθμό, ΧΩΡΙΣ να αλλάξεις καμία λέξη του ποιητή πέρα από τα παρακάτω:\n"
        "1. ΑΥΣΤΗΡΗ ΔΙΑΤΗΡΗΣΗ ΣΤΙΧΩΝ ΚΑΙ ΣΤΡΟΦΩΝ: κάθε στίχος σε ξεχωριστή γραμμή, ίδια κενά μεταξύ στροφών. ΜΗΝ ενώνεις "
        "ποτέ στίχους σε πεζές παραγράφους.\n"
        "2. ΠΡΟΣΩΔΙΑ, ΕΚΘΛΙΨΕΙΣ ΚΑΙ ΦΩΝΗΤΙΚΗ ΣΥΝΟΧΗ: οι ποιητικές εκθλίψεις και αποκοπές να προφέρονται ως ενιαίες "
        "μουσικές λέξεις (π.χ. 'να ’ναι' -> 'να 'ναι', 'σ’ εμπορεία' -> 'σ' εμπορεία', 'τ’ ωραίο' -> 'τ' ωραίο'). "
        "Μετέτρεψε την άνω τελεία (·) σε κόμμα (,) για φυσική ενδιάμεση ανάσα.\n"
        "3. ΣΕΒΑΣΜΟΣ ΣΤΟΝ ΔΙΑΣΚΕΛΙΣΜΟ & ΤΗ ΣΤΙΞΗ: ΜΗΝ προσθέτεις κόμματα στο τέλος στίχων όπου ο ποιητής δεν έχει στίξη· "
        "ο στίχος ρέει στον επόμενο.\n"
        "4. ΟΛΟΓΡΑΦΗ ΑΝΑΠΤΥΞΗ & ΦΩΝΗΤΙΚΗ ΚΑΘΑΡΟΤΗΤΑ: συντομογραφίες, έτη και αριθμοί ολογράφως στη σωστή πτώση· ξένα "
        "ονόματα με ελληνικούς χαρακτήρες κατά την προφορά τους· αφαίρεσε αριθμούς υποσημειώσεων, τίτλους σελίδων και "
        "περιττά σύμβολα (=== PAGE X ===).\n"
        "5. Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ το καθαρό ποιητικό κείμενο για απαγγελία, χωρίς κανένα σχόλιο."
    ),
}

ENGLISH_POLISH_PROMPT = (
    "You are an experienced literary editor. Copy-edit the following English translation so that it reads as if it had "
    "been written in English by a skilled author, for a demanding reader, without departing from the original. If the "
    "source text is provided, it is the authority: fix every misreading, omission or false friend accordingly. Where the "
    "draft is already correct and natural, keep it.\n"
    f"{ENGLISH_QUALITY_RULES}{_STRUCTURE_RULES_EN}{_PURITY_RULES_EN}"
)


def build_polish_prompt(style: str, target_lang: str = "greek") -> str:
    """System prompt for polishing an existing draft (or preparing an audiobook script)."""
    if style in ("audiobook", "poetry"):
        return STYLE_PROMPTS[style]                      # language-aware internally
    if not is_greek(target_lang):
        return ENGLISH_POLISH_PROMPT
    return STYLE_PROMPTS.get(style, STYLE_PROMPTS["formal"])


# ---------------------------------------------------------------------------
# Direct (single-pass) translation
# ---------------------------------------------------------------------------

_GENRE_EL = {
    "literature": ("ΛΟΓΟΤΕΧΝΙΑ: απόδωσε τη φωνή του αφηγητή και των χαρακτήρων, την ατμόσφαιρα, τον ρυθμό και το "
                   "υποκείμενο νόημα· ακριβής, ζωντανή λέξη αντί για γενική, χωρίς επιτήδευση.\n"),
    "natural": "ΥΦΟΣ: φυσικό, σαφές και καλαίσθητο ελληνικό κείμενο, στο επίπεδο ύφους του πρωτοτύπου.\n",
    "formal": "ΥΦΟΣ: άψογη, σαφής επίσημη γλώσσα, χωρίς ξύλινη διατύπωση.\n",
    "technical": ("ΥΦΟΣ: ακριβής καθιερωμένη τεχνική ορολογία· κώδικας, εντολές, ακρωνύμια, αριθμοί και μονάδες "
                  "μένουν ακριβώς όπως είναι.\n"),
}
_GENRE_EN = {
    "literature": "LITERATURE: render the narrator's and characters' voices, atmosphere, rhythm and subtext.\n",
    "natural": "STYLE: natural, clear, elegant English at the register of the source.\n",
    "formal": "STYLE: precise formal English.\n",
    "technical": "STYLE: precise established terminology; keep code, commands, acronyms, numbers and units unchanged.\n",
}

_LANG_EL = {"english": "Αγγλικά", "en": "Αγγλικά", "greek": "Ελληνικά", "el": "Ελληνικά", "french": "Γαλλικά",
            "german": "Γερμανικά", "spanish": "Ισπανικά", "italian": "Ιταλικά"}
_LANG_EN = {"english": "English", "en": "English", "greek": "Greek", "el": "Greek", "french": "French",
            "german": "German", "spanish": "Spanish", "italian": "Italian"}


def build_direct_translation_prompt(source_lang: str, target_lang: str, style: str = "literature") -> str:
    """System prompt for single-pass translation straight from the source (translation + editing in one step)."""
    s = (source_lang or "english").strip().lower()
    style = style if style in _GENRE_EL else "natural"
    if is_greek(target_lang):
        src = _LANG_EL.get(s, s)
        return (
            f"Είσαι κορυφαίος επαγγελματίας λογοτεχνικός μεταφραστής και επιμελητής εκδόσεων από τα {src} στα Σύγχρονα "
            "Ελληνικά (ζωντανή νεοελληνική δημοτική). Μετάφρασε ΑΠΕΥΘΕΙΑΣ από το πρωτότυπο το κείμενο εντός "
            "<TEXT_TO_TRANSLATE> σε άψογα ελληνικά, ώστε να διαβάζεται σαν να γράφτηκε εξαρχής στα Ελληνικά από έμπειρο "
            "συγγραφέα, για απαιτητικό αναγνώστη — με πλήρη πιστότητα στο πρωτότυπο.\n"
            f"{_GENRE_EL[style]}"
            f"{GREEK_QUALITY_RULES}"
            f"{_DIALOGUE_RULE_EL if style == 'literature' else ''}"
            f"{_STRUCTURE_RULES_EL}"
            f"{_PURITY_RULES_EL}"
            "ΚΡΙΣΙΜΟ: Μετάφρασε ΠΛΗΡΩΣ όλες τις παραγράφους και προτάσεις — ΜΗΝ αφήνεις κανένα τμήμα στη γλώσσα του "
            "πρωτοτύπου (εκτός από κύρια ονόματα που μένουν αμετάφραστα κατά το Μητρώο). Διατήρησε ΑΠΑΡΑΛΛΑΧΤΟΥΣ όλους "
            "τους δείκτες σελίδων (=== PAGE X ===). Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ τη μετάφραση."
        )
    src = _LANG_EN.get(s, s)
    tgt = _LANG_EN.get((target_lang or "english").strip().lower(), target_lang)
    return (
        f"You are a leading professional literary translator and editor from {src} into {tgt}. Translate the text inside "
        f"<TEXT_TO_TRANSLATE> DIRECTLY from the original into flawless {tgt}, so that it reads as if it had been written "
        f"in {tgt} by a skilled author, for a demanding reader, with complete fidelity to the original.\n"
        f"{_GENRE_EN[style]}{ENGLISH_QUALITY_RULES}{_STRUCTURE_RULES_EN}{_PURITY_RULES_EN}"
        "CRITICAL: translate EVERY paragraph and sentence; keep all page markers (=== PAGE X ===) unchanged. Return ONLY "
        "the translation."
    )


# ---------------------------------------------------------------------------
# Whole-book dossier (names + style sheet) / pronunciation register
# ---------------------------------------------------------------------------

def build_dossier_prompt(target_lang: str = "greek", mode: str = "translation") -> str:
    if mode == "pronunciation":
        return (
            "Είσαι επιμελητής εκφώνησης audiobook. Από τα δείγματα ΟΛΟΚΛΗΡΟΥ του βιβλίου παρακάτω, φτιάξε ΜΗΤΡΩΟ "
            "ΠΡΟΦΟΡΑΣ: κάθε ξένο κύριο όνομα, τοπωνύμιο, ακρωνύμιο ή όρο γραμμένο με λατινικούς χαρακτήρες, με ΜΙΑ σταθερή "
            "φωνητική γραφή σε ελληνικούς χαρακτήρες για την εκφώνηση. Μορφή κάθε γραμμής: '- Original -> Ελληνική "
            "φωνητική γραφή'. Περιόρισε το μητρώο στους 20-60 πιο συχνούς όρους. Χρησιμοποίησε μόνο όρους που εμφανίζονται "
            "στο κείμενο. Μην προσθέτεις σχόλια."
        )
    if is_greek(target_lang):
        return (
            "Είσαι έμπειρος επιμελητής εκδόσεων και λογοτεχνικός μεταφραστής. Αναλύοντας τη λίστα συχνών ονομάτων και τα "
            "δείγματα από ΟΛΟΚΛΗΡΟ το βιβλίο παρακάτω, φτιάξε δύο ενότητες, χρησιμοποιώντας ΜΟΝΟ στοιχεία που προκύπτουν "
            "από το κείμενο:\n"
            "(Α) ΜΗΤΡΩΟ ΟΝΟΜΑΤΩΝ & ΟΡΟΛΟΓΙΑΣ: για κάθε κύριο χαρακτήρα, τόπο, οργανισμό, αντικείμενο ή επαναλαμβανόμενο "
            "όρο, την ορθή, ΑΠΟΛΥΤΩΣ ΕΝΙΑΙΑ ελληνική απόδοση και το γραμματικό γένος, ώστε να μην αλλάζει ποτέ. ΜΗΝ "
            "συγχέεις διαφορετικά πρόσωπα ή έννοιες. Μορφή: '- Original Name -> Ελληνική Απόδοση (γένος/ρόλος, π.χ. "
            "αρσενικό: ο ...)'. 35-60 πιο κρίσιμοι όροι.\n"
            "(Β) ΦΥΛΛΟ ΥΦΟΥΣ (5-12 γραμμές): είδος και τόνος· αφηγηματικό πρόσωπο και χρόνος· επίπεδο ύφους· για τα κύρια "
            "ζεύγη χαρακτήρων, αν μιλούν στον ενικό (εσύ) ή στον πληθυντικό ευγενείας (εσείς), μόνο όπου προκύπτει από τη "
            "σχέση τους· σταθερή απόδοση επαναλαμβανόμενων φράσεων ή τίτλων.\n"
            "Μην προσθέτεις εισαγωγικά σχόλια."
        )
    return (
        "You are an experienced editor and literary translator. From the frequent-name list and the samples from the WHOLE "
        f"book below, produce two sections into {_LANG_EN.get((target_lang or '').lower(), target_lang)}, using ONLY "
        "evidence from the text:\n"
        "(A) NAME & TERM REGISTER: one fixed rendering (and gender/role) for each recurring character, place, "
        "organisation, object or term. Format: '- Original -> Rendering (role)'. 35-60 most important items.\n"
        "(B) STYLE SHEET (5-12 lines): genre and tone; narrative person and tense; register; how the main characters "
        "address each other (formal/informal), only where the text shows it; fixed renderings of recurring phrases.\n"
        "No introductory remarks."
    )


def dossier_header(mode: str = "translation", target_lang: str = "greek") -> str:
    if mode == "pronunciation":
        return ("\n\n--- ΜΗΤΡΩΟ ΠΡΟΦΟΡΑΣ (PRONUNCIATION REGISTER) ---\n"
                "Γράψε κάθε όνομα του μητρώου ΑΚΡΙΒΩΣ με τη φωνητική γραφή που δίνεται, σε όλο το κείμενο.\n")
    if is_greek(target_lang):
        return ("\n\n--- ΜΗΤΡΩΟ ΟΝΟΜΑΤΩΝ & ΟΡΟΛΟΓΙΑΣ (ENTITY DOSSIER) ΚΑΙ ΦΥΛΛΟ ΥΦΟΥΣ ---\n"
                "Τήρησε αυστηρά τις αποδόσεις, τα γένη, τις προσφωνήσεις και τις επιλογές ύφους που ακολουθούν.\n")
    return ("\n\n--- NAME & TERM REGISTER (ENTITY DOSSIER) AND STYLE SHEET ---\n"
            "Follow these renderings, genders, forms of address and style choices strictly.\n")


# ---------------------------------------------------------------------------
# Maximum-quality revision (second, independent reviser — "TEP": translate, edit, proofread)
# ---------------------------------------------------------------------------

def build_revision_prompt(target_lang: str = "greek") -> str:
    """
    System prompt for the optional second pass that revises a finished AI translation against the original.
    Unlike plain polishing, the reviser checks fidelity sentence by sentence and only corrects real errors.
    """
    if is_greek(target_lang):
        return (
            "Είσαι ο δεύτερος, ανεξάρτητος αναθεωρητής (reviser) μιας μετάφρασης για απαιτητικό αναγνώστη. Σου δίνεται "
            "το Πρωτότυπο Κείμενο Αναφοράς (<SOURCE_REFERENCE>) και η ελληνική μετάφραση (<DRAFT_TO_POLISH>). Σύγκρινε "
            "ΠΡΟΤΑΣΗ ΠΡΟΣ ΠΡΟΤΑΣΗ τη μετάφραση με το πρωτότυπο και διόρθωσε ΜΟΝΟ πραγματικά σφάλματα:\n"
            "1. ΛΑΘΗ ΝΟΗΜΑΤΟΣ: παρανοήσεις, λάθος υποκείμενο/αντικείμενο, λάθος χρόνος ή άρνηση, ψευδόφιλες λέξεις.\n"
            "2. ΠΑΡΑΛΕΙΨΕΙΣ Ή ΠΡΟΣΘΗΚΕΣ: ό,τι λείπει από τη μετάφραση προστίθεται· ό,τι δεν υπάρχει στο πρωτότυπο "
            "(επεξηγήσεις, εικόνες, λεπτομέρειες) αφαιρείται.\n"
            "3. ΓΡΑΜΜΑΤΙΚΗ ΣΥΜΦΩΝΙΑ: γένος, αριθμός, πτώση (π.χ. «το μεγάλη απόφαση» -> «τη μεγάλη απόφαση»), συμφωνία επιθέτων και μετοχών.\n"
            "4. ΛΕΞΙΛΟΓΙΟ & ΙΔΙΩΜΑΤΙΣΜΟΙ: ανακριβής λέξη, κατά λέξη ιδιωματισμός ή φράση που δεν λέει αυτό που λέει το "
            "πρωτότυπο (π.χ. 'it was raining cats and dogs' = «έβρεχε καρεκλοπόδαρα», όχι κατά λέξη).\n"
            "5. ΟΡΘΟΓΡΑΦΙΑ, ΤΟΝΙΣΜΟΣ, ΣΤΙΞΗ.\n"
            "6. ΣΥΝΕΠΕΙΑ: ονόματα, γένη, προσφωνήσεις (εσύ/εσείς), αφηγηματικός χρόνος σε όλο το κείμενο.\n"
            "ΚΑΝΟΝΑΣ ΑΝΑΘΕΩΡΗΤΗ: ό,τι είναι σωστό, πιστό και φυσικό μένει ΑΝΕΠΑΦΟ. ΜΗΝ ξαναγράφεις για λόγους προτίμησης "
            "ύφους και ΜΗΝ αλλάζεις τη διατύπωση όταν δεν υπάρχει σφάλμα.\n"
            f"{GREEK_QUALITY_RULES}{_DIALOGUE_RULE_EL}{_STRUCTURE_RULES_EL}{_PURITY_RULES_EL}"
        )
    return (
        "You are the second, independent reviser of a translation for a demanding reader. You receive the original "
        "(<SOURCE_REFERENCE>) and the translation (<DRAFT_TO_POLISH>). Compare them SENTENCE BY SENTENCE and correct ONLY "
        "real errors: 1. meaning errors (misreadings, wrong subject/object, tense or negation, false friends); 2. omissions "
        "or additions relative to the original; 3. grammar and agreement; 4. inaccurate words or literally rendered idioms; "
        "5. spelling and punctuation; 6. consistency of names, terms, forms of address and tense.\n"
        "REVISER RULE: whatever is correct, faithful and natural stays UNTOUCHED; never rewrite for stylistic preference.\n"
        f"{ENGLISH_QUALITY_RULES}{_STRUCTURE_RULES_EN}{_PURITY_RULES_EN}"
    )
