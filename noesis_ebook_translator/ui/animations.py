"""Lightweight translation animations (GUI only).

Two widgets:

* :class:`ShimmerBar` — a progress bar with a moving highlight; shows an
  indeterminate shimmer when no value is known yet.
* :class:`DotsLabel` — a status label whose trailing ellipsis animates.

Both honour ``reduce_motion``: when enabled, they stay static and never start a
timer (so headless tests and accessibility users are unaffected).
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget

__all__ = ["ShimmerBar", "DotsLabel"]


class ShimmerBar(QWidget):
    """A slim progress bar with an animated shimmer highlight."""

    def __init__(self, parent=None, reduce_motion: bool = False,
                 track: str = "#3a3f47", fill: str = "#4c8bf5") -> None:
        super().__init__(parent)
        self._value = 0  # 0..100
        self._offset = 0
        self._busy = False
        self._reduce_motion = reduce_motion
        self._track = QColor(track)
        self._fill = QColor(fill)
        self.setMinimumHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    # -- API --------------------------------------------------------------
    def set_colors(self, track: str, fill: str) -> None:
        """Match the bar to the active app theme."""
        self._track = QColor(track)
        self._fill = QColor(fill)
        self.update()

    def setValue(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def value(self) -> int:
        return self._value

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        if self._busy and not self._reduce_motion:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        if self._reduce_motion:
            self._timer.stop()

    def is_animating(self) -> bool:
        return self._timer.isActive()

    # -- internals --------------------------------------------------------
    def _tick(self) -> None:
        self._offset = (self._offset + 6) % 200
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track)
        painter.drawRoundedRect(rect, 4, 4)

        fill_width = rect.width() * (self._value / 100.0)
        painter.setBrush(self._fill)
        painter.drawRoundedRect(QRectF(0, 0, fill_width, rect.height()), 4, 4)

        if self._busy and not self._reduce_motion:
            gradient = QLinearGradient(-60 + self._offset, 0,
                                       60 + self._offset, 0)
            gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            gradient.setColorAt(0.5, QColor(255, 255, 255, 120))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(gradient)
            painter.drawRoundedRect(rect, 4, 4)
        painter.end()


class DotsLabel(QLabel):
    """A label whose trailing ``.`` ``..`` ``...`` animates while busy."""

    def __init__(self, base_text: str = "", parent=None,
                 reduce_motion: bool = False) -> None:
        super().__init__(base_text, parent)
        self._base = base_text
        self._count = 0
        self._reduce_motion = reduce_motion
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._tick)

    def set_base_text(self, text: str) -> None:
        self._base = text
        if not self._timer.isActive():
            super().setText(text)

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        if self._reduce_motion:
            self._timer.stop()
            super().setText(self._base)

    def start_busy(self) -> None:
        if self._reduce_motion:
            super().setText(self._base)
            return
        self._count = 0
        self._timer.start()

    def stop_busy(self) -> None:
        self._timer.stop()
        super().setText(self._base)

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self._count = (self._count + 1) % 4
        super().setText(self._base + "." * self._count)
