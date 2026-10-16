"""Band 2 of the Translate view: per-chapter progress.

Two presentations on the same :class:`~noesis_ebook_translator.progress_model.ProgressModel`:

* ``list``  — one row per XHTML document (name, ``done/total``, mini bar, state
  icon), used when there are several units;
* ``detail`` — a single card (title, big count, bar, last translated segment),
  used when translating one or two chapters, where a list would be almost empty.

The list repaints **only the rows that changed** and pulses at ~2 Hz, so a
200-row book costs nothing per frame.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QStackedWidget,
    QStyledItemDelegate, QVBoxLayout, QWidget)

from .. import theme as theme_mod
from ..i18n import T
from ..progress_model import (
    STATE_DONE, STATE_ERROR, STATE_RUNNING, STATE_SKIPPED, ProgressModel)
from .animations import ShimmerBar
from .icons import icon

__all__ = ["ChapterTrackWidget"]

ROW_HEIGHT = 30
_PULSE_MS = 480


class _UnitDelegate(QStyledItemDelegate):
    """Paint a chapter row: marker, name, ``done/total`` and a mini bar."""

    def __init__(self, track: "ChapterTrackWidget") -> None:
        super().__init__(track)
        self._track = track

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt naming
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        data = index.data(Qt.ItemDataRole.UserRole) or {}
        rect = option.rect
        colors = self._track.colors()
        state = data.get("state")
        total = int(data.get("total") or 0)
        done = int(data.get("done") or 0)
        depth = int(data.get("depth") or 0)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        left = rect.left() + 6 + depth * 12
        marker = QRect(left, rect.top() + (ROW_HEIGHT - 14) // 2, 14, 14)
        accent = colors["accent"]
        if state == STATE_DONE:
            check = icon("check")
            if not check.isNull():
                check.paint(painter, marker)
            else:  # pragma: no cover - icon always shipped
                painter.setBrush(colors["done"])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(marker.adjusted(3, 3, -3, -3))
        elif state == STATE_ERROR:
            cancel = icon("cancel")
            if not cancel.isNull():
                cancel.paint(painter, marker)
            else:  # pragma: no cover
                painter.setBrush(colors["error"])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(marker.adjusted(3, 3, -3, -3))
        elif state == STATE_RUNNING:
            color = QColor(accent)
            color.setAlpha(self._track.pulse_alpha())
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(marker.adjusted(3, 3, -3, -3))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(colors["muted"])
            painter.drawEllipse(marker.adjusted(3, 3, -3, -3))

        font = QFont(option.font)
        if state == STATE_RUNNING:
            font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        count = f"{done}/{total}" if total else "—"
        count_width = metrics.horizontalAdvance(count) + 8
        text_left = marker.right() + 7
        text_width = max(10, rect.right() - count_width - text_left - 6)

        if state == STATE_RUNNING:
            name_color = QColor(accent)
        elif state in (STATE_PENDING, STATE_SKIPPED):
            name_color = colors["muted"]
        else:
            name_color = colors["text"]
        painter.setPen(name_color)
        name = metrics.elidedText(str(data.get("name") or ""),
                                  Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRect(text_left, rect.top(), text_width, ROW_HEIGHT),
                         int(Qt.AlignmentFlag.AlignVCenter), name)

        painter.setPen(colors["muted"])
        painter.drawText(QRect(rect.right() - count_width - 6, rect.top(),
                               count_width, ROW_HEIGHT),
                         int(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter), count)

        if state == STATE_RUNNING and total > 0:
            bar = QRect(rect.left() + 6 + depth * 12, rect.bottom() - 2,
                        max(10, rect.width() - 12), 2)
            painter.fillRect(bar, colors["track"])
            filled = QRect(bar.left(), bar.top(),
                           int(bar.width() * min(1.0, done / total)), 2)
            painter.fillRect(filled, accent)
        painter.restore()


class ChapterTrackWidget(QWidget):
    """Band 2: chapter list (``list``) or single-chapter card (``detail``)."""

    def __init__(self, parent=None, reduce_motion: bool = False) -> None:
        super().__init__(parent)
        self._model: ProgressModel | None = None
        self._reduce_motion = bool(reduce_motion)
        self._mode = "list"
        self._phase = 0
        self._files: list[str] = []
        self._snapshot: dict[str, tuple[int, str]] = {}
        self._last_running: list[str] = []
        self._colors = self._theme_colors("light", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.lbl_title = QLabel(T("tab.chapters"))
        self.lbl_title.setObjectName("bandTitle")
        header.addWidget(self.lbl_title)
        #: Name of the unit being translated (also mirrored in "detail" mode).
        self.lbl_subtitle = QLabel("—")
        self.lbl_subtitle.setObjectName("bandHint")
        header.addWidget(self.lbl_subtitle, 1)
        layout.addLayout(header)
        #: Progress bar of the unit being translated.
        self.bar_current = ShimmerBar(reduce_motion=self._reduce_motion)
        layout.addWidget(self.bar_current)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        # page 0: list
        page_list = QWidget()
        list_layout = QVBoxLayout(page_list)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setUniformItemSizes(True)
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setItemDelegate(_UnitDelegate(self))
        list_layout.addWidget(self._list)
        self._stack.addWidget(page_list)

        # page 1: detail
        page_detail = QWidget()
        detail_layout = QVBoxLayout(page_detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_detail_title = QLabel("—")
        self.lbl_detail_title.setObjectName("detailTitle")
        self.lbl_detail_title.setWordWrap(True)
        detail_layout.addWidget(self.lbl_detail_title)
        self.lbl_detail_count = QLabel("—")
        self.lbl_detail_count.setObjectName("detailCount")
        detail_layout.addWidget(self.lbl_detail_count)
        self.bar_detail = ShimmerBar(reduce_motion=self._reduce_motion)
        detail_layout.addWidget(self.bar_detail)
        detail_layout.addSpacing(6)
        self.lbl_last_caption = QLabel(T("translate.last_segment"))
        self.lbl_last_caption.setObjectName("bandTitle")
        detail_layout.addWidget(self.lbl_last_caption)
        self.lbl_last_text = QLabel("")
        self.lbl_last_text.setObjectName("detailText")
        self.lbl_last_text.setWordWrap(True)
        detail_layout.addWidget(self.lbl_last_text)
        self.lbl_cached = QLabel("")
        self.lbl_cached.setObjectName("detailText")
        detail_layout.addWidget(self.lbl_cached)
        detail_layout.addStretch(1)
        self._stack.addWidget(page_detail)

        self._timer = QTimer(self)
        self._timer.setInterval(_PULSE_MS)
        self._timer.timeout.connect(self._tick)

    # -- API --------------------------------------------------------------
    def set_model(self, model: ProgressModel | None) -> None:
        self._model = model
        self._files = []
        self._snapshot.clear()
        self._last_running = []
        self._list.clear()
        self.set_mode("detail" if model and len(model.units) <= 2 else "list")
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = "detail" if mode == "detail" else "list"
        self._stack.setCurrentIndex(1 if self._mode == "detail" else 0)

    def mode(self) -> str:
        return self._mode

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        self.bar_detail.set_reduce_motion(self._reduce_motion)
        self._update_timer()

    def set_theme(self, mode: str, system_dark: bool = True) -> None:
        self._colors = self._theme_colors(mode, system_dark)
        self._list.viewport().update()

    def colors(self) -> dict:
        return self._colors

    def pulse_alpha(self) -> int:
        """Alpha of the running marker: a soft 2 Hz pulse (or steady)."""
        if self._reduce_motion:
            return 255
        return 150 if self._phase else 255

    def is_animating(self) -> bool:
        return self._timer.isActive()

    # -- refresh ----------------------------------------------------------
    def refresh(self) -> None:
        model = self._model
        if model is None:
            return
        files = [unit.file for unit in model.units]
        if files != self._files:
            self._rebuild()
        self.set_mode("detail" if len(model.units) <= 2 else "list")
        self._update_rows()
        self._update_detail(model)
        self._update_header(model)
        self._update_timer()

    def _current_file(self, model: ProgressModel) -> str | None:
        running = model.running_units()
        if running:
            return running[0]
        pending = [u.file for u in model.units
                   if model.state(u.file) not in (STATE_SKIPPED, STATE_DONE)]
        if pending:
            return pending[0]
        return model.units[-1].file if model.units else None

    def _update_header(self, model: ProgressModel) -> None:
        current = self._current_file(model)
        if current is None:
            self.lbl_subtitle.setText("—")
            self.bar_current.setValue(0)
            return
        unit = next((u for u in model.units if u.file == current), None)
        self.lbl_subtitle.setText(unit.label() if unit else current)
        done, total = model.progress(current)
        self.bar_current.setValue(int(done / total * 100) if total else 0)
        self.bar_current.set_busy(model.state(current) == STATE_RUNNING)

    def _rebuild(self) -> None:
        model = self._model
        assert model is not None
        self._list.clear()
        self._snapshot.clear()
        self._files = []
        for unit in model.units:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole,
                         {"name": unit.label(), "depth": unit.depth,
                          "done": 0, "total": 0, "state": ""})
            self._list.addItem(item)
            self._files.append(unit.file)

    def _update_rows(self) -> None:
        model = self._model
        assert model is not None
        running = model.running_units()
        scroll_to: QListWidgetItem | None = None
        for index, unit in enumerate(model.units):
            item = self._list.item(index)
            if item is None:  # pragma: no cover - defensive
                continue
            done, total = model.progress(unit.file)
            state = model.state(unit.file)
            key = (done, state)
            data = {"name": unit.label(), "depth": unit.depth,
                    "done": done, "total": total, "state": state}
            item.setData(Qt.ItemDataRole.UserRole, data)
            if self._snapshot.get(unit.file) != key:
                self._snapshot[unit.file] = key
                self._list.viewport().update(self._list.visualItemRect(item))
            if running and unit.file == running[0] and scroll_to is None:
                scroll_to = item
        if scroll_to is not None and running != self._last_running:
            self._list.scrollToItem(scroll_to,
                                    QListWidget.ScrollHint.PositionAtCenter)
        self._last_running = list(running)

    def _update_detail(self, model: ProgressModel) -> None:
        current = self._current_file(model)
        if current is None:  # pragma: no cover - empty book
            self.lbl_detail_title.setText("—")
            return
        unit = next((u for u in model.units if u.file == current), None)
        title = unit.label() if unit else current
        if len(model.units) > 1:
            index = [u.file for u in model.units].index(current) + 1
            title = f"{title}  ({index}/{len(model.units)})"
        self.lbl_detail_title.setText(title)
        done, total = model.progress(current)
        self.lbl_detail_count.setText(f"{done}/{total}"
                                      if total else "—")
        self.bar_detail.setValue(int(done / total * 100) if total else 0)
        self.bar_detail.set_busy(model.state(current) == STATE_RUNNING)
        if model.last:
            self.lbl_last_text.setText(model.last[1])
        self.lbl_cached.setText(f"{T('translate.cached')}: {model.cached}"
                                if model.cached else "")

    def _update_timer(self) -> None:
        model = self._model
        active = bool(model and model.running_units()
                      and not self._reduce_motion)
        if self._mode == "list":
            active = active and self.isVisible()
        if active and not self._timer.isActive():
            self._timer.start()
        elif not active and self._timer.isActive():
            self._timer.stop()
            self._phase = 0

    def _tick(self) -> None:
        self._phase = 0 if self._phase else 1
        model = self._model
        if model is None:  # pragma: no cover - defensive
            return
        for file_name in model.running_units():
            try:
                row = self._files.index(file_name)
            except ValueError:  # pragma: no cover - defensive
                continue
            item = self._list.item(row)
            if item is not None:
                self._list.viewport().update(self._list.visualItemRect(item))

    @staticmethod
    def _theme_colors(mode: str, system_dark: bool) -> dict:
        palette = theme_mod.palette(mode, system_dark)
        dark = theme_mod.is_dark(mode, system_dark)
        accent = theme_mod.liquid(mode, system_dark)["accent"]
        return {
            "text": QColor(palette["foreground"]),
            "muted": QColor("#8b95a3" if dark else "#6b7684"),
            "accent": QColor(accent),
            "track": QColor("#3a3f47" if dark else "#d9dde4"),
            "done": QColor("#37b24d" if not dark else "#51cf66"),
            "error": QColor("#e03131" if not dark else "#ff6b6b"),
        }
