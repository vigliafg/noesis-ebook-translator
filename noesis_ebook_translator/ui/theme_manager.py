"""Apply the app theme to a QApplication and to the reader backends."""
from __future__ import annotations

from .. import theme as theme_mod

__all__ = ["system_is_dark", "apply_theme"]


def system_is_dark(app=None) -> bool:
    """Best-effort detection of a dark system palette."""
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QPalette
        app = app or QApplication.instance()
        if app is None:
            return False
        color = app.palette().color(QPalette.ColorRole.Window)
        return color.lightness() < 128
    except Exception:  # noqa: BLE001 - optional/headless
        return False


def apply_theme(app, mode: str, reader=None) -> str:
    """Apply ``mode`` to ``app``; optionally push it to a reader backend.

    Returns the concrete reader theme name that was applied.
    """
    system_dark = system_is_dark(app)
    app.setStyleSheet(theme_mod.stylesheet(mode, system_dark))
    reader_theme = theme_mod.reader_theme(mode, system_dark)
    if reader is not None:
        try:
            reader.set_theme(reader_theme)
        except Exception:  # noqa: BLE001 - backend is best effort
            pass
    return reader_theme
