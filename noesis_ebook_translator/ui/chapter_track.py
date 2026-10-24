"""Band 2 of the Translate view: the chapter list, one row per **TOC entry**.

The rows follow the TOC (reading) order and keep the hierarchy (indentation by
depth); headings with no document of their own are shown as plain entries. The
progress itself is per XHTML document -- that is what the engine reports -- so two
entries that share a file show the same numbers.

The list repaints **only the rows that changed** and pulses at ~2 Hz, so a
200-row book costs nothing per frame.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QHelpEvent, QPainter
from PyQt6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QStyle, QStyledItemDelegate, QToolButton, QToolTip,
    QVBoxLayout, QWidget)

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
        if option.state & QStyle.StateFlag.State_Selected:
            selected = QColor(colors["accent"])
            selected.setAlpha(40)
            painter.fillRect(rect, selected)

        left = rect.left() + 6 + depth * INDENT
        marker = QRect(left, rect.top() + (NAME_HEIGHT - 14) // 2, 14, 14)
        accent = colors["accent"]
        if header:
            # A small chevron makes a section distinguishable from a pending
            # chapter even without a marker circle.
            painter.setPen(colors["muted"])
            heading_font = QFont(option.font)
            heading_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(heading_font)
            painter.drawText(marker, int(Qt.AlignmentFlag.AlignCenter), "▸")
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
            if data.get("interrupted"):
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(colors["muted"])
                painter.drawEllipse(marker.adjusted(3, 3, -3, -3))
            else:
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
        elif header:
            font.setWeight(QFont.Weight.DemiBold)
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
            # Blink the whole row (name + marker) while it is being translated;
            # a partial row left by a cancel/open stays still and muted.
            if data.get("interrupted"):
                name_color = colors["muted"]
            else:
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
        name = str(data.get("name") or "")
        if data.get("extra"):
            name = f"{name} ({T('track.extra')})"
        name = metrics.elidedText(name,
                                  Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRect(text_left, rect.top(), text_width, NAME_HEIGHT),
                         int(Qt.AlignmentFlag.AlignVCenter), name)

        painter.setPen(colors["error"] if state == STATE_ERROR
                       else colors["muted"])
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

    def helpEvent(self, event, view, option, index):  # noqa: N802 - Qt naming
        """Dynamic tooltip: full name, file, state, count, cache, error."""
        data = self._track.row_data(index.row())
        if not data:
            return super().helpEvent(event, view, option, index)
        QToolTip.showText(event.globalPos(), self._track.tooltip_for(data), view)
        return True


class ChapterTrackWidget(QWidget):
    """Band 2: the whole TOC as a flat, indented list of entries."""

    #: Emitted when the user activates a row (Enter or double-click): the
    #: target is the TOC href (anchor included) or the document name.
    entryActivated = pyqtSignal(str)

    def __init__(self, parent=None, reduce_motion: bool = False) -> None:
        super().__init__(parent)
        self._model: ProgressModel | None = None
        self._reduce_motion = bool(reduce_motion)
        self._phase = 0
        self._files: list[str] = []
        #: Current free-text search (case-folded, empty when inactive).
        self._search = ""
        self._filter_labels: dict[str, str] = {}
        self._active_running: list[str] = []
        #: The rows currently shown, in order: the delegate reads them by index.
        self._units: list = []
        #: Filtered view cached per ``(filter, model.revision)``: a delta that
        #: changes counts but not the visible set must not re-scan the TOC.
        self._filtered_cache: list | None = None
        self._filtered_keys: list[str] | None = None
        self._filtered_key: tuple | None = None
        self._last_filtered_units: list | None = None
        self._last_filtered_keys: list[str] | None = None
        #: First visible unit and row for each document (header/scroll lookups).
        self._unit_by_file: dict[str, object] = {}
        self._row_by_file: dict[str, int] = {}
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
        self.lbl_sep = QLabel("·")
        self.lbl_sep.setObjectName("bandHint")
        header.addWidget(self.lbl_sep)
        #: Name of the entry being translated.
        self.lbl_subtitle = QLabel("—")
        self.lbl_subtitle.setObjectName("bandHint")
        header.addWidget(self.lbl_subtitle, 1)
        layout.addLayout(header)
        #: Aggregate of the run: ``done/total chapters · errors · running``.
        self.lbl_summary = QLabel("—")
        self.lbl_summary.setObjectName("bandHint")
        layout.addWidget(self.lbl_summary)
        #: Minimal legend: the icons are explained here instead of guessed.
        self.lbl_legend = QLabel(T("track.legend"))
        self.lbl_legend.setObjectName("bandHint")
        self.lbl_legend.setWordWrap(True)
        layout.addWidget(self.lbl_legend)
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
            label = T(widget_key)
            self._filter_labels[key] = label
            button.setText(label)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(lambda _=False, name=key: self.set_filter(name))
            self._filter_group.addButton(button)
            self._filter_buttons[key] = button
            self.toolbar.addWidget(button)
        self.toolbar.addStretch(1)
        self.btn_follow = QToolButton()
        self.btn_follow.setText(f"✓ {T('track.follow')}")
        self.btn_follow.setToolTip(T("track.follow_hint"))
        self.btn_follow.setCheckable(True)
        self.btn_follow.setChecked(True)
        self.btn_follow.setAutoRaise(True)
        self.btn_follow.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_follow.toggled.connect(self._on_follow_toggled)
        self.toolbar.addWidget(self.btn_follow)
        self._filter_buttons["all"].setChecked(True)
        layout.addLayout(self.toolbar)
        search_row = QHBoxLayout()
        search_row.setSpacing(2)
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText(T("track.search"))
        self.edt_search.setClearButtonEnabled(True)
        self.edt_search.textChanged.connect(self._on_search)
        search_row.addWidget(self.edt_search, 1)
        self.btn_next_todo = QToolButton()
        self.btn_next_todo.setText(T("track.next_todo"))
        self.btn_next_todo.setAutoRaise(True)
        self.btn_next_todo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next_todo.clicked.connect(
            lambda: self._jump_to(STATE_PENDING))
        search_row.addWidget(self.btn_next_todo)
        self.btn_next_error = QToolButton()
        self.btn_next_error.setText(T("track.next_error"))
        self.btn_next_error.setAutoRaise(True)
        self.btn_next_error.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next_error.clicked.connect(lambda: self._jump_to(STATE_ERROR))
        search_row.addWidget(self.btn_next_error)
        layout.addLayout(search_row)
        #: Progress bar of the entry being translated (band header).
        self.bar_current = ShimmerBar(reduce_motion=self._reduce_motion)
        layout.addWidget(self.bar_current)

        self._list = QListWidget()
        self._list.setUniformItemSizes(True)
        # Single selection + focus: the rows are read-only for translation, but
        # keyboard users must be able to move and open one.
        self._list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._list.setAccessibleName(T("tab.chapters"))
        self._list.itemActivated.connect(self._activate_current)
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
        self._search = ""
        if hasattr(self, "edt_search"):
            self.edt_search.blockSignals(True)
            self.edt_search.clear()
            self.edt_search.blockSignals(False)
        self._invalidate_filter()
        self._last_filtered_units = None
        self._last_filtered_keys = None
        self._unit_by_file = {}
        self._row_by_file = {}
        self._revision = -1
        self._last_running = []
        self._active_running = []
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
                "file": unit.file or "", "href": unit.href or "",
                "errors": model.errors.get(unit.file or "", 0),
                "error_text": model.error_text.get(unit.file or "", ""),
                "cached": model.cached_pages.get(unit.file or "", 0),
                "extra": bool(getattr(unit, "extra", False)),
                "interrupted": bool(model.finished
                                    and state == STATE_RUNNING),
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
        self._invalidate_filter()
        self.refresh()

    def filter_name(self) -> str:
        return self._filter

    def visible_units(self) -> list:
        model = self._model
        if model is None:
            return []
        return list(self._filtered(model))

    def _filtered(self, model: ProgressModel) -> list:
        """Visible rows, cached per ``(filter, revision, search)``.

        ``all`` with no search is the common case during a run: the rows are the
        model's units in TOC order, so repeated deltas reuse the same list and
        key snapshot instead of copying the whole TOC at every tick.
        """
        key = (self._filter, model.revision, self._search)
        if key == self._filtered_key and self._filtered_cache is not None:
            return self._filtered_cache
        if self._filter == "all" and not self._search:
            units = model.units
            if (self._filtered_cache is units
                    and self._filtered_keys is not None
                    and len(self._filtered_keys) == len(units)):
                self._filtered_key = key
                return units
            self._filtered_cache = units
            self._filtered_keys = [unit.key() for unit in units]
        else:
            self._filtered_cache = self._compute_filtered(model)
            self._filtered_keys = [unit.key()
                                   for unit in self._filtered_cache]
        self._filtered_key = key
        return self._filtered_cache

    def _compute_filtered(self, model: ProgressModel) -> list:
        units = model.units
        if self._filter == "all":
            base = list(units)
        else:
            keep = ((STATE_PENDING, STATE_RUNNING, STATE_ERROR)
                    if self._filter == "todo" else (STATE_DONE,))
            base = []
            for index, unit in enumerate(units):
                if unit.kind != "document" or not unit.file:
                    # A heading stays only while something under it is visible.
                    if self._section_has_visible_child(units, index, model, keep):
                        base.append(unit)
                    continue
                if model.unit_state(unit) in keep:
                    base.append(unit)
        if not self._search:
            return base
        return self._search_rows(units, base)

    def _matches(self, unit) -> bool:
        query = self._search
        if not query:
            return True
        return (query in unit.label().casefold()
                or query in (unit.file or "").casefold()
                or query in (unit.href or "").casefold())

    def _search_rows(self, units, base: list) -> list:
        """Keep matching documents and the headings that contain them."""
        base_ids = {id(unit) for unit in base}
        matches = {id(unit) for unit in base
                   if unit.kind == "document" and self._matches(unit)}
        headings: set[int] = set()
        stack: list = []
        for unit in units:
            while stack and stack[-1].depth >= unit.depth:
                stack.pop()
            if unit.kind == "document":
                if id(unit) in matches:
                    headings.update(id(heading) for heading in stack)
                continue
            stack.append(unit)
            if id(unit) in base_ids and self._matches(unit):
                headings.add(id(unit))
        rows = []
        for unit in base:
            if unit.kind == "document":
                if id(unit) in matches:
                    rows.append(unit)
            elif id(unit) in headings:
                rows.append(unit)
        return rows

    def _on_search(self, text: str) -> None:
        query = (text or "").strip().casefold()
        if query == self._search:
            return
        self._search = query
        self._invalidate_filter()
        self.refresh()

    def _on_follow_toggled(self, checked: bool) -> None:
        self.btn_follow.setText(
            ("✓ " if checked else "") + T("track.follow"))
        self.refresh()

    def _invalidate_filter(self) -> None:
        self._filtered_cache = None
        self._filtered_keys = None
        self._filtered_key = None
        self._rebuild_pending = True

    def _jump_to(self, state: str) -> None:
        """Move the current row to the next visible document in ``state``."""
        if not self._units:
            return
        start = self._list.currentRow()
        if start < 0:
            start = -1
        count = len(self._units)
        for offset in range(count):
            row = (start + 1 + offset) % count
            unit = self._units[row]
            if unit.kind != "document" or not unit.file:
                continue
            if self._model is None or self._model.unit_state(unit) != state:
                continue
            self._list.setCurrentRow(row)
            item = self._list.item(row)
            if item is not None:
                self._list.scrollToItem(
                    item, QListWidget.ScrollHint.PositionAtCenter)
            return

    def _activate_current(self, _item=None) -> None:
        self._activate_row(self._list.currentRow())

    def _activate_row(self, row: int) -> None:
        if not 0 <= row < len(self._units):
            return
        unit = self._units[row]
        target = unit.href or unit.file
        if target:
            self.entryActivated.emit(target)

    def tooltip_for(self, data: dict) -> str:
        """Human-readable tooltip for a row (name, scope, state, counts)."""
        name = str(data.get("name") or "")
        lines = [name]
        target = str(data.get("href") or data.get("file") or "")
        if target and target != name:
            lines.append(target)
        state = str(data.get("state") or "")
        if data.get("interrupted"):
            lines.append(T("track.state.interrupted"))
        elif state:
            lines.append(T(f"track.state.{state}"))
        total = int(data.get("total") or 0)
        done = int(data.get("done") or 0)
        if total:
            lines.append(f"{done}/{total}")
        cached = int(data.get("cached") or 0)
        if cached:
            lines.append(f"{T('track.cached')}: {cached}/{total}" if total
                         else T("track.cached"))
        errors = int(data.get("errors") or 0)
        if errors:
            lines.append(self._errors_label(errors))
            text = str(data.get("error_text") or "").strip()
            if text:
                lines.append(text)
        if data.get("extra"):
            lines.append(T("track.extra"))
        if target and state != STATE_HEADER:
            lines.append(T("track.open_hint"))
        return "\n".join(line for line in lines if line)

    def _errors_label(self, count: int) -> str:
        if count == 1:
            return T("track.error_one")
        return T("track.errors").format(count=count)

    def _update_summary(self, model: ProgressModel, units: list,
                        running: list[str]) -> None:
        if model.plan:
            tracked = model.tracked()
            total = len(tracked)
            done = sum(1 for unit in tracked
                       if model.file_state(unit.file) == STATE_DONE)
        else:
            total = sum(1 for unit in model.units
                        if unit.kind == "document" and unit.file
                        and model.is_selected(unit))
            done = 0
        summary_key = "track.summary_one" if total == 1 else "track.summary"
        parts = [T(summary_key).format(done=done, total=total)
                 if total else "—"]
        errors = model.error_count()
        if errors:
            parts.append(self._errors_label(errors))
        if running:
            if len(running) == 1:
                parts.append(T("track.running_one"))
            else:
                parts.append(T("track.running").format(count=len(running)))
        if self._search:
            results = sum(1 for unit in units if unit.kind == "document")
            parts.append(T("track.search_results").format(count=results))
        self.lbl_summary.setText(" · ".join(parts))

        counts = {"all": total,
                  "todo": max(0, total - done),
                  "done": done}
        for key, label in self._filter_labels.items():
            text = f"{label} ({counts.get(key, 0)})"
            button = self._filter_buttons.get(key)
            if button is not None and button.text() != text:
                button.setText(text)

    @staticmethod
    def _section_has_visible_child(units, index: int, model: ProgressModel,
                                   keep) -> bool:
        depth = units[index].depth
        for unit in units[index + 1:]:
            # A document at the same (or shallower) depth is a sibling, not a
            # descendant: the heading's subtree ended there. Checking only the
            # heading rows let a sibling document keep the heading alive.
            if unit.depth <= depth:
                break
            if unit.kind == "document" and model.unit_state(unit) in keep:
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
        keys = self._filtered_keys or []
        # Rebuild only when the visible set really changed. ``keys is not
        # self._last_filtered_keys`` means the filter recomputed the view; for
        # ``all`` with the same units the cached list and keys are reused.
        if self._rebuild_pending or (
                keys is not self._last_filtered_keys and keys != self._files):
            self._rebuild(units, keys)
            self._revision = -1
        self._last_filtered_units = units
        self._last_filtered_keys = keys
        # Repaint once per real change: the delegate rebuilds each *visible* row's
        # payload while painting; the filter is cached per model revision.
        if model.revision != self._revision:
            self._revision = model.revision
            self._list.viewport().update()
        running = model.running_units()
        self._active_running = list(running)
        if running != self._last_running:
            self._last_running = list(running)
            if self.btn_follow.isChecked():
                self._scroll_to(running[0] if running else None)
        self._update_empty(units)
        self._update_summary(model, units, running)
        self._update_header(model, running)
        self._update_timer(running)

    def _scroll_to(self, file_name: str | None) -> None:
        if not file_name:
            return
        row = self._row_by_file.get(file_name)
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
        if self._error:
            hint = self._error
        elif self._search:
            hint = T("track.none")
        else:
            hint = T("track.empty")
        self.lbl_empty.setText(hint)
        self.lbl_empty.setVisible(empty)
        self._list.setVisible(not empty)

    def _current_file(self, model: ProgressModel,
                      running: list[str] | None = None) -> str | None:
        if model.finished:
            # No run is active: "current chapter" would be a lie. The rows keep
            # their progress; the header shows nothing.
            return None
        running = model.running_units() if running is None else running
        if running:
            return running[0]
        for unit in model.units:
            if unit.kind != "document" or not unit.file:
                continue
            if model.unit_state(unit) not in (STATE_SKIPPED, STATE_DONE,
                                              STATE_EXCLUDED, STATE_HEADER):
                return unit.file
        return None

    def _update_header(self, model: ProgressModel,
                       running: list[str] | None = None) -> None:
        running = model.running_units() if running is None else running
        if len(running) > 1:
            # Parallel translation: there is no single "current" chapter.
            self.lbl_subtitle.setText(
                T("track.running_many").format(count=len(running)))
            self.bar_current.setValue(int(round(model.overall_percent())))
            self.bar_current.set_busy(not model.finished)
            return
        current = self._current_file(model, running)
        if current is None:
            self.lbl_subtitle.setText("—")
            self.bar_current.setValue(0)
            self.bar_current.set_busy(False)
            return
        unit = self._unit_by_file.get(current)
        if unit is None:
            unit = next((u for u in model.units if u.file == current), None)
        self.lbl_subtitle.setText(unit.label() if unit else current)
        done, total = model.progress(current)
        self.bar_current.setValue(int(done / total * 100) if total else 0)
        # After a cancel/fail the run is closed: the partial row keeps its
        # numbers, but the header must not keep shimmering as if it were live.
        self.bar_current.set_busy(
            not model.finished and model.file_state(current) == STATE_RUNNING)

    def _rebuild(self, units, keys: list[str] | None = None) -> None:
        """Recreate the row placeholders (one per visible entry).

        The rows carry no data: the delegate asks :meth:`row_data` for it while
        painting, so a rebuild is just N cheap items. The file→row maps make
        header and auto-scroll lookups O(1) instead of a scan of the TOC.
        """
        self._list.clear()
        self._units = list(units)
        self._files = list(keys) if keys is not None else [
            unit.key() for unit in units]
        self._unit_by_file = {}
        self._row_by_file = {}
        for row, unit in enumerate(self._units):
            if unit.file:
                self._unit_by_file.setdefault(unit.file, unit)
                self._row_by_file.setdefault(unit.file, row)
        self._rebuild_pending = False
        for row, unit in enumerate(self._units):
            item = QListWidgetItem(unit.label())
            # The delegate paints the row, but the accessibility layer reads the
            # item's text: without this, screen readers saw empty rows.
            item.setData(Qt.ItemDataRole.AccessibleTextRole,
                         f"{unit.label()} — {unit.file or unit.href or ''}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._list.addItem(item)
        if self._units and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Re-evaluate the pulse when the band becomes visible.

        The pulse is skipped while hidden (nothing to animate), so becoming
        visible has to restart it: otherwise it would only come back on the next
        progress update.
        """
        super().showEvent(event)
        self._update_timer()

    def _update_timer(self, running: list[str] | None = None) -> None:
        model = self._model
        if running is None:
            running = model.running_units() if model is not None else []
        active = bool(running and not self._reduce_motion and self.isVisible())
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
            # "Greyed out": dimmed but still readable (the old #b4bbc5 was
            # around 2:1 on white, invisible to low-vision users).
            "excluded": QColor("#7d8794" if dark else "#8a93a0"),
            "accent": QColor(accent),
            "track": QColor("#3a3f47" if dark else "#d9dde4"),
            "done": QColor("#37b24d" if not dark else "#51cf66"),
            "error": QColor("#e03131" if not dark else "#ff6b6b"),
        }
