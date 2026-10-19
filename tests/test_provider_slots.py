"""Provider slots, engine filtering and the model cache (no network)."""
import time
import unittest

from noesis_ebook_translator import appconfig


class TestProviderSlots(unittest.TestCase):
    def setUp(self):
        appconfig.save_settings({
            "provider_slots": [],
            "model_cache": {},
            "engine_preferences": {},
            "translate_engine": "Google(Free)New",
        })

    def test_padding_and_cap(self):
        slots = appconfig.provider_slots()
        self.assertEqual(len(slots), appconfig.MAX_PROVIDER_SLOTS)
        self.assertTrue(all(not slot["enabled"] for slot in slots))

        many = [{"enabled": True, "provider": f"p{i}"}
                for i in range(appconfig.MAX_PROVIDER_SLOTS + 3)]
        appconfig.set_provider_slots(many)
        self.assertEqual(len(appconfig.provider_slots()),
                         appconfig.MAX_PROVIDER_SLOTS)

    def test_mirrors_into_engine_preferences(self):
        appconfig.set_provider_slots([
            {"enabled": True, "provider": "groq", "api_key": "k1",
             "model": "llama-3.3-70b-versatile"},
            {"enabled": False, "provider": "mistral", "api_key": "ignored"},
        ])
        pref = appconfig.get_engine_preference("Groq")
        self.assertEqual(pref.get("api_keys"), ["k1"])
        self.assertEqual(pref.get("model"), "llama-3.3-70b-versatile")
        # Disabled slots are not mirrored as active (no key exposed).
        self.assertFalse(appconfig.get_engine_preference("Mistral").get("api_keys"))

    def test_custom_endpoint_is_mirrored(self):
        appconfig.set_provider_slots([
            {"enabled": True, "provider": "custom", "api_key": "",
             "model": "qwen", "endpoint": "http://localhost:11434/v1"},
        ])
        pref = appconfig.get_engine_preference("Custom endpoint")
        self.assertEqual(pref.get("endpoint"), "http://localhost:11434/v1")

    def test_selection_list_shows_non_llm_always_and_llm_only_once_configured(self):
        # Out of the box: the machine-translation engines and no LLM at all.
        names = appconfig.desktop_engine_names()
        for expected in ("Google(Free)New", "DeepL", "MicrosoftEdge(Free)",
                         "Youdao", "Baidu"):
            self.assertIn(expected, names, expected)
        for unexpected in ("ChatGPT", "Gemini", "Claude", "DeepSeek",
                           "OpenRouter", "Groq", "Mistral"):
            self.assertNotIn(unexpected, names, unexpected)

        # An enabled provider slot makes its engine selectable ...
        appconfig.set_provider_slots([
            {"enabled": True, "provider": "groq", "api_key": "k",
             "model": "llama-3.3-70b-versatile"}])
        names = appconfig.desktop_engine_names()
        self.assertIn("Groq", names)
        self.assertNotIn("Mistral", names)          # still not configured

        # ... and disabling it takes the engine away again.
        appconfig.set_provider_slots([])
        self.assertNotIn("Groq", appconfig.desktop_engine_names())

    def test_dropped_slot_clears_its_stale_mirror(self):
        appconfig.set_provider_slots([
            {"enabled": True, "provider": "groq", "api_key": "k",
             "model": "llama-3.3-70b-versatile"}])
        self.assertIn("Groq", appconfig.desktop_engine_names())

        # A slot that disappears from the list is never submitted, so its mirror
        # has to be cleared explicitly: otherwise the engine stays selectable.
        appconfig.set_provider_slots([])
        self.assertFalse(appconfig.get_engine_preference("Groq").get("api_keys"))
        self.assertNotIn("Groq", appconfig.desktop_engine_names())

    def test_verbatim_llm_appears_once_it_has_a_key(self):
        self.assertNotIn("ChatGPT", appconfig.desktop_engine_names())
        appconfig.set_engine_preference("ChatGPT", api_keys=["sk-test"])
        self.assertIn("ChatGPT", appconfig.desktop_engine_names())

    def test_enabled_slot_is_the_users_choice_even_without_a_key(self):
        # An enabled slot is a deliberate choice: a key can come from the
        # environment, a custom endpoint needs no key at all.
        appconfig.set_provider_slots([
            {"enabled": True, "provider": "groq", "model": "llama"}])
        self.assertIn("Groq", appconfig.desktop_engine_names())

        appconfig.set_provider_slots([
            {"enabled": True, "provider": "custom", "model": "qwen",
             "endpoint": "http://127.0.0.1:11434/v1"}])
        self.assertIn("Custom endpoint", appconfig.desktop_engine_names())

    def test_engine_names_keeps_the_full_roster_for_the_cli(self):
        # The shared list is the CLI contract: its TUI picks the engine *before*
        # typing the key, so it must keep offering every engine.
        names = appconfig.engine_names()
        for expected in ("ChatGPT", "Gemini", "Claude", "DeepSeek",
                         "OpenRouter", "Google(Free)New", "DeepL"):
            self.assertIn(expected, names, expected)

    def test_engine_info_for_provider(self):
        info = appconfig.engine_info("Groq")
        self.assertEqual(info["provider"], "groq")
        self.assertTrue(info["need_api_key"])
        self.assertTrue(info["models"])  # bundled snapshot

        info_free = appconfig.engine_info("Google(Free)New")
        self.assertFalse(info_free["need_api_key"])
        self.assertEqual(info_free["provider"], "")

    def test_provider_id_for_engine(self):
        self.assertEqual(appconfig.provider_id_for_engine("Groq"), "groq")
        self.assertEqual(appconfig.provider_id_for_engine("OpenRouter"),
                         "openrouter")
        self.assertEqual(appconfig.provider_id_for_engine("Baidu"), "")

    def test_choices_cover_curated_roster(self):
        choices = {choice["id"] for choice in appconfig.provider_choices()}
        self.assertIn("opencode-go", choices)
        self.assertIn("openrouter", choices)
        self.assertIn("custom", choices)


class TestModelCache(unittest.TestCase):
    def setUp(self):
        appconfig.save_settings({"model_cache": {}, "model_tests": {}})

    def test_snapshot_when_no_cache(self):
        models = appconfig.provider_models("groq")
        self.assertTrue(models)

    def test_cache_wins_and_is_timestamped(self):
        appconfig.save_provider_models("groq", ["a", "b"])
        self.assertEqual(appconfig.provider_models("groq"), ["a", "b"])
        age = appconfig.model_cache_age("groq")
        self.assertIsNotNone(age)
        self.assertLess(age, 5)

    def test_refresh_uses_injected_fetch(self):
        calls = {}

        def fake_fetch(provider_id, key):
            calls["args"] = (provider_id, key)
            return ["x", "y"]

        models = appconfig.refresh_provider_models(
            "mistral", "key", _fetch=fake_fetch)
        self.assertEqual(models, ["x", "y"])
        self.assertEqual(calls["args"], ("mistral", "key"))
        self.assertEqual(appconfig.provider_models("mistral"), ["x", "y"])

    def test_refresh_failure_keeps_cache(self):
        appconfig.save_provider_models("mistral", ["cached"])

        def boom(provider_id, key):
            raise RuntimeError("network down")

        with self.assertRaises(RuntimeError):
            appconfig.refresh_provider_models("mistral", "k", _fetch=boom)
        self.assertEqual(appconfig.provider_models("mistral"), ["cached"])

    def test_models_are_stale_without_cache(self):
        self.assertTrue(appconfig.models_are_stale("groq"))

    def test_fresh_cache_is_not_stale(self):
        appconfig.save_provider_models("groq", ["a"])
        self.assertFalse(appconfig.models_are_stale("groq"))

    def test_old_cache_is_stale(self):
        appconfig.save_settings({"model_cache": {"groq": {
            "at": int(time.time()) - appconfig.MODEL_CACHE_TTL - 10,
            "models": ["a"]}}})
        self.assertTrue(appconfig.models_are_stale("groq"))


class TestModelTestResults(unittest.TestCase):
    def setUp(self):
        appconfig.save_settings({"model_tests": {}})

    def test_success_is_stored_for_the_model(self):
        self.assertEqual(appconfig.model_test_status("Groq"), {})
        appconfig.save_model_test("Groq", ok=True, model="llama")
        status = appconfig.model_test_status("Groq", "llama")
        self.assertTrue(status["ok"])
        self.assertEqual(status["model"], "llama")
        # A different model has no (valid) result.
        self.assertEqual(appconfig.model_test_status("Groq", "other"), {})

    def test_failure_records_the_error(self):
        appconfig.save_model_test("ChatGPT", ok=False, model="gpt-x",
                                  error="HTTP 401 unauthorized")
        status = appconfig.model_test_status("ChatGPT", "gpt-x")
        self.assertFalse(status["ok"])
        self.assertIn("401", status["error"])

    def test_empty_engine_name_is_ignored(self):
        appconfig.save_model_test("", ok=True, model="x")
        self.assertEqual(appconfig.load_settings().get("model_tests"), {})


if __name__ == "__main__":
    unittest.main()
