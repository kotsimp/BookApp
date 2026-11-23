"""
document_blocks.py - Lossless text access to DOCX and EPUB packages.

Shared by format_preserver (translation) and format_sync (later edits), so both see exactly the same blocks.

* Only character data changes: every element, attribute, image, stylesheet and untouched zip entry stays as it was.
* A *block* is a paragraph-like unit made of *slots* (text positions). A *segment* is a run of slots that share their
  formatting and is translated as one piece. Text never crosses a link, field, revision, image or formula.
* `body` blocks form the plain-text translation, in reading order. `extra` blocks are translated in the document
  only (DOCX headers, footers and notes; EPUB navigation), so they are not narrated or repeated in the text.
"""

import copy
import io
import posixpath
import re
import zipfile
from html.entities import name2codepoint
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

from lxml import etree

SPLIT = "\x00"  # separates segments, invisible in the plain text
# what XML 1.0 cannot store: control characters, lone surrogates and two non-characters
XML_INVALID_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f" + chr(0xD800) + "-" + chr(0xDFFF) + chr(0xFFFE) + chr(0xFFFF) + "]"
)
NO_BREAK_HYPHEN = chr(0x2011)
_NAMED_ENTITY_RE = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
_XML_ENTITIES = {b"amp", b"lt", b"gt", b"quot", b"apos"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
XML = "{http://www.w3.org/XML/1998/namespace}"
DC = "{http://purl.org/dc/elements/1.1/}"


class DocumentError(ValueError):
    """The package is damaged, protected, or not a DOCX/EPUB."""


def _parser() -> etree.XMLParser:
    # Uploaded files are untrusted: no external entities, no network
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def _numeric_entities(data: bytes) -> bytes:
    """XHTML may use &nbsp; & co., which plain XML parsers reject: turn them into numeric references."""
    def repl(m):
        name = m.group(1)
        code = name2codepoint.get(name.decode("ascii"))
        return b"&#%d;" % code if code and name not in _XML_ENTITIES else m.group(0)
    return _NAMED_ENTITY_RE.sub(repl, data)


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _holds(container, el) -> bool:
    return container is el or any(a is container for a in el.iterancestors())


class Slot:
    """
    One text position: an element's text, or the tail that follows it.

    ``fmt`` is (look, container, script): slots of equal fmt form one segment. A change of look inside a word (drop
    capital, stray run) keeps the word whole; a change of container (link, field, revision) or script (superscript,
    hidden text) never does.
    """

    __slots__ = ("el", "attr", "fmt", "part", "break_before")

    def __init__(self, el, attr: str, fmt: tuple, part: str, break_before: str = ""):
        self.el, self.attr, self.fmt, self.part, self.break_before = el, attr, fmt, part, break_before

    @property
    def value(self) -> str:
        return getattr(self.el, self.attr) or ""


class LineSlot(Slot):
    """One line of a preformatted text position: the other lines and the line breaks stay as they are."""

    __slots__ = ("pre", "lines", "index")

    def __init__(self, el, attr: str, fmt: tuple, part: str, break_before: str, pre, lines: List[str], index: int):
        super().__init__(el, attr, fmt, part, break_before)
        self.pre, self.lines, self.index = pre, lines, index

    @property
    def value(self) -> str:
        return self.lines[self.index]


class Block:

    def __init__(self, owner, slots: List[Slot], part: str):
        self.owner, self.slots, self.part = owner, slots, part

    @property
    def values(self) -> List[str]:
        return [s.value for s in self.slots]

    @property
    def text(self) -> str:
        """The block as one paragraph of plain text (only real line breaks become newlines)."""
        joined = "".join(
            s.break_before + re.sub(r"[ \t]*[\r\n][ \t\r\n]*", " ", s.value) for s in self.slots
        ).replace(SPLIT, "")
        return re.sub(r"[ \t\r]*\n\s*", "\n", joined).strip()

    def segments(self) -> List[List[Slot]]:
        """Slots to translate together."""
        groups: List[List[Slot]] = []
        for slot in self.slots:
            if not slot.value:
                if slot.break_before:
                    groups.append([slot])
                continue
            if groups and not slot.break_before:
                last = groups[-1][-1]
                same = last.fmt == slot.fmt
                inside_word = (last.fmt[1:] == slot.fmt[1:] and last.value[-1:].isalpha() and slot.value[0].isalpha())
                if same or inside_word:
                    groups[-1].append(slot)
                    continue
            groups.append([slot])
        return [g for g in groups if any(s.value for s in g)]


class Package:
    """Base class: a zip whose XML parts are parsed on demand and written back only when changed."""

    def __init__(self, source):
        """`source`: a path, or a binary file object."""
        self.path = source if hasattr(source, "read") else Path(source)
        self.label = getattr(self.path, "name", "") or "the document"
        self.roots: Dict[str, etree._Element] = {}
        self.changed = set()
        self.removed = set()
        self.body: List[Block] = []
        self.extra: List[Block] = []
        self.kept_code = 0  # <pre> blocks with words that were taken for program code and are not translated
        self._positions: Optional[Dict[tuple, List[Slot]]] = None
        try:
            with zipfile.ZipFile(self.path) as zf:
                self.names = set(zf.namelist())
                self._zip: Optional[zipfile.ZipFile] = zf
                self._load()
        except DocumentError:
            raise
        except (zipfile.BadZipFile, etree.XMLSyntaxError, KeyError, StopIteration, RuntimeError) as e:
            raise DocumentError(f"Cannot read {self.label} (damaged or protected): {e}") from e
        finally:
            self._zip = None

    def _load(self) -> None:
        raise NotImplementedError

    def _parse(self, name: str):
        if name not in self.roots:
            self.roots[name] = etree.fromstring(self._zip.read(name), _parser())
        return self.roots[name]

    def set_value(self, slot: Slot, value: str) -> None:
        value = XML_INVALID_RE.sub("", value)
        if value == slot.value:
            return
        setattr(slot.el, slot.attr, value)
        self.changed.add(slot.part)

    def set_segment(self, segment: List[Slot], value: str) -> None:
        """Puts `value` in the segment's main slot (its longest) and empties the others."""
        main = max(segment, key=lambda s: len(s.value.strip()))
        for slot in segment:
            self.set_value(slot, value if slot is main else "")

    def _move_text(self, src, src_attr: str, dst, dst_attr: str) -> None:
        """Appends one text position to another and takes the slots that point at it along."""
        if self._positions is None:
            self._positions = {}
            for block in self.body + self.extra:
                for slot in block.slots:
                    self._positions.setdefault((slot.el, slot.attr), []).append(slot)
        text, present = getattr(src, src_attr) or "", getattr(dst, dst_attr) or ""
        setattr(src, src_attr, None)
        if text:
            setattr(dst, dst_attr, present + text)
        moving = self._positions.pop((src, src_attr), [])
        stale: List[Slot] = []
        if text.strip() and not present.strip():
            stale = self._positions.pop((dst, dst_attr), [])  # blank text that now is somebody else's
            for slot in moving:
                slot.el, slot.attr = dst, dst_attr
            if moving:
                self._positions[(dst, dst_attr)] = moving
        else:
            stale = moving
        for slot in stale:
            slot.el, slot.attr = etree.Element("detached"), "text"

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(self.path) as src, zipfile.ZipFile(buf, "w") as out:
            infos = sorted(src.infolist(), key=lambda i: i.filename != "mimetype")  # EPUB: mimetype first, stored
            for info in infos:
                if info.filename in self.changed:
                    tree = self.roots[info.filename].getroottree()
                    data = etree.tostring(tree, xml_declaration=True, encoding="UTF-8",
                                          standalone=tree.docinfo.standalone)
                else:
                    data = src.read(info)
                if info.filename == "mimetype":
                    info.compress_type = zipfile.ZIP_STORED
                out.writestr(info, data)
        return buf.getvalue()

    def set_language(self, code: str) -> None:
        pass

    def insert(self, anchor: Block, paragraphs: List[str], before: bool, neighbour: Optional[Block]) -> None:
        """
        New paragraphs beside `anchor`. `neighbour` is the block on their other side (None at the document's edge):
        they go outside any table or text box that holds only the anchor.
        """
        raise NotImplementedError

    def remove(self, block: Block) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

# formatting that makes a separate segment (proofing marks, hints and revision ids do not)
_RUN_PROPS = ("rStyle", "b", "i", "u", "strike", "dstrike", "caps", "smallCaps", "color", "highlight", "shd", "sz", "rFonts")
# switched off explicitly: visible where the paragraph's style switches them on
_RUN_TOGGLES = ("b", "i", "u", "caps", "smallCaps")
# elements inside a paragraph that text must not move across
_DOCX_BREAKS = {f"{W}br": "\n", f"{W}cr": "\n", f"{W}tab": " ", f"{W}ptab": " "}
_DOCX_OBJECTS = {
    f"{W}drawing", f"{W}pict", f"{W}object", f"{W}footnoteReference", f"{W}endnoteReference", f"{W}commentReference",
    f"{W}sym", f"{W}fldChar", f"{MC}AlternateContent", f"{M}oMath", f"{M}oMathPara",
}
_DOCX_CONTAINERS = {f"{W}hyperlink", f"{W}ins", f"{W}moveTo", f"{W}sdt", f"{W}fldSimple"}
_DOCX_IGNORED = {f"{W}pPr", f"{W}rPr", f"{W}del", f"{W}moveFrom", f"{W}instrText"}
# a paragraph with one of these is emptied, never removed
_DOCX_KEEP = tuple(
    f"{W}{name}" for name in (
        "drawing", "pict", "object", "sectPr", "bookmarkStart", "bookmarkEnd", "footnoteReference", "endnoteReference",
        "fldChar", "commentRangeStart", "commentRangeEnd", "commentReference", "permStart", "permEnd", "del",
        "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd", "sym",
    )
) + (f"{MC}AlternateContent", f"{M}oMath")


class DocxPackage(Package):

    def _load(self) -> None:
        main = "word/document.xml"
        if main not in self.names:
            rels = self._parse("_rels/.rels")
            main = next(r.get("Target").lstrip("/") for r in rels if r.get("Type", "").endswith("/officeDocument"))
        root = self._parse(main)
        if root.tag != f"{W}document":
            raise DocumentError(f"{self.label} uses an unsupported DOCX dialect (Strict Open XML).")
        self._collect(main, self.body)
        folder = posixpath.dirname(main)
        for name in sorted(self.names):
            base = posixpath.basename(name)
            if posixpath.dirname(name) == folder and re.fullmatch(r"(header|footer)\d*\.xml|footnotes\.xml|endnotes\.xml", base):
                self._collect(name, self.extra)

    def _collect(self, part: str, into: List[Block]) -> None:
        root = self._parse(part)
        # a non-breaking hyphen is a character of its word: as text, the word is translated and edited whole
        for hyphen in list(root.iter(f"{W}noBreakHyphen")):
            if not any(a.tag == f"{W}del" for a in hyphen.iterancestors()):
                hyphen.tag = f"{W}t"
                hyphen.text = NO_BREAK_HYPHEN
        for p in root.iter(f"{W}p"):
            slots = self._slots(p, part)
            if any(s.value.strip() for s in slots):
                # mc:Fallback repeats a text box for old readers: translate it, don't repeat it in the text
                is_copy = any(a.tag == f"{MC}Fallback" for a in p.iterancestors())
                (self.extra if is_copy else into).append(Block(p, slots, part))

    def _slots(self, p, part: str) -> List[Slot]:
        slots: List[Slot] = []
        pending = ""
        props = p.find(f"{W}pPr")
        style = props.find(f"{W}pStyle") if props is not None else None
        styled = style is not None and style.get(f"{W}val") != "Normal"

        def mark(kind: str) -> None:
            nonlocal pending
            found = (pending, kind)
            pending = "\n" if "\n" in found else (" " if " " in found else SPLIT)

        def walk(el, look: tuple, container: tuple, script: tuple) -> None:
            nonlocal pending
            for child in el:
                tag = child.tag
                if tag in _DOCX_IGNORED or tag == f"{W}p":
                    continue  # paragraphs of text boxes nested in drawings are blocks of their own
                if tag in _DOCX_OBJECTS:
                    mark(SPLIT)
                elif tag in _DOCX_BREAKS:
                    mark(_DOCX_BREAKS[tag])
                elif tag == f"{W}t":
                    slots.append(Slot(child, "text", (look, container, script), part, pending))
                    pending = ""
                elif tag == f"{W}r":
                    run_look, run_script = self._format(child, styled)
                    walk(child, run_look, container, run_script)
                elif tag in _DOCX_CONTAINERS:
                    walk(child, look, container + (child,), script)  # the element itself: an id() can be reused
                else:
                    walk(child, look, container, script)

        walk(p, (), (), ())
        return slots

    @staticmethod
    def _format(run, styled: bool) -> Tuple[tuple, tuple]:
        props = run.find(f"{W}rPr")
        if props is None:
            return (), ()
        look = []
        for name in _RUN_PROPS:
            el = props.find(f"{W}{name}")
            if el is None:
                continue
            if name == "rFonts":
                val = el.get(f"{W}ascii") or el.get(f"{W}asciiTheme")
            elif name == "shd":
                val = el.get(f"{W}fill")
                val = None if val in ("auto", "FFFFFF") else val
            else:
                val = el.get(f"{W}val") or "1"
                if val in ("0", "false", "none", "auto"):
                    val = "off" if styled and name in _RUN_TOGGLES else None
                elif val == "true":
                    val = "1"
            if val:
                look.append((name, val))
        script = []
        for name, off in (("vertAlign", ("baseline",)), ("vanish", ("0", "false"))):
            el = props.find(f"{W}{name}")
            if el is not None and el.get(f"{W}val") not in off:
                script.append((name, el.get(f"{W}val") or "1"))
        return tuple(look), tuple(script)

    def set_value(self, slot: Slot, value: str) -> None:
        super().set_value(slot, value)
        if slot.part in self.changed and slot.value != slot.value.strip():
            slot.el.set(f"{XML}space", "preserve")

    def insert(self, anchor: Block, paragraphs: List[str], before: bool, neighbour: Optional[Block]) -> None:
        ref = anchor.owner
        outer = [a for a in ref.iterancestors() if a.tag in (f"{W}tbl", f"{W}p")
                 and (neighbour is None or not _holds(a, neighbour.owner))]
        if outer:
            ref = outer[-1]  # text typed beside a table or text box goes next to it, not into it
        props = anchor.owner.find(f"{W}pPr")
        style = props.find(f"{W}pStyle") if props is not None else None
        style_name = style.get(f"{W}val", "").lower() if style is not None else ""
        plain = bool(outer) or style_name.startswith(("heading", "title"))
        first = next((s for s in anchor.slots if s.value.strip()), anchor.slots[0] if anchor.slots else None)
        run = next(iter(first.el.iterancestors(f"{W}r")), None) if first is not None else None
        run_props = run.find(f"{W}rPr") if run is not None else None
        for text in paragraphs:
            new = etree.Element(f"{W}p")
            if not plain and props is not None:
                cloned = copy.deepcopy(props)
                for sect in cloned.findall(f"{W}sectPr"):
                    cloned.remove(sect)
                new.append(cloned)
            new_run = etree.SubElement(new, f"{W}r")
            if not plain and run_props is not None:
                new_run.append(copy.deepcopy(run_props))
            for i, line in enumerate(XML_INVALID_RE.sub("", text).split("\n")):
                if i:
                    etree.SubElement(new_run, f"{W}br")
                t = etree.SubElement(new_run, f"{W}t")
                t.text = line
                t.set(f"{XML}space", "preserve")
            if before:
                ref.addprevious(new)
            else:
                ref.addnext(new)
                ref = new
        self.changed.add(anchor.part)

    def remove(self, block: Block) -> None:
        p, parent = block.owner, block.owner.getparent()
        keep = next(p.iter(*_DOCX_KEEP), None) is not None or any(
            br.get(f"{W}type") in ("page", "column") for br in p.iter(f"{W}br")
        )
        only_child = parent.tag != f"{W}body" and len(parent.findall(f"{W}p")) == 1
        content = (f"{W}p", f"{W}tbl", f"{W}sdt")
        prev = next((e for e in p.itersiblings(preceding=True) if e.tag in content), None)
        following = next((e for e in p.itersiblings() if e.tag in content), None)
        # a cell must end with a paragraph, and two tables that touch become one
        separator = (prev is not None and prev.tag != f"{W}p"
                     and (following is None or following.tag != f"{W}p"))
        if keep or only_child or separator:
            for slot in block.slots:
                self.set_value(slot, "")
        else:
            parent.remove(p)
        self.changed.add(block.part)


# ---------------------------------------------------------------------------
# EPUB
# ---------------------------------------------------------------------------

# everything else starts a block (p, div, li, td, h1-h6, figcaption, body text, ...)
_INLINE = set(
    "a abbr acronym b bdi bdo big cite code data del dfn em font i ins kbd label mark q rp rt ruby s samp small span "
    "strike strong sub sup time tt u var wbr img br".split()
)
_NOT_TEXT = {"script", "style", "svg", "math", "pre", "template", "head"}
_NO_FMT = ((), (), ())

# <pre> is translated only when it is plainly prose (a poem, a letter): translated code is broken code
_PROSE_CLASS = "bookapp-prose"  # set on a translated <pre>: in another language it must still be read as prose
_CODE_CLASS_RE = re.compile(
    r"code|source|listing|program|highlight|language-|prettyprint|hljs|syntax|console|terminal|screen|\bshell\b", re.I)
_CODE_TEXT_RE = re.compile(
    r"[{}<>|\\@$`~^]"                                  # symbols of code
    r"|[A-Za-z0-9]_[A-Za-z0-9]|[A-Za-z0-9_]\(|\S?[ \t]*=[ \t]*\S|->|::|\+\+"
    r"|^[ \t]*(?:\#|//|/\*|--[ \t]|>>>|%[ \t])"         # comments and prompts
    r"|^[ \t]*(?:import|from[ \t]+\S+[ \t]+import|def|function|const|public|private)\b[ \t]+[a-z_]"
    r"|^[ \t]*(?:for|if|elif|else|while|with|try|except|class|switch|case)\b[^\n]*:[ \t]*$"
    r"|^[ \t]*(?:SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE)\b"
    r"|^[ \t]*(?:sudo|git|npm|pip|apt|apt-get|cd|curl|wget|docker|chmod|mkdir)[ \t]+[a-z./-]"
    r"|^[ \t]*[a-z][\w.-]*:[ \t]+\S"                   # key: value
    r"|\S(?:[ \t]{3,}|\t)\S",                          # columns
    re.M,
)
_PROSE_WORDS = set(
    "the a an of and was were are been be his her hers my mine your our their they them he him she we us you i me "
    "that this these those there what who whom whose when where but had have has will would shall should could "
    "into upon never always like o oh thy thou thee".split()
)


# what a book calls a passage, in EPUB 3 (epub:type with the z3998 vocabulary), DPUB-ARIA roles and plain classes
_VERSE_MARKS = {"poem", "poems", "poetry", "verse", "stanza", "lyrics", "song", "hymn", "letter", "epigraph",
                "dedication", "doc-epigraph", "doc-dedication"}
_EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"


def _marked_as_verse(pre) -> bool:
    """The book itself calls this <pre>, or a passage around it, a poem, verse or letter."""
    for el in (pre, *pre.iterancestors()):
        tokens = " ".join(filter(None, (el.get(_EPUB_TYPE), el.get("role"), el.get("class")))).lower().split()
        if any(t.split(":")[-1] in _VERSE_MARKS for t in tokens):
            return True
    return False


def _is_prose(pre) -> bool:
    if _PROSE_CLASS in (pre.get("class") or "").split():
        return True
    parent = pre.getparent()
    named = " ".join(filter(None, (pre.get("class"), pre.get("data-type"),
                                   parent.get("class") if parent is not None and _local(parent) == "div" else None)))
    if _CODE_CLASS_RE.search(named) or any(_local(e) in ("code", "samp", "kbd", "var") for e in pre.iter()):
        return False
    if _marked_as_verse(pre):
        return True
    text = "".join(pre.itertext())
    if _CODE_TEXT_RE.search(text.strip("\n")):
        return False
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 3:
        return False
    if 2 * sum(1 for w in words if "Ͱ" <= w[0] <= "Ͽ" or "ἀ" <= w[0] <= "῿") >= len(words):
        return True  # Greek sentences are never code
    hits = sum(1 for w in words if w in _PROSE_WORDS)
    return hits >= 2 or (hits == 1 and len(words) <= 8)


class EpubPackage(Package):

    def _load(self) -> None:
        container = self._parse("META-INF/container.xml")
        self.opf = next(e.get("full-path") for e in container.iter() if _local(e) == "rootfile")
        opf = self._parse(self.opf)
        base = posixpath.dirname(self.opf)
        items, order = {}, []
        for e in opf.iter():
            if _local(e) == "item" and e.get("href"):
                name = posixpath.normpath(posixpath.join(base, unquote(e.get("href"))))
                if name in self.names:
                    items[e.get("id")] = (name, e.get("media-type", ""), (e.get("properties") or "").split())
                    order.append(e.get("id"))
        spine = [e.get("idref") for e in opf.iter() if _local(e) == "itemref" and e.get("idref") in items]
        self.pages: List[str] = []
        seen = set()  # a file listed twice in the manifest is still one file
        for item_id in dict.fromkeys(spine + order):  # reading order first
            name, media, props = items[item_id]
            if name in seen:
                continue
            seen.add(name)
            if media in ("application/xhtml+xml", "text/html"):
                self.roots[name] = self._parse_page(self._zip.read(name), name)
                self.pages.append(name)
                self._collect(name, self.extra if "nav" in props else self.body)
            elif media == "application/x-dtbncx+xml":
                for el in self._parse(name).iter():
                    if _local(el) == "text" and (el.text or "").strip():
                        self.extra.append(Block(el, [Slot(el, "text", _NO_FMT, name)], name))

    def _parse_page(self, data: bytes, name: str):
        data = _numeric_entities(data)
        try:
            return etree.fromstring(data, _parser())
        except etree.XMLSyntaxError:
            # not well-formed XHTML (tolerated by many readers): repair it, only for this page
            from bs4 import BeautifulSoup
            try:
                fixed = str(BeautifulSoup(data, "html.parser"))
                fixed = re.sub(r"^\s*<\?xml[^>]*\?>", "", fixed)
                return etree.fromstring(fixed.encode("utf-8"), _parser())
            except etree.XMLSyntaxError as e:
                raise DocumentError(f"Cannot read {name} inside {self.label}: {e}") from e

    def _collect(self, part: str, into: List[Block]) -> None:
        root = self.roots[part]
        body = next((e for e in root.iter() if _local(e) == "body"), root)
        groups: List[tuple] = []  # (owner, slots) in document order
        pending = ""
        separated = False  # a block element was passed since the last text

        def add(el, attr, owner, fmt):
            nonlocal pending, separated
            value = getattr(el, attr)
            if not value:
                return
            lines = value.split("\n") if _local(owner) == "pre" else [value]
            for index, line in enumerate(lines):
                if index:
                    pending = "\n"
                if not line:
                    continue
                if separated or not groups or groups[-1][0] is not owner:
                    if not line.strip():
                        continue  # indentation between blocks
                    groups.append((owner, []))
                    pending = ""
                    separated = False
                groups[-1][1].append(LineSlot(el, attr, fmt, part, pending, owner, lines, index)
                                     if _local(owner) == "pre" else Slot(el, attr, fmt, part, pending))
                pending = ""

        def inner_format(el, name: str, fmt: tuple) -> tuple:
            look, container, script = fmt
            sign = (name, tuple(sorted((k, v) for k, v in el.attrib.items() if k != "id")))
            if name == "a" and el.get("href"):
                container += (el,)
            if name in ("sup", "sub"):
                script += (name,)
            return look + (sign,), container, script

        # explicit stack: converted books can nest very deeply
        stack = [("open", body, body, _NO_FMT)]
        while stack:
            action, el, owner, fmt = stack.pop()
            if action == "tail":
                add(el, "tail", owner, fmt)
                continue
            if action == "break":
                pending = "\n"
                continue
            if action == "split":
                pending = pending or SPLIT
                continue
            if action == "boundary":
                separated = True
                continue
            add(el, "text", owner, fmt)
            todo = []
            for child in el:
                name = _local(child)
                if name == "br":
                    todo.append(("break", child, owner, fmt))
                elif name == "pre" and _is_prose(child):
                    todo.append(("boundary", child, owner, fmt))
                    todo.append(("open", child, child, _NO_FMT))
                    todo.append(("boundary", child, owner, fmt))
                elif name in _NOT_TEXT or name == "img":
                    if name == "pre" and any(ch.isalpha() for ch in "".join(child.itertext())):
                        self.kept_code += 1
                    todo.append(("split", child, owner, fmt))
                elif name:
                    if name in _INLINE:
                        todo.append(("open", child, owner, inner_format(child, name, fmt)))
                    else:
                        todo.append(("boundary", child, owner, fmt))
                        todo.append(("open", child, child, _NO_FMT))
                        todo.append(("boundary", child, owner, fmt))
                todo.append(("tail", child, owner, fmt))
            stack.extend(reversed(todo))

        for owner, slots in groups:
            into.append(Block(owner, slots, part))

    def set_value(self, slot: Slot, value: str) -> None:
        if not isinstance(slot, LineSlot):
            super().set_value(slot, value)
            return
        value = XML_INVALID_RE.sub("", value)
        if value == slot.value:
            return
        slot.lines[slot.index] = value
        setattr(slot.el, slot.attr, "\n".join(slot.lines))
        classes = (slot.pre.get("class") or "").split()
        if _PROSE_CLASS not in classes:
            slot.pre.set("class", " ".join(classes + [_PROSE_CLASS]))
        self.changed.add(slot.part)

    def set_language(self, code: str) -> None:
        for el in self.roots[self.opf].iter(f"{DC}language"):
            el.text = code
            self.changed.add(self.opf)
            break
        for name in self.pages:
            root = self.roots[name]
            for attr in ("lang", f"{XML}lang"):
                if root.get(attr):
                    root.set(attr, code)
                    self.changed.add(name)

    def insert(self, anchor: Block, paragraphs: List[str], before: bool, neighbour: Optional[Block]) -> None:
        owner = anchor.owner
        ns = etree.QName(owner).namespace
        tag = lambda name: f"{{{ns}}}{name}" if ns else name
        name = _local(owner)
        outer = [a for a in owner.iterancestors() if _local(a) in ("table", "dl")
                 and (neighbour is None or neighbour.part != anchor.part or not _holds(a, neighbour.owner))]
        single_group = [b.owner for b in self.body].count(owner) == 1
        new_name = "p"
        carried = None  # (element, attribute) of text that has to stay behind the new paragraphs
        if not outer and name == "pre":
            outer = [owner]  # text typed beside preformatted text is an ordinary paragraph next to it
        if outer:
            ref = outer[-1]
            parent = ref.getparent()
        elif single_group and (name in ("p", "li", "div") or re.fullmatch(r"h[1-6]", name)):
            parent, ref = owner.getparent(), owner
            new_name = "p" if name.startswith("h") else name
        else:
            # loose text inside a container (body, td, section...): the new paragraph becomes its child
            parent, slot = owner, anchor.slots[0 if before else -1]
            ref = slot.el
            if ref is owner:
                ref = None
                if before:
                    carried = (owner, "text")
            elif before and slot.attr == "tail" and ref.getparent() is owner:
                carried = (ref, "tail")
            else:
                while ref.getparent() is not owner:
                    ref = ref.getparent()
        if ref is None:
            index = 0
        elif before and not carried:
            index = parent.index(ref)
        else:
            index = parent.index(ref) + 1
            if not before and parent is not owner:
                carried = (ref, "tail")  # text that followed the anchor keeps following
        last = None
        for offset, text in enumerate(paragraphs):
            el = etree.Element(tag(new_name))
            if new_name == name:
                for attr in ("class", "style"):
                    if owner.get(attr):
                        el.set(attr, owner.get(attr))
            lines = XML_INVALID_RE.sub("", text).split("\n")
            el.text = lines[0]
            for line in lines[1:]:
                etree.SubElement(el, tag("br")).tail = line
            parent.insert(index + offset, el)
            last = el
        if carried and last is not None:
            self._move_text(carried[0], carried[1], last, "tail")
        self.changed.add(anchor.part)

    def remove(self, block: Block) -> None:
        owner = block.owner
        name = _local(owner)
        removable = name in ("p", "li", "div") or re.fullmatch(r"h[1-6]", name)
        if removable and not owner.get("id") and [b.owner for b in self.body].count(owner) == 1:
            holds_more = any(
                e is not owner and (e.get("id") or _local(e) in ("img", "svg", "image") or _local(e) not in _INLINE)
                for e in owner.iter() if isinstance(e.tag, str))
            parent, prev = owner.getparent(), owner.getprevious()
            # an emptied <body>, list or cell is invalid or collapses the layout
            only_child = len([e for e in parent if isinstance(e.tag, str)]) == 1
            text_before = (prev.tail if prev is not None else parent.text) or ""
            joins_text = bool(text_before.strip() and (owner.tail or "").strip())
            if not holds_more and not only_child and not joins_text and not self._separates_text(block):
                self.removed.add(block)
                if owner.tail:
                    if prev is not None:
                        self._move_text(owner, "tail", prev, "tail")
                    else:
                        self._move_text(owner, "tail", parent, "text")
                parent.remove(owner)
                self.changed.add(block.part)
                return
        for slot in block.slots:
            self.set_value(slot, "")

    def _separates_text(self, block: Block) -> bool:
        """True when the remaining neighbours are loose text of one container and would become one paragraph."""
        live = [b for b in self.body if b not in self.removed]
        i = live.index(block)
        return 0 < i < len(live) - 1 and live[i - 1].owner is live[i + 1].owner


def open_package(path) -> Package:
    return EpubPackage(path) if Path(path).suffix.lower() == ".epub" else DocxPackage(path)
