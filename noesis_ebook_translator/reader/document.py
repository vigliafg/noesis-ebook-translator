"""EPUB document model for the reader (extract to temp, chapter access)."""
from __future__ import annotations

import os
import tempfile
import zipfile

from ebooklib import epub
from lxml import etree

from ..chapters import book_meta, chapters_from_book, flatten

XHTML = "{http://www.w3.org/1999/xhtml}"


class EpubDocument:
    """A book opened for reading: chapters, metadata and a temp working dir."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        self.book = epub.read_epub(path)
        self.chapters = chapters_from_book(self.book)
        self._flat = flatten(self.chapters)
        self.meta = book_meta(path)
        self.workdir = tempfile.mkdtemp(prefix="noesis-reader-")
        with zipfile.ZipFile(path) as archive:
            archive.extractall(self.workdir)
        self._docs = self._spine_files()
        if not self._docs:
            self._docs = [i.file_name for i in self.book.get_items()
                          if i.get_type() == 9]

    def _spine_files(self) -> list[str]:
        files: list[str] = []
        for entry in self.book.spine or []:
            item = entry[0] if isinstance(entry, (tuple, list)) else entry
            if isinstance(item, str):
                item = self.book.get_item_with_id(item)
            if item is None or getattr(item, "get_type", lambda: None)() != 9:
                continue
            if item.file_name not in files:
                files.append(item.file_name)
        return files

    # -- chapters ---------------------------------------------------------
    def chapter_list(self):
        return self._flat

    def readable_chapters(self):
        return [c for c in self._flat if c.file]

    def files(self) -> list[str]:
        return list(self._docs)

    def chapter_path(self, file_name: str) -> str:
        return os.path.join(self.workdir, file_name.split("#", 1)[0])

    def index_of(self, file_name: str) -> int:
        try:
            return self._docs.index(file_name)
        except ValueError:
            return 0

    def body_html(self, file_name: str) -> str:
        """Return the inner HTML of a chapter's ``<body>`` (images inlined)."""
        item = next((i for i in self.book.get_items()
                     if i.file_name == file_name and i.get_type() == 9), None)
        if item is None:
            return ""
        root = etree.fromstring(item.get_content(),
                                parser=etree.XMLParser(recover=True))
        body = root.find(f".//{XHTML}body")
        if body is None:
            body = root.find(".//body")
        if body is None:
            return ""
        return "".join(etree.tostring(child, encoding="unicode") for child in body)

    def title(self) -> str:
        return self.meta.get("title") or os.path.basename(self.path)
