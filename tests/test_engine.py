"""Engine registry and app-config tests (no network)."""
import unittest

from noesis_ebook_translator import appconfig, book
from noesis_ebook_translator.engines import builtin_engines


class TestEngineRegistry(unittest.TestCase):
    def test_all_upstream_engines_present(self):
        names = set(book.list_engine_names())
        for expected in (
                "Google(Free)New", "Google(Free)Html", "Google(Free)",
                "Google(Basic)", "Google(Advanced)", "Gemini", "ChatGPT",
                "Claude", "DeepSeek", "OpenRouter", "DeepL", "DeepL(Free)",
                "MicrosoftEdge(Free)", "Youdao", "Baidu"):
            self.assertIn(expected, names, expected)

    def test_engine_info_flags(self):
        info = appconfig.engine_info("OpenRouter")
        self.assertTrue(info["need_api_key"])
        self.assertIn("deepseek/deepseek-chat", info["models"])

        info_free = appconfig.engine_info("Google(Free)New")
        self.assertFalse(info_free["need_api_key"])

    def test_builtin_engines_non_empty(self):
        self.assertGreaterEqual(len(builtin_engines), 15)


class TestAppDefaults(unittest.TestCase):
    def test_ensure_defaults_single_language_output(self):
        appconfig.ensure_defaults()
        settings = appconfig.load_settings()
        self.assertEqual(settings.get("translation_position"), "only")
        self.assertFalse(settings.get("online_batching"))

    def test_engine_preference_roundtrip(self):
        appconfig.set_engine_preference("OpenRouter", api_keys=["k123"],
                                        model="deepseek/deepseek-chat")
        pref = appconfig.get_engine_preference("OpenRouter")
        self.assertEqual(pref.get("api_keys"), ["k123"])
        self.assertEqual(pref.get("model"), "deepseek/deepseek-chat")


if __name__ == "__main__":
    unittest.main()
