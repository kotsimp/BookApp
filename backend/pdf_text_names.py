"""
pdf_text_names.py - Makes the text of the app's PDFs copy, search and read back as the characters that were written.

A font often draws several characters with one glyph: the space and the no-break space, the hyphen and the soft
hyphen, ';' and the Greek question mark, 'ά' and its polytonic twin 'ά'. A PDF names each glyph by one character
only (its ToUnicode map), and MuPDF picks one of the twins: copied text then holds invisible soft hyphens instead of
hyphens, no-break spaces, Greek question marks in English, and Greek vowels that a search for the word misses.

fix_text_names() renames those shared glyphs after the text has been drawn and before the fonts are subsetted
(a subset no longer has the font's own character table): to the twin the book's text uses, else the canonical one.
"""
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

_INVISIBLE = {0x00A0, 0x00AD, 0x2007, 0x2011, 0x202F, 0x2060, 0xFEFF}  # twins of a visible, plain character
_HEX_RE = re.compile(r"<([0-9A-Fa-f]*)>|\[|\]")


def _rank(cp: int, used: set) -> tuple:
    """Lower is better: a character of the text, canonical, visible, ASCII, compatibility-stable."""
    ch = chr(cp)
    return (
        ch not in used,
        unicodedata.normalize("NFC", ch) != ch,
        cp in _INVISIBLE or unicodedata.category(ch) in ("Zs", "Cf"),
        cp >= 0x80,
        unicodedata.normalize("NFKC", ch) != ch,
    )


def _parse_tounicode(data: str) -> dict:
    """{cid: text} of a ToUnicode CMap (bfchar and bfrange, also with arrays)."""
    names: dict = {}

    def text(hexstr: str) -> str:
        raw = bytes.fromhex(hexstr if len(hexstr) % 4 == 0 else hexstr.zfill(len(hexstr) + 4 - len(hexstr) % 4))
        return raw.decode("utf-16-be", errors="surrogatepass")

    for block in re.findall(r"beginbfchar(.*?)endbfchar", data, re.S):
        tokens = re.findall(r"<([0-9A-Fa-f]*)>", block)
        for src, dst in zip(tokens[0::2], tokens[1::2]):
            names[int(src, 16)] = text(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", data, re.S):
        tokens = [m.group(1) if m.group(1) is not None else m.group(0) for m in _HEX_RE.finditer(block)]
        i = 0
        while i + 2 < len(tokens):
            first, last = int(tokens[i], 16), int(tokens[i + 1], 16)
            if tokens[i + 2] == "[":
                end = tokens.index("]", i + 3)
                for offset, dst in enumerate(tokens[i + 3:end]):
                    names[first + offset] = text(dst)
                i = end + 1
                continue
            start = text(tokens[i + 2])
            for offset in range(last - first + 1):
                names[first + offset] = start[:-1] + chr(ord(start[-1]) + offset) if start else ""
            i += 3
    return names


def _write_tounicode(names: dict) -> bytes:
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    items = sorted(names.items())
    for start in range(0, len(items), 100):
        chunk = items[start:start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        lines.extend(f"<{cid:04X}> <{value.encode('utf-16-be', errors='surrogatepass').hex().upper()}>"
                     for cid, value in chunk)
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode("ascii")


def fix_text_names(doc, text: str = "") -> int:
    """
    Renames the glyphs that several characters share, in every embedded TrueType CID font of `doc` that still has
    its character table; `text` is what was drawn, so that its own characters win. Returns the glyphs renamed.
    Never raises: a font it cannot read keeps the names it had.
    """
    import pymupdf

    used = set(text) | set(unicodedata.normalize("NFC", text)) | set(text.upper())  # comics are in capitals
    renamed, seen = 0, set()
    for page in doc:
        for xref, *_rest in page.get_fonts(full=True):
            if xref in seen:
                continue
            seen.add(xref)
            try:
                renamed += _fix_font(doc, xref, used, pymupdf)
            except Exception as e:  # a name stays as MuPDF wrote it: the PDF itself is fine
                logger.debug(f"PDF font {xref}: glyph names kept ({e})")
    return renamed


def _fix_font(doc, xref: int, used: set, pymupdf) -> int:
    if doc.xref_get_key(xref, "Subtype")[1] != "/Type0" or doc.xref_get_key(xref, "Encoding")[1] != "/Identity-H":
        return 0
    kind, value = doc.xref_get_key(xref, "ToUnicode")
    descendants = doc.xref_get_key(xref, "DescendantFonts")
    if kind != "xref" or descendants[0] not in ("array", "xref"):
        return 0
    child = int(re.search(r"(\d+)\s+0\s+R", descendants[1]).group(1)) if descendants[0] == "array" else \
        int(re.search(r"(\d+)\s+0\s+R", doc.xref_object(int(descendants[1].split()[0]))).group(1))
    if doc.xref_get_key(child, "Subtype")[1] != "/CIDFontType2":
        return 0
    if doc.xref_get_key(child, "CIDToGIDMap")[0] not in ("null", "name"):
        return 0  # glyphs are not numbered by CID
    buffer = doc.extract_font(xref)[3]
    if not buffer:
        return 0
    font = pymupdf.Font(fontbuffer=buffer)
    twins: dict = {}
    for cp in font.valid_codepoints():
        gid = font.has_glyph(cp)
        if gid:
            twins.setdefault(gid, []).append(cp)
    twins = {gid: cps for gid, cps in twins.items() if len(cps) > 1}
    if not twins:
        return 0
    tu_xref = int(value.split()[0])
    names = _parse_tounicode(doc.xref_stream(tu_xref).decode("latin-1"))
    renamed = 0
    for gid, cps in twins.items():
        current = names.get(gid)
        if current is None or len(current) != 1 or ord(current) not in cps:
            continue
        best = min(cps, key=lambda cp: (_rank(cp, used), cp))
        if _rank(best, used) < _rank(ord(current), used):  # ties keep the name MuPDF chose
            names[gid] = chr(best)
            renamed += 1
    if renamed:
        doc.update_stream(tu_xref, _write_tounicode(names))
    return renamed
