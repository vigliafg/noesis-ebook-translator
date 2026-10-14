"""Composite EPUB reader widget (TOC dock + toolbar + view + optional parallel)."""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLineEdit, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from .document import EpubDocument
from .session import Session


class ReaderWidget(QWidget):
    """Reader with a multi-level TOC, navigation, zoom, theme, find, parallel."""

    statusMessage = pyqtSignal(str)
    translatedRequested = pyqtSignal(str)  # emission → host starts translation

    def __init__(self, session: Session | None = None, backend_mode: str = "auto",
                 parent=None) -> None:
        super().__init__(parent)
        self.session = session or Session()
        self.document: EpubDocument | None = None
        self._translated: EpubDocument | None = None
        self._syncing = False

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

        bar = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.btn_prev.clicked.connect(lambda: self.backend.prev_chapter())
        self.btn_next.clicked.connect(lambda: self.backend.next_chapter())
        self.btn_zoom_out = QPushButton("A−")
        self.btn_zoom_in = QPushButton("A+")
        self.btn_zoom_out.clicked.connect(lambda: self.backend.set_zoom(-1))
        self.btn_zoom_in.clicked.connect(lambda: self.backend.set_zoom(1))
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(["light", "sepia", "dark"])
        self.cmb_theme.currentTextChanged.connect(self.backend.set_theme)
        self.btn_parallel = QPushButton("Parallelo")
        self.btn_parallel.setCheckable(True)
        self.btn_parallel.toggled.connect(self._toggle_parallel)
        self.edt_find = QLineEdit()
        self.edt_find.setPlaceholderText("Cerca nel capitolo…")
        self.edt_find.returnPressed.connect(lambda: self._find(False))
        for widget in (self.btn_prev, self.btn_next, self.btn_zoom_out,
                       self.btn_zoom_in, self.cmb_theme, self.btn_parallel):
            bar.addWidget(widget)
        bar.addWidget(self.edt_find, 1)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.toc = QTreeWidget()
        self.toc.setHeaderLabels(["Indice"])
        self.toc.setMinimumWidth(200)
        self.toc.itemClicked.connect(self._on_toc_click)
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

    def _populate_toc(self) -> None:
        self.toc.clear()
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
        self.toc.expandAll()

    # ---------------------------------------------------------- callbacks
    def _on_toc_click(self, item: QTreeWidgetItem, _column: int) -> None:
        file_name = item.data(0, Qt.ItemDataRole.UserRole)
        if file_name:
            self.backend.show_chapter(file_name)

    def _on_link(self, href: str) -> None:
        if not href:
            return
        if href.startswith(("http://", "https://", "mailto:")):
            self.statusMessage.emit(href)
            return
        file_name = href.split("#", 1)[0]
        if file_name and self.document and file_name in self.document.files():
            self.backend.show_chapter(href)

    def _on_position(self, href: str, fraction: float) -> None:
        if self.document is not None:
            self.session.set_position(self.document.path, href, fraction)
        if self.btn_parallel.isChecked() and not self._syncing:
            self._syncing = True
            try:
                if self.second.current_href() != href:
                    self.second.show_chapter(href)
                self.second._pending_fraction = fraction  # noqa: SLF001
                self.second._apply_pending_fraction()  # noqa: SLF001
            finally:
                self._syncing = False

    def _on_second_scroll(self, href: str, fraction: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self.backend._pending_fraction = fraction  # noqa: SLF001
            self.backend._apply_pending_fraction()  # noqa: SLF001
        finally:
            self._syncing = False

    def _toggle_parallel(self, on: bool) -> None:
        if on and self._translated is not None:
            self.second.show()
            href = self.backend.current_href()
            if href:
                self.second.open_document(
                    self._translated, {"href": href, "fraction": self.backend.fraction()})
        else:
            self.second.hide()

    def _find(self, backward: bool) -> None:
        text = self.edt_find.text().strip()
        if text:
            self.backend.find(text, backward)
