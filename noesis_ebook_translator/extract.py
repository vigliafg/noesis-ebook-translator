"""Headless extraction of figures, tables and text from an EPUB.

Shared logic (no Qt) used by the desktop GUI (figures gallery, tables view, text
export) and by the CLI edition. Figures get a caption (``<figcaption>``) and a
per-chapter/global number; tables get their ``<caption>`` and cell grid.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from ebooklib import epub
from lxml import etree

from .chapters import Chapter, chapter_files, isolate_chapters

__all__ = [
    "Figure", "Table", "TextBlock",
    "extract_figures", "extract_tables", "extract_text", "extract_text_blocks",
    "apply_text_edits", "apply_table_edits", "replace_image",
]

XHTML = "{http://www.w3.org/1999/xhtml}"
CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?\.?|plate|tab(?:le)?\.?|chart|map)\b", re.I)
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"}


def _localname(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and "}" in tag else tag


def _parse(item):
    return etree.fromstring(
        item.get_content(),
        parser=etree.XMLParser(recover=True, resolve_entities=False))


def _ordered_documents(book, files: set[str] | None):
    docs = []
    for entry in book.spine or []:
        item = entry[0] if isinstance(entry, (tuple, list)) else entry
        if isinstance(item, str):
            item = book.get_item_with_id(item)
        if item is None or getattr(item, "get_type", lambda: None)() != 9:
            continue
        if isinstance(item, epub.EpubNav):
            continue
        if files and item.file_name not in files:
            continue
        docs.append(item)
    if not docs:
        docs = [i for i in book.get_items() if i.get_type() == 9
                and not isinstance(i, epub.EpubNav)
                and (not files or i.file_name in files)]
    return docs


def _ensure_toc_uids(toc) -> None:
    for entry in toc or []:
        if isinstance(entry, (tuple, list)):
            if entry:
                _ensure_toc_uids([entry[0]])
            if len(entry) > 1:
                _ensure_toc_uids(entry[1])
            continue
        if hasattr(entry, "uid") and not entry.uid:
            href = getattr(entry, "href", "") or ""
            entry.uid = "toc-" + re.sub(r"[^0-9a-zA-Z]+", "", href)[:40] or "toc-x"


def _chapter_index(chapters, file_name) -> tuple[int, str]:
    if not chapters:
        return 0, ""
    for chapter in chapters:
        for node in chapter.walk():
            if node.file == file_name:
                return node.index, node.name
    return 0, ""


def _resolve_image(book, doc_name: str, src: str):
    """Return (bytes, mime, resolved_name) for an image referenced by ``src``."""
    target = posixpath.normpath(posixpath.join(posixpath.dirname(doc_name), src))
    for item in book.get_items():
        if item.file_name == target or item.file_name.endswith("/" + src) \
                or item.file_name == src:
            media = getattr(item, "media_type", "")
            if media.startswith("image/"):
                return item.get_content(), media, item.file_name
    return None, "", target


def _caption_for(img) -> str | None:
    """Best-effort caption for an ``<img>``: figcaption › nearby Fig./Plate text › alt."""
    container = None
    node = img.getparent()
    while node is not None:
        if _localname(node.tag) in ("figure", "div"):
            container = node
            break
        node = node.getparent()
    if container is not None:
        for child in container.iter():
            if _localname(child.tag) == "figcaption":
                text = " ".join(child.itertext()).split()
                if text:
                    return " ".join(text)
        candidates = []
        for child in container.iterdescendants():
            if _localname(child.tag) in ("p", "figcaption"):
                text = " ".join(" ".join(child.itertext()).split())
                if text and CAPTION_RE.match(text):
                    candidates.append(text)
        if candidates:
            return max(candidates, key=len)
    alt = (img.get("alt") or "").strip()
    return alt or None


@dataclass
class Figure:
    number: int
    chapter: int
    chapter_name: str
    src: str
    name: str
    mime: str
    data: bytes
    caption: str | None = None
    file: str = ""


@dataclass
class Table:
    number: int
    chapter: int
    chapter_name: str
    caption: str | None
    rows: list[list[str]] = field(default_factory=list)
    file: str = ""
    order: int = 0


def extract_figures(epub_path: str, chapters: list[Chapter] | None = None,
                    selected: list[Chapter] | None = None) -> list[Figure]:
    book = epub.read_epub(epub_path)
    files = chapter_files(selected) if selected else None
    if selected:
        isolate_chapters(book, selected)
    figures: list[Figure] = []
    for doc in _ordered_documents(book, files):
        doc_chapter, doc_name = _chapter_index(chapters, doc.file_name)
        try:
            root = _parse(doc)
        except Exception:  # noqa: BLE001
            continue
        for img in root.iter():
            if _localname(img.tag) != "img":
                continue
            data, mime, name = _resolve_image(book, doc.file_name, img.get("src", ""))
            if data is None:
                continue
            figures.append(Figure(
                number=len(figures) + 1, chapter=doc_chapter, chapter_name=doc_name,
                src=img.get("src", ""), name=name, mime=mime, data=data,
                caption=_caption_for(img), file=doc.file_name))
    return figures


def extract_tables(epub_path: str, chapters: list[Chapter] | None = None,
                   selected: list[Chapter] | None = None) -> list[Table]:
    book = epub.read_epub(epub_path)
    files = chapter_files(selected) if selected else None
    if selected:
        isolate_chapters(book, selected)
    tables: list[Table] = []
    for doc in _ordered_documents(book, files):
        doc_chapter, doc_name = _chapter_index(chapters, doc.file_name)
        try:
            root = _parse(doc)
        except Exception:  # noqa: BLE001
            continue
        table_order = 0
        for table in root.iter():
            if _localname(table.tag) != "table":
                continue
            caption = None
            for child in table:
                if _localname(child.tag) == "caption":
                    caption = " ".join(child.itertext()).strip() or None
                    break
            rows: list[list[str]] = []
            for tr in table.iter():
                if _localname(tr.tag) != "tr":
                    continue
                cells = [" ".join(c.itertext()).strip() for c in tr
                         if _localname(c.tag) in ("td", "th")]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(Table(
                    number=len(tables) + 1, chapter=doc_chapter,
                    chapter_name=doc_name, caption=caption, rows=rows,
                    file=doc.file_name, order=table_order))
                table_order += 1
    return tables


def extract_text(epub_path: str, chapters: list[Chapter] | None = None,
                 selected: list[Chapter] | None = None) -> list[tuple[int, str, str]]:
    """Return ``[(chapter_index, chapter_name, segment_text), ...]``."""
    book = epub.read_epub(epub_path)
    files = chapter_files(selected) if selected else None
    if selected:
        isolate_chapters(book, selected)
    out: list[tuple[int, str, str]] = []
    for doc in _ordered_documents(book, files):
        doc_chapter, doc_name = _chapter_index(chapters, doc.file_name)
        try:
            root = _parse(doc)
        except Exception:  # noqa: BLE001
            continue
        for el in root.iter():
            if _localname(el.tag) in BLOCK_TAGS:
                text = " ".join("".join(el.itertext()).split())
                if text:
                    out.append((doc_chapter, doc_name, text))
    return out


# ---------------------------------------------------------------------------
#  Editable text blocks + write-back into the EPUB (asset editor, feature 11)
# ---------------------------------------------------------------------------
@dataclass
class TextBlock:
    """A translatable block of text with a stable location inside the EPUB."""

    file: str
    order: int  # 0-based ordinal among the block tags of its document
    tag: str
    text: str


def extract_text_blocks(epub_path: str,
                        selected: list[Chapter] | None = None) -> list[TextBlock]:
    """Return every text block with a stable ``(file, order)`` locator."""
    book = epub.read_epub(epub_path)
    files = chapter_files(selected) if selected else None
    blocks: list[TextBlock] = []
    for doc in _ordered_documents(book, files):
        try:
            root = _parse(doc)
        except Exception:  # noqa: BLE001
            continue
        order = 0
        for el in root.iter():
            name = _localname(el.tag)
            if name not in BLOCK_TAGS:
                continue
            text = " ".join("".join(el.itertext()).split())
            blocks.append(TextBlock(doc.file_name, order, name, text))
            order += 1
    return blocks


def apply_text_edits(epub_path: str, output_path: str, edits) -> str:
    """Write edited text blocks back into a copy of the EPUB.

    ``edits`` is an iterable of ``(file_name, order, new_text)`` tuples. The
    edited element's inline children are replaced by the new plain text.
    """
    by_file: dict[str, dict[int, str]] = {}
    for file_name, order, text in edits:
        by_file.setdefault(file_name, {})[int(order)] = str(text)

    book = epub.read_epub(epub_path)
    for item in book.get_items():
        if item.get_type() != 9 or item.file_name not in by_file:
            continue
        try:
            root = _parse(item)
        except Exception:  # noqa: BLE001
            continue
        order = 0
        for el in root.iter():
            if _localname(el.tag) not in BLOCK_TAGS:
                continue
            new_text = by_file[item.file_name].get(order)
            if new_text is not None:
                for child in list(el):
                    el.remove(child)
                el.text = new_text
            order += 1
        item.set_content(etree.tostring(root, encoding="utf-8", method="xml",
                                        xml_declaration=True))
    _ensure_toc_uids(book.toc)
    epub.write_epub(output_path, book)
    return output_path


def apply_table_edits(epub_path: str, output_path: str, edits) -> str:
    """Write edited tables back into a copy of the EPUB.

    ``edits`` is an iterable of ``(file_name, table_order, rows)`` where ``rows``
    is a list of lists of cell strings. Existing cells are updated in place; extra
    rows/cells are appended, missing ones are left untouched.
    """
    by_file: dict[str, dict[int, list]] = {}
    for file_name, order, rows in edits:
        by_file.setdefault(file_name, {})[int(order)] = rows

    book = epub.read_epub(epub_path)
    for item in book.get_items():
        if item.get_type() != 9 or item.file_name not in by_file:
            continue
        try:
            root = _parse(item)
        except Exception:  # noqa: BLE001
            continue
        order = 0
        for table in root.iter():
            if _localname(table.tag) != "table":
                continue
            rows = by_file[item.file_name].get(order)
            if rows is not None:
                _write_table(table, rows)
            order += 1
        item.set_content(etree.tostring(root, encoding="utf-8", method="xml",
                                        xml_declaration=True))
    _ensure_toc_uids(book.toc)
    epub.write_epub(output_path, book)
    return output_path


def _write_table(table, rows: list[list[str]]) -> None:
    trs = [tr for tr in table.iter() if _localname(tr.tag) == "tr"]
    for row_index, row in enumerate(rows):
        if row_index >= len(trs):
            break
        cells = [c for c in trs[row_index]
                 if _localname(c.tag) in ("td", "th")]
        for col_index, value in enumerate(row):
            if col_index >= len(cells):
                break
            cell = cells[col_index]
            for child in list(cell):
                cell.remove(child)
            cell.text = str(value)


def replace_image(epub_path: str, output_path: str, image_name: str,
                  data: bytes) -> str:
    """Replace the bytes of one image item; return the written EPUB path."""
    book = epub.read_epub(epub_path)
    replaced = False
    for item in book.get_items():
        if item.file_name == image_name and \
                getattr(item, "media_type", "").startswith("image/"):
            item.set_content(data)
            replaced = True
    if not replaced:
        raise KeyError(image_name)
    _ensure_toc_uids(book.toc)
    epub.write_epub(output_path, book)
    return output_path

