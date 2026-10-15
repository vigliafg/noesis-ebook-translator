"""GUI panels: library, chapters, figure/image editor, tables editor, texts,
preview.

Thin Qt wrappers around the headless core (:mod:`noesis_ebook_translator.chapters`,
:mod:`.extract`, :mod:`.exporter`, :mod:`.book`, :mod:`.chapter_store`).
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import chapters as chapters_mod
from .. import exporter, extract
from ..i18n import T

_COVER_CACHE: dict[str, bytes | None] = {}


def _cover_pixmap(path: str) -> QPixmap | None:
    if path not in _COVER_CACHE:
        try:
            _COVER_CACHE[path] = chapters_mod.book_meta(path).get("cover")
        except Exception:  # noqa: BLE001
            _COVER_CACHE[path] = None
    data = _COVER_CACHE[path]
    if not data:
        return None
    pixmap = QPixmap()
    return pixmap if pixmap.loadFromData(data) else None


def _cover_icon(path: str) -> QIcon | None:
    pixmap = _cover_pixmap(path)
    if pixmap is None:
        return None
    return QIcon(pixmap.scaledToHeight(96, Qt.TransformationMode.SmoothTransformation))


def _fallback_icon() -> QIcon:
    from ..ui.icons import icon as _icon
    return _icon("library")


def _chapter_icon() -> QIcon:
    from ..ui.icons import icon as _icon
    return _icon("chapters")


class LibraryWidget(QWidget):
    """Multi-book library with two layouts (grid of covers / vertical list).

    Views (content): ``original`` (all books), ``translated`` (books with a
    translation) and ``chapters`` (extracted chapters). Layouts (presentation):
    ``grid`` (5 covers per row, multi-line title below) and ``list`` (cover with
    the title on the right).
    """

    openRequested = pyqtSignal(str)

    def __init__(self, session, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self._view = "original"
        self._layout = "grid"
        from ..chapter_store import ChapterStore
        self.store = ChapterStore()
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_add = QPushButton(T("library.add"))
        self.btn_remove = QPushButton(T("library.remove"))
        self.edt_filter = QLineEdit()
        self.edt_filter.setPlaceholderText(T("library.filter"))
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_remove)
        bar.addWidget(self.edt_filter, 1)
        layout.addLayout(bar)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(6)
        self.list.itemActivated.connect(self._open_item)
        self.list.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self.list, 1)

        self.btn_add.clicked.connect(self._add)
        self.btn_remove.clicked.connect(self._remove)
        self.edt_filter.textChanged.connect(self.refresh)
        self.set_layout("grid")
        self.refresh()

    # ------------------------------------------------------------ modes
    def set_layout(self, layout: str) -> None:
        self._layout = "list" if layout == "list" else "grid"
        if self._layout == "grid":
            self.list.setViewMode(QListWidget.ViewMode.IconMode)
            self.list.setIconSize(QSize(110, 150))
            self._update_grid()
        else:
            self.list.setViewMode(QListWidget.ViewMode.ListMode)
            self.list.setGridSize(QSize())
            self.list.setIconSize(QSize(48, 64))

    def layout_mode(self) -> str:
        return self._layout

    def _update_grid(self) -> None:
        # 5 covers per row
        width = max(self.list.viewport().width(), 400)
        cell = max(120, width // 5)
        self.list.setGridSize(QSize(cell, 210))

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self._layout == "grid":
            self._update_grid()

    def set_view(self, view: str) -> None:
        self._view = view if view in ("original", "translated", "chapters") else "original"
        self.refresh()

    def view(self) -> str:
        return self._view

    # ------------------------------------------------------------ content
    def refresh(self) -> None:
        self.list.clear()
        needle = self.edt_filter.text().strip().lower()
        if self._view == "chapters":
            self._refresh_chapters(needle)
        else:
            self._refresh_books(needle)

    def _refresh_books(self, needle: str) -> None:
        for entry in self.session.recent():
            if self._view == "translated" and not entry.get("translated_path"):
                continue
            title = entry.get("title") or entry.get("path", "")
            if needle and needle not in title.lower():
                continue
            if entry.get("translated_path"):
                title = f"{title}  ({T('library.translated')})"
            icon = self._book_icon(entry["path"])
            item = QListWidgetItem(icon, title)
            item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            item.setToolTip(entry["path"])
            self.list.addItem(item)

    def _refresh_chapters(self, needle: str) -> None:
        try:
            rows = self.store.all()
        except Exception:  # noqa: BLE001
            rows = []
        fallback = _chapter_icon()
        for row in rows:
            book = os.path.basename(row.get("book_path", ""))
            name = row.get("name") or row.get("chapter_index")
            label = f"{name}\n{book}" if self._layout == "grid" else f"{name} — {book}"
            if needle and needle not in label.lower():
                continue
            icon = self._book_icon(row.get("book_path", ""), fallback)
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, row.get("book_path", ""))
            self.list.addItem(item)

    def _book_icon(self, path: str, fallback: QIcon | None = None) -> QIcon:
        pixmap = _cover_pixmap(path)
        if pixmap is not None:
            return QIcon(pixmap.scaled(
                110, 150, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        return fallback if fallback is not None else _fallback_icon()

    def add_book(self, path: str, title: str = "") -> None:
        if not title:
            try:
                title = chapters_mod.book_meta(path).get("title") or path
            except Exception:  # noqa: BLE001
                title = path
        cover = None
        try:
            cover = chapters_mod.book_meta(path).get("cover")
        except Exception:  # noqa: BLE001
            cover = None
        self.session.library.add_book(path, title=title, cover=cover)
        self.refresh()

    def _add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, T("library.add"), "", "EPUB (*.epub);;All files (*)")
        if path:
            self.add_book(path)

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self.session.remove_recent(item.data(Qt.ItemDataRole.UserRole))
        self.refresh()

    def _open_item(self, item: QListWidgetItem) -> None:
        self.openRequested.emit(item.data(Qt.ItemDataRole.UserRole))


class FiguresWidget(QWidget):
    """Figure gallery with a zoom/rotate viewer and EPUB write-back."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._figures = []
        self._current = -1
        self._zoom = 1.0
        self._rotation = 0
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_load = QPushButton(T("action.load_current"))
        self.btn_export_img = QPushButton(T("assets.export"))
        self.btn_save_back = QPushButton(T("assets.save_back"))
        self.btn_zoom_in = QPushButton(T("assets.zoom_in"))
        self.btn_zoom_out = QPushButton(T("assets.zoom_out"))
        self.btn_rotate = QPushButton(T("assets.rotate"))
        self.btn_reset = QPushButton(T("assets.reset"))
        for widget in (self.btn_load, self.btn_export_img, self.btn_save_back,
                       self.btn_zoom_out, self.btn_zoom_in, self.btn_rotate,
                       self.btn_reset):
            bar.addWidget(widget)
        layout.addLayout(bar)

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setIconSize(self.list.iconSize().__class__(96, 96))
        self.list.setMaximumWidth(240)
        self.list.currentRowChanged.connect(self._show_current)
        body.addWidget(self.list)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.view)
        body.addWidget(self.scroll, 1)
        layout.addLayout(body, 1)

        self.btn_load.clicked.connect(self.load_current)
        self.btn_export_img.clicked.connect(lambda: self._export("img"))
        self.btn_save_back.clicked.connect(self.save_back)
        self.btn_zoom_in.clicked.connect(lambda: self._set_zoom(self._zoom + 0.2))
        self.btn_zoom_out.clicked.connect(lambda: self._set_zoom(self._zoom - 0.2))
        self.btn_rotate.clicked.connect(lambda: self._set_rotation(self._rotation + 90))
        self.btn_reset.clicked.connect(self._reset_view)
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
                96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)) if not pixmap.isNull() else QIcon()
            label = f"Fig. {fig.number}" + (f" — {fig.caption[:40]}"
                                            if fig.caption else "")
            self.list.addItem(QListWidgetItem(icon, label))
        if self._figures:
            self.list.setCurrentRow(0)
        else:
            self.view.clear()

    # -- viewer -----------------------------------------------------------
    def _show_current(self, row: int) -> None:
        if not (0 <= row < len(self._figures)):
            return
        self._current = row
        self._reset_view(view_only=True)
        self._render()

    def _render(self) -> None:
        if not (0 <= self._current < len(self._figures)):
            return
        pixmap = QPixmap()
        pixmap.loadFromData(self._figures[self._current].data)
        if pixmap.isNull():
            self.view.clear()
            return
        if self._rotation:
            pixmap = pixmap.transformed(
                QTransform().rotate(self._rotation),
                Qt.TransformationMode.SmoothTransformation)
        scaled = pixmap.scaled(
            int(pixmap.width() * self._zoom), int(pixmap.height() * self._zoom),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.view.setPixmap(scaled)
        self.view.resize(scaled.size())

    def _set_zoom(self, value: float) -> None:
        self._zoom = max(0.2, min(5.0, value))
        self._render()

    def _set_rotation(self, value: int) -> None:
        self._rotation = value % 360
        self._render()

    def _reset_view(self, view_only: bool = False) -> None:
        self._zoom = 1.0
        self._rotation = 0
        if not view_only:
            self._render()

    # -- actions ----------------------------------------------------------
    def _export(self, fmt: str) -> None:
        if not self._figures:
            return
        directory = QFileDialog.getExistingDirectory(self, T("assets.export"))
        if directory:
            exporter.export_figures(self._figures, directory, fmt)

    def save_back(self) -> None:
        if not (self._source and 0 <= self._current < len(self._figures)):
            return
        fig = self._figures[self._current]
        target, _ = QFileDialog.getSaveFileName(
            self, T("assets.save_back"),
            os.path.splitext(self._source)[0] + "_edited.epub", "EPUB (*.epub)")
        if not target:
            return
        try:
            extract.replace_image(self._source, target, fig.name, fig.data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, T("assets.save_back"), str(exc))
            return
        QMessageBox.information(self, T("assets.save_back"),
                                T("msg.export_done").format(target))


class TablesWidget(QWidget):
    """Editable table view with EPUB write-back and export."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tables = []
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_load = QPushButton(T("action.load_current"))
        self.cmb = QComboBox()
        self.btn_save_back = QPushButton(T("assets.save_back"))
        self.btn_csv = QPushButton(T("format.csv"))
        self.btn_html = QPushButton(T("format.html"))
        self.btn_md = QPushButton(T("format.markdown"))
        bar.addWidget(self.btn_load)
        bar.addWidget(self.cmb, 1)
        for widget in (self.btn_save_back, self.btn_csv, self.btn_html, self.btn_md):
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
        self.btn_save_back.clicked.connect(self.save_back)

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
            label = f"Table {table.number}" + (
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

    def _edited_rows(self, index: int) -> list[list[str]]:
        rows = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                row.append(item.text() if item is not None else "")
            rows.append(row)
        return rows

    def _export(self, fmt: str) -> None:
        if not self._tables:
            return
        directory = QFileDialog.getExistingDirectory(self, T("assets.export"))
        if directory:
            exporter.export_tables(self._tables, directory, fmt)

    def save_back(self) -> None:
        index = self.cmb.currentIndex()
        if not (self._source and 0 <= index < len(self._tables)):
            return
        table = self._tables[index]
        target, _ = QFileDialog.getSaveFileName(
            self, T("assets.save_back"),
            os.path.splitext(self._source)[0] + "_edited.epub", "EPUB (*.epub)")
        if not target:
            return
        try:
            extract.apply_table_edits(
                self._source, target, [(table.file, table.order,
                                        self._edited_rows(index))])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, T("assets.save_back"), str(exc))
            return
        QMessageBox.information(self, T("assets.save_back"),
                                T("msg.export_done").format(target))


class TextsWidget(QWidget):
    """Editable list of text blocks with EPUB write-back and export."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._blocks = []
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_load = QPushButton(T("action.load_current"))
        self.btn_save = QPushButton(T("assets.save"))
        self.btn_save_back = QPushButton(T("assets.save_back"))
        self.btn_export = QPushButton(T("assets.export"))
        for widget in (self.btn_load, self.btn_save, self.btn_save_back,
                       self.btn_export):
            bar.addWidget(widget)
        layout.addLayout(bar)

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(280)
        self.list.currentRowChanged.connect(self._show_current)
        body.addWidget(self.list)
        self.editor = QPlainTextEdit()
        body.addWidget(self.editor, 1)
        layout.addLayout(body, 1)

        self._source = None
        self.btn_load.clicked.connect(self.load_current)
        self.btn_save.clicked.connect(self._save_current)
        self.btn_save_back.clicked.connect(self.save_back)
        self.btn_export.clicked.connect(self._export)

    def set_source(self, path: str) -> None:
        self._source = path

    def load_current(self) -> None:
        if self._source:
            self.load(self._source)

    def load(self, path: str, selected=None) -> None:
        self._source = path
        self._blocks = extract.extract_text_blocks(path, selected=selected)
        self.list.clear()
        for block in self._blocks:
            preview = block.text[:50] + ("…" if len(block.text) > 50 else "")
            self.list.addItem(QListWidgetItem(f"{block.file}:{block.order} — {preview}"))
        if self._blocks:
            self.list.setCurrentRow(0)
        else:
            self.editor.clear()

    def _show_current(self, row: int) -> None:
        if 0 <= row < len(self._blocks):
            self.editor.setPlainText(self._blocks[row].text)

    def _save_current(self) -> None:
        row = self.list.currentRow()
        if not (0 <= row < len(self._blocks)):
            return
        self._blocks[row].text = self.editor.toPlainText()
        item = self.list.item(row)
        preview = self._blocks[row].text[:50]
        item.setText(f"{self._blocks[row].file}:{self._blocks[row].order} — {preview}")

    def _edits(self) -> list[tuple[str, int, str]]:
        self._save_current()
        return [(b.file, b.order, b.text) for b in self._blocks]

    def save_back(self) -> None:
        if not (self._source and self._blocks):
            return
        target, _ = QFileDialog.getSaveFileName(
            self, T("assets.save_back"),
            os.path.splitext(self._source)[0] + "_edited.epub", "EPUB (*.epub)")
        if not target:
            return
        try:
            extract.apply_text_edits(self._source, target, self._edits())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, T("assets.save_back"), str(exc))
            return
        QMessageBox.information(self, T("assets.save_back"),
                                T("msg.export_done").format(target))

    def _export(self) -> None:
        if not self._source:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, T("assets.export"),
            os.path.splitext(self._source)[0] + "_text.txt", "Text (*.txt)")
        if not target:
            return
        exporter.export_text(self._source, target)


class ChaptersWidget(QWidget):
    """Chapter library: extracted/translated chapters with a source viewer.

    Chapters are **selectable** (checkboxes); the selection can be translated or
    exported from here.
    """

    translateRequested = pyqtSignal(list)  # list[int] chapter indices
    exportRequested = pyqtSignal(list)

    def __init__(self, store=None, parent=None) -> None:
        super().__init__(parent)
        from ..chapter_store import ChapterStore
        self.store = store or ChapterStore()
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_load = QPushButton(T("chapters.load"))
        self.btn_translate = QPushButton(T("action.translate_selected"))
        self.btn_export = QPushButton(T("action.export_selected"))
        self.edt_filter = QLineEdit()
        self.edt_filter.setPlaceholderText(T("library.filter"))
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_translate)
        bar.addWidget(self.btn_export)
        bar.addWidget(self.edt_filter, 1)
        layout.addLayout(bar)

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(360)
        self.list.currentRowChanged.connect(self._show_current)
        body.addWidget(self.list)
        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        body.addWidget(self.viewer, 1)
        layout.addLayout(body, 1)

        self._rows: list[dict] = []
        self._source = None
        self.btn_load.clicked.connect(self.load_current)
        self.btn_translate.clicked.connect(
            lambda: self.translateRequested.emit(self.selected_chapters()))
        self.btn_export.clicked.connect(
            lambda: self.exportRequested.emit(self.selected_chapters()))
        self.edt_filter.textChanged.connect(self.refresh)

    def set_source(self, path: str) -> None:
        self._source = path

    def load_current(self) -> None:
        if self._source:
            try:
                self.store.sync_from_epub(self._source)
            except Exception:  # noqa: BLE001 - best effort
                pass
        self.refresh()

    def refresh(self) -> None:
        needle = self.edt_filter.text().strip().lower()
        self.list.clear()
        self._rows = []
        if self._source:
            rows = self.store.for_book(self._source)
        elif needle:
            rows = self.store.search(needle)
        else:
            rows = []
        for row in rows:
            label = f"[{row.get('status', '')}] {row.get('name') or row.get('chapter_index')}"
            if needle and needle not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
            self._rows.append(row)
        if self._rows:
            self.list.setCurrentRow(0)
        else:
            self.viewer.clear()

    def selected_chapters(self) -> list[int]:
        """Return the ``chapter_index`` of every checked chapter."""
        result: list[int] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.CheckState.Checked and i < len(self._rows):
                index = self._rows[i].get("chapter_index")
                if index is not None:
                    result.append(int(index))
        return result

    def _show_current(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        text = row.get("translation") or row.get("source_text") or ""
        self.viewer.setPlainText(text)


class PreviewWidget(QWidget):
    """Preview a few translated segments without writing any file."""

    def __init__(self, settings_provider, parent=None) -> None:
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._source = None
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_run = QPushButton(T("tab.preview"))
        self.spn_limit = QSpinBox()
        self.spn_limit.setRange(1, 200)
        self.spn_limit.setValue(10)
        self.edt_chapters = QLineEdit()
        self.edt_chapters.setPlaceholderText(T("label.chapters_filter"))
        bar.addWidget(self.btn_run)
        bar.addWidget(QLabel(T("label.segments") + ":"))
        bar.addWidget(self.spn_limit)
        bar.addWidget(self.edt_chapters, 1)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Original", "Translation"])
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
            self.log.setPlainText("No book selected.")
            return
        options = self._settings_provider() or {}
        self.log.setPlainText("Preview translation…")
        try:
            pairs = book.preview_translation(
                self._source, engine=options.get("engine"),
                source_lang=options.get("source", "English"),
                target_lang=options.get("target", "Italian"),
                chapters=self.edt_chapters.text().strip() or None,
                limit=self.spn_limit.value(),
                settings=options.get("settings"))
        except Exception as exc:  # noqa: BLE001
            self.log.setPlainText(f"Error: {exc}")
            return
        self.table.setRowCount(len(pairs))
        for row, (original, translation) in enumerate(pairs):
            self.table.setItem(row, 0, QTableWidgetItem(original))
            self.table.setItem(row, 1, QTableWidgetItem(translation))
        self.log.setPlainText(f"{len(pairs)} preview segments.")
