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

    def test_request_interval_is_a_storable_preference(self):
        """The parallel/sequential toggle writes it (see main._start_translation)."""
        try:
            appconfig.set_engine_preference("OpenRouter", request_interval=0)
            self.assertEqual(
                appconfig.get_engine_preference("OpenRouter")
                .get("request_interval"), 0)
            # ``None`` removes the key, so the engine class default returns.
            appconfig.set_engine_preference("OpenRouter", request_interval=None)
            self.assertIsNone(
                appconfig.get_engine_preference("OpenRouter")
                .get("request_interval"))
        finally:
            appconfig.set_engine_preference("OpenRouter", api_keys=None,
                                            model=None)


class TestReasoningDefaults(unittest.TestCase):
    """The app asks engines to skip the model's reasoning when translating."""

    def test_reasoning_is_off_by_default_and_per_engine_wins(self):
        appconfig.ensure_defaults()
        self.assertIs(appconfig.load_settings().get("translate_reasoning"),
                      False)

        class Supported:
            reasoning = None
            reasoning_supported = True
            config: dict = {}

        supported = Supported()
        book._apply_translation_defaults(supported)
        self.assertEqual(supported.reasoning, {"enabled": False})

        class Configured(Supported):
            config = {"reasoning": {"effort": "low"}}

        configured = Configured()
        book._apply_translation_defaults(configured)
        self.assertIsNone(configured.reasoning, "per-engine value must win")

        class Unsupported(Supported):
            reasoning_supported = False

        unsupported = Unsupported()
        book._apply_translation_defaults(unsupported)
        self.assertIsNone(unsupported.reasoning,
                          "engines that reject the field must be untouched")

    def test_opt_out_leaves_the_provider_default(self):
        config = get_config()
        config.set("translate_reasoning", None)
        config.commit()

        class Supported:
            reasoning = None
            reasoning_supported = True
            config: dict = {}

        try:
            engine = Supported()
            book._apply_translation_defaults(engine)
            self.assertIsNone(engine.reasoning)
        finally:
            config.set("translate_reasoning", False)
            config.commit()

    def test_chatgpt_body_carries_the_reasoning_switch(self):
        import json

        from noesis_ebook_translator.engines.openai import ChatgptTranslate

        saved = dict(ChatgptTranslate.config)
        try:
            ChatgptTranslate.set_config(
                {"api_keys": ["k"], "model": "m",
                 "reasoning": {"enabled": False}})
            translator = ChatgptTranslate()
            translator.set_source_lang("English")
            translator.set_target_lang("Italian")
            body = json.loads(translator.get_body("hello"))
            self.assertEqual(body["reasoning"], {"enabled": False})

            # Without the setting the field is not sent at all.
            ChatgptTranslate.set_config({"api_keys": ["k"], "model": "m"})
            translator = ChatgptTranslate()
            translator.set_source_lang("English")
            translator.set_target_lang("Italian")
            body = json.loads(translator.get_body("hello"))
            self.assertNotIn("reasoning", body)
        finally:
            ChatgptTranslate.set_config(saved)

    def test_openrouter_batch_parses_with_the_streaming_default(self):
        """The batch body is never streamed: it must not take the stream path.

        With the engine default ``stream=True`` every batch used to fail with
        "'str' object has no attribute 'readline'", so online batching never
        worked in the app.
        """
        import json

        from noesis_ebook_translator.engines import openrouter as openrouter_mod
        from noesis_ebook_translator.engines.openrouter import (
            OpenRouterTranslate)

        saved_config = dict(OpenRouterTranslate.config)
        saved_request = openrouter_mod.request
        payload = json.dumps({"choices": [{"message": {
            "content": json.dumps({"0": "uno", "1": "due"})}}]})
        openrouter_mod.request = lambda **kwargs: payload
        try:
            OpenRouterTranslate.set_config({"api_keys": ["k"], "model": "m"})
            translator = OpenRouterTranslate()
            translator.set_source_lang("English")
            translator.set_target_lang("Italian")
            self.assertTrue(translator.stream)  # the app default that broke it
            self.assertEqual(translator.translate_batch(["one", "two"]),
                             ["uno", "due"])
            self.assertTrue(translator.stream, "the stream flag must be restored")
        finally:
            openrouter_mod.request = saved_request
            OpenRouterTranslate.set_config(saved_config)


if __name__ == "__main__":
    unittest.main()
