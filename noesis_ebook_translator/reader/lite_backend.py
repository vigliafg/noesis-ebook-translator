"""Lite reader backend: QTextBrowser (no WebEngine needed)."""
from __future__ import annotations

import os

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from .document import EpubDocument

THEMES = {
    "light": "body{background:#ffffff;color:#1c1e21;}",
    "sepia": "body{background:#f4ecd8;color:#4a3f2f;}",
    "dark": "body{background:#1f2227;color:#e8eaed;}",
}

BASE_CSS = """
body {{ font-family: {family}; font-size: {size}pt; line-height: {line};
        margin: 1.5rem auto; max-width: 42rem; padding: 0 1rem; }}
img {{ max-width: 100%; }}
h1,h2,h3 {{ line-height: 1.25; }}
a {{ color: #2d6cdf; }}
"""


class LiteBackend(QWidget):
    """A chapter reader based on ``QTextBrowser`` (EPUB only)."""

    positionChanged = pyqtSignal(str, float)
    linkClicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setOpenExternalLinks(False)
        self.view.anchorClicked.connect(self._on_anchor)
        self.view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self._doc: EpubDocument | None = None
        self._href: str | None = None
        self._zoom = 0
        self._theme = "light"
        self._font = "serif"
        self._line = 1.5
        self._pending_fraction = 0.0

    # -- opening ----------------------------------------------------------
    def open_document(self, doc: EpubDocument, resume: dict | None = None) -> None:
        self._doc = doc
        href = (resume or {}).get("href") or (doc.readable_chapters() or [None])[0].file
        self._pending_fraction = float((resume or {}).get("fraction") or 0.0)
        if href:
            self.show_chapter(href, restore=self._pending_fraction)

    def show_chapter(self, href: str, restore: float = 0.0) -> None:
        if self._doc is None:
            return
        self._href = href.split("#", 1)[0]
        path = self._doc.chapter_path(self._href)
        body = self._doc.body_html(self._href)
        html = self._wrap(body)
        base = QUrl.fromLocalFile(os.path.dirname(path) + os.sep)
        self.view.document().setBaseUrl(base)
        self.view.setSearchPaths([os.path.dirname(path)])
        self.view.setHtml(html)
        self._pending_fraction = float(restore or 0.0)
        QTimer.singleShot(0, self._apply_pending_fraction)
        self.positionChanged.emit(self._href, self._pending_fraction)

    def _wrap(self, body: str) -> str:
        css = BASE_CSS.format(family=self._font, size=12 + self._zoom,
                              line=self._line)
        css += THEMES.get(self._theme, "")
        return f"<html><head><style>{css}</style></head><body>{body}</body></html>"

    def _apply_pending_fraction(self) -> None:
        bar = self.view.verticalScrollBar()
        if self._pending_fraction and bar.maximum() > 0:
            bar.setValue(int(self._pending_fraction * bar.maximum()))
        self._pending_fraction = 0.0

    # -- navigation -------------------------------------------------------
    def next_chapter(self) -> None:
        self._step(1)

    def prev_chapter(self) -> None:
        self._step(-1)

    def _step(self, delta: int) -> None:
        if self._doc is None or self._href is None:
            return
        files = self._doc.files()
        index = files.index(self._href) if self._href in files else 0
        index = max(0, min(len(files) - 1, index + delta))
        self.show_chapter(files[index])

    def go_to(self, href: str) -> None:
        self.show_chapter(href)

    # -- display ----------------------------------------------------------
    def set_zoom(self, delta: int) -> None:
        self._zoom = max(-4, min(12, self._zoom + delta))
        if self._href:
            self.show_chapter(self._href, restore=self.fraction())

    def set_theme(self, mode: str) -> None:
        self._theme = mode if mode in THEMES else "light"
        if self._href:
            self.show_chapter(self._href, restore=self.fraction())

    def set_font(self, family: str) -> None:
        self._font = family
        if self._href:
            self.show_chapter(self._href, restore=self.fraction())

    def set_line_height(self, value: float) -> None:
        self._line = float(value)
        if self._href:
            self.show_chapter(self._href, restore=self.fraction())

    def find(self, text: str, backward: bool = False) -> bool:
        from PyQt6.QtGui import QTextDocument
        found = self.view.find(
            text, QTextDocument.FindFlag.FindBackward if backward
            else QTextDocument.FindFlag(0))
        return bool(found)

    # -- state ------------------------------------------------------------
    def current_href(self) -> str | None:
        return self._href

    def fraction(self) -> float:
        bar = self.view.verticalScrollBar()
        return (bar.value() / bar.maximum()) if bar.maximum() else 0.0

    def set_fraction(self, fraction: float) -> None:
        self._pending_fraction = float(fraction or 0.0)
        self._apply_pending_fraction()

    def plain_text(self) -> str:
        return self.view.toPlainText()

    # -- signals ----------------------------------------------------------
    def _on_scroll(self, _value: int) -> None:
        if self._href:
            self.positionChanged.emit(self._href, self.fraction())

    def _on_anchor(self, url: QUrl) -> None:
        self.linkClicked.emit(url.toString())
