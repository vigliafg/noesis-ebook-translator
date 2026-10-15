"""Full reader backend: foliate-js inside QWebEngineView.

We embed foliate's own reader engine (``reader_web/reader.html`` + ``reader.js``)
and talk to it through a small bridge (``reader_web/noesis_bridge.js``). The book
is served through the private ``app://`` scheme (see :mod:`.scheme`); the Qt
chrome (workflow bar, TOC, mini toolbar) stays in Python.

Each backend owns its own off-the-record WebEngine profile so the ``app://``
scheme handler is never installed twice on a shared profile.
"""
from __future__ import annotations

import json
import os
from urllib.parse import quote

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .scheme import ReaderSchemeHandler, book_url, ensure_scheme

_SUPPORTED = {".epub", ".mobi", ".azw", ".azw3", ".kf8", ".fb2", ".cbz", ".pdf"}


class Bridge(QObject):
    """Receives events from the foliate reader page (JS → Python)."""

    opened = pyqtSignal(str)
    relocated = pyqtSignal(str, float, str)  # cfi, fraction, href
    loaded = pyqtSignal(str)
    failed = pyqtSignal(str)
    ready = pyqtSignal()

    @pyqtSlot(str)
    def on_opened(self, payload: str) -> None:
        self.opened.emit(payload)

    @pyqtSlot(str, float, str)
    def on_relocated(self, cfi: str, fraction: float, href: str) -> None:
        self.relocated.emit(cfi, float(fraction or 0.0), href)

    @pyqtSlot(str)
    def on_loaded(self, payload: str) -> None:
        self.loaded.emit(payload)

    @pyqtSlot(str)
    def on_error(self, message: str) -> None:
        self.failed.emit(message)

    @pyqtSlot(str)
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

        self._profile = QWebEngineProfile(self)
        self._handler = ReaderSchemeHandler(self)
        self._profile.installUrlSchemeHandler(b"app", self._handler)

        self.view = QWebEngineView(self)
        self._page = QWebEnginePage(self._profile, self.view)
        self.view.setPage(self._page)
        layout.addWidget(self.view)

        self._channel = QWebChannel(self)
        self.bridge = Bridge()
        self._channel.registerObject("reader", self.bridge)
        self._page.setWebChannel(self._channel)

        self.bridge.relocated.connect(self._on_relocated)
        self.bridge.ready.connect(self._on_ready)
        self.bridge.opened.connect(self._on_opened)
        self.bridge.failed.connect(self.failed)

        self._doc = None
        self._href: str | None = None
        self._fraction = 0.0
        self._pt = 16
        self._theme = "light"
        self._font = "serif"
        self._line = 1.5
        self._justify = True
        self._hyphenate = True
        self._flow = "paginated"
        self._spread = False
        self._resume_href: str | None = None
        self._ready = False
        self._opened = False
        self._pending_ready: list[str] = []
        self._pending_nav: str | None = None
        self._to_foliate: dict[str, str] = {}
        self._from_foliate: dict[str, str] = {}

        self._page.load(QUrl("app://reader/reader.html"))

    # ------------------------------------------------------------------ JS
    def _load_book(self, url: str) -> None:
        self._page.load(QUrl(
            f"app://reader/reader.html?url={quote(url, safe='')}"))

    def _on_ready(self) -> None:
        self._ready = True
        self._opened = True
        for code in self._pending_ready:
            self._js(code)
        self._pending_ready.clear()
        self._apply_current_style()
        if self._pending_nav:
            code, self._pending_nav = self._pending_nav, None
            self._js(code)
        elif self._resume_href:
            self._js(f"api.goTo({json.dumps(self._resume_href)})")
        self._resume_href = None

    def _apply_current_style(self) -> None:
        self._js(f"api.setTheme({json.dumps(self._theme)})")
        self._js(f"api.setFont({json.dumps(self._font)})")
        self._js(f"api.setSpacing({self._line})")
        self._js(f"api.setJustify({str(bool(self._justify)).lower()})")
        self._js(f"api.setHyphenate({str(bool(self._hyphenate)).lower()})")
        self._js(f"api.setZoom({self._pt})")
        self._js(f"api.setFlow({json.dumps(self._flow)})")
        self._js(f"api.setSpread({str(bool(self._spread)).lower()})")

    def _on_opened(self, _payload: str) -> None:
        self._opened = True

    def _js(self, code: str) -> None:
        self._page.runJavaScript(code)

    def _js_when_ready(self, code: str) -> None:
        if self._ready:
            self._js(code)
        else:
            self._pending_ready.append(code)

    def _js_when_opened(self, code: str) -> None:
        if self._ready and self._opened:
            self._js(code)
        else:
            self._pending_nav = code

    def _on_relocated(self, cfi: str, fraction: float, href: str) -> None:
        self._fraction = fraction
        if href:
            self._href = self._unmap_href(href)
        self.positionChanged.emit(self._href or "", fraction)

    def _map_href(self, href: str) -> str:
        base, _, fragment = href.partition("#")
        mapped = self._to_foliate.get(base, base)
        return f"{mapped}#{fragment}" if fragment else mapped

    def _unmap_href(self, href: str) -> str:
        base, _, fragment = href.partition("#")
        mapped = self._from_foliate.get(base, base)
        return f"{mapped}#{fragment}" if fragment else mapped

    # ------------------------------------------- API (mirrors LiteBackend)
    def open_document(self, doc, resume: dict | None = None) -> None:
        self._doc = doc
        self._handler.book_dir = os.path.dirname(doc.path)
        self._to_foliate = {f: doc.foliate_href(f) for f in doc.files()}
        self._from_foliate = {v: k for k, v in self._to_foliate.items()}
        resume_href = (resume or {}).get("href")
        self._resume_href = self._map_href(resume_href) if resume_href else None
        self._href = resume_href
        self._ready = False
        self._opened = False
        self._pending_nav = None
        self._load_book(book_url(doc.path))

    def open_file(self, path: str) -> None:
        """Open any foliate-js supported format directly (no ebooklib parse)."""
        self._doc = None
        self._handler.book_dir = os.path.dirname(os.path.abspath(path))
        self._to_foliate = {}
        self._from_foliate = {}
        self._resume_href = None
        self._href = None
        self._ready = False
        self._opened = False
        self._pending_nav = None
        self._load_book(book_url(path))

    @staticmethod
    def supports(path: str) -> bool:
        return os.path.splitext(path)[1].lower() in _SUPPORTED

    def show_chapter(self, href: str, restore: float = 0.0) -> None:
        self._href = href.split("#", 1)[0]
        self._js_when_opened(f"api.goTo({json.dumps(self._map_href(href))})")

    def next_chapter(self) -> None:
        self._js_when_opened("api.next()")

    def prev_chapter(self) -> None:
        self._js_when_opened("api.prev()")

    def go_to(self, href: str) -> None:
        self.show_chapter(href)

    def set_zoom(self, delta: int) -> None:
        self._pt = max(10, min(40, self._pt + delta))
        self._js_when_ready(f"api.setZoom({self._pt})")

    def set_theme(self, mode: str) -> None:
        self._theme = mode
        self._js_when_ready(f"api.setTheme({json.dumps(mode)})")

    def set_font(self, family: str) -> None:
        self._font = family
        self._js_when_ready(f"api.setFont({json.dumps(family)})")

    def set_line_height(self, value: float) -> None:
        self._line = float(value)
        self._js_when_ready(f"api.setSpacing({self._line})")

    def set_justify(self, on: bool) -> None:
        self._justify = bool(on)
        self._js_when_ready(f"api.setJustify({str(bool(on)).lower()})")

    def set_hyphenate(self, on: bool) -> None:
        self._hyphenate = bool(on)
        self._js_when_ready(f"api.setHyphenate({str(bool(on)).lower()})")

    def set_spread(self, on: bool) -> None:
        self._spread = bool(on)
        self._js_when_ready(f"api.setSpread({str(bool(on)).lower()})")

    def set_flow(self, flow: str) -> None:
        self._flow = flow or "paginated"
        self._js_when_ready(f"api.setFlow({json.dumps(self._flow)})")

    def find(self, text: str, backward: bool = False) -> bool:
        if text:
            self._js_when_ready(f"api.search({json.dumps(text)})")
        return bool(text)

    def print_pdf(self, path: str) -> None:
        self._page.printToPdf(path)

    def current_href(self) -> str | None:
        return self._href

    def fraction(self) -> float:
        return self._fraction

    def set_fraction(self, fraction: float) -> None:
        # Synchronised via CFI by foliate; fraction is a best-effort fallback.
        if fraction:
            self._js_when_ready(f"api.goToFraction({float(fraction)})")

    def plain_text(self) -> str:
        return ""
