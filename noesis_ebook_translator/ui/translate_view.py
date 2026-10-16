"""The Translate viewport: four vertical bands, left to right.

1. **Choices** — read-only recap of what the wizard collected.
2. **Chapters** — :class:`~noesis_ebook_translator.ui.chapter_track.ChapterTrackWidget`.
3. **Cover + liquid** — :class:`~noesis_ebook_translator.ui.water_glass.WaterGlass`.
4. **Log** — the engine log plus the status line (collapsible).

The bands live in a ``QSplitter``; when the window gets narrow the splitter flips
to a vertical orientation so the four bands stay readable.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QSplitter,
    QToolButton, QVBoxLayout, QWidget)

from .. import theme as theme_mod
from ..i18n import T
from ..progress_model import ProgressModel
from .animations import DotsLabel, ShimmerBar
from .chapter_track import ChapterTrackWidget
from .water_glass import WaterGlass

__all__ = ["TranslateView", "ChoicesPanel"]

#: Default proportions of the four bands.
BAND_SIZES = (22, 28, 18, 32)
#: Below this width the splitter stacks the bands vertically.
STACK_BELOW = 980


class ChoicesPanel(QWidget):
    """Band 1: the wizard choices as a read-only two-column recap."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, str]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)
        self.lbl_title = QLabel(T("translate.choices"))
        self.lbl_title.setObjectName("bandTitle")
        outer.addWidget(self.lbl_title)
        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setSpacing(4)
        self._form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        outer.addWidget(self._form_host)
        outer.addStretch(1)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        rows = list(rows or [])
        if rows == self._rows:
            return
        self._rows = rows
        while self._form.rowCount():
            self._form.removeRow(0)
        for label, value in rows:
            name = QLabel(label)
            name.setObjectName("bandHint")
            text = QLabel(value or "—")
            text.setWordWrap(True)
            self._form.addRow(name, text)

    def rows(self) -> list[tuple[str, str]]:
        return list(self._rows)


class TranslateView(QWidget):
    """The four-band Translate viewport (owns the log/status/progress widgets)."""

    logToggled = pyqtSignal(bool)
    layoutChanged = pyqtSignal()

    def __init__(self, parent=None, reduce_motion: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("translateView")
        self._reduce_motion = bool(reduce_motion)
        self._model: ProgressModel | None = None
        self._selection = False
        self._log_visible = True
        self._stacked = False

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.splitterMoved.connect(lambda *_: self.layoutChanged.emit())

        # --- band 1 -----------------------------------------------------
        self.choices = ChoicesPanel()
        # --- band 2 -----------------------------------------------------
        self.track = ChapterTrackWidget(reduce_motion=self._reduce_motion)
        # --- band 3 -----------------------------------------------------
        self.glass = WaterGlass(reduce_motion=self._reduce_motion)
        glass_box = QWidget()
        glass_layout = QVBoxLayout(glass_box)
        glass_layout.setContentsMargins(6, 6, 6, 6)
        glass_layout.setSpacing(4)
        self.lbl_glass_title = QLabel(T("label.book"))
        self.lbl_glass_title.setObjectName("bandTitle")
        glass_layout.addWidget(self.lbl_glass_title)
        glass_layout.addWidget(self.glass, 1)
        percent_row = QHBoxLayout()
        self.book_label = QLabel("0%")
        self.book_label.setObjectName("detailCount")
        percent_row.addWidget(self.book_label)
        self.progress = ShimmerBar(reduce_motion=self._reduce_motion)
        percent_row.addWidget(self.progress, 1)
        glass_layout.addLayout(percent_row)
        glass_box.setMinimumWidth(120)
        # --- band 4 -----------------------------------------------------
        log_box = QWidget()
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(6, 6, 6, 6)
        log_layout.setSpacing(4)
        log_header = QHBoxLayout()
        self.lbl_log_title = QLabel(T("translate.log"))
        self.lbl_log_title.setObjectName("bandTitle")
        log_header.addWidget(self.lbl_log_title)
        log_header.addStretch(1)
        self.btn_log = QToolButton()
        self.btn_log.setAutoRaise(True)
        self.btn_log.setToolTip(T("translate.log"))
        self.btn_log.setText("▸")
        self.btn_log.clicked.connect(self.toggle_log)
        log_header.addWidget(self.btn_log)
        log_layout.addLayout(log_header)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        # The engine logs ~5 lines per segment; cap the document so a very large
        # book cannot grow the widget without bound (the tail is what matters).
        self.log.setMaximumBlockCount(50000)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Expanding)
        log_layout.addWidget(self.log, 1)
        self.status = DotsLabel(T("status.ready"),
                                reduce_motion=self._reduce_motion)
        log_layout.addWidget(self.status)

        for band in (self.choices, self.track, glass_box, log_box):
            self.splitter.addWidget(band)
        self._log_box = log_box

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.splitter, 1)
        self._apply_sizes(list(BAND_SIZES))
        self.set_theme("light", False)

    # -- wiring -----------------------------------------------------------
    def set_model(self, model: ProgressModel | None, *,
                  selection: bool = False) -> None:
        self._model = model
        self._selection = bool(selection)
        self.track.set_model(model)
        self.lbl_glass_title.setText(
            T("translate.selection") if selection else T("label.book"))
        self.refresh()

    def model(self) -> ProgressModel | None:
        return self._model

    def set_choices(self, rows: list[tuple[str, str]]) -> None:
        self.choices.set_rows(rows)

    def set_theme(self, mode: str, system_dark: bool = True) -> None:
        self.track.set_theme(mode, system_dark)
        self.glass.set_colors(theme_mod.liquid(mode, system_dark))
        self.glass.update()
        dark = theme_mod.is_dark(mode, system_dark)
        palette = theme_mod.palette(mode, system_dark)
        self.progress.set_colors("#3a3f47" if dark else "#d9dde4",
                                 palette["accent"])

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        self.track.set_reduce_motion(self._reduce_motion)
        self.glass.set_reduce_motion(self._reduce_motion)
        self.progress.set_reduce_motion(self._reduce_motion)
        self.status.set_reduce_motion(self._reduce_motion)

    # -- state ------------------------------------------------------------
    def refresh(self) -> None:
        """Repaint every band from the current model."""
        model = self._model
        self.track.refresh()
        if model is None:
            return
        percent = model.overall_percent()
        self.glass.set_level(percent)
        done, total = model.overall()
        parts = [f"{done}/{total} {T('label.segments').lower()}"] if total else []
        if model.cached:
            parts.append(f"{T('translate.cached')}: {model.cached}")
        self.glass.set_caption("\n".join(parts))

    def set_finished(self, ok: bool = True, exported: bool = False) -> None:
        if self._model is None:
            return
        self._model.finish(ok=ok)
        if exported:
            self._model.mark_exported()
        self.refresh()
        self.glass.set_level(self._model.overall_percent())

    def state(self) -> dict:
        return {"sizes": list(self.splitter.sizes()),
                "log_visible": self._log_visible}

    def restore_state(self, state: dict | None) -> None:
        state = state or {}
        sizes = state.get("sizes") or list(BAND_SIZES)
        self.set_log_visible(bool(state.get("log_visible", True)), emit=False)
        self._apply_sizes(sizes)

    # -- log collapsing ---------------------------------------------------
    def log_visible(self) -> bool:
        return self._log_visible

    def toggle_log(self) -> None:
        self.set_log_visible(not self._log_visible)

    def set_log_visible(self, visible: bool, emit: bool = True) -> None:
        self._log_visible = bool(visible)
        self.log.setVisible(self._log_visible)
        self.status.setVisible(self._log_visible)
        self.btn_log.setText("▸" if self._log_visible else "◂")
        if emit:
            self.layoutChanged.emit()
            self.logToggled.emit(self._log_visible)

    # -- responsive layout ------------------------------------------------
    def _apply_sizes(self, sizes) -> None:
        sizes = [max(1, int(s)) for s in (sizes or BAND_SIZES)]
        if len(sizes) != self.splitter.count():
            sizes = list(BAND_SIZES)
        if not self._log_visible:
            sizes[-1] = 1
        self.splitter.setSizes(sizes)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        stacked = self.width() < STACK_BELOW
        if stacked != self._stacked:
            self._stacked = stacked
            self.splitter.setOrientation(Qt.Orientation.Vertical if stacked
                                         else Qt.Orientation.Horizontal)
            self._apply_sizes(list(BAND_SIZES))
