# 🛠️ Administrator & Deployment Manual
### DocTranslate & AudioBook Generator

This manual is intended for System Administrators, DevOps Engineers, and technical maintainers responsible for deploying, configuring, monitoring, and scaling **DocTranslate & AudioBook Generator** in local, on-premises, or cloud server environments.

---

## 📑 Table of Contents
1. [Technical Architecture](#1-technical-architecture)
2. [System Prerequisites](#2-system-prerequisites)
3. [Step-by-Step Installation](#3-step-by-step-installation)
   - [3.1 Ubuntu Server with Docker](#31-ubuntu-server-with-docker)
   - [3.2 Synology NAS with Docker (Container Manager)](#32-synology-nas-with-docker-container-manager)
   - [3.3 Ubuntu Server without Docker (Python + systemd)](#33-ubuntu-server-without-docker-python--systemd)
   - [3.4 First Sign-In (every server installation)](#34-first-sign-in-every-server-installation)
   - [3.5 Windows or macOS Computer (one person)](#35-windows-or-macos-computer-one-person)
4. [Production Deployment](#4-production-deployment)
   - [Option A: Windows Service (NSSM)](#option-a-windows-service-via-nssm)
   - [Option B: Linux Systemd Service](#option-b-linux-systemd-service)
   - [Option C: Docker & Docker Compose](#option-c-docker--docker-compose)
   - [Nginx Reverse Proxy Configuration with SSE](#nginx-reverse-proxy-configuration-with-sse)
   - [User Accounts & Administrators (sign-in)](#user-accounts--administrators-sign-in)
   - [HTTPS for User Accounts (Caddy, nginx, Synology DSM)](#https-for-user-accounts-caddy-nginx-synology-dsm)
5. [Storage Layout & Data Management](#5-storage-layout--data-management)
   - [Directory Structure](#directory-structure)
   - [REST API Administration Endpoints](#rest-api-administration-endpoints)
   - [Automated Storage Housekeeping](#automated-storage-housekeeping)
6. [Automated Test Suite Execution](#6-automated-test-suite-execution)
7. [Technical Troubleshooting](#7-technical-troubleshooting)

---

## 1. Technical Architecture

The application implements an asynchronous, event-driven API architecture:

```
┌────────────────────────────────────────────────────────┐
│                   Web Browser (Client)                 │
│         Single Page App (HTML5 / Vanilla JS / CSS)     │
└──────────────┬────────────────────────▲────────────────┘
               │ REST API (JSON/Files)  │ SSE Streaming
               ▼                        │ (/api/progress)
┌───────────────────────────────────────┴────────────────┐
│               FastAPI / Uvicorn Server                 │
│ ┌────────────────────────────────────────────────────┐ │
│ │  Job Manager (In-Memory + Disk Recovery Fallback)  │ │
│ └────────────────────────────────────────────────────┘ │
│ ┌──────────────────────┐    ┌────────────────────────┐ │
│ │  Format Preserver    │    │      TTS Engine        │ │
│ │  - python-docx       │    │  - edge-tts (Neural)   │ │
│ │  - PyMuPDF (fitz)    │    │  - Streamed MP3 Chunks │ │
│ │  - EbookLib / BS4    │    │  - Nestoras, English   │ │
│ └──────────────────────┘    └────────────────────────┘ │
└──────────────┬────────────────────────┬────────────────┘
               │ Outbound HTTPS         │ Outbound WSS/HTTPS
               ▼                        ▼
      Google Translate API     Microsoft Speech Services
      (client=gtx endpoint)     (Neural Voices: el-GR, en-US)
```

### Core Backend Components
* **FastAPI & Uvicorn:** Asynchronous, non-blocking Python ASGI web framework with connection keep-alive.
* **SQLite Persistence Layer (`data/bookapp.db`):** Persistent job state management in WAL mode (Write-Ahead Logging) with thread-safe locking. Recovers orphaned `running`/`queued` jobs on startup (`db_reset_orphaned_running_jobs`), stores complete metadata (`output_format`, `layout_mode`, `source_lang`, `target_lang`, `ai_polish`, `reading_direction`, `total_pages`, `done_pages`), and heals broken file paths (`_heal_file_path`) for zero data loss across reboots.
* **Smart Batch Queue Engine (`backend/queue_manager.py`):** Serial batch execution engine with a default limit of `MAX_QUEUE_ITEMS = 20` files per batch (max 250 MB per file). Supports dynamic setting synchronization on `POST /api/queue/start` (`apply_settings_to_queued_items`), mixed-batch comic protections (auto-disabling Auto-Start on mixed queues and preserving `layout_mode="comic"`), isolated child `asyncio.Task` per document, item retry (`POST /api/queue/{job_id}/retry`), pause/resume, and ZIP bundling (`GET /api/queue/download-all`, returning HTTP 409 while items are in progress). Automatically pauses the queue if a document encounters quota exhaustion with `quota_behavior="wait"` without failing over to plain translation. A background watchdog loop (`_quota_auto_resume_monitor` in `backend/main.py`, ticking during FastAPI lifespan) continuously monitors pool key cooldowns via `GeminiKeyPool.check_cooldowns()`, resetting the circuit breaker and automatically resuming paused jobs and queues from their disk checkpoint the instant cooldown expires or new keys are saved in settings.
* **Security, Upload Validation & Path Hygiene Guard (`backend/main.py` & `job_manager.py`):** Enforces universal path-traversal validation via `_validate_job_id()` / `is_valid_job_id()` across all endpoints (`/polish`, `/download`, `/cover`, `/jobs/*`, `/preview`, `/debug/extract`). Streaming upload parser validates the 250 MB size limit (`HTTP 413`) without OOM, sanitizes Windows-reserved filenames (`CON`, `NUL`, `<>:"|?*`), caps a name's stem at 100 characters at a word boundary (`_MAX_STEM_CHARS`; outputs add `_translated_greek.pdf`, `.revision-tmp` and so on, Windows paths stop at 260 characters and Linux names at 255 bytes, so 200-character download names used to fail with `OSError`), writes the upload to `temp/uploads/tmp/<uuid><ext>` without the name, turns a storage `OSError` (disk full, permissions) into an HTTP 500 with a readable message (the browser's upload progress comes from `XMLHttpRequest` in `frontend/app.js` `uploadWithProgress`, since `fetch` reports none; its 401/403 answers go through the same sign-in redirect as `fetch`, `window.__bookappAuthRedirect` in `auth.js`), checks file magic headers (`PK`, `%PDF`), prevents **Zip Slip** vulnerabilities in CBZ extractions (`_safe_extract_zip`), and validates voice IDs and prosody bounds.
* **Semantic Cache Layer (v4):** SHA-256 content-hash caching for translated chunks (`google`), AI-polished batches (`gemini_polish_v4` hashing the entire `system_prompt` so styles and languages never collide), and comic Vision detections (`gemini_comic_vision_v2`). Rejects corrupted or MyMemory error payloads before caching. Telemetry available via `GET /api/cache/stats`.
* **Storage Auto-Cleanup Garbage Collector (`backend/storage_cleaner.py`):** Removes scratch files older than the retention window (loose audio chunks, `temp/previews/`, partial uploads in `temp/uploads/tmp/`, extractions) and true orphans: upload folders with neither a job record nor outputs, and output folders older than 7 days with neither a job record nor user files. It never removes a recorded job at any age, and removes no job folder if the database can't be read (`POST /api/admin/cleanup`, default 48 h).
* **Graphic Novel & Manga (RTL) Comic Engine (`backend/comic_translator.py`, `backend/exporter.py`):** Prioritizes full Gemini Flash Vision models, supports Japanese Manga RTL reading progression, clamps `box_2d` to `[0..1000]`, sanitizes Greek uppercase dialytika (`ΐ`/`ΰ` ➔ `Ϊ`/`Ϋ`), renders balloons via a two-pass non-blank layout engine down to `3.0pt` with `Arial Narrow` fallback, sorts CBZ pages naturally (`page_1`, `page_2`, ..., `page_10`), and serializes concurrent vision checkpoints via `asyncio.Lock` and UUID temporary files.
  * **Vision quality gate (`_comic_items_problem`, used by `_take` in `_detect_comic_balloons_vision_async`):** an answer in Latin letters (Greeklish: three or more Latin words the original balloon doesn't have, outweighing the Greek letters) or with mixed scripts goes to the next model. Greeklish is never kept; mixed scripts stay the last resort. An empty answer is checked by a second model, and accepted only if no model saw text. Cache and checkpoint entries that fail the gate are asked again (the new answer replaces the cached one); empty pages are never checkpointed.
  * **One spelling per name:** Vision returns a `names` map per balloon (`{"NAME IN THE ORIGINAL": "NAME IN THE TRANSLATION"}`). Each page's prompt lists the names already used (`known_names`, up to 60). Before rendering, `_harmonize_comic_names` gives each name one spelling on copies of the answers: the glossary's (`load_glossary(style="comic")`), otherwise the one most pages used. Spellings that differ only in their last two letters are Greek cases and stay.
  * **Notes and log:** the job notes give the untranslated pages with the most common Vision error, and the scanned pages where no text was found. The log names each failed page: `Page N left untranslated: Vision AI failed (…)`.
  * **Balloon shapes (`_find_balloon`, `_plan_in_balloon`, `_paint_balloon`):** before drawing, the page is rendered once at 2× (`_BALLOON_ZOOM`). For each Vision box the commonest colour in the box is the paper; a scanline flood (`_flood`, Pillow and `bytes.find` only, no numpy) fills the paper from the box's middle up to the outline, widening the window twice when the paper reaches its edges. Spots the flood can't reach inside the balloon are the letters, giving the true lettering extent and its size (line height ÷ 0.73). The cover is a PNG in the paper colour, masked to the balloon (outline and artwork stay). A balloon holding one text lays it out line by line in the balloon's width at each height; two texts in one balloon keep their own boxes. Size caps: 1.12 × the larger of the text's own lettering and the page's median (at least 4.5pt, at most 13pt). No balloon found (text on the artwork, paper under 35% of the box, flood leaking past the largest window): the old rectangle. Text too long for its balloon falls back to `_plan_balloon_layout` with a backdrop in the paper colour where it leaves the balloon.
* **Greek Editorial Typography & Scripted Sanitization Pass (`backend/typography.py`):** 1.25M words/sec publishing engine that performs automated multi-stage editorial remediation: cross-lingual tokenizer bleed & foreign script removal (Polish `-łεś`, Hebrew, Armenian, Arabic, Ge'ez, Devanagari, Vietnamese words, Latin homoglyphs `k` ➔ `κ`, `pt` ➔ `πτ`, `an` ➔ `αν`, `for` ➔ `φορ`, `ti` ➔ `τι`, `Ta` ➔ `Τα`), code leak purge (`iterrows` ➔ `ίσως`), foreign word elimination (`podría` ➔ `μπορούσε`, `στην hull του` ➔ `στο κύτος του`, `Gang` ➔ `Συμμορία`), comedic calque & false friend fixes (`κατινιάσει τα πέταλα` ➔ `τινάξει τα πέταλα`, `άλωσε το πληκτρολόγιο` ➔ `άρπαξε το πληκτρολόγιο`, `αλόγους της Παναγίας` ➔ `αλογάκι της Παναγίας`, `το σκιασμένο πάνθηρα` ➔ `το σκιασμένο πλαίσιο`, `για ζήση` ➔ `για βιοπορισμό`, `να το λείψω` ➔ `να ζήσω χωρίς αυτό`, `ανθρωπάκια της κάψουλας` ➔ `άνθρωποι των λοβών`, `Είναι μια παρθένη, Σουζ` ➔ `Είναι μια παραίσθηση, Σουζ`), OCR/MT double accent cleanup (`σκύλί` ➔ `σκυλί`) while strictly preserving legitimate Greek enclitics (`το όνομά μου`, `κάνοντάς τα`), machine translation stutter elimination (`ο Σπίντελ ο Σπίντελ` ➔ `ο Σπίντελ`), translated URL restoration, standard Greek publishing quotes (`«...»`), dialogue em-dashes (`—`), and the modern Greek Rule of Final 'ν' (`δε/δεν`, `μη/μην`).
* **Final Output Refinement & Quality-Control Stage (`backend/output_refiner.py`):** Independent, local-only (no API calls) stage invoked as the last step of `main._run_translation()` (after export, before `status="done"`) and `tts_engine.generate_audiobook()` (after assembly, before the `tts_tmp_*` chunk directory is removed). Each hook is wrapped in its own `try/except`: a failure is logged with traceback and the original output is kept; the job still completes. **Translations:** `refine_text_content()` applies conservative deterministic fixes (function-word stutters, accented monosyllables, final-ν, hyphenation, punctuation spacing, blank lines, three unambiguous calques). Ambiguous patterns are reported only. Layout-aware: `poetry`, `preserve` and `comic` skip whitespace changes; French-family targets keep the space before `; : ! ?`. Safety guards revert on page-marker change, paragraph-count change or >10% length drift. `refine_translation_output()` writes via `mkstemp` + `os.replace` (staging names end in `.refine-tmp`, never `.txt`). It re-exports PDF/DOCX/EPUB into a staging directory first, swaps the document after the text, and rolls the text back if the document swap fails. Flows that preserve formatting (comic, in-place DOCX/EPUB) pass `allow_reexport=False` and are inspection-only (`status="inspected"`). **Audiobooks:** `refine_audiobook_output_async()` checks the header (MP3-in-M4B fallback without ffmpeg accepted), mutagen duration, truncation (final size ≥ Σ chunk sizes) and section continuity against `expected_indices` (segments whose cleaned text is empty are excluded). It re-synthesises up to `MAX_AUDIO_HEAL_CHUNKS = 25` failed sections through the existing `_tts_chunk_with_retry`, re-assembles with the existing concat/M4B exporter into a staging file, validates it, then atomically replaces the original. ID3 tags are written only when `TIT2` is missing. **Configuration:** setting `final_refinement_enabled` (default `true`, `GET/POST /api/settings`), env var `FINAL_REFINEMENT_ENABLED` (takes precedence over the setting), and per-request `final_refinement` on `/api/translate`, `/api/audiobook` and `/api/polish`. Queue items follow the global setting. The UI shows the toggle only in Advanced Mode; the stage stays active by default in Basic Mode. **Result:** a compact `refinement_report` (status, corrections, issues, missing sections) is persisted in the job metadata and exposed via `GET /api/status/{job_id}` and SSE.

* **Book Insights (`backend/book_insights.py`):** Summaries, synopses and their audio, built only on existing services.
  * **Reused services:** `parsers.parse_document` for extraction (cached per path and mtime, run with `asyncio.to_thread`); `ai_polisher._call_gemini_api` for generation (key pool rotation, `GeminiRateLimiter`, quota circuit breaker, SQLite `gemini_polish_v4` cache, `sanitize_ai_output`); `output_refiner.refine_text_content` to post-edit Greek; `exporter.export_text` for PDF/TXT, plus python-docx headings and bullets for DOCX; the `tts_engine` chunk helpers for audio (`split_into_chunks`, `_tts_chunk_with_retry`, `_concatenate_mp3s`, `tag_audiobook_file`), validated by `output_refiner.inspect_audiobook_quality`.
  * **Job isolation:** `generate_audiobook()` is deliberately **not** used because it updates job state. Results are stored under `temp/outputs/<job_id>/insights/` (`<type>_<lang>.json` plus exports and MP3), a sub-folder the translation download fallback and the queue ZIP bundler never read. Deleting a job removes its insights.
  * **Eligibility:** meaningful words exclude page-number lines, URLs and short repeated non-sentence lines (running headers). `WORDS_PER_PAGE = 250`, `MIN_SYNOPSIS_WORDS = 375` (1.5 pages), `MIN_SUMMARY_WORDS = 80`. Ineligible requests are rejected with HTTP 422 before any API call.
  * **Targets:** 20–40, 150–300, 500–1,000, 800–1,200 and 1,500–2,500 words, capped by a source-length ratio (0.35/0.5/0.6/0.85) for short documents.
  * **Language:** `detect_language()` returns `greek` / `english` / `other` / `None`. Basic Mode writes in the source language (`other` makes the model write in the source language; `None` returns HTTP 422).
  * **Long documents:** above `SINGLE_PASS_CHARS = 90,000` characters the text is split into ~45k-character sections. Each section is condensed into notes in the source language (2 concurrent calls, cached and shared across types and languages). The notes are condensed again above 120k characters.
  * **Quality gate (`validate_output`):** critical checks cover:
    * wrong language, or more than 4% Latin-script words in Greek outside «quotes»;
    * leaked prompt text;
    * a one-sentence summary that isn't exactly one sentence of 15–50 words;
    * length below 60% or above 180% of the target, or above 90% of the source;
    * two or more unknown numbers of three or more digits;
    * more than three capitalised names absent from the source (same-language outputs only);
    * shingle similarity above 0.6 with the paired summary or synopsis.

    One regeneration is made with the rejection reasons and `bypass_cache=True`. Output that still fails is never stored or shown (`ai_output_rejected`). Greek output also gets one proofreading call (temperature 0.1), kept only if heading count and length (±15%) are preserved.
  * **Tasks:** in-memory background tasks. Identical in-flight requests (job, action, type, language) return the same `task_id` (`duplicate: true`). At most 2 generations run at once. Stored results are reused when the source hash and `INSIGHTS_VERSION` match. Errors carry a stable `code` and a Greek user message: `insufficient_text`, `too_short`, `unsupported_format`, `extraction_failed`, `language_detection_failed`, `no_api_key`, `quota_exhausted`, `rate_limited`, `auth_failed`, `network_error`, `ai_failed`, `ai_output_rejected`, `audio_failed`, `export_failed`.
  * **Audio:** narrates `speech_text(final_text)`, which only strips Markdown markers. Any failed chunk fails the task, so the audio never silently skips text. The MP3 is invalidated when the text is regenerated.
* **Prompt library (`backend/translation_prompts.py`, `PROMPT_VERSION = "2026.11-q2"`):** single source for every Gemini text prompt.
  * **Shared blocks:** `GREEK_QUALITY_RULES` (fidelity and anti-embellishment; the English→Greek fault checklist covering pro-drop subjects, possessives, indefinite article, `ο οποίος`/participle chains, passive voice, false friends, idioms and tense; Greek typography with sentence-case titles, unaccented ALL-CAPS, `;` `·` `…` and «» with nested “”; book-wide consistency) and `ENGLISH_QUALITY_RULES`.
  * **`STYLE_PROMPTS`:** re-exported by `ai_polisher` for compatibility. Contains the literature/natural/formal/technical polish prompts (source text is the authority; minimal necessary intervention), `audiobook` (no paraphrasing; spoken forms in the correct case; Roman numerals, times, ordinals, symbols; ALL-CAPS emphasis lowered; follows the pronunciation register) and `poetry`.
  * **`build_polish_prompt(style, target_lang)`:** English targets get `ENGLISH_POLISH_PROMPT`.
  * **`build_direct_translation_prompt(source, target, style)`:** a dedicated translate-from-source prompt with a genre layer. It replaces the former polish-prompt wrapper.
  * **`build_dossier_prompt(target, mode)`:** `translation` returns the name/term register plus a **style sheet** (genre/tone, narrative person and tense, register, εσύ/εσείς per character pair, recurring phrases), target-aware. `pronunciation` returns a fixed phonetic register, used by `polish_text_with_gemini` for Greek `audiobook`/`poetry` scripts longer than 18k characters that contain Latin-script words. `dossier_header()` gives the matching injection headers.
* **Single-pass translation checkpoint:** `.direct_ai_checkpoint.json` now stores `sig = sha256(PROMPT_VERSION, style, languages, source length, first 2,000 chars)`. A checkpoint with a different signature is discarded, so a run interrupted and restarted with another language or style no longer mixes stale batches in. Unsigned legacy checkpoints are still resumed.
* **Output hygiene:** `sanitize_ai_output()` applies Unicode NFC (polytonic-block or decomposed accents become monotonic code points). Stage 1 of the output refiner restores accents dropped from about 50 high-frequency capitalised words (`Ηταν` → `Ήταν`, `Οταν` → `Όταν`) and applies final-ν to the article/pronoun `τη(ν)`/`στη(ν)` before vowels and κ π τ ξ ψ μπ ντ γκ τσ τζ. The unaccented forms aren't valid words, and ALL-CAPS text is left alone.
* **Maximum-quality revision (`ai_polisher.revise_translation_against_source`, `translation_prompts.build_revision_prompt`):** optional second pass for AI translations.
  * **Enabling:** `TranslateRequest.max_quality`, stored as `Job.max_quality`. Queue items always use `false`; the UI sends it only from Advanced Mode, after a cost warning.
  * **When it runs:** in `main._run_translation`, inside the AI-translation branch (`ai_polish` and a key), after `translate_and_polish_direct_with_gemini` and **before export**, via `_run_max_quality_revision()`. Otherwise `revision_report = {"status": "skipped", "reason": "requires_ai_polish_and_key"}`.
  * **How:** it reuses `polish_text_with_gemini` (page-aligned source anchoring with `<stem>_original.txt`, dossier, checkpoints, per-batch quality gates, bisection) through the new `system_prompt_override` and `temperature_override` (0.15) parameters, with the reviser prompt.
  * **Models:** `_FULL_MODELS_ONLY` (a `contextvars.ContextVar`) restricts `_call_gemini_api` to non-Lite, non-Gemma Flash/Pro models, and adds a `:full` suffix to the cache key. If no full model is available, a `DailyQuotaExhaustedError` is raised and recorded as `reason="quota_exhausted"`.
  * **Acceptance, page by page (`merge_revised_pages`):** a page takes its revision when the revision returned that page exactly once and plausibly (0.6–1.6× the length for pages of 200+ characters, and no truncation or language change per `_answer_problem`); any other page keeps the first pass. Formerly any difference in the page markers (such as an empty duplicate marker left at a split page's seam) threw the whole revision away as `page_markers_changed`. If no page qualifies, `reason="revision_unusable"`. The merged text must then keep a length ratio of 0.8–1.25; whitespace-only differences count as `verified_clean`; the file is replaced atomically via a `.revision-tmp` file.
  * **Report:** `revision_report = {status: revised|verified_clean|skipped|error, reason, changed_lines, similarity, duration_s, kept_pages, kept_page_list}`, persisted in job metadata and exposed via `GET /api/status/{job_id}` and SSE. An error or kept pages also go into the job's final message (`main._revision_notes`), not only into the end-of-job notification.
  * **Duration:** very slow, about 3–8 s per page on top of the first pass (batches of ≤3 pages / 5,500 characters, 5 at a time, full models only). The UI warning (`onMaxQualityToggle`, `revisionMinutes`) estimates it from the page count and names the request count when it exceeds a free key's daily allowance (~20 per model). While it runs, `current_step` shows the parts done and the time left from the pace so far (`main._revision_time_left`; on resume the parts restored from the checkpoint are not counted as speed). The progress card's own time left (`estimateTimeLeft` in `app.js`) uses the pace over the last 5 minutes from what the page first sees, and only says `+ the 2nd AI pass afterwards` (the live updates carry `max_quality`).
* **Format-preserving AI translation (`backend/ai_segment_translator.py` + `format_preserver`):** when AI Polish and a key are used for DOCX→DOCX or EPUB→EPUB, `format_preserver` collects units in document order. Units are paragraphs, or individual runs for mixed bold/italic paragraphs (DOCX), or text nodes (EPUB). Gemini translates them in numbered batches (`⟦n⟧ text`, ~4,000 characters / 60 segments) with the direct-translation prompt, dossier (>18k characters) and glossary, and the result is written back in place. Missing or duplicated segments are retried in halves, then fall back to the free engine individually. A quota error falls back or propagates per `quota_behavior`. Maximum quality is not applied to these outputs (`revision_report.reason = format_preserved_output`).
* **User accounts (`backend/auth.py`, `backend/request_context.py`, `backend/api/auth.py`):** optional (`BOOKAPP_AUTH=1`). The `account_login_guard` middleware resolves the session cookie, redirects pages to `/login` or `/setup`, refuses administrator-only endpoints to users and answers 404 for another user's job id in a URL. Besides the sign-in pages, only `auth.OPEN_PATHS` is reachable without a session: health, the auth API, and the app's icons and manifest (`/favicon.ico`, `/icon.svg`, `/icon-32.png`, `/icon-192.png`, `/icon-512.png`, `/apple-touch-icon.png`, `/manifest.json`), so the sign-in tab and a phone's home-screen shortcut show the icon. Jobs carry an `owner` (stored in the job metadata; empty = administrators' jobs from before accounts); `get_job()` and `list_jobs()` hide other users' jobs, so endpoints taking a `job_id` in the body answer 404 too. The batch queue processor runs in a fresh context (it serves every user) and acts as each item's owner while running it. Gemini usage is also counted per user (`get_daily_gemini_usage_by_user()`). See [User Accounts & Administrators](#user-accounts--administrators-sign-in).
* **Gemini usage accounting:** `ai_polisher.track_gemini_usage()` opens a context-scoped accumulator around each job, Book Insights task and standalone polish. `record_gemini_usage()` adds `usageMetadata` (and cache hits) per call, including comic Vision calls. The result is stored in `Job.gemini_usage` and exposed via status/SSE; the daily total is in `GET /api/gemini/status` (`usage_today`).
* **Slow-model memory:** a model that times out is moved to the end of the candidate list for `SLOW_MODEL_PENALTY_S = 600` seconds; a success clears it.
* **M4B chapters:** `tts_engine.compute_chapter_marks()` derives chapter start times from the synthesised parts (exporter heading detector; proportional placement inside a part; size-based duration fallback). They're written next to the output as `<name>.chapters.json` and passed to ffmpeg as an FFMETADATA file (`-map_metadata` / `-map_chapters`), both during generation and for on-demand MP3→M4B downloads. The ffmpeg timeout is `300 s + 4 s/MB`. Output is staged and swapped atomically; an unreadable cover is skipped, and any other failure is an error (never MP3 data named `.m4b`).
* **Shared Gemini call (`ai_polisher._call_gemini_api`):** size-aware per-request timeout `45 + len(content)/120` seconds (clamped 45–180; previously a fixed 25 s that pushed long batches onto Lite models), rate-limiter token estimate `≈ (prompt + content chars) / 2` (clamped 500–60,000; previously a constant 1,500), and an optional `cache_gate(output) -> bool` predicate. Without a gate, only outputs passing `detect_greek_output_issues` are cached (unchanged); Book Insights and the dossier extraction pass a non-empty gate so English and short outputs are cached too.
* **What an AI book translation may not leave behind (`ai_polisher`):**
  * **Echoed source prose:** `_answer_problem(..., translating=True)` refuses an answer that copies a run of 25+ plain, mostly lower-case source words unchanged (`_copied_source_prose`; reference lists, names and short quotations stay out). The batch is then split by pages and paragraphs (`_bisect_direct`), and a piece that still fails goes to the free engine. Such answers are never cached. Formerly an echoed page passed after one retry and stayed in English.
  * **Dialogue style:** `detect_greek_output_issues` reports `dialogue_dashes(n)` when an answer writes 3+ dialogue lines with dashes where the source uses quotation marks. The retry is told so (`_quality_retry_hint`, shared with the polish path).
  * **Other alphabets:** `_EXOTIC_SCRIPT_RE` also covers the Hebrew/Arabic presentation forms (U+FB1D–FDFF, U+FE70–FEFC). Greek words still carrying such letters after the batch retries are corrected at the end with one validated request (`repair_mixed_script_words`: only a whole Greek word of similar length replaces a corrupted one). Polytonic letters become monotonic in `sanitize_ai_output` (`to_monotonic`) unless the source is polytonic.
  * **Seams:** an empty `=== PAGE N ===` directly followed by the same marker is dropped (`collapse_empty_duplicate_markers`).
  * **Final message:** after the AI translation (and revision), `main._leftover_notes` → `translation_leftover_notes` lists the pages that still carry source prose (`find_untranslated_pages`, compared with `<stem>_original.txt`) and the words with letters of another alphabet.
* **Interface language (`frontend/i18n.js`, the ΕΛ | EN switch):** loaded in the `<head>` of `index.html` and `login.html` (and open before sign-in). `I18N_PAIRS` lists every interface phrase as `[Greek, English, ...other wordings found in the pages]`; `{name}` marks a changing part and `{#name}` a number-only one (`'▶️ Start Batch Translation ({n} files)'`). A `MutationObserver` switches text nodes and the `title`/`placeholder`/`aria-label`/`alt`/`label` attributes as they appear, so text set later by `app.js` (buttons, toasts, queue rows, `document.title`) needs no code changes; `alert`/`confirm`/`prompt` messages are switched too. Each node remembers its phrase, so a switch back is exact even when two phrases share a wording. Content stays inside `translate="no"` (file names, reader, editor, glossary table, Book Insights result). The choice is kept in `localStorage` (`bookapp_ui_lang`); the default follows the browser language. The server's own messages (`current_step` progress steps, end-of-job notes, job errors, `HTTPException` details) are listed too, so the server stays language-neutral and each viewer sees their language. A placeholder first matches within one sentence; a line of several joined notes (`⚠️ note. note.`, audiobook notices joined by `; `) is then split into sentences and switched piece by piece, only when every piece is known (a `;` there becomes `·` in Greek); only after that may a placeholder span sentences. **New interface or server text needs a pair:** `test_frontend_contracts_and_ui.py` fails on any Greek word or English phrase in the pages without one.
* **Help window (`#help-modal` in `index.html`):** the guide and FAQ are written twice, in a `<section class="help-lang" lang="el" translate="no">` and a `lang="en"` one; `style.css` shows the one matching `html[lang]` (set by `i18n.js`), so long prose needs no phrase pairs. Keep both blocks with the same questions (`test_14` checks the counts).
* **Theme (`frontend/theme.js`, loaded in the `<head>` of both pages and open before sign-in):** light between sunrise and sunset, dark otherwise, from the standard solar equations for the date (Athens for `Europe/Athens`, Nicosia for Cyprus, elsewhere the longitude of the standard time offset). The theme button stores `{theme, until}` in `localStorage` (`bookapp_theme_choice`) until the next sunrise or sunset; the former lasting `bookapp_theme` is removed. It re-checks every minute and when the tab becomes visible.
* **Scanned books (`backend/scan_reader.py`):** a scanned PDF (`detect_is_graphic_novel` → `is_scanned`) is a book or a comic.
  * **Choice:** on upload `guess_scanned_book()` renders up to 6 interior pages at 40 dpi; pages of print (mean saturation < 0.2, > 55% light pixels, < 10% dark) on 60% of them, and no comic word in the file name, make a book. `/api/upload` returns `scan_kind: "book" | "comic" | ""` (and `is_comic: false` for a book) and stores `Job.scanned` and `Job.read_scanned_text`. The card's Book / Comic choice is sent as `TranslateRequest.read_scanned_text`; the Comic layout always wins. Queue items read the text when `is_scanned` and not `is_comic`.
  * **Reading:** `read_scanned_text()` sends every page whose image covers the page (`comic_translator._is_image_page`) to `ai_polisher._call_gemini_api` with the page as an inline JPEG (`image=`, ~1,600 px long side) and `prefer_models=LIGHT_MODELS_FIRST` (Flash-Lite first: easy work, large daily allowance). 3 pages at a time; the answer gets `clean_transcription()` only (code fences and special tokens), not the translation sanitiser; `[NO TEXT]` means an empty page. A page with real text keeps its own text. Answers are cached by the image's SHA-256, so a page never costs twice.
  * **Storage:** `<upload>.scantext.json` next to the uploaded file (`{version, source_size, total, pages, complete, blocked}`, written atomically every 10 pages / 15 s and at the end; ignored when the file's size differs). `parsers.parse_pdf` yields these pages whenever any were read, so translation, audiobooks, Book Insights, the editor's original and the estimate need no changes of their own. Deleting the job removes it with the upload folder.
  * **Where it runs:** `main._read_scanned_book()` before the translation of a scanned book (only the sample's pages plus two for a sample), before an audiobook of a scanned PDF that is not fully read, and inside the Book Insights generate task (`needs_scan_reading` and `scan_pages` in `/analysis`; the length and language checks run after the reading). A refused page (`_ContentBlockedError`) stays empty and is listed in `blocked`; other failures raise `ScanReadError` naming the pages, after the others are saved; quota and auth errors propagate like any Gemini work (Wait for Reset, resume).
* **Sample translations (`TranslateRequest.page_from` / `page_to`, `Job.sample_range`):** `_requested_sample()` validates the range against the document's page count (HTTP 400 past the end or reversed). The AI path (`translate_and_polish_direct_with_gemini(page_range=)`) groups the whole book into its usual batches and translates only those holding the chosen pages, with the whole book's dossier and glossary, and keeps `.direct_ai_checkpoint.json`, so the whole book later skips those batches (same signature). The free engine (`translate_document(page_range=)`) and comics (`translate_comic_document(page_range=)`, only those pages in the PDF, page numbers kept) reuse through the caches. A sample never takes the in-place DOCX/EPUB paths. `sample_range` is then the pages actually done; `total_pages` returns to the document's count when the job ends; the final step ends with `· 🧪 Sample: pages a–b`; downloads are named `<name>_sample_pa-b.<ext>`. A plain start (no range) clears it; the UI's Resume repeats the sample.
* **Request estimate (`GET /api/translate/estimate/{job_id}`, `main._estimate_requests`):** query `ai_polish`, `max_quality`, `layout_mode`, `output_format`, `read_scanned_text`, `page_from`, `page_to`. Returns `requests: {read, translate, revise}`, `total`, `pages`, `sample`, `comic`, `scanned`, `has_key`, `keys`, `best_model`, `best_per_day`, `light_per_day`, `best_days`. Translation batches follow the AI path's grouping (≤3 pages / 5,500 characters, from `_page_lengths()`, cached per file version), +1 for the dossier of texts over 18,000 characters; in-place DOCX/EPUB count ~3,800 characters per request; comics one request per page; unread scanned pages count 1,800 characters. `best_per_day` = keys × the best model's daily limit (`gemini_key_pool.model_daily_limit`): the defaults in `DEFAULT_MODEL_RPD`, replaced by the `quotaValue` of Google's 429 answers (`record_model_daily_limit`, from `_call_gemini_api` and the comic Vision calls).
* **Bilingual edition (`backend/bilingual.py`, `GET /api/download/{job_id}/bilingual?format=pdf|docx|epub`):** the original (`<stem>_original.txt`, else the parsed source) and the current translation are split on page markers (both the `=== PAGE N ===` and the free engine's three-line form) and matched page by page, then paragraph by paragraph with a Gale & Church length alignment (`align`: 1–1, 1–2, 2–1, 1–3, 3–1 and unmatched paragraphs, cost from the log length ratio). Without shared markers (format-preserved DOCX/EPUB) the whole text is aligned within ±80 paragraphs of the diagonal. PDF: MuPDF `Story` HTML on A5 with an installed serif face that has the whole Greek alphabet (Times New Roman, Georgia, DejaVu Serif, Liberation Serif), page numbers, and `pdf_text_names.fix_text_names` so copied spaces are not no-break spaces; DOCX: python-docx; EPUB: ebooklib, 120 passages per file. Files are kept in `outputs/{job_id}/bilingual/` (apart from the job's own outputs) and rebuilt when the translation or original is newer. Comics: 400; untranslated: 404; running: 409.
* **Devices (`backend/connections.py`, `backend/api/connections.py`, `backend/notify.py`):** per user (`""` with accounts off), stored in `data/connections.json`.
  * **E-reader catalogue (OPDS 1.2):** `POST /api/connections/opds` makes a secret link `/opds/<token>/` (`secrets.token_urlsafe(24)`; only its SHA-256 is stored, so it is shown once and a new one replaces it; `DELETE` removes it). `/opds/` is an open path for sign-in and device pairing (`auth.is_open_path`, `device_pairing.is_open_path`): the token is the pass, since reading apps cannot sign in. The router opens the request as the token's user (job visibility as in the app; a link made while accounts were off, or of a disabled or deleted account, gives 404). The Atom acquisition feed lists the user's finished translations (newest 300) with cover links; `/opds/<token>/book/{job_id}/{epub|pdf|bilingual-epub|cbz}` and `/cover/{job_id}` reuse `download_output`, `download_bilingual` and `get_cover_image`. Unknown tokens, other formats and other users' jobs: 404.
  * **Phone notifications (ntfy):** `POST /api/connections/ntfy {server, topic, app_url, lang}` (topic `[A-Za-z0-9_-]{6,64}`, http(s) server without credentials or query; an empty topic turns them off), `POST /api/connections/ntfy/test`. `job_manager.update_job` calls `notify.job_finished` when a `translate` or `audiobook` job goes from `running` to `done` or `error`; it publishes JSON (`{topic, title, message, priority, click}`) to the server from a daemon thread (10 s timeout; failures are only logged). Messages carry the file name and outcome only, in the language saved with the settings. **The server needs outbound HTTPS to `ntfy.sh`** (or your ntfy server) for this.
* **Reading along (`tts_engine.compute_read_along`, `GET /api/jobs/{job_id}/read-along`):** after an audiobook is assembled (and any re-narrated parts healed), each part's duration is measured (mutagen, else from its size at 48 kbit/s) and its sentences share it by length plus a 12-character pause; a sentence ends at `. ! ? … ; » "` unless the next word is lowercase. Saved as `<audiobook>.sync.json` (`{version, segments: [{s, e, t, p}]}`); the endpoint serves the file of the newest MP3 (else M4B) and nothing when the times are older than that recording. The player's 📖 panel binary-searches the start times on `timeupdate`.
* **Contents page in the Literature layout (`exporter._prepare_literature_chapters`, `_contents_page`):** a page of 3+ titles each followed by a page number (on its own line or at the line's end, rising) becomes a contents chapter (`"toc": True`, titled Περιεχόμενα/Contents) without the original edition's numbers. The same titles standing alone on later pages open chapters. `_export_literature_pdf` prints each entry's page in the new PDF (as the footers count it) and writes bookmarks for every titled chapter (`doc.set_toc`). DOCX and EPUB show the entries as a plain list.
* **Multi-Key Gemini API Pool & Failover Manager (`backend/gemini_key_pool.py`):** Manages up to **8 free Google Gemini API Keys** (`MAX_KEYS`) simultaneously across different Google accounts (each key adds Google's free allowance, which is set per model and per day and can be small, e.g. 20 requests/day for `gemini-3.5-flash`). Features sliding-window rate limiting (`GeminiRateLimiter` tracking RPM/TPM and smoothing request pacing), explicit Retry-After support, intelligent error payload classification (`parse_gemini_error`), per-model quota cooldown isolation (`_MODEL_COOLDOWNS`: a model whose daily allowance is used up does not block the other models on the same key), seamless key rotation upon HTTP 429 daily exhaustion, requests taking the keys in turn (`GeminiKeyPool.next_key`, so parallel batches add up every key's RPM and daily allowance), the strongest model on every key before a weaker one (`key_for_better_model`: a request whose best model reached its limit on this key moves to a key that still has it, both in `ai_polisher._call_gemini_api` and the comic Vision calls), model lists cached per key (`_MODELS_BY_KEY`), an overloaded model (HTTP 5xx) tried last for 2 minutes (`OVERLOADED_MODEL_PENALTY_S`), transient burst backoff (`retryDelay <= 60s`), thread-safe per-key cooldown timers, automatic circuit breaker reset when cooldowns expire or new keys are saved, and live status endpoints (`GET/POST /api/gemini/pool`).
* **Categorized Terminology Engine (`backend/translator.py`, `config/glossary.json`):** High-speed terminology substitution engine with **3,366+ preconfigured terms** across Technical (1,130), Literary (1,032), and General (1,204) categories. Implements idempotent single-pass placeholder replacement, regex backslash safety, symbol-safe word boundaries, automatic domain isolation (excluding IT/DevOps terms in literary, comic, and poetry modes), and live CRUD REST endpoints (`GET/POST /api/glossary`). In a finished Greek translation (`apply_glossary(..., translated=True)`), an English term inside a Greek sentence is not replaced: its Greek translation follows it once per document, in parentheses (one `explained` set per document).
* **Test Isolation (`run_all_tests.py`, `tests/_sandbox_guard.py`):** The runner copies the code to a temporary folder and runs the suites there on a free port, with an empty database and without keys, then deletes the copy. Test files exit immediately outside it. Name-based test-job detection and purge (`is_test_job_identifier`, `cleanup_test_jobs`) only work when `BOOKAPP_TEST_MODE=1`, which the sandbox sets. **Never set it on a real installation:** there, a file called `Bookkeeping.pdf` would count as test junk.
* **Format-preserved outputs (`backend/format_sync.py`):**
  * **Marker:** the pipeline records how each output was made in `.format_preserved.json` in the job's output folder. Older jobs without a marker are detected conservatively.
  * **Edits:** Editor and AI Polish changes are mapped onto the document's text nodes and written atomically with the text. If an edit can't be placed safely, or the file is locked, the API returns **HTTP 409** and changes nothing.
  * **Never rebuilt:** cover changes, layout downloads and refinement leave these files as they are.
  * **Limits:** EPUB table-of-contents entries and DOCX hyperlink text are not edited in the document; for comics only the text copy changes.

---

## 2. System Prerequisites

### Operating System
* **Windows:** Windows 10, Windows 11, or Windows Server 2016/2019/2022.
* **Linux:** Ubuntu 20.04+, Debian 11+, RHEL/CentOS 8+, AlmaLinux/Rocky Linux.
* **macOS:** macOS 11 Big Sur or newer.

### Software Requirements
* **Python 3.11 through 3.15** with `pip` and `venv`.
* **Git** (for cloning and pulling updates).
* **FFmpeg** (needed for M4B): installed automatically with the `imageio-ffmpeg` dependency; an FFmpeg on `PATH` takes precedence.
* **Linux without Docker:** install `libarchive-tools` (bsdtar reads `.cbr` uploads) and fonts with Greek and italic faces, e.g. `fonts-dejavu-core fonts-dejavu-extra fonts-liberation`. Without an italic face, PDF italics are drawn by leaning the regular face.

### Network & Firewall Rules
* **Inbound:** Port `8000` by default (any port with `BOOKAPP_PORT` in Docker or `--port` without Docker), or `80`/`443` behind a reverse proxy.
* **Outbound Internet Access:**
  * `translate.googleapis.com:443` (HTTPS) for translation services.
  * `*.speech.microsoft.com:443` (WSS / HTTPS) for Microsoft Edge neural voice synthesis.
  * `generativelanguage.googleapis.com:443` (HTTPS) when using Google Gemini API keys.
  * `ntfy.sh:443` (HTTPS), or your own ntfy server, when users turn on phone notifications (📲 Devices).
* **E-readers:** reading apps open the OPDS catalogue on the same port as the browser (`/opds/<token>/`); behind a reverse proxy nothing extra is needed.

### Configuration & Security Notes
* **Environment variables:**
  * `GEMINI_API_KEY`: optional; seeds the key pool.
  * `FINAL_REFINEMENT_ENABLED=true|false`: overrides the Final Output Refinement setting.
  * `BOOKAPP_CORS_ORIGINS="https://a.example,https://b.example"`: extra origins allowed to call the API cross-origin. Normally unnecessary: the UI is served by the same server (same origin), including behind Nginx, on a LAN or in Docker.
* **CORS policy:** only same-origin requests and local development origins (`http(s)://localhost`, `127.0.0.1` and `[::1]`, any port) receive CORS permission. Other websites open in the user's browser cannot read API responses, such as `/api/settings`, which contains the Gemini keys. They also cannot send JSON or DELETE requests to the app.
* **Input validation:** `output_format`, `layout_mode`, `reading_direction` and `quota_behavior` accept only known values, and languages only plain words (they become part of file names); anything else is HTTP 400.
* **Network exposure:** without user accounts the app is single-user. `run.py` and `start_bookapp.bat` bind to `127.0.0.1`. The Docker image binds to `0.0.0.0`, so on a LAN anyone who can reach port 8000 can use the app. For a server shared by several people, switch on **user accounts** (`BOOKAPP_AUTH=1`, see [User Accounts & Administrators](#user-accounts--administrators-sign-in)) and serve it over HTTPS. For one person on a home network, device pairing (below) is enough.
* **`BOOKAPP_AUTH=1`:** user accounts with administrators (sign-in required). It replaces device pairing: `BOOKAPP_PAIRING` is ignored while it is on.
* **Gemini API keys** are stored only in `config/settings.json` on the server. `GET /api/settings` returns masked forms (`AIzaSy...4f2D`), and the browser never stores keys. `GeminiKeyPool.set_keys` and `resolve_gemini_api_key` map masked values back to the stored keys, and drop unknown masked values.
* **Device pairing (optional, no password; single user):**
  * **Enabling:** set `BOOKAPP_PAIRING=1`. Only trusted clients can use the app: the host computer (loopback) and paired devices. Unpaired clients get HTTP 403 (a JSON message for `/api/*`, an explanatory page otherwise). `/api/health` stays open for health checks.
  * **First device:** at startup the server logs a one-time link `http://<this-computer>:8000/pair?code=...`, valid 15 minutes and single use. Opening it sets a 1-year HttpOnly, SameSite=Lax cookie.
  * **More devices:** create links from any trusted device in **🔑 Gemini API Key → 📱 Συσκευές**, which also lists devices and lets you revoke them.
  * **Storage:** only SHA-256 hashes of device tokens are stored (`paired_devices` in settings).
  * **Reverse proxy on the same machine:** set `BOOKAPP_TRUST_LOOPBACK=0`, otherwise every proxied request looks like the host.
  * **Endpoints:** `GET /pair`, `GET /api/pairing`, `POST /api/pairing/links`, `DELETE /api/pairing/devices/{id}`.


---

## 3. Step-by-Step Installation

Pick the guide that matches the machine BookApp will run on. Copy the commands as they are; replace only values written in `<angle brackets>`.

| Where BookApp runs | Guide | Command line | Updating |
|---|---|---|---|
| **Ubuntu server with Docker** (recommended for servers) | [3.1](#31-ubuntu-server-with-docker) | SSH | `git pull` + one command |
| **Synology NAS** (Docker via Container Manager) | [3.2](#32-synology-nas-with-docker-container-manager) | none (Method A) or SSH (Method B) | upload new files, or `git pull` |
| **Ubuntu server without Docker** (Python + systemd) | [3.3](#33-ubuntu-server-without-docker-python--systemd) | SSH | `git pull` + restart |
| **Your own Windows or macOS computer** (one person) | [3.5](#35-windows-or-macos-computer-one-person) | a few commands | `git pull` |

After a server installation, continue with [3.4 First Sign-In](#34-first-sign-in-every-server-installation).

**Values used in the guides**
* `<server-ip>`: the server's address on your network, for example `10.9.251.250`. On Ubuntu, `hostname -I` prints it (the first value). On Synology: **Control Panel → Network → Network Interface**.
* **Port:** the examples use `8000`. Any free port from 1024 up works, for example `2000`; the guides say where to change it. People then open `http://<server-ip>:2000`. The server's IP address is never written in any BookApp file: the app answers on every address of the machine.
* **Install folder:** `/opt/BookApp` on Ubuntu, `/volume1/docker/bookapp` on Synology.

### 3.1 Ubuntu Server with Docker

For Ubuntu 22.04 or 24.04 LTS (20.04 works the same way). You need SSH access (`ssh <your-user>@<server-ip>`) with an account that may use `sudo`. Docker brings Python, FFmpeg and the fonts with it: nothing else is installed on the server.

**Step 1. Install Docker Engine and Docker Compose.** Skip this step if `docker compose version` already prints `Docker Compose version v2…`.
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
These are the commands of Docker's official repository ([docs.docker.com/engine/install/ubuntu](https://docs.docker.com/engine/install/ubuntu/)). If Ubuntu's own `docker.io` package is already installed and works, keep it and skip this step. Don't install both.

**Step 2. Let your account run Docker without `sudo`**, then sign out:
```bash
sudo usermod -aG docker $USER
exit
```
Connect with SSH again and check:
```bash
docker compose version          # Docker Compose version v2.x
docker run --rm hello-world     # prints "Hello from Docker!"
```
Members of the `docker` group have root-level control of the server: add only administrators. Without this step, write `sudo` before every `docker` command below.

**Step 3. Download BookApp**
```bash
sudo mkdir -p /opt/BookApp
sudo chown "$USER": /opt/BookApp
git clone https://github.com/kotsimp/BookApp.git /opt/BookApp
cd /opt/BookApp
```

**Step 4. Write the server settings** in `/opt/BookApp/.env`. Docker Compose reads this file automatically, and git ignores it, so updates never overwrite it. To use port 2000, write `BOOKAPP_PORT=2000`:
```bash
cat > .env <<'EOF'
BOOKAPP_PORT=8000
BOOKAPP_AUTH=1
EOF
cat .env
```
`BOOKAPP_AUTH=1` turns on sign-in with user accounts. The other variables are listed in [Option C](#option-c-docker--docker-compose). To change the file later, use `nano .env`: Ctrl+O and Enter save, Ctrl+X exits.

**Step 5. Build and start**
```bash
docker compose up -d --build
```
The first build downloads Python, FFmpeg and the fonts and takes about 3–10 minutes. Later starts take seconds. The container starts again by itself after a reboot (`restart: unless-stopped`).

**Step 6. Check that it runs.** Write your port in place of 8000:
```bash
docker compose ps                          # STATUS: "Up … (healthy)" after about 30 seconds
curl -s http://localhost:8000/api/health   # {"status":"ok","message":"DocTranslate is running"}
```

**Step 7. Firewall.** Docker opens the published port in the firewall itself, bypassing `ufw`. Every computer that can reach the server can reach the port, whatever `ufw` says. That is why `BOOKAPP_AUTH=1` matters. On a cloud server (AWS, Azure, Hetzner and so on), also allow the port in the provider's firewall or security group.

**Step 8. Read the setup code** for the first administrator:
```bash
docker logs bookapp 2>&1 | grep -i "setup code"
```
It prints a line such as `and enter the setup code:   7K3F-9QXM`. The same code is in `sudo cat /opt/BookApp/data/setup_code.txt`. The log always mentions port 8000, which is the port inside the container. In the browser, use your own port: `http://<server-ip>:8000/setup`. Continue with [3.4 First Sign-In](#34-first-sign-in-every-server-installation).

**Everyday commands** (run them in `/opt/BookApp`)

| Task | Command |
|---|---|
| Watch the log live (Ctrl+C stops watching, not the app) | `docker logs -f bookapp` |
| Last 200 log lines | `docker logs --tail 200 bookapp` |
| Restart | `docker compose restart` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Apply a changed `.env` (port, sign-in) | `docker compose up -d` |
| Account tool (here: list users) | `docker exec -it bookapp python -m backend.auth list-users` |

**Update to a new version**
```bash
cd /opt/BookApp
git pull
docker compose up -d --build
docker image prune -f        # removes the previous, now unused image
```
Users, jobs, books, settings and API keys are kept.

**Back up and restore**
```bash
cd /opt/BookApp
docker compose stop
sudo tar czf ~/bookapp-backup-$(date +%F).tar.gz data config temp .env
docker compose start
```
* **What the backup holds:**
  * `data` holds the job database and the user accounts.
  * `config` holds the settings, the API keys and the glossary.
  * `temp` holds the uploaded books and the results.
* **Keep it private:** the file contains your API keys and the password hashes.
* **Restore on a new server:**
  1. Follow Steps 1–3.
  2. Run `sudo tar xzf ~/bookapp-backup-<date>.tar.gz -C /opt/BookApp`.
  3. Run `docker compose up -d --build`.

**Uninstall**
```bash
cd /opt/BookApp
docker compose down
docker image rm bookapp:latest
sudo rm -rf /opt/BookApp       # deletes every book, user and setting: back up first
```

**Troubleshooting**

| Message or symptom | What to do |
|---|---|
| `permission denied while trying to connect to the Docker daemon socket` | Step 2 needs a new SSH sign-in (`exit`, connect again). Or write `sudo` before the command. |
| `compose build requires buildx 0.17 or later` | `sudo apt-get install -y docker-buildx-plugin` (Docker's repository) or `sudo apt-get install -y docker-buildx` (Ubuntu's `docker.io`) |
| `Bind for 0.0.0.0:8000 failed: port is already allocated` | Another program uses the port: `sudo ss -ltnp \| grep :8000` shows which one. Choose another `BOOKAPP_PORT` in `.env`, then `docker compose up -d`. |
| `curl` works on the server, but another computer's browser can't open the page | A firewall or router between them blocks the port, or a cloud security group does. Port 2000 is also used by Cisco IP phones (SCCP), and some Cisco firewalls intercept it. If so, choose another port. |
| `docker compose ps` shows `Restarting` or `unhealthy` | `docker logs --tail 100 bookapp` shows the reason. |
| A comic job says `page(s) left untranslated` | `docker logs bookapp 2>&1 \| grep "left untranslated"` shows each page with its Vision error. A rate limit, an overloaded model or a timeout passes: translate the file again, and only those pages are sent again. |
| A book job says `page(s) still contain text in the original language` | `docker logs bookapp 2>&1 \| grep -E "untranslated\(copied_words\|batch .* failed"` shows the pages the model handed back unchanged and how they were split. Translate the file again: refused answers are never cached, so those pages are really asked again. |
| The app stops answering after an update, a restart or (with `run.py`) a code change | Older versions waited without limit for open pages' progress streams (SSE) to close before stopping. `run.py`, `start_bookapp.bat` and the Docker image now pass `--timeout-graceful-shutdown 5`: after 5 s the streams are closed, running jobs are marked interrupted (resume them), and the pages reconnect. On an older install restart it (`docker compose restart`, or stop and start `run.py`). |
| Some files of a multi-file upload don't upload | The line above the queue lists each one with its reason. `Δεν ήταν δυνατή η αποθήκευση…` names the disk error (`docker logs bookapp 2>&1 \| grep "could not be stored"`): free space under `./temp`, or the folder's permissions. A `413` comes from a file over 250 MB, or from a reverse proxy's body limit (`client_max_body_size 250M;` in nginx). |
| A Maximum-quality job says `The second AI pass … did not complete` | The reason is in brackets (`quota_exhausted`, `revision_unusable`, …) and in `revision_report`; `docker logs bookapp 2>&1 \| grep -i revision` shows it. The exported book is the first-pass translation. |
| `failed to solve: DeadlineExceeded … load metadata for docker.io/library/python:3.11-slim` | Docker Hub didn't answer in time, so the build stopped and the old container keeps running unchanged. Run the command again later. A changed `.env` (port, sign-in) needs no build: `docker compose up -d` applies it with the image you already have. |
| `docker compose ps` still shows the old port (`0.0.0.0:8000->8000/tcp`) after editing `.env` | The container wasn't recreated, usually because the build failed (row above). Run `docker compose up -d`. A `docker-compose.yml` from before 23 Nov 2026 ignores `.env`: run `git pull` first. |
| `grep -i "setup code"` prints nothing | Right after a start the log is still empty: wait 10 seconds and run it again, or read `sudo cat data/setup_code.txt`. Nothing at all means an account already exists, or `BOOKAPP_AUTH=1` isn't active (`docker exec bookapp env \| grep BOOKAPP`). |
| `git pull`: `Your local changes to the following files would be overwritten by merge: config/glossary.json` | That file holds the glossary edited in the app. To keep your version: `cp config/glossary.json ~/glossary-mine.json && git checkout -- config/glossary.json && git pull && cp ~/glossary-mine.json config/glossary.json`, then `docker compose up -d --build`. |

### 3.2 Synology NAS with Docker (Container Manager)

You need DSM 7.2 or newer and a model that supports **Container Manager**: Package Center lists it only for models that do. The image is built on the NAS, so the first build takes about 5–20 minutes.

There are two ways. **Method A** uses only DSM's web pages. **Method B** uses SSH and makes later updates a single command.

#### Method A: Container Manager only (no command line)

**Step 1. Install Container Manager.** In **Package Center**, search for *Container Manager* and click **Install**. It creates the shared folder `docker`.

**Step 2. Download BookApp** on your computer:
1. Open [github.com/kotsimp/BookApp](https://github.com/kotsimp/BookApp).
2. Click the green **Code** button, then **Download ZIP**.

You get the file `BookApp-master.zip`.

**Step 3. Upload and unpack it with File Station**
1. Open the `docker` folder and click **Upload → Upload - Skip**. Choose `BookApp-master.zip`.
2. Right-click the ZIP and choose **Extract → Extract here**.
3. Right-click the new folder `BookApp-master` and choose **Rename**. Name it `bookapp`.
4. Open `bookapp`. Click **Create → Create folder** and make a folder named `data`. Do the same for a folder named `temp`.
5. Delete the ZIP.

You now have `docker/bookapp/docker-compose.yml`, plus the empty folders `docker/bookapp/data` and `docker/bookapp/temp`.

**Step 4. Create the project.** In **Container Manager**, open **Project → Create**:
1. **Project name:** `bookapp`.
2. **Path:** click **Set path** and choose `docker/bookapp`.
3. **Source:** choose **Use existing docker-compose.yml**.
4. In the editor that opens, find these two lines:
   ```yaml
         - "${BOOKAPP_PORT:-8000}:8000"
         - BOOKAPP_AUTH=${BOOKAPP_AUTH:-}
   ```
   Change them to the following:
   ```yaml
         - "8000:8000"
         - BOOKAPP_AUTH=1
   ```
   For port 2000, write `"2000:8000"`. Only the left number is the NAS port; the right one stays 8000.
5. Click **Next**. Leave the *Web Station* web portal option unticked, then click **Next** again.
6. On the summary, tick **Start the project once it is created** and click **Done**. Container Manager builds the image (a log window shows the progress) and starts the container.

**Step 5. Firewall.** Do this only if DSM's firewall is on (**Control Panel → Security → Firewall**):
1. Click **Edit Rules → Create**.
2. Under **Ports**, choose **Custom**. Set protocol **TCP** and port **8000**, or your port.
3. Set **Action** to **Allow**, then click **OK → Apply**.

**Step 6. Read the setup code.** Go to **Container Manager → Container**, double-click `bookapp` and open the **Log** tab. Look for the line `enter the setup code:   XXXX-XXXX`. With File Station, the code is also in `docker/bookapp/data/setup_code.txt`. Then open `http://<nas-ip>:8000/setup` with your own port, and continue with [3.4 First Sign-In](#34-first-sign-in-every-server-installation).

**Update (Method A)**
1. Download the new ZIP. Upload it to `docker` and extract it there, so that `BookApp-master` appears next to `bookapp`.
2. In `bookapp`, delete the folders `backend` and `frontend`.
3. In `BookApp-master`, select `backend`, `frontend`, `Dockerfile` and `requirements.txt`. Use **Action → Copy to** to copy them to `docker/bookapp`, choosing **Overwrite**.
   * **Don't copy** `docker-compose.yml`, `config`, `data` or `temp`. They hold your port setting, API keys, glossary, users and books.
4. Delete `BookApp-master` and the ZIP.
5. In **Container Manager → Project**, select `bookapp` and click **Action → Build**. When the build finishes the project should be running (green). If it isn't, click **Action → Start**.

#### Method B: SSH (updates with one command)

**Step 1. Install the packages.** In **Package Center**, install **Container Manager** (Method A, Step 1) and **Git Server**. Git Server provides the `git` command.

**Step 2. Turn on SSH.** In **Control Panel → Terminal & SNMP**, tick **Enable SSH service** and click **Apply**.

**Step 3. Connect** from your computer with an administrator account of DSM:
```bash
ssh <dsm-admin-user>@<nas-ip>
```

**Step 4. Download BookApp, write the settings and start it.** `/volume1` is the volume of the `docker` shared folder: check it in **Control Panel → Shared Folder**.
```bash
cd /volume1/docker
git clone https://github.com/kotsimp/BookApp.git bookapp
cd bookapp
mkdir -p data temp
cat > .env <<'EOF'
BOOKAPP_PORT=8000
BOOKAPP_AUTH=1
EOF
sudo docker compose up -d --build
```
`sudo` asks for your DSM password. On an older Container Manager that doesn't know `docker compose`, write `sudo docker-compose` instead.

**Step 5. Read the setup code**, then continue with [3.4 First Sign-In](#34-first-sign-in-every-server-installation):
```bash
sudo docker logs bookapp 2>&1 | grep -i "setup code"
```

**Update (Method B)**
```bash
cd /volume1/docker/bookapp
git pull
sudo docker compose up -d --build
sudo docker image prune -f
```
The container appears in **Container Manager → Container** like any other, where you can see its log and stop or start it. The commands of [3.1](#31-ubuntu-server-with-docker) also work, with `sudo` in front. If you don't use SSH otherwise, you can turn it off again after the installation.

**Backup (both methods):** in **Hyper Backup**, add the shared folder `docker/bookapp` (or at least its `data`, `config` and `temp` folders) to a backup task. Schedule it at night, when no translation is running. **HTTPS:** see [HTTPS for User Accounts](#https-for-user-accounts-caddy-nginx-synology-dsm) (DSM reverse proxy).

### 3.3 Ubuntu Server without Docker (Python + systemd)

Ubuntu 24.04 LTS is recommended, because it comes with Python 3.12. Ubuntu 22.04 comes with Python 3.10, so Step 1 adds Python 3.11 there. BookApp runs as its own system user, `bookapp`, from `/opt/BookApp`.

**Step 1. Install the system packages**
```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg libarchive-tools \
  fonts-dejavu-core fonts-dejavu-extra fonts-liberation fontconfig ca-certificates curl
python3 --version
```
* **Python 3.11 or newer:** go on to Step 2.
* **Python 3.10** (Ubuntu 22.04): run `sudo apt install -y python3.11 python3.11-venv`, and write `python3.11` instead of `python3` in Step 3.
* **What the packages are for:**
  * `ffmpeg` makes M4B audiobooks.
  * `libarchive-tools` reads `.cbr` comics.
  * The fonts give PDFs and comic balloons Greek letters and italics.

**Step 2. Create the service account and download BookApp**
```bash
sudo useradd --system --home-dir /opt/BookApp --shell /usr/sbin/nologin bookapp
sudo git clone https://github.com/kotsimp/BookApp.git /opt/BookApp
sudo chown -R bookapp:bookapp /opt/BookApp
```

**Step 3. Create the Python environment and install the dependencies.** This takes 2–5 minutes.
```bash
cd /opt/BookApp
sudo -u bookapp python3 -m venv /opt/BookApp/.venv
sudo -u bookapp /opt/BookApp/.venv/bin/pip install --no-cache-dir --upgrade pip
sudo -u bookapp /opt/BookApp/.venv/bin/pip install --no-cache-dir -r /opt/BookApp/requirements.txt
```

**Step 4. Create and start the service.** The port is set in the `ExecStart` line (`--port 8000`; for example `--port 2000`). Use a port from 1024 up. `BOOKAPP_AUTH=1` turns on sign-in.
```bash
sudo tee /etc/systemd/system/bookapp.service > /dev/null <<'EOF'
[Unit]
Description=BookApp (DocTranslate & AudioBook Generator)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bookapp
Group=bookapp
WorkingDirectory=/opt/BookApp
Environment=PYTHONUNBUFFERED=1
Environment=BOOKAPP_AUTH=1
ExecStart=/opt/BookApp/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now bookapp
systemctl status bookapp --no-pager      # "active (running)"
```

**Step 5. Check that it runs.** Write your port in place of 8000:
```bash
curl -s http://localhost:8000/api/health   # {"status":"ok","message":"DocTranslate is running"}
```

**Step 6. Firewall.** Add the rule only if `ufw` shows `Status: active`:
```bash
sudo ufw status
sudo ufw allow 8000/tcp
```

**Step 7. Read the setup code**, then continue with [3.4 First Sign-In](#34-first-sign-in-every-server-installation):
```bash
sudo journalctl -u bookapp --no-pager | grep -i "setup code"
sudo cat /opt/BookApp/data/setup_code.txt      # the same code
```
The log always says port 8000. If you set another port in `ExecStart`, use that one in the browser.

**Everyday commands**

| Task | Command |
|---|---|
| Watch the log live | `sudo journalctl -u bookapp -f` |
| Restart | `sudo systemctl restart bookapp` |
| Stop / start | `sudo systemctl stop bookapp` / `sudo systemctl start bookapp` |
| Change the port or variables | `sudo systemctl edit --full bookapp`, then `sudo systemctl restart bookapp` (and `sudo ufw allow <new-port>/tcp`) |
| Account tool (here: list users) | `cd /opt/BookApp && sudo -u bookapp .venv/bin/python -m backend.auth list-users` |

**Update to a new version**
```bash
sudo -u bookapp git -C /opt/BookApp pull
sudo -u bookapp /opt/BookApp/.venv/bin/pip install --no-cache-dir -r /opt/BookApp/requirements.txt
sudo systemctl restart bookapp
```

**Back up and restore**
```bash
sudo systemctl stop bookapp
sudo tar czf ~/bookapp-backup-$(date +%F).tar.gz -C /opt/BookApp data config temp
sudo systemctl start bookapp
```
The backup contains your API keys and the password hashes, so keep it private. To restore on a new server:
1. Follow Steps 1–4.
2. Stop the service: `sudo systemctl stop bookapp`.
3. Unpack the backup: `sudo tar xzf ~/bookapp-backup-<date>.tar.gz -C /opt/BookApp`.
4. Give the files back to the service account: `sudo chown -R bookapp:bookapp /opt/BookApp`.
5. Start the service: `sudo systemctl start bookapp`.

**Troubleshooting**

| Message or symptom | What to do |
|---|---|
| `systemctl status` shows `failed` | `sudo journalctl -u bookapp -n 100 --no-pager` shows the reason |
| `ModuleNotFoundError` in the log | Step 3 did not finish: run its last command again, then `sudo systemctl restart bookapp` |
| `address already in use` | Another program uses the port: `sudo ss -ltnp \| grep :8000`. Choose another port (*Change the port* above). |
| `fatal: detected dubious ownership` on `git pull` | Run git as the service account: `sudo -u bookapp git -C /opt/BookApp pull` |
| `git pull` refuses because of `config/glossary.json` | Keep your glossary: `cd /opt/BookApp && sudo -u bookapp cp config/glossary.json /tmp/glossary-mine.json && sudo -u bookapp git checkout -- config/glossary.json && sudo -u bookapp git pull && sudo -u bookapp cp /tmp/glossary-mine.json config/glossary.json && sudo systemctl restart bookapp` |
| M4B export unavailable | `ffmpeg -version` must work; otherwise `sudo apt install -y ffmpeg` and restart |

For HTTPS with Caddy, bind BookApp to the server itself: `--host 127.0.0.1` in `ExecStart`. See [HTTPS for User Accounts](#https-for-user-accounts-caddy-nginx-synology-dsm).

### 3.4 First Sign-In (every server installation)

1. **Create the first administrator.** Open `http://<server-ip>:<port>/setup` and enter the setup code from the guide's last step. Choose a username and a password:
   * the username uses 2–32 Latin letters, digits, `.`, `_` or `-`;
   * the password has at least 10 characters.

   You are now the first administrator. The setup code stops working.
2. **Add the Gemini key.** Click **🔑 Gemini API Key** in the top menu (only administrators see it) and paste up to 8 keys, then save. Without a key, BookApp uses the free translation engines.
3. **Create the other accounts.** Click **👥 Χρήστες** and create an account for each person. Leave the password empty to get a temporary one, which is shown once: give it to that person. Everyone chooses their own password at the first sign-in. **⭐ Κάνε διαχειριστή** gives someone the same rights as you.
4. **Share the address.** Give everyone the address `http://<server-ip>:<port>`.

* **Forgotten administrator password:** use the account tool's `reset-password` command on the server (see [User Accounts & Administrators](#user-accounts--administrators-sign-in)).
* **Plain `http://`:** passwords cross the network unencrypted. That is fine on a trusted local network. If the app can be reached from the internet, put [HTTPS](#https-for-user-accounts-caddy-nginx-synology-dsm) in front of it.

### 3.5 Windows or macOS Computer (one person)

**Step 1. Clone the repository**
```bash
git clone https://github.com/kotsimp/BookApp.git
cd BookApp
```

**Step 2. Create and activate a virtual environment**
* **On Windows (PowerShell / Command Prompt):**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\activate
  ```
* **On Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

**Step 3. Install the dependencies**
```bash
pip install --upgrade pip
pip install -r requirements.txt
# optional, reproducible: pin to the exact versions of a verified environment
pip install -r requirements.txt -c requirements-lock.txt
```
* **Packages:** FastAPI, Uvicorn, python-multipart, aiofiles, aiohttp, Pydantic, PyMuPDF, python-docx, EbookLib, BeautifulSoup4, deep-translator, edge-tts, mutagen, Pillow (comic page rendering) and imageio-ffmpeg (bundles FFmpeg for M4B).
* **Without FFmpeg:** M4B export returns HTTP 501 and MP3 remains available. `GET /api/settings` reports this as `m4b_available`.

**Step 4. Start the app**
```bash
python run.py
```
*The application launches on `http://localhost:8000` and opens your default browser. It listens only on this computer (`127.0.0.1`). `python run.py` also works on its own: it creates `.venv` and installs the dependencies by itself.*

---

## 4. Production Deployment

For continuous 24/7 background operation on servers, run the application as a managed service.

### Option A: Windows Service (via NSSM)
1. Download [NSSM (Non-Sucking Service Manager)](https://nssm.cc/download).
2. Open PowerShell as Administrator and execute:
   ```powershell
   nssm install BookApp
   ```
3. Configure the service parameters in the GUI:
   * **Path:** `C:\Users\User\Documents\BookApp\.venv\Scripts\uvicorn.exe`
   * **Startup directory:** `C:\Users\User\Documents\BookApp`
   * **Arguments:** `backend.main:app --host 0.0.0.0 --port 8000 --log-level info`
4. Start the service:
   ```powershell
   nssm start BookApp
   ```

### Option B: Linux Systemd Service
The complete procedure is in [3.3 Ubuntu Server without Docker](#33-ubuntu-server-without-docker-python--systemd). It covers the service account, the unit file, the firewall, updates, backups and troubleshooting. On other distributions, use the same unit file with that distribution's package names.

### Option C: Docker & Docker Compose
The project includes a production-ready **`Dockerfile`** and **`docker-compose.yml`** bundling FFmpeg, Unicode fonts, and persistent volumes. Step-by-step procedures: [3.1 Ubuntu Server with Docker](#31-ubuntu-server-with-docker) and [3.2 Synology NAS](#32-synology-nas-with-docker-container-manager).

**Server settings go in `.env`** next to `docker-compose.yml`. Docker Compose reads the file automatically, and git ignores it, so `git pull` never conflicts with it. Container Manager on Synology (Method A) takes the values written directly in `docker-compose.yml` instead.

| Variable | Default | Meaning |
|---|---|---|
| `BOOKAPP_PORT` | `8000` | Port in the browser address (`http://<server-ip>:<port>`); inside the container it is always 8000 |
| `BOOKAPP_AUTH` | off | `1` = sign-in required, administrators create the users |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | `*` only behind a reverse proxy (see [HTTPS](#https-for-user-accounts-caddy-nginx-synology-dsm)) |
| `BOOKAPP_COOKIE_SECURE` | off | `1` = sign-in cookie only over HTTPS |

After changing `.env`, run `docker compose up -d`. The server's IP address is not configured anywhere: the container answers on every address of the host.

* **Your API keys are not in the image:** `.dockerignore` excludes `config/settings.json`, `config/*.tmp`, `config/*.corrupt` and `.env` files; docker-compose mounts `./config` at run time. Images built before 23 Nov 2026 contain `config/settings.json`: remove them (`docker image rm bookapp:latest`), rebuild, and replace the keys if such an image was ever pushed or shared.
* The image installs `libarchive-tools` (bsdtar reads `.cbr` uploads), FFmpeg and the DejaVu and Liberation fonts. `.cbr` exports need no tool: BookApp writes the RAR archive itself.

### Nginx Reverse Proxy Configuration with SSE
Because the application uses **Server-Sent Events (SSE)** for live progress streaming, proxy buffering **must** be disabled in Nginx:

```nginx
server {
    listen 80;
    server_name bookapp.internal.domain;

    client_max_body_size 250M;  # Allow large PDF, EPUB, and Graphic Novel uploads

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # Server-Sent Events (SSE) configuration
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;

        # Standard proxy headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### User Accounts & Administrators (sign-in)

Off by default. With `BOOKAPP_AUTH=1` everyone signs in with a username and password.

**Roles**

| | User | Administrator |
|---|---|---|
| Translate, audiobooks, Book Insights | ✅ | ✅ |
| Session History, downloads, batch queue | own jobs only | all jobs (filter: mine / all users / one user) |
| Own password, sign out | ✅ | ✅ |
| Gemini API keys, settings, device pairing, storage clean-up | — | ✅ |
| Create users, reset passwords, disable, delete, sign out everywhere | — | ✅ |
| Make another user an administrator (same rights) or remove the rights | — | ✅ |
| Gemini usage today per user | own (👤 menu) | everyone (👥 Χρήστες) |

The Gemini keys stay one shared pool managed by the administrators; users never see them, not even masked. Another user's job is answered with "not found" everywhere (status, downloads, progress, editor, insights, queue, AI Polish), so job ids reveal nothing. The batch queue processes everyone's documents one at a time; each user sees and clears only their own items, and *Start* applies a user's settings only to that user's documents (*Pause* and *Auto-start* act on the whole shared queue). The glossary is shared by all users.

**The first administrator** (no account exists yet). Use either way:

1. **Setup code (browser).** On the first start with accounts on, the server writes a one-time code to its log and to `data/setup_code.txt` (owner-only permissions on Linux):
   ```text
   BookApp FIRST-TIME SETUP: no user account exists yet.
   Open  http://<this-server>:8000/setup  (or https://<your-domain>/setup) in a browser
   and enter the setup code:   7K3F-9QXM
   ```
   Read it on the server, then open `/setup` on any computer, enter the code and choose a username and password. Until then every page leads to `/setup`, and nobody can become administrator without the code. The code survives restarts and is deleted as soon as the first administrator exists. Ten wrong codes pause setup for 15 minutes.

   | Installation | Where to read the code |
   |---|---|
   | Ubuntu, systemd | `sudo journalctl -u bookapp \| grep -i "setup code"` or `sudo cat /opt/BookApp/data/setup_code.txt` |
   | Docker | `docker logs bookapp 2>&1 \| grep -i "setup code"` or `sudo cat data/setup_code.txt` next to `docker-compose.yml` |
   | Synology (Container Manager) | **Container → bookapp → Log**, or with File Station the file `setup_code.txt` in the folder mapped to `/app/data` (for example `/docker/bookapp/data/`) |

2. **Command line (SSH).** Run in the BookApp folder with its Python environment; it works while the server runs:
   ```bash
   cd /opt/BookApp && sudo -u bookapp .venv/bin/python -m backend.auth create-admin kostas   # asks for the password twice
   docker exec -it bookapp python -m backend.auth create-admin kostas           # Docker (on Synology: sudo docker exec …)
   ```

**Account tool** (`python -m backend.auth <command>`; prefix `docker exec -it bookapp` for Docker):

| Command | What it does |
|---|---|
| `create-admin NAME` / `create-user NAME` | Creates an account (asks for the password; `--password-stdin` for scripts) |
| `reset-password NAME` | Sets a new password and signs that user out everywhere. **Recovery** when the only administrator forgot the password: access to the server is the key |
| `make-admin NAME` | Gives administrator rights and re-enables the account |
| `list-users` | Lists accounts, roles, last sign-in |
| `setup-code` | Shows the setup code while no account exists |

**Administrators in the app:** the **👥 Χρήστες** button opens user management:
* **Create:** username (2–32 Latin letters, digits, `.` `_` `-`) and role; leave the password empty to get a generated temporary one (shown once). Every new user must choose an own password at the first sign-in.
* **⭐ Κάνε διαχειριστή / ⬇️ Αφαίρεση δικαιωμάτων:** a promoted user has exactly the administrators' rights.
* **🔑 Επαναφορά κωδικού:** new temporary password; the user is signed out everywhere.
* **⏸️ Απενεργοποίηση:** blocks sign-in and ends all sessions at once; **✅ Ενεργοποίηση** undoes it.
* **🚪 Αποσύνδεση παντού** and **🗑️ Διαγραφή**. Deleting asks what happens to the user's jobs: transferred to you, or deleted with their files.
* **Safeguards:** the last active administrator cannot be demoted, disabled or deleted, and you cannot disable or delete your own account. All these actions are recorded in **📜 Ιστορικό ενεργειών διαχείρισης** (last 2,000 entries).

**Sessions:** *Να παραμείνω συνδεδεμένος/η* (ticked by default) keeps a user signed in for **60 days, renewed on every visit**: someone who uses the app regularly is not signed out until they sign out. Unticked, the session ends with the browser (at most 12 idle hours). Changing a password signs out the user's other sessions. **Lockout:** 5 wrong passwords lock that username for 15 minutes; 20 from one address lock that address.

**Security details:** passwords are stored only as salted scrypt hashes (Python standard library, no extra packages) in `data/auth.db`; session tokens are random, sent in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` over HTTPS) and stored only as SHA-256 hashes. Minimum password length 10 (no forced periodic changes). Existing jobs from before accounts were switched on belong to the administrators. Back up `data/auth.db` together with `data/bookapp.db`.

**Endpoints:** `GET /login`, `GET /setup`, `GET /api/auth/status`, `POST /api/auth/setup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password`; administrators: `GET|POST /api/auth/users`, `POST /api/auth/users/{id}/role|disabled|reset-password|sign-out`, `DELETE /api/auth/users/{id}?jobs=transfer|delete`, `GET /api/auth/audit`. `GET /api/jobs` and `DELETE /api/jobs` take `scope=mine|all|<user id>` (administrators); for users they always mean their own jobs.

### HTTPS for User Accounts (Caddy, nginx, Synology DSM)

Passwords must not travel over plain `http://` outside your own home network. Put BookApp behind a reverse proxy with a free Let's Encrypt certificate, and let only the proxy reach port 8000.

* **Caddy (Ubuntu, simplest; obtains and renews the certificate itself):** `/etc/caddy/Caddyfile`
  ```text
  books.example.com {
      request_body {
          max_size 250MB
      }
      reverse_proxy 127.0.0.1:8000 {
          flush_interval -1
      }
  }
  ```
  Then bind BookApp to the local address only: `--host 127.0.0.1` in the systemd `ExecStart` line.
* **nginx:** use the configuration above with `listen 443 ssl;` and a certificate from `certbot --nginx`. It already sends `X-Forwarded-For` and `X-Forwarded-Proto`.
* **Synology DSM:** **Control Panel → Login Portal → Advanced → Reverse Proxy → Create**: source `HTTPS`, your hostname, port 443; destination `HTTP`, `localhost`, port 8000 (or the NAS port you chose). Get the certificate in **Control Panel → Security → Certificate**. In the container settings add the environment variables `BOOKAPP_AUTH=1` and `FORWARDED_ALLOW_IPS=*`. If after signing in over HTTPS the browser's cookie details show `bookapp_session` without *Secure*, the proxy does not pass the original scheme: add under **Custom Header** `X-Forwarded-Proto` = `$scheme` and `X-Forwarded-For` = `$proxy_add_x_forwarded_for`, or set `BOOKAPP_COOKIE_SECURE=1`.

**Why `FORWARDED_ALLOW_IPS`:** Uvicorn trusts the proxy's `X-Forwarded-For` / `X-Forwarded-Proto` headers only from `127.0.0.1` by default. That covers Caddy or nginx on the same machine. In Docker the proxy arrives over Docker's network (for example `172.17.0.1`), so set `FORWARDED_ALLOW_IPS=*` (or the proxy's address). Without it, BookApp sees every visitor as the proxy's address (a lockout would hit everybody) and does not notice HTTPS. Use `*` only when port 8000 is not reachable from untrusted networks except through the proxy. `BOOKAPP_COOKIE_SECURE=1` forces the `Secure` cookie flag regardless.

---

## 5. Storage Layout & Data Management

### Directory Structure
```
BookApp/
├── backend/
│   ├── main.py              # FastAPI application (pipelines, core endpoints & SSE streaming)
│   ├── api/                 # API routers: refine.py, insights.py, pairing.py, auth.py, connections.py (devices, OPDS) + shared common.py (87 routes in total)
│   ├── output_refiner.py    # Final Output Refinement & quality-control stage
│   ├── book_insights.py     # Book Insights: summaries, synopses & their audio
│   ├── translation_prompts.py # Versioned prompt library (translation, polish, revision, audiobook script, dossier)
│   ├── ai_segment_translator.py # Format-preserving AI translation of DOCX/EPUB segments
│   ├── device_pairing.py    # Optional password-free device pairing (BOOKAPP_PAIRING=1)
│   ├── auth.py              # Optional user accounts & administrators (BOOKAPP_AUTH=1); account tool: python -m backend.auth
│   ├── request_context.py   # Signed-in user of the current request (job visibility, usage per user)
│   ├── ai_polisher.py       # Single-Pass Direct AI Translation & Gemini Polish engine
│   ├── comic_translator.py  # Graphic Novel, Scanned PDF & Manga (RTL) Vision AI engine
│   ├── scan_reader.py       # Scanned books: page text read by Gemini Vision, kept next to the upload
│   ├── bilingual.py         # Bilingual edition: paragraph alignment, PDF / DOCX / EPUB
│   ├── connections.py       # Per-user e-reader link (OPDS) and phone notifications (ntfy) settings
│   ├── notify.py            # ntfy messages when a translation or audiobook finishes or stops
│   ├── queue_manager.py     # Smart Batch Queue serial engine (max 20 files, retry, auto-pause)
│   ├── database.py          # SQLite WAL persistence (data/bookapp.db) & SHA-256 semantic cache
│   ├── typography.py        # Greek editorial typography and grammar rules
│   ├── genre_detector.py    # Document genre and editorial style detection
│   ├── storage_cleaner.py   # Scratch-file garbage collector (never deletes jobs)
│   ├── format_sync.py       # In-place edits of format-preserved DOCX/EPUB
│   ├── format_preserver.py  # In-place DOCX and EPUB layout and style preserver
│   ├── exporter.py          # Exporter for TXT, DOCX, EPUB, PDF, CBZ, CBR & Literature layout
│   ├── comic_archive.py     # Reads CBR uploads (7-Zip / bsdtar) and writes CBR exports (RAR 4, pages stored)
│   ├── pdf_text_names.py    # Names shared glyphs in exported PDFs as the book's characters (copy, search)
│   ├── glossary.py          # Categorized domain glossary management
│   ├── settings_manager.py  # Local persistent settings manager (config/settings.json)
│   ├── gemini_key_pool.py   # Multi-Key Gemini API Pool & Failover Manager (up to 8 keys, MAX_KEYS)
│   ├── translator.py        # Core translation engine (Google GTX POST + 429 Circuit Breaker)
│   ├── tts_engine.py        # Neural edge-tts voice synthesis & M4B audiobook assembly
│   ├── job_manager.py       # Task lifecycle manager, SQLite sync & file healing
│   └── parsers.py           # Document parsers and comic detection heuristics
├── config/
│   ├── glossary.json        # Categorized custom glossary terms (3,366+ terms across Technical, Literary, General)
│   └── settings.json        # Persistent configuration & API keys (gitignored)
├── data/
│   ├── bookapp.db           # Persistent SQLite database (jobs, settings & semantic cache)
│   ├── auth.db              # User accounts: password hashes, session hashes, audit log (BOOKAPP_AUTH=1)
│   ├── connections.json     # Per-user e-reader link hashes and ntfy settings
│   └── setup_code.txt       # One-time first-administrator setup code (deleted after setup)
├── frontend/                # Single-page app: index.html, login.html, style.css, i18n.js (Greek / English interface), theme.js (light by day, dark at night), app.js (core), insights.js, pairing.js, auth.js
├── temp/
│   ├── uploads/{job_id}/    # Uploaded input documents (+ <name>.scantext.json: the text read from a scanned book)
│   └── outputs/{job_id}/    # Translated books, checkpoints, audiobooks (+ <name>.chapters.json, <name>.sync.json), insights/, bilingual/
├── tests/                   # 65 automated test suites (sandboxed)
├── eval/passages.json       # Translation quality evaluation passages
├── scripts/                 # eval_translation_quality.py (quality evaluation runner), make_icons.py (redraws frontend/icon.svg, favicon.ico, icon-*.png, apple-touch-icon.png)
├── requirements.txt
└── requirements-lock.txt    # Exact versions of a verified environment (pip -c constraints)
```

### REST API Administration Endpoints
The backend provides **87 routes** (REST endpoints plus the `/login`, `/setup` and `/pair` pages) for complete administrative control. User-account endpoints are listed in [User Accounts & Administrators](#user-accounts--administrators-sign-in):
* `POST /api/translate`: Initiates document translation. Supports `quota_behavior: "wait" | "fallback"`, `final_refinement` (local quality stage override), `max_quality` (second AI revision against the original; requires `ai_polish` and a Gemini key), `read_scanned_text` (a scanned PDF: `true` = a book whose text is read first, `false` = a comic) and `page_from` / `page_to` (a sample of those pages).
* `GET /api/download/{job_id}/bilingual?format=pdf|docx|epub`: The bilingual edition (original and translation, paragraph by paragraph).
* `GET /api/jobs/{job_id}/read-along`: Sentence times of the newest audiobook, for the player's read-along panel.
* `GET /api/connections`, `POST/DELETE /api/connections/opds`, `POST /api/connections/ntfy`, `POST /api/connections/ntfy/test`: The signed-in user's devices (e-reader link, phone notifications).
* `GET /opds/{token}/`, `GET /opds/{token}/book/{job_id}/{kind}`, `GET /opds/{token}/cover/{job_id}`: The e-reader catalogue (open path; the secret token is the pass).
* `GET /api/translate/estimate/{job_id}`: About how many Gemini requests a translation with the given settings needs (reading scanned pages, translation, 2nd pass) and what the keys allow a day. See [Request estimate](#core-backend-components).
* `POST /api/audiobook`: Initiates neural audiobook synthesis.
* `GET /api/queue`, `POST /api/queue/add`, `POST /api/queue/start`, `POST /api/queue/pause`, `POST /api/queue/auto-start`, `POST /api/queue/{job_id}/retry`, `GET /api/queue/download-all`, `DELETE /api/queue/{job_id}`, `DELETE /api/queue`: Full Smart Batch Queue administration.
* `DELETE /api/jobs/{job_id}`: Deletes a specific job from memory, database, queue, and purges its upload and output directories.
* `DELETE /api/jobs`: Clears all job history and temporary files (retaining the semantic cache). With user accounts: only the requester's jobs; administrators can pass `scope=all` for the full clean-up.
* `DELETE /api/jobs/tests/cleanup`: Purges test-generated jobs inside the test sandbox. On a normal installation it deletes nothing and returns `deleted_count: 0`.
* `GET /api/settings`, `POST /api/settings`, `DELETE /api/settings/{key}`: Reads, saves, and deletes configuration parameters.
* `GET /api/gemini/pool`: Returns detailed Multi-Key Pool status (total keys, active keys, individual slot health, and cooldown timestamps).
* `POST /api/gemini/pool`: Configures or updates the pool keys (`{"keys": ["AIzaSy...", ...]}`), clearing quota cooldowns.
* `GET /api/gemini/status`: Returns circuit breaker status, remaining cooldown seconds, and local reset time; `pool.cooling_models` (each model at its daily limit on some keys: `model`, `keys`, `reset_timestamp`, `remaining_sec`), and `waiting_jobs` (the viewer's jobs from the last 48 h stopped on quota or queued for it). Jobs stop with `All Gemini candidate models are in cooldown` without tripping the circuit breaker when only models ran out, so the keys window reads both; it refreshes them every 5 s while open and shows reset times in the browser's clock.
* `POST /api/gemini/reset-quota`: Instantly resets the quota circuit breaker and per-key cooldown timers.
* `GET/HEAD /api/cover/{job_id}`: Inspects and retrieves active cover art.
* `POST /api/cover/{job_id}`: Uploads custom cover artwork (`multipart/form-data`). Refreshes generated exports; `preserved_files` in the response lists the files deliberately left untouched.
* `DELETE /api/cover/{job_id}`: Removes cover artwork for a job.
* `GET /api/insights/{job_id}/analysis`: Meaningful word count, estimated pages, detected language, summary/synopsis availability with reasons, `has_api_key`, existing insights.
* `GET /api/insights/{job_id}`: Stored insights (full text, audio URL).
* `POST /api/insights/generate`: `{"job_id", "insight_type": "summary"|"synopsis"|"one_sentence"|"short_summary"|"extended_summary"|"standard_synopsis"|"extended_synopsis", "language": "auto"|"greek"|"english", "api_key"?}` → `{"task_id", "duplicate"}`. HTTP 401 without a key, 422 for too-short/insufficient/undetectable documents, 400 for invalid options or unsupported formats.
* `GET /api/insights/tasks/{task_id}`: Task progress, step, result or `{code, message}` error.
* `POST /api/insights/export`: `{"job_id", "insight_type", "language", "format": "pdf"|"docx"|"doc"|"txt"}` → download URL.
* `POST /api/insights/audio`: `{"job_id", "insight_type", "language", "voice_name"?}` → `{"task_id", "duplicate"}`.
* `GET /api/insights/{job_id}/files/{filename}`: Serves exports/MP3 strictly from the job's `insights/` folder (name whitelist, no dot-files, resolved-parent check).
* `GET /api/refine/config`: Final Output Refinement status (enabled flag, version, stages, `uses_external_api: false`).
* `POST /api/refine`: On-demand refinement. `{"text": ...}` refines a snippet (nothing written; max 5M chars, HTTP 413 above). `{"job_id": ..., "mode": "translation"|"audiobook"|"auto"}` refines/validates that job's output. `file_path` is accepted **only** for files inside the job's own output folder (HTTP 400 otherwise). Running jobs are rejected with HTTP 409.

### Automated Storage Housekeeping
On startup, `cleanup_old_jobs()` resets interrupted jobs and removes scratch files older than 24 hours. **It never deletes jobs, uploads or results.** Free space with **✕** / **Clear All** in Session History, `DELETE /api/jobs/{job_id}`, or a scheduled scratch cleanup through the API:

* **On Linux (Cron):**
  ```bash
  # Remove scratch files every night at 03:00 AM (jobs and results are kept)
  0 3 * * * curl -fsS -X POST http://127.0.0.1:8000/api/admin/cleanup -H 'Content-Type: application/json' -d '{"max_age_hours":48}'
  ```
* **On Windows (PowerShell via Task Scheduler):**
  ```powershell
  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/admin/cleanup -ContentType 'application/json' -Body '{"max_age_hours":48}'
  ```

> [!CAUTION]
> Don't delete `temp/` by file age (`find … -mtime +7 -delete`, `Remove-Item`), as earlier versions of this manual suggested: `temp/uploads` and `temp/outputs` hold the users' books and results. Remove any such scheduled task.
>
> On Windows, keep BookApp out of `%TEMP%`, which Storage Sense empties when disk space is low.

---

## 6. Automated Test Suite Execution

The repository includes a comprehensive master test runner with **100% endpoint coverage across all 75 FastAPI routes**:

> [!IMPORTANT]
> **Tests never see your data:** `run_all_tests.py` works in a throw-away copy on a free port, with an empty database and no API keys. A running BookApp on port 8000 is not used. Test files refuse to run outside this sandbox.

```bash
# Execute all 62 test suites (Full Master Suite):
.\.venv\Scripts\python run_all_tests.py

# Fast execution (57 local static, unit, contract, UI, and queue suites):
.\.venv\Scripts\python run_all_tests.py --fast

# Selected suites:
.\.venv\Scripts\python run_all_tests.py test_data_safety_and_preservation
```

The master runner automatically executes all test suites:
1. `test_ai_polish_advanced.py`: Source-anchoring, audiobook script phonetics, entity dossier & checkpoints.
2. `test_ai_polisher_deep.py`: Editorial styles, multi-page chunk splitting, cache invalidation, `BLOCK_NONE` safety settings, recursive bisection on safety blocks, and mixed-script detection.
3. `test_api.py`: Comprehensive REST endpoint integration, uploads, translation, and streaming.
4. `test_categorized_glossary.py`: Categorized glossary rules across Technical, Literature, and General domains.
5. `test_code_health.py`: **10-point static code health guard**: AST/Syntax, Unbound Locals, Import Integrity, Unreachable Code, Undefined Globals, Unused Imports, Frontend HTML⇄JS Cross-Integrity, Config Hygiene, Route Alignment, and 100% Endpoint Coverage Guard.
6. `test_comic_translation.py`: Graphic Novel translation (PDF, CBZ, CBR, EPUB) and TXT/DOCX format guards.
7. `test_concurrency_and_stress.py`: Stress testing with 50 parallel jobs, thread-safe settings, and SSE queues.
8. `test_database_and_cache.py`: SQLite persistence (`data/bookapp.db`), restart recovery, and SHA-256 semantic cache.
9. `test_document_integrity_and_encoding.py`: BOM, UTF-16, CP1253, polytonic Greek, and corrupted file handling.
10. `test_dynamic_download.py`: On-demand dynamic format conversion during download.
11. `test_e2e_regression_guard.py`: 10-point end-to-end regression guard verifying database deletes, single-pass DOCX polish, invalid API key fail-fast, Google 429 circuit breaker, and test job isolation.
12. `test_edge_cases_and_robustness.py`: Extreme inputs and edge cases.
13. `test_editor_glossary_ai.py`: In-browser Editor, glossary rules, and AI Polish interactions.
14. `test_exporter.py`: Document export pipelines for DOCX, PDF, EPUB, TXT, CBZ, and CBR.
15. `test_format_preservation.py`: In-place formatting and table preservation in DOCX and EPUB.
16. `test_literature_formatting.py`: Literature layout, running header stripping, chapter markers, and indentations.
17. `test_manga_rtl_and_balloon_fit.py`: Japanese Manga RTL reading progression and balloon scaling.
18. `test_multivoice_and_m4b.py`: Multi-voice dramatization, speaker tags, ID3 cover art tagging, and M4B export.
19. `test_new_api_endpoints.py`: Integration checks for genre detection, voice preview, cache stats, and storage cleanup.
20. `test_parsers.py`: PDF, DOCX, EPUB, CBZ, and TXT parsers and comic auto-detection heuristics.
21. `test_pdf_initial_pages_preservation.py`: Front matter and prologue preservation on initial pages.
22. `test_performance_and_benchmarks.py`: High-load benchmarks (SQLite WAL cache throughput, typography engine speed).
23. `test_poetry_pauses.py`: Poetry recitation, elisions, meter pauses, and verse formatting.
24. `test_scanned_comic_and_autodetect.py`: Scanned graphic novel auto-detection and pixel-level opaque erasing.
25. `test_standalone_ai_polish.py`: Standalone AI polish without prior translation.
26. `test_translator.py`: Core Google GTX POST translation engine, 429 circuit breaker, and Gemini failover.
27. `test_tts_audiobook_deep.py`: Voice catalog, prosody rate/pitch bounds, chunk assembly, and cancellations.
28. `test_typography_and_genre.py`: Greek typography rules, final "ν" grammar, and auto-genre detection.
29. `test_smart_batch_queue.py`: Smart Batch Queue lifecycle (`/api/queue/*`), 20-file capacity, setting sync, pause/resume, retry, and ZIP packaging.
30. `test_translation_quality_fixes.py`: Quality checks for HTML/LLM token removal, CoT leak stripping, full Flash prioritization, privative `μη` vs verbal `μην`, and PDF URL wrapping.
31. `test_security_and_input_validation.py`: Universal path traversal prevention (`job_id`), voice preview sanitization, Windows-reserved filenames, and prosody validation.
32. `test_api_contracts_and_state_machine.py`: TXT/DOCX downloads for normal PDF books, `HEAD /download`, SSE stream termination, and ZIP download gating.
33. `test_ai_polisher_and_translator_resilience.py`: Mocked HTTP resilience tests for cache key isolation, API key leak prevention, double-400 retry handling, and MyMemory error rejection.
34. `test_pipeline_data_integrity.py`: Glossary idempotency, dialogue dash protection, fenced code blocks, and XML control characters.
35. `test_comic_and_tts_edge_cases.py`: CBZ Zip Slip prevention, natural numeric page sorting, clamped bounding boxes, and temp cleanup.
36. `test_concurrency_persistence_and_lifecycle.py`: Thread-safe off-loop SSE delivery, cancelled job state protection, and corrupted `settings.json` recovery.
37. `test_frontend_contracts_and_ui.py`: HTTP route validation against FastAPI `app.routes`, Pydantic schema validation, and Node.js VM runtime UI tests (incl. a lone queued file returning to the Upload Card, upload progress and the batch upload summary), the app icon files, links and open paths, and the Greek / English interface (every page text has a pair; numbers switch with the text).
38. `test_gemini_quota_warning.py`: Gemini quota exhaustion detection, circuit breaker lifecycle, and reset verification.
39. `test_quota_behavior_choice.py`: Prior quota routing choice (`wait` vs `fallback`), Free Mode defaults, and session history hygiene.
40. `test_gemini_key_pool.py`: Multi-Key Pool verification (up to 8 keys, rotation, thread-safety, masking, and REST endpoints).
41. `test_gemini_diagnostics.py`: Dedicated API Key Diagnostics & Stress-Test Suite (CRUD, error parsing, sliding-window rate limiting, per-model isolation, E2E 4-key rotation simulation, pool exhaustion, cooldown recovery, transient backoff/retry, concurrency, and live key diagnostics).
42. `test_scripted_editorial_pass.py`: Dedicated Sanitization & Scripted Editorial Pass Suite (verifying automated remediation of subword token bleed, code leaks, comedic calques, double accents, and stutters).
43. `test_output_refinement.py`: Final Output Refinement stage (49 tests). `_call_gemini_api` tests cover the size-aware timeout and the cache gate. The stage tests cover: Covers: automatic triggering at the end of the translation and audiobook workflows; correction of injected errors; no-op on clean text; meaning safety for ambiguous phrasing and emphatic repetition; poetry, French and code-like spacing; idempotency; empty, malformed and undecodable inputs; rollback on re-export, document-swap and write failures; inspection-only behaviour for format-preserved DOCX; audio header, truncation and missing-section detection; healing of failed sections; rejection of corrupt re-assembly and timeouts; metadata added only when missing; disabled-stage pass-through; settings, env and per-job toggles; a no-network guarantee; and API security (path traversal, foreign files, running jobs).
44. `test_book_insights.py`: Book Insights (32 tests). Gemini and edge-tts are mocked in-process on a private uvicorn port. Covers:
    * Basic and Advanced modes; all five types in Greek and English; word-count and structure guidelines; ordering (extended synopsis > synopsis > short summary).
    * Summary vs synopsis distinctness; PDF/DOCX/DOC/TXT exports and export failure.
    * Minimum-length thresholds below and above the limit, with no API usage when ineligible.
    * Language detection (Greek/English/other/none); extraction failure; unsupported comics; missing key.
    * Quota, network, auth and generic AI failures; the quality-gate retry, and rejection of wrong-language or fabricated output (never stored).
    * Latin-script and condensation checks; the proofreading guard; English stutter collapse.
    * Audio for all types with spoken text == final text; audio failure leaving no file; audio requiring generated text.
    * Duplicate and concurrent requests; result caching; map-reduce for long books.
    * File-endpoint traversal; XSS-safe Markdown rendering (Node); unchanged DocTranslate/Audiobook job state and downloads.
45. `test_translation_prompts.py`: AI translation/polish/audiobook prompt quality and maximum-quality revision (21 tests). Revision tests cover: the reviser prompt (with no examples taken from the evaluation passage); fixes applied under the full-models-only policy, with the policy reset afterwards; guards for marker changes, length, quota and auth that keep the first pass; skips and the clean case; Lite/Gemma models excluded by the policy; pipeline wiring (revision runs before export and only when requested and eligible); a revision crash never failing the job; and the article final-ν rule. The prompt tests cover: generic prompts with no title-specific terms; the direct prompt is a translate-from-source prompt carrying the fidelity and fault checklists; language-aware polish (English targets); audiobook no-paraphrase and spoken-form rules; poetry verse preservation; dossier style sheet and pronunciation modes, and their use in the pipeline; the Greek audiobook pronunciation register; stale checkpoints discarded and matching ones resumed; NFC normalisation; restored capital accents.

46. `test_audit_regressions.py`: regression guards from the November 2026 codebase audit (7 tests): a quota-paused queue reports `paused_for_quota` so it can auto-resume; saving new keys resets the quota circuit breaker; CORS rejects foreign origins and accepts local development origins; every third-party import is declared in `requirements.txt`; no undefined names in the backend (pyflakes, when installed).

47. `test_device_pairing.py`: device pairing (7 tests). Covers: disabled means no change; unpaired clients blocked (JSON for the API, a page otherwise); health stays open; a single-use code sets an HttpOnly cookie; expiry; links from trusted devices; list and revoke (a revoked cookie stops working); only token hashes stored; loopback trust on/off.
48. `test_improvements.py`: improvement batch (17 tests). Covers:
    * per-job and daily Gemini usage, including child tasks and cache hits;
    * slow-model memory;
    * the segment protocol: parsing, alignment and fallback, quota fallback vs wait;
    * DOCX/EPUB AI in-place round-trips keeping bold runs, headings, tables and HTML tags, with the free path unchanged;
    * pipeline routing of DOCX with AI Polish to in-place, and the max-quality skip;
    * chapter marks, FFMETADATA and the ffmpeg command;
    * Insights task recovery;
    * Greek sentence-case headings;
    * the evaluation scorer;
    * no API keys in comic URLs.

**Translation quality evaluation (manual, optional):** `python scripts/eval_translation_quality.py --live` translates the passages in `eval/passages.json` with the current prompt (about 1 Gemini request per passage) and scores structure, script, known wrong renderings and required terms. `--from-dir DIR` scores saved outputs without API use. Run it after changing prompts.

49. `test_data_safety_and_preservation.py`: regression guards for restart data safety, format-preserving edits (DOCX/EPUB, randomized round-trips), comics, Wait for Reset, real M4B, validation and escaping.

50. `test_comic_archive.py`: `.cbr` uploads (RAR 4, RAR 5 or ZIP inside) become CBZ through 7-Zip and through bsdtar; hostile names and sizes stay harmless; a `.cbr` export is a real RAR archive that reads back page for page.
51. `test_comic_fidelity.py`: comics keep their page order and every balloon, read real scans and WebP; balloon text copies out of the PDF as written; a short rate limit never switches a key off.
52. `test_export_fidelity.py`: exporters drop no words; every script is drawn; text copied from PDFs is the book's own characters in every font the exporters use.
53. `test_free_engine_failover.py`: Google's refusals are respected, MyMemory stays inside its limit, Gemini stands in with few requests, and nothing is handed out shortened or untranslated.
54. `test_gemini_answers.py`: only complete Gemini answers count, a blocked text costs one request per model, and request labels follow the language of their instructions.
55. `test_interruptions_and_free_engine.py`: Smart Resume data, queue persistence across restarts, the quota banner, and the free engine never reporting untranslated text as translated.
56. `test_lossless_documents.py`: property tests on random DOCX/EPUB packages (format preservation, edits, preformatted poems vs code, the kept-code note).
57. `test_output_freshness.py`: downloads follow the job's current translation; cover removal, polish language and cross-site protection.
58. `test_parser_fidelity.py`: the parsers drop nothing the reader sees, keep the reading order, and use the PDF's page labels to confirm page numbers.
59. `test_target_language.py`: English targets get English instructions; an AI answer in another language or with lost text never replaces the book's text.
60. `test_text_fidelity.py`: clean-up passes never change correct text, and boundary de-duplication never deletes text the book repeats.
61. `test_voice_fallback.py`: a refused or cut voice request never leaves gaps in an audiobook; network drops are waited out in the chosen voice; Resume reuses parts.
62. `test_auth.py`: user accounts (18 tests). Covers: accounts off changes nothing; the first administrator through the setup code (log/file, stable across restarts, forgiving format, single use) and through the command-line tool; scrypt hashes and password rules; the 5-failure lockout; 60-day remembered sessions that slide forward vs browser sessions; temporary passwords that must be changed before anything else; HttpOnly/SameSite cookies, `Secure` behind an HTTPS proxy; admin-only endpoints and hidden keys; users reach only their own jobs (history, status, downloads, progress, editor, insights, cancel, delete, translate, polish, queue, Clear All) while administrators see all with the filter; promote, demote, disable, reset, sign out everywhere, delete with job transfer or deletion, audit log; the last active administrator protected; pairing replaced; the browser script (expired session to the login page, admin-only controls hidden).
63. `test_translation_leftovers.py`: an echoed untranslated page is split and retried, never written into the book; leftover pages and words of another alphabet are reported; polytonic slips, dash dialogue and corrupted words are corrected; the revision is merged page by page; a contents page gets this edition's page numbers and the PDF gets bookmarks.
64. `test_scanned_books_samples_estimate.py`: scanned books (18 tests). Covers: the book / comic guess; pages read once and used by the parser; a sample reading only its pages and the rest later; pages with their own text not sent; empty and refused pages; failures and quota stops keeping what was read; text of a changed file ignored; the picture call (inline image, Flash-Lite first, light cleaning, cache); learned daily limits; AI samples translating only their batches and the whole book reusing them; free-engine and comic samples; the estimate (batches, 2nd pass, samples, scanned books, comics, keys); and through the API the upload guess, the estimate, a sample run with its download name and the range checks.

65. `test_bilingual_opds_ntfy_readalong.py`: bilingual edition, e-reader catalogue, phone notifications and reading along (13 tests). Covers: both page-marker styles; joined, split and missing paragraphs; whole texts without markers; the PDF (original first, both languages), DOCX and EPUB; secret links (hash only, a new one stops the old, removal); open paths; ntfy server addresses and messages per outcome and language; the notice sent once per run and only for translations and audiobooks; sentence times from part durations; and through the API the bilingual download (formats, untranslated), the OPDS feed and book downloads with 404s, the ntfy settings and a test message and a finished job reaching a local stand-in server, and read-along times ignored for a newer recording.

All test suites pass: **`60/60 PASS in --fast mode`** on Windows 11 (Python 3.15). The full run (65 suites, with the 5 network suites) last passed at 62 suites, on Windows 11 and on Linux (Ubuntu 20.04 under WSL, Python 3.11, bsdtar instead of 7-Zip).

---

## 7. Technical Troubleshooting

| Symptom | Probable Cause | Resolution |
|---|---|---|
| **Question mark symbols (`[?]`) in DOCX bullets** | Non-standard Private Use Area (PUA) characters from Wingdings/Symbol fonts in source file. | Fully resolved: Backend converts PUA glyphs into standard Unicode bullets (`•`) and applies native Word `List Bullet` paragraph styling. |
| **Gemini refusals on dark/mature fiction (`PROHIBITED_CONTENT` / `SAFETY`)** | Content safety filters triggered by fictional violence, horror, or mature themes. | Fully resolved: `ai_polisher.py` sets `BLOCK_NONE` thresholds and catches `PROHIBITED_CONTENT` / `SAFETY` finish reasons instantly with `_ContentBlockedError`. Bypasses candidate model looping and executes recursive page/paragraph bisection, using Google Translate fallback only for the isolated flagged paragraph while keeping 99%+ of the book in full Gemini Flash. |
| **Download button serves original format instead of newly selected format** | Download endpoint was not receiving dynamic format parameter. | Fully resolved: `GET /api/download/{job_id}?format=pdf|docx|epub|txt|cbz|cbr` dynamically converts and serves any file on demand. The UI embeds instant 1-click download pills (`PDF`, `DOCX`, `EPUB`, `TXT`) directly in the result card. |
| **HTTP 404 on download (`Job not found`)** | Server reboot with loss of in-memory dictionary state. | Fully resolved: Jobs persist in SQLite (`data/bookapp.db`) and `job_manager.py` automatically recovers output files from disk. |
| **`NoAudioReceived` error during audiobook generation** | Edge-TTS voice dictionary gaps on complex technical acronyms. | Fully resolved: Primary default voice set to **Nestoras** with automatic fallback handling. |
| **Progress bar stays at 0%** | Proxy server or firewall is buffering Server-Sent Events (SSE). | Ensure `proxy_buffering off;` and `proxy_read_timeout 86400s;` are configured in Nginx. |
| **Scanned PDFs / Graphic Novels have no extracted text** | Document consists purely of bitmap artwork without vector text. | Fully resolved: `detect_is_graphic_novel()` auto-detects scanned PDFs on upload, locks the UI to comic formats, and routes pages to **Gemini Vision AI** workers with opaque background fill and comic lettering. A scanned PDF chosen as a **Book** (`read_scanned_text`) has its page text read by Gemini Vision first (`backend/scan_reader.py`) and is then translated as text; audiobooks and Book Insights read it too when needed. As a **Comic** it takes the Vision balloon path. Both need a Gemini key: `translate_comic_document` refuses image-only pages without one, and `_read_scanned_book` stops with a message. |
| **HTTP 429 rate limit during translation** | Temporary Google GTX rate limit on heavy batch translation. | Fully resolved: `translator.py` features a **20s 429 Circuit Breaker**, fallback to MyMemory, and **automatic failover to Gemini Flash**. Single-Pass AI Polish also bypasses Google Translate entirely. |
| **Queue stalls on Gemini Free Tier daily quota limit** | Used up Google's free daily allowance, which is set per model and can be small (e.g. 20 requests/day for `gemini-3.5-flash`). | Fully resolved: `ai_polisher.py` implements a **Gemini Daily Quota Circuit Breaker** (`DailyQuotaExhaustedError`, `get_gemini_quota_info`). It fails fast in <1ms without sleeping over candidate models. The **Multi-Key Pool** automatically rotates to backup keys (Slots 2–4). When all keys are exhausted, `wait` mode pauses safely at disk checkpoint while `fallback` mode continues with free engines. |
| **Slow AI Polish or timeouts on large books** | Low concurrency, sleep inside semaphore, or hidden thinking token overhead in Gemini 2.5 Flash. | Fully resolved: Upgraded to **5 parallel workers** (`Semaphore(5)`), `thinkingBudget: 0`, HTTP keep-alive connection pooling, and smart multi-page batching, achieving **4x–8x acceleration**. |
| **M4B download returns HTTP 501** | No FFmpeg is available. | Run `pip install -r requirements.txt` in BookApp's virtual environment, then restart. |
| **Saving in the Editor returns HTTP 409** | The document is open in another program, or the edit can't be placed in the format-preserved file safely. | Close the file and retry, or edit the downloaded document directly. Nothing was changed. |
| **Cover image downloaded instead of book document** | `cover_image.jpg` was erroneously selected during job recovery. | Fully resolved: Image formats (`.jpg`, `.png`, `.webp`) are strictly excluded from document download candidates. |
| **Lost front matter on initial PDF pages (Table of Contents, Dedication, Prologue)** | Legacy block-level header filtering discarded entire text blocks containing header lines. | Fully resolved: `_clean_page_blocks` filters headers strictly on a line-by-line basis, keeping 100% of front matter text intact. |
| **Audiobook voice stumbles on foreign names** | Neural Greek voice reads Latin characters letter-by-letter. | Fully resolved: Enable **AI Polish for Spoken Audio (style="audiobook")**, which phonetically transcribes names into Greek (`Keeton` ➔ `Κίτον`) and fully writes out numbers and acronyms. |
| **Empty white speech balloons in Graphic Novels** | Dense Greek translations did not fit within `5.0pt` with `insert_textbox` and were silently omitted. | Fully resolved: Two-pass renderer (`_plan_balloon_layout` + `_draw_planned_balloon_text`) draws all inpainting backgrounds first, then renders centered text scaling down to `3.0pt` with `Arial Narrow` fallback. |
