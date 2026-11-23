/* i18n.js - Interface language: Ελληνικά / English.
   Loaded in <head> before the page, so text is switched as it appears. Every phrase of the interface is listed once
   with its Greek and English form (and any other wording the pages used); a watcher puts whichever is chosen in place
   of the other, also in text the scripts add later (toasts, queue rows, buttons). {name} marks a changing part, such as
   a number or a file name: "▶️ Start Batch Translation ({n} files)" is recognised with any number.
   Book text, file names and glossary terms are inside translate="no" and stay as they are. */
'use strict';

const UI_LANG_KEY = 'bookapp_ui_lang';

// [Greek, English, ...other wordings found in the pages]
const I18N_PAIRS = [
  // ── Top bar, account, modes, tabs ──
  ['DocTranslate & AudioBook — Επεξεργασία εγγράφων Αγγλικά ↔ Ελληνικά', 'DocTranslate & AudioBook — English ↔ Greek Document Processor'],
  ['Ο λογαριασμός μου · αλλαγή κωδικού', 'My account · change password'],
  ['Διαχείριση χρηστών', 'Manage users'],
  ['👥 Χρήστες', '👥 Users'],
  ['Αποσύνδεση', 'Sign out'],
  ['🚪 Αποσύνδεση', '🚪 Sign out'],
  ['Ανανέωση σελίδας & δεδομένων', 'Refresh page & data', 'Ανανέωση Σελίδας & Δεδομένων (Refresh)'],
  ['Ανανέωση σελίδας', 'Refresh page', 'Refresh Page', 'Ανανέωση Σελίδας (Refresh)'],
  ['Ανανέωση', 'Refresh'],
  ['Εναλλαγή σκούρου / φωτεινού θέματος', 'Switch dark / light theme', 'Εναλλαγή Dark / Light Mode'],
  ['Εναλλαγή θέματος', 'Toggle theme', 'Toggle Theme'],
  ['Θέμα', 'Theme'],
  ['Σκούρο', 'Dark'],
  ['Φωτεινό', 'Light'],
  ['Γλώσσα περιβάλλοντος', 'Interface language'],
  ['Με νευρωνική τεχνητή νοημοσύνη', 'Neural AI Powered'],
  ['Μεταφράστε μεγάλα έγγραφα ανάμεσα σε', 'Translate large documents between'],
  ['Αγγλικά & Ελληνικά', 'English & Greek'],
  ['και δημιουργήστε επαγγελματικά audiobooks με νευρωνικές φωνές — έως 2.500 σελίδες.', 'and generate professional-quality audiobooks with neural voices — up to 2,500 pages.'],
  ['Απλή λειτουργία (AI με 1 κλικ)', 'Basic Mode (1-Click AI)', 'Απλή Λειτουργία (1-Click AI Magic)'],
  ['Προχωρημένη λειτουργία (πλήρης έλεγχος)', 'Advanced Mode (Full Control)', 'Advanced Mode (Πλήρης Έλεγχος)', 'Προχωρημένη Λειτουργία (Πλήρεις Ρυθμίσεις & Έλεγχος)'],
  ['⚡ Ενεργοποιήθηκε η απλή λειτουργία (AI με 1 κλικ)', '⚡ Basic Mode (1-Click AI) is on', '⚡ Ενεργοποιήθηκε η Απλή Λειτουργία (1-Click AI)'],
  ['⚙️ Ενεργοποιήθηκε η προχωρημένη λειτουργία (πλήρεις ρυθμίσεις)', '⚙️ Advanced Mode (full settings) is on', '⚙️ Ενεργοποιήθηκε η Προχωρημένη Λειτουργία (Πλήρεις Ρυθμίσεις)'],
  ['Κύρια πλοήγηση', 'Main navigation'],
  ['Μετάφραση εγγράφου', 'Translate Document'],
  ['Δημιουργία audiobook', 'Generate Audiobook'],
  ['Γλωσσάρι', 'Glossary', 'Γλωσσάρι (Glossary)', 'Glossary (Γλωσσάρι)'],
  ['Ρυθμίσεις & κλειδί Gemini API', 'Settings & Gemini API key', 'Ρυθμίσεις & Gemini API Key'],
  ['Κλειδί Gemini API', 'Gemini API Key'],
  ['{a} · {#p}%', '{a} · {#p}%'],

  // ── Quota and resume banners ──
  ['Ημερήσιο όριο Google Gemini (δωρεάν πρόγραμμα):', 'Google Gemini daily limit (free tier):', 'Ημερήσιο Όριο Google Gemini (Free Tier Quota):'],
  ['Εξαντλήθηκε το ημερήσιο όριο χρήσης.', 'The daily usage limit has been reached.'],
  ['🔑 Αλλαγή κλειδιού API', '🔑 Change API key', '🔑 Αλλαγή API Key'],
  ['Ημιτελής εργασία σε checkpoint:', 'Unfinished job at a checkpoint:', 'Ημιτελής Εργασία σε Checkpoint:'],
  ['Βρέθηκε εργασία έτοιμη για άμεση συνέχιση.', 'A job is ready to resume.'],
  ['▶️ Συνέχιση ΤΩΡΑ', '▶️ Resume NOW'],
  ['Παράβλεψη', 'Dismiss'],
  ['Ημερήσιο όριο Gemini (δωρεάν πρόγραμμα):', 'Gemini daily limit (free tier):', 'Ημερήσιο Όριο Gemini (Free Tier):'],
  ['Εξαντλημένο όριο Gemini:', 'Gemini limit reached:', 'Εξαντλημένο Όριο Gemini:'],
  ['Ειδοποίηση ορίου Gemini:', 'Gemini limit notice:', 'Ειδοποίηση Ορίου Gemini:'],
  ['{done}/{total} τμήματα · {p}% ολοκληρωμένο', '{done}/{total} parts · {p}% done'],
  ['» ({info}). Πατήστε για άμεση συνέχιση από το checkpoint.', '» ({info}). Press to resume from the checkpoint at once.'],

  // ── Upload card and batch queue ──
  ['Ανέβασμα εγγράφων', 'Upload Document(s)'],
  ['1 αρχείο ή έως 20 αρχεία (Smart Batch Queue)', '1 file or up to 20 files (Smart Batch Queue)'],
  ['Ανεβάστε ένα ή περισσότερα έγγραφα για μετάφραση', 'Upload one or multiple documents for translation'],
  ['Αφήστε εδώ τα έγγραφά σας', 'Drop your document(s) here'],
  ['Κάντε κλικ για να επιλέξετε 1 ή περισσότερα αρχεία (έως 20 για τη Smart Batch Queue)', 'Click to select 1 or multiple files (up to 20 files for Smart Batch Queue)'],
  ['ΕΩΣ 20 ΑΡΧΕΙΑ', 'MAX 20 FILES'],
  ['Φόρτωση...', 'Loading...'],
  ['Ανέβασμα αρχείου', 'File upload'],
  ['Ανέβασμα αρχείων', 'Uploading files'],
  ['Προσθέστε κι άλλα αρχεία για μαζική μετάφραση (έως 20)', 'Add more files for batch translation (up to 20)'],
  ['➕ Προσθήκη', '➕ Add More'],
  ['➕ Προσθήκη', '➕ Add'],
  ['Αφαίρεση αρχείου', 'Remove file'],
  ['Οι ρυθμίσεις από κάτω εφαρμόζονται σε όλα τα αρχεία σε αναμονή (με αυτόματη προστασία για Comics).', 'The settings below apply to every waiting file (with automatic protection for comics).'],
  ['⚡ Αυτόματη έναρξη', '⚡ Auto-Start'],
  ['Η αυτόματη έναρξη είναι κλειδωμένη', 'Auto-Start is locked', 'Το Auto-Start είναι κλειδωμένο'],
  [', επειδή η ουρά έχει μαζί βιβλία και comics: ελέγξτε τις ρυθμίσεις από κάτω και πατήστε', ', because the queue mixes books and comics: check the settings below and press'],
  ['▶️ Έναρξη μαζικής μετάφρασης', '▶️ Start Batch Translation'],
  ['⏸️ Παύση ουράς', '⏸️ Pause Queue'],
  ['➕ Προσθήκη αρχείων', '➕ Add More Files'],
  ['📦 Λήψη όλων (ZIP)', '📦 Download All (ZIP)'],
  ['🗑️ Άδειασμα ουράς', '🗑️ Clear Queue'],
  ['▶️ Συνέχιση ουράς ({n} απομένουν)', '▶️ Resume Batch Queue ({n} left)'],
  ['▶️ Έναρξη μαζικής μετάφρασης ({n} αρχεία)', '▶️ Start Batch Translation ({n} files)'],
  ['⏳ Μετάφραση παρτίδας ({d}/{t})...', '⏳ Translating Batch ({d}/{t})...'],
  ['⏳ Αναμονή για όριο Gemini ({n})', '⏳ Waiting for Gemini quota ({n})'],
  ['✅ Η παρτίδα ολοκληρώθηκε ({d}/{t})', '✅ Batch Complete ({d}/{t})'],
  ['⚠️ Η παρτίδα τελείωσε ({d}/{t})', '⚠️ Batch finished ({d}/{t})'],
  ['{d} / {t} ολοκληρώθηκαν (μέγ. {m}) · {note}', '{d} / {t} done (max {m}) · {note}'],
  ['{d} / {t} ολοκληρώθηκαν (μέγ. {m})', '{d} / {t} done (max {m})'],
  ['⏸️ Παύση...', '⏸️ Pausing...'],
  ['⏸️ Σε παύση', '⏸️ Paused'],
  ['⚠️ Συμπληρώθηκε το όριο ({n}/{m})', '⚠️ Limit Reached ({n}/{m})'],
  ['➕ Προσθήκη αρχείων ({n}/{m})', '➕ Add More Files ({n}/{m})'],
  ['Λήψη όλων των ολοκληρωμένων μεταφράσεων ως ZIP', 'Download all completed translations as ZIP'],
  ['Η λήψη όλων ενεργοποιείται όταν ολοκληρωθούν όλες οι μεταφράσεις ({d} / {t} ολοκληρώθηκαν)', 'Download All will be enabled once all translations are completed ({d} / {t} done)'],
  ['Απενεργοποιημένο σε μικτή ουρά (βιβλία + graphic novels) ώστε να ελέγχετε τις ρυθμίσεις πριν την εκκίνηση.', 'Off in a mixed queue (books + graphic novels), so you check the settings before it starts.', 'Απενεργοποιημένο σε μικτή ουρά (Βιβλία + Graphic Novels) ώστε να ελέγχετε τις ρυθμίσεις πριν την εκκίνηση.'],
  ['Αυτόματη έναρξη μετάφρασης μόλις προστεθούν αρχεία', 'Start translating as soon as files are added'],
  ['⏳ Σε αναμονή (αυτόματη συνέχιση)', '⏳ Waiting (Auto-Resume)', '⏳ Σε αναμονή (Auto-Resume)'],
  [' · ⏳ Αναμονή Gemini AI (100% ποιότητα)', ' · ⏳ Waits for Gemini AI (100% quality)'],
  [' · ⚠️ Χωρίς AI Polish (Fallback)', ' · ⚠️ Without AI Polish (fallback)'],
  ['Αφαίρεση από την ουρά', 'Remove from the queue'],
  ['⏳ Waiting in queue...', '⏳ Waiting in queue...'],
  ['⏳ Σε αναμονή στην ουρά...', '⏳ Waiting in queue...'],
  ['🔄 Το αρχείο ξαναμπήκε στην ουρά για επανάληψη!', '🔄 The file is back in the queue for a retry!'],
  ['▶️ Η Smart Batch Queue συνεχίζει με τις αποθηκευμένες ρυθμίσεις κάθε αρχείου.', '▶️ The Smart Batch Queue continues with each file\'s saved settings.'],
  ['▶️ Η Smart Batch Queue ξεκίνησε με τις επιλεγμένες ρυθμίσεις (σειριακή εκτέλεση).', '▶️ The Smart Batch Queue started with the chosen settings (one file at a time).'],
  ['⏸️ Η ουρά θα παύσει μόλις ολοκληρωθεί το τρέχον έγγραφο.', '⏸️ The queue will pause once the current document is finished.'],
  ['⚠️ Η αυτόματη έναρξη είναι απενεργοποιημένη σε μικτή ουρά (βιβλία + graphic novels) για ασφαλή έλεγχο ρυθμίσεων.', '⚠️ Auto-Start is off in a mixed queue (books + graphic novels), so the settings can be checked.', '⚠️ Το Auto-Start είναι απενεργοποιημένο σε μικτή ουρά (Βιβλία + Graphic Novels) για ασφαλή έλεγχο ρυθμίσεων.'],
  ['⚠️ Η αυτόματη έναρξη είναι απενεργοποιημένη σε μικτή ουρά (βιβλία + graphic novels).', '⚠️ Auto-Start is off in a mixed queue (books + graphic novels).', '⚠️ Το Auto-Start είναι απενεργοποιημένο σε μικτή ουρά (Βιβλία + Graphic Novels).'],
  ['⚡ Η αυτόματη έναρξη ουράς ενεργοποιήθηκε.', '⚡ Auto-Start Queue is on.', '⚡ Auto-Start Queue ενεργοποιήθηκε.'],
  ['⏸️ Χειροκίνητη ουρά ενεργή.', '⏸️ Manual queue mode is on.', '⏸️ Manual Queue mode ενεργό.'],
  ['🗑️ Η ουρά καθαρίστηκε.', '🗑️ The queue was cleared.'],
  ['Η ουρά περιμένει και θα συνεχίσει αυτόματα με AI μόλις ανανεωθεί το όριο.', 'The queue waits and continues with AI automatically once the limit renews.'],
  ['Η ουρά συνεχίζει αυτόματα χωρίς AI Polish.', 'The queue continues automatically without AI Polish.'],
  ['Τα έγγραφα σε «Αναμονή» περιμένουν την ανανέωση του ορίου· όσα έχουν Auto-Fallback συνεχίζουν χωρίς AI Polish.', 'Documents set to "Wait" wait for the limit to renew; those with Auto-Fallback continue without AI Polish.'],
  ['Εξαντλήθηκε το ημερήσιο όριο του Gemini Free Tier. {rest}', 'The Gemini free tier daily limit has been reached. {rest}'],
  ['⚠️ Εξαντλήθηκε το ημερήσιο όριο Gemini Free Tier. {rest}', '⚠️ The Gemini free tier daily limit has been reached. {rest}'],
  ['Παρακαλώ περιμένετε να ολοκληρωθεί η προηγούμενη προσθήκη αρχείων...', 'Please wait until the previous files have been added...'],
  ['⚠️ Το όριο της ουράς είναι {m} αρχεία. Καθαρίστε ή αφαιρέστε κάποια για να προσθέσετε νέα.', '⚠️ The queue holds at most {m} files. Clear or remove some to add new ones.'],
  ['⚠️ Μέγιστο όριο {m} αρχεία ανά παρτίδα — θα προστεθούν τα πρώτα {n} αρχεία.', '⚠️ At most {m} files per batch — the first {n} files will be added.'],
  ['⏳ Φόρτωση {n} αρχείων στην Smart Batch Queue...', '⏳ Loading {n} files into the Smart Batch Queue...'],
  ['μη υποστηριζόμενο format', 'unsupported format'],
  ['❌ Αποτυχία φόρτωσης "{f}": {r}', '❌ "{f}" did not upload: {r}'],
  ['❌ Σφάλμα φόρτωσης "{f}": {r}', '❌ Error uploading "{f}": {r}'],
  ['❌ "{f}": Αποτυχία προσθήκης στην ουρά', '❌ "{f}": could not be added to the queue'],
  ['❌ Σφάλμα προσθήκης "{f}": {r}', '❌ Error adding "{f}": {r}'],
  ['📋 Προστέθηκαν {n} αρχεία στην Smart Batch Queue! Ρυθμίστε τις επιλογές από κάτω και πατήστε Start.', '📋 {n} files added to the Smart Batch Queue! Set the options below and press Start.'],
  ['📋 Προστέθηκαν {n} αρχεία στην Smart Batch Queue! (Μικτή ουρά: το Auto-Start απενεργοποιήθηκε αυτόματα για έλεγχο ρυθμίσεων).', '📋 {n} files added to the Smart Batch Queue! (Mixed queue: Auto-Start was switched off so the settings can be checked.)'],
  ['⬆️ Ανέβασμα {i}/{n}: "{f}" {p}% (σύνολο {o}%, {a} / {b} MB)', '⬆️ Uploading {i}/{n}: "{f}" {p}% (total {o}%, {a} / {b} MB)'],
  ['⏳ Αρχείο {i}/{n}: "{f}" ανέβηκε· επεξεργασία… (σύνολο {o}%)', '⏳ File {i}/{n}: "{f}" uploaded · processing… (total {o}%)'],
  ['⚠️ Ανέβηκαν {u} από {n} αρχεία. Δεν ανέβηκαν:', '⚠️ {u} of {n} files uploaded. Not uploaded:'],
  ['{s} MB · {t} · ⬆️ Ανέβασμα {p}% ({a} / {b} MB)', '{s} MB · {t} · ⬆️ Uploading {p}% ({a} / {b} MB)'],
  ['{s} MB · {t} · ⏳ Ανέβηκε· επεξεργασία αρχείου…', '{s} MB · {t} · ⏳ Uploaded · processing the file…'],
  ['{s} MB · ~{p} σελίδες · {t} · Έτοιμο', '{s} MB · ~{p} pages · {t} · Ready'],
  ['{s} MB · ~{p} σελίδες · {t} · ⏱️ ~{d} ακρόαση · Έτοιμο', '{s} MB · ~{p} pages · {t} · ⏱️ ~{d} listening · Ready', '{s} MB · ~{p} pages · {t} · ⏱️ ~{d} ακρόαση · Ready'],
  ['{s} MB · {t} · Έτοιμο', '{s} MB · {t} · Ready'],
  ['~{p} σελίδες · {t} · Έτοιμο', '~{p} pages · {t} · Ready'],
  ['{t} · Έτοιμο', '{t} · Ready'],
  ['{t} · Ολοκληρώθηκε', '{t} · Completed'],
  ['{t} · Σε εξέλιξη', '{t} · In Progress'],
  ['Φορτώθηκε από το Ιστορικό · {rest}', 'Loaded from Session History · {rest}'],
  ['{p} σελίδες · {rest}', '{p} pages · {rest}'],
  ['{#h} ώρες {#m} λ', '{#h} h {#m} min'],
  ['{#h} ώρα {#m} λ', '{#h} h {#m} min'],
  ['✅ "{f}" ανέβηκε.', '✅ "{f}" uploaded successfully.'],
  ['❌ Σφάλμα ανεβάσματος: {r}', '❌ Upload error: {r}'],
  ['❌ Ο τύπος αρχείου "{e}" δεν υποστηρίζεται. Χρησιμοποιήστε {l}.', '❌ File type "{e}" is not supported. Please use {l}.'],
  ['PDF, DOCX ή EPUB', 'PDF, DOCX, or EPUB'],
  ['PDF, DOCX, EPUB ή CBZ', 'PDF, DOCX, EPUB, or CBZ'],
  ['(χωρίς επέκταση)', '(no extension)'],
  ['Σφάλμα δικτύου κατά το ανέβασμα', 'Network error while uploading'],
  ['Το ανέβασμα απέτυχε', 'Upload failed'],

  // ── Basic mode, direction, format, layout, cover ──
  ['Ρυθμίσεις μετάφρασης', 'Translation Settings'],
  ['Απλή λειτουργία (μετάφραση με AI σε 1 κλικ)', 'Basic mode (1-click AI translation)', 'Απλή Λειτουργία (1-Click AI Translation)'],
  ['Αυτόματη ανίχνευση:', 'Automatic detection:', 'Αυτόματη Ανίχνευση:'],
  ['Αγγλικά ⇄ Ελληνικά, αυτόματο ταίριασμα μορφής (PDF, DOCX, EPUB, Comic).', 'English ⇄ Greek, output format matched automatically (PDF, DOCX, EPUB, Comic).'],
  ['Ενεργό AI:', 'AI on:'],
  ['Αυτόματη λογοτεχνική επιμέλεια ροής & διαλόγων με το Multi-Key Pool (έως 4 κλειδιά).', 'Automatic literary editing of flow & dialogue with the Multi-Key Pool (up to 4 keys).'],
  ['Έναρξη με 1 κλικ:', '1-click start:', '1-Click Έναρξη:'],
  ['Απλά ανεβάστε το αρχείο σας και πατήστε το κουμπί!', 'Just upload your file and press the button!'],
  ['Κατεύθυνση μετάφρασης', 'Translation Direction'],
  ['🇬🇧 Αγγλικά', '🇬🇧 English'],
  ['🇬🇷 Ελληνικά', '🇬🇷 Greek'],
  ['Αντιστροφή γλωσσών', 'Swap languages'],
  ['Αντιστροφή γλώσσας πρωτοτύπου και μετάφρασης', 'Swap source and target languages'],
  ['Μορφή εξόδου', 'Output Format'],
  ['Απλό κείμενο', 'Plain text'],
  ['Έγγραφο Word', 'Word document'],
  ['Αρχείο PDF', 'PDF file'],
  ['Ηλεκτρονικό βιβλίο', 'E-book'],
  ['Αρχείο κόμικ', 'Comic Archive'],
  ['Κόμικ (RAR)', 'Comic (RAR)'],
  ['Λειτουργία Graphic Novel:', 'Graphic Novel mode:'],
  ['Τα formats TXT & DOCX είναι απενεργοποιημένα επειδή διατηρούνται ανέπαφες οι εικόνες και τα μπαλόνια. Επιλέξτε', 'TXT & DOCX are off because the images and balloons are kept intact. Choose'],
  ['PDF, CBZ, CBR ή EPUB', 'PDF, CBZ, CBR or EPUB'],
  ['Διάταξη εγγράφου', 'Document Layout Style'],
  ['Τυπικό / Έγγραφο', 'Standard / Document', 'Standard / Έγγραφο'],
  ['A4 · Διατήρηση σελίδων', 'A4 · Pages kept'],
  ['Λογοτεχνικό / E-Reader', 'Literature / E-Reader'],
  ['Κεφάλαια, εσοχές, serif', 'Chapters, indents, serif', 'Κεφάλαια, Εσοχές, Serif'],
  ['Εικόνες αναλλοίωτες · Μπαλόνια', 'Artwork untouched · Balloons'],
  ['Φορά ανάγνωσης (Graphic Novel / Manga)', 'Reading direction (Graphic Novel / Manga)', 'Reading Direction (Φορά Ανάγνωσης Graphic Novel / Manga)'],
  ['Τυπική (από αριστερά προς δεξιά ➡️)', 'Standard (Left-to-Right ➡️)'],
  ['Manga (από δεξιά προς αριστερά ⬅️)', 'Manga (Right-to-Left ⬅️)'],
  ['Εξώφυλλο βιβλίου', 'Book cover image', 'Εξώφυλλο Βιβλίου (Book Cover Image)'],
  ['Μικρογραφία εξωφύλλου', 'Cover thumbnail'],
  ['Δεν έχει οριστεί εξώφυλλο. Μπορείτε να ανεβάσετε οποιαδήποτε εικόνα (JPG, PNG, WebP).', 'No cover set. You can upload any image (JPG, PNG, WebP).'],
  ['📷 Ανέβασμα εξωφύλλου', '📷 Upload cover', '📷 Ανέβασμα Εξωφύλλου (Upload Cover)'],
  ['✕ Αφαίρεση', '✕ Remove', '✕ Αφαίρεση (Remove)'],
  ['Απενεργοποιημένο — εντοπίστηκε Graphic Novel / Comic', 'Off — a graphic novel / comic was detected'],
  ['Δεν ισχύει για Graphic Novels — χρησιμοποιήστε Έναρξη μετάφρασης (με ή χωρίς AI Polish)', 'Not for graphic novels — use Start Translation (with or without AI Polish)', 'Δεν ισχύει για Graphic Novels — χρησιμοποιήστε Start Translation (με ή χωρίς AI Polish checkbox)'],
  ['Δεν ισχύει για Graphic Novels', 'Not for graphic novels'],
  ['Εντοπίστηκε αυτόματα Graphic Novel / Comic{d}:', 'Graphic Novel / Comic Auto-Detected{d}:'],
  ['Ενεργοποιήθηκαν αποκλειστικά οι επιλογές Graphic Novel (', 'Only the graphic novel options are on ('],
  ['& LTR/RTL). Οι επιλογές κειμένου/βιβλίου απενεργοποιήθηκαν αυτόματα.', '& LTR/RTL). The text/book options were switched off automatically.'],
  ['🎨 Εντοπίστηκε Graphic Novel / Comic! Ενεργοποιήθηκαν αποκλειστικά οι επιλογές Graphic Novel.', '🎨 Graphic novel / comic detected! Only the graphic novel options are on.'],
  ['Μη διαθέσιμο για Graphic Novels (διατηρούνται εικόνες & μπαλόνια διαλόγων)', 'Not available for graphic novels (artwork & speech balloons are kept)'],
  ['Διαθέσιμο μόνο σε Graphic Novels / Comics', 'Only for graphic novels / comics'],
  ['⚠️ Το format {f} είναι απενεργοποιημένο για Graphic Novels. Επιλέξτε PDF, CBZ, CBR ή EPUB.', '⚠️ {f} is off for graphic novels. Choose PDF, CBZ, CBR or EPUB.'],
  ['Αυτή η επιλογή είναι απενεργοποιημένη για Graphic Novels / Comics.', 'This option is off for graphic novels / comics.'],
  ['Ανιχνεύθηκε ύφος:', 'Detected style:'],
  ['{g} ({#c}% βεβαιότητα). {r}', '{g} ({#c}% confidence). {r}'],
  ['📖 Λογοτεχνικό', '📖 Literature', '📖 Λογοτεχνικό (Literature)'],
  ['🪶 Ποίηση / Στίχοι', '🪶 Poetry', '🪶 Ποίηση / Στίχοι (Poetry)'],
  ['💻 Τεχνικό / Πληροφορική', '💻 Technical', '💻 Τεχνικό / Πληροφορική (Technical)'],
  ['🏛️ Επίσημο / Διοικητικό', '🏛️ Formal', '🏛️ Επίσημο / Διοικητικό (Formal)'],
  ['✓ Εφαρμόστηκε αυτόματα', '✓ Applied automatically'],
  ['✓ Εφαρμόστηκε', '✓ Applied'],
  ['Εφαρμογή προτεινόμενου', 'Apply the suggestion', 'Εφαρμογή Προτεινόμενου'],
  ['✅ Εφαρμόστηκε στυλ: {g}', '✅ Style applied: {g}'],
  ['Παρακαλώ ανεβάστε πρώτα ένα έγγραφο και μετά το εξώφυλλο.', 'Please upload a document first before adding a cover.'],
  ['Ανέβασμα εξωφύλλου...', 'Uploading book cover image...'],
  ['✅ Το εξώφυλλο ενημερώθηκε! Μπαίνει σε PDF, EPUB & DOCX.', '✅ Book cover updated successfully! Included in PDF, EPUB & DOCX.'],
  ['Το εξώφυλλο αφαιρέθηκε.', 'Book cover removed.'],
  ['Αποτυχία ανεβάσματος εξωφύλλου: {r}', 'Failed to upload cover: {r}'],
  ['Αποτυχία αφαίρεσης εξωφύλλου: {r}', 'Failed to remove cover: {r}'],

  // ── AI Polish, maximum quality, final check, quota behaviour ──
  ['— Επιμέλεια λογοτεχνικής ροής & διαλόγων μπαλονιών', '— literary editing of flow & balloon dialogue'],
  ['⚠️ Όριο quota', '⚠️ Quota limit', '⚠️ Όριο Quota'],
  ['Στα Graphic Novels / Comics βελτιστοποιεί τις ατάκες ώστε να χωρούν στα μπαλόνια με φυσικό, ζωντανό προφορικό λόγο.', 'In graphic novels / comics it shapes the lines to fit the balloons, in natural, lively speech.'],
  ['Μέγιστη ποιότητα', 'Maximum quality'],
  ['— 2ο πέρασμα AI: αναθεώρηση της μετάφρασης με το πρωτότυπο', '— 2nd AI pass: the translation revised against the original'],
  ['Όπως ο δεύτερος επιμελητής σε εκδοτικό οίκο: συγκρίνει κάθε πρόταση με το πρωτότυπο και διορθώνει λάθη νοήματος, παραλείψεις, συμφωνίες και λεξιλόγιο. Απαιτεί AI Polish.', 'Like a second editor at a publishing house: it compares every sentence with the original and corrects mistakes of meaning, omissions, agreement and wording. Requires AI Polish.'],
  ['Τελικός αυτόματος έλεγχος ποιότητας', 'Final automatic quality check', 'Τελικός Αυτόματος Έλεγχος Ποιότητας'],
  ['— τελική βελτίωση εξόδου', '— Final Output Refinement'],
  ['Τοπικός έλεγχος & ασφαλείς διορθώσεις στο τέλος κάθε μετάφρασης/ηχητικού βιβλίου (χωρίς κατανάλωση API).', 'Local check & safe corrections at the end of every translation/audiobook (no API use).'],
  ['🔍 Ο τελικός έλεγχος ποιότητας ενεργοποιήθηκε.', '🔍 The final quality check is on.'],
  ['Ο τελικός έλεγχος ποιότητας απενεργοποιήθηκε.', 'The final quality check is off.'],
  ['Αποτυχία αποθήκευσης ρύθμισης τελικού ελέγχου.', 'The final check setting could not be saved.'],
  ['⚡ Όταν εξαντληθεί το όριο Gemini', '⚡ When the Gemini limit runs out', '⚡ Σε εξάντληση ορίου Gemini (On Quota Limit)'],
  ['Προεπιλογή: αναμονή για επαναφορά (χωρίς κλειδί API: δωρεάν μοντέλο)', 'Default: wait for the reset (without an API key: free model)', 'Προεπιλογή: Αναμονή για επαναφορά (χωρίς API Key: Δωρεάν Μοντέλο)'],
  ['Αναμονή για επαναφορά', 'Wait for the reset', 'Αναμονή για επαναφορά (Wait for Reset)'],
  ['Αυτόματη μετάβαση σε δωρεάν μοντέλο (Auto-Fallback)', 'Switch to the free model automatically (Auto-Fallback)', 'Αυτόματη μετάβαση σε Δωρεάν Μοντέλο (Auto-Fallback)'],
  ['Αναμονή:', 'Wait:'],
  ['Εάν εξαντληθεί το ημερήσιο όριο, η εργασία σταματά με ασφάλεια στο checkpoint και περιμένει τον ζωντανό χρονοδιακόπτη ή νέο API Key (διατηρεί 100% την ποιότητα Gemini).', 'If the daily limit runs out, the job stops safely at its checkpoint and waits for the live countdown or a new API key (keeps 100% Gemini quality).'],
  ['Εάν εξαντληθεί το όριο Gemini, η διαδικασία σταματά και περιμένει την επαναφορά για μέγιστη ποιότητα.', 'If the Gemini limit runs out, the process stops and waits for the reset, for maximum quality.'],
  ['Σημείωση:', 'Note:'],
  ['Επιλέξατε Αναμονή για Gemini αλλά δεν έχει εισαχθεί API Key. Συνιστάται η επιλογή Δωρεάν Μοντέλου παρακάτω.', 'You chose to wait for Gemini, but no API key is set. The free model option below is recommended.'],
  ['Επιλέξατε Αναμονή για Gemini αλλά δεν έχει εισαχθεί API Key. Συνιστάται η επιλογή Δωρεάν Μοντέλου παρακάτω ή εισαγωγή κλειδιού στις Ρυθμίσεις.', 'You chose to wait for Gemini, but no API key is set. Choose the free model below or add a key in Settings.'],
  ['Δωρεάν μοντέλα (προεπιλογή):', 'Free models (default):', 'Δωρεάν Μοντέλα (Προεπιλογή):'],
  ['Χωρίς Gemini API Key, η εκφώνηση εκτελείται αυτόματα με το δωρεάν μοντέλο Edge-TTS χωρίς διακοπή και χωρίς όρια.', 'Without a Gemini API key, narration runs with the free Edge-TTS model, without stopping and without limits.'],
  ['Χωρίς Gemini API Key, χρησιμοποιείται η δωρεάν μηχανή. Οι δωρεάν υπηρεσίες έχουν όρια και συχνά αρνούνται αιτήματα: τότε η εργασία σταματά με μήνυμα.', 'Without a Gemini API key, the free engine is used. Free services have limits and often refuse requests: the job then stops with a message.'],
  ['Εάν εξαντληθεί το όριο Gemini στο Script Polish, η εκφώνηση συνεχίζει άμεσα χωρίς διακοπή χρησιμοποιώντας το αρχικό κείμενο (δωρεάν Edge-TTS).', 'If the Gemini limit runs out during Script Polish, narration continues at once with the original text (free Edge-TTS).'],
  ['Εάν εξαντληθεί το όριο Gemini, η εργασία συνεχίζει άμεσα χωρίς διακοπή χρησιμοποιώντας τη δωρεάν μηχανή μετάφρασης (χωρίς όρια χρήσης).', 'If the Gemini limit runs out, the job continues at once with the free translation engine (no usage limits).'],
  ['Η δωρεάν μετάφραση δοκιμάζει την Google και μετά το MyMemory (μικρό ημερήσιο όριο). Η Google αρνείται συχνά: τότε χρειάζεται δωρεάν κλειδί Gemini, που χρησιμοποιείται αυτόματα. Μεγάλα έγγραφα (500+ σελίδες) μπορεί να χρειαστούν 10–60+ λεπτά. Η πρόοδος φαίνεται σε πραγματικό χρόνο.', 'Free translation tries Google, then MyMemory (a small daily limit). Google often refuses: a free Gemini key is then needed and used automatically. Large documents (500+ pages) may take 10–60+ minutes. Progress is shown in real time.'],
  ['🐢 Πολύ αργή διαδικασία.', '🐢 A very slow process.'],
  ['Υπολογίστε περίπου', 'Count on about'],
  ['3–8 δευτερόλεπτα ανά σελίδα', '3–8 seconds per page'],
  ['επιπλέον (π.χ. 15–40 λεπτά για βιβλίο 300 σελίδων).', 'extra (e.g. 15–40 minutes for a 300-page book).'],
  ['Για αυτό το έγγραφο (~{p} σελίδες) υπολογίστε περίπου', 'For this document (~{p} pages) count on about'],
  ['επιπλέον, πάνω από τον χρόνο της AI μετάφρασης.', 'extra, on top of the AI translation time.'],
  ['Κατά την εκτέλεση εμφανίζεται ο χρόνος που απομένει.', 'While it runs, the time left is shown.'],
  ['Επιπλέον κατανάλωση Gemini API:', 'Extra Gemini API use:'],
  ['το πρωτότυπο και η μετάφραση αποστέλλονται ξανά για αναθεώρηση.', 'the original and the translation are sent again for the revision.'],
  ['Η κατανάλωση tokens είναι περίπου', 'Token use is about'],
  ['1,5 φορά', '1.5 times'],
  ['αυτή της AI μετάφρασης.', 'that of the AI translation.'],
  ['Μετράει στο ημερήσιο όριο των κλειδιών σας. Χρησιμοποιούνται μόνο πλήρη μοντέλα Gemini· αν δεν είναι διαθέσιμα, κρατιέται η μετάφραση του 1ου περάσματος.', 'It counts against your keys\' daily limit. Only full Gemini models are used; if none is available, the first-pass translation is kept.'],
  ['Για αυτό το έγγραφο: περίπου', 'For this document: about'],
  ['{n} επιπλέον tokens', '{n} extra tokens'],
  ['Χρειάζονται περίπου {n} αιτήματα Gemini: με δωρεάν κλειδί το ημερήσιο όριο ενός μοντέλου μπορεί να είναι μόλις 20, οπότε η αναθεώρηση μπορεί να σταματήσει νωρίτερα (κρατιέται τότε η μετάφραση του 1ου περάσματος).', 'About {n} Gemini requests are needed: with a free key, a model\'s daily limit may be only 20, so the revision may stop early (the first-pass translation is then kept).'],
  ['❗ Δεν έχει οριστεί Gemini API Key — απαιτείται.', '❗ No Gemini API key is set — one is required.'],
  ['1 λεπτό', '1 minute'],
  ['{#n} λεπτά', '{#n} minutes'],
  ['1 ώρα', '1 hour'],
  ['{#n} ώρες', '{#n} hours'],
  ['{#n} ώρα', '{#n} hour'],
  ['{#h} ώρα {#m} λεπτά', '{#h} hour {#m} minutes'],
  ['{#h} ώρες {#m} λεπτά', '{#h} hours {#m} minutes'],
  ['{#h} ώρα 1 λεπτό', '{#h} hour 1 minute'],
  ['{#h} ώρες 1 λεπτό', '{#h} hours 1 minute'],
  ['{a} – {b}', '{a} – {b}'],
  ['🏆 Αναθεώρηση με το πρωτότυπο: διορθώθηκαν {#n} γραμμές. · {k}', '🏆 Revision against the original: {#n} lines corrected. · {k}'],
  ['🏆 Αναθεώρηση με το πρωτότυπο: διορθώθηκαν {#n} γραμμές.', '🏆 Revision against the original: {#n} lines corrected.'],
  ['🏆 Αναθεώρηση με το πρωτότυπο: δεν χρειάστηκαν διορθώσεις. · {k}', '🏆 Revision against the original: no corrections needed. · {k}'],
  ['🏆 Αναθεώρηση με το πρωτότυπο: δεν χρειάστηκαν διορθώσεις.', '🏆 Revision against the original: no corrections needed.'],
  ['{#n} σελίδες κράτησαν το 1ο πέρασμα (η αναθεώρησή τους δεν ήταν αξιόπιστη).', '{#n} pages kept the first pass (their revision was not reliable).'],
  ['🏆 Η αναθεώρηση παραλείφθηκε (όριο Gemini ή μη διαθέσιμο πλήρες μοντέλο) — κρατήθηκε η μετάφραση του 1ου περάσματος.', '🏆 The revision was skipped (Gemini limit or no full model available) — the first-pass translation was kept.'],
  ['🏆 Η αναθεώρηση δεν ολοκληρώθηκε — κρατήθηκε η μετάφραση του 1ου περάσματος.', '🏆 The revision did not complete — the first-pass translation was kept.'],
  ['🏆 Η αναθεώρηση απαιτεί AI Polish και Gemini API Key.', '🏆 The revision needs AI Polish and a Gemini API key.'],
  ['🏆 Η αναθεώρηση δεν εφαρμόζεται όταν διατηρείται η αρχική μορφοποίηση (DOCX→DOCX / EPUB→EPUB).', '🏆 The revision does not apply when the original formatting is kept (DOCX→DOCX / EPUB→EPUB).'],
  ['{n} αιτήματα · ~{t} tokens · {c}', '{n} requests · ~{t} tokens · {c}'],
  ['{n} αιτήματα · ~{t} tokens', '{n} requests · ~{t} tokens'],
  ['{n} από cache', '{n} from cache'],
  ['🔢 Gemini: {u}', '🔢 Gemini: {u}'],
  ['Σήμερα: {u}', 'Today: {u}'],

  // ── Start, progress, result ──
  ['🌐 Έναρξη μετάφρασης', '🌐 Start Translation'],
  ['✨ Μετάφραση βιβλίου με AI (1 κλικ)', '✨ Translate the book with AI (1-click)', '✨ Μετάφραση Βιβλίου με AI (1-Click)'],
  ['🎧 Δημιουργία audiobook με AI (1 κλικ)', '🎧 Create the audiobook with AI (1-click)', '🎧 Δημιουργία Audiobook με AI (1-Click)'],
  ['🎧 Δημιουργία audiobook', '🎧 Generate Audiobook'],
  ['✨ AI Polish (χωρίς μετάφραση)', '✨ AI Polish (no translation)', '✨ AI Polish (Χωρίς Μετάφραση)'],
  ['✏️ Ή ανοίξτε τον Editor για επικόλληση / απευθείας έλεγχο κειμένου', '✏️ Or open the Editor to paste / check text directly', '✏️ Ή ανοίξτε τον Editor για επικόλληση / απευθείας έλεγχο κειμένου (Paste / Write Directly)'],
  ['Πρόοδος μετάφρασης', 'Translation Progress'],
  ['Σε εξέλιξη', 'Running'],
  ['Σε εξέλιξη', 'In Progress'],
  ['Αδρανές', 'Idle'],
  ['Ολοκληρώθηκε', 'Complete'],
  ['Ολοκληρώθηκε', 'Completed'],
  ['Σφάλμα', 'Error'],
  ['Ακυρώθηκε', 'Cancelled'],
  ['Έτοιμο', 'Ready'],
  ['Έναρξη...', 'Starting...'],
  ['▶️ Συνέχιση μετάφρασης', '▶️ Resume translation', '▶️ Συνέχιση Μετάφρασης (Resume)', '▶️ Συνέχιση Μετάφρασης'],
  ['▶️ Συνέχιση μετάφρασης ΤΩΡΑ', '▶️ Resume translation NOW', '▶️ Συνέχιση Μετάφρασης ΤΩΡΑ'],
  ['🛑 Ακύρωση μετάφρασης', '🛑 Cancel Translation'],
  ['Η μετάφραση ολοκληρώθηκε!', 'Translation Complete!'],
  ['Το έγγραφό σας μεταφράστηκε με επιτυχία.', 'Your document has been translated successfully.'],
  ['Το έγγραφό σας μεταφράστηκε. Πατήστε παρακάτω για λήψη του αρχείου {f}.', 'Your document has been translated. Click below to download the {f} file.'],
  ['Το Graphic Novel / Comic μεταφράστηκε με επιτυχία! Η εικονογράφηση διατηρήθηκε 100% και τα μπαλόνια διαλόγου αποδόθηκαν στα {l}.', 'The graphic novel / comic was translated! The artwork is 100% intact and the speech balloons are in {l}.'],
  ['Αγγλικά', 'English'],
  ['Ελληνικά', 'Greek'],
  ['Το ημερήσιο όριο του Gemini API εξαντλήθηκε κατά τη μετάφραση. Το έγγραφο ολοκληρώθηκε με τη βασική μηχανή μετάφρασης.', 'The Gemini API daily limit ran out during the translation. The document was finished with the basic translation engine.'],
  ['BookApp — Η μετάφραση ολοκληρώθηκε!', 'BookApp — Translation complete!', 'BookApp — Μετάφραση Ολοκληρώθηκε!'],
  ['Το βιβλίο σας μεταφράστηκε με επιτυχία και είναι έτοιμο για λήψη ή ανάγνωση.', 'Your book was translated and is ready to download or read.'],
  ['✅ Η μετάφραση ολοκληρώθηκε!', '✅ Translation complete!'],
  ['🎉 Το audiobook είναι έτοιμο!', '🎉 Audiobook ready!'],
  ['Παρουσιάστηκε άγνωστο σφάλμα.', 'An unknown error occurred.'],
  ['Η διαδικασία ακυρώθηκε.', 'Process was cancelled.'],
  ['Η μετάφραση ακυρώθηκε.', 'Translation cancelled.'],
  ['Η δημιουργία audiobook ακυρώθηκε.', 'Audiobook generation cancelled.'],
  ['Αποτυχία ακύρωσης εργασίας', 'Failed to cancel job'],
  ['Σφάλμα ακύρωσης: {r}', 'Cancellation error: {r}'],
  ['Αποτυχία έναρξης μετάφρασης', 'Failed to start translation'],
  ['Αποτυχία έναρξης δημιουργίας audiobook', 'Failed to start audiobook generation'],
  ['Χάθηκε η σύνδεση με την κατάσταση της εργασίας', 'Lost connection to job status'],
  ['Χάθηκε η σύνδεση με τον διακομιστή κατά την παρακολούθηση της προόδου.', 'Connection to server lost while tracking progress.'],
  ['Μεταφράστηκαν {d} από {t} {u}', 'Translated {d} of {t} {u}s'],
  ['Ολοκληρώθηκαν {d} από {t} παρτίδες AI ({dp} / {tp} σελίδες)', 'Completed {d} of {t} AI batches ({dp} / {tp} pages)'],
  ['Ολοκληρώθηκαν {d} από {t} παρτίδες AI ({tp} σελίδες συνολικά)', 'Completed {d} of {t} AI batches ({tp} pages total)'],
  ['Ολοκληρώθηκαν {d} από {t} παρτίδες AI (~4–5 σελίδες η καθεμία)', 'Completed {d} of {t} AI batches (~4–5 pages each)'],
  ['Μεταφράστηκαν {d} από {t} σελίδες', 'Translated {d} of {t} pages'],
  ['Δημιουργήθηκε το τμήμα ήχου {d} από {t}', 'Generated audio part {d} of {t}'],
  ['⏳ Απομένουν:', '⏳ Time left:'],
  ['{n} σελ/λ', '{n} pages/min'],
  ['{n} τμήματα/δ', '{n} parts/s'],
  ['⚡ Δωρεάν μηχανή', '⚡ Free Engine'],
  ['⚡ Δωρεάν μετάφραση', '⚡ Free Translation'],
  ['⬇️ Λήψη', '⬇️ Download'],
  ['Αρχείο', 'File'],
  ['Κατέβασμα ως PDF', 'Download as PDF'],
  ['Κατέβασμα ως Word DOCX', 'Download as Word DOCX'],
  ['Κατέβασμα ως ηλεκτρονικό βιβλίο EPUB', 'Download as EPUB e-book', 'Κατέβασμα ως EPUB e-book'],
  ['Κατέβασμα ως απλό κείμενο', 'Download as plain text', 'Κατέβασμα ως Plain Text'],
  ['📋 Αντιγραφή κειμένου', '📋 Copy text', '📋 Αντιγραφή Κειμένου'],
  ['📖 Ανάγνωση τώρα', '📖 Read now', '📖 Διαβάστε Τώρα (Reader)'],
  ['✏️ Έλεγχος & διόρθωση', '✏️ Review & Edit', '✏️ Review & Edit (Έλεγχος)'],
  ['Γλώσσα audiobook', 'Audiobook language'],
  ['Επιλέξτε γλώσσα audiobook', 'Choose audiobook language'],
  ['🎧 Μετατροπή σε audiobook', '🎧 Convert to Audiobook'],
  ['⏳ Αντιγραφή...', '⏳ Copying...'],
  ['✅ Αντιγράφηκε!', '✅ Copied!'],
  ['📋 Το μεταφρασμένο κείμενο αντιγράφηκε στο πρόχειρο!', '📋 The translated text was copied to the clipboard!'],
  ['Δεν υπάρχει μεταφρασμένο έγγραφο.', 'There is no translated document.'],
  ['Δεν βρέθηκε κείμενο προς αντιγραφή.', 'No text found to copy.'],
  ['Αποτυχία αντιγραφής: {r}', 'Copy failed: {r}'],
  ['⏳ Περιμένετε να ολοκληρωθεί η μετάφραση πριν τη λήψη.', '⏳ Please wait until this translation is completed before downloading.'],
  ['⏳ Περιμένετε να ολοκληρωθεί η δημιουργία του audiobook πριν τη λήψη.', '⏳ Please wait until this audiobook generation is completed before downloading.'],
  ['Παρακαλώ ανεβάστε πρώτα ένα έγγραφο.', 'Please upload a document first.'],
  ['Παρακαλώ επιλέξτε πρώτα φωνή.', 'Please select a voice first.'],
  ['Συνέχιση μετάφρασης από το αποθηκευμένο σημείο (checkpoint)...', 'Resuming the translation from the saved checkpoint...'],
  ['Συνέχιση audiobook από το αποθηκευμένο σημείο (checkpoint)...', 'Resuming the audiobook from the saved checkpoint...', 'Συνέχιση Audiobook από το αποθηκευμένο σημείο (checkpoint)...'],
  ['▶️ Συνέχιση εργασίας από το αποθηκευμένο checkpoint...', '▶️ Resuming the job from the saved checkpoint...'],
  ['Η εργασία δεν μπόρεσε να φορτωθεί για συνέχιση.', 'The job could not be loaded to resume.'],
  ['📄 Φορτώθηκε "{f}" — έτοιμο για μετάφραση/συνέχιση!', '📄 Loaded "{f}" — ready to translate/resume!'],

  // ── Editor ──
  ['Έλεγχος & διόρθωση μετάφρασης', 'Review & edit translation', 'Review & Edit Translation (Έλεγχος & Διόρθωση)'],
  ['🔍 Εύρεση & αντικατάσταση', '🔍 Find & Replace'],
  ['💾 Αποθήκευση & ενημέρωση αρχείων', '💾 Save & Update Files'],
  ['Κλείσιμο Editor', 'Close Editor'],
  ['Εύρεση κειμένου...', 'Find text...'],
  ['Αντικατάσταση με...', 'Replace with...'],
  ['Αντικατάσταση', 'Replace'],
  ['Αντικατάσταση όλων', 'Replace All'],
  ['Διπλή προβολή (πρωτότυπο ↔ μετάφραση)', 'Split View (Original ↔ Translation)'],
  ['Πλήρης editor', 'Full Editor'],
  ['● Μη αποθηκευμένο', '● Unsaved'],
  ['{w} λέξεις · {c} χαρακτήρες', '{w} words · {c} characters'],
  ['Κείμενο πρωτοτύπου (μόνο ανάγνωση)', 'Original Document Text (Read-Only)'],
  ['Το πρωτότυπο κείμενο θα εμφανιστεί εδώ...', 'Original text will appear here...'],
  ['Επεξεργασία μετάφρασης', 'Editable translated text', 'Editable Translated Text (Επεξεργασία Μετάφρασης)'],
  ['Η μετάφραση θα εμφανιστεί εδώ...', 'Translated text will appear here...'],
  ['Δεν υπάρχει μεταφρασμένο έγγραφο για επεξεργασία.', 'No translated document to edit.'],
  ['Αποτυχία φόρτωσης κειμένου για τον editor: {r}', 'Failed to load text for editor: {r}'],
  ['Γράψτε το κείμενο που θέλετε να βρείτε.', 'Please enter text to find.'],
  ['Αντικαταστάθηκαν {n} εμφανίσεις.', 'Replaced {n} occurrences.'],
  ['Αντικαταστάθηκε η πρώτη εμφάνιση.', 'Replaced first occurrence.'],
  ['Το κείμενο δεν βρέθηκε.', 'Text not found.'],
  ['Τρέξτε το AI Polish ή ανεβάστε πρώτα ένα έγγραφο για να δημιουργηθεί εργασία προς αποθήκευση.', 'Run AI Polish or upload a document first to create a saveable job.'],
  ['💾 Αποθηκεύτηκε μόνο το κείμενο: στα Graphic Novels οι εικόνες και τα μπαλόνια δεν αλλάζουν από τον Editor.', '💾 Only the text was saved: in graphic novels the editor does not change the artwork and balloons.'],
  ['✅ Οι διορθώσεις αποθηκεύτηκαν και τα αρχεία ενημερώθηκαν!', '✅ Corrections saved and export files updated!'],
  ['Σφάλμα αποθήκευσης: {r}', 'Save error: {r}'],
  ['Σφάλμα:', 'Error:'],
  ['Σφάλμα: {r}', 'Error: {r}'],

  // ── Audiobook tab ──
  ['Ανέβασμα εγγράφου', 'Upload Document'],
  ['Ανεβάστε έγγραφο για δημιουργία audiobook', 'Upload document for audiobook generation'],
  ['Αφήστε εδώ το έγγραφό σας', 'Drop your document here'],
  ['ή κάντε κλικ για επιλογή αρχείου', 'or click to browse your files'],
  ['Ρυθμίσεις audiobook', 'Audiobook Settings'],
  ['Απλή λειτουργία (audiobook με AI σε 1 κλικ)', 'Basic mode (1-click AI audiobook)', 'Απλή Λειτουργία (1-Click AI Audiobook)'],
  ['Προεπιλεγμένη φωνή:', 'Default voice:', 'Προεπιλεγμένη Φωνή:'],
  ['🇬🇷 Ελληνική φυσική φωνή', '🇬🇷 Natural Greek voice', '🇬🇷 Ελληνική Φυσική Φωνή'],
  ['σε ιδανική λογοτεχνική ροή.', 'in an ideal literary flow.'],
  ['Ενεργό AI Audio Polish:', 'AI Audio Polish on:'],
  ['Αυτόματη βελτιστοποίηση κειμένου για ακρόαση και καθαρές φυσικές παύσεις.', 'The text is tuned for listening, with clear natural pauses.'],
  ['Παραγωγή με 1 κλικ:', '1-click production:', '1-Click Παραγωγή:'],
  ['Απλά ανεβάστε το αρχείο σας και πατήστε το κουμπί για άμεση δημιουργία MP3!', 'Just upload your file and press the button to create the MP3 at once!'],
  ['Γλώσσα ήχου', 'Audio Language'],
  ['Επιλογή φωνής', 'Select Voice'],
  ['🗣️ Προαιρετική φράση για δοκιμή φωνής (π.χ. απόσπασμα βιβλίου)...', '🗣️ Optional phrase to test the voice (e.g. a passage from the book)...'],
  ['Ακρόαση της επιλεγμένης φωνής με αυτό το κείμενο', 'Hear the selected voice read this text'],
  ['🔊 Δοκιμή φωνής', '🔊 Test voice', '🔊 Δοκιμή Φωνής'],
  ['Διακοπή της ακρόασης', 'Stop listening'],
  ['⏹️ Διακοπή', '⏹️ Stop'],
  ['🔊 Παραγωγή δείγματος για {v}...', '🔊 Creating a sample for {v}...'],
  ['Ακρόαση δείγματος', 'Play a sample'],
  ['🔊 Ακρόαση', '🔊 Listen'],
  ['Νέστορας (Nestoras Neural)', 'Nestoras (Neural)'],
  ['Ύφος & ρυθμός εκφώνησης', 'Narration style & pacing', 'Narration Style & Pacing / Ύφος & Ταχύτητα Εκφώνησης'],
  ['📖 Λογοτεχνία / ροή βιβλίου (-12% ταχύτητα, φυσικές παύσεις)', '📖 Literature / Book Flow (-12% speed, natural pauses)'],
  ['🪶 Ποίηση & απαγγελία (-20% ταχύτητα, ρυθμός στίχου & ήρεμος τόνος)', '🪶 Poetry & Recitation (-20% speed, verse cadence & calm pacing)'],
  ['🐢 Ήρεμη & εκφραστική (-18% ταχύτητα, χαλαρές παύσεις)', '🐢 Calm & Expressive (-18% speed, relaxed pauses)'],
  ['🎙️ Φυσική συνομιλία (+0% ταχύτητα, 1.0x κανονική)', '🎙️ Natural Conversational (+0% speed, 1.0x standard)'],
  ['⚡ Γρήγορη / μη μυθοπλασία (+15% ταχύτητα, 1.15x μελέτη)', '⚡ Brisk / Non-Fiction (+15% speed, 1.15x study)'],
  ['Ακριβής ρύθμιση ταχύτητας:', 'Fine-tune speed:', 'Fine-Tune Speed / Ακριβής Ρύθμιση Ταχύτητας:'],
  ['-30% (πολύ αργά)', '-30% (Very Slow)'],
  ['0% (1.0x κανονικά)', '0% (1.0x Normal)'],
  ['+30% (γρήγορα)', '+30% (Fast)'],
  ['Τονικό ύψος & χροιά:', 'Voice pitch & prosody:', 'Voice Pitch & Prosody / Τονικό Ύψος & Χροιά:'],
  ['{hz} (φυσική)', '{hz} (natural)', '{hz} (Natural / Φυσική)', '{hz} (Natural)'],
  ['{hz} (επιβλητική)', '{hz} (very deep)', '{hz} (Very Deep / Επιβλητική)'],
  ['{hz} (θεατρική)', '{hz} (deep & theatrical)', '{hz} (Deep & Theatrical / Θεατρική)', '{hz} (Deep Baritone)'],
  ['{hz} (ζεστή)', '{hz} (warm)', '{hz} (Warm / Ζεστή)'],
  ['{hz} (καθαρή)', '{hz} (clear)', '{hz} (Clear / Καθαρή)'],
  ['{hz} (λυρική)', '{hz} (bright & lyrical)', '{hz} (Bright & Lyrical / Λυρική)', '{hz} (Bright)'],
  ['✨ AI Polish για εκφώνηση (Gemini — αναπτύσσει συντομογραφίες & βελτιώνει τη ροή)', '✨ AI Polish for Spoken Audio (Gemini — expands abbreviations & improves narration flow)'],
  ['Πολυφωνική αφήγηση', 'Multi-voice dramatization', 'Multi-Voice Dramatization (Πολυφωνική Αφήγηση)'],
  [': Ξεχωριστή φωνή για διαλόγους', ': a separate voice for dialogue'],
  ['Δεύτερη φωνή για διαλόγους:', 'Dialogue voice:', 'Δευτερεύουσα Φωνή Διαλόγων (Dialogue Voice):'],
  ['Χρήση του κειμένου που μεταφράστηκε ήδη (αν υπάρχει από την καρτέλα Μετάφραση)', 'Use previously translated text (if available from Translate tab)'],
  ['Χρήση του κειμένου που μεταφράστηκε ήδη', 'Use previously translated text'],
  ['Χρήση της μετάφρασης ({t}) — ξετσεκάρετε για εκφώνηση του πρωτοτύπου ({s})', 'Use translated text ({t}) — uncheck to narrate original ({s})'],
  ['Έτοιμο για δημιουργία audiobook στα {l} από {s}!', 'Ready to create {l} audiobook from {s}!'],
  ['τη μετάφραση', 'translated text'],
  ['το πρωτότυπο', 'original document'],
  ['⚡ Όταν εξαντληθεί το όριο Gemini στο Script Polish', '⚡ When the Gemini limit runs out in Script Polish', '⚡ Σε εξάντληση ορίου Gemini Script Polish (On Quota Limit)'],
  ['Το audiobook χρησιμοποιεί τις νευρωνικές φωνές του Microsoft Edge — υψηλή ποιότητα, δωρεάν, χρειάζεται internet. Το αποτέλεσμα είναι ένα αρχείο MP3. Πολύ μεγάλα έγγραφα μπορεί να χρειαστούν πολύ χρόνο.', 'Audiobook uses Microsoft Edge neural voices — high-quality, free, requires internet. Output is a single MP3 file. Very large documents may take a long time to process.'],
  ['Πρόοδος δημιουργίας audiobook', 'Audiobook Generation Progress'],
  ['Προετοιμασία εγγράφου...', 'Preparing document...'],
  ['▶️ Συνέχιση audiobook', '▶️ Resume audiobook', '▶️ Συνέχιση Audiobook (Resume)', '▶️ Συνέχιση Audiobook'],
  ['🛑 Ακύρωση audiobook', '🛑 Cancel Audiobook'],
  ['Το audiobook είναι έτοιμο!', 'Audiobook Ready!'],
  ['Το audiobook δημιουργήθηκε με επιτυχία.', 'Your audiobook has been generated successfully.'],
  ['Το audiobook σας δημιουργήθηκε. Πατήστε παρακάτω για λήψη ή ακρόαση του MP3.', 'Your audiobook has been generated. Click below to download or listen to the MP3 file.'],
  ['BookApp — Το audiobook είναι έτοιμο!', 'BookApp — Audiobook ready!', 'BookApp — Audiobook Έτοιμο!'],
  ['Το ηχητικό βιβλίο ολοκληρώθηκε με επιτυχία και είναι έτοιμο για ακρόαση.', 'The audiobook is finished and ready to listen to.'],
  ['Νευρωνική φωνή · MP3 υψηλής πιστότητας', 'Neural Voice · MP3 High Fidelity'],
  ['Νευρωνική φωνή', 'Neural Voice'],
  ['{v} · MP3 υψηλής πιστότητας', '{v} · MP3 High Fidelity'],
  ['Κεφάλαιο:', 'Chapter:'],
  ['Πλήρες audiobook', 'Full audiobook', 'Πλήρες Audiobook'],
  ['Πίσω 15 δευτερόλεπτα', 'Back 15 seconds'],
  ['Εμπρός 15 δευτερόλεπτα', 'Forward 15 seconds'],
  ['Ταχύτητα:', 'Speed:'],
  ['⬇️ Λήψη audiobook MP3', '⬇️ Download MP3 Audiobook'],
  ['📦 Λήψη M4B (audiobook)', '📦 Download M4B (Audiobook)'],
  ['Η εξαγωγή M4B χρειάζεται το FFmpeg στον υπολογιστή του BookApp (pip install -r requirements.txt). Το MP3 είναι διαθέσιμο.', 'M4B export needs FFmpeg on the BookApp computer (pip install -r requirements.txt). The MP3 is available.'],

  // ── Book Insights ──
  ['Βιβλίο / Έγγραφο', 'Book / Document'],
  ['Ανεβάστε έγγραφο για τα Book Insights', 'Upload a document for Book Insights'],
  ['Ρίξτε εδώ το βιβλίο σας', 'Drop your book here'],
  ['📎 Χρήση του εγγράφου που ήδη ανεβάσατε', '📎 Use the document you already uploaded'],
  ['📎 Χρήση του «{f}»', '📎 Use «{f}»'],
  ['Ανάλυση…', 'Analysing…'],
  ['Αφαίρεση εγγράφου', 'Remove document'],
  ['⚠️ Για τα Book Insights απαιτείται κλειδί Google Gemini API (δωρεάν).', '⚠️ Book Insights needs a Google Gemini API key (free).'],
  ['🔑 Προσθήκη κλειδιού', '🔑 Add a key'],
  ['Το αποτέλεσμα γράφεται αυτόματα στη γλώσσα του βιβλίου.', 'The result is written in the book\'s language automatically.'],
  ['📝 Περίληψη (1 κλικ)', '📝 1-Click Summary'],
  ['Σύντομη περίληψη', 'Short summary'],
  ['📚 Σύνοψη (1 κλικ)', '📚 1-Click Synopsis'],
  ['Πλήρης σύνοψη', 'Full synopsis'],
  ['Insights — Προχωρημένες ρυθμίσεις', 'Insights — Advanced settings', 'Insights — Προχωρημένες Ρυθμίσεις'],
  ['📝 Περίληψη', '📝 Summary', '📝 Περίληψη (Summary)'],
  ['Τύπος', 'Type'],
  ['Μίας πρότασης (20–40 λέξεις)', 'One sentence (20–40 words)'],
  ['Σύντομη (150–300 λέξεις)', 'Short (150–300 words)'],
  ['Εκτενής (500–1.000 λέξεις)', 'Long (500–1,000 words)'],
  ['Γλώσσα εξόδου', 'Output language'],
  ['Γλώσσα εγγράφου', 'Document language'],
  ['Εμφάνιση στην οθόνη', 'Show on screen'],
  ['📝 Δημιουργία περίληψης', '📝 Create summary'],
  ['📚 Σύνοψη', '📚 Synopsis', '📚 Σύνοψη (Synopsis)'],
  ['Τυπική (800–1.200 λέξεις)', 'Standard (800–1,200 words)'],
  ['Εκτενής (1.500–2.500 λέξεις)', 'Long (1,500–2,500 words)'],
  ['📚 Δημιουργία σύνοψης', '📚 Create synopsis'],
  ['Τα όρια λέξεων είναι οδηγίες· σε μικρά κείμενα το μήκος προσαρμόζεται ώστε να μην προστίθενται πληροφορίες που δεν υπάρχουν στο βιβλίο.', 'Word limits are guides: on short texts the length adapts, so nothing the book does not contain is added.'],
  ['Έναρξη…', 'Starting…'],
  ['Αποτέλεσμα', 'Result'],
  ['📋 Αντιγραφή', '📋 Copy'],
  ['🎧 Δημιουργία ήχου', '🎧 Create audio'],
  ['⬇️ Λήψη MP3', '⬇️ Download MP3'],
  ['Μεταφόρτωση…', 'Uploading…'],
  ['Η μεταφόρτωση απέτυχε', 'The upload failed'],
  ['Φόρτωση από το Ιστορικό…', 'Loading from Session History…'],
  ['📄 Φορτώθηκε «{f}» στο Book Insights.', '📄 «{f}» loaded into Book Insights.'],
  ['Ανάλυση κειμένου…', 'Analysing the text…'],
  ['Η ανάλυση του εγγράφου απέτυχε', 'The document could not be analysed'],
  ['~{w} λέξεις · ~{p} σελίδες · {l}', '~{w} words · ~{p} pages · {l}'],
  ['άγνωστη γλώσσα', 'unknown language'],
  ['Το έγγραφο δεν περιέχει αρκετό κείμενο.', 'The document does not contain enough text.'],
  ['Δεν εντοπίστηκε η γλώσσα του εγγράφου. Στην Προχωρημένη Λειτουργία μπορείτε να επιλέξετε γλώσσα εξόδου.', 'The document\'s language was not detected. In Advanced Mode you can choose the output language.'],
  ['Σφάλμα ανάλυσης', 'Analysis error'],
  ['Χάθηκε η παρακολούθηση της εργασίας', 'Lost track of the job'],
  ['Η δημιουργία απέτυχε.', 'The creation failed.'],
  ['Μια δημιουργία εκτελείται ήδη — περιμένετε να ολοκληρωθεί.', 'A creation is already running — wait for it to finish.'],
  ['Περιμένετε να ολοκληρωθεί η τρέχουσα δημιουργία.', 'Wait for the current creation to finish.'],
  ['Ανεβάστε πρώτα ένα βιβλίο ή έγγραφο.', 'Upload a book or document first.'],
  ['Η δημιουργία δεν ξεκίνησε', 'The creation did not start'],
  ['Η ίδια δημιουργία εκτελείται ήδη — εμφανίζεται η πρόοδός της.', 'The same creation is already running — its progress is shown.'],
  ['✅ Ολοκληρώθηκε!', '✅ Done!'],
  ['Δεν επιστράφηκε έγκυρο αποτέλεσμα. Δοκιμάστε ξανά.', 'No valid result came back. Try again.'],
  ['📋 Αντιγράφηκε.', '📋 Copied.'],
  ['Η αντιγραφή δεν επιτρέπεται από τον browser.', 'The browser does not allow copying.'],
  ['Η εξαγωγή αρχείου απέτυχε', 'The file export failed'],
  ['Προετοιμασία εκφώνησης…', 'Preparing the narration…'],
  ['Η δημιουργία ήχου δεν ξεκίνησε', 'The audio creation did not start'],
  ['Η δημιουργία ήχου απέτυχε.', 'The audio creation failed.'],
  ['🎧 Ο ήχος είναι έτοιμος.', '🎧 The audio is ready.'],
  ['Ο τύπος αρχείου «{e}» δεν υποστηρίζεται για Book Insights. Χρησιμοποιήστε PDF, DOCX ή EPUB.', 'The file type «{e}» is not supported for Book Insights. Use PDF, DOCX or EPUB.'],
  ['Δεν υπάρχει σύνδεση με τον διακομιστή. Ελέγξτε ότι η εφαρμογή εκτελείται και τη σύνδεσή σας στο διαδίκτυο.', 'No connection to the server. Check that the app is running and your internet connection.'],
  ['Παρουσιάστηκε απρόσμενο σφάλμα.', 'An unexpected error occurred.'],

  // ── Session history, footer ──
  ['🕑 Ιστορικό εργασιών', '🕑 Session History'],
  ['Ποιανού τις εργασίες βλέπετε', 'Whose jobs you see'],
  ['Οι εργασίες μου', 'My jobs'],
  ['Όλοι οι χρήστες', 'All users'],
  ['🗑️ Διαγραφή όλων', '🗑️ Clear All'],
  ['Δεν υπάρχουν εργασίες ακόμη. Ανεβάστε ένα έγγραφο για να ξεκινήσετε.', 'No jobs yet. Upload a document to get started.'],
  ['Διαγραφή αυτής της εργασίας', 'Delete this job'],
  ['Η εργασία αφαιρέθηκε από το ιστορικό.', 'Job removed from history.'],
  ['Αποτυχία διαγραφής εργασίας', 'Failed to delete job'],
  ['Αποτυχία διαγραφής εργασίας.', 'Failed to delete job.'],
  ['Διαγραφή ΟΛΩΝ των εργασιών ΟΛΩΝ των χρηστών και των προσωρινών αρχείων;', 'Delete ALL jobs of ALL users and the temporary files?', 'Διαγραφή ΟΛΩΝ των εργασιών ΟΛΩΝ των χρηστών και των προσωρινών αρχείων; (Are you sure?)'],
  ['Να διαγραφεί όλο το ιστορικό εργασιών και τα προσωρινά αρχεία;', 'Are you sure you want to delete all session history and temporary files?'],
  ['Όλο το ιστορικό διαγράφηκε.', 'All session history deleted.'],
  ['Αποτυχία διαγραφής ιστορικού', 'Failed to clear history'],
  ['Αποτυχία διαγραφής ιστορικού.', 'Failed to clear history.'],
  ['Η εργασία δεν βρέθηκε', 'Job not found'],
  ['Δημιουργία:', 'Created by'],

  // ── AI Polish window ──
  ['✨ Επιμέλεια & διόρθωση μετάφρασης με AI', '✨ AI Translation Polish & Proofreading'],
  ['Βελτιώστε την ελληνική μετάφραση σε άψογη, φυσική γλώσσα με το Google Gemini. Επιλέξτε ύφος:', 'Refine the Greek translation into flawless, natural language using Google Gemini AI. Select your preferred style:'],
  ['Ύφος κειμένου', 'Stylistic tone', 'Stylistic Tone / Ύφος Κειμένου'],
  ['📚 Λογοτεχνικό / μυθιστόρημα', '📚 Literature, fiction & sci-fi', '📚 Λογοτεχνικό / Μυθιστόρημα (Literature, Fiction & Sci-Fi)'],
  ['📖 Φυσική ροή & άνετος λόγος', '📖 Natural & fluent Greek', '📖 Φυσική Ροή & Άνετος Λόγος (Natural & Fluent Greek)'],
  ['🏛️ Επίσημο & υπηρεσιακό', '🏛️ Official administrative / public sector', '🏛️ Επίσημο & Υπηρεσιακό (Official Administrative / Public Sector)'],
  ['💻 Τεχνικό & ακριβές', '💻 Technical documentation / IT', '💻 Τεχνικό & Ακριβές (Technical Documentation / IT)'],
  ['🎧 Κείμενο εκφώνησης audiobook (προφορική ροή & ανεπτυγμένες συντομογραφίες)', '🎧 Audiobook Narration Script (Spoken Flow & Expanded Abbreviations)'],
  ['🎯 Δίγλωσση σύγκριση με το πρωτότυπο', '🎯 Source-anchored verification', '🎯 Source-Anchored Verification (Δίγλωσση σύγκριση με πρωτότυπο)'],
  ['Συγκρίνει τη μετάφραση με το πρωτότυπο κείμενο για διόρθωση παρερμηνειών, αγγλισμών και διατήρηση context.', 'Compares the translation with the original text to correct misreadings and anglicisms and to keep the context.'],
  ['Το AI αναλύει και επιμελείται το κείμενο...', 'AI is analyzing and polishing the text...'],
  ['⚡ Gemini Flash AI υψηλής ταχύτητας', '⚡ High-Speed Gemini Flash AI'],
  ['Προετοιμασία...', 'Preparing...'],
  ['Ακύρωση', 'Cancel'],
  ['✨ Επιμέλεια μετάφρασης', '✨ Polish Translation'],
  ['Ελαχιστοποίηση (εκτέλεση στο παρασκήνιο)', 'Minimize (Run in Background)'],
  ['Μετάφραση εγγράφου · ✨ AI Polish', 'Translate Document · ✨ AI Polish'],
  ['Μετάφραση εγγράφου · ✨ {p}%', 'Translate Document · ✨ {p}%'],
  ['Εκκίνηση της μηχανής Flash AI...', 'Initializing Flash AI engine...'],
  ['Επιμέλεια κειμένου...', 'Refining text...'],
  ['Τμήμα {c} από {t}', 'Part {c} of {t}'],
  ['Ολοκληρώθηκε!', 'Completed!'],
  ['✨ Το AI Polish ολοκληρώθηκε! Το κείμενο βελτιώθηκε.', '✨ AI Polish complete! Text has been refined.'],
  ['Το έγγραφό σας επιμελήθηκε με το Gemini AI. Πατήστε παρακάτω για λήψη του αρχείου.', 'Your document has been polished with Gemini AI. Click below to download the file.'],
  ['Το AI Polish απέτυχε', 'AI Polishing failed'],
  ['Σφάλμα AI: {r}', 'AI Error: {r}'],
  ['Ανεβάστε πρώτα ένα έγγραφο ή επικολλήστε κείμενο στον Editor.', 'Please upload a document or paste text in Editor first.'],
  ['Επικολλήστε ή πληκτρολογήστε εδώ το ελληνικό κείμενο που θέλετε να επιμεληθείτε (AI Polish)...', 'Paste or type here the Greek text you want to polish (AI Polish)...'],
  ['ℹ️ Δεν έχει οριστεί Gemini API Key: χρήση των δωρεάν μοντέλων (τυπογραφία & γλωσσάρι).', 'ℹ️ No Gemini API key is set: the free models are used (typography & glossary).', 'ℹ️ Δεν έχει οριστεί Gemini API Key: Χρήση των δωρεάν μοντέλων (τυπογραφία & γλωσσάρι).'],
  ['Μη έγκυρο κλειδί API. Τα κλειδιά Google Gemini ξεκινούν με "AQ." ή "AIzaSy...". Επικολλήστε ένα έγκυρο κλειδί.', 'Invalid API Key format. Google Gemini keys start with "AQ." or "AIzaSy...". Please paste a valid key.'],

  // ── Gemini keys window ──
  ['🔑 Gemini Multi-Key Pool (έως 8 δωρεάν κλειδιά)', '🔑 Gemini Multi-Key Pool (up to 8 free keys)', '🔑 Gemini Multi-Key Pool (Έως 8 Δωρεάν Κλειδιά)'],
  ['➕ Κλειδιά 5–8', '➕ Keys 5–8'],
  ['🔑 Gemini Multi-Key Pool & ρυθμίσεις API', '🔑 Gemini Multi-Key Pool & API settings', '🔑 Gemini Multi-Key Pool & Ρυθμίσεις API'],
  ['Διαχειριστείτε τα δωρεάν κλειδιά Google Gemini API (έως 8) για αυτόματη εναλλαγή (auto-failover) και αδιάλειπτη ροή χωρίς διακοπές:', 'Manage the free Google Gemini API keys (up to 8) for automatic switching (auto-failover) and uninterrupted work:', 'Διαχειριστείτε τα δωρεάν Google Gemini API Keys (έως 8 κλειδιά) για αυτόματη εναλλαγή (auto-failover) και αδιάλειπτη ροή χωρίς διακοπές:'],
  ['Εμφάνιση / απόκρυψη κλειδιών', 'Show / hide keys', 'Show / Hide Keys'],
  ['Εμφάνιση', 'Show'],
  ['Απόκρυψη', 'Hide'],
  ['Δωρεάν κλειδί ↗', 'Get Free Key ↗'],
  ['Θέση 1 (βασικό κλειδί)', 'Slot 1 (primary API key)', 'Slot 1 (Βασικό / Primary API Key)'],
  ['Θέση {#n} (εφεδρικό κλειδί #{#b})', 'Slot {#n} (backup key #{#b})', 'Slot {#n} (Εφεδρικό Key #{#b} — Backup)'],
  ['⚪ Κενό', '⚪ Empty'],
  ['AIzaSy... (λογαριασμός Google #{n})', 'AIzaSy... (Google Account #{n})'],
  ['Pool: {n} κλειδιά', 'Pool: {n} keys'],
  ['Pool: 0 κλειδιά (δωρεάν fallback)', 'Pool: 0 keys (free fallback)', 'Pool: 0 κλειδιά (Δωρεάν fallback)'],
  ['✓ Αποθηκεύτηκαν', '✓ Saved'],
  ['💾 Αποθήκευση Pool', '💾 Save pool'],
  ['✓ Έτοιμο / Κλείσιμο', '✓ Done / Close'],
  ['⏳ Όριο ({t})', '⏳ Limit ({t})'],
  ['🟢 Ενεργό', '🟢 Active', '🟢 Ενεργό (Active)'],
  ['🟡 Εφεδρικό', '🟡 Standby', '🟡 Εφεδρικό (Standby)'],
  ['Ενεργό', 'Active'],
  ['Εφεδρικό', 'Standby'],
  ['σε αναμονή', 'waiting'],
  ['🟡 {s} · {#n} μοντέλα στο όριο', '🟡 {s} · {#n} models at their limit'],
  ['⏳ Αναμονή για ανανέωση του ορίου Gemini', '⏳ Waiting for the Gemini limit to renew'],
  ['ℹ️ Μοντέλα Gemini στο όριό τους', 'ℹ️ Gemini models at their limit'],
  ['Εξαντλήθηκε το ημερήσιο όριο σε όλα τα κλειδιά. Έτοιμο ξανά στις {c} (σε {t}).', 'The daily limit is used up on every key. Ready again at {c} (in {t}).'],
  ['{m}: όριο ημέρας σε {#k} από {#n} κλειδιά — ξανά στις {c} (σε {t}).', '{m}: daily limit reached on {#k} of {#n} keys — available again at {c} (in {t}).'],
  ['Περιμένουν την ανανέωση: {list}.', 'Waiting for the renewal: {list}.'],
  ['Ένα κλειδί από άλλον λογαριασμό Google συνεχίζει αμέσως την εργασία.', 'A key from another Google account continues the work at once.'],
  ['Η εφαρμογή συνεχίζει με τα άλλα μοντέλα και κλειδιά όσο υπάρχει διαθέσιμο όριο.', 'The app continues with the other models and keys as long as some allowance is left.'],
  ['Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). Έτοιμο ξανά στις {c} (απομένουν ~{t}). Μπορείτε να αλλάξετε API Key στις Ρυθμίσεις (Settings) για άμεση συνέχιση.', 'The Gemini API daily limit (free tier) is used up. Ready again at {c} (~{t} left). You can change the API key in Settings to continue at once.'],
  ['{#h}ώ {#m}λ {#s}δ', '{#h}h {#m}m {#s}s'],
  ['{#h}ώ {#m}λ', '{#h}h {#m}m'],
  ['{#m}λ {#s}δ', '{#m}m {#s}s'],
  ['{#s}δ', '{#s}s'],
  ['⚠️ Όλα τα {n} κλειδιά εξαντλήθηκαν', '⚠️ All {n} keys are used up'],
  ['🟢 {a}/{n} κλειδιά διαθέσιμα', '🟢 {a}/{n} keys available', '🟢 {a}/{n} Κλειδιά Διαθέσιμα'],
  ['🟡 {a}/{n} κλειδιά', '🟡 {a}/{n} Keys'],
  ['🟢 {a}/{n} κλειδιά', '🟢 {a}/{n} Keys'],
  ['🆓 Δωρεάν λειτουργία', '🆓 Free Mode'],
  ['Δωρεάν μοντέλα ενεργά ως προεπιλογή (δωρεάν μετάφραση με όρια & Edge-TTS — χωρίς API key)', 'Free models are the default (free translation with limits & Edge-TTS — no API key)'],
  ['🔑 Τα Gemini API keys και οι ρυθμίσεις τα διαχειρίζεται ένας διαχειριστής.', '🔑 An administrator manages the Gemini API keys and settings.'],
  ['Αυτόματη εναλλαγή χωρίς κόστος ($0):', 'Automatic switching at no cost ($0):', 'Αυτόματη Εναλλαγή Χωρίς Κόστος ($0):'],
  ['Συνδέστε δωρεάν API Keys από έως 8 διαφορετικούς λογαριασμούς Google. Η Google ορίζει', 'Connect free API keys from up to 8 different Google accounts. Google sets a'],
  ['ημερήσιο όριο ανά μοντέλο', 'daily limit per model'],
  ['(σε ορισμένα μόνο 20 αιτήματα/ημέρα). Όταν ένα όριο εξαντληθεί (429 / Quota), η εφαρμογή συνεχίζει αυτόματα με άλλο μοντέλο ή με το επόμενο εφεδρικό κλειδί, όσο υπάρχει διαθέσιμο όριο.', '(only 20 requests a day for some). When a limit runs out (429 / Quota), the app continues automatically with another model or the next backup key, as long as some allowance is left.'],
  ['Παρακαλώ εισάγετε τουλάχιστον ένα Gemini API Key.', 'Please enter at least one Gemini API key.'],
  ['⚠️ Προσοχή: Εντοπίστηκε το ίδιο API Key σε πολλαπλά Slots. Τα κλειδιά πρέπει να είναι διαφορετικά για να λειτουργεί η εναλλαγή.', '⚠️ Careful: the same API key is in several slots. The keys must differ for the switching to work.'],
  ['Slot {n}: Μη έγκυρη μορφή API Key (ξεκινούν με AIzaSy... ή AQ).', 'Slot {n}: invalid API key format (keys start with AIzaSy... or AQ).'],
  ['Αποθηκεύτηκαν επιτυχώς {n} κλειδιά στο Gemini Pool! Αυτόματη εναλλαγή ενεργή.', '{n} keys saved to the Gemini pool! Automatic switching is on.'],
  ['Όλα τα Gemini API Keys αφαιρέθηκαν. Τα δωρεάν μοντέλα είναι πλέον η ενεργή προεπιλογή.', 'All Gemini API keys were removed. The free models are now the default.'],
  ['📱 Συσκευές', '📱 Devices (pairing)', '📱 Συσκευές (Device pairing)'],
  ['Μόνο αυτός ο υπολογιστής και οι συνδεδεμένες συσκευές έχουν πρόσβαση. Δημιουργήστε έναν σύνδεσμο και ανοίξτε τον', 'Only this computer and paired devices have access. Create a link and open it'],
  ['μία φορά', 'once'],
  ['στη νέα συσκευή (ισχύει 15 λεπτά).', 'on the new device (valid for 15 minutes).'],
  ['🔗 Δημιουργία συνδέσμου σύζευξης', '🔗 Create a pairing link'],
  ['Καμία συνδεδεμένη συσκευή ακόμη.', 'No paired devices yet.'],
  ['Ανάκληση', 'Revoke'],
  ['Δεν δημιουργήθηκε σύνδεσμος', 'No link was created'],
  ['📋 Ο σύνδεσμος αντιγράφηκε.', '📋 The link was copied.'],
  ['Η ανάκληση απέτυχε', 'Revoking failed'],
  ['Η συσκευή ανακλήθηκε.', 'The device was revoked.'],
  ['Το ημερήσιο όριο του Gemini API έχει εξαντληθεί.', 'The Gemini API daily limit has been reached.'],
  ['Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier).', 'The Gemini API daily limit (free tier) has been reached.'],
  ['✅ Έτοιμο ξανά!', '✅ Ready again!'],
  ['Το όριο Gemini API ανανεώθηκε! Έτοιμο για μεταφράσεις.', 'The Gemini API limit has renewed! Ready for translations.'],
  ['✅ Το όριο Gemini API ανανεώθηκε!', '✅ The Gemini API limit has renewed!'],
  ['Το σύστημα είναι πλήρως διαθέσιμο ξανά για χρήση AI Polish και μεταφράσεις.', 'The system is fully available again for AI Polish and translations.'],
  ['✅ Το όριο ανανεώθηκε!', '✅ The limit has renewed!'],
  ['Μπορείτε να συνεχίσετε τη μετάφραση από το αποθηκευμένο checkpoint.', 'You can resume the translation from the saved checkpoint.'],
  ['Μπορείτε να συνεχίσετε το Audiobook.', 'You can resume the audiobook.'],
  ['✅ Το όριο του Gemini API ανανεώθηκε! Αυτόματη συνέχιση από το checkpoint...', '✅ The Gemini API limit has renewed! Resuming from the checkpoint...'],
  ['Ημερήσιο όριο Gemini: Έτοιμο ξανά στις {c} (απομένουν {t})', 'Gemini daily limit: ready again at {c} ({t} left)'],
  ['Έτοιμο ξανά στις {c} (απομένουν {t})', 'Ready again at {c} ({t} left)'],
  ['Εξαντλήθηκε το όριο Gemini (Free Tier).', 'The Gemini limit (free tier) has been reached.'],
  ['Έτοιμο ξανά στις {c}', 'Ready again at {c}'],
  ['(Απομένουν:', '(Left:'],
  ['⚠️ Όριο quota ({t})', '⚠️ Quota limit ({t})', '⚠️ Όριο Quota ({t})', '⚠️ Quota ({t})'],
  ['Gemini Quota εξαντλήθηκε. Επαναφορά σε: {t}', 'Gemini quota used up. Reset in: {t}'],
  ['Ανανέωση σελίδας και δεδομένων...', 'Refreshing the page and data...'],
  ['⚠️ Δεν υπάρχει σύνδεση με τον διακομιστή. Βεβαιωθείτε ότι εκτελείται στη θύρα 8000.', '⚠️ Cannot connect to backend. Make sure the server is running on port 8000.'],

  // ── Account and users ──
  ['👤 Ο λογαριασμός μου', '👤 My account'],
  ['🔒 Αλλαγή κωδικού', '🔒 Change password'],
  ['Τρέχων κωδικός', 'Current password'],
  ['Νέος κωδικός (τουλάχιστον 10 χαρακτήρες)', 'New password (at least 10 characters)'],
  ['Επανάληψη νέου κωδικού', 'Repeat the new password'],
  ['Μετά την αλλαγή αποσυνδέεστε από όλες τις άλλες συσκευές σας.', 'After the change you are signed out of all your other devices.'],
  ['Αποθήκευση κωδικού', 'Save password'],
  ['👥 Χρήστες & δικαιώματα', '👥 Users & permissions'],
  ['Οι', 'The'],
  ['χρήστες', 'users'],
  ['βλέπουν μόνο τις δικές τους εργασίες. Οι', 'see only their own jobs. The'],
  ['διαχειριστές', 'administrators'],
  ['διαχειρίζονται χρήστες, Gemini API keys και ρυθμίσεις και βλέπουν όλες τις εργασίες. Πρέπει να υπάρχει πάντα τουλάχιστον ένας ενεργός διαχειριστής.', 'manage users, Gemini API keys and settings and see all jobs. There must always be at least one active administrator.'],
  ['Όνομα χρήστη (π.χ. maria)', 'Username (e.g. maria)'],
  ['Χρήστης', 'User'],
  ['Διαχειριστής', 'Administrator'],
  ['Προσωρινός κωδικός (κενό = αυτόματος)', 'Temporary password (empty = automatic)'],
  ['➕ Δημιουργία', '➕ Create'],
  ['📋 Αντιγραφή κωδικού', '📋 Copy password'],
  ['Διαγραφή — οι εργασίες του μεταφέρονται σε εμένα', 'Delete — their jobs move to me'],
  ['Διαγραφή μαζί με τις εργασίες και τα αρχεία', 'Delete together with the jobs and files'],
  ['Άκυρο', 'Cancel'],
  ['📜 Ιστορικό ενεργειών διαχείρισης', '📜 Administration log'],
  ['ποτέ', 'never'],
  ['καμία χρήση', 'no use'],
  ['Ρυθμίζεται από τον διαχειριστή', 'Set by the administrator'],
  ['Δεν φορτώθηκαν τα στοιχεία λογαριασμού', 'The account details did not load'],
  ['Τελευταία σύνδεση: {d}', 'Last sign-in: {d}'],
  ['Gemini σήμερα: {u}', 'Gemini today: {u}'],
  ['Οι δύο νέοι κωδικοί δεν ταιριάζουν.', 'The two new passwords do not match.'],
  ['Ο κωδικός δεν άλλαξε', 'The password was not changed'],
  ['🔒 Ο κωδικός άλλαξε. Οι άλλες συσκευές σας αποσυνδέθηκαν.', '🔒 Password changed. Your other devices were signed out.'],
  ['🔑 Προσωρινός κωδικός για «', '🔑 Temporary password for «'],
  ['Δώστε τον στον χρήστη· στην πρώτη σύνδεση θα επιλέξει δικό του.', 'Give it to the user; at the first sign-in they choose their own.'],
  ['Δεν θα εμφανιστεί ξανά.', 'It will not be shown again.'],
  ['Η αντιγραφή δεν επιτρέπεται από τον browser — επιλέξτε τον κωδικό και αντιγράψτε τον.', 'The browser does not allow copying — select the password and copy it.'],
  ['Δεν υπάρχουν χρήστες.', 'There are no users.'],
  ['Απενεργοποιημένος', 'Disabled'],
  ['Προσωρινός κωδικός', 'Temporary password'],
  ['εσείς', 'you'],
  ['🔑 Επαναφορά κωδικού', '🔑 Reset password'],
  ['🚪 Αποσύνδεση παντού', '🚪 Sign out everywhere'],
  ['✅ Ενεργοποίηση', '✅ Enable'],
  ['⏸️ Απενεργοποίηση', '⏸️ Disable'],
  ['🗑️ Διαγραφή', '🗑️ Delete'],
  ['⬆️ Διαχειριστής', '⬆️ Make administrator'],
  ['⬇️ Χρήστης', '⬇️ Make user'],
  ['Δεν φορτώθηκαν οι χρήστες', 'The users did not load'],
  ['δημιούργησε τον χρήστη', 'created the user'],
  ['άλλαξε τον ρόλο του', 'changed the role of'],
  ['απενεργοποίησε τον', 'disabled'],
  ['ενεργοποίησε τον', 'enabled'],
  ['διέγραψε τον', 'deleted'],
  ['επανέφερε τον κωδικό του', 'reset the password of'],
  ['άλλαξε τον κωδικό του', 'changed the password of'],
  ['αποσύνδεσε παντού τον', 'signed out everywhere'],
  ['Καμία ενέργεια ακόμη.', 'No actions yet.'],
  ['Γράψτε ένα όνομα χρήστη.', 'Type a username.'],
  ['Ο χρήστης δεν δημιουργήθηκε', 'The user was not created'],
  ['👤 Δημιουργήθηκε ο χρήστης «{u}».', '👤 User «{u}» created.'],
  ['Ο/Η «{u}» θα έχει τα ΙΔΙΑ δικαιώματα με εσάς (χρήστες, API keys, όλες οι εργασίες). Συνέχεια;', '«{u}» will have the SAME rights as you (users, API keys, all jobs). Continue?'],
  ['Να αφαιρεθούν τα δικαιώματα διαχειριστή από «{u}»;', 'Remove the administrator rights of «{u}»?'],
  ['Ο ρόλος δεν άλλαξε', 'The role was not changed'],
  ['Η αλλαγή δεν αποθηκεύτηκε', 'The change was not saved'],
  ['Νέος προσωρινός κωδικός για «{u}»; Θα αποσυνδεθεί από όλες τις συσκευές.', 'A new temporary password for «{u}»? They will be signed out of all devices.'],
  ['Ο κωδικός δεν επαναφέρθηκε', 'The password was not reset'],
  ['Η αποσύνδεση απέτυχε', 'Signing out failed'],
  ['🚪 «{u}»: {n} συνδέσεις τερματίστηκαν.', '🚪 «{u}»: {n} sessions ended.'],
  ['🗑️ Διαγραφή του λογαριασμού «', '🗑️ Delete the account «'],
  ['» ({n} εργασίες).', '» ({n} jobs).'],
  ['Τι να γίνει με τις εργασίες του;', 'What should happen to their jobs?'],
  ['Ο χρήστης δεν διαγράφηκε', 'The user was not deleted'],
  ['Ο χρήστης διαγράφηκε μαζί με {n} εργασίες.', 'The user was deleted together with {n} jobs.'],
  ['Ο χρήστης διαγράφηκε· {n} εργασίες μεταφέρθηκαν σε εσάς.', 'The user was deleted; {n} jobs moved to you.'],

  // ── Glossary ──
  ['⚙️ Γλωσσάρι όρων', '⚙️ Custom terminology & glossary', '⚙️ Custom Terminology & Glossary (Γλωσσάρι Όρων)'],
  ['Κατηγοριοποιημένο γλωσσάρι όρων για αυτόματη αντικατάσταση και τροφοδοσία του AI Polish. Επιλέξτε κατηγορία για φιλτράρισμα ή αναζητήστε συγκεκριμένο όρο.', 'A glossary of terms by category, for automatic replacement and for AI Polish. Choose a category to filter, or search for a term.'],
  ['🌐 Όλοι οι όροι', '🌐 All terms', '🌐 Όλοι οι Όροι'],
  ['💻 Τεχνικοί όροι', '💻 Technical terms', '💻 Τεχνικοί Όροι'],
  ['📚 Λογοτεχνικοί όροι', '📚 Literary terms', '📚 Λογοτεχνικοί Όροι'],
  ['⚙️ Γενικοί / custom', '⚙️ General / custom', '⚙️ Γενικοί / Custom'],
  ['🔍 Αναζήτηση όρου...', '🔍 Search for a term...'],
  ['Αγγλικός όρος (π.χ. Attention Mechanism)', 'English term (e.g. Attention Mechanism)', 'English Term (π.χ. Attention Mechanism)'],
  ['Ελληνικός όρος (π.χ. Μηχανισμός Προσοχής)', 'Greek term (e.g. Μηχανισμός Προσοχής)', 'Greek Term (π.χ. Μηχανισμός Προσοχής)'],
  ['💻 Τεχνικός όρος', '💻 Technical term', '💻 Τεχνικός Όρος'],
  ['📚 Λογοτεχνικός όρος', '📚 Literary term', '📚 Λογοτεχνικός Όρος'],
  ['⚙️ Γενικός / custom', '⚙️ General / custom', '⚙️ Γενικός / Custom'],
  ['💻 Τεχνικός', '💻 Technical'],
  ['📚 Λογοτεχνικός', '📚 Literary'],
  ['⚙️ Γενικός', '⚙️ General'],
  ['Κατηγορία', 'Category'],
  ['Όρος πρωτοτύπου (Αγγλικά)', 'Source Term (English)'],
  ['Μετάφραση (Ελληνικά)', 'Target Translation (Greek)'],
  ['Ενέργεια', 'Action'],
  ['Εμφάνιση όρων...', 'Showing terms...'],
  ['◀ Προηγούμενη', '◀ Previous'],
  ['Επόμενη ▶', 'Next ▶'],
  ['0 όροι', '0 terms'],
  ['Εμφάνιση {a}–{b} από {t} όρους (Σύνολο: {all})', 'Showing {a}–{b} of {t} terms (total: {all})'],
  ['Παρακαλώ συμπληρώστε και τον αγγλικό και τον ελληνικό όρο.', 'Please fill in both the English and the Greek term.'],
  ['Αποτυχία προσθήκης όρου', 'The term could not be added'],
  ['Προστέθηκε: "{s}" ➔ "{t}"', 'Added: "{s}" ➔ "{t}"'],
  ['Αποτυχία διαγραφής όρου', 'The term could not be deleted'],
  ['Διαγράφηκε ο όρος "{t}"', 'Deleted the term "{t}"'],
  ['Αποτυχία φόρτωσης γλωσσαρίου', 'Failed to load glossary'],
  ['Σφάλμα φόρτωσης: {r}', 'Loading error: {r}'],

  // ── Reader ──
  ['Βιβλίο', 'Book'],
  ['Ελληνική μετάφραση', 'Greek translation', 'Ελληνική Μετάφραση'],
  ['📄 Μονή στήλη', '📄 Single column', '📄 Μονή Στήλη'],
  ['↔️ Δίπλα-δίπλα', '↔️ Side-by-Side'],
  ['Χαρτί', 'Paper'],
  ['Σέπια', 'Sepia'],
  ['Μικρότερη γραμματοσειρά', 'Smaller font'],
  ['Μεγαλύτερη γραμματοσειρά', 'Larger font'],
  ['Κλείσιμο αναγνώστη', 'Close reader', 'Κλείσιμο Αναγνώστη'],
  ['Πρωτότυπο κείμενο', 'Original text', 'Πρωτότυπο Κείμενο (Original)'],
  ['Μετάφραση', 'Translation', 'Μετάφραση (Greek)'],
  ['Δεν υπάρχει επιλεγμένο έγγραφο για ανάγνωση.', 'No document is selected for reading.'],
  ['Αποτυχία φόρτωσης κειμένου βιβλίου', 'Failed to fetch book text'],

  // ── Sign-in page ──
  ['Σύνδεση στο BookApp', 'BookApp Sign In'],
  ['Σύνδεση', 'Sign in'],
  ['Αρχική ρύθμιση', 'First setup'],
  ['Νέος κωδικός', 'New password'],
  ['Όνομα χρήστη', 'Username'],
  ['Κωδικός', 'Password'],
  ['Να παραμείνω συνδεδεμένος/η (', 'Keep me signed in ('],
  ['ημέρες, ανανεώνεται σε κάθε επίσκεψη)', 'days, renewed on every visit)'],
  ['Ξεχάσατε τον κωδικό; Ζητήστε από έναν διαχειριστή να τον επαναφέρει.', 'Forgot your password? Ask an administrator to reset it.'],
  ['Δεν υπάρχει ακόμη λογαριασμός. Δημιουργήστε τον', 'There is no account yet. Create the'],
  ['πρώτο διαχειριστή', 'first administrator'],
  ['Ο', 'The'],
  ['κωδικός ρύθμισης', 'setup code'],
  ['βρίσκεται στο log του διακομιστή:', 'is in the server log:'],
  ['ή στο αρχείο', 'or in the file'],
  ['Κωδικός ρύθμισης', 'Setup code'],
  ['Όνομα χρήστη διαχειριστή', 'Administrator username'],
  ['Επανάληψη κωδικού', 'Repeat the password'],
  ['Τουλάχιστον', 'At least'],
  ['χαρακτήρες. Μια φράση από λέξεις είναι ιδανική.', 'characters. A phrase of several words is ideal.'],
  ['χαρακτήρες.', 'characters.'],
  ['Δημιουργία διαχειριστή', 'Create administrator'],
  ['Ο διαχειριστής σάς έδωσε', 'The administrator gave you a'],
  ['προσωρινό κωδικό', 'temporary password'],
  ['. Επιλέξτε τώρα τον δικό σας.', '. Choose your own now.'],
  ['Οι δύο κωδικοί δεν ταιριάζουν.', 'The two passwords do not match.'],
  ['✅ Ο διαχειριστής δημιουργήθηκε. Μεταφορά στην εφαρμογή…', '✅ The administrator was created. Opening the app…'],
  ['✅ Ο κωδικός αποθηκεύτηκε.', '✅ The password was saved.'],
  ['Δεν υπάρχει σύνδεση με τον διακομιστή.', 'No connection to the server.'],
  ['Κάτι πήγε στραβά (HTTP {n}).', 'Something went wrong (HTTP {n}).'],

  // ══ Messages written by the server (progress steps, notes, errors) ══
  // ── Book translation steps ──
  ['⚠️ {a}', '⚠️ {a}'],
  ['Ανάγνωση εγγράφου για μετάφραση με AI...', 'Reading document for Single-Pass AI Translation...'],
  ['Μετάφραση με AI ({b} παράλληλες παρτίδες, {p} σελίδες)...', 'Single-Pass AI Translation ({b} parallel batches, {p} pages)...'],
  ['Συνέχιση μετάφρασης με AI: παρτίδα {c}/{t} ({p}/{tp} σελίδες)...', 'Resuming Single-Pass AI Translation & Polish: batch {c}/{t} ({p}/{tp} pages)...'],
  ['Μετάφραση & επιμέλεια με AI: παρτίδα {c}/{t} ({p}/{tp} σελίδες)...', 'Single-Pass AI Translation & Polish: batch {c}/{t} ({p}/{tp} pages)...'],
  ['⚠️ Όριο Gemini: αυτόματη συνέχιση με δωρεάν μηχανή (παρτίδα {c}/{t})...', '⚠️ Gemini limit: continuing automatically with the free engine (batch {c}/{t})...', '⚠️ Όριο Gemini: Αυτόματη συνέχιση με δωρεάν μηχανή (batch {c}/{t})...'],
  ['Εξαγωγή μητρώου χαρακτήρων & όρων...', 'Extracting character & terminology dossier...'],
  ['Διόρθωση λέξεων με γράμματα άλλου αλφαβήτου...', 'Correcting words with letters of another alphabet...'],
  ['Ολοκλήρωση του μεταφρασμένου εγγράφου...', 'Finalizing AI translated document...'],
  ['✨ Μετάφραση με AI: τμήμα {d} από {t} (διατήρηση μορφοποίησης)...', '✨ AI translation: segment {d} of {t} (preserving formatting)...'],
  ['Μετάφραση παραγράφου {d} από {t} (διατήρηση στυλ)...', 'Translating paragraph {d} of {t} (preserving styles)...'],
  ['Μετάφραση τμήματος {d} από {t} (διατήρηση HTML/CSS)...', 'Translating block {d} of {t} (preserving HTML/CSS)...'],
  ['Εξαγωγή {f} με επιμέλεια AI...', 'Exporting AI-polished {f}...'],
  ['Εξαγωγή σε {f}...', 'Exporting to {f}...'],
  ['Εξήχθη {f} (με διατήρηση μορφοποίησης)', 'Exported {f} (Formatting Preserved)'],
  ['Εξήχθη {f}', 'Exported {f}'],
  ['🔍 Τελικός έλεγχος ποιότητας & βελτίωση κειμένου...', '🔍 Final quality check & text refinement...'],
  ['🏆 Αναθεώρηση της μετάφρασης με το πρωτότυπο (2ο πέρασμα AI, πολύ αργή διαδικασία)· ο χρόνος που απομένει φαίνεται μετά το πρώτο τμήμα…', '🏆 Revising the translation against the original (2nd AI pass, very slow); the time left shows after the first part…'],
  ['🏆 Αναθεώρηση με το πρωτότυπο (πολύ αργή διαδικασία): τμήμα {d}/{t} · {left}…', '🏆 Revision against the original (very slow): part {d}/{t} · {left}…'],
  ['🏆 Αναθεώρηση με το πρωτότυπο (πολύ αργή διαδικασία): τμήμα {d}/{t}…', '🏆 Revision against the original (very slow): part {d}/{t}…'],
  ['απομένει λιγότερο από 1 λεπτό', 'less than 1 minute left'],
  ['απομένουν ~{#n} λεπτά', '~{#n} minutes left'],
  ['απομένουν ~{#h} ώρα', '~{#h} hour left'],
  ['απομένουν ~{#h} ώρες', '~{#h} hours left'],
  ['απομένουν ~{#h} ώρα {#m} λεπτά', '~{#h} hour {#m} minutes left'],
  ['απομένουν ~{#h} ώρες {#m} λεπτά', '~{#h} hours {#m} minutes left'],
  ['Ανάγνωση εγγράφου...', 'Reading document...'],
  ['Μετάφραση {n} σελίδων (παράλληλη μηχανή)...', 'Translating {n} pages (parallel engine)...'],
  ['Μετάφραση σελίδας {d} από {t}...', 'Translating page {d} of {t}...'],
  ['Η Google αρνείται τα αιτήματα: το Gemini μεταφράζει σε παρτίδες ({d}/{t})...', 'Google refuses requests: Gemini translates in batches ({d}/{t})...'],
  ['Εγγραφή μεταφρασμένου αρχείου...', 'Writing translated file...'],
  ['Αποτυχία ανάγνωσης εγγράφου: {r}', 'Failed to read document: {r}'],
  ['Αναμονή για έναρξη...', 'Waiting to start...'],
  ['🛑 Ακυρώθηκε από τον χρήστη.', '🛑 Cancelled by user.'],
  ['Έτοιμο για συνέχιση (αποθηκευμένο checkpoint)', 'Ready to resume (saved checkpoint)'],
  ['⚠️ Σταμάτησε: εξαντλήθηκε το ημερήσιο όριο Gemini API', '⚠️ Stopped: the Gemini API daily limit is used up', '⚠️ Σταμάτησε: Εξαντλήθηκε το ημερήσιο όριο Gemini API'],
  ['⚠️ Σταμάτησε: όριο αιτημάτων Gemini (429)· συνεχίστε σε ένα λεπτό', '⚠️ Stopped: Gemini request limit (429) — resume in a minute'],
  ['⏳ Σε αναμονή στην παρτίδα...', '⏳ Queued in batch...'],
  ['⏳ Σε αναμονή στην παρτίδα (επαναφέρθηκε μετά από επανεκκίνηση)...', '⏳ Queued in batch (restored after restart)...'],
  ['⏳ Σε αναμονή για νέα προσπάθεια...', '⏳ Queued for retry...'],
  ['🔄 Συνέχιση από checkpoint μετά από ανανέωση ορίου Gemini API...', '🔄 Resuming from the checkpoint after the Gemini API limit renewed...'],
  ['⏳ Αναμονή ανανέωσης ορίου Gemini (αυτόματη συνέχιση μόλις γίνει reset)', '⏳ Waiting for the Gemini limit to renew (resumes by itself after the reset)', '⏳ Αναμονή ανανέωσης ορίου Gemini (Αυτόματη συνέχιση μόλις γίνει reset)'],

  // ── End-of-job notes ──
  ['Η δωρεάν μετάφραση της Google αρνήθηκε τα αιτήματα, οπότε μετέφρασε το Gemini (χρησιμοποιεί το όριο Gemini σας).', 'Google\'s free translation refused the requests, so Gemini translated (this uses your Gemini allowance).'],
  ['Μέρος του κειμένου μεταφράστηκε από το MyMemory, μια απλούστερη δωρεάν υπηρεσία, επειδή η Google αρνήθηκε: ελέγξτε το.', 'Some text was translated by MyMemory, a simpler free service, because Google refused: please check it.'],
  ['{#n} μπλοκ προμορφοποιημένου κειμένου έμειναν αμετάφραστα επειδή μοιάζουν με κώδικα: ελέγξτε τα.', '{#n} preformatted block(s) kept untranslated because they look like program code: please check them.'],
  ['{#n} σελίδες έχουν ακόμη κείμενο στη γλώσσα του πρωτοτύπου (σελίδες {p} του πρωτοτύπου): μεταφράστε ξανά για νέα προσπάθεια.', '{#n} page(s) still contain text in the original language (pages {p} of the original): translate again to retry them.'],
  ['{#n} λέξεις έχουν γράμματα άλλου αλφαβήτου ({w}): ελέγξτε τες.', '{#n} word(s) contain letters of another alphabet ({w}): please check them.'],
  ['Το 2ο πέρασμα AI (Μέγιστη ποιότητα) δεν ολοκληρώθηκε ({r}): κρατήθηκε η μετάφραση του 1ου περάσματος.', 'The second AI pass (Maximum quality) did not complete ({r}); the first-pass translation was kept.'],
  ['Μέγιστη ποιότητα: {#n} σελίδες κράτησαν τη μετάφραση του 1ου περάσματος, επειδή η αναθεώρησή τους δεν ήταν αξιοποιήσιμη.', 'Maximum quality: {#n} page(s) kept the first-pass translation because the revision of those pages was unusable.'],
  ['{#n} σελίδες έμειναν αμετάφραστες ({p}): {r}.', '{#n} page(s) left untranslated ({p}): {r}.'],
  ['το Vision AI απέτυχε{why}· μεταφράστε ξανά για νέα προσπάθεια', 'Vision AI failed{why}; translate again to retry them'],
  ['οι σελίδες με μόνο εικόνες χρειάζονται κλειδί Gemini API', 'image-only pages need a Gemini API key'],
  ['Δεν βρέθηκε κείμενο σε {#n} σελίδες ({p}): μόνο εικόνα; Αν κάποια έχει μπαλόνια, μεταφράστε ξανά για νέα προσπάθεια.', 'No text found on {#n} page(s) ({p}): artwork only? If one of them has balloons, translate again to retry it.'],

  // ── Graphic novels ──
  ['Άνοιγμα graphic novel...', 'Opening graphic novel...'],
  ['Εξαγωγή αρχείου κόμικ (CBZ)...', 'Extracting comic archive (CBZ)...'],
  ['Μετάφραση {n} σελίδων κόμικ (παράλληλη μηχανή Vision)...', 'Translating {n} comic pages (parallel Vision engine)...'],
  ['Μετάφραση σελίδας graphic novel {d} από {t} (⚠️ Χωρίς AI Polish: εξαντλήθηκε το ημερήσιο όριο Gemini)...', 'Translating graphic novel page {d} of {t} (⚠️ without AI Polish: the Gemini daily limit is used up)...', 'Translating graphic novel page {d} of {t} (⚠️ Χωρίς AI Polish: εξαντλήθηκε το ημερήσιο όριο Gemini)...'],
  ['Μετάφραση σελίδας graphic novel {d} από {t}...', 'Translating graphic novel page {d} of {t}...'],
  ['Το AI Vision μετέφρασε τη σελίδα {d} από {t}...', 'AI Vision translated graphic novel page {d} of {t}...'],
  ['Η μετάφραση του graphic novel ολοκληρώθηκε! Προετοιμασία εξαγωγής...', 'Graphic novel translation complete! Preparing export...'],
  ['Το PDF του κόμικ έχει 0 σελίδες και δεν μπορεί να μεταφραστεί.', 'Comic PDF contains 0 pages and cannot be translated.'],
  ['Αυτό το graphic novel / σαρωμένο κόμικ έχει σελίδες μόνο με εικόνες και χρειάζεται κλειδί Gemini API για να εντοπιστούν και να μεταφραστούν τα μπαλόνια (Vision AI).', 'This graphic novel / scanned comic contains image-only pages and requires a Gemini API key for Vision AI balloon detection and translation.'],
  ['Δεν βρέθηκαν εικόνες σελίδων στο αρχείο CBZ.', 'No comic page images found in uploaded CBZ archive.'],
  ['Το αρχείο κόμικ είναι πολύ μεγάλο όταν αποσυμπιεστεί (πάνω από 2 GB).', 'The comic archive is too large when unpacked (over 2 GB).'],
  ['Η μετάφραση Vision AI απέτυχε σε {f}/{t} σελίδες ({r}). Η πρόοδος των επιτυχημένων σελίδων αποθηκεύτηκε — περιμένετε λίγα δευτερόλεπτα και πατήστε ξανά Έναρξη μετάφρασης για συνέχιση!', 'Vision AI translation failed on {f}/{t} pages ({r}). The pages done are saved — wait a few seconds and press Start Translation again to continue!', 'Η μετάφραση Vision AI απέτυχε σε {f}/{t} σελίδες ({r}). Η πρόοδος των επιτυχημένων σελίδων αποθηκεύτηκε — περιμένετε λίγα δευτερόλεπτα και πατήστε ξανά Start Translation για συνέχιση!'],
  ['Η μετάφραση Vision AI σταμάτησε λόγω εξάντλησης του ημερήσιου ορίου του Gemini Free Tier. Η πρόοδος ({n} σελίδες) αποθηκεύτηκε σε checkpoint! Αλλάξτε Gemini API key στις Ρυθμίσεις ή δοκιμάστε ξανά αργότερα.', 'Vision AI translation stopped: the Gemini free tier daily limit is used up. The progress ({n} pages) is saved at a checkpoint! Change the Gemini API key in Settings or try again later.'],
  ['Η μετάφραση Vision AI σταμάτησε λόγω εξάντλησης του ημερήσιου ορίου του Gemini Free Tier. Η πρόοδος ({n} σελίδες) αποθηκεύτηκε σε checkpoint! (quota_behavior=\'wait\').', 'Vision AI translation stopped: the Gemini free tier daily limit is used up. The progress ({n} pages) is saved at a checkpoint! (waiting for the reset).'],
  ['Η μετάφραση Vision AI σταμάτησε λόγω εξάντλησης του ημερήσιου ορίου του Gemini Free Tier. Απομένουν {n} σελίδες· η πρόοδος αποθηκεύτηκε σε checkpoint!', 'Vision AI translation stopped: the Gemini free tier daily limit is used up. {n} pages are left; the progress is saved at a checkpoint!'],
  ['Εξαντλήθηκε το ημερήσιο όριο του Gemini API κατά το Comic AI Polish. Η εργασία σταμάτησε σε αναμονή ανανέωσης ορίου (quota_behavior=\'wait\').', 'The Gemini API daily limit ran out during Comic AI Polish. The job stopped to wait for the limit to renew.'],

  // ── Audiobook steps ──
  ['🎙️ Δημιουργία νευρωνικού ήχου σε {#n} τμήματα ({#k} έτοιμα ήδη) με {v} ({s})...', '🎙️ Generating neural audio in {#n} parts ({#k} already narrated) using {v} ({s})...'],
  ['🎙️ Δημιουργία νευρωνικού ήχου σε {#n} τμήματα με {v} ({s})...', '🎙️ Generating neural audio in {#n} parts using {v} ({s})...'],
  ['🎙️ Δημιουργήθηκε το τμήμα ήχου {d} από {t}...', '🎙️ Generated audio part {d} of {t}...'],
  ['🎙️ Σύνθεση ήχου (τμήμα {d}/{t})...', '🎙️ Synthesizing audio (part {d}/{t})...'],
  ['Συναρμολόγηση του τελικού audiobook...', 'Assembling final audiobook...'],
  ['✨ Επιμέλεια του κειμένου εκφώνησης με AI...', '✨ AI polishing script for spoken narration...'],
  ['✨ Επιμέλεια του κειμένου εκφώνησης με AI ({d}/{t})...', '✨ AI polishing audio script ({d}/{t})...'],
  ['ℹ️ Δωρεάν μοντέλο: εκφώνηση με νευρωνικές φωνές Edge-TTS...', 'ℹ️ Free model: narration with Edge-TTS neural voices...', 'ℹ️ Δωρεάν μοντέλο: Εκφώνηση με νευρωνικές φωνές Edge-TTS...'],
  ['⚠️ Όριο Gemini: η εκφώνηση συνεχίζει με το αρχικό κείμενο...', '⚠️ Gemini limit: narration continues with the original text...', '⚠️ Όριο Gemini: Συνέχιση εκφώνησης με αρχικό κείμενο...'],
  ['🔍 Τελικός έλεγχος ποιότητας ηχητικού βιβλίου...', '🔍 Final quality check of the audiobook...'],
  ['Το audiobook είναι έτοιμο!', 'Audiobook ready!'],
  ['⚠️ Το audiobook είναι έτοιμο! {n}.', '⚠️ Audiobook ready! {n}.'],
  ['{#n} τμήματα σε γραφή που δεν διαβάζει αυτή η φωνή παραλείφθηκαν', '{#n} part(s) in a script this voice cannot read were skipped'],
  ['{#n} τμήματα διαβάστηκαν από τη φωνή {a}, επειδή η {b} δεν έδωσε ήχο', '{#n} part(s) read by {a}, because {b} returned no audio'],
  ['Δεν βρέθηκε κείμενο για μετατροπή σε ήχο.', 'No text found to convert to audio.'],
  ['Δεν υπάρχουν έγκυρα τμήματα ήχου για ένωση.', 'No valid audio chunks to concatenate.'],

  // ── AI Polish (editor) ──
  ['Σύνδεση με το Gemini Flash AI...', 'Connecting to Gemini Flash AI...'],
  ['ℹ️ Εφαρμογή δωρεάν τυπογραφικών κανόνων & γλωσσαρίου (Free Mode)...', 'ℹ️ Applying the free typography rules & glossary (Free Mode)...'],
  ['Επιμέλεια παρτίδας {d} από {t}...', 'Polishing batch {d} of {t}...'],
  ['Το AI Polish ολοκληρώθηκε!', 'AI Polishing complete!'],

  // ── Book Insights (server) ──
  ['Ανάλυση ενότητας {d}/{t}…', 'Analysing section {d}/{t}…'],
  ['Συμπύκνωση σημειώσεων…', 'Condensing notes…'],
  ['Έτοιμο (αποθηκευμένο αποτέλεσμα)', 'Ready (saved result)'],
  ['Προετοιμασία κειμένου…', 'Preparing the text…'],
  ['Συγγραφή κειμένου…', 'Writing the text…'],
  ['Διόρθωση & επανέλεγχος…', 'Correcting & re-checking…'],
  ['Γλωσσική επιμέλεια ελληνικού κειμένου…', 'Language editing of the Greek text…'],
  ['Εκφώνηση τμήματος {d}/{t}…', 'Narrating part {d}/{t}…'],
  ['Ο ήχος είναι έτοιμος', 'The audio is ready'],
  ['Αυτός ο τύπος αρχείου δεν υποστηρίζεται για Book Insights. Χρησιμοποιήστε PDF, DOCX ή EPUB με κείμενο (όχι κόμικ/εικόνες).', 'This file type is not supported for Book Insights. Use a PDF, DOCX or EPUB with text (not comics/images).'],
  ['Δεν ήταν δυνατή η ανάγνωση κειμένου από το έγγραφο. Το αρχείο μπορεί να είναι κατεστραμμένο ή προστατευμένο.', 'The text of the document could not be read. The file may be damaged or protected.'],
  ['Το έγγραφο δεν περιέχει αρκετό αναγνώσιμο κείμενο για αξιόπιστη περίληψη. Αν είναι σαρωμένο (εικόνες), δεν υπάρχει εξαγώγιμο κείμενο.', 'The document does not contain enough readable text for a reliable summary. If it is scanned (images), there is no text to extract.'],
  ['Το έγγραφο είναι πολύ μικρό για σύνοψη: χρειάζεται τουλάχιστον ~1,5 σελίδα ουσιαστικού κειμένου.', 'The document is too short for a synopsis: it needs at least ~1.5 pages of real text.'],
  ['Δεν ήταν δυνατός ο εντοπισμός της γλώσσας του εγγράφου. Επιλέξτε γλώσσα εξόδου στην Προχωρημένη Λειτουργία.', 'The document\'s language could not be detected. Choose the output language in Advanced Mode.'],
  ['Για τα Book Insights απαιτείται κλειδί Google Gemini API. Προσθέστε ένα δωρεάν κλειδί από το κουμπί «🔑 Gemini API Key».', 'Book Insights needs a Google Gemini API key. Add a free key with the «🔑 Gemini API Key» button.'],
  ['Εξαντλήθηκε το ημερήσιο όριο του Gemini API. Δοκιμάστε αργότερα ή προσθέστε άλλο κλειδί.', 'The Gemini API daily limit is used up. Try later or add another key.'],
  ['Πάρα πολλά αιτήματα προς το Gemini αυτή τη στιγμή. Περιμένετε λίγο και δοκιμάστε ξανά.', 'Too many requests to Gemini right now. Wait a moment and try again.'],
  ['Το κλειδί Gemini API απορρίφθηκε. Ελέγξτε ότι είναι σωστό στις Ρυθμίσεις.', 'The Gemini API key was rejected. Check that it is correct in Settings.'],
  ['Πρόβλημα σύνδεσης με την υπηρεσία AI. Ελέγξτε τη σύνδεσή σας στο διαδίκτυο και δοκιμάστε ξανά.', 'A connection problem with the AI service. Check your internet connection and try again.'],
  ['Η δημιουργία κειμένου από το AI απέτυχε. Δοκιμάστε ξανά σε λίγο.', 'The AI could not create the text. Try again in a moment.'],
  ['Το AI παρήγαγε κείμενο που δεν πέρασε τον έλεγχο ποιότητας (π.χ. λάθος γλώσσα ή στοιχεία που δεν υπάρχουν στο βιβλίο), οπότε δεν εμφανίζεται. Δοκιμάστε ξανά.', 'The AI wrote a text that failed the quality check (e.g. the wrong language, or details not in the book), so it is not shown. Try again.'],
  ['Η δημιουργία ήχου απέτυχε. Ελέγξτε τη σύνδεσή σας και δοκιμάστε ξανά.', 'The audio creation failed. Check your connection and try again.'],
  ['Ο ήχος είναι διαθέσιμος μόνο για ελληνικό ή αγγλικό κείμενο.', 'Audio is available only for Greek or English text.'],
  ['Η αποθήκευση του αρχείου απέτυχε. Δοκιμάστε άλλη μορφή ή ελέγξτε τον ελεύθερο χώρο στον δίσκο.', 'Saving the file failed. Try another format or check the free disk space.'],
  ['Δεν υπάρχει ακόμη αυτό το κείμενο. Δημιουργήστε το πρώτα.', 'This text does not exist yet. Create it first.'],
  ['Μη έγκυρη επιλογή.', 'Invalid choice.'],
  ['Το έγγραφο δεν βρέθηκε. Ανεβάστε το ξανά.', 'The document was not found. Upload it again.'],
  ['Η εργασία δεν βρέθηκε.', 'The job was not found.'],
  ['Η εργασία δεν βρέθηκε (ίσως έγινε επανεκκίνηση του διακομιστή). Δοκιμάστε ξανά.', 'The job was not found (the server may have restarted). Try again.'],
  ['Το αρχείο δεν βρέθηκε.', 'The file was not found.'],

  // ── Errors: quota, free engine, documents ──
  ['⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). Έτοιμο ξανά στις {c} (απομένουν ~{t}). Αλλάξτε API Key στις Ρυθμίσεις ή περιμένετε την αντίστροφη μέτρηση για αυτόματη συνέχιση.', '⚠️ The Gemini API daily limit (free tier) is used up. Ready again at {c} (~{t} left). Change the API key in Settings or wait for the countdown to resume automatically.'],
  ['⚠️ Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier). Η πρόοδος αποθηκεύτηκε σε checkpoint στο δίσκο. Έτοιμο ξανά στις {c} (απομένουν ~{t}). Παρακαλούμε περιμένετε ή αλλάξτε API Key στις Ρυθμίσεις (Settings).', '⚠️ The Gemini API daily limit (free tier) is used up. The progress is saved at a checkpoint on disk. Ready again at {c} (~{t} left). Please wait or change the API key in Settings.'],
  ['Η δωρεάν μετάφραση δεν είναι διαθέσιμη τώρα: η Google αρνείται τα αιτήματα και το MyMemory δέχεται μόνο λίγο κείμενο την ημέρα. Προσθέστε δωρεάν κλειδί Gemini ή δοκιμάστε αργότερα. Δεν αποθηκεύτηκε αμετάφραστο κείμενο· πατήστε Συνέχιση (όσα μεταφράστηκαν διατηρούνται).', 'Free translation is not available now: Google refuses the requests and MyMemory accepts only a little text a day. Add a free Gemini key or try later. No untranslated text was saved; press Resume (what was translated is kept).'],
  ['Λείπει το κλειδί Gemini API. Προσθέστε ένα στις Ρυθμίσεις ή επιλέξτε τα δωρεάν μοντέλα (fallback).', 'Missing Gemini API Key. Please provide a key in settings or select free models (fallback).'],
  ['Όλα τα διαθέσιμα μοντέλα Gemini είναι σε αναμονή σε όλα τα κλειδιά.', 'All Gemini candidate models are in cooldown across configured keys.'],
  ['Δεν βρέθηκε αναγνώσιμο κείμενο στο έγγραφο.', 'No readable text found in document.'],
  ['Το PDF προστατεύεται με κωδικό / είναι κρυπτογραφημένο και δεν διαβάζεται χωρίς κωδικό.', 'PDF file is password-protected / encrypted and cannot be read without a password.'],
  ['Μη υποστηριζόμενος τύπος αρχείου: {e}', 'Unsupported file type: {e}'],
  ['Μη υποστηριζόμενος τύπος αρχείου \'{e}\'. Υποστηρίζονται: PDF, DOCX, EPUB, CBZ, CBR, ZIP.', 'Unsupported file type \'{e}\'. Supported: PDF, DOCX, EPUB, CBZ, CBR, ZIP.'],
  ['Το παλιό format .doc δεν υποστηρίζεται. Αποθηκεύστε το αρχείο ως .docx με το Microsoft Word ή το LibreOffice.', 'Legacy .doc format is not supported. Please save/convert your file as .docx using Microsoft Word or LibreOffice.'],
  ['Το αρχείο \'{f}\' είναι κενό (0 bytes) και δεν περιέχει δεδομένα.', 'The file \'{f}\' is empty (0 bytes) and holds no data.'],
  ['Το αρχείο \'{f}\' δεν είναι έγκυρο αρχείο {t} (ενδέχεται να είναι κατεστραμμένο ή παλιό .doc που μετονομάστηκε). Ανοίξτε το και αποθηκεύστε το ξανά ως {e}.', 'The file \'{f}\' is not a valid {t} file (it may be damaged, or an old .doc renamed). Open it and save it again as {e}.'],
  ['Το αρχείο \'{f}\' δεν είναι έγκυρο αρχείο PDF (κατεστραμμένη επικεφαλίδα).', 'The file \'{f}\' is not a valid PDF file (damaged header).'],
  ['Το αρχείο \'{f}\' δεν είναι έγκυρο αρχείο CBR.', 'The file \'{f}\' is not a valid CBR file.'],
  ['Το αρχείο \'{f}\' ({s} MB) υπερβαίνει το μέγιστο όριο των 250 MB.', 'The file \'{f}\' ({s} MB) is over the 250 MB limit.'],
  ['Δεν ήταν δυνατή η αποθήκευση του αρχείου \'{f}\' στον server ({r}).', 'The file \'{f}\' could not be stored on the server ({r}).'],
  ['Μια εργασία εκτελείται ήδη για αυτό το έγγραφο.', 'A task is already running for this job.'],
  ['Η γλώσσα πρωτοτύπου και μετάφρασης πρέπει να διαφέρουν.', 'Source and target languages must be different.'],
  ['Μη υποστηριζόμενη μορφή εξόδου \'{f}\'.', 'Unsupported output format \'{f}\'.'],
  ['Μη υποστηριζόμενη μορφή λήψης \'{f}\'.', 'Unsupported download format \'{f}\'.'],
  ['Οι μορφές TXT και DOCX είναι απενεργοποιημένες για Graphic Novels. Επιλέξτε PDF, CBZ, CBR ή EPUB.', 'TXT and DOCX formats are disabled for Graphic Novels. Please choose PDF, CBZ, CBR, or EPUB.'],
  ['Η μορφή \'{f}\' υποστηρίζεται μόνο για Graphic Novels / Comics.', 'Format \'{f}\' is only supported for Graphic Novels / Comics.'],
  ['Δεν βρέθηκε το αρχείο σε μορφή \'{f}\' για την εργασία \'{j}\'.', 'Output file in format \'{f}\' for job \'{j}\' not found.'],
  ['Δεν βρέθηκε το αποτέλεσμα της εργασίας \'{j}\'.', 'Output file for job \'{j}\' not found.'],
  ['Δεν βρέθηκε το αποτέλεσμα της εργασίας.', 'Job output not found.'],
  ['Μια εργασία εκτελείται για αυτό το έγγραφο: το αποτέλεσμά της θα έσβηνε αυτές τις διορθώσεις.', 'A task is running for this job: its output would overwrite these edits.'],
  ['Δεν βρέθηκε η εργασία \'{j}\' ή το αρχείο της.', 'Job \'{j}\' or its source file not found.'],
  ['Δεν βρέθηκε εξώφυλλο για αυτό το βιβλίο.', 'No cover image found for this book.'],
  ['Κενό αρχείο εικόνας.', 'Empty image file.'],
  ['Η εικόνα εξωφύλλου ξεπερνά το όριο των 25 MB.', 'Cover image exceeds maximum size of 25 MB.'],
  ['Μη έγκυρο ή κατεστραμμένο αρχείο εικόνας. Ανεβάστε μια έγκυρη εικόνα JPEG, PNG ή WEBP.', 'Invalid or corrupt image file. Please upload a valid JPEG, PNG, or WEBP image.'],
  ['Το κλειδί Gemini API απαιτείται για το AI Audiobook Polish. Επιλέξτε \'Αυτόματη μετάβαση σε δωρεάν μοντέλο\' για εκφώνηση χωρίς κλειδί.', 'A Gemini API key is required for AI Audiobook Polish. Choose \'Switch to the free model automatically\' to narrate without a key.', 'Gemini API key is required for AI Audiobook Polish. Επιλέξτε \'Αυτόματη μετάβαση σε Δωρεάν Μοντέλο\' για εκφώνηση χωρίς κλειδί.'],
  ['Οι αλλαγές δεν μπόρεσαν να εφαρμοστούν στο έγγραφο χωρίς απώλεια μορφοποίησης, γι\' αυτό δεν άλλαξε κανένα αρχείο. Αν το έγγραφο είναι ανοιχτό σε άλλο πρόγραμμα, κλείστε το και δοκιμάστε ξανά. Αλλιώς κατεβάστε το και διορθώστε το απευθείας.', 'The changes could not be applied to the document without losing formatting, so no file was changed. If the document is open in another program, close it and try again. Otherwise download it and correct it directly.'],
  ['Το AI Polish απέτυχε: {r}', 'AI Polishing failed: {r}'],
  ['Η προεπισκόπηση απέτυχε: {r}', 'Preview extraction failed: {r}'],
  ['Η δοκιμή φωνής απέτυχε: {r}', 'Voice preview failed: {r}'],
  ['Δεν βρέθηκε έγγραφο ή κείμενο για επιμέλεια.', 'No document or text found to polish.'],
  ['Δεν ήταν δυνατή η ανάγνωση κειμένου από το έγγραφο που ανεβάσατε.', 'Could not extract readable text from the uploaded document.'],
  ['Μη έγκυρο αναγνωριστικό φωνής \'{v}\'.', 'Invalid voice identifier \'{v}\'.'],
  ['Δεν υπάρχουν ολοκληρωμένα έγγραφα στην ουρά για λήψη.', 'No completed documents in the queue to download.'],
  ['Πρέπει να ολοκληρωθούν όλες οι μεταφράσεις πριν τη λήψη ({d}/{t} ολοκληρώθηκαν).', 'All translations must be completed before downloading ({d}/{t} completed).'],
  ['Δεν βρέθηκαν αρχεία για λήψη στις ολοκληρωμένες εργασίες της ουράς.', 'No downloadable output files found for completed queue jobs.'],
  ['Η εργασία \'{j}\' δεν βρέθηκε στην ουρά.', 'Job \'{j}\' not found in queue.'],
  ['Η εργασία \'{j}\' εκτελείται ήδη στην ουρά.', 'Job \'{j}\' is already running in the queue.'],
  ['Η εργασία \'{j}\' εκτελείται ήδη.', 'Job \'{j}\' is already running.', 'Job \'{j}\' is currently running.'],
  ['Το όριο της ουράς είναι {n} αρχεία ανά παρτίδα. Καθαρίστε ή αφαιρέστε κάποια ολοκληρωμένα αρχεία για να προσθέσετε νέα.', 'The queue holds at most {n} files per batch. Clear or remove some finished files to add new ones.'],
  ['Οι διασυνοριακές αιτήσεις δεν επιτρέπονται.', 'Cross-site requests are not allowed.'],
  ['Αυτή η συσκευή δεν είναι συνδεδεμένη με το BookApp. Ανοίξτε πρώτα έναν σύνδεσμο σύζευξης.', 'This device is not paired with BookApp. Open a pairing link first.'],
  ['Η συσκευή δεν βρέθηκε.', 'Device not found.'],
  ['Ο όρος του πρωτοτύπου δεν μπορεί να είναι κενός.', 'Source term cannot be empty.'],
  ['Η μετάφραση του όρου δεν μπορεί να είναι κενή.', 'Target term cannot be empty.'],
  ['Συμπληρώθηκε το μέγιστο των {n} κλειδιών Gemini API.', 'Maximum limit of {n} Gemini API keys reached.'],

  // ── Sign-in and accounts (server) ──
  ['Συνδεθείτε για να συνεχίσετε.', 'Sign in to continue.'],
  ['Η εφαρμογή χρειάζεται αρχική ρύθμιση (/setup).', 'The app needs its first setup (/setup).'],
  ['Αλλάξτε πρώτα τον προσωρινό κωδικό σας.', 'Change your temporary password first.'],
  ['Μόνο οι διαχειριστές έχουν πρόσβαση σε αυτή τη λειτουργία.', 'Only administrators can use this.'],
  ['Λάθος όνομα χρήστη ή κωδικός.', 'Wrong username or password.'],
  ['Πολλές αποτυχημένες προσπάθειες. Δοκιμάστε ξανά σε {n} λεπτά.', 'Too many failed attempts. Try again in {n} minutes.'],
  ['Ο λογαριασμός έχει απενεργοποιηθεί. Επικοινωνήστε με τον διαχειριστή.', 'The account is disabled. Contact the administrator.'],
  ['Το όνομα χρήστη πρέπει να έχει 2–32 λατινικά γράμματα, αριθμούς ή . _ - (χωρίς κενά).', 'The username needs 2–32 Latin letters, digits or . _ - (no spaces).'],
  ['Ο κωδικός πρέπει να έχει τουλάχιστον {n} χαρακτήρες (και όχι τον ίδιο χαρακτήρα ξανά και ξανά).', 'The password needs at least {n} characters (and not the same character again and again).'],
  ['Ο κωδικός δεν μπορεί να είναι ίδιος με το όνομα χρήστη.', 'The password cannot be the same as the username.'],
  ['Ο νέος κωδικός πρέπει να διαφέρει από τον τρέχοντα.', 'The new password must differ from the current one.'],
  ['Ο τρέχων κωδικός δεν είναι σωστός.', 'The current password is not correct.'],
  ['Υπάρχει ήδη χρήστης με αυτό το όνομα.', 'A user with this name already exists.'],
  ['Ο χρήστης δεν βρέθηκε.', 'The user was not found.'],
  ['Πρέπει να υπάρχει πάντα τουλάχιστον ένας ενεργός διαχειριστής.', 'There must always be at least one active administrator.'],
  ['Δεν μπορείτε να απενεργοποιήσετε ή να διαγράψετε τον δικό σας λογαριασμό.', 'You cannot disable or delete your own account.'],
  ['Άγνωστος ρόλος (επιτρέπονται: admin, user).', 'Unknown role (allowed: admin, user).'],
  ['Η αρχική ρύθμιση έχει ήδη ολοκληρωθεί. Συνδεθείτε με τον λογαριασμό σας.', 'The first setup is already done. Sign in with your account.'],
  ['Λάθος κωδικός ρύθμισης. Θα τον βρείτε στο αρχείο καταγραφής (log) του διακομιστή ή στο data/setup_code.txt.', 'Wrong setup code. You will find it in the server log or in data/setup_code.txt.'],
  ['Σφάλμα λογαριασμού.', 'Account error.'],
];

const I18N = (() => {
  const LETTER = /[A-Za-zͰ-Ͽἀ-῿]/;
  const ATTRS = ['title', 'placeholder', 'aria-label', 'alt', 'label'];
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE', 'NOSCRIPT']);
  const norm = (s) => String(s).replace(/\s+/g, ' ').trim();
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  const exact = new Map();  // normalised wording -> pair index (the first pair listing it)
  const patterns = [];      // wordings with {name}: [{re, names, pair, hint}]
  I18N_PAIRS.forEach((pair, index) => {
    pair.forEach((wording) => {
      const key = norm(wording);
      if (!/\{#?\w+\}/.test(key)) {
        if (!exact.has(key)) exact.set(key, index);
        return;
      }
      const names = [];
      let strict = '^';
      let loose = '^';
      let hint = '';
      let literal = 0;
      key.split(/\{(#?\w+)\}/).forEach((part, k) => {
        if (k % 2) {
          names.push(part.replace('#', ''));
          if (part.startsWith('#')) {  // {#n}: a number only
            strict += '([\\d.,]+)';
            loose += '([\\d.,]+)';
          } else {
            strict += '((?:(?![.!?…;] )[\\s\\S])*?)';  // within one sentence
            loose += '([\\s\\S]*?)';
          }
        } else {
          strict += escapeRe(part);
          loose += escapeRe(part);
          literal += part.length;
          if (part.trim().length > hint.length) hint = part.trim();
        }
      });
      patterns.push({ strict: new RegExp(strict + '$'), loose: new RegExp(loose + '$'), names, pair: index, hint, literal });
    });
  });
  patterns.sort((a, b) => b.literal - a.literal);  // the most specific wording wins

  let lang = 'el';
  const memory = new WeakMap();  // node or attribute owner -> {key: last text we wrote, pair, vars}

  // Sentences of a text ('A. B; C' -> [['A.', ''], ['B', ';'], ['C', '']]): the server joins its notes this way
  function pieces(key) {
    const out = [];
    let start = 0;
    for (let i = 0; i < key.length - 1; i++) {
      const ch = key[i];
      if (key[i + 1] !== ' ' || !'.!?…;'.includes(ch)) continue;
      out.push(ch === ';' ? [key.slice(start, i), ';'] : [key.slice(start, i + 1), '']);
      start = i + 2;
    }
    out.push([key.slice(start), '']);
    return out.filter(([t]) => t.trim());
  }

  // A text made of known sentences, each switched on its own; null unless every part is known
  function composite(key) {
    const parts = pieces(key);
    const n = parts.length;
    if (n < 2 || n > 8) return null;
    const memo = new Map();
    const solve = (i) => {  // the parts from i on, as known phrases (longest first, backing off when stuck)
      if (i === n) return [];
      if (memo.has(i)) return memo.get(i);
      let result = null;
      for (let j = n; j > i && !result; j--) {
        if (i === 0 && j === n) continue;  // the whole text was tried already
        const span = parts.slice(i, j).map(([t, sep], k) => (k < j - i - 1 ? t + sep : t)).join(' ');
        const hit = identify(span, false);
        const rest = hit && solve(j);
        if (rest) result = [{ found: hit, sep: parts[j - 1][1] }, ...rest];
      }
      memo.set(i, result);
      return result;
    };
    const found = solve(0);
    return found ? { parts: found } : null;
  }

  function matchPatterns(key, strict) {
    for (const p of patterns) {
      if (p.hint && !key.includes(p.hint)) continue;
      const m = (strict ? p.strict : p.loose).exec(key);
      if (!m) continue;
      const vars = {};
      p.names.forEach((name, k) => { vars[name] = m[k + 1]; });
      return { pair: p.pair, vars };
    }
    return null;
  }

  // Which pair (and the changing parts) a text is, or null. A changing part first stays within one sentence, so
  // several joined notes are recognised one by one; only then may it span sentences (a long error reason).
  function identify(text, allowParts = true) {
    const key = norm(text);
    if (!key || !LETTER.test(key)) return null;
    const index = exact.get(key);
    if (index !== undefined) return { pair: index, vars: null };
    return matchPatterns(key, true) || (allowParts && composite(key)) || matchPatterns(key, false);
  }

  function render(found, target) {
    // ';' between joined notes is a question mark in Greek: there it becomes '·'
    if (found.parts) {
      return found.parts.map((p) => render(p.found, target) + (p.sep === ';' && target === 'el' ? '·' : p.sep)).join(' ');
    }
    const wording = I18N_PAIRS[found.pair][target === 'en' ? 1 : 0];
    if (!found.vars) return wording;
    // a changing part may itself be a phrase ("Ready", "English"): it is switched too
    return wording.replace(/\{#?(\w+)\}/g, (_, name) => {
      const value = found.vars[name] ?? '';
      const inner = value && LETTER.test(value) ? identify(value) : null;
      return inner ? render(inner, target) : value;
    });
  }

  function text(source, target = lang) {
    const found = identify(source);
    return found ? render(found, target) : source;
  }

  // A text node or attribute: remembered, so a phrase that became empty or ambiguous still switches back
  function switched(owner, slot, current) {
    let notes = memory.get(owner);
    const known = notes && notes[slot];
    const found = known && norm(current) === known.key ? known : identify(current);
    if (!found) return null;
    const out = render(found, lang);
    if (!notes) memory.set(owner, (notes = {}));
    notes[slot] = { key: norm(out), pair: found.pair, vars: found.vars };
    return out;
  }

  function skipped(el) {
    return !el || Boolean(el.closest('[translate="no"], .notranslate')) || SKIP_TAGS.has(el.tagName);
  }

  function applyText(node) {
    const parent = node.parentElement;
    if (!parent || skipped(parent)) return;
    const raw = node.data;
    if (!LETTER.test(raw)) return;
    const out = switched(node, 'text', raw);
    if (out === null) return;
    const next = raw.match(/^\s*/)[0] + out + raw.match(/\s*$/)[0];
    if (next !== raw) node.data = next;
  }

  function applyAttr(el, name) {
    if (skipped(el) && !(el.tagName === 'TEXTAREA' && name === 'placeholder' && !el.closest('[translate="no"]'))) return;
    const raw = el.getAttribute(name);
    if (!raw || !LETTER.test(raw)) return;
    const out = switched(el, name, raw);
    if (out !== null && out !== raw) el.setAttribute(name, out);
  }

  const NO_TRANSLATE = '[translate="no"], .notranslate';

  function applyTree(root) {
    if (root.nodeType === 3) return applyText(root);
    if (root.nodeType !== 1 || root.closest(NO_TRANSLATE)) return;
    // book text, file names and glossary terms are skipped whole, not node by node
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.nodeType === 1 && n.matches(NO_TRANSLATE) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const selector = ATTRS.map((a) => `[${a}]`).join(',');
    for (let n = walker.currentNode; n; n = walker.nextNode()) {
      if (n.nodeType === 3) applyText(n);
      else if (n.matches(selector)) for (const a of ATTRS) if (n.hasAttribute(a)) applyAttr(n, a);
    }
  }

  const observer = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'characterData') applyText(r.target);
      else if (r.type === 'attributes') applyAttr(r.target, r.attributeName);
      else r.addedNodes.forEach(applyTree);
    }
  });

  function markSwitch() {
    document.querySelectorAll('[data-ui-lang]').forEach((btn) => {
      const on = btn.getAttribute('data-ui-lang') === lang;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function setLanguage(next, save = true) {
    lang = next === 'en' ? 'en' : 'el';
    if (save) {
      try { localStorage.setItem(UI_LANG_KEY, lang); } catch (_) {}
    }
    document.documentElement.lang = lang;
    applyTree(document.documentElement);
    markSwitch();
    document.dispatchEvent(new CustomEvent('bookapp:ui-lang', { detail: { lang } }));
  }

  function initialLanguage() {
    try {
      const saved = localStorage.getItem(UI_LANG_KEY);
      if (saved === 'el' || saved === 'en') return saved;
    } catch (_) {}
    const nav = (navigator.languages && navigator.languages[0]) || navigator.language || 'el';
    return /^el\b/i.test(nav) ? 'el' : (/^en\b/i.test(nav) ? 'en' : 'el');
  }

  lang = initialLanguage();
  document.documentElement.lang = lang;
  observer.observe(document.documentElement, {
    subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS,
  });
  document.addEventListener('DOMContentLoaded', () => setLanguage(lang, false));

  // Dialogs do not pass through the page: their messages are switched here
  for (const name of ['alert', 'confirm', 'prompt']) {
    const original = window[name] && window[name].bind(window);
    if (original) window[name] = (message, ...rest) => original(message == null ? message : text(String(message)), ...rest);
  }

  return { text, setLanguage, get lang() { return lang; }, _identify: identify };
})();

function setUiLanguage(lang) {
  I18N.setLanguage(lang);
}
