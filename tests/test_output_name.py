"""The output-name convention and the overwrite guard.

The wizard's name field is just the *base*: the app always appends
``-<target language>`` and forces ``.epub``, and it asks before overwriting an
existing file. Before this, the wizard's default name produced the very path of
the original book, so pressing Finish replaced it.
"""
import hashlib
import os
import tempfile
import time
import unittest

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import build_sample_epub, register_fake_engine


class TestOutputName(unittest.TestCase):
    def test_the_language_suffix_is_always_appended(self):
        from noesis_ebook_translator.book import output_name

        self.assertEqual(output_name("Dune", "Italian"), "Dune-italian.epub")
        # The rule is literal: a name that already has it gets a second one, so
        # the output can never silently become the input again.
        self.assertEqual(output_name("Dune-italian", "Italian"),
                         "Dune-italian-italian.epub")

    def test_the_extension_is_forced_to_epub(self):
        from noesis_ebook_translator.book import output_name

        self.assertEqual(output_name("Dune.epub", "Italian"), "Dune-italian.epub")
        self.assertEqual(output_name("Dune.txt", "Italian"), "Dune-italian.epub")
        self.assertEqual(output_name("", "Italian"), "book-italian.epub")

    def test_language_names_are_slugged(self):
        from noesis_ebook_translator.book import language_slug, output_name

        self.assertEqual(language_slug("Italian"), "italian")
        self.assertEqual(language_slug("Chinese (Simplified)"),
                         "chinese-simplified")
        self.assertEqual(language_slug("Portuguese (Brazil)"),
                         "portuguese-brazil")
        self.assertEqual(language_slug("Ndebele (South)"), "ndebele-south")
        self.assertEqual(language_slug(""), "translated")
        self.assertEqual(output_name("Atlas", "Batak Karo"),
                         "Atlas-batak-karo.epub")

    def test_a_folder_in_the_name_is_ignored(self):
        from noesis_ebook_translator.book import output_name

        self.assertEqual(output_name("/tmp/../Dune", "Italian"),
                         "Dune-italian.epub")


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestOutputPathInTheApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-name"])
        cls.tmp = tempfile.mkdtemp(prefix="noesis-name-")
        register_fake_engine()

    def setUp(self):
        import main

        self.folder = tempfile.mkdtemp(prefix="noesis-name-book-")
        self.book = build_sample_epub(os.path.join(self.folder, "Dune.epub"))
        self.question = QMessageBox.question
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)

    def tearDown(self):
        QMessageBox.question = self.question

    def _cfg(self, **overrides):
        cfg = {"engine": "Fake", "source": "English", "target": "Italian",
               "batching": False, "cache": False, "sequential": True,
               "chapters": [], "grouping": "grouped", "folder": self.folder,
               "name": "Dune", "bilingual": False}
        cfg.update(overrides)
        return cfg

    def _window(self, book=None):
        import main

        window = main.MainWindow()
        window._apply_source(book or self.book)
        return window

    def _wait(self, window, timeout=60.0):
        deadline = time.time() + timeout
        while window.worker is not None and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()

    def _answer(self, answer, seen=None):
        def question(_parent, _title, text, *args, **kwargs):
            if seen is not None:
                seen.append(text)
            return answer
        QMessageBox.question = staticmethod(question)

    def test_the_written_name_gets_the_language_suffix(self):
        window = self._window()
        try:
            window._start_translation(self._cfg())
            self.assertEqual(window._output_path,
                             os.path.join(self.folder, "Dune-italian.epub"))
            self._wait(window)
            self.assertTrue(os.path.isfile(window._output_path))
        finally:
            window.close()

    def test_the_extension_typed_by_the_user_is_dropped(self):
        window = self._window()
        try:
            window._start_translation(self._cfg(name="Dune.epub"))
            self.assertTrue(window._output_path.endswith("Dune-italian.epub"))
            self._wait(window)
        finally:
            window.close()

    def test_an_existing_target_is_not_overwritten_without_asking(self):
        target = os.path.join(self.folder, "Dune-italian.epub")
        with open(target, "wb") as handle:
            handle.write(b"existing")
        seen: list[str] = []
        self._answer(QMessageBox.StandardButton.No, seen)
        window = self._window()
        try:
            window._start_translation(self._cfg())
            self.assertIsNone(window.worker, "the run started anyway")
            with open(target, "rb") as handle:
                self.assertEqual(handle.read(), b"existing")
            self.assertTrue(seen, "no question was asked")
        finally:
            window.close()

    def test_accepting_overwrites_the_target(self):
        target = os.path.join(self.folder, "Dune-italian.epub")
        with open(target, "wb") as handle:
            handle.write(b"existing")
        self._answer(QMessageBox.StandardButton.Yes)
        window = self._window()
        try:
            window._start_translation(self._cfg())
            self.assertIsNotNone(window.worker)
            self._wait(window)
            self.assertGreater(os.path.getsize(target), 100)
        finally:
            window.close()

    def test_replacing_the_original_is_warned_about_and_refused(self):
        """A book named X-italian.epub translated to Italian hits itself."""
        folder = tempfile.mkdtemp(prefix="noesis-name-orig-")
        original = build_sample_epub(os.path.join(folder, "Dune-italian.epub"))

        def digest(path):
            with open(path, "rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()

        before = digest(original)
        seen: list[str] = []
        self._answer(QMessageBox.StandardButton.No, seen)
        window = self._window(book=original)
        try:
            window._start_translation(self._cfg(folder=folder, name="Dune"))
            self.assertEqual(window._output_path, original)
            self.assertIsNone(window.worker, "the run started anyway")
            self.assertEqual(before, digest(original),
                             "the original book was overwritten")
            # The *specific* warning, not the generic one.
            self.assertTrue(any("original" in text.lower() for text in seen), seen)
        finally:
            window.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestWizardOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-wizname"])
        cls.tmp = tempfile.mkdtemp(prefix="noesis-wizname-")

    def setUp(self):
        self.question = QMessageBox.question

    def tearDown(self):
        QMessageBox.question = self.question

    def _wizard(self, name: str = "Dune.epub", **kwargs):
        from noesis_ebook_translator.ui import TranslateWizard

        book = build_sample_epub(os.path.join(self.tmp, name))
        return TranslateWizard(None, mode="book", input_path=book, **kwargs)

    def test_the_default_name_is_the_base_and_the_preview_shows_the_suffix(self):
        wizard = self._wizard()
        try:
            self.assertEqual(wizard.config()["name"], "Dune")
            self.assertEqual(os.path.basename(wizard.output_path()),
                             "Dune-italian.epub")
            self.assertEqual(wizard.lbl_output_file.text(), "Dune-italian.epub")
            self.assertTrue(wizard.lbl_output_file.toolTip()
                            .endswith("Dune-italian.epub"))
            # The preview follows the fields.
            wizard.edt_name.setText("My Book")
            self.assertEqual(wizard.lbl_output_file.text(), "My Book-italian.epub")
            wizard.cmb_target.setCurrentText("Chinese (Simplified)")
            self.assertEqual(wizard.lbl_output_file.text(),
                             "My Book-chinese-simplified.epub")
        finally:
            wizard.close()

    def test_accept_asks_before_overwriting_and_stays_open_on_no(self):
        wizard = self._wizard(name="Dune2.epub")
        try:
            target = wizard.output_path()
            with open(target, "wb") as handle:
                handle.write(b"x")
            self._answer(QMessageBox.StandardButton.No)
            wizard.accept()
            self.assertFalse(wizard._output_confirmed)
            self.assertEqual(wizard.result(), 0)        # not accepted
            self.assertFalse(wizard.config()["output_confirmed"])
        finally:
            wizard.close()

    def test_accept_confirms_once_and_sets_the_flag(self):
        wizard = self._wizard(name="Dune3.epub")
        try:
            target = wizard.output_path()
            with open(target, "wb") as handle:
                handle.write(b"x")
            seen: list[str] = []
            self._answer(QMessageBox.StandardButton.Yes, seen)
            wizard.accept()
            self.assertTrue(wizard._output_confirmed)
            self.assertEqual(wizard.result(), 1)        # accepted
            self.assertTrue(wizard.config()["output_confirmed"])
            self.assertEqual(len(seen), 1)
        finally:
            wizard.close()

    def test_a_free_name_is_accepted_without_asking(self):
        wizard = self._wizard(name="Dune4.epub")
        try:
            seen: list[str] = []
            self._answer(QMessageBox.StandardButton.Yes, seen)
            wizard.accept()
            self.assertTrue(wizard._output_confirmed)
            self.assertEqual(seen, [], "asked although nothing would be replaced")
        finally:
            wizard.close()

    def _answer(self, answer, seen=None):
        def question(_parent, _title, text, *args, **kwargs):
            if seen is not None:
                seen.append(text)
            return answer
        QMessageBox.question = staticmethod(question)


if __name__ == "__main__":
    unittest.main()
