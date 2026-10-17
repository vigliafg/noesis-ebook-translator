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

    def test_engine_names_only_show_enabled_providers(self):
        appconfig.set_provider_slots([
            {"enabled": True, "provider": "groq", "api_key": "k",
             "model": "llama"},
        ])
        names = appconfig.engine_names()
        self.assertIn("Groq", names)
        self.assertIn("Google(Free)New", names)
        self.assertNotIn("Mistral", names)  # not configured

        appconfig.set_provider_slots([])
        self.assertNotIn("Groq", appconfig.engine_names())

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
