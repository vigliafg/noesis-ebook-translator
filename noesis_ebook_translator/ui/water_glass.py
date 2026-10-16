"""Cover + rising "liquid" progress fill (port of the sibling *cloner* widget).

Visual behaviour is copied from ``noesis-pdf-cloner`` (``LiquidOverlay`` in
``main.py`` and the CSS ``.liquid`` of ``noesis-pdf-cloner-service``): a cover
thumbnail dimmed to 35%, a blue gradient filling the widget from the bottom, a
bright 1px crest with a soft glow above it, and a ~0.5 s eased transition.

Differences: the glass here is a **rectangle** (as in the reference) and the
widget honours ``reduce_motion`` by jumping straight to the new level.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRect, QRectF, Qt, pyqtProperty)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

__all__ = ["WaterGlass"]


def _default_colors() -> dict[str, str]:
    return {"bg": "#e6f2f3f5", "caption_bg": "#e6ffffff",
            "text": "#1c2430", "accent": "#4f8cff"}


class WaterGlass(QWidget):
    """Dimmed cover with a liquid level (0-100) rising from the bottom."""

    #: Transition duration: same as the CSS ``transition: height .5s ease``.
    ANIM_MS = 500
    #: Height of the soft glow drawn above the crest (the CSS ``blur(3px)``).
    GLOW = 6

    def __init__(self, parent=None, reduce_motion: bool = False) -> None:
        super().__init__(parent)
        self._level = 0.0
        self._cover: QPixmap | None = None
        self._cover_scaled: QPixmap | None = None
        self._cover_key: tuple[int, int] | None = None
        self._caption = ""
        self._reduce_motion = bool(reduce_motion)
        self._colors = _default_colors()
        self.setMinimumSize(70, 110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._anim = QPropertyAnimation(self, b"level", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    # -- animated property ------------------------------------------------
    def _get_level(self) -> float:
        return self._level

    def _set_level(self, value: float) -> None:
        self._level = max(0.0, min(100.0, float(value)))
        self.update()

    level = pyqtProperty(float, _get_level, _set_level)

    # -- API --------------------------------------------------------------
    def set_level(self, percent: float, animate: bool = True) -> None:
        target = max(0.0, min(100.0, float(percent)))
        self._anim.stop()
        if self._reduce_motion or not animate or not self.isVisible():
            self.level = target
            return
        self._anim.setStartValue(self._level)
        self._anim.setEndValue(target)
        self._anim.start()

    def level_value(self) -> float:
        return self._level

    def set_caption(self, text: str) -> None:
        if text != self._caption:
            self._caption = text
            self.update()

    def set_cover(self, pixmap: QPixmap | None) -> None:
        self._cover = pixmap
        self._cover_scaled = None
        self._cover_key = None
        self.update()

    def set_reduce_motion(self, reduce: bool) -> None:
        self._reduce_motion = bool(reduce)
        if self._reduce_motion:
            self._anim.stop()

    def set_colors(self, colors: dict[str, str]) -> None:
        merged = _default_colors()
        merged.update({k: v for k, v in (colors or {}).items() if v})
        self._colors = merged
        self.update()

    # -- painting ---------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._cover_scaled = None

    def _color(self, key: str) -> QColor:
        return QColor.fromString(self._colors.get(key, "#4f8cff"))

    def _scaled_cover(self, rect: QRect) -> QPixmap | None:
        if self._cover is None or self._cover.isNull() or rect.isEmpty():
            return None
        key = (rect.width(), rect.height())
        if self._cover_scaled is not None and self._cover_key == key:
            return self._cover_scaled
        self._cover_scaled = self._cover.scaled(
            rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._cover_key = key
        return self._cover_scaled

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, self._color("bg"))

        cover = self._scaled_cover(rect)
        if cover is not None:
            painter.setOpacity(0.35)          # same dimming as the reference
            painter.drawPixmap(
                (rect.width() - cover.width()) // 2,
                (rect.height() - cover.height()) // 2, cover)
            painter.setOpacity(1.0)

        accent = self._color("accent")
        height = int(rect.height() * self._level / 100.0)
        if height > 0:
            top = rect.height() - height
            gradient = QLinearGradient(0, top, 0, rect.height())
            gradient.setColorAt(0.0, _with_alpha(accent, 77))
            gradient.setColorAt(1.0, _with_alpha(accent, 148))
            painter.fillRect(QRect(0, top, rect.width(), height), gradient)
            # Crest: solid line + soft glow above (approx. of filter: blur(3px)).
            glow_top = max(0, top - self.GLOW)
            if top > 0:
                glow = QLinearGradient(0, glow_top, 0, top)
                glow.setColorAt(0.0, _with_alpha(accent, 0))
                glow.setColorAt(1.0, _with_alpha(accent, 89))
                painter.fillRect(QRect(0, glow_top, rect.width(), top - glow_top),
                                 glow)
            painter.setPen(_with_alpha(accent, 230))
            painter.drawLine(0, top, rect.width(), top)

        self._draw_labels(painter, rect)

    def _draw_labels(self, painter: QPainter, rect: QRect) -> None:
        if not self._caption:
            return
        caption_font = QFont(painter.font())
        caption_font.setPointSize(10)
        caption_font.setBold(True)
        painter.setFont(caption_font)
        metrics = painter.fontMetrics()

        pad = 10
        box = QRectF(rect.adjusted(6, 0, -6, 0))
        width = min(metrics.horizontalAdvance(self._caption),
                    max(20, int(box.width()) - 2 * pad))
        height = metrics.height()
        box = QRectF(box.center().x() - (width + 2 * pad) / 2,
                     box.center().y() - (height + 2 * pad) / 2,
                     width + 2 * pad, height + 2 * pad)

        painter.fillRect(box, self._color("caption_bg"))
        painter.setPen(self._color("text"))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter),
                         metrics.elidedText(self._caption,
                                            Qt.TextElideMode.ElideRight,
                                            int(box.width()) - 2 * pad))
        painter.end()


def _with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(alpha)
    return result
