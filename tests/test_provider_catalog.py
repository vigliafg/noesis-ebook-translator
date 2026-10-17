"""Curated provider catalogue + generic OpenAI-compatible engine (no network).

Everything here is offline: the HTTP helper and the model probe are injected.
"""
import json
import unittest

from noesis_ebook_translator import provider_catalog
from noesis_ebook_translator.engines import builtin_engines
from noesis_ebook_translator.engines import openai_compatible as oc


def _engine(name):
    return next(engine for engine in builtin_engines if engine.name == name)


class TestCatalogue(unittest.TestCase):
    def test_ids_unique_and_resolvable(self):
        ids = [provider.id for provider in provider_catalog.providers()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("groq", ids)
        self.assertIn("opencode-go", ids)
        self.assertIn("custom", ids)
        self.assertIsNotNone(provider_catalog.get("groq"))
        self.assertIsNone(provider_catalog.get("nope"))

    def test_engine_name_and_urls(self):
        self.assertEqual(provider_catalog.engine_name("groq"), "Groq")
        # OpenRouter reuses the verbatim plugin engine.
        self.assertEqual(provider_catalog.engine_name("openrouter"), "OpenRouter")
        self.assertEqual(provider_catalog.base_url("groq"),
                         "https://api.groq.com/openai/v1")
        self.assertEqual(provider_catalog.models_url("groq"),
                         "https://api.groq.com/openai/v1/models")
        # The OpenCode Go model endpoint is *not* base_url + /models.
        self.assertEqual(provider_catalog.models_url("opencode-go"),
                         "https://opencode.ai/inference/go/v1/models")

    def test_bundled_snapshot_has_models(self):
        self.assertTrue(provider_catalog.default_models("groq"))
        self.assertTrue(provider_catalog.default_models("openrouter"))
        self.assertEqual(provider_catalog.default_models("custom"), [])

    def test_openrouter_uses_builtin_engine(self):
        # A provider mapped to a builtin engine must not be re-registered.
        names = [engine.name for engine in builtin_engines]
        self.assertEqual(names.count("OpenRouter"), 1)
        self.assertEqual(names.count("Groq"), 1)


class TestParseModels(unittest.TestCase):
    def test_openai_shape(self):
        payload = {"object": "list", "data": [{"id": "a"}, {"id": "b"}]}
        self.assertEqual(provider_catalog.parse_models(json.dumps(payload)),
                         ["a", "b"])

    def test_gemini_shape(self):
        payload = {"models": [{"name": "models/gemini-2.5-flash"}]}
        self.assertEqual(provider_catalog.parse_models(payload),
                         ["gemini-2.5-flash"])

    def test_strings_and_dedup(self):
        self.assertEqual(provider_catalog.parse_models(
            {"data": ["a", "a", {"model": "b"}]}), ["a", "b"])


class TestFetchModels(unittest.TestCase):
    def test_injected_request(self):
        calls = {}

        def fake_request(url, **kwargs):
            calls["url"] = url
            calls["headers"] = kwargs.get("headers", {})
            return {"data": [{"id": "m1"}, {"id": "m2"}]}

        models = provider_catalog.fetch_models("groq", "secret",
                                               _request=fake_request)
        self.assertEqual(models, ["m1", "m2"])
        self.assertEqual(calls["url"], "https://api.groq.com/openai/v1/models")
        self.assertEqual(calls["headers"]["Authorization"], "Bearer secret")

    def test_unknown_provider(self):
        with self.assertRaises(ValueError):
            provider_catalog.fetch_models("nope", "k", _request=lambda *a, **k: {})

    def test_custom_returns_snapshot(self):
        self.assertEqual(
            provider_catalog.fetch_models("custom", "", _request=None), [])


class TestGenericEngine(unittest.TestCase):
    def setUp(self):
        self.engine = _engine("Groq")
        self._saved = dict(self.engine.config or {})
        self.engine.set_config({"api_keys": ["k"], "model": "llama-3.3-70b",
                                "request_timeout": 5})

    def tearDown(self):
        self.engine.set_config(self._saved)

    def test_endpoint_and_headers(self):
        translator = self.engine()
        translator.set_source_lang("English")
        translator.set_target_lang("Italian")
        self.assertEqual(translator.endpoint,
                         "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(
            translator.get_headers()["Authorization"], "Bearer k")
        body = json.loads(translator.get_body("Hello"))
        self.assertEqual(body["model"], "llama-3.3-70b")
        self.assertEqual(body["messages"][1]["content"], "Hello")

    def test_opencode_go_extra_header(self):
        engine = _engine("OpenCode Go")
        saved = dict(engine.config or {})
        engine.set_config({"api_keys": ["k"], "model": "deepseek-v4.1-flash"})
        try:
            translator = engine()
            self.assertEqual(
                translator.get_headers()["x-opencode-session"],
                "noesis-ebook-translator")
            self.assertTrue(translator.models_endpoint.endswith("/v1/models"))
        finally:
            engine.set_config(saved)

    def test_custom_endpoint_from_config(self):
        engine = _engine("Custom endpoint")
        saved = dict(engine.config or {})
        engine.set_config({"api_keys": [], "model": "qwen",
                           "endpoint": "http://localhost:11434/v1"})
        try:
            translator = engine()
            self.assertEqual(translator.endpoint,
                             "http://localhost:11434/v1/chat/completions")
            self.assertEqual(translator.models_endpoint,
                             "http://localhost:11434/v1/models")
        finally:
            engine.set_config(saved)

    def test_batch_parses_json(self):
        translator = self.engine()
        translator.set_source_lang("English")
        translator.set_target_lang("Italian")
        captured = {}

        def fake_request(url, data=None, headers=None, method=None, **kwargs):
            captured["data"] = json.loads(data)
            return json.dumps({"choices": [{"message": {"content":
                    '{"0": "uno", "1": "due"}'}}]})

        original = oc.request
        oc.request = fake_request
        try:
            result = translator.translate_batch(["one", "two"])
        finally:
            oc.request = original
        self.assertEqual(result, ["uno", "due"])
        self.assertFalse(captured["data"]["stream"])

    def test_get_models_falls_back_to_snapshot(self):
        translator = self.engine()
        original = oc.fetch_models

        def boom(*args, **kwargs):
            raise RuntimeError("offline")

        oc.fetch_models = boom
        try:
            models = translator.get_models()
        finally:
            oc.fetch_models = original
        self.assertTrue(models)  # bundled snapshot for groq


class TestModelProbe(unittest.TestCase):
    class _Fake:
        def __init__(self, result=None, error=None):
            self.result = result
            self.error = error
            self.langs = []

        def set_source_lang(self, value):
            self.langs.append(value)

        def set_target_lang(self, value):
            self.langs.append(value)

        def translate(self, text):
            if self.error:
                raise self.error
            return self.result

    def test_ok(self):
        result = provider_catalog.test_model(
            "groq", "k", "llama",
            translator=self._Fake(result="Ciao"))
        self.assertTrue(result.ok)
        self.assertEqual(result.sample, "Ciao")

    def test_generator_result_is_consumed(self):
        def gen():
            yield "Ci"
            yield "ao"

        result = provider_catalog.test_model(
            "groq", "k", "llama", translator=self._Fake(result=gen()))
        self.assertTrue(result.ok)
        self.assertEqual(result.sample, "Ciao")

    def test_auth_error(self):
        result = provider_catalog.test_model(
            "groq", "k", "llama",
            translator=self._Fake(error=RuntimeError("HTTP 401 unauthorized")))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "auth")

    def test_missing_model(self):
        result = provider_catalog.test_model(
            "groq", "k", "", translator=self._Fake(result="x"))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "model")

    def test_missing_key(self):
        result = provider_catalog.test_model(
            "groq", "", "llama", translator=self._Fake(result="x"))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "auth")

    def test_empty_translation(self):
        result = provider_catalog.test_model(
            "groq", "k", "llama", translator=self._Fake(result="  "))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "empty")


if __name__ == "__main__":
    unittest.main()
