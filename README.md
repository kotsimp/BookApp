# 📚 DocTranslate & AudioBook Generator

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: Passing](https://img.shields.io/badge/Tests-68%2F68%20Suites%20Passed-brightgreen.svg)](tests/)

A modern, high-performance local web application to **translate documents** between English and Greek with **Single-Pass Direct AI Translation & Polish**, **in-place format preservation** (fonts, sizes, headings, tables, styles), **automatic Graphic Novel / Scanned Comic & Manga translation** with 100% artwork preservation, **professional AI audiobooks** (including multi-voice dramatization, M4B export, and synchronized read-along text) using Microsoft Edge neural voices, **deep Book Insights** (summaries, synopses, characters, chapter breakdowns, story recaps, blurbs, verified quotes, study guides, timelines, and grounded Q&A), and an **integrated Personal Library & E-reader ecosystem** (series continuity, self-learning glossary, OPDS catalogue, and KOReader reading-position sync). Supports a **Hybrid AI Architecture** allowing seamless operation with an up to 8-key Google Gemini pool or completely free, local/web alternatives.

---

## 📑 Documentation & Manuals

* 📖 **[User Manual (docs/USER_MANUAL.md)](docs/USER_MANUAL.md)**  
  *Comprehensive step-by-step user guide covering: Unified Upload & Smart Batch Queue (1–20 files), Prior Quota Routing Choice (Wait for Reset with live countdown timer vs Auto-Fallback to Free model), Automatic Free Mode default when no API key is provided, Single-Pass AI Translation & Polish (with live batch + page progress & full settings restore on Resume), automatic detection of Graphic Novels & Scanned PDFs (a scanned book read by Gemini Vision, or a comic with compatible options lock), a sample of a few pages first, the Gemini request estimate before starting, the bilingual edition, an e-reader catalogue (OPDS), reading along with audiobooks, Book Insights (summaries, synopses, characters & terms, chapter by chapter, the story so far, spoiler-free blurb, verified quotes, study guide, timeline, and questions to the book), Manga (RTL), format pickers (PDF, CBZ, CBR, EPUB), Greek editorial typography rules, auto-genre detection, multi-voice audiobooks, live voice auditions with instant stop, Refresh button, and Solar Dark/Light Mode.*
* 🛠️ **[Administrator & Deployment Manual (docs/ADMIN_MANUAL.md)](docs/ADMIN_MANUAL.md)**  
  *In-depth technical guide for system administrators: Hybrid AI architecture (Google Gemini + Free local/cloud models), quota management (circuit breaker, countdown, per-task routing, quota_behavior: 'wait' | 'fallback'), Free Mode automation, SQLite database persistence (`data/bookapp.db`) with metadata settings & `file_path` auto-healing, Smart Batch Queue engine (`backend/queue_manager.py`) with ZIP completion gating (HTTP 409 while items are running, immediate individual download for completed items), semantic translation & Vision AI caches (`gemini_polish_v4` full-prompt SHA-256 hash & `gemini_comic_vision_v2`), Single-Pass Full Gemini Flash with `thinkingBudget: 0`, `maxOutputTokens: 16384`, `BLOCK_NONE` safety settings, `thought` filtering, recursive page/paragraph bisection, `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` boundary deduplication, whole-book stratified Entity Consistency Dossier & Greek mixed-script quality gate, zero-tofu PDF glyph guard & URL wrapping, two-pass non-blank comic balloon renderer with natural CBZ page sorting & Zip Slip protection, 429 Circuit Breaker with automatic Gemini failover, universal `job_id` path-traversal validation, Storage Auto-Cleanup Garbage Collector, FastAPI lifespan, Nginx/Caddy reverse proxy with SSE, Final Output Refinement stage, publication-grade AI translation prompts, Book Insights, optional user accounts with administrators (setup code, account tool, HTTPS proxies), reading-position sync (kosync), book series, Glossary suggestions, the EPUB's Characters page, full library backup and restore, 110 routes, and 68 automated test suites.*

---

## ✨ Features

| Feature | Details |
|---|---|
| **Dual-Mode User Interface: Basic vs Advanced Mode (1-Click AI Magic)** | Seamless global mode toggle persisted in `localStorage`: **1. ⚡ Basic Mode**: Designed for maximum simplicity and zero cognitive load. AI is **enabled by default** for Translation (`tr-ai-polish`), Audiobook (`ab-ai-polish`), and Book Insights (1-Click Summary, 1-Click Synopsis, Ask the Book). Granular options are neatly tucked away. Just drop your file and click `✨ Translate Book with AI (1-Click)`, `🎧 Generate Audiobook with AI (1-Click)`, or ask a question directly — input format is automatically matched, document genre is auto-detected and auto-applied with visual confirmation (`✓ Auto-applied`), and audiobook defaults to Greek Nestoras neural voice with Literature pacing (-12% speed). **2. ⚙️ Advanced Mode**: Full granular control over all settings: source/target language direction, format selection (PDF, DOCX, EPUB, CBZ, CBR, TXT), layout styles (Standard, Literature, Comic), RTL manga direction, custom book cover upload, pitch & speed fine-tune sliders, multi-voice character dramatization, granular Book Insights analysis tools, maximum quality revision passes, and quota behavior choice (`wait` vs `fallback`). |
| **💡 Book Insights: Summaries, Synopses & Audio** | Dedicated **Book Insights** tab (`backend/book_insights.py`, `backend/api/insights.py`) offering deep document comprehension without needing external tools. Works with PDFs, Word documents, EPUBs, and scanned books (read via Gemini Vision). **Basic Mode:** *1-Click Summary* (short 150–300 word synthesis of main ideas and plot) and *1-Click Synopsis* (structured 800–1,200 word breakdown covering subject, structure, themes, key developments, and conclusions), written automatically in the language of the book. **Advanced Mode:** customizable word targets: one-sentence (20–40 words), short (150–300 words), and extended (500–1,000 words) summaries; standard (800–1,200 words) and extended (1,500–2,500 words) synopses; selectable output language (Greek or English); on-screen view or 1-click export to **PDF, DOCX, or TXT**. Every result can be narrated into high-quality speech with Microsoft Edge neural voices (**🎧 Create audio** with in-page player and downloadable MP3). Length is estimated from *meaningful* extracted text (page numbers, running headers and URLs removed; 1 page = 250 words); short sources scale targets down to avoid padding or hallucinated facts. Long books use cached map-reduce across section notes. Every text is strictly checked before display (language, sentence/word count, structure, Latin script in Greek, names/numbers absent from source, and condensation); defective outputs are regenerated once, and Greek outputs receive a dedicated proofreading pass. |
| **🔎 More Book Insights Suite: Characters, Chapters, Recaps, Quotes, Study Guides & Timelines** | Advanced analytical suite (`backend/insights_more.py`) generating seven specialized document views: **1. 👥 Characters & Terms (Πρόσωπα & όροι):** Identifies persons (roles, relationships) and specialized terms with definition and the exact page where each first appears. Omits dedication/epigraph names, links short aliases to full names, and offers a 1-click **➕ Ονόματα στο Γλωσσάρι** button to export Greek names directly into the custom Glossary. **2. 📑 Chapter by Chapter (Ανά κεφάλαιο):** 2–4 sentence summary for every chapter with page ranges; supports EPUB spine, PDF bookmarks, tables of contents, and headings, splitting oversized chapters into ~30-page sections `(1/4), (2/4)`. **3. 📖 Single Chapter in Detail (Ένα κεφάλαιο → Αναλυτικά):** Select any chapter for an in-depth 250–450 word breakdown (events, key characters, turning points, resolution) with zero spoilers for subsequent chapters. **4. 🧭 The Story So Far (Η ιστορία ως τώρα, έως σελίδα N):** Narrative recap up to page N (or EPUB chapter); only preceding pages are sent to prevent future plot leakage. **5. 📣 Spoiler-Free Blurb (Οπισθόφυλλο):** 80–130 word back-cover hook setting up the premise without spoiling twists; automatically populates the book description in the e-reader catalogue (OPDS). **6. ❝ Verified Quotes (Αποσπάσματα):** Up to 12 memorable quotes with significance notes; every quote is searched word-for-word in the text, discarding hallucinations and correcting citations. **7. 🎓 Study Guide (Οδηγός μελέτης):** Four-part educational guide featuring core themes, 8–10 discussion questions, an 8-question quiz, and an answer key. **8. 🕰️ Story Timeline (Χρονολόγιο):** Up to 40 chronological story events in narrative order with dates/seasons and verified page numbers. Multi-key parallel acceleration reads long books across up to 6 concurrent requests. |
| **💬 Ask the Book: Grounded Interactive Q&A** | Interactive question-and-answer interface (`backend/insights_more.py`) available in both Basic and Advanced Mode. Every answer is grounded **strictly and exclusively in the text of the book**, citing supporting pages (e.g. `(σ. 42)`); when the book does not contain the answer, it explicitly states so rather than guessing. Books up to ~350k characters (~200 pages) are evaluated in full; longer books use a light model to translate question terms into the book's language, retrieve surrounding text windows, and merge with chapter outlines. Answers match the language of your question or chosen target. Preserves the last 30 questions and answers with individual deletion (**🗑️**) and bulk clearing (**🗑️ Διαγραφή όλων**). Cached responses return instantly without consuming API quota. |
| **📚 Your Library: Series, Learning Glossary, Characters Page, Reading Sync & Backups** | Comprehensive personal library management (`backend/series.py`, `backend/glossary_learning.py`, `backend/epub_extras.py`, `backend/reading_sync.py`, `backend/backup.py`): **1. 📚 Book Series:** Link books in a sequence (e.g. *The Expanse #1, #2, #3*); subsequent books automatically inherit character names, terminology, and spelling choices established by earlier volumes and editorial revisions. Earlier volume summaries appear in Book Insights (**📚 Πριν από αυτό το βιβλίο**) to refresh context. **2. 💡 Self-Learning Glossary:** Following each translation or global replacement in Review & Edit, newly identified character and domain names are proposed at the top of the Glossary window with conflict detection, nominative case normalization, and warnings for dual-use everyday words. Nothing is added without user approval. **3. 👥 Characters Page in EPUB:** Generates an optional *Dramatis Personae* front-matter page in translated EPUBs from the Book Insights characters list, introducing characters as first encountered without plot spoilers. **4. 🔄 Reading-Position Sync:** Built-in KOReader-compatible synchronization server at `/kosync` (compatible with KOReader and Readest) tracking reading progress and powering "The Story So Far" up to your exact page. **5. 💾 Full Library Backup & Restore:** 1-click comprehensive ZIP archive containing all books, translations, insights, covers, series, reading positions, and glossaries (with optional audiobooks toggle), equipped with path-traversal safeguards and tamper-proof restoration validation. |
| **📲 Devices: E-Reader Catalogue (OPDS)** | Built-in **OPDS catalog server** (`/opds/<token>/`, protected by tokenized hash) allowing e-readers and mobile apps (KOReader, Moon+ Reader, Librera, Panels, Readest) to browse, search, and download your finished library directly over Wi-Fi as EPUB, PDF, bilingual EPUB, or CBZ. Isolated per user when authentication is enabled. |
| **📖 Reading Along with Audiobooks** | Real-time sentence-level text tracking (`backend/tts_engine.py` with `<audiobook>.sync.json`) integrated directly into the pro audiobook player (**📖 Κείμενο**). Highlights the sentence currently being narrated, follows along automatically, and allows 1-click seeking to start playback from any selected sentence. |
| **Gemini Multi-Key API Pool & Auto-Failover (Up to 8 Keys)** | Configure **up to 8 free Google Gemini API keys** simultaneously in the Settings modal (Slot 1 Primary + Slots 2–8 Backups) from different Google accounts. Requests take keys in **concurrent round-robin rotation** (Slots 1–8), multiplying both per-minute burst rate and total daily capacity. Prioritizes the best models across **all** configured keys before degrading to lighter tiers. Features **sliding-window rate limiting** (`GeminiRateLimiter`), explicit `Retry-After` header parsing, **per-model cooldown isolation**, transient burst retry handling, live navbar badges (`🟢 8/8 Keys`, `🟡 Partial`, `⏳ Cooldown`, `🆓 Free Mode`), and an in-depth wait status window detailing which models reached limits on which keys, reset countdowns, and affected jobs. Keys are stored encrypted/masked on the server only and never exposed to the client. Features instant **Auto-Resume on Save**. |
| **Single-Pass Direct AI Translation & Polish** | When **AI Polish** is enabled with a Gemini API key, books and documents translate & polish in **one single parallel pass** (5 concurrent workers, prioritizing full Gemini Flash models over Flash-Lite, `maxOutputTokens: 16384`, `thinkingBudget: 0`, `safetySettings: BLOCK_NONE`, `thought: true` part filtering, and `5500 chars / max 3 pages` safe batching) — with **recursive multi-page & paragraph-level bisection** on `MAX_TOKENS`, `SAFETY`, or timeouts, **XML-delimited `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` + deterministic boundary deduplication**, **whole-book stratified Entity Consistency Dossier** (frequency scan + 9 evenly spaced excerpts for 35–60 terms with grammatical gender & anti-conflation), uniform Greek dialogue guillemets (`«...»`), **targeted mixed-script retry**, style-aware Glossary isolation, Disk Checkpointing, exact live progress, and full settings restore on Session History resume. |
| **🏆 Maximum Quality: Second AI Revision Against the Original (Advanced Mode)** | Optional checkbox under AI Polish (`max_quality: true`). Following initial translation, an independent secondary Gemini reviser compares the draft **sentence by sentence with the original source** (page-aligned `<SOURCE_REFERENCE>`/`<DRAFT_TO_POLISH>` batches). Fixes only real errors: meaning divergences, omissions/additions, grammatical agreement, inaccurate vocabulary, literal idioms, and orthography, leaving correct text untouched. Runs on **full Gemini models only** (skipped gracefully if only Lite models are available). Retains draft safety guarantees (rejecting corrupted page markers or implausible length ratios) and reports all edits via `revision_report`. |
| **In-Place Format Preservation (DOCX, EPUB, PDF, TXT)** | Translates `.docx` (preserving fonts, headings, bold/italic, tables, merged cells & embedded inline images `<w:drawing>`) and `.epub` (preserving spine order, nested HTML tags `<em>`/`<strong>`/`<blockquote>`, inline whitespace & CSS without double-translating) in-place with style-aware glossary & Greek typography cleanup. Gemini translates paragraphs, runs, and text nodes in numbered, context-preserving batches (`backend/ai_segment_translator.py`). Later edits (Editor, AI Polish) are applied inside the original file (`backend/format_sync.py`), guarding against destructive plain-text re-exports. |
| **Automatic Graphic Novel & Scanned PDF Detection** | Upload inspection (`detect_is_graphic_novel()`) examines CBZ/CBR archives and PDF pages (image coverage, vector text density, artwork cues) to automatically identify graphic novels and lock the UI to graphic-novel options while disabling incompatible text selectors. **Scanned PDFs require no external OCR**: the system distinguishes between **📖 Book** (page text extracted once by Gemini Vision on Flash-Lite and translated/narrated like a digital book) and **🎨 Comic** (translated directly on page images). Enforces 250 MB streaming upload limits, sanitizes filenames, and guards against path traversal. |
| **Parallel Scanned Comic Vision AI, Manga (RTL) & Real CBR Exports** | Translates both digital and scanned comics & Manga while preserving 100% of underlying artwork. Features **CBZ Zip Slip protection**, natural numeric page sorting, **3 parallel Full-Flash Gemini Vision workers** (`gemini_comic_vision_v2` SHA-256 cache, `maxOutputTokens: 8192`, clamped `[0..1000]` bounding boxes, dialytika+tonos sanitization), and a **two-pass non-blank balloon renderer** down to `3.0pt`. Exports to **PDF, CBZ, real CBR (RAR format via 7-Zip/bsdtar)**, and **Fixed-Layout EPUB** (with RTL progression). Comic archives are built in an isolated child process (`backend/comic_build.py`) so the server remains fully responsive during heavy packaging, preserving native scan resolution (1,600–2,560 px). |
| **Bilingual Edition (Side-by-Side & Paragraph-by-Paragraph)** | 1-click **🔀 Δίγλωσσο** generation from the translation result card (`backend/bilingual.py`). Pairs original source paragraphs with their translated counterparts (with original text formatted smaller and in subtle grey) across PDF, DOCX, and EPUB. Uses Gale & Church length alignment and page-marker synchronization to ensure texts never drift out of alignment. |
| **Sample First & Gemini Request Estimate** | Pre-flight estimator (`GET /api/translate/estimate/{job_id}`) calculates the required Gemini requests for the chosen configuration against available daily key limits. **🧪 Μετάφραση δείγματος** translates only a designated page range *a–b* (`page_from` / `page_to`) using identical settings, caching batches so the subsequent full-book translation seamlessly reuses completed pages. |
| **AI Neural Audiobooks, Multi-Voice Dramatization & Real M4B Export** | Generates high-fidelity MP3 and real M4B (MP4/AAC) audiobooks using Microsoft Edge neural voices with pacing presets (**Literature**, **Poetry & Recitation**, **Calm**, **Standard**, **Brisk**) and fine-tune sliders for Speed (-30% to +30%) and Pitch (-4Hz to +4Hz). Supports **🎭 Multi-Voice Dramatization** (distinct narrator and dialogue voices for English books with automatic quote and speaker tag routing), automatic chapter mark detection, and embedded cover art (`APIC`). Uses 64KB streamed concatenation to prevent memory spikes on 10+ hour recordings. |
| **Voice Preview Auditions with Instant Stop** | Instant 2–3 second voice audition playback button (`🔊 Preview`, `GET /api/tts/preview`) with strict voice-ID validation and atomic preview caching, accompanied by a dedicated **⏹️ Διακοπή** button to halt audition audio immediately without waiting for sample completion. |
| **Prior Choice Quota Routing & Automatic Background Resumption (`quota_behavior: 'wait'`)** | Prior to translation or audio generation, the system defaults strictly to `⏳ Wait for Reset` whenever a Gemini API key is configured. When quota is exhausted, processing pauses safely at disk checkpoint (`.direct_ai_checkpoint.json` / `.comic_vision_checkpoint.json`), displaying a live countdown timer. A background watchdog monitor continuously checks cooldowns and **automatically resumes paused jobs and queued batch items the moment quota resets or new keys are added** — never silently degrading to unpolished machine translation unless the user explicitly selected `🔄 Auto-Fallback`. |
| **Hybrid AI Architecture & Free Mode Fallback** | Modular three-tier architecture (Polishing, Translation, TTS) with independent provider routing between primary (Google Gemini) and secondary completely free self-hosted / local engines (Edge-TTS, Piper TTS `el_GR-joy-medium`, NLLB-200, and Google GTX / MyMemory). When no API keys exist in the pool, BookApp automatically activates **Free Mode** across all modules. |
| **Greek Editorial Typography & Scripted Sanitization Pass** | Built-in publishing typography & editorial sanitation engine (`backend/typography.py`, 1.25M words/sec): sanitizes cross-lingual subword token bleed, eliminates code leaks and foreign word contamination, corrects machine translation calques and false friends, normalizes OCR double accents while preserving enclitics (`το όνομά μου`), removes word stutters, shields URLs, and enforces standard Greek editorial quotes (`«...»`), dialogue em-dashes (`—`), and the Modern Greek Rule of Final 'ν' (`δε/δεν`, `μη/μην`). |
| **Style-Aware Categorized Glossary (3,366+ Terms)** | Categorized terminology engine (`technical`: 1,130 terms, `literary`: 1,032 terms, `general`: 1,204 terms — **3,366+ total terms**) with idempotent single-pass placeholder substitution, regex-backslash-safe replacements, symbol-safe word boundaries, automatic exclusion of IT terms in literary/comic/poetry modes, and protection of bibliographic citations. English terms within Greek sentences receive parenthetical Greek glosses once per document (`το kernel (πυρήνας)`), while standalone terms are cleanly substituted. |
| **Auto-Genre & Style Detection** | Real-time text analysis (`backend/genre_detector.py`, `POST /api/detect-genre`) analyzing uploads to identify Poetry, Literature, Technical, Formal, or Comic documents, filtering TOCs/lists from poetry false positives, and auto-suggesting matching AI polish styles and glossary categories. Leverages EPUB/PDF/DOCX metadata subjects/keywords when available. |
| **Automatic Final Output Refinement & Quality Control** | Independent local-only stage (`backend/output_refiner.py`) running automatically as the final verification step of every translation and audiobook. *Translations:* validates page-marker continuity, empty pages, untranslated paragraphs, bracket balance, stutters, accents, and final-ν; auto-corrects only unambiguous errors and rolls back changes exceeding safety thresholds. Format-preserved DOCX/EPUB and comics are inspected without destructive re-export. *Audiobooks:* validates headers, playable durations, and section continuity, automatically re-synthesizing failed sections (up to 25) before final assembly. Zero API quota consumption. |
| **Unified Upload & Smart Batch Queue (Up to 20 Files)** | Select or drop 1 file or up to 20 mixed files (novels, EPUBs, Graphic Novels, Manga — max 250 MB/file) into the upload card. Configures translation settings uniformly while auto-detecting and protecting comic vs book settings per file. Operates serially to prevent 429 rate collisions, with isolated per-item cancellation, **🔄 Retry**, **⏸️ Pause / ▶️ Resume**, **⚡ Auto-Start**, live progress bars, immediate per-item downloads, and **📦 Download All (ZIP)**. |
| **Advanced UI/UX Suite: Reader, Player, Smart Resume, Live ETA & Solar Themes** | **1.** 📖 **Distraction-Free "Read Now" Reader View**: Clean in-browser reading modal with serif typography, font zoom, 3 themes (Paper, Sepia, Dark), and instant Single-Column or Side-by-Side bilingual comparison. **2.** 🎧 **Pro Audiobook Player**: Built-in player with playback rate presets (`0.8x`, `1.0x`, `1.2x`, `1.5x`), quick skip buttons (`⏪ 15s`, `⏩ 15s`), track metadata, and Chapter/Part selector. **3.** 📌 **Smart Resume Banner**: Automatically detects interrupted or checkpointed jobs on startup and offers instant 1-click resumption. **4.** ⏱️ **Live ETA & Speed Indicator**: Time left calculated from recent pacing (`~1 hour 53 minutes`) and speed (`pages/min` or `parts/min`). **5.** 🏷️ **Hybrid Engine Badge**: Visual indicator showing whether Gemini Flash or the Free Neural Engine is actively translating. **6.** 🔔 **Completion Chime & Desktop Notifications**: Subtle 2-note synthesizer chime and notifications alerting when background tasks complete. **7.** 📋 **1-Click Copy**: Direct clipboard copy with confirmation. **8.** 🌓 **Solar Theme Engine**: Automatic theme adjustment based on sunrise and sunset calculations, with persistent manual toggle. **9.** ❓ **Interactive Help & FAQ Modal**: Bilingual guide and troubleshooting documentation accessible directly from the header. |
| **Mobile Web App & iOS Share Sheet Integration** | Fully responsive web app tailored for smartphones and tablets (320px+). On Apple iOS / iPadOS (Safari and Home Screen PWA), all downloads (translations, audiobooks, bilingual editions, insights exports) route directly through the native iOS **Share Sheet** ("Save to Files", "Books", "AirDrop"), preventing document views from hijacking or locking the web application. |
| **Optional User Accounts with Administrators & Password-Free Device Pairing** | Optional multi-user authentication (`BOOKAPP_AUTH=1`) supporting standard users (isolated personal jobs, reading sync, and glossary suggestions) and administrators (full user management, key configuration, server settings, and audit logs). Supports password-free local network pairing (`BOOKAPP_PAIRING=1`) for seamless phone/tablet connectivity without password entry. |
| **Persistent SQLite Database & Semantic Cache** | Full state persistence across server restarts (`data/bookapp.db` in WAL mode) with orphaned job auto-recovery, `file_path` auto-healing, and thread-safe SSE delivery. Jobs are retained until explicitly deleted. Features SHA-256 semantic caching (`gemini_polish_v4`, `gemini_comic_vision_v2`) delivering sub-3ms responses for previously translated or analyzed text with zero API consumption. |
| **Automated Test Suite (68 Suites in Sandbox)** | Comprehensive test suite (`run_all_tests.py`) executed within an isolated throw-away sandbox (separate port, clean database, no API keys) preventing any interference with live user data. Covers security (path traversal, Zip Slip, XSS), API contracts, mock Gemini/GTX resilience, comic/TTS edge cases, Book Insights, reading sync, library series, and data safety preservation. |

---

## 🚀 Quick Start

### Prerequisites
* **Python 3.11 or higher** — [Download Python](https://www.python.org/downloads/)
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

### 🖥️ Install on a Server (Ubuntu, Synology NAS)
Step-by-step guides with every command are in the **[Administrator Manual, section 3](docs/ADMIN_MANUAL.md#3-step-by-step-installation)**:

| Where | Guide |
|---|---|
| Ubuntu server with Docker (recommended) | [3.1](docs/ADMIN_MANUAL.md#31-ubuntu-server-with-docker): Docker install, `.env`, start, setup code, updates, backups, troubleshooting |
| Synology NAS | [3.2](docs/ADMIN_MANUAL.md#32-synology-nas-with-docker-container-manager): Container Manager only (no command line) or SSH |
| Ubuntu server without Docker | [3.3](docs/ADMIN_MANUAL.md#33-ubuntu-server-without-docker-python--systemd): Python environment and a systemd service |
| First administrator, API key, users | [3.4](docs/ADMIN_MANUAL.md#34-first-sign-in-every-server-installation) |

The short version with Docker (port 2000, sign-in on):
```bash
git clone https://github.com/kotsimp/BookApp.git && cd BookApp
printf 'BOOKAPP_PORT=2000\nBOOKAPP_AUTH=1\n' > .env
docker compose up -d --build
docker logs bookapp 2>&1 | grep -i "setup code"   # then open http://<server-ip>:2000/setup
```
Server settings live in `.env` next to `docker-compose.yml`. Git ignores that file, so `git pull && docker compose up -d --build` updates BookApp without touching them. The server's IP address is not set anywhere, because the app answers on every address of the machine. Jobs (`data/`), settings (`config/`) and books (`temp/`) stay outside the container.

Your settings and API keys (`config/settings.json`) are never copied into the image: they stay in `./config`, which the container mounts.

---

## 📁 Project Structure

```
BookApp/
├── backend/
│   ├── main.py              # FastAPI application (REST endpoints & SSE streaming)
│   ├── ai_polisher.py       # Gemini AI proofreading & style polishing engine
│   ├── ai_segment_translator.py # Format-preserving AI translation of DOCX/EPUB segments
│   ├── async_utils.py       # Async execution helpers and worker thread delegation
│   ├── auth.py              # Optional user accounts & administrators (BOOKAPP_AUTH=1)
│   ├── backup.py            # Comprehensive library backup and restore (.zip)
│   ├── bilingual.py         # Bilingual edition generator (paragraph alignment, PDF/DOCX/EPUB)
│   ├── book_insights.py     # Book Insights: AI summaries, synopses & neural audio versions
│   ├── book_names.py        # Character and domain term name extraction & validation
│   ├── comic_archive.py     # Reads CBR uploads (7-Zip / bsdtar) and writes CBR exports (RAR)
│   ├── comic_build.py       # Child-process comic packaging (keeps server event loop free)
│   ├── comic_translator.py  # Graphic Novel & Manga (RTL) balloon Vision AI translator
│   ├── connections.py       # Per-user e-reader link & OPDS token management
│   ├── database.py          # SQLite database layer & SHA-256 semantic cache (data/bookapp.db)
│   ├── device_pairing.py    # Optional password-free device pairing (BOOKAPP_PAIRING=1)
│   ├── document_blocks.py   # Multi-page text segmentation and block structure models
│   ├── epub_extras.py       # Dramatis Personae (Characters page) generator for EPUB
│   ├── exporter.py          # Multi-format document exporter (DOCX, PDF, EPUB, TXT, CBZ, CBR)
│   ├── format_preserver.py  # In-place DOCX/EPUB formatting & styling preservation
│   ├── format_sync.py       # Applies later edits inside format-preserved files safely
│   ├── gemini_key_pool.py   # Multi-Key Gemini API Pool & Failover Manager (up to 8 keys)
│   ├── genre_detector.py    # Document genre, tone & style auto-detection engine
│   ├── glossary.py          # Categorized custom terminology mapping & regex replacement
│   ├── glossary_learning.py # Self-learning glossary proposal engine from translations & edits
│   ├── insights_more.py     # More Book Insights: characters, chapters, recap, blurb, quotes, study guide, timeline, ask the book
│   ├── job_manager.py       # Persistent job state tracking, SQLite sync & file_path healing
│   ├── output_refiner.py    # Automatic final output refinement & quality-control stage
│   ├── parsers.py           # Multi-mode extractors & Graphic Novel auto-detector (PDF, DOCX, EPUB, CBZ)
│   ├── pdf_text_names.py    # Ensures text copied or searched from exported PDFs matches the book
│   ├── queue_manager.py     # Smart Batch Queue serial engine (max 20 files, isolated cancel/retry)
│   ├── reading_sync.py      # KOReader/Readest-compatible reading-position sync server (/kosync)
│   ├── request_context.py   # Signed-in user context (per-user job visibility & quota metrics)
│   ├── scan_reader.py       # Scanned books: page text read by Gemini Vision, kept next to upload
│   ├── series.py            # Book series continuity, ordering, and cross-book terminology inheritance
│   ├── settings_manager.py  # Thread-safe persistent application settings
│   ├── storage_cleaner.py   # Temporary scratch storage garbage collector
│   ├── translation_prompts.py # Versioned prompt library: translation, polish, audiobook script, dossier
│   ├── translator.py        # High-speed chunked Google GTX & MyMemory translation engine
│   ├── tts_engine.py        # Multi-voice Edge-TTS neural audio generator, M4B exporter & read-along sync
│   ├── typography.py        # Greek editorial typography & final "ν" engine
│   └── api/                 # Modular API routers:
│       ├── auth.py          # Authentication, session, and user administration routes
│       ├── common.py        # Shared dependency injections and route utilities
│       ├── connections.py   # OPDS e-reader feed endpoints
│       ├── insights.py      # Book Insights, specialized analysis, and Ask the Book endpoints
│       ├── library.py       # Series, self-learning glossary, characters page, and backup routes
│       ├── pairing.py       # Password-free device pairing endpoints
│       ├── refine.py        # Standalone and on-demand final refinement endpoints
│       └── sync.py          # KOReader / Readest reading synchronization routes
├── config/
│   ├── glossary.json        # Categorized custom glossary terms (Technical, Literature, General)
│   └── settings.json        # Local persistent settings (gitignored)
├── data/
│   ├── bookapp.db           # Persistent SQLite database (jobs, metadata & translation cache)
│   └── auth.db              # User accounts (password & session hashes, audit log; BOOKAPP_AUTH=1)
├── frontend/
│   ├── index.html           # Modern single-page interface with unified Upload & Batch Queue, ❓ Help
│   ├── style.css            # Responsive CSS theme with solar theme variables
│   ├── theme.js             # Solar theme scheduler (light by day, dark at night based on sunrise/sunset)
│   ├── app.js               # Frontend application state, batch queue, split-screen editor & audio player
│   ├── insights.js          # Book Insights UI controller and interactive Q&A manager
│   ├── library.js           # Series manager, glossary suggestions, and library backup panel
│   ├── pairing.js           # Device pairing panel controller
│   ├── auth.js              # User authentication bar and administrator management UI
│   ├── i18n.js              # Internationalization and localization strings (Greek / English)
│   ├── login.html           # Sign-in, initial setup, and temporary password update page
│   └── manifest.json        # Web Application Manifest for mobile and desktop PWA installation
├── docs/
│   ├── USER_MANUAL.md       # Complete user guide
│   └── ADMIN_MANUAL.md      # Administrator deployment & technical manual
├── tests/                   # 68 Automated Test Suites (sandboxed)
├── run_all_tests.py         # Master unified test runner
├── start_bookapp.bat        # Windows one-click desktop launcher
├── requirements.txt
├── requirements-lock.txt    # Exact versions of a verified environment (use with -c)
├── eval/passages.json       # Translation quality evaluation passages
├── scripts/eval_translation_quality.py # Quality evaluation runner (--live / --from-dir)
├── run.py                   # Automated Python launcher
└── README.md
```

---

## 🎙️ Available AI Voices

### Greek (🇬🇷)
| Voice | Code | Notes |
|---|---|---|
| **Nestoras (Male)** | `el-GR-NestorasNeural` | *Recommended* — Natural intonation, complete dictionary coverage for acronyms & technical terms. |

### English (🇬🇧 / 🇺🇸)
| Voice | Code |
|---|---|
| **Aria (Female, US)** | `en-US-AriaNeural` |
| **Guy (Male, US)** | `en-US-GuyNeural` |
| **Jenny (Female, US)** | `en-US-JennyNeural` |
| **Brian (Male, US)** | `en-US-BrianNeural` |
| **Emma (Female, UK)** | `en-GB-SoniaNeural` |
| **Ryan (Male, UK)** | `en-GB-RyanNeural` |

---

## 🧪 Running Tests

The master runner executes all suites inside an isolated throw-away sandbox (separate free port, empty temporary database, no API keys) so your active jobs, settings, and library remain completely untouched:

```bash
# Run all 68 automated test suites (Full Suite)
.\.venv\Scripts\python run_all_tests.py

# Run fast local suite (63 static/unit/security/contract/resilience/UI/queue/benchmark suites)
.\.venv\Scripts\python run_all_tests.py --fast

# Run individual suites
.\.venv\Scripts\python run_all_tests.py test_data_safety_and_preservation test_output_refinement
```

Test files refuse to execute standalone outside the sandbox (`python tests/test_x.py`, `unittest`, `pytest`) to protect production databases, keys, and network ports from accidental collision.

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
