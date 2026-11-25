# 📖 User Manual
### DocTranslate & AudioBook Generator

Welcome to the **DocTranslate & AudioBook Generator** user guide. This application allows you to translate documents between English and Greek while preserving original formatting, as well as create professional-grade AI audiobooks in MP3 and M4B formats using natural Microsoft Edge neural voices.

---

## 📑 Table of Contents
1. [Accessing the Application](#1-accessing-the-application)
   - [Help: Guide & FAQ](#-help-guide--faq)
   - [Light by Day, Dark at Night](#--light-by-day-dark-at-night)
   - [Signing In & Your Account](#-signing-in--your-account)
   - [Managing Users (Administrators)](#-managing-users-administrators)
2. [Operating Modes: Basic Mode vs Advanced Mode](#2-operating-modes-basic-mode-vs-advanced-mode)
3. [Document Translation](#3-document-translation)
   - [Supported File Formats](#supported-file-formats)
   - [Graphic Novels, Comics & Manga (RTL)](#-graphic-novels-comics--manga-rtl)
   - [Scanned PDFs (Page Images Only)](#-scanned-pdfs-page-images-only)
   - [Auto-Genre & Document Style Detection](#-auto-genre--document-style-detection)
   - [Automatic Greek Editorial Typography](#-automatic-greek-editorial-typography)
   - [Step-by-Step Translation Guide](#step-by-step-translation-guide)
   - [Output Format Selection](#output-format-selection)
   - [Document Layout Styles](#document-layout-styles)
   - [Book Cover Image Management](#-book-cover-image-management)
   - [Gemini Quota Handling Choice & Free Mode](#-gemini-quota-handling-choice--free-mode)
   - [Instant On-Demand Export Without Retranslating](#-instant-on-demand-export-without-retranslating)
   - [Distraction-Free "Read Now" Reader View](#-distraction-free-read-now-reader-view)
   - [Smart Resume Banner](#-smart-resume-banner)
   - [Live ETA, Speed & Hybrid Engine Badge](#-live-eta-speed--hybrid-engine-badge)
   - [In-Browser Review & Edit](#-in-browser-review--edit)
   - [Gemini AI Polish & Proofreading](#-gemini-ai-polish--proofreading)
   - [Gemini Multi-Key API Pool & Auto-Failover](#-gemini-multi-key-api-pool--auto-failover)
   - [Categorized Custom Glossary](#-categorized-custom-glossary)
   - [In-Place Layout & Style Preservation](#in-place-layout--style-preservation)
   - [Automatic Final Quality Check](#-automatic-final-quality-check-final-output-refinement)
4. [Audiobook Generation](#4-audiobook-generation)
   - [Available Neural Voices & Live Auditions](#available-neural-voices--live-auditions)
   - [Multi-Voice Dramatization](#-multi-voice-dramatization)
   - [M4B Export & Embedded Cover Art](#-m4b-export--embedded-cover-art)
   - [Step-by-Step Audiobook Guide](#step-by-step-audiobook-guide)
   - [Direct Conversion: Send to Audiobook](#direct-conversion-send-to-audiobook)
   - [Narration Styles, Speed & Pitch Tuning](#-narration-styles-speed--pitch-tuning)
   - [AI Polish for Spoken Audio](#-ai-polish-for-spoken-audio)
   - [Built-In Pro Audiobook Player](#-built-in-pro-audiobook-player)
   - [Understanding Progress: "Audio Parts" vs "Pages"](#understanding-progress-audio-parts-vs-pages)
5. [Book Insights: Summaries, Synopses & Audio](#5-book-insights-summaries-synopses--audio)
6. [Session History & Task Management](#6-session-history--task-management)
7. [Frequently Asked Questions & Troubleshooting](#7-frequently-asked-questions--troubleshooting)

---

## 1. Accessing the Application

Open your modern web browser (Google Chrome, Microsoft Edge, Mozilla Firefox, Brave, or Safari) and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)** *(the web interface also adapts automatically to `http://127.0.0.1:8000` or your local network LAN IP)*

If BookApp runs on a server or a Synology NAS, open the address your administrator gives you, for example `http://10.9.251.250:2000`. Installing it is described in the [Administrator Manual, section 3](ADMIN_MANUAL.md#3-step-by-step-installation).

You will see the main user interface with two primary tabs at the top:
* 🌐 **Translate Document**
* 🎧 **Generate Audiobook**

### 🌐 Interface Language: Ελληνικά / English
The **ΕΛ | EN** switch at the top right (next to Refresh and Theme, and on the sign-in page) shows the whole interface in Greek or in English: menus, tabs, buttons, settings, tooltips, notifications, a job's progress steps, its final notes and error messages. The choice is remembered in your browser. The first time, BookApp follows your browser's language. Each person sees their own choice, also on a shared server.
* Your books, file names, glossary terms and the reader's text are never translated by the switch.
* Product and format names stay as they are in both languages (AI Polish, Smart Batch Queue, Gemini, PDF, EPUB…), and so do technical details quoted inside a message (an HTTP code, a model's error text).

### ❓ Help: Guide & FAQ
The **❓ Help** button in the tab bar opens a short guide (translation, audiobooks, Book Insights, Gemini keys) and answers to frequently asked questions: whether you need a Gemini key, why a translation can take hours, what happens when the daily Gemini limit runs out, whether several keys from one Google account help, what survives closing the page or a server restart, how accurate the time left is, what Maximum quality does, translating a scanned PDF (no OCR needed, but a Gemini key is), names translated inconsistently, where your files go, a forgotten password, the iPhone home screen and an old look after an update. It shows in the interface language (ΕΛ | EN). Close it with ✕, Esc or a click outside.

### ☀️ / 🌙 Light by Day, Dark at Night
The interface is light from sunrise to sunset and dark at night, by itself (the times follow the date; on Greek time they are those of Athens). The **Theme** button at the top right still switches it whenever you like: your choice holds until the next sunrise or sunset, and then the automatic theme takes over again. Hover over the button to see until when your choice lasts.

### 🔐 Signing In & Your Account

If your administrator has switched on user accounts, BookApp first shows a sign-in page:
* **Username and password** are given to you by an administrator. The first password is **temporary**: right after signing in you choose your own (at least 10 characters; a phrase of a few words is ideal).
* **Να παραμείνω συνδεδεμένος/η** (ticked by default) keeps you signed in on that device for 60 days, and every visit starts the 60 days again. If you use BookApp regularly, you stay signed in until you press **🚪 Αποσύνδεση**. Untick it on a shared computer: you are then signed out when the browser closes.
* **👤 your name** (top right) shows your role, your last sign-in and your Gemini use today, and lets you **change your password**. Changing it signs you out on your other devices.
* **Forgot your password?** Ask an administrator to reset it; you get a new temporary password.
* **5 wrong passwords** pause sign-in to that account for 15 minutes.
* **Privacy between users:** you see only your own jobs in Session History, the batch queue and everywhere else. The Gemini API keys and the shared settings are managed by the administrators, so the 🔑 button is not shown to you.

### 👥 Managing Users (Administrators)

Administrators see the **👥 Χρήστες** button next to their name:
* **Create a user:** type a username, choose *Χρήστης* or *Διαχειριστής* and press **➕ Δημιουργία**. Leave the password field empty to get a temporary password, shown once with a **📋 Αντιγραφή** button. Give it to the person; they choose their own at the first sign-in.
* **⭐ Κάνε διαχειριστή:** the user gets exactly your rights (users, API keys, settings, all jobs). **⬇️ Αφαίρεση δικαιωμάτων διαχειριστή** turns an administrator back into a user.
* **🔑 Επαναφορά κωδικού:** a new temporary password; the user is signed out everywhere.
* **⏸️ Απενεργοποίηση / ✅ Ενεργοποίηση:** blocks or restores sign-in; disabling signs the user out at once.
* **🚪 Αποσύνδεση παντού:** ends all of the user's sessions (for example, a lost phone).
* **🗑️ Διαγραφή:** you choose whether the user's jobs are transferred to you or deleted with their files.
* There is always at least one active administrator: the app refuses to demote, disable or delete the last one, and you cannot disable or delete your own account.
* **Session History** has a filter for administrators: *Οι εργασίες μου* (default, including jobs from before accounts were switched on), *Όλοι οι χρήστες*, or one user. With the filter on someone else's jobs, **🗑️ Clear All** deletes only those.
* **📜 Ιστορικό ενεργειών διαχείρισης** at the bottom lists who created, promoted, reset, disabled or deleted which account.

---

## 2. Operating Modes: Basic Mode vs Advanced Mode

Directly above the main tabs is the global mode switcher:

```text
[ ⚡ Basic Mode (1-Click AI) ]   [ ⚙️ Advanced Mode (Full Control) ]
```

Your selection is saved automatically in browser `localStorage` and persists across sessions.

### ⚡ Basic Mode (Default — 1-Click AI)
Designed for maximum ease of use and zero cognitive load:
* **AI Enabled by Default:** Both Translation and Audiobook generation have AI Polish automatically enabled for literary fluidity and natural phrasing.
* **1-Click Translation:**
  * Drop your file (PDF, DOCX, EPUB, Comic).
  * **Automatic Output Format Matching:** The output format is automatically matched to your input document (`.pdf` ➔ PDF, `.docx` ➔ DOCX, `.epub` ➔ EPUB, `.cbz/.cbr` ➔ Comic).
  * **Auto-Genre Detection & Application:** The engine analyzes the text and automatically applies the optimal style (e.g. Literary fiction with dialogue dashes `—`), immediately showing `✓ Auto-applied` without requiring any manual clicks.
  * Click **`✨ Translate Book with AI (1-Click)`**.
* **1-Click Audiobook:**
  * Automatically preselects the natural Greek voice **Nestoras Neural** at the ideal literary pacing (-12% speed).
  * Click **`🎧 Generate Audiobook with AI (1-Click)`**.
* **Clean Interface:** Granular options (format pickers, layout selectors, speed/pitch fine-tune sliders, multi-voice grids) are hidden to maintain focus.

### ⚙️ Advanced Mode (Full Control)
For users who require granular configuration over every parameter:
* Language direction selection (🇬🇧 ⇄ 🇬🇷).
* Manual export format selection (PDF, DOCX, EPUB, CBZ, CBR, TXT).
* Document layout styles (Standard, Literature/E-Reader, Comic/Graphic Novel).
* Manga reading direction (Right-to-Left / RTL).
* Book cover image upload, preview, and removal.
* Gemini quota exhaustion routing choice (Wait for Reset with live timer vs Auto-Fallback to Free model).
* Full neural voice grid, narration style dropdown, speed sliders (-30% to +30%), and pitch sliders (-4Hz to +4Hz).
* Multi-Voice Dramatization with separate narrator and dialogue voices.

---

## 3. Document Translation

### Supported File Formats
* 📄 **PDF** (`.pdf`) — Digital PDF documents and Graphic Novels / Scanned PDFs
* 📘 **Word** (`.docx`) — Modern Microsoft Word documents
* 📗 **EPUB** (`.epub`) — Reflowable and Fixed-Layout E-books
* 🎨 **CBZ / CBR / ZIP** (`.cbz`, `.cbr`, `.zip`) — Digital Comic Books and Manga
* 📝 **TXT** (`.txt`) — Plain text files

*(Note: Legacy `.doc` files should first be opened in Microsoft Word and saved as `.docx`).*

### 🎨 Graphic Novels, Comics & Manga (RTL)
The application includes a specialized pipeline for illustrated publications:
1. **100% Preserved Artwork:** The engine translates **strictly the text inside speech balloons**, keeping all original artwork completely intact.
2. **Two-Pass Inpainting & Rendering:** Original English dialogue is cleanly erased and infilled with the balloon's authentic background color across two passes (all backgrounds filled first, then all centered text drawn on top, preventing overlapping balloons from obscuring neighboring text).
   - On scanned pages the app finds each balloon's outline. The English is erased in the balloon's own shape and colour, every letter of it even where Gemini's box was too small, and the outline and the artwork around it stay untouched (no white rectangles).
   - The Greek follows the balloon's shape: an oval gets shorter lines at the top and bottom, centred where the original text was.
   - Text sizes follow the original lettering, so a short line is no longer lettered twice as big as its neighbours.
   - Text written straight on the artwork, without a balloon, still gets a rectangle behind it, as does text too long for a very small balloon, so it stays readable.
3. **Smart Fit-to-Box (Zero Blank Balloons) & Natural Page Sorting:** Because Greek text takes ~20% more space, the engine deterministically computes the ideal font size (down to `3.0pt` with whole-word wrapping, fallback to `Arial Narrow`, and subtle bounding box expansion where necessary) — ensuring **no balloon is ever left blank**. For `.cbz`/`.zip` archives, pages are sorted using **natural numeric order** (`page_1`, `page_2`, ..., `page_10`) with Zip Slip security checks. The dialogue sanitizer standardizes comic uppercase Greek (`Ϊ`/`Ϋ`), elision apostrophes (`Σ'`, `ΓΙ'`), and Greek question marks (`;`).
4. **Japanese Manga Support (Right-to-Left — RTL):**
   - Select **Manga (Right-to-Left ⬅️)** under Reading Direction.
   - Speech balloon detection and translation ordering are sorted top-to-bottom and **right-to-left**.
   - Fixed-Layout EPUB exports embed the standard `page-progression-direction="rtl"` directive so e-readers flip pages from right to left naturally.
5. **Permitted Comic Export Formats:**
   - **PDF**, **CBZ** (Comic Book Zip), **CBR** (Comic Book RAR, a real RAR archive), and **EPUB** (Fixed-Layout).
   - Plain text formats (TXT and DOCX) are automatically disabled for comics to protect users from artwork loss.
6. **Checks on scanned pages:**
   - A page that comes back in Latin letters (Greeklish, such as `KALIMERA`) or with mixed alphabets goes to the next Gemini model. Greeklish is never kept.
   - A page that comes back empty is checked by a second model, so a page full of balloons is not skipped.
   - **A name is spelled one way through the whole book.** Each page is told how the earlier pages wrote the names, and before the PDF is drawn every name gets the spelling most pages used. To choose a spelling yourself, add the name to the **Glossary** (for example `Kowalsky` → `Κοβάλσκι`): the glossary always wins. Greek case endings (`ΔΙΟΙΚΗΤΑ` / `ΔΙΟΙΚΗΤΗΣ`) are left as they are.
   - When the job finishes, the progress card lists the pages left untranslated, with the reason, and the scanned pages where no text was found (see the FAQ below).

### 📑 Scanned PDFs (Page Images Only)
A scanned PDF can be translated as it is, **without OCR**:
* On upload the app sees that the pages are pictures with almost no text, shows `🎨 Graphic Novel / Comic Auto-Detected` and switches to the **Graphic Novel** layout by itself. You do not need to choose it.
* **Gemini Vision** reads the text from the page images, and the translation is drawn onto the same pages as described above. This needs a Gemini key; without one the job stops with a message saying so.
* It is made for comics. A scanned novel takes the same path, so it comes out as page images with the translation drawn on them (PDF, CBZ, CBR or Fixed-Layout EPUB), not as plain text.
* **When you do need OCR first:** for a translation as plain text (DOCX, TXT or a normal EPUB), for an audiobook, and for Book Insights. These read the PDF's text, and a scanned PDF has none. An OCR program (for example the free OCRmyPDF) adds a text layer; then upload the new PDF.

### 💡 Auto-Genre & Document Style Detection
Upon uploading a document, the system automatically analyzes the opening pages:
* Detects whether the file is **Literature**, **Poetry**, **Technical Documentation**, **Formal / Administrative**, or a **Graphic Novel**.
* Displays an informative badge (e.g. `💡 Detected genre: Literature (85% confidence)`).
* If the book describes itself as poetry or fiction (the subject saved in the EPUB, PDF or Word file), BookApp follows that instead of judging from the text. A book *about* poetry ("… history and criticism") is still judged from its text.
* In Advanced Mode, clicking **"Apply Recommended"** automatically aligns the layout style, AI Polish prompt, and glossary category. In Basic Mode, the recommendation is **automatically applied immediately** (`✓ Auto-applied`).

### ✍️ Automatic Greek Editorial Typography & Scripted Sanitization Pass
All translated text passes automatically through the built-in publishing typography and scripted editorial engine (`backend/typography.py`):
* **Cross-Lingual Script Bleed & Tokenizer Glitch Remediation:** Automatically catches and corrects subword tokenizer leakages: Polish past-tense suffixes (`μπορούσłεś` ➔ `μπορούσες`, `αναζητούłεś` ➔ `αναζητούσες`), micro sign characters (`µ` ➔ `μ`), Hebrew glyphs (`ד`/`ט`/`ם`), Armenian letters (`ի`/`տ`), Arabic, Ge'ez, Devanagari, Vietnamese words, and Latin homoglyphs in Greek words (`k` ➔ `κ`, `pt` ➔ `πτ`, `an` ➔ `αν`, `for` ➔ `φορ`, `ti` ➔ `τι`, `Ta` ➔ `Τα`), while strictly shielding scientific & SI units (`10μm`, `Δt`, `50μg`, `Ωm`).
* **Code Leaks & Foreign Word Purge:** Strips programming artifacts like `iterrows` ➔ `ίσως`, and corrects foreign words that leak into Greek sentences (`podría` ➔ `μπορούσε`, `στην hull του` ➔ `στο κύτος του`, `Το riven φουσκωτό` ➔ `Το σχισμένο φουσκωτό`, `Gang` ➔ `Συμμορία`, `Major` ➔ `Ταγματάρχη`, `αδοσυμεντεδ` ➔ `μη καταγεγραμμένων`).
* **Comedic Machine Translation Calques & False Friends:** Automatically fixes glaring literal machine translation idioms:
  - `«κατινιάσει τα πέταλα»` ➔ `«τινάξει τα πέταλα»` *(kicked the bucket)*
  - `«άλωσε το πληκτρολόγιο»` ➔ `«άρπαξε το πληκτρολόγιο»` *(took up the keyboard)*
  - `«αλόγους της Παναγίας»` ➔ `«αλογάκι της Παναγίας»` *(praying mantis)*
  - `«το σκιασμένο πάνθηρα»` ➔ `«το σκιασμένο πλαίσιο»` *(shaded panel)*
  - `«για ζήση»` ➔ `«για βιοπορισμό»` *(for a living)*
  - `«να το λείψω»` ➔ `«να ζήσω χωρίς αυτό»` *(do without it)*
  - `«ανθρωπάκια της κάψουλας»` ➔ `«άνθρωποι των λοβών»` *(pod people)*
  - `«Είναι μια παρθένη, Σουζ»` ➔ `«Είναι μια παραίσθηση, Σουζ»` *(form constant / hallucination)*
  - `«σπερματική παρατήρηση»` ➔ `«θεμελιώδης παρατήρηση»` *(seminal observation)*
  - `«κουζίνα προμήθειες»` ➔ `«προμήθειες της κουζίνας»` *(galley supplies)*
* **Double Accent & Orthography Normalization:** Eliminates OCR or MT double tones (`σκύλί` ➔ `σκυλί`, `βαθύνόμενο` ➔ `βαθαινόμενο`, `κύλούσαν` ➔ `κυλούσαν`) while strictly preserving legitimate Greek grammatical enclitics (`το όνομά μου`, `κάνοντάς τα`, `εκτοξεύοντάς τα`) and stripping orphan enclitics on proparoxytone words when clitics are dropped.
* **Machine Translation Stutter Elimination:** Removes accidental repeated word stutters (`ο Σπίντελ ο Σπίντελ` ➔ `ο Σπίντελ`, `μια διασπασμένη μια διασπασμένη` ➔ `μια διασπασμένη`, `Παραπομπές\n\nΠαραπομπές` ➔ `Παραπομπές`).
* **URL Protection & Restoration:** Restores web paths erroneously translated into Greek (e.g. `.../βαμπίρ.htm` ➔ `.../vampires.htm`), and shields URL tokens from subword alterations.
* **Final "ν" Grammatical Rule:** Enforces correct modern Greek usage of `δε/δεν` and `μη/μην`. It protects the conjunctive particle **«δε»** in literary and legal contexts (e.g. *«εάν δε προκύψει»*, *«ο δε υπουργός»*) without corrupting it into the negation «δεν». Verbal «μην» retains «ν» before vowels and stops/affricates (`μην έρθεις`, `μην πας`) and drops it before continuants (`μη λες`, `μη χάνεις`), while privative **«μη»** strictly drops the «ν» before adjectives, participles, nouns, and adverbs (e.g. `μη απαραίτητα`, `μη επανδρωμένος`, `μη επεμβατικές`, `Μη Εμπορική Χρήση`).
* **Hyphenated Line Breaks & Elision Apostrophes:** Automatically rejoins words broken across line wraps (`υποσχέ- θηκαν` ➔ `υποσχέθηκαν`) without joining interrupted dialogue (`Περίμενε- μην`), and restores elision apostrophes (`Σ ΑΥΤΗΝ` ➔ `Σ' ΑΥΤΗΝ`, `ΓΙ ΑΥΤΟ` ➔ `ΓΙ' ΑΥΤΟ`).
* **Greek Quotation Marks & Emphasis:** Replaces straight double quotes `"` with publishing guillemets `«...»` (preserving code blocks in ` ``` `), and converts `*italics*` and `**bold**` into native italic/bold typography (Georgia Italic in PDF, `italic` runs in DOCX, `<em>` in EPUB).
* **Dialogue Dashes, URLs & Punctuation:** Hyphens at line starts turn into standard dialogue em-dashes (`—`) without altering numbered lists, and English question marks (`?`, `?!`, `??!!`) turn into Greek question marks (`;`, `;!`, `;;!!`) while strictly protecting URLs and relative paths (`../`).

### Step-by-Step Translation Guide
1. **Upload Document(s) (1 file or up to 20 files in Smart Batch Queue):**
   - Drag and drop **1 or multiple files (up to 20 files, max 250 MB per file)** onto the **"Drop your document(s) here"** upload card, or click to browse files.
   - **While a file uploads**, a bar under its name shows the percent and the MB sent (`⬆️ Ανέβασμα 45% (5.5 / 12.3 MB)`), then `⏳ Ανέβηκε· επεξεργασία αρχείου…` while the server counts the pages and checks whether it is a comic (a few seconds for a large comic). Removing the file meanwhile stops the upload. When several files go to the queue, a line above the queue shows which file is uploading and the total progress; if any file fails, the line stays and lists each one with the reason.
   - **Very long file names** (downloaded books often have 200+ characters with authors, ISBN and a code) are shortened to their first 100 characters when stored, because longer names no longer fit the disk paths of the output files. The extension stays.
   - For **1 file**: Displays the filename, size, estimated pages (e.g. `~340 pages · PDF · Ready`) and an **➕ Add More** button next to `✕` to seamlessly add more files.
   - For **2+ files**: The **Smart Batch Queue** view opens immediately inside the upload card (allowing you to add more files, enable **⚡ Auto-Start**, or remove individual items).
   - **⚡ Auto-Start starts the queue as soon as files are added.** It is locked when the queue mixes books with comics or graphic novels, so you check the settings and press **▶️ Start Batch Translation** yourself. A note under the switch says so. Each file still keeps the settings of its kind: comics always get the Comic layout, and a scanned comic always gets AI Polish.
   - *(Validation check: empty 0-byte files or corrupted archives are rejected immediately with clear error alerts).*
2. **Translation Direction:**
   - Default: **🇬🇧 English ➔ 🇬🇷 Greek**.
   - Click **⇄** to invert to **🇬🇷 Greek ➔ 🇬🇧 English**.
3. **Output Format Selection & Automatic Matching:**
   - **Automatic Output Format Matching:** When uploading any document, the application automatically matches the default output format to your input document (`.pdf` ➔ PDF, `.docx` ➔ DOCX, `.epub` ➔ EPUB, `.cbz/.cbr` ➔ Comic).
   - In Advanced Mode, you can manually override the export format:
     - 📕 **PDF:** Formatted PDF with custom headers and complete Greek Unicode glyph support (zero missing-glyph tofu boxes `□`).
     - 📘 **DOCX:** Microsoft Word document with full preservation of fonts, tables, headings, and styles.
     - 📗 **EPUB:** E-book formatted with chapters, navigation, and HTML/CSS styling.
     - 🎨 **CBZ / CBR:** Digital comic archive with speech balloons translated (CBZ is a ZIP archive, CBR a RAR archive).
     - 📄 **TXT:** Clean plain text.
   - **Instant On-Demand Conversion:** Even after translation completes in one format, you can download any of the other formats (PDF, DOCX, EPUB, TXT) instantly via the 1-click download pills on the result card.
4. **Document Layout Styles:**
   - 📄 **Standard / Office (A4):** Preserves classic document styling, A4 pagination, and exact paragraph spacing. Ideal for legal papers, technical reports, and corporate documents.
   - 📚 **Literature / E-Reader:** Tailored for novels, fiction, and e-readers:
     - **Strips Running Headers & Footers:** Automatically removes page numbers, author names, and book titles repeating at page margins.
     - **Isolated Chapter Titles:** Detects chapter markers (*Chapter 1*, *Prologue*, *IV*) and isolates them on their own line with larger styling.
     - **Epigraph Isolation:** Separates quotes and source attributions (e.g. «—Ted Bundy») from main narrative blocks.
     - **Cross-Page Sentence Continuation:** Smoothly merges sentences broken by page breaks in the source file.
     - **Scene Breaks:** Centers and standardizes divider marks (e.g. `* * *`).
     - **Table of Contents:** a contents page is recognised and shown as a clean list under "Περιεχόμενα". The original edition's page numbers are replaced by this PDF's own page numbers, and the titles it lists (parts or named sections) start on a new page, as in the printed book.
     - **Bookmarks:** the PDF has a bookmark for every chapter, so a reader app's sidebar jumps straight to it.

5. **🎨 Book Cover Image Management:**
   - **Auto-Detection & Extraction:** When uploading a PDF, EPUB, or DOCX, the first page is analyzed. If full-page artwork is detected, it is extracted immediately, a thumbnail is displayed, and the badge turns green:  
     `✔ Cover active (Automatically embedded on page 1 of PDF, EPUB & DOCX)`.
   - **Manual Cover Upload:** Click **📷 Upload Cover** to select any custom image file (`.jpg`, `.png`, `.webp`).
   - **Cover Removal:** Click **✕ Remove** to export the document cleanly without cover artwork.
   - **Final Placement:** Active covers are embedded as:
     - Full-bleed unpaginated page 1 in **PDF**.
     - Official e-book cover metadata in **EPUB**.
     - Document title page in **DOCX**.
   - **Exception:** a DOCX or EPUB translated in its original format, and every comic, keeps its own artwork and formatting. A custom cover is not inserted into those files (the app tells you); it is used for the other formats you download.

6. **⚡ Gemini Quota Handling Choice & Automatic Resumption:**
   - Choose how the system behaves if the Google Gemini API daily limit is exceeded:
     * **⏳ Wait for Reset & Auto-Resume (Default with API Key):** Pauses safely at disk checkpoint (`.direct_ai_checkpoint.json` or `.comic_vision_checkpoint.json`). Displays a live countdown timer and **automatically resumes translation, audiobook generation, and queued batch items the moment the cooldown timer reaches zero or when a new key is added**, without requiring manual user intervention. **Preserves 100% Gemini literary quality and artwork**. Never downgrades or falls back to plain Google Translate unless explicitly requested.
     * **🔄 Auto-Fallback to Free Model (Explicit Opt-In Only):** Routes remaining batches to the free translation engine and Edge-TTS without stopping (only used if explicitly selected by the user).
   - **Wait for Reset is selected every time the page opens** (whenever an API key exists), in both the Translate and the Audiobook tab. Choosing Auto-Fallback applies only until the page is reloaded, so a one-time choice never becomes the new default. Opening a job from Session History shows the choice that job was run with.
   - **🆓 Free Mode Default:** When no Gemini API key is configured anywhere in the pool, BookApp automatically operates in **Free Mode** (indicated by the `🆓 Free Mode` pill in the navbar). Translation, typography rules, and neural audiobooks run 100% free with zero keys or subscriptions.

7. **Starting Translation:**
   - Click **🌐 Start Translation** (for a single file) or **▶️ Start Batch Translation** (for multiple files).
   - The live progress bar reflects exact completion metrics (e.g. `Completed 12 of 103 AI batches (45 / 340 pages)`).

8. **Downloading Result & Copying Text:**
   - Click **⬇️ Download [FORMAT]** to save your translated book.
   - The **📄 PDF · 📝 DOCX · 📱 EPUB · 📃 TXT** buttons next to it download another format, and that format becomes the chosen one: the main button then says, for example, **⬇️ Download DOCX** and downloads DOCX.
   - **📋 1-Click Copy Text:** Copies all translated text directly to your clipboard with visual confirmation (`✅ Copied!`).
   - **🔔 Completion Chime & Notification:** Plays a gentle synthesizer chime and delivers an OS desktop notification when long tasks finish in the background.

### ⚡ Instant On-Demand Export Without Retranslating
You never need to re-translate a document to obtain another file format:
* **1-Click Multi-Format Download Pills:** Direct download buttons for each supported format are embedded right into the Translation Result Card:
  * 📄 **PDF** — Standard or Literature layout with embedded cover art and zero tofu glyph boxes.
  * 📝 **DOCX** — Formatted Word document preserving headers, fonts, and styles.
  * 📱 **EPUB** — E-reader publication with spine and chapter formatting.
  * 📃 **TXT** — Clean UTF-8 plain text for quick reading or scripts.
* Clicking any format generates and downloads the file **instantaneously (< 1 second)** on-demand from the cached translation text without re-translating or consuming quota.

### 📖 Distraction-Free "Read Now" Reader View
Read your translated book directly inside the application:
1. Click **📖 Read Now (Reader)** on the result card.
2. A clean reading modal opens with:
   * **3 Themes:** **📄 Paper**, **📜 Sepia**, **🌙 Dark Night**.
   * **Font Size Zoom (A- / A+):** Easily adjustable text scaling.
   * **View Modes:** **📄 Single Column** (for distraction-free reading) or **↔️ Side-by-Side** (for bilingual English ↔ Greek sentence comparison).

### 📌 Smart Resume Banner
If a translation or audiobook generation is interrupted (due to quota pause, computer restart, or accidental browser closure):
* Reopening `http://localhost:8000` displays a banner at the top:
  > 📌 **Interrupted Job Checkpoint:** "*Book Title*" *(X/Y chunks · Z% complete)*.
* Click **▶️ Resume NOW** to immediately continue execution from the saved disk checkpoint without searching through history.

### ⏱️ Live ETA, Speed & Hybrid Engine Badge
The active progress card displays real-time telemetry:
* **⏳ Time left:** the estimated time to completion (`~1 hour 53 minutes`) and the current speed (`2.0 pages/min`, or `parts/min` for audiobooks and documents translated in place). It is measured over the last few minutes, so it settles about a minute after the page opens, also when you reload the page or resume a job. It hides while nothing moves (for example while waiting for the Gemini limits to renew) and starts measuring again afterwards.
  * With **Maximum quality** it shows `+ the 2nd AI pass afterwards`: the time is for the translation; the revision then shows its own time left in the progress line.
* **🏷️ Engine Badge:** Live indicator of the active processing provider:
  * `✨ Gemini Flash` when translating with your configured Gemini API key.
  * `⚡ Free Engine` when using the free fallback translation engine.
  * `⚡ Edge-TTS Neural` during audiobook narration synthesis.

### ✏️ In-Browser Review & Edit
1. Click **✏️ Review & Edit** on the result card.
2. The split-screen editor provides:
   * **Split View:** Original source text on the left, editable translation on the right with synchronized scrolling.
   * **Full Screen:** Expands the editor to focus purely on text polishing.
   * **🔍 Find & Replace:** Single and document-wide replacements (Replace All).
   * **Live Word & Character Counters.**
3. Click **💾 Save & Update Files** to instantly update all output files (Word, PDF, EPUB, TXT) and audiobook source text with your edits.
   * **DOCX→DOCX / EPUB→EPUB:** edits are made inside the document, keeping styles, tables, images and bold/italic. Replaced text takes the style of the words it replaced. Table-of-contents entries and hyperlink text don't change in the document.
   * **Paragraph breaks:** leave an empty line between paragraphs. A single line break stays in the same paragraph.
   * **Graphic Novels:** only the text is saved. Pictures and balloons don't change.
   * **If an edit can't be applied safely** (or the file is open in Word), you get a message and no file is changed.

### ✨ Gemini AI Polish & Proofreading
For publications requiring professional editorial tone:
1. Click **✨ AI Polish (Gemini)**.
2. Select from 5 tailored editorial styles:
   * 📚 **Literature, Fiction & Sci-Fi:** Preserves dramatic pacing, standardizes Greek guillemets (`«...»`), accurately translates genre terms (scramblers, fireflies), and maintains character gender consistency.
   * 🎧 **Audiobook Narration Script:** Prepares text for TTS voice synthesis. Phonetically transcribes foreign names and acronyms into Greek characters (`Keeton` ➔ `Κίτον`, `DNA` ➔ `Ντι-Εν-Έι`), spells out all numbers and years in full Greek words (`2006` ➔ `δύο χιλιάδες έξι`), and eliminates non-spoken markers.
   * 🏛️ **Formal & Administrative:** Tailored for public administration, legal briefings, and contracts.
   * 💻 **Technical & Precise:** Tailored for software guides, engineering manuals, and academic papers.
   * 📖 **Fluent & Natural:** Tailored for essays, journalism, and non-fiction articles.
3. **🎯 Source-Anchored Verification:** Compares the translated draft against original English paragraphs page-by-page to resolve false friends and translation omissions.
4. **🧠 Whole-Book Stratified Entity Consistency Dossier:** Scans the entire manuscript across 9 stratified excerpts to extract 35–60 recurring entities with explicit grammatical gender (`ο/η/το`).
5. **🔄 Rolling Context & Boundary Deduplication:** Feeds preceding sentences into `<PREVIOUS_CONTEXT_DO_NOT_REPEAT>` and cleans overlapping boundaries so paragraphs are never duplicated.

#### What AI Polish now pays attention to
With **AI Polish** on, the translation is written for a demanding reader:
* **Faithful to the original:** nothing left out, nothing added, no "decorated" wording. The author's voice and sentence rhythm are kept.
* **Natural Greek:** it avoids the typical signs of a translated text, such as needless "αυτός/αυτή", a "του/της" after every noun, chains of "ο οποίος", and literal idioms and false friends ("makes sense" is not "κάνει νόημα").
* **Correct typography:** chapter titles in Greek capitalisation ("Κεφάλαιο τρίτο: Το γράμμα…"), Greek punctuation, and «» quotation marks.
* **Nothing left in English:** the AI sometimes hands a passage back untranslated (often a violent or crude scene). BookApp refuses such an answer, splits the page into smaller pieces and asks again. If a page still stays in English, the job's final message lists it ("N page(s) still contain text in the original language…"); translate the file again to retry those pages.
* **Clean Greek letters:** a word with stray letters of another alphabet inside it (Cyrillic, Hebrew, Arabic, Chinese) is corrected at the end with one small extra AI request; any left over are named in the final message. Old-style polytonic accents (ῥ, ῶ, ἴ) become modern monotonic ones, unless the original itself is written in polytonic Greek.
* **One dialogue style:** when a part of the book comes back with dash dialogue (— …) although the original uses quotation marks, it is asked again, so the whole book uses «…».
* **Consistent across the whole book:** names, genders, how characters address each other (εσύ/εσείς), and narrative tense, using a register built from the whole book before translation starts.
* **Translations into English** now get English editing rules.

#### 🏆 Maximum quality (Advanced Mode)
Under **AI Polish** you can tick **🏆 Μέγιστη ποιότητα**. After the AI translation, a second AI "reviser" compares every sentence with the original, as a second editor at a publishing house would. It corrects mistakes of meaning, anything left out or added, grammatical agreement, inexact words and literally translated idioms. Anything already correct stays as it is.
* 🐢 **It is very slow:** count on about **3–8 seconds per page** on top of the AI translation (for example 15–40 minutes for a 300-page book). The warning that appears when you tick the box gives the estimate for your document, and while the revision runs the progress line shows the time left.
* ⚠️ **It costs more:** about **1.5×** the Gemini tokens of the AI translation. It sends about one Gemini request per 3 pages; a free key may allow only 20 requests a day per model, so on a long book the revision can stop early and you keep the first-pass translation.
* It needs AI Polish and a Gemini key; ticking it switches AI Polish on automatically.
* It always uses the full Gemini models. If those are unavailable (for example, their daily limit is used up), the revision is skipped and you keep the normal AI translation. The translation never fails because of this step.
* A notification at the end tells you how many lines were corrected.
* The revision is applied page by page. If a few pages come back unusable (missing, duplicated or cut short), only those pages keep the first-pass translation, and the notification and the job's final message say how many. If the revision doesn't complete at all, the final message says so, so you know you got only the first pass.
* It isn't applied to Smart Batch Queue items, and switching to Basic Mode turns it off.

### 🔑 Gemini Multi-Key API Pool & Auto-Failover
* **Connect up to 8 Free Gemini API Keys:** Enter keys in Slots 1 through 8 (Slot 1 Primary + Slots 2–8 Backups) from different Google accounts. Slots 5–8 are under **➕ Κλειδιά 5–8** and open by themselves once one of them holds a key.
* **Free daily allowance, per model:** Google gives each free key a daily allowance for each Gemini model, and it can be small (for example 20 requests a day for `gemini-3.5-flash`). Every key from another Google account adds its own allowance. BookApp uses the best model on **all** your keys before it falls back to a weaker one: with 4 keys that is 80 requests of the best model a day instead of 20. Google AI Studio shows your current limits.
* **All keys work together:** requests take the keys in turn (Slot 1, 2, 3, … then 1 again), so the batches that run at the same time use every key's per-minute pace and daily allowance. Every usable key therefore shows **🟢 Active**; none waits on standby.
* **Instant Automatic Failover:** when a key or one of its models reaches its limit (HTTP 429), the request moves **at once** to another key that still has it, without pausing or losing progress.
* **Keys stay on the server:** keys are stored only in the server configuration (`config/settings.json`) and shown masked in the page (e.g. `AIzaSy...4f2D`). The browser keeps no copy; keys saved in the browser by older versions are moved to the server once. Saving the window without typing a new key keeps your existing keys, so they're never accidentally wiped or duplicated when you switch tabs or refresh.
* **Auto-Resume on Save:** If a translation was waiting on quota, clicking **«💾 Save Pool»** with new keys immediately resumes the job automatically without requiring a manual resume click!
* **Navbar Pool Status Indicator:**
  * `🟢 4/4 Keys`: All configured keys are active and available.
  * `🟡 2/4 Keys`: Some keys are cooling down, but backup keys remain available.
  * `⏳ Cooldown`: All configured keys have temporarily exhausted their daily quota.
  * `🆓 Free Mode`: Operating with free models without API keys.

### ⚙️ Categorized Custom Glossary
Click **⚙️ Glossary** in the top navigation to configure persistent domain terms:
* Out-of-the-box expanded library of **3,366+ specialized terms**:
  * 💻 **Technical (`technical`):** 1,130 terms (AI, LLMs, Machine Learning, Cloud, DevOps, Networks, Cybersecurity, Databases, Robotics, Hardware, Hard Sci-Fi).
  * 📚 **Literary (`literary`):** 1,032 terms (Poetics, Rhetoric, Narrative Structure, Character Tropes, Classical Drama, Genres, Versification).
  * ⚙️ **General (`general`):** 1,204 terms (Publishing, Typography, Legal, Economics, Public Policy, Environment, Medicine, Daily Idioms).
* Add and edit custom translation pairs across all 3 categories with live search and filtering.
* **Domain Isolation:** When translating literature, poetry, or comics, technical IT/DevOps terms (e.g. `pod`, `sandbox`) are automatically ignored to prevent awkward translations in fiction.
* **Terms inside a Greek sentence:** in a finished Greek translation, an English term that was left inside a Greek sentence stays and gets its Greek translation once, in parentheses (for example `το kernel (πυρήνας)`), because a Greek noun cannot replace it without the right case and gender. A term alone on its line is replaced.

### In-Place Layout & Style Preservation
* **Word Documents (`.docx`):** Preserves font sizes, font families (Times New Roman, Arial, Calibri), **Bold**, *Italics*, underline, tables, and nested drawings. Bullet points from Wingdings/Symbol are converted to clean standard Unicode bullets (`•`).
* **Front Matter Preservation:** Line-level header/footer cleaning preserves prologues, epigraphs, and tables of contents on the opening pages.
* **EPUB (`.epub`):** Retains CSS stylesheets, chapter hierarchies (`<h1>`–`<h6>`), and embedded images.
* **PDF (`.pdf`):** Formats headings, validates all characters against font glyph sets to eliminate missing tofu boxes (`□□`), and wraps long URLs cleanly within page margins.
* **With AI Polish too:** DOCX→DOCX and EPUB→EPUB keep their original formatting, so headings, bold/italic, tables, images and the EPUB layout stay exactly as they were. Gemini translates the text inside the document piece by piece, with surrounding context.

---

### 🔍 Automatic Final Quality Check (Final Output Refinement)

Every translation and every audiobook goes through one more automatic step at the very end: a **final quality check**. You don't need to do anything. You'll briefly see *"🔍 Τελικός έλεγχος ποιότητας…"* in the progress bar.

**What it does for translations**
* Fixes only mistakes that are certainly wrong: doubled words (`και και` → `και`, `the the` → `the`), accents on one-syllable words (`γιά` → `για`), the final-ν rule (`δε μπορώ` → `δεν μπορώ`), words split by a hyphen at a line break, spaces before punctuation, excessive blank lines, and a few clear literal translations (`για σίγουρα` → `σίγουρα`).
* Phrases that *might* be fine are **reported, not changed**, so the meaning of your book never changes. Examples are `κάνει νόημα` (which can also mean "signals") and deliberate repetition such as `Όχι όχι` or `σιγά σιγά`.
* It also warns you about possible problems: an empty translated page, a paragraph that seems untranslated, missing page numbers, or unbalanced quotes.
* Poetry layouts keep their spacing, and French punctuation spacing is respected.
* If your document kept its original formatting (Word/EPUB → same format, or comics), the check only **reports**. The file is never rebuilt, so your styles, images and artwork stay exactly as they were.

**What it does for audiobooks**
* Checks that the audio file is complete, playable and in the right order.
* If a part of the narration failed (for example after a short network outage), it automatically **tries that part again** and rebuilds the audiobook. Your original audio is replaced only if the rebuilt one is verified to be better.

**When finished**, a short notification tells you what was corrected. If something serious was found (e.g. audio parts still missing), you'll see a ⚠️ warning so you can check the result.

**Turning it on/off (Advanced Mode):** the check is always on by default. Its checkbox **🔍 Τελικός Αυτόματος Έλεγχος Ποιότητας** is shown only in **⚙️ Advanced Mode** (Translation or Audiobook panel; one setting for both). When it is off, the application works exactly as before. The check runs on your computer and **never uses your Gemini quota**.

---

## 4. Audiobook Generation

Convert any document into high-fidelity MP3 and M4B audiobooks with embedded chapter metadata and cover art.

The audiobook reads the document's text. A scanned PDF (pictures of pages only) has none, so run it through an OCR program first (see [Scanned PDFs](#-scanned-pdfs-page-images-only)).

### Available Neural Voices & Live Auditions
* **Greek Neural Voices (🇬🇷):**
  * 👨 **Nestoras (Male)** (`el-GR-NestorasNeural`) — exceptional pronunciation and acronym handling. It is the only Greek voice: Microsoft's Athina voice was removed because it returned cut-off audio for most parts in tests. Audiobooks saved with Athina are read by Nestoras.
* **English Neural Voices (🇬🇧 / 🇺🇸):**
  * 👩 Aria, Jenny, Emma
  * 👨 Guy, Brian, Ryan
* 🔊 **Live Voice Audition:** Click **«🔊 Preview»** next to any voice card to hear a 2–3 second sample before generating your audiobook. **🔊 Δοκιμή Φωνής** reads your own phrase (or the start of the book) with the selected voice.
* ⏹️ **Stopping a sample:** while a sample plays, a **⏹️ Διακοπή** button appears next to *Δοκιμή Φωνής*. It stops the sound at once, without waiting for the passage to finish, and disappears when the sample ends.

### 🎭 Multi-Voice Dramatization
Create a theatrical audio experience:
1. Enable **🎭 Multi-Voice Dramatization**.
2. Select your primary voice for **Narrator** (e.g. Guy) and secondary voice for **Dialogue** (e.g. Jenny). Greek has one voice, so this option appears for English books only.
3. The system automatically detects quotes (`«...»`) and dialogue dashes (`—`), routing character speech to the dialogue voice and descriptive prose to the narrator voice.

### 📦 M4B Export & Embedded Cover Art
* Every audiobook exports with complete metadata tags (Title, Artist, Album, Genre="Audiobook").
* Active cover art is embedded directly into the audio file container (**Embedded APIC Cover Art**), rendering natively in Apple Books, Android players, and car dashboards.
* **Streamed Audio Assembly:** Audio chunks are assembled in 64KB streams, ensuring 10+ hour audiobooks render without high RAM usage.
* **Chapters:** chapter headings in the book become chapters in the M4B, so your player can skip between them.
* **FFmpeg:** M4B needs it; it is installed with BookApp's requirements (and is in the Docker image). If it is missing, the app tells you and the MP3 stays available.

### Step-by-Step Audiobook Guide
1. Navigate to the **🎧 Generate Audiobook** tab.
2. Upload your file (or use previously translated text). The upload card displays the **estimated listening time** (e.g. `⏱️ ~1h 45m listening` based on ~2 minutes per page).
3. Select the **Audio Language** (Greek or English).
4. Choose your preferred voice (e.g. **Nestoras ♂**).
5. Click **🎧 Generate Audiobook**.
6. When complete, click **⬇️ Download Audiobook (MP3)** or **📦 Download M4B (Audiobook)**.

### Direct Conversion: Send to Audiobook
Immediately after translating an English document to Greek, click:  
**`🎧 Convert to Greek Audiobook`**  
The application smoothly navigates to the Audiobook tab with Greek language and Nestoras voice preselected and *"Use previously translated text"* enabled.

### 🎚️ Narration Styles, Speed & Pitch Tuning
* 📖 **Literature Flow (-12% speed):** Recommended for fiction and novels. Natural breathing cadence.
* 🪶 **Poetry & Recitation (-20% speed):** Tailored for poetry and dramatic recitation, honoring meter and verse pauses.
* 🐢 **Calm & Expressive (-18% speed):** Relaxed cadence for bedtime stories and language learning.
* 🎙️ **Conversational (+0% speed / 1.0x):** Natural human speaking rate for essays and biographies.
* ⚡ **Brisk Non-Fiction (+15% speed):** Faster playback for podcasts and technical manuals.
* **Speed Slider (-30% to +30%):** Fine-tune playback rate to exact percentages.
* **Pitch Slider (-4Hz to +4Hz):** Adjust vocal tone (`-2Hz` or `-3Hz` for a deep dramatic baritone; `-1Hz` for warm book narration).

### ✨ AI Polish for Spoken Audio
Enable **✨ AI Polish for Spoken Audio (Gemini)** to optimize scripts for speech synthesis:
* Phonetically spells foreign names and acronyms in Greek characters (`Keeton` ➔ `Κίτον`, `DNA` ➔ `Ντι-Εν-Έι`).
* Fully writes out numbers and years (`2006` ➔ `δύο χιλιάδες έξι`, `50%` ➔ `πενήντα τοις εκατό`).
* Cleans footnote markers (`[1]`), page headers, and URLs.

**What changed for listeners:**
* The script is no longer rephrased; only what is needed for correct speech is changed.
* Numbers are read in the right grammatical case ("ήταν τριάντα οκτώ βαθμοί", "στους σαράντα βαθμούς").
* Roman numerals, times and ordinals are read correctly ("Κεφάλαιο τέταρτο", "δέκα και μισή", "Λουδοβίκος ο δέκατος τέταρτος").
* Words written in CAPITALS for emphasis are no longer spelled out letter by letter.
* In long books, every foreign name is pronounced the same way from start to finish.

### 🎧 Built-In Pro Audiobook Player
* **In-Browser Playback:** Listen immediately without third-party media players.
* **Skip Buttons (⏪ 15s / ⏩ 15s):** Quick 15-second jumps.
* **Playback Speed Presets:** Select between `0.8x`, `1.0x`, `1.2x`, and `1.5x`.
* **Chapter Navigator:** Jump directly between book chapters.

### Understanding Progress: "Audio Parts" vs "Pages"
The progress indicator displays:  
`Generating audio part 2 of 5...`
* To prevent connection timeouts with speech synthesis servers, text is synthesized in ~1,200 character paragraphs.
* When all parts reach 100%, they are concatenated into a **single seamless MP3/M4B file**.

---

## 5. Book Insights: Summaries, Synopses & Audio

Open the **💡 Book Insights** tab. Upload a PDF, DOCX or EPUB (or press **📎 Use the document you already uploaded** to reuse the book from the Translate or Audiobook tab). The app shows how much readable text it found (words, estimated pages, language).

> A **Google Gemini API key** is required (the same free key used for AI Polish). Without one, the buttons stay disabled and a message explains how to add a key.

### ⚡ Basic Mode
* **📝 1-Click Summary** — a short summary (about 150–300 words) of the main ideas or plot.
* **📚 1-Click Synopsis** — a structured synopsis (about 800–1,200 words): subject, structure, themes, key developments, ending/conclusions.
* The text is written automatically in the **language of the book**.

### ⚙️ Advanced Mode
| Summary types | Synopsis types |
|---|---|
| One sentence (20–40 words) · Short (150–300) · Extended (500–1,000) | Standard (800–1,200) · Extended (1,500–2,500) |

For each, choose the **output language** (Greek or English) and the **output format**: on screen, PDF, DOC/DOCX or TXT. The result is always shown on screen as well, and you can download it later in any format with the ⬇️ buttons.

**Word counts are guidelines.** For short documents the length is reduced automatically, so the text never contains padding or information that is not in the book.

### 📏 Minimum length
* **Synopsis:** needs at least **~1.5 pages of real text** (about 375 words). The app counts only meaningful text and ignores page numbers, repeated headers and links, so page counts of PDFs do not matter. For shorter documents the synopsis buttons are disabled, with an explanation.
* **Summary:** needs at least about 80 words.
* Scanned books (images only) contain no extractable text and cannot be summarised. Run them through an OCR program first, then upload the new PDF.

### ✅ Quality check before you see anything
Every text is checked automatically before it is displayed:
* correct language;
* the right length (one sentence for the one-sentence summary);
* headings for synopses;
* no names or numbers that do not appear in the book;
* real condensation;
* a synopsis that genuinely differs from the summary.

Greek texts also get a proofreading pass. If a check fails, the text is regenerated once. If it still fails, you see an error instead of an unreliable text. Minor notes (e.g. length slightly outside the guideline) are shown above the result.

### 🎧 Listening
Press **🎧 Create audio** under any result. The final text is narrated exactly as written, with a Greek or English neural voice matching the text's language. Play it in the page or **⬇️ Download MP3**.

### ⚠️ Messages you may see
| Message | What to do |
|---|---|
| Document too short / not enough text | Use a longer document; scanned images have no text. |
| Language not detected | Choose the output language in Advanced Mode. |
| Gemini key required / key rejected | Add or correct your key with **🔑 Gemini API Key**. |
| Daily Gemini limit reached / too many requests | Wait, or add another key to the pool. |
| Connection problem | Check your internet connection and that the app is running. |
| Quality check failed | Press the button again; the AI will write a new version. |
| Audio or file export failed | Try again or choose another format. |

Generating the same text twice reuses the saved result (no extra API usage). Pressing a button again while a generation is running does not start a duplicate.

---

## 6. Session History & Task Management

The **Session History** panel at the bottom of the page tracks all jobs (with user accounts: your own jobs; administrators can choose whose jobs to see):
* **Reload & Full Settings Restoration:** Clicking any history entry restores the document, output format, layout style, language direction, and page metrics.
* **Interrupted Job Resumption:** If an AI translation was paused, clicking **Start Translation** continues from the saved checkpoint (`.direct_ai_checkpoint.json`).
* **Deleting Individual Jobs:** Click **✕** on any history item to remove it from database, queue, and disk.
* **Clearing All History:** Click **🗑️ Clear All** (with confirmation) to delete all jobs, books and results while preserving the translation cache. This can't be undone.
* **Your work is kept until you delete it:** restarting BookApp never removes jobs, books or results, whatever their age or file name. As history only shrinks when you delete, remove what you no longer need to free disk space.

---

## 7. Frequently Asked Questions & Troubleshooting

#### ❓ Can I download a translated book in another format without re-translating?
* **Yes!** Simply click **PDF**, **DOCX**, **EPUB**, or **TXT** and click **⬇️ Download**. The conversion happens in less than one second without making new translation calls.

#### ❓ Can I polish text directly in the Editor without uploading a file?
* **Yes!** Open the **Direct Editor**, paste your text, and click **✨ AI Polish**. The system processes your text and lets you download it as TXT, DOCX, PDF, or EPUB.

#### ❓ How are scanned PDFs translated? Do I need OCR first?
* **No OCR is needed to translate.** The upload analyzer automatically detects scanned PDFs, comics and books alike (`🎨 Graphic Novel / Comic Auto-Detected`), and locks the interface to comic-safe options. The **Gemini Vision AI** reads the text, 3 pages at a time, inpainting backgrounds and drawing translated text in comic typography while keeping 100% of the artwork intact. A Gemini key is required.
* A scanned novel also comes out as page images with the translation drawn on them. For plain text, an audiobook or Book Insights, run the PDF through an OCR program first (see [Scanned PDFs](#-scanned-pdfs-page-images-only)).

#### ❓ A comic job says "page(s) left untranslated" or "No text found on page(s)". What do I do?
* **Left untranslated (with a reason in brackets):** Gemini Vision could not read those pages, for example `HTTP 429 (rate limit)`, `HTTP 503 (overloaded)` or a timeout. Translate the file again: the pages already done come from the cache, so only the listed pages are sent again.
* **No text found:** usually the cover or full-page artwork. If one of those pages has balloons, translate again: a page found empty is always asked again, never reused.
* Pages that an older version saved in Latin letters (Greeklish) are translated again automatically.

#### ❓ How does Single-Pass Direct AI Translation speed up processing?
* Enabling **✨ AI Polish** with a Gemini API key translates and polishes in **one single parallel pass** (5 concurrent workers). It is **4x–8x faster**, avoids Google Translate 429 limits, and preserves glossary terms, entity consistency dossiers, and cover art.

#### ❓ How do I use the Smart Batch Queue?
* Drop **up to 20 files** into the Upload Card. Configure your Translation Settings below and click **▶️ Start Batch Translation**. The queue runs serially with parallel internal workers, per-item retry, pause/resume, individual download buttons, and a master **📦 Download All (ZIP)** button once all jobs finish.
* If you remove files before starting until only one is left, that file goes back to the normal Upload Card, with its style recommendation (**Εφαρμογή Προτεινόμενου**), cover check and single-file buttons.

#### ❓ What do the "🔄 Refresh" and "🔑 Gemini API Key" buttons do?
* **🔄 Refresh** (icon at the right end of the tab bar): Instantly refreshes page state, session history, and server settings.
* **🔑 Gemini API Key:** Opens the Multi-Key Pool modal with individual slot status and auto-save capabilities. With user accounts only administrators see it.

#### ❓ Can I translate older Word (.doc) files?
* Please open the file in Microsoft Word and save it as `.docx` before uploading.

#### ❓ How much of my Gemini quota did a job use?
When a translation, audiobook or Book Insights result finishes, a notification shows how many Gemini requests and tokens it used. The settings window (🔑 Gemini API Key) shows today's total.

#### ❓ Where are my API keys stored?
Only on the computer that runs BookApp. The page shows them masked (for example `AIzaSy...4f2D`), and your browser no longer keeps a copy. To replace a key, type the new one into its slot and save.

#### ❓ Can I use BookApp from my phone or another computer safely?
Yes. On a server shared by several people, your administrator switches on **user accounts**: you sign in with your username and password (see [Signing In & Your Account](#-signing-in--your-account)). For a single person at home, your administrator can instead turn on **device pairing**. Then, in 🔑 Gemini API Key → 📱 Συσκευές, create a link and open it once on the new device; after that it just works, with no password. Devices you haven't paired are refused, and you can revoke a device at any time.

#### ❓ How do I put BookApp on my iPhone or iPad home screen?
Open BookApp in Safari, tap **Share** (the square with the arrow) and then **Add to Home Screen**. The shortcut shows BookApp's icon (a stack of books) and the name **BookApp**, and opens the app in Safari. The same icon shows in the tabs of Chrome, Firefox, Safari and Edge, and on Android's home screen. A shortcut or bookmark made before the icon existed keeps its old letter: delete it and add it again. A browser may also need a reload (or a restart) to update the tab icon.

#### ❓ Do I need to pay for an API key?
* **No.** Microsoft Edge neural voices are free, and so is a Google Gemini API key from Google AI Studio. Translation without any key uses Google's free web service and MyMemory, but Google currently refuses most automated requests, so a long book without a key may stop with a message. A free Gemini key makes translation reliable; it is also needed for AI Polish and scanned comics.

#### ❓ How long does translation or audio generation take?
* Small documents (1–5 pages): **2 to 10 seconds**.
* Medium documents (20–50 pages): **20 seconds to 1.5 minutes**.
* Full books (200–500 pages): **3 to 12 minutes** (and `0 ms` for cached chunks).
* Scanned Graphic Novels (~60 pages): **~1.5 to 3 minutes**.

#### ❓ What happens if Google Translate hits a temporary rate limit (HTTP 429)?
* BookApp waits as long as Google asks, then uses MyMemory within its daily limit and, if you saved a Gemini key, lets Gemini translate (this uses your Gemini allowance). The finished job tells you which engine translated. Without a key, a book that cannot be translated stops with a clear message; it is never handed out half translated.

#### ❓ The job says some preformatted blocks were kept untranslated. Why?
* EPUB books sometimes hold program code or tables in preformatted blocks. Translated code would be broken code, so blocks that look like code stay as they are, and the job tells you how many. Poems, verse and letters that the book itself marks as such are always translated.

#### ❓ Text I copy from an exported PDF looks odd (spaces, hyphens, Greek accents).
* PDFs exported by BookApp from 23 Nov 2026 copy and search as the book's own characters. Export older translations again (the download buttons do it in seconds). Quotations in Arabic, Hebrew or Indic scripts still copy out as glyph forms, although they look right on the page.

#### ❓ The audiobook stopped with a voice outage message.
* A short network drop is waited out in the voice you chose. If Microsoft's voice service cannot be reached for about a minute, the audiobook stops and offers **Resume**: the parts already narrated are kept and reused.

#### ❓ What happens if I don't enter a Gemini API Key?
* The application automatically enables **Free Mode** (indicated by the `🆓 Free Mode` badge). Translations use Google Translate, editorial typography rules are applied, and audiobooks use Edge-TTS neural voices completely free.

#### ❓ What happens if the Gemini daily quota is reached?
* The application distinguishes momentary burst limits (15 RPM) from daily exhaustion. If daily quota is reached:
  * With **Gemini Multi-Key Pool**, it automatically rotates to backup keys (Slots 2–8).
  * **The Gemini key window says what is waiting:** a box at the bottom shows whether the daily limit is used up on every key and when it renews, which models reached their limit on how many keys (for example `gemini-3.5-flash: daily limit on 2 of 3 keys — again at 10:00`), and which of your jobs wait for the renewal. Each slot badge also shows `🟡 Active · 2 models at their limit`. The times are in your own clock, and the box updates every few seconds while the window is open.
  * If all keys in the pool are exhausted:
    - By default (`quota_behavior="wait"`), translation and audiobook generation **pause cleanly at disk checkpoint** (`.direct_ai_checkpoint.json` / `.comic_vision_checkpoint.json`) and **wait for quota reset**.
    - The system displays a live countdown timer in the UI.
    - **Automatic Resumption:** The background quota monitor automatically resumes paused jobs and queued batch items the second the cooldown expires or as soon as new working keys are saved in Settings!
    - It **NEVER automatically falls back** to plain Google Translate or unpolished text unless you deliberately choose the `fallback` option.
    - Graphic novels and comics also strictly respect this mode, pausing page-by-page rather than outputting unpolished or plain text.

#### ❓ Why does the reader voice stumble on foreign names?
* Use **AI Polish for Spoken Audio (style="audiobook")**, which phonetically transcribes foreign names into Greek characters (`Keeton` ➔ `Κίτον`, `DNA` ➔ `Ντι-Εν-Έι`) and spells out all numbers in full Greek words.
