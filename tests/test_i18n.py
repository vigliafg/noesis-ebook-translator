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

    def test_ribbon_keys_present(self):
        keys = [
            "tab.assets", "tab.quality", "tab.export", "tab.tools",
            "panel.configuration", "panel.books", "panel.views", "panel.actions",
            "panel.metadata", "panel.search", "panel.compare", "panel.notes",
            "panel.source", "panel.options", "panel.evaluation", "panel.report",
            "panel.result", "panel.content", "panel.format_grp",
            "panel.destination", "panel.split", "panel.merge",
            "panel.maintenance", "panel.information", "panel.diagnostics",
            "action.add_book", "action.remove_book", "action.open_reader",
            "action.refresh", "action.compare", "action.retranslate",
            "action.extract_chapters", "action.reveal", "action.prev",
            "action.next", "action.toc", "action.find", "action.find_next",
            "action.add_note", "action.bookmarks", "action.print_pdf",
            "action.rotate", "action.reset_view", "action.export_assets",
            "action.clear_cache", "action.data_dir", "action.report_save",
            "action.report_open", "action.evaluate", "action.evaluate_ai",
            "action.swap", "action.stats", "action.license", "action.upstream",
            "action.engine_version", "label.samples", "label.threshold",
            "label.search", "label.font", "label.spread", "label.flow",
            "view.original", "view.translated", "view.chapters",
        ]
        for key in keys:
            self.assertNotEqual(i18n.T(key), key, key)


if __name__ == "__main__":
    unittest.main()
