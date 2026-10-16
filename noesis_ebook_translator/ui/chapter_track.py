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
    QButtonGroup, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QStackedWidget, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from .. import theme as theme_mod
from ..i18n import T
from ..progress_model import (
    STATE_DONE, STATE_ERROR, STATE_EXCLUDED, STATE_PENDING, STATE_RUNNING,
    STATE_SKIPPED, ProgressModel)
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
        if state == STATE_DONE:
            # A translated chapter stays bold with its check mark.
            font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        count = f"{done}/{total}" if total else "—"
        exported = bool(data.get("exported"))
        badge = 0
        if exported:
            badge = 18
        count_width = metrics.horizontalAdvance(count) + 8
        text_left = marker.right() + 7
        text_width = max(10, rect.right() - count_width - badge - text_left - 6)

        if state == STATE_RUNNING:
            # Blink the whole row (name + marker) while it is being translated.
            alpha = self._track.pulse_alpha()
            name_color = QColor(accent)
            name_color.setAlpha(alpha)
        elif state == STATE_EXCLUDED:
            name_color = colors["excluded"]      # dimmed: outside the selection
        elif state == STATE_SKIPPED:
            name_color = colors["muted"]
        else:
            # Chosen chapters (pending or done) are in normal colour; only the
            # excluded ones stay grey.
            name_color = colors["text"]
        painter.setPen(name_color)
        name = metrics.elidedText(str(data.get("name") or ""),
                                  Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRect(text_left, rect.top(), text_width, ROW_HEIGHT),
                         int(Qt.AlignmentFlag.AlignVCenter), name)

        painter.setPen(colors["muted"])
        painter.drawText(QRect(rect.right() - count_width - badge - 6, rect.top(),
                               count_width, ROW_HEIGHT),
                         int(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter), count)

        if exported:
            export_icon = icon("export")
            box = QRect(rect.right() - 18, rect.top() + (ROW_HEIGHT - 13) // 2,
                        13, 13)
            if not export_icon.isNull():
                export_icon.paint(painter, box)
            else:  # pragma: no cover - icon always shipped
                painter.setBrush(colors["done"])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(box.adjusted(4, 4, -4, -4))

        if total > 0 and state not in (STATE_SKIPPED, STATE_EXCLUDED):
            # A bar on every chapter, not only the running one: chapters served
            # from the cache (or already finished) show a full bar + check.
            bar = QRect(rect.left() + 6 + depth * 12, rect.bottom() - 2,
                        max(10, rect.width() - 12), 2)
            painter.fillRect(bar, colors["track"])
            if done > 0:
                fraction = min(1.0, done / total)
                if state == STATE_RUNNING:
                    fill = QColor(accent)
                elif state == STATE_ERROR:
                    fill = colors["error"]
                else:
                    fill = colors["done"]
                painter.fillRect(QRect(bar.left(), bar.top(),
                                       int(bar.width() * fraction),
                                       bar.height()), fill)
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
        #: Filter of the list: the whole book, what is still to do, or what is
        #: already translated (the running chapter always stays visible).
        self._filter = "all"
        self.toolbar = QHBoxLayout()
        self.toolbar.setContentsMargins(0, 2, 0, 0)
        self.toolbar.setSpacing(2)
        self._filter_buttons: dict[str, QToolButton] = {}
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for key, widget_key in (("all", "track.all"),
                                ("todo", "track.to_translate"),
                                ("done", "view.translated")):
            button = QToolButton()
            button.setObjectName("trackFilter")
            button.setText(T(widget_key))
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(lambda _=False, name=key: self.set_filter(name))
            self._filter_group.addButton(button)
            self._filter_buttons[key] = button
            self.toolbar.addWidget(button)
        self.toolbar.addStretch(1)
        self._filter_buttons["all"].setChecked(True)
        layout.addLayout(self.toolbar)
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
        self.lbl_empty = QLabel(T("track.empty"))
        self.lbl_empty.setObjectName("bandHint")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.hide()
        list_layout.addWidget(self.lbl_empty)
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
        # The card is only for tiny books (no list to filter); a chapter
        # selection inside a normal book keeps the list + the filter toolbar.
        self.set_mode("detail" if model and len(model.units) <= 2 else "list")
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = "detail" if mode == "detail" else "list"
        self._stack.setCurrentIndex(1 if self._mode == "detail" else 0)
        # No list, nothing to filter.
        self._set_toolbar_visible(self._mode == "list")

    def _set_toolbar_visible(self, visible: bool) -> None:
        for button in self._filter_buttons.values():
            button.setVisible(visible)

    def set_filter(self, name: str) -> None:
        """Show every chapter, only the pending ones, or only the done ones."""
        if name not in ("all", "todo", "done"):
            name = "all"
        self._filter = name
        button = self._filter_buttons.get(name)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._files = []          # force a rebuild of the visible rows
        self.refresh()

    def filter_name(self) -> str:
        return self._filter

    def visible_units(self) -> list[ChapterUnit]:
        model = self._model
        if model is None:
            return []
        return self._filtered(model)

    def _filtered(self, model: ProgressModel) -> list[ChapterUnit]:
        if self._filter == "todo":
            # Still to do: pending + running + failed (excluded chapters and
            # already translated ones drop out as the run progresses).
            return [u for u in model.units
                    if model.state(u.file) in (STATE_PENDING, STATE_RUNNING,
                                               STATE_ERROR)]
        if self._filter == "done":
            return [u for u in model.units if model.state(u.file) == STATE_DONE]
        return list(model.units)

    def mode(self) -> str:
        return self._mode

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        self.bar_detail.set_reduce_motion(self._reduce_motion)
        self._update_timer()

    def set_theme(self, mode: str, system_dark: bool = True) -> None:
        self._colors = self._theme_colors(mode, system_dark)
        track = "#3a3f47" if theme_mod.is_dark(mode, system_dark) else "#d9dde4"
        fill = theme_mod.palette(mode, system_dark)["accent"]
        self.bar_current.set_colors(track, fill)
        self.bar_detail.set_colors(track, fill)
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
        units = self._filtered(model)
        files = [unit.file for unit in units]
        if files != self._files:
            self._rebuild(units)
        self.set_mode("detail" if len(model.units) <= 2 else "list")
        self._update_rows(units)
        self._update_empty(units)
        self._update_detail(model)
        self._update_header(model)
        self._update_timer()

    def _update_empty(self, units: list[ChapterUnit]) -> None:
        empty = self._mode == "list" and not units
        self.lbl_empty.setVisible(empty)
        self._list.setVisible(not empty)

    def _current_file(self, model: ProgressModel) -> str | None:
        running = model.running_units()
        if running:
            return running[0]
        pending = [u.file for u in model.units
                   if model.state(u.file)
                   not in (STATE_SKIPPED, STATE_DONE, STATE_EXCLUDED)]
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

    def _rebuild(self, units: list[ChapterUnit]) -> None:
        self._list.clear()
        self._snapshot.clear()
        self._files = []
        for unit in units:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole,
                         {"name": unit.label(), "depth": unit.depth,
                          "done": 0, "total": 0, "state": "",
                          "exported": False})
            self._list.addItem(item)
            self._files.append(unit.file)

    def _update_rows(self, units: list[ChapterUnit]) -> None:
        model = self._model
        assert model is not None
        running = model.running_units()
        scroll_to: QListWidgetItem | None = None
        for index, unit in enumerate(units):
            item = self._list.item(index)
            if item is None:  # pragma: no cover - defensive
                continue
            done, total = model.progress(unit.file)
            state = model.state(unit.file)
            key = (done, state, model.exported)
            data = {"name": unit.label(), "depth": unit.depth,
                    "done": done, "total": total, "state": state,
                    "exported": model.exported}
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
        chosen = [u.file for u in model.units
                  if model.state(u.file) != STATE_EXCLUDED]
        if len(chosen) > 1 and current in chosen:
            title = f"{title}  ({chosen.index(current) + 1}/{len(chosen)})"
        self.lbl_detail_title.setText(title)
        done, total = model.progress(current)
        self.lbl_detail_count.setText(f"{done}/{total}"
                                      if total else "—")
        self.bar_detail.setValue(int(done / total * 100) if total else 0)
        self.bar_detail.set_busy(model.state(current) == STATE_RUNNING)
        if model.last:
            self.lbl_last_text.setText(model.last[1])
        bits = []
        if model.cached:
            bits.append(f"{T('translate.cached')}: {model.cached}")
        if model.exported:
            bits.append(T("translate.exported"))
        self.lbl_cached.setText(" · ".join(bits))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Re-evaluate the pulse when the band becomes visible.

        The pulse is skipped while hidden (nothing to animate), so becoming
        visible has to restart it: otherwise it would only come back on the next
        progress update.
        """
        super().showEvent(event)
        self._update_timer()

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
            # "Greyed out": low contrast against the background in both themes.
            "excluded": QColor("#59626d" if dark else "#b4bbc5"),
            "accent": QColor(accent),
            "track": QColor("#3a3f47" if dark else "#d9dde4"),
            "done": QColor("#37b24d" if not dark else "#51cf66"),
            "error": QColor("#e03131" if not dark else "#ff6b6b"),
        }
