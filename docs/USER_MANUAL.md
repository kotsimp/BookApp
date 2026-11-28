# 📖 User Manual
### DocTranslate & AudioBook Generator

Welcome to the **DocTranslate & AudioBook Generator** user guide. This application allows you to translate documents between English and Greek while preserving original formatting, as well as create professional-grade AI audiobooks in MP3 and M4B formats using natural Microsoft Edge neural voices.

---

## 📑 Table of Contents
1. [Accessing the Application](#1-accessing-the-application)
   - [Help: Guide & FAQ](#-help-guide--faq)
   - [Light by Day, Dark at Night](#--light-by-day-dark-at-night)
   - [Devices: E-reader Catalogue](#-devices-e-reader-catalogue)
   - [Reading-Position Sync (KOReader, Readest)](#-reading-position-sync-koreader-readest)
   - [Signing In & Your Account](#-signing-in--your-account)
   - [Managing Users (Administrators)](#-managing-users-administrators)
2. [Operating Modes: Basic Mode vs Advanced Mode](#2-operating-modes-basic-mode-vs-advanced-mode)
3. [Document Translation](#3-document-translation)
   - [Supported File Formats](#supported-file-formats)
   - [Graphic Novels, Comics & Manga (RTL)](#-graphic-novels-comics--manga-rtl)
   - [Scanned PDFs (Page Images Only)](#-scanned-pdfs-page-images-only)
   - [Gemini Request Estimate](#-gemini-request-estimate)
   - [Sample First: Translate a Few Pages](#-sample-first-translate-a-few-pages)
   - [Auto-Genre & Document Style Detection](#-auto-genre--document-style-detection)
   - [Automatic Greek Editorial Typography](#-automatic-greek-editorial-typography)
   - [Step-by-Step Translation Guide](#step-by-step-translation-guide)
   - [Output Format Selection](#output-format-selection)
   - [Document Layout Styles](#document-layout-styles)
   - [Book Cover Image Management](#-book-cover-image-management)
   - [Gemini Quota Handling Choice & Free Mode](#-gemini-quota-handling-choice--free-mode)
   - [Instant On-Demand Export Without Retranslating](#-instant-on-demand-export-without-retranslating)
   - [Bilingual Edition](#-bilingual-edition)
   - [Distraction-Free "Read Now" Reader View](#-distraction-free-read-now-reader-view)
   - [Smart Resume Banner](#-smart-resume-banner)
   - [Live ETA, Speed & Hybrid Engine Badge](#-live-eta-speed--hybrid-engine-badge)
   - [In-Browser Review & Edit](#-in-browser-review--edit)
   - [Gemini AI Polish & Proofreading](#-gemini-ai-polish--proofreading)
   - [Gemini Multi-Key API Pool & Auto-Failover](#-gemini-multi-key-api-pool--auto-failover)
   - [Categorized Custom Glossary](#-categorized-custom-glossary)
   - [The Glossary Learns From Your Translations](#-the-glossary-learns-from-your-translations)
   - [Book Series: the Same Names in Every Book](#-book-series-the-same-names-in-every-book)
   - [A "Characters" Page in the EPUB](#-a-characters-page-in-the-epub)
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
   - [Reading Along](#-reading-along)
   - [Understanding Progress: "Audio Parts" vs "Pages"](#understanding-progress-audio-parts-vs-pages)
5. [Book Insights: Summaries, Synopses & Audio](#5-book-insights-summaries-synopses--audio)
   - [More About the Book](#-more-about-the-book)
   - [Ask the Book](#-ask-the-book)
6. [Session History & Task Management](#6-session-history--task-management)
   - [Backup & Restore](#-backup--restore)
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
The **❓ Help** button in the tab bar opens a short guide (translation, audiobooks, Book Insights, Gemini keys) and answers to frequently asked questions: whether you need a Gemini key, why a translation can take hours, what happens when the daily Gemini limit runs out, whether several keys from one Google account help, what survives closing the page or a server restart, how accurate the time left is, what Maximum quality does, trying a few pages first, asking questions about a book, reading on an e-reader, translating a scanned PDF (no OCR needed, but a Gemini key is), names translated inconsistently, where your files go, a forgotten password, the iPhone home screen and an old look after an update. It shows in the interface language (ΕΛ | EN). Close it with ✕, Esc or a click outside.

### ☀️ / 🌙 Light by Day, Dark at Night
The interface is light from sunrise to sunset and dark at night, by itself (the times follow the date; on Greek time they are those of Athens). The **Theme** button at the top right still switches it whenever you like: your choice holds until the next sunrise or sunset, and then the automatic theme takes over again. Hover over the button to see until when your choice lasts.

### 📲 Devices: E-reader Catalogue
The **📲 Συσκευές** button in the tab bar opens the link for your reading devices. With user accounts, each user has their own.

**📚 E-reader catalogue (OPDS).** Reading apps such as **KOReader**, **Moon+ Reader**, **Librera** or **Panels** (comics) list your finished translations and download them directly.
1. Press **🔗 Νέος σύνδεσμος** and copy the link (`http://<server>:8000/opds/…/`).
2. In the reading app, add it as an OPDS catalogue (KOReader: *Search → OPDS catalog → +*; Moon+ Reader: *My Shelf → Net Library → Add*).
* Books offer **EPUB**, **PDF** and **Δίγλωσσο EPUB** (the bilingual edition); comics offer **CBZ**, **EPUB** (a picture per page) and **PDF**. Files are made on demand, as the app's own downloads are; a comic's EPUB and CBZ are made in advance when the catalogue is opened, so the download starts at once. Their pages keep the scan's own sharpness (up to 2,560 pixels on the long side), about 1.2 MB a page: a comic of 150 pages is about 180 MB.
* **The reading app shows PDF or CBZ greyed out, or says the catalogue offers the book only in formats it cannot open:** that app does not open those formats (several iPhone reading apps open only EPUB; KOReader itself runs on Kindle, Kobo, PocketBook, Android and computers, not on the iPhone). Choose **EPUB**, also for comics (a picture per page). On an iPhone you can also download the book in BookApp and choose **Books** in the Share sheet (Apple Books opens PDF and EPUB), or use a reading app that adds OPDS catalogues and opens PDF and CBZ (comic readers such as Panels or Chunky, or KyBook 3).
* **Readest shows only EPUB:** it offers EPUB on its main button and the other formats (PDF, CBZ, the bilingual EPUB) under the small **▾** next to it (*More formats*). An older Readest without the ▾ shows EPUB only: update it from the App Store.
* **A download stays on "Downloading…":** some reading apps check a link before downloading it; the catalogue now answers that check (it used to refuse it, and such an app waited for ever). If an iPhone app still waits while Readest downloads the same book, the app may refuse plain `http://` downloads: use the server's `https://` address in the catalogue link if you have one, or Readest. Also: a comic's EPUB used to be made far larger than its scans (4–7.5 MB a page, 600 MB or more for a long comic), and while a comic's files were being made (when the catalogue opens) the server sent everything else, downloads too, at a crawl. Comic files are now made at the scan's own size, about a quarter of that, by a separate process that does not slow the server: open the catalogue, wait a minute while they are made, then download. A book (not a comic) downloads in seconds; if one stays on "Downloading…", check that the e-reader reaches the server (the same address works in its browser).
* The link is secret: whoever has it sees your books, so don't share it. It is shown only when made; a new link stops the old one, and **🗑️ Κατάργηση** stops it for good.
* If you opened BookApp as `localhost`, put the server's network address (e.g. `192.168.1.10`) in its place on the e-reader. The e-reader must reach the server (same network, or through your HTTPS address).

### 🔄 Reading-Position Sync (KOReader, Readest)
BookApp is also a sync server for **KOReader** and **Readest**: they send it where you stopped in each book, and you carry on from the same place on another device (a Kobo at home, the phone on the bus). BookApp then knows how far you have read: Session History shows **📍 42%** on the book, and Book Insights writes **🧭 Η ιστορία ως τώρα** up to there with one click.
1. In **📲 Συσκευές → 🔄 Συγχρονισμός θέσης ανάγνωσης**, press **🔑 Νέος κωδικός συγχρονισμού**. You see three things to copy: the **server** (`http://<server>:8000/kosync`), your **user name** (your BookApp one; with user accounts off, any name) and the **sync password**. The password shows only now; a new one stops the old one, and **🗑️ Κατάργηση** stops syncing.
2. **KOReader:** open a book, then the tools menu (🔧) → **Progress sync** → **Custom sync server**, enter the server address, then **Login** with the user name and the password. Choose when it syncs (for example on every page turn, or when the book is closed) in the same menu.
3. **Readest:** in its settings, **KOReader Sync**: enter the same server, user name and password.

**Which address to enter.** The sync server is part of BookApp, so its address is **the address you open BookApp with in the browser, with `/kosync` at the end**, for example `http://192.168.1.10:8000/kosync`.
* **The easiest way:** open BookApp in the browser with the server's address (not `localhost`) and press **🔑 Νέος κωδικός συγχρονισμού** in **📲 Συσκευές**: the **Διακομιστής** box shows the full address to enter, next to the user name and the password. Opened as `localhost`, the window says so: put the server's network address in its place.
* **The server's IP address:** on the Ubuntu server, the command `hostname -I` (the first address, e.g. `192.168.1.x`); on a Synology, **Control Panel → Network → Network Interface**.
* **The port:** 8000, or the `BOOKAPP_PORT` you set in the `.env` file next to `docker-compose.yml`. `docker ps` shows it too: `0.0.0.0:2000->8000` means port 2000.
* **With HTTPS** through a reverse proxy: your own address, e.g. `https://books.example.com/kosync`.
* **Before trying:** the server must have the update that brought the sync server (`git pull && docker compose up -d --build`); before it, `/kosync` does not exist. The e-reader must reach the server: on the same network, or through your HTTPS address.
* **Which books:** those you downloaded from BookApp, from the e-reader catalogue or with a download button, while signed in as yourself (with user accounts, the books you download count for your own sync password). KOReader recognises a book by a fingerprint of its file (or of its file name, if you chose that in KOReader); BookApp notes the fingerprint of every file it hands out. Positions in other books are synced between your devices too, but BookApp cannot show them with a book.
* **The story so far:** in Book Insights (Advanced Mode, **🔎 Περισσότερα για το βιβλίο**), a book with a synced position shows **📍 Έχετε διαβάσει 42% (σελίδα 120).** and the button **📍 Από τη θέση ανάγνωσης**, which puts that page (an EPUB: chapter) in the box; then press **🧭 Ανακεφαλαίωση**. The page is worked out from how much of the book's text lies before your position, so it can be a page or two off.
* KOReader's **Register** is not needed: the account is the one in BookApp. (Register with the same name and password simply succeeds.)
* The reading device must reach the server, as for the catalogue. Readest in a web browser needs the server's `https://` address.

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
* **1-Click Insights:** the summary, the synopsis and **💬 Ρωτήστε το βιβλίο**; the other Book Insights are in Advanced Mode.
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
A scanned PDF can be translated as it is, **without OCR**. On upload the app sees that the pages are pictures with almost no text, and the card asks **🖨️ Σκαναρισμένο PDF. Τι περιέχει;** with two choices. One is already selected by a guess: pages of print on light paper suggest a book, coloured panels or large dark areas suggest a comic, and a comic word in the file name (comic, manga…) decides for a comic. Change it if the guess is wrong.

* **📖 Βιβλίο (Book):** Gemini Vision first reads the text of every page, then the text is translated like a digital book, in any layout and format (PDF, DOCX, EPUB, TXT).
  - Each page is one request, sent first to the light Flash-Lite models: reading print is easy for them and their daily allowance is large (about 1,500 a day per key), which leaves the best model's small allowance for the translation itself. A page with real text of its own (a digital title page) is not sent.
  - The progress card shows `📖 Ανάγνωση σκαναρισμένων σελίδων (Gemini Vision): σελίδα 12 από 300…`, then the translation as usual.
  - The text read is kept with the uploaded file. Later jobs on the same file (another translation, an **audiobook**, **Book Insights**, the original in **✏️ Review & Edit**) use it without reading again. An audiobook or Book Insights of a scanned book that has not been read yet reads it first, by itself.
  - A page Gemini refuses stays empty; a page that fails for another reason (a timeout) stops the job with a message naming it, and **Start** again reads only the pages still missing. Every page read is also cached, so nothing is ever paid for twice.
* **🎨 Κόμικ (Comic):** the translation is drawn onto the page images, in the balloons, as described in the section above (PDF, CBZ, CBR or Fixed-Layout EPUB).
* Both need a Gemini key. Without one, a book stops with a message, and the estimate above the Start button says so before you start.
* In the **Smart Batch Queue**, each scanned PDF keeps the choice guessed on upload.

### 📊 Gemini Request Estimate
Above the Start button, a line says about how many Gemini requests the translation needs with the settings chosen, and what your keys allow a day. It changes as you change AI Polish, Maximum quality, the layout, the format, the Book / Comic choice or the sample pages. For example:

`📊 Εκτίμηση: ~214 αιτήματα Gemini (~120 ανάγνωση σελίδων · ~47 μετάφραση · ~47 2ο πέρασμα). Τα κλειδιά σας (3) δίνουν ~60 την ημέρα στο καλύτερο μοντέλο· το 2ο πέρασμα δουλεύει μόνο με πλήρη μοντέλα: ~2 μέρες. Δείγμα 1–10: ~13 αιτήματα.`

* **Reading the pages** (a scanned book): one request per page not read yet.
* **Translation:** the AI translation sends about 3 pages (up to ~5,500 characters) per request, plus one request for the names and terms of a long book. DOCX → DOCX and EPUB → EPUB with AI send their paragraphs in parts of about 4,000 characters. A comic sends one request per page.
* **2nd pass** (Maximum quality): about as many as the translation.
* **What your keys allow:** the best model's daily allowance per key (for example 20 requests for `gemini-3.5-flash`) times your keys. If the translation needs more, it continues the same day on a lighter model. The 2nd pass uses full models only, so the line says how many days it needs. When Google reports a different limit for a model, the estimate uses Google's number from then on.
* Without AI Polish the free engine translates and needs no Gemini requests, unless Google refuses (then Gemini translates in batches).
* It is an estimate: retries of a failed answer, and answers already cached, change the real count a little. When the job finishes, a notification gives the real number of requests.

### 🧪 Sample First: Translate a Few Pages
Under the estimate, **🧪 Δείγμα πρώτα: σελίδες [1] έως [10] · 🧪 Μετάφραση δείγματος** translates only those pages (chapters, for an EPUB), with all the settings of the card, so you can judge the style and quality before spending hours and quota on the whole book.
* The AI translation works on whole requests of about 3 pages, so a sample may end a page or two after the last page you chose. The card then says which pages were done.
* The result card says `🧪 Αυτό είναι δείγμα (1–11)…`, with a **🌐 Μετάφραση ολόκληρου του βιβλίου** button. Download, Read Now, Review & Edit and the audiobook all work on the sample. Its files download with `_sample_p1-11` in the name.
* **Nothing is translated twice:** with AI Polish on a page-based translation (PDF, TXT, or a DOCX / EPUB to another format), the whole book reuses the sample's requests, as long as the languages and style stay the same. The free engine and comics reuse them through the cache. Two exceptions: DOCX → DOCX and EPUB → EPUB with AI translate the sample page by page but the whole book in place (to keep its formatting), and a scanned book's sample is translated before the rest of the book has been read. In both, the sample's translation requests are spent once more for the whole book.
* A scanned book's sample reads only its own pages (and two more). The rest are read when the whole book is translated; the pages already read are not read again.
* A sample stopped by the daily limit resumes as the same sample.
* Maximum quality also works on a sample, for judging the 2nd pass.

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

### 🔀 Bilingual Edition
On the result card, **🔀 Δίγλωσσο** downloads the original and the translation together, paragraph by paragraph: each passage of the original, smaller and in grey italics, followed by its translation. It suits learners and checking a translation.
* It comes in the chosen format if that is **PDF**, **DOCX** or **EPUB** (otherwise as PDF). Files are named `<book>_bilingual.<ext>`.
* Passages are matched page by page and then paragraph by paragraph. Where the translation joined two paragraphs into one (dialogue, for example), or split one, they are matched by their lengths, so a passage never drifts away from its translation.
* It is made from the current translation, so edits in Review & Edit appear in it. A sample gives a bilingual sample.
* Comics have no bilingual edition: their text is part of the pictures.

### 📖 Distraction-Free "Read Now" Reader View
Read your translated book directly inside the application:
1. Click **📖 Read Now (Reader)** on the result card.
2. A clean reading modal opens with:
   * **3 Themes:** **📄 Paper**, **📜 Sepia**, **🌙 Dark Night**.
   * **Font Size Zoom (A- / A+):** Easily adjustable text scaling.
   * **View Modes:** **📄 Single Column** (for distraction-free reading) or **↔️ Side-by-Side** (for bilingual English ↔ Greek sentence comparison).
3. Close it with **✕** (top right), Esc or a click outside. On a phone the reader fills the screen: the title and **✕** are on the first line, the controls on the line below (swipe them sideways if they do not fit).

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
* **The AI's own list of names follows the Glossary:** for a long book the AI first makes a list of its names and how to write them; wherever the Glossary (or the book's series) writes a name another way, the list is corrected before the translation starts, so the AI is never given two spellings for one name.

### 💡 The Glossary Learns From Your Translations
After each translation, the names it used (people, places, ships, invented terms) are offered for the Glossary, so your next books write them the same way. They appear at the top of the Glossary window, under **💡 Προτάσεις από τις μεταφράσεις σας**:
* **✓** puts one in the Glossary (General category), **✕** dismisses it (it is not offered again with the same spelling). **✅ Αποδοχή όλων** adds all of them except the marked ones below.
* **✏️ Your corrections come first:** when you write a name another way everywhere in **✏️ Review & Edit** (for example with Find & Replace → Replace All, `Κίτον` → `Κήτον`), the new spelling is offered, in its nominative even if you changed `του Θησέα` and `ο Θησέας`. A name changed in one place only is taken for a local fix and not offered.
* **⚠️ also an ordinary word:** a one-word name that the book also uses as a plain English word (*Will*, *Hope*, *Mark*). A Glossary rule would apply to the word too, so decide for yourself.
* **↔️ the Glossary writes it another way:** shows the Glossary's spelling. Accepting replaces it.
* Only names are offered (people, places, ships: every word capitalised but small ones like *of* or *the*), and only those the finished translation really writes, in any Greek case: not a name the AI was told but did not use, nor one the original does not have. Phrases and everyday objects in the AI's own list (*In the cold rain*, *lantern*, also when written *Lantern*: the translation writes it *φανάρι*, not as a name) are never offered. A place written with a lowercase word (*Greywater lighthouse*) is not offered either: add it yourself if you want it. A translation into English offers its pairs the Glossary's way round (*Nick* → *Νίκος*).
* Nothing goes into the Glossary unless you accept it: the Glossary serves every book (and, with user accounts, every user). With user accounts, each user sees the suggestions from their own books.
* Graphic novels offer their names too, as prose writes them (*FRODO* → *Frodo*); a name lettered only in capitals, which has lost its accents, is not offered.

### 📚 Book Series: the Same Names in Every Book
Link the books of a series, and each one is translated with the names the books before it used: as their translations wrote them, with your corrections in the editor, and the Greek names of their **👥 Πρόσωπα & όροι**. Your Glossary still comes first.
* **Under the file, in the Translation tab:** **📚 Σειρά βιβλίων** puts the book in a series (**➕ Νέα σειρά…** makes one) and **Βιβλίο #** sets its place. The line next to it says how many names come from the earlier books. Do this **before you translate** the book.
* **📚 Σειρές** (in Session History, or **⚙️ Σειρές** next to the series) lists your series: rename or delete one (its books stay), move books up and down (**↑ ↓**), take one out (**✕**) or add one (**➕ Προσθήκη βιβλίου…**), also books you uploaded together for the batch queue.
* The book nearest before wins: if you corrected a name in book 2, book 3 uses your spelling, not book 1's.
* Session History shows the series and the book's place, for example **📚 The Expanse #3**.
* **Book Insights:** for a book that is not the first, **📚 Πριν από αυτό το βιβλίο** (Advanced Mode, below **🧭 Η ιστορία ως τώρα**) shows the summary of each earlier book, to remember what happened before. An earlier book without a summary has **📄 Άνοιγμα**, which opens it in Book Insights to make one.
* Graphic novels work the same way: volume 2 writes each name as volume 1 did.

### 👥 A "Characters" Page in the EPUB
The translated EPUB can start with a page listing the book's people and key terms, for long novels with many names:
1. In Book Insights, make **👥 Πρόσωπα & όροι** in the language of the translation (Greek for a translation into Greek).
2. After the translation, under the download buttons, tick **👥 Σελίδα «Πρόσωπα» στην αρχή του EPUB**. The line next to it says how many people and terms it will list.
* It works for every translated EPUB, also a book translated in place that keeps its own layout (an older EPUB 2 book gets a page in the older format that its e-readers expect). The page comes after the cover, the title page and the table of contents, before chapter 1, and is in the table of contents as **Πρόσωπα** (*Characters*). Each name is written as the translation writes it (with your corrections), with the original name, and what the reader learns where the person first appears: nothing the story reveals later. (A list made before this feature has no first description; it shows the person's role, which may say more: make the list again for one without spoilers.)
* The bilingual EPUB has it too, and so do EPUBs from the e-reader catalogue. It is a copy: the EPUB itself is not changed, and unticking the box gives the book without the page.

### In-Place Layout & Style Preservation
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

The audiobook reads the document's text. For a scanned PDF (pictures of pages only), Gemini Vision first reads the text of its pages, unless it was read already for a translation (see [Scanned PDFs](#-scanned-pdfs-page-images-only)). This needs a Gemini key.

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

### 📖 Reading Along
Audiobooks made with this version show **📖 Κείμενο** in the player. It opens the book's text under the player: the sentence being read is highlighted and kept in view, and a click on any sentence plays from there. Untick **Ακολουθεί την αφήγηση** to scroll freely while it plays.
* Each part of the recording (about a minute) is timed exactly; within a part, a sentence's time follows its length, so the highlight can run a second or two ahead or behind in long sentences.
* Audiobooks made before this feature have no timing; make the audiobook again to read along.

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
* **💬 Ρωτήστε το βιβλίο** is in Basic Mode too (see [Ask the Book](#-ask-the-book)).
* The other kinds (characters, chapter by chapter, the story so far, blurb, quotes, study guide, timeline) each need a choice or two, so they are in Advanced Mode. A line under the two buttons says so, and its **⚙️ Προχωρημένη Λειτουργία** button switches there.

### ⚙️ Advanced Mode
| Summary types | Synopsis types |
|---|---|
| One sentence (20–40 words) · Short (150–300) · Extended (500–1,000) | Standard (800–1,200) · Extended (1,500–2,500) |

For each, choose the **output language** (Greek or English) and the **output format**: on screen, PDF, DOC/DOCX or TXT. The result is always shown on screen as well, and you can download it later in any format with the ⬇️ buttons.

**Word counts are guidelines.** For short documents the length is reduced automatically, so the text never contains padding or information that is not in the book.

### 📏 Minimum length
* **Synopsis:** needs at least **~1.5 pages of real text** (about 375 words). The app counts only meaningful text and ignores page numbers, repeated headers and links, so page counts of PDFs do not matter. For shorter documents the synopsis buttons are disabled, with an explanation.
* **Summary:** needs at least about 80 words.
* Scanned books (images only) have no text of their own. The panel says `📖 Σκαναρισμένο PDF: πρώτα διαβάζονται N σελίδες με Gemini Vision`, and the summary or synopsis reads them first (one request per page, shown in the progress), then checks the length and the language. Pages read for a translation or an audiobook are not read again. A scanned PDF uploaded as a comic is not summarised.

### ✅ Quality check before you see anything
Every text is checked automatically before it is displayed:
* correct language;
* the right length (one sentence for the one-sentence summary);
* headings for synopses;
* no names or numbers that do not appear in the book. A Greek name counts as the book's in any of its forms (Νίκος, του Νίκου, τον Νίκο), and 1.200, 1,200 and 1 200 are the same number. A long text may hold a few more names and numbers the check can't match;
* real condensation;
* a synopsis that genuinely differs from the summary.

Greek texts also get a proofreading pass. If a check fails, the text is regenerated once. If it still fails, you see an error instead of an unreliable text, with an **Αιτία:** line under it that says which check failed (for example *Το κείμενο βγήκε πολύ σύντομο: 820 λέξεις αντί για 1500–2500.*). Minor notes (e.g. length slightly outside the guideline) are shown above the result.

### 🎧 Listening
Press **🎧 Create audio** under any result. The final text is narrated exactly as written, with a Greek or English neural voice matching the text's language. Play it in the page or **⬇️ Download MP3**.

### 🔎 More About the Book
The **🔎 Περισσότερα για το βιβλίο** card (Advanced Mode) makes seven more kinds of text. Choose the **text language** first: the book's own, Greek or English. Like the summaries, each result shows on screen, downloads as PDF, DOCX or TXT, can be narrated, and is kept with the book: asking again gives the stored result at once, with no new Gemini requests. Each is checked before you see it (right language, nothing the book does not contain); a result that fails is not shown (the recap, blurb and study guide are first written once more).

| Button | What you get | How it is checked |
|---|---|---|
| **👥 Πρόσωπα & όροι** | The people (role, relations to others) and, for non-fiction or invented worlds, the key terms with a one-line definition, each with the page where it first appears. | A name or term the book does not contain is left out; the first page is found in the book itself. Only the work's own pages are read: not the title page, contents, acknowledgments, notes or licence, and not the names under epigraphs, so the author and quoted writers are not listed. A short form (“Szpindel”) joins its full name (“Isaac Szpindel”) and still goes to the Glossary; a ship, planet or place is a term, not a person. A description written in the wrong language is left out (the notes say how many), the name stays. |
| **📑 Ανά κεφάλαιο** | Two to four sentences for every chapter, under its title, with its pages. | Chapters come from the EPUB's chapters, or else from the PDF's bookmarks, the table of contents (even without page numbers) and chapter headings; a book without any is cut into equal parts. A very long part (a novel in a few long parts) comes in pieces of about 30 pages, shown as “(2/4)”, so its middle is summarised too. Acknowledgments, licences, contents and indexes are left out. A chapter the answer left out is asked again. |
| **📖 Ένα κεφάλαιο → 📖 Αναλυτικά** | One chapter you choose from the list (the same chapters, and pieces of long parts, as **📑 Ανά κεφάλαιο**), in detail: what happens, who appears, its key moments and how it ends, about 250–450 words with its pages. The button is a switch: pressed again, it hides the account (it stays lit while its chapter is shown); with another chapter or language chosen, it fetches that one. | Only that chapter is sent, so nothing after it can leak in. One request (and the Greek proofreading); a chapter asked again is shown without a request. |
| **🧭 Η ιστορία ως τώρα, έως σελίδα N** | A recap of everything up to the page (EPUB: chapter) you have reached, to pick a book up again. | Only the pages up to N are sent, so nothing later can leak in. |
| **📣 Οπισθόφυλλο** | An 80–130-word back-cover text that sets up the premise and stops before the ending or the twists. | Length and language. It also becomes the book's description in the e-reader catalogue (📲 Συσκευές). |
| **❝ Αποσπάσματα** | Up to 12 memorable passages, spread over the book, each with its page and a line on why it matters. | Every passage is searched for word for word in the book; one that is not found exactly is left out (the notes say how many), and a wrong page is corrected. Passages stay in the book's own language. |
| **🎓 Οδηγός μελέτης** | Themes, 8–10 discussion questions, an 8-question quiz and its answers. | It must have its four sections. |
| **🕰️ Χρονολόγιο** | Up to 40 main events in the order they happen in the story (dates, years or seasons where the book states them), each with its page. | Page numbers must exist in the book. If putting them in story order fails, they stay in the order the book tells them, and the notes say so. |

**Where the result appears.** The progress bar, any message and the result appear below this card, and the page scrolls down to them on its own; **✕** at the top of a result closes it.

**👥 → 📚 Glossary.** When the characters list is in Greek and the book is not, **➕ Ονόματα στο Γλωσσάρι** adds every name and term with its Greek spelling to the Glossary (General category), so a translation of the book writes them the same way everywhere.

**Requests:** a short book is one request for each of these. A long book is read in parts of about 45,000 characters (about one request per part), plus one more for the chronological order of the timeline; the blurb, the recap and the study guide use the same section notes as the summaries. With several Gemini keys the parts are read at the same time, two per key (up to six): the same requests and the same result, in much less time (Blindsight's characters: 15 parts in 36 seconds with 6 keys).

### 💬 Ask the Book
Type a question in **💬 Ρωτήστε το βιβλίο** and press Enter or **💬 Ερώτηση**.
* The answer comes only from the book's text, with the pages it rests on, for example `(σ. 42)`. When the book does not answer the question, it says so instead of guessing.
* The box has a card of its own, in both modes.
* It is written in the language of the question (in Advanced Mode, or in the text language you chose in the card above).
* A book of up to about 350,000 characters (about 200 pages) is sent whole. For a longer one, a small request to a light model first turns the question into search words in the book's own language (a Greek question about an English book shares no word with it), and the pages that hold them are sent, with the pages next to them. When none matches, pages spread over the whole book are sent. A **📑 Ανά κεφάλαιο** made earlier goes along as an overview, which helps questions about the whole story or its ending.
* Each question is **one large Gemini request**. The same question asked again is answered from the cache.
* The last 30 questions and answers are kept with the book and shown under the box.
* **🗑️** next to a question deletes it and its answer. With two answers or more, **🗑️ Διαγραφή όλων** above them deletes them all (after you confirm). A deleted question can be asked again; it is answered from the cache without a new request.

### ⚠️ Messages you may see
| Message | What to do |
|---|---|
| Document too short / not enough text | Use a longer document. A scanned PDF uploaded as a comic is not read as text. |
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
* **It opens in the tab you are on:** on the Translation tab a book opens there, also a translation you later made into an audiobook (showing its translation); on the Audiobook tab it opens there, with its audiobook if it has one, else ready to narrate. A book that was only narrated opens in the Translation tab ready to translate. On the Book Insights tab it becomes the document for the insights.
* **Interrupted Job Resumption:** If an AI translation was paused, clicking **Start Translation** continues from the saved checkpoint (`.direct_ai_checkpoint.json`).
* **Deleting Individual Jobs:** Click **✕** on any history item to remove it from database, queue, and disk.
* **Clearing All History:** Click **🗑️ Clear All** (with confirmation) to delete all jobs, books and results while preserving the translation cache. This can't be undone. A backup you made is kept (its file stays ready to download), and your series stay, without the deleted books.
* **Your work is kept until you delete it:** restarting BookApp never removes jobs, books or results, whatever their age or file name. As history only shrinks when you delete, remove what you no longer need to free disk space.
* **📚 and 📍 on a book:** its series and place in it, and how far your reading apps have got (see [Reading-Position Sync](#-reading-position-sync-koreader-readest)).

### 💾 Backup & Restore
**💾 Αντίγραφο ασφαλείας** (in Session History) puts all your books in one ZIP file: the uploaded originals, the translations and their files, Book Insights, covers, the names lists, your series, your reading positions and the Glossary. Keep it safe, or use it to move your books to another BookApp server (for example from the Ubuntu server to the Synology).
1. **Make a backup:** press **💾 Δημιουργία αντιγράφου** (tick **Μαζί και τα ηχητικά βιβλία** to include MP3 and M4B audiobooks: a much larger file). The progress shows; when it is ready, **⬇️ Λήψη αντιγράφου** downloads it. A large library takes a few minutes; the file stays ready to download for 24 hours. A book being translated at that moment is left out (the message says how many).
2. **Restore:** choose the ZIP under **📥 Επαναφορά από αντίγραφο** and press **📥 Επαναφορά**. The books are added to yours. A book that is already here stays as it is; one that another user on this server also has comes in as a copy of your own. Glossary terms are added only where the Glossary has no term for that word, so your own spellings are never replaced.
* With user accounts, a backup holds your own books (an administrator's: also the books from before accounts), and a restore adds them to the account that restores them.
* A backup never contains Gemini API keys, user accounts or server settings. It is checked before anything is restored: a file that is not a BookApp backup, holds paths outside a book's folders, or does not fit on the server's disk is refused with the reason. A backup from anywhere is treated with care: the books' names and settings in it are cleaned as an upload's are, so even a tampered file can only bring in books.

---

## 7. Frequently Asked Questions & Troubleshooting

#### ❓ Can I download a translated book in another format without re-translating?
* **Yes!** Simply click **PDF**, **DOCX**, **EPUB**, or **TXT** and click **⬇️ Download**. The conversion happens in less than one second without making new translation calls.

#### ❓ Can I polish text directly in the Editor without uploading a file?
* **Yes!** Open the **Direct Editor**, paste your text, and click **✨ AI Polish**. The system processes your text and lets you download it as TXT, DOCX, PDF, or EPUB.

#### ❓ How are scanned PDFs translated? Do I need OCR first?
* **No OCR is needed.** The upload analyzer detects scanned PDFs and asks whether the file is a **📖 Book** or a **🎨 Comic**, with a guess already selected.
* **Book:** Gemini Vision reads the text of every page first, then it is translated like a digital book in any format. The text read also serves audiobooks and Book Insights.
* **Comic:** the interface locks to comic-safe options. The **Gemini Vision AI** reads the speech balloons, 3 pages at a time, inpainting backgrounds and drawing translated text in comic typography while keeping 100% of the artwork intact.
* Both need a Gemini key. See [Scanned PDFs](#-scanned-pdfs-page-images-only).

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

#### ❓ A downloaded file opened over the app on my iPhone and I could not go back.
On an iPhone or iPad a file opened in the page covers BookApp; in the Home Screen app (since iOS 26 every Home Screen shortcut opens as one) there is then no way back. Now, on every iPhone and iPad, in Safari or the Home Screen app, each download (a translation, an audiobook, the bilingual edition, a Book Insights PDF, DOCX, TXT or MP3, the History's links) opens the iPhone's **Share** sheet: choose **Save to Files**, **Books**, **Mail** and so on, and BookApp stays where it was. If the file took a while to prepare, a bar **✅ The file is ready** appears at the bottom: tap **📤 Save or share**. On computers and Android, files download as before.

#### ❓ Do I need to pay for an API key?
* **No.** Microsoft Edge neural voices are free, and so is a Google Gemini API key from Google AI Studio. Translation without any key uses Google's free web service and MyMemory, but Google currently refuses most automated requests, so a long book without a key may stop with a message. A free Gemini key makes translation reliable; it is also needed for AI Polish and for scanned PDFs (books and comics).

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
