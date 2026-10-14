"""Qt stylesheet themes for the desktop app (pure module, no Qt import)."""
from __future__ import annotations

__all__ = ["MODES", "normalize_mode", "stylesheet", "is_dark"]

MODES = ("system", "light", "dark")

_LIGHT = """
QWidget { background: #f6f7f9; color: #1c1e21; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: #ffffff; border: 1px solid #d0d3d9; border-radius: 4px;
    padding: 3px 6px; selection-background-color: #2d6cdf;
}
QPushButton { background: #e7e9ee; border: 1px solid #cfd3da; border-radius: 4px;
    padding: 4px 10px; }
QPushButton:hover { background: #dfe3ea; }
QProgressBar { border: 1px solid #cfd3da; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #2d6cdf; }
QGroupBox { border: 1px solid #d5d8de; border-radius: 6px; margin-top: 10px;
    padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
"""

_DARK = """
QWidget { background: #1f2227; color: #e8eaed; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: #2a2e35; border: 1px solid #3a3f47; border-radius: 4px;
    padding: 3px 6px; color: #e8eaed; selection-background-color: #4c8bf5;
}
QPushButton { background: #313640; border: 1px solid #3f4550; border-radius: 4px;
    padding: 4px 10px; color: #e8eaed; }
QPushButton:hover { background: #3a404b; }
QProgressBar { border: 1px solid #3f4550; border-radius: 4px; text-align: center;
    color: #e8eaed; }
QProgressBar::chunk { background: #4c8bf5; }
QGroupBox { border: 1px solid #3a3f47; border-radius: 6px; margin-top: 10px;
    padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QPlainTextEdit { font-family: monospace; }
"""


def normalize_mode(mode: str) -> str:
    return mode if mode in MODES else "system"


def is_dark(mode: str, system_dark: bool = True) -> bool:
    mode = normalize_mode(mode)
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return system_dark


def stylesheet(mode: str, system_dark: bool = True) -> str:
    return _DARK if is_dark(mode, system_dark) else _LIGHT
