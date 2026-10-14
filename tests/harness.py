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

__all__ = ["ReaderReport", "run_reader_harness", "webengine_available"]


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
