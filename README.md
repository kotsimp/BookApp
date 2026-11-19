# 📚 DocTranslate & AudioBook Generator

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: Passing](https://img.shields.io/badge/Tests-40%2F40%20Suites%20Passed-brightgreen.svg)](tests/)

A modern, high-performance local web application to **translate documents** between English and Greek with **Single-Pass Direct AI Translation & Polish**, **in-place format preservation** (fonts, sizes, headings, tables, styles), **automatic Graphic Novel / Scanned Comic & Manga translation** with 100% artwork preservation, and **professional AI audiobooks** (including multi-voice dramatization and M4B export) using Microsoft Edge neural voices. Supports a **Hybrid AI Architecture** allowing seamless operation with Google Gemini or completely free, local/web alternatives.

---

## 📑 Documentation & Manuals (Εγχειρίδια)

* 📖 **[Εγχειρίδιο Χρήστη / User Manual (docs/USER_MANUAL.md)](docs/USER_MANUAL.md)**  
  *Αναλυτικός οδηγός βήμα-βήμα για τον χρήστη: Ενιαίο Upload & Smart Batch Queue (1–20 αρχεία), Προηγούμενη Επιλογή Συμπεριφοράς σε Εξάντληση Ορίου Gemini (Αναμονή με ζωντανό χρονοδιακόπτη vs Αυτόματη Μετάβαση σε Δωρεάν Μοντέλο), Αυτόματη Προεπιλογή Δωρεάν Μοντέλων (Free Mode) όταν δεν υπάρχει API Key, Single-Pass AI Translation & Polish (με live πρόοδο batches + σελίδων & αυτόματη επαναφορά ρυθμίσεων στο Resume), αυτόματη ανίχνευση Graphic Novels & Scanned PDFs (με κλείδωμα συμβατών επιλογών), Manga (RTL), επιλογή φορμάτ (PDF, CBZ, CBR, EPUB), ελληνική τυπογραφική επιμέλεια, αυτόματη ανίχνευση είδους, πολυφωνικά audiobooks, ακρόαση δειγμάτων φωνής, κουμπί Refresh και Dark/Light Mode.*
* 🛠️ **[Εγχειρίδιο Διαχειριστή / Admin Manual (docs/ADMIN_MANUAL.md)](docs/ADMIN_MANUAL.md)**  
  *Τεχνικός οδηγός για διαχειριστές: Υβριδική αρχιτεκτονική AI (Google Gemini + Free local/cloud models), διαχείριση ορίων Quota (circuit breaker, countdown, per-task routing, quota_behavior: 'wait' | 'fallback'), αυτόματη ενεργοποίηση Free Mode, SQLite database persistence (`data/bookapp.db`) με metadata settings & `file_path` auto-healing, Smart Batch Queue engine (`backend/queue_manager.py`) με ZIP completion gating (409 όσο υπάρχουν ενεργές εργασίες, άμεση μεμονωμένη λήψη ολοκληρωμένων αρχείων), σημασιολογική προσωρινή μνήμη μεταφράσεων & Vision AI (`gemini_polish_v4` full-prompt SHA-256 hash & `gemini_comic_vision_v2`), Single-Pass Full Gemini Flash με `thinkingBudget: 0`, `maxOutputTokens: 16384`, `BLOCK_NONE` safety settings, `thought` filtering, recursive page/paragraph bisection, `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` boundary deduplication, whole-book stratified Entity Dossier & Greek mixed-script quality gate, zero-tofu PDF glyph guard & URL wrapping, two-pass non-blank comic balloon renderer με natural CBZ page sorting & Zip Slip protection, 429 Circuit Breaker με αυτόματο Gemini failover, universal `job_id` path-traversal validation, Storage Auto-Cleanup Garbage Collector, FastAPI lifespan, Nginx reverse proxy με SSE, 45 REST API endpoints και 40 αυτοματοποιημένα test suites.*

---

## ✨ Features (Χαρακτηριστικά)

| Feature | Details |
|---|---|
| **Dual-Mode User Interface: Basic vs Advanced Mode (1-Click AI Magic)** | Seamless global mode toggle persisted in `localStorage`: **1. ⚡ Basic Mode (Απλή Λειτουργία)**: Designed for maximum simplicity and zero cognitive load. AI is **enabled by default** for both Translation (`tr-ai-polish` checked) and Audiobook (`ab-ai-polish` checked). Granular options (format pickers, layout selectors, pitch/speed sliders, multi-voice grids) are neatly tucked away. Just drop your file and click `✨ Μετάφραση Βιβλίου με AI (1-Click)` or `🎧 Δημιουργία Audiobook με AI (1-Click)` — input format is automatically matched and audiobook defaults to Greek Nestoras neural voice with Literature pacing (-12% speed). **2. ⚙️ Advanced Mode (Προχωρημένη Λειτουργία)**: Full granular control over all settings: source/target language direction, format selection (PDF, DOCX, EPUB, CBZ, CBR, TXT), layout styles (Standard, Literature, Comic), RTL manga direction, custom book cover upload, pitch & speed fine-tune sliders, multi-voice character dramatization, and quota behavior choice (`wait` vs `fallback`). |
| **Gemini Multi-Key API Pool & Auto-Failover (Up to 4 Keys)** | Configure **up to 4 free Google Gemini API keys** simultaneously in the Settings modal (Slot 1 Primary + Slots 2–4 Backups). When Slot 1 encounters HTTP 429 / daily quota exhaustion (1,500 requests/day per key), the engine **seamlessly and instantaneously rotates to Slot 2, then Slot 3, then Slot 4** without pausing or losing progress. Provides **up to 6,000 free AI requests/day ($0 cost)** using standard free Google accounts. Features thread-safe per-key cooldown management (`GeminiKeyPool`), individual slot status badges (`🟢 Active`, `🟡 Standby`, `⏳ Exhausted with Reset Countdown`, `⚪ Empty`), and UI pool health diagnostics. The global quota timer triggers only if all configured keys are exhausted. |
| **Advanced UI/UX Suite: Reader, Player, Smart Resume, Live ETA & Notifications** | **1.** 📖 **Distraction-Free "Read Now" Reader View**: Clean in-browser reading modal with serif typography, font-size zoom, 3 themes (Paper, Sepia, Dark), and instant Single-Column or Side-by-Side (English ↔ Greek) bilingual comparison. **2.** 🎧 **Pro Audiobook Player**: Built-in player with playback rate presets (`0.8x`, `1.0x`, `1.2x`, `1.5x`), quick skip buttons (`⏪ 15s`, `⏩ 15s`), track metadata, and Chapter/Part selector. **3.** 📌 **Smart Resume Banner**: Automatically detects interrupted or checkpointed jobs on startup and offers instant 1-click resumption. **4.** ⏱️ **Live ETA & Speed Indicator**: Real-time remaining time calculation (`~7λ 30δ`) and throughput tracking (`22 σελ/λ` or `1.5 batches/δ`). **5.** 🏷️ **Hybrid Engine Badge**: Live visual indicator in progress card showing whether Gemini Flash or the Free Neural Engine is actively translating. **6.** 🗣️ **Contextual Voice Sample**: Voice audition box supporting custom user phrases or excerpts from the uploaded book. **7.** 🔔 **Completion Chime & Desktop Notifications**: Subtle 2-note Web Audio synthesizer chime + HTML5 Desktop Notifications alerting you when long translations or audiobooks finish in the background. **8.** 📋 **1-Click Copy Translated Text**: Quick clipboard copy button on the result card with visual confirmation (`✅ Αντιγράφηκε!`). **9.** 🟢 **Live Multi-Key Pool Health Badge**: Visual status pill on navbar indicating active/standby keys (`🟢 4/4 Keys`, `🟡 2/4 Keys`, `⏳ Cooldown`, `✓ Active`, or `🆓 Free Mode`). **10.** ⏱️ **Audiobook Duration Estimation**: Real-time listening time estimate (`⏱️ ~X ώρες Y λεπτά ακρόαση`) computed upon document upload. **11.** 📦 **On-Demand M4B Download**: Direct 1-click download of M4B audiobooks (`#ab-download-m4b-btn`) with chapters and embedded cover art. |
| **Prior Choice Quota Routing & Free Models Default (`Free Mode`)** | Prior to translating or generating an audiobook, users can choose their preferred behavior when Gemini API quota is exhausted: `⏳ Αναμονή για επαναφορά (Wait for Reset)` (pausing safely at disk checkpoint with live countdown timer and resume button, preserving 100% Gemini quality) or `🔄 Αυτόματη μετάβαση σε Δωρεάν Μοντέλο (Auto-Fallback)` (seamlessly falling back to free Google Translate & Edge-TTS without stopping). **When no Gemini API key is configured, BookApp automatically activates Free Mode as the default** across all modules: translation, editorial typography, and neural audiobooks run 100% free with zero keys, subscriptions, or credit card requirements. |
| **Hybrid AI Architecture** | Modular three-tier architecture (Polishing, Translation, TTS) with independent provider routing between primary (Google Gemini) and secondary completely free self-hosted / local engines (Edge-TTS, Piper TTS `el_GR-joy-medium`, NLLB-200, and OpenAI-compatible endpoints like VoiceStudio). |
| **Single-Pass Direct AI Translation & Polish** | When **AI Polish** is enabled with a Gemini API key, books and documents (PDF, EPUB, DOCX, TXT) translate & polish in **one single parallel pass** (5 concurrent workers, prioritizing full Gemini Flash models over Flash-Lite, `maxOutputTokens: 16384`, `thinkingBudget: 0`, `safetySettings: BLOCK_NONE`, `thought: true` part filtering, and `5500 chars / max 3 pages` safe batching) — with **recursive multi-page & paragraph-level bisection** on `MAX_TOKENS`, `SAFETY`/`PROHIBITED_CONTENT`, or timeouts (eliminating silent multi-page raw-MT fallbacks), **XML-delimited `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` + deterministic boundary deduplication** (zero repeated overlap paragraphs or leaked `[...]` context), **whole-book stratified Entity Consistency Dossier** (full-book frequency scan + 9 evenly spaced excerpts for 35–60 terms with explicit grammatical gender & anti-conflation), uniform Greek dialogue guillemets (`«...»`), **targeted mixed-script retry** (without Flash-Lite downgrade), style-aware Glossary isolation, Disk Checkpointing, exact `batches + pages` live progress, and full settings restore on Session History resume. |
| **Parallel English ⇄ Greek Translation + 429 Failover** | High-speed parallel translation (`Semaphore(4)`, `CHUNK_SIZE=4000`, HTTP keep-alive) via Google's GTX POST API with a 20s `429` circuit breaker, fast MyMemory fallback, and **automatic Gemini Flash failover**. Includes a **Gemini Daily Quota Circuit Breaker & Warning System** (`DailyQuotaExhaustedError`, `get_gemini_quota_info`): when Google's Free Tier daily request limit is exceeded, it fails fast in <1ms without looping over 35 candidate models, surfaces instant UI warning toasts, prominent Quota Banners with exact remaining cooldown and a one-click `🔑 Αλλαγή API Key` button (across the Batch Queue, Single Progress Card, Result Card, and AI Polish Modal), and gracefully falls back to standard translation with checkpoint preservation so queues and single translations never hang or produce silent unnotified degradation. |
| **Automatic Graphic Novel & Scanned PDF Detection** | On upload (`POST /api/upload`), `detect_is_graphic_novel()` inspects CBZ/CBR archives and PDF pages (image coverage, vector text density, artwork cues) to automatically detect digital & scanned Graphic Novels and **lock the UI strictly to Graphic Novel options** (`PDF/CBZ/CBR/EPUB`, `Graphic Novel` layout, `LTR/RTL` reading direction) while disabling incompatible text options. Streaming upload validation enforces the 250 MB cap without OOM, sanitizes Windows-illegal/reserved filenames, enforces universal `job_id` path-traversal protection across all endpoints, and rejects empty (0-byte), >250 MB, or corrupted DOCX/EPUB/CBZ/PDF files immediately with clear messages. |
| **Parallel Scanned Comic Vision AI & Manga (RTL)** | Translates both digital and **scanned/image-only** comics & Manga preserving 100% of surrounding artwork. Features **CBZ Zip Slip protection**, **natural numeric page sorting** (`page_1`, `page_2`, ..., `page_10`), target-language-aware vector AI polish, fail-loud validation if a scanned comic lacks a Gemini API key, **3 parallel Full-Flash Gemini Vision workers** (`gemini_comic_vision_v2` SHA-256 cache, `maxOutputTokens: 8192`, `thought` filtering, mixed-script corruption failover, clamped `[0..1000]` boxes, resilient malformed-JSON recovery, dialytika+tonos `ΐ`/`ΰ` ALL-CAPS sanitization), a **two-pass non-blank balloon renderer** (down to `3.0pt` with condensed font fallback), and exports to **PDF, CBZ, CBR, and Fixed-Layout EPUB** (including `page-progression-direction="rtl"`). |
| **Persistent SQLite Database & Full Resume Restore** | Full job state & translation settings persistence across server restarts (`data/bookapp.db`) in WAL mode with connection locking, automatic orphaned `running`/`queued` job recovery on startup, `file_path` auto-healing, persisted cancellations & standalone AI polish states, thread-safe SSE subscriber delivery with full-queue resilience & automatic terminal close, `.cbz`/`.cbr`/`.m4b` disk recovery, and full UI settings restoration when resuming from Session History. Includes **Automatic Test Job Isolation & Purge** (`cleanup_test_jobs`, `DELETE /api/jobs/tests/cleanup`), ensuring test-generated artifacts never pollute user Session History or disk storage. |
| **Semantic Translation, Polish & Vision Cache** | SHA-256 content-hash caching (`gemini_polish_v4` hashing the full system prompt so styles, languages, glossaries & dossiers never collide; `gemini_comic_vision_v2`; `google`) for translated chunks, AI-polished batches, and scanned comic Vision detections (corrupted/truncated outputs and MyMemory error strings are never cached). Cached items return in ~3ms with zero API/quota consumption and live statistics (`GET /api/cache/stats`). |
| **Storage Auto-Cleanup Garbage Collector** | Automated disk management (`backend/storage_cleaner.py`) that safely purges orphaned temporary audio chunks, voice previews (`temp/previews/`), M4B/CBZ work folders, and extractions older than 48 hours while actively protecting running/queued jobs and user exports (`POST /api/admin/cleanup`, enforcing `max_age_hours >= 1`). |
| **Greek Editorial Typography Engine** | Built-in publishing typography (`backend/typography.py`, 1.25M words/sec): converts straight quotes `"..."` to Greek guillemets `«...»` (preserving fenced code blocks), standardizes dialogue dashes (`—`) while keeping indented/numeric bullets intact, enforces modern Greek final "ν" rules (`δε/δεν`, `μη/μην` while preserving conjunctive `δε` = "however" in legal/literary Greek and privative `μη` before adjectives/participles/nouns/adverbs), rejoins broken hyphenated words without gluing interrupted dialogue (`Περίμενε- μην`), restores elision apostrophes (`Σ'`, `ΓΙ'`, `ΑΠ'`), and normalizes punctuation spacing & Greek question marks (`;`, `;!`, `;;!!`) while protecting URLs and relative paths (`../`). |
| **Style-Aware Categorized Glossary** | Categorized terminology engine (`technical`, `literary`, `general`) with **idempotent single-pass placeholder substitution** (never recursively double-substituting parenthetical terms across passes), regex-backslash-safe replacements (`C:\temp`, `\1`), hyphen-safe & symbol-safe word boundaries (`pod-man`, `royalty-free`, `(.NET)`), automatic exclusion of IT/DevOps/Kubernetes terms in literary/comic/audiobook/poetry modes, and protection of English bibliographic citations. |
| **Auto-Genre & Style Detection** | Real-time text analysis (`backend/genre_detector.py`, `POST /api/detect-genre`) with single-word & multi-word phrase matching (including 2-letter acronyms like `IP`) detecting Poetry, Literature, Technical, Formal, or Comic documents upon upload while filtering TOC/bullet lists from poetry false positives, auto-suggesting matching AI polish style and glossary category (`technical`, `literary`, `general`). |
| **Multi-Voice Audiobook Dramatization** | Distinct narrator and dialogue voices (e.g. Nestoras for narration + Athina for character speech), explicit speaker tags (`[Nestoras]: ...`, `[Athina]: ...`), case-insensitive & raw Edge-TTS voice code lookup, and automatic quote dialogue routing. |
| **M4B & Tagged Audiobooks** | Exports audiobooks in both `.mp3` and `.m4b` formats with full ID3v2/MP4 metadata tagging (Title, Artist, Album, Genre="Audiobook"), embedded cover art via `ffmpeg` (`attached_pic`) and `mutagen`, synthesis/subprocess timeouts, and guaranteed temp-folder cleanup on errors. |
| **Voice Preview Auditions** | Instant 2–3 second voice audition playback button (`🔊 Ακρόαση`, `GET /api/tts/preview`) next to each voice in the UI with strict voice-ID validation and atomic preview caching. |
| **Modern UI Controls & One-Click Launcher** | Dynamic origin API detection (`localhost`, `127.0.0.1`, or LAN hosts), resilient error formatting (`parseApiError` for HTTP 422/500/non-JSON responses), Dark/Light theme toggle, dedicated **🔄 Refresh** button in header & navbar, dedicated **🔑 Gemini API Key** button with **💾 Save Key** and auto-sync to server (resetting both text and comic vision model caches), Direct Editor AI Polish without requiring a file upload first, Split-Screen Editor with Sync Scroll, and Windows desktop launcher (`start_bookapp.bat`). |
| **Unified Upload & Smart Batch Queue (Up to 20 Files)** | Select or drop **1 file or up to 20 mixed files** (novels, EPUBs, Graphic Novels, Manga — max 250 MB/file) directly inside the top **Upload Document(s)** card, or click **➕ Add More** on a single file to seamlessly promote it into a batch. Configure Translation Settings below once — `POST /api/queue/start` syncs your latest settings onto all queued items while auto-protecting Comics vs Books per file (and auto-disabling Auto-Start on mixed queues). Runs serially (1 doc at a time at full 4–5x internal parallelism to avoid `429` collisions) with isolated per-item cancel, **🔄 Retry** (`POST /api/queue/{job_id}/retry`), **⏸️ Pause / ▶️ Resume**, **⚡ Auto-Start**, live progress bars, immediate per-item download as soon as each file finishes, and **📦 Download All (ZIP)** (`/api/queue/download-all`, unlocked once all queued translations complete). |
| **Automated Test Suite (40 Suites)** | Bulletproof master runner `run_all_tests.py` (with `--fast` mode running 35 local suites in ~45s, auto-server launch, automatic `config/settings.json` snapshot/restore so user API keys are never overwritten, and automatic test session cleanup after runs). Executes **40 suites (100% pass rate)** covering security/path-traversal/Zip Slip (`test_security_and_input_validation.py`), API contracts & state machine (`test_api_contracts_and_state_machine.py`), mocked Gemini/GTX HTTP resilience (`test_ai_polisher_and_translator_resilience.py`), end-to-end pipeline data integrity (`test_pipeline_data_integrity.py`), comic/TTS edge cases (`test_comic_and_tts_edge_cases.py`), concurrency/lifecycle (`test_concurrency_persistence_and_lifecycle.py`), frontend FastAPI schema + Node.js VM runtime UI tests (`test_frontend_contracts_and_ui.py`), a 10-point static guard (`test_code_health.py`), `test_ai_polisher_deep.py` (recursive bisection, boundary dedup, stratified dossier), `test_translation_quality_fixes.py` (zero-tofu PDF & URL wrapping), `test_e2e_regression_guard.py`, `test_gemini_key_pool.py`, `test_multivoice_and_m4b.py`, and `test_smart_batch_queue.py`. |
| **In-Place Format Preservation** | Translates `.docx` (preserving fonts, headings, bold/italic, tables, merged cells & embedded inline images `<w:drawing>`) and `.epub` (preserving spine order, nested HTML tags `<em>`/`<strong>`/`<blockquote>`, inline whitespace & HTML comments without double-translating) in-place with style-aware glossary & Greek typography cleanup. |
| **Cover Image Management** | Auto-extraction of original artwork from PDF/EPUB/DOCX (with proper handle cleanup), live preview thumbnail with status `✔ Εξώφυλλο ενεργό`, manual upload for custom artwork (`.jpg`, `.png`, `.webp`), removal button (`DELETE /api/cover/{job_id}`), and strict download isolation ensuring only book documents are served. |
| **Literature / E-Reader Layout** | Dedicated `layout=literature` mode for novels and books: strips running headers/footers and page numbers, renders `*italic*` and `**bold**` emphasis natively (Georgia Italic in PDF, italic runs in DOCX, `<em>` in EPUB), isolates chapter headings and epigraphs, merges cross-page sentences, formats scene breaks (`* * *`), wraps long unbroken URLs cleanly within page margins, guarantees zero missing-glyph tofu boxes (`□`), and embeds full-bleed covers on page 1 of PDF/EPUB/DOCX. |
| **Multi-Page Front Matter Preservation** | Line-level header/footer cleaning (`_clean_page_blocks`) ensures the initial pages of books (tables of contents, epigraphs, author dedications, and prologues) are 100% preserved without dropping text blocks. |
| **Optimized AI Polish & Proofreading** | Google Gemini AI integration with 5 tailored styles (including dedicated `literature` for fiction & sci-fi with uniform `«...»` dialogue punctuation and `audiobook` spoken narration script editor). Features **Bilingual Source-Anchoring** (page-level comparison between Greek draft and original English to fix mistranslations and false friends), **Whole-Book Stratified Entity Consistency Dossier** (frequency scan + 9 evenly spaced excerpts for uniform character/term names & grammatical gender from chapter 1 to the end), **Clean Boundary-Deduplicated Rolling Context**, **Recursive Multi-Page & Paragraph Bisection** with `BLOCK_NONE` safety settings, **Smart Real-Time Disk Checkpoints** (`.polish_checkpoint.json`), smart multi-page batching cutting API calls by 80%, dynamic backoff, and persistent settings (`config/settings.json`). |
| **Audiobook Script Polish & Spoken Phonetics** | Dedicated spoken script refinement for Edge-TTS neural voices: phonetically transliterates foreign names/acronyms into Greek script (`Keeton` -> `Κίτον`, `Rorschach` -> `Ρόρσαχ`, `DNA` -> `Ντι-Εν-Έι`), fully expands numbers, years, percentages, and abbreviations into spoken words (`2006` -> `δύο χιλιάδες έξι`, `50%` -> `πενήντα τοις εκατό`), completely strips non-spoken artifacts (page markers, footnotes, URLs), and optimizes sentence breathing and pauses. |
| **Translation Editor & Review** | Built-in in-browser Split-View / Full editor to review, edit, and search/replace translated text with live re-export. |
| **Custom Glossary & Terminology** | Custom terminology mapping engine with regex word boundaries to enforce exact translations for domain terms. |
| **Instant On-Demand Export** | Switch output format (**PDF**, **DOCX**, **EPUB**, **TXT**) post-translation with immediate download (< 1s) without re-translating. |
| **Bullet, Glyph & URL Normalization** | Replaces proprietary Wingdings/PUA symbols with standard Unicode bullets (`•`) and native Word `List Bullet` paragraphs, strips invisible/replacement control chars (`\ufffd`, `\u200b`), guards PDF rendering per font glyph (`has_glyph` — zero `□` tofu boxes), and wraps long unbroken URLs cleanly within page margins. |
| **Multi-Format Export** | Export translated output to **DOCX**, **PDF** (Unicode Greek with TrueType fonts), **EPUB**, or **TXT**. |
| **AI Neural Audiobooks** | Generates high-fidelity MP3 audiobooks using Microsoft Edge neural voices with balanced pacing presets (**Literature**, **Poetry & Recitation**, **Calm**, **Standard**, **Brisk**) along with interactive fine-tune sliders for **Speed** (-30% to +30%) and **Voice Pitch & Prosody** (-4Hz to +4Hz). Features theatrical prosody modulation, elision normalization, and refined verse pause handling that preserves poetic enjambment and strophic cadence. |
| **Greek Audio Support** | Native Greek neural voices: **Nestoras (Male)** with 100% dictionary coverage & **Athina (Female)** with automatic fallback. |
| **One-Click Direct Audio** | Convert any completed translation directly into a Greek Audiobook with a single click. |
| **Live Progress Streaming** | Real-time progress updates via Server-Sent Events (SSE) distinguishing between document pages and audio parts. |
| **Disk Recovery & Auto-Cleanup** | Completed jobs survive server restarts via SQLite & disk recovery, while startup housekeeping (`cleanup_old_jobs` & `clean_temp_storage`) prunes stale temp directories. |

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

### 🐳 Run with Docker & Docker Compose (Ubuntu, Synology NAS, MacBook)
```bash
# Clone and run with one command
git clone https://github.com/kotsimp/BookApp.git
cd BookApp
docker compose up -d --build
```
Access the application at **`http://localhost:8000`** (or your server's IP). All database files (`data/`), settings (`config/`), and outputs are automatically persisted outside the container.

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
│   ├── gemini_key_pool.py   # Multi-Key Gemini API Pool & Failover Manager (up to 4 keys)
│   ├── translator.py        # High-speed chunked Google GTX translation engine
│   ├── tts_engine.py        # Multi-voice Edge-TTS neural audio generator & M4B exporter
│   ├── job_manager.py       # Persistent job state tracking, SQLite sync, file_path healing & cleanup
│   ├── queue_manager.py     # Smart Batch Queue serial engine (max 20 files, isolated cancel, retry)
│   └── parsers.py           # Multi-mode extractors & Graphic Novel auto-detector (PDF, DOCX, EPUB, CBZ)
├── config/
│   ├── glossary.json        # Categorized custom glossary terms (Technical, Literature, General)
│   └── settings.json        # Local persistent settings (gitignored)
├── data/
│   └── bookapp.db           # Persistent SQLite database (jobs, metadata & translation cache)
├── frontend/
│   ├── index.html           # Modern single-page interface with unified Upload & Batch Queue + Dark/Light theme
│   ├── style.css            # Responsive CSS theme with theme variables
│   └── app.js               # Frontend state, batch queue, split-screen editor & voice preview
├── docs/
│   ├── USER_MANUAL.md       # Complete user guide in Greek
│   └── ADMIN_MANUAL.md      # Administrator deployment & technical manual
├── tests/                   # 38 Automated Test Suites (100% PASS · 45/45 Endpoints)
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

The master runner automatically protects & restores your `config/settings.json` (never touching your saved API keys), clears all temporary test sessions cleanly upon completion, and starts a temporary test server if none is running:

```bash
# Run all 37 automated test suites (Full Suite)
.\.venv\Scripts\python run_all_tests.py

# Run fast local suite (32 static/unit/security/contract/resilience/UI/queue/benchmark suites in ~50s)
.\.venv\Scripts\python run_all_tests.py --fast
```

Or run individual focused guard suites directly:
```bash
.\.venv\Scripts\python tests/test_security_and_input_validation.py
.\.venv\Scripts\python tests/test_api_contracts_and_state_machine.py
.\.venv\Scripts\python tests/test_ai_polisher_and_translator_resilience.py
.\.venv\Scripts\python tests/test_pipeline_data_integrity.py
.\.venv\Scripts\python tests/test_comic_and_tts_edge_cases.py
.\.venv\Scripts\python tests/test_concurrency_persistence_and_lifecycle.py
.\.venv\Scripts\python tests/test_frontend_contracts_and_ui.py
.\.venv\Scripts\python tests/test_translation_quality_fixes.py
.\.venv\Scripts\python tests/test_code_health.py
.\.venv\Scripts\python tests/test_smart_batch_queue.py
.\.venv\Scripts\python tests/test_e2e_regression_guard.py
```

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
