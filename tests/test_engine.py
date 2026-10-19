"""Engine registry and app-config tests (no network)."""
import unittest

from noesis_ebook_translator import appconfig, book
from noesis_ebook_translator.engines import builtin_engines
from noesis_ebook_translator.lib.config import get_config


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

    def test_openrouter_has_no_literary_persona(self):
        """A hard-coded literary prompt is wrong for non-fiction/medical."""
        from noesis_ebook_translator.engines.openai import ChatgptTranslate
        from noesis_ebook_translator.engines.openrouter import (
            OpenRouterTranslate)
        self.assertEqual(OpenRouterTranslate.prompt, ChatgptTranslate.prompt)
        self.assertNotIn("letterario", OpenRouterTranslate.prompt)
        # The generic gateway keeps a low, stable sampler value of its own...
        self.assertEqual(OpenRouterTranslate.temperature, 0.2)

    def test_engine_tuned_temperature_is_left_alone(self):
        """DeepSeek/Gemini ship their own value: the app must not override it."""
        from noesis_ebook_translator.engines.deepseek import DeepseekTranslate
        from noesis_ebook_translator.engines.google import GeminiTranslate
        self.assertEqual(DeepseekTranslate.temperature, 1.3)
        self.assertEqual(GeminiTranslate.temperature, 0.9)
        appconfig.ensure_defaults()
        self.assertIsNone(appconfig.load_settings().get("translate_temperature"))


class TestAppDefaults(unittest.TestCase):
    def test_ensure_defaults_single_language_output(self):
        appconfig.ensure_defaults()
        settings = appconfig.load_settings()
        self.assertEqual(settings.get("translation_position"), "only")
        self.assertFalse(settings.get("online_batching"))

    def test_temperature_override_is_opt_in(self):
        appconfig.ensure_defaults()
        self.assertIsNone(appconfig.load_settings().get("translate_temperature"))

        class Dummy:
            temperature = 1.0
            config: dict = {}

        dummy = Dummy()
        book._apply_translation_defaults(dummy)
        self.assertEqual(dummy.temperature, 1.0)  # untouched by default

        # ... but an explicit global override is applied when set.
        config = get_config()
        config.set("translate_temperature", 0.2)
        config.commit()
        try:
            book._apply_translation_defaults(dummy)
            self.assertEqual(dummy.temperature, 0.2)
        finally:
            config.delete("translate_temperature")
            config.commit()

        # An explicit per-engine value wins over the global one.
        config.set("translate_temperature", 0.2)
        config.commit()

        class Configured(Dummy):
            config = {"temperature": 1.0}

        configured = Configured()
        try:
            book._apply_translation_defaults(configured)
            self.assertEqual(configured.temperature, 1.0)
        finally:
            config.delete("translate_temperature")
            config.commit()

    def test_engine_preference_roundtrip(self):
        appconfig.set_engine_preference("OpenRouter", api_keys=["k123"],
                                        model="deepseek/deepseek-chat")
        pref = appconfig.get_engine_preference("OpenRouter")
        self.assertEqual(pref.get("api_keys"), ["k123"])
        self.assertEqual(pref.get("model"), "deepseek/deepseek-chat")


if __name__ == "__main__":
    unittest.main()
