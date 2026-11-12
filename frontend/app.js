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

// ── Output Format & Layout Selection ─────────────────────────
function selectFormat(fmt, btn) {
  // Deselect only format buttons (not layout buttons)
  document.querySelectorAll('#tr-format-selector .format-btn').forEach(b => b.classList.remove('active'));
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
  document.querySelectorAll('#tr-layout-selector .format-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tr-layout-mode').value = layout;

  const fmt = document.getElementById('tr-output-format')?.value || 'txt';
  const dlBtn = document.getElementById('tr-download-btn');
  if (dlBtn && state.tr.jobId) {
    dlBtn.href = `${API}/download/${state.tr.jobId}?format=${fmt}&layout=${layout}`;
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
  const layoutMode = document.getElementById('tr-layout-mode')?.value || 'standard';

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
  const aiPolish = document.getElementById('ab-ai-polish')?.checked || false;
  const apiKey = localStorage.getItem('gemini_api_key') || null;
  const styleRaw = document.getElementById('ab-narration-style')?.value || 'literature:-10%';
  const [narrationStyle, narrationRate] = styleRaw.split(':');

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
        narration_style: narrationStyle,
        rate: narrationRate,
        ai_polish: aiPolish,
        api_key: aiPolish ? apiKey : null,
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
    meta.textContent = `Your document has been translated. Click below to download the ${label} file.`;
    // Keep format label in download button in sync
    const labelEl = document.getElementById('tr-format-label');
    if (labelEl) labelEl.textContent = label;
    const dlBtn = document.getElementById('tr-download-btn');
    const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
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
  const labels = { idle: 'Idle', running: 'Running', done: 'Complete', error: 'Error' };
  badge.innerHTML = `<span class="status-dot"></span> ${labels[status] || status}`;
}

async function downloadOutput(prefix) {
  const jobId = state[prefix].jobId;
  if (!jobId) return;
  if (prefix === 'tr') {
    const fmt = document.getElementById('tr-output-format')?.value || 'txt';
    const layout = document.getElementById('tr-layout-mode')?.value || 'standard';
    const targetUrl = `${API}/download/${jobId}?format=${fmt}&layout=${layout}`;
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
  const prefix = mode === 'audiobook' ? 'ab' : 'tr';
  state[prefix].jobId = jobId;
  switchTab(mode === 'audiobook' ? 'audiobook' : 'translate');

  try {
    const res = await fetch(`${API}/status/${jobId}`);
    const data = await res.json();
    if (data.status === 'running') {
      document.getElementById(`${prefix}-progress-card`).style.display = 'block';
      document.getElementById(`${prefix}-start-btn`).disabled = true;
      setStatusBadge(prefix, 'running');
      updateProgress(prefix, data);
      connectSSE(prefix, jobId);
    } else if (data.has_output && data.status === 'done') {
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
    const dlBtn = document.getElementById('tr-download-btn');
    if (dlBtn) dlBtn.href = `${API}/download/${jobId}?format=${fmt}`;
  } catch (err) {
    toast(`Save error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '💾 Save & Update Files';
  }
}

// ── AI Polish via Gemini ───────────────────────────────────
let _polishPollTimer = null;

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

  const prog = document.getElementById('ai-polish-progress-container');
  if (prog) prog.style.display = 'none';
  const btn = document.getElementById('btn-run-polish');
  if (btn) btn.disabled = false;
}

function closeAiPolishModal() {
  if (_polishPollTimer) {
    clearInterval(_polishPollTimer);
    _polishPollTimer = null;
  }
  document.getElementById('ai-polish-modal').style.display = 'none';
  const prog = document.getElementById('ai-polish-progress-container');
  if (prog) prog.style.display = 'none';
  const btn = document.getElementById('btn-run-polish');
  if (btn) btn.disabled = false;
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
            stepEl.innerHTML = `<span class="status-dot"></span> ${data.step || 'Refining Greek translation...'}`;
            if (pagesEl) pagesEl.textContent = `Page ${data.current} of ${data.total}`;
          }
        }
      } catch (_) {}
    }, 500);
  }

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
      closeAiPolishModal();
    }, 600);
  } catch (err) {
    toast(`AI Error: ${err.message}`, 'error');
    progEl.style.display = 'none';
    btn.disabled = false;
  } finally {
    if (_polishPollTimer) {
      clearInterval(_polishPollTimer);
      _polishPollTimer = null;
    }
  }
}

// ── Glossary Management ────────────────────────────────────
async function openGlossaryModal() {
  document.getElementById('glossary-modal').style.display = 'flex';
  await loadGlossary();
}

function closeGlossaryModal() {
  document.getElementById('glossary-modal').style.display = 'none';
}

async function loadGlossary() {
  const tbody = document.getElementById('glossary-tbody');
  tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:var(--text-muted)">Loading terms...</td></tr>';

  try {
    const res = await fetch(`${API}/glossary`);
    const terms = await res.json();
    const entries = Object.entries(terms);

    if (entries.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:var(--text-muted)">No glossary terms yet. Add one above!</td></tr>';
      return;
    }

    tbody.innerHTML = entries.map(([src, tgt]) => `
      <tr>
        <td><strong>${escHtml(src)}</strong></td>
        <td>${escHtml(tgt)}</td>
        <td style="text-align:center">
          <button class="glossary-del-btn" onclick="deleteGlossaryRule('${escHtml(src)}')" title="Delete term">✕</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="3" style="color:#f87171">Failed to load glossary: ${err.message}</td></tr>`;
  }
}

async function addGlossaryRule() {
  const src = document.getElementById('glossary-source').value.trim();
  const tgt = document.getElementById('glossary-target').value.trim();
  if (!src || !tgt) {
    toast('Please enter both source and target terms.', 'error');
    return;
  }

  try {
    const res = await fetch(`${API}/glossary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: src, target: tgt }),
    });
    if (!res.ok) throw new Error('Failed to add term');
    document.getElementById('glossary-source').value = '';
    document.getElementById('glossary-target').value = '';
    toast(`Added "${src}" ➔ "${tgt}"`, 'success');
    await loadGlossary();
  } catch (err) {
    toast(`Error: ${err.message}`, 'error');
  }
}

async function deleteGlossaryRule(term) {
  try {
    const res = await fetch(`${API}/glossary/${encodeURIComponent(term)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete term');
    toast(`Deleted term "${term}"`, 'info');
    await loadGlossary();
  } catch (err) {
    toast(`Error: ${err.message}`, 'error');
  }
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
