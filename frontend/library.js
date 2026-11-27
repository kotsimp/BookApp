/* library.js — the user's library: series, the EPUB's Characters page, reading-position sync (📲 Devices),
   what the Glossary learns from the translations, backups. Loaded after app.js and insights.js; uses their globals
   (API, state, toast, escHtml, parseApiError, saveFile, refreshHistory, loadGlossary, insState). */
'use strict';

const libState = {
  series: [],          // the user's series [{id, name, books: [{job_id, title}]}]
  bookSeries: null,    // the Translation tab book's place in a series (GET /jobs/<id>/series)
  backupTask: null,
  position: null,      // the Book Insights book's reading position (GET /jobs/<id>/reading-position)
  pollers: {},
};

// app.js calls this when the Translation tab's book changes (upload, Session History, removed)
function onBookChanged(prefix) {
  if (prefix !== 'tr') return;
  refreshBookSeries();
  refreshEpubCharacters();
}

// ── 📚 Series ──

async function loadSeriesList() {
  const res = await fetch(`${API}/series`);
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load the series'));
  const data = await res.json();
  libState.series = Array.isArray(data.series) ? data.series : [];
  return libState.series;
}

async function refreshBookSeries() {
  const row = document.getElementById('tr-series-row');
  if (!row) return;
  const jobId = state.tr.jobId;
  if (!jobId) {
    row.style.display = 'none';
    return;
  }
  try {
    const [list, res] = await Promise.all([loadSeriesList(), fetch(`${API}/jobs/${encodeURIComponent(jobId)}/series`)]);
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load the series'));
    const mine = await res.json();
    if (state.tr.jobId !== jobId) return;
    libState.bookSeries = mine;
    renderSeriesSelect(list, mine);
    row.style.display = '';
  } catch (_) {
    row.style.display = 'none';
  }
}

function renderSeriesSelect(list, mine) {
  const select = document.getElementById('tr-series-select');
  const pos = document.getElementById('tr-series-position');
  const note = document.getElementById('tr-series-note');
  if (!select) return;
  const current = mine && mine.series ? mine.series.id : '';
  select.innerHTML = ['<option value="">— Καμία —</option>',
    ...(list || []).map((s) => `<option value="${escHtml(s.id)}" translate="no">${escHtml(s.name)}</option>`),
    '<option value="__new">➕ Νέα σειρά…</option>'].join('');
  select.value = current;
  if (pos) {
    pos.disabled = !current;
    pos.value = current && mine.position ? String(mine.position) : '';
    if (current && mine.books) pos.max = String(mine.books);
  }
  if (!note) return;
  if (!current) note.textContent = 'Τα βιβλία μιας σειράς γράφουν τα ονόματα ίδια.';
  else if (mine.position === 1) note.textContent = 'Το πρώτο βιβλίο της σειράς: τα ονόματά του περνούν στα επόμενα.';
  else if (mine.names_from_earlier) note.textContent = `${mine.names_from_earlier} ονόματα από τα προηγούμενα βιβλία γράφονται ίδια σε αυτό.`;
  else note.textContent = 'Τα προηγούμενα βιβλία δεν έχουν ακόμη ονόματα από μετάφραση.';
}

async function _seriesCreate(name) {
  const res = await fetch(`${API}/series`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to make the series'));
  return res.json();
}

async function _seriesUpdate(seriesId, body) {
  const res = await fetch(`${API}/series/${encodeURIComponent(seriesId)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to change the series'));
  return res.json();
}

async function _placeBook(jobId, seriesId, position = null) {
  const res = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/series`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ series_id: seriesId || null, position }),
  });
  if (!res.ok) throw new Error(await parseApiError(res, 'Failed to save the series'));
  return res.json();
}

async function onBookSeriesChange() {
  const select = document.getElementById('tr-series-select');
  const pos = document.getElementById('tr-series-position');
  const jobId = state.tr.jobId;
  if (!jobId || !select) return;
  let seriesId = select.value;
  try {
    if (seriesId === '__new') {
      const name = ((typeof window.prompt === 'function' ? window.prompt('Όνομα της νέας σειράς:', '') : '') || '').trim();
      if (!name) {
        renderSeriesSelect(libState.series, libState.bookSeries);
        return;
      }
      seriesId = (await _seriesCreate(name)).id;
    }
    const before = libState.bookSeries && libState.bookSeries.series ? libState.bookSeries.series.id : '';
    const wanted = parseInt(pos && pos.value, 10);
    await _placeBook(jobId, seriesId, seriesId === before && wanted > 0 ? wanted : null);
    if (seriesId !== before) toast(seriesId ? '📚 Το βιβλίο μπήκε στη σειρά.' : '📚 Το βιβλίο βγήκε από τη σειρά.', 'success');
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await refreshBookSeries();
  if (typeof refreshHistory === 'function') refreshHistory();
}

async function openSeriesModal() {
  const modal = document.getElementById('series-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  await renderSeriesModal();
}

function closeSeriesModal() {
  const modal = document.getElementById('series-modal');
  if (modal) modal.style.display = 'none';
  refreshBookSeries();
  if (typeof refreshHistory === 'function') refreshHistory();
}

async function renderSeriesModal() {
  const box = document.getElementById('series-list');
  if (!box) return;
  let list;
  let jobs = [];
  try {
    list = await loadSeriesList();
    const res = await fetch(`${API}/jobs`);
    jobs = res.ok ? await res.json() : [];
  } catch (e) {
    box.textContent = `❌ ${e.message}`;
    return;
  }
  if (!list.length) {
    box.innerHTML = '<p class="devices-note">Δεν υπάρχουν σειρές ακόμη. Φτιάξτε μία εδώ ή από το βιβλίο, στην καρτέλα Μετάφραση.</p>';
    return;
  }
  const inSeries = new Set(list.flatMap((s) => s.books.map((b) => b.job_id)));
  const free = (Array.isArray(jobs) ? jobs : []).filter((j) => j.file_name && !inSeries.has(j.job_id));
  box.innerHTML = list.map((s) => {
    const sid = escHtml(s.id);
    const books = s.books.map((b, i) => `
      <li><span class="series-book-title" translate="no">${escHtml(b.title)}</span>
        <span class="series-book-actions">
          <button type="button" class="btn-icon-sm" data-series-id="${sid}" data-index="${i}" onclick="moveSeriesBook(this.dataset.seriesId, Number(this.dataset.index), -1)" title="Νωρίτερα στη σειρά" aria-label="Νωρίτερα στη σειρά"${i === 0 ? ' disabled' : ''}>↑</button>
          <button type="button" class="btn-icon-sm" data-series-id="${sid}" data-index="${i}" onclick="moveSeriesBook(this.dataset.seriesId, Number(this.dataset.index), 1)" title="Αργότερα στη σειρά" aria-label="Αργότερα στη σειρά"${i === s.books.length - 1 ? ' disabled' : ''}>↓</button>
          <button type="button" class="btn-icon-sm" data-series-id="${sid}" data-index="${i}" onclick="removeSeriesBook(this.dataset.seriesId, Number(this.dataset.index))" title="Έξω από τη σειρά" aria-label="Έξω από τη σειρά">✕</button>
        </span></li>`).join('');
    const add = free.length ? `<select class="form-select-sm" data-series-id="${sid}" onchange="addBookToSeries(this.dataset.seriesId, this.value)" aria-label="Προσθήκη βιβλίου στη σειρά">
        <option value="">➕ Προσθήκη βιβλίου…</option>
        ${free.map((j) => `<option value="${escHtml(j.job_id)}" translate="no">${escHtml(j.file_name)}</option>`).join('')}
      </select>` : '';
    return `<section class="series-item">
      <div class="series-item-head">
        <strong translate="no">${escHtml(s.name)}</strong>
        <span class="series-item-actions">
          <button type="button" class="btn-sm btn-outline" data-series-id="${sid}" onclick="renameSeries(this.dataset.seriesId)">✏️ Μετονομασία</button>
          <button type="button" class="btn-sm btn-outline" data-series-id="${sid}" onclick="deleteSeries(this.dataset.seriesId)">🗑️ Διαγραφή</button>
        </span>
      </div>
      ${books ? `<ol class="series-books">${books}</ol>` : '<p class="devices-note">Κανένα βιβλίο ακόμη.</p>'}
      ${add}
    </section>`;
  }).join('');
}

async function createSeriesFromModal() {
  const input = document.getElementById('series-new-name');
  const name = (input && input.value || '').trim();
  if (!name) {
    toast('Γράψτε ένα όνομα σειράς.', 'info');
    return;
  }
  try {
    await _seriesCreate(name);
    input.value = '';
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await renderSeriesModal();
}

function _seriesById(seriesId) {
  return libState.series.find((s) => s.id === seriesId) || null;
}

async function renameSeries(seriesId) {
  const s = _seriesById(seriesId);
  if (!s) return;
  const name = ((typeof window.prompt === 'function' ? window.prompt('Νέο όνομα της σειράς:', s.name) : '') || '').trim();
  if (!name || name === s.name) return;
  try {
    await _seriesUpdate(seriesId, { name });
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await renderSeriesModal();
}

async function deleteSeries(seriesId) {
  if (!window.confirm('Να διαγραφεί η σειρά; Τα βιβλία της μένουν.')) return;
  try {
    const res = await fetch(`${API}/series/${encodeURIComponent(seriesId)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to delete the series'));
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await renderSeriesModal();
}

async function _setSeriesBooks(seriesId, books) {
  try {
    await _seriesUpdate(seriesId, { books });
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await renderSeriesModal();
}

async function moveSeriesBook(seriesId, index, step) {
  const s = _seriesById(seriesId);
  if (!s) return;
  const books = s.books.map((b) => b.job_id);
  const to = index + step;
  if (to < 0 || to >= books.length) return;
  [books[index], books[to]] = [books[to], books[index]];
  await _setSeriesBooks(seriesId, books);
}

async function removeSeriesBook(seriesId, index) {
  const s = _seriesById(seriesId);
  if (!s) return;
  await _setSeriesBooks(seriesId, s.books.map((b) => b.job_id).filter((_, i) => i !== index));
}

async function addBookToSeries(seriesId, jobId) {
  if (!jobId) return;
  try {
    await _placeBook(jobId, seriesId);
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await renderSeriesModal();
}

// ── 👥 The EPUB's Characters page ──

async function refreshEpubCharacters() {
  const box = document.getElementById('tr-epub-extras');
  if (!box) return;
  const jobId = state.tr.jobId;
  if (!jobId) {
    box.style.display = 'none';
    return;
  }
  try {
    const res = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/epub-options`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load the EPUB options'));
    const o = await res.json();
    if (state.tr.jobId === jobId) showEpubCharacters(o);
  } catch (_) {
    box.style.display = 'none';
  }
}

function showEpubCharacters(o) {
  const box = document.getElementById('tr-epub-extras');
  const check = document.getElementById('tr-epub-characters');
  const note = document.getElementById('tr-epub-characters-note');
  if (!box || !check) return;
  const layout = (document.getElementById('tr-layout-mode')?.value || '').toLowerCase();
  box.style.display = layout === 'comic' ? 'none' : '';  // a graphic novel's EPUB is its pages
  check.checked = Boolean(o && o.characters);
  check.disabled = !(o && (o.available || o.characters));
  if (!note) return;
  if (o && o.available) {
    note.textContent = `Από τα 👥 Πρόσωπα & όροι: ${o.people} πρόσωπα, ${o.terms} όροι.`;
  } else {
    note.textContent = o && o.language === 'english'
      ? 'Φτιάξτε πρώτα 👥 Πρόσωπα & όροι στο Book Insights, στα Αγγλικά.'
      : 'Φτιάξτε πρώτα 👥 Πρόσωπα & όροι στο Book Insights, στα Ελληνικά.';
  }
}

async function setEpubCharacters(on) {
  const jobId = state.tr.jobId;
  if (!jobId) return;
  try {
    const res = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/epub-options`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ characters: Boolean(on) }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to save the EPUB options'));
    showEpubCharacters(await res.json());
    toast(on ? '👥 Το EPUB θα έχει σελίδα «Πρόσωπα».' : '👥 Το EPUB χωρίς σελίδα «Πρόσωπα».', 'success');
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
    refreshEpubCharacters();
  }
}

// ── 🔄 Reading-position sync (📲 Devices) ──

function showSyncState(sync, username) {
  const remove = document.getElementById('sync-remove-btn');
  const details = document.getElementById('sync-details');
  if (details) details.style.display = 'none';
  if (remove) remove.style.display = sync && sync.exists ? '' : 'none';
  const status = document.getElementById('sync-status');
  if (!status) return;
  if (sync && sync.exists) {
    const day = new Date((sync.created || 0) * 1000).toLocaleDateString('el-GR');
    status.textContent = sync.last_sync
      ? `Υπάρχει κωδικός από ${day}. Τελευταίος συγχρονισμός: ${new Date(sync.last_sync * 1000).toLocaleString('el-GR')}.`
      : `Υπάρχει κωδικός από ${day}. Καμία θέση δεν έχει σταλεί ακόμη.`;
  } else {
    status.textContent = 'Δεν υπάρχει κωδικός συγχρονισμού ακόμη.';
  }
  libState.syncUser = username || '';
}

async function newSyncPassword() {
  const remove = document.getElementById('sync-remove-btn');
  const exists = remove && remove.style.display !== 'none';
  if (exists && !window.confirm('Ο τωρινός κωδικός θα σταματήσει να λειτουργεί. Να φτιαχτεί νέος;')) return;
  try {
    const res = await fetch(`${API}/connections/sync`, { method: 'POST' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to make a sync password'));
    const data = await res.json();
    document.getElementById('sync-server').value = `${window.location.origin}${data.path}`;
    document.getElementById('sync-username').value = data.username || 'reader';
    document.getElementById('sync-password').value = data.password;
    document.getElementById('sync-details').style.display = '';
    if (remove) remove.style.display = '';
    setDevicesStatus('sync-status', data.username
      ? '✅ Νέος κωδικός. Αντιγράψτε τον τώρα: δεν θα ξαναφανεί.'
      : '✅ Νέος κωδικός. Αντιγράψτε τον τώρα: δεν θα ξαναφανεί. Χωρίς λογαριασμούς χρηστών, το όνομα χρήστη μπορεί να είναι οποιοδήποτε.');
  } catch (e) {
    setDevicesStatus('sync-status', `❌ ${e.message}`);
  }
}

async function copySyncDetail(id) {
  const input = document.getElementById(id);
  if (!input || !input.value) return;
  try {
    await navigator.clipboard.writeText(input.value);
  } catch (_) {  // plain http on a LAN address: no clipboard API
    input.select();
    document.execCommand('copy');
  }
  toast('📋 Αντιγράφηκε.', 'success');
}

async function removeSyncPassword() {
  if (!window.confirm('Να καταργηθεί ο κωδικός; Οι εφαρμογές ανάγνωσης δεν θα συγχρονίζουν πια τη θέση σας.')) return;
  try {
    const res = await fetch(`${API}/connections/sync`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to remove the sync password'));
    showSyncState({ exists: false }, libState.syncUser);
  } catch (e) {
    setDevicesStatus('sync-status', `❌ ${e.message}`);
  }
}

// ── 📍 Book Insights: the reading position and the earlier books of the series ──

async function refreshInsightsLibrary(jobId) {
  const btn = document.getElementById('ins-recap-position');
  const note = document.getElementById('ins-recap-position-note');
  libState.position = null;
  if (btn) btn.style.display = 'none';
  if (note) note.textContent = '';
  const box = document.getElementById('ins-series');
  if (box) box.style.display = 'none';
  if (!jobId) return;
  try {
    const res = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/reading-position`);
    const data = res.ok ? await res.json() : null;
    if (insState.jobId !== jobId) return;
    if (data && data.position) {
      libState.position = data;
      const pct = Math.round(Number(data.position.percentage || 0) * 100);
      const where = data.until ? (data.unit === 'chapter' ? ` (κεφάλαιο ${data.until})` : ` (σελίδα ${data.until})`) : '';
      if (note) note.textContent = `📍 Έχετε διαβάσει ${pct}%${where}.`;
      if (btn) btn.style.display = data.until ? '' : 'none';
    }
  } catch (_) {}
  try {
    const lang = document.getElementById('ins-more-lang')?.value;
    const language = lang === 'english' ? 'english' : 'greek';
    const res = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/series?language=${language}`);
    const data = res.ok ? await res.json() : null;
    if (insState.jobId !== jobId) return;
    renderInsightsSeries(data);
  } catch (_) {}
}

function useReadingPosition() {
  const input = document.getElementById('ins-recap-until');
  if (!input || !libState.position || !libState.position.until) return;
  input.value = String(libState.position.until);
  toast('📍 Η ιστορία ως τώρα: ως εκεί που σταματήσατε.', 'info');
}

function renderInsightsSeries(data) {
  const box = document.getElementById('ins-series');
  const list = document.getElementById('ins-series-books');
  const name = document.getElementById('ins-series-name');
  if (!box || !list) return;
  if (!data || !data.series || !Array.isArray(data.earlier) || !data.earlier.length) {
    box.style.display = 'none';
    return;
  }
  if (name) {
    name.textContent = '';
    const n = document.createElement('span');
    n.setAttribute('translate', 'no');
    n.textContent = data.series.name;
    name.append(n, document.createTextNode(` · βιβλίο ${data.position}`));
  }
  list.innerHTML = data.earlier.map((b, i) => {
    const title = `<span translate="no">${escHtml(b.title)}</span>`;
    if (b.summary && b.summary.text) {
      return `<details class="ins-series-book"><summary>${i + 1}. ${title}</summary>
        <div class="ins-series-summary" translate="no">${escHtml(b.summary.text).replace(/\n/g, '<br>')}</div></details>`;
    }
    return `<div class="ins-series-book">${i + 1}. ${title} <span class="sample-hint">χωρίς περίληψη ακόμη</span>
      <button type="button" class="btn-sm btn-outline" data-job-id="${escHtml(b.job_id)}" data-title="${escHtml(b.title)}" onclick="loadHistoryJobIntoInsights(this.dataset.jobId, this.dataset.title)">📄 Άνοιγμα</button></div>`;
  }).join('');
  box.style.display = '';
}

// ── 💡 What the Glossary learns ──

async function loadGlossarySuggestions() {
  const box = document.getElementById('glossary-suggestions');
  if (!box) return;
  try {
    const res = await fetch(`${API}/glossary/suggestions`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to load the suggestions'));
    renderGlossarySuggestions(await res.json());
  } catch (_) {
    box.style.display = 'none';
  }
}

function renderGlossarySuggestions(data) {
  const box = document.getElementById('glossary-suggestions');
  const body = document.getElementById('glossary-suggestions-tbody');
  const count = document.getElementById('glossary-suggestions-count');
  const all = document.getElementById('glossary-accept-all-btn');
  const items = (data && Array.isArray(data.suggestions)) ? data.suggestions : [];
  if (!box || !body) return;
  box.style.display = items.length ? '' : 'none';
  if (count) count.textContent = String(items.length);
  if (all) all.disabled = !(data && data.safe);
  body.innerHTML = items.map((s) => {
    const tags = [
      s.origin === 'edit' ? '<span class="sugg-tag sugg-edit" title="Το γράψατε έτσι στον Έλεγχο & Διόρθωση">✏️</span>' : '',
      s.ordinary_word ? '<span class="sugg-tag sugg-warn" title="Και συνηθισμένη λέξη του βιβλίου: ο κανόνας θα ίσχυε και γι’ αυτήν">⚠️</span>' : '',
      s.glossary ? `<span class="sugg-tag sugg-conflict" title="Το Γλωσσάρι το γράφει αλλιώς">↔️ <span translate="no">${escHtml(s.glossary)}</span></span>` : '',
    ].join('');
    const books = (s.books || []).map((b) => escHtml(b.title)).join(', ');
    const src = escHtml(s.source);
    return `<tr>
      <td translate="no">${src}</td>
      <td><span translate="no">${escHtml(s.target)}</span> ${tags}</td>
      <td class="sugg-books" translate="no">${books}</td>
      <td style="text-align:center; white-space:nowrap">
        <button type="button" class="btn-icon-sm" data-source="${src}" onclick="acceptGlossarySuggestion(this.dataset.source)" title="Στο Γλωσσάρι" aria-label="Στο Γλωσσάρι">✓</button>
        <button type="button" class="btn-icon-sm" data-source="${src}" onclick="dismissGlossarySuggestion(this.dataset.source)" title="Όχι, να μην προταθεί ξανά" aria-label="Όχι, να μην προταθεί ξανά">✕</button>
      </td></tr>`;
  }).join('');
}

async function _acceptSuggestions(body) {
  try {
    const res = await fetch(`${API}/glossary/suggestions/accept`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to add the suggestions'));
    const data = await res.json();
    toast(`✅ ${data.added} όροι μπήκαν στο Γλωσσάρι.`, 'success');
    if (typeof loadGlossary === 'function') await loadGlossary();
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await loadGlossarySuggestions();
}

function acceptGlossarySuggestion(source) {
  return _acceptSuggestions({ sources: [source] });
}

function acceptAllSuggestions() {
  return _acceptSuggestions({ all: true });
}

async function dismissGlossarySuggestion(source) {
  try {
    const res = await fetch(`${API}/glossary/suggestions/dismiss`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources: [source] }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to dismiss the suggestion'));
  } catch (e) {
    toast(`❌ ${e.message}`, 'error');
  }
  await loadGlossarySuggestions();
}

// ── 💾 Backup and restore ──

function openBackupModal() {
  const modal = document.getElementById('backup-modal');
  if (modal) modal.style.display = 'flex';
}

function closeBackupModal() {
  const modal = document.getElementById('backup-modal');
  if (modal) modal.style.display = 'none';
}

function _sizeText(bytes) {
  const mb = Number(bytes || 0) / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`;
}

function _backupIdle() {
  for (const id of ['backup-start-btn', 'restore-start-btn']) {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = false;
  }
  const bar = document.getElementById('restore-bar');
  if (bar) bar.style.display = 'none';
}

function _pollBackupTask(taskId, statusId, onDone) {
  clearInterval(libState.pollers[statusId]);
  const tick = async () => {
    try {
      const res = await fetch(`${API}/backup/${encodeURIComponent(taskId)}`);
      if (!res.ok) throw new Error(await parseApiError(res, 'The task was not found'));
      const t = await res.json();
      if (t.state === 'running') {
        setDevicesStatus(statusId, `⏳ ${t.progress || 0}%…`);
        return;
      }
      clearInterval(libState.pollers[statusId]);
      _backupIdle();
      if (t.state === 'error') setDevicesStatus(statusId, `❌ ${t.error}`);
      else onDone(t);
    } catch (e) {
      clearInterval(libState.pollers[statusId]);
      _backupIdle();
      setDevicesStatus(statusId, `❌ ${e.message}`);
    }
  };
  libState.pollers[statusId] = setInterval(tick, 1500);
  tick();
}

async function startBackup() {
  const btn = document.getElementById('backup-start-btn');
  const dl = document.getElementById('backup-download-btn');
  if (dl) dl.style.display = 'none';
  if (btn) btn.disabled = true;
  try {
    const includeAudio = Boolean(document.getElementById('backup-audio')?.checked);
    const res = await fetch(`${API}/backup`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ include_audio: includeAudio }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Failed to start the backup'));
    const data = await res.json();
    libState.backupTask = data.task_id;
    setDevicesStatus('backup-status', '⏳ 0%…');
    _pollBackupTask(data.task_id, 'backup-status', (t) => {
      const r = t.result || {};
      const skipped = (r.skipped || []).length ? ` ${r.skipped.length} βιβλία που μεταφράζονται τώρα έμειναν έξω.` : '';
      setDevicesStatus('backup-status', `✅ Έτοιμο: ${r.books} βιβλία, ${_sizeText(t.size)}.${skipped}`);
      if (dl) dl.style.display = '';
    });
  } catch (e) {
    _backupIdle();
    setDevicesStatus('backup-status', `❌ ${e.message}`);
  }
}

function downloadBackup() {
  if (!libState.backupTask) return;
  saveFile(`${API}/backup/${encodeURIComponent(libState.backupTask)}/download`, 'BookApp-backup.zip');
}

function _uploadBackup(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}/backup/restore`);
    xhr.setRequestHeader('Content-Type', 'application/zip');
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : file.size);
    xhr.onload = () => resolve(new Response(xhr.responseText, {
      status: xhr.status, headers: { 'Content-Type': xhr.getResponseHeader('Content-Type') || 'application/json' },
    }));
    xhr.onerror = () => reject(new TypeError('Network error while uploading'));
    xhr.send(file);
  });
}

async function startRestore() {
  const input = document.getElementById('restore-file');
  const file = input && input.files && input.files[0];
  if (!file) {
    setDevicesStatus('restore-status', 'Διαλέξτε πρώτα το αρχείο του αντιγράφου (.zip).');
    return;
  }
  const btn = document.getElementById('restore-start-btn');
  const bar = document.getElementById('restore-bar');
  const fill = document.getElementById('restore-bar-fill');
  if (btn) btn.disabled = true;
  if (bar) bar.style.display = '';
  try {
    const res = await _uploadBackup(file, (loaded, total) => {
      const pct = total ? Math.round((loaded / total) * 100) : 0;
      if (fill) fill.style.width = `${pct}%`;
      setDevicesStatus('restore-status', `⬆️ Ανέβασμα: ${pct}%`);
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Restore failed'));
    const data = await res.json();
    setDevicesStatus('restore-status', '⏳ 0%…');
    _pollBackupTask(data.task_id, 'restore-status', (t) => {
      const r = t.result || {};
      const parts = [`✅ Επαναφέρθηκαν ${r.restored} βιβλία.`];
      if ((r.already_here || []).length) parts.push(`${r.already_here.length} υπήρχαν ήδη.`);
      if (r.glossary_added) parts.push(`${r.glossary_added} όροι μπήκαν στο Γλωσσάρι.`);
      setDevicesStatus('restore-status', parts.join(' '));
      if (typeof refreshHistory === 'function') refreshHistory();
    });
  } catch (e) {
    _backupIdle();
    setDevicesStatus('restore-status', `❌ ${e.message}`);
  }
}
