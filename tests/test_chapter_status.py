"""Cache coverage on open: the chapter panel must know what was already done.

A run persists its per-document plan and its translations in the cache. These
tests prove that :func:`book.chapter_cache_status` reads them back for the whole
book or for the last selection, and that the Translate view seeds the chapter
model before the user starts anything.
"""
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001 - optional dependency
    _HAS_GUI = False

from tests.fixtures import build_rich_epub, register_fake_engine

from noesis_ebook_translator import book
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


class ChapterCacheStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-status-")
        self.app = None
        # Other tests legitimately run with the cache disabled; restore it here
        # so this test exercises the real cache path regardless of order.
        from noesis_ebook_translator.lib.config import get_config

        self._config = get_config()
        self._cache_enabled = self._config.get("cache_enabled")
        self._config.save(cache_enabled=True)

    def tearDown(self):
        if self.app is not None:
            self.app.processEvents()
        self._config.save(cache_enabled=self._cache_enabled)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, chapters=None):
        src = build_rich_epub(os.path.join(self.tmp, "book.epub"))
        out = os.path.join(self.tmp, "out.epub")
        with cache_at(self.tmp):
            book.translate_epub(
                src, out, engine="Fake", source_lang="English",
                target_lang="Italian", chapters=chapters)
            return src, book.chapter_cache_status(src)

    def test_a_full_run_is_reported_for_every_document(self):
        _src, status = self._run()
        self.assertTrue(status["plan"])
        self.assertTrue(status["cached"])
        for page, total in status["plan"].items():
            self.assertEqual(status["cached"].get(page, 0), total, page)
        self.assertIsNone(status["chapters"])

    def test_a_selection_reports_only_the_selected_documents(self):
        _src, status = self._run(chapters=["c1.xhtml"])
        self.assertEqual(set(status["plan"]), {"c1.xhtml"})
        self.assertEqual(status["cached"].get("c1.xhtml"),
                         status["plan"]["c1.xhtml"])
        self.assertEqual(status["chapters"], ["c1.xhtml"])

    def test_no_cache_is_not_an_error(self):
        src = build_rich_epub(os.path.join(self.tmp, "fresh.epub"))
        self.assertEqual(book.chapter_cache_status(src), {})

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_opening_the_book_seeds_the_panel_with_the_cache(self):
        import main

        src, status = self._run()
        self.app = QApplication.instance() or QApplication(["noesis-status"])
        with cache_at(self.tmp):
            window = main.MainWindow()
            try:
                window._input_path = src
                window._show_toc(src)
                model = window.translate_view.model()
                self.assertIsNotNone(model)
                self.assertEqual(model.plan, status["plan"])
                for page, cached in status["cached"].items():
                    self.assertEqual(model.done.get(page), cached, page)
                # No run is active: the panel must not animate.
                self.assertTrue(model.finished)
                self.assertEqual(model.running_units(), [])
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
