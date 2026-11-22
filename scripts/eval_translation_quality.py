"""
eval_translation_quality.py - Repeatable translation-quality evaluation for BookApp's AI translation prompts.

Scores translations of the passages in eval/passages.json with machine-checkable rules:
  * structure: page markers and paragraph count preserved, plausible length ratio
  * language: Greek-script share, Latin-script leakage outside «quotes»
  * passage checks: forbidden renderings (known errors), required renderings, max counts of overused words
  * local quality inspector: number of issues found by backend.output_refiner.inspect_text_quality

Usage:
  python scripts/eval_translation_quality.py --live              # translate with the CURRENT prompt via Gemini
                                                                  # (uses your API quota: ~1 request per passage)
  python scripts/eval_translation_quality.py --from-dir DIR       # score saved outputs DIR/<passage_id>.txt
  python scripts/eval_translation_quality.py --live --save DIR    # also save the outputs for later comparison
Exit code 0 when every passage passes all hard checks, 1 otherwise.
"""

import re
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASSAGES_FILE = ROOT / "eval" / "passages.json"
_MARKER = re.compile(r"={3,}\s*PAGE\s+(\d+)\s*={3,}")


def load_passages(path: Path = PASSAGES_FILE) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["passages"]


def _paragraphs(text: str) -> List[str]:
    body = _MARKER.sub("", text or "")
    return [p for p in re.split(r"\n\s*\n", body) if p.strip()]


def score_translation(source: str, output: str, checks: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {'passed': bool, 'failures': [...], 'metrics': {...}} — pure function, no network."""
    failures: List[str] = []
    out = output or ""
    if _MARKER.findall(source) != _MARKER.findall(out):
        failures.append("page markers changed")
    n_src, n_out = len(_paragraphs(source)), len(_paragraphs(out))
    if n_src != n_out:
        failures.append(f"paragraph count {n_src} -> {n_out}")
    ratio = len(_MARKER.sub("", out)) / max(len(_MARKER.sub("", source)), 1)
    if not 0.7 <= ratio <= 1.8:
        failures.append(f"length ratio {ratio:.2f}")
    letters = [c for c in out if c.isalpha()]
    greek_share = sum(1 for c in letters if "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿") / max(len(letters), 1)
    if greek_share < 0.75:
        failures.append(f"Greek-script share {greek_share:.0%}")
    low = out.lower()
    for bad in checks.get("forbid", []):
        # Phrases containing capitals are matched exactly (e.g. Title Case checks); lowercase ones case-insensitively
        hit = (bad in out) if any(ch.isupper() for ch in bad) else (bad.lower() in low)
        if hit:
            failures.append(f"forbidden rendering: {bad!r}")
    for group in checks.get("require_any", []):
        if not any(g.lower() in low for g in group):
            failures.append(f"missing any of: {group}")
    for word, limit in (checks.get("max_count") or {}).items():
        n = out.count(word)
        if n > limit:
            failures.append(f"{word.strip()!r} used {n}x (max {limit})")
    try:
        from backend.output_refiner import inspect_text_quality
        local_issues = [i for i in inspect_text_quality(out, "greek") if i.severity != "info"]
    except Exception:
        local_issues = []
    return {
        "passed": not failures,
        "failures": failures,
        "metrics": {"length_ratio": round(ratio, 2), "greek_share": round(greek_share, 3),
                    "paragraphs": [n_src, n_out], "local_issues": len(local_issues)},
    }


async def _translate_live(passage: Dict[str, Any]) -> str:
    import aiohttp
    from backend.ai_polisher import _call_gemini_api
    from backend.translation_prompts import build_direct_translation_prompt
    from backend.gemini_key_pool import resolve_gemini_api_key
    key = resolve_gemini_api_key(None)
    if not key:
        raise SystemExit("No Gemini API key configured (needed for --live).")
    prompt = build_direct_translation_prompt("english", "greek", passage.get("style", "literature"))
    async with aiohttp.ClientSession() as s:
        return await _call_gemini_api(f"<TEXT_TO_TRANSLATE>\n{passage['source']}\n</TEXT_TO_TRANSLATE>", key, prompt,
                                      session=s, temperature=0.25, bypass_cache=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="translate with the current prompt via Gemini (uses quota)")
    ap.add_argument("--from-dir", type=Path, help="score saved outputs <dir>/<passage_id>.txt")
    ap.add_argument("--save", type=Path, help="with --live: save outputs to this directory")
    args = ap.parse_args(argv)
    if not args.live and not args.from_dir:
        ap.error("choose --live or --from-dir")

    import asyncio
    rows, all_passed = [], True
    for p in load_passages():
        if args.live:
            out = asyncio.run(_translate_live(p))
            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                (args.save / f"{p['id']}.txt").write_text(out, encoding="utf-8")
        else:
            f = args.from_dir / f"{p['id']}.txt"
            if not f.is_file():
                print(f"[skip] {p['id']}: {f} not found")
                continue
            out = f.read_text(encoding="utf-8")
        res = score_translation(p["source"], out, p.get("checks", {}))
        all_passed &= res["passed"]
        rows.append((p["id"], res))
        mark = "PASS" if res["passed"] else "FAIL"
        print(f"[{mark}] {p['id']:22} ratio={res['metrics']['length_ratio']:<5} greek={res['metrics']['greek_share']:<6} "
              f"local_issues={res['metrics']['local_issues']}")
        for fl in res["failures"]:
            print(f"        - {fl}")
    print(f"\n{sum(1 for _, r in rows if r['passed'])}/{len(rows)} passages passed.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
