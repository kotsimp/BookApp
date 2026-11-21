# 📖 User Manual
### DocTranslate & AudioBook Generator

Welcome to the **DocTranslate & AudioBook Generator** user guide. This application allows you to translate documents between English and Greek while preserving original formatting, as well as create professional-grade AI audiobooks in MP3 and M4B formats using natural Microsoft Edge neural voices.

---

## 📑 Table of Contents
1. [Accessing the Application](#1-accessing-the-application)
2. [Operating Modes: Basic Mode vs Advanced Mode](#2-operating-modes-basic-mode-vs-advanced-mode)
3. [Document Translation](#3-document-translation)
   - [Supported File Formats](#supported-file-formats)
   - [Graphic Novels, Comics & Manga (RTL)](#-graphic-novels-comics--manga-rtl)
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
5. [Session History & Task Management](#5-session-history--task-management)
6. [Frequently Asked Questions & Troubleshooting](#6-frequently-asked-questions--troubleshooting)

---

## 1. Accessing the Application

Open your modern web browser (Google Chrome, Microsoft Edge, Mozilla Firefox, Brave, or Safari) and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)** *(the web interface also adapts automatically to `http://127.0.0.1:8000` or your local network LAN IP)*

You will see the main user interface with two primary tabs at the top:
* 🌐 **Translate Document**
* 🎧 **Generate Audiobook**

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
3. **Smart Fit-to-Box (Zero Blank Balloons) & Natural Page Sorting:** Because Greek text takes ~20% more space, the engine deterministically computes the ideal font size (down to `3.0pt` with whole-word wrapping, fallback to `Arial Narrow`, and subtle bounding box expansion where necessary) — ensuring **no balloon is ever left blank**. For `.cbz`/`.zip` archives, pages are sorted using **natural numeric order** (`page_1`, `page_2`, ..., `page_10`) with Zip Slip security checks. The dialogue sanitizer standardizes comic uppercase Greek (`Ϊ`/`Ϋ`), elision apostrophes (`Σ'`, `ΓΙ'`), and Greek question marks (`;`).
4. **Japanese Manga Support (Right-to-Left — RTL):**
   - Select **Manga (Right-to-Left ⬅️)** under Reading Direction.
   - Speech balloon detection and translation ordering are sorted top-to-bottom and **right-to-left**.
   - Fixed-Layout EPUB exports embed the standard `page-progression-direction="rtl"` directive so e-readers flip pages from right to left naturally.
5. **Permitted Comic Export Formats:**
   - **PDF**, **CBZ** (Comic Book Zip), **CBR** (Comic Book Archive), and **EPUB** (Fixed-Layout).
   - Plain text formats (TXT and DOCX) are automatically disabled for comics to protect users from artwork loss.

### 💡 Auto-Genre & Document Style Detection
Upon uploading a document, the system automatically analyzes the opening pages:
* Detects whether the file is **Literature**, **Poetry**, **Technical Documentation**, **Formal / Administrative**, or a **Graphic Novel**.
* Displays an informative badge (e.g. `💡 Detected genre: Literature (85% confidence)`).
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
   - For **1 file**: Displays the filename, size, estimated pages (e.g. `~340 pages · PDF · Ready`) and an **➕ Add More** button next to `✕` to seamlessly add more files.
   - For **2+ files**: The **Smart Batch Queue** view opens immediately inside the upload card (allowing you to add more files, enable **⚡ Auto-Start**, or remove individual items).
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
     - 🎨 **CBZ / CBR:** Digital comic archive with speech balloons translated.
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

5. **🎨 Book Cover Image Management:**
   - **Auto-Detection & Extraction:** When uploading a PDF, EPUB, or DOCX, the first page is analyzed. If full-page artwork is detected, it is extracted immediately, a thumbnail is displayed, and the badge turns green:  
     `✔ Cover active (Automatically embedded on page 1 of PDF, EPUB & DOCX)`.
   - **Manual Cover Upload:** Click **📷 Upload Cover** to select any custom image file (`.jpg`, `.png`, `.webp`).
   - **Cover Removal:** Click **✕ Remove** to export the document cleanly without cover artwork.
   - **Final Placement:** Active covers are embedded as:
     - Full-bleed unpaginated page 1 in **PDF**.
     - Official e-book cover metadata in **EPUB**.
     - Document title page in **DOCX**.

6. **⚡ Gemini Quota Handling Choice & Automatic Resumption:**
   - Choose how the system behaves if the Google Gemini API daily limit is exceeded:
     * **⏳ Wait for Reset & Auto-Resume (Default with API Key):** Pauses safely at disk checkpoint (`.direct_ai_checkpoint.json` or `.comic_vision_checkpoint.json`). Displays a live countdown timer and **automatically resumes translation, audiobook generation, and queued batch items the moment the cooldown timer reaches zero or when a new key is added**, without requiring manual user intervention. **Preserves 100% Gemini literary quality and artwork**. Never downgrades or falls back to plain Google Translate unless explicitly requested.
     * **🔄 Auto-Fallback to Free Model (Explicit Opt-In Only):** Routes remaining batches to the free translation engine and Edge-TTS without stopping (only used if explicitly selected by the user).
   - **🆓 Free Mode Default:** When no Gemini API key is configured anywhere in the pool, BookApp automatically operates in **Free Mode** (indicated by the `🆓 Free Mode` pill in the navbar). Translation, typography rules, and neural audiobooks run 100% free with zero keys or subscriptions.

7. **Starting Translation:**
   - Click **🌐 Start Translation** (for a single file) or **▶️ Start Batch Translation** (for multiple files).
   - The live progress bar reflects exact completion metrics (e.g. `Completed 12 of 103 AI batches (45 / 340 pages)`).

8. **Downloading Result & Copying Text:**
   - Click **⬇️ Download [FORMAT] File** to save your translated book.
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
* **⏳ Time Remaining:** Live estimated time to completion (`~4m 20s`) based on true processing throughput (`24 pages/min` or `1.8 batches/s`).
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

### 🔑 Gemini Multi-Key API Pool & Auto-Failover
* **Connect up to 4 Free Gemini API Keys:** Enter keys in Slots 1 through 4 (Slot 1 Primary + Slots 2–4 Backups) from different Google accounts.
* **Up to 6,000 Free Requests/Day ($0 Cost):** Each free Google account grants 1,500 requests/day. Combining 4 keys multiplies your daily quota to 6,000 requests completely free.
* **Instant Automatic Failover:** When Slot 1 encounters quota exhaustion (HTTP 429), the engine **instantly rotates to Slot 2, then Slot 3, then Slot 4** without pausing or losing progress.
* **Authoritative Server Sync & Key Protection:** The application performs a safe bidirectional merge between server configuration (`config/settings.json`) and browser `localStorage`. Your configured backup keys are never accidentally wiped, duplicated, or dropped when switching tabs or refreshing the page.
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

### In-Place Layout & Style Preservation
* **Word Documents (`.docx`):** Preserves font sizes, font families (Times New Roman, Arial, Calibri), **Bold**, *Italics*, underline, tables, and nested drawings. Bullet points from Wingdings/Symbol are converted to clean standard Unicode bullets (`•`).
* **Front Matter Preservation:** Line-level header/footer cleaning preserves prologues, epigraphs, and tables of contents on the opening pages.
* **EPUB (`.epub`):** Retains CSS stylesheets, chapter hierarchies (`<h1>`–`<h6>`), and embedded images.
* **PDF (`.pdf`):** Formats headings, validates all characters against font glyph sets to eliminate missing tofu boxes (`□□`), and wraps long URLs cleanly within page margins.

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

**Turning it on/off:** use the **🔍 Τελικός Αυτόματος Έλεγχος Ποιότητας** checkbox in the Translation or Audiobook panel (one setting for both). When it is off, the application works exactly as before. The check runs on your computer and **never uses your Gemini quota**.

---

## 4. Audiobook Generation

Convert any document into high-fidelity MP3 and M4B audiobooks with embedded chapter metadata and cover art.

### Available Neural Voices & Live Auditions
* **Greek Neural Voices (🇬🇷):**
  * 👨 **Nestoras (Male)** (`el-GR-NestorasNeural`) — Recommended voice with exceptional pronunciation and acronym handling.
  * 👩 **Athina (Female)** (`el-GR-AthinaNeural`) — Natural feminine voice.
* **English Neural Voices (🇬🇧 / 🇺🇸):**
  * 👩 Aria, Jenny, Emma
  * 👨 Guy, Davis, Ryan
* 🔊 **Live Voice Audition:** Click **«🔊 Preview»** next to any voice card to hear a 2–3 second sample before generating your audiobook.

### 🎭 Multi-Voice Dramatization
Create a theatrical audio experience:
1. Enable **🎭 Multi-Voice Dramatization**.
2. Select your primary voice for **Narrator** (e.g. Nestoras) and secondary voice for **Dialogue** (e.g. Athina).
3. The system automatically detects quotes (`«...»`) and dialogue dashes (`—`), routing character speech to the dialogue voice and descriptive prose to the narrator voice.

### 📦 M4B Export & Embedded Cover Art
* Every audiobook exports with complete metadata tags (Title, Artist, Album, Genre="Audiobook").
* Active cover art is embedded directly into the audio file container (**Embedded APIC Cover Art**), rendering natively in Apple Books, Android players, and car dashboards.
* **Streamed Audio Assembly:** Audio chunks are assembled in 64KB streams, ensuring 10+ hour audiobooks render without high RAM usage.

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

## 5. Session History & Task Management

The **Session History** panel at the bottom of the page tracks all jobs:
* **Reload & Full Settings Restoration:** Clicking any history entry restores the document, output format, layout style, language direction, and page metrics.
* **Interrupted Job Resumption:** If an AI translation was paused, clicking **Start Translation** continues from the saved checkpoint (`.direct_ai_checkpoint.json`).
* **Deleting Individual Jobs:** Click **✕** on any history item to remove it from database, queue, and disk.
* **Clearing All History:** Click **🗑️ Clear All** (with confirmation) to delete old jobs and temporary files while preserving the translation cache.
* **Automatic Test Job Isolation & Zero-Junk History:** Automated test runs and test-generated jobs (files or identifiers matching `test_*`, `reg_*`, `mock_*`, `sample_*`, `direct_text*`, `book*`, `temp_*`, `stress_*`) are automatically purged from disk and strictly filtered out of Session History. Even if test suites execute in the background, your Session History stays 100% clean, displaying only your real personal translations.

---

## 6. Frequently Asked Questions & Troubleshooting

#### ❓ Can I download a translated book in another format without re-translating?
* **Yes!** Simply click **PDF**, **DOCX**, **EPUB**, or **TXT** and click **⬇️ Download**. The conversion happens in less than one second without making new translation calls.

#### ❓ Can I polish text directly in the Editor without uploading a file?
* **Yes!** Open the **Direct Editor**, paste your text, and click **✨ AI Polish**. The system processes your text and lets you download it as TXT, DOCX, PDF, or EPUB.

#### ❓ How are scanned PDF comics translated?
* The upload analyzer automatically detects scanned comics (`🎨 Graphic Novel / Comic Auto-Detected`) and locks the interface to comic-safe options. The **Gemini Vision AI** reads speech balloons across 4 parallel workers, inpainting backgrounds and drawing translated text in comic typography while keeping 100% of the artwork intact.

#### ❓ How does Single-Pass Direct AI Translation speed up processing?
* Enabling **✨ AI Polish** with a Gemini API key translates and polishes in **one single parallel pass** (5 concurrent workers). It is **4x–8x faster**, avoids Google Translate 429 limits, and preserves glossary terms, entity consistency dossiers, and cover art.

#### ❓ How do I use the Smart Batch Queue?
* Drop **up to 20 files** into the Upload Card. Configure your Translation Settings below and click **▶️ Start Batch Translation**. The queue runs serially with parallel internal workers, per-item retry, pause/resume, individual download buttons, and a master **📦 Download All (ZIP)** button once all jobs finish.

#### ❓ What do the "🔄 Refresh" and "🔑 Gemini API Key" buttons do?
* **🔄 Refresh:** Instantly refreshes page state, session history, and server settings.
* **🔑 Gemini API Key:** Opens the Multi-Key Pool modal with individual slot status and auto-save capabilities.

#### ❓ Can I translate older Word (.doc) files?
* Please open the file in Microsoft Word and save it as `.docx` before uploading.

#### ❓ Do I need to pay for an API key?
* **No.** Standard document translation and Microsoft Edge neural voices are 100% free with zero keys. A free Google Gemini API key is only needed for Gemini AI Polish and scanned comic Vision AI.

#### ❓ How long does translation or audio generation take?
* Small documents (1–5 pages): **2 to 10 seconds**.
* Medium documents (20–50 pages): **20 seconds to 1.5 minutes**.
* Full books (200–500 pages): **3 to 12 minutes** (and `0 ms` for cached chunks).
* Scanned Graphic Novels (~60 pages): **~1.5 to 3 minutes**.

#### ❓ What happens if Google Translate hits a temporary rate limit (HTTP 429)?
* The application triggers a **429 Circuit Breaker** with fallback to MyMemory API and automatic failover to Gemini Flash, ensuring translations complete without interruption.

#### ❓ What happens if I don't enter a Gemini API Key?
* The application automatically enables **Free Mode** (indicated by the `🆓 Free Mode` badge). Translations use Google Translate, editorial typography rules are applied, and audiobooks use Edge-TTS neural voices completely free.

#### ❓ What happens if the Gemini daily quota is reached?
* The application distinguishes momentary burst limits (15 RPM) from daily exhaustion. If daily quota is reached:
  * With **Gemini Multi-Key Pool**, it automatically rotates to backup keys (Slots 2–4).
  * If all keys in the pool are exhausted:
    - By default (`quota_behavior="wait"`), translation and audiobook generation **pause cleanly at disk checkpoint** (`.direct_ai_checkpoint.json` / `.comic_vision_checkpoint.json`) and **wait for quota reset**.
    - The system displays a live countdown timer in the UI.
    - **Automatic Resumption:** The background quota monitor automatically resumes paused jobs and queued batch items the second the cooldown expires or as soon as new working keys are saved in Settings!
    - It **NEVER automatically falls back** to plain Google Translate or unpolished text unless you deliberately choose the `fallback` option.
    - Graphic novels and comics also strictly respect this mode, pausing page-by-page rather than outputting unpolished or plain text.

#### ❓ Why does the reader voice stumble on foreign names?
* Use **AI Polish for Spoken Audio (style="audiobook")**, which phonetically transcribes foreign names into Greek characters (`Keeton` ➔ `Κίτον`, `DNA` ➔ `Ντι-Εν-Έι`) and spells out all numbers in full Greek words.
