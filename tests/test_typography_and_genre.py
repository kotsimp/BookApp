"""
test_typography_and_genre.py - Unit Tests for Greek Typography & Genre Detection Engines.
Tests:
1. Greek quotes conversion ("..." to «...»).
2. Dialogue em-dash standardization (—).
3. The Greek Rule of Final "ν" (δε/δεν and μη/μην).
4. Punctuation spacing and Greek question mark (;).
5. Automatic genre detection across poetry, technical, formal, literature, and comics.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import sys
sys.path.insert(0, ".")
import unittest

from backend.typography import (
    format_greek_quotes,
    format_dialogue_dashes,
    apply_final_nu_rules,
    format_greek_punctuation,
    format_greek_typography,
)
from backend.genre_detector import detect_genre_and_style


class TestTypographyAndGenre(unittest.TestCase):

    def test_greek_quotes(self):
        print("-> 1. Testing Greek Guillemets Quotation Conversion...")
        inp = 'Ο Πέτρος είπε "θα έρθω αύριο" και έφυγε.'
        out = format_greek_quotes(inp)
        self.assertEqual(out, 'Ο Πέτρος είπε «θα έρθω αύριο» και έφυγε.')
        print("   Greek quotes conversion: OK")

    def test_dialogue_dashes(self):
        print("-> 2. Testing Dialogue Dash Standardization (—)...")
        inp = "- Πού πας;\n- Στην πόλη, απάντησε ο Γιάννης."
        out = format_dialogue_dashes(inp)
        self.assertIn("— Πού πας;", out)
        self.assertIn("— Στην πόλη, απάντησε ο Γιάννης.", out)
        print("   Dialogue dashes: OK")

    def test_rule_of_final_nu(self):
        print("-> 3. Testing Modern Greek Rule of Final 'ν'...")
        # 1. Before continuants (β, γ, δ, ζ, θ, λ, μ, ν, ρ, σ, φ, χ), drop 'ν'
        self.assertEqual(apply_final_nu_rules("δεν θέλω"), "δε θέλω")
        self.assertEqual(apply_final_nu_rules("δεν φεύγω"), "δε φεύγω")
        self.assertEqual(apply_final_nu_rules("μην χάνεις"), "μη χάνεις")
        self.assertEqual(apply_final_nu_rules("μην λες"), "μη λες")

        # 2. Before vowels, keep 'ν'
        self.assertEqual(apply_final_nu_rules("δε ακούω"), "δεν ακούω")
        self.assertEqual(apply_final_nu_rules("μη έρθεις"), "μην έρθεις")

        # 3. Before plosives / doubles (κ, π, τ, ξ, ψ, μπ, ντ, γκ, τσ, τζ), keep 'ν'
        self.assertEqual(apply_final_nu_rules("δε ξέρω"), "δεν ξέρω")
        self.assertEqual(apply_final_nu_rules("δε μπορώ"), "δεν μπορώ")
        self.assertEqual(apply_final_nu_rules("δε τρέχω"), "δεν τρέχω")
        self.assertEqual(apply_final_nu_rules("μη πας"), "μην πας")

        # 4. Title case preservation
        self.assertEqual(apply_final_nu_rules("Δεν θέλω τίποτα."), "Δε θέλω τίποτα.")
        self.assertEqual(apply_final_nu_rules("Δε ξέρω πού είναι."), "Δεν ξέρω πού είναι.")
        print("   Rule of final 'ν': OK")

    def test_greek_punctuation(self):
        print("-> 4. Testing Punctuation Spacing & Greek Question Marks...")
        inp = "Λέξη , άλλη λέξη . Τι ώρα είναι?"
        out = format_greek_punctuation(inp)
        self.assertEqual(out, "Λέξη, άλλη λέξη. Τι ώρα είναι;")
        print("   Punctuation & question marks: OK")

    def test_full_typography_pipeline(self):
        print("-> 5. Testing Integrated Typography Pipeline...")
        raw = '- "δεν θέλω", είπε ο Νίκος , "δε ξέρω τίποτα" ?'
        formatted = format_greek_typography(raw)
        self.assertIn("— «δε θέλω»", formatted)
        self.assertIn("«δεν ξέρω τίποτα»;", formatted)
        self.assertNotIn(" ,", formatted)
        print("   Integrated typography pipeline: OK")

    def test_genre_detection(self):
        print("-> 6. Testing Document Genre & Style Auto-Detection...")

        # 1. Poetry
        poem = (
            "Στου πικραμένου την αυγή\n"
            "άνοιξε ρόδο και γιορτή\n"
            "μες στης καρδιάς το πέλαγο\n"
            "κι ο άνεμος σιωπά\n"
            "σα να προσμένει τη χαρά\n"
            "που χάθηκε μακριά"
        )
        res_poem = detect_genre_and_style(poem)
        self.assertEqual(res_poem["genre"], "poetry")
        self.assertEqual(res_poem["suggested_style"], "poetry")

        # 2. Technical
        tech = (
            "The architecture consists of a Docker container running a FastAPI server. "
            "The database client connects via IP and port with high bandwidth. "
            "We configure the CPU and RAM parameters to optimize query latency."
        )
        res_tech = detect_genre_and_style(tech)
        self.assertEqual(res_tech["genre"], "technical")
        self.assertEqual(res_tech["glossary_category"], "technical")

        # 3. Formal / Administrative
        formal = (
            "Σύμφωνα με το άρθρο 12 του νόμου και την απόφαση του υπουργείου "
            "που δημοσιεύθηκε στην εφημερίδα της κυβερνήσεως, ορίζονται οι εξής διατάξεις."
        )
        res_formal = detect_genre_and_style(formal)
        self.assertEqual(res_formal["genre"], "formal")
        self.assertEqual(res_formal["suggested_style"], "formal")

        # 4. Comics
        res_comic = detect_genre_and_style("any text", file_type="cbz")
        self.assertEqual(res_comic["genre"], "comic")

        print("   Genre & style auto-detection: OK")


if __name__ == "__main__":
    unittest.main()
