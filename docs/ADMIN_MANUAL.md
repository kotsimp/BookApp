# 🛠️ Administrator & Deployment Manual
### DocTranslate & AudioBook Generator

This manual is intended for System Administrators, DevOps Engineers, and technical maintainers responsible for deploying, configuring, monitoring, and scaling **DocTranslate & AudioBook Generator** in local, on-premises, or cloud server environments.

---

## 📑 Table of Contents
1. [Technical Architecture](#1-technical-architecture)
2. [System Prerequisites](#2-system-prerequisites)
3. [Step-by-Step Installation](#3-step-by-step-installation)
4. [Production Deployment](#4-production-deployment)
   - [Option A: Windows Service (NSSM)](#option-a-windows-service-via-nssm)
   - [Option B: Linux Systemd Service](#option-b-linux-systemd-service)
   - [Option C: Docker & Docker Compose](#option-c-docker--docker-compose)
   - [Nginx Reverse Proxy Configuration with SSE](#nginx-reverse-proxy-configuration-with-sse)
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
│ │  - EbookLib / BS4    │    │  - Nestoras / Athina   │ │
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
* **Security, Upload Validation & Path Hygiene Guard (`backend/main.py` & `job_manager.py`):** Enforces universal path-traversal validation via `_validate_job_id()` / `is_valid_job_id()` across all endpoints (`/polish`, `/download`, `/cover`, `/jobs/*`, `/preview`, `/debug/extract`). Streaming upload parser validates the 250 MB size limit (`HTTP 413`) without OOM, sanitizes Windows-reserved filenames (`CON`, `NUL`, `<>:"|?*`), checks file magic headers (`PK`, `%PDF`), prevents **Zip Slip** vulnerabilities in CBZ extractions (`_safe_extract_zip`), and validates voice IDs and prosody bounds.
* **Semantic Cache Layer (v4):** SHA-256 content-hash caching for translated chunks (`google`), AI-polished batches (`gemini_polish_v4` hashing the entire `system_prompt` so styles and languages never collide), and comic Vision detections (`gemini_comic_vision_v2`). Rejects corrupted or MyMemory error payloads before caching. Telemetry available via `GET /api/cache/stats`.
* **Storage Auto-Cleanup Garbage Collector (`backend/storage_cleaner.py`):** Automated routine that purges orphaned temporary audio chunks, voice previews (`temp/previews/`), upload slices (`temp/uploads/tmp/`), `tts_tmp_*` working directories, and comic exports older than 48 hours while actively safeguarding running/queued jobs and user exports (`POST /api/admin/cleanup`).
* **Graphic Novel & Manga (RTL) Comic Engine (`backend/comic_translator.py`, `backend/exporter.py`):** Prioritizes full Gemini Flash Vision models, supports Japanese Manga RTL reading progression, clamps `box_2d` to `[0..1000]`, sanitizes Greek uppercase dialytika (`ΐ`/`ΰ` ➔ `Ϊ`/`Ϋ`), renders balloons via a two-pass non-blank layout engine down to `3.0pt` with `Arial Narrow` fallback, sorts CBZ pages naturally (`page_1`, `page_2`, ..., `page_10`), and serializes concurrent vision checkpoints via `asyncio.Lock` and UUID temporary files.
* **Greek Editorial Typography Engine (`backend/typography.py`):** 1.25M words/sec publishing engine that converts quotes to `«...»`, standardizes dialogue dashes (`—`), enforces modern Greek final "ν" rules (protecting conjunctive `δε` and privative `μη`), rejoins hyphenated wraps without altering interrupted dialogue, and normalizes Greek punctuation (`;`, `;!`, `;;!!`).
* **Multi-Key Gemini API Pool & Failover Manager (`backend/gemini_key_pool.py`):** Manages up to **4 free Google Gemini API Keys** simultaneously across different Google accounts (providing up to 6,000 free requests/day). Features sliding-window rate limiting (`GeminiRateLimiter` tracking RPM/TPM and smoothing request pacing), explicit Retry-After support, intelligent error payload classification (`parse_gemini_error`), per-model quota cooldown isolation (`_MODEL_COOLDOWNS` preventing low-quota models like `gemini-3.8-flash` with 20 RPD from blocking 1,500 RPD models on the same key), seamless key rotation upon HTTP 429 daily exhaustion, transient burst backoff (`retryDelay <= 60s`), thread-safe per-key cooldown timers, automatic circuit breaker reset when cooldowns expire or new keys are saved, and live status endpoints (`GET/POST /api/gemini/pool`).
* **Categorized Terminology Engine (`backend/translator.py`, `config/glossary.json`):** High-speed terminology substitution engine with **3,366+ preconfigured terms** across Technical (1,130), Literary (1,032), and General (1,204) categories. Implements idempotent single-pass placeholder replacement, regex backslash safety, symbol-safe word boundaries, automatic domain isolation (excluding IT/DevOps terms in literary, comic, and poetry modes), and live CRUD REST endpoints (`GET/POST /api/glossary`).
* **Test Session Isolation & Disk Hygiene Guard (`backend/job_manager.py`, `backend/database.py`, `run_all_tests.py`):** Multi-layered protection separating test execution from user state. Broadened test pattern detection (`test_*`, `reg_*`, `mock_*`, `sample_*`, `direct_text*`, `book*`, `temp_*`, `stress_*`, `bench_*`) combined with pre-test filesystem/database snapshotting ensures 100% of temporary directories, orphaned artifacts, and test jobs are purged upon test completion without touching real user documents.

---

## 2. System Prerequisites

### Operating System
* **Windows:** Windows 10, Windows 11, or Windows Server 2016/2019/2022.
* **Linux:** Ubuntu 20.04+, Debian 11+, RHEL/CentOS 8+, AlmaLinux/Rocky Linux.
* **macOS:** macOS 11 Big Sur or newer.

### Software Requirements
* **Python 3.9 through 3.15** with `pip` and `venv`.
* **Git** (for cloning and pulling updates).
* **FFmpeg** (optional, recommended for M4B audiobook chapter assembly and cover embedding).

### Network & Firewall Rules
* **Inbound:** Port `8000` (or `80`/`443` when behind a reverse proxy).
* **Outbound Internet Access:**
  * `translate.googleapis.com:443` (HTTPS) for translation services.
  * `*.speech.microsoft.com:443` (WSS / HTTPS) for Microsoft Edge neural voice synthesis.
  * `generativelanguage.googleapis.com:443` (HTTPS) when using Google Gemini API keys.

---

## 3. Step-by-Step Installation

### Step 1: Clone Repository
```bash
git clone https://github.com/kotsimp/BookApp.git
cd BookApp
```

### Step 2: Create & Activate Virtual Environment
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

### Step 3: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Verify Installation
```bash
python run.py
```
*The application will launch on `http://localhost:8000` and automatically open your default browser.*

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
1. Create the systemd service file:
   ```bash
   sudo nano /etc/systemd/system/bookapp.service
   ```
2. Paste the following configuration:
   ```ini
   [Unit]
   Description=DocTranslate and AudioBook Generator Service
   After=network.target

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/opt/BookApp
   ExecStart=/opt/BookApp/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info
   Restart=always
   RestartSec=5
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   ```
3. Reload systemd, enable, and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable bookapp
   sudo systemctl start bookapp
   sudo systemctl status bookapp
   ```

### Option C: Docker & Docker Compose
The project includes a production-ready **`Dockerfile`** and **`docker-compose.yml`** bundling FFmpeg, Unicode fonts, and persistent volumes:

```bash
# Build and run containers in background
docker compose up -d --build
```
Access the application on `http://localhost:8000`.

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

---

## 5. Storage Layout & Data Management

### Directory Structure
```
BookApp/
├── backend/
│   ├── main.py              # FastAPI application (45 REST endpoints & SSE streaming)
│   ├── ai_polisher.py       # Single-Pass Direct AI Translation & Gemini Polish engine
│   ├── comic_translator.py  # Graphic Novel, Scanned PDF & Manga (RTL) Vision AI engine
│   ├── queue_manager.py     # Smart Batch Queue serial engine (max 20 files, retry, auto-pause)
│   ├── database.py          # SQLite WAL persistence (data/bookapp.db) & SHA-256 semantic cache
│   ├── typography.py        # Greek editorial typography and grammar rules
│   ├── genre_detector.py    # Document genre and editorial style detection
│   ├── storage_cleaner.py   # Temporary storage garbage collector (48h retention)
│   ├── format_preserver.py  # In-place DOCX and EPUB layout and style preserver
│   ├── exporter.py          # Exporter for TXT, DOCX, EPUB, PDF, CBZ, CBR & Literature layout
│   ├── glossary.py          # Categorized domain glossary management
│   ├── settings_manager.py  # Local persistent settings manager (config/settings.json)
│   ├── gemini_key_pool.py   # Multi-Key Gemini API Pool & Failover Manager (up to 4 keys)
│   ├── translator.py        # Core translation engine (Google GTX POST + 429 Circuit Breaker)
│   ├── tts_engine.py        # Neural edge-tts voice synthesis & M4B audiobook assembly
│   ├── job_manager.py       # Task lifecycle manager, SQLite sync & file healing
│   └── parsers.py           # Document parsers and comic detection heuristics
├── config/
│   ├── glossary.json        # Categorized custom glossary terms (3,366+ terms across Technical, Literary, General)
│   └── settings.json        # Persistent configuration & API keys (gitignored)
├── data/
│   └── bookapp.db           # Persistent SQLite database (jobs, settings & semantic cache)
├── frontend/                # Single-page application assets (HTML, CSS, JS)
├── temp/
│   ├── uploads/{job_id}/    # Uploaded input documents
│   └── outputs/{job_id}/    # Translated books, checkpoints, and audiobooks
├── tests/                   # 41 Automated test suites (100% PASS rate)
└── requirements.txt
```

### REST API Administration Endpoints
The backend provides **45 REST endpoints** for complete administrative control:
* `POST /api/translate`: Initiates document translation. Supports `quota_behavior: "wait" | "fallback"`.
* `POST /api/audiobook`: Initiates neural audiobook synthesis.
* `GET /api/queue`, `POST /api/queue/add`, `POST /api/queue/start`, `POST /api/queue/pause`, `POST /api/queue/auto-start`, `POST /api/queue/{job_id}/retry`, `GET /api/queue/download-all`, `DELETE /api/queue/{job_id}`, `DELETE /api/queue`: Full Smart Batch Queue administration.
* `DELETE /api/jobs/{job_id}`: Deletes a specific job from memory, database, queue, and purges its upload and output directories.
* `DELETE /api/jobs`: Clears all job history and temporary files (retaining the semantic cache).
* `DELETE /api/jobs/tests/cleanup`: Purges test artifacts, temporary scratch folders, and test-generated jobs from memory, SQLite, and disk (`temp/outputs/` and `temp/uploads/`) while strictly safeguarding real user jobs and translated documents.
* `GET /api/settings`, `POST /api/settings`, `DELETE /api/settings/{key}`: Reads, saves, and deletes configuration parameters.
* `GET /api/gemini/pool`: Returns detailed Multi-Key Pool status (total keys, active keys, individual slot health, and cooldown timestamps).
* `POST /api/gemini/pool`: Configures or updates the pool keys (`{"keys": ["AIzaSy...", ...]}`), clearing quota cooldowns.
* `GET /api/gemini/status`: Returns circuit breaker status, remaining cooldown seconds, and local reset time.
* `POST /api/gemini/reset-quota`: Instantly resets the quota circuit breaker and per-key cooldown timers.
* `GET/HEAD /api/cover/{job_id}`: Inspects and retrieves active cover art.
* `POST /api/cover/{job_id}`: Uploads custom cover artwork (`multipart/form-data`).
* `DELETE /api/cover/{job_id}`: Removes cover artwork for a job.

### Automated Storage Housekeeping
On application startup, `cleanup_old_jobs()` automatically deletes orphaned jobs and folders in `temp/uploads/` and `temp/outputs/` older than 24 hours. For scheduled cleanup in production:

* **On Linux (Cron):**
  ```bash
  # Delete temporary files older than 7 days every night at 03:00 AM
  0 3 * * * find /opt/BookApp/temp/ -type f -mtime +7 -delete
  ```
* **On Windows (PowerShell via Task Scheduler):**
  ```powershell
  Get-ChildItem -Path "C:\Users\User\Documents\BookApp\temp" -Recurse | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force -Recurse
  ```

---

## 6. Automated Test Suite Execution

The repository includes a comprehensive master test runner with **100% endpoint coverage across all 45 FastAPI routes**:

> [!IMPORTANT]
> **User Output Protection & Zero-Junk Guarantee During Test Runs:** Test automation runs safely isolate test jobs and outputs using `DELETE /api/jobs/tests/cleanup`. User translation outputs in `temp/outputs/` and `temp/uploads/` are never wiped during automated test suite execution, and `run_all_tests.py` / `test_e2e_regression_guard.py` automatically back up and restore real user directories and SQLite records. All test sessions, temporary artifacts, and scratch directories created during tests are guaranteed 100% purged upon completion, ensuring zero junk files or test history in the user interface.

```bash
# Execute all 41 test suites (Full Master Suite):
.\.venv\Scripts\python run_all_tests.py

# Fast execution (36 local static, unit, contract, UI, and queue suites in ~48s):
.\.venv\Scripts\python run_all_tests.py --fast
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
37. `test_frontend_contracts_and_ui.py`: HTTP route validation against FastAPI `app.routes`, Pydantic schema validation, and Node.js VM runtime UI tests.
38. `test_gemini_quota_warning.py`: Gemini quota exhaustion detection, circuit breaker lifecycle, and reset verification.
39. `test_quota_behavior_choice.py`: Prior quota routing choice (`wait` vs `fallback`), Free Mode defaults, and session history hygiene.
40. `test_gemini_key_pool.py`: Multi-Key Pool verification (up to 4 keys, rotation, thread-safety, masking, and REST endpoints).
41. `test_gemini_diagnostics.py`: Dedicated API Key Diagnostics & Stress-Test Suite (CRUD, error parsing, sliding-window rate limiting, per-model isolation, E2E 4-key rotation simulation, pool exhaustion, cooldown recovery, transient backoff/retry, concurrency, and live key diagnostics).

All test suites consistently pass with **`41/41 PASS (36/36 in --fast mode · 45/45 FastAPI endpoints verified)`**.

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
| **Scanned PDFs / Graphic Novels have no extracted text** | Document consists purely of bitmap artwork without vector text. | Fully resolved: `detect_is_graphic_novel()` auto-detects scanned PDFs on upload, locks the UI to comic formats, and routes pages to **Gemini Vision AI** workers with opaque background fill and comic lettering. |
| **HTTP 429 rate limit during translation** | Temporary Google GTX rate limit on heavy batch translation. | Fully resolved: `translator.py` features a **20s 429 Circuit Breaker**, fallback to MyMemory, and **automatic failover to Gemini Flash**. Single-Pass AI Polish also bypasses Google Translate entirely. |
| **Queue stalls on Gemini Free Tier daily quota limit** | Exceeded 1,500 requests/day per key on Google AI Studio Free Tier. | Fully resolved: `ai_polisher.py` implements a **Gemini Daily Quota Circuit Breaker** (`DailyQuotaExhaustedError`, `get_gemini_quota_info`). It fails fast in <1ms without sleeping over candidate models. The **Multi-Key Pool** automatically rotates to backup keys (Slots 2–4). When all keys are exhausted, `wait` mode pauses safely at disk checkpoint while `fallback` mode continues with free engines. |
| **Slow AI Polish or timeouts on large books** | Low concurrency, sleep inside semaphore, or hidden thinking token overhead in Gemini 2.5 Flash. | Fully resolved: Upgraded to **5 parallel workers** (`Semaphore(5)`), `thinkingBudget: 0`, HTTP keep-alive connection pooling, and smart multi-page batching, achieving **4x–8x acceleration**. |
| **Cover image downloaded instead of book document** | `cover_image.jpg` was erroneously selected during job recovery. | Fully resolved: Image formats (`.jpg`, `.png`, `.webp`) are strictly excluded from document download candidates. |
| **Lost front matter on initial PDF pages (Table of Contents, Dedication, Prologue)** | Legacy block-level header filtering discarded entire text blocks containing header lines. | Fully resolved: `_clean_page_blocks` filters headers strictly on a line-by-line basis, keeping 100% of front matter text intact. |
| **Audiobook voice stumbles on foreign names** | Neural Greek voice reads Latin characters letter-by-letter. | Fully resolved: Enable **AI Polish for Spoken Audio (style="audiobook")**, which phonetically transcribes names into Greek (`Keeton` ➔ `Κίτον`) and fully writes out numbers and acronyms. |
| **Empty white speech balloons in Graphic Novels** | Dense Greek translations did not fit within `5.0pt` with `insert_textbox` and were silently omitted. | Fully resolved: Two-pass renderer (`_plan_balloon_layout` + `_draw_planned_balloon_text`) draws all inpainting backgrounds first, then renders centered text scaling down to `3.0pt` with `Arial Narrow` fallback. |
