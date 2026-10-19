"""Translation-quality harness tests (offline fake engine / judge)."""
import os
import tempfile
import unittest

from tests.fixtures import (
    build_sample_epub, register_fake_engine, register_score_engine)

from noesis_ebook_translator.quality import (
    evaluate, make_engine_judge, write_report)
from noesis_ebook_translator.quality.metrics import (
    SegmentResult, compute_metrics, digits_preserved, is_untranslated)


class TestMetrics(unittest.TestCase):
    def test_untranslated_detection(self):
        self.assertTrue(is_untranslated("Hello world", "hello world"))
        self.assertFalse(is_untranslated("Hello world", "Ciao mondo"))
        self.assertFalse(is_untranslated("", ""))

    def test_digits_preserved(self):
        self.assertTrue(digits_preserved("Chapter 12, 1900", "Capitolo 12, 1900"))
        self.assertFalse(digits_preserved("Chapter 12", "Capitolo"))

    def test_compute_metrics(self):
        pairs = [
            SegmentResult("a.xhtml", 0, "Hello", "Ciao"),
            SegmentResult("a.xhtml", 1, "Same", "Same"),
            SegmentResult("a.xhtml", 2, "Text", ""),
        ]
        metrics = compute_metrics(pairs)
        self.assertEqual(metrics["total"], 3)
        self.assertEqual(metrics["untranslated"], 1)
        self.assertEqual(metrics["empty"], 1)


class TestEvaluate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-quality-")
        self.src = build_sample_epub(os.path.join(self.tmp, "b.epub"))
        self.out = os.path.join(self.tmp, "b_IT.epub")
        from noesis_ebook_translator import book
        book.translate_epub(
            self.src, self.out, engine="Fake",
            settings={"translation_position": "only", "cache_enabled": False})

    def test_evaluate_with_lambda_judge(self):
        report = evaluate(self.src, self.out, judge=lambda s, t: 90.0,
                          judge_sample=3)
        self.assertEqual(report.metrics["total"], 5)
        self.assertEqual(report.metrics["untranslated"], 0)
        self.assertEqual(report.judge_score, 90.0)
        self.assertTrue(report.judge_samples)

    def test_write_report_markdown_and_json(self):
        report = evaluate(self.src, self.out)
        md = write_report(report, os.path.join(self.tmp, "q.md"))
        js = write_report(report, os.path.join(self.tmp, "q.json"))
        self.assertIn("Translation quality report",
                      open(md, encoding="utf-8").read())
        self.assertIn('"metrics"', open(js, encoding="utf-8").read())


class TestEngineJudge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_score_engine()

    def test_engine_judge_parses_score(self):
        judge = make_engine_judge("FakeScore")
        self.assertEqual(judge("a", "b"), 85.0)

    def test_engine_judge_reads_a_streamed_reply(self):
        """A streaming engine returns a generator: ``str(generator)`` is not the
        reply, so every score used to come out 0."""
        from noesis_ebook_translator.lib.translation import get_engine_class
        from noesis_ebook_translator.quality import judge as judge_mod

        engine_class = get_engine_class("FakeScore")
        original = engine_class.translate

        def streaming(self, content):
            return (chunk for chunk in ("8", "7"))

        engine_class.translate = streaming
        try:
            score = judge_mod.make_engine_judge("FakeScore")("a", "b")
        finally:
            engine_class.translate = original
        self.assertEqual(score, 87.0)


if __name__ == "__main__":
    unittest.main()
