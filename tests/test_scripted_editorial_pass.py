"""
test_scripted_editorial_pass.py - Comprehensive tests for the Sanitation and Scripted Editorial Pass.
Verifies automated remediation of:
1. Subword token bleed & exotic script leaks (Polish, Hebrew, Armenian, Georgian, Arabic, Devanagari, Ge'ez, Vietnamese, Latin).
2. Code & method leaks (iterrows, podría, hull, riven, Gang, Major, αδοσυμεντεδ).
3. Machine translation comedic calques & false friends (κατινιάσει τα πέταλα, άλωσε το πληκτρολόγιο,
   αλόγους της Παναγίας, σκιασμένο πάνθηρα, για ζήση, να το λείψω, ανθρωπάκια της κάψουλας, παρθένη).
4. Double accents and orthographic glitches while strictly preserving legitimate Greek enclitics.
5. Machine translation stutters and duplicate tokens.
6. Erroneously translated URLs restoration and URL path protection.
7. Seamless integration in format_greek_typography, sanitize_ai_output, and export_text pipelines.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
import unittest

sys.path.insert(0, ".")

from backend.typography import (
    clean_script_glitches_and_foreign_artifacts,
    fix_literary_calques_and_glitches,
    fix_double_accents_and_orthography,
    fix_stutters_and_duplicate_tokens,
    sanitize_translated_urls,
    sanitize_editorial_pass,
    format_greek_typography,
)
from backend.ai_polisher import sanitize_ai_output


class TestScriptedEditorialPass(unittest.TestCase):
    def test_1_polish_and_exotic_script_glitches(self):
        # Polish past-tense suffix bleed into Greek verbs
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("Θα μπορούσłεś να είχες κάνει τόσα πολλά περισσότερα."),
            "Θα μπορούσες να είχες κάνει τόσα πολλά περισσότερα.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("κατά πόσο αναζητούłεś μια ευρύτερη εξήγηση."),
            "κατά πόσο αναζητούσες μια ευρύτερη εξήγηση.",
        )

        # Micro sign (U+00B5) inside or prefixing Greek words
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("Δισεκατομμύρια µορίων και µ-ΟΠΙΟΕΙΔΩΝ ενώσεων."),
            "Δισεκατομμύρια μορίων και μ-ΟΠΙΟΕΙΔΩΝ ενώσεων.",
        )

        # Hebrew letter leaks
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("«Αם ήθελα θεραπεία, θα έβλεπα έναν θεραπευτή». Το σήμα στο σαדλπὸιντ."),
            "«Αν ήθελα θεραπεία, θα έβλεπα έναν θεραπευτή». Το σήμα στο σάντλποϊντ.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("πίεσε τη γανטωμένη παλάμη των γανטωμένων χεριών."),
            "πίεσε τη γαντωμένη παλάμη των γαντωμένων χεριών.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("το συμβόλαιό μου με την Κούρτσווייל συνειδητοποίησα."),
            "το συμβόλαιό μου με την Κούρτσβαϊλ συνειδητοποίησα.",
        )

        # Armenian letter leaks
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("«Γիου μου», μουρμούρισε. Το γανտρωμένο χέρι."),
            "«Γιου μου», μουρμούρισε. Το γαντωμένο χέρι.",
        )

        # Arabic & Devanagari & Ge'ez leaks
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("«Δεν κάνεις εσύ κουμάντο, Ταγματάρχه». Ίσως αυτό να ॲλήθευε, δεν μπορούσህ."),
            "«Δεν κάνεις εσύ κουμάντο, Ταγματάρχη». Ίσως αυτό να αλήθευε, δεν μπορούσες.",
        )

        # Vietnamese leaks
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("«Μερικές λầνες ένας είναι όλος κι όλος. Μερικές lần μένει ά trọng και τρọνgος»."),
            "«Μερικές φορές ένας είναι όλος κι όλος. Μερικές φορές μένει άτρωτος και άτρωτος».",
        )

    def test_2_code_leaks_and_foreign_word_contamination(self):
        # Code leak iterrows
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("Ή iterrows ίσως τον είχε υπολογίσει από πριν."),
            "Ή ίσως τον είχε υπολογίσει από πριν.",
        )
        # Foreign Spanish/English leaks
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("πίστευε ότι podría να υπήρχε κάποια επικοινωνία."),
            "πίστευε ότι μπορούσε να υπήρχε κάποια επικοινωνία.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("σκράμπλερ ξεχύθηκαν στην hull του Ρόρσαχ."),
            "σκράμπλερ ξεχύθηκαν στο κύτος του Ρόρσαχ.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("Το riven φουσκωτό συγκρούστηκε βίαια."),
            "Το σχισμένο φουσκωτό συγκρούστηκε βίαια.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("Άρπαξε την Gang από το πόδι της Gang."),
            "Άρπαξε τη Συμμορία από το πόδι της Συμμορίας.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("παρέμεναν μέχρι πρότινος αδοσυμεντεδ και άγνωστοι."),
            "παρέμεναν μέχρι πρότινος μη καταγεγραμμένων και άγνωστοι.",
        )
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("ότι υπήρχαν out εκεί έξω στον κόσμο."),
            "ότι υπήρχαν εκεί έξω στον κόσμο.",
        )

    def test_3_latin_lookalikes_and_subwords(self):
        # Standalone Ta -> Τα
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("Ta εννέα χιλιόμετρα που μας χώριζαν."),
            "Τα εννέα χιλιόμετρα που μας χώριζαν.",
        )
        # Subwords and specific corrupted words
        self.assertEqual(
            clean_script_glitches_and_foreign_artifacts("για λόγους αντιΗρισμού και επιβΑνες συνέπειες."),
            "για λόγους αντιπερισπασμού και επιβλαβείς συνέπειες.",
        )

    def test_4_machine_translation_calques_and_false_friends(self):
        self.assertEqual(
            fix_literary_calques_and_glitches("«Καλά, μας μιλάς, οπότε σίγουρα δεν έχεις κατινιάσει τα πέταλα.»"),
            "«Καλά, μας μιλάς, οπότε σίγουρα δεν έχεις τινάξει τα πέταλα.»",
        )
        self.assertEqual(
            fix_literary_calques_and_glitches("Το πτώμα άλωσε το πληκτρολόγιο χειρός."),
            "Το πτώμα άρπαξε το πληκτρολόγιο χειρός.",
        )
        self.assertEqual(
            fix_literary_calques_and_glitches("μακριά άκρα σαν πόδια αλόγους της Παναγίας."),
            "μακριά άκρα σαν πόδια αλογάκι της Παναγίας.",
        )
        self.assertEqual(
            fix_literary_calques_and_glitches("Κάποτε το σκιασμένο πάνθηρα φαινόταν να είναι μπροστά."),
            "Κάποτε το σκιασμένο πλαίσιο φαινόταν να είναι μπροστά.",
        )
        self.assertEqual(
            fix_literary_calques_and_glitches("«Πες μου πώς είναι να ξανακαλωδιώνεις τα κεφάλια των ανθρώπων για ζήση». «Το σφύριγμα θα μπορούσα να το λείψω»."),
            "«Πες μου πώς είναι να ξανακαλωδιώνεις τα κεφάλια των ανθρώπων για βιοπορισμό». «Το σφύριγμα θα μπορούσα να ζήσω χωρίς αυτό».",
        )
        self.assertEqual(
            fix_literary_calques_and_glitches("— Είναι μια παρθένη, Σουζ. Είχε μετατραπεί σε άνθρωπο της κάψουλας, ένα ανθρωπάκι της κάψουλας."),
            "— Είναι μια παραίσθηση, Σουζ. Είχε μετατραπεί σε άνθρωπο των λοβών, ένα ανθρωπάκι των λοβών.",
        )
        self.assertEqual(
            fix_literary_calques_and_glitches("Ήταν μια σπερματική παρατήρηση και χρειαζόμασταν κουζίνα προμήθειες. Πέζαμε προς έναν τοιχώματα."),
            "Ήταν μια θεμελιώδης παρατήρηση και χρειαζόμασταν προμήθειες της κουζίνας. Πέφταμε προς έναν τοίχο.",
        )

    def test_5_double_accents_and_enclitic_preservation(self):
        # Glitched words should have secondary accent eliminated
        self.assertEqual(
            fix_double_accents_and_orthography("Το σκύλί κύλούσαν στο βαθύνόμενο σκοτάδι. Χαλάρώστε, Άπλώς αιώρούμενη."),
            "Το σκυλί κυλούσαν στο βαθαινόμενο σκοτάδι. Χαλαρώστε, Απλώς αιωρούμενη.",
        )
        self.assertEqual(
            fix_double_accents_and_orthography("Ξστρίμώχτηκα μέσα. Ανόξική ατμόσφαιρα. Τιναχτήκαπίσω απότομα."),
            "Στριμώχτηκα μέσα. Ανοξική ατμόσφαιρα. Τιναχτήκαμε πίσω απότομα.",
        )
        # Orphan enclitic accent on proparoxytone words without enclitic pronoun
        self.assertEqual(
            fix_double_accents_and_orthography("Το όνομά ήταν άγνωστο και η απόφασή ήταν τελική."),
            "Το όνομα ήταν άγνωστο και η απόφαση ήταν τελική.",
        )

        # CRITICAL: Must strictly preserve legitimate Greek enclitic rules (antepenult + ultima before clitic)
        self.assertIn("το όνομά μου", fix_double_accents_and_orthography("το όνομά μου είναι Σίρι."))
        self.assertIn("ο δάσκαλός μας", fix_double_accents_and_orthography("ο δάσκαλός μας μάς είπε."))
        self.assertIn("κάνοντάς τα", fix_double_accents_and_orthography("κάνοντάς τα να νομίζουν."))
        self.assertIn("εκτοξεύοντάς τα", fix_double_accents_and_orthography("εκτοξεύοντάς τα πίσω."))

    def test_6_stutters_and_duplicate_tokens(self):
        self.assertEqual(
            fix_stutters_and_duplicate_tokens("τους είχε αποκαλέσει ο Σπίντελ ο Σπίντελ εκείνη τη μέρα."),
            "τους είχε αποκαλέσει ο Σπίντελ εκείνη τη μέρα.",
        )
        self.assertEqual(
            fix_stutters_and_duplicate_tokens("μια διασπασμένη μια διασπασμένη προσωπικότητα."),
            "μια διασπασμένη προσωπικότητα.",
        )
        self.assertEqual(
            fix_stutters_and_duplicate_tokens("Παραπομπές\n\nΠαραπομπές\n\n1. Watts, P."),
            "Παραπομπές\n\n1. Watts, P.",
        )
        # possessive + object clitic is correct Greek ("our ship gave us hope"): deleting one changes the meaning
        self.assertEqual(
            fix_stutters_and_duplicate_tokens("το σκάφος μας μας έδωσε ελπίδα."),
            "το σκάφος μας μας έδωσε ελπίδα.",
        )
        self.assertEqual(
            fix_stutters_and_duplicate_tokens("το σκάφος μας μας μας έδωσε ελπίδα."),
            "το σκάφος μας έδωσε ελπίδα.",
        )

    def test_7_url_sanitization_and_protection(self):
        raw = "Διαθέσιμο στο http://www.rifters.com/blindsight/βαμπίρ.htm και http://hctv.humnet.ucla.edu/departments/linguistics/VowelsandConsonants/ευρετήριο"
        sanitized = sanitize_translated_urls(raw)
        self.assertEqual(
            sanitized,
            "Διαθέσιμο στο http://www.rifters.com/blindsight/vampires.htm και http://hctv.humnet.ucla.edu/departments/linguistics/VowelsandConsonants/index.html",
        )

        # URL path components must never be damaged by subword substitutions
        url_text = "Επισκεφτείτε το http://example.com/department/token/entry.html για πληροφορίες."
        processed = sanitize_editorial_pass(url_text)
        self.assertIn("http://example.com/department/token/entry.html", processed)

    def test_8_end_to_end_format_greek_typography_integration(self):
        text = (
            "- «Καλά, δεν έχεις κατινιάσει τα πέταλα;» είπε.\n"
            "Ta νέα ήταν καλά. Το σκύλί ήταν ήρεμο. Θα μπορούσłεś να το δεις."
        )
        formatted = format_greek_typography(text)
        # Verify dialogue dash standardization
        self.assertTrue(formatted.startswith("— «Καλά, δεν έχεις τινάξει τα πέταλα;» είπε."))
        # Verify Latin lookalike Ta -> Τα
        self.assertIn("Τα νέα ήταν καλά.", formatted)
        # Verify double accent fix
        self.assertIn("Το σκυλί ήταν ήρεμο.", formatted)
        # Verify Polish glyph bleed fix
        self.assertIn("Θα μπορούσες να το δεις.", formatted)

    def test_9_ai_polisher_sanitize_ai_output_integration(self):
        leaked = (
            "<i>Θησέας</i> προσέγγισε.\n"
            "Ο Σπίντελ ο Σπίντελ πίστευε ότι podría να ήταν άλωσε το πληκτρολόγιο.\n"
            "[Σημείωση επιμελητή: έλεγχος κανόνων]\n"
            "**Review against Rules and Dossier:**\n* No introductory chatter? Checked.\n"
            "Proceed to output pure translated text."
        )
        cleaned = sanitize_ai_output(leaked)
        self.assertNotIn("<i>", cleaned)
        self.assertNotIn("Σημείωση", cleaned)
        self.assertNotIn("Review against", cleaned)
        self.assertNotIn("Proceed to output", cleaned)
        self.assertIn("Θησέας προσέγγισε.", cleaned)
        self.assertIn("Ο Σπίντελ πίστευε ότι μπορούσε να ήταν άρπαξε το πληκτρολόγιο.", cleaned)


if __name__ == "__main__":
    unittest.main()
