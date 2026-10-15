"""GUI smoke tests (offscreen). Skipped when Qt/pyqtribbon are unavailable."""
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    import pyqtribbon  # noqa: F401
    _HAS_GUI = True
except Exception:  # noqa: BLE001 - optional dependency
    _HAS_GUI = False


@unittest.skipUnless(_HAS_GUI, "PyQt6 / pyqtribbon not installed")
class TestGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_builds_with_ribbon(self):
        from noesis_ebook_translator import appconfig

        appconfig.ensure_defaults()
        import main

        window = main.MainWindow()
        try:
            self.assertEqual(len(window.ribbon.categories()), 8)
            self.assertGreater(window.cmb_engine.count(), 10)
            self.assertGreater(window.cmb_target.count(), 100)
        finally:
            window.close()

    def test_engine_selection_toggles_api_key(self):
        from noesis_ebook_translator import appconfig

        appconfig.ensure_defaults()
        import main

        window = main.MainWindow()
        try:
            window.cmb_engine.setCurrentText("OpenRouter")
            self.assertTrue(window.edt_api_key.isEnabled())
            self.assertGreater(window.cmb_model.count(), 0)
        finally:
            window.close()

    def test_reader_chapter_selection(self):
        import os
        import tempfile

        from PyQt6.QtCore import Qt

        from noesis_ebook_translator import appconfig
        from tests.fixtures import build_rich_epub

        appconfig.ensure_defaults()
        import main

        path = build_rich_epub(os.path.join(tempfile.mkdtemp(), "r.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(path)
            self.assertEqual(window.reader.selected_files(), [])

            def walk(item):
                yield item
                for i in range(item.childCount()):
                    yield from walk(item.child(i))

            for i in range(window.reader.toc.topLevelItemCount()):
                for item in walk(window.reader.toc.topLevelItem(i)):
                    if item.data(0, Qt.ItemDataRole.UserRole) == "c3.xhtml":
                        item.setCheckState(0, Qt.CheckState.Checked)
            self.assertEqual(window.reader.selected_files(), ["c3.xhtml"])

            worker = main.TranslationWorker(
                path, "/tmp/x.epub", "Fake", "English", "Italian", {},
                chapters=["c3.xhtml"])
            self.assertEqual(worker.chapters, ["c3.xhtml"])
        finally:
            window.close()

    def test_reader_opens_and_navigates(self):
        import os
        import tempfile

        from noesis_ebook_translator import appconfig
        from tests.fixtures import build_sample_epub

        appconfig.ensure_defaults()
        import main

        path = build_sample_epub(os.path.join(tempfile.mkdtemp(), "s.epub"))
        window = main.MainWindow()
        try:
            self.assertEqual(window.tabs.count(), 8)
            window.reader.open_path(path)
            self.assertGreater(window.reader.toc.topLevelItemCount(), 0)
            first = window.reader.backend.current_href()
            window.reader.backend.next_chapter()
            self.assertNotEqual(window.reader.backend.current_href(), first)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
