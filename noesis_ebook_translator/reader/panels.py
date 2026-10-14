"""Extra GUI panels: library, figures gallery, tables view and preview.

These are thin Qt wrappers around the headless core
(:mod:`noesis_ebook_translator.chapters`, :mod:`.extract`, :mod:`.exporter`,
:mod:`.book`).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)

from .. import chapters as chapters_mod
from .. import exporter, extract

_COVER_CACHE: dict[str, QIcon | None] = {}


def _cover_icon(path: str) -> QIcon | None:
    if path in _COVER_CACHE:
        return _COVER_CACHE[path]
    icon = None
    try:
        data = chapters_mod.book_meta(path).get("cover")
        if data:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                icon = QIcon(pixmap.scaledToHeight(
                    96, Qt.TransformationMode.SmoothTransformation))
    except Exception:  # noqa: BLE001
        icon = None
    _COVER_CACHE[path] = icon
    return icon


class LibraryWidget(QWidget):
    """Multi-book library backed by the JSON session."""

    openRequested = pyqtSignal(str)

    def __init__(self, session, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_add = QPushButton("Aggiungi EPUB…")
        self.btn_remove = QPushButton("Rimuovi")
        self.edt_filter = QLineEdit()
        self.edt_filter.setPlaceholderText("Filtra per titolo…")
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_remove)
        bar.addWidget(self.edt_filter, 1)
        layout.addLayout(bar)

        self.list = QListWidget()
        self.list.setIconSize(self.list.iconSize())
        layout.addWidget(self.list, 1)

        self.btn_add.clicked.connect(self._add)
        self.btn_remove.clicked.connect(self._remove)
        self.edt_filter.textChanged.connect(self.refresh)
        self.list.itemActivated.connect(self._open_item)
        self.list.itemDoubleClicked.connect(self._open_item)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        needle = self.edt_filter.text().strip().lower()
        for entry in self.session.recent():
            title = entry.get("title") or entry.get("path", "")
            if needle and needle not in title.lower():
                continue
            icon = _cover_icon(entry["path"])
            item = (QListWidgetItem(icon, title) if icon is not None
                    else QListWidgetItem(title))
            item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            self.list.addItem(item)

    def add_book(self, path: str, title: str = "") -> None:
        if not title:
            try:
                title = chapters_mod.book_meta(path).get("title") or path
            except Exception:  # noqa: BLE001
                title = path
        self.session.add_recent(path, title)
        self.refresh()

    def _add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Aggiungi EPUB", "", "EPUB (*.epub);;Tutti i file (*)")
        if path:
            self.add_book(path)

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        recent = [r for r in self.session.recent() if r.get("path") != path]
        self.session.data["recent"] = recent
        self.session.save()
        self.refresh()

    def _open_item(self, item: QListWidgetItem) -> None:
        self.openRequested.emit(item.data(Qt.ItemDataRole.UserRole))


class FiguresWidget(QWidget):
    """Figure gallery with export."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._figures = []
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_load = QPushButton("Carica figure dal libro corrente")
        self.btn_export_img = QPushButton("Esporta immagini")
        self.btn_export_html = QPushButton("Esporta HTML")
        self.btn_export_md = QPushButton("Esporta Markdown")
        for widget in (self.btn_load, self.btn_export_img,
                       self.btn_export_html, self.btn_export_md):
            bar.addWidget(widget)
        layout.addLayout(bar)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setIconSize(self.list.iconSize().expandedTo(
            self.list.iconSize().__class__(120, 120)))
        layout.addWidget(self.list, 1)

        self.btn_load.clicked.connect(self.load_current)  # wired by host
        self.btn_export_img.clicked.connect(lambda: self._export("img"))
        self.btn_export_html.clicked.connect(lambda: self._export("html"))
        self.btn_export_md.clicked.connect(lambda: self._export("md"))
        self._source = None

    def set_source(self, path: str) -> None:
        self._source = path

    def load_current(self) -> None:
        if self._source:
            self.load(self._source)

    def load(self, path: str, selected=None) -> None:
        self._source = path
        self.list.clear()
        self._figures = extract.extract_figures(path, selected=selected)
        for fig in self._figures:
            pixmap = QPixmap()
            pixmap.loadFromData(fig.data)
            icon = QIcon(pixmap.scaled(
                120, 120, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)) if not pixmap.isNull() else QIcon()
            label = f"Fig. {fig.number}" + (f" — {fig.caption[:40]}"
                                            if fig.caption else "")
            item = QListWidgetItem(icon, label)
            self.list.addItem(item)

    def _export(self, fmt: str) -> None:
        if not self._figures:
            return
        directory = QFileDialog.getExistingDirectory(self, "Cartella di export")
        if directory:
            exporter.export_figures(self._figures, directory, fmt)


class TablesWidget(QWidget):
    """Tables view (one at a time) with export."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tables = []
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_load = QPushButton("Carica tabelle dal libro corrente")
        self.cmb = QComboBox()
        self.btn_csv = QPushButton("Esporta CSV")
        self.btn_html = QPushButton("Esporta HTML")
        self.btn_md = QPushButton("Esporta Markdown")
        bar.addWidget(self.btn_load)
        bar.addWidget(self.cmb, 1)
        for widget in (self.btn_csv, self.btn_html, self.btn_md):
            bar.addWidget(widget)
        layout.addLayout(bar)

        self.table = QTableWidget()
        layout.addWidget(self.table, 1)

        self._source = None
        self.btn_load.clicked.connect(self.load_current)
        self.cmb.currentIndexChanged.connect(self._show_current)
        self.btn_csv.clicked.connect(lambda: self._export("csv"))
        self.btn_html.clicked.connect(lambda: self._export("html"))
        self.btn_md.clicked.connect(lambda: self._export("md"))

    def set_source(self, path: str) -> None:
        self._source = path

    def load_current(self) -> None:
        if self._source:
            self.load(self._source)

    def load(self, path: str, selected=None) -> None:
        self._source = path
        self._tables = extract.extract_tables(path, selected=selected)
        self.cmb.clear()
        for table in self._tables:
            label = f"Tabella {table.number}" + (
                f": {table.caption[:50]}" if table.caption else "")
            self.cmb.addItem(label)
        if self._tables:
            self._show_current(0)
        else:
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)

    def _show_current(self, index: int) -> None:
        if not (0 <= index < len(self._tables)):
            return
        rows = self._tables[index].rows
        self.table.clear()
        self.table.setColumnCount(max((len(r) for r in rows), default=0))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(value))

    def _export(self, fmt: str) -> None:
        if not self._tables:
            return
        directory = QFileDialog.getExistingDirectory(self, "Cartella di export")
        if directory:
            exporter.export_tables(self._tables, directory, fmt)


class PreviewWidget(QWidget):
    """Preview a few translated segments without writing any file."""

    def __init__(self, settings_provider, parent=None) -> None:
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._source = None
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_run = QPushButton("Anteprima")
        self.spn_limit = QSpinBox()
        self.spn_limit.setRange(1, 200)
        self.spn_limit.setValue(10)
        self.edt_chapters = QLineEdit()
        self.edt_chapters.setPlaceholderText("capitoli (es. 1,3,5-7) — vuoto = tutti")
        bar.addWidget(self.btn_run)
        bar.addWidget(QLabel("Segmenti:"))
        bar.addWidget(self.spn_limit)
        bar.addWidget(self.edt_chapters, 1)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Originale", "Traduzione"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        layout.addWidget(self.log)

        self.btn_run.clicked.connect(self.run_preview)

    def set_source(self, path: str) -> None:
        self._source = path

    def run_preview(self) -> None:
        from .. import book

        if not self._source:
            self.log.setPlainText("Nessun libro selezionato.")
            return
        options = self._settings_provider() or {}
        self.log.setPlainText("Traduzione di anteprima…")
        try:
            pairs = book.preview_translation(
                self._source, engine=options.get("engine"),
                source_lang=options.get("source", "English"),
                target_lang=options.get("target", "Italian"),
                chapters=self.edt_chapters.text().strip() or None,
                limit=self.spn_limit.value(),
                settings=options.get("settings"))
        except Exception as exc:  # noqa: BLE001
            self.log.setPlainText(f"Errore: {exc}")
            return
        self.table.setRowCount(len(pairs))
        for row, (original, translation) in enumerate(pairs):
            self.table.setItem(row, 0, QTableWidgetItem(original))
            self.table.setItem(row, 1, QTableWidgetItem(translation))
        self.log.setPlainText(f"{len(pairs)} segmenti di anteprima.")
