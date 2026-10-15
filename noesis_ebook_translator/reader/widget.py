"""Composite EPUB reader widget (TOC dock + search + view + optional parallel)."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..i18n import T
from .document import EpubDocument
from .session import Session


class ReaderWidget(QWidget):
    """Reader with a multi-level TOC, search, and an optional parallel view.

    The TOC has two modes:

    * ``"read"`` — clickable bookmarks only (click a chapter to navigate);
    * ``"select"`` — clickable **and** with checkboxes to pick chapters.

    Navigating (TOC click, link click) moves **both** viewports when the
    parallel view is on, and scrolling is synchronised in both directions.
    """

    statusMessage = pyqtSignal(str)
    translatedRequested = pyqtSignal(str)  # emission → host starts translation
    parallelChanged = pyqtSignal(bool)

    def __init__(self, session: Session | None = None, backend_mode: str = "auto",
                 parent=None) -> None:
        super().__init__(parent)
        self.session = session or Session()
        self.document: EpubDocument | None = None
        self._translated: EpubDocument | None = None
        self._syncing = False
        self._toc_mode = "read"
        self._toc_items: list = []
        self._parallel = False

        from . import create_backend
        self.mode = backend_mode
        self.backend = create_backend(backend_mode, self)
        self.second = create_backend(backend_mode, self)
        self.second.hide()

        self._build_ui()
        self.backend.linkClicked.connect(self._on_link)
        self.backend.positionChanged.connect(self._on_position)
        self.second.positionChanged.connect(self._on_second_scroll)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.toc = QTreeWidget()
        self.toc.setHeaderLabels([T("action.toc")])
        self.toc.setMinimumWidth(200)
        self.toc.itemClicked.connect(self._on_toc_click)
        self.toc.itemActivated.connect(self._on_toc_click)
        splitter.addWidget(self.toc)

        views = QSplitter(Qt.Orientation.Horizontal)
        views.addWidget(self.backend)
        views.addWidget(self.second)
        self._views = views
        splitter.addWidget(views)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    # --------------------------------------------------------------- open
    def open_path(self, path: str) -> None:
        if not path.lower().endswith(".epub") and hasattr(self.backend, "open_file") \
                and self.backend.supports(path):
            # Non-EPUB formats are handled natively by the full (foliate-js) backend.
            self.document = None
            self.toc.clear()
            self._toc_items = []
            self.backend.open_file(path)
            self.session.add_recent(path, path.rsplit("/", 1)[-1])
            self.statusMessage.emit(path.rsplit("/", 1)[-1])
            return
        self.document = EpubDocument(path)
        self._populate_toc()
        resume = self.session.get_position(path)
        self.backend.open_document(self.document, resume)
        self.session.add_recent(path, self.document.title())
        self.statusMessage.emit(self.document.title())

    def set_translated_path(self, path: str) -> None:
        try:
            self._translated = EpubDocument(path)
        except Exception:  # noqa: BLE001
            self._translated = None

    # --------------------------------------------------------------- theme
    def set_theme(self, mode: str) -> None:
        """Apply the reading theme to both viewports (called by ``apply_theme``)."""
        for backend in (self.backend, self.second):
            try:
                backend.set_theme(mode)
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- TOC
    def _populate_toc(self) -> None:
        self.toc.clear()
        self._toc_items = []
        if self.document is None:
            return
        items: list[QTreeWidgetItem] = []

        def add(chapter, parent_item=None):
            item = QTreeWidgetItem([chapter.name or chapter.file or "(section)"])
            if chapter.file:
                item.setData(0, Qt.ItemDataRole.UserRole, chapter.file)
            if parent_item is None:
                self.toc.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            for child in chapter.children:
                add(child, item)
            items.append(item)

        for chapter in self.document.chapters:
            add(chapter)
        self._toc_items = items
        self.toc.expandAll()
        self._apply_toc_mode()

    def set_toc_mode(self, mode: str) -> None:
        """Set the TOC behaviour: ``"read"`` (click only) or ``"select"``."""
        self._toc_mode = "select" if mode == "select" else "read"
        self._apply_toc_mode()

    def toc_mode(self) -> str:
        return self._toc_mode

    def _apply_toc_mode(self) -> None:
        selectable = self._toc_mode == "select"
        for item in self._toc_items:
            flags = item.flags()
            if selectable:
                item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
                if item.data(0, Qt.ItemDataRole.CheckStateRole) is None:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                # Clearing the data (not just the flag) is required: Qt keeps
                # drawing the checkbox while a CheckStateRole value is present.
                item.setData(0, Qt.ItemDataRole.CheckStateRole, None)
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)

    def selected_files(self) -> list[str]:
        """Files of the checked chapters (a checked parent selects its subtree)."""
        result: list[str] = []

        def collect(item: QTreeWidgetItem, inherit: bool) -> None:
            checked = inherit or item.checkState(0) == Qt.CheckState.Checked
            if checked:
                file_name = item.data(0, Qt.ItemDataRole.UserRole)
                if file_name and file_name not in result:
                    result.append(file_name)
            for i in range(item.childCount()):
                collect(item.child(i), checked)

        for i in range(self.toc.topLevelItemCount()):
            collect(self.toc.topLevelItem(i), False)
        return result

    # ---------------------------------------------------------- navigation
    def _navigate(self, href: str, fraction: float = 0.0) -> None:
        """Move the primary viewport (and the parallel one) to ``href``."""
        self.backend.show_chapter(href, restore=fraction)
        if self._parallel and self._translated is not None:
            self.second.show_chapter(href, restore=fraction)

    def _on_toc_click(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        file_name = item.data(0, Qt.ItemDataRole.UserRole)
        if file_name:
            self._navigate(file_name)
        else:
            # A section (no file): expand/collapse instead of navigating.
            item.setExpanded(not item.isExpanded())

    def _on_link(self, href: str) -> None:
        if not href:
            return
        if href.startswith(("http://", "https://", "mailto:")):
            self.statusMessage.emit(href)
            return
        file_name = href.split("#", 1)[0]
        if file_name and self.document and file_name in self.document.files():
            self._navigate(href)

    def _on_position(self, href: str, fraction: float) -> None:
        if self.document is not None:
            self.session.set_position(self.document.path, href, fraction)
        if self._parallel and self._translated is not None and not self._syncing:
            self._syncing = True
            try:
                if href and self.second.current_href() != href:
                    self.second.show_chapter(href, restore=fraction)
                else:
                    self.second.set_fraction(fraction)
            finally:
                self._syncing = False

    def _on_second_scroll(self, href: str, fraction: float) -> None:
        if not self._parallel or self._syncing:
            return
        self._syncing = True
        try:
            if href and self.backend.current_href() != href:
                self.backend.show_chapter(href, restore=fraction)
            else:
                self.backend.set_fraction(fraction)
        finally:
            self._syncing = False

    # ------------------------------------------------------------- parallel
    def is_parallel(self) -> bool:
        return self._parallel

    def set_parallel(self, on: bool) -> None:
        on = bool(on) and self._translated is not None
        if on == self._parallel:
            return
        self._parallel = on
        if on:
            self.second.show()
            href = self.backend.current_href()
            self.second.open_document(
                self._translated, {"href": href, "fraction": self.backend.fraction()})
        else:
            self.second.hide()
        self.parallelChanged.emit(self._parallel)

    def toggle_parallel(self) -> None:
        self.set_parallel(not self._parallel)

    # --------------------------------------------------------------- search
    def find_text(self, text: str, backward: bool = False) -> bool:
        if not text:
            return False
        return bool(self.backend.find(text, backward))

    # Backwards-compatible alias.
    def find_next(self, text: str = "", backward: bool = False) -> bool:
        return self.find_text(text, backward)
