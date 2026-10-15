"""Theme registry tests (pure logic, no Qt)."""
import unittest

from noesis_ebook_translator import theme


class TestTheme(unittest.TestCase):
    def test_registry_has_expected_modes(self):
        self.assertEqual(theme.theme_choices(),
                         ["system", "light", "dark", "sepia"])

    def test_normalize_falls_back_to_system(self):
        self.assertEqual(theme.normalize_mode("nope"), "system")
        self.assertEqual(theme.normalize_mode("dark"), "dark")

    def test_is_dark(self):
        self.assertTrue(theme.is_dark("dark"))
        self.assertFalse(theme.is_dark("light"))
        self.assertFalse(theme.is_dark("sepia"))
        self.assertTrue(theme.is_dark("system", system_dark=True))
        self.assertFalse(theme.is_dark("system", system_dark=False))

    def test_reader_theme(self):
        self.assertEqual(theme.reader_theme("sepia"), "sepia")
        self.assertEqual(theme.reader_theme("dark"), "dark")
        self.assertEqual(theme.reader_theme("system", True), "dark")
        self.assertEqual(theme.reader_theme("system", False), "light")

    def test_stylesheets_distinct_and_nonempty(self):
        sheets = {mode: theme.stylesheet(mode) for mode in
                  ("light", "dark", "sepia")}
        for mode, sheet in sheets.items():
            self.assertIn("QWidget", sheet, mode)
        self.assertEqual(len(set(sheets.values())), 3)

    def test_palette(self):
        pal = theme.palette("sepia")
        self.assertIn("background", pal)
        self.assertIn("accent", pal)


if __name__ == "__main__":
    unittest.main()
