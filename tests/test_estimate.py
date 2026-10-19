"""Token counting and the cost/duration estimate (offline).

``tiktoken`` counts the bundled encodings; the pricing table is a small stub so
the arithmetic is asserted exactly, and a real (fake-engine) run proves the
"already in cache" scope, including the style prompt.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager

from tests.fixtures import build_rich_epub, register_fake_engine

from noesis_ebook_translator import appconfig, book, estimate, provider_catalog
from noesis_ebook_translator import token_count
from noesis_ebook_translator.lib.cache import TranslationCache


@contextmanager
def cache_at(directory: str):
    previous = (TranslationCache.dir_path, TranslationCache.cache_path)
    cache_dir = os.path.join(directory, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    TranslationCache.dir_path = directory
    TranslationCache.cache_path = cache_dir
    try:
        yield cache_dir
    finally:
        TranslationCache.dir_path, TranslationCache.cache_path = previous


class TokenCountTest(unittest.TestCase):
    def test_bundled_encodings_load_offline(self):
        # The whole point of shipping the BPE files: no download, no /tmp.
        self.assertEqual(token_count.backend("gpt-4o"), "tiktoken")
        self.assertEqual(token_count.backend("some-unknown-model"), "tiktoken")

    def test_known_counts(self):
        self.assertEqual(token_count.count("", "gpt-4o"), 0)
        self.assertEqual(token_count.count("hello world", "gpt-4o"), 2)
        self.assertEqual(
            len(token_count.count_many(["hello", "world"], "gpt-4o")), 2)
        self.assertEqual(token_count.count_many([], "gpt-4o"), [])

    def test_special_tokens_do_not_raise(self):
        self.assertGreater(token_count.count("<|endoftext|> and text", "gpt-4o"), 0)

    def test_encoding_by_model(self):
        self.assertEqual(token_count.encoding_name_for("gpt-4o-mini"), "o200k_base")
        self.assertEqual(token_count.encoding_name_for("openai/gpt-4o"), "o200k_base")
        self.assertEqual(token_count.encoding_name_for("gpt-4.1"), "o200k_base")
        self.assertEqual(token_count.encoding_name_for("gpt-4-turbo"), "cl100k_base")
        self.assertEqual(token_count.encoding_name_for("text-embedding-ada-002"),
                         "cl100k_base")
        self.assertEqual(token_count.encoding_name_for("claude-3-7-sonnet"),
                         "o200k_base")

    def test_heuristic_fallback(self):
        self.assertEqual(token_count.backend("gpt-4o"), "tiktoken")
        saved = token_count._encoder
        try:
            token_count._reset_for_tests()
            token_count._encoder = lambda model=None: None   # force the fallback
            self.assertEqual(token_count.backend("gpt-4o"), "heuristic")
            self.assertGreater(token_count.count("hello world", "gpt-4o"), 0)
            # CJK is roughly one token per character, Latin about a quarter.
            latin = token_count.count("a" * 100, "gpt-4o")
            cjk = token_count.count("中" * 100, "gpt-4o")
            self.assertGreater(cjk, latin)
        finally:
            token_count._encoder = saved
            token_count._reset_for_tests()


class EstimateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = register_fake_engine()

    def setUp(self):
        from noesis_ebook_translator.lib.config import get_config

        self.tmp = tempfile.mkdtemp(prefix="estimate-test-")
        self.cache_store = os.path.join(self.tmp, "cache-store")
        self.cache_path = os.path.join(self.cache_store, "cache")
        self.src = build_rich_epub(os.path.join(self.tmp, "book.epub"))
        config = get_config()
        self._cache_enabled = config.get("cache_enabled")
        config.save(cache_enabled=True)
        self._price = provider_catalog.price
        self._dev_map = dict(estimate.ENGINE_TO_MODELS_DEV)
        appconfig.set_engine_preference("Fake", concurrency_limit=1)

    def _pin_price(self, pricing):
        """Give the offline fake engine a price (its models.dev id is a stub)."""
        estimate.ENGINE_TO_MODELS_DEV["Fake"] = "groq"
        provider_catalog.price = lambda provider, model: pricing

    def tearDown(self):
        provider_catalog.price = self._price
        estimate.ENGINE_TO_MODELS_DEV.clear()
        estimate.ENGINE_TO_MODELS_DEV.update(self._dev_map)
        appconfig.set_engine_preference("Fake", concurrency_limit=None)
        from noesis_ebook_translator.lib.config import get_config

        get_config().save(cache_enabled=self._cache_enabled)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_counts_segments_matching_the_engine_plan(self):
        segments = book.collect_segments(self.src, engine="Fake")
        usable = [segment for segment in segments if not segment["ignored"]]
        with cache_at(self.cache_store):
            est = estimate.estimate_book(self.src, engine="Fake",
                                         segments=segments)
        self.assertEqual(est.segments, len(usable))
        self.assertGreater(est.tokens_in, 0)
        self.assertGreater(est.tokens_out, 0)
        self.assertEqual(est.requests, len(usable))
        self.assertEqual(est.backend, "tiktoken")
        self.assertTrue(est.sample)
        # Per-chapter rows sum to the total.
        self.assertEqual(sum(row.segments for row in est.per_chapter),
                         est.segments)
        self.assertEqual(sum(row.tokens_in for row in est.per_chapter),
                         est.tokens_in)

    def test_cost_uses_the_price_table(self):
        self._pin_price((1.0, 2.0))
        with cache_at(self.cache_store):
            est = estimate.estimate_book(
                self.src, engine="Fake", model="stub", segments=book.collect_segments(
                    self.src, engine="Fake"))
        expected = est.tokens_in / 1e6 + 2 * est.tokens_out / 1e6
        self.assertAlmostEqual(est.cost_usd, expected, places=9)
        self.assertEqual(est.pricing, (1.0, 2.0))

    def test_free_and_unknown_prices(self):
        self._pin_price((0.0, 0.0))
        with cache_at(self.cache_store):
            est = estimate.estimate_book(self.src, engine="Fake")
        self.assertEqual(est.cost_usd, 0.0)
        self._pin_price(None)
        with cache_at(self.cache_store):
            est = estimate.estimate_book(self.src, engine="Fake")
        self.assertIsNone(est.cost_usd)

    def test_duration_sequential_parallel_and_batching(self):
        from tests.fixtures import register_fake_engine

        fake = register_fake_engine()
        with cache_at(self.cache_store):
            sequential = estimate.estimate_book(self.src, engine="Fake",
                                                sequential=True)
            parallel = estimate.estimate_book(self.src, engine="Fake",
                                              sequential=False, concurrency=4)
            # The estimate only needs the engine to expose translate_batch.
            fake.translate_batch = lambda self, texts: list(texts)
            try:
                batched = estimate.estimate_book(self.src, engine="Fake",
                                                 batching=True, batch_size=10)
            finally:
                del fake.translate_batch
        self.assertGreater(sequential.seconds, 0)
        self.assertLess(parallel.seconds, sequential.seconds)
        self.assertEqual(parallel.concurrency, 4)
        self.assertEqual(parallel.seconds_low, parallel.seconds * 0.6)
        # Batching divides the requests by the configured batch size.
        self.assertEqual(batched.batch_size, 10)
        self.assertEqual(batched.requests, (batched.segments + 9) // 10)

    def test_cached_segments_are_excluded(self):
        self._pin_price((10.0, 10.0))
        out = os.path.join(self.tmp, "out.epub")
        with cache_at(self.cache_store):
            book.translate_epub(self.src, out, engine="Fake",
                                target_lang="Italian", chapters="1")
            est = estimate.estimate_book(self.src, engine="Fake",
                                         chapters_spec="1")
        self.assertGreater(est.cached_segments, 0)
        self.assertGreater(est.cached_requests, 0)
        self.assertEqual(est.engine_calls, 0)
        self.assertEqual(est.cost_usd, 0.0)     # everything already paid for

    def test_style_prompt_is_part_of_the_cache_scope(self):
        out = os.path.join(self.tmp, "styled.epub")
        with cache_at(self.cache_store):
            book.translate_epub(self.src, out, engine="Fake",
                                target_lang="Italian", chapters="1",
                                style_prompt="Translate as poetry.")
            same = estimate.estimate_book(self.src, engine="Fake", chapters_spec="1",
                                          style_prompt="Translate as poetry.")
            other = estimate.estimate_book(self.src, engine="Fake", chapters_spec="1",
                                           style_prompt="Translate as a manual.")
            none = estimate.estimate_book(self.src, engine="Fake", chapters_spec="1")
        self.assertGreater(same.cached_segments, 0)
        self.assertEqual(other.cached_segments, 0)
        self.assertEqual(none.cached_segments, 0)

    def test_style_prompt_is_appended_to_the_engine_prompt(self):
        seen = []
        original = book.get_translator

        def capture(engine_class):
            translator = original(engine_class)
            seen.append(translator)
            return translator

        book.get_translator = capture
        try:
            with cache_at(self.cache_store):
                book.translate_epub(self.src, os.path.join(self.tmp, "s.epub"),
                                    engine="Fake", target_lang="Italian",
                                    chapters="1",
                                    style_prompt="GENRE-ADDENDUM")
        finally:
            book.get_translator = original
        self.assertTrue(seen)
        prompt = seen[0].prompt
        self.assertIn("GENRE-ADDENDUM", prompt)
        self.assertIn("meticulous translator", prompt)   # base prompt preserved

    def test_observed_latency_reads_previous_runs(self):
        os.makedirs(self.cache_path, exist_ok=True)
        db_path = os.path.join(self.cache_path, "stub.db")
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE info(key UNIQUE, value)")
        connection.executemany(
            "INSERT INTO info VALUES (?, ?)",
            [("engine_name", "Fake"), ("model", "m"),
             ("run_status", "finished"), ("run_batching", "0"),
             ("run_engine_calls", "100"), ("run_concurrency", "2"),
             ("run_started_at", "1000"), ("run_finished_at", "1100")])
        connection.commit()
        connection.close()
        with cache_at(self.cache_store):
            latency = estimate.observed_latency("Fake", "m", False)
        self.assertAlmostEqual(latency, 2.0, places=6)   # 100s * 2 / 100 calls
        with cache_at(self.cache_store):
            self.assertIsNone(estimate.observed_latency("Fake", "other", False))

    def test_sample_segments_is_bounded(self):
        segments = book.collect_segments(self.src, engine="Fake")
        sample = estimate.sample_segments(segments, count=4, chars=50,
                                          total_chars=1000)
        self.assertLessEqual(len(sample), 4)
        self.assertTrue(all(len(text) <= 50 for text in sample))


class StyleScopeResumeTest(unittest.TestCase):
    """The style prompt must behave like the model: its own resumable work."""

    @classmethod
    def setUpClass(cls):
        cls.engine = register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="style-resume-")
        self.cache_store = os.path.join(self.tmp, "cache-store")
        self.cache_path = os.path.join(self.cache_store, "cache")
        self.src = build_rich_epub(os.path.join(self.tmp, "book.epub"))
        from noesis_ebook_translator.lib.config import get_config

        config = get_config()
        self._cache_enabled = config.get("cache_enabled")
        config.save(cache_enabled=True)
        self.calls = 0
        self._translate = self.engine.translate
        test = self

        def counting(engine_self, text):
            test.calls += 1
            return test._translate(engine_self, text)

        self.engine.translate = counting
        appconfig.set_engine_preference("Fake", concurrency_limit=1)

    def tearDown(self):
        self.engine.translate = self._translate
        appconfig.set_engine_preference("Fake", concurrency_limit=None)
        from noesis_ebook_translator.lib.config import get_config

        get_config().save(cache_enabled=self._cache_enabled)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, name, style):
        self.calls = 0
        with cache_at(self.cache_store):
            book.translate_epub(self.src, os.path.join(self.tmp, f"{name}.epub"),
                                engine="Fake", target_lang="Italian",
                                chapters="1", style_prompt=style)
        return self.calls

    def test_same_style_resumes_but_a_different_style_retranslates(self):
        self.assertGreater(self._run("a", "poetry"), 0)
        self.assertEqual(self._run("a2", "poetry"), 0)
        self.assertGreater(self._run("b", "manual"), 0)
        # Switching back restores the first style's work.
        self.assertEqual(self._run("a3", "poetry"), 0)

    def test_style_survives_in_the_interrupted_run(self):
        original = book.epub.write_epub
        book.epub.write_epub = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("power loss"))
        try:
            with cache_at(self.cache_store):
                with self.assertRaises(RuntimeError):
                    book.translate_epub(
                        self.src, os.path.join(self.tmp, "lost.epub"),
                        engine="Fake", target_lang="Italian", chapters="1",
                        style_prompt="POETRY-STYLE", genre="poetry")
        finally:
            book.epub.write_epub = original
        with cache_at(self.cache_store):
            runs = book.interrupted_runs(self.src)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["style_prompt"], "POETRY-STYLE")
        self.assertEqual(runs[0]["genre"], "poetry")
        # A resume with the stored style reinstates everything from the cache.
        self.assertEqual(self._run("resumed", runs[0]["style_prompt"]), 0)

    def test_legacy_resume_table_migrates(self):
        """A cache written before the style column keeps resuming (0 calls)."""
        with cache_at(self.cache_store):
            connection = sqlite3.connect(os.path.join(self.cache_path, "legacy.db"))
            connection.execute(
                "CREATE TABLE noesis_resume(content_hash TEXT NOT NULL, "
                "engine_name TEXT NOT NULL, model TEXT NOT NULL, "
                "source_lang TEXT NOT NULL, target_lang TEXT NOT NULL, "
                "original TEXT, translation TEXT, updated_at INTEGER, "
                "PRIMARY KEY(content_hash, engine_name, model, source_lang, "
                "target_lang))")
            connection.execute("CREATE TABLE info(key UNIQUE, value)")
            connection.execute("CREATE TABLE cache(id UNIQUE, md5 UNIQUE, raw, "
                               "original, ignored, attributes, page, translation, "
                               "engine_name, target_lang)")
            connection.execute(
                "INSERT INTO noesis_resume VALUES (?,?,?,?,?,?,?,?)",
                ("h", "Fake", "", "English", "Italian", "x", "y", 1))
            connection.commit()
            connection.close()
            # Opening a run migrates the table in place, keeping ``style_hash``
            # for the un-styled scope.
            from noesis_ebook_translator.book import _ensure_resume_table

            cache = TranslationCache(
                os.path.splitext("legacy.db")[0], persistence=True)
            try:
                _ensure_resume_table(cache)
                columns = [row[1] for row in cache.cursor.execute(
                    "PRAGMA table_info(noesis_resume)").fetchall()]
                self.assertIn("style_hash", columns)
                rows = cache.cursor.execute(
                    "SELECT style_hash, translation FROM noesis_resume").fetchall()
                self.assertEqual(rows, [("", "y")])
            finally:
                cache.close()


if __name__ == "__main__":
    unittest.main()
