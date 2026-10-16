"""Band 2 of the Translate view: the chapter list, one row per **TOC entry**.

The rows follow the TOC (reading) order and keep the hierarchy (indentation by
depth); headings with no document of their own are shown as plain entries. The
progress itself is per XHTML document -- that is what the engine reports -- so two
entries that share a file show the same numbers.

The list repaints **only the rows that changed** and pulses at ~2 Hz, so a
200-row book costs nothing per frame.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from .. import theme as theme_mod
from ..i18n import T
from ..progress_model import (
    STATE_DONE, STATE_ERROR, STATE_EXCLUDED, STATE_HEADER, STATE_PENDING,
    STATE_RUNNING, STATE_SKIPPED, ProgressModel)
from .animations import ShimmerBar
from .icons import icon

__all__ = ["ChapterTrackWidget"]

ROW_HEIGHT = 34
#: The name/count band, and the bar just under it. Keeping both *inside* the row
#: (instead of painting on its last two pixels) means a row that is only partly
#: visible still shows its bar, not just its text.
NAME_HEIGHT = 22
BAR_TOP = 23
BAR_HEIGHT = 5
INDENT = 14
_PULSE_MS = 480


class _UnitDelegate(QStyledItemDelegate):
    """Paint a chapter row: marker, name, ``done/total`` and a mini bar."""

    def __init__(self, track: "ChapterTrackWidget") -> None:
        super().__init__(track)
        self._track = track

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt naming
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        # The payload is built *here*, for the rows Qt is actually painting: a
        # 7500-entry book costs a handful of dictionary builds per frame instead
        # of one per row per refresh.
        data = self._track.row_data(index.row())
        if not data:
            return
        rect = option.rect
        colors = self._track.colors()
        state = data.get("state")
        total = int(data.get("total") or 0)
        done = int(data.get("done") or 0)
        depth = int(data.get("depth") or 0)
        header = state == STATE_HEADER
        has_bar = total > 0 and state not in (STATE_SKIPPED, STATE_EXCLUDED,
                                              STATE_HEADER)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        left = rect.left() + 6 + depth * INDENT
        marker = QRect(left, rect.top() + (NAME_HEIGHT - 14) // 2, 14, 14)
        accent = colors["accent"]
        if header:
            pass                                # a heading has no marker
        elif state == STATE_DONE:
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
            painter.setPen(colors["muted"]
                           if state in (STATE_SKIPPED, STATE_EXCLUDED)
                           else colors["text"])
            painter.drawEllipse(marker.adjusted(3, 3, -3, -3))

        font = QFont(option.font)
        if state == STATE_DONE:
            # A translated chapter stays bold with its check mark.
            font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        count = f"{done}/{total}" if (total and state not in (
            STATE_EXCLUDED, STATE_SKIPPED)) else "—"
        exported = bool(data.get("exported"))
        badge = 18 if exported else 0
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
            # Headings, chosen chapters (pending or done) and headings are in the
            # normal colour; only the excluded ones stay grey.
            name_color = colors["text"]
        painter.setPen(name_color)
        name = metrics.elidedText(str(data.get("name") or ""),
                                  Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRect(text_left, rect.top(), text_width, NAME_HEIGHT),
                         int(Qt.AlignmentFlag.AlignVCenter), name)

        painter.setPen(colors["muted"])
        painter.drawText(QRect(rect.right() - count_width - badge - 6, rect.top(),
                               count_width, NAME_HEIGHT),
                         int(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter), count)

        if exported:
            export_icon = icon("export")
            box = QRect(rect.right() - 18, rect.top() + (NAME_HEIGHT - 13) // 2,
                        13, 13)
            if not export_icon.isNull():
                export_icon.paint(painter, box)
            else:  # pragma: no cover - icon always shipped
                painter.setBrush(colors["done"])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(box.adjusted(4, 4, -4, -4))

        if has_bar:
            # A bar on every chapter, not only the running one: chapters served
            # from the cache (or already finished) show a full bar + check.
            bar = QRect(left, rect.top() + BAR_TOP,
                        max(10, rect.right() - left - 6), BAR_HEIGHT)
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
    """Band 2: the whole TOC as a flat, indented list of entries."""

    def __init__(self, parent=None, reduce_motion: bool = False) -> None:
        super().__init__(parent)
        self._model: ProgressModel | None = None
        self._reduce_motion = bool(reduce_motion)
        self._phase = 0
        self._files: list[str] = []
        #: The rows currently shown, in order: the delegate reads them by index.
        self._units: list = []
        #: Set when the visible set must be rebuilt even if it looks unchanged
        #: (an empty result must not be mistaken for "nothing changed").
        self._rebuild_pending = True
        self._revision = -1
        self._last_running: list[str] = []
        #: Why the list is empty (a TOC that could not be read), if anything.
        self._error = ""
        self._colors = self._theme_colors("light", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.lbl_title = QLabel(T("tab.chapters"))
        self.lbl_title.setObjectName("bandTitle")
        header.addWidget(self.lbl_title)
        #: Name of the entry being translated.
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
        #: Progress bar of the entry being translated (band header).
        self.bar_current = ShimmerBar(reduce_motion=self._reduce_motion)
        layout.addWidget(self.bar_current)

        self._list = QListWidget()
        self._list.setUniformItemSizes(True)
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerItem)
        self._list.setItemDelegate(_UnitDelegate(self))
        layout.addWidget(self._list, 1)
        self.lbl_empty = QLabel(T("track.empty"))
        self.lbl_empty.setObjectName("bandHint")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.hide()
        layout.addWidget(self.lbl_empty)

        self._timer = QTimer(self)
        self._timer.setInterval(_PULSE_MS)
        self._timer.timeout.connect(self._tick)

    # -- API --------------------------------------------------------------
    def set_model(self, model: ProgressModel | None) -> None:
        self._model = model
        self._files = []
        self._units = []
        self._rebuild_pending = True
        self._revision = -1
        self._last_running = []
        self._list.clear()
        self.refresh()

    def set_error(self, text: str | None) -> None:
        """Say why the chapter list is not available (empty string clears it)."""
        self._error = (text or "").strip()
        # Without a model refresh() returns early, so update the hint directly.
        self._update_empty([])
        if self._model is not None:
            self.refresh()

    def row_data(self, row: int) -> dict | None:
        """Payload for one visible row, built on demand by the delegate."""
        model = self._model
        if model is None or not 0 <= row < len(self._units):
            return None
        unit = self._units[row]
        done, total = model.progress(unit.file)
        state = model.unit_state(unit)
        return {"name": unit.label(), "depth": unit.depth, "done": done,
                "total": total, "state": state,
                "exported": model.exported and state == STATE_DONE}

    def set_filter(self, name: str) -> None:
        """Show every entry, only the ones to translate, or only the done ones."""
        if name not in ("all", "todo", "done"):
            name = "all"
        self._filter = name
        button = self._filter_buttons.get(name)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._files = []
        self._rebuild_pending = True     # an empty result is still a change
        self.refresh()

    def filter_name(self) -> str:
        return self._filter

    def visible_units(self) -> list:
        model = self._model
        if model is None:
            return []
        return self._filtered(model)

    def _filtered(self, model: ProgressModel) -> list:
        if self._filter == "all":
            return list(model.units)
        keep = ((STATE_PENDING, STATE_RUNNING, STATE_ERROR)
                if self._filter == "todo" else (STATE_DONE,))
        units = model.units
        rows = []
        for index, unit in enumerate(units):
            if unit.kind != "document" or not unit.file:
                # A heading stays only while something under it is visible.
                if self._section_has_visible_child(units, index, model, keep):
                    rows.append(unit)
                continue
            if model.unit_state(unit) in keep:
                rows.append(unit)
        return rows

    @staticmethod
    def _section_has_visible_child(units, index: int, model: ProgressModel,
                                   keep) -> bool:
        depth = units[index].depth
        for unit in units[index + 1:]:
            if unit.kind != "document":
                if unit.depth <= depth:
                    break            # a sibling heading: the subtree is over
                continue
            if model.unit_state(unit) in keep:
                return True
        return False

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        self.bar_current.set_reduce_motion(self._reduce_motion)
        self._update_timer()

    def set_theme(self, mode: str, system_dark: bool = True) -> None:
        self._colors = self._theme_colors(mode, system_dark)
        track = "#3a3f47" if theme_mod.is_dark(mode, system_dark) else "#d9dde4"
        fill = theme_mod.palette(mode, system_dark)["accent"]
        self.bar_current.set_colors(track, fill)
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
        if self._rebuild_pending or [unit.key() for unit in units] != self._files:
            self._rebuild(units)
            self._revision = -1
        # Repaint once per real change: the delegate rebuilds each *visible* row's
        # payload while painting, so nothing here is O(entries) per frame.
        if model.revision != self._revision:
            self._revision = model.revision
            self._list.viewport().update()
        running = model.running_units()
        if running != self._last_running:
            self._last_running = list(running)
            self._scroll_to(running[0] if running else None)
        self._update_empty(units)
        self._update_header(model)
        self._update_timer()

    def _scroll_to(self, file_name: str | None) -> None:
        if not file_name:
            return
        row = next((index for index, unit in enumerate(self._units)
                    if unit.file == file_name), None)
        if row is None:
            return
        item = self._list.item(row)
        if item is not None:
            self._list.scrollToItem(item,
                                    QListWidget.ScrollHint.PositionAtCenter)

    def _update_empty(self, units) -> None:
        empty = not units
        # When the TOC could not be read at all, say so instead of hinting that
        # the filter simply matched nothing.
        self.lbl_empty.setText(self._error or T("track.empty"))
        self.lbl_empty.setVisible(empty)
        self._list.setVisible(not empty)

    def _current_file(self, model: ProgressModel) -> str | None:
        running = model.running_units()
        if running:
            return running[0]
        for unit in model.units:
            if unit.kind != "document" or not unit.file:
                continue
            if model.unit_state(unit) not in (STATE_SKIPPED, STATE_DONE,
                                              STATE_EXCLUDED, STATE_HEADER):
                return unit.file
        return None

    def _update_header(self, model: ProgressModel) -> None:
        current = self._current_file(model)
        if current is None:
            self.lbl_subtitle.setText("—")
            self.bar_current.setValue(0)
            self.bar_current.set_busy(False)
            return
        unit = next((u for u in model.units if u.file == current), None)
        self.lbl_subtitle.setText(unit.label() if unit else current)
        done, total = model.progress(current)
        self.bar_current.setValue(int(done / total * 100) if total else 0)
        self.bar_current.set_busy(model.file_state(current) == STATE_RUNNING)

    def _rebuild(self, units) -> None:
        """Recreate the row placeholders (one per visible entry).

        The rows carry no data: the delegate asks :meth:`row_data` for it while
        painting, so a rebuild is just N cheap items.
        """
        self._list.clear()
        self._units = list(units)
        self._files = [unit.key() for unit in units]
        self._rebuild_pending = False
        for _ in units:
            self._list.addItem(QListWidgetItem())

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
                      and not self._reduce_motion and self.isVisible())
        if active and not self._timer.isActive():
            self._timer.start()
        elif not active and self._timer.isActive():
            self._timer.stop()
            self._phase = 0

    def _tick(self) -> None:
        self._phase = 0 if self._phase else 1
        if self._model is None:  # pragma: no cover - defensive
            return
        # Repaint the visible rows: the running entry may share its document with
        # other entries, and they pulse together. Only visible rows are painted,
        # so a 200-row book costs nothing.
        self._list.viewport().update()

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
