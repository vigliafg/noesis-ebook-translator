"""Genre analysis and style prompt (the LLM call is injected)."""
import unittest

from tests.fixtures import register_fake_engine

from noesis_ebook_translator import provider_catalog, text_analysis


class ParseTest(unittest.TestCase):
    def test_parses_plain_json(self):
        result = text_analysis.parse_analysis(
            '{"category": "fiction", "genre": "novel", "confidence": 0.9, '
            '"guidance": ["keep names", "- keep dates"]}')
        self.assertTrue(result.ok)
        self.assertEqual(result.label, "novel")
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.guidance, ["keep names", "keep dates"])

    def test_parses_fenced_json_with_prose(self):
        raw = ("Here is the analysis:\n```json\n"
               '{"category": "poetry", "genre": "verse", "subgenre": "epic"}\n'
               "```\nHope it helps!")
        result = text_analysis.parse_analysis(raw)
        self.assertTrue(result.ok)
        self.assertEqual(result.category, "poetry")
        self.assertEqual(result.label, "verse — epic")

    def test_unknown_category_falls_back(self):
        result = text_analysis.parse_analysis(
            '{"category": "sci-fi-western", "genre": "x"}')
        self.assertEqual(result.category, "other")

    def test_invalid_reply_is_reported(self):
        result = text_analysis.parse_analysis("I cannot do that.")
        self.assertFalse(result.ok)
        self.assertIn("invalid JSON", result.error)
        self.assertEqual(text_analysis.parse_analysis("").error, "empty reply")

    def test_guidance_is_capped_and_cleaned(self):
        result = text_analysis.parse_analysis(
            '{"category": "fiction", "genre": "x", "guidance": '
            '["a", "b", "c", "d", "e", "f", "g", "h"]}')
        self.assertEqual(len(result.guidance), 6)


class PromptTest(unittest.TestCase):
    def _result(self, **kwargs):
        payload = {"category": "technical", "genre": "manual",
                   "register": "formal", "tone": "neutral",
                   "audience": "engineers", "guidance": ["keep units"]}
        payload.update(kwargs)
        return text_analysis.parse_analysis(__import__("json").dumps(payload))

    def test_style_prompt_keeps_integrity_rules(self):
        prompt = text_analysis.build_style_prompt(self._result())
        self.assertIn("manual", prompt)
        self.assertIn("keep units", prompt)
        self.assertIn("Never summarise", prompt)
        self.assertIn("placeholder", prompt)

    def test_category_guidance_differs(self):
        poetry = text_analysis.build_style_prompt(self._result(category="poetry"))
        self.assertIn("line breaks", poetry)

    def test_failed_analysis_falls_back_to_generic(self):
        prompt = text_analysis.build_style_prompt(
            text_analysis.AnalysisResult(error="boom"))
        self.assertIn("Never summarise", prompt)
        self.assertEqual(prompt, text_analysis.generic_style_prompt())

    def test_analysis_prompt_carries_excerpts_and_context(self):
        prompt = text_analysis.analysis_prompt(
            ["one", "two"], title="Book", author="Author", source_lang="English")
        self.assertIn("Title: Book", prompt)
        self.assertIn("EXCERPT 1", prompt)
        self.assertIn("DATA", prompt)


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.segments = [
            {"page": "c1.xhtml", "anchor": "", "ignored": False,
             "text": "This is a long enough sentence to be used as a sample."},
            {"page": "c2.xhtml", "anchor": "", "ignored": False,
             "text": "Another long enough sentence, for the analysis sample."},
        ]

    def test_analyze_uses_the_injected_runner(self):
        seen = []

        def runner(prompt):
            seen.append(prompt)
            return '{"category": "fiction", "genre": "novel", "confidence": 0.5}'

        result = text_analysis.analyze(self.segments, runner=runner,
                                       title="T", source_lang="English")
        self.assertTrue(result.ok)
        self.assertEqual(result.genre, "novel")
        self.assertEqual(len(seen), 1)
        self.assertIn("EXCERPT", seen[0])
        self.assertGreater(result.prompt_tokens, 0)

    def test_analyze_reports_a_failing_runner(self):
        def runner(prompt):
            raise RuntimeError("no network")

        result = text_analysis.analyze(self.segments, runner=runner)
        self.assertFalse(result.ok)
        self.assertIn("no network", result.error)

    def test_no_text_to_analyse(self):
        result = text_analysis.analyze([], runner=lambda prompt: "{}")
        self.assertFalse(result.ok)


class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = register_fake_engine()

    def test_runner_uses_a_transient_subclass(self):
        runner = text_analysis.make_runner("Fake", "model-x", "",
                                           source_lang="English",
                                           target_lang="Italian")
        self.assertEqual(runner("hello"), "IT<hello>")
        # The shared engine class keeps its own prompt.
        self.assertNotEqual(self.engine.prompt, text_analysis.ANALYSIS_INSTRUCTIONS)


class CostTest(unittest.TestCase):
    def setUp(self):
        self._price = provider_catalog.price

    def tearDown(self):
        provider_catalog.price = self._price

    def test_cost_is_computed_from_the_price(self):
        provider_catalog.price = lambda provider, model: (2.0, 2.0)
        info = text_analysis.analysis_cost("a" * 400, engine="Groq",
                                           model="x", output_tokens=100)
        self.assertGreater(info["input_tokens"], 0)
        self.assertAlmostEqual(info["cost_usd"],
                               (info["input_tokens"] + 100) / 1e6 * 2.0)

    def test_cost_is_none_without_a_price(self):
        provider_catalog.price = lambda provider, model: None
        info = text_analysis.analysis_cost("text", engine="Groq", model="x")
        self.assertIsNone(info["cost_usd"])


if __name__ == "__main__":
    unittest.main()
