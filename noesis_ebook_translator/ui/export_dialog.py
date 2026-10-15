"""Export dialog: book/chapters → EPUB/HTML/Markdown/TXT/JSON/CSV/DOCX/PDF."""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from .. import exporter
from ..i18n import T

__all__ = ["ExportDialog"]

_EXT = {"epub": ".epub", "html": ".html", "markdown": ".md", "text": ".txt",
        "json": ".json", "csv": ".csv", "docx": ".docx", "pdf": ".pdf"}


class ExportDialog(QDialog):
    def __init__(self, source_path: str | None, translated_path: str | None,
                 parent=None) -> None:
        super().__init__(parent)
        self._source = source_path
        self._translated = translated_path
        self.setWindowTitle(T("export.title"))
        self.resize(560, 300)
        self.written: list[str] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(T("export.header")))
        form = QFormLayout()

        self.cmb_edition = QComboBox()
        self.cmb_edition.addItem(T("edition.original"), "original")
        if translated_path:
            self.cmb_edition.addItem(T("edition.translated"), "translated")
        form.addRow(T("label.edition"), self.cmb_edition)

        self.edt_chapters = QLineEdit()
        self.edt_chapters.setPlaceholderText(T("label.chapters_filter"))
        form.addRow(T("label.chapters_filter"), self.edt_chapters)

        self.cmb_format = QComboBox()
        for fmt in exporter.supported_exports():
            self.cmb_format.addItem(T(f"format.{fmt}"), fmt)
        form.addRow(T("label.format"), self.cmb_format)

        dest_row = QHBoxLayout()
        self.edt_dest = QLineEdit()
        self.btn_browse = QPushButton("…")
        self.btn_browse.clicked.connect(self._browse)
        dest_row.addWidget(self.edt_dest, 1)
        dest_row.addWidget(self.btn_browse)
        form.addRow(T("label.destination"), dest_row)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_run = QPushButton(T("export.run"))
        self.btn_run.clicked.connect(self.run_export)
        buttons.addButton(self.btn_run, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.cmb_format.currentIndexChanged.connect(self._suggest_destination)
        self._suggest_destination()

    # ------------------------------------------------------------------
    def _current_input(self) -> str | None:
        if self.cmb_edition.currentData() == "translated":
            return self._translated
        return self._source

    def _suggest_destination(self) -> None:
        source = self._current_input() or self._source or "book.epub"
        fmt = self.cmb_format.currentData() or "epub"
        base = os.path.splitext(source)[0]
        default = base + _EXT.get(fmt, ".out")
        if not self.edt_dest.text():
            self.edt_dest.setText(default)

    def _browse(self) -> None:
        fmt = self.cmb_format.currentData() or "epub"
        ext = _EXT.get(fmt, "")
        path, _ = QFileDialog.getSaveFileName(
            self, T("export.run"), self.edt_dest.text(),
            f"*.{ext.lstrip('.')}")
        if path:
            self.edt_dest.setText(path)

    def run_export(self) -> None:
        source = self._current_input()
        if not source or not os.path.isfile(source):
            QMessageBox.warning(self, T("export.title"), T("msg.no_input"))
            return
        fmt = self.cmb_format.currentData() or "epub"
        dest = self.edt_dest.text().strip()
        if not dest:
            return
        chapters = self.edt_chapters.text().strip() or None
        try:
            from ..chapters import load_chapters, resolve_selection
            selected = None
            if chapters:
                selected = resolve_selection(load_chapters(source), chapters)
            self.written = exporter.export_chapters(
                source, dest, selected, fmt)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(self, T("export.title"),
                                 T("msg.export_failed").format(exc))
            return
        QMessageBox.information(
            self, T("export.title"),
            T("msg.export_done").format("\n".join(self.written)))
        self.accept()
