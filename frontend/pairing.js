/* Device pairing UI (opt-in, BOOKAPP_PAIRING=1) — loaded after app.js; uses its globals (API, state, toast, escHtml, parseApiError, ...). */
'use strict';

// ── Device pairing (opt-in, BOOKAPP_PAIRING=1) ─────────────
async function loadPairingPanel() {
  const section = document.getElementById('pairing-section');
  if (!section) return;
  try {
    const res = await fetch(`${API}/pairing`);
    if (!res.ok) { section.style.display = 'none'; return; }
    const data = await res.json();
    if (!data.enabled) { section.style.display = 'none'; return; }
    section.style.display = '';
    const list = document.getElementById('pairing-devices');
    list.innerHTML = '';
    if (!data.devices.length) {
      const li = document.createElement('li');
      li.textContent = 'Καμία συνδεδεμένη συσκευή ακόμη.';
      list.appendChild(li);
    }
    data.devices.forEach((d) => {
      const li = document.createElement('li');
      const when = d.last_seen ? new Date(d.last_seen * 1000).toLocaleString('el-GR') : '';
      li.textContent = `${d.name}${d.id === data.this_device_id ? ' (αυτή η συσκευή)' : ''} — τελευταία χρήση ${when} `;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-outline';
      btn.textContent = 'Ανάκληση';
      btn.addEventListener('click', () => revokePairedDevice(d.id));
      li.appendChild(btn);
      list.appendChild(li);
    });
  } catch (_) {
    section.style.display = 'none';
  }
}

async function createPairingLink() {
  try {
    const res = await fetch(`${API}/pairing/links`, { method: 'POST' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Δεν δημιουργήθηκε σύνδεσμος'));
    const data = await res.json();
    const out = document.getElementById('pairing-link-output');
    out.value = data.url;
    document.getElementById('pairing-link-box').style.display = 'flex';
    out.select();
  } catch (err) {
    toast(err.message || 'Σφάλμα', 'error');
  }
}

async function copyPairingLink() {
  const out = document.getElementById('pairing-link-output');
  try {
    await navigator.clipboard.writeText(out.value);
    toast('📋 Ο σύνδεσμος αντιγράφηκε.', 'success');
  } catch (_) {
    out.select();
  }
}

async function revokePairedDevice(id) {
  try {
    const res = await fetch(`${API}/pairing/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Η ανάκληση απέτυχε'));
    toast('Η συσκευή ανακλήθηκε.', 'info');
    loadPairingPanel();
  } catch (err) {
    toast(err.message || 'Σφάλμα', 'error');
  }
}
