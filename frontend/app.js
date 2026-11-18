/* ============================================================
   DocTranslate & AudioBook — Frontend Application Logic
   ============================================================ */

'use strict';

const API = 'http://localhost:8000/api';

// ── State ──────────────────────────────────────────────────
const state = {
  tr: { jobId: null, file: null, sse: null, status: 'idle' },
  ab: { jobId: null, file: null, sse: null, status: 'idle' },
  voices: {},
  selectedVoice: '',
};

// ── Tab Switching ──────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => {
    el.classList.remove('active');
    el.setAttribute('aria-selected', 'false');
  });
  document.getElementById(`tab-${tab}`).classList.add('active');
  const btn = document.getElementById(`btn-${tab}`);
  btn.classList.add('active');
  btn.setAttribute('aria-selected', 'true');
}

// ── File Upload Handling ───────────────────────────────────
function handleDragOver(e, zoneId) {
  e.preventDefault();
  e.stopPropagation();
  document.getElementById(zoneId).classList.add('dragover');
}

function handleDragLeave(e, zoneId) {
  document.getElementById(zoneId).classList.remove('dragover');
}

function handleDrop(e, inputId, prefix) {
  e.preventDefault();
  const zoneId = prefix + '-upload-zone';
  document.getElementById(zoneId).classList.remove('dragover');
  const files = Array.from(e.dataTransfer.files || []);
  if (files.length === 0) return;
  const queueOpen = prefix === 'tr' && document.getElementById('tr-queue-card')?.style.display === 'block';
  if (prefix === 'tr' && (files.length > 1 || queueOpen)) {
    enqueueMultipleFiles(files);
  } else {
    processFile(files[0], prefix);
  }
}

function handleFileSelect(e, prefix) {
  const files = Array.from(e.target.files || []);
  if (files.length === 0) return;
  const queueOpen = prefix === 'tr' && document.getElementById('tr-queue-card')?.style.display === 'block';
  if (prefix === 'tr' && (files.length > 1 || queueOpen)) {
    enqueueMultipleFiles(files);
    e.target.value = '';
  } else {
    processFile(files[0], prefix);
  }
}

async function processFile(file, prefix) {
  const allowed = ['.pdf', '.docx', '.epub', '.cbz', '.zip'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();

  if (!allowed.includes(ext)) {
    toast(`❌ File type "${ext}" is not supported. Please use PDF, DOCX, EPUB, or CBZ.`, 'error');
    return;
  }

  state[prefix].file = file;
  state[prefix].jobId = null;
  resetProgress(prefix);

  // Show selected file UI
  showSelectedFile(prefix, file);

  // Upload to backend
  await uploadFile(prefix, file);
}

function showSelectedFile(prefix, file) {
  const iconMap = { pdf: '📕', docx: '📘', epub: '📗', cbz: '🎨', zip: '🎨' };
  const ext = file.name.split('.').pop().toLowerCase();
  const icon = iconMap[ext] || '📄';
  const sizeMB = (file.size / 1024 / 1024).toFixed(1);

  document.getElementById(`${prefix}-file-icon`).textContent = icon;
  document.getElementById(`${prefix}-file-name`).textContent = file.name;
  document.getElementById(`${prefix}-file-meta`).textContent = `${sizeMB} MB · ${ext.toUpperCase()} · Uploading...`;
  document.getElementById(`${prefix}-selected-file`).classList.add('visible');
  document.getElementById(`${prefix}-upload-zone`).style.display = 'none';
}

function removeFile(prefix) {
  state[prefix].file = null;
  state[prefix].jobId = null;
  document.getElementById(`${prefix}-selected-file`).classList.remove('visible');
  document.getElementById(`${prefix}-upload-zone`).style.display = '';
  document.getElementById(`${prefix}-start-btn`).disabled = true;
  const addQBtn = document.getElementById('tr-add-queue-btn');
  if (prefix === 'tr' && addQBtn) addQBtn.disabled = true;
  const directBtn = document.getElementById('tr-direct-polish-btn');
  if (directBtn) directBtn.disabled = true;
  resetProgress(prefix);
  if (prefix === 'ab') {
    restrictAudiobookLanguage(null);
    const transOpt = document.getElementById('ab-translate-option');
    if (transOpt) transOpt.style.display = 'none';
    const useTranslated = document.getElementById('ab-use-translated');
    if (useTranslated) useTranslated.checked = false;
  }
  if (prefix === 'tr') {
    setGraphicNovelLock(false);
    const stdBtn = document.getElementById('layout-standard');
    if (stdBtn) selectLayout('standard', stdBtn);
    updateFormatAvailability('standard', '');
  }
  // Reset file input
  const inp = document.getElementById(`${prefix}-file-input`);
  if (inp) inp.value = '';
}

function setGraphicNovelLock(isComic, reason = '', isScanned = false) {
  state.tr.isComic = !!isComic;
  const btnStd = document.getElementById('layout-standard');
  const btnLit = document.getElementById('layout-literature');
  const btnComic = document.getElementById('layout-comic');
  const directPolishBtn = document.getElementById('tr-direct-polish-btn');
  const directEditorBtn = document.getElementById('tr-direct-editor-btn');
  const hintEl = document.getElementById('comic-format-hint');
  const readingDirGroup = document.getElementById('tr-reading-dir-group');
  const covGroup = document.getElementById('tr-cover-group');
  const aiPolishChk = document.getElementById('tr-ai-polish');

  if (isComic) {
    // Lock layout strictly to Graphic Novel / Comic
    if (btnStd) {
      btnStd.disabled = true;
      btnStd.classList.add('format-btn-disabled');
      btnStd.classList.remove('active');
      btnStd.title = 'Απενεργοποιημένο — εντοπίστηκε Graphic Novel / Comic';
    }
    if (btnLit) {
      btnLit.disabled = true;
      btnLit.classList.add('format-btn-disabled');
      btnLit.classList.remove('active');
      btnLit.title = 'Απενεργοποιημένο — εντοπίστηκε Graphic Novel / Comic';
    }
    if (btnComic) {
      btnComic.disabled = false;
      btnComic.classList.remove('format-btn-disabled');
      selectLayout('comic', btnComic);
    }
    // Disable non-comic standalone text buttons
    if (directPolishBtn) {
      directPolishBtn.disabled = true;
      directPolishBtn.style.opacity = '0.45';
      directPolishBtn.title = 'Δεν ισχύει για Graphic Novels — χρησιμοποιήστε Start Translation (με ή χωρίς AI Polish checkbox)';
    }
    if (directEditorBtn) {
      directEditorBtn.disabled = true;
      directEditorBtn.style.opacity = '0.4';
      directEditorBtn.style.pointerEvents = 'none';
      directEditorBtn.title = 'Δεν ισχύει για Graphic Novels';
    }
    if (covGroup) covGroup.style.display = 'none';
    if (readingDirGroup) readingDirGroup.style.display = 'block';
    if (isScanned && aiPolishChk) {
      aiPolishChk.checked = true;
    }
    if (hintEl) {
      hintEl.style.display = 'flex';
      const detail = reason ? ` (${reason})` : '';
      hintEl.innerHTML = `<span>🎨 <strong>Graphic Novel / Comic Auto-Detected${detail}:</strong> Ενεργοποιήθηκαν αποκλειστικά οι επιλογές Graphic Novel (<strong>PDF, CBZ, CBR, EPUB</strong> &amp; LTR/RTL). Οι επιλογές κειμένου/βιβλίου απενεργοποιήθηκαν αυτόματα.</span>`;
    }
  } else {
    // Unlock all standard book/document options
    if (btnStd) {
      btnStd.disabled = false;
      btnStd.classList.remove('format-btn-disabled');
      btnStd.title = '';
    }
    if (btnLit) {
      btnLit.disabled = false;
      btnLit.classList.remove('format-btn-disabled');
      btnLit.title = '';
    }
    if (directPolishBtn) {
      directPolishBtn.disabled = !state.tr.jobId;
      directPolishBtn.style.opacity = '';
      directPolishBtn.title = '';
    }
    if (directEditorBtn) {
      directEditorBtn.disabled = false;
      directEditorBtn.style.opacity = '';
      directEditorBtn.style.pointerEvents = '';
      directEditorBtn.title = '';
    }
  }
}

async function uploadFile(prefix, file) {
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`${API}/upload`, { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Upload failed');
    }
    const data = await res.json();
    state[prefix].jobId = data.job_id;

    const pages = data.estimated_pages > 0 ? `~${data.estimated_pages} pages · ` : '';
    document.getElementById(`${prefix}-file-meta`).textContent =
      `${(file.size / 1024 / 1024).toFixed(1)} MB · ${pages}${data.file_type.toUpperCase()} · Ready`;

    document.getElementById(`${prefix}-start-btn`).disabled = false;
    const addQBtn = document.getElementById('tr-add-queue-btn');
    if (prefix === 'tr' && addQBtn) addQBtn.disabled = false;
    const directBtn = document.getElementById('tr-direct-polish-btn');
    if (directBtn) directBtn.disabled = false;
    toast(`✅ "${file.name}" uploaded successfully.`, 'success');

    // Direct upload in Audiobook tab: lock Audio Language to detected document language
    if (prefix === 'ab') {
      const transOpt = document.getElementById('ab-translate-option');
      if (transOpt) transOpt.style.display = 'none';
      const useTranslated = document.getElementById('ab-use-translated');
      if (useTranslated) useTranslated.checked = false;
      restrictAudiobookLanguage(data.detected_language || null);
    }

    refreshHistory();
    if (prefix === 'tr') {
      state.tr.file = file;
      const ext = file.name.split('.').pop().toLowerCase();
      const autoDetectedComic = Boolean(data.is_comic) || ['cbz', 'cbr', 'zip'].includes(ext);
      if (autoDetectedComic) {
        setGraphicNovelLock(true, data.comic_reason || '', Boolean(data.is_scanned));
        toast(`🎨 Εντοπίστηκε Graphic Novel / Comic! Ενεργοποιήθηκαν αποκλειστικά οι επιλογές Graphic Novel.`, 'info');
      } else {
        setGraphicNovelLock(false);
        const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
        if (layout === 'comic') {
          const stdBtn = document.getElementById('layout-standard');
          if (stdBtn) selectLayout('standard', stdBtn);
        } else {
          updateFormatAvailability(layout, ext);
        }
        checkCoverImage(data.job_id);

        // Auto-Genre Detection
        detectDocumentGenre(data.job_id, data.file_type);
      }
    }
  } catch (err) {
    toast(`❌ Upload error: ${err.message}`, 'error');
    removeFile(prefix);
  }
}

async function detectDocumentGenre(jobId, fileType) {
  try {
    const prevRes = await fetch(`${API}/preview/${jobId}`);
    if (!prevRes.ok) return;
    const prevData = await prevRes.json();
    const sample = prevData.preview_text || '';
    if (!sample.trim()) return;

    const res = await fetch(`${API}/detect-genre`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample_text: sample.substring(0, 3500), file_type: fileType }),
    });
    if (res.ok) {
      const gInfo = await res.json();
      showGenreHint(gInfo);
    }
  } catch (e) {
    console.debug('Genre detection skipped:', e);
  }
}

function showGenreHint(gInfo) {
  const hintEl = document.getElementById('tr-genre-hint');
  if (!hintEl) return;
  const genreTitles = {
    literature: '📖 Λογοτεχνικό (Literature)',
    poetry: '🪶 Ποίηση / Στίχοι (Poetry)',
    technical: '💻 Τεχνικό / Πληροφορική (Technical)',
    formal: '🏛️ Επίσημο / Διοικητικό (Formal)',
    comic: '🎨 Graphic Novel / Comic',
  };
  const title = genreTitles[gInfo.genre] || gInfo.genre;
  const confPct = Math.round((gInfo.confidence || 0.8) * 100);
  hintEl.innerHTML = `
    <span>💡 <strong>Ανιχνεύθηκε ύφος:</strong> ${title} (${confPct}% βεβαιότητα). ${gInfo.reason || ''}</span>
    <button class="btn-sm btn-outline" style="margin-left:auto; padding:3px 10px; font-size:0.75rem; white-space:nowrap" onclick="applyDetectedGenre('${gInfo.genre}')">Εφαρμογή Προτεινόμενου</button>
  `;
  hintEl.style.display = 'flex';
}

function applyDetectedGenre(genre) {
  if (genre === 'comic') {
    const b = document.getElementById('layout-comic');
    if (b) selectLayout('comic', b);
  } else if (genre === 'literature' || genre === 'poetry') {
    const b = document.getElementById('layout-literature');
    if (b) selectLayout('literature', b);
  } else {
    const b = document.getElementById('layout-standard');
    if (b) selectLayout('standard', b);
  }
  toast(`✅ Εφαρμόστηκε στυλ: ${genre}`, 'success');
}

// ── Language Swap (Translate Tab) ──────────────────────────
const langConfig = {
  english: { label: '🇬🇧 English', code: 'english' },
  greek:   { label: '🇬🇷 Greek',   code: 'greek' },
};

function swapLangs() {
  const src = document.getElementById('tr-source-lang').value;
  const tgt = document.getElementById('tr-target-lang').value;
  setLangs(tgt, src);
}

function setLangs(src, tgt) {
  document.getElementById('tr-source-lang').value = src;
  document.getElementById('tr-target-lang').value = tgt;
  document.getElementById('tr-source-display').textContent = langConfig[src].label;
  document.getElementById('tr-target-display').textContent = langConfig[tgt].label;
}

// ── Output Format & Layout Selection ─────────────────────────
function updateFormatAvailability(layout, fileExt) {
  const isComic = layout === 'comic' || ['cbz', 'cbr'].includes(fileExt);

  const btnTxt = document.getElementById('fmt-txt');
  const btnDocx = document.getElementById('fmt-docx');
  const btnPdf = document.getElementById('fmt-pdf');
  const btnEpub = document.getElementById('fmt-epub');
  const btnCbz = document.getElementById('fmt-cbz');
  const btnCbr = document.getElementById('fmt-cbr');
  const hintEl = document.getElementById('comic-format-hint');
  const badgeNote = document.getElementById('tr-format-badge-note');

  let curFmt = document.getElementById('tr-output-format')?.value || 'txt';

  if (isComic) {
    // Disable TXT and DOCX for Graphic Novels (artwork & speech balloons must be preserved)
    if (btnTxt) {
      btnTxt.disabled = true;
      btnTxt.classList.add('format-btn-disabled');
      btnTxt.classList.remove('active');
      btnTxt.title = 'Μη διαθέσιμο για Graphic Novels (διατηρούνται εικόνες & μπαλόνια διαλόγων)';
    }
    if (btnDocx) {
      btnDocx.disabled = true;
      btnDocx.classList.add('format-btn-disabled');
      btnDocx.classList.remove('active');
      btnDocx.title = 'Μη διαθέσιμο για Graphic Novels (διατηρούνται εικόνες & μπαλόνια διαλόγων)';
    }

    // Enable comic formats: PDF, CBZ, CBR, EPUB
    [btnPdf, btnEpub, btnCbz, btnCbr].forEach((b) => {
      if (b) {
        b.disabled = false;
        b.classList.remove('format-btn-disabled');
        b.style.display = 'flex';
      }
    });

    if (hintEl) hintEl.style.display = 'flex';
    if (badgeNote) badgeNote.textContent = '(PDF, CBZ, CBR, EPUB)';

    // If currently on disabled format (txt or docx), switch to comic format
    if (curFmt === 'txt' || curFmt === 'docx') {
      const preferred = fileExt === 'cbr' ? btnCbr : (fileExt === 'cbz' ? btnCbz : btnPdf);
      if (preferred) {
        selectFormat(preferred.dataset.format, preferred);
      }
    }
  } else {
    // Standard / Literature: Enable TXT, DOCX, PDF, EPUB
    [btnTxt, btnDocx, btnPdf, btnEpub].forEach((b) => {
      if (b) {
        b.disabled = false;
        b.classList.remove('format-btn-disabled');
        b.style.display = 'flex';
      }
    });

    // Disable comic-only archives (CBZ, CBR) for standard text
    if (btnCbz) {
      btnCbz.disabled = true;
      btnCbz.classList.add('format-btn-disabled');
      btnCbz.classList.remove('active');
      btnCbz.title = 'Διαθέσιμο μόνο σε Graphic Novels / Comics';
    }
    if (btnCbr) {
      btnCbr.disabled = true;
      btnCbr.classList.add('format-btn-disabled');
      btnCbr.classList.remove('active');
      btnCbr.title = 'Διαθέσιμο μόνο σε Graphic Novels / Comics';
    }

    if (hintEl) hintEl.style.display = 'none';
    if (badgeNote) badgeNote.textContent = '';

    // If currently on cbz or cbr, switch to pdf or docx
    if (curFmt === 'cbz' || curFmt === 'cbr') {
      if (btnPdf) selectFormat('pdf', btnPdf);
    }
  }
}

function selectFormat(fmt, btn) {
  if (!btn) return;
  if (btn.disabled || btn.classList.contains('format-btn-disabled')) {
    toast(`⚠️ Το format ${fmt.toUpperCase()} είναι απενεργοποιημένο για Graphic Novels. Επιλέξτε PDF, CBZ, CBR ή EPUB.`, 'info');
    return;
  }
  // Deselect only format buttons (not layout buttons)
  document.querySelectorAll('#tr-format-selector .format-btn').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tr-output-format').value = fmt;
  // Update download button label immediately
  const label = fmt.toUpperCase();
  const labelEl = document.getElementById('tr-format-label');
  if (labelEl) labelEl.textContent = label;

  // Also update result card text if already completed
  const metaEl = document.getElementById('tr-result-meta');
  if (metaEl) {
    metaEl.textContent = `Your document has been translated. Click below to download the ${label} file.`;
  }

  // Update download button href directly
  const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
  const dlBtn = document.getElementById('tr-download-btn');
  if (dlBtn && state.tr.jobId) {
    dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}&layout=${layout}`;
  }
}

function selectLayout(layout, btn) {
  if (btn && btn.disabled) {
    toast('Αυτή η επιλογή είναι απενεργοποιημένη για Graphic Novels / Comics.', 'info');
    return;
  }
  document.querySelectorAll('#tr-layout-selector .format-btn').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tr-layout-mode').value = layout;

  const currentExt = state.tr.file ? state.tr.file.name.split('.').pop().toLowerCase() : '';
  updateFormatAvailability(layout, currentExt);

  if (layout === 'comic') {
    const covGroup = document.getElementById('tr-cover-group');
    if (covGroup) covGroup.style.display = 'none';
  } else {
    const covGroup = document.getElementById('tr-cover-group');
    if (covGroup && state.tr.jobId) {
      covGroup.style.display = 'block';
    }
  }

  const readingDirGroup = document.getElementById('tr-reading-dir-group');
  if (readingDirGroup) {
    readingDirGroup.style.display = (layout === 'comic' || currentExt === 'cbz' || currentExt === 'cbr') ? 'block' : 'none';
  }

  const fmt = document.getElementById('tr-output-format')?.value || 'txt';
  const dlBtn = document.getElementById('tr-download-btn');
  if (dlBtn && state.tr.jobId) {
    dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}&layout=${layout}`;
  }
}

// ── Book Cover Image Handling ──────────────────────────────
async function checkCoverImage(jobId) {
  if (!jobId) return;
  const covGroup = document.getElementById('tr-cover-group');
  const thumb = document.getElementById('tr-cover-thumb');
  const thumbContainer = document.getElementById('tr-cover-thumb-container');
  const statusEl = document.getElementById('tr-cover-status');
  const removeBtn = document.getElementById('tr-cover-remove-btn');

  if (covGroup) covGroup.style.display = 'block';

  try {
    const res = await fetch(`${API}/cover/${jobId}`);
    if (res.ok) {
      if (thumb) thumb.src = `${API}/cover/${jobId}?t=${Date.now()}`;
      if (thumbContainer) thumbContainer.style.display = 'block';
      if (statusEl) statusEl.innerHTML = '<span style="color:var(--emerald);font-weight:600">✔ Εξώφυλλο ενεργό</span> (Περιλαμβάνεται αυτόματα στην 1η σελίδα σε PDF, EPUB &amp; DOCX).';
      if (removeBtn) removeBtn.style.display = 'inline-flex';
    } else {
      if (thumbContainer) thumbContainer.style.display = 'none';
      if (statusEl) statusEl.textContent = 'Δεν έχει οριστεί εξώφυλλο. Μπορείτε να ανεβάσετε οποιαδήποτε εικόνα (JPG, PNG, WebP).';
      if (removeBtn) removeBtn.style.display = 'none';
    }
  } catch (_) {
    if (thumbContainer) thumbContainer.style.display = 'none';
    if (removeBtn) removeBtn.style.display = 'none';
  }
}

async function handleCoverUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  const jobId = state.tr.jobId;
  if (!jobId) {
    toast('Please upload a document first before adding a cover.', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  try {
    toast('Uploading book cover image...', 'info');
    const res = await fetch(`${API}/cover/${jobId}`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error('Cover upload failed');
    toast('✅ Book cover updated successfully! Included in PDF, EPUB & DOCX.', 'success');
    await checkCoverImage(jobId);
  } catch (err) {
    toast(`Failed to upload cover: ${err.message}`, 'error');
  }
}

async function removeCoverImage() {
  const jobId = state.tr.jobId;
  if (!jobId) return;
  try {
    await fetch(`${API}/cover/${jobId}`, { method: 'DELETE' });
    toast('Book cover removed.', 'info');
    await checkCoverImage(jobId);
  } catch (err) {
    toast(`Failed to remove cover: ${err.message}`, 'error');
  }
}

// ── Voice Selection (Audiobook Tab) ────────────────────────
async function loadVoices() {
  try {
    const res = await fetch(`${API}/voices`);
    state.voices = await res.json();
    updateVoices();
  } catch (e) {
    console.error('Could not load voices:', e);
  }
}

function detectTextLanguage(text) {
  if (!text || !text.trim()) return null;
  const sample = text.slice(0, 3000);
  const greekMatches = sample.match(/[\u0370-\u03FF\u1F00-\u1FFF]/g) || [];
  const latinMatches = sample.match(/[A-Za-z]/g) || [];
  if (greekMatches.length === 0 && latinMatches.length === 0) return null;
  return greekMatches.length >= latinMatches.length ? 'greek' : 'english';
}

function restrictAudiobookLanguage(allowedLang) {
  const langSelect = document.getElementById('ab-lang-select');
  if (!langSelect) return;
  Array.from(langSelect.options).forEach(opt => {
    const blocked = Boolean(allowedLang && opt.value !== allowedLang);
    opt.disabled = blocked;
    opt.hidden = blocked;
  });
  if (allowedLang) {
    langSelect.value = allowedLang;
  }
  updateVoices();
}

function updateVoices() {
  const lang = document.getElementById('ab-lang-select').value;
  const transOpt = document.getElementById('ab-translate-option');
  const useTranslated = document.getElementById('ab-use-translated');
  if (transOpt && transOpt.style.display !== 'none' && useTranslated) {
    const targetLang = document.getElementById('tr-target-lang')?.value || 'greek';
    useTranslated.checked = (lang === targetLang);
  }
  const voices = state.voices[lang] || {};
  const grid = document.getElementById('ab-voice-grid');
  const voiceIcons = {
    'Athina (Female)': '👩',
    'Nestoras (Male)': '👨',
    'Aria (Female)': '👩',
    'Guy (Male)': '👨',
    'Jenny (Female)': '👩',
    'Davis (Male)': '👨',
    'Emma (Female)': '👩',
    'Ryan (Male)': '👨',
  };

  grid.innerHTML = '';
  const entries = Object.entries(voices);
  if (entries.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem">No voices available for this language.</p>';
    return;
  }

  entries.forEach(([name, code], i) => {
    const card = document.createElement('div');
    card.className = 'voice-card' + (i === 0 ? ' selected' : '');
    card.dataset.voice = name;
    card.innerHTML = `
      <div class="voice-card-icon">${voiceIcons[name] || '🎙️'}</div>
      <div class="voice-card-name">${name.replace(' (Female)', ' ♀').replace(' (Male)', ' ♂')}</div>
      <div class="voice-card-lang">${code}</div>
      <button class="voice-preview-btn" onclick="playVoicePreview('${code}', event)" title="Ακρόαση δείγματος">🔊 Ακρόαση</button>
    `;
    card.onclick = () => selectVoice(name, card);
    grid.appendChild(card);
  });

  // Populate dialogue voice select for multi-voice mode
  const diagSelect = document.getElementById('ab-dialogue-voice-select');
  if (diagSelect) {
    diagSelect.innerHTML = entries.map(([name, code]) => `<option value="${name}">${name}</option>`).join('');
    if (entries.length > 1) {
      diagSelect.selectedIndex = 1; // Default dialogue to second voice
    }
  }

  // Auto-select first voice
  if (entries.length > 0) {
    state.selectedVoice = entries[0][0];
    document.getElementById('ab-voice-selected').value = entries[0][0];
  }
}

let currentAudioPreview = null;
function playVoicePreview(voiceCode, event) {
  if (event) event.stopPropagation();
  if (currentAudioPreview) {
    currentAudioPreview.pause();
    currentAudioPreview = null;
  }
  const url = `${API}/tts/preview?voice=${encodeURIComponent(voiceCode)}`;
  currentAudioPreview = new Audio(url);
  toast(`🔊 Παραγωγή δείγματος για ${voiceCode}...`, 'info');
  currentAudioPreview.play().catch(e => {
    console.debug('Preview audio playback failed:', e);
  });
}

function toggleMultiVoiceSelect() {
  const chk = document.getElementById('ab-multi-voice');
  const container = document.getElementById('ab-dialogue-voice-container');
  if (container) {
    container.style.display = chk && chk.checked ? 'block' : 'none';
  }
}

function selectVoice(name, card) {
  document.querySelectorAll('.voice-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  state.selectedVoice = name;
  document.getElementById('ab-voice-selected').value = name;
}

// ── Start Translation ──────────────────────────────────────
async function startTranslation() {
  const jobId = state.tr.jobId;
  if (!jobId) { toast('Please upload a document first.', 'error'); return; }

  const sourceLang = document.getElementById('tr-source-lang').value;
  const targetLang = document.getElementById('tr-target-lang').value;
  let outputFormat = document.getElementById('tr-output-format').value || 'txt';
  const layoutMode = document.getElementById('tr-layout-mode')?.value || 'standard';
  if (layoutMode === 'comic' && (outputFormat === 'txt' || outputFormat === 'docx')) {
    outputFormat = 'pdf';
    document.getElementById('tr-output-format').value = 'pdf';
  }
  const aiPolish = document.getElementById('tr-ai-polish')?.checked || false;
  const apiKey = localStorage.getItem('gemini_api_key') || null;
  const readingDirEl = document.querySelector('input[name="tr-reading-dir"]:checked');
  const readingDirection = readingDirEl ? readingDirEl.value : 'ltr';

  // Update download button label to show chosen format
  const labelEl = document.getElementById('tr-format-label');
  if (labelEl) labelEl.textContent = outputFormat.toUpperCase();

  // Show progress UI
  closeEditor();
  document.getElementById('tr-progress-card').style.display = 'block';
  document.getElementById('tr-result-card').classList.remove('visible');
  document.getElementById('tr-error-card').classList.remove('visible');
  document.getElementById('tr-progress-detail').textContent = '';
  document.getElementById('tr-start-btn').disabled = true;
  const trCancelBtn = document.getElementById('tr-cancel-btn');
  if (trCancelBtn) {
    trCancelBtn.disabled = false;
    trCancelBtn.innerHTML = '🛑 Cancel Translation';
  }
  setStatusBadge('tr', 'running');

  try {
    const res = await fetch(`${API}/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        source_lang: sourceLang,
        target_lang: targetLang,
        output_format: outputFormat,
        layout_mode: layoutMode,
        reading_direction: readingDirection,
        ai_polish: aiPolish,
        api_key: apiKey || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to start translation');
    }

    // Connect SSE for progress
    connectSSE('tr', jobId);
  } catch (err) {
    showError('tr', err.message);
    document.getElementById('tr-start-btn').disabled = false;
  }
}

// ── Narration Style & Prosody Sliders ───────────────────────────
function onNarrationStyleChange() {
  const styleRaw = document.getElementById('ab-narration-style')?.value || 'literature:-12%';
  const [narrationStyle, rateStr] = styleRaw.split(':');
  if (rateStr) {
    const rateVal = parseInt(rateStr.replace('%', '').replace('+', ''), 10);
    const slider = document.getElementById('ab-speed-slider');
    const label = document.getElementById('ab-speed-label');
    if (slider) slider.value = rateVal;
    if (label) label.textContent = rateVal >= 0 ? `+${rateVal}%` : `${rateVal}%`;
  }
  // Auto-adjust default pitch for the selected style
  const pitchSlider = document.getElementById('ab-pitch-slider');
  if (pitchSlider) {
    let defaultPitch = -1;
    if (narrationStyle === 'poetry') defaultPitch = -2;
    else if (narrationStyle === 'standard') defaultPitch = 0;
    pitchSlider.value = defaultPitch;
    onPitchSliderInput(defaultPitch);
  }
}

function onSpeedSliderInput(val) {
  const num = parseInt(val, 10);
  const label = document.getElementById('ab-speed-label');
  if (label) {
    label.textContent = num >= 0 ? `+${num}%` : `${num}%`;
  }
}

function onPitchSliderInput(val) {
  const num = parseInt(val, 10);
  const label = document.getElementById('ab-pitch-label');
  if (label) {
    const sign = num >= 0 ? `+${num}Hz` : `${num}Hz`;
    let desc = 'Natural / Φυσική';
    if (num <= -3) desc = 'Very Deep / Επιβλητική';
    else if (num === -2) desc = 'Deep & Theatrical / Θεατρική';
    else if (num === -1) desc = 'Warm / Ζεστή';
    else if (num === 1) desc = 'Clear / Καθαρή';
    else if (num >= 2) desc = 'Bright & Lyrical / Λυρική';
    label.textContent = `${sign} (${desc})`;
  }
}

// ── Start Audiobook ────────────────────────────────────────
async function startAudiobook() {
  const jobId = state.ab.jobId;
  if (!jobId) { toast('Please upload a document first.', 'error'); return; }

  const language = document.getElementById('ab-lang-select').value;
  const voiceName = document.getElementById('ab-voice-selected').value || state.selectedVoice;
  const useTranslated = document.getElementById('ab-use-translated')?.checked || false;
  const aiPolish = document.getElementById('ab-ai-polish')?.checked || false;
  const apiKey = localStorage.getItem('gemini_api_key') || null;
  const styleRaw = document.getElementById('ab-narration-style')?.value || 'literature:-12%';
  const [narrationStyle] = styleRaw.split(':');
  const sliderEl = document.getElementById('ab-speed-slider');
  const sliderVal = sliderEl ? parseInt(sliderEl.value, 10) : -12;
  const narrationRate = sliderVal >= 0 ? `+${sliderVal}%` : `${sliderVal}%`;
  const pitchEl = document.getElementById('ab-pitch-slider');
  const pitchVal = pitchEl ? parseInt(pitchEl.value, 10) : -1;
  const narrationPitch = pitchVal >= 0 ? `+${pitchVal}Hz` : `${pitchVal}Hz`;

  if (!voiceName) { toast('Please select a voice first.', 'error'); return; }

  // Show progress UI
  document.getElementById('ab-progress-card').style.display = 'block';
  document.getElementById('ab-result-card').classList.remove('visible');
  document.getElementById('ab-error-card').classList.remove('visible');
  document.getElementById('ab-start-btn').disabled = true;
  const abCancelBtn = document.getElementById('ab-cancel-btn');
  if (abCancelBtn) {
    abCancelBtn.disabled = false;
    abCancelBtn.innerHTML = '🛑 Cancel Audiobook';
  }
  setStatusBadge('ab', 'running');

  try {
    const isMultiVoice = document.getElementById('ab-multi-voice')?.checked || false;
    const dialogueVoice = isMultiVoice ? (document.getElementById('ab-dialogue-voice-select')?.value || null) : null;

    const res = await fetch(`${API}/audiobook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        language,
        voice_name: voiceName,
        dialogue_voice: dialogueVoice,
        use_translated: useTranslated,
        narration_style: narrationStyle,
        rate: narrationRate,
        pitch: narrationPitch,
        ai_polish: aiPolish,
        api_key: apiKey || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to start audiobook generation');
    }

    connectSSE('ab', jobId);
  } catch (err) {
    showError('ab', err.message);
    document.getElementById('ab-start-btn').disabled = false;
  }
}

// ── SSE Progress Stream ────────────────────────────────────
function connectSSE(prefix, jobId) {
  if (state[prefix].sse) {
    state[prefix].sse.close();
  }

  const sse = new EventSource(`${API}/progress/${jobId}`);
  state[prefix].sse = sse;

  sse.onmessage = (event) => {
    const data = JSON.parse(event.data);
    updateProgress(prefix, data);

    if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
      sse.close();
      state[prefix].sse = null;
    }
  };

  sse.onerror = () => {
    console.warn('SSE connection lost, falling back to polling.');
    sse.close();
    state[prefix].sse = null;
    pollProgress(prefix, jobId);
  };
}

function pollProgress(prefix, jobId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`${API}/status/${jobId}`);
      const data = await res.json();
      updateProgress(prefix, data);
      if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
        clearInterval(interval);
      }
    } catch (e) {
      clearInterval(interval);
    }
  }, 2000);
}

function updateProgress(prefix, data) {
  const pct = data.progress || 0;
  const step = data.current_step || '';
  state[prefix].status = data.status || 'running';

  // Keep tab button label updated with live percentage while running
  const tabBtnId = prefix === 'tr' ? 'btn-translate' : 'btn-audiobook';
  const defaultTabText = prefix === 'tr' ? 'Translate Document' : 'Generate Audiobook';
  const tabLabelEl = document.querySelector(`#${tabBtnId} .tab-label`);
  if (tabLabelEl) {
    tabLabelEl.textContent = data.status === 'running' ? `${defaultTabText} · ${pct}%` : defaultTabText;
  }

  document.getElementById(`${prefix}-progress-pct`).textContent = `${pct}%`;
  document.getElementById(`${prefix}-progress-bar`).style.width = `${pct}%`;
  document.getElementById(`${prefix}-progress-step`).textContent = step;

  // Show detail while actively running
  const detailEl = document.getElementById(`${prefix}-progress-detail`);
  if (data.total_chunks > 0 && data.status !== 'done') {
    if (prefix === 'tr') {
      const isBatchMode = (data.current_step || '').toLowerCase().includes('batch');
      detailEl.textContent = isBatchMode
        ? `Completed ${data.done_chunks} of ${data.total_chunks} AI batches (~4–5 pages each)`
        : `Translated ${data.done_chunks} of ${data.total_chunks} pages`;
    } else {
      detailEl.textContent = `Generated audio part ${data.done_chunks} of ${data.total_chunks}`;
    }
  } else if (data.status === 'done') {
    detailEl.textContent = '';
  }

  if (data.status === 'done') {
    setStatusBadge(prefix, 'done');
    document.getElementById(`${prefix}-progress-bar`).classList.remove('shimmer');
    document.getElementById(`${prefix}-progress-step`).textContent = '✅ Complete';
    document.getElementById(`${prefix}-start-btn`).disabled = false;
    showResult(prefix, data);
    refreshHistory();
    toast(prefix === 'tr' ? '✅ Translation complete!' : '🎉 Audiobook ready!', 'success');
  } else if (data.status === 'error') {
    setStatusBadge(prefix, 'error');
    showError(prefix, data.error || 'An unknown error occurred.');
    document.getElementById(`${prefix}-start-btn`).disabled = false;
    refreshHistory();
  } else if (data.status === 'cancelled') {
    setStatusBadge(prefix, 'cancelled');
    document.getElementById(`${prefix}-progress-bar`).classList.remove('shimmer');
    document.getElementById(`${prefix}-progress-step`).textContent = '🛑 Cancelled';
    if (detailEl) detailEl.textContent = 'Process was cancelled.';
    document.getElementById(`${prefix}-start-btn`).disabled = false;
    const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
    if (cancelBtn) {
      cancelBtn.disabled = false;
      cancelBtn.innerHTML = prefix === 'tr' ? '🛑 Cancel Translation' : '🛑 Cancel Audiobook';
    }
    refreshHistory();
  }
}

async function cancelJob(prefix) {
  const jobId = state[prefix]?.jobId;
  if (!jobId) return;

  const btn = document.getElementById(`${prefix}-cancel-btn`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Cancelling...';
  }

  try {
    const res = await fetch(`${API}/jobs/${jobId}/cancel`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to cancel job');
    }
    toast(prefix === 'tr' ? 'Translation cancelled.' : 'Audiobook generation cancelled.', 'info');
  } catch (e) {
    toast(`Cancellation error: ${e.message}`, 'error');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = prefix === 'tr' ? '🛑 Cancel Translation' : '🛑 Cancel Audiobook';
    }
  }
}

// ── UI Helpers ─────────────────────────────────────────────
function resetProgress(prefix) {
  document.getElementById(`${prefix}-progress-card`).style.display = 'none';
  document.getElementById(`${prefix}-result-card`).classList.remove('visible');
  document.getElementById(`${prefix}-error-card`).classList.remove('visible');
  document.getElementById(`${prefix}-progress-bar`).style.width = '0%';
  document.getElementById(`${prefix}-progress-bar`).classList.add('shimmer');
  document.getElementById(`${prefix}-progress-pct`).textContent = '0%';
  document.getElementById(`${prefix}-start-btn`).disabled = true;
  const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
  if (cancelBtn) {
    cancelBtn.disabled = false;
    cancelBtn.innerHTML = prefix === 'tr' ? '🛑 Cancel Translation' : '🛑 Cancel Audiobook';
  }
  const directBtn = document.getElementById('tr-direct-polish-btn');
  if (directBtn) directBtn.disabled = true;

  if (prefix === 'tr') {
    closeEditor();
  }
  state[prefix].status = 'idle';
  const tabBtnId = prefix === 'tr' ? 'btn-translate' : 'btn-audiobook';
  const defaultTabText = prefix === 'tr' ? 'Translate Document' : 'Generate Audiobook';
  const tabLabelEl = document.querySelector(`#${tabBtnId} .tab-label`);
  if (tabLabelEl) tabLabelEl.textContent = defaultTabText;
}

function showResult(prefix, data) {
  const card = document.getElementById(`${prefix}-result-card`);
  const meta = document.getElementById(`${prefix}-result-meta`);
  if (prefix === 'tr') {
    const fmt = (document.getElementById('tr-output-format')?.value || 'txt').toLowerCase();
    const label = fmt.toUpperCase();
    const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
    if (layout === 'comic') {
      meta.textContent = 'Το Graphic Novel / Comic μεταφράστηκε με επιτυχία! Η εικονογράφηση διατηρήθηκε 100% και τα μπαλόνια διαλόγου αποδόθηκαν στα Ελληνικά.';
    } else {
      meta.textContent = `Your document has been translated. Click below to download the ${label} file.`;
    }
    // Keep format label in download button in sync
    const labelEl = document.getElementById('tr-format-label');
    if (labelEl) {
      labelEl.textContent = layout === 'comic' ? 'Graphic Novel (PDF)' : label;
    }
    const dlBtn = document.getElementById('tr-download-btn');
    if (dlBtn && state.tr.jobId) {
      dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}&layout=${layout}`;
    }
    const audioLangSelect = document.getElementById('tr-audio-lang');
    const targetLang = document.getElementById('tr-target-lang')?.value || 'greek';
    if (audioLangSelect) {
      audioLangSelect.value = targetLang;
    }
  } else {
    meta.textContent = 'Your audiobook has been generated. Click below to download the MP3 file.';
  }
  card.classList.add('visible');
}

function showError(prefix, msg) {
  document.getElementById(`${prefix}-error-msg`).textContent = msg;
  document.getElementById(`${prefix}-error-card`).classList.add('visible');
}

function setStatusBadge(prefix, status) {
  const badge = document.getElementById(`${prefix}-status-badge`);
  badge.className = `status-badge status-${status}`;
  const labels = { idle: 'Idle', running: 'Running', done: 'Complete', error: 'Error', cancelled: 'Cancelled' };
  badge.innerHTML = `<span class="status-dot"></span> ${labels[status] || status}`;
}

async function downloadOutput(prefix) {
  const jobId = state[prefix].jobId;
  if (!jobId) return;
  if (prefix === 'tr') {
    const fmt = document.getElementById('tr-output-format')?.value || 'txt';
    const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
    const targetUrl = `${API}/download/${jobId}?format=${fmt}&layout=${layout}`;
    window.location.href = targetUrl;
  } else {
    window.location.href = `${API}/download/${jobId}`;
  }
}

function sendToAudiobook() {
  if (!state.tr.jobId) return;
  // Transfer job ID and file metadata to the audiobook tab
  state.ab.jobId = state.tr.jobId;
  state.ab.file = state.tr.file;

  const rawTrName = document.getElementById('tr-file-name')?.textContent;
  const rawTrMeta = document.getElementById('tr-file-meta')?.textContent;
  const trName = (rawTrName && rawTrName !== 'filename.pdf') ? rawTrName : 'Document';
  const trMeta = (rawTrMeta && rawTrMeta !== 'Loading...') ? rawTrMeta : 'Ready';

  const abName = document.getElementById('ab-file-name');
  const abMeta = document.getElementById('ab-file-meta');
  if (abName) abName.textContent = trName;
  if (abMeta) abMeta.textContent = trMeta;

  document.getElementById('ab-upload-zone').style.display = 'none';
  document.getElementById('ab-selected-file').style.display = 'flex';
  document.getElementById('ab-start-btn').disabled = false;

  const sourceLang = document.getElementById('tr-source-lang')?.value || 'english';
  const targetLang = document.getElementById('tr-target-lang')?.value || 'greek';
  const chosenLang = document.getElementById('tr-audio-lang')?.value || targetLang;
  const shouldUseTranslated = (chosenLang === targetLang);

  // Both original and translated languages are available when coming from Translate
  restrictAudiobookLanguage(null);

  // Set language dropdown to match the chosen audiobook language and refresh voice cards
  const langSelect = document.getElementById('ab-lang-select');
  if (langSelect) {
    langSelect.value = chosenLang;
    updateVoices();
  }

  // Sync the "Use previously translated text" checkbox with chosen language
  const transOpt = document.getElementById('ab-translate-option');
  if (transOpt) transOpt.style.display = 'block';
  const useTranslated = document.getElementById('ab-use-translated');
  if (useTranslated) useTranslated.checked = shouldUseTranslated;
  const useTranslatedLabel = document.getElementById('ab-use-translated-label');
  if (useTranslatedLabel) {
    const tgtName = targetLang === 'greek' ? 'Greek' : 'English';
    const srcName = sourceLang === 'greek' ? 'Greek' : 'English';
    useTranslatedLabel.textContent = `Use translated text (${tgtName}) — uncheck to narrate original (${srcName})`;
  }

  // Switch to the Audiobook tab
  switchTab('audiobook');
  const langLabel = chosenLang === 'greek' ? 'Greek' : 'English';
  const sourceDesc = shouldUseTranslated ? 'translated text' : 'original document';
  toast(`Ready to create ${langLabel} audiobook from ${sourceDesc}!`, 'info');
}

function syncAudiobookLangWithSource() {
  const useTranslated = document.getElementById('ab-use-translated')?.checked;
  const sourceLang = document.getElementById('tr-source-lang')?.value || 'english';
  const targetLang = document.getElementById('tr-target-lang')?.value || 'greek';
  const langSelect = document.getElementById('ab-lang-select');
  if (langSelect) {
    langSelect.value = useTranslated ? targetLang : sourceLang;
    updateVoices();
  }
}

// ── History ────────────────────────────────────────────────
async function refreshHistory() {
  try {
    const res = await fetch(`${API}/jobs`);
    const jobs = await res.json();
    renderHistory(jobs);
  } catch (e) {
    console.warn('Could not refresh history:', e);
  }
}

function renderHistory(jobs) {
  const grid = document.getElementById('history-grid');
  const clearBtn = document.getElementById('clear-history-btn');

  if (!jobs || jobs.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted); font-size:0.9rem;">No jobs yet. Upload a document to get started.</p>';
    if (clearBtn) clearBtn.style.display = 'none';
    return;
  }

  if (clearBtn) clearBtn.style.display = 'inline-flex';

  const modeIcon = { translate: '🌐', audiobook: '🎧', '': '📄' };
  const statusIcon = { done: '✅', running: '⏳', error: '❌', idle: '🔵' };

  grid.innerHTML = jobs.map(j => `
    <div class="history-item" onclick="loadHistoryJob('${j.job_id}', '${j.mode || ''}')">
      <span class="history-icon">${modeIcon[j.mode] || '📄'}</span>
      <div class="history-info">
        <div class="history-name">${escHtml(j.file_name)}</div>
        <div class="history-meta">
          ${j.mode ? j.mode.charAt(0).toUpperCase() + j.mode.slice(1) : 'Uploaded'} ·
          ${statusIcon[j.status] || ''} ${j.status}
          ${j.progress > 0 && j.status !== 'done' ? `· ${j.progress}%` : ''}
        </div>
      </div>
      ${j.has_output ? `<span style="color:var(--emerald);font-size:0.8rem;font-weight:600">⬇️ Ready</span>` : ''}
      <button class="history-delete-btn" onclick="deleteHistoryJob(event, '${j.job_id}')" title="Delete this job">✕</button>
    </div>
  `).join('');
}

async function deleteHistoryJob(event, jobId) {
  event.stopPropagation();
  try {
    const res = await fetch(`${API}/jobs/${jobId}`, { method: 'DELETE' });
    if (res.ok) {
      toast('Job removed from history.', 'info');
      if (state.tr.jobId === jobId) resetProgress('tr');
      if (state.ab.jobId === jobId) resetProgress('ab');
      await refreshHistory();
    }
  } catch (err) {
    toast('Failed to delete job.', 'error');
  }
}

async function clearAllHistory() {
  if (!confirm('Are you sure you want to delete all session history and temporary files?')) {
    return;
  }
  try {
    const res = await fetch(`${API}/jobs`, { method: 'DELETE' });
    if (res.ok) {
      toast('All session history deleted.', 'success');
      resetProgress('tr');
      resetProgress('ab');
      await refreshHistory();
    }
  } catch (err) {
    toast('Failed to clear history.', 'error');
  }
}

async function loadHistoryJob(jobId, mode) {
  const onAudiobookTab = document.getElementById('tab-audiobook')?.classList.contains('active');
  const targetTab = (mode === 'audiobook' || onAudiobookTab) ? 'audiobook' : 'translate';
  const prefix = targetTab === 'audiobook' ? 'ab' : 'tr';
  state[prefix].jobId = jobId;
  switchTab(targetTab);

  try {
    const res = await fetch(`${API}/status/${jobId}`);
    const data = await res.json();

    if (data.file_name) {
      const nameEl = document.getElementById(`${prefix}-file-name`);
      const metaEl = document.getElementById(`${prefix}-file-meta`);
      const uploadZone = document.getElementById(`${prefix}-upload-zone`);
      const selectedFile = document.getElementById(`${prefix}-selected-file`);
      if (nameEl) nameEl.textContent = data.file_name;
      if (metaEl) metaEl.textContent = data.status === 'done'
        ? 'Loaded from Session History · Ready'
        : `Loaded from Session History · ${data.current_step || 'Ready to translate'}`;
      if (uploadZone) uploadZone.style.display = 'none';
      if (selectedFile) {
        selectedFile.classList.add('visible');
        selectedFile.style.display = 'flex';
      }
    }

    if (prefix === 'ab') {
      document.getElementById('ab-start-btn').disabled = false;
      try {
        const textRes = await fetch(`${API}/jobs/${jobId}/text`);
        if (textRes.ok) {
          const textData = await textRes.json();
          const hasTrans = Boolean(textData.translated_text && textData.translated_text.trim());
          const transOpt = document.getElementById('ab-translate-option');
          const useTranslated = document.getElementById('ab-use-translated');
          if (!hasTrans) {
            const detLang = detectTextLanguage(textData.original_text || '');
            restrictAudiobookLanguage(detLang);
            if (transOpt) transOpt.style.display = 'none';
          } else {
            restrictAudiobookLanguage(null);
            if (transOpt) transOpt.style.display = 'block';
            if (useTranslated) useTranslated.checked = true;
            const transLang = detectTextLanguage(textData.translated_text || '');
            const langSelect = document.getElementById('ab-lang-select');
            if (langSelect && transLang) {
              langSelect.value = transLang;
              updateVoices();
            }
          }
        }
      } catch (_) {}
    }
    if (data.status === 'running') {
      document.getElementById(`${prefix}-progress-card`).style.display = 'block';
      document.getElementById(`${prefix}-start-btn`).disabled = true;
      setStatusBadge(prefix, 'running');
      updateProgress(prefix, data);
      connectSSE(prefix, jobId);
    } else if (data.has_output && data.status === 'done' && (prefix === 'tr' || mode === 'audiobook')) {
      // Re-enable action buttons and show completed output
      document.getElementById(`${prefix}-start-btn`).disabled = false;
      if (prefix === 'tr') {
        const addQBtn = document.getElementById('tr-add-queue-btn');
        if (addQBtn) addQBtn.disabled = false;
        const directBtn = document.getElementById('tr-direct-polish-btn');
        if (directBtn && !state.tr.isComic) directBtn.disabled = false;
      }
      showResult(prefix, data);
      setStatusBadge(prefix, 'done');
      document.getElementById(`${prefix}-progress-card`).style.display = 'block';
      document.getElementById(`${prefix}-progress-pct`).textContent = '100%';
      document.getElementById(`${prefix}-progress-bar`).style.width = '100%';
      document.getElementById(`${prefix}-progress-step`).textContent = data.current_step;
    } else {
      // Idle, queued, cancelled, or error job loaded from history -> enable start/resume buttons!
      const startBtn = document.getElementById(`${prefix}-start-btn`);
      if (startBtn) startBtn.disabled = false;
      if (prefix === 'tr') {
        const addQBtn = document.getElementById('tr-add-queue-btn');
        if (addQBtn) addQBtn.disabled = false;
        const directBtn = document.getElementById('tr-direct-polish-btn');
        if (directBtn && !state.tr.isComic) directBtn.disabled = false;
      }
      resetProgress(prefix);
      toast(`📄 Φορτώθηκε "${data.file_name || 'έγγραφο'}" — έτοιμο για μετάφραση/συνέχιση!`, 'info');
    }
    if (prefix === 'tr') {
      checkCoverImage(jobId);
    }
  } catch (e) {
    console.warn('Could not reload job:', e);
  }
}

// ── Toasts ─────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  const typeClass = { success: 'toast-success', error: 'toast-error', info: 'toast-info' };
  el.className = `toast ${typeClass[type] || ''}`;
  const span = document.createElement('span');
  span.textContent = msg;
  el.appendChild(span);
  container.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g, '&#39;');
}

// ── Translation Editor ──────────────────────────────────────
async function openEditor() {
  const jobId = state.tr.jobId;
  if (!jobId) {
    toast('No translated document to edit.', 'error');
    return;
  }

  const editorCard = document.getElementById('tr-editor-card');
  editorCard.style.display = 'block';

  try {
    const res = await fetch(`${API}/jobs/${jobId}/text`);
    if (!res.ok) throw new Error('Could not fetch document text');
    const data = await res.json();

    document.getElementById('editor-original-text').value = data.original_text || '';
    document.getElementById('editor-translated-text').value = data.translated_text || '';
    clearEditorDirty();
    updateEditorStats();
    editorCard.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    toast(`Failed to load text for editor: ${err.message}`, 'error');
  }
}

function markEditorDirty() {
  const badge = document.getElementById('editor-dirty-badge');
  if (badge) badge.classList.add('visible');
}

function clearEditorDirty() {
  const badge = document.getElementById('editor-dirty-badge');
  if (badge) badge.classList.remove('visible');
}

function closeEditor() {
  const card = document.getElementById('tr-editor-card');
  if (card) card.style.display = 'none';
  const src = document.getElementById('editor-original-text');
  if (src) src.value = '';
  const tr = document.getElementById('editor-translated-text');
  if (tr) tr.value = '';
  const findBox = document.getElementById('find-replace-bar');
  if (findBox) findBox.style.display = 'none';
  clearEditorDirty();
}

function setEditorView(mode) {
  const grid = document.getElementById('editor-grid');
  const btnSplit = document.getElementById('btn-view-split');
  const btnFull = document.getElementById('btn-view-full');

  if (mode === 'full') {
    grid.classList.add('full-view');
    btnFull.classList.add('active');
    btnSplit.classList.remove('active');
  } else {
    grid.classList.remove('full-view');
    btnSplit.classList.add('active');
    btnFull.classList.remove('active');
  }
}

function updateEditorStats() {
  const text = document.getElementById('editor-translated-text').value || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const chars = text.length;
  document.getElementById('editor-stats').textContent = `${words.toLocaleString()} words · ${chars.toLocaleString()} characters`;
}

function toggleFindReplace() {
  const bar = document.getElementById('find-replace-bar');
  bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
  if (bar.style.display === 'flex') {
    document.getElementById('find-input').focus();
  }
}

function applyReplace(replaceAll = false) {
  const findVal = document.getElementById('find-input').value;
  const replVal = document.getElementById('replace-input').value;
  if (!findVal) {
    toast('Please enter text to find.', 'error');
    return;
  }

  const textarea = document.getElementById('editor-translated-text');
  let text = textarea.value;

  if (replaceAll) {
    const count = (text.split(findVal).length - 1);
    text = text.replaceAll(findVal, replVal);
    textarea.value = text;
    updateEditorStats();
    toast(`Replaced ${count} occurrences.`, 'success');
  } else {
    if (text.includes(findVal)) {
      textarea.value = text.replace(findVal, replVal);
      updateEditorStats();
      toast('Replaced first occurrence.', 'success');
    } else {
      toast('Text not found.', 'info');
    }
  }
}

async function saveEditorText() {
  const jobId = state.tr.jobId;
  if (!jobId) return;

  const text = document.getElementById('editor-translated-text').value;
  const btn = document.getElementById('btn-save-editor');
  btn.disabled = true;
  btn.textContent = '⏳ Saving...';

  try {
    const res = await fetch(`${API}/jobs/${jobId}/text`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ translated_text: text }),
    });

    if (!res.ok) throw new Error('Failed to save corrections');
    clearEditorDirty();
    toast('✅ Corrections saved and export files updated!', 'success');

    // Also update download button URL
    const fmt = (document.getElementById('tr-output-format')?.value || 'txt').toLowerCase();
    const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
    const dlBtn = document.getElementById('tr-download-btn');
    if (dlBtn) dlBtn.href = `${API}/download/${jobId}?format=${fmt}&layout=${layout}`;
  } catch (err) {
    toast(`Save error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '💾 Save & Update Files';
  }
}

// ── AI Polish via Gemini ───────────────────────────────────
let _polishPollTimer = null;
let _polishRunning = false;

function toggleApiKeyVisibility() {
  const input = document.getElementById('gemini-api-key');
  const btn = document.getElementById('btn-toggle-key');
  if (input.type === 'password') {
    input.type = 'text';
    btn.textContent = '🔒';
  } else {
    input.type = 'password';
    btn.textContent = '👁️';
  }
}

async function openAiPolishModal() {
  const modal = document.getElementById('ai-polish-modal');
  modal.style.display = 'flex';
  let savedKey = localStorage.getItem('gemini_api_key') || '';

  // If not found in browser localStorage, load from persistent server settings
  if (!savedKey) {
    try {
      const sRes = await fetch(`${API}/settings`);
      if (sRes.ok) {
        const sData = await sRes.json();
        if (sData.gemini_api_key) {
          savedKey = sData.gemini_api_key;
          localStorage.setItem('gemini_api_key', savedKey);
        }
      }
    } catch (_) {}
  }

  const input = document.getElementById('gemini-api-key');
  input.value = savedKey;

  const badge = document.getElementById('gemini-key-saved-badge');
  if (badge) {
    badge.style.display = savedKey ? 'inline' : 'none';
  }
  const clearBtn = document.getElementById('btn-clear-key');
  if (clearBtn) {
    clearBtn.style.display = savedKey ? 'inline' : 'none';
  }

  const layout = document.getElementById('tr-layout-mode')?.value;
  const styleSelect = document.getElementById('ai-polish-style');
  if (styleSelect && layout === 'literature') {
    styleSelect.value = 'literature';
  }

  const prog = document.getElementById('ai-polish-progress-container');
  if (prog) prog.style.display = _polishRunning ? 'block' : 'none';
  const btn = document.getElementById('btn-run-polish');
  if (btn) btn.disabled = _polishRunning;
  const cancelBtn = document.getElementById('btn-cancel-polish');
  if (cancelBtn) cancelBtn.textContent = _polishRunning ? 'Minimize (Run in Background)' : 'Cancel';
}

function closeAiPolishModal() {
  document.getElementById('ai-polish-modal').style.display = 'none';
  if (!_polishRunning) {
    if (_polishPollTimer) {
      clearInterval(_polishPollTimer);
      _polishPollTimer = null;
    }
    const prog = document.getElementById('ai-polish-progress-container');
    if (prog) prog.style.display = 'none';
    const btn = document.getElementById('btn-run-polish');
    if (btn) btn.disabled = false;
  }
}

async function saveGeminiKeyOnly() {
  const input = document.getElementById('gemini-api-key');
  const apiKey = (input ? input.value : '').trim();
  if (!apiKey) {
    toast('Παρακαλώ εισάγετε το Gemini API Key σας.', 'error');
    return;
  }
  localStorage.setItem('gemini_api_key', apiKey);
  try {
    await fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: apiKey }),
    });
  } catch (_) {}
  const badge = document.getElementById('gemini-key-saved-badge');
  if (badge) badge.style.display = 'inline';
  const clearBtn = document.getElementById('btn-clear-key');
  if (clearBtn) clearBtn.style.display = 'inline';
  toast('Το Gemini API Key αποθηκεύτηκε επιτυχώς!', 'success');
}

async function clearGeminiKey() {
  localStorage.removeItem('gemini_api_key');
  const input = document.getElementById('gemini-api-key');
  if (input) input.value = '';
  const badge = document.getElementById('gemini-key-saved-badge');
  if (badge) badge.style.display = 'none';
  const clearBtn = document.getElementById('btn-clear-key');
  if (clearBtn) clearBtn.style.display = 'none';
  try {
    await fetch(`${API}/settings/gemini_api_key`, { method: 'DELETE' });
  } catch (_) {}
  toast('Saved Gemini API key cleared.', 'info');
}

function openDirectPolishModal() {
  if (!state.tr.jobId) {
    toast('Please upload a document or paste text in Editor first.', 'error');
    return;
  }
  const biChk = document.getElementById('ai-polish-bilingual');
  if (biChk) {
    // Only default Source-Anchored Verification to checked when a prior translation exists
    biChk.checked = (state.tr.status === 'done');
  }
  openAiPolishModal();
}

async function openDirectEditor() {
  const editorCard = document.getElementById('tr-editor-card');
  editorCard.style.display = 'block';
  editorCard.scrollIntoView({ behavior: 'smooth' });

  if (state.tr.jobId) {
    await openEditor();
  } else {
    document.getElementById('editor-original-text').value = '';
    const tr = document.getElementById('editor-translated-text');
    if (!tr.value) {
      tr.placeholder = 'Επικολλήστε ή πληκτρολογήστε εδώ το ελληνικό κείμενο που θέλετε να επιμεληθείτε (AI Polish)...';
    }
    updateEditorStats();
  }
}

async function runAiPolish() {
  const jobId = state.tr.jobId;

  // If editor is open and modified, pass current editor text
  let currentText = null;
  const editorCard = document.getElementById('tr-editor-card');
  if (editorCard.style.display !== 'none') {
    currentText = document.getElementById('editor-translated-text').value;
  }

  if (!jobId && !currentText) {
    toast('Please upload a document or paste text in Editor first.', 'error');
    return;
  }

  const apiKey = document.getElementById('gemini-api-key').value.trim();
  if (!apiKey) {
    toast('Please enter your Gemini API Key.', 'error');
    return;
  }
  const isValidFormat = (apiKey.startsWith('AQ.') && apiKey.length >= 25) ||
                        (apiKey.startsWith('AIza') && apiKey.length >= 35) ||
                        (apiKey.length >= 25);
  if (!isValidFormat) {
    toast('Invalid API Key format. Google Gemini keys start with "AQ." or "AIzaSy...". Please paste a valid key.', 'error');
    return;
  }
  localStorage.setItem('gemini_api_key', apiKey);
  // Persist permanently on server settings as well
  fetch(`${API}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gemini_api_key: apiKey }),
  }).catch(() => {});

  const style = document.getElementById('ai-polish-style').value;
  const progEl = document.getElementById('ai-polish-progress-container');
  const barEl = document.getElementById('ai-polish-bar');
  const pctEl = document.getElementById('ai-polish-pct');
  const stepEl = document.getElementById('ai-polish-step');
  const pagesEl = document.getElementById('ai-polish-pages');
  const btn = document.getElementById('btn-run-polish');

  progEl.style.display = 'block';
  barEl.style.width = '5%';
  pctEl.textContent = '5%';
  stepEl.innerHTML = '<span class="status-dot"></span> Initializing Flash AI engine...';
  if (pagesEl) pagesEl.textContent = 'Starting...';
  btn.disabled = true;
  _polishRunning = true;
  const cancelBtn = document.getElementById('btn-cancel-polish');
  if (cancelBtn) cancelBtn.textContent = 'Minimize (Run in Background)';
  const trTabLabel = document.querySelector('#btn-translate .tab-label');
  if (trTabLabel) trTabLabel.textContent = 'Translate Document · ✨ AI Polish';

  // Poll progress every 500ms if jobId exists
  if (jobId) {
    _polishPollTimer = setInterval(async () => {
      try {
        const pRes = await fetch(`${API}/polish/status/${jobId}`);
        if (pRes.ok) {
          const data = await pRes.json();
          if (data.status === 'running' && data.total > 0) {
            const pct = Math.max(5, Math.min(98, data.percent));
            barEl.style.width = `${pct}%`;
            pctEl.textContent = `${pct}%`;
            stepEl.innerHTML = `<span class="status-dot"></span> ${data.step || 'Refining text...'}`;
            if (pagesEl) pagesEl.textContent = `Part ${data.current} of ${data.total}`;
            if (trTabLabel) trTabLabel.textContent = `Translate Document · ✨ ${pct}%`;
          }
        }
      } catch (_) {}
    }, 500);
  }

  const bilingual = document.getElementById('ai-polish-bilingual')?.checked ?? true;

  try {
    const res = await fetch(`${API}/polish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        text: currentText,
        style: style,
        api_key: apiKey,
        layout_mode: document.getElementById('tr-layout-mode')?.value || 'standard',
        bilingual_mode: bilingual,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'AI Polishing failed');
    }

    const data = await res.json();
    barEl.style.width = '100%';
    pctEl.textContent = '100%';
    stepEl.innerHTML = '<span class="status-dot"></span> Completed!';
    if (pagesEl) pagesEl.textContent = 'Complete';

    toast('✨ AI Polish complete! Text has been refined.', 'success');

    // Update job state and show result card so user can download the polished file in any format
    state.tr.jobId = data.job_id;
    showResult('tr', { has_output: true, job_id: data.job_id });
    const meta = document.getElementById('tr-result-meta');
    if (meta) {
      meta.textContent = 'Your document has been polished with Gemini AI. Click below to download the file.';
    }

    // If editor is open, put the polished text into it
    document.getElementById('editor-translated-text').value = data.polished_text;
    updateEditorStats();
    if (editorCard.style.display === 'none') {
      openEditor();
    }
    setTimeout(() => {
      if (document.getElementById('ai-polish-modal').style.display !== 'none') {
        closeAiPolishModal();
      }
    }, 600);
  } catch (err) {
    toast(`AI Error: ${err.message}`, 'error');
    progEl.style.display = 'none';
    btn.disabled = false;
  } finally {
    _polishRunning = false;
    const cBtn = document.getElementById('btn-cancel-polish');
    if (cBtn) cBtn.textContent = 'Cancel';
    const trTabLabel = document.querySelector('#btn-translate .tab-label');
    if (trTabLabel && state.tr.status !== 'running') {
      trTabLabel.textContent = 'Translate Document';
    }
    if (_polishPollTimer) {
      clearInterval(_polishPollTimer);
      _polishPollTimer = null;
    }
  }
}

// ── Categorized Glossary Management ──────────────────────────────
const glossaryState = {
  items: [],
  activeCategory: 'all',
  searchQuery: '',
  page: 1,
  pageSize: 50,
  counts: { all: 0, technical: 0, literary: 0, general: 0 },
};

async function openGlossaryModal() {
  document.getElementById('glossary-modal').style.display = 'flex';
  await loadGlossary();
}

function closeGlossaryModal() {
  document.getElementById('glossary-modal').style.display = 'none';
}

async function loadGlossary() {
  const tbody = document.getElementById('glossary-tbody');
  tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:20px">Φόρτωση όρων γλωσσαρίου...</td></tr>';

  try {
    const res = await fetch(`${API}/glossary?categorized=true`);
    const data = await res.json();

    glossaryState.items = Array.isArray(data.terms) ? data.terms : [];
    glossaryState.counts = data.counts || { all: 0, technical: 0, literary: 0, general: 0 };

    // Update count badges
    const bAll = document.getElementById('glossary-badge-all');
    const bTech = document.getElementById('glossary-badge-technical');
    const bLit = document.getElementById('glossary-badge-literary');
    const bGen = document.getElementById('glossary-badge-general');
    if (bAll) bAll.textContent = glossaryState.counts.all || glossaryState.items.length;
    if (bTech) bTech.textContent = glossaryState.counts.technical || 0;
    if (bLit) bLit.textContent = glossaryState.counts.literary || 0;
    if (bGen) bGen.textContent = glossaryState.counts.general || 0;

    renderGlossaryTable();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:#f87171; text-align:center; padding:20px">Σφάλμα φόρτωσης: ${escHtml(err.message)}</td></tr>`;
  }
}

function filterGlossaryCategory(cat, btn) {
  glossaryState.activeCategory = cat;
  glossaryState.page = 1;

  // Update active tab button style
  document.querySelectorAll('.glossary-tab-btn').forEach((b) => b.classList.remove('active'));
  if (btn) btn.classList.add('active');

  // Auto-sync add form category dropdown
  const catSelect = document.getElementById('glossary-category-select');
  if (catSelect && ['technical', 'literary', 'general'].includes(cat)) {
    catSelect.value = cat;
  }

  renderGlossaryTable();
}

function onGlossarySearch(val) {
  glossaryState.searchQuery = (val || '').trim().toLowerCase();
  glossaryState.page = 1;
  renderGlossaryTable();
}

function changeGlossaryPage(delta) {
  glossaryState.page = Math.max(1, glossaryState.page + delta);
  renderGlossaryTable();
}

function renderGlossaryTable() {
  const tbody = document.getElementById('glossary-tbody');
  if (!tbody) return;

  // Filter items by category & search query
  let filtered = glossaryState.items;
  if (glossaryState.activeCategory && glossaryState.activeCategory !== 'all') {
    filtered = filtered.filter((it) => it.category === glossaryState.activeCategory);
  }

  if (glossaryState.searchQuery) {
    const q = glossaryState.searchQuery;
    filtered = filtered.filter((it) => (it.source || '').toLowerCase().includes(q) || (it.target || '').toLowerCase().includes(q));
  }

  const total = filtered.length;
  if (total === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:24px">Δεν βρέθηκαν όροι για τα επιλεγμένα κριτήρια.</td></tr>';
    document.getElementById('glossary-pagination-info').textContent = '0 όροι';
    document.getElementById('glossary-prev-btn').disabled = true;
    document.getElementById('glossary-next-btn').disabled = true;
    document.getElementById('glossary-page-indicator').textContent = '1';
    return;
  }

  const totalPages = Math.ceil(total / glossaryState.pageSize) || 1;
  if (glossaryState.page > totalPages) glossaryState.page = totalPages;

  const startIdx = (glossaryState.page - 1) * glossaryState.pageSize;
  const endIdx = Math.min(startIdx + glossaryState.pageSize, total);
  const pageItems = filtered.slice(startIdx, endIdx);

  const catMeta = {
    technical: { label: '💻 Τεχνικός', cls: 'cat-technical' },
    literary: { label: '📚 Λογοτεχνικός', cls: 'cat-literary' },
    general: { label: '⚙️ Γενικός', cls: 'cat-general' },
  };

  tbody.innerHTML = pageItems.map((item) => {
    const meta = catMeta[item.category] || catMeta.general;
    return `
      <tr>
        <td>
          <span class="glossary-cat-badge ${meta.cls}">${meta.label}</span>
        </td>
        <td><strong>${escHtml(item.source)}</strong></td>
        <td>${escHtml(item.target)}</td>
        <td style="text-align:center">
          <button class="glossary-del-btn" onclick="deleteGlossaryRule('${escHtml(item.source)}')" title="Διαγραφή όρου">✕</button>
        </td>
      </tr>
    `;
  }).join('');

  // Update pagination UI
  const infoEl = document.getElementById('glossary-pagination-info');
  if (infoEl) {
    infoEl.textContent = `Εμφάνιση ${startIdx + 1}–${endIdx} από ${total} όρους (Σύνολο: ${glossaryState.counts.all || glossaryState.items.length})`;
  }

  const pageInd = document.getElementById('glossary-page-indicator');
  if (pageInd) pageInd.textContent = `${glossaryState.page} / ${totalPages}`;

  const prevBtn = document.getElementById('glossary-prev-btn');
  const nextBtn = document.getElementById('glossary-next-btn');
  if (prevBtn) prevBtn.disabled = glossaryState.page <= 1;
  if (nextBtn) nextBtn.disabled = glossaryState.page >= totalPages;
}

async function addGlossaryRule() {
  const src = document.getElementById('glossary-source').value.trim();
  const tgt = document.getElementById('glossary-target').value.trim();
  const cat = document.getElementById('glossary-category-select')?.value || 'general';

  if (!src || !tgt) {
    toast('Παρακαλώ συμπληρώστε και τον αγγλικό και τον ελληνικό όρο.', 'error');
    return;
  }

  try {
    const res = await fetch(`${API}/glossary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: src, target: tgt, category: cat }),
    });
    if (!res.ok) throw new Error('Αποτυχία προσθήκης όρου');

    document.getElementById('glossary-source').value = '';
    document.getElementById('glossary-target').value = '';
    toast(`Προστέθηκε: "${src}" ➔ "${tgt}"`, 'success');
    await loadGlossary();
  } catch (err) {
    toast(`Σφάλμα: ${err.message}`, 'error');
  }
}

async function deleteGlossaryRule(term) {
  try {
    const res = await fetch(`${API}/glossary/${encodeURIComponent(term)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Αποτυχία διαγραφής όρου');
    toast(`Διαγράφηκε ο όρος "${term}"`, 'info');
    await loadGlossary();
  } catch (err) {
    toast(`Σφάλμα: ${err.message}`, 'error');
  }
}

// ── Page Refresh & Theme Management ────────────────────────
function refreshPageApp() {
  const heroIcon = document.getElementById('refresh-icon');
  const navIcon = document.getElementById('nav-refresh-icon');
  if (heroIcon) heroIcon.classList.add('spinning');
  if (navIcon) navIcon.classList.add('spinning');
  toast('Ανανέωση σελίδας και δεδομένων...', 'info');
  setTimeout(() => {
    window.location.reload();
  }, 350);
}

// ── Theme Management (Dark / Light Mode) ──────────────────
function initTheme() {
  const saved = localStorage.getItem('bookapp_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  updateThemeButton(saved);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('bookapp_theme', next);
  updateThemeButton(next);
}

function updateThemeButton(theme) {
  const icon = document.getElementById('theme-icon');
  const label = document.getElementById('theme-label');
  if (icon && label) {
    if (theme === 'light') {
      icon.textContent = '☀️';
      label.textContent = 'Light';
    } else {
      icon.textContent = '🌓';
      label.textContent = 'Dark';
    }
  }
}

// ── Synchronized Scrolling for Split-Screen Editor ────────
let isSyncingOrig = false;
let isSyncingTrans = false;

function setupSyncScroll() {
  const orig = document.getElementById('editor-original-text');
  const trans = document.getElementById('editor-translated-text');
  if (!orig || !trans) return;

  orig.addEventListener('scroll', () => {
    if (isSyncingOrig) { isSyncingOrig = false; return; }
    isSyncingTrans = true;
    const maxOrig = orig.scrollHeight - orig.clientHeight;
    if (maxOrig > 0) {
      const pct = orig.scrollTop / maxOrig;
      trans.scrollTop = pct * (trans.scrollHeight - trans.clientHeight);
    }
  });

  trans.addEventListener('scroll', () => {
    if (isSyncingTrans) { isSyncingTrans = false; return; }
    isSyncingOrig = true;
    const maxTrans = trans.scrollHeight - trans.clientHeight;
    if (maxTrans > 0) {
      const pct = trans.scrollTop / maxTrans;
      orig.scrollTop = pct * (orig.scrollHeight - orig.clientHeight);
    }
  });
}

// ── Smart Batch Queue ──────────────────────────────────────
let _queuePollTimer = null;

async function enqueueMultipleFiles(files) {
  const allowed = ['.pdf', '.docx', '.epub', '.cbz', '.zip'];
  const srcLang = document.getElementById('tr-source-lang')?.value || 'english';
  const tgtLang = document.getElementById('tr-target-lang')?.value || 'greek';
  const chosenFmt = document.getElementById('tr-output-format')?.value || 'pdf';
  const chosenLayout = document.getElementById('tr-layout-mode')?.value || 'standard';
  const aiPolish = document.getElementById('tr-ai-polish')?.checked || false;
  const apiKey = localStorage.getItem('gemini_api_key') || null;
  const readingDirEl = document.querySelector('input[name="tr-reading-dir"]:checked');
  const readingDirection = readingDirEl ? readingDirEl.value : 'ltr';

  let added = 0;
  for (const file of files) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) {
      toast(`⚠️ Παράλειψη "${file.name}" (μη υποστηριζόμενο format).`, 'error');
      continue;
    }
    try {
      const fd = new FormData();
      fd.append('file', file);
      const upRes = await fetch(`${API}/upload`, { method: 'POST', body: fd });
      if (!upRes.ok) continue;
      const upData = await upRes.json();

      const isComic = Boolean(upData.is_comic) || ['.cbz', '.cbr', '.zip'].includes(ext);
      const itemLayout = isComic ? 'comic' : chosenLayout;
      let itemFmt = chosenFmt;
      if (isComic && ['txt', 'docx', 'doc'].includes(itemFmt)) {
        itemFmt = 'pdf';
      }

      await fetch(`${API}/queue/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: upData.job_id,
          source_lang: srcLang,
          target_lang: tgtLang,
          output_format: itemFmt,
          layout_mode: itemLayout,
          reading_direction: readingDirection,
          ai_polish: isComic ? true : aiPolish,
          api_key: apiKey || null,
          is_comic: isComic,
          is_scanned: Boolean(upData.is_scanned),
        }),
      });
      added++;
    } catch (err) {
      toast(`❌ Σφάλμα φόρτωσης "${file.name}": ${err.message}`, 'error');
    }
  }

  if (added > 0) {
    toast(`📋 Προστέθηκαν ${added} αρχεία στην Smart Batch Queue!`, 'success');
    await refreshBatchQueue();
    refreshHistory();
  }
}

async function addCurrentFileToQueue() {
  if (!state.tr.jobId) {
    toast('Ανεβάστε πρώτα ένα αρχείο για να προστεθεί στην ουρά.', 'error');
    return;
  }
  const srcLang = document.getElementById('tr-source-lang')?.value || 'english';
  const tgtLang = document.getElementById('tr-target-lang')?.value || 'greek';
  let outputFormat = document.getElementById('tr-output-format')?.value || 'pdf';
  const layoutMode = document.getElementById('tr-layout-mode')?.value || 'standard';
  const isComic = Boolean(state.tr.isComic) || layoutMode === 'comic';
  if (isComic && ['txt', 'docx', 'doc'].includes(outputFormat)) outputFormat = 'pdf';
  const aiPolish = document.getElementById('tr-ai-polish')?.checked || false;
  const apiKey = localStorage.getItem('gemini_api_key') || null;
  const readingDirEl = document.querySelector('input[name="tr-reading-dir"]:checked');
  const readingDirection = readingDirEl ? readingDirEl.value : 'ltr';

  try {
    const res = await fetch(`${API}/queue/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: state.tr.jobId,
        source_lang: srcLang,
        target_lang: tgtLang,
        output_format: outputFormat,
        layout_mode: isComic ? 'comic' : layoutMode,
        reading_direction: readingDirection,
        ai_polish: aiPolish,
        api_key: apiKey || null,
        is_comic: isComic,
      }),
    });
    if (!res.ok) throw new Error('Failed to add file to queue');
    toast('📋 Προστέθηκε στην Smart Batch Queue!', 'success');
    removeFile('tr');
    await refreshBatchQueue();
  } catch (err) {
    toast(`❌ ${err.message}`, 'error');
  }
}

async function refreshBatchQueue() {
  try {
    const res = await fetch(`${API}/queue`);
    if (!res.ok) return;
    const q = await res.json();
    renderBatchQueue(q);

    if (q.is_running) {
      if (!_queuePollTimer) {
        _queuePollTimer = setInterval(refreshBatchQueue, 1500);
      }
    } else if (_queuePollTimer) {
      clearInterval(_queuePollTimer);
      _queuePollTimer = null;
      refreshHistory();
    }
  } catch (_) {}
}

function renderBatchQueue(q) {
  const card = document.getElementById('tr-queue-card');
  const list = document.getElementById('tr-queue-list');
  const counter = document.getElementById('tr-queue-counter');
  const autoToggle = document.getElementById('queue-auto-start-toggle');
  const startBtn = document.getElementById('btn-queue-start');
  const pauseBtn = document.getElementById('btn-queue-pause');
  const dlAllBtn = document.getElementById('btn-queue-download-all');

  if (!card || !list) return;
  if (!q.items || q.items.length === 0) {
    card.style.display = 'none';
    return;
  }

  card.style.display = 'block';
  if (counter) counter.textContent = `${q.done_count} / ${q.total_count} completed`;
  if (autoToggle) autoToggle.checked = Boolean(q.auto_start);

  if (startBtn) {
    startBtn.style.display = (!q.is_running && q.queued_count > 0) ? 'inline-flex' : 'none';
    startBtn.textContent = q.paused ? '▶️ Resume Queue' : '▶️ Start Queue';
  }
  if (pauseBtn) {
    pauseBtn.style.display = (q.is_running && !q.paused) ? 'inline-flex' : 'none';
  }
  if (dlAllBtn) {
    dlAllBtn.style.display = q.done_count > 0 ? 'inline-flex' : 'none';
    dlAllBtn.href = `${API}/queue/download-all`;
  }

  const statusLabels = {
    queued: '⏳ Queued',
    running: '🔄 Running',
    done: '✅ Done',
    error: '❌ Error',
    cancelled: '🛑 Cancelled',
  };

  list.innerHTML = q.items.map((it) => {
    const modeTag = it.is_comic
      ? `🎨 Comic (${it.reading_direction.toUpperCase()})`
      : (it.layout_mode === 'literature' ? '📚 Literature' : '📄 Standard');
    const aiTag = it.ai_polish ? ' · ✨ AI Polish' : '';
    const dlLink = it.has_output
      ? `<a class="btn-sm btn-outline" href="${API}/download/${it.job_id}?format=${it.output_format}&layout=${it.layout_mode}" style="text-decoration:none; color:var(--emerald); border-color:rgba(16,185,129,0.4)">⬇️ ${it.output_format.toUpperCase()}</a>`
      : '';
    const progressBar = (it.status === 'running' || it.status === 'done')
      ? `<div class="queue-progress-track"><div class="queue-progress-fill" style="width:${it.status === 'done' ? 100 : it.progress}%"></div></div>`
      : '';
    const errLine = it.error
      ? `<div style="font-size:0.75rem; color:var(--rose)">${escapeHtml(it.error)}</div>`
      : '';
    return `
      <div class="queue-item ${it.status}">
        <div class="queue-item-top">
          <div class="queue-item-info">
            <span style="font-size:1.2rem">${it.is_comic ? '🎨' : '📄'}</span>
            <div style="min-width:0; flex:1">
              <div class="queue-item-name" title="${escapeHtml(it.file_name)}">${escapeHtml(it.file_name)}</div>
              <div class="queue-item-meta">
                <span>${modeTag}${aiTag}</span>
                <span>→ ${it.output_format.toUpperCase()}</span>
                <span>${escapeHtml(it.current_step || '')}</span>
              </div>
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:8px; flex-shrink:0">
            <span class="queue-badge ${it.status}">${statusLabels[it.status] || it.status}${it.status === 'running' ? ` ${it.progress}%` : ''}</span>
            ${dlLink}
            <button type="button" class="btn-icon" onclick="removeQueueItem('${it.job_id}')" title="Αφαίρεση από την ουρά">✕</button>
          </div>
        </div>
        ${progressBar}
        ${errLine}
      </div>
    `;
  }).join('');
}

async function startBatchQueue() {
  try {
    const res = await fetch(`${API}/queue/start`, { method: 'POST' });
    if (res.ok) {
      toast('▶️ Η Smart Batch Queue ξεκίνησε (σειριακή εκτέλεση).', 'info');
      await refreshBatchQueue();
    }
  } catch (err) {
    toast(`❌ ${err.message}`, 'error');
  }
}

async function pauseBatchQueue() {
  try {
    const res = await fetch(`${API}/queue/pause`, { method: 'POST' });
    if (res.ok) {
      toast('⏸️ Η ουρά θα παύσει μόλις ολοκληρωθεί το τρέχον έγγραφο.', 'info');
      await refreshBatchQueue();
    }
  } catch (err) {
    toast(`❌ ${err.message}`, 'error');
  }
}

async function toggleQueueAutoStart() {
  const enabled = document.getElementById('queue-auto-start-toggle')?.checked || false;
  try {
    await fetch(`${API}/queue/auto-start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_start: enabled }),
    });
    toast(enabled ? '⚡ Auto-Start Queue ενεργοποιήθηκε.' : '⏸️ Manual Queue mode ενεργό.', 'info');
    await refreshBatchQueue();
  } catch (_) {}
}

async function removeQueueItem(jobId) {
  try {
    await fetch(`${API}/queue/${jobId}`, { method: 'DELETE' });
    await refreshBatchQueue();
  } catch (_) {}
}

async function clearBatchQueue() {
  try {
    await fetch(`${API}/queue`, { method: 'DELETE' });
    await refreshBatchQueue();
    toast('🗑️ Η ουρά καθαρίστηκε.', 'info');
  } catch (_) {}
}

// ── Init ───────────────────────────────────────────────────
async function init() {
  // Initialize Theme and Editor Sync Scroll
  initTheme();
  setupSyncScroll();

  // Auto-sync Gemini API key between localStorage and backend server
  const localKey = localStorage.getItem('gemini_api_key');
  if (localKey) {
    fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: localKey }),
    }).catch(() => {});
  }

  // Check backend is reachable
  try {
    await fetch(`${API}/health`);
  } catch (e) {
    toast('⚠️ Cannot connect to backend. Make sure the server is running on port 8000.', 'error');
  }

  // Load voices
  await loadVoices();

  // Load history & any active batch queue
  await refreshHistory();
  await refreshBatchQueue();

  // Initialize format selector rules
  updateFormatAvailability('standard', '');

  // Keyboard support for upload zones
  document.querySelectorAll('.upload-zone').forEach(zone => {
    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        zone.click();
      }
    });
  });

  // Click outside modal box (on dark backdrop) to close / minimize
  const polishModal = document.getElementById('ai-polish-modal');
  if (polishModal) {
    polishModal.addEventListener('click', (e) => {
      if (e.target === polishModal) closeAiPolishModal();
    });
  }
  const glossaryModal = document.getElementById('glossary-modal');
  if (glossaryModal) {
    glossaryModal.addEventListener('click', (e) => {
      if (e.target === glossaryModal) closeGlossaryModal();
    });
  }

  // Global keyboard shortcuts (Ctrl+S, Ctrl+F in editor; Esc to close modals)
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const polishModal = document.getElementById('ai-polish-modal');
      if (polishModal && polishModal.style.display !== 'none') {
        closeAiPolishModal();
      }
      const glossaryModal = document.getElementById('glossary-modal');
      if (glossaryModal && glossaryModal.style.display !== 'none') {
        closeGlossaryModal();
      }
      return;
    }

    const editorCard = document.getElementById('tr-editor-card');
    if (!editorCard || editorCard.style.display === 'none') return;

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      saveEditorText();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      const bar = document.getElementById('find-replace-bar');
      if (bar && bar.style.display !== 'flex') toggleFindReplace();
      const findInput = document.getElementById('find-input');
      if (findInput) findInput.focus();
    }
  });
}

init();
