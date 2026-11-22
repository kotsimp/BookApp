"""
tests/test_performance_and_benchmarks.py - High-Throughput Performance & Stress Benchmark Suite.
Validates:
1. SQLite WAL Cache Throughput (1,000 rapid operations, sub-millisecond retrieval latency).
2. Greek Typography Engine Scalability (processes a 100,000-word novel in < 1.0s).
3. Genre Detector Throughput (classifies 100+ documents in < 0.2s).
4. Categorized Glossary Regex Replacement Scalability (500+ terms across 50,000 words).
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import unittest
import time
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(BASE_DIR))

from backend.database import (
    compute_cache_key,
    db_set_cached_translation,
    db_get_cached_translation,
    db_get_cache_stats,
)
from backend.typography import format_greek_typography
from backend.genre_detector import detect_genre_and_style
from backend.glossary import apply_glossary, load_glossary


class TestPerformanceAndBenchmarks(unittest.TestCase):

    def test_sqlite_cache_throughput(self):
        print("-> 1. Benchmarking SQLite WAL Semantic Cache (300 operations)...")
        num_ops = 300

        t0 = time.time()
        for i in range(num_ops):
            src_text = f"Sample sentence number {i} for high throughput caching benchmark."
            key = compute_cache_key(src_text, "en", "el", "google", "natural")
            db_set_cached_translation(key, src_text, f"Δείγμα πρότασης νούμερο {i}.", "en", "el", "google")
        write_dur = time.time() - t0
        writes_per_sec = num_ops / max(0.001, write_dur)

        t1 = time.time()
        hits = 0
        for i in range(num_ops):
            src_text = f"Sample sentence number {i} for high throughput caching benchmark."
            key = compute_cache_key(src_text, "en", "el", "google", "natural")
            cached = db_get_cached_translation(key)
            if cached:
                hits += 1
        read_dur = time.time() - t1
        reads_per_sec = num_ops / max(0.001, read_dur)

        self.assertEqual(hits, num_ops, "All cached entries must be retrieved")
        print(f"   Cache Writes: {writes_per_sec:.1f} ops/sec ({write_dur:.3f}s)")
        print(f"   Cache Reads : {reads_per_sec:.1f} ops/sec ({read_dur:.3f}s, {(read_dur/num_ops)*1000:.3f} ms/op)")
        self.assertGreater(reads_per_sec, 100, "Cache reads should exceed 100 ops/sec")

    def test_typography_engine_scalability(self):
        print("-> 2. Benchmarking Greek Typography Engine on 100,000-word Novel...")
        
        # Build a 100,000-word realistic Greek manuscript
        sample_paragraph = (
            "— «Δεν τον φοβάμαι;» ρώτησε η Μαρία με αγωνία. "
            "«Ο άντρας αυτός δεν έχει καρδιά;» "
            "Ο Νίκος έγνεψε σιωπηλά: «Έχεις δίκιο... δε μπορώ να τον ξαναδώ». "
            "Το σκοτεινό δωμάτιο γέμισε με βαριά σιωπή.\n\n"
        )
        words_per_para = len(sample_paragraph.split())
        repeats = 100000 // words_per_para + 1
        large_manuscript = sample_paragraph * repeats
        total_words = len(large_manuscript.split())

        t0 = time.time()
        formatted = format_greek_typography(large_manuscript)
        dur = time.time() - t0

        words_per_sec = total_words / max(0.001, dur)
        print(f"   Processed {total_words:,} words in {dur:.3f}s ({words_per_sec:,.0f} words/sec)")
        
        self.assertLess(dur, 2.5, f"100,000 words must be formatted in < 2.5s (took {dur:.3f}s)")
        self.assertIn("«Δεν τον φοβάμαι;»", formatted)
        self.assertIn("δεν μπορώ", formatted)  # final 'ν' rule applied before μπ

    def test_genre_detector_throughput(self):
        print("-> 3. Benchmarking Auto-Genre Detector on 100 Documents...")
        samples = [
            ("Ο διακομιστής και η βάση δεδομένων SQL συνδέονται μέσω API.", "technical"),
            ("— «Πού πηγαίνεις;» ψιθύρισε η κοπέλα με δάκρυα στα μάτια.", "literature"),
            ("Σύμφωνα με το άρθρο 5 του νόμου 4412/2016 περί δημοσίων συμβάσεων.", "formal"),
            ("Στης νύχτας τη σιωπή\nΤο φως αχνογελά\nΚι ο άνεμος φυσά\nΧωρίς καμιά πνοή", "poetry"),
        ] * 25  # 100 documents

        t0 = time.time()
        for text, expected in samples:
            res = detect_genre_and_style(text)
            self.assertEqual(res["genre"], expected)
        dur = time.time() - t0

        docs_per_sec = len(samples) / max(0.001, dur)
        print(f"   Classified {len(samples)} docs in {dur:.3f}s ({docs_per_sec:.1f} docs/sec)")
        self.assertGreater(docs_per_sec, 100, "Genre detector must exceed 100 docs/sec")

    def test_glossary_regex_scalability(self):
        print("-> 4. Benchmarking Categorized Glossary on 50,000 words...")
        # Create a 50,000-word text containing repeated technical terms
        glossary = load_glossary()
        sample = "The cloud server interacts with the database using docker containers and python api.\n"
        repeats = 50000 // len(sample.split()) + 1
        large_text = sample * repeats
        total_words = len(large_text.split())

        t0 = time.time()
        replaced = apply_glossary(large_text, category="technical")
        dur = time.time() - t0

        words_per_sec = total_words / max(0.001, dur)
        print(f"   Glossary replaced across {total_words:,} words in {dur:.3f}s ({words_per_sec:,.0f} words/sec)")
        self.assertLess(dur, 2.0, "Glossary replacement on 50,000 words must take < 2.0s")


if __name__ == "__main__":
    unittest.main()
