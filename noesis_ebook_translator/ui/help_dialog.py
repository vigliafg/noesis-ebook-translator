"""In-app help dialog (online GitHub Pages + offline fallback)."""
from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout)

from .. import help as help_mod
from ..i18n import T

__all__ = ["HelpDialog"]


class HelpDialog(QDialog):
    def __init__(self, lang: str | None = None, section: str = "index",
                 parent=None) -> None:
        super().__init__(parent)
        self.lang = lang
        self.section = section
        self.setWindowTitle(T("help.title"))
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setHtml(help_mod.fallback_html(lang))
        self.browser.anchorClicked.connect(
            lambda url: QDesktopServices.openUrl(url))
        layout.addWidget(self.browser, 1)

        bar = QHBoxLayout()
        self.btn_online = QPushButton(T("help.open_online"))
        self.btn_online.clicked.connect(self.open_online)
        self.btn_close = QPushButton(T("action.close"))
        self.btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_online)
        bar.addStretch(1)
        bar.addWidget(self.btn_close)
        layout.addLayout(bar)

    def url(self) -> str:
        return help_mod.help_url(self.lang, self.section)

    def open_online(self) -> None:
        QDesktopServices.openUrl(QUrl(self.url()))
