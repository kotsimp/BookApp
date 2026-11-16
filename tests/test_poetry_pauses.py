"""
Unit tests for Poetry & Literature pause handling and rhythm refinement in TTS engine.
"""

import unittest
from backend.tts_engine import _clean_tts_text, default_rates, default_pitches
from backend.ai_polisher import STYLE_PROMPTS


class TestPoetryPauses(unittest.TestCase):
    def test_poetry_enjambment_no_forced_comma(self):
        # A verse where line 1 continues into line 2 without punctuation (διασκελισμός)
        poem = (
            "αν μέν’ η σκέψις σου υψηλή, αν εκλεκτή\n"
            "συγκίνησις το πνεύμα και το σώμα σου αγγίζει."
        )
        cleaned = _clean_tts_text(poem, narration_style="poetry")
        # Must preserve verse line break and not inject comma after 'εκλεκτή'
        self.assertIn("εκλεκτή\nσυγκίνησις", cleaned)
        self.assertNotIn("εκλεκτή,", cleaned)

    def test_poetry_no_double_ellipsis(self):
        poem = (
            "Σα βγεις στον πηγαιμό για την Ιθάκη,\n"
            "να εύχεσαι νάναι μακρύς ο δρόμος.\n\n"
            "Τους Λαιστρυγόνας και τους Κύκλωπας,\n"
            "τον θυμωμένο Ποσειδώνα μη φοβάσαι."
        )
        cleaned = _clean_tts_text(poem, narration_style="poetry")
        self.assertNotIn("... ...", cleaned)
        self.assertNotIn("...", cleaned)
        # Stanzas must be separated by \n\n
        self.assertIn("\n\nΤους", cleaned)

    def test_greek_ano_teleia_normalized(self):
        poem = "θα μπαίνεις σε λιμένας πρωτοειδωμένους·\nκαι τες καλές πραγμάτειες ν’ αποκτήσεις."
        cleaned = _clean_tts_text(poem, narration_style="poetry")
        self.assertNotIn("·", cleaned)
        self.assertIn("πρωτοειδωμένους,\n", cleaned)

    def test_literature_no_awkward_ellipses_between_paragraphs(self):
        prose = (
            "Ήταν μια σκοτεινή και θυελλώδης νύχτα.\n\n"
            "Ο άνεμος λυσσομανούσε ανάμεσα στα δέντρα."
        )
        cleaned = _clean_tts_text(prose, narration_style="literature")
        self.assertNotIn("...", cleaned)
        self.assertIn("νύχτα. Ο άνεμος", cleaned)

    def test_slow_pauses_uses_single_gentle_ellipsis(self):
        prose = (
            "Ήταν μια σκοτεινή νύχτα.\n\n"
            "Όλα ήταν ήσυχα."
        )
        cleaned = _clean_tts_text(prose, narration_style="slow_pauses")
        self.assertIn("νύχτα. ... Όλα", cleaned)
        self.assertNotIn("... ...", cleaned)

    def test_poetry_rates_and_pitches(self):
        self.assertEqual(default_rates["poetry"], "-20%")
        self.assertEqual(default_pitches["poetry"], "-1Hz")
        self.assertIn("poetry", STYLE_PROMPTS)

    def test_generate_audiobook_style_variable_order(self):
        # Ensure style variable is defined before ai_polish check
        import asyncio
        from backend.tts_engine import generate_audiobook
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
            f.write("Σα βγεις στον πηγαιμό για την Ιθάκη.\n")
            tmp_in = f.name
        tmp_out = tmp_in.replace(".txt", ".mp3")

        try:
            async def run():
                await generate_audiobook(
                    job_id="test-regression-style-order",
                    file_path=tmp_in,
                    file_type="docx",
                    language="greek",
                    voice_name="Nestoras (Male)",
                    output_path=tmp_out,
                    translated_text_path=tmp_in,
                    narration_style="poetry",
                    ai_polish=True,
                    api_key="AQ.TestKeyOrderValidation",
                )
            asyncio.run(run())
        finally:
            for p in (tmp_in, tmp_out):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass


if __name__ == "__main__":
    unittest.main()
