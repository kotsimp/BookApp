# exporter.py - Export translated text to various formats (Standard & Literature/E-Reader)

import functools
import hashlib
import html
import io
import logging
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


def extract_cover_image(file_path: Optional[Union[str, Path]]) -> Optional[bytes]:
    """
    Extracts the original cover image from an input book (PDF, DOCX, or EPUB).
    Returns raw image bytes (JPEG/PNG) or None if no cover is found.
    """
    if not file_path:
        return None
    p = Path(file_path)
    if not p.exists():
        return None

    ext = p.suffix.lower()

    if ext == ".pdf":
        try:
            import pymupdf
            with pymupdf.open(str(p)) as doc:
                if len(doc) == 0:
                    return None
                p0 = doc[0]
                imgs = p0.get_images()
                text_len = len(p0.get_text().strip())
                # A cover page typically has images and little/no textual prose (< 150 chars),
                # or has an image covering most of the page.
                if imgs or text_len < 150:
                    pix = p0.get_pixmap(dpi=150)
                    return pix.tobytes("jpeg")
        except Exception:
            pass

    elif ext == ".docx":
        try:
            import docx
            doc = docx.Document(str(p))
            for rel in doc.part.rels.values():
                if "image" in rel.target_ref:
                    return rel.target_part.blob
        except Exception:
            pass

    elif ext == ".epub":
        try:
            import ebooklib
            from ebooklib import epub
            book = epub.read_epub(str(p))
            for it in book.get_items():
                name_l = it.get_name().lower()
                if "cover" in name_l and getattr(it, "content", None):
                    if it.get_type() in (ebooklib.ITEM_COVER, ebooklib.ITEM_IMAGE) or name_l.endswith((".jpg", ".jpeg", ".png")):
                        return it.content
            # Fallback: check first image item in the epub
            for it in book.get_items():
                if it.get_type() == ebooklib.ITEM_IMAGE and getattr(it, "content", None):
                    return it.content
        except Exception:
            pass

    return None


_PUA_MAP = {
    "\uf0b7": "• ",  # Wingdings round bullet
    "\uf0a7": "• ",  # Wingdings square bullet
    "\uf076": "✓ ",  # Checkmark
    "\uf0d8": "➢ ",  # Arrow
    "\uf0fc": "✔ ",  # Heavy check
    "\uf0e0": "✉ ",  # Envelope
    "\uf0a8": "❖ ",
    "\uf02d": "-",
}

_CHAPTER_RE = re.compile(
    r"^(?:"
    r"(?:chapter|chap\.|part|book|prologue|epilogue|preface|introduction|afterword|acknowledgments|notes\s*and\s*references|license)"
    r"(?:\s+[\w\d\.\-]+(?:\s*[:\-–—]\s*.+)?)?"
    r"|(?:κ[εέ]φ[αά]λαιο|κεφ\.|μ[εέ]ρος|βιβλ[ιί]ο|πρ[οό]λογος|επ[ιί]λογος|εισαγωγ[ηή]|ευχαριστ[ιί]ες|σημει[ώω]σεις(?:\s*και\s*παραπομπ[εέ]ς)?|[αά]δεια)"
    r"(?:\s+[\w\d\.\-]+(?:\s*[:\-–—]\s*.+)?)?"
    r")$",
    re.IGNORECASE,
)
_STRICT_ROMAN_CHAPTER_RE = re.compile(r"^(?:X{0,3})(?:IX|IV|V?I{0,3})$")

_SCENE_BREAK_RE = re.compile(r"^(?:\*\s*\*\s*\*+|---\s*|~~~\s*|•\s*•\s*•+)$")


# Only emphasis markup left over from a model. A standalone tag is the book's text ('the <p> element').
_EXPORT_HTML_PAIR_RE = re.compile(r"<(i|b|em|strong|u|span)>([^<>\n]+)</\1>", re.IGNORECASE)
_EXPORT_HTML_TAG_RE = re.compile(
    r"(?<=\w)</?(?:i|b|em|strong|u|s|span|sup|sub|small|big|mark|del|ins)>(?=\w)"
    r"|(?<=\S)</(?:i|b|em|strong|u|span)>",
    re.IGNORECASE,
)
_EXPORT_SPECIAL_TOKEN_RE = re.compile(
    r"<(?:/?(?:bos|eos|pad|unk|sep|cls|mask|start_of_turn|end_of_turn)|\|[^|\n]{1,32}\|)>",
    re.IGNORECASE,
)
# Both markers hug their words and stand outside words: '2**10', '**kwargs' and '*.txt' are the book's text
_EMPHASIS_TOKEN_RE = re.compile(
    r"((?<![\w*])\*\*(?!\s)[^*\n]+?(?<!\s)\*\*(?![\w*])|(?<![\w*])\*(?!\s)[^*\n]+?(?<!\s)\*(?![\w*]))"
)
_XML_ILLEGAL_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Scripts that need shaping or run right to left: U+0590-109F, U+1780-17FF and the Arabic/Hebrew presentation forms
_SHAPED = r"\u0590-\u109f\u1780-\u17ff\ufb1d-\ufdff\ufe70-\ufefc"
_SHAPED_RE = re.compile(f"[{_SHAPED}]")
# Zero-width (non-)joiners spell words in Persian and Indic scripts, and are garbage after any other character
_INVISIBLE_GARBAGE_RE = re.compile(
    r"[\ufffd\u00ad\ufeff\u200b\u200e\u200f\u202a-\u202e\u2060-\u206f]"
    f"|(?<![{_SHAPED}])[" + r"\u200c\u200d]"
)
_EXOTIC_SPACE_RE = re.compile(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]")
_UNICODE_PUNCT_NORMALIZE = {
    "\u2010": "-",   # hyphen
    "\u2011": "-",   # non-breaking hyphen
    "\u2012": "–",   # figure dash
    "\u2212": "-",   # minus sign
    "\u2032": "'",   # prime
    "\u2033": '"',   # double prime
    "\u2028": "\n",  # line separator
    "\u2029": "\n\n",  # paragraph separator
}
_PDF_GLYPH_FALLBACKS = {
    "•": "-",
    "—": "-",
    "–": "-",
    "…": "...",
    "«": '"',
    "»": '"',
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "×": "x",
    "÷": "/",
    "±": "+/-",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "→": "->",
    "←": "<-",
    "↔": "<->",
    "✓": "v",
    "✔": "v",
    "➢": ">",
    "❖": "*",
    "✉": "",
}


def _sanitize_pua(text: str, editorial: bool = True) -> str:
    """
    Map Wingdings / Symbol Private Use Area (PUA) characters to standard Unicode,
    normalize exotic Unicode spaces/dashes, strip XML-illegal / replacement / zero-width
    control characters, stray inline HTML tags, LLM special tokens, and broken Greek hyphens.
    """
    if not text:
        return ""
    for pua, repl in _PUA_MAP.items():
        text = text.replace(pua, repl)
    text = re.sub(r"[\ue000-\uf8ff]", "• ", text)
    for ch, repl in _UNICODE_PUNCT_NORMALIZE.items():
        if ch in text:
            text = text.replace(ch, repl)
    text = _EXOTIC_SPACE_RE.sub(" ", text)
    text = _INVISIBLE_GARBAGE_RE.sub("", text)
    text = _XML_ILLEGAL_CTRL_RE.sub("", text)
    if not editorial:
        return text  # character normalisation only: source text, or text that has been cleaned already
    text = _EXPORT_SPECIAL_TOKEN_RE.sub("", text)
    text = _EXPORT_HTML_PAIR_RE.sub(r"\2", text)
    text = _EXPORT_HTML_TAG_RE.sub("", text)
    try:
        from backend.typography import fix_broken_hyphens, sanitize_editorial_pass, is_mostly_greek
        text = fix_broken_hyphens(text)
        if is_mostly_greek(text):
            text = sanitize_editorial_pass(text)
    except Exception:
        pass
    return text


def _sanitize_for_pdf_font(text: str, font_obj) -> str:
    """
    Replaces or strips any character not present in font_obj so PyMuPDF never renders
    hollow tofu/missing-glyph boxes (□ / \\x00) in exported PDFs.
    """
    if not text or font_obj is None or not hasattr(font_obj, "has_glyph"):
        return text or ""
    out: list[str] = []
    changed = False
    own = getattr(font_obj, "base", font_obj)
    for ch in text:
        # the book's own font first, then a plain replacement, only then a glyph from another font
        if ch.isspace() or ((ch not in _PDF_GLYPH_FALLBACKS or own.has_glyph(ord(ch))) and font_obj.has_glyph(ord(ch))):
            out.append(ch)
        else:
            changed = True
            fb = _PDF_GLYPH_FALLBACKS.get(ch, "")
            if fb:
                safe_fb = "".join(c for c in fb if c.isspace() or font_obj.has_glyph(ord(c)))
                if safe_fb:
                    out.append(safe_fb)
    return "".join(out) if changed else text


# Punctuation around a right-to-left quotation belongs to the left-to-right line that holds it
_EDGE_PUNCT_RE = re.compile(r"^([\s!-/:-@\[-`{-~«»“”‘’„…—–]*)(.*?)([\s!-/:-@\[-`{-~«»“”‘’„…—–]*)$", re.S)
_FONT_DIRS = ("C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu", "/System/Library/Fonts/Supplemental")
# Fonts that stand in, word by word, for what the book's own font lacks (polytonic Greek, phonetics, symbols)
_SUBSTITUTE_FONTS = {
    "r": ("times.ttf", "Times New Roman.ttf", "DejaVuSerif.ttf", "pala.ttf", "arial.ttf", "DejaVuSans.ttf", "seguisym.ttf"),
    "i": ("timesi.ttf", "Times New Roman Italic.ttf", "DejaVuSerif-Italic.ttf", "palai.ttf", "ariali.ttf"),
    "b": ("timesbd.ttf", "Times New Roman Bold.ttf", "DejaVuSerif-Bold.ttf", "palab.ttf", "arialbd.ttf"),
}
_SUBSTITUTE_FONTS_SANS = ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf", "times.ttf", "DejaVuSerif.ttf", "seguisym.ttf")


_ITALIC_SLANT = 0.2  # how far a regular face leans where a family has no italic face (as browsers draw it)


def _complete_family(families) -> tuple:
    """
    The faces of the first family whose every face exists, else of the first family whose regular face exists
    (a face it lacks is None), else (None, None, None). A family is a tuple of font paths, regular first.
    """
    present = [tuple(p if p and os.path.exists(p) else None for p in family) for family in families]
    found = next((f for f in present if all(f)), None) or next((f for f in present if f[0]), None)
    return found or (None, None, None)


def _family_for(text: str, family: tuple) -> tuple:
    """
    (regular, italic, bold) for a literature PDF. A quotation can borrow a font word by word; a whole book of it
    (polytonic Greek, phonetics) gets a family that has every character: one look, and far faster.
    """
    if not family[0]:
        return family
    import pymupdf
    own = pymupdf.Font(fontfile=family[0])
    counts = Counter(text)
    lacking = {ch: n for ch, n in counts.items() if 0x100 <= ord(ch) < 0x2000 and not _SHAPED_RE.match(ch)
               and not ch.isspace() and not own.has_glyph(ord(ch))}
    if sum(lacking.values()) <= max(20, len(text) // 500):
        return family
    for names in zip(*(_SUBSTITUTE_FONTS[style][:4] for style in ("r", "i", "b"))):
        paths = tuple(next((f"{d}/{name}" for d in _FONT_DIRS if os.path.exists(f"{d}/{name}")), None) for name in names)
        if not all(paths):
            continue
        regular = pymupdf.Font(fontfile=paths[0])
        if all(regular.has_glyph(ord(ch)) for ch in lacking if unicodedata.category(ch) != "Cn"):
            return paths
    return family


def _shaped_html(text: str, size: float, style: str, serif: bool, color=(0, 0, 0)) -> tuple:
    """(html, css) of one unbroken line, for MuPDF's engine: it shapes, orders and has fonts for every script."""
    letters = [ch for ch in text if ch.isalpha()]
    rtl = bool(letters) and all(unicodedata.bidirectional(ch) in ("R", "AL") for ch in letters)
    rgb = ",".join(str(round(255 * part)) for part in color)
    css = (f"* {{margin:0; padding:0}} p {{font-family:{'serif' if serif else 'sans-serif'}; font-size:{size}px; "
           f"line-height:2; white-space:nowrap; text-align:left; color:rgb({rgb}); "
           f"font-weight:{'bold' if style == 'b' else 'normal'}; font-style:{'italic' if style == 'i' else 'normal'}}}")
    return f'<p dir="{"rtl" if rtl else "ltr"}">{html.escape(text)}</p>', css


@functools.lru_cache(maxsize=8192)
def _measure_shaped(text: str, size: float, style: str, serif: bool) -> tuple:
    """(width, left edge, baseline) of the line inside the box that _shaped_box gives."""
    import pymupdf
    box = _shaped_box(size)
    body, css = _shaped_html(text, size, style, serif)
    with pymupdf.open() as scratch:
        page = scratch.new_page(width=box[0], height=box[1])
        page.insert_htmlbox(pymupdf.Rect(0, 0, *box), body, css=css)
        spans = [span for block in page.get_text("dict")["blocks"] for line in block.get("lines", ())
                 for span in line["spans"] if span["text"].strip()]
    if not spans:
        return 0.0, 0.0, size
    left = min(span["bbox"][0] for span in spans)
    return max(span["bbox"][2] for span in spans) - left, left, spans[0]["origin"][1]


def _shaped_box(size: float) -> tuple:
    return 4000.0, size * 4.0


class _BookFont:
    """
    The book's font plus stand-ins, so that no script is lost: a substitute font for a word it cannot write,
    PyMuPDF's CJK font for East Asian characters, and shaped text for everything else.
    """

    SHAPED = "shaped"
    CJK = "cjk"

    def __init__(self, base, style: str = "r", serif: bool = True, builtin: bool = False, slant: float = 0.0):
        self.base, self.style, self.serif = base, style, serif
        self.slant = slant  # the regular face drawn leaning, standing in for an italic face the system lacks
        self.builtin = builtin  # a PDF base-14 font writes Latin-1 only
        self._cjk = None
        self._own: dict[str, bool] = {}
        self._words: dict[str, list] = {}
        self._substitutes = None
        self._bundled = None
        self.stood_in = False  # a stand-in was drawn: the file then needs its fonts subsetted

    @property
    def cjk(self):
        if self._cjk is None:
            import pymupdf
            self._cjk = pymupdf.Font("cjk")
        return self._cjk

    @property
    def substitutes(self) -> list:
        if self._substitutes is None:
            import pymupdf
            self._substitutes = []
            names = _SUBSTITUTE_FONTS[self.style] if self.serif else _SUBSTITUTE_FONTS_SANS
            for name in names:
                path = next((f"{d}/{name}" for d in _FONT_DIRS if os.path.exists(f"{d}/{name}")), None)
                if path:
                    try:
                        self._substitutes.append((path, pymupdf.Font(fontfile=path)))
                    except Exception as ex:
                        logger.debug(f"Cannot use font {path}: {ex}")
        return self._substitutes

    def own(self, ch: str) -> bool:
        """True where the book's font can write the character correctly by itself."""
        known = self._own.get(ch)
        if known is None:
            known = ch.isspace() or (
                not _SHAPED_RE.match(ch)
                and (ord(ch) < 256 if self.builtin else True)
                and bool(self.base.has_glyph(ord(ch)))
            )
            self._own[ch] = known
        return known

    def uses_cjk(self, ch: str) -> bool:
        code = ord(ch)
        return code >= 0x1100 and not self.own(ch) and (
            code < 0x1200 or code >= 0x2E80) and bool(self.cjk.has_glyph(code))

    def has_glyph(self, code: int):
        ch = chr(code)
        if self.own(ch) or code in (0x200C, 0x200D) or self.uses_cjk(ch):
            return True
        if unicodedata.category(ch)[0] == "C":
            return False
        if self._bundled is None:
            import pymupdf
            self._bundled = pymupdf.Font()
        return bool(self._bundled.has_glyph(code, fallback=True)) or any(
            font.has_glyph(code) for _, font in self.substitutes)

    def _word_runs(self, word: str) -> list:
        if word in self._words:
            return self._words[word]
        if _SHAPED_RE.search(word):
            runs = [(self.SHAPED, word)]
        elif all(self.own(ch) for ch in word):
            runs = [(None, word)]
        elif any(self.uses_cjk(ch) for ch in word):
            runs = []  # East Asian text has no spaces: character by character
            for ch in word:
                kind = None if self.own(ch) else (self.CJK if self.uses_cjk(ch) else self.SHAPED)
                if runs and runs[-1][0] == kind:
                    runs[-1] = (kind, runs[-1][1] + ch)
                else:
                    runs.append((kind, ch))
        else:
            # the whole word in one font: accents from another typeface inside a word look broken
            found = next((sub for sub in self.substitutes if all(sub[1].has_glyph(ord(ch)) for ch in word)), None)
            runs = [(found or self.SHAPED, word)]
        self._words[word] = runs
        return runs

    def runs(self, text: str) -> list:
        """[(kind, text)]: kind is None (own font), CJK, SHAPED or a substitute (path, font)."""
        if all(self.own(ch) for ch in text):
            return [(None, text)]
        out: list = []
        for token in re.split(r"(\s+)", text):
            if not token:
                continue
            for kind, part in ([(None, token)] if token.isspace() else self._word_runs(token)):
                # spaces, digits and punctuation between two shaped runs are ordered with them
                if (kind == self.SHAPED and len(out) > 1 and out[-1][0] is None and out[-2][0] == self.SHAPED
                        and not any(c.isalpha() for c in out[-1][1])):
                    part = out.pop()[1] + part
                if out and out[-1][0] == kind:
                    out[-1] = (kind, out[-1][1] + part)
                else:
                    out.append((kind, part))
        if not any(kind != self.SHAPED and any(c.isalpha() for c in part) for kind, part in out):
            return out  # nothing left-to-right: the line is ordered as a whole
        mixed: list = []
        for kind, part in out:
            pieces = [(kind, part)]
            if kind == self.SHAPED:
                before, middle, after = _EDGE_PUNCT_RE.match(part).groups()
                if middle:
                    pieces = [(None, before), (kind, middle), (None, after)]
            for piece_kind, piece in pieces:
                if piece_kind is None and not all(self.own(c) for c in piece):
                    piece_kind = kind
                if not piece:
                    continue
                if mixed and mixed[-1][0] == piece_kind:
                    mixed[-1] = (piece_kind, mixed[-1][1] + piece)
                else:
                    mixed.append((piece_kind, piece))
        return mixed

    def width(self, kind, text: str, fontsize: float) -> float:
        if kind == self.SHAPED:
            # shaping never crosses a space, and words repeat: measure word by word
            words = text.split(" ")
            space = self.base.text_length(" ", fontsize=fontsize)
            return space * (len(words) - 1) + sum(
                _measure_shaped(w, fontsize, self.style, self.serif)[0] for w in words if w)
        font = self.base if kind is None else (self.cjk if kind == self.CJK else kind[1])
        return font.text_length(text, fontsize=fontsize)

    def text_length(self, text: str, fontsize: float = 11) -> float:
        return sum(self.width(kind, part, fontsize) for kind, part in self.runs(text))


def _draw_pdf_text(page, point, text: str, font: "_BookFont", fontsize: float, fontname: str, color) -> None:
    import pymupdf
    x, y = point.x, point.y
    for kind, part in font.runs(text):
        font.stood_in = font.stood_in or kind is not None
        if kind == font.SHAPED:
            width, left, baseline = _measure_shaped(part, fontsize, font.style, font.serif)
            box = _shaped_box(fontsize)
            top_left = pymupdf.Point(x - left, y - baseline)
            body, css = _shaped_html(part, fontsize, font.style, font.serif, color)
            page.insert_htmlbox(pymupdf.Rect(top_left, top_left + pymupdf.Point(*box)), body, css=css)
            x += width
            continue
        name, source = fontname, None
        if kind == font.CJK:
            name, source = "book_cjk", {"fontbuffer": font.cjk.buffer}
        elif kind is not None:
            name, source = "book_" + hashlib.sha1(kind[0].encode("utf-8")).hexdigest()[:8], {"fontfile": kind[0]}
        if source and not any(f[4] == name for f in page.get_fonts()):
            page.insert_font(fontname=name, **source)
        if font.slant:
            origin = pymupdf.Point(x, y)
            page.insert_text(origin, part, fontsize=fontsize, fontname=name, color=color,
                             morph=(origin, pymupdf.Matrix(1, 0, font.slant, 1, 0, 0)))
        else:
            page.insert_text((x, y), part, fontsize=fontsize, fontname=name, color=color)
        x += font.width(kind, part, fontsize)


def _save_pdf(doc, out_path, fonts: list, text: str = "") -> None:
    from backend.pdf_text_names import fix_text_names
    fix_text_names(doc, text)  # before subsetting: a subset has lost the font's own character table
    if not any(font.stood_in for font in fonts):
        doc.save(str(out_path))
        return
    try:
        doc.subset_fonts()  # stand-in fonts are embedded whole, and once per shaped piece: megabytes for one quotation
    except Exception as ex:
        logger.warning(f"PDF fonts were not subsetted: {ex}")
    doc.save(str(out_path), garbage=3, deflate=True)


def _split_oversized_token(token: str, font_obj, fontsize: float, max_w: float) -> list[str]:
    """
    Splits a single unbroken token (such as a long URL) that exceeds max_w into
    margin-safe chunks, preferring natural delimiters ('/', '?', '&', '=', '-', '_', '.')
    before falling back to clean character boundaries so text never clips past the right margin.
    """
    if not token or max_w <= 10.0:
        return [token] if token else []
    if font_obj.text_length(token, fontsize=fontsize) <= max_w:
        return [token]

    parts: list[str] = []
    rem = token
    break_chars = "/?&=-_.:"
    while rem:
        if font_obj.text_length(rem, fontsize=fontsize) <= max_w:
            parts.append(rem)
            break
        # Binary search for the longest prefix that fits within max_w
        lo, hi = 1, len(rem)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font_obj.text_length(rem[:mid], fontsize=fontsize) <= max_w:
                lo = mid
            else:
                hi = mid - 1
        cut = max(1, lo)
        # Prefer breaking right after a natural URL/token separator in the second half of the chunk
        best_sep = -1
        for idx in range(cut - 1, max(0, cut // 2 - 1), -1):
            if rem[idx] in break_chars:
                best_sep = idx + 1
                break
        if best_sep > 0:
            cut = best_sep
        while 1 < cut < len(rem) and unicodedata.category(rem[cut])[0] == "M":
            cut -= 1  # never between a letter and its marks
        parts.append(rem[:cut])
        rem = rem[cut:]
    return parts


def _split_emphasis_runs(text: str) -> list[tuple[str, bool, bool]]:
    """
    Splits a paragraph into (segment_text, is_bold, is_italic) tuples for real typographic rendering
    of markdown *italic* and **bold** spans without ever leaving raw asterisks in exported books.
    """
    if not text or "*" not in text:
        return [(text, False, False)] if text else []
    runs: list[tuple[str, bool, bool]] = []
    pos = 0
    for m in _EMPHASIS_TOKEN_RE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False, False))
        tok = m.group(1)
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            runs.append((tok[2:-2], True, False))
        elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
            runs.append((tok[1:-1], False, True))
        else:
            runs.append((tok, False, False))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False, False))
    return runs


def _plain_emphasis(text: str) -> str:
    """The text without emphasis markers, for headings and narration."""
    return "".join(seg for seg, _bold, _italic in _split_emphasis_runs(text)) if "*" in (text or "") else text


def _add_runs(paragraph, text: str, bold: bool = False, size=None) -> None:
    for seg, is_bold, is_italic in _split_emphasis_runs(text):
        run = paragraph.add_run(seg)
        if bold or is_bold:
            run.bold = True
        if is_italic:
            run.italic = True
        if size:
            run.font.size = size


def _styled_words(text: str, styles: dict, size: float, max_w: float) -> list:
    """
    The words of a line to wrap, each a list of (piece, style): '(*Odyssey*).' is one word in two fonts, so no space
    appears before its full stop. `styles` maps 'r', 'b', 'i' to (PDF font name, _BookFont, font file to embed or None).
    """
    words: list = []
    glue = False  # the last piece was not followed by white space
    for seg, is_bold, is_italic in _split_emphasis_runs(text):
        style = "b" if is_bold else ("i" if is_italic else "r")
        font = styles[style][1]
        for token in re.findall(r"\s+|\S+", _sanitize_for_pdf_font(seg, font)):
            if token.isspace():
                glue = False
                continue
            for k, piece in enumerate(_split_oversized_token(token, font, size, max_w)):
                if (k == 0 and glue and words
                        and _word_width(words[-1], styles, size) + font.text_length(piece, fontsize=size) <= max_w):
                    words[-1].append((piece, style))
                else:
                    words.append([(piece, style)])
            glue = True
    return words


def _word_width(word: list, styles: dict, size: float) -> float:
    return sum(styles[style][1].text_length(piece, fontsize=size) for piece, style in word)


def _wrap_styled(words: list, styles: dict, size: float, widths) -> list:
    """Lines of words; `widths(line_index)` is the room of each line."""
    space = styles["r"][1].text_length(" ", fontsize=size)
    lines: list = []
    line: list = []
    used = 0.0
    for word in words:
        width = _word_width(word, styles, size)
        if line and used + space + width > widths(len(lines)):
            lines.append(line)
            line, used = [], 0.0
        used += (space if line else 0.0) + width
        line.append(word)
    if line:
        lines.append(line)
    return lines


def _draw_styled(page, x: float, y: float, line: list, styles: dict, size: float, color) -> None:
    import pymupdf
    groups: list = []  # neighbours of one style are drawn together: clean text extraction and shaped phrases
    for w, word in enumerate(line):
        for p, (piece, style) in enumerate(word):
            gap = w > 0 and p == 0
            if groups and groups[-1][1] == style:
                groups[-1][0] += (" " if gap else "") + piece
            else:
                groups.append([piece, style, gap])
    for piece, style, gap in groups:
        name, font, path = styles[style]
        if gap:
            x += styles["r"][1].text_length(" ", fontsize=size)
        if path and not any(f[4] == name for f in page.get_fonts()):
            page.insert_font(fontname=name, fontfile=path)
            font.stood_in = True  # embedded for a few words: subset it
        _draw_pdf_text(page, pymupdf.Point(x, y), piece, font, size, name, color)
        x += font.text_length(piece, fontsize=size)


def _emphasis_to_html(text: str) -> str:
    """Escapes HTML and converts *italic* / **bold** markdown spans into <em> / <strong> tags."""
    out = []
    for seg, is_bold, is_italic in _split_emphasis_runs(text):
        esc = html.escape(seg)
        if is_bold:
            out.append(f"<strong>{esc}</strong>")
        elif is_italic:
            out.append(f"<em>{esc}</em>")
        else:
            out.append(esc)
    return "".join(out)


def _is_chapter_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if _CHAPTER_RE.match(s):
        return True
    # Match genuine uppercase Roman numerals II..XXXIX as chapter headings (never English words like 'I', 'Did', 'Civil')
    if len(s) >= 2 and s.isupper() and _STRICT_ROMAN_CHAPTER_RE.match(s):
        return True
    return False


def _is_scene_break(line: str) -> bool:
    return bool(_SCENE_BREAK_RE.match(line.strip()))


def _prepare_literature_chapters(text: str, default_title: str = "Book") -> list[dict]:
    """
    Cleans PDF page-break artifacts, running headers/footers, merges sentences broken
    across pages, isolates chapter headings & epigraphs/quotes, and groups paragraphs
    into semantic chapters for e-readers, tablets & printed books.
    Returns list of {"title": str, "paragraphs": list[str]}.
    """
    from backend.parsers import _may_number_page, _page_number_value

    text = _sanitize_pua(text)

    # Split by === PAGE X === markers and seamlessly merge sentences broken across pages
    parts = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text)
    raw_pages = [(None, parts[0])] + [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]
    pages: list[tuple[Optional[int], list[str]]] = []
    for page_no, page_chunk in raw_pages:
        chunk = page_chunk.strip()
        if chunk:
            pages.append((page_no, [ln.strip() for ln in chunk.splitlines()]))

    def number_counts_pages(index: int, position: int) -> bool:
        """A number is a page number only if a nearby page carries its own number in the same place."""
        page_no, lines = pages[index]
        if page_no is None or not -len(lines) <= position < len(lines):
            return False
        value = _page_number_value(lines[position])
        if not _may_number_page(value, page_no):
            return False
        for other_no, other in pages[max(0, index - 6):index + 7]:
            if other_no in (None, page_no) or not -len(other) <= position < len(other):
                continue
            other_value = _page_number_value(other[position])
            if other_value and other_value - value == other_no - page_no:
                return True
        return False

    def is_running_line(index: int, position: int) -> bool:
        """The same short line in the same place on a nearby page."""
        lines = pages[index][1]
        if len(lines) <= position or not lines[position] or len(lines[position]) >= 50 or _is_chapter_heading(lines[position]):
            return False
        return any(k != index and pages[k][1][position:position + 1] == lines[position:position + 1]
                   for k in range(max(0, index - 6), min(len(pages), index + 7)))

    # A number above a page's text may equally be a chapter's: EPUB chapters are 'pages' titled 1, 2, 3. Such a series
    # numbers pages only with more evidence: a sentence that runs across it, a running line or a heading beside it.
    folio_series: set[tuple[int, int]] = set()
    for index, (page_no, lines) in enumerate(pages):
        for position in (0, 1):
            if not number_counts_pages(index, position):
                continue
            following = next((ln for ln in lines[position + 1:] if ln), "")
            proven = (
                bool(re.fullmatch(r"[-–—]\s*\d{1,4}\s*[-–—]", lines[position]))
                or following[:1].islower()
                or bool(following and _is_chapter_heading(following) and not _page_number_value(following))
                or is_running_line(index, position + 1)
                or (position == 1 and is_running_line(index, 0))
            )
            if proven:
                folio_series.add((position, _page_number_value(lines[position]) - page_no))

    def numbers_page(index: int, position: int) -> bool:
        page_no, lines = pages[index]
        return number_counts_pages(index, position) and (position, _page_number_value(lines[position]) - page_no) in folio_series

    merged_blocks: list[str] = []
    cleaned_pages: list[list[str]] = []
    for index, (_page_no, page_lines) in enumerate(pages):
        # Only what provably counts the pages or repeats is dropped: a short line or a lone number may be a title, a
        # chapter number, a year or an address.
        first, last = 0, len(page_lines)
        if numbers_page(index, 0):
            first = 1
            if (is_running_line(index, 1) and not page_lines[1].endswith((".", "!", "?", ";", "»", '"'))):
                first = 2
        elif numbers_page(index, 1) and is_running_line(index, 0):
            # Author / number / Title
            first = 3 if is_running_line(index, 2) else 2
        if last > first and number_counts_pages(index, -1):
            last -= 1
        cleaned_pages.append(page_lines[first:last])

    for lines in cleaned_pages:
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        if not lines:
            continue

        # Split into distinct paragraphs, isolating chapter headings, scene breaks & epigraphs
        paras = []
        curr = []
        for line in lines:
            if not line:
                if curr:
                    paras.append(" ".join(curr))
                    curr = []
                continue

            if _is_chapter_heading(line) or _is_scene_break(line):
                if curr:
                    paras.append(" ".join(curr))
                    curr = []
                paras.append(line)
                continue

            # Epigraph attributions (e.g. "—Ted Bundy", "—Susanne Vega")
            if line.startswith(("—", "–", "--")) and len(line) < 80:
                if curr:
                    paras.append(" ".join(curr))
                    curr = []
                paras.append(line)
                continue

            if not curr:
                curr.append(line)
                continue

            prev_l = curr[-1]
            prev_closed = prev_l[-1] in '.!?»"”…'
            starts_dialogue = line.startswith(("«", '"', "“", "—", "- ", "– "))
            if prev_closed and (starts_dialogue or (len(line) > 2 and line[0].isupper())):
                paras.append(" ".join(curr))
                curr = [line]
            else:
                curr.append(line)

        if curr:
            paras.append(" ".join(curr))

        # Check if first block of this page continues the last block of the previous page
        for para in paras:
            if (
                merged_blocks
                and not _is_chapter_heading(para)
                and not _is_chapter_heading(merged_blocks[-1])
                and not _is_scene_break(para)
                and not _is_scene_break(merged_blocks[-1])
            ):
                prev = merged_blocks[-1].rstrip()
                nxt = para.lstrip()
                prev_ends_sentence = prev[-1] in '.!?»"”…)]:;'
                nxt_starts_lower = bool(nxt) and (nxt[0].islower() or (len(nxt) > 1 and nxt[0] in '«"\'“' and nxt[1].islower()))
                if not prev_ends_sentence and nxt_starts_lower:
                    merged_blocks[-1] = prev + " " + nxt
                    continue
            merged_blocks.append(para)

    # Group into chapters
    chapters: list[dict] = []
    current_chapter = {"title": default_title, "paragraphs": []}
    seen_heading = False

    for blk in merged_blocks:
        if _is_chapter_heading(blk):
            if current_chapter["paragraphs"] or seen_heading:  # a heading may have no text of its own ("Part One")
                chapters.append(current_chapter)
            seen_heading = True
            current_chapter = {"title": blk, "paragraphs": []}
        else:
            current_chapter["paragraphs"].append(blk)

    if current_chapter["paragraphs"] or seen_heading or not chapters:
        chapters.append(current_chapter)

    # Nothing is filtered out: a title page, a "Part One" page or a contents list is text of the book. Headings
    # without text of their own share one page, and text before the first chapter gets no invented heading.
    cleaned_chapters: list[dict] = []
    bare_run = False
    for idx, ch in enumerate(chapters):
        if idx == 0 and len(chapters) > 1 and ch["title"] == default_title:
            ch["title"] = ""
        elif ch["title"] != default_title:
            ch["title"] = _plain_emphasis(ch["title"])
        if not " ".join(ch["paragraphs"]).strip() and ch["title"]:
            if bare_run:
                cleaned_chapters[-1]["paragraphs"].append(ch["title"])
                continue
            bare_run = True
            ch["paragraphs"] = []
        else:
            bare_run = False
        cleaned_chapters.append(ch)

    return cleaned_chapters


# TXT
def export_txt(text: str, out_path: Path) -> Path:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(text or "", encoding="utf-8")
    return Path(out_path)


# DOCX (requires python-docx)
def export_docx(text: str, out_path: Path, layout: str = "standard", cover_image: Optional[bytes] = None) -> Path:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    text = _sanitize_pua(text)
    doc = Document()

    if layout == "literature":
        # 6" x 9" trade-paperback / e-reader friendly page geometry
        for section in doc.sections:
            section.page_width = Inches(6.0)
            section.page_height = Inches(9.0)
            section.top_margin = Inches(0.75)
            section.bottom_margin = Inches(0.75)
            section.left_margin = Inches(0.75)
            section.right_margin = Inches(0.75)

        normal_style = doc.styles["Normal"]
        normal_style.font.name = "Georgia"
        normal_style.font.size = Pt(11.5)

        # Validate cover image BEFORE inserting a cover page so corrupt bytes never leave a blank page
        if cover_image:
            valid_cover = False
            try:
                import pymupdf
                pix = pymupdf.Pixmap(cover_image)
                valid_cover = pix.width > 0 and pix.height > 0
            except Exception:
                valid_cover = False
            if valid_cover:
                try:
                    cp = doc.add_paragraph()
                    cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cp.paragraph_format.space_before = Pt(0)
                    cp.paragraph_format.space_after = Pt(0)
                    c_run = cp.add_run()
                    c_run.add_picture(io.BytesIO(cover_image), width=Inches(4.5))
                    doc.add_page_break()
                except Exception:
                    pass

        chapters = _prepare_literature_chapters(text, default_title=out_path.stem)
        for ch_idx, ch in enumerate(chapters):
            if ch_idx > 0:
                doc.add_page_break()

            if ch["title"] and (len(chapters) > 1 or ch["title"] != out_path.stem):
                h = doc.add_paragraph()
                h.alignment = WD_ALIGN_PARAGRAPH.CENTER
                h.paragraph_format.space_before = Pt(24)
                h.paragraph_format.space_after = Pt(18)
                run = h.add_run(ch["title"])
                run.bold = True
                run.font.name = "Georgia"
                run.font.size = Pt(16)

            is_first = True
            for para in ch["paragraphs"]:
                if _is_scene_break(para):
                    sb = doc.add_paragraph("* * *")
                    sb.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    sb.paragraph_format.space_before = Pt(12)
                    sb.paragraph_format.space_after = Pt(12)
                    is_first = True
                    continue

                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                p.paragraph_format.line_spacing = 1.4
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.first_line_indent = Inches(0) if is_first else Inches(0.28)
                for seg, is_bold, is_italic in _split_emphasis_runs(para):
                    run = p.add_run(seg)
                    run.font.name = "Georgia"
                    run.font.size = Pt(11.5)
                    if is_bold:
                        run.bold = True
                    if is_italic:
                        run.italic = True
                is_first = False

        doc.save(str(out_path))
        return out_path

    # Standard / Administrative layout
    sections = re.split(r"={3,}\s*PAGE\s+\d+\s*={3,}", text)
    pages = [s.strip() for s in sections if s.strip()]
    if not pages:
        pages = [text.strip()]

    header_prefixes = ("ΠΡΟΣ:", "ΑΠΟ:", "ΘΕΜΑ:", "Συνημμένο:", "TO:", "FROM:", "SUBJECT:", "DATE:", "Ημερομηνία:")

    for p_idx, page_content in enumerate(pages):
        if p_idx > 0 and len(doc.paragraphs) > 0:
            doc.add_page_break()

        for block in page_content.split("\n\n"):
            b = block.strip()
            if not b:
                continue

            for line in b.split("\n"):
                l = line.strip()
                if not l:
                    continue

                if l.startswith("• ") or l.startswith("- ") or l.startswith("* "):
                    bullet_text = re.sub(r"^[•\-\*]\s*", "", l)
                    _add_runs(doc.add_paragraph(style="List Bullet"), bullet_text)
                elif l.isupper() and len(l) < 60:
                    _add_runs(doc.add_paragraph(), l, bold=True, size=Pt(13))
                elif any(l.startswith(k) for k in header_prefixes):
                    p = doc.add_paragraph()
                    parts = l.split(":", 1)
                    r1 = p.add_run(parts[0] + ":")
                    r1.bold = True
                    if len(parts) > 1:
                        _add_runs(p, parts[1])
                else:
                    _add_runs(doc.add_paragraph(), l)

    doc.save(str(out_path))
    return out_path


# PDF (uses pymupdf which supports full Unicode / Greek)
def _export_literature_pdf(text: str, out_path: Path, cover_image: Optional[bytes] = None) -> Path:
    import pymupdf

    doc = pymupdf.open()
    serif_candidates = [
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/pala.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    italic_candidates = [
        "C:/Windows/Fonts/georgiai.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/palai.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Italic.ttf",
        "C:/Windows/Fonts/ariali.ttf",
    ]
    bold_candidates = [
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/palab.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    # one family, with every face where one exists: a missing italic is drawn leaning, a missing bold is regular
    font_path, italic_font_path, bold_font_path = _complete_family(
        zip(serif_candidates, italic_candidates, bold_candidates))
    default_family = (font_path, italic_font_path, bold_font_path)
    font_path, italic_font_path, bold_font_path = _family_for(text or "", default_family)

    # 6" x 9" trade paperback size (ideal for iPad & e-readers)
    width = 432.0
    height = 648.0
    margin_x = 46.0
    margin_top = 52.0
    content_bottom = height - 52.0
    max_line_w = width - 2 * margin_x

    # Insert cover image as page 0 if valid (validate before creating page to avoid blank page on corrupt bytes)
    has_cover_page = False
    if cover_image:
        try:
            pix = pymupdf.Pixmap(cover_image)
            if pix.width > 0 and pix.height > 0:
                cov_page = doc.new_page(width=width, height=height)
                cov_page.insert_image(pymupdf.Rect(0, 0, width, height), stream=cover_image)
                has_cover_page = True
        except Exception:
            pass

    fname = "book_serif" if font_path else "helv"
    fname_it = "book_serif_it" if italic_font_path else fname
    fname_bd = "book_serif_bd" if bold_font_path else fname
    font_obj = _BookFont(pymupdf.Font(fontfile=font_path) if font_path else pymupdf.Font("helv"), builtin=not font_path)
    font_obj_it = (_BookFont(pymupdf.Font(fontfile=italic_font_path), style="i") if italic_font_path
                   else _BookFont(font_obj.base, style="i", builtin=not font_path, slant=_ITALIC_SLANT))
    font_obj_bd = _BookFont(pymupdf.Font(fontfile=bold_font_path), style="b") if bold_font_path else font_obj
    font_obj.stood_in = font_path != default_family[0]  # a stand-in family is embedded whole: subset it
    styles = {"r": (fname, font_obj, None), "i": (fname_it, font_obj_it, None), "b": (fname_bd, font_obj_bd, None)}

    def new_book_page():
        pg = doc.new_page(width=width, height=height)
        if font_path:
            pg.insert_font(fontname=fname, fontfile=font_path)
        if italic_font_path:
            pg.insert_font(fontname=fname_it, fontfile=italic_font_path)
        if bold_font_path:
            pg.insert_font(fontname=fname_bd, fontfile=bold_font_path)
        return pg, margin_top

    chapters = _prepare_literature_chapters(text, default_title=out_path.stem)

    for ch_idx, ch in enumerate(chapters):
        page, y = new_book_page()

        # Chapter title
        if ch["title"] and (len(chapters) > 1 or ch["title"] != out_path.stem):
            y += 28.0
            title_size = 15.5
            safe_title = _sanitize_for_pdf_font(ch["title"], font_obj)
            title_w = font_obj.text_length(safe_title, fontsize=title_size)
            tx = max(margin_x, (width - title_w) / 2.0)
            _draw_pdf_text(page, pymupdf.Point(tx, y), safe_title, font_obj, title_size, fname, (0.1, 0.1, 0.1))
            y += 32.0

        body_size = 11.0
        line_height = 16.5
        indent = 16.0
        is_first = True

        for para in ch["paragraphs"]:
            if _is_scene_break(para):
                if y + 28.0 > content_bottom:
                    page, y = new_book_page()
                y += 8.0
                sb_text = "* * *"
                sb_w = font_obj.text_length(sb_text, fontsize=body_size)
                page.insert_text(pymupdf.Point((width - sb_w) / 2.0, y), sb_text, fontsize=body_size, fontname=fname, color=(0.3, 0.3, 0.3))
                y += 20.0
                is_first = True
                continue

            first_indent = 0.0 if is_first else indent
            words = _styled_words(para, styles, body_size, max_line_w - indent)
            lines = _wrap_styled(words, styles, body_size, lambda i: max_line_w - (0.0 if i else first_indent))
            for i, line in enumerate(lines):
                if y + line_height > content_bottom:
                    page, y = new_book_page()
                _draw_styled(page, margin_x + (0.0 if i else first_indent), y, line, styles, body_size, (0.12, 0.12, 0.12))
                y += line_height

            y += 4.5
            is_first = False

    if len(doc) == 0:
        blank_pg = doc.new_page(width=width, height=height)
        if font_path:
            blank_pg.insert_font(fontname="book_serif", fontfile=font_path)

    # Centered book-style page numbers (skip cover page if present)
    for p_no, pg in enumerate(doc, 1):
        if has_cover_page and p_no == 1:
            continue
        display_num = p_no - 1 if has_cover_page else p_no
        footer = f"- {display_num} -"
        fw = font_obj.text_length(footer, fontsize=9.0)
        pg.insert_text(pymupdf.Point((width - fw) / 2.0, height - 28.0), footer, fontsize=9.0, fontname=fname, color=(0.45, 0.45, 0.45))

    try:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        _save_pdf(doc, out_path, [font_obj, font_obj_it, font_obj_bd], text)
    finally:
        doc.close()
    return out_path


def export_pdf(text: str, out_path: Path, layout: str = "standard", cover_image: Optional[bytes] = None) -> Path:
    if layout == "literature":
        return _export_literature_pdf(text, out_path, cover_image=cover_image)

    import pymupdf

    doc = pymupdf.open()
    try:
        candidate_fonts = [
            ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
            ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf", "C:/Windows/Fonts/calibrii.ttf"),
            ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeuii.ttf"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
            ("/usr/share/fonts/truetype/freefont/FreeSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
             "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf"),
            ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
             "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf"),
        ]
        family = _complete_family(candidate_fonts)  # (regular, bold, italic); a missing face is None
        font_path = family[0]
        if not font_path:
            family = None

        sections = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", text or "")
        pages_data = []

        if len(sections) > 1:
            if sections[0].strip():
                pages_data.append(("", sections[0].strip()))  # text before the first page marker
            i = 1
            while i < len(sections):
                pnum = sections[i]
                pcontent = sections[i + 1] if i + 1 < len(sections) else ""
                pages_data.append((f"Page {pnum}", pcontent.strip()))
                i += 2
        else:
            pages_data.append(("", (text or "").strip()))

        margin = 48.0
        width = 595.0   # A4 width
        height = 842.0  # A4 height
        content_bottom = height - margin - 20.0

        def is_heading(line: str) -> bool:
            s = line.strip()
            if not s or len(s) > 85:
                return False
            if s.isupper() and len(s) > 3:
                return True
            if s.startswith(("ΘΕΜΑ:", "ΠΡΟΣ:", "ΑΠΟ:", "SUBJECT:", "TO:", "FROM:", "Συνημμένο:", "Ημερομηνία:")):
                return True
            return False

        fname = "unicode_font" if font_path else "helv"
        font_obj = _BookFont(pymupdf.Font(fontfile=font_path) if font_path else pymupdf.Font("helv"),
                             serif=False, builtin=not font_path)
        styles = {"r": (fname, font_obj, None)}
        for style, at, builtin_name in (("b", 1, "hebo"), ("i", 2, "heit")):
            if not family:
                styles[style] = (builtin_name, _BookFont(pymupdf.Font(builtin_name), style, serif=False, builtin=True), None)
            elif family[at]:
                styles[style] = (f"unicode_font_{style}",
                                 _BookFont(pymupdf.Font(fontfile=family[at]), style, serif=False), family[at])
            elif style == "i":  # no italic face: the regular one, leaning
                styles[style] = (fname, _BookFont(font_obj.base, style, serif=False, slant=_ITALIC_SLANT), None)
            else:
                styles[style] = styles["r"]

        for section_title, section_body in pages_data:
            if not section_body:
                continue

            page = doc.new_page(width=width, height=height)
            if font_path:
                page.insert_font(fontname="unicode_font", fontfile=font_path)
            y = margin

            if section_title:
                page.insert_text(pymupdf.Point(margin, y), section_title, fontsize=9.0, fontname=fname, color=(0.5, 0.5, 0.5))
                y += 18.0

            for raw_line in section_body.split("\n"):
                line = _sanitize_pua(raw_line).strip()
                plain = _sanitize_for_pdf_font(_plain_emphasis(line), font_obj).strip()
                if not plain:
                    y += 7.0
                    continue

                heading = is_heading(plain)
                font_size = 12.5 if heading else 10.5
                line_height = 17.5 if heading else 14.5
                color = (0.05, 0.05, 0.2) if heading else (0.1, 0.1, 0.1)

                max_w = width - 2 * margin
                words = _styled_words(line, styles, font_size, max_w)
                for words_of_line in _wrap_styled(words, styles, font_size, lambda _i: max_w):
                    if y + line_height > content_bottom:
                        page = doc.new_page(width=width, height=height)
                        if font_path:
                            page.insert_font(fontname="unicode_font", fontfile=font_path)
                        y = margin
                    _draw_styled(page, margin, y, words_of_line, styles, font_size, color)
                    y += line_height

                y += 4.0

        # Ensure PyMuPDF never crashes with "cannot save with zero pages" on empty inputs
        if len(doc) == 0:
            blank_pg = doc.new_page(width=width, height=height)
            if font_path:
                blank_pg.insert_font(fontname="unicode_font", fontfile=font_path)

        total_pages = len(doc)
        for p_no, pg in enumerate(doc, 1):
            footer = f"{p_no} / {total_pages}"
            pg.insert_text(pymupdf.Point(width - margin - 35, height - margin + 15), footer, fontsize=9.0, fontname=fname, color=(0.5, 0.5, 0.5))

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        _save_pdf(doc, out_path, [font for _name, font, _path in styles.values()], text)
    finally:
        doc.close()
    return out_path


# EPUB (requires EbookLib)
def export_epub(text: str, out_path: Path, title: str = "Translated Book", layout: str = "standard", cover_image: Optional[bytes] = None) -> Path:
    from ebooklib import epub

    safe_text = text or ""
    greek_letters = len(re.findall(r"[\u0370-\u03ff]", safe_text))  # an English book may quote α or Ω
    epub_lang = "el" if greek_letters and greek_letters >= 0.25 * (greek_letters + len(re.findall(r"[A-Za-z]", safe_text))) else "en"

    book = epub.EpubBook()
    book.set_identifier(str(out_path.stem))
    book.set_title(title)
    book.set_language(epub_lang)

    has_cover = False
    if cover_image:
        try:
            # Set cover in EPUB
            book.set_cover("cover.jpg", cover_image)
            has_cover = True
        except Exception:
            pass

    if layout == "literature":
        book_css = """
body {
    font-family: Georgia, "Times New Roman", Palatino, serif;
    line-height: 1.55;
    margin: 5% 6%;
}
h1.chapter-title {
    text-align: center;
    font-weight: normal;
    font-size: 1.45em;
    letter-spacing: 0.04em;
    margin-top: 2.2em;
    margin-bottom: 1.5em;
    page-break-before: always;
}
p {
    text-align: justify;
    text-indent: 1.4em;
    margin: 0 0 0.35em 0;
}
p.first-para {
    text-indent: 0;
}
p.scene-break {
    text-align: center;
    text-indent: 0;
    margin: 1.4em 0;
    letter-spacing: 0.3em;
}
"""
    else:
        book_css = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
    margin: 4% 5%;
}
h2 {
    margin-top: 1.5em;
    margin-bottom: 0.8em;
}
p {
    margin: 0 0 0.8em 0;
}
"""

    css_item = epub.EpubItem(
        uid="style_book",
        file_name="style/book.css",
        media_type="text/css",
        content=book_css.encode("utf-8"),
    )
    book.add_item(css_item)

    chapters_items = []

    if layout == "literature":
        chapters = _prepare_literature_chapters(safe_text, default_title=title)
        for idx, ch in enumerate(chapters, 1):
            ch_title = ch["title"] or title
            c = epub.EpubHtml(title=ch_title, file_name=f"chap_{idx:03d}.xhtml", lang=epub_lang)
            c.add_item(css_item)

            parts = []
            if ch["title"] and (len(chapters) > 1 or ch_title != title):
                parts.append(f'<h1 class="chapter-title">{html.escape(ch_title)}</h1>')

            is_first = True
            for para in ch["paragraphs"]:
                if _is_scene_break(para):
                    parts.append('<p class="scene-break">* * *</p>')
                    is_first = True
                else:
                    cls = ' class="first-para"' if is_first else ""
                    parts.append(f"<p{cls}>{_emphasis_to_html(para)}</p>")
                    is_first = False

            c.content = "\n".join(parts) or "<p>&#160;</p>"
            book.add_item(c)
            chapters_items.append(c)
    else:
        sections = re.split(r"={3,}\s*PAGE\s+(\d+)\s*={3,}", _sanitize_pua(safe_text))
        if len(sections) > 1:
            seen_fnames = set()
            if sections[0].strip():  # text before the first page marker
                intro = epub.EpubHtml(title=title, file_name="page_intro.xhtml", lang=epub_lang)
                intro.add_item(css_item)
                intro.content = "".join(
                    f"<p>{_emphasis_to_html(p.strip())}</p>" for p in sections[0].split("\n\n") if p.strip())
                book.add_item(intro)
                chapters_items.append(intro)
            i = 1
            sec_idx = 0
            while i < len(sections):
                sec_idx += 1
                pnum = sections[i]
                pcontent = sections[i + 1] if i + 1 < len(sections) else ""
                fname_xhtml = f"page_{pnum}.xhtml"
                if fname_xhtml in seen_fnames:
                    fname_xhtml = f"page_{pnum}_{sec_idx}.xhtml"
                seen_fnames.add(fname_xhtml)
                c = epub.EpubHtml(title=f"Page {pnum}", file_name=fname_xhtml, lang=epub_lang)
                c.add_item(css_item)
                body_html = f"<h2>Page {html.escape(pnum)}</h2>"
                for p in pcontent.strip().split("\n\n"):
                    if p.strip():
                        body_html += f"<p>{_emphasis_to_html(p.strip())}</p>"
                c.content = body_html
                book.add_item(c)
                chapters_items.append(c)
                i += 2
        else:
            c1 = epub.EpubHtml(title=title, file_name="chap_01.xhtml", lang=epub_lang)
            c1.add_item(css_item)
            body_html = f"<h1>{html.escape(title)}</h1>"
            for para in _sanitize_pua(safe_text).split("\n\n"):
                if para.strip():
                    body_html += f"<p>{_emphasis_to_html(para.strip())}</p>"
            c1.content = body_html
            book.add_item(c1)
            chapters_items.append(c1)

    book.toc = tuple(chapters_items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = (["cover"] if has_cover else []) + ["nav"] + chapters_items
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book, {})
    return out_path


def export_comic_archive(
    pdf_path: Union[str, Path],
    out_path: Union[str, Path],
    format: str = "cbz",
    dpi: int = 150,
) -> Path:
    """
    Renders pages of a translated comic PDF as JPEG images and packages them: a ZIP for .cbz, a RAR for .cbr.
    The file appears complete or not at all.
    """
    import uuid
    import zipfile
    import pymupdf
    from backend.comic_archive import RarWriter

    pdf_p = Path(pdf_path)
    if not pdf_p.exists():
        raise FileNotFoundError(f"Source comic PDF not found: {pdf_path}")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    part = out_p.with_name(f".{out_p.name}.{uuid.uuid4().hex[:8]}.part")
    doc = pymupdf.open(str(pdf_p))
    try:
        with open(part, "wb") as raw:
            if format.lower() == "cbr":
                archive = RarWriter(raw)
                add = archive.add
            else:
                archive = zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED)
                add = archive.writestr
            for i, page in enumerate(doc):
                add(f"page_{i+1:04d}.jpg", page.get_pixmap(dpi=dpi).tobytes("jpeg"))
            archive.close()
        part.replace(out_p)
    finally:
        doc.close()
        part.unlink(missing_ok=True)
    return out_p


def export_comic_epub(
    pdf_path: Union[str, Path],
    out_path: Union[str, Path],
    title: str = "Graphic Novel",
    dpi: int = 150,
    reading_direction: str = "ltr",
) -> Path:
    """
    Creates a pre-paginated fixed-layout EPUB containing rendered full-bleed comic pages.
    Supports standard LTR or Japanese Manga RTL page progression.
    """
    import pymupdf
    from ebooklib import epub

    pdf_p = Path(pdf_path)
    if not pdf_p.exists():
        raise FileNotFoundError(f"Source comic PDF not found: {pdf_path}")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(str(pdf_p))
    try:
        book = epub.EpubBook()
        book.set_identifier(f"comic-{pdf_p.stem}")
        book.set_title(title)
        comic_lang = "en" if pdf_p.stem.endswith("_translated_english") else "el"
        book.set_language(comic_lang)
        book.add_author("BookApp Comic Engine")
        if reading_direction.lower() == "rtl":
            book.set_direction("rtl")
            try:
                book.add_metadata(None, "meta", "rtl", {"property": "page-progression-direction"})
            except Exception:
                pass

        spine = ["nav"]
        chapters = []

        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("jpeg")
            img_name = f"images/page_{i+1:04d}.jpg"
            img_item = epub.EpubItem(
                uid=f"img_{i+1}",
                file_name=img_name,
                media_type="image/jpeg",
                content=img_bytes,
            )
            book.add_item(img_item)

            w = int(page.rect.width)
            h = int(page.rect.height)
            html_content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Page {i+1}</title>
  <meta name="viewport" content="width={w}, height={h}"/>
  <style>
    body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; text-align: center; }}
    img {{ max-width: 100%; max-height: 100%; width: auto; height: auto; display: block; margin: auto; }}
  </style>
</head>
<body>
  <img src="{img_name}" alt="Page {i+1}"/>
</body>
</html>"""
            c = epub.EpubHtml(title=f"Page {i+1}", file_name=f"page_{i+1:04d}.xhtml", lang=comic_lang)
            c.content = html_content
            book.add_item(c)
            spine.append(c)
            chapters.append(c)

        book.spine = spine
        book.toc = tuple(chapters)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        epub.write_epub(str(out_p), book, {})
    finally:
        doc.close()
    return out_p


# Helper dispatch
def export_text(
    text: str,
    out_dir: Path,
    fmt: str,
    base_name: str,
    layout: str = "standard",
    cover_image: Optional[bytes] = None,
) -> Path:
    """Export `text` to `fmt` inside `out_dir` using `layout` ('standard' or 'literature').
    If `cover_image` is provided (or if a saved cover image exists in `out_dir`), it is included
    in literature-formatted outputs (DOCX, PDF, EPUB).
    Returns the absolute path to the generated file.
    """
    # Look for cached cover in out_dir if not explicitly passed
    if cover_image is None and out_dir.exists():
        for cov_candidate in ("cover_image.jpg", "cover_image.png", "cover.jpg", "cover.png"):
            cov_file = out_dir / cov_candidate
            if cov_file.exists():
                try:
                    cover_image = cov_file.read_bytes()
                    break
                except Exception:
                    pass

    fmt = fmt.lower()
    out_path = out_dir / f"{base_name}.{fmt}"

    if fmt in ("cbz", "cbr"):
        own = out_dir / f"{base_name}.pdf"
        candidates = ([own] if own.is_file() else []) or list(out_dir.glob("*_translated_*.pdf")) or list(out_dir.glob("*.pdf"))
        if candidates:
            return export_comic_archive(candidates[0], out_path, format=fmt)
        raise ValueError(f"No comic PDF found in {out_dir} to build {fmt.upper()} archive.")

    if fmt == "txt":
        return export_txt(text, out_path)
    if fmt in ("doc", "docx"):
        return export_docx(text, out_path, layout=layout, cover_image=cover_image)
    if fmt == "pdf":
        return export_pdf(text, out_path, layout=layout, cover_image=cover_image)
    if fmt == "epub":
        if layout == "comic":
            candidates = list(out_dir.glob("*_translated_*.pdf")) or list(out_dir.glob("*.pdf"))
            if candidates:
                return export_comic_epub(candidates[0], out_path, title=base_name)
        return export_epub(text, out_path, title=base_name, layout=layout, cover_image=cover_image)
    raise ValueError(f"Unsupported format: {fmt}")
