"""
epub_extras.py - A "Characters" page at the start of a translated EPUB, made from 👥 Characters & terms.

Each person (and each key term) with the spelling the translation uses (backend/book_names.py, the user's corrections
included), the original name, and what the reader learns about them where they first appear: no later turns of the
story. It is a page of its own after the cover and the table of contents, listed in the table of contents too.

Per book, in the job's epub_options.json: {"characters": true}. The book's EPUB with the page is a copy in extras/,
made again when the EPUB, the list or the names change; the EPUB itself is never altered.
"""

import html
import json
import logging
import os
import posixpath
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import unquote

logger = logging.getLogger(__name__)

OPTIONS_FILE = "epub_options.json"
EXTRAS_DIR = "extras"
PAGE_ID = "bookapp-characters"
PAGE_FILE = "bookapp-characters.xhtml"
MAX_DESCRIPTION = 400

TEXTS = {
    "greek": {"title": "Πρόσωπα", "people": "Πρόσωπα", "terms": "Όροι",
              "note": "Όπως τα γνωρίζει ο αναγνώστης όταν πρωτοεμφανίζονται, χωρίς όσα αποκαλύπτονται αργότερα."},
    "english": {"title": "Characters", "people": "Characters", "terms": "Terms",
                "note": "As the reader first meets them, without what the story reveals later."},
}


def _lang(target_lang: str) -> str:
    return "greek" if (target_lang or "").lower() in ("greek", "el") else "english"


def options(out_dir: Path) -> Dict[str, Any]:
    try:
        data = json.loads((Path(out_dir) / OPTIONS_FILE).read_text(encoding="utf-8"))
        return {"characters": bool(data.get("characters"))} if isinstance(data, dict) else {"characters": False}
    except (OSError, ValueError):
        return {"characters": False}


def set_options(out_dir: Path, characters: bool) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f".{OPTIONS_FILE}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(json.dumps({"characters": bool(characters)}), encoding="utf-8")
        os.replace(tmp, out_dir / OPTIONS_FILE)
    finally:
        tmp.unlink(missing_ok=True)
    return options(out_dir)


def _record_path(out_dir: Path, lang: str) -> Optional[Path]:
    from backend.book_insights import _stem
    p = Path(out_dir) / "insights" / f"{_stem('characters', lang)}.json"
    return p if p.is_file() else None


def entries(out_dir: Path, target_lang: str) -> Optional[Tuple[str, List[Dict[str, str]], List[Dict[str, str]]]]:
    """(language, people, terms) for the page, or None without a 👥 Characters & terms list in the translation's
    language. Each entry: {"name": as the translation writes it, "original": the book's own, "about": ...}."""
    from backend.book_insights import load_insight
    from backend.book_names import names_map
    lang = _lang(target_lang)
    rec = load_insight(Path(out_dir), "characters", lang)
    data = (rec or {}).get("data") or {}
    if not data.get("people") and not data.get("terms"):
        return None
    translated = {k.casefold(): v for k, v in names_map(Path(out_dir)).items()}

    def made(items: List[Dict[str, Any]], key: str, out_key: str, text_keys: Tuple[str, ...]) -> List[Dict[str, str]]:
        rows = []
        for item in items or []:
            original = str(item.get(key) or "").strip()
            if not original:
                continue
            name = translated.get(original.casefold()) or str(item.get(out_key) or "").strip() or original
            about = str(item.get("intro") or "").strip() or next(
                (str(item.get(k) or "").strip() for k in text_keys if str(item.get(k) or "").strip()), "")
            if len(about) > MAX_DESCRIPTION:
                about = about[:MAX_DESCRIPTION].rsplit(" ", 1)[0] + "…"
            rows.append({"name": name, "original": original if original.casefold() != name.casefold() else "",
                         "about": about})
        return rows

    people = made(data.get("people"), "name", "name_out", ("role",))
    terms = made(data.get("terms"), "term", "term_out", ("definition",))
    return (lang, people, terms) if people or terms else None


def page_xhtml(lang: str, people: List[Dict[str, str]], terms: List[Dict[str, str]], epub3: bool = True) -> str:
    """The page as XHTML for the book's EPUB version: an EPUB 2 book (many format-preserved ones) gets XHTML 1.1, which
    older readers (Adobe's, on many e-readers) expect, without the EPUB 3 section and its namespace."""
    t = TEXTS[lang]
    code = "el" if lang == "greek" else "en"
    esc = html.escape

    def block(title: str, rows: List[Dict[str, str]]) -> str:
        if not rows:
            return ""
        items = []
        for r in rows:
            orig = f' <span class="orig">({esc(r["original"])})</span>' if r["original"] else ""
            about = f"<dd>{esc(r['about'])}</dd>" if r["about"] else ""
            items.append(f"<dt>{esc(r['name'])}{orig}</dt>{about}")
        return f"<h2>{esc(title)}</h2>\n<dl>\n" + "\n".join(items) + "\n</dl>"

    body = "\n".join(b for b in (block(t["people"], people), block(t["terms"], terms)) if b)
    style = ('<style type="text/css">dt{font-weight:bold;margin-top:0.8em}dd{margin:0.2em 0 0 1.2em}'
             ".orig{font-weight:normal;font-style:italic}.note{font-size:0.85em;font-style:italic}</style>\n")
    content = f'<h1>{esc(t["title"])}</h1>\n<p class="note">{esc(t["note"])}</p>\n{body}\n'
    if epub3:
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{code}" '
            f'xml:lang="{code}">\n<head>\n<meta charset="utf-8"/>\n<title>{esc(t["title"])}</title>\n{style}</head>\n'
            f'<body>\n<section epub:type="dramatis-personae">\n{content}</section>\n</body>\n</html>\n'
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{code}">\n<head>\n'
        '<meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8"/>\n'
        f'<title>{esc(t["title"])}</title>\n{style}</head>\n<body>\n<div class="dramatis-personae">\n'
        f'{content}</div>\n</body>\n</html>\n'
    )


# ---------------------------------------------------------------------------
# Putting the page into an EPUB
# ---------------------------------------------------------------------------

_SKIP_AT_START = re.compile(r"cover|title|nav|toc|contents|copyright", re.IGNORECASE)


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag) or re.search(rf"\b{name}\s*=\s*'([^']*)'", tag)
    return html.unescape(m.group(1)) if m else ""


def _with_toc_entry_nav(nav: str, href: str, title: str) -> str:
    m = re.search(r"<nav\b[^>]*epub:type\s*=\s*[\"'][^\"']*\btoc\b[^\"']*[\"'][^>]*>", nav)
    if not m:
        return nav
    ol = re.compile(r"<ol\b[^>]*>").search(nav, m.end())
    if not ol:
        return nav
    li = f'<li><a href="{html.escape(href, quote=True)}">{html.escape(title)}</a></li>'
    return nav[: ol.end()] + li + nav[ol.end():]


def _with_toc_entry_ncx(ncx: str, href: str, title: str) -> str:
    m = re.search(r"<navMap\b[^>]*>", ncx)
    if not m:
        return ncx
    ncx = re.sub(r'playOrder="(\d+)"', lambda x: f'playOrder="{int(x.group(1)) + 1}"', ncx)
    m = re.search(r"<navMap\b[^>]*>", ncx)
    point = (f'<navPoint id="{PAGE_ID}" playOrder="1"><navLabel><text>{html.escape(title)}</text></navLabel>'
             f'<content src="{html.escape(href, quote=True)}"/></navPoint>')
    return ncx[: m.end()] + point + ncx[m.end():]


def add_page(src: Path, dest: Path, page: Union[str, Callable[[bool], str]], title: str) -> Path:
    """A copy of the EPUB `src` with the page after its cover and contents, in its spine and table of contents.
    `page`: its XHTML, or a function giving it for the book's version (True: EPUB 3)."""
    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        container = zin.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_path = _attr(re.search(r"<rootfile\b[^>]*>", container).group(0), "full-path")
        opf = zin.read(opf_path).decode("utf-8")
        if f'id="{PAGE_ID}"' in opf:
            raise ValueError("the EPUB already has the page")
        package = re.search(r"<(?:\w+:)?package\b[^>]*>", opf)
        epub3 = not (package and _attr(package.group(0), "version").startswith("2"))
        xhtml = page(epub3) if callable(page) else page
        opf_dir = posixpath.dirname(opf_path)
        page_path = posixpath.join(opf_dir, PAGE_FILE) if opf_dir else PAGE_FILE
        # an OPF may write its elements with a prefix (<opf:item>): the page's entries take the same one
        found_manifest = re.search(r"<(\w+:)?manifest\b", opf)
        prefix = (found_manifest.group(1) or "") if found_manifest else ""
        manifest = {}
        nav_path = ncx_path = ""
        for tag in re.findall(r"<(?:\w+:)?item\b[^>]*>", opf):
            item_id, href = _attr(tag, "id"), unquote(_attr(tag, "href"))
            full = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else posixpath.normpath(href)
            manifest[item_id] = href
            if "nav" in _attr(tag, "properties").split():
                nav_path = full
            if _attr(tag, "media-type") == "application/x-dtbncx+xml":
                ncx_path = full
        item = f'<{prefix}item id="{PAGE_ID}" href="{PAGE_FILE}" media-type="application/xhtml+xml"/>'
        opf = re.sub(r"</(\w+:)?manifest>", lambda m: item + m.group(0), opf, count=1)
        # after the cover, title page and contents at the start of the spine: before the book's first chapter
        refs = list(re.finditer(r"<(?:\w+:)?itemref\b[^>]*>", opf))
        at = None
        for ref in refs:
            idref = _attr(ref.group(0), "idref")
            if _attr(ref.group(0), "linear") == "no" or _SKIP_AT_START.search(idref + " " + manifest.get(idref, "")):
                continue
            at = ref.start()
            break
        itemref = f'<{prefix}itemref idref="{PAGE_ID}"/>'
        if at is not None:
            opf = opf[:at] + itemref + opf[at:]
        else:
            opf = re.sub(r"</(\w+:)?spine>", lambda m: itemref + m.group(0), opf, count=1)
        changed = {opf_path: opf.encode("utf-8"), page_path: xhtml.encode("utf-8")}
        for toc_path, add in ((nav_path, _with_toc_entry_nav), (ncx_path, _with_toc_entry_ncx)):
            if toc_path and toc_path in names:
                href = posixpath.relpath(page_path, posixpath.dirname(toc_path) or ".")
                changed[toc_path] = add(zin.read(toc_path).decode("utf-8"), href, title).encode("utf-8")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.stem}.{uuid.uuid4().hex[:8]}{dest.suffix}")
        try:
            with zipfile.ZipFile(tmp, "w") as zout:
                if "mimetype" in names:  # first and stored, as EPUB readers expect
                    zout.writestr(zipfile.ZipInfo("mimetype"), zin.read("mimetype"), compress_type=zipfile.ZIP_STORED)
                for info in zin.infolist():
                    if info.filename == "mimetype" or info.filename == page_path:
                        continue
                    data = changed.pop(info.filename, None)
                    zout.writestr(info, zin.read(info.filename) if data is None else data,
                                  compress_type=info.compress_type)
                for path, data in changed.items():
                    zout.writestr(path, data, compress_type=zipfile.ZIP_DEFLATED)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    return dest


def served_epub(out_dir: Path, epub: Path, target_lang: str) -> Path:
    """The EPUB to hand out: with the Characters page when the book asks for it and has the list, else `epub`."""
    out_dir = Path(out_dir)
    if not options(out_dir).get("characters"):
        return epub
    found = entries(out_dir, target_lang)
    if not found:
        return epub
    lang, people, terms = found
    rel = epub.relative_to(out_dir) if epub.is_relative_to(out_dir) else Path(epub.name)
    dest = out_dir / EXTRAS_DIR / rel
    sources = [epub, out_dir / OPTIONS_FILE, _record_path(out_dir, lang), out_dir / "book_names.json"]
    newest = max((p.stat().st_mtime for p in sources if p and p.is_file()), default=0)
    if dest.is_file() and dest.stat().st_mtime >= newest:
        return dest
    try:
        return add_page(epub, dest, lambda epub3: page_xhtml(lang, people, terms, epub3), TEXTS[lang]["title"])
    except Exception as e:  # a book whose EPUB cannot take the page is still handed out
        logger.warning(f"Characters page not added to {epub.name}: {e}")
        return epub
