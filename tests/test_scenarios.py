"""End-to-end scenario tests that assert **state invariants**.

``tests/harness.py::run_feature_harness`` is a *smoke* check ("did it open?").
The scenarios here assert *what the run ended up with*: every segment the engine
planned was processed, no chapter was left half-done, the output carries the
translation in every document and in every TOC level. A watchdog turns a stall
into a red test instead of a frozen suite.

The matrix was written *before* the fix it guards: playing it against the old
``book._ensure_cache_rows`` fails on ``partial_cache``,
``large_cache_new_chapter``, ``chapter_added_before_cache`` and
``selection_shrinks`` (a positional cache match crossed the segments, leaving
chapters in the source language).
"""
import os
import shutil
import tempfile
import time
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import build_rich_epub, register_fake_engine
from tests.harness import run_scenario_matrix, run_translation_scenario

_EXPECTED_CONDITIONS = {
    "whole_book", "all_cached", "partial_cache", "large_cache_new_chapter",
    "chapter_added_before_cache", "selection_shrinks", "single_chapter",
    "anchored_sections", "nested_toc",
}
#: A real book whose documents hold two chapters each (anchored TOC entries).
_CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "data", "corpus", "astronomy_for_amateurs.epub")


class TestScenarioMatrix(unittest.TestCase):
    """One condition = one cache/chapter situation; all must complete correctly."""

    @classmethod
    def setUpClass(cls):
        register_fake_engine()
        cls.tmp = tempfile.mkdtemp(prefix="noesis-scenarios-")
        cls.reports = run_scenario_matrix(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_matrix_covers_every_condition(self):
        expected = set(_EXPECTED_CONDITIONS)
        if os.path.isfile(_CORPUS):
            expected |= {"anchored_single_entry", "shared_document_whole"}
        self.assertEqual(set(self.reports), expected)

    def test_selecting_one_entry_does_not_drag_its_neighbour(self):
        """Regression: the selection travelled as file names, so picking one
        chapter of a shared document also translated its neighbour."""
        if not os.path.isfile(_CORPUS):
            self.skipTest("corpus fixture missing")
        one = self.reports["anchored_single_entry"]
        whole = self.reports["shared_document_whole"]
        self.assertTrue(one.ok, one.summary())
        self.assertTrue(whole.ok, whole.summary())
        self.assertGreater(one.planned_total, 0)
        self.assertLess(one.planned_total, whole.planned_total,
                        "selecting one entry covered the whole document")

    def test_no_scenario_stalls_or_errors(self):
        for name, report in self.reports.items():
            with self.subTest(condition=name):
                self.assertFalse(report.stalled, report.summary())
                self.assertFalse(report.cancelled, report.summary())
                self.assertIsNone(report.error, report.summary())

    def test_every_planned_segment_is_processed(self):
        for name, report in self.reports.items():
            with self.subTest(condition=name):
                self.assertEqual(report.processed_total, report.planned_total,
                                 report.summary())

    def test_no_chapter_is_left_half_done(self):
        for name, report in self.reports.items():
            with self.subTest(condition=name):
                self.assertEqual(report.pending_chapters, [], report.summary())

    def test_the_output_carries_the_translation_everywhere(self):
        for name, report in self.reports.items():
            with self.subTest(condition=name):
                self.assertEqual(report.output_missing, [], report.summary())

    def test_every_toc_level_is_translated(self):
        for name, report in self.reports.items():
            with self.subTest(condition=name):
                self.assertEqual(report.toc_missing, [], report.summary())

    def test_a_first_time_chapter_before_the_cache_is_translated(self):
        """The regression: a new chapter *before* the cached ones shifts every
        index, so a positional cache match left it entirely in the source
        language (only 3 of its segments survived)."""
        report = self.reports["chapter_added_before_cache"]
        self.assertTrue(report.ok, report.summary())
        # c2 + c3 (two segments each) were reused from the cache...
        self.assertEqual(report.cached_segments, 4, report.summary())
        # ... and c1 was translated for the first time.
        self.assertGreater(report.processed_total, report.cached_segments,
                           report.summary())

    def test_a_warm_rerun_is_served_entirely_from_the_cache(self):
        report = self.reports["all_cached"]
        self.assertTrue(report.ok, report.summary())
        self.assertEqual(report.cached_segments, report.processed_total,
                         report.summary())


class TestCancellation(unittest.TestCase):
    """A cancelled run must be reported as cancelled, never as a stall."""

    def test_cancellation_is_reported_not_stalled(self):
        tmp = tempfile.mkdtemp(prefix="noesis-cancel-")
        register_fake_engine()
        src = build_rich_epub(os.path.join(tmp, "cancel.epub"))
        calls = {"n": 0}

        def should_cancel() -> bool:
            calls["n"] += 1
            return calls["n"] > 1        # cancel before doing any work

        report = run_translation_scenario(
            "cancel", src, tmpdir=tmp, timeout=60, should_cancel=should_cancel)
        self.assertFalse(report.stalled, report.summary())
        self.assertTrue(report.cancelled, report.summary())
        self.assertFalse(report.ok)      # partial work is never "ok"
        self.assertGreater(calls["n"], 0)
        # A cancelled run leaves no half-translated EPUB behind.
        self.assertFalse(os.path.isfile(os.path.join(tmp, "cancel.out.epub")),
                         "a cancelled run still wrote an output file")


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestGuiMixedCache(unittest.TestCase):
    """The user-visible invariant: with a partly warm cache the view completes.

    This is the GUI twin of the engine scenario: the progress model must reach
    100% and report the cached chapters, which is exactly what did not happen
    while a stale queue kept a chapter at 0%.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-scenario-gui"])
        register_fake_engine()
        cls.tmp = tempfile.mkdtemp(prefix="noesis-scenario-gui-")
        cls.book = build_rich_epub(os.path.join(cls.tmp, "gui.epub"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run_gui(self, **overrides):
        import main
        from noesis_ebook_translator import book as book_mod

        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)

        # A previous, partial run: only the first two chapters are in the cache.
        book_mod.translate_epub(
            self.book, os.path.join(self.tmp, "gui_seed.epub"), engine="Fake",
            source_lang="English", target_lang="Italian",
            chapters=["c1.xhtml", "c2.xhtml"],
            settings={"translation_position": "only", "cache_enabled": True})

        cfg = {"engine": "Fake", "source": "English", "target": "Italian",
               "batching": False, "cache": True, "sequential": True,
               "chapters": ["c1.xhtml", "c2.xhtml", "c3.xhtml"],
               "grouping": "grouped", "folder": self.tmp,
               "name": "gui_mixed.epub", "bilingual": False}
        cfg.update(overrides)

        window = main.MainWindow()
        try:
            window._apply_source(self.book)
            window._start_translation(cfg)
            deadline = time.time() + 60
            while ((window.worker is not None or window._split_worker is not None)
                   and time.time() < deadline):
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()
            return window, window.translate_view.model()
        except Exception:
            window.close()
            raise

    def test_mixed_cache_reaches_one_hundred_percent(self):
        from noesis_ebook_translator.progress_model import STATE_DONE

        window, model = self._run_gui()
        try:
            self.assertIsNone(window.worker)
            self.assertEqual(model.overall_percent(), 100.0)
            for unit in model.tracked():
                self.assertEqual(model.state(unit.file), STATE_DONE, unit.file)
            self.assertEqual(window.book_label.text(), "100%")
            summary = model.summary()
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["cached"], 2)
        finally:
            window.close()
            self.app.processEvents()

    def test_whole_book_after_a_single_chapter_run(self):
        """Translating c1 alone, then the whole book: nothing stays behind."""
        import main
        from noesis_ebook_translator.progress_model import STATE_DONE

        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        window, model = self._run_gui(chapters=["c1.xhtml"])
        try:
            self.assertEqual(model.state("c1.xhtml"), STATE_DONE)
            self.assertEqual(model.overall_percent(), 100.0)
        finally:
            window.close()
            self.app.processEvents()

    def test_cancelling_never_records_a_translated_book(self):
        """A cancelled run must not reach the library as a translated book."""
        import main
        from noesis_ebook_translator.i18n import T

        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        # A book used only here: the library database is shared by the whole test
        # run, so a path translated by another test must not leak into the check.
        book = build_rich_epub(os.path.join(self.tmp, "cancelled.epub"))
        window = main.MainWindow()
        try:
            window._apply_source(book)
            window._on_cancelled()
            self.assertEqual(window.status.text(), T("status.canceled"))
            recorded = [entry.get("translated_path")
                        for entry in window.reader.session.recent()
                        if entry.get("path") == book]
            self.assertEqual(recorded, [""],
                             f"a cancelled run recorded a translation: {recorded}")
        finally:
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
