"""Backend-agnostic reader harness.

Runs the same scenario against the **lite** (`QTextBrowser`) and **full**
(`QWebEngineView` + foliate-js) readers and returns a structured report. Used by
``tests/test_reader_backends.py`` and by the standalone
``tools/reader_harness.py`` (handy for validating the full backend on a desktop).

The full backend needs a working WebEngine (GPU/display). When the page does not
come up (e.g. a headless CI without the Chromium flags), the report marks
``ready = False`` instead of hanging.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

__all__ = ["ReaderReport", "run_reader_harness", "webengine_available",
           "FeatureReport", "run_feature_harness"]


def webengine_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("PyQt6.QtWebEngineWidgets") is not None


@dataclass
class ReaderReport:
    mode: str
    available: bool = False
    backend: str | None = None
    opened: bool = False
    ready: bool = False
    navigated: bool = False
    theme_ok: bool = False
    zoom_ok: bool = False
    find_ok: bool = False
    formats: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.available and self.opened and self.navigated

    def summary(self) -> str:
        return (f"mode={self.mode} backend={self.backend} available={self.available} "
                f"opened={self.opened} ready={self.ready} navigated={self.navigated} "
                f"theme={self.theme_ok} zoom={self.zoom_ok} find={self.find_ok} "
                f"formats={','.join(self.formats)}"
                + (f" notes={self.notes}" if self.notes else ""))


def _app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["noesis-harness"])


def run_reader_harness(mode: str, book_path: str, *, wait: float = 20.0,
                       app=None) -> ReaderReport:
    report = ReaderReport(mode=mode)
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--no-sandbox --disable-gpu --disable-software-rasterizer")

    try:
        from noesis_ebook_translator.reader import create_backend, prepare_full
        if mode == "full":
            prepare_full()
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"prepare_full: {exc}")

    app = app or _app()
    try:
        backend = create_backend(mode)
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"create_backend: {type(exc).__name__}: {exc}")
        return report

    report.available = True
    report.backend = type(backend).__name__
    report.formats = sorted(getattr(backend, "supported_extensions", []) or [])

    from noesis_ebook_translator.reader.document import EpubDocument
    doc = EpubDocument(book_path)
    backend.open_document(doc)

    # Wait until the view is usable.
    deadline = time.time() + wait
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
        if backend.current_href():
            report.opened = True
            break
        if getattr(backend, "_ready", False):
            report.ready = True
            report.opened = True
            break
    report.ready = report.ready or report.opened

    first = backend.current_href()
    try:
        backend.set_theme("dark")
        report.theme_ok = True
        backend.set_zoom(1)
        report.zoom_ok = True
        report.find_ok = bool(backend.find("the"))
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"controls: {exc}")

    backend.next_chapter()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    current = backend.current_href()
    if current and first:
        report.navigated = current != first
    elif current and not first:
        report.navigated = True
    if not report.navigated and mode == "full" and not report.ready:
        report.notes.append("full backend not ready (headless/GPU?)")

    return report


@dataclass
class FeatureReport:
    """Result of exercising the new GUI features on a real book."""

    mode: str
    available: bool = False
    window_built: bool = False
    tabs: int = 0
    categories: int = 0
    figures: int = 0
    tables: int = 0
    texts: int = 0
    chapters: int = 0
    theme_ok: bool = False
    library_ok: bool = False
    settings_ok: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.available and self.window_built and self.figures >= 1
                and self.tables >= 1 and self.chapters >= 1 and self.theme_ok)

    def summary(self) -> str:
        return (f"mode={self.mode} available={self.available} "
                f"built={self.window_built} tabs={self.tabs} cats={self.categories} "
                f"figures={self.figures} tables={self.tables} texts={self.texts} "
                f"chapters={self.chapters} theme={self.theme_ok} "
                f"library={self.library_ok} settings={self.settings_ok}"
                + (f" notes={self.notes}" if self.notes else ""))


def run_feature_harness(book_path: str, *, app=None) -> FeatureReport:
    """Exercise the new GUI features (tabs, panels, theme, library, settings)."""
    report = FeatureReport(mode="gui")
    try:
        from PyQt6.QtWidgets import QApplication
        app = app or (QApplication.instance() or QApplication(["noesis-features"]))
        import pyqtribbon  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - optional dependency
        report.notes.append(f"qt unavailable: {exc}")
        return report

    from noesis_ebook_translator import appconfig
    appconfig.ensure_defaults()
    import main

    report.available = True
    window = main.MainWindow()
    try:
        report.window_built = True
        report.tabs = window.tabs.count()
        report.categories = len(window.ribbon.categories())
        window._apply_source(book_path)
        window.figures.load_current()
        window.tables.load_current()
        window.texts.load_current()
        window.chapters.load_current()
        report.figures = window.figures.list.count()
        report.tables = window.tables.cmb.count()
        report.texts = window.texts.list.count()
        report.chapters = window.chapters.list.count()
        # theme switching must not raise and must update the stylesheet
        index = (window.cmb_theme.currentIndex() + 1) % window.cmb_theme.count()
        window.cmb_theme.setCurrentIndex(index)
        report.theme_ok = bool(app.styleSheet())
        report.library_ok = len(window.reader.session.recent()) >= 1
        # settings dialog can be built and read
        from noesis_ebook_translator.ui import SettingsDialog
        dialog = SettingsDialog(window)
        report.settings_ok = bool(dialog.changes().get("ui_theme"))
        dialog.close()
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"{type(exc).__name__}: {exc}")
    finally:
        window.close()
        app.processEvents()
    return report
