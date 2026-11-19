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

import sys
sys.path.insert(0, ".")
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi.routing import APIRoute
from backend.main import app


class TestFrontendContractsAndUI(unittest.TestCase):

    def test_1_strict_http_method_and_route_alignment(self):
        print("-> 1. Testing strict (HTTP method, path) alignment between app.js and FastAPI app.routes...")
        js_src = Path("frontend/app.js").read_text(encoding="utf-8")

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
        js_src = Path("frontend/app.js").read_text(encoding="utf-8")
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
        js_src = Path("frontend/app.js").read_text(encoding="utf-8")

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
            res = subprocess.run([node_bin, "--check", "frontend/app.js"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"JavaScript syntax error in frontend/app.js:\n{res.stderr}")
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

  // 13. Download M4B calls downloadOutput('ab', 'm4b')
  appState.ab.jobId = 'ab-job-42';
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


if __name__ == "__main__":
    unittest.main()
