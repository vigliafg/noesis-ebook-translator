"""Crash-safe resume: a power cut must not lose a translated segment.

Everything runs offline with the fake engine of ``tests/fixtures.py``. The
engine-call counter is the assertion that matters: a resumed run must ask the
engine **only** for segments that were not already committed.

Each test points the translation cache at its own directory (the plugin's
default cache lives in a shared temporary path, which would leak between
tests).
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import contextmanager
from glob import glob

from tests.fixtures import build_rich_epub, register_fake_engine

from noesis_ebook_translator import appconfig, book
from noesis_ebook_translator.lib.cache import TranslationCache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextmanager
def cache_at(directory: str):
    """Run the pipeline against a private cache directory."""
    previous = (TranslationCache.dir_path, TranslationCache.cache_path)
    cache_dir = os.path.join(directory, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    TranslationCache.dir_path = directory
    TranslationCache.cache_path = cache_dir
    try:
        yield cache_dir
    finally:
        TranslationCache.dir_path, TranslationCache.cache_path = previous


def _db(cache_path: str) -> str | None:
    files = glob(os.path.join(cache_path, "*.db"))
    return max(files, key=os.path.getmtime) if files else None


def _count(cache_path: str, sql: str) -> int:
    path = _db(cache_path)
    if not path:
        return 0
    con = sqlite3.connect(path)
    try:
        return int(con.execute(sql).fetchone()[0])
    finally:
        con.close()


def _translated(cache_path: str) -> int:
    return _count(cache_path, "SELECT COUNT(*) FROM cache WHERE NOT ignored "
                              "AND translation IS NOT NULL AND translation<>''")


def _total(cache_path: str) -> int:
    return _count(cache_path, "SELECT COUNT(*) FROM cache WHERE NOT ignored")


def _missing(cache_path: str) -> int:
    return _count(cache_path, "SELECT COUNT(*) FROM cache WHERE NOT ignored "
                              "AND (translation IS NULL OR translation='')")


class ResumeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="resume-test-")
        self.cache_store = os.path.join(self.tmp, "cache-store")
        self.cache_path = os.path.join(self.cache_store, "cache")
        self.src = build_rich_epub(os.path.join(self.tmp, "book.epub"))
        self.calls = 0
        self._translate = self.engine.translate
        test = self

        def counting(engine_self, text):
            test.calls += 1
            return test._translate(engine_self, text)

        self.engine.translate = counting
        # Deterministic interruption: one segment at a time.
        appconfig.set_engine_preference("Fake", concurrency_limit=1)

    def tearDown(self):
        self.engine.translate = self._translate
        appconfig.set_engine_preference("Fake", concurrency_limit=None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, spec, name="out", **kwargs):
        self.calls = 0
        with cache_at(self.cache_store):
            out = os.path.join(self.tmp, f"{name}.epub")
            book.translate_epub(self.src, out, engine="Fake",
                                target_lang="Italian", chapters=spec, **kwargs)
        return out

    # ------------------------------------------------------------------
    def test_same_selection_resumes_without_engine_calls(self):
        self._run("1")
        self.assertGreater(self.calls, 0)
        self._run("1")
        self.assertEqual(self.calls, 0)

    def test_another_selection_does_not_destroy_work(self):
        self._run("1")
        self._run("2")
        # Coming back to chapter 1 must restore it from the content-keyed table.
        self._run("1")
        self.assertEqual(self.calls, 0)

    def test_narrowing_and_expanding_the_selection(self):
        self._run("1-3")
        self._run("1")            # narrow: rebuilds the positional cache table
        self._run("1-3")          # expand: everything must come from resume
        self.assertEqual(self.calls, 0)

    def test_model_change_does_not_mix_and_switches_back(self):
        original = getattr(self.engine, "model", None)
        try:
            self.engine.model = "model-a"
            self._run("1-3", "a")
            self.assertGreater(self.calls, 0)

            self.engine.model = "model-b"
            self._run("1-3", "b")
            self.assertGreater(self.calls, 0)      # no reuse across models

            self.engine.model = "model-a"
            self._run("1-3", "a2")
            self.assertEqual(self.calls, 0)        # model-a work restored
        finally:
            if original is None:
                self.engine.model = ""
            else:
                self.engine.model = original

    def test_cancelled_run_resumes_from_the_cache(self):
        def should_cancel():
            return _translated(self.cache_path) >= 3

        out = os.path.join(self.tmp, "cancelled.epub")
        with cache_at(self.cache_store):
            with self.assertRaises(book.TranslationCanceled):
                book.translate_epub(self.src, out, engine="Fake",
                                    target_lang="Italian", chapters="1-3",
                                    should_cancel=should_cancel)
        self.assertFalse(os.path.exists(out))
        done = _translated(self.cache_path)
        self.assertGreaterEqual(done, 3)
        missing = _missing(self.cache_path)

        self._run("1-3")
        # Identical source text shares one translation, so the engine may be
        # asked for even fewer segments than there are rows: never more.
        self.assertLessEqual(self.calls, missing)
        self.assertGreater(self.calls, 0)
        self.assertEqual(_missing(self.cache_path), 0)

    def test_on_resume_reports_cached_segments(self):
        self._run("1")
        seen = []
        self._run("1", on_resume=lambda done, total: seen.append((done, total)))
        self.assertTrue(seen)
        done, total = seen[-1]
        self.assertGreater(done, 0)
        self.assertEqual(done, total)      # fully cached before translating
        self.assertEqual(self.calls, 0)

    def test_app_uses_a_persistent_cache_directory(self):
        """A reboot must not wipe the cache: it lives under the app data dir."""
        cfg = os.path.join(self.tmp, "appcfg")
        env = dict(os.environ, NOESIS_CONFIG_DIR=cfg, QT_QPA_PLATFORM="offscreen")
        code = (
            "import main\n"
            "from noesis_ebook_translator.paths import data_dir\n"
            "from noesis_ebook_translator.lib.cache import TranslationCache\n"
            "print(TranslationCache.cache_path)\n"
            "print(data_dir())\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cache_path, data_dir = proc.stdout.strip().splitlines()
        self.assertTrue(cache_path.startswith(str(data_dir) + os.sep),
                        cache_path)
        self.assertIn("translator-cache", cache_path)

    def test_cache_dir_follows_the_configured_path(self):
        from pathlib import Path

        from noesis_ebook_translator.lib.config import get_config
        from noesis_ebook_translator.paths import cache_dir

        config = get_config()
        previous = config.get("cache_path") or ""
        try:
            config.save(cache_path=self.cache_store)
            self.assertEqual(Path(cache_dir()), Path(self.cache_path))
        finally:
            config.save(cache_path=previous)

    def test_final_write_is_atomic(self):
        out = os.path.join(self.tmp, "atomic.epub")
        original = book.epub.write_epub

        def broken(path, book_obj, *args, **kwargs):
            with open(path, "wb") as handle:
                handle.write(b"partial")
            raise RuntimeError("power loss")

        book.epub.write_epub = broken
        try:
            with cache_at(self.cache_store):
                with self.assertRaises(RuntimeError):
                    book.translate_epub(self.src, out, engine="Fake",
                                        target_lang="Italian", chapters="1")
        finally:
            book.epub.write_epub = original
        # No half-written EPUB, no leftover temporary file.
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.exists(out + ".part"))

    @unittest.skipIf(os.name == "nt", "SIGKILL semantics")
    def test_sigkill_mid_run_then_resume(self):
        """The real scenario: the process dies (power cut) while translating."""
        out = os.path.join(self.tmp, "killed.epub")
        runner = os.path.join(self.tmp, "runner.py")
        with open(runner, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(f"""
                import os, sys, time
                sys.path.insert(0, {ROOT!r})
                from tests.fixtures import register_fake_engine
                from noesis_ebook_translator import appconfig, book
                from noesis_ebook_translator.lib.cache import TranslationCache
                TranslationCache.dir_path = {self.cache_store!r}
                TranslationCache.cache_path = {self.cache_path!r}
                os.makedirs(TranslationCache.cache_path, exist_ok=True)
                count = 0
                FAKE = register_fake_engine()
                appconfig.set_engine_preference("Fake", concurrency_limit=1)
                _original = FAKE.translate
                def slow(self, text):
                    global count
                    time.sleep(0.25)
                    count += 1
                    return _original(self, text)
                FAKE.translate = slow
                book.translate_epub({self.src!r}, {out!r}, engine="Fake",
                                    target_lang="Italian", chapters="1-3")
                print("CALLS=%d" % count, flush=True)
            """))

        proc = subprocess.Popen(
            [sys.executable, runner], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 60
        try:
            while time.time() < deadline:
                if _translated(self.cache_path) >= 2:
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(_translated(self.cache_path), 2,
                                    "the child never committed a segment")
            proc.kill()                       # like pulling the plug
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:  # pragma: no cover - defensive
                proc.kill()
                proc.wait(timeout=10)
            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
            proc.stdout.close()
            proc.stderr.close()

        done = _translated(self.cache_path)
        total = _total(self.cache_path)
        self.assertGreater(done, 0, stderr)
        self.assertLess(done, total, "the child finished before the kill")

        # A real death leaves the marker from which the app discovers the run.
        runs = book.interrupted_runs(self.src, directory=self.cache_path)
        self.assertEqual(len(runs), 1, runs)
        self.assertEqual(runs[0]["engine"], "Fake")
        self.assertEqual(runs[0]["done"], done)
        self.assertEqual(runs[0]["total"], total)

        self._run("1-3", "resumed")
        self.assertLessEqual(self.calls, total - done)
        self.assertGreater(self.calls, 0)
        self.assertEqual(_missing(self.cache_path), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "resumed.epub")))


if __name__ == "__main__":
    unittest.main()
