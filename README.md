# 📚 DocTranslate & AudioBook Generator

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: Passing](https://img.shields.io/badge/Tests-9%2F9%20Passed-brightgreen.svg)](tests/)

A modern, high-performance local web application to **translate documents** between English and Greek with **in-place format preservation** (fonts, sizes, headings, tables, styles), and **generate professional AI audiobooks** using Microsoft Edge neural voices.

---

## 📑 Documentation & Manuals (Εγχειρίδια)

* 📖 **[Εγχειρίδιο Χρήστη / User Manual (docs/USER_MANUAL.md)](docs/USER_MANUAL.md)**  
  *Αναλυτικός οδηγός βήμα-βήμα για τον απλό χρήστη: μετάφραση, επιλογή φορμάτ, διατήρηση μορφοποίησης, δημιουργία Audiobook και επεξήγηση προόδου.*
* 🛠️ **[Εγχειρίδιο Διαχειριστή / Admin Manual (docs/ADMIN_MANUAL.md)](docs/ADMIN_MANUAL.md)**  
  *Τεχνικός οδηγός για διαχειριστές: αρχιτεκτονική, απαιτήσεις, εγκατάσταση, λειτουργία ως Windows/Linux Service, ρυθμίσεις Nginx reverse proxy με SSE, συντήρηση και ασφάλεια.*

---

## ✨ Features (Χαρακτηριστικά)

| Feature | Details |
|---|---|
| **English ⇄ Greek Translation** | High-speed, robust translation using Google's direct GTX client API (milliseconds per chunk, zero bot-blocking). |
| **In-Place Format Preservation** | Translates `.docx` and `.epub` in-place, preserving font families, font sizes, headings, bold/italic, alignments, and tables. |
| **Translation Editor & Review** | Built-in in-browser Split-View / Full editor to review, edit, and search/replace translated text with live re-export. |
| **AI Polish & Proofreading** | Google Gemini AI integration to refine translated text or run standalone AI Polish on uploaded documents / pasted text without translating, with persistent API key storage (`config/settings.json`). |
| **Literature / E-Reader Layout** | Optional `layout=literature` mode for novels and books: preserves the original artwork cover image (PDF, EPUB, DOCX), reflows Kindle/iPad EPUB with TOC & serif CSS, and produces 6×9 trade-paperback PDF/DOCX with Georgia serif & cross-page sentence merging. |
| **Custom Glossary & Terminology** | Custom terminology mapping engine with regex word boundaries to enforce exact translations for domain terms. |
| **Instant On-Demand Export** | Switch output format (**PDF**, **DOCX**, **EPUB**, **TXT**) post-translation with immediate download (< 1s) without re-translating. |
| **Bullet & Glyph Normalization** | Replaces proprietary Wingdings/PUA symbols with standard Unicode bullets (`•`) and native Word `List Bullet` paragraphs. |
| **Multi-Format Export** | Export translated output to **DOCX**, **PDF** (Unicode Greek with TrueType fonts), **EPUB**, or **TXT**. |
| **AI Neural Audiobooks** | Generates high-fidelity MP3 audiobooks using Microsoft Edge neural voices. |
| **Greek Audio Support** | Native Greek neural voices: **Nestoras (Male)** with 100% dictionary coverage & **Athina (Female)** with automatic fallback. |
| **One-Click Direct Audio** | Convert any completed translation directly into a Greek Audiobook with a single click. |
| **Live Progress Streaming** | Real-time progress updates via Server-Sent Events (SSE) distinguishing between document pages and audio parts. |
| **Disk Recovery & Auto-Cleanup** | Completed jobs survive server restarts via disk recovery, while startup housekeeping (`cleanup_old_jobs`) prunes stale temp directories older than 24 hours. |
| **Automated Test Suite** | Comprehensive 9-part test suite verifying parsers, translator, exporters, format preservation, literature/e-reader formatting, dynamic download, editor/glossary/AI polish, and end-to-end APIs. |

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
│   ├── format_preserver.py  # In-place DOCX/EPUB formatting & styling preservation
│   ├── exporter.py          # Multi-format & literature/e-reader exporter (DOCX, PDF, EPUB, TXT)
│   ├── glossary.py          # Custom terminology mapping & regex replacement
│   ├── settings_manager.py  # Persistent application settings (config/settings.json)
│   ├── translator.py        # High-speed chunked Google GTX translation engine
│   ├── tts_engine.py        # Edge-TTS neural audio generator with voice fallback
│   ├── job_manager.py       # Job state tracking, disk recovery & startup cleanup
│   └── parsers.py           # Multi-mode extractors for PDF, DOCX, and EPUB
├── config/
│   ├── glossary.json        # Saved custom glossary terms
│   └── settings.json        # Local persistent settings (gitignored)
├── frontend/
│   ├── index.html           # Modern dark-mode single-page interface
│   ├── style.css            # Responsive CSS theme
│   └── app.js               # Frontend state, format picker & SSE stream handler
├── docs/
│   ├── USER_MANUAL.md       # Complete user guide in Greek
│   └── ADMIN_MANUAL.md      # Administrator deployment & technical manual
├── tests/
│   ├── test_parsers.py
│   ├── test_exporter.py
│   ├── test_translator.py
│   ├── test_format_preservation.py
│   ├── test_literature_formatting.py # Literature & e-reader formatting tests
│   ├── test_dynamic_download.py      # On-demand format conversion tests
│   ├── test_editor_glossary_ai.py    # Editor, Glossary & AI Polish tests
│   ├── test_standalone_ai_polish.py  # Standalone AI Polish & Settings API tests
│   └── test_api.py                   # End-to-end integration tests
├── temp/                    # Uploads and outputs directory (auto-created)
│   ├── uploads/
│   └── outputs/
├── requirements.txt
├── run.py                   # One-click automated launcher
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
python -c "import sys; sys.path.insert(0, '.'); import tests.test_parsers, tests.test_exporter, tests.test_translator, tests.test_format_preservation, tests.test_literature_formatting, tests.test_dynamic_download, tests.test_editor_glossary_ai, tests.test_standalone_ai_polish, tests.test_api"
```

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
