# 📚 DocTranslate & AudioBook Generator

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: Passing](https://img.shields.io/badge/Tests-62%2F62%20Suites%20Passed-brightgreen.svg)](tests/)

A modern, high-performance local web application to **translate documents** between English and Greek with **Single-Pass Direct AI Translation & Polish**, **in-place format preservation** (fonts, sizes, headings, tables, styles), **automatic Graphic Novel / Scanned Comic & Manga translation** with 100% artwork preservation, and **professional AI audiobooks** (including multi-voice dramatization and M4B export) using Microsoft Edge neural voices. Supports a **Hybrid AI Architecture** allowing seamless operation with Google Gemini or completely free, local/web alternatives.

---

## 📑 Documentation & Manuals

* 📖 **[User Manual (docs/USER_MANUAL.md)](docs/USER_MANUAL.md)**  
  *Comprehensive step-by-step user guide covering: Unified Upload & Smart Batch Queue (1–20 files), Prior Quota Routing Choice (Wait for Reset with live countdown timer vs Auto-Fallback to Free model), Automatic Free Mode default when no API key is provided, Single-Pass AI Translation & Polish (with live batch + page progress & full settings restore on Resume), automatic detection of Graphic Novels & Scanned PDFs (a scanned book read by Gemini Vision, or a comic with compatible options lock), a sample of a few pages first, the Gemini request estimate before starting, the bilingual edition, an e-reader catalogue (OPDS), reading along with audiobooks, more Book Insights (characters & terms, chapter by chapter, the story so far, a spoiler-free blurb, verified quotes, a study guide, a timeline and questions to the book), Manga (RTL), format pickers (PDF, CBZ, CBR, EPUB), Greek editorial typography rules, auto-genre detection, multi-voice audiobooks, live voice auditions, Refresh button, and Dark/Light Mode.*
* 🛠️ **[Administrator & Deployment Manual (docs/ADMIN_MANUAL.md)](docs/ADMIN_MANUAL.md)**  
  *In-depth technical guide for system administrators: Hybrid AI architecture (Google Gemini + Free local/cloud models), quota management (circuit breaker, countdown, per-task routing, quota_behavior: 'wait' | 'fallback'), Free Mode automation, SQLite database persistence (`data/bookapp.db`) with metadata settings & `file_path` auto-healing, Smart Batch Queue engine (`backend/queue_manager.py`) with ZIP completion gating (HTTP 409 while items are running, immediate individual download for completed items), semantic translation & Vision AI caches (`gemini_polish_v4` full-prompt SHA-256 hash & `gemini_comic_vision_v2`), Single-Pass Full Gemini Flash with `thinkingBudget: 0`, `maxOutputTokens: 16384`, `BLOCK_NONE` safety settings, `thought` filtering, recursive page/paragraph bisection, `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` boundary deduplication, whole-book stratified Entity Consistency Dossier & Greek mixed-script quality gate, zero-tofu PDF glyph guard & URL wrapping, two-pass non-blank comic balloon renderer with natural CBZ page sorting & Zip Slip protection, 429 Circuit Breaker with automatic Gemini failover, universal `job_id` path-traversal validation, Storage Auto-Cleanup Garbage Collector, FastAPI lifespan, Nginx reverse proxy with SSE, Final Output Refinement stage, publication-grade AI translation prompts, Book Insights, optional user accounts with administrators (setup code, account tool, HTTPS proxies), 90 routes, and 66 automated test suites.*

---

## ✨ Features

| Feature | Details |
|---|---|
| **Dual-Mode User Interface: Basic vs Advanced Mode (1-Click AI Magic)** | Seamless global mode toggle persisted in `localStorage`: **1. ⚡ Basic Mode**: Designed for maximum simplicity and zero cognitive load. AI is **enabled by default** for both Translation (`tr-ai-polish` checked) and Audiobook (`ab-ai-polish` checked). Granular options (format pickers, layout selectors, pitch/speed sliders, multi-voice grids) are neatly tucked away. Just drop your file and click `✨ Translate Book with AI (1-Click)` or `🎧 Generate Audiobook with AI (1-Click)` — input format is automatically matched, document genre is auto-detected and auto-applied with visual confirmation (`✓ Auto-applied`), and audiobook defaults to Greek Nestoras neural voice with Literature pacing (-12% speed). **2. ⚙️ Advanced Mode**: Full granular control over all settings: source/target language direction, format selection (PDF, DOCX, EPUB, CBZ, CBR, TXT), layout styles (Standard, Literature, Comic), RTL manga direction, custom book cover upload, pitch & speed fine-tune sliders, multi-voice character dramatization, and quota behavior choice (`wait` vs `fallback`). |
| **Gemini Multi-Key API Pool & Auto-Failover (Up to 4 Keys)** | Configure **up to 4 free Google Gemini API keys** simultaneously in the Settings modal (Slot 1 Primary + Slots 2–4 Backups) from different Google accounts. When Slot 1 runs out of its daily allowance, the engine **seamlessly and instantaneously rotates to Slot 2, then Slot 3, then Slot 4** without pausing or losing progress. Features **sliding-window rate limiting** (`GeminiRateLimiter` tracking RPM/TPM and smoothing request pacing), explicit `Retry-After` header handling, **per-model cooldown isolation** (a model whose daily allowance is used up does not block the other models on the same key), transient burst retry handling (`retryDelay <= 60s`), and dedicated diagnostics (`tests/test_gemini_diagnostics.py`). Google's free allowance is set **per model and per day, and it can be small** (for example 20 requests a day for `gemini-3.5-flash`); every key from another Google account adds its own allowance. Google AI Studio shows your current limits. Features thread-safe per-key cooldown management (`GeminiKeyPool`), individual slot status badges (`🟢 Active`, `🟡 Standby`, `⏳ Exhausted with Reset Countdown`, `⚪ Empty`), **instant Auto-Resume on Save** (automatically resuming paused translations or queues without requiring a manual resume click), and UI pool health diagnostics. The global quota timer triggers only if all configured keys are exhausted. |
| **Advanced UI/UX Suite: Reader, Player, Smart Resume, Live ETA & Notifications** | **1.** 📖 **Distraction-Free "Read Now" Reader View**: Clean in-browser reading modal with serif typography, font-size zoom, 3 themes (Paper, Sepia, Dark), and instant Single-Column or Side-by-Side (English ↔ Greek) bilingual comparison. **2.** 🎧 **Pro Audiobook Player**: Built-in player with playback rate presets (`0.8x`, `1.0x`, `1.2x`, `1.5x`), quick skip buttons (`⏪ 15s`, `⏩ 15s`), track metadata, and Chapter/Part selector. **3.** 📌 **Smart Resume Banner**: Automatically detects interrupted or checkpointed jobs on startup and offers instant 1-click resumption. **4.** ⏱️ **Live ETA & Speed Indicator**: Time left from the pace over the last few minutes (`~1 hour 53 minutes`, right after a reload or resume too) and the speed (`2.0 pages/min` or `parts/min`). **5.** 🏷️ **Hybrid Engine Badge**: Live visual indicator in progress card showing whether Gemini Flash or the Free Neural Engine is actively translating. **6.** 🗣️ **Contextual Voice Sample**: Voice audition box supporting custom user phrases or excerpts from the uploaded book. **7.** 🔔 **Completion Chime & Desktop Notifications**: Subtle 2-note Web Audio synthesizer chime + HTML5 Desktop Notifications alerting you when long translations or audiobooks finish in the background. **8.** 📋 **1-Click Copy Translated Text**: Quick clipboard copy button on the result card with visual confirmation (`✅ Copied!`). **9.** 🟢 **Live Multi-Key Pool Health Badge**: Visual status pill on navbar indicating active/standby keys (`🟢 4/4 Keys`, `🟡 2/4 Keys`, `⏳ Cooldown`, `✓ Active`, or `🆓 Free Mode`). **10.** ⏱️ **Audiobook Duration Estimation**: Real-time listening time estimate (`⏱️ ~X hours Y minutes listening`) computed upon document upload. **11.** 📦 **On-Demand M4B Download**: Direct 1-click download of M4B audiobooks (`#ab-download-m4b-btn`) with chapters and embedded cover art. **12.** 📥 **Instant 1-Click Multi-Format Download Pills**: On-demand download buttons for PDF, DOCX, EPUB, and TXT directly inside the translation result card, generating and serving any format in < 1 second from cached translation memory. |
| **Prior Choice Quota Routing & Automatic Background Resumption (`quota_behavior: 'wait'`)** | Prior to translating or generating an audiobook, the system defaults strictly to `⏳ Wait for Reset` whenever a Gemini API key is configured. **When quota is reached, processing halts and pauses safely at disk checkpoint (`.direct_ai_checkpoint.json` / `.comic_vision_checkpoint.json`), displaying a live countdown timer. A background watchdog monitor continuously checks pool cooldowns and AUTOMATICALLY resumes waiting jobs and queued batch items the moment cooldown expires or new keys are added — NEVER silently falling back to basic Google Translate or skipping AI polish unless the user explicitly chose `🔄 Auto-Fallback`.** When no API keys exist in the pool, BookApp automatically activates **Free Mode** as the default across all modules. |
| **Hybrid AI Architecture** | Modular three-tier architecture (Polishing, Translation, TTS) with independent provider routing between primary (Google Gemini) and secondary completely free self-hosted / local engines (Edge-TTS, Piper TTS `el_GR-joy-medium`, NLLB-200, and OpenAI-compatible endpoints like VoiceStudio). |
| **Single-Pass Direct AI Translation & Polish** | When **AI Polish** is enabled with a Gemini API key, books and documents (PDF, TXT, and cross-format DOCX/EPUB exports) translate & polish in **one single parallel pass**; DOCX→DOCX and EPUB→EPUB instead use the format-preserving AI path, which keeps the original formatting (5 concurrent workers, prioritizing full Gemini Flash models over Flash-Lite, `maxOutputTokens: 16384`, `thinkingBudget: 0`, `safetySettings: BLOCK_NONE`, `thought: true` part filtering, and `5500 chars / max 3 pages` safe batching) — with **recursive multi-page & paragraph-level bisection** on `MAX_TOKENS`, `SAFETY`/`PROHIBITED_CONTENT`, or timeouts (eliminating silent multi-page raw-MT fallbacks), **XML-delimited `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` + deterministic boundary deduplication** (zero repeated overlap paragraphs or leaked `[...]` context), **whole-book stratified Entity Consistency Dossier** (full-book frequency scan + 9 evenly spaced excerpts for 35–60 terms with explicit grammatical gender & anti-conflation), uniform Greek dialogue guillemets (`«...»`), **targeted mixed-script retry** (without Flash-Lite downgrade), style-aware Glossary isolation, Disk Checkpointing, exact `batches + pages` live progress, and full settings restore on Session History resume. |
| **Parallel English ⇄ Greek Translation + 429 Failover** | High-speed parallel translation (`Semaphore(4)`, `CHUNK_SIZE=4000`, HTTP keep-alive) via Google's GTX POST API with a 20s `429` circuit breaker, async MyMemory fallback, concurrent thread-safe deep-translator isolation, and **automatic Gemini Flash failover**. Includes a **Gemini Daily Quota Circuit Breaker & Warning System** (`DailyQuotaExhaustedError`, `get_gemini_quota_info`): when Google's Free Tier daily request limit is exceeded, it fails fast in <1ms without looping over 35 candidate models, surfaces instant UI warning toasts, prominent Quota Banners with exact remaining cooldown and a one-click `🔑 Change API Key` button (across the Batch Queue, Single Progress Card, Result Card, and AI Polish Modal), and gracefully falls back to standard translation with checkpoint preservation so queues and single translations never hang or produce silent unnotified degradation. |
| **Automatic Graphic Novel & Scanned PDF Detection** | On upload (`POST /api/upload`), `detect_is_graphic_novel()` inspects CBZ/CBR archives and PDF pages (image coverage, vector text density, artwork cues) to automatically detect digital & scanned Graphic Novels and **lock the UI strictly to Graphic Novel options** (`PDF/CBZ/CBR/EPUB`, `Graphic Novel` layout, `LTR/RTL` reading direction) while disabling incompatible text options. **Scanned PDFs need no OCR**: the upload card asks whether a scanned PDF is a **📖 Book** or a **🎨 Comic** (guessed from the page images and the file name). A book's page text is read once by Gemini Vision (`backend/scan_reader.py`, one request per page on Flash-Lite, kept next to the upload) and then translated, narrated or summarised like a digital book; a comic is translated on its page images. Both need a Gemini key. Streaming upload validation enforces the 250 MB cap without OOM, sanitizes Windows-illegal/reserved filenames, enforces universal `job_id` path-traversal protection across all endpoints, and rejects empty (0-byte), >250 MB, or corrupted DOCX/EPUB/CBZ/PDF files immediately with clear messages. |
| **Parallel Scanned Comic Vision AI & Manga (RTL)** | Translates both digital and **scanned/image-only** comics & Manga preserving 100% of surrounding artwork. Features **CBZ Zip Slip protection**, **natural numeric page sorting** (`page_1`, `page_2`, ..., `page_10`), target-language-aware vector AI polish, fail-loud validation if a scanned comic lacks a Gemini API key, **3 parallel Full-Flash Gemini Vision workers** (`gemini_comic_vision_v2` SHA-256 cache, `maxOutputTokens: 8192`, `thought` filtering, mixed-script corruption failover, clamped `[0..1000]` boxes, resilient malformed-JSON recovery, dialytika+tonos `ΐ`/`ΰ` ALL-CAPS sanitization), a **two-pass non-blank balloon renderer** (down to `3.0pt` with condensed font fallback), and exports to **PDF, CBZ, CBR (a real RAR archive) and Fixed-Layout EPUB** (including `page-progression-direction="rtl"`); their pages keep the scan's own resolution (1,600–2,560 px on the long side, about 1.2 MB a page), and files made too large by earlier versions are made again. |
| **Sample First & Gemini Request Estimate** | Above the Start button, `GET /api/translate/estimate/{job_id}` says about how many Gemini requests the chosen settings need (reading scanned pages, translation batches, the 2nd pass) and what the keys allow a day on the best model, with daily limits learned from Google's 429 answers. **🧪 Μετάφραση δείγματος** translates only pages *a–b* (`page_from` / `page_to`) with the same settings: the AI path translates only the batches holding them and keeps its checkpoint, so the whole book reuses them; the sample's downloads are named `_sample_pa-b`. |
| **Bilingual Edition** | **🔀 Δίγλωσσο** on the result card: the original and the translation together, paragraph by paragraph (the original smaller and grey), as PDF, DOCX or EPUB (`backend/bilingual.py`). Pages are matched by their markers and paragraphs by a Gale & Church length alignment, so joined or split paragraphs never make the texts drift. |
| **📲 Devices: E-reader Catalogue** | A secret **OPDS** link (`/opds/<token>/`, only its hash stored) lets KOReader, Moon+ Reader, Librera or Panels list and download the user's finished books as EPUB, PDF, bilingual EPUB or CBZ. Per user with accounts on. |
| **Reading Along** | The audiobook player's **📖 Κείμενο** panel highlights the sentence being read and follows it; a click plays from any sentence. Times come from each recorded part's real duration (`<audiobook>.sync.json`). |
| **More Book Insights** | Besides summaries and synopses (`backend/insights_more.py`): **characters & terms** (names the book does not contain are dropped; Greek spellings go to the Glossary in one click), **chapter-by-chapter** summaries (or **one chapter** in detail), **the story so far** up to the reader's page (only those pages are sent), a spoiler-free **back-cover blurb** (also the book's description in the e-reader catalogue), **quotes** verified word for word with their page, a **study guide**, a **timeline** in story order, and **ask the book**: answers from the book alone, citing pages. Results are stored, exported and narrated like the summaries. |
| **Persistent SQLite Database & Full Resume Restore** | Full job state & translation settings persistence across server restarts (`data/bookapp.db`) in WAL mode with connection locking, automatic orphaned `running`/`queued` job recovery on startup, `file_path` auto-healing, persisted cancellations & standalone AI polish states, thread-safe SSE subscriber delivery with full-queue resilience & automatic terminal close, `.cbz`/`.cbr`/`.m4b` disk recovery, and full UI settings restoration when resuming from Session History. Jobs are kept **until you delete them**: no restart or housekeeping removes them by age or file name. |
| **Semantic Translation, Polish & Vision Cache** | SHA-256 content-hash caching (`gemini_polish_v4` hashing the full system prompt so styles, languages, glossaries & dossiers never collide; `gemini_comic_vision_v2`; `google`) for translated chunks, AI-polished batches, and scanned comic Vision detections (corrupted/truncated outputs and MyMemory error strings are never cached). Cached items return in ~3ms with zero API/quota consumption and live statistics (`GET /api/cache/stats`). |
| **Storage Auto-Cleanup Garbage Collector** | Automated disk management (`backend/storage_cleaner.py`) that removes only scratch files older than the retention window (audio chunks, voice previews, extractions, abandoned partial uploads) and orphaned folders without a job record or user files. It never removes a job in Session History or a folder holding results (`POST /api/admin/cleanup`, default 48 h, enforcing `max_age_hours >= 1`; startup uses 24 h). |
| **Greek Editorial Typography & Scripted Sanitization Pass** | Built-in publishing typography & editorial sanitation engine (`backend/typography.py`, 1.25M words/sec): **1.** Sanitizes cross-lingual subword token bleed (Polish `-łεś` ➔ `-ες`/`-σες`, micro sign `µ` ➔ `μ`, Hebrew `ד`/`ט`/`ם`, Armenian `ի`/`տ`, Arabic, Ge'ez, Devanagari, Vietnamese words, Latin homoglyphs `k` ➔ `κ`, `pt` ➔ `πτ`, `an` ➔ `αν`, `for` ➔ `φορ`, `ti` ➔ `τι`, `Ta` ➔ `Τα`). **2.** Eliminates code leaks (`iterrows` ➔ `ίσως`) and foreign word contamination (`podría` ➔ `μπορούσε`, `στην hull του` ➔ `στο κύτος του`, `То riven φουσκωτό` ➔ `Το σχισμένο φουσκωτό`, `Gang` ➔ `Συμμορία`, `Major` ➔ `Ταγματάρχη`, `αδοσυμεντεδ` ➔ `μη καταγεγραμμένων`). **3.** Corrects glaring machine translation comedic calques and false friends (`κατινιάσει τα πέταλα` ➔ `τινάξει τα πέταλα`, `άλωσε το πληκτρολόγιο` ➔ `άρπαξε το πληκτρολόγιο`, `αλόγους της Παναγίας` ➔ `αλογάκι της Παναγίας`, `το σκιασμένο πάνθηρα` ➔ `το σκιασμένο πλαίσιο`, `για ζήση` ➔ `για βιοπορισμό`, `να το λείψω` ➔ `να ζήσω χωρίς αυτό`, `ανθρωπάκια της κάψουλας` ➔ `άνθρωποι των λοβών`, `Είναι μια παρθένη, Σουζ` ➔ `Είναι μια παραίσθηση, Σουζ`). **4.** Normalizes OCR/MT double accents (`σκύλί` ➔ `σκυλί`, `βαθύνόμενο` ➔ `βαθαινόμενο`) while strictly preserving legitimate Greek enclitics (`το όνομά μου`, `κάνοντάς τα`). **5.** Removes word stutters (`ο Σπίντελ ο Σπίντελ` ➔ `ο Σπίντελ`). **6.** Restores erroneously translated URLs and shields URL paths. **7.** Enforces standard Greek editorial quotes (`«...»`), dialogue em-dashes (`—`), and the Modern Greek Rule of Final 'ν' (`δε/δεν`, `μη/μην`). |
| **Style-Aware Categorized Glossary** | Categorized terminology engine (`technical`: 1,130 terms, `literary`: 1,032 terms, `general`: 1,204 terms — **3,366+ total terms**) with **idempotent single-pass placeholder substitution** (never recursively double-substituting parenthetical terms across passes), regex-backslash-safe replacements (`C:\temp`, `\1`), hyphen-safe & symbol-safe word boundaries (`pod-man`, `royalty-free`, `(.NET)`), automatic exclusion of IT/DevOps/Kubernetes terms in literary/comic/audiobook/poetry modes, and protection of English bibliographic citations. In a finished Greek translation, an English term inside a Greek sentence keeps its place and gets its Greek translation once per document, in parentheses (a Greek noun cannot replace it without knowing its case and gender); a term alone on its line is replaced. |
| **Auto-Genre & Style Detection** | Real-time text analysis (`backend/genre_detector.py`, `POST /api/detect-genre`) with single-word & multi-word phrase matching (including 2-letter acronyms like `IP`) detecting Poetry, Literature, Technical, Formal, or Comic documents upon upload while filtering TOC/bullet lists from poetry false positives, auto-suggesting matching AI polish style and glossary category (`technical`, `literary`, `general`). When the file describes itself as poetry or fiction (EPUB `dc:subject`/`dc:type`, PDF subject/keywords, DOCX subject/keywords/category), that decides; a book *about* poetry ("… history and criticism") is left to the text analysis. The suggestion is shown and can be changed before translating. |
| **Multi-Voice Audiobook Dramatization** | Distinct narrator and dialogue voices for English books (e.g. Guy for narration + Jenny for character speech), explicit speaker tags (`[Guy]: ...`, `[Jenny]: ...`), case-insensitive & raw Edge-TTS voice code lookup, and automatic quote dialogue routing. Greek has one voice (Nestoras), so the option is hidden for Greek. |
| **M4B & Tagged Audiobooks** | Exports `.mp3` and real `.m4b` (MP4/AAC) audiobooks with full ID3v2/MP4 metadata tagging (Title, Artist, Album, Genre="Audiobook"), chapters and embedded cover art (`attached_pic`). Uses FFmpeg from `PATH`, or the copy bundled with the `imageio-ffmpeg` dependency. If conversion is impossible the app says so and keeps the MP3; it never saves MP3 data under an `.m4b` name. |
| **Voice Preview Auditions** | Instant 2–3 second voice audition playback button (`🔊 Preview`, `GET /api/tts/preview`) next to each voice in the UI with strict voice-ID validation and atomic preview caching. |
| **Modern UI Controls & One-Click Launcher** | Dynamic origin API detection (`localhost`, `127.0.0.1`, or LAN hosts), resilient error formatting (`parseApiError` for HTTP 422/500/non-JSON responses), Light theme by day and dark at night (the toggle switches until the next sunrise or sunset), ❓ Help window with a guide & FAQ in Greek and English, dedicated **🔄 Refresh** button in header & navbar, dedicated **🔑 Gemini API Key** button with **💾 Save Key** and auto-sync to server (resetting both text and comic vision model caches), Direct Editor AI Polish without requiring a file upload first, Split-Screen Editor with Sync Scroll, and Windows desktop launcher (`start_bookapp.bat`). |
| **💡 Book Insights: Summaries, Synopses & Audio** | New **Book Insights** tab (`backend/book_insights.py`) next to Translate and Audiobook. **Basic Mode:** *1-Click Summary* (short summary) and *1-Click Synopsis* (standard synopsis), written automatically in the document's language. **Advanced Mode:** one-sentence (20–40 words), short (150–300) and extended (500–1,000) summaries; standard (800–1,200) and extended (1,500–2,500) synopses; output in Greek or English; shown on screen or exported to PDF / DOCX / TXT. Every result can be narrated with the existing neural voices (playable in the page, downloadable MP3). Length is estimated from *meaningful* extracted text (page numbers, running headers and URLs removed; 1 page = 250 words). Synopses need at least 1.5 pages (375 words), summaries at least 80 words; word targets scale down for short sources so nothing is padded or invented. Long books use cached map-reduce (section notes are reused by every type and language). Each text is checked automatically before it is shown: language, sentence/word count, structure, Latin script inside Greek, names/numbers absent from the source, condensation, and similarity to the paired summary/synopsis. Defective output is regenerated once and never displayed if it still fails. Greek output gets an extra proofreading pass. Requires a Gemini API key; reuses the 4-key pool, failover, rate limiter and cache. |
| **Publication-grade AI translation & audiobook prompts** | Prompt library `backend/translation_prompts.py` (versioned, `PROMPT_VERSION`). Shared by single-pass AI translation, AI Polish and the audiobook script polish.
<br>• **Fidelity first:** no omissions, additions or embellishment; the author's voice, register and sentence rhythm are kept.
<br>• **English→Greek fault checklist:** subject pronouns (Greek is pro-drop), overused possessives, needless indefinite articles, `ο οποίος` chains, participle chains, passive voice, false friends (`eventually`, `actually`, `makes sense`), literal idioms, precise everyday vocabulary, consistent tense.
<br>• **Greek typography:** sentence-case titles (no English Title Case), unaccented ALL-CAPS, `;` `·` `…`, «» with nested “”.
<br>• **Dedicated translate-from-source prompt:** single-pass translation previously wrapped the *polish* prompt ("improve this Greek translation") around an English source.
<br>• **Language-aware:** English targets get English rules instead of Greek-only ones.
<br>• **Generic:** terminology hard-coded from one novel was removed.
<br>• **Whole-book dossier plus style sheet:** narrative tense and person, register, and εσύ/εσείς between characters, kept consistent across parallel batches. Greek audiobooks get a **pronunciation register**, so each foreign name is spoken identically throughout.
<br>• **Audiobook script:** no paraphrasing; spoken forms in the correct grammatical case (`ήταν 38°C` → `ήταν τριάντα οκτώ βαθμοί`), Roman numerals, times, ordinals, symbols, ALL-CAPS emphasis lowered so TTS doesn't spell it.
<br>• **Fixes:** resume checkpoints are signed (an interrupted run restarted with another language or style no longer mixes in old batches); AI output is Unicode-normalised (NFC); the final local check restores accents LLMs drop from capitalised words (`Ηταν` → `Ήταν`) and applies final-ν to the article (`στη κάσα` → `στην κάσα`). |
| **🏆 Maximum quality: second AI revision against the original (Advanced Mode)** | Optional checkbox under AI Polish (translation tab, Advanced Mode only; `max_quality: true` on `POST /api/translate`). After the single-pass AI translation, a second, independent Gemini reviser compares the translation **sentence by sentence with the original** (page-aligned `<SOURCE_REFERENCE>`/`<DRAFT_TO_POLISH>` batches). It fixes only real errors: meaning, omissions or additions, gender/number/case agreement, inaccurate words and literal idioms, spelling, and consistency. Correct text is left untouched.
<br>• **Cost:** shown in the UI before you start (≈ 1.5× the tokens of the AI translation, ≈ 2× the time).
<br>• **Models:** runs on **full Gemini models only**, via a context-scoped policy. If only Lite models are available, the revision is skipped rather than degraded.
<br>• **Safety:** the result is accepted only if every page marker is preserved and the length stays plausible (0.8–1.25×). Any failure (quota, auth, crash) keeps the first-pass translation, and the job still completes.
<br>• **Reporting:** stored as `revision_report` (status API & SSE). Never applied to batch-queue items.
<br>• **Measured on a test passage with real Gemini:** fixed gender agreement, a dropped accent, a mistranslated idiom and an added detail. It may still make an occasional unneeded stylistic change. |
| **AI Polish engine improvements** | `_call_gemini_api` (shared by AI Polish, Single-Pass translation, comics and Book Insights) now uses a **size-aware request timeout** (45–180 s instead of a fixed 25 s). The fixed limit made long batches time out on full Flash models and silently fall back to Lite models. The rate limiter now gets a **real token estimate** instead of a constant 1,500, so TPM pacing is accurate. A new optional `cache_gate` lets callers whose outputs are legitimately short or non-Greek (summaries, notes, English text) use the SQLite cache. The default Greek quality gate is unchanged. |
| **Automatic Final Output Refinement & Quality Control** | Independent, local-only stage (`backend/output_refiner.py`) that runs automatically as the **last step of every successful translation and audiobook**. *Translations:* inspects page-marker continuity, empty pages, untranslated (Latin-script) paragraphs, unbalanced quotes/brackets, possible calques, stutters, accented monosyllables, final-ν, broken hyphenation and spacing; auto-corrects **only unambiguous errors** (ambiguous phrasing such as `κάνει νόημα` or emphatic repetition such as `Όχι όχι` is reported, never rewritten). Respects layout & language (poetry whitespace kept, French `« Bonjour ! »` spacing kept). Safety guards revert any change that alters page markers, paragraph count or length by >10%. Writes are staged and swapped atomically; the text and the exported PDF/DOCX/EPUB stay in sync (rollback on failure). **Format-preserving outputs (in-place DOCX/EPUB, comics) are inspected only, never regenerated.** *Audiobooks:* validates container header, playable duration, truncation and section continuity; **re-synthesises failed sections (max 25) and re-assembles** into a validated staging file before replacing the original; adds ID3 tags only if missing. Zero API consumption. Always active by default; the 🔍 toggle appears only in **Advanced Mode** (also `final_refinement_enabled` setting / `FINAL_REFINEMENT_ENABLED` env var / per-request `final_refinement`). Report stored on the job (`refinement_report`, shown via `/api/status` & SSE); on-demand via `POST /api/refine`. |
| **Unified Upload & Smart Batch Queue (Up to 20 Files)** | Select or drop **1 file or up to 20 mixed files** (novels, EPUBs, Graphic Novels, Manga — max 250 MB/file) directly inside the top **Upload Document(s)** card, or click **➕ Add More** on a single file to seamlessly promote it into a batch. Configure Translation Settings below once — `POST /api/queue/start` syncs your latest settings onto all queued items while auto-protecting Comics vs Books per file (and auto-disabling Auto-Start on mixed queues). Runs serially (1 doc at a time at full 4–5x internal parallelism to avoid `429` collisions) with isolated per-item cancel, **🔄 Retry** (`POST /api/queue/{job_id}/retry`), **⏸️ Pause / ▶️ Resume**, **⚡ Auto-Start**, live progress bars, immediate per-item download as soon as each file finishes, and **📦 Download All (ZIP)** (`/api/queue/download-all`, unlocked once all queued translations complete). |
| **Security & reliability hardening (Nov 2026 audit)** | <br>• **CORS:** restricted to the app's own origin plus local development origins (`localhost`, `127.0.0.1`, `[::1]`); previously any website open in the browser could read `/api/settings`, including the Gemini keys, or send requests to the local app. Add origins explicitly with `BOOKAPP_CORS_ORIGINS`.
<br>• **Queue auto-resume:** fixed a quota-paused Smart Batch Queue that never resumed by itself (missing `global`).
<br>• **Comic AI polish:** an undefined exception name no longer turns errors into crashes.
<br>• **Dependencies:** Pillow added to `requirements.txt`; it was used by the comic translator but missing, which broke fresh installs and Docker.
<br>• **Event loop kept free:** document analysis on upload, PDF/DOCX/EPUB exports, full-document parsing, audiobook MP3 concatenation, tagging and M4B copy, and the refinement re-export now run in worker threads, so long books no longer freeze progress updates or other requests.
<br>• **Cleanup:** dead code and five obsolete one-off glossary generator scripts removed. The backend is pyflakes-clean. |
| **November 2026 improvement batch** |<br>• **Format-preserving AI translation:** DOCX→DOCX and EPUB→EPUB with AI Polish now keep fonts, styles, bold/italic runs, tables, images and HTML/CSS. Gemini translates the document's own paragraphs, runs and text nodes in numbered, context-preserving batches (`backend/ai_segment_translator.py`). Dropped segments fall back individually to the free engine.
<br>• **API keys never leave the server:** `/api/settings` returns masked keys only; the browser no longer stores keys (old browser-stored keys are migrated once). Masked values sent back on save map to the stored keys.
<br>• **Optional device pairing (no password):** `BOOKAPP_PAIRING=1`; see the Admin Manual.
<br>• **Gemini usage per job and per day:** requests and tokens recorded on every job, shown when it finishes and in the settings window.
<br>• **Faster model failover:** a model that timed out is tried last for 10 minutes.
<br>• **M4B chapters:** detected from chapter headings, with chapter marks saved next to the MP3 so later M4B downloads get them too. The ffmpeg timeout now scales with file size.
<br>• **Book Insights after a restart:** progress recovers (the saved result, or a clear 'interrupted' message).
<br>• **Title Case fix:** English-style Title Case headings are converted to Greek sentence case, with names kept.
<br>• **Comic requests:** no API key in URLs any more.
<br>• **Translation evaluation set:** `eval/passages.json` + `scripts/eval_translation_quality.py`.
<br>• **Reproducible installs:** constraints file `requirements-lock.txt`.
<br>• **Code structure:** routers in `backend/api/`, frontend split into `app.js`, `insights.js` and `pairing.js`. |
| **User accounts with administrators (Nov 2026)** |<br>• **Optional sign-in** (`BOOKAPP_AUTH=1`) for a server shared by several people (Ubuntu, Docker, Synology).<br>• **Two roles:** users see only their own jobs; administrators manage users, Gemini API keys and settings, see every job, and can make another user an administrator with the same rights. The last active administrator is always protected.<br>• **First administrator on a headless server:** a one-time setup code appears in the server log (`journalctl`, `docker logs`, Synology Container Manager) and in `data/setup_code.txt`; open `/setup`. Or run `python -m backend.auth create-admin NAME`, which also resets forgotten passwords.<br>• **Sessions:** "keep me signed in" lasts 60 days and renews on every visit. Temporary passwords must be changed at the first sign-in; 5 wrong passwords lock for 15 minutes.<br>• **Storage:** scrypt password hashes and hashed session tokens in `data/auth.db`; admin actions in an audit log.<br>• **Setup guide:** HTTPS with Caddy, nginx or Synology DSM in the Admin Manual. |
| **Data-safety fixes (22 Nov 2026)** |<br>• **No more data loss on restart:** startup used to delete jobs named like test files (`book*`, `test_*`, `temp_*`…), records and uploads older than 24 hours and outputs older than 7 days. Jobs now stay until you delete them.<br>• **Formatting kept after editing:** Editor, AI Polish, cover changes, layout downloads and `/api/refine` no longer replace format-preserved DOCX/EPUB or comics with plain-text re-exports.<br>• **Audiobook Wait for Reset:** the web UI now really sends `wait` when a key is stored.<br>• **Real M4B:** MP4/AAC output with working cover + chapters; FFmpeg is bundled through `imageio-ffmpeg`. Mislabelled files from older versions are converted again on download.<br>• **Security:** formats, layouts, directions, quota choices and languages are validated (closing a path traversal through language names), and the batch queue escapes every value (closing a stored XSS).<br>• **Upgrading:** run `pip install -r requirements.txt`, then restart the server. |
| **Reliability fixes (23 Nov 2026)** |<br>• **Free translation without a key:** Google's refusals are respected and MyMemory is used within its daily limit. A saved Gemini key stands in with few requests (this uses your Gemini allowance), and the job says which engine translated. Google currently refuses most automated key-free requests, so a long book without a key may stop with a message instead of being half translated.
<br>• **English audiobooks with AI polish** no longer come out in Greek: English targets get English instructions, and an AI answer in the wrong language or with lost text never replaces the book's text.
<br>• **Your API keys are safe from file locks:** a settings file held for a moment by another program (antivirus, backup) is read again instead of being replaced by an almost empty one.
<br>• **Audiobooks:** cut-off audio is detected and narrated again; Resume reuses finished parts (they stay on disk until the book is complete); a network drop is waited out in the chosen voice; a complete voice outage is reported after about a minute, with Resume. Microsoft's Athina voice was removed (in tests it returned cut-off audio for most parts); saved Athina choices are read by Nestoras.
<br>• **Comics:** captions no longer print over each other; CBR uploads are read with 7-Zip or bsdtar; **CBR exports are real RAR archives** (pages stored as JPEG; checked with RARLAB's UnRAR, 7-Zip and bsdtar).
<br>• **PDF exports:** every script is drawn (polytonic Greek, Arabic, Hebrew, Indic and more), and copied or searched text gives the book's characters. Spaces, hyphens, `;`, `·`, accented Greek vowels and quotes used to come back as look-alike characters (no-break spaces, invisible soft hyphens, Greek question marks). Quotations in Arabic, Hebrew or Indic scripts still copy out as glyph forms.
<br>• **Italics in PDFs:** a font family with every face is preferred (on Linux also Liberation, FreeFont and Noto); where no italic face is installed, the regular face is drawn leaning, so emphasis is never lost.
<br>• **Page numbers:** the PDF's own page labels confirm page numbers, also a lone one such as the number at the foot of a chapter's first page.
<br>• **EPUB:** preformatted text that the book marks as a poem, verse or letter is translated; blocks kept untranslated as program code are reported when the job finishes.
<br>• **Phones:** every screen fits from 320 px wide, also with long file names; the editor's Save and Close stay on screen.
<br>• **Glossary:** an English term inside a Greek sentence is explained once in parentheses instead of being replaced.
<br>• **Queue and exports:** after a restart the queue comes back paused (a queue you paused stays paused, per-file settings are kept); a replaced export is kept in `temp/outputs/<job>/previous/`.
<br>• **Docker:** the image no longer contains `config/settings.json`, which holds your API keys.
<br>• **Upgrading:** interrupted AI jobs restart from the beginning once; books translated by older versions need translating again to benefit. Run `pip install -r requirements.txt` and restart the server. |
| **Automated Test Suite (62 Suites)** | `run_all_tests.py` (`--fast` runs the 57 offline suites; suite names select individual ones) executes everything in a **throw-away sandbox**: a copy of the code on a free port, with an empty database and no API keys, so your jobs, files, settings and a running BookApp are never touched. Suites refuse to run outside it. Covers security (path traversal, Zip Slip, stored XSS), API contracts & state machine, mocked Gemini/GTX resilience, pipeline data integrity, comic/TTS edge cases, concurrency & lifecycle, Node.js VM UI tests, static code health, editorial pass, AI polisher, key pool & diagnostics, batch queue, output refinement, translation prompts, Book Insights, device pairing, user accounts, audit regressions, and `test_data_safety_and_preservation.py` (no data loss on restart, format-preserving edits with randomized round-trips, real M4B, Wait for Reset, input validation). |
| **In-Place Format Preservation** | Translates `.docx` (preserving fonts, headings, bold/italic, tables, merged cells & embedded inline images `<w:drawing>`) and `.epub` (preserving spine order, nested HTML tags `<em>`/`<strong>`/`<blockquote>`, inline whitespace & HTML comments without double-translating) in-place with style-aware glossary & Greek typography cleanup. Later edits (Editor, AI Polish) are applied inside the same file (`backend/format_sync.py`); cover changes, layout downloads and refinement never rebuild it from plain text. |
| **Cover Image Management** | Auto-extraction of original artwork from PDF/EPUB/DOCX (with proper handle cleanup), live preview thumbnail with status `✔ Cover active`, manual upload for custom artwork (`.jpg`, `.png`, `.webp`), removal button (`DELETE /api/cover/{job_id}`), and strict download isolation ensuring only book documents are served. Custom covers go into generated PDF/EPUB/DOCX exports; format-preserved DOCX/EPUB and comics keep their own artwork. |
| **Literature / E-Reader Layout** | Dedicated `layout=literature` mode for novels and books: strips running headers/footers and page numbers, renders `*italic*` and `**bold**` emphasis natively (Georgia Italic in PDF, italic runs in DOCX, `<em>` in EPUB), isolates chapter headings and epigraphs, merges cross-page sentences, formats scene breaks (`* * *`), wraps long unbroken URLs cleanly within page margins, guarantees zero missing-glyph tofu boxes (`□`), and embeds full-bleed covers on page 1 of PDF/EPUB/DOCX. |
| **Multi-Page Front Matter Preservation** | Line-level header/footer cleaning (`_clean_page_blocks`) ensures the initial pages of books (tables of contents, epigraphs, author dedications, and prologues) are 100% preserved without dropping text blocks. |
| **Optimized AI Polish & Proofreading** | Google Gemini AI integration with 5 tailored styles (including dedicated `literature` for fiction & sci-fi with uniform `«...»` dialogue punctuation and `audiobook` spoken narration script editor). Features **Bilingual Source-Anchoring** (page-level comparison between Greek draft and original English to fix mistranslations and false friends), **Whole-Book Stratified Entity Consistency Dossier** (frequency scan + 9 evenly spaced excerpts for uniform character/term names & grammatical gender from chapter 1 to the end), **Clean Boundary-Deduplicated Rolling Context**, **Recursive Multi-Page & Paragraph Bisection** with `BLOCK_NONE` safety settings, **Smart Real-Time Disk Checkpoints** (`.polish_checkpoint.json`), smart multi-page batching cutting API calls by 80%, dynamic backoff, and persistent settings (`config/settings.json`). |
| **Audiobook Script Polish & Spoken Phonetics** | Dedicated spoken script refinement for Edge-TTS neural voices: phonetically transliterates foreign names/acronyms into Greek script (`Keeton` -> `Κίτον`, `Rorschach` -> `Ρόρσαχ`, `DNA` -> `Ντι-Εν-Έι`), fully expands numbers, years, percentages, and abbreviations into spoken words (`2006` -> `δύο χιλιάδες έξι`, `50%` -> `πενήντα τοις εκατό`), completely strips non-spoken artifacts (page markers, footnotes, URLs), and optimizes sentence breathing and pauses. |
| **Translation Editor & Review** | Built-in in-browser Split-View / Full editor to review, edit, and search/replace translated text with live re-export. Format-preserved DOCX/EPUB are edited in place; for comics only the text copy changes. |
| **Gemini Multi-Key API Pool (Up to 4 Keys)** | Connect up to 4 free API keys across different Google accounts (each key adds Google's free daily allowance, which is set per model). Features zero-friction automatic failover upon HTTP 429 quota exhaustion, rotating through standby keys seamlessly before falling back to free web translation engines without stopping or interrupting document progress. |
| **Instant On-Demand Export & Format Auto-Matching** | Uploaded documents automatically set the default output format (e.g. PDF input defaults to PDF output). Output result cards feature instant 1-click pills (**PDF**, **DOCX**, **EPUB**, **TXT**) providing on-demand conversions in < 1s from memory without re-translating. |
| **Bullet, Glyph & URL Normalization** | Replaces proprietary Wingdings/PUA symbols with standard Unicode bullets (`•`) and native Word `List Bullet` paragraphs, strips invisible/replacement control chars (`\ufffd`, `\u200b`), guards PDF rendering per font glyph (`has_glyph` — zero `□` tofu boxes), and wraps long unbroken URLs cleanly within page margins. |
| **Distraction-Free "Read Now" Reader** | In-browser reader modal with Paper, Sepia, and Dark Night themes, text scaling, and side-by-side bilingual comparison mode (English source next to Greek translation) directly from the result card. |
| **AI Neural Audiobooks** | Generates high-fidelity MP3 and M4B audiobooks using Microsoft Edge neural voices with balanced pacing presets (**Literature**, **Poetry & Recitation**, **Calm**, **Standard**, **Brisk**) along with interactive fine-tune sliders for **Speed** (-30% to +30%) and **Voice Pitch & Prosody** (-4Hz to +4Hz). Features theatrical prosody modulation, elision normalization, refined verse pause handling, and **low-memory streamed chunk concatenation (64KB chunks)** guaranteeing zero memory spikes even on 10+ hour audiobooks. |
| **Greek Audio Support** | Native Greek neural voice **Nestoras (Male)** with complete dictionary coverage. |
| **One-Click Direct Audio** | Convert any completed translation directly into a Greek Audiobook with a single click. |
| **Live Progress Streaming** | Real-time progress updates via Server-Sent Events (SSE) distinguishing between document pages and audio parts. |
| **Disk Recovery & Auto-Cleanup** | Jobs, uploads and outputs survive server restarts indefinitely via SQLite & disk recovery; startup housekeeping (`cleanup_old_jobs` & `clean_temp_storage`) only prunes scratch files and true orphans. Remove work with **✕** or **Clear All** in Session History. |

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

Your settings and API keys (`config/settings.json`) are never copied into the image: they stay in `./config`, which the container mounts. Images built by versions before 23 Nov 2026 do contain that file, so delete them (`docker image rm bookapp:latest`) and build again; if such an image was ever shared, replace your keys.

---

## 📁 Project Structure

```
BookApp/
├── backend/
│   ├── main.py              # FastAPI application (REST endpoints & SSE streaming)
│   ├── ai_polisher.py       # Gemini AI proofreading & style polishing engine
│   ├── translation_prompts.py # Versioned prompt library: translation, polish, audiobook script, dossier
│   ├── comic_translator.py  # Graphic Novel & Manga (RTL) balloon translator
│   ├── scan_reader.py       # Scanned books: page text read by Gemini Vision, kept next to the upload
│   ├── bilingual.py         # Bilingual edition: paragraph alignment, PDF / DOCX / EPUB
│   ├── connections.py       # Per-user e-reader link (OPDS)
│   ├── database.py          # SQLite database layer & SHA-256 semantic cache (data/bookapp.db)
│   ├── typography.py        # Greek editorial typography & final "ν" engine
│   ├── output_refiner.py    # Automatic final output refinement & quality-control stage
│   ├── book_insights.py     # Book Insights: AI summaries, synopses & their audio versions
│   ├── insights_more.py     # More Book Insights: characters, chapters, recap, blurb, quotes, study guide, timeline, questions
│   ├── ai_segment_translator.py # Format-preserving AI translation of DOCX/EPUB segments
│   ├── device_pairing.py    # Optional password-free device pairing (BOOKAPP_PAIRING=1)
│   ├── auth.py              # Optional user accounts & administrators (BOOKAPP_AUTH=1); tool: python -m backend.auth
│   ├── request_context.py   # Signed-in user of a request (per-user job visibility & Gemini usage)
│   ├── api/                 # API routers: refine, insights, pairing, auth (+ shared common.py)
│   ├── genre_detector.py    # Document genre, tone & style auto-detection engine
│   ├── storage_cleaner.py   # Temporary files & storage garbage collector
│   ├── format_sync.py       # Applies later edits inside format-preserved DOCX/EPUB; guards them from re-export
│   ├── format_preserver.py  # In-place DOCX/EPUB formatting & styling preservation
│   ├── exporter.py          # Exporter for DOCX, PDF, EPUB, TXT, CBZ, CBR
│   ├── comic_archive.py     # Reads CBR uploads (7-Zip / bsdtar) and writes CBR exports (RAR)
│   ├── comic_build.py       # Makes a comic's EPUB / CBZ / CBR in a child process (the server keeps answering)
│   ├── pdf_text_names.py    # Makes text copied or searched from exported PDFs match the book
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
│   ├── bookapp.db           # Persistent SQLite database (jobs, metadata & translation cache)
│   └── auth.db              # User accounts (password & session hashes, audit log; BOOKAPP_AUTH=1)
├── frontend/
│   ├── index.html           # Modern single-page interface with unified Upload & Batch Queue, ❓ Help (guide & FAQ, Greek / English)
│   ├── style.css            # Responsive CSS theme with theme variables
│   ├── theme.js             # Light by day, dark at night (sunrise / sunset); the button switches until the next change
│   ├── app.js               # Frontend state, batch queue, split-screen editor & voice preview
│   ├── insights.js          # Book Insights tab
│   ├── pairing.js           # Device pairing panel (settings window)
│   ├── auth.js              # Signed-in user bar, own account, user management (administrators)
│   └── login.html           # Sign-in, first-time setup & temporary-password page
├── docs/
│   ├── USER_MANUAL.md       # Complete user guide
│   └── ADMIN_MANUAL.md      # Administrator deployment & technical manual
├── tests/                   # 62 Automated Test Suites (sandboxed)
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

The master runner works in a throw-away copy of the project (free port, empty database, no API keys), so your jobs, files, settings and a running BookApp are never touched:

```bash
# Run all 66 automated test suites (Full Suite)
.\.venv\Scripts\python run_all_tests.py

# Run fast local suite (57 static/unit/security/contract/resilience/UI/queue/benchmark suites)
.\.venv\Scripts\python run_all_tests.py --fast

# Run individual suites
.\.venv\Scripts\python run_all_tests.py test_data_safety_and_preservation test_output_refinement
```

Test files refuse to run on their own (`python tests/test_x.py`, `unittest`, `pytest`), because outside the sandbox they would share your real database, keys and port 8000.

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
