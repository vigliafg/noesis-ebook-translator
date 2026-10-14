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

from .chapters import Chapter, chapter_files

__all__ = ["Figure", "Table", "extract_figures", "extract_tables", "extract_text"]

XHTML = "{http://www.w3.org/1999/xhtml}"
CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?\.?|plate|tab(?:le)?\.?|chart|map)\b", re.I)


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
        if files and item.file_name not in files:
            continue
        docs.append(item)
    if not docs:
        docs = [i for i in book.get_items() if i.get_type() == 9
                and (not files or i.file_name in files)]
    return docs


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


@dataclass
class Table:
    number: int
    chapter: int
    chapter_name: str
    caption: str | None
    rows: list[list[str]] = field(default_factory=list)


def extract_figures(epub_path: str, chapters: list[Chapter] | None = None,
                    selected: list[Chapter] | None = None) -> list[Figure]:
    book = epub.read_epub(epub_path)
    files = chapter_files(selected) if selected else None
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
                caption=_caption_for(img)))
    return figures


def extract_tables(epub_path: str, chapters: list[Chapter] | None = None,
                   selected: list[Chapter] | None = None) -> list[Table]:
    book = epub.read_epub(epub_path)
    files = chapter_files(selected) if selected else None
    tables: list[Table] = []
    for doc in _ordered_documents(book, files):
        doc_chapter, doc_name = _chapter_index(chapters, doc.file_name)
        try:
            root = _parse(doc)
        except Exception:  # noqa: BLE001
            continue
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
                    chapter_name=doc_name, caption=caption, rows=rows))
    return tables


def extract_text(epub_path: str, chapters: list[Chapter] | None = None,
                 selected: list[Chapter] | None = None) -> list[tuple[int, str, str]]:
    """Return ``[(chapter_index, chapter_name, segment_text), ...]``."""
    book = epub.read_epub(epub_path)
    files = chapter_files(selected) if selected else None
    out: list[tuple[int, str, str]] = []
    block_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"}
    for doc in _ordered_documents(book, files):
        doc_chapter, doc_name = _chapter_index(chapters, doc.file_name)
        try:
            root = _parse(doc)
        except Exception:  # noqa: BLE001
            continue
        for el in root.iter():
            if _localname(el.tag) in block_tags:
                text = " ".join("".join(el.itertext()).split())
                if text:
                    out.append((doc_chapter, doc_name, text))
    return out
