/* User accounts UI (BOOKAPP_AUTH=1): signed-in user bar, own account & password, user management for admins.
   Loaded after app.js; uses its globals (API, toast, escHtml, parseApiError, refreshHistory). Inert when accounts are off. */
'use strict';

const authState = {
  enabled: false,
  user: null,
  users: [],
  historyScope: 'mine',     // Session History of an admin: 'mine' | 'all' | <user id>
  pendingDelete: null,      // user id awaiting the delete confirmation
  tempPassword: '',
};

const AUTH_ROLE_LABELS = { admin: 'Διαχειριστής', user: 'Χρήστης' };

// A session that expired or was revoked (or a temporary password still to change) sends the browser to the login page.
(function installAuthFetchGuard() {
  if (typeof window === 'undefined' || typeof window.fetch !== 'function' || window.__bookappAuthGuard) return;
  const originalFetch = window.fetch.bind(window);
  window.__bookappAuthGuard = true;
  let redirecting = false;
  window.fetch = async (...args) => {
    const res = await originalFetch(...args);
    if (!redirecting && res && (res.status === 401 || res.status === 403)) {
      try {
        const data = await res.clone().json();
        if (data && (data.auth_required || data.password_change_required)) {
          redirecting = true;
          const here = window.location.pathname + window.location.search;
          window.location.href = data.password_change_required
            ? '/login?change=1'
            : (data.setup_required ? '/setup' : `/login?next=${encodeURIComponent(here)}`);
        }
      } catch (_) {}
    }
    return res;
  };
})();

function authIsRestrictedUser() {
  return Boolean(authState.enabled && authState.user && authState.user.role !== 'admin');
}

function authIsAdmin() {
  return Boolean(authState.enabled && authState.user && authState.user.role === 'admin');
}

function _authDate(ts) {
  if (!ts) return 'ποτέ';
  try {
    return new Date(ts * 1000).toLocaleString('el-GR', { dateStyle: 'short', timeStyle: 'short' });
  } catch (_) {
    return '';
  }
}

function _authUsageText(u) {
  const g = u || {};
  const req = Number(g.requests || 0);
  const tok = Number(g.total_tokens || 0);
  return req ? `${req.toLocaleString('el-GR')} αιτήματα · ${tok.toLocaleString('el-GR')} tokens` : 'καμία χρήση';
}

async function initAuthUi() {
  let st = null;
  try {
    const res = await fetch(`${API}/auth/status`);
    if (!res.ok) return;
    st = await res.json();
  } catch (_) {
    return;
  }
  if (!st || !st.enabled || !st.user) return;
  authState.enabled = true;
  authState.user = st.user;
  document.body.classList.add('auth-on');
  if (st.user.role === 'admin') document.body.classList.add('auth-admin');

  const label = document.getElementById('auth-user-label');
  if (label) label.textContent = st.user.username;
  const badge = document.getElementById('auth-role-badge');
  if (badge) badge.textContent = AUTH_ROLE_LABELS[st.user.role] || st.user.role;

  if (st.user.role !== 'admin') {
    // Shared settings (API keys, final quality check default) belong to the administrators
    document.querySelectorAll('.final-refinement-toggle').forEach((cb) => {
      cb.disabled = true;
      cb.title = 'Ρυθμίζεται από τον διαχειριστή';
    });
  } else {
    await loadHistoryOwnerFilter();
  }
}

// ── Session History filter (administrators) ─────────────────
async function loadHistoryOwnerFilter() {
  const sel = document.getElementById('history-owner-filter');
  if (!sel || !authIsAdmin()) return;
  try {
    const res = await fetch(`${API}/auth/users`);
    if (!res.ok) return;
    const data = await res.json();
    authState.users = Array.isArray(data.users) ? data.users : [];
  } catch (_) {
    return;
  }
  const keep = authState.historyScope;
  const others = authState.users.filter((u) => u.id !== authState.user.id);
  sel.innerHTML = '<option value="mine">Οι εργασίες μου</option><option value="all">Όλοι οι χρήστες</option>' +
    others.map((u) => `<option value="${escHtml(u.id)}">👤 ${escHtml(u.username)}</option>`).join('');
  sel.value = [...sel.options].some((o) => o.value === keep) ? keep : 'mine';
  authState.historyScope = sel.value;
}

function onHistoryOwnerFilterChange(value) {
  authState.historyScope = value || 'mine';
  refreshHistory();
}

// ── Own account ─────────────────────────────────────────────
async function openAccountModal() {
  const modal = document.getElementById('account-modal');
  if (!modal) return;
  ['account-current-password', 'account-new-password', 'account-new-password2'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  modal.style.display = 'flex';
  const box = document.getElementById('account-summary');
  try {
    const res = await fetch(`${API}/auth/me`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Δεν φορτώθηκαν τα στοιχεία λογαριασμού'));
    const data = await res.json();
    const u = data.user || {};
    box.innerHTML =
      `<div><strong>${escHtml(u.username || '')}</strong> · ${escHtml(AUTH_ROLE_LABELS[u.role] || u.role || '')}</div>` +
      `<div class="auth-muted">Τελευταία σύνδεση: ${escHtml(_authDate(u.last_login))}</div>` +
      `<div class="auth-muted">Gemini σήμερα: ${escHtml(_authUsageText(data.gemini_usage_today))}</div>`;
  } catch (err) {
    box.textContent = err.message;
  }
}

function closeAccountModal() {
  const modal = document.getElementById('account-modal');
  if (modal) modal.style.display = 'none';
}

async function submitPasswordChange() {
  const current = document.getElementById('account-current-password').value;
  const next = document.getElementById('account-new-password').value;
  if (next !== document.getElementById('account-new-password2').value) {
    toast('Οι δύο νέοι κωδικοί δεν ταιριάζουν.', 'error');
    return;
  }
  const btn = document.getElementById('account-save-password-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API}/auth/change-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Ο κωδικός δεν άλλαξε'));
    toast('🔒 Ο κωδικός άλλαξε. Οι άλλες συσκευές σας αποσυνδέθηκαν.', 'success');
    closeAccountModal();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function logoutAccount() {
  try {
    await fetch(`${API}/auth/logout`, { method: 'POST' });
  } catch (_) {}
  window.location.href = '/login';
}

// ── User management (administrators) ────────────────────────
function _usersError(msg) {
  const el = document.getElementById('users-error');
  if (!el) return;
  el.textContent = msg ? `❌ ${msg}` : '';
  el.style.display = msg ? '' : 'none';
}

function _showTempPassword(username, password) {
  authState.tempPassword = password || '';
  const box = document.getElementById('users-temp-box');
  const text = document.getElementById('users-temp-text');
  if (!box || !text) return;
  if (!password) {
    box.style.display = 'none';
    return;
  }
  text.innerHTML = `🔑 Προσωρινός κωδικός για «<strong>${escHtml(username)}</strong>»: ` +
    `<code class="auth-temp-code">${escHtml(password)}</code><br>` +
    'Δώστε τον στον χρήστη· στην πρώτη σύνδεση θα επιλέξει δικό του. <strong>Δεν θα εμφανιστεί ξανά.</strong>';
  box.style.display = '';
}

async function copyTempPassword() {
  if (!authState.tempPassword) return;
  try {
    await navigator.clipboard.writeText(authState.tempPassword);
    toast('📋 Αντιγράφηκε.', 'success');
  } catch (_) {
    toast('Η αντιγραφή δεν επιτρέπεται από τον browser — επιλέξτε τον κωδικό και αντιγράψτε τον.', 'info');
  }
}

async function openUsersModal() {
  const modal = document.getElementById('users-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  _usersError('');
  _showTempPassword('', '');
  cancelDeleteUser();
  await loadUsersPanel();
}

function closeUsersModal() {
  const modal = document.getElementById('users-modal');
  if (modal) modal.style.display = 'none';
  authState.tempPassword = '';
}

function renderUsersList(users, meId) {
  const list = document.getElementById('users-list');
  if (!list) return;
  if (!users.length) {
    list.innerHTML = '<p class="auth-muted">Δεν υπάρχουν χρήστες.</p>';
    return;
  }
  list.innerHTML = users.map((u) => {
    const isMe = u.id === meId;
    const isAdmin = u.role === 'admin';
    const flags = [
      `<span class="auth-pill ${isAdmin ? 'auth-pill-admin' : ''}">${escHtml(AUTH_ROLE_LABELS[u.role] || u.role)}</span>`,
      u.disabled ? '<span class="auth-pill auth-pill-off">Απενεργοποιημένος</span>' : '',
      u.must_change ? '<span class="auth-pill auth-pill-warn">Προσωρινός κωδικός</span>' : '',
      isMe ? '<span class="auth-pill">εσείς</span>' : '',
    ].join('');
    const actions = [
      `<button type="button" class="btn btn-sm btn-secondary" data-user-id="${escHtml(u.id)}" data-role="${isAdmin ? 'user' : 'admin'}" data-username="${escHtml(u.username)}" onclick="toggleUserRole(this.dataset.userId, this.dataset.role, this.dataset.username)">${isAdmin ? '⬇️ Αφαίρεση δικαιωμάτων διαχειριστή' : '⭐ Κάνε διαχειριστή'}</button>`,
      `<button type="button" class="btn btn-sm btn-secondary" data-user-id="${escHtml(u.id)}" data-username="${escHtml(u.username)}" onclick="resetUserPassword(this.dataset.userId, this.dataset.username)">🔑 Επαναφορά κωδικού</button>`,
      `<button type="button" class="btn btn-sm btn-secondary" data-user-id="${escHtml(u.id)}" data-username="${escHtml(u.username)}" onclick="signOutUserEverywhere(this.dataset.userId, this.dataset.username)">🚪 Αποσύνδεση παντού</button>`,
      isMe ? '' : `<button type="button" class="btn btn-sm btn-secondary" data-user-id="${escHtml(u.id)}" data-disabled="${u.disabled ? '0' : '1'}" onclick="toggleUserDisabled(this.dataset.userId, this.dataset.disabled)">${u.disabled ? '✅ Ενεργοποίηση' : '⏸️ Απενεργοποίηση'}</button>`,
      isMe ? '' : `<button type="button" class="btn btn-sm btn-secondary auth-danger" data-user-id="${escHtml(u.id)}" data-username="${escHtml(u.username)}" data-jobs="${Number(u.jobs) || 0}" onclick="askDeleteUser(this.dataset.userId, this.dataset.username, this.dataset.jobs)">🗑️ Διαγραφή</button>`,
    ].join('');
    return `<div class="auth-user-card${u.disabled ? ' auth-user-disabled' : ''}">
      <div class="auth-user-head"><strong>${escHtml(u.username)}</strong>${flags}</div>
      <div class="auth-muted">Τελευταία σύνδεση: ${escHtml(_authDate(u.last_login))} · Εργασίες: ${Number(u.jobs) || 0} · Ενεργές συνδέσεις: ${Number(u.active_sessions) || 0}</div>
      <div class="auth-muted">Gemini σήμερα: ${escHtml(_authUsageText(u.gemini_usage_today))}</div>
      <div class="auth-user-actions">${actions}</div>
    </div>`;
  }).join('');
}

async function loadUsersPanel() {
  try {
    const res = await fetch(`${API}/auth/users`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Δεν φορτώθηκαν οι χρήστες'));
    const data = await res.json();
    authState.users = Array.isArray(data.users) ? data.users : [];
    renderUsersList(authState.users, data.me);
  } catch (err) {
    _usersError(err.message);
  }
  await loadUsersAudit();
  await loadHistoryOwnerFilter();
}

async function loadUsersAudit() {
  const list = document.getElementById('users-audit-list');
  if (!list) return;
  const labels = {
    user_created: 'δημιούργησε τον χρήστη', role_changed: 'άλλαξε τον ρόλο του', user_disabled: 'απενεργοποίησε τον',
    user_enabled: 'ενεργοποίησε τον', user_deleted: 'διέγραψε τον', password_reset: 'επανέφερε τον κωδικό του',
    password_changed: 'άλλαξε τον κωδικό του', signed_out_everywhere: 'αποσύνδεσε παντού τον',
  };
  try {
    const res = await fetch(`${API}/auth/audit?limit=40`);
    if (!res.ok) return;
    const data = await res.json();
    const entries = Array.isArray(data.entries) ? data.entries : [];
    list.innerHTML = entries.length ? entries.map((e) =>
      `<li><span class="auth-muted">${escHtml(_authDate(e.ts))}</span> · <strong>${escHtml(e.actor || '—')}</strong> ` +
      `${escHtml(labels[e.action] || e.action)} <strong>${escHtml(e.target || '')}</strong>` +
      `${e.detail ? ` <span class="auth-muted">(${escHtml(e.detail)})</span>` : ''}</li>`).join('')
      : '<li class="auth-muted">Καμία ενέργεια ακόμη.</li>';
  } catch (_) {}
}

async function createUserAccount() {
  const nameEl = document.getElementById('users-new-username');
  const roleEl = document.getElementById('users-new-role');
  const pwEl = document.getElementById('users-new-password');
  const username = (nameEl.value || '').trim();
  if (!username) {
    _usersError('Γράψτε ένα όνομα χρήστη.');
    return;
  }
  _usersError('');
  const btn = document.getElementById('users-create-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`${API}/auth/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, role: roleEl.value, password: pwEl.value || null }),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Ο χρήστης δεν δημιουργήθηκε'));
    const data = await res.json();
    _showTempPassword(data.user.username, data.temporary_password || pwEl.value);
    nameEl.value = '';
    pwEl.value = '';
    roleEl.value = 'user';
    toast(`👤 Δημιουργήθηκε ο χρήστης «${data.user.username}».`, 'success');
    await loadUsersPanel();
  } catch (err) {
    _usersError(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _usersAction(fetchPromise, fallback) {
  _usersError('');
  try {
    const res = await fetchPromise;
    if (!res.ok) throw new Error(await parseApiError(res, fallback));
    const data = await res.json();
    await loadUsersPanel();
    return data;
  } catch (err) {
    _usersError(err.message);
    return null;
  }
}

async function toggleUserRole(userId, role, username) {
  const doConfirm = typeof window.confirm === 'function' ? window.confirm : () => true;
  const question = role === 'admin'
    ? `Ο/Η «${username}» θα έχει τα ΙΔΙΑ δικαιώματα με εσάς (χρήστες, API keys, όλες οι εργασίες). Συνέχεια;`
    : `Να αφαιρεθούν τα δικαιώματα διαχειριστή από «${username}»;`;
  if (!doConfirm(question)) return;
  const data = await _usersAction(fetch(`${API}/auth/users/${encodeURIComponent(userId)}/role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  }), 'Ο ρόλος δεν άλλαξε');
  if (data && userId === authState.user.id && role !== 'admin') window.location.reload();  // own rights removed
}

async function toggleUserDisabled(userId, disabledFlag) {
  await _usersAction(fetch(`${API}/auth/users/${encodeURIComponent(userId)}/disabled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disabled: disabledFlag === '1' }),
  }), 'Η αλλαγή δεν αποθηκεύτηκε');
}

async function resetUserPassword(userId, username) {
  const doConfirm = typeof window.confirm === 'function' ? window.confirm : () => true;
  if (!doConfirm(`Νέος προσωρινός κωδικός για «${username}»; Θα αποσυνδεθεί από όλες τις συσκευές.`)) return;
  const data = await _usersAction(fetch(`${API}/auth/users/${encodeURIComponent(userId)}/reset-password`, {
    method: 'POST',
  }), 'Ο κωδικός δεν επαναφέρθηκε');
  if (data) _showTempPassword(username, data.temporary_password);
}

async function signOutUserEverywhere(userId, username) {
  const data = await _usersAction(fetch(`${API}/auth/users/${encodeURIComponent(userId)}/sign-out`, {
    method: 'POST',
  }), 'Η αποσύνδεση απέτυχε');
  if (data) toast(`🚪 «${username}»: ${data.signed_out_sessions} συνδέσεις τερματίστηκαν.`, 'info');
}

function askDeleteUser(userId, username, jobs) {
  authState.pendingDelete = userId;
  const box = document.getElementById('users-delete-box');
  const text = document.getElementById('users-delete-text');
  if (!box || !text) return;
  text.innerHTML = `🗑️ Διαγραφή του λογαριασμού «<strong>${escHtml(username)}</strong>» (${Number(jobs) || 0} εργασίες). ` +
    'Τι να γίνει με τις εργασίες του;';
  box.style.display = '';
}

function cancelDeleteUser() {
  authState.pendingDelete = null;
  const box = document.getElementById('users-delete-box');
  if (box) box.style.display = 'none';
}

async function confirmDeleteUser(jobsMode) {
  const userId = authState.pendingDelete;
  if (!userId) return;
  const mode = jobsMode === 'delete' ? 'delete' : 'transfer';
  cancelDeleteUser();
  const data = await _usersAction(fetch(`${API}/auth/users/${encodeURIComponent(userId)}?jobs=${mode}`, {
    method: 'DELETE',
  }), 'Ο χρήστης δεν διαγράφηκε');
  if (data) {
    toast(mode === 'delete'
      ? `Ο χρήστης διαγράφηκε μαζί με ${data.job_count} εργασίες.`
      : `Ο χρήστης διαγράφηκε· ${data.job_count} εργασίες μεταφέρθηκαν σε εσάς.`, 'info');
    refreshHistory();
  }
}

if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAuthUi);
  else initAuthUi();
}
