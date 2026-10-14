"""Automated tests for both reader backends (lite always; full when possible)."""
import os
import tempfile
import unittest

from ebooklib import epub

from tests.fixtures import TINY_PNG, build_rich_epub, build_sample_epub
from tests.harness import run_reader_harness, webengine_available


def _book(tmp) -> str:
    return build_sample_epub(os.path.join(tmp, "book.epub"))


class TestLiteBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="noesis-harness-lite-")
        cls.book = _book(cls.tmp)

    def test_lite_harness_ok(self):
        report = run_reader_harness("lite", self.book)
        self.assertTrue(report.available, report.summary())
        self.assertEqual(report.backend, "LiteBackend", report.summary())
        self.assertTrue(report.opened, report.summary())
        self.assertTrue(report.navigated, report.summary())
        self.assertTrue(report.theme_ok)
        self.assertTrue(report.zoom_ok)

    def test_lite_rejects_non_epub(self):
        # Without a full backend, a non-EPUB file must not crash the harness.
        path = os.path.join(self.tmp, "note.txt")
        open(path, "w").write("hello")
        with self.assertRaises(Exception):
            run_reader_harness("lite", path)


@unittest.skipUnless(webengine_available(), "QtWebEngine not installed")
class TestFullBackend(unittest.TestCase):
    """The full backend runs in a **subprocess** (WebEngine can keep the
    interpreter alive / needs its zygote process isolated from the suite)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="noesis-harness-full-")
        cls.book = _book(cls.tmp)

    def test_full_harness(self):
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env["NOESIS_CONFIG_DIR"] = self.tmp
        env.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                       "--no-sandbox --disable-gpu --disable-software-rasterizer")
        proc = subprocess.run(
            [sys.executable, str(root / "tools" / "reader_harness.py"),
             "--mode", "full", "--wait", "10", self.book],
            capture_output=True, text=True, timeout=120, env=env)
        line = next((ln for ln in proc.stdout.splitlines()
                     if ln.startswith("[full]")), "")
        if "ready=True" not in line:
            self.skipTest(f"WebEngine not ready in this environment: {line.strip()}")
        self.assertIn("opened=True", line)


class TestFormatAwareness(unittest.TestCase):
    def test_full_backend_declares_extra_formats(self):
        # Run in a subprocess so WebEngine never loads inside the suite.
        import subprocess
        import sys
        from pathlib import Path

        if not webengine_available():
            self.skipTest("QtWebEngine not installed")
        root = Path(__file__).resolve().parent.parent
        tmp = tempfile.mkdtemp(prefix="noesis-harness-fmt-")
        book = _book(tmp)
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["NOESIS_CONFIG_DIR"] = tmp
        proc = subprocess.run(
            [sys.executable, str(root / "tools" / "reader_harness.py"),
             "--mode", "full", "--wait", "6", book],
            capture_output=True, text=True, timeout=90, env=env)
        line = next((ln for ln in proc.stdout.splitlines()
                     if ln.startswith("[full]")), "")
        if "backend=WebEngineBackend" not in line:
            self.skipTest(f"WebEngine unavailable: {line.strip()}")
        for ext in (".mobi", ".azw3", ".fb2", ".cbz", ".pdf"):
            self.assertIn(ext, line)


class TestGuiPanelsHarness(unittest.TestCase):
    def test_panels_populate(self):
        try:
            from PyQt6.QtWidgets import QApplication
        except Exception:  # noqa: BLE001
            self.skipTest("PyQt6 not installed")
        from noesis_ebook_translator import appconfig
        appconfig.ensure_defaults()
        app = QApplication.instance() or QApplication(["noesis-harness"])
        import main

        tmp = tempfile.mkdtemp(prefix="noesis-harness-panels-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)
            self.assertGreaterEqual(window.reader.toc.topLevelItemCount(), 1)
            window.figures.load_current()
            self.assertEqual(window.figures.list.count(), 1)
            window.tables.load_current()
            self.assertEqual(window.tables.cmb.count(), 1)
            self.assertGreaterEqual(len(window.library.session.recent()), 1)
        finally:
            window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
