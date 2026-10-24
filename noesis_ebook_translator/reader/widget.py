"""Composite EPUB reader widget (TOC dock + search + view + optional parallel)."""
from __future__ import annotations

import os

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from ..i18n import T
from .document import EpubDocument
from .session import Session


def _deleted(obj) -> bool:
    """True when the Qt object behind ``obj`` has already been destroyed."""
    try:
        return sip.isdeleted(obj)
    except Exception:  # noqa: BLE001 - not a SIP wrapper at all
        return False


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
    flowChanged = pyqtSignal(str)
    spreadChanged = pyqtSignal(bool)
    tocVisibilityChanged = pyqtSignal(bool)
    fullscreenRequested = pyqtSignal()

    def __init__(self, session: Session | None = None, backend_mode: str = "auto",
                 parent=None) -> None:
        super().__init__(parent)
        self.session = session or Session()
        self.document: EpubDocument | None = None
        self._translated: EpubDocument | None = None
        self._syncing = False
        self._toc_mode = "read"
        self._toc_items: list = []
        self._current_toc_item = None
        self._toc_visible = False
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
    def shutdown(self) -> None:
        """Tear the readers down (called when the window closes)."""
        for backend in (self.backend, self.second):
            teardown = getattr(backend, "shutdown", None)
            if callable(teardown):
                try:
                    teardown()
                except Exception:  # noqa: BLE001 - never block closing
                    pass

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.shutdown()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Reader toolbar: the controls used *while reading*, and therefore the
        # only ones available in full screen (where the ribbon is hidden).
        # Theme, font, line height and search stay in the Reader ribbon panel:
        # two controls for the same setting would mean two states to sync.
        bar = QHBoxLayout()
        self.btn_toc = QPushButton(T("action.toc"))
        self.btn_toc.setCheckable(True)
        self.btn_toc.setToolTip(T("tip.toc"))
        self.btn_toc.toggled.connect(self.set_toc_visible)
        self.btn_prev = QPushButton("◀ " + T("action.prev"))
        self.btn_next = QPushButton(T("action.next") + " ▶")
        self.btn_prev.clicked.connect(lambda: self.backend.prev_chapter())
        self.btn_next.clicked.connect(lambda: self.backend.next_chapter())
        self.cmb_flow = QComboBox()
        self.cmb_flow.addItem(T("flow.paginated"), "paginated")
        self.cmb_flow.addItem(T("flow.scrolled"), "scrolled")
        self.cmb_flow.currentIndexChanged.connect(
            lambda i: self.set_flow(self.cmb_flow.itemData(i)))
        self.btn_spread = QPushButton(T("label.spread"))
        self.btn_spread.setCheckable(True)
        self.btn_spread.toggled.connect(self.set_spread)
        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setToolTip(T("assets.zoom_out"))
        self.btn_zoom_out.clicked.connect(lambda: self.set_zoom(-1))
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setToolTip(T("assets.zoom_in"))
        self.btn_zoom_in.clicked.connect(lambda: self.set_zoom(1))
        self.btn_fullscreen = QPushButton(T("action.fullscreen"))
        self.btn_fullscreen.setToolTip(T("tip.fullscreen"))
        self.btn_fullscreen.clicked.connect(self.fullscreenRequested.emit)
        bar.addWidget(self.btn_toc)
        bar.addWidget(self.btn_prev)
        bar.addWidget(self.btn_next)
        bar.addSpacing(12)
        bar.addWidget(self.cmb_flow)
        bar.addWidget(self.btn_spread)
        bar.addSpacing(12)
        bar.addWidget(self.btn_zoom_out)
        bar.addWidget(self.btn_zoom_in)
        bar.addStretch(1)
        bar.addWidget(self.btn_fullscreen)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.toc = QTreeWidget()
        self.toc.setHeaderLabels([T("action.toc")])
        self.toc.setMinimumWidth(200)
        self.toc.itemClicked.connect(self._on_toc_click)
        self.toc.itemActivated.connect(self._on_toc_click)
        # Reader-first: the TOC takes the whole pane away only on demand.
        self.toc.setVisible(self._toc_visible)
        splitter.addWidget(self.toc)

        views = QSplitter(Qt.Orientation.Horizontal)
        views.addWidget(self.backend)
        views.addWidget(self.second)
        self._views = views
        splitter.addWidget(views)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    # --------------------------------------------------------------- open
    def show_chapter(self, href: str, fraction: float = 0.0) -> None:
        """Public navigation hook for other panels (chapter list, search)."""
        if href:
            self._navigate(href, fraction)

    def open_path(self, path: str) -> None:
        if not path.lower().endswith(".epub") and hasattr(self.backend, "open_file") \
                and self.backend.supports(path):
            # Non-EPUB formats are handled natively by the full (foliate-js) backend.
            self.document = None
            self.toc.clear()
            self._toc_items = []
            self._current_toc_item = None
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

    def set_font(self, family: str) -> None:
        """Apply the reading font to both viewports."""
        for backend in (self.backend, self.second):
            try:
                backend.set_font(family)
            except Exception:  # noqa: BLE001
                pass

    def set_line_height(self, value: float) -> None:
        """Apply the line height to both viewports."""
        for backend in (self.backend, self.second):
            try:
                backend.set_line_height(value)
            except Exception:  # noqa: BLE001
                pass

    def set_justify(self, on: bool) -> None:
        for backend in (self.backend, self.second):
            try:
                backend.set_justify(bool(on))
            except Exception:  # noqa: BLE001
                pass

    def set_hyphenate(self, on: bool) -> None:
        for backend in (self.backend, self.second):
            try:
                backend.set_hyphenate(bool(on))
            except Exception:  # noqa: BLE001
                pass

    def expand_all(self) -> None:
        self.toc.expandAll()

    def collapse_all(self) -> None:
        self.toc.collapseAll()

    def _mark_current(self, href: str | None) -> None:
        """Bold the TOC entry of the chapter currently shown."""
        if not href or not self._toc_items:
            return
        base = href.split("#", 1)[0]
        target = None
        for item in self._toc_items:
            if item.data(0, Qt.ItemDataRole.UserRole) == base:
                target = item
                break
        if target is self._current_toc_item:
            return
        if self._current_toc_item is not None and not _deleted(self._current_toc_item):
            # Opening another book rebuilds the tree, so the remembered item can
            # belong to a widget that no longer exists (RuntimeError otherwise).
            font = self._current_toc_item.font(0)
            font.setBold(False)
            self._current_toc_item.setFont(0, font)
        self._current_toc_item = target
        if target is not None:
            font = target.font(0)
            font.setBold(True)
            target.setFont(0, font)
            self.toc.scrollToItem(target)

    def set_flow(self, mode: str) -> None:
        """Set the flow (``paginated``/``scrolled``) on both viewports."""
        for backend in (self.backend, self.second):
            if hasattr(backend, "set_flow"):
                try:
                    backend.set_flow(mode)
                except Exception:  # noqa: BLE001
                    pass
        self.flowChanged.emit(mode or "paginated")

    def set_spread(self, on: bool) -> None:
        """Set single vs two-page spread on both viewports."""
        for backend in (self.backend, self.second):
            if hasattr(backend, "set_spread"):
                try:
                    backend.set_spread(bool(on))
                except Exception:  # noqa: BLE001
                    pass
        self.spreadChanged.emit(bool(on))

    def set_zoom(self, delta: int) -> None:
        """Zoom **both** viewports.

        The ribbon used to call ``backend.set_zoom`` directly, so the parallel
        (translated) view kept its own zoom and drifted apart from the primary
        one. Everything that zooms now goes through here.
        """
        for backend in (self.backend, self.second):
            zoom = getattr(backend, "set_zoom", None)
            if callable(zoom):
                try:
                    zoom(int(delta))
                except Exception:  # noqa: BLE001
                    pass

    def apply_reading_settings(self, *, theme=None, font=None, line=None,
                               justify=None, hyphenate=None, flow=None,
                               spread=None) -> None:
        """Apply saved reading defaults to the viewports and the mini toolbar."""
        if theme:
            self.set_theme(theme)
        if font:
            self.set_font(font)
        if line is not None:
            self.set_line_height(line)
        if justify is not None:
            self.set_justify(justify)
        if hyphenate is not None:
            self.set_hyphenate(hyphenate)
        if flow:
            index = self.cmb_flow.findData(flow)
            if index >= 0:
                self.cmb_flow.setCurrentIndex(index)
        if spread is not None:
            self.btn_spread.setChecked(bool(spread))

    # ---------------------------------------------------------------- TOC
    def _populate_toc(self) -> None:
        self.toc.clear()
        self._toc_items = []
        # The remembered item belonged to the tree that was just cleared.
        self._current_toc_item = None
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

    # ------------------------------------------------------ TOC visibility
    def set_toc_visible(self, visible: bool) -> None:
        """Show or hide the TOC pane.

        The pane keeps working while hidden (navigation, checkboxes and
        ``selected_files()`` only need the tree, not a visible widget).
        """
        visible = bool(visible)
        if visible == self._toc_visible:
            return
        self._toc_visible = visible
        self.toc.setVisible(visible)
        if self.btn_toc.isChecked() != visible:
            self.btn_toc.blockSignals(True)
            self.btn_toc.setChecked(visible)
            self.btn_toc.blockSignals(False)
        self.tocVisibilityChanged.emit(visible)

    def toc_visible(self) -> bool:
        return self._toc_visible

    def toggle_toc(self) -> None:
        self.set_toc_visible(not self._toc_visible)

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
        self._mark_current(href)
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
