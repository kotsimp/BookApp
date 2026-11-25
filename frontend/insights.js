/* Book Insights UI (summaries, synopses, audio) — loaded after app.js; uses its globals (API, state, toast, escHtml, parseApiError, ...). */
'use strict';

// ============================================================
// Book Insights — summaries, synopses & their audio versions
// (backend: backend/book_insights.py, endpoints /api/insights/*)
// ============================================================
const insState = {
  jobId: null,
  fileName: '',
  analysis: null,
  busy: false,
  record: null,     // last displayed insight record
  pollTimer: null,
};

const INS_LANG_LABELS = { greek: 'Ελληνικά', english: 'English', other: 'Γλώσσα εγγράφου' };

function _insApiOrigin() {
  return API.replace(/\/api$/, '');
}

function _insFriendlyNetworkError(err) {
  if (err && (err.name === 'TypeError' || /Failed to fetch|NetworkError/i.test(String(err.message || '')))) {
    return 'Δεν υπάρχει σύνδεση με τον διακομιστή. Ελέγξτε ότι η εφαρμογή εκτελείται και τη σύνδεσή σας στο διαδίκτυο.';
  }
  return (err && err.message) ? err.message : 'Παρουσιάστηκε απρόσμενο σφάλμα.';
}

function showInsightsError(msg) {
  const box = document.getElementById('ins-error');
  if (!box) return;
  if (!msg) {
    box.style.display = 'none';
    box.textContent = '';
    return;
  }
  box.textContent = `❌ ${msg}`;
  box.style.display = '';
}

function setInsightsBusy(busy) {
  insState.busy = !!busy;
  updateInsightsButtons();
  const audioBtn = document.getElementById('ins-audio-btn');
  if (audioBtn) audioBtn.disabled = !!busy;
  const resultCard = document.getElementById('ins-result-card');
  if (resultCard && resultCard.classList) {
    if (busy) resultCard.classList.add('ins-busy'); else resultCard.classList.remove('ins-busy');
  }
}

function setInsightsProgress(pct, step) {
  const card = document.getElementById('ins-progress-card');
  if (!card) return;
  if (pct === null) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  document.getElementById('ins-progress-bar').style.width = `${p}%`;
  document.getElementById('ins-progress-pct').textContent = `${p}%`;
  document.getElementById('ins-progress-step').textContent = step || '';
}

function updateInsightsButtons() {
  const a = insState.analysis;
  const ready = Boolean(insState.jobId && a && a.has_api_key);
  const canSummary = ready && a.can_summary;
  const canSynopsis = ready && a.can_synopsis;
  const set = (id, enabled) => { const el = document.getElementById(id); if (el) el.disabled = insState.busy || !enabled; };
  set('ins-basic-summary-btn', canSummary);
  set('ins-basic-synopsis-btn', canSynopsis);
  set('ins-adv-summary-btn', canSummary);
  set('ins-adv-synopsis-btn', canSynopsis);

  const synReason = (a && !a.can_synopsis) ? (a.reasons?.synopsis || '') : '';
  const sumReason = (a && !a.can_summary) ? (a.reasons?.summary || '') : '';
  ['ins-basic-synopsis-reason', 'ins-adv-synopsis-reason'].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const msg = sumReason || synReason;
    el.textContent = msg ? `ℹ️ ${msg}` : '';
    el.style.display = msg ? '' : 'none';
  });
  const keyWarn = document.getElementById('ins-key-warning');
  if (keyWarn) keyWarn.style.display = (insState.jobId && a && !a.has_api_key) ? '' : 'none';
}

function refreshInsightsPanel() {
  const btn = document.getElementById('ins-use-current-btn');
  if (!btn) return;
  const other = state.tr.jobId ? 'tr' : (state.ab.jobId ? 'ab' : null);
  const show = Boolean(other && !insState.jobId);
  btn.style.display = show ? '' : 'none';
  if (show) {
    const name = state[other].file?.name || '';
    btn.textContent = name ? `📎 Χρήση του «${name}»` : '📎 Χρήση του εγγράφου που ήδη ανεβάσατε';
  }
}

function _insShowDocument(name, metaText) {
  document.getElementById('ins-file-name').textContent = name || 'Έγγραφο';
  document.getElementById('ins-file-meta').textContent = metaText || '';
  const ext = (name || '').split('.').pop().toLowerCase();
  document.getElementById('ins-file-icon').textContent = ({ pdf: '📕', docx: '📘', epub: '📗' })[ext] || '📄';
  document.getElementById('ins-selected-file').classList.add('visible');
  document.getElementById('ins-upload-zone').style.display = 'none';
  const useBtn = document.getElementById('ins-use-current-btn');
  if (useBtn) useBtn.style.display = 'none';
}

function removeInsightsDocument() {
  if (insState.busy) {
    toast('Περιμένετε να ολοκληρωθεί η τρέχουσα δημιουργία.', 'info');
    return;
  }
  insState.jobId = null;
  insState.fileName = '';
  insState.analysis = null;
  insState.record = null;
  document.getElementById('ins-selected-file').classList.remove('visible');
  document.getElementById('ins-upload-zone').style.display = '';
  document.getElementById('ins-result-card').style.display = 'none';
  const inp = document.getElementById('ins-file-input');
  if (inp) inp.value = '';
  showInsightsError('');
  setInsightsProgress(null);
  updateInsightsButtons();
  refreshInsightsPanel();
}

function handleInsightsDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  const zone = document.getElementById('ins-upload-zone');
  if (zone) zone.classList.remove('dragover');
  const files = Array.from(e.dataTransfer?.files || []);
  if (files.length) uploadInsightsDocument(files[0]);
}

function handleInsightsFileSelect(e) {
  const files = Array.from(e.target.files || []);
  if (files.length) uploadInsightsDocument(files[0]);
  try { e.target.value = ''; } catch (_) {}
}

async function uploadInsightsDocument(file) {
  if (insState.busy) {
    toast('Περιμένετε να ολοκληρωθεί η τρέχουσα δημιουργία.', 'info');
    return;
  }
  const dot = file.name.lastIndexOf('.');
  const ext = dot > 0 ? file.name.slice(dot).toLowerCase() : '';
  if (!['.pdf', '.docx', '.epub'].includes(ext)) {
    showInsightsError(`Ο τύπος αρχείου «${ext || 'χωρίς επέκταση'}» δεν υποστηρίζεται για Book Insights. Χρησιμοποιήστε PDF, DOCX ή EPUB.`);
    return;
  }
  showInsightsError('');
  _insShowDocument(file.name, 'Μεταφόρτωση…');
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(`${API}/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await parseApiError(res, 'Η μεταφόρτωση απέτυχε'));
    const data = await res.json();
    insState.jobId = data.job_id;
    insState.fileName = file.name;
    await loadInsightsAnalysis();
  } catch (err) {
    showInsightsError(_insFriendlyNetworkError(err));
    document.getElementById('ins-file-meta').textContent = 'Σφάλμα';
  }
}

async function useCurrentDocumentForInsights() {
  const other = state.tr.jobId ? 'tr' : (state.ab.jobId ? 'ab' : null);
  if (!other) return;
  insState.jobId = state[other].jobId;
  insState.fileName = state[other].file?.name || '';
  _insShowDocument(insState.fileName, 'Ανάλυση…');
  await loadInsightsAnalysis();
}

// Session History click while the Book Insights tab is open: load that document here (not into
// Translation) and show its most recent saved summary/synopsis, if any.
async function loadHistoryJobIntoInsights(jobId, fileName) {
  if (!jobId) return false;
  if (insState.busy) {
    toast('Περιμένετε να ολοκληρωθεί η τρέχουσα δημιουργία.', 'info');
    return false;
  }
  insState.jobId = jobId;
  insState.fileName = fileName || '';
  insState.analysis = null;
  insState.record = null;
  document.getElementById('ins-result-card').style.display = 'none';
  setInsightsProgress(null);
  showInsightsError('');
  _insShowDocument(insState.fileName || 'Έγγραφο', 'Φόρτωση από το Ιστορικό…');
  const card = document.getElementById('ins-selected-file');
  if (card && typeof card.scrollIntoView === 'function') card.scrollIntoView({ behavior: 'smooth', block: 'center' });

  await loadInsightsAnalysis();
  if (insState.jobId !== jobId) return false;   // another item was clicked meanwhile
  if (!fileName && insState.fileName) _insShowDocument(insState.fileName, document.getElementById('ins-file-meta').textContent);

  try {
    const res = await fetch(`${API}/insights/${encodeURIComponent(jobId)}`);
    if (res.ok && insState.jobId === jobId) {
      const data = await res.json();
      const saved = (Array.isArray(data.insights) ? data.insights : []).filter((r) => r && r.text);
      saved.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
      if (saved.length) renderInsightResult(saved[0]);
    }
  } catch (_) {}
  toast(`📄 Φορτώθηκε «${insState.fileName || 'έγγραφο'}» στο Book Insights.`, 'info');
  return true;
}

async function loadInsightsAnalysis() {
  if (!insState.jobId) return;
  const jobId = insState.jobId;
  showInsightsError('');
  document.getElementById('ins-file-meta').textContent = 'Ανάλυση κειμένου…';
  try {
    const res = await fetch(`${API}/insights/${encodeURIComponent(jobId)}/analysis`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Η ανάλυση του εγγράφου απέτυχε'));
    const a = await res.json();
    if (insState.jobId !== jobId) return;   // a different document was loaded while this one was analysed
    insState.analysis = a;
    if (a.file_name && !insState.fileName) insState.fileName = a.file_name;
    const lang = a.detected_language ? (INS_LANG_LABELS[a.detected_language] || a.detected_language) : 'άγνωστη γλώσσα';
    if (a.needs_scan_reading) {
      // a scanned book: Gemini Vision reads its pages first, when a summary or synopsis is asked for
      document.getElementById('ins-file-meta').textContent =
        `📖 Σκαναρισμένο PDF: πρώτα διαβάζονται ${a.scan_pages} σελίδες με Gemini Vision (1 αίτημα ανά σελίδα)`;
      if (!a.has_api_key) showInsightsError('Χρειάζεται κλειδί Gemini για να διαβαστεί το κείμενο των σελίδων.');
      updateInsightsButtons();
      return;
    }
    document.getElementById('ins-file-meta').textContent =
      `~${a.meaningful_words.toLocaleString('el-GR')} λέξεις · ~${a.estimated_pages} σελίδες · ${lang}`;
    if (!a.can_summary) showInsightsError(a.reasons?.summary || 'Το έγγραφο δεν περιέχει αρκετό κείμενο.');
    else if (!a.detected_language) showInsightsError('Δεν εντοπίστηκε η γλώσσα του εγγράφου. Στην Προχωρημένη Λειτουργία μπορείτε να επιλέξετε γλώσσα εξόδου.');
  } catch (err) {
    if (insState.jobId !== jobId) return;
    insState.analysis = null;
    showInsightsError(_insFriendlyNetworkError(err));
    document.getElementById('ins-file-meta').textContent = 'Σφάλμα ανάλυσης';
  }
  updateInsightsButtons();
}

function _insPollTask(taskId) {
  return new Promise((resolve, reject) => {
    let failures = 0;
    const tick = async () => {
      try {
        const res = await fetch(`${API}/insights/tasks/${encodeURIComponent(taskId)}`);
        if (!res.ok) throw new Error(await parseApiError(res, 'Χάθηκε η παρακολούθηση της εργασίας'));
        failures = 0;
        const t = await res.json();
        setInsightsProgress(t.progress || 0, t.step || '');
        if (t.status === 'done') return resolve(t);
        if (t.status === 'error') return reject(new Error(t.error?.message || 'Η δημιουργία απέτυχε.'));
      } catch (err) {
        failures += 1;
        if (failures >= 5) return reject(err);
      }
      insState.pollTimer = setTimeout(tick, 1500);
    };
    tick();
  });
}

async function runInsight(mode, kind) {
  if (insState.busy) {
    toast('Μια δημιουργία εκτελείται ήδη — περιμένετε να ολοκληρωθεί.', 'info');
    return;
  }
  if (!insState.jobId) {
    showInsightsError('Ανεβάστε πρώτα ένα βιβλίο ή έγγραφο.');
    return;
  }
  let insightType = kind;            // basic: 'summary' | 'synopsis' (server maps to short/standard)
  let language = 'auto';
  let format = 'screen';
  if (mode === 'advanced') {
    insightType = document.getElementById(kind === 'summary' ? 'ins-summary-type' : 'ins-synopsis-type').value;
    language = document.getElementById(kind === 'summary' ? 'ins-summary-lang' : 'ins-synopsis-lang').value;
    format = document.getElementById(kind === 'summary' ? 'ins-summary-format' : 'ins-synopsis-format').value;
  }
  showInsightsError('');
  setInsightsBusy(true);
  setInsightsProgress(2, 'Έναρξη…');
  try {
    const apiKey = getClientApiKey();
    const res = await fetch(`${API}/insights/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: insState.jobId, insight_type: insightType, language, api_key: apiKey }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Η δημιουργία δεν ξεκίνησε'));
    const started = await res.json();
    if (started.duplicate) toast('Η ίδια δημιουργία εκτελείται ήδη — εμφανίζεται η πρόοδός της.', 'info');
    const task = await _insPollTask(started.task_id);
    renderInsightResult(task.result);
    if (format !== 'screen') await exportInsight(format);
    toast('✅ Ολοκληρώθηκε!', 'success');
  } catch (err) {
    showInsightsError(_insFriendlyNetworkError(err));
  } finally {
    setInsightsProgress(null);
    setInsightsBusy(false);
  }
}

function renderInsightMarkdown(md) {
  // Escape first, then apply a tiny safe subset of Markdown (headings, bullets, bold, paragraphs)
  const blocks = escHtml(md || '').split(/\n\s*\n/);
  return blocks.map((block) => {
    const lines = block.split('\n');
    if (lines.every((l) => /^\s*-\s+/.test(l))) {
      return '<ul>' + lines.map((l) => `<li>${l.replace(/^\s*-\s+/, '')}</li>`).join('') + '</ul>';
    }
    return lines.map((l) => {
      const h = l.match(/^(#{2,3})\s+(.*)$/);
      if (h) return h[1].length === 2 ? `<h3>${h[2]}</h3>` : `<h4>${h[2]}</h4>`;
      if (/^\s*-\s+/.test(l)) return `<ul><li>${l.replace(/^\s*-\s+/, '')}</li></ul>`;
      return l.trim() ? `<p>${l}</p>` : '';
    }).join('');
  }).join('').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

function renderInsightResult(rec) {
  if (!rec || !rec.text) {
    showInsightsError('Δεν επιστράφηκε έγκυρο αποτέλεσμα. Δοκιμάστε ξανά.');
    return;
  }
  insState.record = rec;
  document.getElementById('ins-result-title').textContent = `${rec.label || 'Αποτέλεσμα'} — ${rec.title || ''}`;
  const target = Array.isArray(rec.target_words) ? ` · στόχος ${rec.target_words[0]}–${rec.target_words[1]}` : '';
  document.getElementById('ins-result-meta').textContent =
    `${rec.word_count} λέξεις${target} · ${INS_LANG_LABELS[rec.language] || rec.language}` +
    (rec.from_notes ? ' · από ανάλυση ολόκληρου του βιβλίου ανά ενότητα' : '') +
    (rec.gemini_usage ? ` · Gemini: ${formatGeminiUsage(rec.gemini_usage)}` : '');
  const warnEl = document.getElementById('ins-result-warnings');
  const warnings = Array.isArray(rec.warnings) ? rec.warnings : [];
  warnEl.textContent = warnings.length ? `⚠️ Σημειώσεις ελέγχου: ${warnings.join(' · ')}` : '';
  warnEl.style.display = warnings.length ? '' : 'none';
  document.getElementById('ins-result-body').innerHTML = renderInsightMarkdown(rec.text);
  const audioBox = document.getElementById('ins-audio-box');
  if (rec.audio_url) {
    _insShowAudio(rec.audio_url);
  } else if (audioBox) {
    audioBox.style.display = 'none';
  }
  const audioBtn = document.getElementById('ins-audio-btn');
  if (audioBtn) audioBtn.style.display = (rec.language === 'greek' || rec.language === 'english') ? '' : 'none';
  document.getElementById('ins-result-card').style.display = '';
}

async function copyInsightText() {
  if (!insState.record) return;
  try {
    await navigator.clipboard.writeText(insState.record.text);
    toast('📋 Αντιγράφηκε.', 'success');
  } catch (_) {
    toast('Η αντιγραφή δεν επιτρέπεται από τον browser.', 'error');
  }
}

async function exportInsight(fmt) {
  const rec = insState.record;
  if (!rec || !insState.jobId) return;
  try {
    const res = await fetch(`${API}/insights/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: insState.jobId, insight_type: rec.insight_type, language: rec.language, format: fmt }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Η εξαγωγή αρχείου απέτυχε'));
    const data = await res.json();
    const a = document.createElement('a');
    a.href = `${_insApiOrigin()}${data.url}`;
    a.download = data.file_name || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (err) {
    showInsightsError(_insFriendlyNetworkError(err));
  }
}

function _insShowAudio(url) {
  const box = document.getElementById('ins-audio-box');
  const player = document.getElementById('ins-audio-player');
  const dl = document.getElementById('ins-audio-download');
  const full = `${_insApiOrigin()}${url}`;
  player.src = full;
  dl.href = full;
  box.style.display = '';
}

async function generateInsightAudio() {
  const rec = insState.record;
  if (!rec || !insState.jobId) return;
  if (insState.busy) {
    toast('Μια δημιουργία εκτελείται ήδη — περιμένετε να ολοκληρωθεί.', 'info');
    return;
  }
  showInsightsError('');
  setInsightsBusy(true);
  setInsightsProgress(2, 'Προετοιμασία εκφώνησης…');
  try {
    const res = await fetch(`${API}/insights/audio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: insState.jobId, insight_type: rec.insight_type, language: rec.language }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Η δημιουργία ήχου δεν ξεκίνησε'));
    const started = await res.json();
    const task = await _insPollTask(started.task_id);
    const audioUrl = task.result && task.result.audio_url;
    if (!audioUrl) throw new Error('Η δημιουργία ήχου απέτυχε.');
    insState.record = task.result;
    _insShowAudio(audioUrl);
    toast('🎧 Ο ήχος είναι έτοιμος.', 'success');
  } catch (err) {
    showInsightsError(_insFriendlyNetworkError(err));
  } finally {
    setInsightsProgress(null);
    setInsightsBusy(false);
  }
}
