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
* **Server-Sent Events (SSE):** Μηχανισμός ζωντανής ενημέρωσης προόδου (0–100%) χωρίς polling.
* **PyMuPDF (fitz):** Εξαγωγή κειμένου, αναγνώριση διάταξης και παραγωγή PDF με ελληνικές TrueType γραμματοσειρές (Arial/Calibri/Georgia).
* **python-docx:** In-place ανάγνωση και εγγραφή εγγράφων Word με διατήρηση στυλ, γραμματοσειρών και πινάκων.
* **EbookLib & BeautifulSoup4:** Ανάγνωση, ανάλυση και ανακατασκευή EPUB κεφαλαίων διατηρώντας το HTML/CSS.
* **edge-tts:** Παραγωγή ήχου μέσω των δωρεάν νευρωνικών φωνών της Microsoft.
* **On-Demand Dynamic Exporter:** Δυναμική εξαγωγή σε οποιαδήποτε υποστηριζόμενη μορφή (`format=pdf|docx|epub|txt`) κατά τη λήψη, χωρίς επανυπολογισμό μετάφρασης.
* **Wingdings / PUA Glyph Normalizer:** Αυτόματη μετατροπή συμβόλων Private Use Area (`\ue000`–`\uf8ff`) σε πρότυπες Unicode κουκίδες (`•`) και native στυλ `List Bullet`.
* **Interactive Translation Editor:** Αμφίδρομη ανάγνωση και ενημέρωση μεταφρασμένου κειμένου (`GET`/`PUT /api/jobs/{job_id}/text`) με αυτόματο re-exporting, άμεση ανάγνωση pre-extracted `*_original.txt` και διατήρηση του αρχικού `file_type` κατά το disk recovery.
* **Robust Translator Engine (HTTP POST & Validation):** Αποστολή αιτημάτων μετάφρασης μέσω HTTP POST στο Google GTX client API (`https://translate.googleapis.com/translate_a/single`), εξαλείφοντας περιορισμούς μήκους URI. Αυτόματος έλεγχος ελληνικών χαρακτήρων (`has_greek_text`) με εκθετικό backoff για αποτροπή σιωπηλών επιστροφών στα Αγγλικά.
* **Optimized AI Polisher (Gemini):** Ασύγχρονη επιμέλεια και διόρθωση μέσω Google Gemini API (`POST /api/polish`) με smart multi-page batching (~5 σελίδες / 10.000 χαρακτήρες ανά κλήση) και concurrency limiter (`MAX_CONCURRENT_REQUESTS = 2`). Μειώνει τις κλήσεις κατά 80% για συμβατότητα με το δωρεάν όριο (15 RPM) του Google AI Studio, διαθέτοντας dynamic exponential backoff (12s–48s) σε HTTP 429 και 5 εξειδικευμένα στυλ (συμπεριλαμβανομένου του `literature` για μυθιστορήματα και sci-fi).
* **Cover Image Management:** Πλήρης υποστήριξη εξαγωγής και διαχείρισης εξωφύλλων (`GET/HEAD /api/cover/{job_id}`, `POST /api/cover/{job_id}`, `DELETE /api/cover/{job_id}`). Αυτόματη ανίχνευση από πρωτότυπα PDF/EPUB/DOCX, προβολή μικρογραφίας, χειροκίνητη αντικατάσταση και πλήρης απομόνωση από τα candidate files λήψης (ώστε να μην κατεβαίνει εικόνα αντί για βιβλίο).
* **Persistent Settings Manager:** Αποθήκευση και διαγραφή ρυθμίσεων (όπως Gemini API key) στο `config/settings.json` μέσω `GET`/`POST`/`DELETE /api/settings`.
* **Literature / E-Reader Formatter:** Λειτουργία `layout=literature` για εξαγωγή 6×9 trade-paperback PDF/DOCX (Georgia serif) και reflowable Kindle/iPad EPUB με TOC. Αφαιρεί running headers/footers και αριθμούς σελίδων από το κείμενο, απομονώνει τίτλους κεφαλαίων και παραθέματα, ενώνει σπασμένες προτάσεις ανάμεσα σε σελίδες και ενσωματώνει αυθεντικό εξώφυλλο στην 1η σελίδα.
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

    client_max_body_size 100M;  # Επιτρέπει μεγάλα PDF/EPUB

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
│   ├── main.py              # Endpoints API (Upload, Translate, Audiobook, Polish, Settings, Download)
│   ├── ai_polisher.py       # Επιμέλεια κειμένου μέσω Google Gemini API
│   ├── format_preserver.py  # In-place DOCX/EPUB styling preservation
│   ├── exporter.py          # Εξαγωγή TXT, DOCX, EPUB, Rich PDF & Literature/E-Reader layout
│   ├── glossary.py          # Διαχείριση προσαρμοσμένου γλωσσαρίου όρων
│   ├── settings_manager.py  # Αποθήκευση/ανάγνωση ρυθμίσεων (config/settings.json)
│   ├── translator.py        # Μηχανή μετάφρασης (Google GTX client API)
│   ├── tts_engine.py        # Παραγωγή ήχου edge-tts (Nestoras / Athina)
│   ├── job_manager.py       # Διαχείριση εργασιών, ανάκτηση από δίσκο & αυτόματος καθαρισμός
│   └── parsers.py           # Αναλυτές εγγράφων PDF, DOCX, EPUB
├── config/
│   ├── glossary.json        # Αποθηκευμένο γλωσσάρι όρων
│   └── settings.json        # Τοπικές ρυθμίσεις & API keys (gitignored)
├── frontend/                # Static files (HTML, CSS, JS)
├── temp/
│   ├── uploads/{job_id}/    # Αποθηκευμένα αρχεία εισόδου
│   └── outputs/{job_id}/    # Μεταφρασμένα αρχεία και MP3 audiobooks
├── tests/                   # Αυτοματοποιημένα τεστ
└── requirements.txt
```

### Διαχείριση Εργασιών, Ρυθμίσεων & Εξωφύλλων μέσω REST Endpoints
Η εφαρμογή παρέχει ολοκληρωμένο REST API για τη διαχείριση εργασιών, ρυθμίσεων και εικόνων εξωφύλλου:
* `DELETE /api/jobs/{job_id}`: Διαγράφει συγκεκριμένη εργασία, καθαρίζει τη μνήμη και αφαιρεί οριστικά τους φακέλους `temp/uploads/{job_id}` και `temp/outputs/{job_id}` από το δίσκο.
* `DELETE /api/jobs`: Καθαρίζει ολόκληρο το ιστορικό και διαγράφει όλα τα προσωρινά αρχεία στο `temp/uploads/` και `temp/outputs/`.
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

Η εφαρμογή περιλαμβάνει πλήρη σουίτα αυτοματοποιημένων ελέγχων στο φάκελο `tests/`. Για να επιβεβαιώσετε την ορθή λειτουργία όλων των υποσυστημάτων:

```bash
# Βεβαιωθείτε ότι το .venv είναι ενεργό και ο server εκτελείται
python -c "import sys; sys.path.insert(0, '.'); import tests.test_parsers, tests.test_exporter, tests.test_translator, tests.test_format_preservation, tests.test_literature_formatting, tests.test_dynamic_download, tests.test_editor_glossary_ai, tests.test_standalone_ai_polish, tests.test_api"
```

Όλοι οι έλεγχοι πρέπει να ολοκληρωθούν με **`PASSED`**.

---

## 7. Αντιμετώπιση Τεχνικών Προβλημάτων (Troubleshooting)

| Σύμπτωμα | Πιθανή Αιτία | Λύση |
|---|---|---|
| **Σύμβολα με ερωτηματικό (`[?]`) σε bullets στο DOCX** | Μη συμβατοί χαρακτήρες Private Use Area (PUA) από γραμματοσειρές Wingdings/Symbol στο πρωτότυπο έγγραφο. | Έχει επιλυθεί αυτόματα: το backend φιλτράρει όλα τα PUA σύμβολα, τα μετατρέπει σε Unicode κουκίδες (`•`) και εφαρμόζει native Word `List Bullet` παραγράφους. |
| **Αλλαγή μορφής κατά τη λήψη κατέβαζε το αρχικό format** | Το download endpoint δεν λάμβανε παραμέτρους μορφής. | Έχει επιλυθεί: το endpoint υποστηρίζει πλέον `GET /api/download/{job_id}?format=pdf\|docx\|epub\|txt` και μετατρέπει ακαριαία το αποτέλεσμα on-demand. |
| **Σφάλμα 404 κατά τη λήψη (`Job not found`)** | Επανεκκίνηση του server με απώλεια μνήμης. | Έχει επιλυθεί αυτόματα: ο `job_manager.py` ανακτά αυτόματα τις εργασίες απευθείας από τον φάκελο `temp/outputs/` στο δίσκο. |
| **Σφάλμα `NoAudioReceived` στο Audiobook** | Ελλιπές λεξικό της φωνής Athina σε σύνθετα ακρωνύμια (π.χ. `UPS`, `Server Room`). | Έχει επιλυθεί αυτόματα: ορίστηκε ως κύρια φωνή ο **Nestoras** και προστέθηκε αυτόματο fallback. |
| **Η μπάρα προόδου δεν κινείται (μένει στο 0%)** | Ο proxy ή το firewall μπλοκάρει τα Server-Sent Events (SSE). | Βεβαιωθείτε ότι στο Nginx έχει τεθεί `proxy_buffering off;` και `proxy_read_timeout 86400s;`. |
| **Η μετάφραση αποδίδει μόνο «Page 1, Page 2»** | Το PDF είναι σκαναρισμένο (εικόνες) χωρίς ψηφιακό επίπεδο κειμένου. | Ενημερώστε τον χρήστη ότι απαιτείται OCR πριν την εισαγωγή του αρχείου. |
| **Σφάλμα HTTP 429 στη μετάφραση** | Υπερβολικά γρήγορα αιτήματα στο scraping endpoint. | Έχει επιλυθεί: η εφαρμογή χρησιμοποιεί πλέον το direct client API (`client=gtx`) που αποκρίνεται σε χιλιοστά του δευτερολέπτου χωρίς bot-blocking. |
| **Σελίδα εμφανίζεται αμετάφραστη (στα Αγγλικά) μετά από μετάφραση** | Προσωρινό rate limit της Google ή αποκοπή μεγάλου URL στο GET request. | Έχει επιλυθεί πλήρως: η μηχανή χρησιμοποιεί HTTP POST (χωρίς όριο μήκους URL) και επικυρώνει υποχρεωτικά την ύπαρξη ελληνικού κειμένου (`has_greek_text`). Σε περίπτωση σφάλματος εφαρμόζει εκθετικό backoff και επαναλαμβάνει αυτόματα. |
| **Κατέβασμα εικόνας εξωφύλλου αντί για το αρχείο βιβλίου** | Κατά το recovery του job, το `cover_image.jpg` αναγνωριζόταν ως αρχείο εξόδου. | Έχει επιλυθεί: τα αρχεία εικόνων (`.jpg`, `.png`, `.webp`) εξαιρούνται αυστηρά από τα candidate output files του `job_manager.py` και του `/api/download`. |
| **Σφάλμα Rate Limit / Quota (429) στο Gemini AI Polish** | Υπερβολικός αριθμός αιτημάτων ανά λεπτό (15 RPM) σε πολυσέλιδα βιβλία. | Έχει επιλυθεί: υλοποιήθηκε έξυπνη ομαδοποίηση σε παρτίδες (Smart Batching ~5 σελίδων / 10k chars ανά κλήση) μειώνοντας τις κλήσεις κατά 80%, με όριο ταυτόχρονων αιτημάτων (semaphore=2) και δυναμικό backoff 12s–48s. |
