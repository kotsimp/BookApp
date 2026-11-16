"""
test_multivoice_and_m4b.py - Unit & Integration Tests for Multi-Voice Narration & M4B Audiobook Features.
Tests:
1. Multi-voice speaker tag parsing ([Nestoras]: ..., [Athina]: ...).
2. Automatic dialogue alternation (narrator vs characters).
3. ID3v2 & cover art metadata tagging via mutagen.
4. M4B container export and fallback tagging.
"""

import sys
sys.path.insert(0, ".")
import os
import unittest
from pathlib import Path

from backend.tts_engine import (
    split_into_voice_segments,
    tag_audiobook_file,
    export_audiobook_m4b,
)


class TestMultiVoiceAndM4B(unittest.TestCase):

    def test_explicit_speaker_tag_segmentation(self):
        print("-> 1. Testing Explicit Speaker Tag Segmentation...")
        script = (
            "[Narrator]: Το διαστημόπλοιο πλησίαζε τον άγνωστο πλανήτη.\n"
            "[Athina]: Βλέπω κάτι παράξενο στις οθόνες, είπε ανήσυχη.\n"
            "[Nestoras]: Κράτα σταθερή πορεία, απάντησε ο κυβερνήτης."
        )
        default_voice = "el-GR-NestorasNeural"
        dialogue_voice = "el-GR-AthinaNeural"

        segments = split_into_voice_segments(script, default_voice, dialogue_voice)
        self.assertEqual(len(segments), 3)

        # 1. Narrator segment
        self.assertIn("Το διαστημόπλοιο", segments[0][0])
        self.assertEqual(segments[0][1], default_voice)

        # 2. Athina segment
        self.assertIn("Βλέπω κάτι παράξενο", segments[1][0])
        self.assertEqual(segments[1][1], dialogue_voice)

        # 3. Nestoras segment
        self.assertIn("Κράτα σταθερή πορεία", segments[2][0])
        self.assertEqual(segments[2][1], default_voice)

        print("   Explicit speaker tags: OK")

    def test_automatic_dialogue_alternation(self):
        print("-> 2. Testing Automatic Dialogue Alternation...")
        dialogue_text = (
            "Ο ήλιος έδυε πίσω από τα βουνά.\n"
            "— Πρέπει να φύγουμε πριν νυχτώσει.\n"
            "Η σιωπή απλώθηκε στο δάσος.\n"
            "«Δεν φοβάμαι το σκοτάδι», ψιθύρισε η Μαρία."
        )
        narrator_voice = "el-GR-NestorasNeural"
        dialogue_voice = "el-GR-AthinaNeural"

        segments = split_into_voice_segments(dialogue_text, narrator_voice, dialogue_voice)
        self.assertEqual(len(segments), 4)

        # 1. Narration
        self.assertIn("Ο ήλιος έδυε", segments[0][0])
        self.assertEqual(segments[0][1], narrator_voice)

        # 2. Dialogue dash
        self.assertIn("Πρέπει να φύγουμε", segments[1][0])
        self.assertEqual(segments[1][1], dialogue_voice)

        # 3. Narration
        self.assertIn("Η σιωπή απλώθηκε", segments[2][0])
        self.assertEqual(segments[2][1], narrator_voice)

        # 4. Quotes
        self.assertIn("Δεν φοβάμαι το σκοτάδι", segments[3][0])
        self.assertEqual(segments[3][1], dialogue_voice)

        print("   Automatic dialogue alternation: OK")

    def test_id3_and_cover_tagging(self):
        print("-> 3. Testing ID3v2 & Cover Art Metadata Tagging...")
        tmp_dir = Path("temp/test_m4b_tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        sample_mp3 = tmp_dir / "sample_audio.mp3"
        # Write mock MP3 frames
        sample_mp3.write_bytes(b"\xFF\xFB\x90\x64" + b"\x00" * 2000)

        mock_cover = tmp_dir / "cover.jpg"
        mock_cover.write_bytes(b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"\x00" * 200)

        tag_audiobook_file(
            str(sample_mp3),
            title="Η Οδύσσεια του Διαστήματος",
            author="Arthur C. Clarke",
            cover_image_path=str(mock_cover),
        )

        from mutagen.id3 import ID3
        tags = ID3(str(sample_mp3))
        self.assertEqual(str(tags.get("TIT2")), "Η Οδύσσεια του Διαστήματος")
        self.assertEqual(str(tags.get("TPE1")), "Arthur C. Clarke")
        self.assertEqual(str(tags.get("TCON")), "Audiobook")
        self.assertIn("APIC:Cover", tags)

        print("   ID3v2 & cover tagging: OK")

    def test_m4b_export_fallback(self):
        print("-> 4. Testing M4B Container Export & Fallback Tagging...")
        import asyncio
        tmp_dir = Path("temp/test_m4b_tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        sample_mp3 = tmp_dir / "source.mp3"
        sample_mp3.write_bytes(b"\xFF\xFB\x90\x64" + b"\x00" * 1500)
        target_m4b = tmp_dir / "book.m4b"

        res = asyncio.run(export_audiobook_m4b(
            str(sample_mp3),
            str(target_m4b),
            title="Book Title",
            author="Author Name",
        ))
        self.assertTrue(Path(res).exists())
        self.assertGreater(Path(res).stat().st_size, 0)
        print("   M4B export & fallback tagging: OK")


if __name__ == "__main__":
    unittest.main()
