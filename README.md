# 📚 DocTranslate & AudioBook Generator

A powerful local web application to **translate documents** between English and Greek, and **generate professional audiobooks** with neural AI voices — supporting files up to 2,500 pages.

---

## ✨ Features

| Feature | Details |
|---------|---------|
| **Translation** | English ↔ Greek using Google Translate (free, no API key) |
| **Audiobook** | Neural TTS via Microsoft Edge voices (free, requires internet) |
| **Formats** | PDF, DOCX, EPUB |
| **Scale** | Up to 2,500 pages (large jobs run in background with live progress) |
| **Voices** | Greek: Athina (♀), Nestoras (♂) · English: Aria, Guy, Jenny, Davis, Emma, Ryan |
| **Output** | Translated `.txt` file · Audiobook `.mp3` file |

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.9 or higher** — [Download here](https://www.python.org/downloads/)
- Internet connection (for translation and TTS APIs)

### Run the App

```bash
python run.py
```

That's it! The script will:
1. Create a virtual environment (`.venv/`)
2. Install all dependencies automatically
3. Start the server at `http://localhost:8000`
4. Open your browser automatically

---

## 📖 How to Use

### Translate a Document
1. Click the **Translate Document** tab
2. Drag & drop or upload your PDF, DOCX, or EPUB file
3. Choose translation direction (English → Greek or Greek → English)
4. Click **Start Translation** and watch live progress
5. Download the translated `.txt` file when complete

### Generate an Audiobook
1. Click the **Generate Audiobook** tab
2. Upload your document
3. Select the **audio language** (English or Greek)
4. Pick a **voice** (female or male neural voices)
5. Optionally check "Use previously translated text" if you already translated the document
6. Click **Generate Audiobook** and monitor progress
7. Download your `.mp3` audiobook

---

## ⏱️ Processing Times

Approximate times depend on document length and internet speed:

| Document Size | Translation | Audiobook |
|---------------|-------------|-----------|
| 10 pages | ~1 minute | ~3 minutes |
| 100 pages | ~8 minutes | ~25 minutes |
| 500 pages | ~35 minutes | ~2 hours |
| 2,500 pages | ~2–3 hours | ~8–12 hours |

> **Tip:** Large audiobook jobs (500+ pages) can run overnight. The app tracks progress and the output is saved to `temp/outputs/` even if you close the browser tab.

---

## 📁 Project Structure

```
BookApp/
├── backend/
│   ├── main.py          # FastAPI app (REST + SSE endpoints)
│   ├── parsers.py       # PDF/DOCX/EPUB text extractors
│   ├── translator.py    # Chunked translation engine
│   ├── tts_engine.py    # Neural TTS audiobook generator
│   └── job_manager.py   # In-memory job state + SSE pub/sub
├── frontend/
│   ├── index.html       # Single-page app
│   ├── style.css        # Premium dark UI
│   └── app.js           # Client logic + SSE streaming
├── temp/                # Auto-created; stores uploads and outputs
│   ├── uploads/
│   └── outputs/
├── requirements.txt
├── run.py               # One-click launcher
└── README.md
```

---

## 🛠️ Manual Setup (Alternative)

If you prefer to manage the environment yourself:

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn backend.main:app --reload --port 8000
```

Then open `http://localhost:8000` in your browser.

---

## 🎙️ Available Voices

### Greek
| Voice | Code |
|-------|------|
| Athina (Female) | `el-GR-AthinaNeural` |
| Nestoras (Male) | `el-GR-NestorasNeural` |

### English
| Voice | Code |
|-------|------|
| Aria (Female, US) | `en-US-AriaNeural` |
| Guy (Male, US) | `en-US-GuyNeural` |
| Jenny (Female, US) | `en-US-JennyNeural` |
| Davis (Male, US) | `en-US-DavisNeural` |
| Emma (Female, UK) | `en-GB-SoniaNeural` |
| Ryan (Male, UK) | `en-GB-RyanNeural` |

---

## ⚠️ Known Limitations

- **`.doc` files**: Legacy Word `.doc` format is not supported. Save as `.docx` first.
- **Scanned PDFs**: PDFs that are image-only (scanned without OCR) will not extract text. Use a PDF with real text content.
- **Rate limiting**: Google Translate may occasionally slow down or block very rapid requests. The app includes automatic retry and rate limiting.
- **Internet required**: Both translation and TTS require internet access.

---

## 🔧 Troubleshooting

**"Cannot connect to backend" error in browser**
- Make sure `python run.py` is still running in your terminal
- Check that port 8000 is not used by another app

**Translation returns original text for some chunks**
- This is the retry fallback — occasional API hiccups won't break the whole job
- Check your internet connection

**Audiobook MP3 has silent gaps**
- Some TTS chunks may fail if the internet drops briefly; the gaps are where retries failed
- Re-run the audiobook job for a cleaner result
