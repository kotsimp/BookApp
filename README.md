# 📚 DocTranslate & AudioBook Generator

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: Passing](https://img.shields.io/badge/Tests-24%2F24%20Passed-brightgreen.svg)](tests/)

A modern, high-performance local web application to **translate documents** between English and Greek with **in-place format preservation** (fonts, sizes, headings, tables, styles), **Graphic Novel & Manga translation** with 100% artwork preservation, and **generate professional AI audiobooks** (including multi-voice dramatization and M4B export) using Microsoft Edge neural voices.

---

## 📑 Documentation & Manuals (Εγχειρίδια)

* 📖 **[Εγχειρίδιο Χρήστη / User Manual (docs/USER_MANUAL.md)](docs/USER_MANUAL.md)**  
  *Αναλυτικός οδηγός βήμα-βήμα για τον χρήστη: μετάφραση εγγράφων, Graphic Novels & Manga (RTL), επιλογή φορμάτ (PDF, CBZ, CBR, EPUB), ελληνική τυπογραφική επιμέλεια, αυτόματη ανίχνευση είδους (Auto-Genre), πολυφωνικά audiobooks, ακρόαση δειγμάτων φωνής και Dark/Light Mode.*
* 🛠️ **[Εγχειρίδιο Διαχειριστή / Admin Manual (docs/ADMIN_MANUAL.md)](docs/ADMIN_MANUAL.md)**  
  *Τεχνικός οδηγός για διαχειριστές: SQLite database persistence (`data/bookapp.db`), σημασιολογική προσωρινή μνήμη μεταφράσεων (Semantic Cache), Storage Auto-Cleanup Garbage Collector, εκτέλεση ως Windows/Linux Service, Nginx reverse proxy με SSE, API endpoints και 24 αυτοματοποιημένα test suites.*

---

## ✨ Features (Χαρακτηριστικά)

| Feature | Details |
|---|---|
| **English ⇄ Greek Translation** | High-speed, robust translation using Google's direct GTX client API via HTTP POST with Greek character validation and exponential backoff on 429 (zero bot-blocking, no URL length limits). |
| **Persistent SQLite Database** | Full job state persistence across server restarts (`data/bookapp.db`) in WAL mode with connection locking, preventing data loss and allowing resumption of long tasks. |
| **Semantic Translation & Polish Cache** | SHA-256 content-hash based caching for translated paragraphs and AI-polished batches. Identical phrases return in 0ms with zero API/quota consumption and live hit statistics (`/api/cache/stats`). |
| **Storage Auto-Cleanup Garbage Collector** | Automated disk management (`backend/storage_cleaner.py`) that safely purges orphaned temporary audio chunks and extractions older than 48 hours while protecting user exports. |
| **Greek Editorial Typography Engine** | Built-in publishing typography standards (`backend/typography.py`): auto-conversion of straight quotes `"..."` to Greek guillemets `«...»`, standardization of dialogue hyphens to em-dash (`—`), automatic application of the modern Greek grammar rule for final "ν" (`δε/δεν`, `μη/μην`), and punctuation spacing normalization. |
| **Auto-Genre & Style Detection** | Real-time text analysis (`backend/genre_detector.py`) detecting Poetry, Literature, Technical, Formal, or Comic documents upon upload, auto-suggesting matching AI polish style and glossary category. |
| **Graphic Novel & Manga (RTL) Mode** | In-place comic translation preserving 100% original artwork. Translates balloon text, redacts original text with sampled background color, and auto-scales Greek font sizes (`fit-to-box` down to 5.5pt). Supports **Japanese Manga Right-to-Left (RTL)** balloon reading order and exports to **PDF, CBZ, CBR, and Fixed-Layout EPUB** with `page-progression-direction="rtl"`. |
| **Multi-Voice Audiobook Dramatization** | Next-generation audiobooks featuring distinct narrator and dialogue voices (e.g. Nestoras for narration + Athina for character speech), explicit speaker tags (`[Nestoras]: ...`, `[Athina]: ...`), and automatic quote dialogue routing. |
| **M4B & Tagged Audiobooks** | Exports audiobooks in both `.mp3` and `.m4b` formats with full ID3v2/MP4 metadata tagging (Title, Artist, Album, Genre="Audiobook") and embedded cover art via `mutagen`. |
| **Voice Preview Auditions** | Instant 2-3 second voice audition playback button (`🔊 Ακρόαση`) next to each voice in the UI without needing to generate full audio. |
| **Dark / Light Theme Toggle** | Sleek theme switcher in the UI header with instant switching and persistent memory in `localStorage`. |
| **Split-Screen Editor with Sync Scroll** | Side-by-side bilingual review editor with synchronized scrolling, find & replace, and live re-export. |
| **Desktop One-Click Launcher** | Standalone Windows script `start_bookapp.bat` to launch the virtual environment, start Uvicorn, and open the browser automatically. |
| **Automated Test Suite (24 Suites)** | Master test runner `run_all_tests.py` running 24 comprehensive test suites (100% pass rate) covering databases, caches, typography, comics, manga RTL, multi-voice TTS, concurrency, encoding, and APIs. |
| **In-Place Format Preservation** | Translates `.docx` and `.epub` in-place, preserving font families, font sizes, headings, bold/italic, alignments, and tables. |
| **Cover Image Management** | Auto-extraction of original artwork from PDF/EPUB/DOCX, live preview thumbnail with status `✔ Εξώφυλλο ενεργό`, manual upload for custom artwork (`.jpg`, `.png`, `.webp`), removal button (`DELETE /api/cover/{job_id}`), and strict download isolation ensuring only book documents are served. |
| **Literature / E-Reader Layout** | Dedicated `layout=literature` mode for novels and books: strips running headers/footers and page numbers, isolates chapter headings (*Πρόλογος*, *Θησεύς*, etc.) and epigraphs, merges cross-page sentences, formats scene breaks (`* * *`), and embeds full-bleed covers on page 1 of PDF/EPUB/DOCX. |
| **Multi-Page Front Matter Preservation** | Line-level header/footer cleaning (`_clean_page_blocks`) ensures the initial pages of books (tables of contents, epigraphs, author dedications, and prologues) are 100% preserved without dropping text blocks. |
| **Optimized AI Polish & Proofreading** | Google Gemini AI integration with 5 tailored styles (including dedicated `literature` for fiction & sci-fi and `audiobook` spoken narration script editor). Features **Bilingual Source-Anchoring** (page-level comparison between Greek draft and original English to fix mistranslations and false friends), **Entity & Character Consistency Dossier** (uniform character and term transliteration across chapters), **Rolling Narrative Context**, **Smart Real-Time Disk Checkpoints** (`.polish_checkpoint.json`), smart multi-page batching cutting API calls by 80%, dynamic backoff, and persistent settings (`config/settings.json`). |
| **Audiobook Script Polish & Spoken Phonetics** | Dedicated spoken script refinement for Edge-TTS neural voices: phonetically transliterates foreign names/acronyms into Greek script (`Keeton` -> `Κίτον`, `Rorschach` -> `Ρόρσαχ`, `DNA` -> `Ντι-Εν-Έι`), fully expands numbers, years, percentages, and abbreviations into spoken words (`2006` -> `δύο χιλιάδες έξι`, `50%` -> `πενήντα τοις εκατό`), completely strips non-spoken artifacts (page markers, footnotes, URLs), and optimizes sentence breathing and pauses. |
| **Translation Editor & Review** | Built-in in-browser Split-View / Full editor to review, edit, and search/replace translated text with live re-export. |
| **Custom Glossary & Terminology** | Custom terminology mapping engine with regex word boundaries to enforce exact translations for domain terms. |
| **Instant On-Demand Export** | Switch output format (**PDF**, **DOCX**, **EPUB**, **TXT**) post-translation with immediate download (< 1s) without re-translating. |
| **Bullet & Glyph Normalization** | Replaces proprietary Wingdings/PUA symbols with standard Unicode bullets (`•`) and native Word `List Bullet` paragraphs. |
| **Multi-Format Export** | Export translated output to **DOCX**, **PDF** (Unicode Greek with TrueType fonts), **EPUB**, or **TXT**. |
| **AI Neural Audiobooks** | Generates high-fidelity MP3 audiobooks using Microsoft Edge neural voices with balanced pacing presets (**Literature**, **Poetry & Recitation**, **Calm**, **Standard**, **Brisk**) along with interactive fine-tune sliders for **Speed** (-30% to +30%) and **Voice Pitch & Prosody** (-4Hz to +4Hz). Features theatrical prosody modulation, elision normalization, and refined verse pause handling that preserves poetic enjambment and strophic cadence. |
| **Greek Audio Support** | Native Greek neural voices: **Nestoras (Male)** with 100% dictionary coverage & **Athina (Female)** with automatic fallback. |
| **One-Click Direct Audio** | Convert any completed translation directly into a Greek Audiobook with a single click. |
| **Live Progress Streaming** | Real-time progress updates via Server-Sent Events (SSE) distinguishing between document pages and audio parts. |
| **Disk Recovery & Auto-Cleanup** | Completed jobs survive server restarts via disk recovery, while startup housekeeping (`cleanup_old_jobs`) prunes stale temp directories older than 24 hours. |
| **Automated Test Suite** | Comprehensive 11-part test suite verifying parsers, translator, exporters, format preservation, literature/e-reader formatting, dynamic download, editor/glossary/AI polish, front matter preservation, advanced bilingual polish, and end-to-end APIs. |

---

## 🚀 Quick Start (Γρήγορη Εκκίνηση)

### Prerequisites
* **Python 3.9 or higher** — [Download Python](https://www.python.org/downloads/)
* Internet connection (for translation and speech synthesis)

### Run with One Click
```bash
python run.py
```
The launcher will automatically create a virtual environment (`.venv/`), install all dependencies, start the FastAPI server at `http://localhost:8000`, and open your browser!

### Manual Installation
```bash
# Clone the repository
git clone https://github.com/kotsimp/BookApp.git
cd BookApp

# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\activate      # Windows (PowerShell)
# source .venv/bin/activate   # Linux / macOS

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## 📁 Project Structure (Δομή Έργου)

```
BookApp/
├── backend/
│   ├── main.py              # FastAPI application (REST endpoints & SSE streaming)
│   ├── ai_polisher.py       # Gemini AI proofreading & style polishing engine
│   ├── comic_translator.py  # Graphic Novel & Manga (RTL) balloon translator
│   ├── database.py          # SQLite database layer & SHA-256 semantic cache (data/bookapp.db)
│   ├── typography.py        # Greek editorial typography & final "ν" engine
│   ├── genre_detector.py    # Document genre, tone & style auto-detection engine
│   ├── storage_cleaner.py   # Temporary files & storage garbage collector
│   ├── format_preserver.py  # In-place DOCX/EPUB formatting & styling preservation
│   ├── exporter.py          # Exporter for DOCX, PDF, EPUB, TXT, CBZ, CBR
│   ├── glossary.py          # Categorized custom terminology mapping & regex replacement
│   ├── settings_manager.py  # Thread-safe persistent application settings
│   ├── translator.py        # High-speed chunked Google GTX translation engine
│   ├── tts_engine.py        # Multi-voice Edge-TTS neural audio generator & M4B exporter
│   ├── job_manager.py       # Persistent job state tracking, SQLite sync & cleanup
│   └── parsers.py           # Multi-mode extractors for PDF, DOCX, EPUB, CBZ, TXT
├── config/
│   ├── glossary.json        # Categorized custom glossary terms (Technical, Literature, General)
│   └── settings.json        # Local persistent settings (gitignored)
├── data/
│   └── bookapp.db           # Persistent SQLite database (jobs & translation cache)
├── frontend/
│   ├── index.html           # Modern single-page interface with Dark/Light theme
│   ├── style.css            # Responsive CSS theme with theme variables
│   └── app.js               # Frontend state, split-screen editor & voice preview
├── docs/
│   ├── USER_MANUAL.md       # Complete user guide in Greek
│   └── ADMIN_MANUAL.md      # Administrator deployment & technical manual
├── tests/                   # 24 Automated Test Suites (100% PASS)
├── run_all_tests.py         # Master unified test runner
├── start_bookapp.bat        # Windows one-click desktop launcher
├── requirements.txt
├── run.py                   # Automated Python launcher
└── README.md
```

---

## 🎙️ Available AI Voices (Φωνές)

### Greek (Ελληνικά 🇬🇷)
| Voice | Code | Notes |
|---|---|---|
| **Nestoras (Male)** | `el-GR-NestorasNeural` | *Recommended* — Natural intonation, complete dictionary coverage for acronyms & technical terms. |
| **Athina (Female)** | `el-GR-AthinaNeural` | Natural female voice with automatic fallback to Nestoras on unknown phonetic tokens. |

### English (Αγγλικά 🇬🇧 / 🇺🇸)
| Voice | Code |
|---|---|
| **Aria (Female, US)** | `en-US-AriaNeural` |
| **Guy (Male, US)** | `en-US-GuyNeural` |
| **Jenny (Female, US)** | `en-US-JennyNeural` |
| **Davis (Male, US)** | `en-US-DavisNeural` |
| **Emma (Female, UK)** | `en-GB-SoniaNeural` |
| **Ryan (Male, UK)** | `en-GB-RyanNeural` |

---

## 🧪 Running Tests (Αυτοματοποιημένοι Έλεγχοι)

To run the automated verification test suite:

```bash
python -c "import sys; sys.path.insert(0, '.'); import tests.test_parsers, tests.test_exporter, tests.test_translator, tests.test_format_preservation, tests.test_literature_formatting, tests.test_dynamic_download, tests.test_editor_glossary_ai, tests.test_standalone_ai_polish, tests.test_pdf_initial_pages_preservation, tests.test_ai_polish_advanced, tests.test_api"
```

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
