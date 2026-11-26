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

// ── Gemini API keys: stored ONLY on the server ─────────────
// The browser never keeps keys (no localStorage); it only knows whether a key exists and its masked form
// (e.g. "AIzaSy...4f2D"). Masked values sent back on save are mapped to the stored keys by the server.
const geminiKeyState = { hasKey: false, masked: [] };
let m4bAvailable = true;  // reported by GET /api/settings

function hasGeminiKey() {
  return Boolean(geminiKeyState.hasKey);
}

function getClientApiKey() {
  // Requests never carry a key: the server resolves one from its multi-key pool.
  return null;
}

function applyGeminiKeyState(sData) {
  if (!sData) return;
  geminiKeyState.hasKey = Boolean(sData.has_gemini_key);
  m4bAvailable = sData.m4b_available !== false;
  geminiKeyState.masked = Array.isArray(sData.gemini_api_keys) ? sData.gemini_api_keys.filter(Boolean) : [];
}

function isMaskedKeyValue(v) {
  return typeof v === 'string' && (v.includes('...') || v === '***');
}

async function migrateBrowserStoredGeminiKeys() {
  // Older versions kept the keys in localStorage: hand any real key over to the server once, then forget it.
  let legacy = [];
  try {
    const raw = localStorage.getItem('gemini_api_keys');
    if (raw) legacy = JSON.parse(raw);
    if (!Array.isArray(legacy) || legacy.length === 0) {
      const single = localStorage.getItem('gemini_api_key');
      legacy = single ? [single] : [];
    }
  } catch (_) { legacy = []; }
  const realKeys = legacy.filter(k => typeof k === 'string' && k.trim() && !isMaskedKeyValue(k));
  if (realKeys.length) {
    const merged = [...geminiKeyState.masked];
    for (const k of realKeys) if (merged.length < 4) merged.push(k);
    try {
      const res = await fetch(`${API}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gemini_api_keys: merged }),
      });
      if (!res.ok) return;   // keep local copy until the server has accepted it
    } catch (_) { return; }
  }
  try {
    localStorage.removeItem('gemini_api_key');
    localStorage.removeItem('gemini_api_keys');
  } catch (_) {}
}

async function refreshGeminiKeyState() {
  try {
    const sRes = await fetch(`${API}/settings`);
    if (!sRes.ok) return null;
    const sData = await sRes.json();
    applyGeminiKeyState(sData);
    return sData;
  } catch (_) {
    return null;
  }
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
  if (tab === 'insights' && typeof refreshInsightsPanel === 'function') refreshInsightsPanel();
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
    // The token-intensive maximum-quality revision exists only in Advanced Mode
    const mq = document.getElementById('tr-max-quality');
    if (mq) mq.checked = false;
    const mqWarn = document.getElementById('tr-max-quality-warning');
    if (mqWarn) mqWarn.style.display = 'none';
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
    : ['.pdf', '.docx', '.epub', '.cbz', '.cbr', '.zip'];
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

const FILE_ICONS = { pdf: '📕', docx: '📘', epub: '📗', cbz: '🎨', cbr: '🎨', zip: '🎨' };

const _mb = (bytes) => (bytes / 1024 / 1024).toFixed(1);

// POST /upload reporting its progress (fetch cannot), answered like fetch with a Response.
// onProgress(loaded, total, sent): `sent` once every byte is out and the server is reading the file.
// The returned promise has .abort(); an aborted upload rejects with an AbortError.
function uploadWithProgress(file, onProgress) {
  const fd = new FormData();
  fd.append('file', file);
  if (typeof XMLHttpRequest === 'undefined') {
    const p = fetch(`${API}/upload`, { method: 'POST', body: fd });
    p.abort = () => {};
    return p;
  }
  const xhr = new XMLHttpRequest();
  const p = new Promise((resolve, reject) => {
    xhr.open('POST', `${API}/upload`);
    xhr.upload.onprogress = (e) => { if (onProgress) onProgress(e.loaded, e.lengthComputable ? e.total : file.size, false); };
    xhr.upload.onload = () => { if (onProgress) onProgress(file.size, file.size, true); };
    xhr.onload = () => {
      const noBody = [204, 205, 304].includes(xhr.status);
      const res = new Response(noBody ? null : xhr.responseText, {
        status: xhr.status,
        headers: { 'Content-Type': xhr.getResponseHeader('Content-Type') || 'application/json' },
      });
      if (typeof window.__bookappAuthRedirect === 'function') window.__bookappAuthRedirect(res);
      resolve(res);
    };
    xhr.onerror = () => reject(new TypeError('Network error while uploading'));
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'));
    xhr.send(fd);
  });
  p.abort = () => xhr.abort();
  return p;
}

// The bar and line under the selected file while it uploads: percent and MB sent, then the server's reading of it
function showUploadProgress(prefix, file, loaded, total, sent = false) {
  const ext = file.name.split('.').pop().toUpperCase();
  const pct = sent ? 100 : Math.min(100, Math.round((loaded / Math.max(total, 1)) * 100));
  const meta = document.getElementById(`${prefix}-file-meta`);
  if (meta) {
    meta.textContent = sent
      ? `${_mb(file.size)} MB · ${ext} · ⏳ Ανέβηκε· επεξεργασία αρχείου…`
      : `${_mb(file.size)} MB · ${ext} · ⬆️ Ανέβασμα ${pct}% (${_mb(loaded)} / ${_mb(total)} MB)`;
  }
  const bar = document.getElementById(`${prefix}-upload-bar`);
  const fill = document.getElementById(`${prefix}-upload-bar-fill`);
  if (bar) {
    bar.style.display = '';
    bar.setAttribute('aria-valuenow', String(pct));
  }
  if (fill) {
    fill.style.width = `${pct}%`;
    if (sent) fill.classList.add('shimmer'); else fill.classList.remove('shimmer');
  }
}

function hideUploadProgress(prefix) {
  const bar = document.getElementById(`${prefix}-upload-bar`);
  const fill = document.getElementById(`${prefix}-upload-bar-fill`);
  if (bar) bar.style.display = 'none';
  if (fill) {
    fill.style.width = '0%';
    fill.classList.remove('shimmer');
  }
}

function showSelectedFile(prefix, file) {
  const ext = file.name.split('.').pop().toLowerCase();
  const icon = FILE_ICONS[ext] || '📄';

  document.getElementById(`${prefix}-file-icon`).textContent = icon;
  document.getElementById(`${prefix}-file-name`).textContent = file.name;
  showUploadProgress(prefix, file, 0, file.size);
  document.getElementById(`${prefix}-selected-file`).classList.add('visible');
  document.getElementById(`${prefix}-upload-zone`).style.display = 'none';
}

function removeFile(prefix) {
  stopJobTracking(prefix);
  if (state[prefix].upload) {  // removed while still uploading: stop sending it
    const upload = state[prefix].upload;
    state[prefix].upload = null;
    upload.abort();
  }
  hideUploadProgress(prefix);
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
    showScanChoice('');
    state.tr.sampleRun = null;
    updateSampleRow();
    const estEl = document.getElementById('tr-estimate');
    if (estEl) estEl.style.display = 'none';
    const sampleDone = document.getElementById('tr-sample-done');
    if (sampleDone) sampleDone.style.display = 'none';
    const prevLayout = document.getElementById('tr-layout-mode')?.value || 'standard';
    setGraphicNovelLock(false);
    if (!hasQueue) _formatChosenByUser = false;
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
      hintEl.innerHTML = `<span>🎨 <strong>Graphic Novel / Comic Auto-Detected${escHtml(detail)}:</strong> Ενεργοποιήθηκαν αποκλειστικά οι επιλογές Graphic Novel (<strong>PDF, CBZ, CBR, EPUB</strong> &amp; LTR/RTL). Οι επιλογές κειμένου/βιβλίου απενεργοποιήθηκαν αυτόματα.</span>`;
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

// ── Scanned PDF: a book (its text is read first) or a comic (translated on the page images) ──
function showScanChoice(kind, applyLayout = true) {
  const box = document.getElementById('tr-scan-choice');
  state.tr.scanKind = kind || '';
  if (!box) return;
  box.style.display = kind ? '' : 'none';
  if (kind) chooseScanKind(kind, applyLayout);
}

function chooseScanKind(kind, applyLayout = true) {
  state.tr.scanKind = kind;
  ['book', 'comic'].forEach((k) => {
    const btn = document.getElementById(`scan-kind-${k}`);
    if (btn) {
      btn.classList.toggle('active', k === kind);
      btn.setAttribute('aria-checked', String(k === kind));
    }
    const hint = document.getElementById(`tr-scan-hint-${k}`);
    if (hint) hint.style.display = k === kind ? '' : 'none';
  });
  if (applyLayout) {
    if (kind === 'comic') {
      setGraphicNovelLock(true, '', true);
    } else {
      setGraphicNovelLock(false);
      const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
      const stdBtn = document.getElementById('layout-standard');
      if (layout === 'comic' && stdBtn) selectLayout('standard', stdBtn);
      else updateFormatAvailability(layout, 'pdf');
      const fmt = document.getElementById('tr-output-format')?.value || '';
      const pdfBtn = document.getElementById('fmt-pdf');
      if (['cbz', 'cbr'].includes(fmt) && pdfBtn) selectFormat('pdf', pdfBtn);
    }
  }
  updateSampleRow();
  scheduleTranslationEstimate();
}

// ── Sample first: translate a few pages to see the style and quality before the whole book ──
function sampleUnitIsChapter() {
  const name = state.tr.file?.name || document.getElementById('tr-file-name')?.textContent || '';
  return name.split('.').pop().toLowerCase() === 'epub';
}

function updateSampleRow(resetRange = false) {
  const row = document.getElementById('tr-sample-row');
  if (!row) return;
  const visible = Boolean(state.tr.jobId) && state.tr.status !== 'running';
  row.style.display = visible ? '' : 'none';
  const btn = document.getElementById('tr-sample-btn');
  if (btn) btn.disabled = !visible;
  const unit = document.getElementById('tr-sample-unit');
  if (unit) unit.textContent = sampleUnitIsChapter() ? 'κεφάλαια' : 'σελίδες';
  if (resetRange) {
    const total = Number(state.tr.estimatedPages || 0);
    const span = sampleUnitIsChapter() ? 3 : 10;
    const fromEl = document.getElementById('tr-sample-from');
    const toEl = document.getElementById('tr-sample-to');
    if (fromEl) fromEl.value = '1';
    if (toEl) toEl.value = String(total ? Math.min(span, total) : span);
  }
}

function readSampleRange() {
  const total = Number(state.tr.estimatedPages || 0);
  let from = Math.max(1, parseInt(document.getElementById('tr-sample-from')?.value, 10) || 1);
  let to = parseInt(document.getElementById('tr-sample-to')?.value, 10) || from;
  if (total) {
    from = Math.min(from, total);
    to = Math.min(to, total);
  }
  return [from, Math.max(from, to)];
}

function onSampleRangeChange() {
  const [from, to] = readSampleRange();
  const fromEl = document.getElementById('tr-sample-from');
  const toEl = document.getElementById('tr-sample-to');
  if (fromEl) fromEl.value = String(from);
  if (toEl) toEl.value = String(to);
  scheduleTranslationEstimate();
}

function startSampleTranslation() {
  if (!state.tr.jobId) return;
  startTranslation({ sample: readSampleRange() });
}

function startFullAfterSample() {
  startTranslation({ sample: null });
}

// ── Before starting: about how many Gemini requests the translation needs, and what the keys allow a day ──
let _estimateTimer = null;
let _estimateSeq = 0;

function scheduleTranslationEstimate() {
  clearTimeout(_estimateTimer);
  _estimateTimer = setTimeout(refreshTranslationEstimate, 350);
}

function estimateQuery(sample = null) {
  const p = new URLSearchParams({
    ai_polish: String(Boolean(document.getElementById('tr-ai-polish')?.checked)),
    max_quality: String(isMaxQualityRequested()),
    layout_mode: document.getElementById('tr-layout-mode')?.value || 'standard',
    output_format: document.getElementById('tr-output-format')?.value || '',
  });
  if (state.tr.scanKind) p.set('read_scanned_text', String(state.tr.scanKind === 'book'));
  if (sample) {
    p.set('page_from', String(sample[0]));
    p.set('page_to', String(sample[1]));
  }
  return p.toString();
}

async function refreshTranslationEstimate() {
  const el = document.getElementById('tr-estimate');
  if (!el) return;
  const jobId = state.tr.jobId;
  if (!jobId || state.tr.status === 'running') {
    el.style.display = 'none';
    return;
  }
  const seq = ++_estimateSeq;
  const ask = (sample) => fetch(`${API}/translate/estimate/${encodeURIComponent(jobId)}?${estimateQuery(sample)}`)
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const [full, sample] = await Promise.all([ask(null), ask(readSampleRange())]);
  if (seq !== _estimateSeq || state.tr.jobId !== jobId) return;  // a newer request, or another file
  if (!full) {
    el.style.display = 'none';
    return;
  }
  el.innerHTML = formatEstimate(full, sample);
  el.style.display = '';
}

function formatEstimate(e, s = null) {
  const r = e.requests || {};
  if (e.read_scanned_text && !e.has_key) return '<span>📖 Χρειάζεται κλειδί Gemini για να διαβαστεί το κείμενο των σελίδων.</span>';
  if (e.comic && e.scanned && !e.has_key) return '<span>🎨 Χρειάζεται κλειδί Gemini για τις σκαναρισμένες σελίδες.</span>';
  if (!e.total) {
    return '<span>📊 Χωρίς αιτήματα Gemini: μεταφράζει η δωρεάν μηχανή (αν το Google αρνηθεί, μεταφράζει το Gemini).</span>';
  }
  const parts = [];
  if (r.read) parts.push(`<span>~${r.read} ανάγνωση σελίδων</span>`);
  if (r.translate) parts.push(`<span>~${r.translate} μετάφραση</span>`);
  if (r.revise) parts.push(`<span>~${r.revise} 2ο πέρασμα</span>`);
  let html = `<span>📊 Εκτίμηση: ~${e.total} αιτήματα Gemini</span> (${parts.join(' · ')}).`;
  const heavy = (r.translate || 0) + (r.revise || 0);
  if (heavy && heavy <= e.best_per_day) {
    html += ` <span>Τα κλειδιά σας (${e.keys}) δίνουν ~${e.best_per_day} την ημέρα στο καλύτερο μοντέλο: χωράνε σήμερα.</span>`;
  } else if (heavy && r.revise) {
    html += ` <span>Τα κλειδιά σας (${e.keys}) δίνουν ~${e.best_per_day} την ημέρα στο καλύτερο μοντέλο· το 2ο πέρασμα δουλεύει μόνο με πλήρη μοντέλα: ~${e.best_days} μέρες.</span>`;
  } else if (heavy) {
    html += ` <span>Τα κλειδιά σας (${e.keys}) δίνουν ~${e.best_per_day} την ημέρα στο καλύτερο μοντέλο· μετά η μετάφραση συνεχίζει με ελαφρύτερο μοντέλο.</span>`;
  }
  if (s && Array.isArray(s.sample) && s.total < e.total) {
    html += ` <span>Δείγμα ${s.sample[0]}–${s.sample[1]}: ~${s.total} αιτήματα.</span>`;
  }
  return html;
}

async function uploadFile(prefix, file) {
  const selected = state[prefix].file; // what was selected when this upload began
  if (state[prefix].upload) state[prefix].upload.abort();  // a newer file replaces one still uploading
  const upload = uploadWithProgress(file, (loaded, total, sent) => {
    if (state[prefix].file === selected) showUploadProgress(prefix, file, loaded, total, sent);
  });
  state[prefix].upload = upload;

  try {
    const res = await upload;
    if (state[prefix].upload === upload) state[prefix].upload = null;
    if (!res.ok) {
      throw new Error(await parseApiError(res, 'Upload failed'));
    }
    const data = await res.json();
    if (state[prefix].file !== selected) { // removed, or replaced (possibly by one of the same name)
      console.log(`[Upload] File was swapped while upload was in flight; ignoring job ${data.job_id}`);
      return;
    }
    hideUploadProgress(prefix);
    state[prefix].jobId = data.job_id;
    state[prefix].estimatedPages = Number(data.estimated_pages || 0);
    if (prefix === 'tr' && typeof onMaxQualityToggle === 'function') onMaxQualityToggle();

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
          _formatChosenByUser = false;
        }
        checkCoverImage(data.job_id);

        // Auto-Genre Detection
        detectDocumentGenre(data.job_id, data.file_type);
      }
      showScanChoice(data.scan_kind || '', false);  // the lock above already follows the preselected choice
      updateSampleRow(true);
      scheduleTranslationEstimate();
    }
  } catch (err) {
    if (state[prefix].upload === upload) state[prefix].upload = null;
    // removed or replaced while uploading: that was the user's choice, not an error
    if (err && err.name === 'AbortError') return;
    if (state[prefix].file !== selected) return;
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
      body: JSON.stringify({ sample_text: sample.substring(0, 3500), file_type: fileType, subjects: prevData.subjects || [] }),
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

function selectFormat(fmt, btn, byUser = false) {
  if (!btn) return;
  if (btn.disabled || btn.classList.contains('format-btn-disabled')) {
    toast(`⚠️ Το format ${fmt.toUpperCase()} είναι απενεργοποιημένο για Graphic Novels. Επιλέξτε PDF, CBZ, CBR ή EPUB.`, 'info');
    return;
  }
  // Deselect only format buttons (not layout buttons)
  document.querySelectorAll('#tr-format-selector .format-btn').forEach((b) => b.classList.remove('active'));
  btn.classList.add('active');
  if (byUser) _formatChosenByUser = true;
  document.getElementById('tr-output-format').value = fmt;
  syncResultDownload(fmt);
}

// The result card's main download button names, describes and fetches the format currently chosen
function syncResultDownload(fmt, layout = document.getElementById('tr-layout-mode')?.value || 'standard') {
  const label = fmt.toUpperCase();
  const labelEl = document.getElementById('tr-format-label');
  if (labelEl) labelEl.textContent = layout === 'comic' ? `Graphic Novel (${label})` : label;
  const metaEl = document.getElementById('tr-result-meta');
  if (metaEl && layout !== 'comic') {
    metaEl.textContent = `Your document has been translated. Click below to download the ${label} file.`;
  }
  const dlBtn = document.getElementById('tr-download-btn');
  if (dlBtn && state.tr.jobId) {
    dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}&layout=${layout}`;
  }
}

// A quick-download button (PDF / DOCX / EPUB / TXT next to the main one) makes its format the chosen one
function chooseResultFormat(fmt) {
  const input = document.getElementById('tr-output-format');
  if (!input || input.value === fmt) return;
  input.value = fmt;
  const btn = document.getElementById(`fmt-${fmt}`);
  if (btn && !btn.disabled && !btn.classList.contains('format-btn-disabled')) {
    document.querySelectorAll('#tr-format-selector .format-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
  }
  syncResultDownload(fmt);
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
    const kept = (await res.json().catch(() => ({})))?.preserved_files || [];
    if (kept.length) {
      toast(`✅ Το εξώφυλλο αποθηκεύτηκε. Δεν μπαίνει στο ${kept.join(', ')}, ώστε να διατηρηθεί η μορφοποίησή του.`, 'info');
    } else {
      toast('✅ Book cover updated successfully! Included in PDF, EPUB & DOCX.', 'success');
    }
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
    'Nestoras (Male)': '👨',
    'Aria (Female)': '👩',
    'Guy (Male)': '👨',
    'Jenny (Female)': '👩',
    'Brian (Male)': '👨',
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

  // A separate dialogue voice needs a second voice in this language (Greek has one)
  const multiVoice = document.getElementById('ab-multi-voice');
  const multiGroup = document.getElementById('ab-multi-voice-group');
  if (multiGroup) multiGroup.style.display = entries.length > 1 ? '' : 'none';
  if (multiVoice && entries.length < 2) {
    multiVoice.checked = false;
    toggleMultiVoiceSelect();
  }

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

function _setVoicePreviewStopVisible(visible) {
  const btn = document.getElementById('ab-preview-stop-btn');
  if (btn) btn.style.display = visible ? '' : 'none';
}

// ⏹️ Διακοπή: stops a voice sample at once (also one still being generated) instead of waiting for its end
function stopVoicePreview() {
  const audio = currentAudioPreview;
  currentAudioPreview = null;
  if (audio) {
    try {
      audio.pause();
      audio.removeAttribute('src');   // aborts the download of a sample that is still being generated
      audio.load();
    } catch (_) {}
  }
  _setVoicePreviewStopVisible(false);
}

function playVoicePreview(voiceCode, event, customText = null) {
  if (event) event.stopPropagation();
  stopVoicePreview();
  const customInput = document.getElementById('ab-custom-preview-text')?.value?.trim();
  const sample = (customText || customInput || '').slice(0, 150);
  let url = `${API}/tts/preview?voice=${encodeURIComponent(voiceCode)}`;
  if (sample) {
    url += `&text=${encodeURIComponent(sample)}`;
  }
  if (typeof Audio !== 'undefined') {
    const audio = new Audio(url);
    currentAudioPreview = audio;
    const finished = () => { if (currentAudioPreview === audio) stopVoicePreview(); };
    audio.addEventListener('ended', finished);
    audio.addEventListener('error', finished);
    _setVoicePreviewStopVisible(true);
    toast(`🔊 Παραγωγή δείγματος για ${voiceCode}...`, 'info');
    audio.play().catch(e => {
      console.debug('Preview audio playback failed:', e);
      finished();
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
async function startTranslation(opts = {}) {
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
  if (!opts.keepSavedFormat && currentAppMode === 'basic' && ['pdf', 'docx', 'epub', 'cbz', 'cbr', 'txt'].includes(fileExt)) {
    outputFormat = fileExt;
    document.getElementById('tr-output-format').value = fileExt;
  }
  const layoutMode = document.getElementById('tr-layout-mode')?.value || 'standard';
  if (layoutMode === 'comic' && (outputFormat === 'txt' || outputFormat === 'docx')) {
    outputFormat = 'pdf';
    document.getElementById('tr-output-format').value = 'pdf';
  }
  const aiPolish = document.getElementById('tr-ai-polish')?.checked || false;
  const apiKey = getClientApiKey();
  const hasKey = hasGeminiKey();
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
  state.tr.etaSamples = [];
  // A sample: only these pages. Resume keeps the sample it was; a new start is the whole book unless it asks for one.
  const sample = 'sample' in opts ? opts.sample : (opts.resume ? state.tr.sampleRun : null);
  state.tr.sampleRun = sample || null;
  state.tr.status = 'running';
  updateSampleRow();
  const estEl = document.getElementById('tr-estimate');
  if (estEl) estEl.style.display = 'none';
  const sampleDone = document.getElementById('tr-sample-done');
  if (sampleDone) sampleDone.style.display = 'none';

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
        max_quality: isMaxQualityRequested(),
        read_scanned_text: state.tr.scanKind ? state.tr.scanKind === 'book' : null,
        page_from: sample ? sample[0] : null,
        page_to: sample ? sample[1] : null,
      }),
    });
    if (!res.ok) {
      throw new Error(await parseApiError(res, 'Failed to start translation'));
    }

    // Connect SSE for progress
    connectSSE('tr', jobId);
  } catch (err) {
    state.tr.status = 'error';
    showError('tr', err.message);
    setActionButtonsEnabled('tr', true);
    updateSampleRow();
  }
}

// ── Quota Limit Behavior (Wait vs Auto-Fallback) ────────────────
function onQuotaBehaviorChange(prefix) {
  const sel = document.querySelector(`input[name="${prefix}-quota-behavior"]:checked`);
  const val = sel ? sel.value : 'wait';
  const descEl = document.getElementById(`${prefix}-quota-behavior-desc`);
  const hasKey = hasGeminiKey();
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
          : '🔄 <em>Δωρεάν Μοντέλα (Προεπιλογή):</em> Χωρίς Gemini API Key, χρησιμοποιείται η δωρεάν μηχανή. Οι δωρεάν υπηρεσίες έχουν όρια και συχνά αρνούνται αιτήματα: τότε η εργασία σταματά με μήνυμα.';
      } else {
        descEl.innerHTML = (prefix === 'ab')
          ? '🔄 <em>Auto-Fallback:</em> Εάν εξαντληθεί το όριο Gemini στο Script Polish, η εκφώνηση συνεχίζει άμεσα χωρίς διακοπή χρησιμοποιώντας το αρχικό κείμενο (δωρεάν Edge-TTS).'
          : '🔄 <em>Auto-Fallback:</em> Εάν εξαντληθεί το όριο Gemini, η εργασία συνεχίζει άμεσα χωρίς διακοπή χρησιμοποιώντας τη δωρεάν μηχανή μετάφρασης (χωρίς όρια χρήσης).';
      }
    }
  }
}

function initQuotaBehaviorSelectors() {
  // Default: Wait for Reset (full Gemini quality) whenever a Gemini key exists; without a key only the free engine
  // can run. A choice applies to the current page only: older versions remembered it, and a one-time Auto-Fallback
  // (or a job loaded from history) then silently became the default.
  const targetVal = hasGeminiKey() ? 'wait' : 'fallback';
  ['tr', 'ab'].forEach((prefix) => {
    try {
      localStorage.removeItem(`${prefix}_quota_behavior`);
    } catch (_) {}
    try {
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
  const apiKey = getClientApiKey();
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
  state.ab.etaSamples = [];

  try {
    const hasKey = hasGeminiKey();  // not apiKey: keys live on the server, so that is always null
    const isMultiVoice = document.getElementById('ab-multi-voice')?.checked || false;
    const dialogueVoice = isMultiVoice ? (document.getElementById('ab-dialogue-voice-select')?.value || null) : null;
    const quotaBehaviorEl = document.querySelector('input[name="ab-quota-behavior"]:checked');
    let quotaBehavior = quotaBehaviorEl ? quotaBehaviorEl.value : (hasKey ? 'wait' : 'fallback');
    if (!hasKey && quotaBehavior === 'wait') {
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
  for (const shown of [_shownRefinementReports, _shownRevisionReports, _shownUsageReports]) shown.delete(jobId); // a new run

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
    notifyRefinementReport(jobId, data);
    notifyRevisionReport(jobId, data);
    notifyGeminiUsage(jobId, data);

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

// ---------------------------------------------------------------------------
// Final Output Refinement (automatic quality-control stage) — global toggle & report
// ---------------------------------------------------------------------------
const _shownRefinementReports = new Set();

function syncFinalRefinementToggles(enabled) {
  document.querySelectorAll('.final-refinement-toggle').forEach(cb => { cb.checked = !!enabled; });
}

async function setFinalRefinementEnabled(enabled) {
  syncFinalRefinementToggles(enabled);
  try {
    const res = await fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ final_refinement_enabled: !!enabled }),
    });
    if (!res.ok) throw new Error('save failed');
    toast(enabled ? '🔍 Ο τελικός έλεγχος ποιότητας ενεργοποιήθηκε.' : 'Ο τελικός έλεγχος ποιότητας απενεργοποιήθηκε.', 'info');
  } catch (_) {
    syncFinalRefinementToggles(!enabled);
    toast('Αποτυχία αποθήκευσης ρύθμισης τελικού ελέγχου.', 'error');
  }
}

function isMaxQualityRequested() {
  const cb = document.getElementById('tr-max-quality');
  return currentAppMode === 'advanced' && Boolean(cb && cb.checked);
}

function onAiPolishToggle() {
  const ai = document.getElementById('tr-ai-polish');
  const mq = document.getElementById('tr-max-quality');
  if (ai && mq && !ai.checked && mq.checked) {
    mq.checked = false;
    onMaxQualityToggle();
  }
}

function onMaxQualityToggle() {
  const mq = document.getElementById('tr-max-quality');
  const warn = document.getElementById('tr-max-quality-warning');
  if (!mq || !warn) return;
  if (!mq.checked) {
    warn.style.display = 'none';
    return;
  }
  const ai = document.getElementById('tr-ai-polish');
  if (ai && !ai.checked) ai.checked = true;   // the revision pass revises the AI translation
  const pages = Number(state.tr.estimatedPages || 0);
  // ~300 words/page; revision reads source (~1.3 tok/word) + translation (~1.6) and writes the translation (~1.6)
  const estTxt = pages
    ? ` Για αυτό το έγγραφο: περίπου <strong>${Math.round(pages * 300 * 4.5).toLocaleString('el-GR')} επιπλέον tokens</strong>.`
    : '';
  const [low, high] = revisionMinutes(pages);
  const requests = Math.ceil(pages / REVISION_PAGES_PER_REQUEST);
  const timeTxt = pages
    ? `Για αυτό το έγγραφο (~${pages} σελίδες) υπολογίστε περίπου <strong>${formatMinutesEl(low)} – ${formatMinutesEl(high)}</strong> ` +
      'επιπλέον, πάνω από τον χρόνο της AI μετάφρασης.'
    : 'Υπολογίστε περίπου <strong>3–8 δευτερόλεπτα ανά σελίδα</strong> επιπλέον (π.χ. 15–40 λεπτά για βιβλίο 300 σελίδων).';
  const dailyTxt = requests > 20
    ? ` Χρειάζονται περίπου ${requests} αιτήματα Gemini: με δωρεάν κλειδί το ημερήσιο όριο ενός μοντέλου μπορεί να είναι μόλις 20, ` +
      'οπότε η αναθεώρηση μπορεί να σταματήσει νωρίτερα (κρατιέται τότε η μετάφραση του 1ου περάσματος).'
    : '';
  const hasKey = hasGeminiKey();
  warn.innerHTML = '🐢 <strong>Πολύ αργή διαδικασία.</strong> ' + timeTxt +
    ' Κατά την εκτέλεση εμφανίζεται ο χρόνος που απομένει.' + dailyTxt + '<br>' +
    '⚠️ <strong>Επιπλέον κατανάλωση Gemini API:</strong> το πρωτότυπο και η μετάφραση αποστέλλονται ξανά για αναθεώρηση. ' +
    'Η κατανάλωση tokens είναι περίπου <strong>1,5 φορά</strong> αυτή της AI μετάφρασης.' + estTxt +
    ' Μετράει στο ημερήσιο όριο των κλειδιών σας. Χρησιμοποιούνται μόνο πλήρη μοντέλα Gemini· αν δεν είναι διαθέσιμα, κρατιέται η μετάφραση του 1ου περάσματος.' +
    (hasKey ? '' : ' <br>❗ Δεν έχει οριστεί Gemini API Key — απαιτείται.');
  warn.style.display = '';
}

// The 2nd pass sends up to 3 pages per Gemini request, 5 at a time, with the full (slower) models only:
// about 3–8 seconds per page in practice, waits for per-minute limits included.
const REVISION_PAGES_PER_REQUEST = 3;

function revisionMinutes(pages) {
  if (!pages) return [0, 0];
  return [Math.max(1, Math.round(pages * 3 / 60)), Math.max(1, Math.ceil(pages * 8 / 60))];
}

function formatMinutesEl(minutes) {
  if (minutes < 60) return minutes === 1 ? '1 λεπτό' : `${minutes} λεπτά`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const hours = h === 1 ? '1 ώρα' : `${h} ώρες`;
  return m ? `${hours} ${m === 1 ? '1 λεπτό' : `${m} λεπτά`}` : hours;
}

const _shownRevisionReports = new Set();

function notifyRevisionReport(jobId, data) {
  const rep = data && data.revision_report;
  if (!rep || data.status !== 'done' || !jobId || _shownRevisionReports.has(jobId)) return;
  _shownRevisionReports.add(jobId);
  const kept = rep.kept_pages ? ` · ${rep.kept_pages} σελίδες κράτησαν το 1ο πέρασμα (η αναθεώρησή τους δεν ήταν αξιόπιστη).` : '';
  if (rep.status === 'revised') {
    toast(`🏆 Αναθεώρηση με το πρωτότυπο: διορθώθηκαν ${rep.changed_lines || 0} γραμμές.${kept}`, kept ? 'warning' : 'success');
  } else if (rep.status === 'verified_clean') {
    toast(`🏆 Αναθεώρηση με το πρωτότυπο: δεν χρειάστηκαν διορθώσεις.${kept}`, kept ? 'warning' : 'info');
  } else if (rep.status === 'error' && rep.reason === 'quota_exhausted') {
    toast('🏆 Η αναθεώρηση παραλείφθηκε (όριο Gemini ή μη διαθέσιμο πλήρες μοντέλο) — κρατήθηκε η μετάφραση του 1ου περάσματος.', 'warning');
  } else if (rep.status === 'error') {
    toast('🏆 Η αναθεώρηση δεν ολοκληρώθηκε — κρατήθηκε η μετάφραση του 1ου περάσματος.', 'warning');
  } else if (rep.status === 'skipped' && rep.reason === 'requires_ai_polish_and_key') {
    toast('🏆 Η αναθεώρηση απαιτεί AI Polish και Gemini API Key.', 'info');
  } else if (rep.status === 'skipped' && rep.reason === 'format_preserved_output') {
    toast('🏆 Η αναθεώρηση δεν εφαρμόζεται όταν διατηρείται η αρχική μορφοποίηση (DOCX→DOCX / EPUB→EPUB).', 'info');
  }
}

// ── Gemini usage per job / per day ─────────────────────────
function formatGeminiUsage(u) {
  if (!u) return '';
  const tok = Number(u.total_tokens || ((u.prompt_tokens || 0) + (u.output_tokens || 0)));
  const cached = u.cached ? ` · ${u.cached} από cache` : '';
  return `${u.requests || 0} αιτήματα · ~${tok.toLocaleString('el-GR')} tokens${cached}`;
}

const _shownUsageReports = new Set();

function notifyGeminiUsage(jobId, data) {
  const u = data && data.gemini_usage;
  if (!u || data.status !== 'done' || !jobId || _shownUsageReports.has(jobId)) return;
  _shownUsageReports.add(jobId);
  if ((u.requests || 0) + (u.cached || 0) > 0) toast(`🔢 Gemini: ${formatGeminiUsage(u)}`, 'info');
}

async function loadGeminiUsageToday() {
  const el = document.getElementById('gemini-usage-today');
  if (!el) return;
  try {
    const res = await fetch(`${API}/gemini/status`);
    if (!res.ok) return;
    const data = await res.json();
    el.textContent = data.usage_today ? `Σήμερα: ${formatGeminiUsage(data.usage_today)}` : '';
  } catch (_) {}
}

function notifyRefinementReport(jobId, data) {
  const rep = data && data.refinement_report;
  if (!rep || data.status !== 'done' || !jobId || _shownRefinementReports.has(jobId)) return;
  _shownRefinementReports.add(jobId);
  const nCorr = Array.isArray(rep.corrections) ? rep.corrections.length : 0;
  if (rep.critical_count > 0) {
    const missing = Array.isArray(rep.missing_sections) && rep.missing_sections.length
      ? ` (${rep.missing_sections.length} τμήματα ήχου λείπουν)` : '';
    toast(`⚠️ Τελικός έλεγχος: ${rep.critical_count} κρίσιμα ζητήματα${missing}. Ελέγξτε το αποτέλεσμα.`, 'warning');
  } else if (rep.status === 'refined' || rep.status === 'healed') {
    toast(`🔍 Τελικός έλεγχος: εφαρμόστηκαν ${nCorr} ομάδες διορθώσεων.`, 'success');
  }
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
      notifyRefinementReport(jobId, data);
      notifyRevisionReport(jobId, data);
      notifyGeminiUsage(jobId, data);
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

// Time left from the recent pace. Samples (time, done) start from what is already done when this page begins to
// watch (a resumed or reloaded job is not divided by a few seconds of watching), and only the last few minutes count,
// so a fast start from cached batches, the slow start and waits for Gemini limits fade out.
const ETA_WINDOW_MS = 5 * 60 * 1000;
const ETA_MIN_SPAN_S = 45;  // no estimate before this much watched progress

function estimateTimeLeft(prefix, done, total, now = Date.now()) {
  const st = state[prefix];
  if (!Array.isArray(st.etaSamples) || st.etaTotal !== total) {  // another job or another phase
    st.etaSamples = [];
    st.etaTotal = total;
  }
  const samples = st.etaSamples;
  const last = samples[samples.length - 1];
  if (last && (done < last[1] || (done > last[1] && now - last[0] > ETA_WINDOW_MS))) {
    samples.length = 0;  // went back, or moved again after a long pause (a wait for Gemini limits): measure afresh
  }
  if (!samples.length || samples[samples.length - 1][1] !== done) samples.push([now, done]);
  else if (now - samples[samples.length - 1][0] > ETA_WINDOW_MS) return null;  // nothing moved for minutes
  while (samples.length > 2 && now - samples[1][0] > ETA_WINDOW_MS) samples.shift();
  if (samples.length < 3) return null;  // the first steps watched may be a burst from cache: no pace yet
  const [t0, d0] = samples[0];
  const span = (now - t0) / 1000;  // up to now: a pause since the last step slows the pace down too
  const progressed = done - d0;
  if (progressed <= 0 || span < ETA_MIN_SPAN_S) return null;
  const perSecond = progressed / span;
  return { seconds: (total - done) / perSecond, perMinute: perSecond * 60 };
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
      const isAiStep = (Boolean(data.ai_polish) && hasGeminiKey()) || stepLower.includes('ai translation') || stepLower.includes('polish') || stepLower.includes('gemini');
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
        engineBadge.textContent = '⚡ Free Translation';
      }
    } else {
      engineBadge.style.display = 'inline-flex';
      engineBadge.className = 'engine-pill engine-free';
      engineBadge.textContent = '⚡ Edge-TTS Neural';
    }
  }

  // Live time left & processing speed, from the recent pace
  const etaEl = document.getElementById(`${prefix}-progress-eta`);
  if (etaEl) {
    // pages when the job counts them (AI translation); other jobs count parts and leave done_pages at 0
    const byPages = prefix === 'tr' && data.total_pages > 0 && (data.done_pages > 0 || !data.done_chunks);
    const done = Number(byPages ? data.done_pages : (data.done_chunks || data.done_pages || 0));
    const total = Number(byPages ? data.total_pages : (data.total_chunks || data.total_pages || 0));
    const est = data.status === 'running' && total > done ? estimateTimeLeft(prefix, done, total) : null;
    if (data.status !== 'running') state[prefix].etaSamples = [];  // a wait or a stop: the pace starts afresh
    if (est) {
      const time = est.seconds < 60 ? '<span>λιγότερο από 1 λεπτό</span>'
        : `~<span>${formatMinutesEl(Math.round(est.seconds / 60))}</span>`;
      const pace = `${est.perMinute < 10 ? est.perMinute.toFixed(1) : Math.round(est.perMinute)} ${byPages ? 'σελ/λ' : 'τμήματα/λ'}`;
      // Maximum quality: the revision against the original comes after this and has its own time left
      const second = data.max_quality && prefix === 'tr' ? ' · <span>+ το 2ο πέρασμα AI μετά</span>' : '';
      etaEl.innerHTML = `⏳ Απομένουν: <strong>${time}</strong> (<span>${pace}</span>)${second}`;
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
    if ((data.current_step || '').startsWith('📖')) {  // a scanned book's pages are read first (Gemini Vision)
      detailEl.textContent = `Read ${data.done_chunks} of ${data.total_chunks} pages`;
    } else if (prefix === 'tr') {
      const stepLower = (data.current_step || '').toLowerCase();
      const totalPages = Number(data.total_pages || 0);
      const donePages = Number(data.done_pages || 0);
      const isBatchMode =
        stepLower.includes('batch') ||
        stepLower.includes('single-pass') ||
        stepLower.includes('ai translation') ||
        (totalPages > 0 && totalPages > data.total_chunks);
      const unit = (/\b(segment|paragraph|block)\b/.exec(stepLower) || [])[1];
      if (unit) {
        detailEl.textContent = `Translated ${data.done_chunks} of ${data.total_chunks} ${unit}s`;
      } else if (isBatchMode) {
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
    const doneStep = data.current_step || ''; // a finished job may carry a warning (substituted voice)
    document.getElementById(`${prefix}-progress-step`).textContent = doneStep.startsWith('⚠') ? doneStep : '✅ Complete';
    setActionButtonsEnabled(prefix, true);
    const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
    if (cancelBtn) cancelBtn.style.display = 'none';
    showResult(prefix, data);
    refreshHistory();
    if (prefix === 'tr') afterTranslationStopped();
    toast(prefix === 'tr' ? '✅ Translation complete!' : '🎉 Audiobook ready!', 'success');
  } else if (data.status === 'error') {
    state[prefix].status = 'error';
    setStatusBadge(prefix, 'error');
    const cancelBtn = document.getElementById(`${prefix}-cancel-btn`);
    if (cancelBtn) cancelBtn.style.display = 'none';
    showError(prefix, data.error || 'An unknown error occurred.');
    setActionButtonsEnabled(prefix, true);
    refreshHistory();
    if (prefix === 'tr') afterTranslationStopped();
  } else if (data.status === 'cancelled') {
    if (prefix === 'tr') setTimeout(afterTranslationStopped, 0);
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

// A translation ended (done, error or cancelled): the sample row and the estimate are offered again
function afterTranslationStopped() {
  updateSampleRow();
  scheduleTranslationEstimate();
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
  state[prefix].etaSamples = [];
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
    Object.assign(_readAlong, { jobId: null, segments: [], rendered: false, current: -1 });
    const raPanel = document.getElementById('ab-readalong');
    if (raPanel) raPanel.style.display = 'none';
    const raBtn = document.getElementById('ab-readalong-btn');
    if (raBtn) raBtn.style.display = 'none';
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
    let serverFmt = (data?.output_format || '').toLowerCase();
    if (['mp3', 'm4b'].includes(serverFmt)) serverFmt = ''; // the job's audiobook is not its translation
    const curFmt = (document.getElementById('tr-output-format')?.value || '').toLowerCase();
    const fmt = serverFmt || curFmt || 'pdf';
    const label = fmt.toUpperCase();
    const trFmtInput = document.getElementById('tr-output-format');
    if (trFmtInput) trFmtInput.value = fmt;
    const layout = (data?.layout_mode || document.getElementById('tr-layout-mode')?.value || 'standard').toLowerCase();
    if (layout === 'comic') {
      const comicLang = document.getElementById('tr-target-lang')?.value === 'english' ? 'Αγγλικά' : 'Ελληνικά';
      meta.textContent = `Το Graphic Novel / Comic μεταφράστηκε με επιτυχία! Η εικονογράφηση διατηρήθηκε 100% και τα μπαλόνια διαλόγου αποδόθηκαν στα ${comicLang}.`;
    } else {
      meta.textContent = `Your document has been translated. Click below to download the ${label} file.`;
    }
    syncResultDownload(fmt, layout);  // the main download button's format label and link
    const bilingualBtn = document.getElementById('tr-bilingual-btn');
    if (bilingualBtn) bilingualBtn.style.display = layout === 'comic' ? 'none' : '';  // a comic's text is in its pictures
    const sampleDone = document.getElementById('tr-sample-done');
    const sampleText = document.getElementById('tr-sample-done-text');
    const doneSample = Array.isArray(data?.sample_range) ? data.sample_range : null;
    if (sampleDone) sampleDone.style.display = doneSample ? '' : 'none';
    if (doneSample && sampleText) {
      sampleText.textContent = `🧪 Αυτό είναι δείγμα (${doneSample[0]}–${doneSample[1]}). Αν σας αρέσει, μεταφράστε όλο το βιβλίο.`;
    }
    const dlBtn = document.getElementById('tr-download-btn');
    if (dlBtn && state.tr.jobId) {
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
      audio.src = `${API}/download/${state.ab.jobId}?format=mp3`;
      loadAudioChapters(state.ab.jobId);
      loadReadAlong(state.ab.jobId);
      if (trackTitle) trackTitle.textContent = (data && data.file_name) || state.ab.file?.name || 'Audiobook';
      if (trackVoice) {
        const vName = (data && data.voice_name) || state.selectedVoice || 'Neural Voice';
        trackVoice.textContent = `${vName} · MP3 High Fidelity`;
      }
    }
    const abDlBtn = document.getElementById('ab-download-btn');
    if (abDlBtn && state.ab.jobId) {
      abDlBtn.href = `${API}/download/${state.ab.jobId}?format=mp3`;
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
    // never from the Reader's cache: that may hold another book, or this one before it was edited
    let textToCopy = '';
    const res = await fetch(`${API}/jobs/${jobId}/text`);
    if (res.ok) {
      const data = await res.json();
      textToCopy = (data.translated_text || data.original_text || '').trim();
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

function isQuotaMessage(msg) {
  const text = String(msg || '').replace(/\S+\.(pdf|docx|doc|epub|txt|cbz|cbr|zip)\b/gi, ' ');
  return /quota|resource_exhausted|(^|[^\w.-])429(?![\w-])|εξαντλήθηκε|εξάντλησης|are in cooldown/i.test(text);
}

function showError(prefix, msg) {
  const errEl = document.getElementById(`${prefix}-error-msg`);
  if (errEl) errEl.textContent = msg;
  const card = document.getElementById(`${prefix}-error-card`);
  if (card) card.classList.add('visible');

  const isQuota = isQuotaMessage(msg);
  if (state[prefix]) state[prefix].quotaStopped = isQuota; // only this may ever resume by itself
  // every stopped job can continue from its checkpoint by hand (the outage message tells the user to press it)
  const canResume = isQuota || Boolean(msg && state[prefix]?.jobId);
  const quotaActions = document.getElementById(`${prefix}-error-quota-actions`);
  if (quotaActions) {
    quotaActions.style.display = canResume ? 'inline-flex' : 'none';
    const changeKey = quotaActions.querySelector?.('button:not([id])');
    if (changeKey) changeKey.style.display = isQuota ? '' : 'none';
  }
  const errResumeBtn = document.getElementById(`${prefix}-error-resume-btn`);
  if (errResumeBtn && canResume) errResumeBtn.style.display = 'inline-flex';
  const resumeBtn = document.getElementById(`${prefix}-resume-btn`);
  if (resumeBtn) resumeBtn.style.display = canResume ? 'inline-flex' : 'none';
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
    await startTranslation({ resume: true });
  }
}

function setStatusBadge(prefix, status) {
  const badge = document.getElementById(`${prefix}-status-badge`);
  badge.className = `status-badge status-${status}`;
  const labels = { idle: 'Idle', running: 'Running', done: 'Complete', error: 'Error', cancelled: 'Cancelled' };
  badge.innerHTML = `<span class="status-dot"></span> ${escHtml(labels[status] || status)}`;
}

// ── Files on an iPhone / iPad ──
// There a downloaded file opens over the app in its own window. In the Home Screen app (since iOS 26 every Home
// Screen shortcut opens as one, whatever the manifest says) that window has no back button and the app is lost until
// it is closed; whether the page runs as one is not reliably told (navigator.standalone, display-mode). A new window
// would not help: it does not share the app's sign-in. So on every iPhone and iPad the app fetches the file itself and
// hands it to the Share sheet (Save to Files, Books, Mail…), staying where it was. Elsewhere files download as before.
const DOWNLOAD_URL_RE = /\/api\/(?:download\/|insights\/[^/?#]+\/files\/)/;

function filesTrapTheApp() {
  try {
    const nav = typeof navigator !== 'undefined' ? navigator : {};
    return /iPhone|iPad|iPod/.test(nav.userAgent || '') || (nav.platform === 'MacIntel' && nav.maxTouchPoints > 1);
  } catch (_) {
    return false;
  }
}

function _downloadName(res, url) {
  const cd = res.headers.get('Content-Disposition') || '';
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) {
    try { return decodeURIComponent(star[1]); } catch (_) { /* the plain name below */ }
  }
  const plain = cd.match(/filename="?([^";]+)"?/i);
  if (plain) return plain[1];
  try { return decodeURIComponent(url.split('?')[0].split('/').pop()); } catch (_) { return 'file'; }
}

async function _shareFile(file) {
  await navigator.share({ files: [file], title: file.name });
}

// The tap that asked for the file has expired while it was prepared: one more tap shares it
let _readyFile = null;

function showFileReady(file) {
  _readyFile = file;
  document.getElementById('file-ready-name').textContent = file.name;
  document.getElementById('file-ready-bar').style.display = 'flex';
}

function hideFileReady() {
  _readyFile = null;
  const bar = document.getElementById('file-ready-bar');
  if (bar) bar.style.display = 'none';
}

async function shareReadyFile() {
  if (!_readyFile) {
    hideFileReady();
    return;
  }
  try {
    await _shareFile(_readyFile);
    hideFileReady();
  } catch (err) {
    if (!err || err.name !== 'AbortError') toast(`❌ ${err?.message || err}`, 'error');
  }
}

async function _shareFromApp(url, fallbackName) {
  toast('⏳ Προετοιμασία αρχείου…', 'info');
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(await parseApiError(res, 'Η λήψη του αρχείου απέτυχε'));
  const blob = await res.blob();
  const name = _downloadName(res, url) || fallbackName || 'file';
  const file = new File([blob], name, { type: blob.type || 'application/octet-stream' });
  if (!(navigator.canShare && navigator.canShare({ files: [file] }))) {
    window.location.href = url;  // no Share sheet for files on this device: the old way
    return;
  }
  try {
    await _shareFile(file);
  } catch (err) {
    if (err && err.name === 'AbortError') return;  // the user closed the Share sheet
    showFileReady(file);
  }
}

// Every download goes through here (buttons, Book Insights exports, the History's links)
function saveFile(url, fileName = '') {
  if (filesTrapTheApp()) {
    _shareFromApp(url, fileName).catch((err) => toast(`❌ ${err?.message || err}`, 'error'));
    return;
  }
  if (!fileName) {
    window.location.href = url;
    return;
  }
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// Plain download links (the History, the Book Insights MP3); buttons with their own onclick call saveFile themselves
document.addEventListener('click', (event) => {
  if (!filesTrapTheApp()) return;
  const link = event.target && event.target.closest ? event.target.closest('a[href]') : null;
  if (!link || link.hasAttribute('onclick') || !DOWNLOAD_URL_RE.test(link.getAttribute('href') || '')) return;
  event.preventDefault();
  saveFile(link.href, link.getAttribute('download') || '');
}, true);

async function downloadOutput(prefix, overrideFmt = null) {
  const jobId = state[prefix].jobId;
  if (!jobId) return;
  if (state[prefix].status === 'running') {
    const action = prefix === 'tr' ? 'translation' : 'audiobook generation';
    toast(`⏳ Please wait until this ${action} is completed before downloading.`, 'info');
    return;
  }
  if (prefix === 'tr') {
    if (overrideFmt) chooseResultFormat(overrideFmt);  // the main button then names and fetches this format too
    const fmt = overrideFmt || document.getElementById('tr-output-format')?.value || 'txt';
    const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
    saveFile(`${API}/download/${jobId}?format=${fmt}&layout=${layout}`);
  } else {
    saveFile(`${API}/download/${jobId}?format=${overrideFmt || 'mp3'}`); // not "latest output": that may be a PDF
  }
}

// The bilingual edition (original and translation, paragraph by paragraph) in the chosen format: PDF, DOCX or EPUB
function downloadBilingual() {
  const jobId = state.tr.jobId;
  if (!jobId) return;
  if (state.tr.status === 'running') {
    toast('⏳ Please wait until this translation is completed before downloading.', 'info');
    return;
  }
  const chosen = (document.getElementById('tr-output-format')?.value || 'pdf').toLowerCase();
  const fmt = ['pdf', 'docx', 'epub'].includes(chosen) ? chosen : 'pdf';
  saveFile(`${API}/download/${encodeURIComponent(jobId)}/bilingual?format=${fmt}`);
}

function downloadOutputM4b() {
  if (!m4bAvailable) {
    toast('Η εξαγωγή M4B χρειάζεται το FFmpeg στον υπολογιστή του BookApp (pip install -r requirements.txt). Το MP3 είναι διαθέσιμο.', 'error');
    return;
  }
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

async function loadAudioChapters(jobId) {
  const wrap = document.getElementById('ab-chapter-wrap');
  const select = document.getElementById('ab-chapter-select');
  if (!wrap || !select) return;
  wrap.style.display = 'none';
  try {
    const res = await fetch(`${API}/jobs/${jobId}/chapters`);
    if (!res.ok) return;
    const chapters = (await res.json()).chapters || [];
    if (state.ab.jobId !== jobId || !chapters.length) return;
    select.innerHTML = chapters
      .map((c) => `<option value="${Number(c.start_seconds) || 0}">${escHtml(c.title)}</option>`).join('');
    wrap.style.display = '';
  } catch (_) {}
}

// ── Reading along: the sentence being narrated is lit and followed; a click on a sentence plays from there ──
const _readAlong = { jobId: null, segments: [], rendered: false, current: -1, bound: false };

async function loadReadAlong(jobId) {
  const btn = document.getElementById('ab-readalong-btn');
  const panel = document.getElementById('ab-readalong');
  Object.assign(_readAlong, { jobId, segments: [], rendered: false, current: -1 });
  if (btn) btn.style.display = 'none';
  if (panel) panel.style.display = 'none';
  try {
    const res = await fetch(`${API}/jobs/${jobId}/read-along`);
    if (!res.ok) return;
    const segments = (await res.json()).segments || [];
    if (_readAlong.jobId !== jobId || !segments.length) return;
    _readAlong.segments = segments;
    if (btn) {
      btn.style.display = '';
      btn.setAttribute('aria-expanded', 'false');
    }
    bindReadAlong();
  } catch (_) {}
}

function bindReadAlong() {
  if (_readAlong.bound) return;
  const audio = document.getElementById('ab-audio-element');
  const text = document.getElementById('ab-readalong-text');
  if (!audio || !text) return;
  audio.addEventListener('timeupdate', () => readAlongAt(audio.currentTime * 1000));
  audio.addEventListener('seeked', () => readAlongAt(audio.currentTime * 1000, true));
  text.addEventListener('click', (e) => {
    const span = e.target.closest ? e.target.closest('[data-i]') : null;
    if (!span) return;
    const seg = _readAlong.segments[Number(span.dataset.i)];
    if (!seg) return;
    audio.currentTime = seg.s / 1000;
    if (audio.paused && typeof audio.play === 'function') audio.play().catch(() => {});
  });
  _readAlong.bound = true;
}

function renderReadAlong() {
  const box = document.getElementById('ab-readalong-text');
  if (!box) return;
  let html = '';
  let open = false;
  _readAlong.segments.forEach((seg, i) => {
    if (seg.p || !open) {
      html += `${open ? '</p>' : ''}<p>`;
      open = true;
    }
    html += `<span class="ra-s" data-i="${i}">${escHtml(seg.t)}</span> `;
  });
  box.innerHTML = html + (open ? '</p>' : '');
  _readAlong.rendered = true;
  _readAlong.current = -1;
}

function toggleReadAlong() {
  const panel = document.getElementById('ab-readalong');
  const btn = document.getElementById('ab-readalong-btn');
  if (!panel) return;
  const show = panel.style.display === 'none';
  if (show && !_readAlong.rendered) renderReadAlong();
  panel.style.display = show ? '' : 'none';
  if (btn) btn.setAttribute('aria-expanded', String(show));
  if (show) {
    const audio = document.getElementById('ab-audio-element');
    readAlongAt((audio?.currentTime || 0) * 1000, true);
  }
}

// The sentence playing at `ms` (binary search over the start times)
function readAlongIndex(ms) {
  const segs = _readAlong.segments;
  let lo = 0;
  let hi = segs.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segs[mid].s <= ms) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}

function readAlongAt(ms, jump = false) {
  if (!_readAlong.rendered) return;
  const i = readAlongIndex(ms);
  if (i === _readAlong.current) return;
  const box = document.getElementById('ab-readalong-text');
  if (!box) return;
  const prev = box.querySelector?.(`[data-i="${_readAlong.current}"]`);
  if (prev) prev.classList.remove('ra-current');
  _readAlong.current = i;
  const span = i >= 0 ? box.querySelector?.(`[data-i="${i}"]`) : null;
  if (!span) return;
  span.classList.add('ra-current');
  const follow = document.getElementById('ab-readalong-follow');
  if (follow && !follow.checked) return;
  // keep the sentence in the middle of the panel (the page itself does not move)
  const target = span.offsetTop - box.clientHeight / 2 + span.offsetHeight / 2;  // the box is the span's offsetParent
  if (typeof box.scrollTo === 'function') box.scrollTo({ top: Math.max(0, target), behavior: jump ? 'auto' : 'smooth' });
  else box.scrollTop = Math.max(0, target);
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
function historyScope() {
  // User accounts (auth.js): an administrator chooses whose jobs to see; everyone else always sees their own
  return (typeof authState !== 'undefined' && authState.historyScope) ? authState.historyScope : 'mine';
}

async function refreshHistory() {
  try {
    const res = await fetch(`${API}/jobs?scope=${encodeURIComponent(historyScope())}`);
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

  // No filtering by file name here: "Bookkeeping.pdf" or "test_results.docx" are ordinary documents.
  const displayJobs = (jobs || []).filter(j => j.file_name || j.job_id);

  if (!displayJobs || displayJobs.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted); font-size:0.9rem;">No jobs yet. Upload a document to get started.</p>';
    if (clearBtn) clearBtn.style.display = 'none';
    return;
  }

  if (clearBtn) clearBtn.style.display = 'inline-flex';

  const modeIcon = { translate: '🌐', audiobook: '🎧', '': '📄' };
  const me = (typeof authState !== 'undefined' && authState.user) ? authState.user : null;
  const ownerTag = (j) => (me && me.role === 'admin' && j.owner && j.owner !== me.id && j.owner_name)
    ? ` · 👤 ${escHtml(j.owner_name)}` : '';
  const statusIcon = { done: '✅', running: '⏳', error: '❌', idle: '🔵' };

  grid.innerHTML = displayJobs.map(j => `
    <div class="history-item" data-job-id="${escHtml(j.job_id)}" data-mode="${escHtml(j.mode || '')}" data-file-name="${escHtml(j.file_name || '')}" onclick="openHistoryJob(this.dataset.jobId, this.dataset.mode, this.dataset.fileName)">
      <span class="history-icon">${modeIcon[j.mode] || '📄'}</span>
      <div class="history-info">
        <div class="history-name" translate="no">${escHtml(j.file_name)}</div>
        <div class="history-meta">
          ${j.mode ? escHtml(j.mode.charAt(0).toUpperCase() + j.mode.slice(1)) : 'Uploaded'} ·
          ${statusIcon[j.status] || ''} ${escHtml(j.status)}
          ${j.progress > 0 && j.status !== 'done' ? `· ${Number(j.progress) || 0}%` : ''}${ownerTag(j)}
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
  const scope = historyScope();
  const question = scope === 'all'
    ? 'Διαγραφή ΟΛΩΝ των εργασιών ΟΛΩΝ των χρηστών και των προσωρινών αρχείων; (Are you sure?)'
    : 'Are you sure you want to delete all session history and temporary files?';
  if (doConfirm && !doConfirm(question)) {
    return;
  }
  try {
    const res = await fetch(`${API}/jobs?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' });
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

// A Session History click loads the job into the tab the user is looking at. Book Insights keeps
// its own document slot; Smart Resume calls loadHistoryJob directly because it must translate/narrate.
function openHistoryJob(jobId, mode, fileName) {
  const isActive = (id) => Boolean(document.getElementById(id)?.classList.contains('active'));
  if (isActive('tab-insights') && typeof loadHistoryJobIntoInsights === 'function') {
    return loadHistoryJobIntoInsights(jobId, fileName);
  }
  // A translated book narrated later is an "audiobook" job: from the Translation tab it still opens there
  const tab = isActive('tab-audiobook') ? 'audiobook' : (isActive('tab-translate') ? 'translate' : null);
  return loadHistoryJob(jobId, mode, tab);
}

// `tab`: the tab to load into (a History click: the one in view); without it, the job's own mode decides
async function loadHistoryJob(jobId, mode, tab = null) {
  const onAudiobookTab = document.getElementById('tab-audiobook')?.classList.contains('active');
  const targetTab = tab || ((mode === 'audiobook' || mode === 'translate') ? mode : (onAudiobookTab ? 'audiobook' : 'translate'));
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
      // A scanned PDF: read as a book or translated as a comic; a sample that stopped resumes as that sample
      showScanChoice(data.scanned ? (data.read_scanned_text && !isComic ? 'book' : 'comic') : '', false);
      state.tr.estimatedPages = Number(data.total_pages || 0);
      state.tr.sampleRun = data.status !== 'done' && Array.isArray(data.sample_range) ? data.sample_range : null;
      updateSampleRow(true);

      // Restore original output format (pdf / epub / docx / txt / cbz / cbr): an audiobook's MP3 is not the translation's
      if (data.output_format && !['mp3', 'm4b'].includes(data.output_format.toLowerCase())) {
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

    if (prefix === 'tr') {
      const mq = document.getElementById('tr-max-quality');
      if (mq && currentAppMode === 'advanced') {
        mq.checked = Boolean(data.max_quality);
        onMaxQualityToggle();
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
      restoreAudiobookOptions(data.audiobook_options);
    }

    if (data.status === 'running') {
      document.getElementById(`${prefix}-progress-card`).style.display = 'block';
      setActionButtonsEnabled(prefix, false);
      state[prefix].status = 'running';
      setStatusBadge(prefix, 'running');
      updateProgress(prefix, data);
      connectSSE(prefix, jobId);
    } else if (data.has_output && data.status === 'done'
               && ((prefix === 'tr' && data.has_translation !== false) || (prefix === 'ab' && mode === 'audiobook'))) {
      // done: its translation in the Translation tab, its audiobook in the Audiobook tab. A book only narrated,
      // loaded into the Translation tab, or a translation loaded into the Audiobook tab, is ready instead (below).
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
      state[prefix].status = data.status === 'done' ? 'idle' : (data.status || 'idle');  // nothing of it here yet
      state[prefix].quotaStopped = data.status === 'error' && isQuotaMessage(data.error);
      setActionButtonsEnabled(prefix, true);
      toast(`📄 Φορτώθηκε "${data.file_name || 'έγγραφο'}" — έτοιμο για μετάφραση/συνέχιση!`, 'info');
    }
    if (prefix === 'tr') {
      checkCoverImage(jobId);
      updateSampleRow();
      scheduleTranslationEstimate();
    }
    return true;
  } catch (e) {
    console.warn('Could not reload job:', e);
    return false;
  }
}

// A resumed audiobook must keep the voice, language and pacing it was started with
function restoreAudiobookOptions(o) {
  if (!o) return;
  const el = (id) => document.getElementById(id);
  const lang = el('ab-lang-select');
  if (lang && o.language) {
    lang.value = o.language;
    updateVoices();
  }
  const card = Array.from(document.querySelectorAll('.voice-card') || []).find((c) => c.dataset.voice === o.voice_name);
  if (card) selectVoice(o.voice_name, card);
  if (el('ab-use-translated')) el('ab-use-translated').checked = Boolean(o.use_translated);
  if (el('ab-ai-polish')) el('ab-ai-polish').checked = Boolean(o.ai_polish);
  if (el('ab-multi-voice')) {
    const voiceCount = Object.keys(state.voices?.[el('ab-lang-select')?.value] || {}).length;
    el('ab-multi-voice').checked = Boolean(o.dialogue_voice) && voiceCount > 1;
    toggleMultiVoiceSelect();
    if (o.dialogue_voice && el('ab-dialogue-voice-select')) el('ab-dialogue-voice-select').value = o.dialogue_voice;
  }
  const style = el('ab-narration-style');
  if (style?.options && o.narration_style) {
    const options = Array.from(style.options).filter((x) => x.value.split(':')[0] === o.narration_style);
    const match = options.find((x) => x.value.split(':')[1] === o.rate) || options[0];
    if (match) style.value = match.value;
  }
  const rate = parseInt(o.rate, 10), pitch = parseInt(o.pitch, 10);
  if (!isNaN(rate) && el('ab-speed-slider')) {
    el('ab-speed-slider').value = rate;
    onSpeedSliderInput(rate);
  }
  if (!isNaN(pitch) && el('ab-pitch-slider')) {
    el('ab-pitch-slider').value = pitch;
    onPitchSliderInput(pitch);
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
    text = text.replaceAll(findVal, () => replVal);
    textarea.value = text;
    if (count > 0) markEditorDirty();
    updateEditorStats();
    toast(`Replaced ${count} occurrences.`, 'success');
  } else {
    if (text.includes(findVal)) {
      textarea.value = text.replace(findVal, () => replVal);
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

    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to save corrections'));
    const saved = await res.json().catch(() => ({}));
    clearEditorDirty();
    if (saved?.artwork_unchanged) {
      toast('💾 Αποθηκεύτηκε μόνο το κείμενο: στα Graphic Novels οι εικόνες και τα μπαλόνια δεν αλλάζουν από τον Editor.', 'info');
    } else {
      toast('✅ Corrections saved and export files updated!', 'success');
    }

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
    _smartResumeJob = null;
    banner.style.display = 'none';
    return;
  }

  // Find most recent job that was interrupted or has uncompleted checkpoint
  const candidate = jobs.find(j => {
    if (!j.job_id || !j.resumable) return false;
    if (state.tr.jobId === j.job_id && state.tr.status === 'running') return false;
    if (state.ab.jobId === j.job_id && state.ab.status === 'running') return false;
    const dismissed = sessionStorage.getItem(`dismiss_resume_${j.job_id}`);
    if (dismissed) return false;
    return true;
  });

  _smartResumeJob = candidate || null;
  if (candidate) {
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
  sessionStorage.removeItem?.(`dismiss_resume_${job.job_id}`); // resumed, not dismissed: offer it again if interrupted again
  const loaded = await loadHistoryJob(job.job_id, job.mode || 'translate');
  if (!loaded) {
    toast('Η εργασία δεν μπόρεσε να φορτωθεί για συνέχιση.', 'error');
    return;
  }
  toast('▶️ Συνέχιση εργασίας από το αποθηκευμένο checkpoint...', 'info');
  if ((job.mode || 'translate') === 'translate') {
    await startTranslation({ keepSavedFormat: true, resume: true });  // a stopped sample resumes as that sample
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

// The key slots of the Gemini pool, in order (slots 5-8 sit in a fold-out section)
const GEMINI_SLOT_IDS = ['gemini-api-key', ...Array.from({ length: 7 }, (_, i) => `gemini-api-key-${i + 2}`)];

function toggleApiKeyVisibility() {
  const slotIds = GEMINI_SLOT_IDS;
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

// A reset time in the viewer's own clock (the server's clock may be UTC inside Docker)
function localClock(timestamp) {
  try {
    return new Date(Number(timestamp) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (_) {
    return '';
  }
}

// The keys window says what waits for Gemini and until when: the daily limit on every key, models that used up
// their daily allowance on some keys, and the viewer's jobs waiting for the renewal.
function renderGeminiWaitStatus(q) {
  const box = document.getElementById('ai-polish-quota-warning-banner');
  const title = document.getElementById('ai-polish-quota-warning-title');
  const body = document.getElementById('ai-polish-quota-warning-text');
  if (!box || !body) return;
  const pool = (q && q.pool) || {};
  const totalKeys = pool.total_keys || 0;
  const models = pool.cooling_models || [];
  const jobs = (q && q.waiting_jobs) || [];
  const left = (sec) => formatMinutesEl(Math.max(1, Math.ceil(Number(sec || 0) / 60)));
  const lines = [];
  if (q && q.exhausted) {
    lines.push(`Εξαντλήθηκε το ημερήσιο όριο σε όλα τα κλειδιά. Έτοιμο ξανά στις ${localClock(q.reset_timestamp)} (σε ${left(q.remaining_seconds)}).`);
  }
  for (const m of models) {
    lines.push(`${m.model}: όριο ημέρας σε ${m.keys} από ${totalKeys} κλειδιά — ξανά στις ${localClock(m.reset_timestamp)} (σε ${left(m.remaining_sec)}).`);
  }
  const waiting = (q && q.exhausted) || jobs.length > 0;
  if (jobs.length) {
    lines.push(`Περιμένουν την ανανέωση: ${jobs.map((j) => `«${j.file_name || 'έγγραφο'}»`).join(', ')}.`);
  }
  if (!lines.length) {
    box.style.display = 'none';
    return;
  }
  lines.push(waiting
    ? 'Ένα κλειδί από άλλον λογαριασμό Google συνεχίζει αμέσως την εργασία.'
    : 'Η εφαρμογή συνεχίζει με τα άλλα μοντέλα και κλειδιά όσο υπάρχει διαθέσιμο όριο.');
  if (title) title.textContent = waiting ? '⏳ Αναμονή για ανανέωση του ορίου Gemini' : 'ℹ️ Μοντέλα Gemini στο όριό τους';
  body.innerHTML = lines.map((line) => `<div>${escHtml(line)}</div>`).join('');
  box.style.display = 'block';
}

let _geminiWaitTimer = null;

async function refreshGeminiWaitStatus() {
  try {
    const res = await fetch(`${API}/gemini/status`);
    if (!res.ok) return;
    const q = await res.json();
    renderGeminiWaitStatus(q);
    if (q.pool) renderGeminiPoolStatus(q.pool);
  } catch (_) {}
}

// While the keys window is open its status follows the server (a limit ends, a job starts waiting)
function watchGeminiWaitStatus(on) {
  if (_geminiWaitTimer) {
    clearInterval(_geminiWaitTimer);
    _geminiWaitTimer = null;
  }
  if (on) _geminiWaitTimer = setInterval(refreshGeminiWaitStatus, 5000);
}

function renderGeminiPoolStatus(poolData) {
  if (!poolData) return;
  const slots = poolData.slots || [];
  const total = poolData.total_keys || 0;
  const avail = poolData.available_keys || 0;
  const allExh = Boolean(poolData.all_exhausted);

  for (let i = 1; i <= GEMINI_SLOT_IDS.length; i++) {
    const badge = document.getElementById(`pool-slot-status-${i}`);
    if (!badge) continue;
    const slotInfo = slots[i - 1];
    badge.title = '';
    if (!slotInfo) {
      badge.textContent = '⚪ Κενό';
      badge.style.background = 'rgba(255,255,255,0.06)';
      badge.style.color = 'var(--text-muted)';
      continue;
    }
    const cooling = slotInfo.cooling_models || [];
    if (slotInfo.is_exhausted) {
      const at = slotInfo.reset_timestamp ? localClock(slotInfo.reset_timestamp) : 'σε αναμονή';
      badge.textContent = `⏳ Όριο (${at})`;
      badge.style.background = 'rgba(245,158,11,0.18)';
      badge.style.color = 'var(--amber)';
    } else if (cooling.length) {
      // the key works, but some of its models used up their daily allowance
      badge.textContent = `🟡 Ενεργό · ${cooling.length} μοντέλα στο όριο`;
      badge.title = cooling.join(', ');
      badge.style.background = 'rgba(245,158,11,0.14)';
      badge.style.color = 'var(--amber)';
    } else {
      // requests take the keys in turn: every usable key is in use, none waits on standby
      badge.textContent = '🟢 Ενεργό (Active)';
      badge.style.background = 'rgba(16,185,129,0.18)';
      badge.style.color = 'var(--emerald)';
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
      sumBadge.textContent = `🟢 ${avail}/${total} Κλειδιά Διαθέσιμα`;
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
  const savedKey = hasGeminiKey() ? (geminiKeyState.masked[0] || 'configured') : null;

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
      navBadge.title = `${avail}/${total} Gemini API Key(s) ενεργά`;
    }
  } else if (savedKey) {
    navBadge.style.background = 'rgba(16,185,129,0.15)';
    navBadge.style.color = 'var(--emerald)';
    navBadge.style.border = '1px solid rgba(16,185,129,0.4)';
    navBadge.textContent = '✓ Active';
    navBadge.title = 'Gemini API Key είναι αποθηκευμένο και ενεργό';
  } else {
    navBadge.style.background = 'rgba(59,130,246,0.15)';
    navBadge.style.color = 'var(--blue, #3b82f6)';
    navBadge.style.border = '1px solid rgba(59,130,246,0.3)';
    navBadge.textContent = '🆓 Free Mode';
    navBadge.title = 'Δωρεάν μοντέλα ενεργά ως προεπιλογή (δωρεάν μετάφραση με όρια & Edge-TTS — χωρίς API key)';
  }
}

let _currentAiModalMode = 'polish';

async function openApiKeyModal() {
  if (typeof authIsRestrictedUser === 'function' && authIsRestrictedUser()) {
    toast('🔑 Τα Gemini API keys και οι ρυθμίσεις τα διαχειρίζεται ένας διαχειριστής.', 'info');
    return null;
  }
  return openAiPolishModal('settings');
}

async function openAiPolishModal(mode = 'polish') {
  _currentAiModalMode = (mode === 'settings' || mode === 'keys') ? 'settings' : 'polish';
  const modal = document.getElementById('ai-polish-modal');
  modal.style.display = 'flex';

  const modalTitle = document.getElementById('ai-polish-modal-title');
  const modalDesc = document.getElementById('ai-polish-modal-desc');
  const toneGroup = document.getElementById('ai-polish-tone-group');
  const bilingualGroup = document.getElementById('ai-polish-bilingual-group');
  const btnRunPolish = document.getElementById('btn-run-polish');
  const btnCancelPolish = document.getElementById('btn-cancel-polish');

  const pairingSection = document.getElementById('pairing-section');
  if (pairingSection) pairingSection.style.display = 'none';
  if (_currentAiModalMode === 'settings') {
    if (typeof loadPairingPanel === 'function') loadPairingPanel();
    loadGeminiUsageToday();
    if (modalTitle) modalTitle.innerHTML = '🔑 Gemini Multi-Key Pool &amp; Ρυθμίσεις API';
    if (modalDesc) modalDesc.innerHTML = 'Διαχειριστείτε τα δωρεάν Google Gemini API Keys (έως 8 κλειδιά) για αυτόματη εναλλαγή (auto-failover) και αδιάλειπτη ροή χωρίς διακοπές:';
    if (toneGroup) toneGroup.style.display = 'none';
    if (bilingualGroup) bilingualGroup.style.display = 'none';
    if (btnRunPolish) btnRunPolish.style.display = 'none';
    if (btnCancelPolish) {
      btnCancelPolish.textContent = '✓ Έτοιμο / Κλείσιμο';
      btnCancelPolish.className = 'btn btn-primary';
    }
  } else {
    if (modalTitle) modalTitle.innerHTML = '✨ AI Translation Polish &amp; Proofreading';
    if (modalDesc) modalDesc.innerHTML = 'Refine the Greek translation into flawless, natural language using Google Gemini AI. Select your preferred style:';
    if (toneGroup) toneGroup.style.display = '';
    if (bilingualGroup) bilingualGroup.style.display = '';
    if (btnRunPolish) {
      btnRunPolish.style.display = '';
      btnRunPolish.disabled = _polishRunning;
    }
    if (btnCancelPolish) {
      btnCancelPolish.textContent = _polishRunning ? 'Minimize (Run in Background)' : 'Cancel';
      btnCancelPolish.className = 'btn btn-secondary';
    }
  }

  // Fetch latest settings & pool state from server (keys arrive masked; they never leave the server in clear)
  const sData = await refreshGeminiKeyState();
  if (sData && sData.pool) renderGeminiPoolStatus(sData.pool);
  const poolKeys = [...geminiKeyState.masked];

  const slotIds = GEMINI_SLOT_IDS;
  slotIds.forEach((id, idx) => {
    const input = document.getElementById(id);
    if (input) {
      input.value = poolKeys[idx] || '';
    }
  });
  const moreSlots = document.getElementById('gemini-more-slots');
  if (moreSlots && poolKeys.length > 4) moreSlots.open = true;

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
  if (cancelBtn && _currentAiModalMode === 'polish') cancelBtn.textContent = _polishRunning ? 'Minimize (Run in Background)' : 'Cancel';

  // What waits for Gemini and until when; kept current while the keys window is open
  await refreshGeminiWaitStatus();
  watchGeminiWaitStatus(_currentAiModalMode === 'settings');
}

function closeAiPolishModal() {
  document.getElementById('ai-polish-modal').style.display = 'none';
  _currentAiModalMode = 'polish';
  watchGeminiWaitStatus(false);
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
      homeText.innerHTML = `Εξαντλήθηκε το όριο (Free Tier). <strong style="color:var(--amber)">Έτοιμο ξανά στις ${clockStr}</strong> (Αντίστροφη μέτρηση: <span style="font-family:monospace; font-weight:700; font-size:1.05rem; color:var(--amber)">${mmss}</span>). Μπορείτε να αλλάξετε API Key στις Ρυθμίσεις για άμεση συνέχιση.`;
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

  // 3b. Audiobook banner: Gemini matters there only for the AI script polish
  const abQuotaBanner = document.getElementById('ab-quota-warning-banner');
  const abUsesGemini = Boolean(document.getElementById('ab-ai-polish')?.checked || state.ab.quotaStopped);
  if (abQuotaBanner) {
    abQuotaBanner.style.display = abUsesGemini ? 'block' : 'none';
    abQuotaBanner.style.background = 'rgba(245,158,11,0.14)';
    abQuotaBanner.style.borderColor = 'rgba(245,158,11,0.6)';
    const abQuotaText = document.getElementById('ab-quota-warning-text');
    if (abQuotaText && abUsesGemini) {
      abQuotaText.innerHTML = `Εξαντλήθηκε το όριο Gemini. <strong style="color:var(--amber)">Έτοιμο ξανά στις ${clockStr}</strong> (Αντίστροφη μέτρηση: <span style="font-family:monospace; font-weight:700; font-size:1.05rem; color:var(--amber)">${mmss}</span>). Η πρόοδος διατηρήθηκε.`;
    }
  }

  // 4. Batch queue banner
  const qBanner = document.getElementById('queue-quota-warning-banner');
  const qText = document.getElementById('queue-quota-warning-text');
  if (qBanner) {
    qBanner.style.display = 'block';
    if (qText) {
      qText.innerHTML = `Εξαντλήθηκε το όριο Gemini (Free Tier). <strong>Έτοιμο ξανά στις ${clockStr}</strong> (Απομένουν: <span style="font-family:monospace; font-weight:700">${mmss}</span>). ${queueQuotaBehaviorText()}`;
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

  const abQuotaBanner = document.getElementById('ab-quota-warning-banner');
  const abQuotaText = document.getElementById('ab-quota-warning-text');
  if (abQuotaBanner && abQuotaText) {
    abQuotaBanner.style.background = 'rgba(16,185,129,0.12)';
    abQuotaBanner.style.borderColor = 'rgba(16,185,129,0.5)';
    abQuotaText.innerHTML = '<strong>✅ Το όριο ανανεώθηκε!</strong> Μπορείτε να συνεχίσετε το Audiobook.';
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
  if (state.tr.jobId && state.tr.status === 'error' && state.tr.quotaStopped) {
    console.log(`Auto-resuming translation job ${state.tr.jobId} after quota restoration...`);
    setTimeout(() => {
      resumeTranslation('tr');
    }, 2000);
  } else if (_smartResumeJob?.quota_stopped) {
    console.log(`Auto-resuming checkpoint job ${_smartResumeJob.job_id} after quota restoration...`);
    setTimeout(() => {
      executeSmartResume();
    }, 2000);
  } else if (_batchQueueState.total_count > 0 && _batchQueueState.paused_for_quota) {
    // never a queue the user paused, or one restored paused after a restart
    console.log('Auto-resuming batch queue after quota restoration...');
    setTimeout(() => {
      startBatchQueue({ keepItemSettings: true });
    }, 2000);
  } else if (state.ab.jobId && state.ab.status === 'error' && state.ab.quotaStopped) {
    console.log(`Auto-resuming audiobook job ${state.ab.jobId} after quota restoration...`);
    setTimeout(() => {
      resumeTranslation('ab');
    }, 2000);
  }
}

async function saveGeminiKeyOnly() {
  const slotIds = GEMINI_SLOT_IDS;
  const keys = [];
  const seen = new Set();
  let hasDuplicate = false;

  for (let idx = 0; idx < slotIds.length; idx++) {
    const id = slotIds[idx];
    const input = document.getElementById(id);
    const val = (input ? input.value : '').trim();
    if (val && isMaskedKeyValue(val)) {
      keys.push(val);   // unchanged slot: the server maps the masked form back to the stored key
      continue;
    }
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

  try {
    const res = await fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_keys: keys }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.pool) renderGeminiPoolStatus(data.pool);
    }
    // Show the saved keys in masked form only
    const hadKey = hasGeminiKey();
    await refreshGeminiKeyState();
    if (!hadKey && hasGeminiKey()) initQuotaBehaviorSelectors();  // first key: back to the Wait for Reset default
    slotIds.forEach((id, idx) => {
      const input = document.getElementById(id);
      if (input) input.value = geminiKeyState.masked[idx] || '';
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
  const abQuotaBanner = document.getElementById('ab-quota-warning-banner');
  if (abQuotaBanner) abQuotaBanner.style.display = 'none';
  const qBanner = document.getElementById('queue-quota-warning-banner');
  if (qBanner) qBanner.style.display = 'none';
  const polishTag = document.getElementById('tr-ai-polish-quota-tag');
  if (polishTag) polishTag.style.display = 'none';

  await checkGlobalGeminiQuotaStatus();

  // If there is an active job or queue waiting on quota, automatically resume it now!
  if (state.tr.jobId && state.tr.status === 'error' && state.tr.quotaStopped) {
    closeAiPolishModal();
    toast(`✅ Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά! Αυτόματη συνέχιση μετάφρασης...`, 'success');
    setTimeout(() => {
      resumeTranslation('tr');
    }, 400);
    return;
  }

  if (_smartResumeJob?.quota_stopped) {
    closeAiPolishModal();
    toast(`✅ Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά! Αυτόματη συνέχιση από checkpoint...`, 'success');
    setTimeout(() => {
      executeSmartResume();
    }, 400);
    return;
  }

  if (_batchQueueState.total_count > 0 && _batchQueueState.paused_for_quota) {
    closeAiPolishModal();
    toast(`✅ Αποθηκεύτηκαν επιτυχώς ${keys.length} κλειδιά! Αυτόματη συνέχιση της ουράς...`, 'success');
    setTimeout(() => {
      startBatchQueue({ keepItemSettings: true });
    }, 400);
    return;
  }

  if (state.ab.jobId && state.ab.status === 'error' && state.ab.quotaStopped) {
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
  try { localStorage.removeItem('gemini_api_key'); localStorage.removeItem('gemini_api_keys'); } catch (_) {}
  geminiKeyState.hasKey = false;
  geminiKeyState.masked = [];
  const slotIds = GEMINI_SLOT_IDS;
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
  // Without a key only the free models can run (Wait for Reset returns as the default when a key is added)
  ['tr', 'ab'].forEach((prefix) => {
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
      const abQuotaBanner = document.getElementById('ab-quota-warning-banner');
      if (abQuotaBanner) abQuotaBanner.style.display = 'none';
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
  openAiPolishModal('polish');
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
  const typedKey = apiKeyInput ? apiKeyInput.value.trim() : '';
  const apiKey = (typedKey && !isMaskedKeyValue(typedKey)) ? typedKey : '';
  if (!apiKey && hasGeminiKey()) {
    // A key is already stored on the server — nothing to send.
  } else if (apiKey) {
    const isValidFormat = (apiKey.startsWith('AQ.') && apiKey.length >= 25) ||
                          (apiKey.startsWith('AIza') && apiKey.length >= 35) ||
                          (apiKey.length >= 25);
    if (!isValidFormat) {
      toast('Invalid API Key format. Google Gemini keys start with "AQ." or "AIzaSy...". Please paste a valid key.', 'error');
      return;
    }
    // Persist on the server (the browser does not keep keys)
    fetch(`${API}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gemini_api_key: apiKey }),
    }).then(() => refreshGeminiKeyState()).catch(() => {});
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
            stepEl.innerHTML = `<span class="status-dot"></span> ${escHtml(data.step || 'Refining text...')}`;
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

// Help: a short guide and the frequently asked questions (index.html holds both languages)
function openHelpModal() {
  const modal = document.getElementById('help-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  const body = modal.querySelector('.modal-body');
  if (body) body.scrollTop = 0;
}

function closeHelpModal() {
  const modal = document.getElementById('help-modal');
  if (modal) modal.style.display = 'none';
}

// ── 📲 Devices: the e-reader catalogue (OPDS) ──
let _opdsLinkExists = false;

function setDevicesStatus(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

async function openDevicesModal() {
  const modal = document.getElementById('devices-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  setDevicesStatus('opds-status', '');
  const linkBox = document.getElementById('opds-link-box');
  if (linkBox) linkBox.style.display = 'none';
  const host = (window.location && window.location.hostname) || '';
  const localNote = document.getElementById('opds-localhost-note');
  if (localNote) localNote.style.display = ['localhost', '127.0.0.1', '::1', '[::1]'].includes(host) ? '' : 'none';
  try {
    const res = await fetch(`${API}/connections`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load the devices settings'));
    const data = await res.json();
    showOpdsState(data.opds || {});
  } catch (e) {
    setDevicesStatus('opds-status', `❌ ${e.message}`);
  }
}

function closeDevicesModal() {
  const modal = document.getElementById('devices-modal');
  if (modal) modal.style.display = 'none';
}

function showOpdsState(opds) {
  _opdsLinkExists = Boolean(opds.exists);
  const remove = document.getElementById('opds-remove-btn');
  if (remove) remove.style.display = _opdsLinkExists ? '' : 'none';
  if (_opdsLinkExists && opds.created) {
    const day = new Date(opds.created * 1000).toLocaleDateString('el-GR');
    setDevicesStatus('opds-status', `Υπάρχει σύνδεσμος από ${day}. Για να τον ξαναδείτε, φτιάξτε νέο.`);
  } else {
    setDevicesStatus('opds-status', 'Δεν υπάρχει σύνδεσμος ακόμη.');
  }
}

async function newOpdsLink() {
  if (_opdsLinkExists && !window.confirm('Ο τωρινός σύνδεσμος θα σταματήσει να λειτουργεί. Να φτιαχτεί νέος;')) return;
  try {
    const res = await fetch(`${API}/connections/opds`, { method: 'POST' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to make a link'));
    const data = await res.json();
    const input = document.getElementById('opds-link');
    input.value = `${window.location.origin}${data.path}`;
    document.getElementById('opds-link-box').style.display = '';
    input.focus?.();
    input.select?.();
    _opdsLinkExists = true;
    const remove = document.getElementById('opds-remove-btn');
    if (remove) remove.style.display = '';
    setDevicesStatus('opds-status', '✅ Νέος σύνδεσμος. Αντιγράψτε τον τώρα: δεν θα ξαναφανεί.');
  } catch (e) {
    setDevicesStatus('opds-status', `❌ ${e.message}`);
  }
}

async function copyOpdsLink() {
  const input = document.getElementById('opds-link');
  if (!input || !input.value) return;
  try {
    await navigator.clipboard.writeText(input.value);
  } catch (_) {  // plain http on a LAN address: no clipboard API
    input.select();
    document.execCommand('copy');
  }
  toast('📋 Ο σύνδεσμος αντιγράφηκε.', 'success');
}

async function removeOpdsLink() {
  if (!window.confirm('Να καταργηθεί ο σύνδεσμος; Οι εφαρμογές ανάγνωσης δεν θα βλέπουν πια τα βιβλία σας.')) return;
  try {
    const res = await fetch(`${API}/connections/opds`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to remove the link'));
    document.getElementById('opds-link-box').style.display = 'none';
    showOpdsState({ exists: false });
  } catch (e) {
    setDevicesStatus('opds-status', `❌ ${e.message}`);
  }
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

// ── Theme (Dark / Light) ──────────────────────────────────
// theme.js picks it: light by day, dark at night; the button switches until the next sunrise or sunset.
function initTheme() {
  if (typeof BookAppTheme === 'undefined') return;
  BookAppTheme.onChange(updateThemeButton);
  updateThemeButton(BookAppTheme.apply());
}

function toggleTheme() {
  if (typeof BookAppTheme === 'undefined') return;
  updateThemeButton(BookAppTheme.toggle());
}

function updateThemeButton(theme) {
  const icon = document.getElementById('theme-icon');
  const label = document.getElementById('theme-label');
  if (icon && label) {
    icon.textContent = theme === 'light' ? '☀️' : '🌙';
    label.textContent = theme === 'light' ? 'Light' : 'Dark';
  }
  const btn = document.getElementById('theme-toggle-btn');
  if (btn && typeof BookAppTheme !== 'undefined') {
    btn.title = BookAppTheme.isManual()
      ? `Δική σας επιλογή έως τις ${localClock(BookAppTheme.nextChange() / 1000)}, μετά αυτόματα`
      : 'Αυτόματο θέμα: φωτεινό τη μέρα, σκοτεινό τη νύχτα · πατήστε για αλλαγή';
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
let _formatChosenByUser = false;
let _queueSeen = false;
let _keepQueuedSettings = false; // a queue found on page load keeps its settings until the user edits the form
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
  const apiKey = getClientApiKey();
  const hasKey = hasGeminiKey();
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
    const waiting = q.items.filter((it) => it.status === 'waiting_quota').length;
    trStartBtn.textContent = waiting
      ? `⏳ Waiting for Gemini quota (${waiting})`
      : (q.done_count === q.total_count ? '✅ Batch Complete' : '⚠️ Batch finished') + ` (${q.done_count}/${q.total_count})`;
  }
}

// The line and bar above the queue while several files upload: which file, its percent, and the batch's bytes overall
function showBatchUploadProgress(index, count, file, fileLoaded, batchLoaded, batchTotal, sent) {
  const box = document.getElementById('tr-batch-upload');
  const text = document.getElementById('tr-batch-upload-text');
  const fill = document.getElementById('tr-batch-upload-fill');
  if (!box || !text || !fill) return;
  box.style.display = '';
  const filePct = sent ? 100 : Math.min(100, Math.round((fileLoaded / Math.max(file.size, 1)) * 100));
  const overall = Math.min(100, Math.round((batchLoaded / Math.max(batchTotal, 1)) * 100));
  text.textContent = sent
    ? `⏳ Αρχείο ${index}/${count}: "${file.name}" ανέβηκε· επεξεργασία… (σύνολο ${overall}%)`
    : `⬆️ Ανέβασμα ${index}/${count}: "${file.name}" ${filePct}% (σύνολο ${overall}%, ${_mb(batchLoaded)} / ${_mb(batchTotal)} MB)`;
  fill.style.width = `${overall}%`;
  if (sent) fill.classList.add('shimmer'); else fill.classList.remove('shimmer');
}

// After the uploads: the box goes away when all went up, or stays with the files that did not and why
function finishBatchUpload(uploaded, count, failed) {
  const box = document.getElementById('tr-batch-upload');
  const text = document.getElementById('tr-batch-upload-text');
  const fill = document.getElementById('tr-batch-upload-fill');
  if (!box || !text || !fill) return;
  fill.classList.remove('shimmer');
  if (!failed.length) {
    box.style.display = 'none';
    fill.style.width = '0%';
    return;
  }
  box.style.display = '';
  fill.style.width = `${Math.round((uploaded / Math.max(count, 1)) * 100)}%`;
  text.innerHTML = `⚠️ Ανέβηκαν ${uploaded} από ${count} αρχεία. Δεν ανέβηκαν:<br>`
    + failed.map(([name, reason]) => `• <strong>${escHtml(name)}</strong>: ${escHtml(reason)}`).join('<br>')
    + ` <button type="button" class="btn-sm btn-outline" style="margin-left:6px; padding:1px 8px"`
    + ` onclick="document.getElementById('tr-batch-upload').style.display='none'">✕</button>`;
}

async function enqueueMultipleFiles(files) {
  if (_isEnqueuing) {
    toast('Παρακαλώ περιμένετε να ολοκληρωθεί η προηγούμενη προσθήκη αρχείων...', 'info');
    return;
  }
  _isEnqueuing = true;
  try {
    const allowed = ['.pdf', '.docx', '.epub', '.cbz', '.cbr', '.zip'];
  const cfg = _readCurrentTranslationSettings();
  const maxItems = _batchQueueState.max_items || MAX_BATCH_FILES;
  if (!_batchQueueState.total_count) _formatChosenByUser = false; // a new batch follows each file's own format

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
  const failedUploads = [];  // [name, reason]: listed under the queue when the uploads end, not only in toasts
  const uploadable = filesToUpload.filter((file) => {
    const ok = allowed.includes('.' + file.name.split('.').pop().toLowerCase());
    if (!ok) failedUploads.push([file.name, 'μη υποστηριζόμενο format']);
    return ok;
  });
  const totalBytes = uploadable.reduce((sum, f) => sum + f.size, 0);
  let doneBytes = 0;
  for (const [i, file] of uploadable.entries()) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    try {
      const upRes = await uploadWithProgress(file, (loaded, total, sent) =>
        showBatchUploadProgress(i + 1, uploadable.length, file, loaded, doneBytes + loaded, totalBytes, sent));
      if (!upRes.ok) {
        const reason = await parseApiError(upRes, upRes.statusText || `HTTP ${upRes.status}`);
        failedUploads.push([file.name, reason]);
        toast(`❌ Αποτυχία φόρτωσης "${file.name}": ${reason}`, 'error');
        continue;
      }
      const upData = await upRes.json();
      const isComic = Boolean(upData.is_comic) || ['.cbz', '.cbr', '.zip'].includes(ext);
      const isScanned = Boolean(upData.is_scanned);
      uploadedPayloads.push({ file, ext, upData, isComic, isScanned });
    } catch (err) {
      failedUploads.push([file.name, err.message]);
      toast(`❌ Σφάλμα φόρτωσης "${file.name}": ${err.message}`, 'error');
    } finally {
      doneBytes += file.size;
    }
  }
  finishBatchUpload(uploadedPayloads.length, filesToUpload.length, failedUploads);

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

      const detected = currentAppMode === 'basic' && langConfig[upData.detected_language] ? upData.detected_language : null;
      const addRes = await fetch(`${API}/queue/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: upData.job_id,
          source_lang: detected || cfg.srcLang,
          target_lang: detected ? (detected === 'greek' ? 'english' : 'greek') : cfg.tgtLang,
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
    adoptQueueSettings(q);
    renderBatchQueue(q);

    // a waiting queue continues on the server: keep watching it
    if (q.is_running || q.paused_for_quota) {
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

function restoreQueueForm(item) {
  if (langConfig[item.source_lang] && langConfig[item.target_lang]) setLangs(item.source_lang, item.target_lang);
  const layoutBtn = document.getElementById(`layout-${item.layout_mode}`);
  if (!item.is_comic && layoutBtn) selectLayout(item.layout_mode, layoutBtn);
  const fmtBtn = document.getElementById(`fmt-${item.output_format}`);
  if (fmtBtn && !fmtBtn.disabled) selectFormat(item.output_format, fmtBtn);
  const aiChk = document.getElementById('tr-ai-polish');
  if (aiChk) aiChk.checked = Boolean(item.ai_polish);
  for (const [name, value] of [['tr-reading-dir', item.reading_direction], ['tr-quota-behavior', item.quota_behavior]]) {
    const radio = document.querySelector(`input[name="${name}"][value="${value}"]`);
    if (radio) radio.checked = true;
  }
}

function adoptQueueSettings(q) {
  const pending = (q.items || []).filter((it) => it.status !== 'done' && it.status !== 'cancelled');
  if (!pending.length) _keepQueuedSettings = false;
  if (_queueSeen) return;
  _queueSeen = true;
  if (pending.length && !state.tr.jobId) {
    restoreQueueForm(pending[0]);
    _keepQueuedSettings = true;
  }
}

function watchTranslationSettings() {
  const controls = '#tr-format-selector button, .lang-swap-btn, [data-layout], #tr-ai-polish, input[name="tr-reading-dir"], input[name="tr-quota-behavior"]';
  // what changes the number of Gemini requests (the estimate waits a moment, until the click has taken effect)
  const estimated = '#tr-format-selector button, [data-layout], #tr-ai-polish, #tr-max-quality, .mode-toggle-btn';
  for (const type of ['click', 'change']) {
    document.addEventListener(type, (e) => {
      if (e.target.closest?.(controls)) _keepQueuedSettings = false;
      if (e.target.closest?.(estimated)) scheduleTranslationEstimate();
    }, true);
  }
}

function queueQuotaBehaviorText() {
  const items = _batchQueueState.items || [];
  const open = items.filter((it) => it.status !== 'done' && it.status !== 'cancelled');
  const pending = open.length ? open : items;
  const waiting = pending.filter((it) => (it.quota_behavior || 'wait') === 'wait').length;
  if (waiting === pending.length) return 'Η ουρά περιμένει και θα συνεχίσει αυτόματα με AI μόλις ανανεωθεί το όριο.';
  if (waiting === 0) return 'Η ουρά συνεχίζει αυτόματα χωρίς AI Polish.';
  return 'Τα έγγραφα σε «Αναμονή» περιμένουν την ανανέωση του ορίου· όσα έχουν Auto-Fallback συνεχίζουν χωρίς AI Polish.';
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
    // The reason is written under the switch, not only in the hover tooltip (touch screens have no hover)
    const autoNote = document.getElementById('queue-auto-start-note');
    if (autoNote) autoNote.style.display = isMixed ? '' : 'none';
  }

  const quotaBanner = document.getElementById('queue-quota-warning-banner');
  const quotaText = document.getElementById('queue-quota-warning-text');
  if (quotaBanner) {
    if (q.gemini_quota_exhausted) {
      quotaBanner.style.display = 'block';
      if (quotaText) {
        quotaText.textContent = q.gemini_quota_message || `Εξαντλήθηκε το ημερήσιο όριο του Gemini Free Tier. ${queueQuotaBehaviorText()}`;
      }
      if (!_seenQuotaWarning) {
        _seenQuotaWarning = true;
        checkGlobalGeminiQuotaStatus();
        toast(`⚠️ Εξαντλήθηκε το ημερήσιο όριο Gemini Free Tier. ${queueQuotaBehaviorText()}`, 'warning');
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
    // Everything from the server is escaped: queue items can be created by any client that reaches the API
    const fmtLabel = escHtml(String(it.output_format ?? '').toUpperCase());
    const statusClass = escHtml(it.status);
    const pct = Number(it.progress) || 0;
    const modeTag = it.is_comic
      ? `🎨 Comic (${escHtml(String(it.reading_direction || 'ltr').toUpperCase())})`
      : (it.layout_mode === 'literature' ? '📚 Literature' : '📄 Standard');
    const isWaitMode = (it.quota_behavior || 'wait') === 'wait';
    const aiTag = it.ai_polish
      ? (q.gemini_quota_exhausted
          ? (isWaitMode ? ' · ⏳ Αναμονή Gemini AI (100% ποιότητα)' : ' · ⚠️ Χωρίς AI Polish (Fallback)')
          : ' · ✨ AI Polish')
      : '';
    const dlLink = it.has_output
      ? `<a class="btn-sm btn-outline" href="${escHtml(`${API}/download/${encodeURIComponent(it.job_id)}?format=${encodeURIComponent(it.output_format)}&layout=${encodeURIComponent(it.layout_mode)}`)}" style="text-decoration:none; color:var(--emerald); border-color:rgba(16,185,129,0.4)">⬇️ ${fmtLabel}</a>`
      : '';
    const retryBtn = (it.status === 'error' || it.status === 'cancelled' || it.status === 'waiting_quota')
      ? `<button type="button" class="btn-sm btn-outline" data-job-id="${escHtml(it.job_id)}" onclick="retryQueueItem(this.dataset.jobId)" title="${it.status === 'waiting_quota' ? 'Άμεση δοκιμή εκ νέου' : 'Επανάληψη μετάφρασης'}" style="color:var(--amber); border-color:rgba(245,158,11,0.45)">${it.status === 'waiting_quota' ? '⚡ Retry Now' : '🔄 Retry'}</button>`
      : '';
    const progressBar = (it.status === 'running' || it.status === 'done')
      ? `<div class="queue-progress-track"><div class="queue-progress-fill" style="width:${it.status === 'done' ? 100 : pct}%"></div></div>`
      : '';
    const errLine = (it.error && it.status !== 'running' && it.status !== 'done')
      ? `<div style="font-size:0.75rem; color:var(--rose)">${escHtml(it.error)}</div>`
      : '';
    return `
      <div class="queue-item ${statusClass}">
        <div class="queue-item-top">
          <div class="queue-item-info">
            <span style="font-size:1.2rem">${it.is_comic ? '🎨' : '📄'}</span>
            <div style="min-width:0; flex:1">
              <div class="queue-item-name" translate="no" title="${escHtml(it.file_name)}">${escHtml(it.file_name)}</div>
              <div class="queue-item-meta">
                <span>${modeTag}${aiTag}</span>
                <span>→ ${fmtLabel}</span>
                <span>${escHtml(it.current_step || '')}</span>
              </div>
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:8px; flex-shrink:0">
            <span class="queue-badge ${statusClass}">${statusLabels[it.status] || statusClass}${it.status === 'running' ? ` ${pct}%` : ''}</span>
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

async function startBatchQueue({ keepItemSettings = false } = {}) {
  const cfg = _readCurrentTranslationSettings();
  // without a body every file keeps the settings it was queued with
  const keep = keepItemSettings || _keepQueuedSettings;
  try {
    const res = await fetch(`${API}/queue/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: keep ? undefined : JSON.stringify({
        // Basic Mode detects per file; the format follows each file unless the user picked one
        source_lang: currentAppMode === 'basic' ? null : cfg.srcLang,
        target_lang: currentAppMode === 'basic' ? null : cfg.tgtLang,
        output_format: (currentAppMode !== 'basic' && _formatChosenByUser) ? cfg.chosenFmt : null,
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
    toast(keep
      ? '▶️ Η Smart Batch Queue συνεχίζει με τις αποθηκευμένες ρυθμίσεις κάθε αρχείου.'
      : '▶️ Η Smart Batch Queue ξεκίνησε με τις επιλεγμένες ρυθμίσεις (σειριακή εκτέλεση).', 'info');
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
    const res = await fetch(`${API}/queue/${jobId}`, { method: 'DELETE' });
    const q = res.ok ? await res.json().catch(() => null) : null;
    if (q && await returnLoneQueuedFileToCard(q)) return;
    await refreshBatchQueue();
  } catch (_) {}
}

// One file left in a queue that hasn't started is a single document again: it goes back to the Upload Card, where it
// gets the style recommendation ("Εφαρμογή Προτεινόμενου"), the cover check and the single-file buttons.
async function returnLoneQueuedFileToCard(q) {
  const items = (q && q.items) || [];
  if (items.length !== 1 || q.is_running || state.tr.jobId) return false;
  const item = items[0];
  if (item.status !== 'queued') return false;
  const res = await fetch(`${API}/queue/${item.job_id}`, { method: 'DELETE' });
  if (!res.ok) return false;
  const emptied = await res.json().catch(() => null);

  let info = {};
  try {
    const sRes = await fetch(`${API}/status/${item.job_id}`);
    if (sRes.ok) info = await sRes.json();
  } catch (_) {}

  state.tr.jobId = item.job_id;  // set first: the emptied queue then leaves the Upload Card to this file
  state.tr.file = null;
  state.tr.estimatedPages = Number(info.total_pages || 0);
  _keepQueuedSettings = false;
  renderBatchQueue(emptied || { items: [] });

  const ext = (item.file_type || (item.file_name || '').split('.').pop() || '').toLowerCase();
  const pages = state.tr.estimatedPages > 0 ? `~${state.tr.estimatedPages} pages · ` : '';
  document.getElementById('tr-file-icon').textContent = FILE_ICONS[ext] || '📄';
  document.getElementById('tr-file-name').textContent = item.file_name || '';
  document.getElementById('tr-file-meta').textContent = `${pages}${ext.toUpperCase()} · Ready`;
  const selEl = document.getElementById('tr-selected-file');
  selEl.style.display = '';
  selEl.classList.add('visible');
  document.getElementById('tr-upload-zone').style.display = 'none';

  restoreQueueForm(item);
  setGraphicNovelLock(Boolean(item.is_comic), '', Boolean(item.is_scanned));
  showScanChoice(info.scanned ? (info.read_scanned_text && !item.is_comic ? 'book' : 'comic') : '', false);
  updateSampleRow(true);
  scheduleTranslationEstimate();
  const startBtn = document.getElementById('tr-start-btn');
  if (startBtn) {
    startBtn.disabled = false;
    startBtn.textContent = currentAppMode === 'basic' ? '✨ Μετάφραση Βιβλίου με AI (1-Click)' : '🌐 Start Translation';
  }
  if (!item.is_comic) {
    updateFormatAvailability(document.getElementById('tr-layout-mode')?.value || 'standard', ext);
    const directBtn = document.getElementById('tr-direct-polish-btn');
    if (directBtn) directBtn.disabled = false;
    checkCoverImage(item.job_id);
    detectDocumentGenre(item.job_id, item.file_type || ext);
  }
  if (typeof onMaxQualityToggle === 'function') onMaxQualityToggle();
  return true;
}

async function clearBatchQueue() {
  try {
    await fetch(`${API}/queue`, { method: 'DELETE' });
    _formatChosenByUser = false;
    await refreshBatchQueue();
    toast('🗑️ Η ουρά καθαρίστηκε.', 'info');
  } catch (_) {}
}

// ── Init ───────────────────────────────────────────────────
async function init() {
  // Initialize Theme, Editor Sync Scroll, Mode, and Quota Behavior choice
  initTheme();
  watchTranslationSettings();
  setupSyncScroll();
  initQuotaBehaviorSelectors();
  applyAppMode(currentAppMode);

  // Gemini keys live only on the server: load the masked state, migrate any legacy browser-stored keys once
  try {
    const sData = await refreshGeminiKeyState();
    if (sData) {
      syncFinalRefinementToggles(sData.final_refinement_enabled !== false);
      await migrateBrowserStoredGeminiKeys();
      const fresh = await refreshGeminiKeyState();
      const poolData = (fresh || sData).pool;
      if (poolData) renderGeminiPoolStatus(poolData);
      initQuotaBehaviorSelectors();
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
  const helpModal = document.getElementById('help-modal');
  if (helpModal) {
    helpModal.addEventListener('click', (e) => {
      if (e.target === helpModal) closeHelpModal();
    });
  }
  const devicesModal = document.getElementById('devices-modal');
  if (devicesModal) {
    devicesModal.addEventListener('click', (e) => {
      if (e.target === devicesModal) closeDevicesModal();
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
      const helpModal = document.getElementById('help-modal');
      if (helpModal && helpModal.style.display !== 'none') {
        closeHelpModal();
      }
      const devicesModal = document.getElementById('devices-modal');
      if (devicesModal && devicesModal.style.display !== 'none') {
        closeDevicesModal();
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
