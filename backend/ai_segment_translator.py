"""
ai_segment_translator.py - Gemini translation of ordered text *segments* (format-preserving AI translation).

Used by backend.format_preserver for DOCX/EPUB "in place" translation when AI Polish is on: the document's
paragraphs / runs / HTML text nodes are collected in order, translated here in numbered batches (so the model
sees neighbouring context), and written back into exactly the same places — fonts, styles, tables, images and
HTML/CSS stay untouched.

Protocol: each segment is sent as `⟦n⟧ text` on its own block; the model must return every marker once, in order.
Robustness: missing/empty/duplicated segments fall back to the free engine individually; a batch with too many
problems is retried once in halves; quota errors either fall back (quota_behavior='fallback') or propagate.
Batches go through _call_gemini_api (pool rotation, rate limiting, SQLite cache), so a resumed job re-uses
already translated batches without new API calls.
"""

import re
import asyncio
import logging
from typing import Optional, Callable, List, Dict

logger = logging.getLogger(__name__)

MAX_BATCH_CHARS = 4000
MAX_BATCH_SEGMENTS = 60
_MARKER_RE = re.compile(r"⟦(\d{1,5})⟧")

_SEGMENT_PROTOCOL_EL = (
    "\nΜΟΡΦΗ ΕΙΣΟΔΟΥ/ΕΞΟΔΟΥ (ΑΥΣΤΗΡΟ): Το κείμενο αποτελείται από αριθμημένα τμήματα της μορφής ⟦n⟧ κείμενο, με τη σειρά "
    "που εμφανίζονται στο έγγραφο (παράγραφοι, επικεφαλίδες, κελιά πινάκων ή κομμάτια μίας πρότασης με διαφορετική "
    "μορφοποίηση). Μετάφρασε ΚΑΘΕ τμήμα και επίστρεψε ΟΛΑ τα τμήματα με τους ΙΔΙΟΥΣ δείκτες ⟦n⟧, με την ίδια σειρά, ένα "
    "ανά μπλοκ. ΜΗΝ ενώνεις, ΜΗΝ χωρίζεις και ΜΗΝ παραλείπεις τμήματα. Όταν διαδοχικά τμήματα είναι κομμάτια της ίδιας "
    "πρότασης, μετάφρασέ τα ώστε η πρόταση να διαβάζεται σωστά όταν ενωθούν με τη σειρά. Τμήματα που είναι αριθμοί, "
    "κωδικοί ή κύρια ονόματα μένουν όπως είναι όταν δεν μεταφράζονται.\n"
)
_SEGMENT_PROTOCOL_EN = (
    "\nINPUT/OUTPUT FORMAT (STRICT): the text consists of numbered segments `⟦n⟧ text`, in document order (paragraphs, "
    "headings, table cells, or pieces of one sentence with different formatting). Translate EVERY segment and return ALL "
    "segments with the SAME ⟦n⟧ markers, in the same order, one per block. Never merge, split or drop segments. When "
    "consecutive segments are pieces of one sentence, translate them so the sentence reads correctly when joined in "
    "order. Numbers, codes and proper names stay as they are when they are not translated.\n"
)


def _batches(segments: List[str], max_chars: int = MAX_BATCH_CHARS) -> List[List[int]]:
    out, cur, size = [], [], 0
    for i, s in enumerate(segments):
        ln = len(s) + 8
        if cur and (size + ln > max_chars or len(cur) >= MAX_BATCH_SEGMENTS):
            out.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += ln
    if cur:
        out.append(cur)
    return out


def parse_segments(output: str, expected_ids: List[int]) -> Dict[int, str]:
    """Parses `⟦n⟧ text` blocks; returns {n: text} for expected ids that appear exactly once."""
    parts = _MARKER_RE.split(output or "")
    found: Dict[int, List[str]] = {}
    for k in range(1, len(parts) - 1, 2):
        try:
            n = int(parts[k])
        except ValueError:
            continue
        found.setdefault(n, []).append(parts[k + 1].strip())
    return {n: v[0] for n, v in found.items() if n in expected_ids and len(v) == 1 and v[0]}


async def translate_segments_with_gemini(
    segments: List[str],
    source_lang: str,
    target_lang: str,
    api_key: str,
    style: str = "literature",
    quota_behavior: str = "wait",
    progress: Optional[Callable[[int, int], None]] = None,
    fallback_translate: Optional[Callable[[str], "asyncio.Future"]] = None,
    max_batch_chars: int = MAX_BATCH_CHARS,
) -> List[str]:
    """Translates segments in order; the result list is aligned 1:1 with the input."""
    import aiohttp
    from backend.ai_polisher import (
        _call_gemini_api, _extract_entity_dossier, _script_counts, english_glossary_rules, DailyQuotaExhaustedError,
    )
    from backend.translation_prompts import build_direct_translation_prompt, dossier_header, is_greek
    from backend.glossary import load_glossary

    if fallback_translate is None:
        from backend.translator import _translate_with_retry

        async def fallback_translate(t: str) -> str:
            return await _translate_with_retry(t, source_lang, target_lang)

    results: List[Optional[str]] = [None] * len(segments)
    todo = [i for i, s in enumerate(segments) if s.strip()]
    for i, s in enumerate(segments):
        if not s.strip():
            results[i] = s
    if not todo:
        return [r or "" for r in results]

    greek = is_greek(target_lang)
    system = build_direct_translation_prompt(source_lang, target_lang, style)
    system += _SEGMENT_PROTOCOL_EL if greek else _SEGMENT_PROTOCOL_EN
    full_text = "\n\n".join(segments[i] for i in todo)

    async with aiohttp.ClientSession() as session:
        if len(full_text) > 18000:
            dossier = await _extract_entity_dossier(full_text, api_key, session=session, target_lang=target_lang)
            if dossier:
                system += dossier_header("translation", target_lang) + dossier + "\n"
        glossary = load_glossary(style=style) or {}
        low = full_text.lower()
        matched = [(k, v) for k, v in glossary.items() if k.lower() in low][:50] if greek else []
        if not greek:
            system += english_glossary_rules(glossary, full_text)
        if matched:
            system += "\n--- GLOSSARY ---\n" + "\n".join(f"- {k} -> {v}" for k, v in matched) + "\n"

        sem = asyncio.Semaphore(3)
        done = 0
        quota_hit = False
        # batch over the non-empty segments only; _batches returns positions in `todo`
        batches = [[todo[k] for k in b] for b in _batches([segments[i] for i in todo], max_batch_chars)]

        async def _translate_batch(ids: List[int], depth: int = 0):
            nonlocal quota_hit
            if quota_hit:
                return
            numbered = "\n\n".join(f"⟦{k + 1}⟧ {segments[i]}" for k, i in enumerate(ids))
            content = f"<TEXT_TO_TRANSLATE>\n{numbered}\n</TEXT_TO_TRANSLATE>"
            try:
                out = await _call_gemini_api(content, api_key, system, session=session, temperature=0.25,
                                             cache_gate=lambda o: bool(_MARKER_RE.search(o or "")))
            except DailyQuotaExhaustedError:
                if quota_behavior == "fallback":
                    quota_hit = True
                    return
                raise
            except PermissionError:
                raise
            except Exception as e:
                logger.warning(f"AI segment batch failed ({e}); falling back for {len(ids)} segments.")
                return
            got = parse_segments(out, list(range(1, len(ids) + 1)))
            if not greek:  # a segment left in Greek is not an English translation
                for k, value in list(got.items()):
                    in_greek, in_latin = _script_counts(value)
                    if in_greek >= 20 and in_greek > in_latin:
                        del got[k]
            missing = [k for k in range(1, len(ids) + 1) if k not in got]
            if len(missing) > max(2, len(ids) // 4) and len(ids) > 1 and depth < 2:
                mid = len(ids) // 2
                await _translate_batch(ids[:mid], depth + 1)
                await _translate_batch(ids[mid:], depth + 1)
                return
            for k, i in enumerate(ids, start=1):
                if k in got:
                    results[i] = got[k]

        async def _run(ids):
            nonlocal done
            async with sem:
                await _translate_batch(ids)
            done += len(ids)
            if progress:
                progress(done, len(todo))

        from backend.async_utils import gather_or_cancel
        await gather_or_cancel(_run(b) for b in batches)

    fallbacks = [i for i in todo if not (results[i] or "").strip()]
    if fallbacks:
        logger.info(f"AI segment translation: {len(fallbacks)}/{len(todo)} segments translated by the free engine.")
    for i in fallbacks:
        # a failure stops the job: source text must not be passed off as a translation
        results[i] = await fallback_translate(segments[i])
    return [r if r is not None else "" for r in results]
