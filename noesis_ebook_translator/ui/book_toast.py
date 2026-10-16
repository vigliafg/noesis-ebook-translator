"""Rounded "toast" pill showing the book being worked on.

It sits in the top strip of the workflow bar, in the empty area between the last
tab and the settings gear, and must read as something *outside* the toolbar: a
larger, bolder label with its own colours (yellow with black text on the dark
theme, bright blue with white text on the light one) and, while a translation is
running, a **sweeping sheen** -- the same reflection used by the sibling project
``noesis-pdf-cloner`` for its floating action button: a diagonal light band that
crosses the surface, reaching the far edge at 55% of a 2.4 s cycle and then
resting off-screen before the next pass.

Qt cannot animate a stylesheet, so the pill is painted by hand and the animation
drives a ``sheenPos`` property (0..1) read by :meth:`paintEvent`.
``reduce_motion`` keeps the pill still.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .icons import icon

__all__ = ["BookToast"]

#: Per-theme palette: the pill background (two gradient stops), the foreground
#: and the sheen colour. The sheen is white with alpha -- on both pills the
#: surface is saturated, so a white reflection is what reads as glossy (the
#: cloner's ``fab_spark``: white on dark, tinted on light).
PALETTES = {
    "dark": {"bg": "#ffd60a", "bg2": "#ffc300", "fg": "#101418",
             "dot": "#101418", "sheen": "#f2ffffff"},
    "light": {"bg": "#5b9bff", "bg2": "#2f6fe0", "fg": "#ffffff",
              "dot": "#ffffff", "sheen": "#d9ffffff"},
}

#: Painting metrics, shared by :meth:`BookToast.paintEvent` and
#: :meth:`BookToast.sizeHint` so the label never has to be elided when the pill
#: is at its natural width. The status dot's space is always reserved, so the
#: pill does not resize when a translation starts.
PAD_LEFT = 12.0
PAD_RIGHT = 12.0
DOT_W = 12.0
ICON = 18.0
ICON_GAP = 7.0
PERCENT_GAP = 8.0


class BookToast(QWidget):
    """Pill with the book title; a sheen sweeps it while translating."""

    #: Sheen timing, copied from the cloner: it crosses the pill by 55% of the
    #: cycle, then rests off-screen until the next pass.
    SHEEN_MS = 2400
    HEIGHT = 30
    RADIUS = 15

    def __init__(self, parent=None, reduce_motion: bool = False) -> None:
        super().__init__(parent)
        self._text = ""
        self._percent: int | None = None
        self._working = False
        self._sheen = 0.0
        self._reduce_motion = bool(reduce_motion)
        self._mode = "light"
        self._colors = dict(PALETTES["light"])
        self._sheen_visible = False
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._anim = QPropertyAnimation(self, b"sheenPos", self)
        self._anim.setDuration(self.SHEEN_MS)
        self._anim.setLoopCount(-1)
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.55, 1.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)

    # -- animated property ------------------------------------------------
    def _get_sheen_pos(self) -> float:
        return self._sheen

    def _set_sheen_pos(self, value: float) -> None:
        self._sheen = max(0.0, min(1.0, float(value)))
        self.update()

    sheenPos = pyqtProperty(float, _get_sheen_pos, _set_sheen_pos)

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
        """Sweep the sheen while the book is being worked on, rest otherwise."""
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
        self._colors = dict(PALETTES[self._mode])
        self.update()

    def is_animating(self) -> bool:
        return self._anim.state() == QPropertyAnimation.State.Running

    def sheen_color(self) -> QColor:
        return QColor(self._colors["sheen"])

    def _sync_animation(self) -> None:
        if self._working and not self._reduce_motion and self.isVisible():
            if not self.is_animating():
                self._anim.start()
            return
        self._anim.stop()
        self._sheen = 0.0
        self.update()

    # -- geometry ---------------------------------------------------------
    def _label_font(self) -> QFont:
        """The (larger, bold) font used for the book name."""
        font = QFont(self.font())
        font.setPointSizeF(max(11.5, font.pointSizeF() + 2.5))
        font.setBold(True)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        metrics = QFontMetrics(self._label_font())
        width = (PAD_LEFT + DOT_W + ICON + ICON_GAP
                 + metrics.horizontalAdvance(self._text))
        if self._percent is not None:
            width += (metrics.horizontalAdvance(f"{self._percent}%")
                      + PERCENT_GAP)
        width += PAD_RIGHT
        return QSize(min(int(width), 460), self.HEIGHT)

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
        pill = QRectF(self.rect())
        colors = self._colors

        gradient = QLinearGradient(0.0, pill.top(), 0.0, pill.bottom())
        gradient.setColorAt(0.0, QColor(colors["bg"]))
        gradient.setColorAt(1.0, QColor(colors["bg2"]))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(pill, self.RADIUS, self.RADIUS)

        # Sweeping reflection (same as the cloner's FAB): a diagonal band that
        # crosses the pill and then stays off-screen until the next pass.
        if self._working and not self._reduce_motion:
            width = float(self.width())
            height = float(self.height())
            path = QPainterPath()
            path.addRoundedRect(QRectF(pill).adjusted(1.0, 1.0, -1.0, -1.0),
                                self.RADIUS, self.RADIUS)
            painter.setClipPath(path)
            band = max(24.0, width * 0.5)
            x = -band + (width + 2.0 * band) * self._sheen
            sheen = self.sheen_color()
            edge = QColor(sheen)
            edge.setAlpha(0)
            shine = QLinearGradient(x, 0.0, x + band, height)
            shine.setColorAt(0.0, edge)
            shine.setColorAt(0.5, sheen)
            shine.setColorAt(1.0, edge)
            painter.fillRect(self.rect(), shine)
            painter.setClipping(False)

        font = self._label_font()
        painter.setFont(font)
        metrics = painter.fontMetrics()

        x = pill.left() + PAD_LEFT
        if self._working:
            painter.setBrush(QColor(colors["dot"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(x, pill.center().y() - 3.5, 7.0, 7.0))
        x += DOT_W
        pixmap = icon("closed_book").pixmap(int(ICON), int(ICON))
        if not pixmap.isNull():
            painter.drawPixmap(int(x),
                               int(pill.center().y() - ICON / 2), pixmap)
        x += ICON + ICON_GAP

        painter.setPen(QColor(colors["fg"]))
        right = pill.right() - PAD_RIGHT
        if self._percent is not None:
            percent = f"{self._percent}%"
            width = metrics.horizontalAdvance(percent)
            painter.drawText(QRectF(right - width, pill.top(), width,
                                    pill.height()),
                             int(Qt.AlignmentFlag.AlignVCenter
                                 | Qt.AlignmentFlag.AlignRight), percent)
            right -= width + PERCENT_GAP
        text = metrics.elidedText(self._text, Qt.TextElideMode.ElideRight,
                                  int(max(10.0, right - x)))
        painter.drawText(QRectF(x, pill.top(), right - x, pill.height()),
                         int(Qt.AlignmentFlag.AlignVCenter
                             | Qt.AlignmentFlag.AlignLeft), text)
        painter.end()
