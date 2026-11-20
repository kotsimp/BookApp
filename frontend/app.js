/* ============================================================
   DocTranslate & AudioBook — Frontend Application Logic
   ============================================================ */

'use strict';

const API = (typeof window !== 'undefined' && window.location && window.location.origin && window.location.origin !== 'null' && (window.location.protocol || '').startsWith('http'))
  ? `${window.location.origin}/api`
  : 'http://localhost:8000/api';

async function parseApiError(res, fallbackMsg = 'Request failed') {
  try {
    const err = await res.json();
    if (typeof err?.detail === 'string' && err.detail.trim()) return err.detail;
    if (Array.isArray(err?.detail)) {
      return err.detail.map(d => d?.msg || JSON.stringify(d)).join('; ') || fallbackMsg;
    }
    if (err?.message) return String(err.message);
  } catch (_) {
    // Non-JSON 500/502 response body
  }
  return `${fallbackMsg} (HTTP ${res.status})`;
}

// ── State ──────────────────────────────────────────────────
const state = {
  tr: { jobId: null, file: null, sse: null, pollInterval: null, status: 'idle' },
  ab: { jobId: null, file: null, sse: null, pollInterval: null, status: 'idle' },
  voices: {},
  selectedVoice: '',
};

function stopJobTracking(prefix) {
  if (state[prefix]?.sse) {
    try { state[prefix].sse.close(); } catch (_) {}
    state[prefix].sse = null;
  }
  if (state[prefix]?.pollInterval) {
    clearInterval(state[prefix].pollInterval);
    state[prefix].pollInterval = null;
  }
}

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

// ── Global Mode Switching: Basic vs Advanced ──────────────
let currentAppMode = (typeof localStorage !== 'undefined' && localStorage.getItem('bookapp_ui_mode')) || 'basic';
let _lastDetectedGenreInfo = null;
let _isEnqueuing = false;

function setAppMode(mode) {
  currentAppMode = (mode === 'advanced') ? 'advanced' : 'basic';
  try {
    localStorage.setItem('bookapp_ui_mode', currentAppMode);
  } catch (_) {}
  applyAppMode(currentAppMode);
  if (typeof toast === 'function') {
    toast(
      currentAppMode === 'basic'
        ? '⚡ Ενεργοποιήθηκε η Απλή Λειτουργία (1-Click AI)'
        : '⚙️ Ενεργοποιήθηκε η Προχωρημένη Λειτουργία (Πλήρεις Ρυθμίσεις)',
      'info'
    );
  }
}

function applyAppMode(mode) {
  currentAppMode = (mode === 'advanced') ? 'advanced' : 'basic';
  const isBasic = currentAppMode === 'basic';

  const btnBasic = document.getElementById('btn-mode-basic');
  const btnAdv = document.getElementById('btn-mode-advanced');
  if (btnBasic && btnBasic.classList) {
    if (isBasic) btnBasic.classList.add('active'); else btnBasic.classList.remove('active');
  }
  if (btnAdv && btnAdv.classList) {
    if (!isBasic) btnAdv.classList.add('active'); else btnAdv.classList.remove('active');
  }

  // Toggle CSS visibility classes
  const advEls = document.querySelectorAll('.mode-advanced-only');
  if (advEls && advEls.forEach) {
    advEls.forEach((el) => {
      if (el && el.classList) {
        if (isBasic) el.classList.add('is-hidden'); else el.classList.remove('is-hidden');
      }
    });
  }
  const basicEls = document.querySelectorAll('.mode-basic-only');
  if (basicEls && basicEls.forEach) {
    basicEls.forEach((el) => {
      if (el && el.classList) {
        if (!isBasic) el.classList.add('is-hidden'); else el.classList.remove('is-hidden');
      }
    });
  }

  const trStart = document.getElementById('tr-start-btn');
  const abStart = document.getElementById('ab-start-btn');

  if (isBasic) {
    // Ensure AI Polish is checked by default for both translation and audiobook
    const trAi = document.getElementById('tr-ai-polish');
    if (trAi) trAi.checked = true;
    const abAi = document.getElementById('ab-ai-polish');
    if (abAi) abAi.checked = true;

    // Audiobook defaults for Basic Mode: Greek, Nestoras, Literature style
    const abLang = document.getElementById('ab-lang-select');
    if (abLang && abLang.value !== 'greek') {
      const greekOpt = abLang.querySelector ? abLang.querySelector('option[value="greek"]') : null;
      if (!greekOpt || !greekOpt.disabled) {
        abLang.value = 'greek';
        if (typeof updateVoices === 'function') updateVoices();
      }
    }
    const nestorasCard = document.querySelector('.voice-card[data-voice^="Nestoras"]');
    if (nestorasCard && typeof selectVoice === 'function') {
      selectVoice(nestorasCard.dataset.voice || 'Nestoras (Male)', nestorasCard);
    } else {
      const vSelected = document.getElementById('ab-voice-selected');
      if (vSelected) vSelected.value = 'Nestoras (Male)';
      state.selectedVoice = 'Nestoras (Male)';
    }
    const styleSelect = document.getElementById('ab-narration-style');
    if (styleSelect) {
      styleSelect.value = 'literature:-12%';
      if (typeof onNarrationStyleChange === 'function') onNarrationStyleChange();
    }

    if (trStart) {
      trStart.textContent = '✨ Μετάφραση Βιβλίου με AI (1-Click)';
    }
    if (abStart) {
      abStart.textContent = '🎧 Δημιουργία Audiobook με AI (1-Click)';
    }
  } else {
    // In Advanced Mode, restore standard button labels
    if (trStart) {
      trStart.textContent = '🌐 Start Translation';
    }
    if (abStart) {
      abStart.textContent = '🎧 Generate Audiobook';
    }
  }

  // Sync genre detection banner with mode if a document is currently loaded
  if (state.tr.jobId && _lastDetectedGenreInfo) {
    showGenreHint(_lastDetectedGenreInfo, isBasic);
    if (isBasic) {
      applyDetectedGenre(_lastDetectedGenreInfo.genre, true);
    }
  }
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
  e.stopPropagation();
  const cardEl = document.getElementById(prefix + '-upload-card');
  if (cardEl) cardEl.classList.remove('dragover');
  const zoneEl = document.getElementById(prefix + '-upload-zone');
  if (zoneEl) zoneEl.classList.remove('dragover');
  const files = Array.from(e.dataTransfer?.files || []);
  if (files.length === 0) return;
  const shouldBatch = prefix === 'tr' && (files.length > 1 || _batchQueueState.total_count > 0 || Boolean(state.tr.jobId));
  if (shouldBatch) {
    enqueueMultipleFiles(files);
  } else {
    processFile(files[0], prefix);
  }
}

function handleFileSelect(e, prefix) {
  const files = Array.from(e.target.files || []);
  if (files.length === 0) return;
  const shouldBatch = prefix === 'tr' && (files.length > 1 || _batchQueueState.total_count > 0 || Boolean(state.tr.jobId));
  if (shouldBatch) {
    enqueueMultipleFiles(files);
  } else {
    processFile(files[0], prefix);
  }
  try { e.target.value = ''; } catch (_) {}
}

async function processFile(file, prefix) {
  const allowed = prefix === 'ab'
    ? ['.pdf', '.docx', '.epub']
    : ['.pdf', '.docx', '.epub', '.cbz', '.zip'];
  const dotIdx = file.name.lastIndexOf('.');
  const ext = dotIdx > 0 ? file.name.slice(dotIdx).toLowerCase() : '(no extension)';

  if (!allowed.includes(ext)) {
    const supportedList = prefix === 'ab' ? 'PDF, DOCX, or EPUB' : 'PDF, DOCX, EPUB, or CBZ';
    toast(`❌ File type "${ext}" is not supported. Please use ${supportedList}.`, 'error');
    return;
  }

  stopJobTracking(prefix);
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
  stopJobTracking(prefix);
  state[prefix].file = null;
  state[prefix].jobId = null;
  if (prefix === 'tr') {
    _lastDetectedGenreInfo = null;
  }
  const selEl = document.getElementById(`${prefix}-selected-file`);
  if (selEl) {
    selEl.classList.remove('visible');
    selEl.style.display = '';
  }
  const hasQueue = (prefix === 'tr' && _batchQueueState.total_count > 0);
  const upZone = document.getElementById(`${prefix}-upload-zone`);
  if (upZone) upZone.style.display = hasQueue ? 'none' : '';
  setActionButtonsEnabled(prefix, false);
  resetProgress(prefix, false);
  if (prefix === 'ab') {
    restrictAudiobookLanguage(null);
    const transOpt = document.getElementById('ab-translate-option');
    if (transOpt) transOpt.style.display = 'none';
    const useTranslated = document.getElementById('ab-use-translated');
    if (useTranslated) useTranslated.checked = false;
  }
  if (prefix === 'tr') {
    const genreHint = document.getElementById('tr-genre-hint');
    if (genreHint) {
      genreHint.style.display = 'none';
      genreHint.innerHTML = '';
    }
    const covGroup = document.getElementById('tr-cover-group');
    if (covGroup) covGroup.style.display = 'none';
    const prevLayout = document.getElementById('tr-layout-mode')?.value || 'standard';
    setGraphicNovelLock(false);
    // When promoting a single file into the Batch Queue, preserve non-comic layout (e.g. Literature)
    if (!hasQueue || prevLayout === 'comic') {
      const stdBtn = document.getElementById('layout-standard');
      if (stdBtn) selectLayout('standard', stdBtn);
      updateFormatAvailability('standard', '');
    } else {
      const keepBtn = document.getElementById(`layout-${prevLayout}`);
      if (keepBtn) selectLayout(prevLayout, keepBtn);
      updateFormatAvailability(prevLayout, '');
    }
    if (hasQueue) {
      syncPrimaryStartButtonWithQueue(_batchQueueState);
    }
  }
  // Reset file input
  const inp = document.getElementById(`${prefix}-file-input`);
  if (inp) inp.value = '';
}

function setGraphicNovelLock(isComic, reason = '', isScanned = false) {
  state.tr.isComic = !!isComic;
  state.tr.isScanned = !!isScanned;
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
      throw new Error(await parseApiError(res, 'Upload failed'));
    }
    const data = await res.json();
    if (state[prefix].file && file && state[prefix].file.name !== file.name) {
      console.log(`[Upload] File was swapped while upload was in flight; ignoring job ${data.job_id}`);
      return;
    }
    state[prefix].jobId = data.job_id;

    const pages = data.estimated_pages > 0 ? `~${data.estimated_pages} pages · ` : '';
    let durationEst = '';
    if (prefix === 'ab' && data.estimated_pages > 0) {
      const totalMinutes = Math.round(data.estimated_pages * 2);
      const hours = Math.floor(totalMinutes / 60);
      const mins = totalMinutes % 60;
      durationEst = hours > 0
        ? ` · ⏱️ ~${hours} ${hours === 1 ? 'ώρα' : 'ώρες'}${mins > 0 ? ' ' + mins + ' λ' : ''} ακρόαση`
        : ` · ⏱️ ~${mins} λεπτά ακρόαση`;
    }
    document.getElementById(`${prefix}-file-meta`).textContent =
      `${(file.size / 1024 / 1024).toFixed(1)} MB · ${pages}${data.file_type.toUpperCase()}${durationEst} · Ready`;

    const startBtn = document.getElementById(`${prefix}-start-btn`);
    if (startBtn) {
      startBtn.disabled = false;
      if (prefix === 'tr') {
        startBtn.textContent = currentAppMode === 'basic' ? '✨ Μετάφραση Βιβλίου με AI (1-Click)' : '🌐 Start Translation';
      } else if (prefix === 'ab') {
        startBtn.textContent = currentAppMode === 'basic' ? '🎧 Δημιουργία Audiobook με AI (1-Click)' : '🎧 Generate Audiobook';
      }
    }
    if (prefix === 'tr' && !data.is_comic) {
      const directBtn = document.getElementById('tr-direct-polish-btn');
      if (directBtn) directBtn.disabled = false;
    }
    toast(`✅ "${file.name}" uploaded successfully.`, 'success');

    // Direct upload in Audiobook tab: lock Audio Language to detected document language
    if (prefix === 'ab') {
      const transOpt = document.getElementById('ab-translate-option');
      if (transOpt) transOpt.style.display = 'none';
      const useTranslated = document.getElementById('ab-use-translated');
      if (useTranslated) useTranslated.checked = false;
      restrictAudiobookLanguage(data.detected_language || null);
      if (currentAppMode === 'basic') {
        const abAi = document.getElementById('ab-ai-polish');
        if (abAi) abAi.checked = true;
      }
    }

    refreshHistory();
    if (prefix === 'tr') {
      state.tr.file = file;
      const ext = file.name.split('.').pop().toLowerCase();

      // Auto-align translation language direction based on detected document language
      if (data.detected_language === 'greek') {
        setLangs('greek', 'english');
      } else if (data.detected_language === 'english') {
        setLangs('english', 'greek');
      }

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
        // Auto-match output format to input format (PDF->PDF, DOCX->DOCX, EPUB->EPUB, CBZ->CBZ)
        const targetFormat = ['pdf', 'docx', 'epub', 'cbz', 'cbr'].includes(ext) ? ext : 'pdf';
        const fmtBtn = document.getElementById(`fmt-${targetFormat}`);
        if (fmtBtn && !fmtBtn.disabled) {
          selectFormat(targetFormat, fmtBtn);
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

    // Guard against race condition: check if file was removed/swapped during preview fetch
    if (state.tr.jobId !== jobId) return;

    const res = await fetch(`${API}/detect-genre`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample_text: sample.substring(0, 3500), file_type: fileType }),
    });
    if (res.ok) {
      // Guard against race condition: check if file was removed/swapped during genre detection
      if (state.tr.jobId !== jobId) return;

      const gInfo = await res.json();
      _lastDetectedGenreInfo = gInfo;
      const shouldAutoApply = (currentAppMode === 'basic' && Boolean(gInfo.genre));
      showGenreHint(gInfo, shouldAutoApply);
      if (shouldAutoApply) {
        applyDetectedGenre(gInfo.genre, true);
      }
    }
  } catch (e) {
    console.debug('Genre detection skipped:', e);
  }
}

function showGenreHint(gInfo, isAutoApplied = false) {
  const hintEl = document.getElementById('tr-genre-hint');
  if (!hintEl) return;
  const genreTitles = {
    literature: '📖 Λογοτεχνικό (Literature)',
    poetry: '🪶 Ποίηση / Στίχοι (Poetry)',
    technical: '💻 Τεχνικό / Πληροφορική (Technical)',
    formal: '🏛️ Επίσημο / Διοικητικό (Formal)',
    comic: '🎨 Graphic Novel / Comic',
  };
  const genreKey = gInfo?.genre || 'literature';
  const rawTitle = genreTitles[genreKey] || genreKey;
  const confPct = Math.round((gInfo?.confidence || 0.8) * 100);
  const actionHtml = isAutoApplied
    ? `<span id="tr-genre-applied-badge" style="margin-left:auto; font-size:0.76rem; font-weight:600; color:var(--emerald); background:rgba(16,185,129,0.15); padding:4px 10px; border-radius:6px; border:1px solid rgba(16,185,129,0.35); white-space:nowrap">✓ Εφαρμόστηκε αυτόματα</span>`
    : `<button id="tr-genre-apply-btn" class="btn-sm btn-outline" style="margin-left:auto; padding:3px 10px; font-size:0.75rem; white-space:nowrap" data-genre="${escHtml(genreKey)}" onclick="applyDetectedGenre(this.dataset.genre)">Εφαρμογή Προτεινόμενου</button>`;

  hintEl.innerHTML = `
    <span>💡 <strong>Ανιχνεύθηκε ύφος:</strong> ${escHtml(rawTitle)} (${confPct}% βεβαιότητα). ${escHtml(gInfo?.reason || '')}</span>
    ${actionHtml}
  `;
  hintEl.style.display = 'flex';
}

function applyDetectedGenre(genre, silent = false) {
  if (genre === 'comic') {
    const b = document.getElementById('layout-comic');
    if (b) selectLayout('comic', b);
    setGraphicNovelLock(true, _lastDetectedGenreInfo?.reason || 'Graphic Novel / Comic');
  } else if (genre === 'literature' || genre === 'poetry') {
    const b = document.getElementById('layout-literature');
    if (b) selectLayout('literature', b);
  } else {
    const b = document.getElementById('layout-standard');
    if (b) selectLayout('standard', b);
  }

  const applyBtn = document.getElementById('tr-genre-apply-btn');
  if (applyBtn) {
    const badge = document.createElement('span');
    badge.id = 'tr-genre-applied-badge';
    badge.style.cssText = 'margin-left:auto; font-size:0.76rem; font-weight:600; color:var(--emerald); background:rgba(16,185,129,0.15); padding:4px 10px; border-radius:6px; border:1px solid rgba(16,185,129,0.35); white-space:nowrap';
    badge.textContent = silent ? '✓ Εφαρμόστηκε αυτόματα' : '✓ Εφαρμόστηκε';
    if (applyBtn.parentNode) {
      applyBtn.parentNode.replaceChild(badge, applyBtn);
    }
  }

  if (!silent) {
    toast(`✅ Εφαρμόστηκε στυλ: ${genre}`, 'success');
  }
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

  // Sync genre detection hint badge/button with manual layout selection
  const hintEl = document.getElementById('tr-genre-hint');
  if (hintEl && hintEl.style.display !== 'none' && _lastDetectedGenreInfo) {
    const recLayout = (_lastDetectedGenreInfo.genre === 'literature' || _lastDetectedGenreInfo.genre === 'poetry') ? 'literature' : (_lastDetectedGenreInfo.genre === 'comic' ? 'comic' : 'standard');
    const isMatching = (layout === recLayout);
    const existingBadge = document.getElementById('tr-genre-applied-badge');
    const existingBtn = document.getElementById('tr-genre-apply-btn');
    if (isMatching) {
      if (existingBtn && !existingBadge) {
        const badge = document.createElement('span');
        badge.id = 'tr-genre-applied-badge';
        badge.style.cssText = 'margin-left:auto; font-size:0.76rem; font-weight:600; color:var(--emerald); background:rgba(16,185,129,0.15); padding:4px 10px; border-radius:6px; border:1px solid rgba(16,185,129,0.35); white-space:nowrap';
        badge.textContent = (currentAppMode === 'basic') ? '✓ Εφαρμόστηκε αυτόματα' : '✓ Εφαρμόστηκε';
        if (existingBtn.parentNode) {
          existingBtn.parentNode.replaceChild(badge, existingBtn);
        }
      }
    } else {
      if (existingBadge && existingBadge.parentNode) {
        const btnEl = document.createElement('button');
        btnEl.id = 'tr-genre-apply-btn';
        btnEl.className = 'btn-sm btn-outline';
        btnEl.style.cssText = 'margin-left:auto; padding:3px 10px; font-size:0.75rem; white-space:nowrap';
        btnEl.dataset.genre = _lastDetectedGenreInfo.genre || 'literature';
        btnEl.onclick = function() { applyDetectedGenre(this.dataset.genre); };
        btnEl.textContent = 'Εφαρμογή Προτεινόμενου';
        existingBadge.parentNode.replaceChild(btnEl, existingBadge);
      }
    }
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
    if (!res.ok) throw new Error(await parseApiError(res, 'Cover upload failed'));
    toast('✅ Book cover updated successfully! Included in PDF, EPUB & DOCX.', 'success');
    await checkCoverImage(jobId);
  } catch (err) {
    toast(`Failed to upload cover: ${err.message}`, 'error');
  } finally {
    if (e?.target) e.target.value = '';
  }
}

async function removeCoverImage() {
  const jobId = state.tr.jobId;
  if (!jobId) return;
  try {
    const res = await fetch(`${API}/cover/${jobId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to remove cover'));
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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
  Array.from(langSelect.options || []).forEach(opt => {
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
  const lang = document.getElementById('ab-lang-select')?.value || 'greek';
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
function playVoicePreview(voiceCode, event, customText = null) {
  if (event) event.stopPropagation();
  if (currentAudioPreview) {
    currentAudioPreview.pause();
    currentAudioPreview = null;
  }
  const customInput = document.getElementById('ab-custom-preview-text')?.value?.trim();
  const sample = (customText || customInput || '').slice(0, 150);
  let url = `${API}/tts/preview?voice=${encodeURIComponent(voiceCode)}`;
  if (sample) {
    url += `&text=${encodeURIComponent(sample)}`;
  }
  if (typeof Audio !== 'undefined') {
    currentAudioPreview = new Audio(url);
    toast(`🔊 Παραγωγή δείγματος για ${voiceCode}...`, 'info');
    currentAudioPreview.play().catch(e => {
      console.debug('Preview audio playback failed:', e);
    });
  }
}

async function playActiveVoiceCustomPreview() {
  const selectedVoiceName = document.getElementById('ab-voice-selected')?.value || state.selectedVoice;
  const lang = document.getElementById('ab-lang-select')?.value || 'english';
  const voices = (state.voices && state.voices[lang]) || {};
  let voiceCode = voices[selectedVoiceName];
  if (!voiceCode) {
    const firstCode = Object.values(voices)[0];
    voiceCode = firstCode || (lang === 'greek' ? 'el-GR-NestorasNeural' : 'en-US-GuyNeural');
  }

  let customText = document.getElementById('ab-custom-preview-text')?.value?.trim();
  if (!customText && state.ab.jobId) {
    try {
      const res = await fetch(`${API}/jobs/${state.ab.jobId}/text`);
      if (res.ok) {
        const d = await res.json();
        const text = (d.translated_text || d.original_text || '').trim();
        if (text) {
          customText = text.slice(0, 130).replace(/\s+/g, ' ');
          const inputEl = document.getElementById('ab-custom-preview-text');
          if (inputEl) inputEl.value = customText;
        }
      }
    } catch (_) {}
  }
  playVoicePreview(voiceCode, null, customText);
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
  if (!jobId) {
    if (_batchQueueState.total_count > 0) {
      return startBatchQueue();
    }
    toast('Please upload a document first.', 'error');
    return;
  }

  const sourceLang = document.getElementById('tr-source-lang').value;
  const targetLang = document.getElementById('tr-target-lang').value;
  let outputFormat = document.getElementById('tr-output-format').value || 'pdf';
  const rawTrName = document.getElementById('tr-file-name')?.textContent || '';
  const fileExt = (state.tr.file?.name || rawTrName || '').split('.').pop().toLowerCase();
  if (currentAppMode === 'basic' && ['pdf', 'docx', 'epub', 'cbz', 'cbr', 'txt'].includes(fileExt)) {
    outputFormat = fileExt;
    document.getElementById('tr-output-format').value = fileExt;
  }
  const layoutMode = document.getElementById('tr-layout-mode')?.value || 'standard';
  if (layoutMode === 'comic' && (outputFormat === 'txt' || outputFormat === 'docx')) {
    outputFormat = 'pdf';
    document.getElementById('tr-output-format').value = 'pdf';
  }
  const aiPolish = document.getElementById('tr-ai-polish')?.checked || false;
  const apiKey = localStorage.getItem('gemini_api_key') || null;
  let hasKey = Boolean(apiKey);
  try {
    const rawKeys = localStorage.getItem('gemini_api_keys');
    if (rawKeys) {
      const arr = JSON.parse(rawKeys);
      if (Array.isArray(arr) && arr.some(k => typeof k === 'string' && k.trim())) hasKey = true;
    }
  } catch (_) {}
  const readingDirEl = document.querySelector('input[name="tr-reading-dir"]:checked');
  const readingDirection = readingDirEl ? readingDirEl.value : 'ltr';
  const quotaBehaviorEl = document.querySelector('input[name="tr-quota-behavior"]:checked');
  let quotaBehavior = quotaBehaviorEl ? quotaBehaviorEl.value : (hasKey ? 'wait' : 'fallback');
  if (!hasKey && quotaBehavior === 'wait') {
    quotaBehavior = 'fallback';
  }

  // Update download button label to show chosen format
  const labelEl = document.getElementById('tr-format-label');
  if (labelEl) labelEl.textContent = outputFormat.toUpperCase();

  // Show progress UI
  closeEditor();
  document.getElementById('tr-progress-card').style.display = 'block';
  document.getElementById('tr-result-card').classList.remove('visible');
  document.getElementById('tr-error-card').classList.remove('visible');
  document.getElementById('tr-progress-detail').textContent = '';
  setActionButtonsEnabled('tr', false);
  const trCancelBtn = document.getElementById('tr-cancel-btn');
  if (trCancelBtn) {
    trCancelBtn.disabled = false;
    trCancelBtn.innerHTML = '🛑 Cancel Translation';
  }
  setStatusBadge('tr', 'running');
  state.tr.startTime = Date.now();

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
        quota_behavior: quotaBehavior,
      }),
    });
    if (!res.ok) {
      throw new Error(await parseApiError(res, 'Failed to start translation'));
    }

    // Connect SSE for progress
    connectSSE('tr', jobId);
  } catch (err) {
    showError('tr', err.message);
    setActionButtonsEnabled('tr', true);
  }
}

// ── Quota Limit Behavior (Wait vs Auto-Fallback) ────────────────
function onQuotaBehaviorChange(prefix) {
  const sel = document.querySelector(`input[name="${prefix}-quota-behavior"]:checked`);
  const val = sel ? sel.value : 'wait';
  const descEl = document.getElementById(`${prefix}-quota-behavior-desc`);
  const hasKey = Boolean(localStorage.getItem('gemini_api_key'));
  if (descEl) {
    if (val === 'wait') {
      if (!hasKey) {
        descEl.innerHTML = (prefix === 'ab')
          ? '⚠️ <em>Σημείωση:</em> Επιλέξατε Αναμονή για Gemini αλλά δεν έχει εισαχθεί API Key. Συνιστάται η επιλογή Δωρεάν Μοντέλου παρακάτω.'
          : '⚠️ <em>Σημείωση:</em> Επιλέξατε Αναμονή για Gemini αλλά δεν έχει εισαχθεί API Key. Συνιστάται η επιλογή Δωρεάν Μοντέλου παρακάτω ή εισαγωγή κλειδιού στις Ρυθμίσεις.';
      } else {
        descEl.innerHTML = (prefix === 'ab')
          ? '⏳ <em>Αναμονή:</em> Εάν εξαντληθεί το όριο Gemini, η διαδικασία σταματά και περιμένει την επαναφορά για μέγιστη ποιότητα.'
          : '⏳ <em>Αναμονή:</em> Εάν εξαντληθεί το ημερήσιο όριο, η εργασία σταματά με ασφάλεια στο checkpoint και περιμένει τον ζωντανό χρονοδιακόπτη ή νέο API Key (διατηρεί 100% την ποιότητα Gemini).';
      }
    } else {
      if (!hasKey) {
        descEl.innerHTML = (prefix === 'ab')
          ? '🔄 <em>Δωρεάν Μοντέλα (Προεπιλογή):</em> Χωρίς Gemini API Key, η εκφώνηση εκτελείται αυτόματα με το δωρεάν μοντέλο Edge-TTS χωρίς διακοπή και χωρίς όρια.'
          : '🔄 <em>Δωρεάν Μοντέλα (Προεπιλογή):</em> Χωρίς Gemini API Key, χρησιμοποιείται αυτόματα η δωρεάν μηχανή (Google Translate & τυπογραφία) χωρίς διακοπή και χωρίς όρια χρήσης.';
      } else {
        descEl.innerHTML = (prefix === 'ab')
          ? '🔄 <em>Auto-Fallback:</em> Εάν εξαντληθεί το όριο Gemini στο Script Polish, η εκφώνηση συνεχίζει άμεσα χωρίς διακοπή χρησιμοποιώντας το αρχικό κείμενο (δωρεάν Edge-TTS).'
          : '🔄 <em>Auto-Fallback:</em> Εάν εξαντληθεί το όριο Gemini, η εργασία συνεχίζει άμεσα χωρίς διακοπή χρησιμοποιώντας τη δωρεάν μηχανή μετάφρασης (χωρίς όρια χρήσης).';
      }
    }
  }
  try {
    localStorage.setItem(`${prefix}_quota_behavior`, val);
  } catch (_) {}
}

function initQuotaBehaviorSelectors() {
  const hasKey = Boolean(localStorage.getItem('gemini_api_key'));
  const defaultBehavior = hasKey ? 'wait' : 'fallback';
  ['tr', 'ab'].forEach((prefix) => {
    try {
      const saved = localStorage.getItem(`${prefix}_quota_behavior`);
      const targetVal = saved || defaultBehavior;
      const radio = document.querySelector(`input[name="${prefix}-quota-behavior"][value="${targetVal}"]`);
      if (radio) {
        radio.checked = true;
        onQuotaBehaviorChange(prefix);
      }
    } catch (_) {}
  });
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
  state.ab.startTime = Date.now();

  try {
    const isMultiVoice = document.getElementById('ab-multi-voice')?.checked || false;
    const dialogueVoice = isMultiVoice ? (document.getElementById('ab-dialogue-voice-select')?.value || null) : null;
    const quotaBehaviorEl = document.querySelector('input[name="ab-quota-behavior"]:checked');
    let quotaBehavior = quotaBehaviorEl ? quotaBehaviorEl.value : (apiKey ? 'wait' : 'fallback');
    if (!apiKey && quotaBehavior === 'wait') {
      quotaBehavior = 'fallback';
    }

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
        quota_behavior: quotaBehavior,
      }),
    });
    if (!res.ok) {
      throw new Error(await parseApiError(res, 'Failed to start audiobook generation'));
    }

    connectSSE('ab', jobId);
  } catch (err) {
    showError('ab', err.message);
    document.getElementById('ab-start-btn').disabled = false;
    document.getElementById('ab-start-btn').textContent = currentAppMode === 'basic' ? '🎧 Δημιουργία Audiobook με AI (1-Click)' : '🎧 Generate Audiobook';
    if (currentAppMode === 'basic') {
      const abAi = document.getElementById('ab-ai-polish');
      if (abAi) abAi.checked = true;
    }
  }
}

// ── SSE Progress Stream ────────────────────────────────────
function connectSSE(prefix, jobId) {
  stopJobTracking(prefix);

  const sse = new EventSource(`${API}/progress/${jobId}`);
  state[prefix].sse = sse;

  sse.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (parseErr) {
      console.warn('Malformed SSE JSON payload ignored:', parseErr);
      return;
    }
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
    if (['done', 'error', 'cancelled'].includes(state[prefix].status)) {
      return;
    }
    pollProgress(prefix, jobId);
  };
}

function pollProgress(prefix, jobId) {
  stopJobTracking(prefix);
  let consecutiveErrors = 0;
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`${API}/status/${jobId}`);
      if (!res.ok) {
        consecutiveErrors += 1;
        if (res.status === 404 || consecutiveErrors >= 5) {
          stopJobTracking(prefix);
          showError(prefix, await parseApiError(res, 'Lost connection to job status'));
          setActionButtonsEnabled(prefix, true);
        }
        return;
      }
      consecutiveErrors = 0;
      const data = await res.json();
      updateProgress(prefix, data);
      if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
        stopJobTracking(prefix);
      }
    } catch (e) {
      consecutiveErrors += 1;
      if (consecutiveErrors >= 5) {
        stopJobTracking(prefix);
        showError(prefix, 'Connection to server lost while tracking progress.');
        setActionButtonsEnabled(prefix, true);
      }
    }
  }, 2000);
  state[prefix].pollInterval = interval;
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

  const fileMetaEl = document.getElementById(`${prefix}-file-meta`);
  if (fileMetaEl && (data.total_pages > 0 || data.total_chunks > 0)) {
    const pagesTag = data.total_pages > 0 ? `${data.total_pages} pages · ` : '';
    const fmtTag = data.output_format ? `${data.output_format.toUpperCase()} · ` : '';
    const statusLabel = data.status === 'done' ? 'Completed' : (data.status === 'running' ? 'In Progress' : 'Ready');
    fileMetaEl.textContent = `${pagesTag}${fmtTag}${statusLabel}`;
  }

  // Update Hybrid Engine Badge
  const engineBadge = document.getElementById(`${prefix}-engine-badge`);
  if (engineBadge) {
    if (prefix === 'tr') {
      const stepLower = (data.current_step || '').toLowerCase();
      const isAiStep = Boolean(data.ai_polish) || stepLower.includes('ai translation') || stepLower.includes('polish') || stepLower.includes('gemini');
      if (data.quota_behavior === 'fallback' && (stepLower.includes('όριο') || stepLower.includes('δωρεάν') || data.gemini_quota_exhausted)) {
        engineBadge.style.display = 'inline-flex';
        engineBadge.className = 'engine-pill engine-free';
        engineBadge.textContent = '⚡ Free Engine';
      } else if (isAiStep) {
        engineBadge.style.display = 'inline-flex';
        engineBadge.className = 'engine-pill engine-gemini';
        engineBadge.textContent = '✨ Gemini Flash';
      } else {
        engineBadge.style.display = 'inline-flex';
        engineBadge.className = 'engine-pill engine-free';
        engineBadge.textContent = '⚡ Google Translate';
      }
    } else {
      engineBadge.style.display = 'inline-flex';
      engineBadge.className = 'engine-pill engine-free';
      engineBadge.textContent = '⚡ Edge-TTS Neural';
    }
  }

  // Update Live ETA & Processing Speed
  const etaEl = document.getElementById(`${prefix}-progress-eta`);
  if (etaEl) {
    if (!state[prefix].startTime && data.status === 'running') {
      state[prefix].startTime = Date.now();
    }
    const elapsed = state[prefix].startTime ? (Date.now() - state[prefix].startTime) / 1000 : 0;
    const done = Number(data.done_chunks || data.done_pages || 0);
    const total = Number(data.total_chunks || data.total_pages || 0);
    if (elapsed >= 3 && done > 0 && total > done && data.status === 'running') {
      const rate = done / elapsed;
      const remSec = Math.max(1, Math.round((total - done) / rate));
      const remMin = Math.floor(remSec / 60);
      const s = remSec % 60;
      const timeStr = remMin > 0 ? `~${remMin}λ ${s}δ` : `~${s}δ`;
      const unitStr = (prefix === 'tr' && data.total_pages > 0) ? `${Math.round(rate * 60)} σελ/λ` : `${rate.toFixed(1)} τμήματα/δ`;
      etaEl.innerHTML = `⏳ Απομένουν: <strong>${timeStr}</strong> (${unitStr})`;
      etaEl.style.display = 'inline-block';
    } else {
      etaEl.style.display = 'none';
    }
  }

  // Single-document Gemini quota warning banner
  const quotaBanner = document.getElementById(`${prefix}-quota-warning-banner`);
  const quotaText = document.getElementById(`${prefix}-quota-warning-text`);
  if (quotaBanner) {
    if (data.gemini_quota_exhausted) {
      quotaBanner.style.display = 'block';
      if (quotaText) {
        quotaText.textContent = data.gemini_quota_message || 'Εξαντλήθηκε το ημερήσιο όριο του Gemini API (Free Tier).';
      }
      if (data.gemini_quota_reset_timestamp) {
        startGeminiQuotaCountdown(data.gemini_quota_reset_timestamp, data.gemini_quota_reset_time_str);
      }
    } else {
      if (!_geminiResetTimestamp) {
        quotaBanner.style.display = 'none';
      }
    }
  }

  // Show detail while actively running
  const detailEl = document.getElementById(`${prefix}-progress-detail`);
  if (data.total_chunks > 0 && data.status !== 'done') {
    if (prefix === 'tr') {
      const stepLower = (data.current_step || '').toLowerCase();
      const totalPages = Number(data.total_pages || 0);
      const donePages = Number(data.done_pages || 0);
      const isBatchMode =
        stepLower.includes('batch') ||
        stepLower.includes('single-pass') ||
        stepLower.includes('ai translation') ||
        (totalPages > 0 && totalPages > data.total_chunks);
      if (isBatchMode) {
        if (totalPages > 0 && donePages > 0) {
          detailEl.textContent = `Completed ${data.done_chunks} of ${data.total_chunks} AI batches (${donePages} / ${totalPages} pages)`;
        } else if (totalPages > 0) {
          detailEl.textContent = `Completed ${data.done_chunks} of ${data.total_chunks} AI batches (${totalPages} pages total)`;
        } else {
          detailEl.textContent = `Completed ${data.done_chunks} of ${data.total_chunks} AI batches (~4–5 pages each)`;
        }
      } else {
        detailEl.textContent = `Translated ${data.done_chunks} of ${data.total_chunks} pages`;
      }
    } else {
      detailEl.textContent = `Generated audio part ${data.done_chunks} of ${data.total_chunks}`;
    }
  } else if (data.status === 'done') {
    detailEl.textContent = '';
  }

  if (data.status === 'running') {
    const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
    if (cancelBtn) {
      cancelBtn.style.display = 'inline-flex';
      cancelBtn.disabled = false;
    }
  }

  if (data.status === 'done') {
    state[prefix].status = 'done';
    setStatusBadge(prefix, 'done');
    document.getElementById(`${prefix}-progress-bar`).classList.remove('shimmer');
    document.getElementById(`${prefix}-progress-step`).textContent = '✅ Complete';
    setActionButtonsEnabled(prefix, true);
    const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
    if (cancelBtn) cancelBtn.style.display = 'none';
    showResult(prefix, data);
    refreshHistory();
    toast(prefix === 'tr' ? '✅ Translation complete!' : '🎉 Audiobook ready!', 'success');
  } else if (data.status === 'error') {
    state[prefix].status = 'error';
    setStatusBadge(prefix, 'error');
    const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
    if (cancelBtn) cancelBtn.style.display = 'none';
    showError(prefix, data.error || 'An unknown error occurred.');
    setActionButtonsEnabled(prefix, true);
    refreshHistory();
  } else if (data.status === 'cancelled') {
    state[prefix].status = 'cancelled';
    setStatusBadge(prefix, 'cancelled');
    document.getElementById(`${prefix}-progress-bar`).classList.remove('shimmer');
    document.getElementById(`${prefix}-progress-step`).textContent = '🛑 Cancelled';
    if (detailEl) detailEl.textContent = 'Process was cancelled.';
    setActionButtonsEnabled(prefix, true);
    const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
    if (cancelBtn) {
      cancelBtn.disabled = false;
      cancelBtn.style.display = 'none';
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
function setActionButtonsEnabled(prefix, enabled) {
  const startBtn = document.getElementById(`${prefix}-start-btn`);
  if (startBtn) {
    startBtn.disabled = !enabled;
    if (prefix === 'tr') {
      startBtn.textContent = currentAppMode === 'basic' ? '✨ Μετάφραση Βιβλίου με AI (1-Click)' : '🌐 Start Translation';
    } else if (prefix === 'ab') {
      startBtn.textContent = currentAppMode === 'basic' ? '🎧 Δημιουργία Audiobook με AI (1-Click)' : '🎧 Generate Audiobook';
    }
  }
  if (prefix === 'tr') {
    const directBtn = document.getElementById('tr-direct-polish-btn');
    if (directBtn) directBtn.disabled = !enabled || Boolean(state.tr.isComic);
  }
}

function resetProgress(prefix, keepButtonsEnabled = false) {
  document.getElementById(`${prefix}-progress-card`).style.display = 'none';
  document.getElementById(`${prefix}-result-card`).classList.remove('visible');
  document.getElementById(`${prefix}-error-card`).classList.remove('visible');
  document.getElementById(`${prefix}-progress-bar`).style.width = '0%';
  document.getElementById(`${prefix}-progress-bar`).classList.add('shimmer');
  document.getElementById(`${prefix}-progress-pct`).textContent = '0%';
  if (!keepButtonsEnabled) {
    setActionButtonsEnabled(prefix, false);
  }
  const etaEl = document.getElementById(`${prefix}-progress-eta`);
  if (etaEl) { etaEl.style.display = 'none'; etaEl.textContent = ''; }
  const eng = document.getElementById(`${prefix}-engine-badge`);
  if (eng) eng.style.display = 'none';
  state[prefix].startTime = null;
  const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
  if (cancelBtn) {
    cancelBtn.disabled = false;
    cancelBtn.innerHTML = prefix === 'tr' ? '🛑 Cancel Translation' : '🛑 Cancel Audiobook';
  }

  if (prefix === 'tr') {
    closeEditor();
  }
  if (prefix === 'ab') {
    const audio = document.getElementById('ab-audio-element');
    if (audio) {
      if (typeof audio.pause === 'function') {
        audio.pause();
      }
      audio.currentTime = 0;
      audio.src = '';
    }
    const playerWrap = document.getElementById('ab-player-container');
    if (playerWrap) playerWrap.style.display = 'none';
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

  const resQuota = document.getElementById(`${prefix}-result-quota-notice`);
  const resQuotaText = document.getElementById(`${prefix}-result-quota-text`);
  if (resQuota) {
    if (data && data.gemini_quota_exhausted) {
      resQuota.style.display = 'block';
      if (resQuotaText) {
        resQuotaText.textContent = data.gemini_quota_message || 'Το ημερήσιο όριο του Gemini API εξαντλήθηκε κατά τη μετάφραση. Το έγγραφο ολοκληρώθηκε με τη βασική μηχανή μετάφρασης.';
      }
    } else {
      resQuota.style.display = 'none';
    }
  }
  if (prefix === 'tr') {
    const serverFmt = (data?.output_format || '').toLowerCase();
    const curFmt = (document.getElementById('tr-output-format')?.value || '').toLowerCase();
    const fmt = serverFmt || curFmt || 'pdf';
    const label = fmt.toUpperCase();
    const trFmtInput = document.getElementById('tr-output-format');
    if (trFmtInput) trFmtInput.value = fmt;
    const layout = (data?.layout_mode || document.getElementById('tr-layout-mode')?.value || 'standard').toLowerCase();
    if (layout === 'comic') {
      meta.textContent = 'Το Graphic Novel / Comic μεταφράστηκε με επιτυχία! Η εικονογράφηση διατηρήθηκε 100% και τα μπαλόνια διαλόγου αποδόθηκαν στα Ελληνικά.';
    } else {
      meta.textContent = `Your document has been translated. Click below to download the ${label} file.`;
    }
    // Keep format label in download button in sync
    const labelEl = document.getElementById('tr-format-label');
    if (labelEl) {
      labelEl.textContent = layout === 'comic' ? `Graphic Novel (${fmt.toUpperCase()})` : label;
    }
    const dlBtn = document.getElementById('tr-download-btn');
    if (dlBtn && state.tr.jobId) {
      dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}&layout=${layout}`;
      dlBtn.setAttribute('aria-disabled', 'false');
      dlBtn.setAttribute('tabindex', '0');
      dlBtn.style.opacity = '';
      dlBtn.style.pointerEvents = '';
      dlBtn.style.cursor = 'pointer';
    }
    const audioLangSelect = document.getElementById('tr-audio-lang');
    const targetLang = document.getElementById('tr-target-lang')?.value || 'greek';
    if (audioLangSelect) {
      audioLangSelect.value = targetLang;
    }
    playCompletionNotification('BookApp — Μετάφραση Ολοκληρώθηκε!', 'Το βιβλίο σας μεταφράστηκε με επιτυχία και είναι έτοιμο για λήψη ή ανάγνωση.');
  } else {
    meta.textContent = 'Your audiobook has been generated. Click below to download or listen to the MP3 file.';
    const playerWrap = document.getElementById('ab-player-container');
    const audio = document.getElementById('ab-audio-element');
    const trackTitle = document.getElementById('ab-player-title');
    const trackVoice = document.getElementById('ab-player-voice');
    if (playerWrap && audio && state.ab.jobId) {
      playerWrap.style.display = 'block';
      audio.src = `${API}/download/${state.ab.jobId}`;
      if (trackTitle) trackTitle.textContent = (data && data.file_name) || state.ab.file?.name || 'Audiobook';
      if (trackVoice) {
        const vName = (data && data.voice_name) || state.selectedVoice || 'Neural Voice';
        trackVoice.textContent = `${vName} · MP3 High Fidelity`;
      }
    }
    const abDlBtn = document.getElementById('ab-download-btn');
    if (abDlBtn && state.ab.jobId) {
      abDlBtn.href = `${API}/download/${state.ab.jobId}`;
    }
    const abM4bBtn = document.getElementById('ab-download-m4b-btn');
    if (abM4bBtn && state.ab.jobId) {
      abM4bBtn.href = `${API}/download/${state.ab.jobId}?format=m4b`;
    }
    playCompletionNotification('BookApp — Audiobook Έτοιμο!', 'Το ηχητικό βιβλίο ολοκληρώθηκε με επιτυχία και είναι έτοιμο για ακρόαση.');
  }
  card.classList.add('visible');
}

function playCompletionChime() {
  try {
    if (typeof window === 'undefined') return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;
    const notes = [
      { freq: 523.25, start: now, dur: 0.18 },       // C5
      { freq: 783.99, start: now + 0.15, dur: 0.35 } // G5
    ];
    notes.forEach(note => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(note.freq, note.start);
      gain.gain.setValueAtTime(0.12, note.start);
      gain.gain.exponentialRampToValueAtTime(0.001, note.start + note.dur);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(note.start);
      osc.stop(note.start + note.dur);
    });
  } catch (_) {}
}

function sendDesktopNotification(title, body) {
  try {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      if (Notification.permission === 'granted') {
        new Notification(title, { body, icon: '/favicon.ico' });
      } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(permission => {
          if (permission === 'granted') {
            new Notification(title, { body, icon: '/favicon.ico' });
          }
        });
      }
    }
  } catch (_) {}
}

function playCompletionNotification(title, message) {
  playCompletionChime();
  sendDesktopNotification(title, message);
}

async function copyTranslatedText() {
  const jobId = state.tr.jobId;
  if (!jobId) {
    toast('Δεν υπάρχει μεταφρασμένο έγγραφο.', 'error');
    return;
  }
  const btn = document.getElementById('tr-copy-btn');
  const origHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.innerHTML = '⏳ Αντιγραφή...';
    btn.disabled = true;
  }

  try {
    let textToCopy = '';
    if (typeof _readerData !== 'undefined' && _readerData && _readerData.translated_text) {
      textToCopy = _readerData.translated_text;
    } else {
      const res = await fetch(`${API}/jobs/${jobId}/text`);
      if (res.ok) {
        const data = await res.json();
        _readerData = data;
        textToCopy = (data.translated_text || data.original_text || '').trim();
      }
    }

    if (!textToCopy) {
      toast('Δεν βρέθηκε κείμενο προς αντιγραφή.', 'warning');
      if (btn) {
        btn.innerHTML = origHtml;
        btn.disabled = false;
      }
      return;
    }

    if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(textToCopy);
    } else if (typeof document !== 'undefined') {
      try {
        const ta = document.createElement('textarea');
        ta.value = textToCopy;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        if (document.body && document.body.appendChild) document.body.appendChild(ta);
        if (ta.focus) ta.focus();
        if (ta.select) ta.select();
        if (document.execCommand) document.execCommand('copy');
        if (document.body && document.body.removeChild) document.body.removeChild(ta);
      } catch (_) {}
    }

    if (btn) {
      btn.innerHTML = '✅ Αντιγράφηκε!';
      setTimeout(() => {
        if (btn) {
          btn.innerHTML = origHtml;
          btn.disabled = false;
        }
      }, 2500);
    }
    toast('📋 Το μεταφρασμένο κείμενο αντιγράφηκε στο πρόχειρο!', 'success');
  } catch (err) {
    toast(`Αποτυχία αντιγραφής: ${err.message}`, 'error');
    if (btn) {
      btn.innerHTML = origHtml;
      btn.disabled = false;
    }
  }
}

function showError(prefix, msg) {
  const errEl = document.getElementById(`${prefix}-error-msg`);
  if (errEl) errEl.textContent = msg;
  const card = document.getElementById(`${prefix}-error-card`);
  if (card) card.classList.add('visible');

  const isQuota = msg && (msg.includes('όριο') || msg.includes('Quota') || msg.includes('quota') || msg.includes('429'));
  const quotaActions = document.getElementById(`${prefix}-error-quota-actions`);
  if (quotaActions) quotaActions.style.display = isQuota ? 'inline-flex' : 'none';
  const resumeBtn = document.getElementById(`${prefix}-resume-btn`);
  if (resumeBtn) resumeBtn.style.display = isQuota ? 'inline-flex' : 'none';
  const keyBtn = document.getElementById(`${prefix}-quota-key-btn`);
  if (keyBtn) keyBtn.style.display = isQuota ? 'inline-flex' : 'none';
}

async function resumeTranslation(prefix = 'tr') {
  const errCard = document.getElementById(`${prefix}-error-card`);
  if (errCard) errCard.classList.remove('visible');
  const resumeBtn = document.getElementById(`${prefix}-resume-btn`);
  if (resumeBtn) resumeBtn.style.display = 'none';
  const errResumeBtn = document.getElementById(`${prefix}-error-resume-btn`);
  if (errResumeBtn) errResumeBtn.style.display = 'none';
  const quotaKeyBtn = document.getElementById(`${prefix}-quota-key-btn`);
  if (quotaKeyBtn) quotaKeyBtn.style.display = 'none';
  const errQuotaActions = document.getElementById(`${prefix}-error-quota-actions`);
  if (errQuotaActions) errQuotaActions.style.display = 'none';

  if (prefix === 'ab') {
    toast('Συνέχιση Audiobook από το αποθηκευμένο σημείο (checkpoint)...', 'info');
    await startAudiobook();
  } else {
    toast('Συνέχιση μετάφρασης από το αποθηκευμένο σημείο (checkpoint)...', 'info');
    await startTranslation();
  }
}

function setStatusBadge(prefix, status) {
  const badge = document.getElementById(`${prefix}-status-badge`);
  badge.className = `status-badge status-${status}`;
  const labels = { idle: 'Idle', running: 'Running', done: 'Complete', error: 'Error', cancelled: 'Cancelled' };
  badge.innerHTML = `<span class="status-dot"></span> ${labels[status] || status}`;
}

async function downloadOutput(prefix, overrideFmt = null) {
  const jobId = state[prefix].jobId;
  if (!jobId) return;
  if (state[prefix].status === 'running') {
    const action = prefix === 'tr' ? 'translation' : 'audiobook generation';
    toast(`⏳ Please wait until this ${action} is completed before downloading.`, 'info');
    return;
  }
  if (prefix === 'tr') {
    const fmt = overrideFmt || document.getElementById('tr-output-format')?.value || 'txt';
    const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
    const targetUrl = `${API}/download/${jobId}?format=${fmt}&layout=${layout}`;
    window.location.href = targetUrl;
  } else {
    const targetUrl = overrideFmt ? `${API}/download/${jobId}?format=${overrideFmt}` : `${API}/download/${jobId}`;
    window.location.href = targetUrl;
  }
}

function downloadOutputM4b() {
  downloadOutput('ab', 'm4b');
}

function audioSkip(seconds) {
  const audio = document.getElementById('ab-audio-element');
  if (audio) {
    audio.currentTime = Math.max(0, Math.min(audio.duration || Infinity, audio.currentTime + seconds));
  }
}

function setAudioSpeed(rate, btn) {
  const audio = document.getElementById('ab-audio-element');
  if (audio) {
    audio.playbackRate = rate;
  }
  document.querySelectorAll('.ab-speed-pills .speed-pill').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

function onAudioChapterSelect(val) {
  const audio = document.getElementById('ab-audio-element');
  if (audio && val) {
    const sec = parseFloat(val);
    if (!isNaN(sec) && sec >= 0) {
      audio.currentTime = sec;
      if (typeof audio.play === 'function') {
        audio.play().catch(() => {});
      }
    }
  }
}

function sendToAudiobook() {
  if (!state.tr.jobId) return;
  stopJobTracking('ab');
  resetProgress('ab', true);
  // Transfer job ID and file metadata to the audiobook tab
  state.ab.jobId = state.tr.jobId;
  state.ab.file = state.tr.file;

  const rawTrName = document.getElementById('tr-file-name')?.textContent;
  const rawTrMeta = document.getElementById('tr-file-meta')?.textContent;
  const trIcon = document.getElementById('tr-file-icon')?.textContent || '📄';
  const trName = (rawTrName && rawTrName !== 'filename.pdf') ? rawTrName : 'Document';
  const trMeta = (rawTrMeta && rawTrMeta !== 'Loading...') ? rawTrMeta : 'Ready';

  const abIcon = document.getElementById('ab-file-icon');
  const abName = document.getElementById('ab-file-name');
  const abMeta = document.getElementById('ab-file-meta');
  if (abIcon) abIcon.textContent = trIcon;
  if (abName) abName.textContent = trName;
  if (abMeta) {
    let metaTxt = trMeta;
    const pageMatch = trMeta.match(/~(\d+)\s+pages/);
    if (pageMatch) {
      const p = parseInt(pageMatch[1], 10);
      const totalMinutes = Math.round(p * 2);
      const hours = Math.floor(totalMinutes / 60);
      const mins = totalMinutes % 60;
      const durationEst = hours > 0
        ? ` · ⏱️ ~${hours} ${hours === 1 ? 'ώρα' : 'ώρες'}${mins > 0 ? ' ' + mins + ' λ' : ''} ακρόαση`
        : ` · ⏱️ ~${mins} λεπτά ακρόαση`;
      metaTxt = trMeta.replace(/\s*·\s*⏱️.*?ακρόαση/g, '').replace(/ · Ready$/, '') + durationEst + ' · Ready';
    }
    abMeta.textContent = metaTxt;
  }

  document.getElementById('ab-upload-zone').style.display = 'none';
  const abSel = document.getElementById('ab-selected-file');
  if (abSel) {
    abSel.style.display = '';
    abSel.classList.add('visible');
  }
  document.getElementById('ab-start-btn').disabled = false;
  document.getElementById('ab-start-btn').textContent = currentAppMode === 'basic' ? '🎧 Δημιουργία Audiobook με AI (1-Click)' : '🎧 Generate Audiobook';
  if (currentAppMode === 'basic') {
    const abAi = document.getElementById('ab-ai-polish');
    if (abAi) abAi.checked = true;
  }

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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const jobs = await res.json();
    const jobList = Array.isArray(jobs) ? jobs : [];
    renderHistory(jobList);
    checkSmartResume(jobList);
  } catch (e) {
    console.warn('Could not refresh history:', e);
  }
}

function renderHistory(jobs) {
  const grid = document.getElementById('history-grid');
  const clearBtn = document.getElementById('clear-history-btn');

  const testPrefixes = ['test_', 'reg_', 'mock_', 'sample_', 'q_iso_', 'cover_check', 'sse_test', 'sse_thread', 'cancel_guard', 'scanned_only', 'book_', 'book', 'path_', 'direct_text', 'temp_', 'stress_', 'bench_'];
  const testExact = ['sample.pdf', 'sample.txt', 'book.pdf', 'book.txt', 'active.pdf', 'direct_text.txt', 'direct_text'];
  const displayJobs = (jobs || []).filter(j => {
    const fn = (j.file_name || '').toLowerCase().trim();
    const jid = (j.job_id || '').toLowerCase().trim();
    if (!fn && !jid) return false;
    if (testExact.includes(fn)) return false;
    if (testPrefixes.some(p => fn.startsWith(p) || (jid && jid.startsWith(p)))) return false;
    return true;
  });

  if (!displayJobs || displayJobs.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted); font-size:0.9rem;">No jobs yet. Upload a document to get started.</p>';
    if (clearBtn) clearBtn.style.display = 'none';
    return;
  }

  if (clearBtn) clearBtn.style.display = 'inline-flex';

  const modeIcon = { translate: '🌐', audiobook: '🎧', '': '📄' };
  const statusIcon = { done: '✅', running: '⏳', error: '❌', idle: '🔵' };

  grid.innerHTML = displayJobs.map(j => `
    <div class="history-item" data-job-id="${escHtml(j.job_id)}" data-mode="${escHtml(j.mode || '')}" onclick="loadHistoryJob(this.dataset.jobId, this.dataset.mode)">
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
      <button class="history-delete-btn" data-job-id="${escHtml(j.job_id)}" onclick="deleteHistoryJob(event, this.dataset.jobId)" title="Delete this job">✕</button>
    </div>
  `).join('');
}

async function deleteHistoryJob(event, jobId) {
  event.stopPropagation();
  try {
    const res = await fetch(`${API}/jobs/${jobId}`, { method: 'DELETE' });
    if (res.ok) {
      toast('Job removed from history.', 'info');
      if (state.tr.jobId === jobId) removeFile('tr');
      if (state.ab.jobId === jobId) removeFile('ab');
      await refreshHistory();
      await refreshBatchQueue();
    } else {
      toast(await parseApiError(res, 'Failed to delete job'), 'error');
    }
  } catch (err) {
    toast('Failed to delete job.', 'error');
  }
}

async function clearAllHistory() {
  const doConfirm = (typeof window !== 'undefined' && typeof window.confirm === 'function')
    ? window.confirm
    : (typeof confirm === 'function' ? confirm : null);
  if (doConfirm && !doConfirm('Are you sure you want to delete all session history and temporary files?')) {
    return;
  }
  try {
    const res = await fetch(`${API}/jobs`, { method: 'DELETE' });
    if (res.ok) {
      toast('All session history deleted.', 'success');
      if (state.tr.jobId) removeFile('tr');
      else resetProgress('tr');
      if (state.ab.jobId) removeFile('ab');
      else resetProgress('ab');
      await refreshHistory();
      await refreshBatchQueue();
    } else {
      toast(await parseApiError(res, 'Failed to clear history'), 'error');
    }
  } catch (err) {
    toast('Failed to clear history.', 'error');
  }
}

async function loadHistoryJob(jobId, mode) {
  const onAudiobookTab = document.getElementById('tab-audiobook')?.classList.contains('active');
  const targetTab = (mode === 'audiobook' || mode === 'translate') ? mode : (onAudiobookTab ? 'audiobook' : 'translate');
  const prefix = targetTab === 'audiobook' ? 'ab' : 'tr';

  try {
    const res = await fetch(`${API}/status/${jobId}`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Job not found'));
    const data = await res.json();

    stopJobTracking(prefix);
    state[prefix].jobId = jobId;
    state[prefix].file = null;
    switchTab(targetTab);

    if (data.file_name) {
      const nameEl = document.getElementById(`${prefix}-file-name`);
      const metaEl = document.getElementById(`${prefix}-file-meta`);
      const uploadZone = document.getElementById(`${prefix}-upload-zone`);
      const selectedFile = document.getElementById(`${prefix}-selected-file`);
      if (nameEl) nameEl.textContent = data.file_name;
      const pagesTag = data.total_pages > 0 ? `${data.total_pages} pages · ` : '';
      const fmtTag = data.output_format ? `${data.output_format.toUpperCase()} · ` : '';
      if (metaEl) {
        const statusLabel = data.status === 'done' ? 'Completed' : (data.status === 'running' ? 'In Progress' : 'Ready');
        metaEl.textContent = `Loaded from Session History · ${pagesTag}${fmtTag}${statusLabel}`;
      }
      if (uploadZone) uploadZone.style.display = 'none';
      if (selectedFile) {
        selectedFile.style.display = '';
        selectedFile.classList.add('visible');
      }
    }

    if (prefix === 'tr') {
      const ext = (data.file_type || (data.file_name || '').split('.').pop() || '').toLowerCase();
      const isComic = data.layout_mode === 'comic' || ['cbz', 'cbr', 'zip'].includes(ext);

      // Restore original language direction
      if (data.source_lang && data.target_lang && langConfig[data.source_lang] && langConfig[data.target_lang]) {
        setLangs(data.source_lang, data.target_lang);
      }

      // Restore comic lock or original layout style (standard / literature)
      setGraphicNovelLock(isComic);
      if (!isComic) {
        const savedLayout = (data.layout_mode === 'literature') ? 'literature' : 'standard';
        const layoutBtn = document.getElementById(`layout-${savedLayout}`);
        if (layoutBtn) selectLayout(savedLayout, layoutBtn);
      }

      // Restore original output format (pdf / epub / docx / txt / cbz / cbr)
      if (data.output_format) {
        const savedFmt = data.output_format.toLowerCase();
        const fmtBtn = document.getElementById(`fmt-${savedFmt}`);
        if (fmtBtn && !fmtBtn.disabled) {
          selectFormat(savedFmt, fmtBtn);
        } else {
          const trFmtInput = document.getElementById('tr-output-format');
          if (trFmtInput) trFmtInput.value = savedFmt;
          const labelEl = document.getElementById('tr-format-label');
          if (labelEl) labelEl.textContent = savedFmt.toUpperCase();
        }
      }

      // Restore AI Polish checkbox & reading direction
      const aiChk = document.getElementById('tr-ai-polish');
      if (aiChk && typeof data.ai_polish === 'boolean') {
        aiChk.checked = data.ai_polish;
      }
      if (data.reading_direction) {
        const dirRadio = document.querySelector(`input[name="tr-reading-dir"][value="${data.reading_direction}"]`);
        if (dirRadio) dirRadio.checked = true;
      }
      // Restore Quota Behavior preference
      if (data.quota_behavior) {
        const quotaRadio = document.querySelector(`input[name="tr-quota-behavior"][value="${data.quota_behavior}"]`);
        if (quotaRadio) {
          quotaRadio.checked = true;
          onQuotaBehaviorChange('tr');
        }
      }
    }

    if (prefix === 'ab') {
      setActionButtonsEnabled('ab', true);
      if (data.quota_behavior) {
        const abQuotaRadio = document.querySelector(`input[name="ab-quota-behavior"][value="${data.quota_behavior}"]`);
        if (abQuotaRadio) {
          abQuotaRadio.checked = true;
          onQuotaBehaviorChange('ab');
        }
      }
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
      setActionButtonsEnabled(prefix, false);
      state[prefix].status = 'running';
      setStatusBadge(prefix, 'running');
      updateProgress(prefix, data);
      connectSSE(prefix, jobId);
    } else if (data.has_output && data.status === 'done' && (prefix === 'tr' || mode === 'audiobook')) {
      resetProgress(prefix, true);
      state[prefix].status = 'done';
      setActionButtonsEnabled(prefix, true);
      showResult(prefix, data);
      setStatusBadge(prefix, 'done');
      document.getElementById(`${prefix}-progress-card`).style.display = 'block';
      document.getElementById(`${prefix}-progress-pct`).textContent = '100%';
      document.getElementById(`${prefix}-progress-bar`).style.width = '100%';
      document.getElementById(`${prefix}-progress-step`).textContent = data.current_step;
    } else {
      // Idle, queued, cancelled, or error job loaded from history -> reset progress FIRST, then enable buttons!
      resetProgress(prefix, true);
      state[prefix].status = data.status || 'idle';
      setActionButtonsEnabled(prefix, true);
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
  const typeClass = { success: 'toast-success', error: 'toast-error', info: 'toast-info', warning: 'toast-warning' };
  el.className = `toast ${typeClass[type] || ''}`;
  const span = document.createElement('span');
  span.textContent = msg;
  el.appendChild(span);
  container.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function escHtml(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g, '&#39;');
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
    if (typeof editorCard?.scrollIntoView === 'function') {
      editorCard.scrollIntoView({ behavior: 'smooth' });
    }
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
    if (count > 0) markEditorDirty();
    updateEditorStats();
    toast(`Replaced ${count} occurrences.`, 'success');
  } else {
    if (text.includes(findVal)) {
      textarea.value = text.replace(findVal, replVal);
      markEditorDirty();
      updateEditorStats();
      toast('Replaced first occurrence.', 'success');
    } else {
      toast('Text not found.', 'info');
    }
  }
}

async function saveEditorText() {
  const jobId = state.tr.jobId;
  if (!jobId) {
    toast('Run AI Polish or upload a document first to create a saveable job.', 'info');
    return;
  }

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

// ── Distraction-Free Reader ────────────────────────────────
let _readerFontSizeScale = 1.0;
let _readerData = null;

async function openReaderModal(targetJobId = null) {
  const jobId = targetJobId || state.tr.jobId;
  if (!jobId) {
    toast('Δεν υπάρχει επιλεγμένο έγγραφο για ανάγνωση.', 'error');
    return;
  }
  const modal = document.getElementById('reader-modal');
  if (!modal) return;
  modal.style.display = 'flex';

  const titleEl = document.getElementById('reader-book-title');
  const fileName = document.getElementById('tr-file-name')?.textContent || 'Βιβλίο';
  if (titleEl) titleEl.textContent = fileName;

  const singleContent = document.getElementById('reader-single-content');
  const origText = document.getElementById('reader-orig-text');
  const transText = document.getElementById('reader-trans-text');
  if (singleContent) singleContent.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-muted)">⏳ Φόρτωση κειμένου ανάγνωσης...</div>';

  try {
    const res = await fetch(`${API}/jobs/${jobId}/text`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to fetch book text'));
    _readerData = await res.json();
    const greekText = (_readerData.translated_text || '').trim() || (_readerData.original_text || '').trim();
    const englishText = (_readerData.original_text || '').trim();

    if (singleContent) {
      if (greekText) {
        singleContent.innerHTML = formatReaderText(greekText);
      } else {
        singleContent.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-muted)">Δεν βρέθηκε μεταφρασμένο κείμενο για ανάγνωση.</div>';
      }
    }
    if (transText) transText.innerHTML = formatReaderText(greekText);
    if (origText) origText.innerHTML = formatReaderText(englishText);
  } catch (err) {
    if (singleContent) singleContent.innerHTML = `<div style="color:var(--rose); padding:20px">Σφάλμα φόρτωσης: ${escHtml(err.message)}</div>`;
  }
}

function formatReaderText(raw) {
  if (!raw) return '';
  return raw
    .split(/\n{2,}/)
    .map(p => {
      const clean = p.trim();
      if (!clean) return '';
      if (/^={3,}.*?={3,}$/.test(clean) || /^PAGE\s+\d+$/i.test(clean)) {
        return `<div class="reader-page-divider" style="text-align:center; font-family:sans-serif; font-size:0.75rem; letter-spacing:0.1em; opacity:0.5; margin:24px 0">❖ ${escHtml(clean.replace(/=/g, '').trim())} ❖</div>`;
      }
      return `<p style="margin-bottom:1.4em; text-indent:1.5em">${escHtml(clean)}</p>`;
    })
    .join('');
}

function closeReaderModal() {
  const modal = document.getElementById('reader-modal');
  if (modal) modal.style.display = 'none';
}

function setReaderViewMode(mode) {
  const singleBtn = document.getElementById('reader-btn-single');
  const splitBtn = document.getElementById('reader-btn-split');
  const singleContent = document.getElementById('reader-single-content');
  const splitContent = document.getElementById('reader-split-content');

  if (mode === 'split') {
    if (singleBtn) singleBtn.classList.remove('active');
    if (splitBtn) splitBtn.classList.add('active');
    if (singleContent) singleContent.style.display = 'none';
    if (splitContent) splitContent.style.display = 'grid';
  } else {
    if (splitBtn) splitBtn.classList.remove('active');
    if (singleBtn) singleBtn.classList.add('active');
    if (splitContent) splitContent.style.display = 'none';
    if (singleContent) singleContent.style.display = 'block';
  }
}

function setReaderTheme(theme) {
  const body = document.getElementById('reader-body');
  if (!body) return;
  body.classList.remove('theme-paper', 'theme-sepia', 'theme-dark');
  body.classList.add(`theme-${theme}`);
  ['paper', 'sepia', 'dark'].forEach(t => {
    const btn = document.getElementById(`r-theme-${t}`);
    if (btn) btn.classList.toggle('active', t === theme);
  });
}

function adjustReaderFontSize(delta) {
  _readerFontSizeScale = Math.max(0.75, Math.min(1.6, _readerFontSizeScale + delta * 0.1));
  const body = document.getElementById('reader-body');
  if (body) {
    body.style.setProperty('--reader-font-scale', _readerFontSizeScale);
  }
  const label = document.getElementById('reader-font-size-label');
  if (label) {
    label.textContent = `${Math.round(_readerFontSizeScale * 100)}%`;
  }
}

// ── Smart Resume Banner Logic ──────────────────────────────
let _smartResumeJob = null;

function checkSmartResume(jobs) {
  const banner = document.getElementById('smart-resume-banner');
  if (!banner) return;

  if (!jobs || !Array.isArray(jobs) || jobs.length === 0) {
    banner.style.display = 'none';
    return;
  }

  // Find most recent job that was interrupted or has uncompleted checkpoint
  const candidate = jobs.find(j => {
    if (!j.job_id || j.status === 'done' || j.status === 'cancelled') return false;
    if (state.tr.jobId === j.job_id && state.tr.status === 'running') return false;
    if (state.ab.jobId === j.job_id && state.ab.status === 'running') return false;
    const dismissed = sessionStorage.getItem(`dismiss_resume_${j.job_id}`);
    if (dismissed) return false;
    const done = Number(j.done_chunks || j.done_pages || 0);
    const total = Number(j.total_chunks || j.total_pages || 0);
    return done > 0 || j.status === 'error';
  });

  if (candidate) {
    _smartResumeJob = candidate;
    const textEl = document.getElementById('smart-resume-text');
    const done = Number(candidate.done_chunks || candidate.done_pages || 0);
    const total = Number(candidate.total_chunks || candidate.total_pages || 0);
    const pct = candidate.progress || (total > 0 ? Math.round((done / total) * 100) : 0);
    const info = total > 0 ? `${done}/${total} τμήματα · ${pct}% ολοκληρωμένο` : `${pct}%`;
    if (textEl) {
      textEl.innerHTML = `«<strong>${escHtml(candidate.file_name || 'Έγγραφο')}</strong>» (${info}). Πατήστε για άμεση συνέχιση από το checkpoint.`;
    }
    banner.style.display = 'block';
  } else {
    banner.style.display = 'none';
  }
}

async function executeSmartResume() {
  if (!_smartResumeJob) return;
  const job = _smartResumeJob;
  dismissSmartResume();
  await loadHistoryJob(job.job_id, job.mode || 'translate');
  toast('▶️ Συνέχιση εργασίας από το αποθηκευμένο checkpoint...', 'info');
  if ((job.mode || 'translate') === 'translate') {
    await startTranslation();
  } else {
    await startAudiobook();
  }
}

function dismissSmartResume() {
  if (_smartResumeJob) {
    sessionStorage.setItem(`dismiss_resume_${_smartResumeJob.job_id}`, '1');
    _smartResumeJob = null;
  }
  const banner = document.getElementById('smart-resume-banner');
  if (banner) banner.style.display = 'none';
}

// ── AI Polish via Gemini ───────────────────────────────────
let _polishPollTimer = null;
let _polishRunning = false;

function toggleApiKeyVisibility() {
  const slotIds = ['gemini-api-key', 'gemini-api-key-2', 'gemini-api-key-3', 'gemini-api-key-4'];
  const firstInput = document.getElementById('gemini-api-key');
  const isHidden = firstInput && (firstInput.type === 'password' || firstInput.style.webkitTextSecurity !== 'none');
  const labelEl = document.getElementById('toggle-key-label');

  slotIds.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.type = 'text';
      el.style.webkitTextSecurity = isHidden ? 'none' : 'disc';
    }
  });

  const btn = document.getElementById('btn-toggle-key');
  if (btn) {
    const iconSpan = btn.querySelector('span:first-child');
    if (iconSpan) iconSpan.textContent = isHidden ? '🔒' : '👁️';
  }
  if (labelEl) {
    labelEl.textContent = isHidden ? 'Απόκρυψη' : 'Εμφάνιση';
  }
}

function renderGeminiPoolStatus(poolData) {
  if (!poolData) return;
  const slots = poolData.slots || [];
  const total = poolData.total_keys || 0;
  const avail = poolData.available_keys || 0;
  const allExh = Boolean(poolData.all_exhausted);

  for (let i = 1; i <= 4; i++) {
    const badge = document.getElementById(`pool-slot-status-${i}`);
    if (!badge) continue;
    const slotInfo = slots[i - 1];
    if (!slotInfo) {
      badge.textContent = '⚪ Κενό';
      badge.style.background = 'rgba(255,255,255,0.06)';
      badge.style.color = 'var(--text-muted)';
      continue;
    }
    if (slotInfo.is_exhausted) {
      badge.textContent = `⏳ Όριο (${slotInfo.reset_time_str || 'σε αναμονή'})`;
      badge.style.background = 'rgba(245,158,11,0.18)';
      badge.style.color = 'var(--amber)';
    } else if (slotInfo.is_active) {
      badge.textContent = '🟢 Ενεργό (Active)';
      badge.style.background = 'rgba(16,185,129,0.18)';
      badge.style.color = 'var(--emerald)';
    } else {
      badge.textContent = '🟡 Εφεδρικό (Standby)';
      badge.style.background = 'rgba(124,58,237,0.15)';
      badge.style.color = 'var(--violet)';
    }
  }

  const sumBadge = document.getElementById('gemini-pool-summary-badge');
  if (sumBadge) {
    if (total === 0) {
      sumBadge.textContent = 'Pool: 0 κλειδιά (Δωρεάν fallback)';
      sumBadge.style.color = 'var(--text-muted)';
    } else if (allExh) {
      sumBadge.textContent = `⚠️ Όλα τα ${total} κλειδιά εξαντλήθηκαν`;
      sumBadge.style.color = 'var(--amber)';
    } else {
      sumBadge.textContent = `🟢 ${avail}/${total} Κλειδιά Διαθέσιμα (~${avail * 1500} αιτήματα)`;
      sumBadge.style.color = 'var(--emerald)';
    }
  }
  updateNavGeminiBadge(poolData);
}

function updateNavGeminiBadge(poolData) {
  const navBadge = document.getElementById('nav-gemini-quota-badge');
  if (!navBadge) return;

  const total = poolData?.total_keys || 0;
  const avail = poolData?.available_keys || 0;
  const allExh = Boolean(poolData?.all_exhausted);
  const savedKey = (typeof localStorage !== 'undefined') ? localStorage.getItem('gemini_api_key') : null;

  navBadge.style.display = 'inline-block';

  if (total > 0) {
    if (allExh || avail === 0) {
      navBadge.style.background = 'rgba(245,158,11,0.18)';
      navBadge.style.color = 'var(--amber, #f59e0b)';
      navBadge.style.border = '1px solid rgba(245,158,11,0.4)';
      navBadge.textContent = '⏳ Cooldown';
      navBadge.title = `Όλα τα ${total} Gemini API keys βρίσκονται σε cooldown (${poolData.earliest_reset_time_str || 'σε αναμονή'})`;
    } else if (avail < total) {
      navBadge.style.background = 'rgba(245,158,11,0.15)';
      navBadge.style.color = 'var(--amber, #f59e0b)';
      navBadge.style.border = '1px solid rgba(245,158,11,0.4)';
      navBadge.textContent = `🟡 ${avail}/${total} Keys`;
      navBadge.title = `${avail}/${total} Gemini API Keys διαθέσιμα (${total - avail} σε cooldown)`;
    } else {
      navBadge.style.background = 'rgba(16,185,129,0.15)';
      navBadge.style.color = 'var(--emerald)';
      navBadge.style.border = '1px solid rgba(16,185,129,0.4)';
      navBadge.textContent = total > 1 ? `🟢 ${avail}/${total} Keys` : '✓ Active';
      navBadge.title = `${avail}/${total} Gemini API Key(s) ενεργά (~${avail * 1500} RPD)`;
    }
  } else if (savedKey) {
    navBadge.style.background = 'rgba(16,185,129,0.15)';
    navBadge.style.color = 'var(--emerald)';
    navBadge.style.border = '1px solid rgba(16,185,129,0.4)';
    navBadge.textContent = '✓ Active';
    navBadge.title = 'Gemini API Key είναι αποθηκευμένο και ενεργό (15 RPM / 1.500 RPD)';
  } else {
    navBadge.style.background = 'rgba(59,130,246,0.15)';
    navBadge.style.color = 'var(--blue, #3b82f6)';
    navBadge.style.border = '1px solid rgba(59,130,246,0.3)';
    navBadge.textContent = '🆓 Free Mode';
    navBadge.title = 'Δωρεάν μοντέλα ενεργά ως προεπιλογή (Google Translate & Edge-TTS — χωρίς API key)';
  }
}

async function openAiPolishModal() {
  const modal = document.getElementById('ai-polish-modal');
  modal.style.display = 'flex';

  let localPool = [];
  try {
    const rawLocal = localStorage.getItem('gemini_api_keys');
    if (rawLocal) {
      localPool = JSON.parse(rawLocal);
    }
  } catch (_) {}

  if (!Array.isArray(localPool) || localPool.length === 0) {
    const single = localStorage.getItem('gemini_api_key');
    if (single) localPool = [single];
  }

  // Fetch latest settings & pool state from server
  let serverPool = [];
  try {
    const sRes = await fetch(`${API}/settings`);
    if (sRes.ok) {
      const sData = await sRes.json();
      if (Array.isArray(sData.gemini_api_keys) && sData.gemini_api_keys.length > 0) {
        serverPool = sData.gemini_api_keys;
      } else if (sData.gemini_api_key) {
        serverPool = [sData.gemini_api_key];
      }
      if (sData.pool) {
        renderGeminiPoolStatus(sData.pool);
      }
    }
  } catch (_) {}

  // Intelligent merge: retain every unique key from both server and local storage!
  const poolKeys = [...serverPool];
  for (const k of localPool) {
    if (k && !poolKeys.includes(k) && poolKeys.length < 4) {
      poolKeys.push(k);
    }
  }

  // Keep both local and server synchronized with the complete pool
  if (poolKeys.length > 0) {
    localStorage.setItem('gemini_api_key', poolKeys[0]);
    localStorage.setItem('gemini_api_keys', JSON.stringify(poolKeys));
  }
  if (poolKeys.length > serverPool.length) {
    fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: poolKeys[0], gemini_api_keys: poolKeys }),
    }).then(r => r.json()).then(d => {
      if (d.pool) renderGeminiPoolStatus(d.pool);
    }).catch(() => {});
  }

  const slotIds = ['gemini-api-key', 'gemini-api-key-2', 'gemini-api-key-3', 'gemini-api-key-4'];
  slotIds.forEach((id, idx) => {
    const input = document.getElementById(id);
    if (input) {
      input.value = poolKeys[idx] || '';
    }
  });

  const hasAnyKey = poolKeys.length > 0;
  const badge = document.getElementById('gemini-key-saved-badge');
  if (badge) {
    badge.style.display = hasAnyKey ? 'inline' : 'none';
  }
  const clearBtn = document.getElementById('btn-clear-key');
  if (clearBtn) {
    clearBtn.style.display = hasAnyKey ? 'inline' : 'none';
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

  // Check Gemini daily quota status and display warning if exhausted
  const mBanner = document.getElementById('ai-polish-quota-warning-banner');
  const mText = document.getElementById('ai-polish-quota-warning-text');
  try {
    const qRes = await fetch(`${API}/gemini/status`);
    if (qRes.ok) {
      const qData = await qRes.json();
      if (mBanner) {
        if (qData.exhausted) {
          mBanner.style.display = 'block';
          if (mText) mText.textContent = qData.message || 'Το ημερήσιο όριο του Gemini API έχει εξαντληθεί.';
        } else {
          mBanner.style.display = 'none';
        }
      }
    }
  } catch (_) {}
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

// ── Gemini Quota Live Countdown & Notification Management ──
let _geminiCountdownTimer = null;
let _geminiResetTimestamp = 0;
let _geminiResetTimeStr = '';

function startGeminiQuotaCountdown(resetTimestamp, resetTimeStr) {
  if (resetTimestamp) {
    _geminiResetTimestamp = Number(resetTimestamp);
  }
  if (resetTimeStr) {
    _geminiResetTimeStr = resetTimeStr;
  }
  if (!_geminiResetTimestamp || _geminiResetTimestamp <= Date.now() / 1000) {
    stopGeminiQuotaCountdown(true);
    return;
  }

  if (_geminiCountdownTimer) {
    clearInterval(_geminiCountdownTimer);
    _geminiCountdownTimer = null;
  }

  // Immediate first tick
  _tickGeminiQuotaCountdown();

  // Tick every second
  _geminiCountdownTimer = setInterval(() => {
    _tickGeminiQuotaCountdown();
  }, 1000);
}

function stopGeminiQuotaCountdown(isFinished = false) {
  if (_geminiCountdownTimer) {
    clearInterval(_geminiCountdownTimer);
    _geminiCountdownTimer = null;
  }
  _geminiResetTimestamp = 0;
  _geminiResetTimeStr = '';

  if (isFinished) {
    onGeminiQuotaRestored();
  }
}

function _tickGeminiQuotaCountdown() {
  const nowSec = Date.now() / 1000;
  const remSec = Math.max(0, Math.floor(_geminiResetTimestamp - nowSec));

  if (remSec <= 0) {
    stopGeminiQuotaCountdown(true);
    return;
  }

  const min = Math.floor(remSec / 60);
  const sec = remSec % 60;
  const hrs = Math.floor(min / 60);
  const remM = min % 60;

  const mmss = hrs > 0
    ? `${String(hrs).padStart(2, '0')}:${String(remM).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;

  let formattedTime = `${min}λ ${sec}δ`;
  if (hrs > 0) {
    formattedTime = `${hrs}ώ ${remM}λ ${sec}δ`;
  } else if (min < 1) {
    formattedTime = `${sec}δ`;
  }

  let clockStr = _geminiResetTimeStr;
  if (!clockStr && _geminiResetTimestamp > 0) {
    const d = new Date(_geminiResetTimestamp * 1000);
    clockStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  // 1. Top navbar badge
  const navBadge = document.getElementById('nav-gemini-quota-badge');
  if (navBadge) {
    navBadge.style.display = 'inline-block';
    navBadge.style.background = 'rgba(245,158,11,0.2)';
    navBadge.style.color = 'var(--amber)';
    navBadge.style.border = '1px solid rgba(245,158,11,0.5)';
    navBadge.innerHTML = `⚠️ Quota (${mmss})`;
    navBadge.title = `Ημερήσιο όριο Gemini: Έτοιμο ξανά στις ${clockStr} (απομένουν ${formattedTime})`;
  }

  // 2. Home banner at top of Translate tab
  const homeBanner = document.getElementById('home-gemini-quota-banner');
  const homeText = document.getElementById('home-gemini-quota-text');
  if (homeBanner) {
    homeBanner.style.display = 'block';
    homeBanner.style.background = 'rgba(245,158,11,0.14)';
    homeBanner.style.borderColor = 'rgba(245,158,11,0.65)';
    if (homeText) {
      homeText.innerHTML = `Εξαντλήθηκε το όριο (Free Tier 15 RPM / 1.500 RPD). <strong style="color:var(--amber)">Έτοιμο ξανά στις ${clockStr}</strong> (Αντίστροφη μέτρηση: <span style="font-family:monospace; font-weight:700; font-size:1.05rem; color:var(--amber)">${mmss}</span>). Μπορείτε να αλλάξετε API Key στις Ρυθμίσεις για άμεση συνέχιση.`;
    }
  }

  // 3. Translation progress banner
  const trQuotaBanner = document.getElementById('tr-quota-warning-banner');
  const trQuotaText = document.getElementById('tr-quota-warning-text');
  if (trQuotaBanner) {
    trQuotaBanner.style.display = 'block';
    if (trQuotaText) {
      trQuotaText.innerHTML = `Εξαντλήθηκε το όριο Gemini. <strong style="color:var(--amber)">Έτοιμο ξανά στις ${clockStr}</strong> (Αντίστροφη μέτρηση: <span style="font-family:monospace; font-weight:700; font-size:1.05rem; color:var(--amber)">${mmss}</span>). Η πρόοδος διατηρήθηκε σε checkpoint.`;
    }
  }

  // 4. Batch queue banner
  const qBanner = document.getElementById('queue-quota-warning-banner');
  const qText = document.getElementById('queue-quota-warning-text');
  if (qBanner) {
    qBanner.style.display = 'block';
    if (qText) {
      qText.innerHTML = `Εξαντλήθηκε το όριο Gemini (Free Tier). <strong>Έτοιμο ξανά στις ${clockStr}</strong> (Απομένουν: <span style="font-family:monospace; font-weight:700">${mmss}</span>). Η ουρά συνεχίζει αυτόματα χωρίς AI Polish.`;
    }
  }

  // 5. Settings checkbox tag
  const polishTag = document.getElementById('tr-ai-polish-quota-tag');
  if (polishTag) {
    polishTag.style.display = 'inline-block';
    polishTag.textContent = `⚠️ Όριο Quota (${mmss})`;
    polishTag.title = `Έτοιμο ξανά στις ${clockStr} (απομένουν ${formattedTime})`;
  }

  // 6. Action buttons on progress card and error card
  const trResumeBtn = document.getElementById('tr-resume-btn');
  if (trResumeBtn && state.tr.status === 'error') {
    trResumeBtn.style.display = 'inline-flex';
  }
  const trQuotaKeyBtn = document.getElementById('tr-quota-key-btn');
  if (trQuotaKeyBtn && state.tr.status === 'error') {
    trQuotaKeyBtn.style.display = 'inline-flex';
  }
  const errActions = document.getElementById('tr-error-quota-actions');
  if (errActions && document.getElementById('tr-error-card')?.classList.contains('visible')) {
    errActions.style.display = 'inline-flex';
  }
}

function onGeminiQuotaRestored() {
  // 1. Update top navbar badge to green
  const navBadge = document.getElementById('nav-gemini-quota-badge');
  if (navBadge) {
    navBadge.style.display = 'inline-block';
    navBadge.style.background = 'rgba(16,185,129,0.18)';
    navBadge.style.color = 'var(--emerald)';
    navBadge.style.border = '1px solid rgba(16,185,129,0.5)';
    navBadge.innerHTML = '✅ Έτοιμο ξανά!';
    navBadge.title = 'Το όριο Gemini API ανανεώθηκε! Έτοιμο για μεταφράσεις.';
  }

  // 2. Update home banner
  const homeBanner = document.getElementById('home-gemini-quota-banner');
  const homeText = document.getElementById('home-gemini-quota-text');
  if (homeBanner) {
    homeBanner.style.display = 'block';
    homeBanner.style.background = 'rgba(16,185,129,0.12)';
    homeBanner.style.borderColor = 'rgba(16,185,129,0.5)';
    if (homeText) {
      homeText.innerHTML = '<strong>✅ Το όριο Gemini API ανανεώθηκε!</strong> Το σύστημα είναι πλήρως διαθέσιμο ξανά για χρήση AI Polish και μεταφράσεις.';
    }
  }

  // 3. Update translation banner
  const trQuotaBanner = document.getElementById('tr-quota-warning-banner');
  const trQuotaText = document.getElementById('tr-quota-warning-text');
  if (trQuotaBanner && trQuotaText) {
    trQuotaBanner.style.background = 'rgba(16,185,129,0.12)';
    trQuotaBanner.style.borderColor = 'rgba(16,185,129,0.5)';
    trQuotaText.innerHTML = '<strong>✅ Το όριο ανανεώθηκε!</strong> Μπορείτε να συνεχίσετε τη μετάφραση από το αποθηκευμένο checkpoint.';
  }

  // 4. Highlight resume buttons
  const trResumeBtn = document.getElementById('tr-resume-btn');
  if (trResumeBtn && state.tr.jobId) {
    trResumeBtn.style.display = 'inline-flex';
    trResumeBtn.innerHTML = '▶️ Συνέχιση Μετάφρασης ΤΩΡΑ';
  }
  const trErrResume = document.getElementById('tr-error-resume-btn');
  if (trErrResume && state.tr.jobId) {
    trErrResume.style.display = 'inline-flex';
    trErrResume.innerHTML = '▶️ Συνέχιση Μετάφρασης ΤΩΡΑ';
  }

  const polishTag = document.getElementById('tr-ai-polish-quota-tag');
  if (polishTag) polishTag.style.display = 'none';

  // 5. Toast notification to user
  toast('✅ Το όριο του Gemini API ανανεώθηκε! Αυτόματη συνέχιση από το checkpoint...', 'success');

  // 6. Automatic Resume when countdown finishes
  if (state.tr.jobId && (state.tr.status === 'error' || state.tr.status === 'idle')) {
    console.log(`Auto-resuming translation job ${state.tr.jobId} after quota restoration...`);
    setTimeout(() => {
      resumeTranslation('tr');
    }, 2000);
  } else if (_smartResumeJob) {
    console.log(`Auto-resuming checkpoint job ${_smartResumeJob.job_id} after quota restoration...`);
    setTimeout(() => {
      executeSmartResume();
    }, 2000);
  } else if (_batchQueueState.total_count > 0 && (_batchQueueState.paused || _batchQueueState.status === 'paused' || _batchQueueState.status === 'idle')) {
    console.log('Auto-resuming batch queue after quota restoration...');
    setTimeout(() => {
      startBatchQueue();
    }, 2000);
  } else if (state.ab.jobId && (state.ab.status === 'error' || state.ab.status === 'idle')) {
    console.log(`Auto-resuming audiobook job ${state.ab.jobId} after quota restoration...`);
    setTimeout(() => {
      resumeTranslation('ab');
    }, 2000);
  }
}

async function saveGeminiKeyOnly() {
  const slotIds = ['gemini-api-key', 'gemini-api-key-2', 'gemini-api-key-3', 'gemini-api-key-4'];
  const keys = [];
  const seen = new Set();
  let hasDuplicate = false;

  for (let idx = 0; idx < slotIds.length; idx++) {
    const id = slotIds[idx];
    const input = document.getElementById(id);
    const val = (input ? input.value : '').trim();
    if (val) {
      const isValid = (val.startsWith('AQ.') && val.length >= 25) ||
                      (val.startsWith('AIza') && val.length >= 35) ||
                      (val.length >= 25);
      if (!isValid) {
        toast(`Slot ${idx + 1}: Μη έγκυρη μορφή API Key (ξεκινούν με AIzaSy... ή AQ).`, 'error');
        return;
      }
      if (seen.has(val)) {
        hasDuplicate = true;
      } else {
        seen.add(val);
        keys.push(val);
      }
    }
  }

  if (hasDuplicate) {
    toast('⚠️ Προσοχή: Εντοπίστηκε το ίδιο API Key σε πολλαπλά Slots. Τα κλειδιά πρέπει να είναι διαφορετικά για να λειτουργεί η εναλλαγή.', 'warning');
  }

  if (keys.length === 0) {
    toast('Παρακαλώ εισάγετε τουλάχιστον ένα Gemini API Key.', 'error');
    return;
  }

  const primaryKey = keys[0] || '';
  localStorage.setItem('gemini_api_key', primaryKey);
  localStorage.setItem('gemini_api_keys', JSON.stringify(keys));

  try {
    const res = await fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: primaryKey, gemini_api_keys: keys }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.pool) renderGeminiPoolStatus(data.pool);
    }
    // Keep input slots cleanly aligned with saved keys
    slotIds.forEach((id, idx) => {
      const input = document.getElementById(id);
      if (input) input.value = keys[idx] || '';
    });
  } catch (_) {}

  try {
    await fetch(`${API}/gemini/reset-quota`, { method: 'POST' });
  } catch (_) {}

  stopGeminiQuotaCountdown(false);
  const badge = document.getElementById('gemini-key-saved-badge');
  if (badge) badge.style.display = 'inline';
  const clearBtn = document.getElementById('btn-clear-key');
  if (clearBtn) clearBtn.style.display = 'inline';
  const mBanner = document.getElementById('ai-polish-quota-warning-banner');
  if (mBanner) mBanner.style.display = 'none';

  // Clear quota banners across UI
  const homeBanner = document.getElementById('home-gemini-quota-banner');
  if (homeBanner) homeBanner.style.display = 'none';
  const trQuotaBanner = document.getElementById('tr-quota-warning-banner');
  if (trQuotaBanner) trQuotaBanner.style.display = 'none';
  const qBanner = document.getElementById('queue-quota-warning-banner');
  if (qBanner) qBanner.style.display = 'none';
  const polishTag = document.getElementById('tr-ai-polish-quota-tag');
  if (polishTag) polishTag.style.display = 'none';

  await checkGlobalGeminiQuotaStatus();

  // If there is an active job or queue waiting on quota, automatically resume it now!
  const hasVisibleTrResume = (
    document.getElementById('tr-resume-btn')?.style.display !== 'none' ||
    document.getElementById('tr-error-resume-btn')?.style.display !== 'none'
  );
  if (state.tr.jobId && state.tr.status !== 'done' && (state.tr.status === 'error' || state.tr.status === 'idle' || hasVisibleTrResume)) {
    closeAiPolishModal();
    toast(`✅ Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά! Αυτόματη συνέχιση μετάφρασης...`, 'success');
    setTimeout(() => {
      resumeTranslation('tr');
    }, 400);
    return;
  }

  if (_smartResumeJob) {
    closeAiPolishModal();
    toast(`✅ Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά! Αυτόματη συνέχιση από checkpoint...`, 'success');
    setTimeout(() => {
      executeSmartResume();
    }, 400);
    return;
  }

  if (_batchQueueState.total_count > 0 && (_batchQueueState.paused || _batchQueueState.status === 'paused' || _batchQueueState.status === 'idle')) {
    closeAiPolishModal();
    toast(`✅ Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά! Αυτόματη συνέχιση της ουράς...`, 'success');
    setTimeout(() => {
      startBatchQueue();
    }, 400);
    return;
  }

  if (state.ab.jobId && (state.ab.status === 'error' || state.ab.status === 'idle')) {
    closeAiPolishModal();
    toast(`✅ Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά! Αυτόματη συνέχιση του Audiobook...`, 'success');
    setTimeout(() => {
      startAudiobook();
    }, 600);
    return;
  }

  toast(`Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά στο Gemini Pool! Αυτόματη εναλλαγή ενεργή.`, 'success');
}

async function clearGeminiKey() {
  localStorage.removeItem('gemini_api_key');
  localStorage.removeItem('gemini_api_keys');
  const slotIds = ['gemini-api-key', 'gemini-api-key-2', 'gemini-api-key-3', 'gemini-api-key-4'];
  slotIds.forEach((id) => {
    const input = document.getElementById(id);
    if (input) input.value = '';
  });
  const badge = document.getElementById('gemini-key-saved-badge');
  if (badge) badge.style.display = 'none';
  const clearBtn = document.getElementById('btn-clear-key');
  if (clearBtn) clearBtn.style.display = 'none';
  try {
    await fetch(`${API}/settings/gemini_api_keys`, { method: 'DELETE' });
  } catch (_) {}
  stopGeminiQuotaCountdown(false);
  renderGeminiPoolStatus({ total_keys: 0, available_keys: 0, slots: [] });
  // Default selectors to free models (fallback) when key is removed
  ['tr', 'ab'].forEach((prefix) => {
    localStorage.setItem(`${prefix}_quota_behavior`, 'fallback');
    const radio = document.querySelector(`input[name="${prefix}-quota-behavior"][value="fallback"]`);
    if (radio) {
      radio.checked = true;
      onQuotaBehaviorChange(prefix);
    }
  });
  await checkGlobalGeminiQuotaStatus();
  toast('Όλα τα Gemini API Keys αφαιρέθηκαν. Τα δωρεάν μοντέλα είναι πλέον η ενεργή προεπιλογή.', 'info');
}

async function checkGlobalGeminiQuotaStatus() {
  try {
    const res = await fetch(`${API}/gemini/status`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.pool) {
      renderGeminiPoolStatus(data.pool);
    } else {
      updateNavGeminiBadge(null);
    }
    const isExhausted = Boolean(data.exhausted) && (!data.pool || data.pool.available_keys === 0);
    const resetTs = Number(data.reset_timestamp || 0);
    const resetTimeStr = data.reset_time_str || '';

    if (isExhausted && resetTs > Date.now() / 1000) {
      startGeminiQuotaCountdown(resetTs, resetTimeStr);
      const navBadge = document.getElementById('nav-gemini-quota-badge');
      if (navBadge) {
        navBadge.style.display = 'inline-block';
        navBadge.style.background = 'rgba(245,158,11,0.18)';
        navBadge.style.color = 'var(--amber, #f59e0b)';
        navBadge.style.border = '1px solid rgba(245,158,11,0.4)';
        navBadge.textContent = '⏳ Cooldown';
        navBadge.title = `Gemini Quota εξαντλήθηκε. Επαναφορά σε: ${resetTimeStr || 'σύντομα'}`;
      }
    } else {
      stopGeminiQuotaCountdown(false);
      const homeBanner = document.getElementById('home-gemini-quota-banner');
      if (homeBanner) homeBanner.style.display = 'none';
      const trQuotaBanner = document.getElementById('tr-quota-warning-banner');
      if (trQuotaBanner) trQuotaBanner.style.display = 'none';
      const qBanner = document.getElementById('queue-quota-warning-banner');
      if (qBanner) qBanner.style.display = 'none';
      const polishTag = document.getElementById('tr-ai-polish-quota-tag');
      if (polishTag) polishTag.style.display = 'none';

      if (data.pool) {
        updateNavGeminiBadge(data.pool);
      } else {
        updateNavGeminiBadge(null);
      }
    }
  } catch (_) {}
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
  if (editorCard) {
    editorCard.style.display = 'block';
    if (typeof editorCard.scrollIntoView === 'function') {
      editorCard.scrollIntoView({ behavior: 'smooth' });
    }
  }

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

  const apiKeyInput = document.getElementById('gemini-api-key');
  const apiKey = (apiKeyInput ? apiKeyInput.value.trim() : '') || localStorage.getItem('gemini_api_key') || '';
  if (apiKey) {
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
  } else {
    toast('ℹ️ Δεν έχει οριστεί Gemini API Key: Χρήση των δωρεάν μοντέλων (τυπογραφία & γλωσσάρι).', 'info');
  }

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
      throw new Error(await parseApiError(res, 'AI Polishing failed'));
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

    // If editor is open, put the polished text into it and clear dirty flag
    document.getElementById('editor-translated-text').value = data.polished_text;
    clearEditorDirty();
    updateEditorStats();
    if (editorCard.style.display === 'none') {
      await openEditor();
    }
    refreshHistory();
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
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load glossary'));
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
          <button class="glossary-del-btn" data-source="${escHtml(item.source)}" onclick="deleteGlossaryRule(this.dataset.source)" title="Διαγραφή όρου">✕</button>
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

// ── Smart Batch Queue (Unified in Upload Card, Max 20 Files) ─
const MAX_BATCH_FILES = 20;
let _queuePollTimer = null;
let _seenQuotaWarning = false;
let _batchQueueState = {
  items: [],
  is_running: false,
  paused: false,
  auto_start: false,
  done_count: 0,
  queued_count: 0,
  total_count: 0,
  max_items: MAX_BATCH_FILES,
};

function _readCurrentTranslationSettings() {
  const srcLang = document.getElementById('tr-source-lang')?.value || 'english';
  const tgtLang = document.getElementById('tr-target-lang')?.value || 'greek';
  const chosenFmt = document.getElementById('tr-output-format')?.value || 'pdf';
  const chosenLayout = document.getElementById('tr-layout-mode')?.value || 'standard';
  const aiPolish = document.getElementById('tr-ai-polish')?.checked || false;
  const apiKey = localStorage.getItem('gemini_api_key') || null;
  let hasKey = Boolean(apiKey);
  try {
    const rawKeys = localStorage.getItem('gemini_api_keys');
    if (rawKeys) {
      const arr = JSON.parse(rawKeys);
      if (Array.isArray(arr) && arr.some(k => typeof k === 'string' && k.trim())) hasKey = true;
    }
  } catch (_) {}
  const readingDirEl = document.querySelector('input[name="tr-reading-dir"]:checked');
  const readingDirection = readingDirEl ? readingDirEl.value : 'ltr';
  const quotaBehaviorEl = document.querySelector('input[name="tr-quota-behavior"]:checked');
  let quotaBehavior = quotaBehaviorEl ? quotaBehaviorEl.value : (hasKey ? 'wait' : 'fallback');
  if (!hasKey && quotaBehavior === 'wait') {
    quotaBehavior = 'fallback';
  }
  return { srcLang, tgtLang, chosenFmt, chosenLayout, aiPolish, apiKey, readingDirection, quotaBehavior };
}

function syncPrimaryStartButtonWithQueue(q) {
  const trStartBtn = document.getElementById('tr-start-btn');
  const directPolishBtn = document.getElementById('tr-direct-polish-btn');
  if (!trStartBtn || state.tr.jobId) return;

  if (!q || !q.items || q.items.length === 0) {
    trStartBtn.disabled = true;
    trStartBtn.textContent = currentAppMode === 'basic' ? '✨ Μετάφραση Βιβλίου με AI (1-Click)' : '🌐 Start Translation';
    if (directPolishBtn) directPolishBtn.disabled = true;
    return;
  }

  if (directPolishBtn) directPolishBtn.disabled = true;
  if (q.queued_count > 0 && (!q.is_running || q.paused)) {
    trStartBtn.disabled = false;
    trStartBtn.textContent = q.paused
      ? `▶️ Resume Batch Queue (${q.queued_count} left)`
      : `▶️ Start Batch Translation (${q.queued_count} files)`;
  } else if (q.is_running) {
    trStartBtn.disabled = true;
    trStartBtn.textContent = `⏳ Translating Batch (${q.done_count}/${q.total_count})...`;
  } else {
    trStartBtn.disabled = true;
    trStartBtn.textContent = `✅ Batch Complete (${q.done_count}/${q.total_count})`;
  }
}

async function enqueueMultipleFiles(files) {
  if (_isEnqueuing) {
    toast('Παρακαλώ περιμένετε να ολοκληρωθεί η προηγούμενη προσθήκη αρχείων...', 'info');
    return;
  }
  _isEnqueuing = true;
  try {
    const allowed = ['.pdf', '.docx', '.epub', '.cbz', '.zip'];
  const cfg = _readCurrentTranslationSettings();
  const maxItems = _batchQueueState.max_items || MAX_BATCH_FILES;

  // If a single file is already selected in the Upload Card, seamlessly promote it into the queue first
  let promotedExisting = false;
  if (state.tr.jobId) {
    const existingJobId = state.tr.jobId;
    const isComic = Boolean(state.tr.isComic) || cfg.chosenLayout === 'comic';
    const isScanned = Boolean(state.tr.isScanned);
    let itemFmt = cfg.chosenFmt;
    let itemLayout = isComic ? 'comic' : cfg.chosenLayout;
    if (isComic && ['txt', 'docx', 'doc'].includes(itemFmt)) itemFmt = 'pdf';
    if (!isComic && ['cbz', 'cbr'].includes(itemFmt)) itemFmt = 'pdf';
    try {
      const promoteRes = await fetch(`${API}/queue/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: existingJobId,
          source_lang: cfg.srcLang,
          target_lang: cfg.tgtLang,
          output_format: itemFmt,
          layout_mode: itemLayout,
          reading_direction: cfg.readingDirection,
          ai_polish: (isComic && isScanned) ? true : cfg.aiPolish,
          api_key: cfg.apiKey || null,
          is_comic: isComic,
          is_scanned: isScanned,
          quota_behavior: cfg.quotaBehavior || 'wait',
        }),
      });
      if (promoteRes.ok) {
        promotedExisting = true;
        _batchQueueState = await promoteRes.json();
        removeFile('tr');
      }
    } catch (_) {}
  }

  const remainingSlots = Math.max(0, maxItems - (_batchQueueState.total_count || 0));
  if (remainingSlots === 0) {
    toast(`⚠️ Το όριο της ουράς είναι ${maxItems} αρχεία. Καθαρίστε ή αφαιρέστε κάποια για να προσθέσετε νέα.`, 'error');
    await refreshBatchQueue();
    return;
  }

  let filesToUpload = Array.from(files);
  if (filesToUpload.length > remainingSlots) {
    toast(`⚠️ Μέγιστο όριο ${maxItems} αρχεία ανά παρτίδα — θα προστεθούν τα πρώτα ${remainingSlots} αρχεία.`, 'info');
    filesToUpload = filesToUpload.slice(0, remainingSlots);
  } else if (filesToUpload.length > 1) {
    toast(`⏳ Φόρτωση ${filesToUpload.length} αρχείων στην Smart Batch Queue...`, 'info');
  }

  let added = 0;
  const uploadedPayloads = [];
  for (const file of filesToUpload) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) {
      toast(`⚠️ Παράλειψη "${file.name}" (μη υποστηριζόμενο format).`, 'error');
      continue;
    }
    try {
      const fd = new FormData();
      fd.append('file', file);
      const upRes = await fetch(`${API}/upload`, { method: 'POST', body: fd });
      if (!upRes.ok) {
        const upErr = await upRes.json().catch(() => ({}));
        toast(`❌ Αποτυχία φόρτωσης "${file.name}": ${upErr.detail || upRes.statusText}`, 'error');
        continue;
      }
      const upData = await upRes.json();
      const isComic = Boolean(upData.is_comic) || ['.cbz', '.cbr', '.zip'].includes(ext);
      const isScanned = Boolean(upData.is_scanned);
      uploadedPayloads.push({ file, ext, upData, isComic, isScanned });
    } catch (err) {
      toast(`❌ Σφάλμα φόρτωσης "${file.name}": ${err.message}`, 'error');
    }
  }

  // Detect mixed queue (Books + Graphic Novels) BEFORE enqueueing so Auto-Start is safely disabled upfront
  const existingHasComic = (_batchQueueState.items || []).some((it) => it.is_comic);
  const existingHasBook = (_batchQueueState.items || []).some((it) => !it.is_comic);
  const incomingHasComic = uploadedPayloads.some((p) => p.isComic);
  const incomingHasBook = uploadedPayloads.some((p) => !p.isComic);
  const willBeMixed = (existingHasComic || incomingHasComic) && (existingHasBook || incomingHasBook);
  if (willBeMixed && _batchQueueState.auto_start) {
    try {
      await fetch(`${API}/queue/auto-start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_start: false }),
      });
      _batchQueueState.auto_start = false;
    } catch (_) {}
  }

  for (const { file, ext, upData, isComic, isScanned } of uploadedPayloads) {
    try {
      let itemLayout = isComic ? 'comic' : cfg.chosenLayout;
      let itemFmt = cfg.chosenFmt;
      const cleanExt = (ext || '').replace('.', '').toLowerCase();
      if (['pdf', 'docx', 'epub', 'cbz', 'cbr'].includes(cleanExt)) {
        itemFmt = cleanExt;
      }
      if (isComic) {
        if (['txt', 'docx', 'doc'].includes(itemFmt)) itemFmt = 'pdf';
      } else {
        // Protect non-comic books in mixed batches from inheriting comic-only settings
        if (itemLayout === 'comic') itemLayout = (ext === '.epub' ? 'literature' : 'standard');
        if (['cbz', 'cbr'].includes(itemFmt)) itemFmt = 'pdf';
      }

      const addRes = await fetch(`${API}/queue/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: upData.job_id,
          source_lang: cfg.srcLang,
          target_lang: cfg.tgtLang,
          output_format: itemFmt,
          layout_mode: itemLayout,
          reading_direction: cfg.readingDirection,
          ai_polish: (isComic && isScanned) ? true : cfg.aiPolish,
          api_key: cfg.apiKey || null,
          is_comic: isComic,
          is_scanned: isScanned,
          quota_behavior: cfg.quotaBehavior || 'wait',
        }),
      });
      if (!addRes.ok) {
        const addErr = await addRes.json().catch(() => ({}));
        toast(`❌ "${file.name}": ${addErr.detail || 'Αποτυχία προσθήκης στην ουρά'}`, 'error');
        continue;
      }
      added++;
    } catch (err) {
      toast(`❌ Σφάλμα προσθήκης "${file.name}": ${err.message}`, 'error');
    }
  }

  if (added > 0 || promotedExisting) {
    const totalAdded = added + (promotedExisting ? 1 : 0);
    const mixedNote = willBeMixed
      ? ' (Μικτή ουρά: το Auto-Start απενεργοποιήθηκε αυτόματα για έλεγχο ρυθμίσεων).'
      : ' Ρυθμίστε τις επιλογές από κάτω και πατήστε Start.';
    toast(`📋 Προστέθηκαν ${totalAdded} αρχεία στην Smart Batch Queue!${mixedNote}`, 'success');
    await refreshBatchQueue();
    refreshHistory();
  }
} finally {
  _isEnqueuing = false;
}
}

let _queuePollInFlight = false;
let _queuePollFailures = 0;

async function refreshBatchQueue() {
  if (_queuePollInFlight) return;
  _queuePollInFlight = true;
  try {
    const res = await fetch(`${API}/queue`);
    if (!res.ok) {
      _queuePollFailures += 1;
      if (_queuePollFailures >= 5 && _queuePollTimer) {
        clearInterval(_queuePollTimer);
        _queuePollTimer = null;
      }
      return;
    }
    _queuePollFailures = 0;
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
  } catch (err) {
    _queuePollFailures += 1;
    if (_queuePollFailures >= 5 && _queuePollTimer) {
      clearInterval(_queuePollTimer);
      _queuePollTimer = null;
    }
    console.warn('Batch queue refresh error:', err);
  } finally {
    _queuePollInFlight = false;
  }
}

function renderBatchQueue(q) {
  _batchQueueState = q || { items: [], is_running: false, paused: false, auto_start: false, done_count: 0, queued_count: 0, total_count: 0, max_items: MAX_BATCH_FILES };
  const card = document.getElementById('tr-queue-card');
  const list = document.getElementById('tr-queue-list');
  const counter = document.getElementById('tr-queue-counter');
  const autoToggle = document.getElementById('queue-auto-start-toggle');
  const pauseBtn = document.getElementById('btn-queue-pause');
  const addMoreBtn = document.getElementById('btn-queue-add-more');
  const dlAllBtn = document.getElementById('btn-queue-download-all');
  const upZone = document.getElementById('tr-upload-zone');
  const genreHint = document.getElementById('tr-genre-hint');

  if (!card || !list) return;
  const maxItems = _batchQueueState.max_items || MAX_BATCH_FILES;

  if (!_batchQueueState.items || _batchQueueState.items.length === 0) {
    card.style.display = 'none';
    if (counter) counter.style.display = 'none';
    if (dlAllBtn) {
      dlAllBtn.style.display = 'none';
      dlAllBtn.href = '#';
      dlAllBtn.removeAttribute('download');
      dlAllBtn.setAttribute('aria-disabled', 'true');
      dlAllBtn.setAttribute('tabindex', '-1');
      dlAllBtn.style.opacity = '0.45';
      dlAllBtn.style.pointerEvents = 'none';
      dlAllBtn.style.cursor = 'not-allowed';
    }
    if (upZone && !state.tr.jobId) upZone.style.display = '';
    syncPrimaryStartButtonWithQueue(_batchQueueState);
    return;
  }

  card.style.display = 'block';
  if (upZone && !state.tr.jobId) upZone.style.display = 'none';
  if (genreHint && !state.tr.jobId) genreHint.style.display = 'none';

  if (counter) {
    counter.style.display = 'inline-block';
    const pauseNote = (q.is_running && q.paused) ? ' · ⏸️ Pausing...' : (q.paused ? ' · ⏸️ Paused' : '');
    counter.textContent = `${q.done_count} / ${q.total_count} done (max ${maxItems})${pauseNote}`;
  }
  if (autoToggle) {
    const isMixed = Boolean(q.is_mixed);
    autoToggle.checked = isMixed ? false : Boolean(q.auto_start);
    autoToggle.disabled = isMixed;
    const autoLabel = autoToggle.closest('label');
    if (autoLabel) {
      autoLabel.style.opacity = isMixed ? '0.55' : '1';
      autoLabel.style.cursor = isMixed ? 'not-allowed' : 'pointer';
      autoLabel.title = isMixed
        ? 'Απενεργοποιημένο σε μικτή ουρά (Βιβλία + Graphic Novels) ώστε να ελέγχετε τις ρυθμίσεις πριν την εκκίνηση.'
        : 'Αυτόματη έναρξη μετάφρασης μόλις προστεθούν αρχεία';
    }
  }

  const quotaBanner = document.getElementById('queue-quota-warning-banner');
  const quotaText = document.getElementById('queue-quota-warning-text');
  if (quotaBanner) {
    if (q.gemini_quota_exhausted) {
      quotaBanner.style.display = 'block';
      if (quotaText) {
        quotaText.textContent = q.gemini_quota_message || 'Εξαντλήθηκε το ημερήσιο όριο του Gemini Free Tier. Η ουρά συνεχίζει αυτόματα χωρίς AI Polish.';
      }
      if (!_seenQuotaWarning) {
        _seenQuotaWarning = true;
        checkGlobalGeminiQuotaStatus();
        toast('⚠️ Εξαντλήθηκε το ημερήσιο όριο Gemini Free Tier — η μετάφραση συνεχίζεται αυτόματα χωρίς AI polish.', 'warning');
      }
    } else {
      quotaBanner.style.display = 'none';
      if (_seenQuotaWarning) {
        _seenQuotaWarning = false;
        checkGlobalGeminiQuotaStatus();
      }
    }
  }

  if (pauseBtn) {
    pauseBtn.style.display = (q.is_running && !q.paused) ? 'inline-flex' : 'none';
  }
  if (addMoreBtn) {
    const atLimit = q.total_count >= maxItems;
    addMoreBtn.disabled = atLimit;
    addMoreBtn.textContent = atLimit
      ? `⚠️ Limit Reached (${q.total_count}/${maxItems})`
      : `➕ Add More Files (${q.total_count}/${maxItems})`;
  }
  const allCompleted = (
    q.total_count > 0
    && q.done_count === q.total_count
    && !q.is_running
    && q.queued_count === 0
  );

  if (dlAllBtn) {
    dlAllBtn.style.display = q.total_count > 0 ? 'inline-flex' : 'none';
    if (allCompleted) {
      dlAllBtn.href = `${API}/queue/download-all`;
      dlAllBtn.setAttribute('download', 'BookApp_Batch_Translated.zip');
      dlAllBtn.setAttribute('aria-disabled', 'false');
      dlAllBtn.setAttribute('tabindex', '0');
      dlAllBtn.style.opacity = '';
      dlAllBtn.style.pointerEvents = '';
      dlAllBtn.style.cursor = 'pointer';
      dlAllBtn.title = 'Download all completed translations as ZIP';
    } else {
      dlAllBtn.href = '#';
      dlAllBtn.removeAttribute('download');
      dlAllBtn.setAttribute('aria-disabled', 'true');
      dlAllBtn.setAttribute('tabindex', '-1');
      dlAllBtn.style.opacity = '0.45';
      dlAllBtn.style.pointerEvents = 'none';
      dlAllBtn.style.cursor = 'not-allowed';
      dlAllBtn.title = `Download All will be enabled once all translations are completed (${q.done_count} / ${q.total_count} done)`;
    }
  }

  syncPrimaryStartButtonWithQueue(q);

  const statusLabels = {
    queued: '⏳ Queued',
    running: '🔄 Running',
    waiting_quota: '⏳ Σε αναμονή (Auto-Resume)',
    done: '✅ Done',
    error: '❌ Error',
    cancelled: '🛑 Cancelled',
  };

  list.innerHTML = q.items.map((it) => {
    const modeTag = it.is_comic
      ? `🎨 Comic (${(it.reading_direction || 'ltr').toUpperCase()})`
      : (it.layout_mode === 'literature' ? '📚 Literature' : '📄 Standard');
    const isWaitMode = (it.quota_behavior || 'wait') === 'wait';
    const aiTag = it.ai_polish
      ? (q.gemini_quota_exhausted
          ? (isWaitMode ? ' · ⏳ Αναμονή Gemini AI (100% ποιότητα)' : ' · ⚠️ Χωρίς AI Polish (Fallback)')
          : ' · ✨ AI Polish')
      : '';
    const dlLink = it.has_output
      ? `<a class="btn-sm btn-outline" href="${API}/download/${it.job_id}?format=${it.output_format}&layout=${it.layout_mode}" style="text-decoration:none; color:var(--emerald); border-color:rgba(16,185,129,0.4)">⬇️ ${it.output_format.toUpperCase()}</a>`
      : '';
    const retryBtn = (it.status === 'error' || it.status === 'cancelled' || it.status === 'waiting_quota')
      ? `<button type="button" class="btn-sm btn-outline" data-job-id="${escHtml(it.job_id)}" onclick="retryQueueItem(this.dataset.jobId)" title="${it.status === 'waiting_quota' ? 'Άμεση δοκιμή εκ νέου' : 'Επανάληψη μετάφρασης'}" style="color:var(--amber); border-color:rgba(245,158,11,0.45)">${it.status === 'waiting_quota' ? '⚡ Retry Now' : '🔄 Retry'}</button>`
      : '';
    const progressBar = (it.status === 'running' || it.status === 'done')
      ? `<div class="queue-progress-track"><div class="queue-progress-fill" style="width:${it.status === 'done' ? 100 : it.progress}%"></div></div>`
      : '';
    const errLine = it.error
      ? `<div style="font-size:0.75rem; color:var(--rose)">${escHtml(it.error)}</div>`
      : '';
    return `
      <div class="queue-item ${it.status}">
        <div class="queue-item-top">
          <div class="queue-item-info">
            <span style="font-size:1.2rem">${it.is_comic ? '🎨' : '📄'}</span>
            <div style="min-width:0; flex:1">
              <div class="queue-item-name" title="${escHtml(it.file_name)}">${escHtml(it.file_name)}</div>
              <div class="queue-item-meta">
                <span>${modeTag}${aiTag}</span>
                <span>→ ${it.output_format.toUpperCase()}</span>
                <span>${escHtml(it.current_step || '')}</span>
              </div>
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:8px; flex-shrink:0">
            <span class="queue-badge ${it.status}">${statusLabels[it.status] || it.status}${it.status === 'running' ? ` ${it.progress}%` : ''}</span>
            ${dlLink}
            ${retryBtn}
            <button type="button" class="btn-icon" data-job-id="${escHtml(it.job_id)}" onclick="removeQueueItem(this.dataset.jobId)" title="Αφαίρεση από την ουρά">✕</button>
          </div>
        </div>
        ${progressBar}
        ${errLine}
      </div>
    `;
  }).join('');
}

async function retryQueueItem(jobId) {
  try {
    const res = await fetch(`${API}/queue/${jobId}/retry`, { method: 'POST' });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Retry failed');
    }
    toast('🔄 Το αρχείο ξαναμπήκε στην ουρά για επανάληψη!', 'info');
    await refreshBatchQueue();
  } catch (err) {
    toast(`❌ ${err.message}`, 'error');
  }
}

async function startBatchQueue() {
  const cfg = _readCurrentTranslationSettings();
  try {
    const res = await fetch(`${API}/queue/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_lang: cfg.srcLang,
        target_lang: cfg.tgtLang,
        output_format: cfg.chosenFmt,
        layout_mode: cfg.chosenLayout,
        reading_direction: cfg.readingDirection,
        ai_polish: cfg.aiPolish,
        api_key: cfg.apiKey || null,
        quota_behavior: cfg.quotaBehavior,
      }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to start batch queue');
    }
    toast('▶️ Η Smart Batch Queue ξεκίνησε με τις επιλεγμένες ρυθμίσεις (σειριακή εκτέλεση).', 'info');
    await refreshBatchQueue();
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
  const autoToggle = document.getElementById('queue-auto-start-toggle');
  const enabled = autoToggle?.checked || false;
  if (enabled && _batchQueueState.is_mixed) {
    if (autoToggle) autoToggle.checked = false;
    toast('⚠️ Το Auto-Start είναι απενεργοποιημένο σε μικτή ουρά (Βιβλία + Graphic Novels) για ασφαλή έλεγχο ρυθμίσεων.', 'info');
    return;
  }
  try {
    const res = await fetch(`${API}/queue/auto-start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_start: enabled }),
    });
    const data = res.ok ? await res.json().catch(() => null) : null;
    if (enabled && data && data.is_mixed && !data.auto_start) {
      toast('⚠️ Το Auto-Start είναι απενεργοποιημένο σε μικτή ουρά (Βιβλία + Graphic Novels).', 'info');
    } else {
      toast(enabled ? '⚡ Auto-Start Queue ενεργοποιήθηκε.' : '⏸️ Manual Queue mode ενεργό.', 'info');
    }
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
  // Initialize Theme, Editor Sync Scroll, Mode, and Quota Behavior choice
  initTheme();
  setupSyncScroll();
  initQuotaBehaviorSelectors();
  applyAppMode(currentAppMode);

  // Auto-sync Gemini API key pool between localStorage and backend server
  // Authoritative sync: Server settings are primary. Merge unique keys, never delete server keys on reload.
  try {
    const sRes = await fetch(`${API}/settings`);
    if (sRes.ok) {
      const sData = await sRes.json();
      const serverKeys = Array.isArray(sData.gemini_api_keys) ? sData.gemini_api_keys : (sData.gemini_api_key ? [sData.gemini_api_key] : []);

      let localKeys = [];
      try {
        const rawKeys = localStorage.getItem('gemini_api_keys');
        if (rawKeys) localKeys = JSON.parse(rawKeys);
      } catch (_) {}
      if (!Array.isArray(localKeys) || localKeys.length === 0) {
        const single = localStorage.getItem('gemini_api_key');
        if (single) localKeys = [single];
      }

      // Merge unique keys preserving server priority up to 4 keys
      const merged = [...serverKeys];
      for (const k of localKeys) {
        if (k && !merged.includes(k) && merged.length < 4) {
          merged.push(k);
        }
      }

      // Keep localStorage in sync with authoritative merged list
      if (merged.length > 0) {
        localStorage.setItem('gemini_api_key', merged[0]);
        localStorage.setItem('gemini_api_keys', JSON.stringify(merged));
      }

      // If local had new keys that server was missing, sync merged pool to server
      if (merged.length > serverKeys.length) {
        await fetch(`${API}/settings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ gemini_api_key: merged[0], gemini_api_keys: merged }),
        });
      }

      if (sData.pool) {
        renderGeminiPoolStatus(sData.pool);
      }
    }
  } catch (_) {}

  // Check backend is reachable
  try {
    await fetch(`${API}/health`);
  } catch (e) {
    toast('⚠️ Cannot connect to backend. Make sure the server is running on port 8000.', 'error');
  }

  // Load voices
  await loadVoices();

  // Check Gemini daily quota status on initial load and keep updated periodically
  await checkGlobalGeminiQuotaStatus();
  setInterval(checkGlobalGeminiQuotaStatus, 30000);

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
  const readerModal = document.getElementById('reader-modal');
  if (readerModal) {
    readerModal.addEventListener('click', (e) => {
      if (e.target === readerModal) closeReaderModal();
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
      const readerModal = document.getElementById('reader-modal');
      if (readerModal && readerModal.style.display !== 'none') {
        closeReaderModal();
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
