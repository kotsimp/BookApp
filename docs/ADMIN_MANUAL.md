# 🛠️ Εγχειρίδιο Διαχειριστή & Τεχνικής Εγκατάστασης
### (Administrator & Deployment Manual)
**DocTranslate & AudioBook Generator**

Το παρόν εγχειρίδιο απευθύνεται σε διαχειριστές συστημάτων (System Administrators), τεχνικούς πληροφορικής και DevOps engineers που αναλαμβάνουν την εγκατάσταση, διαμόρφωση, λειτουργία και συντήρηση της εφαρμογής **DocTranslate & AudioBook Generator** σε τοπικό περιβάλλον ή διακομιστή (On-Premises / Cloud Server).

---

## 📑 Πίνακας Περιεχομένων
1. [Τεχνική Αρχιτεκτονική](#1-τεχνική-αρχιτεκτονική)
2. [Προαπαιτούμενα Συστήματος](#2-προαπαιτούμενα-συστήματος)
3. [Εγκατάσταση Βήμα-Βήμα](#3-εγκατάσταση-βήμα-βήμα)
4. [Εκτέλεση σε Περιβάλλον Παραγωγής (Production)](#4-εκτέλεση-σε-περιβάλλον-παραγωγής-production)
   - [Επιλογή Α: Windows Service (NSSM)](#επιλογή-α-λειτουργία-ως-windows-service-μέσω-nssm)
   - [Επιλογή Β: Linux Systemd Service](#επιλογή-β-λειτουργία-ως-linux-systemd-service)
   - [Διαμόρφωση Reverse Proxy (Nginx) με SSE](#διαμόρφωση-reverse-proxy-nginx-με-υποστήριξη-sse)
5. [Δομή Αρχείων & Διαχείριση Χώρου (Storage)](#5-δομή-αρχείων--διαχείριση-χώρου-storage)
6. [Εκτέλεση Αυτοματοποιημένων Ελέγχων (Testing)](#6-εκτέλεση-αυτοματοποιημένων-ελέγχων-testing)
7. [Αντιμετώπιση Τεχνικών Προβλημάτων (Troubleshooting)](#7-αντιμετώπιση-τεχνικών-προβλημάτων-troubleshooting)

---

## 1. Τεχνική Αρχιτεκτονική

Η εφαρμογή ακολουθεί αρχιτεκτονική ασύγχρονου API με Event-Driven ροή εργασιών:

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
│ │  - PyMuPDF           │    │  - MP3 Concatenation   │ │
│ │  - EbookLib / BS4    │    │  - Fallback: Nestoras  │ │
│ └──────────────────────┘    └────────────────────────┘ │
└──────────────┬────────────────────────┬────────────────┘
               │ Outbound HTTPS         │ Outbound WSS/HTTPS
               ▼                        ▼
     Google Translate API     Microsoft Speech Services
     (client=gtx endpoint)     (Neural Voices: el-GR, en-US)
```

### Βασικές Τεχνολογίες Backend:
* **FastAPI + Uvicorn:** Υψηλής απόδοσης ασύγχρονος Web server.
* **SQLite Database Layer (`data/bookapp.db`):** Μόνιμη αποθήκευση κατάστασης εργασιών (συμπεριλαμβανομένων ακυρώσεων `cancelled` και αυτόνομου AI Polish), πλήρων μεταδεδομένων ρυθμίσεων (`output_format`, `layout_mode`, `source_lang`, `target_lang`, `ai_polish`, `reading_direction`, `total_pages`, `done_pages`) σε WAL mode (Write-Ahead Logging) με thread-safe κλειδώματα, ασφαλή χειρισμό `None` πεδίων, αυτόματη αποκατάσταση ορφανών `running` & `queued` jobs κατά την εκκίνηση (`db_reset_orphaned_running_jobs`), ανάκτηση `.cbz`/`.cbr`/`.m4b` από το δίσκο και self-healing `file_path` (`_heal_file_path`) για μηδενική απώλεια δεδομένων μετά από επανεκκινήσεις.
* **Smart Batch Queue Engine (`backend/queue_manager.py`):** Σειριακή μηχανή μαζικής μετάφρασης ενοποιημένη στο Upload Card με όριο `MAX_QUEUE_ITEMS = 20` αρχεία ανά παρτίδα (και `MAX_UPLOAD_SIZE_BYTES = 250 MB` ανά αρχείο). Υποστηρίζει δυναμικό συγχρονισμό ρυθμίσεων στο `POST /api/queue/start` (`apply_settings_to_queued_items` με case-insensitive same-language guard), προστασία μικτών παρτίδων (Comics vs Books με αυτόματη απενεργοποίηση Auto-Start σε μικτές ουρές και διατήρηση `layout_mode="comic"`), απομονωμένο child `asyncio.Task` ανά αρχείο (συμβατό με Python 3.9+), `POST /api/queue/{job_id}/retry`, `Pause/Resume`, `Auto-Start`, άμεση μεμονωμένη λήψη για κάθε ολοκληρωμένο item (`GET /api/download/{job_id}`) και εξαγωγή ενιαίου ZIP (`GET /api/queue/download-all`, το οποίο επιστρέφει `HTTP 409` και κρατά το κουμπί **Download All (ZIP)** ανενεργό όσο υπάρχουν items σε κατάσταση `running`/`queued`).
* **Security, Upload Validation & Path Hygiene Guard (`backend/main.py` & `job_manager.py`):** Καθολικός έλεγχος `_validate_job_id()` / `is_valid_job_id()` κατά path traversal σε όλα τα REST endpoints (`/polish`, `/download`, `/cover`, `/jobs/*`, `/preview`, `/debug/extract`) και στο disk recovery, streaming upload με επιβολή ορίου 250 MB (`HTTP 413`) χωρίς OOM, εξυγίανση Windows-illegal & reserved ονομάτων αρχείων (`CON`, `NUL`, `<>:"|?*`), έλεγχος magic headers (`PK`, `%PDF`), προστασία **Zip Slip** στην αποσυμπίεση CBZ (`_safe_extract_zip`), αυστηρός έλεγχος εικόνων εξωφύλλου (`400` σε κατεστραμμένα bytes), έλεγχος ορίων σε `max_chars >= 1`, `max_age_hours >= 1`, voice IDs και prosody (`rate`/`pitch`).
* **Semantic Translation, Polish & Vision Cache (v4):** Σημασιολογική προσωρινή μνήμη βασισμένη σε SHA-256 (`google`, `gemini_polish_v4` με hash ολόκληρου του `system_prompt` ώστε να μην συγκρούονται ποτέ στυλ, γλώσσες, γλωσσάρια ή entity dossiers, και `gemini_comic_vision_v2`) που απορρίπτει αλλοιωμένα/περικομμένα αποτελέσματα και σφάλματα MyMemory πριν την αποθήκευση, με ζωντανά στατιστικά (`GET /api/cache/stats`).
* **Storage Auto-Cleanup Garbage Collector (`backend/storage_cleaner.py`):** Αυτόματος μηχανισμός εκκαθάρισης προσωρινών τμημάτων ήχου, `temp/previews/`, `tts_tmp_*` (M4B), `cbz_*` εξαγωγών και εξαγωγών παλαιότερων των 48 ωρών, προστατεύοντας ενεργές (`running`/`queued`) εργασίες και τελικά αρχεία εξόδου (`POST /api/admin/cleanup`, με `max_age_hours >= 1`).
* **Graphic Novel & Manga (RTL) Comic Engine (`backend/comic_translator.py`):** Προτεραιότητα σε πλήρη Flash Vision μοντέλα (`VISION_MODELS_PRIORITY`), `maxOutputTokens: 8192`, φιλτράρισμα `thought: true`, ανίχνευση mixed-script αλλοιώσεων με αυτόματο failover, **φυσική αριθμητική ταξινόμηση σελίδων CBZ** (`page_1`, `page_2`, ..., `page_10`), προστασία **Zip Slip**, σεβασμός της γλώσσας-στόχου στο vector AI polish, σαφής αποτυχία αν λείπει Gemini API key σε σκαναρισμένο κόμικ, clamping `box_2d` στο `[0..1000]`, ορθή μετατροπή `ΐ`/`ΰ` ➔ `Ϊ`/`Ϋ` σε κεφαλαία μπαλόνια, **two-pass non-blank balloon renderer** (`_plan_balloon_layout` + `_draw_planned_balloon_text`), υποστήριξη Manga RTL, `try...finally` κλείσιμο PyMuPDF handles & καθαρισμός προσωρινών CBZ φακέλων, και `reset_vision_model_cache()` κατά την αλλαγή API key.
* **Greek Editorial Typography Engine (`backend/typography.py`):** Αυτόματη μετατροπή εισαγωγικών σε «...» (με προστασία fenced code blocks ` ``` `), διαλόγων σε em-dash (`—`) χωρίς αλλοίωση αριθμημένων/indented bullets, κανόνας τελικού «ν» με προστασία του αντιθετικού συνδέσμου **«δε»** (π.χ. *«εάν δε προκύψει»*, *«ο δε υπουργός»*) και ακριβή διάκριση στερητικού `μη` έναντι ρηματικού `μην`, συνένωση σπασμένων ενωτικών (`fix_broken_hyphens`) χωρίς συγκόλληση διακοπτόμενων διαλόγων (*«Περίμενε- μην»*), αποκατάσταση αποστρόφων (`fix_greek_elision_apostrophes`) και διόρθωση ελληνικών ερωτηματικών (`;`, `;!`, `;;!!`) με προστασία URLs & σχετικών διαδρομών (`../`).
* **Auto-Genre & Style Detector (`backend/genre_detector.py`):** Ευρετική και γλωσσική ανάλυση κειμένου (ασφαλής σε `None` inputs, με υποστήριξη 2-γράμματων ακρωνυμίων όπως `IP` και φιλτράρισμα TOC/lists από ψευδή ποίηση) για αυτόματη ανίχνευση λογοτεχνίας, ποίησης, τεχνικών, διοικητικών ή comic εγγράφων (`POST /api/detect-genre`).
* **Multi-Voice TTS Engine & M4B Exporter (`backend/tts_engine.py`):** Παραγωγή πολυφωνικών audiobooks (Αφηγητής + Διάλογοι) με case-insensitive & raw-code voice lookup, timeouts σε `edge_tts` (60s) και `ffmpeg` (300s), εγγυημένο καθαρισμό `tts_tmp_*` σε `finally`, language-aware AI polish (χωρίς ελληνική τυπογραφία σε αγγλικά audiobooks), ενσωμάτωση εξωφύλλου τόσο σε `ffmpeg` M4B (`attached_pic`) όσο και σε `mutagen` ID3v2/MP4, και ατομική παραγωγή προεπισκοπήσεων φωνής (`GET /api/tts/preview`).
* **Server-Sent Events (SSE) & Resilient Frontend (`frontend/app.js`):** Thread-safe SSE ενημερώσεις προόδου (0–100%) με διατήρηση συνδρομητών σε γεμάτη ουρά, άμεσο κλείσιμο stream σε τερματικές καταστάσεις (`done`/`error`/`cancelled`), δυναμικό `API` origin (`window.location.origin`), `parseApiError()` για HTTP 422/500/non-JSON, `stopJobTracking()` καθαρισμό EventSource/timers και XSS-safe `data-source` διαχείριση γλωσσαρίου.
* **PyMuPDF (fitz), Parsers & Format Preserver (`parsers.py`, `format_preserver.py`, `exporter.py`):** Ασφαλές κλείσιμο handles (`with`/`try...finally`), σαφής απόρριψη κρυπτογραφημένων PDF, εξαγωγή πινάκων DOCX, ανάγνωση EPUB σε **spine order** με αφαίρεση `<style>`/`<script>`, fallback κωδικοποιήσεων TXT (UTF-8/UTF-16/CP1253), in-place DOCX μετάφραση με διατήρηση ενσωματωμένων εικόνων (`<w:drawing>`) & deduplication συγχωνευμένων κελιών, in-place EPUB μετάφραση χωρίς διπλο-μετάφραση ένθετων tags (`<blockquote><p><em>`) ή σχολίων HTML, και προστασία από κενά PDF/EPUB και XML control characters.
* **edge-tts:** Παραγωγή ήχου μέσω των δωρεάν νευρωνικών φωνών της Microsoft.
* **On-Demand Dynamic Exporter:** Δυναμική εξαγωγή σε οποιαδήποτε υποστηριζόμενη μορφή (`format=pdf|docx|epub|txt`) κατά τη λήψη, χωρίς επανυπολογισμό μετάφρασης.
* **Wingdings / PUA, Glyph & URL Normalizer (`exporter.py`):** Αυτόματη μετατροπή συμβόλων Private Use Area (`\ue000`–`\uf8ff`) σε πρότυπες Unicode κουκίδες (`•`) και native στυλ `List Bullet`, αφαίρεση `\ufffd`/C1/zero-width χαρακτήρων, έλεγχος κάθε γλύφου ανά γραμματοσειρά PDF (`_sanitize_for_pdf_font` μέσω `font_obj.has_glyph`, μηδέν tofu `□` κουτάκια) και αυτόματη αναδίπλωση μεγάλων αδιάσπαστων URLs/tokens εντός περιθωρίων (`_split_oversized_token`).
* **Interactive Translation Editor:** Αμφίδρομη ανάγνωση και ενημέρωση μεταφρασμένου κειμένου (`GET`/`PUT /api/jobs/{job_id}/text`) με αυτόματο re-exporting, άμεση ανάγνωση pre-extracted `*_original.txt` και διατήρηση του αρχικού `file_type` κατά το disk recovery.
* **Robust Translator Engine (HTTP POST & Validation):** Αποστολή αιτημάτων μετάφρασης μέσω HTTP POST στο Google GTX client API (`https://translate.googleapis.com/translate_a/single`), εξαλείφοντας περιορισμούς μήκους URI. Αυτόματος έλεγχος ελληνικών χαρακτήρων (`has_greek_text`) με εκθετικό backoff για αποτροπή σιωπηλών επιστροφών στα Αγγλικά.
* **Optimized AI Polisher & Single-Pass Translator (Gemini):** Ασύγχρονη επιμέλεια και απευθείας μετάφραση μέσω Google Gemini API (`POST /api/polish` & Single-Pass) με **προτεραιότητα στα πλήρη Flash μοντέλα** έναντι Flash-Lite, `maxOutputTokens: 16384`, `thinkingBudget: 0` (2.5 & 3.x Flash), `safetySettings: BLOCK_NONE`, `promptFeedback.blockReason` / `_ContentBlockedError` detection, smart multi-page batching (`5.500 chars / max 3 σελίδες`), transient cooldown retry και `Semaphore(5)`. Περιλαμβάνει:
  * **Output Sanitizer, Boundary Deduplicator & Quality Gate (`sanitize_ai_output`, `_deduplicate_batch_boundary`, `detect_greek_output_issues`):** Φιλτράρισμα `thought: true` parts, αφαίρεση leaked HTML tags (`</i>`), special tokens (`<bos>`), `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` / XML wrapper tags, `[... ...]` context echoes, σημειώσεων επιμελητή & CoT chatter, ντετερμινιστικό αποδιπλασιασμό ορίων batch (pre-marker stripping + fuzzy overlap dedup), στοχευμένο retry για mixed-script λέξεις (`_find_mixed_script_tokens`) χωρίς υποβάθμιση σε Flash-Lite και **αναδρομικό διχασμό (Multi-Page ➔ Single-Page ➔ Paragraph halves)** σε `MAX_TOKENS`, `_ContentBlockedError`, χαμένους δείκτες σελίδων, περικοπή ή timeout.
  * **Source-Anchored Verification:** Δίγλωσση σύγκριση ανά σελίδα (`<SOURCE_REFERENCE>` vs `<DRAFT_TO_POLISH>`) του ελληνικού προσχεδίου με το πρωτότυπο αγγλικό κείμενο για εξάλειψη παρερμηνειών και αγγλισμών.
  * **Audiobook Script Polish & Spoken Phonetics:** Φωνητική μεταγραφή ξένων ονομάτων και ακρωνυμίων σε ελληνικούς χαρακτήρες (π.χ. `Keeton` ➔ `Κίτον`, `Theseus` ➔ `Θησέας`, `DNA` ➔ `Ντι-Εν-Έι`), πλήρης ολογράφως ανάπτυξη αριθμών/ετών/ποσοστών και αφαίρεση μη εκφωνήσιμων συμβόλων.
  * **Whole-Book Stratified Entity Dossier (`_build_stratified_book_sample`):** Σάρωση συχνότητας κύριων ονομάτων σε **ολόκληρο το βιβλίο** + 9 στρωματοποιημένα δείγματα (0%–95%) για εξαγωγή 35–60 όρων με ρητό γραμματικό γένος (`ο/η/το`) και αυστηρό διαχωρισμό διακριτών οντοτήτων, σε συνδυασμό με ενιαία στίξη διαλόγων (`«...»`) στο `STYLE_PROMPTS["literature"]`.
  * **Clean Tail Context & Smart Real-Time Checkpointing:** Εξαγωγή 1–2 ολοκληρωμένων προηγούμενων προτάσεων (`_extract_clean_tail_context`), αποθήκευση προόδου στο δίσκο (`.polish_checkpoint.json` / `.direct_ai_checkpoint.json`) και ενοποιημένο `POLISH_STATUS` μέσω `get_polish_job_status()` / `update_polish_job_status()`.
* **Cover Image Management:** Πλήρης υποστήριξη εξαγωγής (με καθαρό κλείσιμο PDF handles μέσω context manager) και διαχείρισης εξωφύλλων (`GET/HEAD /api/cover/{job_id}`, `POST /api/cover/{job_id}`, `DELETE /api/cover/{job_id}`).
* **Persistent Settings Manager:** Αποθήκευση και διαγραφή ρυθμίσεων στο `config/settings.json` μέσω `GET`/`POST`/`DELETE /api/settings` (με ταυτόχρονο reset τόσο του text όσο και του comic vision model cache).
* **Literature / E-Reader Formatter:** Λειτουργία `layout=literature` για εξαγωγή 6×9 trade-paperback PDF/DOCX (Georgia + Georgia Italic/Bold για πραγματικά `*πλάγια*`/`**έντονα**`, `_sanitize_for_pdf_font` για μηδέν tofu `□`, `_split_oversized_token` για καθαρή αναδίπλωση URLs) και reflowable Kindle/iPad EPUB (`<em>`/`<strong>`) με TOC.
* **Multi-Page Front Matter Preservation:** Καθαρισμός κεφαλίδων σε επίπεδο γραμμής (`_clean_page_blocks`), διασφαλίζοντας ότι πίνακες περιεχομένων, προμετωπίδες (epigraphs) και πρόλογοι στις αρχικές σελίδες διατηρούνται 100% ακέραιοι.
* **Style-Aware Categorized Glossary Engine:** Κατηγοριοποιημένη ορολογία (`technical`, `literary`, `general`) με hyphen-safe word boundaries (`(?<![\w-])` / `(?![\w-])`), αυτόματο αποκλεισμό IT όρων σε λογοτεχνία/comics/audiobooks και προστασία αγγλικών βιβλιογραφικών γραμμών (`GET`/`POST`/`DELETE /api/glossary`).
* **Multi-Key Gemini API Pool & Failover Manager (`backend/gemini_key_pool.py`):**
  * Διαχείριση έως και **4 δωρεάν Google Gemini API Keys** ταυτόχρονα (`gemini_api_keys` στο `config/settings.json`), προσφέροντας έως και 6.000 δωρεάν αιτήματα/ημέρα ($0 κόστος).
  * Αυτόματη, ακαριαία εναλλαγή (Failover / Rotation) σε επόμενο διαθέσιμο κλειδί (Slot 1 ➔ Slot 2 ➔ Slot 3 ➔ Slot 4) μόλις εντοπιστεί κωδικός HTTP 429 ή εξάντληση ημερήσιου ορίου, χωρίς διακοπή εργασίας ή απώλεια προόδου.
  * Thread-safe χρονοδιακόπτες cooldown ανά κλειδί (`_KEY_COOLDOWNS`), ασφαλής απόκρυψη κλειδιών (`mask_api_key`), και αναλυτικά διαγνωστικά REST endpoints (`GET /api/gemini/pool`, `POST /api/gemini/pool`).
  * Ενεργοποίηση του καθολικού Circuit Breaker και του χρονοδιακόπτη αναμονής μόνο εάν εξαντληθούν όλα τα ρυθμισμένα κλειδιά του pool.
* **Dual-Mode UI Architecture: Basic vs Advanced Mode (`frontend/app.js`, `frontend/style.css`):**
  * **⚡ Basic Mode (Απλή Λειτουργία — Προεπιλογή):** Εστίαση στην ταχύτητα και μέγιστη απλότητα. Το AI Polish είναι ενεργό από προεπιλογή (`tr-ai-polish.checked = true`, `ab-ai-polish.checked = true`), το format εξόδου ταυτίζεται αυτόματα με το αρχείο εισόδου, και το audiobook προεπιλέγει αυτόματα τη φωνή Νέστορας (`el-GR-NestorasNeural`) σε λογοτεχνικό ρυθμό (`literature:-12%`). Όλες οι περιττές επιλογές αποκρύπτονται μέσω CSS `.mode-advanced-only.is-hidden`.
  * **⚙️ Advanced Mode (Προχωρημένη Λειτουργία):** Πλήρης έλεγχος σε όλες τις παραμέτρους (επιλογείς format, στυλ διάταξης, Manga RTL, εξώφυλλα, Voice Grid, sliders ταχύτητας/pitch, πολυφωνία και διακόπτης συμπεριφοράς εξάντλησης ορίου Gemini `wait` vs `fallback`).
  * Διατήρηση κατάστασης μέσω `localStorage` (`bookapp_ui_mode`), με ασφαλείς DOM guards και άμεση εφαρμογή σε κάθε συνεδρία (`applyAppMode`).
* **Distraction-Free Reader, Smart Resume Banner & Pro Audio Player (`frontend/app.js`, `frontend/style.css`):**
  * **Distraction-Free Reader (`#reader-modal`):** Πλήρης ενσωματωμένος αναγνώστης με serif τυπογραφία, 3 θέματα (Paper `#fbfbfb`, Sepia `#f6eedb`, Dark `#0f111a`), κλιμάκωση γραμματοσειράς και υποστήριξη παράθεσης (Side-by-Side: Original ↔ Greek).
  * **Smart Resume Banner (`#smart-resume-banner`):** Αυτόματος εντοπισμός διακοπεισών εργασιών με αποθηκευμένο checkpoint κατά την είσοδο στην εφαρμογή και άμεση συνέχιση με 1 κλικ.
  * **Live ETA & Throughput Meter (`.progress-eta`):** Ζωντανός υπολογισμός υπολειπόμενου χρόνου (`~Χλ Υδ`) και ρυθμού επεξεργασίας (`σελ/λ` ή `batches/δ`).
  * **Hybrid Engine Badge (`.engine-pill`):** Οπτική ένδειξη ενεργού κινητήρα (`✨ Gemini Flash` vs `⚡ Free Engine` vs `⚡ Edge-TTS Neural`).
  * **Pro Audiobook Player (`#ab-player-container`):** Ενσωματωμένος player με presets ταχύτητας (`0.8x`, `1.0x`, `1.2x`, `1.5x`), κουμπιά skip 15s (`⏪`, `⏩`) και πλοήγηση κεφαλαίων.
  * **Contextual Voice Audition:** Δυνατότητα δοκιμής νευρωνικής φωνής με πραγματικό απόσπασμα του βιβλίου ή προσαρμοσμένο κείμενο (`#ab-custom-preview-text`).

---

## 2. Προαπαιτούμενα Συστήματος

### Λειτουργικό Σύστημα
* **Windows:** Windows 10, Windows 11 ή Windows Server 2016/2019/2022.
* **Linux:** Ubuntu 20.04+, Debian 11+, RHEL/CentOS 8+, AlmaLinux/Rocky Linux.
* **macOS:** macOS 11 Big Sur ή νεότερο.

### Λογισμικό
* **Python 3.9 έως 3.15** εγκατεστημένη στο σύστημα με `pip` και `venv` (πλήρης συμβατότητα με `asyncio.get_running_loop()`).
* **Git** (για λήψη και ενημέρωση του κώδικα).

### Δικτυακές Απαιτήσεις (Firewall / Network Rules)
* **Inbound:**
  * Θύρα `8000` (ή `80`/`443` αν εκτελείται μέσω Reverse Proxy) προσβάσιμη από τους χρήστες του τοπικού δικτύου.
* **Outbound (απαραίτητη πρόσβαση στο διαδίκτυο):**
  * `translate.googleapis.com:443` (HTTPS) για τις μεταφράσεις.
  * `*.speech.microsoft.com:443` (WSS / HTTPS) για τις νευρωνικές φωνές του Audiobook.

---

## 3. Εγκατάσταση Βήμα-Βήμα

### Βήμα 1: Λήψη Αποθετηρίου
```bash
git clone https://github.com/kotsimp/BookApp.git
cd BookApp
```

### Βήμα 2: Δημιουργία και Ενεργοποίηση Virtual Environment
* **Σε Windows (PowerShell / Command Prompt):**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\activate
  ```
* **Σε Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### Βήμα 3: Εγκατάσταση Εξαρτήσεων
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Βήμα 4: Δοκιμαστική Εκκίνηση
```bash
python run.py
```
*Η εφαρμογή θα ξεκινήσει στη διεύθυνση `http://localhost:8000` και θα ανοίξει αυτόματα τον browser.*

---

## 4. Εκτέλεση σε Περιβάλλον Παραγωγής (Production)

Για μόνιμη λειτουργία 24/7 σε server χωρίς την ανάγκη ανοιχτού παραθύρου τερματικού, προτείνεται η λειτουργία ως Service.

### Επιλογή Α: Λειτουργία ως Windows Service (μέσω NSSM)

1. Κατεβάστε το [NSSM (Non-Sucking Service Manager)](https://nssm.cc/download).
2. Ανοίξτε το PowerShell ως Διαχειριστής (Administrator) και εκτελέστε:
   ```powershell
   nssm install BookApp
   ```
3. Στο παράθυρο διαλόγου ρυθμίστε:
   * **Path:** `C:\Users\User\Documents\BookApp\.venv\Scripts\uvicorn.exe`
   * **Startup directory:** `C:\Users\User\Documents\BookApp`
   * **Arguments:** `backend.main:app --host 0.0.0.0 --port 8000 --log-level info`
4. Εκκινήστε το Service:
   ```powershell
   nssm start BookApp
   ```

### Επιλογή Β: Λειτουργία ως Linux Systemd Service

1. Δημιουργήστε το αρχείο μονάδας systemd:
   ```bash
   sudo nano /etc/systemd/system/bookapp.service
   ```
2. Προσθέστε την ακόλουθη παραμετροποίηση:
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
3. Ενεργοποιήστε και εκκινήστε την υπηρεσία:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable bookapp
   sudo systemctl start bookapp
   sudo systemctl status bookapp
   ```

---

### Διαμόρφωση Reverse Proxy (Nginx) με υποστήριξη SSE

Επειδή η εφαρμογή χρησιμοποιεί **Server-Sent Events (SSE)** για τη ζωντανή ροή της μπάρας προόδου, είναι **κρίσιμο** να απενεργοποιηθεί το proxy buffering στο Nginx:

```nginx
server {
    listen 80;
    server_name bookapp.internal.domain;

    client_max_body_size 250M;  # Επιτρέπει μεγάλα PDF/EPUB/Graphic Novels (έως 250 MB)

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # Ρυθμίσεις για Server-Sent Events (SSE)
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;

        # Standard headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 5. Δομή Αρχείων & Διαχείριση Χώρου (Storage)

### Δομή Καταλόγων:
```
BookApp/
├── backend/
│   ├── main.py              # FastAPI endpoints (45 REST routes & SSE streaming)
│   ├── ai_polisher.py       # Single-Pass AI Translation & Gemini Polish (Semaphore(5), thinkingBudget: 0)
│   ├── comic_translator.py  # Graphic Novel / Scanned PDF / Manga (RTL) Vision AI (4 parallel workers)
│   ├── queue_manager.py     # Smart Batch Queue serial engine (max 20 files, isolated cancel, retry)
│   ├── database.py          # SQLite WAL persistence (data/bookapp.db) & SHA-256 semantic cache
│   ├── typography.py        # Ελληνική εκδοτική τυπογραφία & κανόνας τελικού «ν»
│   ├── genre_detector.py    # Αυτόματη ανίχνευση είδους/ύφους εγγράφου
│   ├── storage_cleaner.py   # Garbage collector προσωρινών αρχείων (48h)
│   ├── format_preserver.py  # In-place DOCX/EPUB styling preservation
│   ├── exporter.py          # Εξαγωγή TXT, DOCX, EPUB, Rich PDF, CBZ, CBR & Literature layout
│   ├── glossary.py          # Διαχείριση κατηγοριοποιημένου γλωσσαρίου όρων
│   ├── settings_manager.py  # Αποθήκευση/ανάγνωση ρυθμίσεων (config/settings.json)
│   ├── gemini_key_pool.py   # Multi-Key Gemini API Pool & Failover Manager (up to 4 keys)
│   ├── translator.py        # Μηχανή μετάφρασης (Google GTX POST + 429 Circuit Breaker + Gemini failover)
│   ├── tts_engine.py        # Πολυφωνική παραγωγή ήχου edge-tts (Nestoras / Athina) & M4B export
│   ├── job_manager.py       # Διαχείριση εργασιών, SQLite metadata sync, file_path healing & cleanup
│   └── parsers.py           # Αναλυτές PDF, DOCX, EPUB, CBZ & detect_is_graphic_novel()
├── config/
│   ├── glossary.json        # Αποθηκευμένο γλωσσάρι όρων
│   └── settings.json        # Τοπικές ρυθμίσεις & API keys (gitignored)
├── data/
│   └── bookapp.db           # Μόνιμη SQLite βάση (jobs, metadata & semantic cache)
├── frontend/                # Static files (HTML, CSS, JS)
├── temp/
│   ├── uploads/{job_id}/    # Αποθηκευμένα αρχεία εισόδου
│   └── outputs/{job_id}/    # Μεταφρασμένα αρχεία, checkpoints και MP3/M4B audiobooks
├── tests/                   # 40 Αυτοματοποιημένα test suites (100% PASS)
└── requirements.txt
```

### Διαχείριση Εργασιών, Ουράς, Ρυθμίσεων & Εξωφύλλων μέσω REST Endpoints
Η εφαρμογή παρέχει ολοκληρωμένο REST API (**45 endpoints**) για τη διαχείριση εργασιών, Smart Batch Queue, ρυθμίσεων, Gemini Multi-Key Pool, επιλογών Quota και εικόνων εξωφύλλου:
* `POST /api/translate`: Εκκίνηση μετάφρασης. Υποστηρίζει `quota_behavior: "wait" | "fallback"` (προεπιλογή `"fallback"` όταν δεν υπάρχει API Key).
* `POST /api/audiobook`: Εκκίνηση παραγωγής ηχοβιβλίου. Υποστηρίζει `quota_behavior: "wait" | "fallback"` (αυτόματη χρήση Edge-TTS χωρίς διακοπή).
* `GET /api/queue`, `POST /api/queue/add`, `POST /api/queue/start`, `POST /api/queue/pause`, `POST /api/queue/auto-start`, `POST /api/queue/{job_id}/retry`, `GET /api/queue/download-all`, `DELETE /api/queue/{job_id}`, `DELETE /api/queue`: Πλήρης διαχείριση της Smart Batch Queue (έως 20 αρχεία, συγχρονισμός ρυθμίσεων και `quota_behavior` στο start, retry, pause/resume, ZIP export).
* `DELETE /api/jobs/{job_id}`: Διαγράφει συγκεκριμένη εργασία από τη μνήμη, τη SQLite, την ουρά και αφαιρεί οριστικά τους φακέλους `temp/uploads/{job_id}` και `temp/outputs/{job_id}` από το δίσκο.
* `DELETE /api/jobs`: Καθαρίζει ολόκληρο το ιστορικό, την ουρά και τα προσωρινά αρχεία (διατηρώντας τη `translation_cache`).
* `DELETE /api/jobs/tests/cleanup`: Καθαρίζει άμεσα όλα τα δοκιμαστικά αρχεία/εργασίες που δημιουργήθηκαν από αυτοματοποιημένα τεστ (prefixes `test_`, `reg_`, `mock_`, κ.λπ.) από τη βάση SQLite, τη μνήμη και τους φακέλους `temp/`, διατηρώντας ανέπαφο το πραγματικό ιστορικό του χρήστη.
* `GET /api/jobs?include_tests=true`: Προαιρετική παράμετρος ανάκτησης εργασιών. Από προεπιλογή (`include_tests=false`), τα δοκιμαστικά αρχεία φιλτράρονται αυτόματα ώστε να μην εμφανίζονται ποτέ στο Session History του UI.
* `GET /api/settings`, `POST /api/settings`, `DELETE /api/settings/{key}`: Ανάγνωση, αποθήκευση και διαγραφή τοπικών ρυθμίσεων. Υποστηρίζει `gemini_api_keys: list[str]` (έως 4 κλειδιά για το Gemini Pool). Το `GET /api/settings` επιστρέφει `{"gemini_api_key", "gemini_api_keys", "pool", "default_quota_behavior", "has_gemini_key", "default_engine"}`. Κατά την αποθήκευση νέου κλειδιού ή pool, μηδενίζεται αυτόματα ο cooldown διακόπτης του Gemini.
* `GET /api/gemini/pool`: Επιστρέφει την αναλυτική κατάσταση του Gemini Multi-Key Pool (σύνολο κλειδιών, διαθέσιμα κλειδιά, κατάσταση κάθε slot ξεχωριστά με ένδειξη `is_active`, `is_exhausted`, χρόνο αναμονής και ακριβή ώρα επαναφοράς).
* `POST /api/gemini/pool`: Ρύθμιση ή ενημέρωση της λίστας κλειδιών του pool (`{"keys": ["AIzaSy...", ...]}`), αυτόματος μηδενισμός quota cooldowns και εκκαθάριση των caches μοντέλων.
* `GET /api/gemini/status`: Επιστρέφει την κατάσταση του διακόπτη προστασίας Gemini Quota (`exhausted: bool`), τα εναπομείναντα δευτερόλεπτα (`remaining_seconds: int`), το Unix timestamp επαναφοράς (`reset_timestamp: float`), την ακριβή τοπική ώρα επαναφοράς (`reset_time_str: "HH:MM:SS"`), το φορμαρισμένο κείμενο (`cooldown_time_str`), το αντικείμενο `pool` και το αναλυτικό μήνυμα προς το χρήστη.
* `POST /api/gemini/reset-quota`: Μηδενίζει άμεσα τον διακόπτη προστασίας Quota Circuit Breaker και όλα τα per-key cooldowns στο Multi-Key Pool, αποκαθιστώντας την άμεση διαθεσιμότητα των κλήσεων AI Polish.
* `GET/HEAD /api/cover/{job_id}`: Ελέγχει αν υπάρχει ενεργό εξώφυλλο για τη συγκεκριμένη εργασία και επιστρέφει το αρχείο εικόνας.
* `POST /api/cover/{job_id}`: Ανέβασμα νέου προσαρμοσμένου εξωφύλλου (`multipart/form-data`) με αυτόματη ενημέρωση των αρχείων εξόδου.
* `DELETE /api/cover/{job_id}`: Αφαίρεση του εξωφύλλου για τη συγκεκριμένη εργασία.

### Ακεραιότητα Εξαγωγής & Απομόνωση Εξωφύλλων
Για να αποφευχθεί η εσφαλμένη λήψη εικόνων εξωφύλλου (`cover_image.jpg`) αντί για το πλήρες έγγραφο του βιβλίου, το υποσύστημα `job_manager.py` και το endpoint `GET /api/download/{job_id}` εξαιρούν ρητά όλα τα αρχεία εικόνων (`.jpg`, `.jpeg`, `.png`, `.webp`) από τις υποψήφιες εξόδους εγγράφων.

### Αυτόματος Καθαρισμός Προσωρινών Αρχείων (Housekeeping)
Κατά την εκκίνηση της εφαρμογής, η συνάρτηση `cleanup_old_jobs()` καθαρίζει αυτόματα παλαιές εργασίες και φακέλους στο `temp/uploads/` και `temp/outputs/` που είναι παλαιότεροι των 24 ωρών (`86400s`). Για πρόσθετο περιοδικό καθαρισμό σε περιβάλλον παραγωγής χωρίς επανεκκίνηση:

* **Σε Linux (Cron Job):**
  ```bash
  # Καθημερινός καθαρισμός αρχείων παλαιότερων των 7 ημερών στις 03:00 π.μ.
  0 3 * * * find /opt/BookApp/temp/ -type f -mtime +7 -delete
  ```
* **Σε Windows (PowerShell Script μέσω Task Scheduler):**
  ```powershell
  Get-ChildItem -Path "C:\Users\User\Documents\BookApp\temp" -Recurse | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force -Recurse
  ```

---

## 6. Εκτέλεση Αυτοματοποιημένων Ελέγχων (Testing)

Η εφαρμογή περιλαμβάνει θωρακισμένη (**bulletproof**) σουίτα **40 αυτοματοποιημένων ελέγχων (test suites)** στο φάκελο `tests/` με **100% κάλυψη όλων των 45 FastAPI endpoints**, αυτόματη προστασία/επαναφορά του `config/settings.json` (ώστε τα tests να μην διαγράφουν ή αλλοιώνουν ποτέ το API Key του χρήστη), αυτόματο καθαρισμό test sessions μετά την ολοκλήρωση και αυτόματη εκκίνηση προσωρινού Uvicorn server αν δεν τρέχει ήδη:

```bash
# Εκτέλεση όλων των 40 suites (Full Suite):
.\.venv\Scripts\python run_all_tests.py

# Ταχεία εκτέλεση (35 local static/unit/security/contract/resilience/UI/queue/benchmark suites σε ~45s):
.\.venv\Scripts\python run_all_tests.py --fast
```

Ο master runner ανακαλύπτει και εκτελεί αυτόματα όλες τις **40 σουίτες δοκιμών**:
1. `test_ai_polish_advanced.py`: Δίγλωσση επιμέλεια, Audiobook phonetics, consistency dossier & checkpoints.
2. `test_ai_polisher_deep.py`: Όλα τα 6 στυλ επιμέλειας, temperatures, multi-page splitting, cache invalidation, `BLOCK_NONE` & `promptFeedback`, αναδρομικός διχασμός (pages ➔ paragraphs) σε safety blocks, αποδιπλασιασμός ορίων & `[...]` sanitization, whole-book stratified dossier sampling και mixed-script token detector (9 tests).
3. `test_api.py`: Ολοκληρωμένοι έλεγχοι REST endpoints, upload, translation & streaming.
4. `test_categorized_glossary.py`: Κατηγοριοποιημένο γλωσσάρι (Technical, Literature, General).
5. `test_code_health.py`: **10-σημείων στατικός φύλακας υγείας κώδικα:** AST/Syntax, Unbound Locals, Import Integrity, Unreachable Code, Undefined Globals & Missing Submodule Imports, Unused Imports & Deprecated FastAPI APIs, Frontend HTML⇄JS Cross-Integrity & UI Contracts, Production Config Hygiene, Frontend `${API}`⇄Backend Route Alignment (0 silent 404s) και 100% Backend Endpoint Test Coverage Guard.
6. `test_comic_translation.py`: Μετάφραση Graphic Novels (PDF, CBZ, CBR, EPUB) και απαγόρευση TXT/DOCX.
7. `test_concurrency_and_stress.py`: Stress test 50 παράλληλων jobs, multi-thread settings με καθαρό teardown, SSE queues.
8. `test_database_and_cache.py`: SQLite persistence (`data/bookapp.db`), restart recovery & SHA-256 cache.
9. `test_document_integrity_and_encoding.py`: BOM, UTF-16, CP1253, πολυτονικά ελληνικά, corrupted file handling.
10. `test_dynamic_download.py`: Άμεση αλλαγή φορμάτ κατά τη λήψη χωρίς επανυπολογισμό.
11. `test_e2e_regression_guard.py`: **10-σημείων E2E φύλακας παλινδρόμησης:** Single-Job Delete & Clear All (`DELETE /api/jobs`) σε API + SQLite (με διατήρηση cache και προστασία ιστορικού), DOCX + AI Polish Single-Pass, Invalid API key fail-fast (<1s), `/health`, `/preview/{id}`, `/cover/{id}` (POST/GET/DELETE), `/debug/extract/{id}`, `/polish/status/{id}`, `/progress/{id}` SSE, Source-Anchored identical-text auto-disable, Google 429 Circuit Breaker, επανεκκίνηση `cancelled` jobs & ανάκτηση ορφανών `running` jobs, SQLite `file_path` persistence & πλήρης επαναφορά ρυθμίσεων στο Resume, καθώς και καθαρισμός & απομόνωση δοκιμαστικών εργασιών (`DELETE /api/jobs/tests/cleanup`).
12. `test_edge_cases_and_robustness.py`: Οριακές περιπτώσεις, ακραία inputs και ανθεκτικότητα.
13. `test_editor_glossary_ai.py`: In-browser Editor, κανόνες γλωσσαρίου και AI Polish.
14. `test_exporter.py`: Εξαγωγή σε DOCX, PDF, EPUB, TXT, CBZ, CBR.
15. `test_format_preservation.py`: Διατήρηση μορφοποίησης, πινάκων και στυλ σε DOCX/EPUB.
16. `test_literature_formatting.py`: Λογοτεχνικό layout, καθαρισμός κεφαλίδων, κεφάλαια, εσοχές.
17. `test_manga_rtl_and_balloon_fit.py`: Japanese Manga RTL φορά ανάγνωσης και fit-to-box κλιμάκωση.
18. `test_multivoice_and_m4b.py`: Πολυφωνική αφήγηση, speaker tags, ID3 cover tagging και M4B export.
19. `test_new_api_endpoints.py`: Αυτοματοποιημένοι HTTP integration έλεγχοι για `/api/detect-genre`, `/api/tts/preview`, `/api/cache/stats` και `/api/admin/cleanup`.
20. `test_parsers.py`: Αναλυτές PDF, DOCX, EPUB, CBZ, TXT και auto-detection Graphic Novels.
21. `test_pdf_initial_pages_preservation.py`: Ακέραιη διατήρηση αρχικών σελίδων (TOC, πρόλογος).
22. `test_performance_and_benchmarks.py`: Benchmarks υψηλού φόρτου (SQLite WAL cache throughput, Typography 100k λέξεων <0.1s, Genre detector, Glossary regex 50k λέξεων).
23. `test_poetry_pauses.py`: Ποιητική απαγγελία, εκθλίψεις, αποκοπές, άνω τελεία, διασκελισμός.
24. `test_scanned_comic_and_autodetect.py`: Αυτόματη ανίχνευση σκαναρισμένων Graphic Novel PDFs vs μυθιστορημάτων, pixel-level έλεγχος αδιαφανούς διαγραφής αγγλικών pixels σε μπαλόνια, και Single-Pass Direct AI για EPUB.
25. `test_standalone_ai_polish.py`: Αυτόνομο AI Polish χωρίς προηγούμενη μετάφραση (με προστασία ρυθμίσεων).
26. `test_translator.py`: Μηχανή μετάφρασης GTX POST, 429 circuit breaker, Gemini failover.
27. `test_tts_audiobook_deep.py`: Κατάλογος φωνών, prosody, συνένωση chunks, ακύρωση in-flight.
28. `test_typography_and_genre.py`: Ελληνική τυπογραφία, κανόνας τελικού «ν», αυτόματη ανίχνευση είδους.
29. `test_smart_batch_queue.py`: Πλήρης κύκλος ζωής Smart Batch Queue (`/api/queue/*`), όριο 20 αρχείων, συγχρονισμός ρυθμίσεων στο `/queue/start` σε μικτές παρτίδες (Comic + Book), απομονωμένη ακύρωση running item, Pause/Resume, Retry (`/queue/{id}/retry`), validation (400/404/0-byte DOCX), History-Delete sync, λήψη ενιαίου ZIP (`/api/queue/download-all`) και ανθεκτική ανάκτηση κακοσχηματισμένου Vision JSON (`_parse_vision_json`).
30. `test_translation_quality_fixes.py`: Ολοκληρωμένος έλεγχος ποιότητας ελληνικής μετάφρασης, αφαίρεσης HTML/LLM tokens/CoT leaks, ανίχνευσης mixed-script αλλοιώσεων & περικοπών, προτεραιότητας Full Flash μοντέλων, στερητικού `μη` vs ρηματικού `μην`, απομόνωσης τεχνικού γλωσσαρίου από λογοτεχνία & σύνθετες λέξεις, απόδοσης πλάγιων γραμμάτων σε PDF/DOCX/EPUB, two-pass non-blank comic balloon rendering, μηδέν tofu `□` glyphs και αναδίπλωσης μεγάλων URLs σε PDF (10 tests).
31. `test_security_and_input_validation.py`: Καθολικός έλεγχος path traversal (`job_id` σε `/polish`, `/download`, `/cover`, `/jobs/*`, `/preview`, `/debug/extract`, `job_manager`), voice preview sanitization, Windows-illegal/reserved filenames (`CON`, `<>:"|?*`), απόρριψη κατεστραμμένων cover bytes, `POST /polish` με `job_id: null` (Direct Editor), invalid `?format=`, `max_chars <= 0`, `max_age_hours <= 0`, case-insensitive same-lang και TTS prosody bounds.
32. `test_api_contracts_and_state_machine.py`: Έλεγχος λήψης TXT/DOCX σε κανονικά PDF βιβλία (χωρίς ψευδές comic 400), `HEAD /download` χωρίς side-effects, άμεσο κλείσιμο SSE `/progress` σε τερματικές εργασίες, προστασία `*_original.txt` στο `PUT /text`, αυτόνομη εξαγωγή αρχείου στο `POST /polish` (`text=None`), προστασία `done` jobs από `cancel`, ανανέωση εξαγωγών στο `DELETE /cover` και `HTTP 409` gating στο `GET /api/queue/download-all` όσο υπάρχουν ενεργές μεταφράσεις (με παράλληλη διαθεσιμότητα μεμονωμένου `GET /api/download/{job_id}`).
33. `test_ai_polisher_and_translator_resilience.py`: Mocked `aiohttp` HTTP resilience tests (χωρίς `AQ.Test*` παράκαμψη): απομόνωση cache key (full prompt SHA-256), μη-διαρροή API key σε URL, double-400 (`thinkingConfig` + `safetySettings`) retry, `TimeoutError` καταγραφή, 100% batch-failure loud error, 3-line `PAGE` marker CoT reset, εξαίρεση SI units (`μm`, `Δt`, `Ωm`), προστασία αγγλικών audiobooks, case-insensitive `LANG_CODES`, κακοσχηματισμένο GTX JSON και απόρριψη MyMemory HTTP-200 error μηνυμάτων.
34. `test_pipeline_data_integrity.py`: Ιδανική ταυτοδυναμία γλωσσαρίου (μηδενική αναδρομική διπλο-αντικατάσταση σε `Server Room`/`UPS`/`backup`) & backslash safety, προστασία αντιθετικού `δε`, διακοπτόμενων διαλόγων, fenced code blocks & URLs, PDF/EPUB spine order & `<style>`/`<script>` stripping, DOCX πίνακες/εικόνες/merged cells, EPUB ένθετα tags & HTML comments, κενά PDF/EPUB, XML control chars και genre anti-poetry guard.
35. `test_comic_and_tts_edge_cases.py`: Προστασία CBZ Zip Slip, φυσική ταξινόμηση σελίδων (`page_1`, `page_2`, `page_10`), σεβασμός `target_lang="english"` σε vector comics, fail-loud έλεγχος απουσίας κλειδιού σε σκαναρισμένα κόμικς, clamped Vision `box_2d`, `ΐ`/`ΰ` ➔ `Ϊ`/`Ϋ` σε κεφαλαία μπαλόνια, TTS voice code resolution, `edge_tts`/`ffmpeg` timeouts, M4B cover attachment και εγγυημένος καθαρισμός `tts_tmp_*`.
36. `test_concurrency_persistence_and_lifecycle.py`: Thread-safe off-loop SSE delivery, διατήρηση συνδρομητών σε γεμάτη ουρά, προστασία `cancelled` jobs από overwrites, partial-update same-lang guard & comic PDF preservation στην ουρά, `None` coercion στη SQLite, reset ορφανών `queued` jobs, backup κατεστραμμένου `settings.json` και προστασία ενεργών jobs στον `storage_cleaner`.
37. `test_frontend_contracts_and_ui.py`: Αυστηρός έλεγχος `(HTTP method, path)` απέναντι στο live `app.routes` του FastAPI, αντιστοίχιση JSON payload keys με τα Pydantic models, στατικός έλεγχος XSS/API origin/`node --check`, καθώς και runtime Node.js VM DOM & state test harness (10 assertions, συμπεριλαμβανομένου του download button gating) για το `frontend/app.js`.
38. `test_gemini_quota_warning.py`: Έλεγχος εντοπισμού εξάντλησης ορίου Gemini (RPD/RPM), λειτουργία διακόπτη προστασίας Quota Circuit Breaker, live endpoint `/api/gemini/status`, αντίστροφος μετρητής, cooldown messages και άμεσο reset στο `/api/gemini/reset-quota`.
39. `test_quota_behavior_choice.py`: Προηγούμενη επιλογή συμπεριφοράς σε εξάντληση ορίου (`wait` vs `fallback`), ασφαλής διατήρηση checkpoint και χρονοδιακόπτη στο `wait`, άμεση αυτόματη συνέχιση με δωρεάν μηχανή στο `fallback`, αυτόματη ενεργοποίηση `Free Mode` ως προεπιλογή όταν δεν υπάρχει API Key (σε settings, μετάφραση, ηχοβιβλίο και AI Polish), και απόλυτη υγιεινή Session History (0 test jobs).
40. `test_gemini_key_pool.py`: Πλήρης έλεγχος λειτουργίας Gemini Multi-Key Pool (έως 4 κλειδιά, deduplication, thread-safety, ασφαλές masking `AIzaSy...2345`), αυτόματη εναλλαγή κλειδιού σε 429 / quota exhaustion, ενεργοποίηση circuit breaker μόνο αν εξαντληθούν και τα 4 κλειδιά, καθώς και έλεγχος REST endpoints `/api/gemini/pool` (GET/POST), `/api/settings` (GET/POST) και `/api/settings/gemini_api_keys` (DELETE).

Όλοι οι έλεγχοι ολοκληρώνονται με **`40/40 PASS (35/35 σε --fast · 45/45 FastAPI endpoints)`** και αυτόματο καθαρισμό test sessions.

---

## 7. Αντιμετώπιση Τεχνικών Προβλημάτων (Troubleshooting)

| Σύμπτωμα | Πιθανή Αιτία | Λύση |
|---|---|---|
| **Σύμβολα με ερωτηματικό (`[?]`) σε bullets στο DOCX** | Μη συμβατοί χαρακτήρες Private Use Area (PUA) από γραμματοσειρές Wingdings/Symbol στο πρωτότυπο έγγραφο. | Έχει επιλυθεί αυτόματα: το backend φιλτράρει όλα τα PUA σύμβολα, τα μετατρέπει σε Unicode κουκίδες (`•`) και εφαρμόζει native Word `List Bullet` παραγράφους. |
| **Αλλαγή μορφής κατά τη λήψη κατέβαζε το αρχικό format** | Το download endpoint δεν λάμβανε παραμέτρους μορφής. | Έχει επιλυθεί: το endpoint υποστηρίζει πλέον `GET /api/download/{job_id}?format=pdf\|docx\|epub\|txt\|cbz\|cbr` και μετατρέπει ακαριαία το αποτέλεσμα on-demand. |
| **Σφάλμα 404 κατά τη λήψη (`Job not found`)** | Επανεκκίνηση του server με απώλεια μνήμης. | Έχει επιλυθεί αυτόματα: οι εργασίες επιβιώνουν μόνιμα στη SQLite (`data/bookapp.db`) και ο `job_manager.py` ανακτά αυτόματα τα αρχεία εξόδου από το δίσκο. |
| **Σφάλμα `NoAudioReceived` στο Audiobook** | Ελλιπές λεξικό της φωνής Athina σε σύνθετα ακρωνύμια (π.χ. `UPS`, `Server Room`). | Έχει επιλυθεί αυτόματα: ορίστηκε ως κύρια φωνή ο **Nestoras** και προστέθηκε αυτόματο fallback. |
| **Η μπάρα προόδου δεν κινείται (μένει στο 0%)** | Ο proxy ή το firewall μπλοκάρει τα Server-Sent Events (SSE). | Βεβαιωθείτε ότι στο Nginx έχει τεθεί `proxy_buffering off;` και `proxy_read_timeout 86400s;`. |
| **Σκαναρισμένα PDF / Graphic Novels (μόνο εικόνες χωρίς ψηφιακό κείμενο)** | Τα γράμματα βρίσκονται μέσα στα pixels της εικόνας. | Έχει επιλυθεί πλήρως: το `detect_is_graphic_novel()` αναγνωρίζει αυτόματα σκαναρισμένα PDF/Comics στο `/api/upload`, κλειδώνει το UI στις επιλογές Graphic Novel και δρομολογεί τη μετάφραση σε 4 παράλληλους **Gemini Vision** workers με αδιαφανές γέμισμα φόντου (`draw_rect`) και SHA-256 Vision cache. Απαιτείται έγκυρο Gemini API Key στις ρυθμίσεις. |
| **Σφάλμα HTTP 429 στη μετάφραση ή σελίδες στα Αγγλικά** | Προσωρινό rate limit της Google στον GTX client. | Έχει επιλυθεί πλήρως: το `translator.py` διαθέτει **20s 429 Circuit Breaker**, fallback στο MyMemory API και **αυτόματο failover στο Gemini Flash**. Επίσης, με ενεργό **AI Polish**, ΟΛΑ τα formats (PDF, EPUB, DOCX, TXT) εκτελούν **Single-Pass Direct AI Translation & Polish** (παρακάμπτοντας τελείως το Google Translate). |
| **Πάγωμα ουράς ("κόλλησε") λόγω εξάντλησης ημερήσιου ορίου Gemini Free Tier** | Εξάντληση ημερήσιων αιτημάτων (RPD limit / `RESOURCE_EXHAUSTED` / `requests per day limit exceeded`) μετά από μετάφραση εκατοντάδων σελίδων, με αποτέλεσμα παλαιότερα να δοκιμάζονται 35 μοντέλα σε λούπα ύπνου. | Έχει επιλυθεί πλήρως: το `ai_polisher.py` διαθέτει πλέον **Gemini Daily Quota Circuit Breaker** (`DailyQuotaExhaustedError`, `get_gemini_quota_info`) με διαμοιραζόμενη επιμονή στο `config/settings.json`. Όταν εντοπιστεί υπέρβαση ημερήσιου ορίου ή `retryDelay > 60s`, ενεργοποιείται ακαριαία cooldown και παρακάμπτονται όλα τα επόμενα μοντέλα σε <1ms. Στο UI εμφανίζονται ειδικά Banners με εκτιμώμενο χρόνο ανανέωσης και κουμπί «🔑 Αλλαγή API Key» (στην Ουρά, στην Κάρτα Προόδου, στην Κάρτα Αποτελέσματος και στο Modal), ενώ το endpoint `/api/gemini/status` επιτρέπει άμεσο έλεγχο. Στα Graphic Novels/Comics, η μετάφραση συνεχίζει απρόσκοπτα μέσω Google/MyMemory χωρίς AI Polish, ενώ στα υπόλοιπα έγγραφα τα checkpoints προστατεύουν το 100% της προόδου. Επιπλέον, όλα τα test jobs καθαρίζονται αυτόματα (`conftest.py` + `cleanup_test_jobs`), διατηρώντας το Session History των χρηστών πεντακάθαρο. |
| **Αργό AI Polish ή timeouts σε μεγάλα βιβλία** | Χαμηλή παραλληλία, dead sleep εντός semaphore, 15s timeout ή hidden thinking tokens στο Gemini 2.5 Flash. | Έχει επιλυθεί πλήρως: αναβαθμίστηκε σε **5 παράλληλους workers** (`Semaphore(5)`), `req_timeout=60s`, `MAX_BATCH_CHARS=5500` (έως 3 σελίδες), `thinkingConfig: {thinkingBudget: 0}` στα 2.5/3.x Flash μοντέλα, HTTP keep-alive connection pooling και αφαίρεση idle sleep — επιτυγχάνοντας **4x–8x επιτάχυνση**. |
| **Κατέβασμα εικόνας εξωφύλλου αντί για το αρχείο βιβλίου** | Κατά το recovery του job, το `cover_image.jpg` αναγνωριζόταν ως αρχείο εξόδου. | Έχει επιλυθεί: τα αρχεία εικόνων (`.jpg`, `.png`, `.webp`) εξαιρούνται αυστηρά από τα candidate output files του `job_manager.py` και του `/api/download`. |
| **Απώλεια αρχικών σελίδων PDF (Πίνακας Περιεχομένων, Πρόλογος, Εισαγωγή)** | Το παλαιότερο regex φιλτράρισμα κεφαλίδων απέρριπτε ολόκληρα μπλοκ κειμένου εάν περιείχαν γραμμή κεφαλίδας. | Έχει επιλυθεί πλήρως: το `_clean_page_blocks` καθαρίζει πλέον μόνο τις συγκεκριμένες γραμμές κεφαλίδας σε επίπεδο γραμμής (`lines`), διατηρώντας το 100% του περιεχομένου των πρώτων σελίδων (front matter) τόσο κατά τη μετάφραση όσο και κατά την εξαγωγή. |
| **Διακοπή AI Polish σε πολυσέλιδα βιβλία (>300 σελίδες)** | Διακοπή δικτύου ή κατά λάθος ανανέωση της σελίδας κατά την εκτέλεση δεκάδων batches. | Έχει επιλυθεί πλήρως: κάθε επιτυχής παρτίδα αποθηκεύεται σε πραγματικό χρόνο στο `temp/outputs/{job_id}/.polish_checkpoint.json` (ή `.direct_ai_checkpoint.json`). Κατά την επανεκτέλεση, τα αποθηκευμένα batches ανακτώνται ακαριαία χωρίς νέα αιτήματα στο Gemini API. |
| **Νευρωνική φωνή Edge-TTS κομπιάζει σε ξένα ονόματα ή διαβάζει αριθμούς ως ψηφία** | Η φωνή `Nestoras` διαβάζει αγγλικούς χαρακτήρες γράμμα-γράμμα ή κομπιάζει σε λατινικά ακρωνύμια (`DNA`, `AI`). | Χρησιμοποιήστε την επιλογή **AI Polish for Spoken Audio (style="audiobook")**, η οποία μεταγράφει φωνητικά τα ξένα ονόματα σε ελληνικά (`Κίτον`, `Θησέας`, `Ρόρσαχ`), αναπτύσσει ολογράφως τους αριθμούς (`δύο χιλιάδες έξι`) και αφαιρεί δείκτες σελίδων και υποσημειώσεις. |
| **Σφάλμα `no such file: ...temp/uploads/tmp/...` κατά το Resume από Session History** | Παλαιότερη έκδοση του `db_save_job` δεν ενημέρωνε το `file_path` στο `ON CONFLICT DO UPDATE`. | Έχει επιλυθεί πλήρως: το `database.py` ενημερώνει πλέον `file_path`, και ο `job_manager.py` διαθέτει αυτόματο `_heal_file_path()` από `temp/uploads/{job_id}/`. |
| **Σφάλμα `Package not found` σε `.docx` αρχείο** | Το ανεβασμένο αρχείο ήταν 0 bytes (κενό) ή μετονομασμένο παλιό `.doc`. | Έχει επιλυθεί: το `POST /api/upload` απορρίπτει αμέσως κενά (0 bytes) ή μη έγκυρα `.docx`/`.epub`/`.cbz`/`.pdf` αρχεία με σαφές μήνυμα σφάλματος. |
| **Άδεια λευκά μπαλόνια σε Graphic Novels** | Πυκνά ελληνικά κείμενα δεν χωρούσαν στα `5.0pt` με `insert_textbox` και παραλείπονταν αθόρυβα. | Έχει επιλυθεί πλήρως: ο νέος two-pass renderer (`_plan_balloon_layout` + `_draw_planned_balloon_text`) σχεδιάζει πρώτα όλα τα φόντα και έπειτα όλα τα κεντραρισμένα κείμενα με προσαρμογή έως `3.0pt` και fallback σε `arialn.ttf`. |
| **HTML tags (`</i>`), `<bos>`, CoT leaks, mixed-script (`ημIFωτισμένη`) ή `□□` / κομμένα URLs σε PDF** | Χρήση Flash-Lite, απουσία φιλτραρίσματος `thought: true` / `MAX_TOKENS`, ή μη-υποστηριζόμενοι γλύφοι/μακριά tokens στο PDF. | Έχει επιλυθεί πλήρως: προτεραιότητα σε πλήρη Flash μοντέλα, `maxOutputTokens: 16384`, `sanitize_ai_output()`, `detect_greek_output_issues()` + `_find_mixed_script_tokens()` στοχευμένο retry, `_sanitize_for_pdf_font()` (`has_glyph` guard), `_split_oversized_token()` (URL wrapping) και φρέσκια `gemini_polish_v4` cache. |
| **«Νησίδες» ωμού Google Translate, διπλοτυπίες ορίων (`[... ...]`) ή ασυνέπεια ονομάτων/γένους σε μεγάλα βιβλία** | Safety refusals (`BLOCK_ONLY_HIGH`) που έριχναν ολόκληρο 3σέλιδο batch σε MT, inline `[... snippet]` echoes και δειγματοληψία Entity Dossier μόνο από τους πρώτους 18.000 χαρακτήρες. | Έχει επιλυθεί πλήρως: `BLOCK_NONE` safety settings + αναδρομικός διχασμός (pages ➔ paragraphs), απομονωμένο `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` + `_deduplicate_batch_boundary()`, whole-book stratified `_build_stratified_book_sample()` (35–60 όροι με ρητό γένος) και ενιαία στίξη διαλόγων (`«...»`). |
