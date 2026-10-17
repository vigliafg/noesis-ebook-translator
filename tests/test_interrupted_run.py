"""The *app* must know a translation was interrupted.

The engine already resumes by itself (``tests/test_resume.py``), but only when the
same translation is started again: after a power cut nothing told the user that
hours of work were sitting in the cache. Every run now leaves a marker in the
cache's ``info`` table (``running`` / ``finished`` / ``cancelled`` / ``dismissed``),
``book.interrupted_runs`` discovers the ``running`` ones and the window offers to
continue exactly where the run stopped.

Offline, with the fake engine of ``tests/fixtures.py``.
"""
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from glob import glob

from tests.fixtures import build_rich_epub, register_fake_engine

from noesis_ebook_translator import appconfig, book
from noesis_ebook_translator.lib.cache import TranslationCache

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    _HAS_GUI = True
except Exception:  # noqa: BLE001 - optional dependency
    _HAS_GUI = False


@contextmanager
def cache_at(directory: str):
    """Point the pipeline (and discovery) at a private cache directory."""
    previous = (TranslationCache.dir_path, TranslationCache.cache_path)
    cache_dir = os.path.join(directory, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    TranslationCache.dir_path = directory
    TranslationCache.cache_path = cache_dir
    try:
        yield cache_dir
    finally:
        TranslationCache.dir_path, TranslationCache.cache_path = previous


def _info(cache_path: str) -> dict:
    files = glob(os.path.join(cache_path, "*.db"))
    if not files:
        return {}
    connection = sqlite3.connect(max(files, key=os.path.getmtime))
    try:
        return {str(key): value
                for key, value in connection.execute("SELECT key, value FROM info")}
    finally:
        connection.close()


class RunMarkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="interrupted-test-")
        self.cache_store = os.path.join(self.tmp, "cache-store")
        self.cache_path = os.path.join(self.cache_store, "cache")
        self.src = build_rich_epub(os.path.join(self.tmp, "book.epub"))
        # Other suites run the pipeline with ``cache_enabled: False`` and that
        # setting persists in the shared config: a persistent cache is what this
        # file is about, so pin it (and put it back afterwards).
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

    def _run(self, name="out", **kwargs):
        self.calls = 0
        with cache_at(self.cache_store):
            out = os.path.join(self.tmp, f"{name}.epub")
            book.translate_epub(self.src, out, engine="Fake",
                                target_lang="Italian", chapters="1", **kwargs)
        return out

    def _run_failing_at_the_save(self, name="broken"):
        """A run that translates everything and then dies writing the EPUB."""
        out = os.path.join(self.tmp, f"{name}.epub")
        original = book.epub.write_epub

        def broken(path, book_obj, *args, **kwargs):
            raise RuntimeError("power loss while saving")

        book.epub.write_epub = broken
        try:
            with cache_at(self.cache_store):
                with self.assertRaises(RuntimeError):
                    book.translate_epub(self.src, out, engine="Fake",
                                        target_lang="Italian", chapters="1")
        finally:
            book.epub.write_epub = original
        return out

    # ------------------------------------------------------------------
    def test_output_base_name_inverts_output_name(self):
        self.assertEqual(book.output_base_name("/x/Dune-italian.epub", "Italian"),
                         "Dune")
        self.assertEqual(
            book.output_base_name("Book-chinese-simplified.epub",
                                  "Chinese (Simplified)"), "Book")
        self.assertEqual(book.output_base_name("/x/Dune.epub", "Italian"), "Dune")
        self.assertEqual(book.output_base_name("", "Italian"), "book")

    def test_finished_run_is_not_offered(self):
        self._run()
        self.assertEqual(_info(self.cache_path)["run_status"], "finished")
        self.assertEqual(
            book.interrupted_runs(self.src, directory=self.cache_path), [])

    def test_cancelled_run_is_not_offered(self):
        def should_cancel():
            return _count(self.cache_path) >= 2

        with cache_at(self.cache_store):
            with self.assertRaises(book.TranslationCanceled):
                book.translate_epub(
                    self.src, os.path.join(self.tmp, "cancel.epub"),
                    engine="Fake", target_lang="Italian", chapters="1",
                    should_cancel=should_cancel)
        self.assertEqual(_info(self.cache_path)["run_status"], "cancelled")
        self.assertEqual(
            book.interrupted_runs(self.src, directory=self.cache_path), [])

    def test_abrupt_death_is_offered_with_its_own_context(self):
        self._run_failing_at_the_save()
        self.assertEqual(_info(self.cache_path)["run_status"], "running")

        runs = book.interrupted_runs(self.src, directory=self.cache_path)
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["engine"], "Fake")
        self.assertEqual(run["target_lang"], "Italian")
        self.assertEqual(run["chapters"], "1")
        self.assertEqual(run["title"], "book.epub")
        self.assertEqual(os.path.abspath(run["input_path"]),
                         os.path.abspath(self.src))
        self.assertTrue(run["output_path"].endswith("broken.epub"))
        self.assertGreater(run["total"], 0)
        self.assertEqual(run["done"], run["total"])

    def test_discovery_is_read_only_and_scoped_to_the_book(self):
        self._run_failing_at_the_save()
        db = glob(os.path.join(self.cache_path, "*.db"))[0]
        before = (os.path.getmtime(db), os.path.getsize(db))
        time.sleep(0.02)
        # Another book must not see this run...
        self.assertEqual(
            book.interrupted_runs(os.path.join(self.tmp, "other.epub"),
                                  directory=self.cache_path), [])
        # ...and looking must not touch the cache file.
        self.assertEqual(len(book.interrupted_runs(
            self.src, directory=self.cache_path)), 1)
        self.assertEqual((os.path.getmtime(db), os.path.getsize(db)), before)

    def test_dismissing_stops_the_offer_but_keeps_the_work(self):
        self._run_failing_at_the_save()
        run = book.interrupted_runs(self.src, directory=self.cache_path)[0]
        book.dismiss_interrupted_run(run)
        self.assertEqual(
            book.interrupted_runs(self.src, directory=self.cache_path), [])
        self.assertEqual(_info(self.cache_path)["run_status"], "dismissed")

        # The translations are untouched: resuming the same run costs nothing.
        self._run("resumed")
        self.assertEqual(self.calls, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "resumed.epub")))

    def test_missing_directory_is_not_an_error(self):
        self.assertEqual(
            book.interrupted_runs(self.src, directory=self.tmp), [])
        book.dismiss_interrupted_run({"cache_path": os.path.join(self.tmp, "no.db")})


def _count(cache_path: str) -> int:
    files = glob(os.path.join(cache_path, "*.db"))
    if not files:
        return 0
    connection = sqlite3.connect(files[0])
    try:
        return int(connection.execute(
            "SELECT COUNT(*) FROM cache WHERE NOT ignored AND translation "
            "IS NOT NULL AND translation<>''").fetchone()[0])
    finally:
        connection.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class OfferResumeTest(unittest.TestCase):
    """The window must ask, and 'Yes' must rebuild the *same* run."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.engine = register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="offer-resume-")
        self.cache_store = os.path.join(self.tmp, "cache-store")
        self.cache_path = os.path.join(self.cache_store, "cache")
        self.src = build_rich_epub(os.path.join(self.tmp, "book.epub"))
        self.question = QMessageBox.question
        appconfig.ensure_defaults()
        from noesis_ebook_translator.lib.config import get_config

        config = get_config()
        self._cache_enabled = config.get("cache_enabled")
        config.save(cache_enabled=True)
        appconfig.set_engine_preference("Fake", concurrency_limit=1)
        self._window = None

    def tearDown(self):
        QMessageBox.question = self.question
        appconfig.set_engine_preference("Fake", concurrency_limit=None)
        from noesis_ebook_translator.lib.config import get_config

        get_config().save(cache_enabled=self._cache_enabled)
        if self._window is not None:
            self._window.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_interrupted_run(self, name="lost"):
        """Leave a ``running`` marker for ``self.src`` (no EPUB written)."""
        original = book.epub.write_epub

        def broken(path, book_obj, *args, **kwargs):
            raise RuntimeError("power loss while saving")

        book.epub.write_epub = broken
        try:
            with cache_at(self.cache_store):
                with self.assertRaises(RuntimeError):
                    book.translate_epub(
                        self.src, os.path.join(self.tmp, f"{name}.epub"),
                        engine="Fake", target_lang="Italian", chapters="1")
        finally:
            book.epub.write_epub = original

    def _window_for(self, answer):
        import main

        QMessageBox.question = staticmethod(lambda *args, **kwargs: answer)
        return main.MainWindow()

    def test_no_dismisses_the_run(self):
        self._make_interrupted_run()
        with cache_at(self.cache_store):
            window = self._window_for(QMessageBox.StandardButton.No)
            self._window = window
            window._apply_source(self.src)
            self.assertIsNone(window.worker)
        self.assertEqual(
            book.interrupted_runs(self.src, directory=self.cache_path), [])
        self.assertEqual(_info(self.cache_path)["run_status"], "dismissed")

    def test_yes_rebuilds_the_same_run(self):
        self._make_interrupted_run()
        seen = []
        with cache_at(self.cache_store):
            window = self._window_for(QMessageBox.StandardButton.Yes)
            self._window = window
            window._resume_run = seen.append
            window._apply_source(self.src)
        self.assertEqual(len(seen), 1)
        run = seen[0]
        self.assertEqual(run["engine"], "Fake")
        self.assertEqual(run["target_lang"], "Italian")
        self.assertEqual(run["chapters"], "1")
        self.assertGreater(run["done"], 0)

    def test_resume_configuration_reuses_engine_model_and_selection(self):
        captured = []
        with cache_at(self.cache_store):
            window = self._window_for(QMessageBox.StandardButton.No)
            self._window = window
            window._start_translation = captured.append
            engine = window.cmb_engine.itemText(0)
            appconfig.set_engine_preference(engine,
                                            api_keys=["key-1", "key-2"])
            try:
                run = {
                    "engine": engine,
                    "model": "some-model",
                    "source_lang": "English",
                    "target_lang": "Italian",
                    "chapters": "1",
                    "output_path": os.path.join(self.tmp, "book-italian.epub"),
                    "options": {"translation_position": "below",
                                "cache_enabled": True, "online_batching": False,
                                "sequential": False},
                }
                window._resume_run(run)
            finally:
                appconfig.set_engine_preference(engine, api_keys=[])
        self.assertEqual(len(captured), 1)
        cfg = captured[0]
        self.assertEqual(cfg["engine"], run["engine"])
        self.assertEqual(cfg["model"], "some-model")
        self.assertEqual(cfg["source"], "English")
        self.assertEqual(cfg["target"], "Italian")
        self.assertEqual(cfg["chapters"], "1")
        self.assertTrue(cfg["bilingual"])
        self.assertFalse(cfg["sequential"])
        # Key rotation must survive a resume, not collapse to the first key.
        self.assertEqual(cfg["api_keys"], ["key-1", "key-2"])
        self.assertEqual(cfg["api_key"], "key-1")
        self.assertEqual(cfg["folder"], self.tmp)
        # The suffix must not be doubled: "<name>-<language>.epub".
        self.assertEqual(cfg["name"], "book")

    def test_resume_reports_an_engine_that_is_gone(self):
        messages = []
        with cache_at(self.cache_store):
            window = self._window_for(QMessageBox.StandardButton.No)
            self._window = window
            window._start_translation = lambda cfg: messages.append(cfg)
            window._status_message = lambda text, title=None: messages.append(text)
            window._resume_run({"engine": "NotAProvider", "target_lang": "Italian"})
        self.assertEqual(len(messages), 1)
        self.assertNotIsInstance(messages[0], dict)


if __name__ == "__main__":
    unittest.main()
