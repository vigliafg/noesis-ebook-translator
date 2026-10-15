"""Internationalization tests: 5 catalogs, key parity, live language switch."""
import unittest

from noesis_ebook_translator import i18n


class TestCatalogs(unittest.TestCase):
    def test_five_languages_available(self):
        self.assertEqual(set(i18n.available_languages()),
                         {"it", "en", "fr", "es", "de"})

    def test_key_parity_across_languages(self):
        reference = i18n.catalog_keys("en")
        self.assertTrue(reference, "english catalog must not be empty")
        for lang in i18n.LANGUAGES:
            self.assertEqual(i18n.catalog_keys(lang), reference, lang)

    def test_no_empty_values(self):
        for lang in i18n.LANGUAGES:
            for key, value in i18n.catalog(lang).items():
                self.assertTrue(value.strip(), f"{lang}:{key} is empty")

    def test_language_switch_and_fallback(self):
        original = i18n.get_language()
        try:
            i18n.set_language("de")
            self.assertEqual(i18n.get_language(), "de")
            self.assertEqual(i18n.T("tab.library"), "Bibliothek")
            i18n.set_language("fr")
            self.assertEqual(i18n.T("action.translate"), "Traduire")
            # unknown key falls back to the key itself
            self.assertEqual(i18n.T("does.not.exist"), "does.not.exist")
        finally:
            i18n.set_language(original)


if __name__ == "__main__":
    unittest.main()
