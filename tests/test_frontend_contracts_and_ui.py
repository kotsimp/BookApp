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


if __name__ == "__main__":
    unittest.main()
