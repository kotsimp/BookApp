"""
bilingual.py - A bilingual edition of a finished translation: each passage of the original followed by its translation,
the original smaller and in grey. PDF, DOCX and EPUB.

The two texts are matched page by page where both carry the same page markers, then paragraph by paragraph: a
translation keeps the paragraphs of the original almost always, and where it joins or splits some, the paragraphs are
matched by their lengths (the method of Gale & Church), so a passage never drifts away from its translation.
"""

import html
import io
import logging
import math
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PAGE_ONE_LINE = re.compile(r"^\s*={3,}\s*PAGE\s+(\d+)\s*={3,}\s*$", re.MULTILINE)
_PAGE_THREE_LINES = re.compile(r"^\s*={6,}\s*\n\s*PAGE\s+(\d+)\s*\n\s*={6,}\s*$", re.MULTILINE)

# a group of original / translated paragraphs that go together: (originals, translations), extra cost
_MOVES = ((1, 1, 0.0), (1, 2, 1.2), (2, 1, 1.2), (1, 3, 2.6), (3, 1, 2.6), (1, 0, 4.5), (0, 1, 4.5))
WHOLE_TEXT_BAND = 80  # paragraphs either side of the diagonal when a text has no page markers


def split_pages(text: str) -> list[tuple[Optional[int], str]]:
    """[(page number or None for text before the first marker, page text)] in order; both marker styles."""
    text = _PAGE_THREE_LINES.sub(lambda m: f"=== PAGE {m.group(1)} ===", text or "")
    parts = _PAGE_ONE_LINE.split(text)
    out: list[tuple[Optional[int], str]] = [(None, parts[0])] if parts[0].strip() else []
    out += [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]
    return out


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def align(src: list[str], tgt: list[str], band: Optional[int] = None) -> list[tuple[list[str], list[str]]]:
    """Groups of original and translated paragraphs that correspond, in order (every paragraph exactly once)."""
    n, m = len(src), len(tgt)
    if n == m and (n == 0 or band is None):
        return [([s], [t]) for s, t in zip(src, tgt)]
    if not n or not m:
        return [(src, tgt)] if (src or tgt) else []
    ps = [0]
    for p in src:
        ps.append(ps[-1] + len(p))
    pt = [0]
    for p in tgt:
        pt.append(pt[-1] + len(p))
    ratio = min(2.5, max(0.4, (pt[-1] + 1) / (ps[-1] + 1)))

    def near(i: int, j: int) -> bool:
        return band is None or abs(i * m / n - j) <= band

    inf = float("inf")
    best: dict[tuple[int, int], tuple[float, tuple[int, int]]] = {(0, 0): (0.0, (0, 0))}
    for i in range(n + 1):
        for j in range(m + 1):
            if (i, j) == (0, 0) or not near(i, j):
                continue
            cost, step = inf, (0, 0)
            for a, b, extra in _MOVES:
                prev = best.get((i - a, j - b))
                if i < a or j < b or prev is None:
                    continue
                x = ps[i] - ps[i - a]
                y = pt[j] - pt[j - b]
                if a and b:
                    c = 5.0 * abs(math.log((y + 30) / (x * ratio + 30))) + extra
                else:
                    c = extra + (x + y) / 2000.0
                if prev[0] + c < cost:
                    cost, step = prev[0] + c, (a, b)
            if cost < inf:
                best[(i, j)] = (cost, step)
    if (n, m) not in best:  # outside the band: the whole text as one passage rather than a wrong match
        return [(src, tgt)]
    groups = []
    i, j = n, m
    while (i, j) != (0, 0):
        a, b = best[(i, j)][1]
        groups.append((src[i - a:i], tgt[j - b:j]))
        i, j = i - a, j - b
    groups.reverse()
    return groups


def bilingual_passages(original: str, translated: str) -> list[tuple[list[str], list[str]]]:
    """The book as passages (original paragraphs, translated paragraphs), matched page by page where possible."""
    src_pages = split_pages(original)
    tgt_pages = split_pages(translated)
    src_numbered = {p: t for p, t in src_pages if p is not None}
    tgt_numbered = [(p, t) for p, t in tgt_pages if p is not None]
    if tgt_numbered and src_numbered and sum(1 for p, _ in tgt_numbered if p in src_numbered) >= 0.6 * len(tgt_numbered):
        passages: list[tuple[list[str], list[str]]] = []
        lead = next((t for p, t in tgt_pages if p is None), "")
        if lead.strip():
            passages += align(paragraphs(next((t for p, t in src_pages if p is None), "")), paragraphs(lead))
        for page, text in tgt_numbered:
            passages += align(paragraphs(src_numbered.get(page, "")), paragraphs(text))
        return [p for p in passages if p[0] or p[1]]
    # no shared page markers (a format-preserved DOCX or EPUB): the whole text, near the diagonal
    src_all = [p for _, t in src_pages for p in paragraphs(t)] if src_pages else paragraphs(original)
    tgt_all = [p for _, t in tgt_pages for p in paragraphs(t)] if tgt_pages else paragraphs(translated)
    return align(src_all, tgt_all, band=WHOLE_TEXT_BAND)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    from backend.exporter import _sanitize_pua
    return _sanitize_pua(text, editorial=False)


def _lang_code(lang: str) -> str:
    return "el" if (lang or "").lower() in ("greek", "el") else "en"


CSS = """
body { font-family: serif; line-height: 1.5; }
h1 { font-size: 1.6em; text-align: center; margin: 1.5em 0 0.3em; }
p.subtitle { text-align: center; color: #555; margin: 0 0 2em; }
div.passage { margin: 0 0 1.1em; }
p.src { color: #5b5b5b; font-size: 0.86em; font-style: italic; margin: 0 0 0.25em; }
p.tr { margin: 0 0 0.35em; }
"""


def _passage_html(src: list[str], tgt: list[str], src_lang: str, tgt_lang: str) -> str:
    def para(text: str, cls: str, lang: str) -> str:
        body = "<br/>".join(html.escape(_clean(line)) for line in text.split("\n"))
        return f'<p class="{cls}" lang="{lang}">{body}</p>'
    return ('<div class="passage">' + "".join(para(s, "src", src_lang) for s in src)
            + "".join(para(t, "tr", tgt_lang) for t in tgt) + "</div>")


def _heading_html(title: str, subtitle: str) -> str:
    return f"<h1>{html.escape(title)}</h1><p class=\"subtitle\">{html.escape(subtitle)}</p>"


# (regular, italic) serif faces with the whole Greek alphabet: one face for every letter of a passage
_SERIF_FACES = (
    ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesi.ttf"),
    ("C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/georgiai.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf",
     "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"),
)


def _pdf_font(pymupdf) -> tuple:
    """(css, archive) naming an installed serif face for the whole text; ("", None) lets MuPDF choose."""
    for regular, italic in _SERIF_FACES:
        if Path(regular).is_file():
            archive = pymupdf.Archive()
            archive.add(str(Path(regular).parent))
            css = f"@font-face {{ font-family: Book; src: url('{Path(regular).name}'); }}\n"
            if Path(italic).is_file():
                if Path(italic).parent != Path(regular).parent:
                    archive.add(str(Path(italic).parent))
                css += f"@font-face {{ font-family: Book; font-style: italic; src: url('{Path(italic).name}'); }}\n"
            return css + "body { font-family: Book, serif; }\n", archive
    return "", None


def export_bilingual_pdf(passages, out_path: Path, title: str, subtitle: str, src_lang: str, tgt_lang: str) -> Path:
    import pymupdf
    body = _heading_html(title, subtitle) + "".join(
        _passage_html(s, t, _lang_code(src_lang), _lang_code(tgt_lang)) for s, t in passages)
    font_css, archive = _pdf_font(pymupdf)
    story = pymupdf.Story(html=f"<body>{body}</body>", user_css=CSS + font_css + "body { font-size: 11pt; }",
                          archive=archive)
    mediabox = pymupdf.paper_rect("a5")
    where = mediabox + (42, 46, -42, -50)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    with pymupdf.open("pdf", buffer.getvalue()) as doc:  # page numbers
        from backend.pdf_text_names import fix_text_names
        # a space and a no-break space share one glyph in Times: copied text must have the book's own spaces
        fix_text_names(doc, title + subtitle + "".join(p for s, t in passages for p in (*s, *t)))
        for number, page in enumerate(doc, 1):
            if number > 1:
                page.insert_text((mediabox.width / 2 - 6, mediabox.height - 24), str(number), fontsize=8,
                                 color=(0.45, 0.45, 0.45))
        doc.set_metadata({"title": title, "subject": subtitle, "creator": "BookApp"})
        try:
            doc.subset_fonts()  # only the letters used: ~100 KB instead of the whole face (over 1 MB)
        except Exception as e:
            logger.debug(f"Bilingual PDF fonts kept whole: {e}")
        doc.save(str(out_path), garbage=3, deflate=True)
    return out_path


def export_bilingual_docx(passages, out_path: Path, title: str, subtitle: str, src_lang: str, tgt_lang: str) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor
    doc = Document()
    doc.core_properties.title = title
    heading = doc.add_heading(title, level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph(subtitle)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for src, tgt in passages:
        for k, text in enumerate(src):
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(8) if k == 0 else Pt(0)
            run = p.add_run(_clean(text))
            run.italic = True
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0x5B, 0x5B, 0x5B)
        for k, text in enumerate(tgt):
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            if not src and k == 0:
                p.paragraph_format.space_before = Pt(8)
            p.add_run(_clean(text)).font.size = Pt(11)
    doc.save(str(out_path))
    return out_path


def export_bilingual_epub(passages, out_path: Path, title: str, subtitle: str, src_lang: str, tgt_lang: str,
                          cover_image: Optional[bytes] = None) -> Path:
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier(f"bookapp-bilingual-{out_path.stem}")
    book.set_title(title)
    book.set_language(_lang_code(tgt_lang))
    if cover_image:
        try:
            book.set_cover("cover.jpg", cover_image)
        except Exception:
            pass
    style = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(style)
    chapters = []
    per_file = 120  # passages in one XHTML file: e-readers open long books faster in parts
    for start in range(0, max(1, len(passages)), per_file):
        part = passages[start:start + per_file]
        number = start // per_file + 1
        chapter = epub.EpubHtml(title=f"{number}", file_name=f"part_{number:03d}.xhtml", lang=_lang_code(tgt_lang))
        head = _heading_html(title, subtitle) if start == 0 else ""
        chapter.content = head + "".join(
            _passage_html(s, t, _lang_code(src_lang), _lang_code(tgt_lang)) for s, t in part)
        chapter.add_item(style)
        book.add_item(chapter)
        chapters.append(chapter)
    book.toc = [epub.Link(chapters[0].file_name, title, "start")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]
    epub.write_epub(str(out_path), book)
    return out_path


EXPORTERS = {"pdf": export_bilingual_pdf, "docx": export_bilingual_docx, "epub": export_bilingual_epub}
