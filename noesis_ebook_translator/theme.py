"""Qt stylesheet themes for the desktop app (pure module, no Qt import).

The app exposes a small registry of themes; each theme provides a Qt stylesheet
(for the whole window) and, optionally, a matching reader theme name understood
by the reader backends (``light``/``sepia``/``dark``).
"""
from __future__ import annotations

__all__ = [
    "THEMES", "MODES", "THEME_LABELS", "normalize_mode", "is_dark",
    "reader_theme", "stylesheet", "theme_choices", "theme_label", "palette",
    "liquid",
]

#: Ordered theme ids shown in the UI.
THEMES = ("system", "light", "dark", "sepia")

#: Backwards-compatible alias (older callers imported ``MODES``).
MODES = THEMES

#: Human-readable labels (English; the GUI may translate them via ``T()``).
THEME_LABELS = {
    "system": "System",
    "light": "Light",
    "dark": "Dark",
    "sepia": "Sepia",
}

#: Reader theme used by the backends for each app theme. ``system`` resolves to
#: light/dark at runtime, so the reader theme is picked dynamically in the GUI.
_READER_THEME = {
    "system": None,
    "light": "light",
    "dark": "dark",
    "sepia": "sepia",
}

#: Foreground/background hints for embedding (e.g. generated HTML exports).
_PALETTES = {
    "light": {"background": "#f6f7f9", "foreground": "#1c1e21",
              "accent": "#2d6cdf", "surface": "#ffffff"},
    "dark": {"background": "#1f2227", "foreground": "#e8eaed",
             "accent": "#4c8bf5", "surface": "#2a2e35"},
    "sepia": {"background": "#f4ecd8", "foreground": "#4a3f2f",
              "accent": "#a06a2c", "surface": "#fbf3e0"},
}

#: Colours of the "liquid" progress fill (cover + rising water). Copied from the
#: sibling project ``noesis-pdf-cloner`` (``LiquidOverlay`` /
#: ``.liquid``) so the two apps look alike: same blue, same soft transition.
_LIQUID = {
    "dark": {"bg": "#ee0b0e13", "caption_bg": "#e6141414",
             "text": "#ffffff", "accent": "#4f8cff"},
    "light": {"bg": "#e6f2f3f5", "caption_bg": "#e6ffffff",
              "text": "#1c2430", "accent": "#4f8cff"},
    "sepia": {"bg": "#e6f4ecd8", "caption_bg": "#e6fbf3e0",
              "text": "#4a3f2f", "accent": "#4f8cff"},
}

_LIGHT = """
QWidget { background: #f6f7f9; color: #1c1e21; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QTextEdit, QTextBrowser {
    background: #ffffff; border: 1px solid #d0d3d9; border-radius: 4px;
    padding: 3px 6px; selection-background-color: #2d6cdf;
}
QPushButton { background: #e7e9ee; border: 1px solid #cfd3da; border-radius: 4px;
    padding: 4px 10px; }
QPushButton:hover { background: #dfe3ea; }
QPushButton:pressed { background: #d3d8e0; }
QPushButton:checked { background: #c9d6f2; border-color: #2d6cdf; }
QProgressBar { border: 1px solid #cfd3da; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #2d6cdf; border-radius: 3px; }
QGroupBox { border: 1px solid #d5d8de; border-radius: 6px; margin-top: 10px;
    padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QTabWidget::pane { border: 1px solid #d5d8de; border-radius: 6px; }
QTabBar::tab { background: #e7e9ee; padding: 5px 12px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #ffffff; border-bottom: 2px solid #2d6cdf; }
QListWidget, QTreeWidget, QTableWidget { background: #ffffff;
    border: 1px solid #d0d3d9; border-radius: 4px; }
QHeaderView::section { background: #eceef2; border: 0; padding: 4px; }
#workflowBar { background: #f6f7f9; border-bottom: 1px solid #d5d8de; }
#sectionBar::tab { background: transparent; color: #1c1e21; padding: 4px 12px;
    margin: 2px; border-radius: 5px; }
#sectionBar::tab:selected { background: #2d6cdf; color: #ffffff; }
#sectionBar::tab:hover:!selected { background: #e3e6ec; }
#sectionPage { background: #f6f7f9; }
#workflowBar QToolButton { color: #1c1e21; padding: 4px 8px; border-radius: 5px; }
#workflowBar QToolButton:hover { background: #e3e6ec; }
#workflowBar QToolButton:checked { background: #c9d6f2; }
#translateView { background: #f6f7f9; }
#bandTitle { color: #5c6674; font-weight: 600; }
#bandHint { color: #5c6674; }
#detailTitle { font-size: 15px; font-weight: 600; }
#detailCount { font-size: 19px; font-weight: 600; }
#detailText { color: #5c6674; }
"""

_DARK = """
QWidget { background: #1f2227; color: #e8eaed; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QTextEdit, QTextBrowser {
    background: #2a2e35; border: 1px solid #3a3f47; border-radius: 4px;
    padding: 3px 6px; color: #e8eaed; selection-background-color: #4c8bf5;
}
QPushButton { background: #313640; border: 1px solid #3f4550; border-radius: 4px;
    padding: 4px 10px; color: #e8eaed; }
QPushButton:hover { background: #3a404b; }
QPushButton:pressed { background: #2b303a; }
QPushButton:checked { background: #2f4772; border-color: #4c8bf5; }
QProgressBar { border: 1px solid #3f4550; border-radius: 4px; text-align: center;
    color: #e8eaed; }
QProgressBar::chunk { background: #4c8bf5; border-radius: 3px; }
QGroupBox { border: 1px solid #3a3f47; border-radius: 6px; margin-top: 10px;
    padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QTabWidget::pane { border: 1px solid #3a3f47; border-radius: 6px; }
QTabBar::tab { background: #313640; padding: 5px 12px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #1f2227; border-bottom: 2px solid #4c8bf5; }
QListWidget, QTreeWidget, QTableWidget { background: #262a30;
    border: 1px solid #3a3f47; border-radius: 4px; }
QHeaderView::section { background: #313640; border: 0; padding: 4px; }
QPlainTextEdit { font-family: monospace; }
#workflowBar { background: #1f2227; border-bottom: 1px solid #3a3f47; }
#sectionBar::tab { background: transparent; color: #e8eaed; padding: 4px 12px;
    margin: 2px; border-radius: 5px; }
#sectionBar::tab:selected { background: #4c8bf5; color: #ffffff; }
#sectionBar::tab:hover:!selected { background: #313640; }
#sectionPage { background: #1f2227; }
#workflowBar QToolButton { color: #e8eaed; padding: 4px 8px; border-radius: 5px; }
#workflowBar QToolButton:hover { background: #313640; }
#workflowBar QToolButton:checked { background: #2f4772; }
#translateView { background: #1f2227; }
#bandTitle { color: #9aa4b2; font-weight: 600; }
#bandHint { color: #9aa4b2; }
#detailTitle { font-size: 15px; font-weight: 600; }
#detailCount { font-size: 19px; font-weight: 600; }
#detailText { color: #9aa4b2; }
"""

_SEPIA = """
QWidget { background: #f4ecd8; color: #4a3f2f; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QTextEdit, QTextBrowser {
    background: #fbf3e0; border: 1px solid #d8c9a6; border-radius: 4px;
    padding: 3px 6px; color: #4a3f2f; selection-background-color: #a06a2c;
}
QPushButton { background: #ecdfc2; border: 1px solid #d0bd93; border-radius: 4px;
    padding: 4px 10px; color: #4a3f2f; }
QPushButton:hover { background: #e5d5b3; }
QPushButton:checked { background: #dcc79b; border-color: #a06a2c; }
QProgressBar { border: 1px solid #d0bd93; border-radius: 4px; text-align: center;
    color: #4a3f2f; }
QProgressBar::chunk { background: #a06a2c; border-radius: 3px; }
QGroupBox { border: 1px solid #d8c9a6; border-radius: 6px; margin-top: 10px;
    padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QTabWidget::pane { border: 1px solid #d8c9a6; border-radius: 6px; }
QTabBar::tab { background: #ecdfc2; padding: 5px 12px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #fbf3e0; border-bottom: 2px solid #a06a2c; }
QListWidget, QTreeWidget, QTableWidget { background: #fbf3e0;
    border: 1px solid #d8c9a6; border-radius: 4px; }
QHeaderView::section { background: #ecdfc2; border: 0; padding: 4px; }
#workflowBar { background: #f4ecd8; border-bottom: 1px solid #d8c9a6; }
#sectionBar::tab { background: transparent; color: #4a3f2f; padding: 4px 12px;
    margin: 2px; border-radius: 5px; }
#sectionBar::tab:selected { background: #a06a2c; color: #ffffff; }
#sectionBar::tab:hover:!selected { background: #e5d5b3; }
#sectionPage { background: #f4ecd8; }
#workflowBar QToolButton { color: #4a3f2f; padding: 4px 8px; border-radius: 5px; }
#workflowBar QToolButton:hover { background: #e5d5b3; }
#workflowBar QToolButton:checked { background: #dcc79b; }
#translateView { background: #f4ecd8; }
#bandTitle { color: #7a6a52; font-weight: 600; }
#bandHint { color: #7a6a52; }
#detailTitle { font-size: 15px; font-weight: 600; }
#detailCount { font-size: 19px; font-weight: 600; }
#detailText { color: #7a6a52; }
"""

_SHEETS = {"light": _LIGHT, "dark": _DARK, "sepia": _SEPIA}


def normalize_mode(mode: str) -> str:
    return mode if mode in THEMES else "system"


def is_dark(mode: str, system_dark: bool = True) -> bool:
    mode = normalize_mode(mode)
    if mode == "dark":
        return True
    if mode in ("light", "sepia"):
        return False
    return system_dark


def reader_theme(mode: str, system_dark: bool = True) -> str:
    """Return the concrete reader theme name for an app theme id."""
    mode = normalize_mode(mode)
    if mode == "system":
        return "dark" if system_dark else "light"
    return _READER_THEME.get(mode) or "light"


def palette(mode: str, system_dark: bool = True) -> dict:
    effective = "dark" if is_dark(mode, system_dark) else (
        "sepia" if normalize_mode(mode) == "sepia" else "light")
    return dict(_PALETTES[effective])


def liquid(mode: str, system_dark: bool = True) -> dict:
    """Colours for the liquid progress widget (app theme, not reader theme)."""
    effective = "dark" if is_dark(mode, system_dark) else (
        "sepia" if normalize_mode(mode) == "sepia" else "light")
    return dict(_LIQUID[effective])


def stylesheet(mode: str, system_dark: bool = True) -> str:
    mode = normalize_mode(mode)
    if mode == "system":
        mode = "dark" if system_dark else "light"
    return _SHEETS.get(mode, _LIGHT)


def theme_choices() -> list[str]:
    return list(THEMES)


def theme_label(mode: str) -> str:
    return THEME_LABELS.get(normalize_mode(mode), mode)
