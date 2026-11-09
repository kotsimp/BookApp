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
  const file = e.dataTransfer.files[0];
  if (file) processFile(file, prefix);
}

function handleFileSelect(e, prefix) {
  const file = e.target.files[0];
  if (file) processFile(file, prefix);
}

async function processFile(file, prefix) {
  const allowed = ['.pdf', '.docx', '.epub'];
  const ext = '.' + file.name.split('.').pop().toLowerCase();

  if (!allowed.includes(ext)) {
    toast(`❌ File type "${ext}" is not supported. Please use PDF, DOCX, or EPUB.`, 'error');
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
  const iconMap = { pdf: '📕', docx: '📘', epub: '📗' };
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
  resetProgress(prefix);
  // Reset file input
  const inp = document.getElementById(`${prefix}-file-input`);
  if (inp) inp.value = '';
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
    toast(`✅ "${file.name}" uploaded successfully.`, 'success');

    // Show translate option in audiobook tab
    if (prefix === 'ab') {
      document.getElementById('ab-translate-option').style.display = 'block';
    }

    refreshHistory();
  } catch (err) {
    toast(`❌ Upload error: ${err.message}`, 'error');
    removeFile(prefix);
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

// ── Output Format Selection ─────────────────────────────────
function selectFormat(fmt, btn) {
  // Deselect all format buttons
  document.querySelectorAll('.format-btn').forEach(b => b.classList.remove('active'));
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
  const dlBtn = document.getElementById('tr-download-btn');
  if (dlBtn && state.tr.jobId) {
    dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}`;
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

function updateVoices() {
  const lang = document.getElementById('ab-lang-select').value;
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
    `;
    card.onclick = () => selectVoice(name, card);
    grid.appendChild(card);
  });

  // Auto-select first voice
  if (entries.length > 0) {
    state.selectedVoice = entries[0][0];
    document.getElementById('ab-voice-selected').value = entries[0][0];
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
  const outputFormat = document.getElementById('tr-output-format').value || 'txt';

  // Update download button label to show chosen format
  const labelEl = document.getElementById('tr-format-label');
  if (labelEl) labelEl.textContent = outputFormat.toUpperCase();

  // Show progress UI
  document.getElementById('tr-progress-card').style.display = 'block';
  document.getElementById('tr-result-card').classList.remove('visible');
  document.getElementById('tr-error-card').classList.remove('visible');
  document.getElementById('tr-progress-detail').textContent = '';
  document.getElementById('tr-start-btn').disabled = true;
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

// ── Start Audiobook ────────────────────────────────────────
async function startAudiobook() {
  const jobId = state.ab.jobId;
  if (!jobId) { toast('Please upload a document first.', 'error'); return; }

  const language = document.getElementById('ab-lang-select').value;
  const voiceName = document.getElementById('ab-voice-selected').value || state.selectedVoice;
  const useTranslated = document.getElementById('ab-use-translated')?.checked || false;

  if (!voiceName) { toast('Please select a voice first.', 'error'); return; }

  // Show progress UI
  document.getElementById('ab-progress-card').style.display = 'block';
  document.getElementById('ab-result-card').classList.remove('visible');
  document.getElementById('ab-error-card').classList.remove('visible');
  document.getElementById('ab-start-btn').disabled = true;
  setStatusBadge('ab', 'running');

  try {
    const res = await fetch(`${API}/audiobook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        language,
        voice_name: voiceName,
        use_translated: useTranslated,
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

    if (data.status === 'done' || data.status === 'error') {
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
      if (data.status === 'done' || data.status === 'error') {
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

  document.getElementById(`${prefix}-progress-pct`).textContent = `${pct}%`;
  document.getElementById(`${prefix}-progress-bar`).style.width = `${pct}%`;
  document.getElementById(`${prefix}-progress-step`).textContent = step;

  // Show detail while actively running
  const detailEl = document.getElementById(`${prefix}-progress-detail`);
  if (data.total_chunks > 0 && data.status !== 'done') {
    if (prefix === 'tr') {
      detailEl.textContent = `Translated ${data.done_chunks} of ${data.total_chunks} pages`;
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
}

function showResult(prefix, data) {
  const card = document.getElementById(`${prefix}-result-card`);
  const meta = document.getElementById(`${prefix}-result-meta`);
  if (prefix === 'tr') {
    const fmt = (document.getElementById('tr-output-format')?.value || 'txt').toLowerCase();
    const label = fmt.toUpperCase();
    meta.textContent = `Your document has been translated. Click below to download the ${label} file.`;
    // Keep format label in download button in sync
    const labelEl = document.getElementById('tr-format-label');
    if (labelEl) labelEl.textContent = label;
    const dlBtn = document.getElementById('tr-download-btn');
    if (dlBtn && state.tr.jobId) {
      dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}`;
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
  const labels = { idle: 'Idle', running: 'Running', done: 'Complete', error: 'Error' };
  badge.innerHTML = `<span class="status-dot"></span> ${labels[status] || status}`;
}

async function downloadOutput(prefix) {
  const jobId = state[prefix].jobId;
  if (!jobId) return;
  if (prefix === 'tr') {
    const fmt = document.getElementById('tr-output-format')?.value || 'txt';
    const targetUrl = `${API}/download/${jobId}?format=${fmt}`;
    console.log('Initiating download:', targetUrl);
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

  const trName = document.getElementById('tr-file-name')?.textContent || 'Document';
  const trMeta = document.getElementById('tr-file-meta')?.textContent || 'Ready';

  const abName = document.getElementById('ab-file-name');
  const abMeta = document.getElementById('ab-file-meta');
  if (abName) abName.textContent = trName;
  if (abMeta) abMeta.textContent = trMeta;

  document.getElementById('ab-upload-zone').style.display = 'none';
  document.getElementById('ab-selected-file').style.display = 'flex';
  document.getElementById('ab-start-btn').disabled = false;

  // Set language dropdown to Greek and refresh voice cards
  const langSelect = document.getElementById('ab-lang-select');
  if (langSelect) {
    langSelect.value = 'greek';
    updateVoices();
  }

  // Check the "Use previously translated text" checkbox
  const transOpt = document.getElementById('ab-translate-option');
  if (transOpt) transOpt.style.display = 'block';
  const useTranslated = document.getElementById('ab-use-translated');
  if (useTranslated) useTranslated.checked = true;

  // Switch to the Audiobook tab
  switchTab('audiobook');
  toast('Ready to create Greek audiobook from translated text!', 'info');
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
  if (!jobs || jobs.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted); font-size:0.9rem;">No jobs yet. Upload a document to get started.</p>';
    return;
  }

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
    </div>
  `).join('');
}

async function loadHistoryJob(jobId, mode) {
  const prefix = mode === 'audiobook' ? 'ab' : 'tr';
  state[prefix].jobId = jobId;
  switchTab(mode === 'audiobook' ? 'audiobook' : 'translate');

  try {
    const res = await fetch(`${API}/status/${jobId}`);
    const data = await res.json();
    if (data.has_output && data.status === 'done') {
      // Re-enable download button
      document.getElementById(`${prefix}-start-btn`).disabled = false;
      showResult(prefix, data);
      setStatusBadge(prefix, 'done');
      document.getElementById(`${prefix}-progress-card`).style.display = 'block';
      document.getElementById(`${prefix}-progress-pct`).textContent = '100%';
      document.getElementById(`${prefix}-progress-bar`).style.width = '100%';
      document.getElementById(`${prefix}-progress-step`).textContent = data.current_step;
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
  el.innerHTML = `<span>${msg}</span>`;
  container.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ───────────────────────────────────────────────────
async function init() {
  // Check backend is reachable
  try {
    await fetch(`${API}/health`);
  } catch (e) {
    toast('⚠️ Cannot connect to backend. Make sure the server is running on port 8000.', 'error');
  }

  // Load voices
  await loadVoices();

  // Load history
  await refreshHistory();

  // Keyboard support for upload zones
  document.querySelectorAll('.upload-zone').forEach(zone => {
    zone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        zone.click();
      }
    });
  });
}

init();
