"""End-to-end GUI feature harness + widget-level tests for the new features."""
import os
import tempfile
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    import pyqtribbon  # noqa: F401
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import build_rich_epub
from tests.harness import run_feature_harness


@unittest.skipUnless(_HAS_GUI, "PyQt6 / pyqtribbon not installed")
class TestFeatureHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-features"])
        cls.tmp = tempfile.mkdtemp(prefix="noesis-features-")
        cls.book = build_rich_epub(os.path.join(cls.tmp, "rich.epub"))

    def test_feature_harness(self):
        report = run_feature_harness(self.book, app=self.app)
        self.assertTrue(report.available, report.summary())
        self.assertTrue(report.window_built, report.summary())
        self.assertEqual(report.tabs, 8, report.summary())
        self.assertEqual(report.categories, 8, report.summary())
        self.assertGreaterEqual(report.figures, 1, report.summary())
        self.assertGreaterEqual(report.tables, 1, report.summary())
        self.assertGreaterEqual(report.texts, 1, report.summary())
        self.assertGreaterEqual(report.chapters, 1, report.summary())
        self.assertTrue(report.theme_ok, report.summary())
        self.assertTrue(report.library_ok, report.summary())
        self.assertTrue(report.settings_ok, report.summary())


@unittest.skipUnless(_HAS_GUI, "PyQt6 / pyqtribbon not installed")
class TestWidgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-widgets"])

    def test_shimmer_reduce_motion(self):
        from noesis_ebook_translator.ui.animations import ShimmerBar

        moving = ShimmerBar(reduce_motion=False)
        moving.set_busy(True)
        self.assertTrue(moving.is_animating())
        moving.set_busy(False)
        self.assertFalse(moving.is_animating())

        still = ShimmerBar(reduce_motion=True)
        still.set_busy(True)
        self.assertFalse(still.is_animating())
        still.setValue(50)
        self.assertEqual(still.value(), 50)

    def test_dots_label(self):
        from noesis_ebook_translator.ui.animations import DotsLabel

        label = DotsLabel("Loading", reduce_motion=True)
        label.start_busy()
        self.assertEqual(label.text(), "Loading")
        self.assertFalse(label.is_animating())

    def test_wizard_applies_settings(self):
        from noesis_ebook_translator.ui.wizard import OnboardingWizard
        from noesis_ebook_translator import appconfig

        wizard = OnboardingWizard()
        try:
            wizard.cmb_language.setCurrentIndex(
                wizard.cmb_language.findData("en"))
            values = wizard.apply()
            self.assertEqual(values["ui_language"], "en")
            self.assertTrue(values["onboarding_done"])
            self.assertTrue(appconfig.load_settings().get("onboarding_done"))
        finally:
            wizard.close()

    def test_help_dialog_builds(self):
        from noesis_ebook_translator.ui.help_dialog import HelpDialog

        dialog = HelpDialog("it")
        try:
            self.assertIn("/it/", dialog.url())
            self.assertIn("Aiuto", dialog.browser.toPlainText())
        finally:
            dialog.close()

    def test_export_dialog_builds(self):
        from noesis_ebook_translator.ui.export_dialog import ExportDialog

        tmp = tempfile.mkdtemp(prefix="noesis-exportdlg-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        dialog = ExportDialog(book, None)
        try:
            self.assertGreater(dialog.cmb_format.count(), 3)
            # "translated" edition is hidden when there is no translation
            self.assertEqual(dialog.cmb_edition.count(), 1)
        finally:
            dialog.close()


class TestPaths(unittest.TestCase):
    def test_data_dir_respects_env(self):
        import os as _os
        from noesis_ebook_translator import paths

        old = _os.environ.get("NOESIS_CONFIG_DIR")
        try:
            _os.environ["NOESIS_CONFIG_DIR"] = "/tmp/noesis-paths-check"
            self.assertEqual(str(paths.data_dir()), "/tmp/noesis-paths-check/"
                             "noesis-ebook-translator")
            self.assertTrue(str(paths.data_file("x.db")).endswith("x.db"))
        finally:
            if old is None:
                _os.environ.pop("NOESIS_CONFIG_DIR", None)
            else:
                _os.environ["NOESIS_CONFIG_DIR"] = old


if __name__ == "__main__":
    unittest.main()
