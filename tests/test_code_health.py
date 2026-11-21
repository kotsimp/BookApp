"""
test_code_health.py - Automated Code Health, AST Validation & Static Integrity Suite.
Validates:
1. AST parsing and syntax validity for all Python files in backend/ and tests/.
2. Unbound local variable detection (checks that all loaded variables are assigned before use in all scopes).
3. Import integrity (verifies all backend modules import cleanly without side-effects or circular dependencies).
4. Unreachable code detection (no statements placed after unconditional return/raise).
"""

import sys
sys.path.insert(0, ".")
import ast
import glob
import importlib
from pathlib import Path


def test_ast_and_syntax_validity():
    print("-> 1. Testing AST & Syntax validity for all Python modules...")
    py_files = sorted(glob.glob("backend/**/*.py", recursive=True) + glob.glob("tests/**/*.py", recursive=True))
    assert len(py_files) >= 15, "Expected at least 15 Python files in repository"
    
    for path in py_files:
        p = Path(path)
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        try:
            tree = ast.parse(content, filename=str(p))
            assert tree is not None
        except SyntaxError as e:
            assert False, f"SyntaxError in {p}: {e}"
    print(f"   AST validity: OK ({len(py_files)} files parsed successfully)")


def test_unbound_local_variables():
    print("-> 2. Testing for unbound local variables in function scopes...")
    py_files = sorted(glob.glob("backend/**/*.py", recursive=True))
    
    for path in py_files:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src, filename=path)
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Collect function argument names
                args = {a.arg for a in node.args.args}
                args.update({a.arg for a in node.args.kwonlyargs})
                if node.args.vararg:
                    args.add(node.args.vararg.arg)
                if node.args.kwarg:
                    args.add(node.args.kwarg.arg)

                # Collect variables explicitly stored in this local function scope
                # (exclude variables stored inside nested functions or lambdas)
                locally_assigned = set()
                global_or_nonlocal = set()

                def _find_stores_and_loads(stmts):
                    assigned = set()
                    for s in stmts:
                        # Don't recurse into nested function definitions
                        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            assigned.add(s.name)
                            continue
                        for n in ast.walk(s):
                            if isinstance(n, (ast.Global, ast.Nonlocal)):
                                global_or_nonlocal.update(n.names)
                            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                                assigned.add(n.id)
                    return assigned

                locally_assigned = _find_stores_and_loads(node.body)

                assigned_so_far = set(args).union(global_or_nonlocal)
                for stmt in node.body:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        assigned_so_far.add(stmt.name)
                        continue

                    # For statements, collect loaded names that belong to this function's scope
                    # (ignoring inner lambdas/comprehensions)
                    for sub in ast.walk(stmt):
                        # If a lambda or comprehension has its own param, ignore that name
                        if isinstance(sub, ast.Lambda):
                            continue
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                            if sub.id in locally_assigned and sub.id not in assigned_so_far:
                                # Check if it's inside a lambda/comprehension parameter
                                is_nested_scope_param = False
                                for parent in ast.walk(stmt):
                                    if isinstance(parent, ast.Lambda):
                                        lambda_args = {a.arg for a in parent.args.args}
                                        if sub.id in lambda_args and any(sub is n for n in ast.walk(parent)):
                                            is_nested_scope_param = True
                                            break
                                    elif isinstance(parent, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
                                        comp_targets = set()
                                        for gen in parent.generators:
                                            for gn in ast.walk(gen.target):
                                                if isinstance(gn, ast.Name):
                                                    comp_targets.add(gn.id)
                                        if sub.id in comp_targets and any(sub is n for n in ast.walk(parent)):
                                            is_nested_scope_param = True
                                            break

                                if is_nested_scope_param:
                                    continue

                                # Ensure it is not assigned inside this same statement
                                in_stmt_store = any(
                                    isinstance(s, ast.Name) and isinstance(s.ctx, ast.Store) and s.id == sub.id
                                    for s in ast.walk(stmt)
                                )
                                if not in_stmt_store:
                                    assert False, f"UnboundLocalError risk in {path} -> {node.name}(): variable '{sub.id}' loaded at line {sub.lineno} before assignment"

                    for sub in ast.walk(stmt):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                            assigned_so_far.add(sub.id)

    print("   Unbound local variable check: OK (no unassigned local accesses detected)")


def test_import_integrity():
    print("-> 3. Testing module import integrity and circular dependencies...")
    modules = [
        "backend.job_manager",
        "backend.settings_manager",
        "backend.glossary",
        "backend.parsers",
        "backend.format_preserver",
        "backend.exporter",
        "backend.translator",
        "backend.tts_engine",
        "backend.ai_polisher",
        "backend.comic_translator",
        "backend.queue_manager",
        "backend.output_refiner",
        "backend.book_insights",
        "backend.main",
    ]
    for mod_name in modules:
        try:
            mod = importlib.import_module(mod_name)
            assert mod is not None
        except Exception as ex:
            assert False, f"Failed to import {mod_name}: {ex}"
    print(f"   Import integrity: OK ({len(modules)} backend modules import cleanly)")


def test_no_unreachable_code_after_returns():
    print("-> 4. Testing for unreachable code blocks after return/raise statements...")
    py_files = sorted(glob.glob("backend/**/*.py", recursive=True))
    
    for path in py_files:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        
        for node in ast.walk(tree):
            if hasattr(node, "body") and isinstance(node.body, list):
                has_terminator = False
                for stmt in node.body:
                    if has_terminator:
                        assert False, f"Unreachable statement in {path} at line {stmt.lineno}: {type(stmt).__name__}"
                    if isinstance(stmt, (ast.Return, ast.Raise)):
                        has_terminator = True

    print("   Unreachable code check: OK (no dead code blocks after return/raise)")


def test_undefined_globals_and_missing_imports():
    print("-> 5. Testing for undefined global/module names and missing submodule imports...")
    import builtins
    builtin_names = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__"}
    py_files = sorted(glob.glob("backend/**/*.py", recursive=True))

    for path in py_files:
        src = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(src, filename=path)

        # Catch submodule usage without explicit import (e.g. urllib.error)
        if "urllib.error" in src and "import urllib.error" not in src:
            assert False, f"Missing 'import urllib.error' in {path}"

        defined = set(builtin_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    defined.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    defined.add(a.asname or a.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                if hasattr(node, "name"):
                    defined.add(node.name)
                if hasattr(node, "args"):
                    for arg in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
                        defined.add(arg.arg)
                    if node.args.vararg:
                        defined.add(node.args.vararg.arg)
                    if node.args.kwarg:
                        defined.add(node.args.kwarg.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.alias):
                defined.add(node.asname or node.name.split(".")[0])

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                assert node.id in defined, f"Undefined global/name '{node.id}' in {path} at line {node.lineno}"

    print(f"   Undefined global & missing import check: OK ({len(py_files)} backend files clean)")


def test_no_unused_imports_or_deprecated_apis():
    print("-> 6. Testing for unused top-level imports and deprecated FastAPI APIs...")
    py_files = sorted(glob.glob("backend/**/*.py", recursive=True))

    for path in py_files:
        src = Path(path).read_text(encoding="utf-8")
        assert "@app.on_event(" not in src, f"Deprecated @app.on_event() found in {path} — use lifespan instead"
        tree = ast.parse(src, filename=path)

        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                cur = node
                while isinstance(cur, ast.Attribute):
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    used_names.add(cur.id)

        for node in tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    nm = a.asname or a.name.split(".")[0]
                    assert nm in used_names, f"Unused import '{a.name}' in {path}:{node.lineno}"
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    nm = a.asname or a.name
                    if nm != "*":
                        assert nm in used_names, f"Unused import '{a.name}' from '{node.module}' in {path}:{node.lineno}"

    print("   Unused imports & deprecated API check: OK")


def test_frontend_html_js_integrity():
    print("-> 7. Testing Frontend HTML <-> JS cross-integrity & UI contracts...")
    import re
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    js = Path("frontend/app.js").read_text(encoding="utf-8")

    html_ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', html))
    js_dyn_ids = set(re.findall(r'id=["\']([^"\']+)["\']', js))
    all_ids = html_ids | js_dyn_ids

    # Every inline event handler in index.html AND dynamic templates in app.js must exist in app.js
    handlers = set(re.findall(r'on(?:click|change|input|submit|dragover|dragleave|drop|keydown)=["\']([a-zA-Z0-9_]+)\(', html))
    dyn_handlers = set(re.findall(r'on(?:click|change|input|submit)=["\']([a-zA-Z0-9_]+)\(', js))
    js_func_list = re.findall(r'(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\(', js)
    js_funcs = set(js_func_list)
    for h in handlers | dyn_handlers:
        if h not in ("document", "window"):
            assert h in js_funcs, f"Event handler '{h}()' is not defined in frontend/app.js"

    # Guard against common undefined helper typos (e.g. escapeHtml instead of escHtml)
    assert "escapeHtml(" not in js, "Undefined 'escapeHtml(' call found in frontend/app.js — use escHtml()!"

    # No duplicate top-level JS function definitions
    assert len(js_func_list) == len(js_funcs), "Duplicate function definitions detected in frontend/app.js"

    # Every static getElementById in app.js must exist in index.html or dynamic templates
    for gid in set(re.findall(r'getElementById\(["\']([^"\']+)["\']\)', js)):
        if "$" not in gid:
            assert gid in all_ids, f"JS queries missing HTML element #{gid}"

    # Verify critical UX regression guards remain intact
    assert "api_key: apiKey || null" in js, "app.js must always forward apiKey (not gate it behind aiPolish)"
    assert "function setGraphicNovelLock(" in js, "app.js must expose setGraphicNovelLock() for comic auto-lock"
    assert "function refreshPageApp(" in js, "app.js must expose refreshPageApp() for Refresh button"
    assert "function saveGeminiKeyOnly(" in js, "app.js must expose saveGeminiKeyOnly() for Save Key button"
    assert "function setActionButtonsEnabled(" in js, "app.js must centralize action button enable/disable via setActionButtonsEnabled()"
    assert "resetProgress(prefix, true);" in js, "loadHistoryJob must preserve action buttons via resetProgress(prefix, true)"
    print("   Frontend HTML <-> JS cross-integrity: OK")


def test_production_config_hygiene():
    print("-> 8. Testing Production Config Hygiene (no leaked test keys)...")
    import json
    settings_path = Path("config/settings.json")
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        k = str(data.get("gemini_api_key", ""))
        assert not k.startswith("AQ.Test") and not k.startswith("AIzaTest"), (
            f"Leaked test API key found in config/settings.json: {k[:12]}..."
        )
        for key_name in data.keys():
            assert not key_name.startswith("stress_key_"), f"Leaked stress test key '{key_name}' in config/settings.json"
    print("   Production Config Hygiene: OK")


def test_frontend_api_routes_match_backend():
    print("-> 9. Testing Frontend ${API} URLs match real FastAPI routes (zero 404 drift)...")
    import re
    main_src = Path("backend/main.py").read_text(encoding="utf-8")
    js_src = Path("frontend/app.js").read_text(encoding="utf-8")

    routes = re.findall(r'@app\.(?:get|post|put|delete|patch|api_route)\(["\']([^"\']+)["\']', main_src)
    backend_patterns = []
    for path in routes:
        pat = "^" + re.sub(r"\{[^}]+\}", r"[^/?]+", path.replace("/api", "")) + r"(\?.*)?$"
        backend_patterns.append(re.compile(pat))

    js_calls = sorted(set(re.findall(r'\$\{API\}(/[a-zA-Z0-9_/\-${}.?=&]+)', js_src)))
    assert len(js_calls) >= 10, "Expected at least 10 API calls in frontend/app.js"
    for call in js_calls:
        normalized = re.sub(r"\$\{[^}]+\}", "PLACEHOLDER", call).split("?")[0]
        matched = any(p.match(normalized) for p in backend_patterns)
        assert matched, f"Frontend calls ${{API}}{call} which has NO matching FastAPI route in backend/main.py!"
    print(f"   Frontend -> Backend API route alignment: OK ({len(js_calls)} UI endpoints verified)")


def test_all_backend_endpoints_covered_by_tests():
    print("-> 10. Testing 100% Backend Endpoint Test Coverage Guard...")
    import re
    main_src = Path("backend/main.py").read_text(encoding="utf-8")
    routes = re.findall(r'@app\.(get|post|put|delete|patch|api_route)\(["\']([^"\']+)["\']', main_src)
    # Exclude test_code_health.py itself so static guards cannot count as coverage
    test_files = [f for f in glob.glob("tests/*.py") if Path(f).name != "test_code_health.py"]
    test_src = "\n".join(Path(f).read_text(encoding="utf-8") for f in test_files)

    uncovered = []
    for method, path in routes:
        short = path.replace("/api", "")
        seg = short.split("{")[0].rstrip("/")
        covered = (seg in test_src) or (path in test_src)
        suffix = short.split("}")[-1] if "}" in short else ""
        if suffix and suffix not in test_src:
            covered = False
        if not covered:
            uncovered.append(f"{method.upper()} {path}")

    assert not uncovered, f"Uncovered FastAPI endpoints found (zero test coverage): {uncovered}"
    print(f"   100% Backend endpoint coverage: OK ({len(routes)}/{len(routes)} endpoints covered)")


if __name__ == "__main__":
    test_ast_and_syntax_validity()
    test_unbound_local_variables()
    test_import_integrity()
    test_no_unreachable_code_after_returns()
    test_undefined_globals_and_missing_imports()
    test_no_unused_imports_or_deprecated_apis()
    test_frontend_html_js_integrity()
    test_production_config_hygiene()
    test_frontend_api_routes_match_backend()
    test_all_backend_endpoints_covered_by_tests()
    print("\nALL CODE HEALTH AND STATIC INTEGRITY TESTS PASSED!")
