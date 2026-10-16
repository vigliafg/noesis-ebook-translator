"""Subprocess entry points whose **stderr** is asserted by the test suite.

PyQt prints an exception raised inside a slot and keeps going, and Chromium
warns on stderr; neither fails an ordinary test. Running these paths in a
subprocess lets ``tests/test_console_clean.py`` read the stream and fail on the
noise, which is how the reported ``AttributeError`` and the WebEngine warnings
went unnoticed for so long.

Usage: ``python -m tests.console_probe <gui|engine|reader>``.
"""
from __future__ import annotations

import os
import sys
import tempfile


def _probe_gui() -> int:
    """Start the app, open a book, touch the dirty signal paths, close it."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("NOESIS_READER_BACKEND", "lite")
    os.environ.setdefault("NOESIS_CONFIG_DIR",
                          tempfile.mkdtemp(prefix="noesis-probe-gui-"))

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["noesis-probe-gui"])

    import main
    main.QMessageBox.information = staticmethod(lambda *a, **k: None)
    main.QMessageBox.warning = staticmethod(lambda *a, **k: None)

    from tests.fixtures import build_rich_epub
    tmp = tempfile.mkdtemp(prefix="noesis-probe-book-")
    book = build_rich_epub(os.path.join(tmp, "probe.epub"))

    window = main.MainWindow()
    window._apply_source(book)
    for _ in range(10):
        app.processEvents()

    # Signal paths that carry no item (the reported AttributeError).
    window.library._open_item(None)
    window.library._open_item()
    window.library.edt_filter.setText("zzz")
    window.library.refresh()
    window.library.edt_filter.clear()
    window.set_library_view("translated")
    window.set_library_view("chapters")
    window.set_library_view("original")
    for _ in range(10):
        app.processEvents()

    # Closing must release the reader (no "Release of profile" warning).
    window.close()
    for _ in range(10):
        app.processEvents()
    print("PROBE gui: ok")
    return 0


def _probe_engine() -> int:
    """Run a real translation through the offline engine."""
    os.environ.setdefault("NOESIS_CONFIG_DIR",
                          tempfile.mkdtemp(prefix="noesis-probe-engine-"))
    from tests.fixtures import build_rich_epub, register_fake_engine

    register_fake_engine()
    from noesis_ebook_translator import book

    tmp = tempfile.mkdtemp(prefix="noesis-probe-engine-book-")
    src = build_rich_epub(os.path.join(tmp, "probe.epub"))
    book.translate_epub(
        src, os.path.join(tmp, "probe_out.epub"), engine="Fake",
        source_lang="English", target_lang="Italian",
        settings={"translation_position": "only", "cache_enabled": True})
    print("PROBE engine: ok")
    return 0


def _probe_reader() -> int:
    """Open a book in the full WebEngine reader and tear it down."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["NOESIS_READER_BACKEND"] = "full"
    os.environ.setdefault("NOESIS_CONFIG_DIR",
                          tempfile.mkdtemp(prefix="noesis-probe-reader-"))
    from tests.fixtures import build_rich_epub
    from tests.harness import run_reader_harness

    tmp = tempfile.mkdtemp(prefix="noesis-probe-reader-book-")
    book = build_rich_epub(os.path.join(tmp, "probe.epub"))
    report = run_reader_harness("full", book, wait=20.0)
    print(f"PROBE reader: {report.summary()}")
    return 0 if report.ok else 1


_PROBES = {"gui": _probe_gui, "engine": _probe_engine, "reader": _probe_reader}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in _PROBES:
        print(f"usage: python -m tests.console_probe {{{'|'.join(_PROBES)}}}",
              file=sys.stderr)
        return 2
    return _PROBES[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
