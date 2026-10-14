"""Full reader backend: foliate-js inside QWebEngineView.

Supports EPUB, MOBI/KF8 (AZW3), FB2, CBZ and PDF (pdf.js) with pagination, a
two-page spread, themes and printing. Python talks to the page through
QWebChannel; assets and the book are served through the private ``app://``
scheme (see :mod:`.scheme`).
"""
from __future__ import annotations

import json
import os

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .scheme import ReaderSchemeHandler, ensure_scheme

_SUPPORTED = {".epub", ".mobi", ".azw", ".azw3", ".kf8", ".fb2", ".cbz", ".pdf"}


class Bridge(QObject):
    """Receives events from the foliate-js page (JS → Python)."""

    opened = pyqtSignal(str)
    relocated = pyqtSignal(str, float, str)  # cfi, fraction, href
    loaded = pyqtSignal(str)
    failed = pyqtSignal(str)
    ready = pyqtSignal()

    @pyqtSlot(str, name="opened")
    def on_opened(self, payload: str) -> None:
        self.opened.emit(payload)

    @pyqtSlot(str, float, str, name="relocated")
    def on_relocated(self, cfi: str, fraction: float, href: str) -> None:
        self.relocated.emit(cfi, float(fraction or 0.0), href)

    @pyqtSlot(str, name="pageLoaded")
    def on_loaded(self, payload: str) -> None:
        self.loaded.emit(payload)

    @pyqtSlot(str, name="error")
    def on_error(self, message: str) -> None:
        self.failed.emit(message)

    @pyqtSlot(str, name="ready")
    def on_ready(self, payload: str) -> None:
        self.ready.emit()


class WebEngineBackend(QWidget):
    supported_extensions = _SUPPORTED

    positionChanged = pyqtSignal(str, float)
    linkClicked = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        ensure_scheme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QWebEngineView(self)
        layout.addWidget(self.view)

        self._handler = ReaderSchemeHandler(self)
        self._handler.book_dir = None
        self._profile = QWebEngineProfile.defaultProfile()
        self._profile.installUrlSchemeHandler(b"app", self._handler)

        self._channel = QWebChannel(self)
        self.bridge = Bridge()
        self._channel.registerObject("reader", self.bridge)
        self.view.page().setWebChannel(self._channel)

        self.bridge.relocated.connect(self._on_relocated)
        self.bridge.ready.connect(self._on_ready)
        self.bridge.failed.connect(self.failed)

        self._doc = None
        self._href: str | None = None
        self._fraction = 0.0
        self._pt = 16
        self._theme = "light"
        self._book_url: str | None = None
        self._ready = False

        self.view.load(QUrl("app://reader/index.html"))

    # ------------------------------------------------------------------ JS
    def _on_ready(self) -> None:
        self._ready = True
        if self._book_url:
            self._js(f"api.open({json.dumps(self._book_url)})")

    def _js(self, code: str) -> None:
        self.view.page().runJavaScript(code)

    def _on_relocated(self, cfi: str, fraction: float, href: str) -> None:
        self._fraction = fraction
        if href:
            self._href = href.split("#", 1)[0]
        self.positionChanged.emit(self._href or "", fraction)

    # ------------------------------------------- API (mirrors LiteBackend)
    def open_document(self, doc, resume: dict | None = None) -> None:
        self._doc = doc
        self._handler.book_dir = os.path.dirname(doc.path)
        self._book_url = f"app://book/{os.path.basename(doc.path)}"
        self._href = (resume or {}).get("href")
        if self._ready:
            self._js(f"api.open({json.dumps(self._book_url)})")

    def show_chapter(self, href: str, restore: float = 0.0) -> None:
        self._href = href.split("#", 1)[0]
        self._js(f"api.goTo({json.dumps(href)})")

    def next_chapter(self) -> None:
        self._js("api.next()")

    def prev_chapter(self) -> None:
        self._js("api.prev()")

    def go_to(self, href: str) -> None:
        self.show_chapter(href)

    def set_zoom(self, delta: int) -> None:
        self._pt = max(10, min(30, self._pt + delta))
        self._js(f"api.zoom({self._pt})")

    def set_theme(self, mode: str) -> None:
        self._theme = mode
        self._js(f"api.theme({json.dumps(mode)})")

    def set_font(self, family: str) -> None:
        return None

    def set_spread(self, on: bool) -> None:
        self._js(f"api.setAttr('max-column-count', {2 if on else 1})")

    def set_flow(self, flow: str) -> None:
        self._js(f"api.setAttr('flow', {json.dumps(flow)})")

    def find(self, text: str, backward: bool = False) -> bool:
        from PyQt6.QtWebEngineCore import QWebEnginePage
        flags = QWebEnginePage.FindFlag.FindBackward if backward else \
            QWebEnginePage.FindFlag(0)
        self.view.page().findText(text, flags)
        return True

    def print_pdf(self, path: str) -> None:
        self.view.page().printToPdf(path)

    def current_href(self) -> str | None:
        return self._href

    def fraction(self) -> float:
        return self._fraction

    def set_fraction(self, fraction: float) -> None:
        # The full backend syncs by CFI; a raw fraction is a best-effort no-op.
        return None

    def plain_text(self) -> str:
        return ""
