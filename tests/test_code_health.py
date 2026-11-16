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


if __name__ == "__main__":
    test_ast_and_syntax_validity()
    test_unbound_local_variables()
    test_import_integrity()
    test_no_unreachable_code_after_returns()
    print("\nALL CODE HEALTH AND STATIC INTEGRITY TESTS PASSED!")
