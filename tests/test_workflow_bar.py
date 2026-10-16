"""Ribbon panels: captions, dividers, dialog launchers, alignment.

The toolbar used to be a flat row of controls split by vertical rules but with no
group captions (the old ``pyqtribbon`` bar had them; the custom one lost them).
These tests pin the Office-like geometry back down.
"""
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from noesis_ebook_translator.i18n import T

SECTIONS = ("library", "reader", "assets", "translate", "quality", "export",
            "tools")


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestRibbonPanels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-ribbon"])

    def _window(self):
        import main

        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        window.resize(1500, 760)
        window.show()
        self._pump()
        return window

    def _pump(self, rounds: int = 6) -> None:
        for _ in range(rounds):
            self.app.processEvents()

    def _pages(self, window):
        for index, key in enumerate(SECTIONS):
            window.workflow.setCurrentSection(index)
            self._pump()
            yield key, window.workflow.stack.currentWidget()

    def test_every_section_has_panels_with_captions(self):
        window = self._window()
        try:
            for key, page in self._pages(window):
                panels = page.panels()
                self.assertTrue(panels, f"{key}: no panels")
                for panel in panels:
                    self.assertTrue(panel.caption_text(),
                                    f"{key}: empty caption on {panel.key}")
                    self.assertEqual(panel.caption_text(), T(panel.key),
                                     f"{key}: {panel.key}")
                    # Every caption must be translated (no key leaking through).
                    self.assertNotEqual(T(panel.key), panel.key,
                                        f"{key}: missing translation {panel.key}")
        finally:
            window.close()

    def test_dividers_between_panels(self):
        window = self._window()
        try:
            for key, page in self._pages(window):
                panels = page.panels()
                self.assertEqual(page.dividers(), len(panels) - 1, key)
                for divider in page._dividers:
                    self.assertEqual(divider.width(), 1, key)
                    # Hairline spans the whole panel height.
                    self.assertGreaterEqual(divider.height(),
                                            panels[0].height() - 2, key)
        finally:
            window.close()

    def test_captions_are_aligned_across_panels(self):
        """A taller launcher must not lift the caption (regression guard)."""
        window = self._window()
        try:
            for key, page in self._pages(window):
                ys = set()
                heights = set()
                for panel in page.panels():
                    caption = panel.caption
                    ys.add(caption.mapTo(page, caption.rect().topLeft()).y())
                    heights.add(caption.height())
                self.assertEqual(len(ys), 1,
                                 f"{key}: captions misaligned {sorted(ys)}")
                self.assertEqual(len(heights), 1, key)
        finally:
            window.close()

    def test_dialog_launchers_open_settings_on_the_right_tab(self):
        window = self._window()
        opened: list = []
        original = window.on_settings
        window.on_settings = lambda tab=None: opened.append(tab)
        count = 0
        try:
            for _key, page in self._pages(window):
                for panel in page.panels():
                    if panel.launcher is None:
                        continue
                    self.assertEqual(panel.launcher.toolTip(),
                                     T("action.settings"))
                    self.assertEqual(panel.launcher.width(), 13)
                    panel.launcher.click()
                    count += 1
            # ``panel.source`` shows up twice (Assets → Paths, Export → Export),
            # so the expectation is an ordered list, not a mapping.
            self.assertEqual(count, 11)
            self.assertEqual(opened, [5, 1, 5,  # library, reader, assets
                                      2, 2, 2,  # engine, languages, options
                                      3, 3,     # evaluation, report
                                      4, 4,     # source, format
                                      5])       # maintenance
        finally:
            window.on_settings = original
            window.close()

    def test_rows_are_short_and_stable(self):
        """The strip stays a single control row: ~120px + the top tabs."""
        window = self._window()
        try:
            heights = []
            for _key, page in self._pages(window):
                heights.append(page.sizeHint().height())
            # A single row of 40px icons plus the 17px caption line.
            self.assertLessEqual(max(heights), 125,
                                 f"rows too tall: {heights}")
            self.assertGreaterEqual(min(heights), 95)
        finally:
            window.close()

    def test_rendering_every_section_works(self):
        """Paint regression guard: a broken delegate/stylesheet must fail here."""
        window = self._window()
        try:
            for key, page in self._pages(window):
                pixmap = window.workflow.grab()
                self.assertFalse(pixmap.isNull(), key)
                self.assertGreater(pixmap.width(), 200, key)
                self.assertFalse(page.panels()[0].caption.grab().isNull(), key)
        finally:
            window.close()

    def test_workflow_buttons_still_present(self):
        from noesis_ebook_translator.ui.workflow_bar import WorkflowButton

        window = self._window()
        try:
            buttons = window.workflow.findChildren(WorkflowButton)
            self.assertGreaterEqual(len(buttons), 30)
            self.assertFalse(window.btn_translate.icon().isNull())
            self.assertTrue(window.cmb_engine.count() > 0)
            # Panels must not swallow the wiring the window keeps referring to.
            for attribute in ("btn_translate", "btn_cancel", "cmb_engine",
                              "cmb_source", "cmb_target", "edt_api_key",
                              "cmb_model", "chk_cache"):
                self.assertTrue(hasattr(window, attribute), attribute)
        finally:
            window.close()


class TestStartupGeometry(unittest.TestCase):
    """The window must fit the screen and never grow past it when switching tabs."""

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_minimum_is_capped_to_the_screen(self):
        import main

        app = QApplication.instance() or QApplication(["noesis-geometry"])
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        try:
            available = app.primaryScreen().availableGeometry()
            self.assertLessEqual(window.minimumSize().width(),
                                 max(640, available.width() - 40))
            self.assertLessEqual(window.minimumSize().height(),
                                 max(420, available.height() - 40))
        finally:
            window.close()

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_switching_sections_does_not_grow_the_window(self):
        import main

        app = QApplication.instance() or QApplication(["noesis-geometry"])
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        try:
            window.showNormal()
            window.resize(1024, 700)
            for _ in range(4):
                app.processEvents()
            for index in range(window.workflow.sections()):
                window.workflow.setCurrentSection(index)
                window._on_section_changed(index)
                for _ in range(6):
                    app.processEvents()
                self.assertLessEqual(window.width(), 1024,
                                     f"section {index} grew the window")
        finally:
            window.close()

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_fullscreen_toggle_round_trip(self):
        import main

        app = QApplication.instance() or QApplication(["noesis-geometry"])
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        try:
            window.show()
            app.processEvents()
            window.toggle_fullscreen()
            app.processEvents()
            self.assertTrue(window.isFullScreen())
            window.toggle_fullscreen()
            app.processEvents()
            self.assertFalse(window.isFullScreen())
        finally:
            window.close()


class TestToolPanelLayout(unittest.TestCase):
    """Pure-layout unit test for the optional two-row panels."""

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_break_after_stacks_the_rest_on_a_second_row(self):
        from PyQt6.QtWidgets import QLabel
        from noesis_ebook_translator.ui.workflow_bar import ToolPanel

        app = QApplication.instance() or QApplication(["noesis-panel"])
        panel = ToolPanel("panel.file", "File", break_after=2)
        try:
            for index in range(4):
                panel.add(QLabel(str(index)))
            self.assertEqual(panel.grid.count(), 4)
            positions = [panel.grid.getItemPosition(i)[:2] for i in range(4)]
            self.assertEqual(positions, [(0, 0), (0, 1), (1, 0), (1, 1)])
        finally:
            panel.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
