"""What only *real* engines do: latency, parallel workers, failures, streaming,
batching and rate limits.

The offline ``Fake`` engine (tests/fixtures) is instant and always succeeds, so it
never exercises those paths -- and they are exactly what the user's paid engines
do. ``Realistic`` mimics them without a network: see ``fixtures.REALISTIC``.

Each test builds its own book: the engine cache is keyed on the input path, so
sharing one would leak "already translated" content between tests.
"""
import os
import tempfile
import time
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import REALISTIC, build_rich_epub, register_realistic_engine

if _HAS_GUI:
    from noesis_ebook_translator.progress_model import (
        STATE_DONE, STATE_ERROR, STATE_RUNNING)


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestRealEngineBehaviours(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-real"])
        cls.tmp = tempfile.mkdtemp(prefix="noesis-real-")
        cls.engine = register_realistic_engine()

    def setUp(self):
        # A book of its own per test: the cache is keyed on the path.
        self.book = build_rich_epub(
            os.path.join(self.tmp, f"real_{time.time_ns()}.epub"))
        REALISTIC.update({"delay": 0.0, "fail_on": None, "stream": False})
        self._saved = (self.engine.concurrency_limit,
                       self.engine.request_interval,
                       self.engine.request_attempt)

    def tearDown(self):
        REALISTIC.update({"delay": 0.0, "fail_on": None, "stream": False})
        (self.engine.concurrency_limit, self.engine.request_interval,
         self.engine.request_attempt) = self._saved
        # ``_start`` writes these as engine preferences: clear them so no other
        # test inherits this run's concurrency/throttle.
        from noesis_ebook_translator import appconfig
        appconfig.set_engine_preference("Realistic", concurrency_limit=None,
                                        request_interval=None)

    # -- harness ----------------------------------------------------------
    def _start(self, *, chapters=None, sequential=False, cache=True,
               batching=False, name="out.epub", **overrides):
        import main

        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        window._apply_source(self.book)
        cfg = {"engine": "Realistic", "source": "English", "target": "Italian",
               "batching": batching, "cache": cache, "sequential": sequential,
               "chapters": chapters or [], "grouping": "grouped",
               "folder": self.tmp, "name": name, "bilingual": False}
        cfg.update(overrides)
        window._start_translation(cfg)
        # The app appends its "<name>-<language>" suffix: read the real path back.
        return window, window._output_path

    def _wait(self, window, *, timeout=90.0, sample=False):
        """Run the event loop until the worker is done; return the running peak."""
        peak = 0
        deadline = time.time() + timeout
        while window.worker is not None and time.time() < deadline:
            self.app.processEvents()
            if sample:
                model = window.translate_view.model()
                peak = max(peak, len(model.running_units()))
            time.sleep(0.001)
        self.app.processEvents()
        return peak

    # -- the behaviours ---------------------------------------------------
    def test_parallel_workers_overlap_at_the_engine(self):
        """"Sequential" off + concurrency_limit>1: requests really overlap.

        Measured at the engine (requests in flight), not through the progress
        deltas: those are coalesced every 50 ms, so a short run may not show two
        *rows* running even when the workers did overlap.
        """
        self.engine.concurrency_limit = 4
        REALISTIC.update({"delay": 0.08, "in_flight": 0, "max_in_flight": 0})
        window, _ = self._start(sequential=False)
        try:
            self._wait(window)
            model = window.translate_view.model()
            self.assertEqual(model.overall_percent(), 100.0)
            self.assertGreaterEqual(
                REALISTIC["max_in_flight"], 2,
                "the engine never had two requests in flight")
            for unit in model.tracked():
                self.assertEqual(model.unit_state(unit), STATE_DONE)
        finally:
            window.close()

    def test_parallelism_goes_past_the_loop_default_executor(self):
        """>8 concurrent calls must really run: the executor is sized to the limit.

        ``run_in_executor(None, …)`` runs on the loop's *default* executor,
        which CPython sizes ``min(32, cpu+4)`` (= 8 here): workers above that
        just queued, so ``translate_parallel`` was a no-op past ~8.
        """
        from noesis_ebook_translator import appconfig
        from noesis_ebook_translator.lib.handler import Handler

        target = min(12, Handler.MAX_WORKERS)
        REALISTIC.update({"delay": 0.15, "in_flight": 0, "max_in_flight": 0})
        window, _ = self._start(sequential=False, concurrency=target)
        try:
            self._wait(window)
            self.assertEqual(window.translate_view.model().overall_percent(),
                             100.0)
            self.assertGreaterEqual(
                REALISTIC["max_in_flight"], 9,
                "the loop's default executor capped the concurrency at 8")
            # Parallel really means "no engine throttle": the 20 s default
            # between requests made the knob pointless.
            self.assertEqual(
                appconfig.get_engine_preference("Realistic")
                .get("request_interval"), 0)
        finally:
            window.close()

    def test_parallel_removes_the_engine_throttle(self):
        """Sequential keeps the engine default; parallel removes the throttle."""
        from noesis_ebook_translator import appconfig

        window, _ = self._start(sequential=True, name="seq.epub")
        self._wait(window)
        window.close()
        self.assertIsNone(
            appconfig.get_engine_preference("Realistic")
            .get("request_interval"))

        window, _ = self._start(sequential=False, concurrency=4,
                                name="parallel.epub")
        try:
            self._wait(window)
            preference = appconfig.get_engine_preference("Realistic")
            self.assertEqual(preference.get("request_interval"), 0)
            self.assertEqual(preference.get("concurrency_limit"), 4)
        finally:
            window.close()

    def test_batching_records_requests_not_segments(self):
        """``run_engine_calls`` feeds the estimate's latency calibration: with
        batching it must count the requests (ceil(n/20)), not the segments."""
        from tests.test_resume import _count, cache_at

        with cache_at(os.path.join(self.tmp,
                                   f"calls-{time.time_ns()}")) as cache_dir:
            window, _ = self._start(sequential=True, cache=True,
                                    batching=True, name="calls.epub")
            try:
                self._wait(window)
                self.assertEqual(
                    window.translate_view.model().overall_percent(), 100.0)
            finally:
                window.close()
            segments = _count(cache_dir,
                              "SELECT COUNT(*) FROM cache WHERE NOT ignored")
            calls = _count(cache_dir,
                           "SELECT value FROM info WHERE key='run_engine_calls'")
        self.assertGreater(segments, 10)
        self.assertGreater(calls, 0)
        self.assertLess(calls, segments, "batching must divide by the batch size")
        self.assertLessEqual(calls, (segments + 19) // 20)

    def test_a_refused_segment_is_reported_and_the_rest_finish(self):
        """A per-segment failure must paint that chapter as failed, not the run."""
        self.engine.request_attempt = 0     # fail at once (no 5 s backoff)
        REALISTIC["fail_on"] = "Body of chapter three"
        window, _ = self._start(sequential=True)
        try:
            self._wait(window)
            model = window.translate_view.model()
            self.assertIsNone(window.worker)
            self.assertGreater(model.error_count(), 0)
            self.assertEqual(model.unit_state(
                next(u for u in model.units if u.file == "c3.xhtml")),
                STATE_ERROR)
            # The other chapters still finished, and the run is not "all done".
            self.assertEqual(model.state("c1.xhtml"), STATE_DONE)
            self.assertEqual(model.state("c2.xhtml"), STATE_DONE)
            self.assertLess(model.summary()["done"], model.summary()["total"])
        finally:
            window.close()

    def test_a_generator_engine_streams_through(self):
        """The GenAI engines return a generator when streaming is on."""
        import zipfile

        REALISTIC["stream"] = True
        window, out = self._start(sequential=True, name="stream.epub")
        try:
            self._wait(window)
            model = window.translate_view.model()
            self.assertEqual(model.overall_percent(), 100.0)
            self.assertIsNone(window.worker)
            # The zip entries are compressed: read them, do not grep the bytes.
            with zipfile.ZipFile(out) as archive:
                body = "".join(archive.read(name).decode("utf-8", "replace")
                               for name in archive.namelist()
                               if name.endswith((".xhtml", ".html")))
            self.assertGreaterEqual(body.count("IT&lt;"), 12)
        finally:
            window.close()

    def test_online_batching_reports_the_cached_segments(self):
        """The batching path never calls translate_paragraph: a warm cache must
        still be reported as cached (it used to look freshly translated)."""
        name = "batch.epub"
        window, _ = self._start(sequential=True, cache=True, name=name)
        try:
            self._wait(window)
            self.assertEqual(window.translate_view.model().cached, 0)
        finally:
            window.close()

        window, _ = self._start(sequential=True, cache=True, name=name,
                                batching=True)
        try:
            self._wait(window)
            model = window.translate_view.model()
            self.assertEqual(model.overall_percent(), 100.0)
            self.assertGreater(model.cached, 0, "the cache was not recognised")
            self.assertGreater(model.summary()["cached"], 0)
        finally:
            window.close()

    def test_rate_limiting_does_not_lose_progress(self):
        """request_interval spaces the requests out: every segment is still
        accounted for exactly once."""
        self.engine.request_interval = 0.01
        window, _ = self._start(sequential=True)
        try:
            self._wait(window)
            model = window.translate_view.model()
            done, total = model.overall()
            self.assertEqual(done, total)
            self.assertGreater(done, 0)
            self.assertEqual(model.overall_percent(), 100.0)
        finally:
            window.close()

    def test_cancelling_a_slow_run_mid_flight(self):
        """With a slow engine the cancel lands mid-run: not a translation, no file."""
        from noesis_ebook_translator.i18n import T

        REALISTIC["delay"] = 0.05
        window, out = self._start(sequential=True, name="cancel.epub")
        try:
            # Let a few segments through, then stop the run mid-flight.
            deadline = time.time() + 2.0
            while time.time() < deadline and window.worker is not None:
                self.app.processEvents()
                time.sleep(0.005)
                model = window.translate_view.model()
                if model is not None and model.done:
                    break
            self.assertIsNotNone(window.worker, "the run had already finished")
            window.on_cancel()
            model = window.translate_view.model()
            self._wait(window)
            self.assertIsNone(window.worker)
            self.assertEqual(window.status.text(), T("status.canceled"))
            self.assertLess(model.overall_percent(), 100.0)
            self.assertFalse(os.path.isfile(out),
                             "a cancelled run wrote an output file")
            recorded = [entry.get("translated_path")
                        for entry in window.reader.session.recent()
                        if entry.get("path") == self.book]
            self.assertEqual(recorded, [""],
                             f"a cancelled run was recorded: {recorded}")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
