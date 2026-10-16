"""Rounded "toast" pill showing the book being worked on.

It sits in the top strip of the workflow bar, in the empty area between the last
tab and the settings gear, and must read as something *outside* the toolbar: a
larger, bolder label with its own colours (yellow on the dark theme, bright blue
on the light one) and a soft pulsing halo while a translation is running.

Qt cannot animate a stylesheet, so the pill is painted by hand and the animation
drives a ``pulse`` property (0..1) read by :meth:`paintEvent`. ``reduce_motion``
keeps the pill static.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .icons import icon

__all__ = ["BookToast"]

#: Per-theme palette: background (optionally two stops for a soft gradient),
#: foreground and the halo colour used by the pulse.
PALETTES = {
    "dark": {"bg": "#ffd60a", "bg2": "#ffc300", "fg": "#101418",
             "halo": "#ffd60a", "dot": "#101418"},
    "light": {"bg": "#5b9bff", "bg2": "#2f6fe0", "fg": "#ffffff",
              "halo": "#3b82f6", "dot": "#ffffff"},
}


class BookToast(QWidget):
    """Pill with the book title; pulses while the book is being translated."""

    #: One pulse cycle (ms) and how far the halo grows (px).
    PULSE_MS = 1900
    HALO = 6
    #: Padding around the pill so the halo has room inside the widget bounds.
    PAD = 6
    HEIGHT = 30
    RADIUS = 15

    def __init__(self, parent=None, reduce_motion: bool = False) -> None:
        super().__init__(parent)
        self._text = ""
        self._percent: int | None = None
        self._working = False
        self._pulse = 0.0
        self._reduce_motion = bool(reduce_motion)
        self._mode = "light"
        self._system_dark = False
        self._colors = dict(PALETTES["light"])
        self.setFixedHeight(self.HEIGHT + 2 * self.PAD)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._anim = QPropertyAnimation(self, b"pulse", self)
        self._anim.setDuration(self.PULSE_MS)
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)

    # -- animated property ------------------------------------------------
    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        self._pulse = max(0.0, min(1.0, float(value)))
        self.update()

    pulse = pyqtProperty(float, _get_pulse, _set_pulse)

    # -- API --------------------------------------------------------------
    def set_text(self, text: str) -> None:
        text = (text or "").strip()
        if text == self._text:
            return
        self._text = text
        self.setToolTip(text)
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def set_percent(self, percent: int | None) -> None:
        percent = None if percent is None else int(percent)
        if percent != self._percent:
            self._percent = percent
            self.updateGeometry()
            self.update()

    def percent(self) -> int | None:
        return self._percent

    def set_working(self, working: bool) -> None:
        """Pulse while the book is being worked on, stay still otherwise."""
        working = bool(working)
        if working == self._working:
            return
        self._working = working
        self._sync_animation()
        self.update()

    def is_working(self) -> bool:
        return self._working

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        self._sync_animation()
        self.update()

    def set_theme(self, mode: str = "light", system_dark: bool = False) -> None:
        from .. import theme as theme_mod

        dark = theme_mod.is_dark(mode, system_dark)
        self._mode = "dark" if dark else "light"
        self._system_dark = system_dark
        self._colors = dict(PALETTES[self._mode])
        self.update()

    def is_animating(self) -> bool:
        return self._anim.state() == QPropertyAnimation.State.Running

    def _sync_animation(self) -> None:
        if self._working and not self._reduce_motion and self.isVisible():
            if not self.is_animating():
                self._anim.start()
            return
        self._anim.stop()
        self._pulse = 0.0

    # -- geometry ---------------------------------------------------------
    def _label_font(self) -> QFont:
        """The (larger, bold) font used for the book name."""
        font = QFont(self.font())
        font.setPointSizeF(max(11.5, font.pointSizeF() + 2.5))
        font.setBold(True)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        from PyQt6.QtGui import QFontMetrics

        metrics = QFontMetrics(self._label_font())
        width = metrics.horizontalAdvance(self._text) + 58
        if self._percent is not None:
            width += metrics.horizontalAdvance(f"{self._percent}%") + 8
        return QSize(min(width, 420) + 2 * self.PAD,
                     self.HEIGHT + 2 * self.PAD)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._sync_animation()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().hideEvent(event)
        self._anim.stop()

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pill = QRectF(self.rect()).adjusted(self.PAD, self.PAD,
                                            -self.PAD, -self.PAD)
        colors = self._colors

        # Pulsing halo: a soft ring growing out of the pill while translating.
        if self._working and self._pulse > 0 and not self._reduce_motion:
            halo = QColor(colors["halo"])
            halo.setAlpha(int(90 * (1.0 - self._pulse)))
            spread = self.HALO * self._pulse
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawRoundedRect(pill.adjusted(-spread, -spread,
                                                  spread, spread),
                                    self.RADIUS + spread, self.RADIUS + spread)

        gradient = QLinearGradient(0.0, pill.top(), 0.0, pill.bottom())
        top = QColor(colors["bg"])
        bottom = QColor(colors["bg2"])
        if self._working and not self._reduce_motion:
            # ... plus a gentle brightness breathing, so the pulse reads even
            # where a halo would be lost against a busy background.
            lift = 0.10 * self._pulse
            top = _lighten(top, lift)
            bottom = _lighten(bottom, lift)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(pill, self.RADIUS, self.RADIUS)

        font = self._label_font()
        painter.setFont(font)
        metrics = painter.fontMetrics()

        x = pill.left() + 12.0
        if self._working:
            dot = QColor(colors["dot"])
            dot.setAlpha(255 if self._pulse > 0.5 else 130)
            painter.setBrush(dot)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(x, pill.center().y() - 3.5, 7.0, 7.0))
            x += 12.0
        icon_size = 18
        pixmap = icon("closed_book").pixmap(icon_size, icon_size)
        if not pixmap.isNull():
            painter.drawPixmap(int(x),
                               int(pill.center().y() - icon_size / 2), pixmap)
        x += icon_size + 7

        painter.setPen(QColor(colors["fg"]))
        right = pill.right() - 12.0
        if self._percent is not None:
            percent = f"{self._percent}%"
            width = metrics.horizontalAdvance(percent)
            painter.drawText(QRectF(right - width, pill.top(), width,
                                    pill.height()),
                             int(Qt.AlignmentFlag.AlignVCenter
                                 | Qt.AlignmentFlag.AlignRight), percent)
            right -= width + 8.0
        text = metrics.elidedText(self._text, Qt.TextElideMode.ElideRight,
                                  int(max(10.0, right - x)))
        painter.drawText(QRectF(x, pill.top(), right - x, pill.height()),
                         int(Qt.AlignmentFlag.AlignVCenter
                             | Qt.AlignmentFlag.AlignLeft), text)
        painter.end()


def _lighten(color: QColor, amount: float) -> QColor:
    """Blend ``color`` towards white by ``amount`` (0..1)."""
    light = QColor(color)
    light.setRed(min(255, int(color.red() + (255 - color.red()) * amount)))
    light.setGreen(min(255, int(color.green()
                                + (255 - color.green()) * amount)))
    light.setBlue(min(255, int(color.blue() + (255 - color.blue()) * amount)))
    return light
