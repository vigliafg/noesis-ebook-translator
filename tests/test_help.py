"""Help system tests (URL builder + offline fallback)."""
import unittest

from noesis_ebook_translator import help as help_mod
from noesis_ebook_translator import i18n


class TestHelp(unittest.TestCase):
    def test_url_per_language(self):
        for lang in i18n.LANGUAGES:
            url = help_mod.help_url(lang)
            self.assertIn(f"/{lang}/", url)
            self.assertTrue(url.startswith(help_mod.HELP_BASE_URL))
        self.assertIn("translation.html", help_mod.help_url("en", "translation"))

    def test_invalid_language_falls_back(self):
        url = help_mod.help_url("xx")
        self.assertTrue(any(f"/{lang}/" in url for lang in i18n.LANGUAGES))

    def test_fallback_html_has_title(self):
        html = help_mod.fallback_html("it")
        self.assertIn("<h1>", html)
        self.assertIn("Aiuto", html)


if __name__ == "__main__":
    unittest.main()
