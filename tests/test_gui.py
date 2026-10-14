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
            self.assertEqual(len(window.ribbon.categories()), 5)
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


if __name__ == "__main__":
    unittest.main()
