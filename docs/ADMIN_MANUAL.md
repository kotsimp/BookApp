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
* **SQLite Database Layer (`data/bookapp.db`):** Μόνιμη αποθήκευση κατάστασης εργασιών και πλήρων μεταδεδομένων ρυθμίσεων (`output_format`, `layout_mode`, `source_lang`, `target_lang`, `ai_polish`, `reading_direction`, `total_pages`, `done_pages`) σε WAL mode (Write-Ahead Logging) με thread-safe κλειδώματα, αυτόματη αποκατάσταση ορφανών `running` jobs κατά την εκκίνηση (`db_reset_orphaned_running_jobs`) και self-healing `file_path` (`_heal_file_path`) για μηδενική απώλεια δεδομένων μετά από επανεκκινήσεις.
* **Smart Batch Queue Engine (`backend/queue_manager.py`):** Σειριακή μηχανή μαζικής μετάφρασης ενοποιημένη στο Upload Card με όριο `MAX_QUEUE_ITEMS = 20` αρχεία ανά παρτίδα (και `MAX_UPLOAD_SIZE_BYTES = 250 MB` ανά αρχείο). Υποστηρίζει δυναμικό συγχρονισμό ρυθμίσεων στο `POST /api/queue/start` (`apply_settings_to_queued_items`), προστασία μικτών παρτίδων (Comics vs Books), απομονωμένο child `asyncio.Task` ανά αρχείο (ώστε η ακύρωση του ενεργού στοιχείου να συνεχίζει αυτόματα στο επόμενο), `POST /api/queue/{job_id}/retry`, `Pause/Resume`, `Auto-Start` και εξαγωγή ενιαίου ZIP (`GET /api/queue/download-all`).
* **Upload Validation Guard (`POST /api/upload`):** Άμεση απόρριψη κενών αρχείων (`0 bytes`), αρχείων >250 MB (`HTTP 413`) και κατεστραμμένων/μετονομασμένων αρχείων ελέγχοντας magic headers (`PK` για `.docx`/`.epub`/`.cbz`/`.zip`, `%PDF` για `.pdf`) με unique UUID temp filenames για αποφυγή συγκρούσεων σε multi-file uploads.
* **Semantic Translation & Polish Cache:** Σημασιολογική προσωρινή μνήμη μεταφράσεων και AI Polish βασισμένη σε κατακερματισμό περιεχομένου (SHA-256). Επαναλαμβανόμενες φράσεις και παράγραφοι επιστρέφονται ακαριαία (0ms) χωρίς κατανάλωση εξωτερικού API quota, με ζωντανά στατιστικά επιτυχιών (`GET /api/cache/stats`).
* **Storage Auto-Cleanup Garbage Collector (`backend/storage_cleaner.py`):** Αυτόματος μηχανισμός εκκαθάρισης προσωρινών τμημάτων ήχου και εξαγωγών παλαιότερων των 48 ωρών, προστατεύοντας τα τελικά αρχεία εξόδου. Προσβάσιμος και μέσω `POST /api/admin/cleanup`.
* **Graphic Novel & Manga (RTL) Comic Engine (`backend/comic_translator.py`):** Εντοπισμός μπαλονιών διαλόγου, inpainting φόντου, έξυπνη κλιμάκωση γραμματοσειράς `fit-to-box` (έως 5.5pt), υποστήριξη ιαπωνικής φοράς ανάγνωσης Manga (RTL: top-to-bottom, right-to-left) και εξαγωγή σε PDF, CBZ, CBR και Fixed-Layout EPUB.
* **Greek Editorial Typography Engine (`backend/typography.py`):** Αυτόματη μετατροπή εισαγωγικών σε «...», διαλόγων σε em-dash (`—`), αυτόματη επιβολή του κανόνα του τελικού «ν» (`δε/δεν`, `μη/μην`) και διόρθωση στίξης.
* **Auto-Genre & Style Detector (`backend/genre_detector.py`):** Ευρετική και γλωσσική ανάλυση κειμένου (`POST /api/detect-genre`) για αυτόματη ανίχνευση λογοτεχνίας, ποίησης, τεχνικών ή διοικητικών κειμένων.
* **Multi-Voice TTS Engine & M4B Exporter (`backend/tts_engine.py`):** Παραγωγή πολυφωνικών audiobooks (Αφηγητής + Διάλογοι), ενσωμάτωση εξωφύλλου και ετικετών ID3v2/MP4 μέσω `mutagen`, άμεση ακρόαση δειγμάτων (`GET /api/tts/preview`) και εξαγωγή σε `.m4b`.
* **Server-Sent Events (SSE):** Μηχανισμός ζωντανής ενημέρωσης προόδου (0–100%) χωρίς polling.
* **PyMuPDF (fitz):** Εξαγωγή κειμένου, αναγνώριση διάταξης και παραγωγή PDF με ελληνικές TrueType γραμματοσειρές (Arial/Calibri/Georgia).
* **python-docx:** In-place ανάγνωση και εγγραφή εγγράφων Word με διατήρηση στυλ, γραμματοσειρών και πινάκων.
* **EbookLib & BeautifulSoup4:** Ανάγνωση, ανάλυση και ανακατασκευή EPUB κεφαλαίων διατηρώντας το HTML/CSS.
* **edge-tts:** Παραγωγή ήχου μέσω των δωρεάν νευρωνικών φωνών της Microsoft.
* **On-Demand Dynamic Exporter:** Δυναμική εξαγωγή σε οποιαδήποτε υποστηριζόμενη μορφή (`format=pdf|docx|epub|txt`) κατά τη λήψη, χωρίς επανυπολογισμό μετάφρασης.
* **Wingdings / PUA Glyph Normalizer:** Αυτόματη μετατροπή συμβόλων Private Use Area (`\ue000`–`\uf8ff`) σε πρότυπες Unicode κουκίδες (`•`) και native στυλ `List Bullet`.
* **Interactive Translation Editor:** Αμφίδρομη ανάγνωση και ενημέρωση μεταφρασμένου κειμένου (`GET`/`PUT /api/jobs/{job_id}/text`) με αυτόματο re-exporting, άμεση ανάγνωση pre-extracted `*_original.txt` και διατήρηση του αρχικού `file_type` κατά το disk recovery.
* **Robust Translator Engine (HTTP POST & Validation):** Αποστολή αιτημάτων μετάφρασης μέσω HTTP POST στο Google GTX client API (`https://translate.googleapis.com/translate_a/single`), εξαλείφοντας περιορισμούς μήκους URI. Αυτόματος έλεγχος ελληνικών χαρακτήρων (`has_greek_text`) με εκθετικό backoff για αποτροπή σιωπηλών επιστροφών στα Αγγλικά.
* **Optimized AI Polisher (Gemini):** Ασύγχρονη επιμέλεια και διόρθωση μέσω Google Gemini API (`POST /api/polish`) με smart multi-page batching (~5 σελίδες / 10.000 χαρακτήρες ανά κλήση) και concurrency limiter (`MAX_CONCURRENT_REQUESTS = 2`). Περιλαμβάνει:
  * **Source-Anchored Verification:** Δίγλωσση σύγκριση ανά σελίδα του ελληνικού προσχεδίου με το πρωτότυπο αγγλικό κείμενο για εξάλειψη παρερμηνειών και αγγλισμών.
  * **Audiobook Script Polish & Spoken Phonetics:** Φωνητική μεταγραφή ξένων ονομάτων και ακρωνυμίων σε ελληνικούς χαρακτήρες (π.χ. `Keeton` ➔ `Κίτον`, `Theseus` ➔ `Θησέας`, `DNA` ➔ `Ντι-Εν-Έι`), πλήρης ολογράφως ανάπτυξη αριθμών/ετών/ποσοστών και αφαίρεση μη εκφωνήσιμων συμβόλων για άψογη εκφώνηση από νευρωνικές φωνές TTS (Nestoras/Athina).
  * **Entity & Character Consistency Dossier:** Αυτόματη εξαγωγή και διοχέτευση μητρώου όρων και ονομάτων σε όλες τις επιμέρους παρτίδες για απόλυτη συνέπεια σε όλο το βιβλίο.
  * **Rolling Context Window & Smart Real-Time Checkpointing:** Συνεχής ροή ανάμεσα σε διαδοχικές παρτίδες και αποθήκευση προόδου στο δίσκο (`.polish_checkpoint.json`) για μηδενική απώλεια tokens και άμεση συνέχιση σε περίπτωση επανεκκίνησης ή διακοπής.
  * **Concurrency & Rate Limit Protection:** Μειώνει τις κλήσεις κατά 80% για συμβατότητα με το δωρεάν όριο (15 RPM) του Google AI Studio, διαθέτοντας dynamic exponential backoff (12s–48s) σε HTTP 429 και 5 εξειδικευμένα στυλ.
* **Cover Image Management:** Πλήρης υποστήριξη εξαγωγής και διαχείρισης εξωφύλλων (`GET/HEAD /api/cover/{job_id}`, `POST /api/cover/{job_id}`, `DELETE /api/cover/{job_id}`). Αυτόματη ανίχνευση από πρωτότυπα PDF/EPUB/DOCX, προβολή μικρογραφίας, χειροκίνητη αντικατάσταση και πλήρης απομόνωση από τα candidate files λήψης (ώστε να μην κατεβαίνει εικόνα αντί για βιβλίο).
* **Persistent Settings Manager:** Αποθήκευση και διαγραφή ρυθμίσεων (όπως Gemini API key) στο `config/settings.json` μέσω `GET`/`POST`/`DELETE /api/settings`.
* **Literature / E-Reader Formatter:** Λειτουργία `layout=literature` για εξαγωγή 6×9 trade-paperback PDF/DOCX (Georgia serif) και reflowable Kindle/iPad EPUB με TOC. Αφαιρεί running headers/footers και αριθμούς σελίδων από το κείμενο, απομονώνει τίτλους κεφαλαίων και παραθέματα, ενώνει σπασμένες προτάσεις ανάμεσα σε σελίδες και ενσωματώνει αυθεντικό εξώφυλλο στην 1η σελίδα.
* **Multi-Page Front Matter Preservation:** Καθαρισμός κεφαλίδων σε επίπεδο γραμμής (`_clean_page_blocks`), διασφαλίζοντας ότι πίνακες περιεχομένων, προμετωπίδες (epigraphs) και πρόλογοι στις αρχικές σελίδες του βιβλίου διατηρούνται 100% ακέραιοι χωρίς απόρριψη μπλοκ κειμένου.
* **Custom Glossary Engine:** Αποθήκευση και αντικατάσταση ορολογίας με regex word boundaries (`GET`/`POST`/`DELETE /api/glossary`).

---

## 2. Προαπαιτούμενα Συστήματος

### Λειτουργικό Σύστημα
* **Windows:** Windows 10, Windows 11 ή Windows Server 2016/2019/2022.
* **Linux:** Ubuntu 20.04+, Debian 11+, RHEL/CentOS 8+, AlmaLinux/Rocky Linux.
* **macOS:** macOS 11 Big Sur ή νεότερο.

### Λογισμικό
* **Python 3.9 έως 3.12** εγκατεστημένη στο σύστημα με `pip` και `venv`.
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
│   ├── main.py              # FastAPI endpoints (40 REST routes & SSE streaming)
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
├── tests/                   # 29 Αυτοματοποιημένα test suites (100% PASS)
└── requirements.txt
```

### Διαχείριση Εργασιών, Ουράς, Ρυθμίσεων & Εξωφύλλων μέσω REST Endpoints
Η εφαρμογή παρέχει ολοκληρωμένο REST API (**40 endpoints**) για τη διαχείριση εργασιών, Smart Batch Queue, ρυθμίσεων και εικόνων εξωφύλλου:
* `GET /api/queue`, `POST /api/queue/add`, `POST /api/queue/start`, `POST /api/queue/pause`, `POST /api/queue/auto-start`, `POST /api/queue/{job_id}/retry`, `GET /api/queue/download-all`, `DELETE /api/queue/{job_id}`, `DELETE /api/queue`: Πλήρης διαχείριση της Smart Batch Queue (έως 20 αρχεία, συγχρονισμός ρυθμίσεων στο start, retry, pause/resume, ZIP export).
* `DELETE /api/jobs/{job_id}`: Διαγράφει συγκεκριμένη εργασία από τη μνήμη, τη SQLite, την ουρά και αφαιρεί οριστικά τους φακέλους `temp/uploads/{job_id}` και `temp/outputs/{job_id}` από το δίσκο.
* `DELETE /api/jobs`: Καθαρίζει ολόκληρο το ιστορικό, την ουρά και τα προσωρινά αρχεία (διατηρώντας τη `translation_cache`).
* `GET /api/settings`, `POST /api/settings`, `DELETE /api/settings/{key}`: Ανάγνωση, αποθήκευση και διαγραφή τοπικών ρυθμίσεων (π.χ. `gemini_api_key`).
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

Η εφαρμογή περιλαμβάνει θωρακισμένη (**bulletproof**) σουίτα **29 αυτοματοποιημένων ελέγχων (test suites)** στο φάκελο `tests/` με **100% κάλυψη όλων των 40 FastAPI endpoints**, αυτόματη προστασία/επαναφορά του `config/settings.json` (ώστε τα tests να μην διαγράφουν ή αλλοιώνουν ποτέ το API Key του χρήστη) και αυτόματη εκκίνηση προσωρινού Uvicorn server αν δεν τρέχει ήδη:

```bash
# Εκτέλεση όλων των 29 suites (Full Suite):
.\.venv\Scripts\python run_all_tests.py

# Ταχεία εκτέλεση (static/unit/regression/queue/benchmark suites σε ~30s):
.\.venv\Scripts\python run_all_tests.py --fast
```

Ο master runner ανακαλύπτει και εκτελεί αυτόματα όλες τις **29 σουίτες δοκιμών**:
1. `test_ai_polish_advanced.py`: Δίγλωσση επιμέλεια, Audiobook phonetics, consistency dossier & checkpoints.
2. `test_ai_polisher_deep.py`: Όλα τα 6 στυλ επιμέλειας, temperatures, multi-page splitting, cache invalidation.
3. `test_api.py`: Ολοκληρωμένοι έλεγχοι REST endpoints, upload, translation & streaming.
4. `test_categorized_glossary.py`: Κατηγοριοποιημένο γλωσσάρι (Technical, Literature, General).
5. `test_code_health.py`: **10-σημείων στατικός φύλακας υγείας κώδικα:** AST/Syntax, Unbound Locals, Import Integrity, Unreachable Code, Undefined Globals & Missing Submodule Imports, Unused Imports & Deprecated FastAPI APIs, Frontend HTML⇄JS Cross-Integrity & UI Contracts, Production Config Hygiene, Frontend `${API}`⇄Backend Route Alignment (0 silent 404s) και 100% Backend Endpoint Test Coverage Guard.
6. `test_comic_translation.py`: Μετάφραση Graphic Novels (PDF, CBZ, CBR, EPUB) και απαγόρευση TXT/DOCX.
7. `test_concurrency_and_stress.py`: Stress test 50 παράλληλων jobs, multi-thread settings με καθαρό teardown, SSE queues.
8. `test_database_and_cache.py`: SQLite persistence (`data/bookapp.db`), restart recovery & SHA-256 cache.
9. `test_document_integrity_and_encoding.py`: BOM, UTF-16, CP1253, πολυτονικά ελληνικά, corrupted file handling.
10. `test_dynamic_download.py`: Άμεση αλλαγή φορμάτ κατά τη λήψη χωρίς επανυπολογισμό.
11. `test_e2e_regression_guard.py`: **9-σημείων E2E φύλακας παλινδρόμησης:** Single-Job Delete & Clear All (`DELETE /api/jobs`) σε API + SQLite (με διατήρηση cache), DOCX + AI Polish Single-Pass, Invalid API key fail-fast (<1s), `/health`, `/preview/{id}`, `/cover/{id}` (POST/GET/DELETE), `/debug/extract/{id}`, `/polish/status/{id}`, `/progress/{id}` SSE, Source-Anchored identical-text auto-disable, Google 429 Circuit Breaker, επανεκκίνηση `cancelled` jobs & ανάκτηση ορφανών `running` jobs, καθώς και SQLite `file_path` persistence & πλήρης επαναφορά ρυθμίσεων στο Resume.
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

Όλοι οι έλεγχοι ολοκληρώνονται με **`29/29 PASS (100% επιτυχία · 40/40 FastAPI endpoints)`**.

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
| **Αργό AI Polish ή timeouts σε μεγάλα βιβλία** | Χαμηλή παραλληλία, dead sleep εντός semaphore, 15s timeout ή hidden thinking tokens στο Gemini 2.5 Flash. | Έχει επιλυθεί πλήρως: αναβαθμίστηκε σε **5 παράλληλους workers** (`Semaphore(5)`), `req_timeout=45s`, `MAX_BATCH_CHARS=7500`, `thinkingConfig: {thinkingBudget: 0}` στα 2.5 Flash μοντέλα, HTTP keep-alive connection pooling και αφαίρεση idle sleep — επιτυγχάνοντας **4x–8x επιτάχυνση**. |
| **Κατέβασμα εικόνας εξωφύλλου αντί για το αρχείο βιβλίου** | Κατά το recovery του job, το `cover_image.jpg` αναγνωριζόταν ως αρχείο εξόδου. | Έχει επιλυθεί: τα αρχεία εικόνων (`.jpg`, `.png`, `.webp`) εξαιρούνται αυστηρά από τα candidate output files του `job_manager.py` και του `/api/download`. |
| **Απώλεια αρχικών σελίδων PDF (Πίνακας Περιεχομένων, Πρόλογος, Εισαγωγή)** | Το παλαιότερο regex φιλτράρισμα κεφαλίδων απέρριπτε ολόκληρα μπλοκ κειμένου εάν περιείχαν γραμμή κεφαλίδας. | Έχει επιλυθεί πλήρως: το `_clean_page_blocks` καθαρίζει πλέον μόνο τις συγκεκριμένες γραμμές κεφαλίδας σε επίπεδο γραμμής (`lines`), διατηρώντας το 100% του περιεχομένου των πρώτων σελίδων (front matter) τόσο κατά τη μετάφραση όσο και κατά την εξαγωγή. |
| **Διακοπή AI Polish σε πολυσέλιδα βιβλία (>300 σελίδες)** | Διακοπή δικτύου ή κατά λάθος ανανέωση της σελίδας κατά την εκτέλεση δεκάδων batches. | Έχει επιλυθεί πλήρως: κάθε επιτυχής παρτίδα αποθηκεύεται σε πραγματικό χρόνο στο `temp/outputs/{job_id}/.polish_checkpoint.json` (ή `.direct_ai_checkpoint.json`). Κατά την επανεκτέλεση, τα αποθηκευμένα batches ανακτώνται ακαριαία χωρίς νέα αιτήματα στο Gemini API. |
| **Νευρωνική φωνή Edge-TTS κομπιάζει σε ξένα ονόματα ή διαβάζει αριθμούς ως ψηφία** | Η φωνή `Nestoras` διαβάζει αγγλικούς χαρακτήρες γράμμα-γράμμα ή κομπιάζει σε λατινικά ακρωνύμια (`DNA`, `AI`). | Χρησιμοποιήστε την επιλογή **AI Polish for Spoken Audio (style="audiobook")**, η οποία μεταγράφει φωνητικά τα ξένα ονόματα σε ελληνικά (`Κίτον`, `Θησέας`, `Ρόρσαχ`), αναπτύσσει ολογράφως τους αριθμούς (`δύο χιλιάδες έξι`) και αφαιρεί δείκτες σελίδων και υποσημειώσεις. |
| **Σφάλμα `no such file: ...temp/uploads/tmp/...` κατά το Resume από Session History** | Παλαιότερη έκδοση του `db_save_job` δεν ενημέρωνε το `file_path` στο `ON CONFLICT DO UPDATE`. | Έχει επιλυθεί πλήρως: το `database.py` ενημερώνει πλέον `file_path`, και ο `job_manager.py` διαθέτει αυτόματο `_heal_file_path()` από `temp/uploads/{job_id}/`. |
| **Σφάλμα `Package not found` σε `.docx` αρχείο** | Το ανεβασμένο αρχείο ήταν 0 bytes (κενό) ή μετονομασμένο παλιό `.doc`. | Έχει επιλυθεί: το `POST /api/upload` απορρίπτει αμέσως κενά (0 bytes) ή μη έγκυρα `.docx`/`.epub`/`.cbz`/`.pdf` αρχεία με σαφές μήνυμα σφάλματος. |
