"""Online batching: parallelism, partial replies, truncated JSON.

The batching path is where the engine differs most from the per-segment one: a
request carries 20 segments, a JSON reply can lose entries, and the model may
truncate it. These tests pin the three behaviours the speed test asked for:
batches really overlap, a short reply retries only what is missing, and a
truncated object never yields a half-translated string.
"""
import os
import tempfile
import threading
import time
import unittest

from tests.fixtures import build_rich_epub, register_realistic_engine

from noesis_ebook_translator import appconfig, book
from noesis_ebook_translator.engines import openrouter as openrouter_mod
from noesis_ebook_translator.lib import config as config_mod


class RecordingBatchEngine:
    """Realistic engine whose translate_batch records the calls it receives."""

    calls: list[list[str]] = []
    overlap = 0
    max_overlap = 0
    delay = 0.05
    drop_first = 0

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.overlap = 0
        cls.max_overlap = 0
        cls.drop_first = 0


class BatchTranslationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = register_realistic_engine()
        cls._original = cls.engine.translate_batch
        cls._lock = threading.Lock()

        def translate_batch(engine_self, texts):
            with cls._lock:
                RecordingBatchEngine.overlap += 1
                RecordingBatchEngine.max_overlap = max(
                    RecordingBatchEngine.max_overlap,
                    RecordingBatchEngine.overlap)
                RecordingBatchEngine.calls.append(list(texts))
                drop = RecordingBatchEngine.drop_first
                if drop:
                    RecordingBatchEngine.drop_first -= 1
            try:
                time.sleep(RecordingBatchEngine.delay)
                results = [engine_self._reply(text, stream=False)
                           for text in texts]
                # Mirror a model that drops ids: blank entries.
                if drop:
                    results = ["" if index < drop else value
                               for index, value in enumerate(results)]
                return results
            finally:
                with cls._lock:
                    RecordingBatchEngine.overlap -= 1

        cls.engine.translate_batch = translate_batch

    @classmethod
    def tearDownClass(cls):
        cls.engine.translate_batch = cls._original

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-batch-")
        self.src = build_rich_epub(os.path.join(self.tmp, "batch.epub"))
        self.out = os.path.join(self.tmp, "out.epub")
        RecordingBatchEngine.reset()
        self._config = config_mod.get_config()
        self._saved = {key: self._config.get(key)
                       for key in ("online_batching", "batch_size")}
        self._config.set("online_batching", True)
        self._config.set("batch_size", 5)
        self._config.commit()
        appconfig.set_engine_preference(
            "Realistic", concurrency_limit=1, api_keys=["k"])

    def tearDown(self):
        for key, value in self._saved.items():
            self._config.set(key, value)
        self._config.commit()
        appconfig.set_engine_preference("Realistic", concurrency_limit=None)

    def test_batches_run_in_parallel(self):
        appconfig.set_engine_preference("Realistic", concurrency_limit=4)
        RecordingBatchEngine.delay = 0.08
        book.translate_epub(self.src, self.out, engine="Realistic",
                            source_lang="English", target_lang="Italian")
        self.assertGreater(RecordingBatchEngine.max_overlap, 1,
                           "batches were issued one at a time")

    def test_batch_size_comes_from_the_configuration(self):
        book.translate_epub(self.src, self.out, engine="Realistic",
                            source_lang="English", target_lang="Italian")
        sizes = {len(call) for call in RecordingBatchEngine.calls}
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), 5,
                             f"batch_size ignored: {sizes}")

    def test_a_short_reply_retries_only_the_missing_segments(self):
        RecordingBatchEngine.drop_first = 2   # first call loses two ids
        book.translate_epub(self.src, self.out, engine="Realistic",
                            source_lang="English", target_lang="Italian")
        full = max((len(call) for call in RecordingBatchEngine.calls),
                   default=0)
        retry = min((len(call) for call in RecordingBatchEngine.calls[1:]),
                    default=0)
        self.assertGreater(len(RecordingBatchEngine.calls), 1)
        self.assertLess(retry, full,
                        "the retry re-sent the whole batch instead of the gaps")


class JsonRepairTest(unittest.TestCase):
    def test_truncated_object_keeps_the_complete_pairs(self):
        parse = openrouter_mod._parse_json_object
        self.assertEqual(parse('{"0": "a", "1": "b"'), {"0": "a", "1": "b"})
        # Cut mid-string: the half translation must be dropped, never accepted.
        self.assertEqual(parse('{"0": "a", "1": "trunc'), {"0": "a"})
        self.assertEqual(parse('```json\n{"0": "a"}\n```'), {"0": "a"})
        self.assertIsNone(parse("not json at all"))

    def test_batch_returns_empty_ids_instead_of_mismatched_values(self):
        saved_config = dict(openrouter_mod.OpenRouterTranslate.config)
        saved_request = openrouter_mod.request
        openrouter_mod.request = lambda **kwargs: (
            '{"choices": [{"message": {"content": "{\\"0\\": \\"uno\\"}"}}]}')
        try:
            openrouter_mod.OpenRouterTranslate.set_config(
                {"api_keys": ["k"], "model": "m"})
            translator = openrouter_mod.OpenRouterTranslate()
            translator.set_source_lang("English")
            translator.set_target_lang("Italian")
            self.assertEqual(translator.translate_batch(["one", "two"]),
                             ["uno", ""])
        finally:
            openrouter_mod.request = saved_request
            openrouter_mod.OpenRouterTranslate.set_config(saved_config)


if __name__ == "__main__":
    unittest.main()
