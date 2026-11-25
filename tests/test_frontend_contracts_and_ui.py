"""
test_frontend_contracts_and_ui.py - Frontend <-> Backend Contract, Security & Node.js Runtime UI Suite.
Tests:
Layer A (Static Contract & Security Guards):
1. Strict (HTTP method, path) alignment against live FastAPI app.routes (not just path regexes).
2. JSON payload keys sent by frontend/app.js match Pydantic request models in backend/main.py.
3. Zero unsafe inline JS attribute quoting (e.g. onclick="fn('${escHtml(...)}')") & dynamic API origin.
4. Valid JS syntax verified via `node --check frontend/app.js` (when Node is installed).

Layer B (Real Node.js VM Runtime DOM & State Behavior Tests):
5. parseApiError handles FastAPI 422 array details & non-JSON 502 HTML responses (never '[object Object]').
6. renderGlossaryTable safely renders single-quote terms ("Murphy's law") using data-source attributes.
7. processFile('ab') rejects .cbz/.zip & reports extensionless filenames cleanly.
8. uploadFile('ab') does NOT enable #tr-direct-polish-btn.
9. removeFile() closes active EventSource & clears pollInterval timers.
10. sendToAudiobook() resets stale audiobook progress, updates icon, and shows selected file via classList.
11. refreshHistory() handles HTTP 500 JSON error without throwing TypeError: jobs.map is not a function.
12. connectSSE() tolerates malformed JSON event payloads without throwing.
"""
try:
    import _sandbox_guard  # noqa: F401  (never run against the real jobs, keys or port 8000)
except ImportError:
    from tests import _sandbox_guard  # noqa: F401

import json
import os
import sys
sys.path.insert(0, ".")
import re
import shutil
import subprocess
import unittest
from pathlib import Path


def _frontend_js_source() -> str:
    """All frontend scripts (app.js first, then the feature modules loaded after it)."""
    files = [Path("frontend/app.js")] + sorted(p for p in Path("frontend").glob("*.js") if p.name != "app.js")
    return "\n".join(f.read_text(encoding="utf-8") for f in files)

from fastapi.routing import APIRoute
from backend.main import app


class TestFrontendContractsAndUI(unittest.TestCase):

    def test_1_strict_http_method_and_route_alignment(self):
        print("-> 1. Testing strict (HTTP method, path) alignment between app.js and FastAPI app.routes...")
        js_src = _frontend_js_source()

        # Collect real (methods_set, compiled_regex) from FastAPI app.routes
        fastapi_routes = []
        for route in app.routes:
            if isinstance(route, APIRoute) and route.path.startswith("/api"):
                short_path = route.path[len("/api"):]
                pat = "^" + re.sub(r"\{[^}]+\}", r"[^/?]+", short_path) + "$"
                fastapi_routes.append((set(route.methods or set()), re.compile(pat), route.path))

        # Extract every fetch(`${API}/...`, { method: '...' }) call
        fetch_pattern = re.compile(
            r'fetch\(\s*`\$\{API\}(/[^`]+)`\s*(?:,\s*\{([^}]*)\})?',
            re.DOTALL,
        )
        matches = fetch_pattern.findall(js_src)
        self.assertGreaterEqual(len(matches), 20, "Expected at least 20 fetch() API calls in frontend/app.js")

        for raw_path, opts in matches:
            m_match = re.search(r"method\s*:\s*['\"]([A-Z]+)['\"]", opts or "")
            method = m_match.group(1) if m_match else "GET"
            norm_path = re.sub(r"\$\{[^}]+\}", "PLACEHOLDER", raw_path).split("?")[0]

            matched = any(
                (method in r_methods and r_pat.match(norm_path))
                for r_methods, r_pat, _ in fastapi_routes
            )
            self.assertTrue(
                matched,
                f"Frontend calls {method} ${{API}}{raw_path} which has NO matching FastAPI route/method!",
            )
        print(f"   Strict (method, route) alignment: OK ({len(matches)} fetch calls verified)")

    def test_2_frontend_json_payloads_match_pydantic_models(self):
        print("-> 2. Testing frontend JSON payload keys match FastAPI Pydantic models...")
        js_src = _frontend_js_source()
        from backend.main import (
            TranslateRequest,
            AudiobookRequest,
            PolishRequest,
            UpdateTextRequest,
            GlossaryTermRequest,
            GenreDetectionRequest,
            QueueAddRequest,
            QueueStartRequest,
            QueueAutoStartRequest,
            SettingsRequest,
        )

        # Map endpoint path substring -> Pydantic model
        endpoint_models = {
            "/translate": TranslateRequest,
            "/audiobook": AudiobookRequest,
            "/polish": PolishRequest,
            "/glossary": GlossaryTermRequest,
            "/detect-genre": GenreDetectionRequest,
            "/queue/add": QueueAddRequest,
            "/queue/start": QueueStartRequest,
            "/queue/auto-start": QueueAutoStartRequest,
            "/settings": SettingsRequest,
        }

        # Verify PolishRequest explicitly accepts job_id=None (Direct Editor contract)
        inst = PolishRequest(job_id=None, text="hello", style="formal")
        self.assertIsNone(inst.job_id)

        # Verify UpdateTextRequest accepts translated_text
        ut = UpdateTextRequest(translated_text="edited")
        self.assertEqual(ut.translated_text, "edited")

        # For each JSON.stringify({ ... }) body inside a fetch() to a known endpoint, verify keys exist in Pydantic model
        for ep, model in endpoint_models.items():
            model_fields = set(model.model_fields.keys())
            pat = re.compile(
                rf'fetch\(\s*`\$\{{API\}}{re.escape(ep)}`\s*,\s*\{{[\s\S]{{0,300}}?JSON\.stringify\(\{{([\s\S]{{0,700}}?)\}}\)',
            )
            found = pat.findall(js_src)
            self.assertGreaterEqual(len(found), 1, f"Expected JSON.stringify fetch call to {ep} in app.js")
            for obj_body in found:
                keys = re.findall(r"(?:^|[,\n])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", obj_body)
                unknown = [k for k in keys if k not in model_fields]
                self.assertEqual(
                    unknown,
                    [],
                    f"Frontend sends unknown keys {unknown} to {ep} (model fields: {sorted(model_fields)})",
                )
        print("   Frontend JSON payload <-> Pydantic schema alignment: OK")

    def test_3_frontend_security_and_static_hygiene(self):
        print("-> 3. Testing frontend security hygiene (no inline single-quote XSS, dynamic API origin)...")
        js_src = _frontend_js_source()

        # Must not interpolate escHtml(...) inside single-quoted JS string inside onclick="..."
        unsafe_onclick = re.findall(r'onclick="[^"]*\'[^\']*\$\{escHtml\([^)]+\)\}[^\']*\'[^"]*"', js_src)
        self.assertEqual(
            unsafe_onclick,
            [],
            f"Unsafe inline JS onclick quoting detected (breaks on single quotes / XSS risk): {unsafe_onclick}",
        )

        # Must use dynamic origin instead of bare hardcoded localhost
        self.assertNotIn("const API = 'http://localhost:8000/api';", js_src)
        self.assertIn("window.location.origin", js_src)

        # Verify JS syntax with node --check if Node is available
        node_bin = shutil.which("node")
        if node_bin:
            for js_file in sorted(Path("frontend").glob("*.js")):
                res = subprocess.run([node_bin, "--check", str(js_file)], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"JavaScript syntax error in {js_file}:\n{res.stderr}")
        print("   Frontend security & JS syntax check: OK")

    def test_4_node_runtime_dom_and_state_behavior(self):
        print("-> 4. Testing frontend/app.js runtime DOM & state logic inside Node.js VM...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")

        harness = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

// Minimal DOM mock for testing app.js functions deterministically
const elements = new Map();
function makeEl(id) {
  const classes = new Set();
  return {
    id,
    value: '',
    textContent: '',
    innerHTML: '',
    checked: false,
    disabled: false,
    href: '',
    title: '',
    options: [],
    dataset: {},
    style: { display: '' },
    className: '',
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; },
    closest: () => null,
    addEventListener: () => {},
    focus: () => {},
    pause: () => {},
    play: () => Promise.resolve(),
    querySelector: () => null,
    querySelectorAll: () => [],
  };
}
function getEl(id) {
  if (!elements.has(id)) elements.set(id, makeEl(id));
  return elements.get(id);
}

const toasts = [];
let sseClosed = 0;
let intervalsCleared = 0;
let nextFetchImpl = async () => ({ ok: true, status: 200, json: async () => ({}) });

class MockEventSource {
  constructor(url) { this.url = url; this.closed = false; }
  close() { this.closed = true; sseClosed += 1; }
}
class MockFormData {
  constructor() { this.entries = []; }
  append(k, v) { this.entries.push([k, v]); }
}

const ctx = vm.createContext({
  console,
  setTimeout: () => 1,
  clearTimeout: () => {},
  setInterval: () => 42,
  clearInterval: () => { intervalsCleared += 1; },
  EventSource: MockEventSource,
  FormData: MockFormData,
  confirm: () => true,
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: (...args) => nextFetchImpl(...args),
  window: {
    location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' },
    addEventListener: () => {},
  },
  document: {
    documentElement: makeEl('html'),
    getElementById: (id) => getEl(id),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    createElement: (tag) => makeEl(tag),
    body: { appendChild: () => {} },
  },
});

const src = fs.readFileSync('frontend/app.js', 'utf8');
vm.runInContext(src + '\nglobalThis.__exports = { API, state, glossaryState };', ctx);
const { API: resolvedAPI, state: appState, glossaryState: appGlossaryState } = ctx.__exports;
// Override toast to capture UI messages
ctx.toast = (msg, type) => toasts.push({ msg, type });

(async () => {
  // 1. Dynamic API origin resolves from window.location.origin
  assert.strictEqual(resolvedAPI, 'http://127.0.0.1:8000/api');

  // 2. parseApiError formats FastAPI 422 array detail & non-JSON 502 cleanly
  const msg422 = await ctx.parseApiError({
    status: 422,
    json: async () => ({ detail: [{ msg: 'Field required' }, { msg: 'Invalid format' }] }),
  }, 'Fallback');
  assert.strictEqual(msg422, 'Field required; Invalid format');
  assert(!msg422.includes('[object Object]'));

  const msg502 = await ctx.parseApiError({
    status: 502,
    json: async () => { throw new SyntaxError('Unexpected token <'); },
  }, 'Upload failed');
  assert.strictEqual(msg502, 'Upload failed (HTTP 502)');

  // 3. renderGlossaryTable safely renders single-quote source term using data-source
  appGlossaryState.items = [{ source: "Murphy's law", target: "Νόμος του Μέρφι", category: "general" }];
  appGlossaryState.counts = { all: 1, technical: 0, literary: 0, general: 1 };
  ctx.renderGlossaryTable();
  const tbodyHtml = getEl('glossary-tbody').innerHTML;
  assert(tbodyHtml.includes('data-source="Murphy&#39;s law"'), `Missing safe data-source attribute: ${tbodyHtml}`);
  assert(tbodyHtml.includes('onclick="deleteGlossaryRule(this.dataset.source)"'));

  // 4. processFile('ab') rejects .cbz and handles extensionless filenames cleanly
  toasts.length = 0;
  await ctx.processFile({ name: 'manga.cbz', size: 1024 }, 'ab');
  assert(toasts.some(t => t.type === 'error' && t.msg.includes('.cbz')));
  toasts.length = 0;
  await ctx.processFile({ name: 'README', size: 1024 }, 'tr');
  assert(toasts.some(t => t.type === 'error' && t.msg.includes('(no extension)')));

  // 5. uploadFile('ab') must NOT enable #tr-direct-polish-btn
  getEl('tr-direct-polish-btn').disabled = true;
  nextFetchImpl = async (url) => {
    if (url.endsWith('/upload')) {
      return { ok: true, status: 200, json: async () => ({ job_id: 'ab-job-1', file_type: 'pdf', estimated_pages: 5, detected_language: 'greek', is_comic: false }) };
    }
    return { ok: true, status: 200, json: async () => ([]) };
  };
  await ctx.uploadFile('ab', { name: 'novel.pdf', size: 1048576 });
  assert.strictEqual(getEl('tr-direct-polish-btn').disabled, true, 'Audiobook upload falsely enabled Translate Direct Polish button!');

  // 6. removeFile('tr') closes active SSE & clears pollInterval
  appState.tr.sse = new MockEventSource('http://127.0.0.1:8000/api/progress/x');
  appState.tr.pollInterval = 42;
  const beforeClose = sseClosed;
  const beforeClear = intervalsCleared;
  ctx.removeFile('tr');
  assert.strictEqual(sseClosed, beforeClose + 1, 'removeFile did not close active SSE!');
  assert.strictEqual(intervalsCleared, beforeClear + 1, 'removeFile did not clear pollInterval!');
  assert.strictEqual(appState.tr.sse, null);
  assert.strictEqual(appState.tr.pollInterval, null);

  // 7. sendToAudiobook() resets stale progress, copies icon, and uses classList.add('visible')
  appState.tr.jobId = 'tr-job-99';
  getEl('tr-file-icon').textContent = '📗';
  getEl('tr-file-name').textContent = 'book.epub';
  getEl('ab-result-card').classList.add('visible');
  ctx.sendToAudiobook();
  assert.strictEqual(getEl('ab-file-icon').textContent, '📗');
  assert.strictEqual(getEl('ab-selected-file').classList.contains('visible'), true);
  assert.strictEqual(getEl('ab-result-card').classList.contains('visible'), false, 'Stale audiobook result card was not cleared!');

  // 8. refreshHistory() survives HTTP 500 JSON error without throwing jobs.map TypeError
  nextFetchImpl = async () => ({ ok: false, status: 500, json: async () => ({ detail: 'Internal error' }) });
  await ctx.refreshHistory();

  // 9. connectSSE() ignores malformed JSON payload without crashing
  ctx.connectSSE('tr', 'job-sse-bad');
  appState.tr.sse.onmessage({ data: '{broken-json' });
  ctx.stopJobTracking('tr');

  // 10. Batch "Download All (ZIP)" stays disabled until ALL translations are completed,
  //     while any individually finished item remains immediately downloadable.
  ctx.renderBatchQueue({
    items: [
      { job_id: 'j1', file_name: 'a.pdf', output_format: 'pdf', layout_mode: 'standard', status: 'done', progress: 100, has_output: true },
      { job_id: 'j2', file_name: 'b.pdf', output_format: 'pdf', layout_mode: 'standard', status: 'running', progress: 40, has_output: false },
    ],
    is_running: true,
    paused: false,
    auto_start: false,
    is_mixed: false,
    done_count: 1,
    queued_count: 0,
    total_count: 2,
    max_items: 20,
  });
  const dlAll = getEl('btn-queue-download-all');
  assert.strictEqual(dlAll.getAttribute('aria-disabled'), 'true', 'Download All must be disabled while batch is still running!');
  assert.strictEqual(dlAll.href, '#', 'Download All href must be # while incomplete!');
  assert.strictEqual(dlAll.getAttribute('download'), undefined, 'Download attribute must be removed while incomplete!');
  assert.strictEqual(dlAll.style.pointerEvents, 'none');
  // Finished item j1 MUST remain downloadable even while j2 is still running/queued
  assert(getEl('tr-queue-list').innerHTML.includes('/download/j1'), 'Finished item must remain downloadable while other items are still in queue!');
  assert(!getEl('tr-queue-list').innerHTML.includes('/download/j2'), 'Unfinished item must NOT have a download link!');

  // Single-file downloadOutput('tr') blocks only when THAT translation is still running
  appState.tr.jobId = 'j1';
  appState.tr.status = 'running';
  ctx.window.location.href = '';
  toasts.length = 0;
  await ctx.downloadOutput('tr');
  assert.strictEqual(ctx.window.location.href, '', 'downloadOutput must NOT navigate while that translation is running!');
  assert(toasts.some(t => t.type === 'info' && t.msg.includes('completed')));

  appState.tr.status = 'done';
  await ctx.downloadOutput('tr');
  assert(ctx.window.location.href.includes('/download/j1'), 'Finished single translation must be downloadable even if batch has queued items!');

  // Once ALL items are done (2/2, not running, 0 queued), Download All (ZIP) MUST be enabled
  ctx.renderBatchQueue({
    items: [
      { job_id: 'j1', file_name: 'a.pdf', output_format: 'pdf', layout_mode: 'standard', status: 'done', progress: 100, has_output: true },
      { job_id: 'j2', file_name: 'b.pdf', output_format: 'pdf', layout_mode: 'standard', status: 'done', progress: 100, has_output: true },
    ],
    is_running: false,
    paused: false,
    auto_start: false,
    is_mixed: false,
    done_count: 2,
    queued_count: 0,
    total_count: 2,
    max_items: 20,
  });
  assert.strictEqual(dlAll.getAttribute('aria-disabled'), 'false', 'Download All must be enabled once all translations are completed!');
  assert(dlAll.href.endsWith('/queue/download-all'));
  assert.strictEqual(dlAll.getAttribute('download'), 'BookApp_Batch_Translated.zip');
  assert.strictEqual(dlAll.style.pointerEvents, '');
  assert(getEl('tr-queue-list').innerHTML.includes('/download/j1'));
  assert(getEl('tr-queue-list').innerHTML.includes('/download/j2'));

  // Clearing queue hides & disables Download All cleanly
  ctx.renderBatchQueue({
    items: [],
    is_running: false,
    paused: false,
    auto_start: false,
    is_mixed: false,
    done_count: 0,
    queued_count: 0,
    total_count: 0,
    max_items: 20,
  });
  assert.strictEqual(dlAll.style.display, 'none');
  assert.strictEqual(dlAll.getAttribute('aria-disabled'), 'true');

  // 11. Global Basic vs Advanced UI Modes behavior
  const store = {};
  ctx.localStorage.setItem = (k, v) => { store[k] = String(v); };
  ctx.localStorage.getItem = (k) => store[k] || null;

  ctx.setAppMode('basic');
  assert.strictEqual(store['bookapp_ui_mode'], 'basic');
  assert.strictEqual(getEl('tr-ai-polish').checked, true, 'Basic mode must enable Translation AI Polish by default');
  assert.strictEqual(getEl('ab-ai-polish').checked, true, 'Basic mode must enable Audiobook AI Polish by default');
  assert.strictEqual(getEl('btn-mode-basic').classList.contains('active'), true);
  assert.strictEqual(getEl('btn-mode-advanced').classList.contains('active'), false);
  assert(getEl('tr-start-btn').textContent.includes('(1-Click)'));
  assert(getEl('ab-start-btn').textContent.includes('(1-Click)'));

  ctx.setAppMode('advanced');
  assert.strictEqual(store['bookapp_ui_mode'], 'advanced');
  assert.strictEqual(getEl('btn-mode-basic').classList.contains('active'), false);
  assert.strictEqual(getEl('btn-mode-advanced').classList.contains('active'), true);
  assert.strictEqual(getEl('tr-start-btn').textContent, '🌐 Start Translation');
  assert.strictEqual(getEl('ab-start-btn').textContent, '🎧 Generate Audiobook');

  // 12. Live Multi-Key Pool Badge rendering (updateNavGeminiBadge)
  ctx.updateNavGeminiBadge({ total_keys: 4, available_keys: 4, all_exhausted: false });
  assert.strictEqual(getEl('nav-gemini-quota-badge').textContent, '🟢 4/4 Keys');

  ctx.updateNavGeminiBadge({ total_keys: 4, available_keys: 2, all_exhausted: false });
  assert.strictEqual(getEl('nav-gemini-quota-badge').textContent, '🟡 2/4 Keys');

  ctx.updateNavGeminiBadge({ total_keys: 4, available_keys: 0, all_exhausted: true });
  assert.strictEqual(getEl('nav-gemini-quota-badge').textContent, '⏳ Cooldown');

  ctx.updateNavGeminiBadge({ total_keys: 0, available_keys: 0, all_exhausted: false });
  assert.strictEqual(getEl('nav-gemini-quota-badge').textContent, '🆓 Free Mode');

  // 13. Download M4B calls downloadOutput('ab', 'm4b') and blocks if running
  appState.ab.jobId = 'ab-job-42';
  appState.ab.status = 'running';
  ctx.window.location.href = '';
  toasts.length = 0;
  await ctx.downloadOutput('ab');
  assert.strictEqual(ctx.window.location.href, '', 'downloadOutput must block while audiobook is running');
  assert(toasts.some(t => t.type === 'info' && t.msg.includes('audiobook generation is completed')));

  appState.ab.status = 'done';
  ctx.window.location.href = '';
  ctx.downloadOutputM4b();
  assert.strictEqual(ctx.window.location.href, 'http://127.0.0.1:8000/api/download/ab-job-42?format=m4b');

  // 14. 1-Click Copy Translated Text to clipboard
  appState.tr.jobId = 'tr-job-1';
  getEl('tr-copy-btn').innerHTML = '📋 Αντιγραφή Κειμένου';
  nextFetchImpl = async (url) => {
    if (url.includes('/text')) {
      return { ok: true, status: 200, json: async () => ({ translated_text: 'Αυτό είναι το μεταφρασμένο κείμενο.', original_text: 'This is the original text.' }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  await ctx.copyTranslatedText();
  assert.strictEqual(getEl('tr-copy-btn').innerHTML, '✅ Αντιγράφηκε!');

  // 15. Audiobook Duration Estimation in uploadFile('ab')
  nextFetchImpl = async (url) => {
    if (url.endsWith('/upload')) {
      return { ok: true, status: 200, json: async () => ({ job_id: 'ab-dur-1', file_type: 'pdf', estimated_pages: 45, detected_language: 'greek', is_comic: false }) };
    }
    return { ok: true, status: 200, json: async () => ([]) };
  };
  await ctx.uploadFile('ab', { name: 'novel_long.pdf', size: 2097152 });
  assert(getEl('ab-file-meta').textContent.includes('⏱️ ~1 ώρα 30 λ ακρόαση'), `Duration estimate missing in meta: ${getEl('ab-file-meta').textContent}`);

  // 16. playCompletionNotification runs safely in Node VM without throwing
  ctx.playCompletionNotification('Test Title', 'Test Body');

  console.log('NODE_UI_HARNESS_OK');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Node UI harness failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertIn("NODE_UI_HARNESS_OK", res.stdout)
        print("   Node.js runtime DOM & state tests (16 assertions): OK")

    def test_5_voice_preview_can_be_stopped(self):
        """The voice test has a stop button: visible while a sample plays, stops it at once, hides when it ends."""
        print("-> 5. Testing the voice preview stop button...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('id="ab-preview-stop-btn"', html)
        self.assertIn('onclick="stopVoicePreview()"', html)
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
const getEl = (id) => { if (!els.has(id)) els.set(id, { id, value: '', style: { display: '' } }); return els.get(id); };
const created = [];
class FakeAudio {
  constructor(src) { this.src = src; this.paused = true; this.listeners = {}; this.loads = 0; created.push(this); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  removeAttribute(name) { if (name === 'src') this.src = ''; }
  load() { this.loads += 1; }
  fire(ev) { (this.listeners[ev] || []).forEach((fn) => fn()); }
}
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  Audio: FakeAudio, EventSource: class { close() {} }, FormData: class { append() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  window: { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} },
  document: { documentElement: getEl('html'), getElementById: getEl, querySelector: () => null,
    querySelectorAll: () => [], addEventListener() {}, createElement: getEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
ctx.toast = () => {};
const btn = getEl('ab-preview-stop-btn');
btn.style.display = 'none';
ctx.playVoicePreview('el-GR-NestorasNeural', null, 'Καλημέρα σας.');
const first = created[created.length - 1];
assert.strictEqual(first.paused, false);
assert.strictEqual(btn.style.display, '', 'stop button shown while playing');
ctx.stopVoicePreview();
assert.strictEqual(first.paused, true, 'sound stops at once');
assert.strictEqual(first.src, '', 'download of the sample aborted');
assert.strictEqual(btn.style.display, 'none', 'stop button hidden again');
ctx.playVoicePreview('el-GR-AthinaNeural', null, 'Δεύτερο δείγμα.');
const second = created[created.length - 1];
first.fire('ended');                              // a stale event of the stopped sample changes nothing
assert.strictEqual(btn.style.display, '');
second.fire('ended');                             // the sample played to its end
assert.strictEqual(btn.style.display, 'none');
process.stdout.write('OK');
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Voice preview stop button: OK")

    def test_6_mixed_queue_lock_reason_is_visible(self):
        """A mixed (books + comics) queue keeps Auto-Start locked and says why under the switch, not only on hover."""
        print("-> 6. Testing the visible reason for the locked Auto-Start...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('id="queue-auto-start-note"', html)
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  const cls = new Set();
  return { id, value: '', textContent: '', innerHTML: '', checked: false, disabled: false, title: '', dataset: {},
    style: { display: '' }, setAttribute() {}, getAttribute() {}, removeAttribute() {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c), toggle() {} },
    closest: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const label = makeEl('label');
getEl('queue-auto-start-toggle').closest = () => label;
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  EventSource: class { close() {} }, FormData: class { append() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  window: { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} },
  document: { documentElement: makeEl('html'), getElementById: getEl, querySelector: () => null,
    querySelectorAll: () => [], addEventListener() {}, createElement: makeEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
ctx.toast = () => {};
const item = (name, comic) => ({ job_id: name, file_name: name, file_type: comic ? 'cbz' : 'pdf', status: 'queued',
  is_comic: comic, layout_mode: comic ? 'comic' : 'standard', output_format: 'pdf', progress: 0, current_step: '' });
const base = { is_running: false, paused: false, paused_for_quota: false, done_count: 0, max_items: 20 };
const note = getEl('queue-auto-start-note');
const toggle = getEl('queue-auto-start-toggle');
note.style.display = 'none';
ctx.renderBatchQueue(Object.assign({}, base, { items: [item('Blindsight.pdf', false), item('Nebraska.cbz', true)],
  is_mixed: true, auto_start: false, queued_count: 2, total_count: 2 }));
assert.strictEqual(note.style.display, '', 'reason shown for a mixed queue');
assert.strictEqual(toggle.disabled, true, 'Auto-Start stays locked');
assert.strictEqual(toggle.checked, false);
ctx.renderBatchQueue(Object.assign({}, base, { items: [item('Blindsight.pdf', false), item('Echopraxia.pdf', false)],
  is_mixed: false, auto_start: true, queued_count: 2, total_count: 2 }));
assert.strictEqual(note.style.display, 'none', 'no note for a books-only queue');
assert.strictEqual(toggle.disabled, false);
assert.strictEqual(toggle.checked, true);
process.stdout.write('OK');
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Locked Auto-Start reason visible: OK")

    def test_7_lone_queued_file_returns_to_upload_card(self):
        """Removing one of two queued, unstarted files puts the other back in the Upload Card with its style
        recommendation ("Εφαρμογή Προτεινόμενου"); a queue whose last file is already done stays a queue."""
        print("-> 7. Testing a lone queued file returning to the Upload Card...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  const cls = new Set();
  return { id, value: '', textContent: '', innerHTML: '', checked: false, disabled: false, title: '', dataset: {},
    style: { display: '' }, setAttribute() {}, getAttribute() {}, removeAttribute() {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c), toggle() {} },
    closest: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const item = (name, status) => ({ job_id: name, file_name: name, file_type: 'pdf', status, is_comic: false,
  is_scanned: false, layout_mode: 'standard', output_format: 'pdf', source_lang: 'english', target_lang: 'greek',
  ai_polish: true, reading_direction: 'ltr', quota_behavior: 'wait', progress: 0, current_step: '' });
const base = { is_running: false, paused: false, paused_for_quota: false, done_count: 0, max_items: 20,
  is_mixed: false, auto_start: false };
let remaining = 'queued';
const calls = [];
const reply = (data) => ({ ok: true, status: 200, json: async () => data });
async function fakeFetch(url, opts = {}) {
  const method = opts.method || 'GET';
  calls.push(`${method} ${url}`);
  if (method === 'DELETE' && url.endsWith('/queue/Blindsight.pdf'))
    return reply(Object.assign({}, base, { items: [item('Echopraxia.pdf', remaining)], queued_count: 1, total_count: 1 }));
  if (method === 'DELETE' && url.endsWith('/queue/Echopraxia.pdf'))
    return reply(Object.assign({}, base, { items: [], queued_count: 0, total_count: 0 }));
  if (url.includes('/status/Echopraxia.pdf')) return reply({ total_pages: 120, file_name: 'Echopraxia.pdf' });
  if (url.includes('/preview/Echopraxia.pdf')) return reply({ preview_text: 'It began with a storm at sea.', subjects: [] });
  if (url.includes('/detect-genre')) return reply({ genre: 'literature', confidence: 0.9, reason: 'Narrative prose.' });
  return reply({});
}
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  EventSource: class { close() {} }, FormData: class { append() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: fakeFetch,
  window: { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} },
  document: { documentElement: makeEl('html'), getElementById: getEl, querySelector: () => null,
    querySelectorAll: () => [], addEventListener() {}, createElement: makeEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
ctx.toast = () => {};
vm.runInContext("currentAppMode = 'advanced'", ctx);
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };

(async () => {
  ctx.renderBatchQueue(Object.assign({}, base, { items: [item('Blindsight.pdf', 'queued'), item('Echopraxia.pdf', 'queued')],
    queued_count: 2, total_count: 2 }));
  await ctx.removeQueueItem('Blindsight.pdf');
  await settle();
  assert.strictEqual(vm.runInContext('state.tr.jobId', ctx), 'Echopraxia.pdf', 'the last file is the single document');
  const leftQueue = () => calls.some((c) => c.startsWith('DELETE ') && c.endsWith('/queue/Echopraxia.pdf'));
  assert.ok(leftQueue(), 'it leaves the queue');
  assert.strictEqual(getEl('tr-queue-card').style.display, 'none');
  assert.strictEqual(getEl('tr-upload-zone').style.display, 'none');
  assert.strictEqual(getEl('tr-file-name').textContent, 'Echopraxia.pdf');
  assert.ok(getEl('tr-file-meta').textContent.includes('~120 pages'));
  assert.strictEqual(getEl('tr-start-btn').disabled, false);
  const hint = getEl('tr-genre-hint');
  assert.strictEqual(hint.style.display, 'flex', 'style recommendation shown');
  assert.ok(hint.innerHTML.includes('Εφαρμογή Προτεινόμενου'), hint.innerHTML);

  // the last file already translated: the queue stays as it is
  vm.runInContext('state.tr.jobId = null', ctx);
  calls.length = 0;
  remaining = 'done';
  await ctx.removeQueueItem('Blindsight.pdf');
  await settle();
  assert.strictEqual(vm.runInContext('state.tr.jobId', ctx), null);
  assert.ok(!leftQueue(), 'a finished file stays in the queue');
  process.stdout.write('OK');
})().catch((e) => { process.stdout.write(String(e && e.stack || e)); });
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Lone queued file back in the Upload Card: OK")

    def test_8_upload_progress_and_batch_failures(self):
        """An upload shows its percent and a bar, then 'processing' until the server answers; a file removed while
        uploading is cancelled without an error; a batch upload names the files that failed and why."""
        print("-> 8. Testing upload progress and the batch upload summary...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        for el in ('id="tr-upload-bar"', 'id="tr-upload-bar-fill"', 'id="ab-upload-bar"', 'id="tr-batch-upload"'):
            self.assertIn(el, html)
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  const cls = new Set();
  return { id, value: '', textContent: '', innerHTML: '', checked: false, disabled: false, title: '', dataset: {},
    style: { display: '' }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
    removeAttribute() {}, classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c),
    toggle() {} }, closest: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const xhrs = [];
class FakeXHR {
  constructor() { this.upload = {}; this.status = 0; this.responseText = ''; this.aborted = false; xhrs.push(this); }
  open(method, url) { this.url = url; }
  getResponseHeader() { return 'application/json'; }
  send(body) { this.body = body; }
  abort() { this.aborted = true; if (this.onabort) this.onabort(); }
  progress(loaded, total) { this.upload.onprogress({ loaded, total, lengthComputable: true }); }
  respond(status, obj) { this.status = status; this.responseText = JSON.stringify(obj); this.onload(); }
}
const toasts = [];
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  EventSource: class { close() {} }, FormData: class { append() {} }, XMLHttpRequest: FakeXHR, Response, DOMException,
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({ items: [], total_count: 0 }) }),
  window: { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} },
  document: { documentElement: makeEl('html'), getElementById: getEl, querySelector: () => null,
    querySelectorAll: () => [], addEventListener() {}, createElement: makeEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
ctx.toast = (msg, kind) => toasts.push([kind, msg]);
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };
const MB = 1024 * 1024;
const ok = (name) => ({ job_id: name, file_name: name, file_type: 'pdf', estimated_pages: 12, is_comic: false,
  is_scanned: false, detected_language: 'english' });

(async () => {
  // one file: percent and bar, then processing, then Ready with the bar gone
  const meta = getEl('tr-file-meta'), bar = getEl('tr-upload-bar'), fill = getEl('tr-upload-bar-fill');
  const done = ctx.processFile({ name: 'Book.pdf', size: 10 * MB }, 'tr');
  await settle();
  assert.strictEqual(bar.style.display, '', 'bar shown at once');
  xhrs[0].progress(5 * MB, 10 * MB);
  assert.ok(meta.textContent.includes('Ανέβασμα 50%'), meta.textContent);
  assert.strictEqual(fill.style.width, '50%');
  xhrs[0].upload.onload();
  assert.ok(meta.textContent.includes('επεξεργασία'), meta.textContent);
  xhrs[0].respond(200, ok('J1'));
  await done; await settle();
  assert.ok(meta.textContent.includes('Ready'), meta.textContent);
  assert.strictEqual(bar.style.display, 'none', 'bar hidden once uploaded');
  assert.strictEqual(vm.runInContext('state.tr.jobId', ctx), 'J1');

  // removed while uploading: the upload stops, no error
  ctx.removeFile('tr');
  const second = ctx.processFile({ name: 'Other.pdf', size: 4 * MB }, 'tr');
  await settle();
  ctx.removeFile('tr');
  await second; await settle();
  assert.strictEqual(xhrs[1].aborted, true, 'upload cancelled');
  assert.ok(!toasts.some(([kind]) => kind === 'error'), JSON.stringify(toasts));
  assert.strictEqual(bar.style.display, 'none');

  // several files: overall progress, then a summary naming the one that failed
  const box = getEl('tr-batch-upload'), text = getEl('tr-batch-upload-text');
  const batch = ctx.enqueueMultipleFiles([{ name: 'A.pdf', size: 2 * MB }, { name: 'B.pdf', size: 2 * MB }]);
  await settle();
  xhrs[2].progress(1 * MB, 2 * MB);
  assert.strictEqual(box.style.display, '');
  assert.ok(text.textContent.includes('1/2') && text.textContent.includes('σύνολο 25%'), text.textContent);
  xhrs[2].respond(200, ok('JA'));
  await settle();
  xhrs[3].respond(500, { detail: "Δεν ήταν δυνατή η αποθήκευση του αρχείου 'B.pdf' στον server (No space left)." });
  await batch; await settle();
  assert.strictEqual(box.style.display, '', 'summary stays visible');
  assert.ok(text.innerHTML.includes('Ανέβηκαν 1 από 2') && text.innerHTML.includes('B.pdf')
    && text.innerHTML.includes('No space left'), text.innerHTML);
  process.stdout.write('OK');
})().catch((e) => { process.stdout.write(String(e && e.stack || e)); });
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Upload progress and batch summary: OK")

    def test_9_app_icon_for_every_browser_and_home_screen(self):
        """Safari and iOS do not use an SVG tab icon: the pages link PNG/ICO icons and a 180 px apple-touch-icon
        (an iPhone home-screen shortcut otherwise shows the first letter), all reachable before signing in."""
        print("-> 9. Testing the app icon files and links...")
        from PIL import Image
        from backend import auth
        front = Path("frontend")
        for page in ("index.html", "login.html"):
            html = (front / page).read_text(encoding="utf-8")
            for tag in ('rel="icon" href="/favicon.ico"' if page == "login.html" else 'rel="icon" href="favicon.ico"',
                        'type="image/svg+xml"', 'rel="apple-touch-icon"', 'rel="manifest"',
                        'name="apple-mobile-web-app-title" content="BookApp"'):
                self.assertIn(tag, html, f"{page}: {tag}")
            self.assertNotIn("<text y='.9em'", html, f"{page}: the emoji-only SVG icon is gone")
        apple = Image.open(front / "apple-touch-icon.png")
        self.assertEqual((apple.size, apple.mode), ((180, 180), "RGB"), "square and opaque, iOS rounds it itself")
        self.assertEqual(Image.open(front / "favicon.ico").info["sizes"], {(16, 16), (32, 32), (48, 48)})
        manifest = json.loads((front / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["short_name"], "BookApp")
        for icon in manifest["icons"]:
            self.assertTrue((front / icon["src"]).is_file(), icon["src"])
            if icon["type"] == "image/png":
                w, h = Image.open(front / icon["src"]).size
                self.assertEqual(f"{w}x{h}", icon["sizes"])
        for path in ("/favicon.ico", "/icon.svg", "/icon-32.png", "/apple-touch-icon.png", "/manifest.json"):
            self.assertTrue(auth.is_open_path(path), path)
        self.assertFalse(auth.is_open_path("/app.js"), "only the icons are open, not the app")
        print("   App icon files and links: OK")

    def test_10_interface_language_switch(self):
        """Every interface text of the pages exists in Greek and English (i18n.js), both pages carry the ΕΛ | EN switch,
        texts with numbers switch with their numbers, and book text / file names are never translated."""
        print("-> 10. Testing the Greek / English interface switch...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        from html.parser import HTMLParser
        from backend import auth

        class Texts(HTMLParser):
            VOID = {"br", "img", "input", "meta", "link", "hr", "source"}

            def __init__(self):
                super().__init__()
                self.stack, self.texts = [], []

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                skip = tag in ("script", "style", "code") or a.get("translate") == "no"
                if tag not in self.VOID:
                    self.stack.append(skip or bool(self.stack and self.stack[-1]))
                if not (self.stack and self.stack[-1]) and not skip:
                    self.texts += [a[k] for k in ("title", "placeholder", "aria-label", "alt") if a.get(k)]

            def handle_endtag(self, tag):
                if tag not in self.VOID and self.stack:
                    self.stack.pop()

            def handle_data(self, data):
                if not (self.stack and self.stack[-1]):
                    self.texts.append(" ".join(data.split()))

        front = Path("frontend")
        texts = []
        for page in ("index.html", "login.html"):
            html = (front / page).read_text(encoding="utf-8")
            self.assertIn('data-ui-lang="el"', html, page)
            self.assertIn('data-ui-lang="en"', html, page)
            head = html.split("</head>")[0]
            self.assertIn("i18n.js", head, f"{page}: i18n.js loads in <head>, before the page text")
            parser = Texts()
            parser.feed(html)
            # Greek words or English phrases: names, formats and code examples are the same in both languages
            texts += [t for t in parser.texts if re.search(r"[Ͱ-Ͽ]{2,}|[A-Za-z]{3,} [A-Za-z]{3,}", t)]
        index = (front / "index.html").read_text(encoding="utf-8")
        for ident in ("tr-file-name", "reader-single-content", "glossary-tbody", "ins-result-body"):
            self.assertIn(f'id="{ident}" translate="no"', index, f"{ident} holds book content: never translated")
        self.assertTrue(auth.is_open_path("/i18n.js"), "the sign-in page loads it before signing in")

        same = {"DocTranslate & AudioBook", "Smart Batch Queue:", "Graphic Novel / Comic", "AI Polish (Gemini)",
                "✨ AI Polish (Gemini)", "1-Click Insights", "⚡ Edge-TTS Neural", "George Kotsimpos", "Book Insights",
                "CBZ / CBR COMIC", "✨ Gemini Flash",
                "sudo journalctl -u bookapp | grep \"setup code\"", "docker logs bookapp"}
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const ctx = vm.createContext({ console, MutationObserver: class { observe() {} }, CustomEvent: class {},
  localStorage: { getItem: () => null, setItem() {} }, navigator: { language: 'el-GR' },
  document: { documentElement: {}, addEventListener() {}, querySelectorAll: () => [], dispatchEvent() {} },
  window: { alert() {}, confirm() { return true; }, prompt() {} }, NodeFilter: {} });
vm.runInContext(fs.readFileSync('frontend/i18n.js', 'utf8') + ';globalThis.I18N = I18N;', ctx);
const { I18N } = ctx;
const [texts, same] = JSON.parse(fs.readFileSync(0, 'utf8'));
const missing = texts.filter((t) => !same.includes(t) && !I18N._identify(t));
assert.deepStrictEqual(missing, [], 'interface texts without a Greek / English pair in i18n.js');
const t = (s, l) => I18N.text(s, l);
assert.strictEqual(t('🌐 Start Translation', 'el'), '🌐 Έναρξη μετάφρασης');
assert.strictEqual(t('🌐 Έναρξη μετάφρασης', 'en'), '🌐 Start Translation');
assert.strictEqual(t('Advanced Mode (Πλήρης Έλεγχος)', 'en'), 'Advanced Mode (Full Control)', 'mixed wording becomes one language');
assert.strictEqual(t('▶️ Start Batch Translation (12 files)', 'el'), '▶️ Έναρξη μαζικής μετάφρασης (12 αρχεία)');
assert.strictEqual(t('4.0 MB · ~340 pages · PDF · Ready', 'el'), '4.0 MB · ~340 σελίδες · PDF · Έτοιμο');
assert.strictEqual(t('15 λεπτά – 1 ώρα 5 λεπτά', 'en'), '15 minutes – 1 hour 5 minutes');
assert.strictEqual(t('Ready in 5 minutes', 'el'), 'Ready in 5 minutes', 'unknown text is left alone');
// messages written by the server: progress steps, joined end-of-job notes, errors
assert.strictEqual(t('Single-Pass AI Translation & Polish: batch 12/152 (36/336 pages)...', 'el'),
  'Μετάφραση & επιμέλεια με AI: παρτίδα 12/152 (36/336 σελίδες)...');
assert.strictEqual(t('🏆 Αναθεώρηση με το πρωτότυπο (πολύ αργή διαδικασία): τμήμα 3/50 · απομένουν ~1 ώρα 12 λεπτά…', 'en'),
  '🏆 Revision against the original (very slow): part 3/50 · ~1 hour 12 minutes left…');
assert.strictEqual(t('⚠️ 1 page(s) still contain text in the original language (pages 7 of the original): translate again to retry them. ' +
  '2 word(s) contain letters of another alphabet (ποгда, Ίσות): please check them.', 'el'),
  '⚠️ 1 σελίδες έχουν ακόμη κείμενο στη γλώσσα του πρωτοτύπου (σελίδες 7 του πρωτοτύπου): μεταφράστε ξανά για νέα προσπάθεια. ' +
  '2 λέξεις έχουν γράμματα άλλου αλφαβήτου (ποгда, Ίσות): ελέγξτε τες.', 'joined notes are switched one by one');
assert.ok(t('⚠️ Audiobook ready! 3 part(s) in a script this voice cannot read were skipped; 2 part(s) read by Nestoras, ' +
  'because Athina returned no audio.', 'el').includes('παραλείφθηκαν· 2 τμήματα'), "';' is a question mark in Greek: '·'");
assert.strictEqual(t('Λάθος όνομα χρήστη ή κωδικός.', 'en'), 'Wrong username or password.');
// the pieces of the time left in the progress card
assert.strictEqual(t('⏳ Απομένουν: ', 'en').trim(), '⏳ Time left:');
assert.strictEqual(t('1 ώρα 53 λεπτά', 'en'), '1 hour 53 minutes');
assert.strictEqual(t('λιγότερο από 1 λεπτό', 'en'), 'less than 1 minute');
assert.strictEqual(t('5.0 σελ/λ', 'en'), '5.0 pages/min');
assert.strictEqual(t('12 τμήματα/λ', 'en'), '12 parts/min');
assert.strictEqual(t('+ το 2ο πέρασμα AI μετά', 'en'), '+ the 2nd AI pass afterwards');
assert.strictEqual(t('⚠️ Something unknown. Another unknown sentence.', 'el'), '⚠️ Something unknown. Another unknown sentence.');
process.stdout.write('OK');
"""
        res = subprocess.run([node_bin, "-e", harness], input=json.dumps([texts, sorted(same)]), capture_output=True,
                             text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print(f"   Interface language switch ({len(texts)} texts with both languages): OK")

    def test_11_quick_download_updates_the_main_button(self):
        """After a finished translation, a quick-download button (DOCX next to 'Download PDF') makes DOCX the chosen
        format: the main button then says DOCX and downloads DOCX."""
        print("-> 11. Testing the main download button after a quick download...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        self.assertNotIn("</span> File", Path("frontend/index.html").read_text(encoding="utf-8"),
                         "the caption is 'Download PDF', which also reads right in Greek ('Λήψη PDF')")
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  const cls = new Set();
  return { id, value: '', textContent: '', innerHTML: '', checked: false, disabled: false, title: '', href: '', dataset: {},
    style: { display: '' }, setAttribute() {}, getAttribute() {}, removeAttribute() {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c), toggle() {} },
    closest: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const win = { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} };
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  EventSource: class { close() {} }, FormData: class { append() {} }, Notification: undefined, Audio: class { play() { return Promise.resolve(); } },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  window: win,
  document: { documentElement: makeEl('html'), getElementById: getEl, querySelector: () => null, hidden: false,
    querySelectorAll: () => [], addEventListener() {}, createElement: makeEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
ctx.toast = () => {};
ctx.playCompletionNotification = () => {};
vm.runInContext("state.tr.jobId = 'J1'; state.tr.status = 'done';", ctx);
getEl('tr-layout-mode').value = 'standard';
getEl('tr-output-format').value = 'pdf';
ctx.showResult('tr', { output_format: 'pdf', layout_mode: 'standard' });
const label = getEl('tr-format-label');
assert.strictEqual(label.textContent, 'PDF');
ctx.downloadOutput('tr', 'docx');
assert.ok(win.location.href.includes('format=docx'), 'the quick button downloads DOCX');
assert.strictEqual(label.textContent, 'DOCX', 'the main button now says DOCX');
assert.ok(getEl('tr-download-btn').href.includes('format=docx'));
assert.ok(getEl('tr-result-meta').textContent.includes('DOCX'));
assert.ok(getEl('fmt-docx').classList.contains('active'), 'the settings show DOCX as chosen');
win.location.href = '';
ctx.downloadOutput('tr');
assert.ok(win.location.href.includes('format=docx'), 'the main button downloads DOCX');
// a graphic novel keeps its caption form
getEl('tr-layout-mode').value = 'comic';
ctx.showResult('tr', { output_format: 'pdf', layout_mode: 'comic' });
ctx.downloadOutput('tr', 'epub');
assert.strictEqual(label.textContent, 'Graphic Novel (EPUB)');
process.stdout.write('OK');
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Main download button follows a quick download: OK")

    def test_12_gemini_keys_window_eight_slots_and_waiting_status(self):
        """The keys window has 8 slots (5-8 fold out), and says what waits for Gemini: models at their limit on how
        many keys and until when, and the viewer's waiting jobs; nothing when all is well."""
        print("-> 12. Testing the Gemini keys window: 8 slots and the waiting status...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        for n in range(1, 9):
            self.assertIn(f'id="pool-slot-status-{n}"', html)
        self.assertIn('id="gemini-api-key-8"', html)
        self.assertIn('id="gemini-more-slots"', html)
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  const cls = new Set();
  return { id, value: '', textContent: '', innerHTML: '', checked: false, disabled: false, title: '', open: false,
    dataset: {}, style: { display: '' }, setAttribute() {}, getAttribute() {}, removeAttribute() {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c), toggle() {} },
    closest: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  EventSource: class { close() {} }, FormData: class { append() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  window: { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} },
  document: { documentElement: makeEl('html'), getElementById: getEl, querySelector: () => null,
    querySelectorAll: () => [], addEventListener() {}, createElement: makeEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
assert.strictEqual(vm.runInContext('GEMINI_SLOT_IDS.length', ctx), 8);
assert.strictEqual(vm.runInContext('GEMINI_SLOT_IDS[7]', ctx), 'gemini-api-key-8');
const now = Date.now() / 1000;
const pool = { total_keys: 6, available_keys: 6, all_exhausted: false,
  slots: Array.from({ length: 6 }, (_, i) => ({ slot: i + 1, is_active: i === 0, is_exhausted: false,
    cooling_models: i < 2 ? ['gemini-3.5-flash'] : [] })),
  cooling_models: [{ model: 'gemini-3.5-flash', keys: 2, reset_timestamp: now + 3 * 3600, remaining_sec: 3 * 3600 }] };
ctx.renderGeminiPoolStatus(pool);
assert.ok(getEl('pool-slot-status-1').textContent.includes('1 μοντέλα στο όριο'), getEl('pool-slot-status-1').textContent);
assert.strictEqual(getEl('pool-slot-status-3').textContent, '🟢 Ενεργό (Active)', 'keys take turns: none on standby');
assert.strictEqual(getEl('pool-slot-status-7').textContent, '⚪ Κενό', 'slots 7-8 are empty but drawn');
const box = getEl('ai-polish-quota-warning-banner');
const body = getEl('ai-polish-quota-warning-text');
const title = getEl('ai-polish-quota-warning-title');
// only a model at its limit: the app goes on with the others
ctx.renderGeminiWaitStatus({ exhausted: false, pool, waiting_jobs: [] });
assert.strictEqual(box.style.display, 'block');
assert.ok(title.textContent.startsWith('ℹ️'), title.textContent);
assert.ok(body.innerHTML.includes('gemini-3.5-flash: όριο ημέρας σε 2 από 6 κλειδιά'), body.innerHTML);
// a job waits for it
ctx.renderGeminiWaitStatus({ exhausted: false, pool, waiting_jobs: [{ file_name: 'Blindsight.pdf' }] });
assert.ok(title.textContent.startsWith('⏳'), title.textContent);
assert.ok(body.innerHTML.includes('Περιμένουν την ανανέωση: «Blindsight.pdf»'), body.innerHTML);
assert.ok(body.innerHTML.includes('άλλον λογαριασμό Google'));
// every key spent
ctx.renderGeminiWaitStatus({ exhausted: true, reset_timestamp: now + 600, remaining_seconds: 600,
  pool: { total_keys: 2, cooling_models: [] }, waiting_jobs: [] });
assert.ok(body.innerHTML.includes('Εξαντλήθηκε το ημερήσιο όριο σε όλα τα κλειδιά') && body.innerHTML.includes('10 λεπτά'), body.innerHTML);
// all well: no box
ctx.renderGeminiWaitStatus({ exhausted: false, pool: { total_keys: 2, cooling_models: [] }, waiting_jobs: [] });
assert.strictEqual(box.style.display, 'none');
process.stdout.write('OK');
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Gemini keys window (8 slots, waiting status): OK")

    def test_13_time_left_follows_the_recent_pace(self):
        """The time left comes from the pace over the last minutes, counted from what the page first sees: a reload
        in the middle of a long job does not divide hours of work by a few seconds, a fast start from cached batches
        and a wait for Gemini limits fade out, the unit is right, and long times are in hours."""
        print("-> 13. Testing the time-left estimate...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  const cls = new Set();
  return { id, value: '', textContent: '', innerHTML: '', checked: false, disabled: false, title: '', dataset: {},
    style: { display: '' }, setAttribute() {}, getAttribute() {}, removeAttribute() {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c), toggle() {} },
    closest: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
}
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  EventSource: class { close() {} }, FormData: class { append() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  window: { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} },
  document: { documentElement: makeEl('html'), getElementById: getEl, querySelector: () => null,
    querySelectorAll: () => [], addEventListener() {}, createElement: makeEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
vm.runInContext('Date.now = () => globalThis.__now;', ctx);
const T0 = 1.8e12;
const at = (sec) => { ctx.__now = T0 + sec * 1000; };
const tr = (done, extra = {}) => ctx.updateProgress('tr', Object.assign({ status: 'running', progress: 50,
  current_step: 'Single-Pass AI Translation', total_chunks: 80, done_chunks: Math.floor(done / 5),
  total_pages: 400, done_pages: done }, extra));
const eta = getEl('tr-progress-eta');
const shown = () => eta.style.display !== 'none';

// a reload in the middle: 200 of 400 pages were done hours ago, the page sees them at once
at(0); tr(200);
assert.ok(!shown(), 'no guess from the first look');
at(60); tr(205);
assert.ok(!shown(), 'one step is not a pace yet');
at(120); tr(210);
assert.ok(shown(), eta.innerHTML);
assert.ok(eta.innerHTML.includes('~<span>38 λεπτά</span>'), eta.innerHTML);   // 190 left at 5 pages/min
assert.ok(eta.innerHTML.includes('5.0 σελ/λ'), eta.innerHTML);
assert.ok(!eta.innerHTML.includes('2ο πέρασμα'), 'no second pass without Maximum quality');

// hours, and the second pass of Maximum quality is mentioned
vm.runInContext('state.tr.etaSamples = [];', ctx);
at(1000); tr(100, { max_quality: true });
at(1060); tr(101, { max_quality: true });
at(1120); tr(102, { max_quality: true });   // 1 page/min, 298 left
assert.ok(eta.innerHTML.includes('~<span>4 ώρες 58 λεπτά</span>'), eta.innerHTML);
assert.ok(eta.innerHTML.includes('+ το 2ο πέρασμα AI μετά'), eta.innerHTML);

// a fast start from cached batches fades out: after five minutes only the real pace counts
vm.runInContext('state.tr.etaSamples = [];', ctx);
at(5000); tr(0);
at(5005); tr(150);                           // restored from the checkpoint in a burst
for (let k = 1; k <= 12; k++) { at(5005 + k * 60); tr(150 + 2 * k); }   // then 2 pages a minute
assert.ok(eta.innerHTML.includes('2.0 σελ/λ'), eta.innerHTML);
assert.ok(eta.innerHTML.includes('~<span>1 ώρα 53 λεπτά</span>'), eta.innerHTML);  // 226 left at 2 a minute

// a long wait for Gemini limits: hidden while nothing moves, then measured afresh
at(5005 + 12 * 60 + 400); tr(174);
assert.ok(!shown(), 'nothing moved for minutes: no time left');
at(9000); tr(176);
assert.ok(!shown(), 'after the wait the pace starts again');
at(9060); tr(178); at(9120); tr(180);
assert.ok(shown() && eta.innerHTML.includes('2.0 σελ/λ'), eta.innerHTML);

// not running (queued, waiting, stopped): hidden, and the next run measures afresh
tr(180, { status: 'waiting_quota' });
assert.ok(!shown());
assert.strictEqual(vm.runInContext('state.tr.etaSamples.length', ctx), 0);

// almost done
vm.runInContext('state.tr.etaSamples = [];', ctx);
at(20000); tr(390); at(20030); tr(394); at(20060); tr(398);
assert.ok(eta.innerHTML.includes('<span>λιγότερο από 1 λεπτό</span>'), eta.innerHTML);

// an audiobook counts parts, per minute
const ab = (done) => ctx.updateProgress('ab', { status: 'running', progress: 10, current_step: '', total_chunks: 300,
  done_chunks: done, total_pages: 0, done_pages: 0 });
at(30000); ab(10); at(30030); ab(13); at(30060); ab(16);
const abEta = getEl('ab-progress-eta');
assert.ok(abEta.innerHTML.includes('6.0 τμήματα/λ'), abEta.innerHTML);
assert.ok(abEta.innerHTML.includes('~<span>47 λεπτά</span>'), abEta.innerHTML);   // 284 left at 6 a minute
process.stdout.write('OK');
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Time left from the recent pace: OK")

    def test_14_help_window_in_both_languages(self):
        """The ❓ help window holds a short guide and the FAQ twice, in Greek and in English, with the same
        questions; only the block of the interface language shows, and neither is switched word by word."""
        print("-> 14. Testing the help window (guide & FAQ)...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        css = Path("frontend/style.css").read_text(encoding="utf-8")
        self.assertIn('id="btn-help" onclick="openHelpModal()"', html)
        self.assertIn('id="help-modal"', html)
        modal = html.split('id="help-modal"', 1)[1].split("MODAL: DISTRACTION-FREE READER", 1)[0]
        el = modal.split('<section class="help-lang" lang="el" translate="no">', 1)[1].split("</section>", 1)[0]
        en = modal.split('<section class="help-lang" lang="en" translate="no">', 1)[1].split("</section>", 1)[0]
        self.assertGreaterEqual(el.count("<details>"), 10, "a useful number of questions")
        self.assertEqual(el.count("<details>"), en.count("<details>"), "the same questions in both languages")
        self.assertEqual(el.count("<h4>"), en.count("<h4>"), "the same guide sections in both languages")
        self.assertIsNone(re.search(r"[A-Za-z]{4,} [a-z]{4,} [a-z]{4,}", re.sub(r"<[^>]+>", " ", el).replace("Graphic Novel", "")),
                          "the Greek block is in Greek")
        self.assertIsNone(re.search(r"[Ͱ-Ͽ]{3,}", re.sub(r"<[^>]+>", " ", en).replace("ΕΛ", "")), "the English block is in English")
        self.assertIn('html[lang="en"] .help-lang[lang="el"]', css)
        self.assertIn('html:not([lang="en"]) .help-lang[lang="en"]', css)
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const els = new Map();
function makeEl(id) {
  return { id, value: '', textContent: '', innerHTML: '', style: { display: 'none' }, dataset: {}, scrollTop: 0,
    setAttribute() {}, getAttribute() {}, removeAttribute() {}, classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    closest: () => null, addEventListener() {}, querySelector() { return body; }, querySelectorAll: () => [] };
}
const body = makeEl('help-body');
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };
const ctx = vm.createContext({ console, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  EventSource: class { close() {} }, FormData: class { append() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  window: { location: { origin: 'http://127.0.0.1:8000', protocol: 'http:', href: '' }, addEventListener() {} },
  document: { documentElement: makeEl('html'), getElementById: getEl, querySelector: () => null,
    querySelectorAll: () => [], addEventListener() {}, createElement: makeEl, body: { appendChild() {} } } });
vm.runInContext(fs.readFileSync('frontend/app.js', 'utf8'), ctx);
body.scrollTop = 300;
ctx.openHelpModal();
assert.strictEqual(getEl('help-modal').style.display, 'flex');
assert.strictEqual(body.scrollTop, 0, 'opens at the top');
ctx.closeHelpModal();
assert.strictEqual(getEl('help-modal').style.display, 'none');
process.stdout.write('OK');
"""
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Help window in Greek and English: OK")

    def test_15_theme_follows_daylight(self):
        """Light by day and dark at night by default (sunrise and sunset at Athens); the button switches by hand
        until the next sunrise or sunset, and then the automatic theme comes back."""
        print("-> 15. Testing the automatic light / dark theme...")
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js not available in PATH")
        from backend import auth
        self.assertTrue(auth.is_open_path("/theme.js"), "the sign-in page loads it before signing in")
        for page in ("index.html", "login.html"):
            html = Path("frontend", page).read_text(encoding="utf-8")
            self.assertIn("theme.js", html.split("</head>")[0], f"{page}: theme.js in <head>, so no flash of the other theme")
            self.assertNotIn("localStorage.getItem('bookapp_theme')", html, f"{page}: no lasting theme choice any more")
        harness = r"""
const fs = require('fs'); const vm = require('vm'); const assert = require('assert');
const store = new Map([['bookapp_theme', 'dark']]);  // a choice saved by the former button
const attrs = {};
const ctx = vm.createContext({ console, setInterval: () => 1, Intl,
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k) },
  document: { hidden: false, addEventListener() {},
    documentElement: { setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k] ?? null } } });
vm.runInContext(fs.readFileSync('frontend/theme.js', 'utf8') + ';globalThis.T = BookAppTheme;', ctx);
const T = ctx.T;
assert.ok(!store.has('bookapp_theme'), 'the former lasting choice is dropped');
T._setPlace(37.98, 23.73);  // Athens
const close = (ms, iso, label) => assert.ok(Math.abs(ms - Date.parse(iso)) < 6 * 60000, `${label}: ${new Date(ms).toISOString()} vs ${iso}`);
let sun = T._sunTimes(Date.parse('2026-06-21T10:00:00Z'), 37.98, 23.73);
close(sun.rise, '2026-06-21T03:02:00Z', 'summer sunrise 06:02');
close(sun.set, '2026-06-21T17:51:00Z', 'summer sunset 20:51');
sun = T._sunTimes(Date.parse('2026-12-21T10:00:00Z'), 37.98, 23.73);
close(sun.rise, '2026-12-21T05:38:00Z', 'winter sunrise 07:38');
close(sun.set, '2026-12-21T15:10:00Z', 'winter sunset 17:10');
assert.ok(T._sunTimes(Date.parse('2026-12-21T10:00:00Z'), 78, 15).always === 'night', 'polar night');

const day = Date.parse('2026-12-21T11:00:00Z');      // 13:00 in Athens
const night = Date.parse('2026-12-21T19:00:00Z');    // 21:00
const nextMorning = Date.parse('2026-12-22T07:00:00Z');
assert.strictEqual(T.current(day), 'light');
assert.strictEqual(T.current(night), 'dark');
assert.strictEqual(T.apply(day), 'light');
assert.strictEqual(attrs['data-theme'], 'light');
// switched by hand at midday: dark until sunset, then the automatic (dark) theme, then light next morning
assert.strictEqual(T.toggle(day), 'dark');
assert.ok(T.isManual(day));
close(JSON.parse(store.get('bookapp_theme_choice')).until, '2026-12-21T15:10:00Z', 'the choice lasts until sunset');
assert.strictEqual(T.current(day + 3600000), 'dark', 'the choice holds');
assert.strictEqual(T.current(night), 'dark');
assert.ok(!T.isManual(night), 'after sunset the theme is automatic again');
assert.strictEqual(T.current(nextMorning), 'light');
// switched by hand at night: light until sunrise
assert.strictEqual(T.toggle(night), 'light');
assert.strictEqual(T.current(night + 3600000), 'light');
assert.strictEqual(T.current(nextMorning), 'light');
assert.strictEqual(T.current(Date.parse('2026-12-22T19:00:00Z')), 'dark', 'next evening: dark again');
// switching back to the automatic theme leaves no choice behind
T.toggle(night + 3600000);
assert.ok(!store.has('bookapp_theme_choice'));
process.stdout.write('OK');
"""
        env = dict(os.environ, TZ="Europe/Athens")
        res = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30, env=env)
        self.assertEqual(res.stdout.strip(), "OK", res.stdout + res.stderr)
        print("   Light by day, dark at night, manual switch until the next change: OK")


if __name__ == "__main__":
    unittest.main()
