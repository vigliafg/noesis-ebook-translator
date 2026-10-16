"""The book toast: pill with the book being worked on, in the workflow bar."""
import os
import tempfile
import time
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import build_rich_epub


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestBookToast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-toast"])

    def _toast(self, reduce_motion=False):
        from noesis_ebook_translator.ui.book_toast import BookToast

        return BookToast(reduce_motion=reduce_motion)

    def test_text_percent_and_visibility(self):
        toast = self._toast()
        try:
            self.assertEqual(toast.text(), "")
            toast.set_text("Storia illustrata del libro")
            toast.set_percent(39)
            self.assertEqual(toast.text(), "Storia illustrata del libro")
            self.assertEqual(toast.percent(), 39)
            self.assertEqual(toast.toolTip(), "Storia illustrata del libro")
            # The text must fit in the pill (it is elided, not cut by accident).
            self.assertGreaterEqual(toast.sizeHint().width(),
                                    toast.fontMetrics().horizontalAdvance(
                                        toast.text()))
        finally:
            toast.close()

    def test_sheen_sweeps_only_while_working(self):
        toast = self._toast()
        try:
            toast.set_text("Libro")
            toast.show()
            self.app.processEvents()
            self.assertFalse(toast.is_animating())
            toast.set_working(True)
            self.app.processEvents()
            self.assertTrue(toast.is_animating())
            # The reflection must actually travel (0 -> 1, same as the cloner).
            lowest = highest = toast.sheenPos
            deadline = time.time() + 3.0
            while time.time() < deadline and (highest - lowest) < 0.6:
                self.app.processEvents()
                lowest = min(lowest, toast.sheenPos)
                highest = max(highest, toast.sheenPos)
                time.sleep(0.02)
            self.assertGreater(highest - lowest, 0.6, "the sheen must sweep")
            toast.set_working(False)
            self.assertFalse(toast.is_animating())
            self.assertEqual(toast.sheenPos, 0.0)
        finally:
            toast.hide()
            toast.close()

    def test_sheen_is_visible_in_the_painted_pill(self):
        """The reflection must change the pixels (a real, visible band)."""
        toast = self._toast()
        try:
            toast.set_text("Storia illustrata del libro")
            toast.resize(toast.sizeHint())
            toast.set_working(True)
            toast.show()
            self.app.processEvents()
            toast._set_sheen_pos(0.0)
            self.app.processEvents()
            start = toast.grab().toImage()
            toast._set_sheen_pos(0.55)      # the band right on the pill
            self.app.processEvents()
            middle = toast.grab().toImage()
            toast._set_sheen_pos(0.99)
            self.app.processEvents()
            end = toast.grab().toImage()
            self.assertNotEqual(start, middle)
            self.assertNotEqual(middle, end)
        finally:
            toast.hide()
            toast.close()

    def test_reduce_motion_keeps_the_pill_still(self):
        toast = self._toast(reduce_motion=True)
        try:
            toast.set_text("Libro")
            toast.set_working(True)
            toast.show()
            self.app.processEvents()
            self.assertFalse(toast.is_animating())
            self.assertEqual(toast.sheenPos, 0.0)
        finally:
            toast.hide()
            toast.close()

    def test_colours_per_theme(self):
        from noesis_ebook_translator.ui.book_toast import PALETTES

        toast = self._toast()
        try:
            toast.set_theme("light", False)
            self.assertEqual(toast._colors, PALETTES["light"])
            self.assertEqual(toast._colors["fg"], "#ffffff")
            toast.set_theme("dark", True)
            self.assertEqual(toast._colors, PALETTES["dark"])
            # Yellow with a black foreground on the dark theme.
            self.assertEqual(toast._colors["bg"], "#ffd60a")
            self.assertEqual(toast._colors["fg"], "#101418")
            # "system" follows the system palette.
            toast.set_theme("system", True)
            self.assertEqual(toast._colors, PALETTES["dark"])
            toast.set_theme("system", False)
            self.assertEqual(toast._colors, PALETTES["light"])
        finally:
            toast.close()

    def test_renders_without_errors(self):
        toast = self._toast()
        try:
            toast.set_text("Storia illustrata del libro")
            toast.set_percent(39)
            toast.set_working(True)
            toast.resize(300, 42)
            toast.show()
            self.app.processEvents()
            self.assertFalse(toast.grab().isNull())
        finally:
            toast.hide()
            toast.close()

    def test_bar_centres_the_pill_between_tabs_and_gear(self):
        import main

        app = QApplication.instance() or QApplication(["noesis-toast"])
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        tmp = tempfile.mkdtemp(prefix="noesis-toast-")
        epub_path = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window.resize(1500, 300)
            window.show()
            for _ in range(6):
                app.processEvents()
            bar = window.workflow
            # Hidden while no book is open.
            self.assertFalse(bar.book_toast.isVisible())
            # Layout: ... tabs | stretch | toast | stretch | settings
            layout = bar.layout().itemAt(0).widget().layout()
            kinds = []
            for index in range(layout.count()):
                widget = layout.itemAt(index).widget()
                kinds.append(type(widget).__name__ if widget else "stretch")
            self.assertEqual(kinds, ["QToolButton", "QTabBar", "stretch",
                                     "BookToast", "stretch", "WorkflowButton"])

            window._apply_source(epub_path)
            for _ in range(6):
                app.processEvents()
            toast = bar.book_toast
            self.assertTrue(toast.isVisible())
            self.assertEqual(toast.text(), "The Rich Test")   # EPUB metadata
            # Centred in the free space between the last tab and the gear.
            free_left = bar.tabs.x() + bar.tabs.width()
            free_right = bar.btn_settings.x()
            centre = toast.x() + toast.width() // 2
            self.assertAlmostEqual(centre, (free_left + free_right) / 2,
                                   delta=12)
        finally:
            window.close()

    def test_chapters_message_with_and_without_cache(self):
        import main

        app = QApplication.instance() or QApplication(["noesis-toast"])
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        try:
            plain = window._chapters_message({"done": 3, "total": 3,
                                              "cached": 0})
            self.assertIn("3/3", plain)
            cached = window._chapters_message({"done": 3, "total": 3,
                                               "cached": 2})
            self.assertIn("3/3", cached)
            self.assertIn("2", cached)
            self.assertNotEqual(plain, cached)
            # Nothing to report on an empty/unknown model.
            self.assertEqual(window._chapters_message({}), "")
            self.assertEqual(window._chapters_message({"done": 0, "total": 0}),
                             "")
        finally:
            window.close()

    def test_translation_run_drives_the_pill(self):
        import main
        from tests.fixtures import register_fake_engine

        register_fake_engine()
        app = QApplication.instance() or QApplication(["noesis-toast"])
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        tmp = tempfile.mkdtemp(prefix="noesis-toast-run-")
        epub_path = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(epub_path)
            window._start_translation({
                "engine": "Fake", "source": "English", "target": "Italian",
                "batching": False, "cache": True, "sequential": True,
                "chapters": [], "grouping": "grouped", "folder": tmp,
                "name": "out.epub", "bilingual": False})
            self.assertTrue(window.workflow.book_toast.is_working())
            deadline = time.time() + 60
            while window.worker is not None and time.time() < deadline:
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            toast = window.workflow.book_toast
            self.assertFalse(toast.is_working())
            self.assertEqual(toast.percent(), 100)
            # The completion notice tells the user how many chapters were
            # translated and how many came from the cache.
            summary = window.translate_view.model().summary()
            self.assertEqual(summary["done"], summary["total"])
            self.assertGreaterEqual(summary["total"], 1)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
