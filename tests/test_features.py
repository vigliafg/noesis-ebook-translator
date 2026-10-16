"""End-to-end GUI feature harness + widget-level tests for the new features."""
import os
import tempfile
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import build_rich_epub
from tests.harness import run_feature_harness


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
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
        self.assertEqual(report.categories, 7, report.summary())
        self.assertGreaterEqual(report.figures, 1, report.summary())
        self.assertGreaterEqual(report.tables, 1, report.summary())
        self.assertGreaterEqual(report.texts, 1, report.summary())
        self.assertGreaterEqual(report.chapters, 1, report.summary())
        self.assertTrue(report.theme_ok, report.summary())
        self.assertTrue(report.library_ok, report.summary())
        self.assertTrue(report.settings_ok, report.summary())


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
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

    def test_icons_available(self):
        from noesis_ebook_translator.ui import icons

        names = icons.available()
        for expected in ("library", "reader", "assets", "translate", "quality",
                         "export", "tools", "info"):
            self.assertIn(expected, names, expected)
            self.assertTrue(icons.has_icon(expected))
            self.assertFalse(icons.icon(expected).isNull())

    def test_toc_modes_by_category(self):
        from PyQt6.QtCore import Qt
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-tocmode-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)
            item = window.reader.toc.topLevelItem(0)
            # Reader section (index 1) → no checkboxes at all
            window.workflow.setCurrentSection(1)
            self.assertEqual(window.reader.toc_mode(), "read")
            self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable))
            self.assertIsNone(item.data(0, Qt.ItemDataRole.CheckStateRole))
            # Translate section (index 3) → selectable checkboxes
            window.workflow.setCurrentSection(3)
            self.assertEqual(window.reader.toc_mode(), "select")
            self.assertTrue(bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable))
            self.assertIsNotNone(item.data(0, Qt.ItemDataRole.CheckStateRole))
        finally:
            window.close()

    def test_toc_click_navigates_and_section_expands(self):
        from PyQt6.QtCore import Qt
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-tocclick-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)

            def find(name):
                def walk(it):
                    yield it
                    for i in range(it.childCount()):
                        yield from walk(it.child(i))
                for i in range(window.reader.toc.topLevelItemCount()):
                    for it in walk(window.reader.toc.topLevelItem(i)):
                        if it.data(0, Qt.ItemDataRole.UserRole) == name:
                            return it
                return None

            target = find("c3.xhtml")
            window.reader._on_toc_click(target, 0)
            self.assertEqual(window.reader.backend.current_href(), "c3.xhtml")
            # a section without a file toggles expansion instead of navigating
            section = next(
                window.reader.toc.topLevelItem(i)
                for i in range(window.reader.toc.topLevelItemCount())
                if not window.reader.toc.topLevelItem(i).data(
                    0, Qt.ItemDataRole.UserRole))
            before = section.isExpanded()
            window.reader._on_toc_click(section, 0)
            self.assertNotEqual(section.isExpanded(), before)
        finally:
            window.close()

    def test_parallel_view_syncs_both_on_toc_click(self):
        from PyQt6.QtCore import Qt
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-parallel-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        translated = build_rich_epub(os.path.join(tmp, "rich_IT.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)
            window.reader.set_translated_path(translated)
            window.reader.set_parallel(True)
            self.assertTrue(window.reader.is_parallel())

            def find(name):
                def walk(it):
                    yield it
                    for i in range(it.childCount()):
                        yield from walk(it.child(i))
                for i in range(window.reader.toc.topLevelItemCount()):
                    for it in walk(window.reader.toc.topLevelItem(i)):
                        if it.data(0, Qt.ItemDataRole.UserRole) == name:
                            return it
                return None

            window.reader._on_toc_click(find("c3.xhtml"), 0)
            self.assertEqual(window.reader.backend.current_href(), "c3.xhtml")
            self.assertEqual(window.reader.second.current_href(), "c3.xhtml")
        finally:
            window.close()

    def test_reader_find(self):
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-find-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)
            self.assertTrue(window.reader.find_text("Opening"))
            # the reader has no inner toolbar anymore (controls live in the ribbon)
            self.assertFalse(hasattr(window.reader, "edt_find"))
        finally:
            window.close()

    def test_translate_wizards(self):
        from PyQt6.QtCore import Qt
        from noesis_ebook_translator import appconfig
        from noesis_ebook_translator.ui import TranslateWizard
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-wizard-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)
            book_wiz = TranslateWizard(window, mode="book", input_path=book)
            try:
                cfg = book_wiz.config()
                self.assertEqual(cfg["chapters"], [])
                self.assertEqual(cfg["grouping"], "grouped")
            finally:
                book_wiz.close()
            ch_wiz = TranslateWizard(window, mode="chapters", input_path=book)
            try:
                self.assertEqual(ch_wiz.chapter_list.count(), 3)
                ch_wiz.chapter_list.item(0).setCheckState(Qt.CheckState.Checked)
                self.assertEqual(len(ch_wiz.selected_chapters()), 1)
                ch_wiz.radio_single.setChecked(True)
                self.assertEqual(ch_wiz.config()["grouping"], "single")
            finally:
                ch_wiz.close()
        finally:
            window.close()

    def test_progress_labels(self):
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        window = main.MainWindow()
        try:
            window._chapter_names = ["A", "B", "C"]
            window._on_progress(0.5, "working")
            self.assertEqual(window.book_label.text(), "50%")
            self.assertIn(window.chapter_label.text(), ("A", "B", "C"))
        finally:
            window.close()

    def test_toc_current_chapter_bold_and_text_settings(self):
        from PyQt6.QtCore import Qt
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-tocbold-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)

            def find(name):
                def walk(it):
                    yield it
                    for i in range(it.childCount()):
                        yield from walk(it.child(i))
                for i in range(window.reader.toc.topLevelItemCount()):
                    for it in walk(window.reader.toc.topLevelItem(i)):
                        if it.data(0, Qt.ItemDataRole.UserRole) == name:
                            return it
                return None

            window.reader._on_toc_click(find("c3.xhtml"), 0)
            self.assertTrue(find("c3.xhtml").font(0).bold())
            self.assertFalse(find("c1.xhtml").font(0).bold())
            # typographic handlers must not raise
            window.on_justify_toggled(False)
            window.on_hyphenate_toggled(False)
            window.on_expand_all()
            window.on_collapse_all()
        finally:
            window.close()

    def test_library_layouts_and_views(self):
        from PyQt6.QtWidgets import QListWidget
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-lib-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window.tabs.setCurrentWidget(window.library)
            window.library.add_book(book)
            self.assertGreaterEqual(window.library.list.count(), 1)

            window.set_library_layout("grid")
            self.assertEqual(window.library.layout_mode(), "grid")
            self.assertEqual(window.library.list.viewMode(),
                             QListWidget.ViewMode.IconMode)
            window.set_library_layout("list")
            self.assertEqual(window.library.layout_mode(), "list")
            self.assertEqual(window.library.list.viewMode(),
                             QListWidget.ViewMode.ListMode)
            # views keep the same layouts
            window.set_library_view("original")
            self.assertEqual(window.library.view(), "original")
            window.set_library_view("translated")
            self.assertEqual(window.library.view(), "translated")
            window.set_library_view("chapters")
            self.assertEqual(window.library.view(), "chapters")

            # The toolbar buttons show the active view (and layout), so the two
            # content views cannot look identical any more.
            views = window.workflow.library_view_buttons
            layouts = window.workflow.library_layout_buttons
            window.set_library_view("translated")
            self.assertTrue(views["translated"].isChecked())
            self.assertFalse(views["original"].isChecked())
            self.assertFalse(views["chapters"].isChecked())
            self.assertIn("(", views["original"].toolTip())   # item count
            window.set_library_view("original")
            self.assertTrue(views["original"].isChecked())
            self.assertFalse(views["translated"].isChecked())
            window.set_library_layout("list")
            self.assertTrue(layouts["list"].isChecked())
            self.assertFalse(layouts["grid"].isChecked())
            window.set_library_layout("grid")
            self.assertTrue(layouts["grid"].isChecked())

            # Views with nothing to show say so instead of looking empty/equal.
            window.set_library_view("original")
            window.library.edt_filter.setText("zzz-nothing-matches")
            self.assertEqual(window.library.list.count(), 0)
            self.assertFalse(window.library.lbl_empty.isHidden())
            window.library.edt_filter.clear()
            self.assertFalse(window.library.list.count() == 0)
            self.assertTrue(window.library.lbl_empty.isHidden())
        finally:
            window.close()

    def test_settings_dialog_tabs(self):
        from noesis_ebook_translator.ui import SettingsDialog

        dialog = SettingsDialog()
        try:
            self.assertEqual(dialog.tabs.count(), 7)
            values = dialog.values()
            for key in ("ui_theme", "reader_theme", "reader_font", "reader_flow",
                        "export_format", "output_dir", "quality_samples"):
                self.assertIn(key, values)
        finally:
            dialog.close()

    def test_startup_section_matches_view(self):
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        window = main.MainWindow()
        try:
            # the selected workflow section must match the shown view
            self.assertEqual(window.workflow.currentSection(), 0)  # Library
            self.assertIs(window.tabs.currentWidget(), window.library)
            window.workflow.setCurrentSection(3)  # Translate
            self.assertIs(window.tabs.currentWidget(), window._translate_tab)
        finally:
            window.close()

    def test_content_tabbar_hidden(self):
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        window = main.MainWindow()
        try:
            # navigation is driven by the ribbon: the content tab bar is hidden
            self.assertTrue(window.tabs.tabBar().isHidden())
            # 7 workflow sections, every button has an icon
            from noesis_ebook_translator.ui.workflow_bar import WorkflowButton
            self.assertEqual(window.workflow.sections(), 7)
            buttons = window.workflow.findChildren(WorkflowButton)
            self.assertTrue(buttons)
            for button in buttons:
                self.assertFalse(button.icon().isNull(), button.text())
        finally:
            window.close()

    def test_chapters_are_selectable(self):
        from PyQt6.QtCore import Qt
        from noesis_ebook_translator import appconfig
        import main

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-chapters-")
        book = build_rich_epub(os.path.join(tmp, "rich.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)
            window.on_extract_chapters()
            self.assertGreaterEqual(window.chapters.list.count(), 1)
            item = window.chapters.list.item(0)
            self.assertTrue(bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable))
            self.assertEqual(window.chapters.selected_chapters(), [])
            item.setCheckState(Qt.CheckState.Checked)
            self.assertEqual(len(window.chapters.selected_chapters()), 1)
        finally:
            window.close()


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


class TestOpenItemGuard(unittest.TestCase):
    """Regression: double-clicking a library row could pass ``None``."""

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_open_item_without_item_does_not_raise(self):
        from noesis_ebook_translator.reader.panels import LibraryWidget

        app = QApplication.instance() or QApplication(["noesis-library"])

        class _Session:
            def recent(self):
                return []

        widget = LibraryWidget(_Session())
        emitted = []
        widget.openRequested.connect(emitted.append)
        try:
            widget._open_item(None)            # used to raise AttributeError
            widget._open_item()                # no item at all
            self.assertEqual(emitted, [])
        finally:
            widget.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
