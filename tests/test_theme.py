"""Theme registry tests (pure logic, no Qt)."""
import unittest

from noesis_ebook_translator import theme


class TestTheme(unittest.TestCase):
    def test_registry_has_expected_modes(self):
        # The "sepia" *app* theme was removed; the reader keeps its own sepia.
        self.assertEqual(theme.theme_choices(), ["system", "light", "dark"])

    def test_normalize_falls_back_to_system(self):
        self.assertEqual(theme.normalize_mode("nope"), "system")
        self.assertEqual(theme.normalize_mode("dark"), "dark")
        self.assertEqual(theme.normalize_mode("sepia"), "system")

    def test_is_dark(self):
        self.assertTrue(theme.is_dark("dark"))
        self.assertFalse(theme.is_dark("light"))
        self.assertTrue(theme.is_dark("system", system_dark=True))
        self.assertFalse(theme.is_dark("system", system_dark=False))

    def test_reader_theme(self):
        self.assertEqual(theme.reader_theme("dark"), "dark")
        self.assertEqual(theme.reader_theme("light"), "light")
        self.assertEqual(theme.reader_theme("system", True), "dark")
        self.assertEqual(theme.reader_theme("system", False), "light")

    def test_stylesheets_distinct_and_nonempty(self):
        sheets = {mode: theme.stylesheet(mode) for mode in ("light", "dark")}
        for mode, sheet in sheets.items():
            self.assertIn("QWidget", sheet, mode)
        self.assertEqual(len(set(sheets.values())), 2)

    def test_palette(self):
        for mode in ("light", "dark"):
            pal = theme.palette(mode)
            self.assertIn("background", pal, mode)
            self.assertIn("accent", pal, mode)
            self.assertEqual(pal, theme.palette(mode))
        # The liquid colours exist for every theme too.
        for mode in ("light", "dark"):
            self.assertIn("accent", theme.liquid(mode))


if __name__ == "__main__":
    unittest.main()
