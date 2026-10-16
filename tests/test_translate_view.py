"""Tests for the four-band Translate view (progress model, throttle, widgets)."""
import os
import tempfile
import time
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import build_rich_epub, build_sample_epub


class _FakeClock:
    """Deterministic clock for the throttle (no sleeping in tests)."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeParagraph:
    def __init__(self, page, translation="x", error=None, ignored=False,
                 is_cache=False):
        self.page = page
        self.translation = translation
        self.error = error
        self.ignored = ignored
        self.is_cache = is_cache


class TestDeltaBatch(unittest.TestCase):
    def test_counts_per_page_and_skips_toc_and_ignored(self):
        from noesis_ebook_translator.progress_model import DeltaBatch

        batch = DeltaBatch()
        batch.add_paragraph(_FakeParagraph("a.xhtml"))
        batch.add_paragraph(_FakeParagraph("a.xhtml", is_cache=True))
        batch.add_paragraph(_FakeParagraph("b.xhtml"))
        batch.add_paragraph(_FakeParagraph("a.xhtml", error="boom"))
        # Not counted: the TOC pseudo-document and ignored (empty) elements.
        batch.add_paragraph(_FakeParagraph("toc.ncx"))
        batch.add_paragraph(_FakeParagraph("a.xhtml", ignored=True))

        payload = batch.payload()
        self.assertEqual(payload["counts"], {"a.xhtml": 3, "b.xhtml": 1})
        self.assertEqual(payload["errors"], {"a.xhtml": 1})
        self.assertEqual(payload["cached"], 1)
        self.assertEqual(payload["last"][0], "a.xhtml")
        self.assertEqual(batch.payload()["counts"], payload["counts"])
        batch.reset()
        self.assertIsNone(batch.payload())

    def test_log_accumulates(self):
        from noesis_ebook_translator.progress_model import DeltaBatch

        batch = DeltaBatch()
        batch.add_log("one\n")
        batch.add_log("two\n")
        self.assertEqual(batch.payload()["log"], ["one\n", "two\n"])


class TestTransferThrottle(unittest.TestCase):
    def test_rate_and_single_flight(self):
        from noesis_ebook_translator.progress_model import TransferThrottle

        clock = _FakeClock()
        throttle = TransferThrottle(interval=0.05, clock=clock)
        # First event always goes through.
        self.assertTrue(throttle.due())
        throttle.emitted()
        # Single-flight: nothing until the GUI releases it, even much later.
        clock.advance(10.0)
        self.assertFalse(throttle.due())
        throttle.release()
        # Released, and the interval has long passed.
        self.assertTrue(throttle.due())
        throttle.emitted()
        clock.advance(0.04)
        self.assertFalse(throttle.due())   # still in flight
        throttle.release()
        self.assertFalse(throttle.due())   # released but too early
        clock.advance(0.02)
        self.assertTrue(throttle.due())

    def test_twenty_thousand_segments_stay_under_the_rate(self):
        """Acceptance criterion 12: ~20 UI updates/s, not one per segment."""
        from noesis_ebook_translator.progress_model import TransferThrottle

        clock = _FakeClock()
        throttle = TransferThrottle(interval=0.05, clock=clock)
        emissions = 0
        # The GUI is instant here, so only the interval limits the emissions.
        for _ in range(20000):
            clock.advance(0.0005)  # 20k segments in 10 simulated seconds
            if throttle.due():
                throttle.emitted()
                emissions += 1
                throttle.release()
        self.assertLessEqual(emissions, 200)   # 10 s / 0.05 s
        self.assertGreaterEqual(emissions, 150)


class TestProgressModel(unittest.TestCase):
    def _model(self):
        from noesis_ebook_translator.progress_model import ChapterUnit, ProgressModel

        units = [ChapterUnit("a.xhtml", "Chapter 1"), ChapterUnit("b.xhtml", "Chapter 2")]
        return ProgressModel(units)

    def test_states_and_totals(self):
        from noesis_ebook_translator.progress_model import (
            STATE_DONE, STATE_PENDING, STATE_RUNNING, STATE_SKIPPED)

        model = self._model()
        self.assertEqual(model.state("a.xhtml"), STATE_PENDING)
        model.set_plan({"a.xhtml": 2, "b.xhtml": 1})
        self.assertEqual(model.overall(), (0, 3))
        model.apply({"counts": {"a.xhtml": 1}, "errors": {}, "cached": 0, "last": None})
        self.assertEqual(model.state("a.xhtml"), STATE_RUNNING)
        model.apply({"counts": {"a.xhtml": 1}, "errors": {}, "cached": 0,
                     "last": ("a.xhtml", "ciao")})
        self.assertEqual(model.state("a.xhtml"), STATE_DONE)
        self.assertEqual(model.last, ("a.xhtml", "ciao"))
        self.assertAlmostEqual(model.overall_percent(), 2 / 3 * 100)
        # A plan document missing from the chapter list becomes a unit itself.
        model.set_plan({"a.xhtml": 2, "b.xhtml": 1, "cover.xhtml": 4})
        self.assertIn("cover.xhtml", [u.file for u in model.units])
        # A chapter with no translatable content is tracked but skipped.
        model.set_plan({"a.xhtml": 2, "b.xhtml": 1, "empty.xhtml": 0})
        self.assertEqual(model.state("empty.xhtml"), STATE_SKIPPED)
        self.assertEqual(model.overall(), (2, 3))

    def test_selection_marks_excluded_units(self):
        """Chapters outside the selection stay visible but out of the totals."""
        from noesis_ebook_translator.progress_model import (
            STATE_DONE, STATE_EXCLUDED, STATE_PENDING)

        model = self._model()
        model.set_selection(["a.xhtml"])
        model.set_plan({"a.xhtml": 2})
        self.assertEqual(model.state("a.xhtml"), STATE_PENDING)
        self.assertEqual(model.state("b.xhtml"), STATE_EXCLUDED)
        self.assertEqual(model.overall(), (0, 2))
        model.apply({"counts": {"a.xhtml": 2}, "errors": {}, "cached": 0,
                     "last": None})
        self.assertEqual(model.state("a.xhtml"), STATE_DONE)
        self.assertEqual(model.overall_percent(), 100.0)
        model.finish(ok=True)
        self.assertEqual(model.state("b.xhtml"), STATE_EXCLUDED)
        model.mark_exported()
        self.assertTrue(model.exported)

    def test_cached_chapters_and_summary(self):
        """Chapters served entirely from the cache are reported as cached."""
        from noesis_ebook_translator.progress_model import ProgressModel

        model = ProgressModel()
        model.set_plan({"a.xhtml": 4, "b.xhtml": 2, "c.xhtml": 3})
        model.apply({"counts": {"a.xhtml": 4, "b.xhtml": 2, "c.xhtml": 1},
                     "errors": {}, "cached": 6,
                     "cached_pages": {"a.xhtml": 4, "b.xhtml": 2},
                     "last": None})
        self.assertEqual(model.cached_chapters(), 2)
        self.assertEqual(model.done_chapters(), 2)
        self.assertEqual(model.selection_size(), 3)
        self.assertEqual(model.summary(), {"done": 2, "total": 3, "cached": 2,
                                          "segments": 6})
        # Not finished yet: it is not "done", so it is not "cached" either.
        self.assertEqual(model.state("c.xhtml"), "running")
        model.apply({"counts": {"c.xhtml": 2}, "errors": {}, "cached": 0,
                     "cached_pages": {}, "last": None})
        self.assertEqual(model.summary(),
                         {"done": 3, "total": 3, "cached": 2, "segments": 6})

    def test_error_state_and_finish(self):
        from noesis_ebook_translator.progress_model import (
            STATE_DONE, STATE_ERROR, STATE_PENDING, STATE_RUNNING)

        model = self._model()
        model.set_plan({"a.xhtml": 2, "b.xhtml": 2})
        model.apply({"counts": {"a.xhtml": 2, "b.xhtml": 1},
                     "errors": {"b.xhtml": 1}, "cached": 0, "last": None})
        self.assertEqual(model.state("a.xhtml"), STATE_DONE)
        self.assertEqual(model.state("b.xhtml"), STATE_ERROR)
        self.assertEqual(model.error_count(), 1)
        self.assertTrue(model.apply({"counts": {"b.xhtml": 1}, "errors": {},
                                     "cached": 0, "last": None}))
        self.assertFalse(model.apply(None))

        # A failed run must not pretend the interrupted work completed.
        model2 = self._model()
        model2.set_plan({"a.xhtml": 2, "b.xhtml": 2})
        model2.apply({"counts": {"a.xhtml": 1}, "errors": {}, "cached": 0, "last": None})
        model2.finish(ok=False)
        self.assertEqual(model2.state("a.xhtml"), STATE_RUNNING)
        self.assertEqual(model2.overall(), (1, 4))
        # A closing (successful) finish completes the units that were started.
        model2.finish(ok=True)
        self.assertEqual(model2.state("a.xhtml"), STATE_DONE)
        self.assertEqual(model2.state("b.xhtml"), STATE_PENDING)
        self.assertEqual(model2.overall(), (2, 4))


class TestBuildUnits(unittest.TestCase):
    #: A real Project Gutenberg book: two chapters share an XHTML document
    #: (CHAPTER IV/V and IX/X are anchors inside one file).
    CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "corpus", "astronomy_for_amateurs.epub")

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="noesis-units-")
        cls.book = build_sample_epub(os.path.join(cls.tmp, "sample.epub"))
        cls.rich = build_rich_epub(os.path.join(cls.tmp, "rich.epub"))

    def test_units_follow_engine_order(self):
        from noesis_ebook_translator.progress_model import build_units

        units = build_units(self.book)
        files = [u.file for u in units]
        self.assertEqual(files, ["chap_01.xhtml", "chap_02.xhtml"])
        self.assertEqual(units[0].name, "Chapter 1")

    def test_selection_filters_units(self):
        from noesis_ebook_translator.progress_model import build_units

        units = build_units(self.book, ["chap_02.xhtml"])
        self.assertEqual([u.file for u in units], ["chap_02.xhtml"])

    def test_headings_without_a_document_stay_in_the_tree(self):
        """A "Part Two" with no document of its own is a row, not dropped, and
        the sub-chapters keep their depth."""
        from noesis_ebook_translator.progress_model import build_units

        units = build_units(self.rich)
        self.assertEqual([u.name for u in units],
                         ["Introduction", "Part Two", "Chapter 2", "Chapter 3"])
        self.assertEqual([u.depth for u in units], [0, 0, 1, 1])
        self.assertEqual([u.kind for u in units],
                         ["document", "section", "document", "document"])
        self.assertIsNone(units[1].file)

    @unittest.skipUnless(os.path.isfile(CORPUS), "corpus fixture missing")
    def test_every_toc_entry_is_a_row_in_reading_order(self):
        """Regression: the list collapsed entries by file and sorted them by file
        name, so chapters vanished and the order was unreadable."""
        from noesis_ebook_translator.chapters import flatten, load_chapters
        from noesis_ebook_translator.progress_model import build_units

        toc = flatten(load_chapters(self.CORPUS))
        units = build_units(self.CORPUS)
        # One row per TOC entry, in the TOC (reading) order, depth preserved.
        self.assertEqual(len(units), len(toc))
        self.assertEqual([u.name for u in units], [c.name for c in toc])
        self.assertEqual([u.depth for u in units], [c.depth for c in toc])
        # The chapters that share a document with a neighbour are still there.
        names = [u.name for u in units]
        for expected in ("CONTENTS", "INTRODUCTION", "CHAPTER I", "CHAPTER IV",
                         "CHAPTER V", "CHAPTER IX", "CHAPTER X"):
            self.assertIn(expected, names)
        # ... and the hierarchy is deeper than one level.
        self.assertIn(1, [u.depth for u in units])
        # No entry is swallowed: the identities are unique.
        self.assertEqual(len({u.key() for u in units}), len(units))

    @unittest.skipUnless(os.path.isfile(CORPUS), "corpus fixture missing")
    def test_two_chapters_in_one_document_are_two_rows(self):
        """Regression: they used to collapse into one row labelled with the
        first entry that pointed at the document."""
        from noesis_ebook_translator.progress_model import build_units

        units = build_units(self.CORPUS)
        by_name = {u.name: u for u in units}
        four, five = by_name["CHAPTER IV"], by_name["CHAPTER V"]
        self.assertEqual(four.file, five.file)
        self.assertNotEqual(four.href, five.href)
        # Both rows carry their own label -- not the document's first entry.
        self.assertEqual(four.label(), "CHAPTER IV")
        self.assertEqual(five.label(), "CHAPTER V")

    def test_the_reading_order_is_kept(self):
        """``set_plan`` must not reorder the list: the TOC order is *the* order.

        Regression: the plan used to be sorted by file name, which scrambled the
        chapters into an order the reader could not recognise.
        """
        from noesis_ebook_translator.progress_model import ChapterUnit, ProgressModel

        model = ProgressModel([ChapterUnit("c10.xhtml"), ChapterUnit("c2.xhtml")])
        model.set_plan({"c10.xhtml": 1, "c2.xhtml": 1})
        self.assertEqual([u.file for u in model.units], ["c10.xhtml", "c2.xhtml"])
        # Documents the TOC does not mention are appended at the end, not sorted
        # into the middle of the tree.
        model.set_plan({"c10.xhtml": 1, "c2.xhtml": 1, "cover.xhtml": 4})
        self.assertEqual([u.file for u in model.units],
                         ["c10.xhtml", "c2.xhtml", "cover.xhtml"])


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestTranslateViewWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-view"])

    def _model(self, files):
        from noesis_ebook_translator.progress_model import ChapterUnit, ProgressModel

        return ProgressModel([ChapterUnit(f, f"Ch {i}") for i, f in enumerate(files)])

    def test_always_the_list_and_liquid_level(self):
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            view.set_model(self._model(["a.xhtml", "b.xhtml", "c.xhtml"]))
            self.assertEqual(view.track._list.count(), 3)

            view.model().set_plan({"a.xhtml": 4, "b.xhtml": 4, "c.xhtml": 4})
            view.model().apply({"counts": {"a.xhtml": 4, "b.xhtml": 4},
                                "errors": {}, "cached": 0, "last": None})
            view.refresh()
            self.assertAlmostEqual(view.glass.level_value(), 8 / 12 * 100)
            self.assertEqual(view.book_label.text(), "0%")  # set by _on_progress

            # There is no single-chapter "card" any more: the list is the only
            # presentation, so even a one-chapter book keeps its hierarchy.
            view.set_model(self._model(["only.xhtml"]))
            self.assertEqual(view.track._list.count(), 1)
        finally:
            view.close()

    def test_liquid_glides_and_reaches_the_target(self):
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=False)
        try:
            view.resize(900, 600)
            view.set_model(self._model(["a.xhtml", "b.xhtml", "c.xhtml"]))
            view.show()
            self.app.processEvents()
            view.glass.set_level(80.0)
            samples = []
            deadline = time.time() + 1.5
            while time.time() < deadline:
                self.app.processEvents()
                samples.append(view.glass.level_value())
                if abs(samples[-1] - 80.0) < 0.2 and len(samples) > 5:
                    break
                time.sleep(0.03)
            self.assertAlmostEqual(view.glass.level_value(), 80.0, delta=0.5)
            # It really glided: some sample sits strictly between start and end.
            self.assertTrue(any(1.0 < s < 78.0 for s in samples), samples[:8])
        finally:
            view.hide()
            view.close()

    def test_pulse_runs_while_a_chapter_is_translating(self):
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=False)
        try:
            view.resize(900, 600)
            view.set_model(self._model(["a.xhtml", "b.xhtml", "c.xhtml"]))
            model = view.model()
            model.set_plan({"a.xhtml": 4, "b.xhtml": 4, "c.xhtml": 4})
            model.apply({"counts": {"a.xhtml": 4, "b.xhtml": 2}, "errors": {},
                         "cached": 0, "last": None})
            view.refresh()
            view.show()
            self.app.processEvents()
            self.assertTrue(view.track.is_animating())
            first = view.track.pulse_alpha()
            seen = {first}
            deadline = time.time() + 1.5
            while time.time() < deadline and len(seen) < 2:
                self.app.processEvents()
                seen.add(view.track.pulse_alpha())
                time.sleep(0.03)
            self.assertEqual(len(seen), 2, "the running chapter must blink")
            # ... and it stops once nothing is running any more.
            model.apply({"counts": {"b.xhtml": 2, "c.xhtml": 4}, "errors": {},
                         "cached": 0, "last": None})
            view.refresh()
            self.assertEqual(model.running_units(), [])
            self.assertFalse(view.track.is_animating())
        finally:
            view.hide()
            view.close()

    def test_a_partly_visible_row_keeps_its_bar(self):
        """Regression: the bar was painted on the row's last two pixels, so the
        last (clipped) row of the viewport showed only its text."""
        from noesis_ebook_translator.ui.chapter_track import (
            BAR_HEIGHT, BAR_TOP, ROW_HEIGHT)
        from noesis_ebook_translator.ui.translate_view import TranslateView

        # The bar must live inside the row: painting on the last two pixels is
        # exactly what made a clipped row lose it.
        self.assertLess(BAR_TOP + BAR_HEIGHT, ROW_HEIGHT - 2,
                        "the bar would sit on the row's last pixels")

        view = TranslateView(reduce_motion=True)
        try:
            files = [f"c{i}.xhtml" for i in range(1, 8)]
            view.set_model(self._model(files))
            model = view.model()
            model.set_plan({f: 4 for f in files})
            model.apply({"counts": {f: 4 for f in files}, "errors": {},
                         "cached": 0, "last": None})
            view.resize(700, 300)
            view.set_theme("light", False)
            view.show()
            lst = view.track._list
            # Leave the fifth row visible for 30 px only: enough for the text and
            # for a bar drawn inside the row, not for one drawn at the bottom
            # (+2 is the list frame).
            lst.setFixedHeight(4 * ROW_HEIGHT + 30 + 2)
            view.refresh()
            self.app.processEvents()
            vp = lst.viewport()
            rect = lst.visualItemRect(lst.item(4))
            self.assertGreaterEqual(rect.bottom(), vp.height(), "row not clipped")
            self.assertLess(vp.height() - rect.top(), ROW_HEIGHT)
            image = vp.grab().toImage()
            done_fill = view.track.colors()["done"].name()
            y = rect.top() + 25
            self.assertLess(y, vp.height())
            self.assertEqual(image.pixelColor(rect.left() + 40, y).name(),
                             done_fill,
                             "a partly visible row lost its progress bar")
        finally:
            view.hide()
            view.close()

    def test_done_rows_are_bold(self):
        """A translated chapter's name is drawn bold.

        Only the *font* changes for a done row (the colour is the same as a
        pending one), so any difference in the name band means the bold took
        effect -- and the check is independent of the active theme.
        """
        from noesis_ebook_translator.ui.chapter_track import NAME_HEIGHT
        from noesis_ebook_translator.ui.translate_view import TranslateView

        def name_band(view):
            image = view.track._list.viewport().grab().toImage()
            rect = view.track._list.visualItemRect(view.track._list.item(0))
            return image.copy(rect.left() + 24, rect.top(), 60, NAME_HEIGHT)

        view = TranslateView(reduce_motion=True)
        try:
            view.set_model(self._model(["a.xhtml", "b.xhtml"]))
            model = view.model()
            model.set_plan({"a.xhtml": 2, "b.xhtml": 2})
            view.resize(700, 300)
            view.show()
            self.app.processEvents()
            before = name_band(view)
            model.apply({"counts": {"a.xhtml": 2}, "errors": {}, "cached": 0,
                         "last": None})
            view.refresh()
            self.app.processEvents()
            self.assertNotEqual(name_band(view), before,
                                "the translated row is not drawn bold")
        finally:
            view.hide()
            view.close()

    def test_reduce_motion_keeps_everything_still(self):
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            view.resize(900, 600)
            view.set_model(self._model(["a.xhtml", "b.xhtml", "c.xhtml"]))
            model = view.model()
            model.set_plan({"a.xhtml": 4, "b.xhtml": 4, "c.xhtml": 4})
            model.apply({"counts": {"a.xhtml": 4, "b.xhtml": 2}, "errors": {},
                         "cached": 0, "last": None})
            view.refresh()
            view.show()
            self.app.processEvents()
            # No blink, no shimmer, liquid jumps straight to the value.
            self.assertFalse(view.track.is_animating())
            self.assertEqual(view.track.pulse_alpha(), 255)
            self.assertFalse(view.track.bar_current.is_animating())
            view.glass.set_level(80.0)
            self.assertEqual(view.glass.level_value(), 80.0)
        finally:
            view.hide()
            view.close()

    def test_filters_switch_the_visible_rows(self):
        """Mini-toolbar in band 2: all / to translate / translated."""
        from noesis_ebook_translator.progress_model import ProgressModel
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            view.set_model(self._model(["a.xhtml", "b.xhtml", "c.xhtml",
                                        "d.xhtml"]))
            model = view.model()
            model.set_plan({"a.xhtml": 2, "b.xhtml": 2, "c.xhtml": 2,
                            "d.xhtml": 2})
            model.apply({"counts": {"a.xhtml": 2, "b.xhtml": 1},
                         "errors": {}, "cached": 0, "last": None})
            view.refresh()
            track = view.track

            self.assertEqual(track.filter_name(), "all")
            self.assertEqual([u.file for u in track.visible_units()],
                             ["a.xhtml", "b.xhtml", "c.xhtml", "d.xhtml"])
            # Buttons: three, exclusive, the first one checked.
            self.assertEqual(len(track._filter_buttons), 3)
            self.assertTrue(track._filter_buttons["all"].isChecked())

            track.set_filter("todo")
            self.assertEqual([u.file for u in track.visible_units()],
                             ["b.xhtml", "c.xhtml", "d.xhtml"])
            self.assertTrue(track._filter_buttons["todo"].isChecked())
            self.assertFalse(track._filter_buttons["all"].isChecked())
            # The list holds exactly the filtered rows (so the hint is hidden).
            self.assertEqual(track._list.count(), 3)
            self.assertTrue(track.lbl_empty.isHidden())

            track.set_filter("done")
            self.assertEqual([u.file for u in track.visible_units()],
                             ["a.xhtml"])
            self.assertEqual(track._list.count(), 1)

            # An empty filter shows the hint instead of an empty list.
            model.plan = {}
            model.done.clear()
            view.refresh()
            track.set_filter("done")
            self.assertEqual(track.visible_units(), [])
            self.assertFalse(track.lbl_empty.isHidden())
            track.set_filter("all")
            self.assertTrue(track.lbl_empty.isHidden())
        finally:
            view.close()

    def test_log_collapse_and_state_round_trip(self):
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            self.assertTrue(view.log_visible())
            view.set_log_visible(False)
            self.assertFalse(view.log.isVisible() or view.log_visible())
            state = view.state()
            self.assertFalse(state["log_visible"])
            self.assertEqual(len(state["sizes"]), 4)
            view.restore_state({"sizes": [1, 2, 3, 4], "log_visible": True})
            self.assertTrue(view.log_visible())
        finally:
            view.close()

    def test_narrow_window_stacks_the_bands(self):
        from PyQt6.QtCore import Qt
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            view.resize(1400, 700)
            view.resizeEvent(None)
            self.assertEqual(view.splitter.orientation(),
                             Qt.Orientation.Horizontal)
            view.resize(800, 700)
            view.resizeEvent(None)
            self.assertEqual(view.splitter.orientation(), Qt.Orientation.Vertical)
        finally:
            view.close()

    def test_view_state_persists_across_windows(self):
        """Criterion 5: log visibility and band sizes survive a restart."""
        import main

        window = main.MainWindow()
        try:
            window.translate_view.set_log_visible(False)
            window.translate_view.splitter.setSizes([10, 20, 30, 1])
            window._save_view_state()
        finally:
            window.close()
        window = main.MainWindow()
        try:
            self.assertFalse(window.translate_view.log_visible())
            self.assertEqual(window.translate_view.state()["log_visible"], False)
        finally:
            window.close()
        # Leave the shared test config in the default state for other tests.
        window = main.MainWindow()
        try:
            window.translate_view.set_log_visible(True)
            window._save_view_state()
        finally:
            window.close()

    def test_painting_the_rows_works_for_every_state(self):
        """Smoke the delegate: every state (and the export badge) must paint."""
        from noesis_ebook_translator.progress_model import ProgressModel
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            view.set_model(self._model(["a.xhtml", "b.xhtml", "c.xhtml", "d.xhtml"]))
            model = view.model()
            model.set_plan({"a.xhtml": 2, "b.xhtml": 2, "c.xhtml": 2,
                            "d.xhtml": 2})
            model.apply({"counts": {"a.xhtml": 2, "b.xhtml": 1, "c.xhtml": 1},
                         "errors": {"c.xhtml": 1}, "cached": 3,
                         "last": ("b.xhtml", "testo")})
            view.glass.set_level(50, animate=False)
            view.refresh()
            view.resize(1200, 700)
            view.show()
            self.app.processEvents()
            pixmap = view.grab()          # forces the delegate to paint
            self.assertFalse(pixmap.isNull())
            self.assertEqual(view.track._list.count(), 4)
            # The export badge paints too.
            model.mark_exported()
            view.refresh()
            self.app.processEvents()
            self.assertFalse(view.grab().isNull())
        finally:
            view.hide()
            view.close()

    def test_chapter_row_bars_reflect_the_state(self):
        """Every chapter shows its own bar: done = full, running = partial."""
        from noesis_ebook_translator.progress_model import ProgressModel
        from noesis_ebook_translator.ui.chapter_track import BAR_TOP
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            view.set_model(self._model(["a.xhtml", "b.xhtml", "c.xhtml"]))
            model = view.model()
            model.set_plan({"a.xhtml": 4, "b.xhtml": 4, "c.xhtml": 4})
            model.apply({"counts": {"a.xhtml": 4, "b.xhtml": 2},
                         "errors": {}, "cached": 0, "last": None})
            view.resize(800, 400)
            view.set_theme("light", False)
            view.refresh()
            view.show()
            self.app.processEvents()
            image = view.track._list.viewport().grab().toImage()
            done_fill = view.track.colors()["done"].name()
            accent = view.track.colors()["accent"].name()
            # The bar lives *inside* the row (never on its last two pixels, where
            # a partly-scrolled row would lose it).
            rect_a = view.track._list.visualItemRect(view.track._list.item(0))
            rect_b = view.track._list.visualItemRect(view.track._list.item(1))
            y_a = rect_a.top() + BAR_TOP + 2
            y_b = rect_b.top() + BAR_TOP + 2
            x = rect_a.left() + 60
            # Row a is done -> the whole bar is painted in the "done" colour...
            self.assertEqual(image.pixelColor(x, y_a).name(), done_fill)
            # ... while row b is half done -> the fill is the accent colour and
            # the right half is still the (empty) track.
            self.assertEqual(image.pixelColor(rect_b.left() + 20, y_b).name(),
                             accent)
            self.assertNotEqual(
                image.pixelColor(rect_b.right() - 20, y_b).name(), accent)
            # The third row has no progress: the track only, never the fill.
            rect_c = view.track._list.visualItemRect(view.track._list.item(2))
            self.assertNotEqual(
                image.pixelColor(rect_c.left() + 20,
                                 rect_c.top() + BAR_TOP + 2).name(), accent)
        finally:
            view.hide()
            view.close()

    def test_title_switches_to_selection(self):
        from noesis_ebook_translator.i18n import T
        from noesis_ebook_translator.ui.translate_view import TranslateView

        view = TranslateView(reduce_motion=True)
        try:
            view.set_model(self._model(["a.xhtml"]), selection=True)
            self.assertEqual(view.lbl_glass_title.text(), T("translate.selection"))
            view.set_model(self._model(["a.xhtml"]), selection=False)
            self.assertEqual(view.lbl_glass_title.text(), T("label.book"))
        finally:
            view.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestChapterTrackContract(unittest.TestCase):
    """The agreed behaviour of band 2: state A (open), B (running), C (done)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-track"])
        cls.tmp = tempfile.mkdtemp(prefix="noesis-track-")
        cls.book = build_rich_epub(os.path.join(cls.tmp, "rich.epub"))
        from tests.fixtures import register_fake_engine
        register_fake_engine()

    def _open(self):
        import main
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        window._apply_source(self.book)
        return window

    def test_state_a_opening_the_book_already_fills_the_trail(self):
        """No translation started: the whole TOC, neutral, no numbers."""
        from noesis_ebook_translator.progress_model import (
            STATE_HEADER, STATE_PENDING, build_units)

        window = self._open()
        try:
            model = window.translate_view.model()
            self.assertIsNotNone(model)
            self.assertEqual([u.name for u in model.units],
                             [u.name for u in build_units(self.book)])
            self.assertEqual([u.name for u in model.units],
                             ["Introduction", "Part Two", "Chapter 2",
                              "Chapter 3"])
            # Every document is neutral and nothing is tracked: no bars, no totals.
            self.assertEqual(
                {model.unit_state(u) for u in model.units if u.kind == "document"},
                {STATE_PENDING})
            section = next(u for u in model.units if u.kind == "section")
            self.assertEqual(model.unit_state(section), STATE_HEADER)
            self.assertEqual(model.tracked(), [])
            self.assertEqual(window.translate_view.track._list.count(), 4)
        finally:
            window.close()

    def test_state_b_selected_normal_excluded_grey(self):
        """After the wizard: chosen rows normal, the others grey; filters."""
        from noesis_ebook_translator.progress_model import (
            STATE_EXCLUDED, STATE_HEADER, STATE_RUNNING)

        window = self._open()
        try:
            track = window.translate_view.track
            model = window.translate_view.model()
            model.set_selection(["c2.xhtml"])
            model.set_plan({"c1.xhtml": 2, "c2.xhtml": 2, "c3.xhtml": 2})
            model.apply({"counts": {"c2.xhtml": 1}, "errors": {}, "cached": 0,
                         "last": None})
            window.translate_view.refresh()
            states = {u.label(): model.unit_state(u) for u in model.units}
            self.assertEqual(states["Chapter 2"], STATE_RUNNING)
            self.assertEqual(states["Introduction"], STATE_EXCLUDED)
            self.assertEqual(states["Chapter 3"], STATE_EXCLUDED)
            self.assertEqual(states["Part Two"], STATE_HEADER)
            # "All" shows everything; "to translate" hides the grey rows but keeps
            # the heading of what is still visible; "translated" is empty.
            self.assertEqual(len(track.visible_units()), 4)
            track.set_filter("todo")
            self.assertEqual([u.label() for u in track.visible_units()],
                             ["Part Two", "Chapter 2"])
            track.set_filter("done")
            self.assertEqual(track.visible_units(), [])
        finally:
            window.close()

    def test_state_c_translated_rows_stay_in_the_hierarchy(self):
        """At the end the translated rows keep their place, bold + check."""
        from noesis_ebook_translator.progress_model import (
            STATE_DONE, STATE_EXCLUDED)

        window = self._open()
        try:
            window._start_translation({
                "engine": "Fake", "source": "English", "target": "Italian",
                "batching": False, "cache": True, "sequential": True,
                "chapters": ["c2.xhtml"], "grouping": "grouped",
                "folder": self.tmp, "name": "contract.epub", "bilingual": False})
            deadline = time.time() + 60
            while window.worker is not None and time.time() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()
            track = window.translate_view.track
            model = window.translate_view.model()
            self.assertIsNone(window.worker)
            self.assertEqual(model.state("c2.xhtml"), STATE_DONE)
            self.assertEqual(model.state("c1.xhtml"), STATE_EXCLUDED)
            self.assertEqual([u.label() for u in track.visible_units()],
                             ["Introduction", "Part Two", "Chapter 2",
                              "Chapter 3"])
            track.set_filter("done")
            self.assertEqual([u.label() for u in track.visible_units()],
                             ["Part Two", "Chapter 2"])
        finally:
            window.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestWizardChapterSelection(unittest.TestCase):
    """The real flow: pick a chapter in the wizard, translate only that one."""

    CORPUS = TestBuildUnits.CORPUS

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-wiz"])
        cls.tmp = tempfile.mkdtemp(prefix="noesis-wiz-")
        from tests.fixtures import register_fake_engine
        register_fake_engine()

    @unittest.skipUnless(os.path.isfile(CORPUS), "corpus fixture missing")
    def test_wizard_selection_of_one_entry_of_a_shared_document(self):
        """Regression: the wizard keyed its list on the *file*, so two chapters in
        one document were indistinguishable and picking one translated both."""
        from PyQt6.QtCore import Qt

        import main
        from noesis_ebook_translator.progress_model import (
            STATE_DONE, STATE_EXCLUDED)
        from noesis_ebook_translator.ui import TranslateWizard

        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)

        wizard = TranslateWizard(None, mode="chapters", input_path=self.CORPUS)
        try:
            labels = [wizard.chapter_list.item(i).text()
                      for i in range(wizard.chapter_list.count())]
            self.assertEqual(len(labels), 31)          # every TOC entry
            self.assertIn("CHAPTER IV", [t.strip() for t in labels])
            self.assertIn("CHAPTER V", [t.strip() for t in labels])
            target = next(i for i, t in enumerate(labels)
                          if t.strip().startswith("CHAPTER V"))
            for i in range(wizard.chapter_list.count()):
                wizard.chapter_list.item(i).setCheckState(
                    Qt.CheckState.Checked if i == target
                    else Qt.CheckState.Unchecked)
            selected = wizard.selected_chapters()
            self.assertEqual(len(selected), 1)
            self.assertIn("#", selected[0])            # an anchor, not a bare file
            cfg = wizard.config()
            cfg["folder"] = self.tmp
        finally:
            wizard.close()

        window = main.MainWindow()
        try:
            window._input_path = self.CORPUS
            window._output_path = os.path.join(self.tmp, "wizard_out.epub")
            window._start_translation(cfg)
            deadline = time.time() + 60
            while window.worker is not None and time.time() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()
            model = window.translate_view.model()
            self.assertEqual(len(model.units), 31)
            self.assertEqual(len(model.tracked()), 1)   # one document tracked
            self.assertEqual(model.overall_percent(), 100.0)
            states = {u.label(): model.unit_state(u) for u in model.units}
            self.assertEqual(states["CHAPTER V"], STATE_DONE)
            self.assertEqual(states["CHAPTER IV"], STATE_EXCLUDED)
        finally:
            window.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestTranslationThroughTheGui(unittest.TestCase):
    """End-to-end: the GUI bands reflect a real (offline) translation run."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-bands"])
        cls.tmp = tempfile.mkdtemp(prefix="noesis-bands-")
        cls.book = build_rich_epub(os.path.join(cls.tmp, "rich.epub"))
        from tests.fixtures import register_fake_engine
        register_fake_engine()

    def _run(self, cfg):
        import main

        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        try:
            window._apply_source(self.book)
            window._start_translation(cfg)
            deadline = time.time() + 60
            while ((window.worker is not None
                    or window._split_worker is not None)
                   and time.time() < deadline):
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()
            return window, window.translate_view.model()
        except Exception:
            window.close()
            raise

    def _cfg(self, name, **overrides):
        cfg = {"engine": "Fake", "source": "English", "target": "Italian",
               "batching": False, "cache": True, "sequential": True,
               "chapters": [], "grouping": "grouped", "folder": self.tmp,
               "name": name, "bilingual": False}
        cfg.update(overrides)
        return cfg

    def test_whole_book_finishes_and_reports_100(self):
        from noesis_ebook_translator.i18n import T
        from noesis_ebook_translator.progress_model import STATE_DONE

        window, model = self._run(self._cfg("whole.epub"))
        try:
            self.assertIsNone(window.worker)
            self.assertGreaterEqual(len(model.units), 3)
            self.assertTrue(all(model.state(u.file) == STATE_DONE
                                for u in model.tracked()))
            self.assertEqual(model.overall_percent(), 100.0)
            self.assertEqual(window.book_label.text(), "100%")
            self.assertEqual(window.translate_view.glass.level_value(), 100.0)
            # The log arrives in batches, so it is far shorter than 5 lines/segment.
            self.assertGreater(window.log.blockCount(), 0)
            self.assertLess(window.log.blockCount(), 200)
            # Band 1 recaps the wizard choices (never the API key).
            labels = [row[0] for row in window.translate_view.choices.rows()]
            self.assertIn(T("label.input"), labels)
            self.assertIn(T("label.output"), labels)
        finally:
            window.close()

    def test_single_chapter_selection_lists_the_whole_toc(self):
        """A selection lists the whole TOC: chosen rows translate, the rest stay
        dimmed (excluded) for context, headings included."""
        from noesis_ebook_translator.i18n import T
        from noesis_ebook_translator.progress_model import (
            STATE_DONE, STATE_EXCLUDED, STATE_HEADER)

        window, model = self._run(self._cfg("one.epub", chapters=["c2.xhtml"]))
        try:
            # A chapter selection keeps the whole list (filters + context): the
            # three documents *and* the "Part Two" heading, in reading order.
            self.assertEqual([u.file for u in model.units],
                             ["c1.xhtml", None, "c2.xhtml", "c3.xhtml"])
            self.assertEqual(model.units[1].kind, "section")
            self.assertEqual(model.unit_state(model.units[1]), STATE_HEADER)
            self.assertEqual(model.state("c2.xhtml"), STATE_DONE)
            self.assertEqual(model.state("c1.xhtml"), STATE_EXCLUDED)
            self.assertEqual(model.state("c3.xhtml"), STATE_EXCLUDED)
            self.assertEqual(model.overall_percent(), 100.0)
            self.assertEqual(window.translate_view.lbl_glass_title.text(),
                             T("translate.selection"))
            # ... and the filter isolates it.
            window.translate_view.track.set_filter("todo")
            self.assertEqual(window.translate_view.track.visible_units(), [])
            window.translate_view.track.set_filter("done")
            labels = [u.label() for u in
                      window.translate_view.track.visible_units()]
            self.assertIn("Chapter 2", labels)
            self.assertIn("Part Two", labels)      # its heading stays visible
            self.assertNotIn("Chapter 3", labels)
        finally:
            window.close()

    def test_grouping_single_splits_in_background_and_marks_exported(self):
        """Criterion 11: one EPUB per chapter, exported off the UI thread."""
        from noesis_ebook_translator.progress_model import STATE_DONE

        folder = tempfile.mkdtemp(prefix="noesis-split-")
        window, model = self._run(self._cfg(
            "split.epub", chapters=["c1.xhtml", "c2.xhtml", "c3.xhtml"],
            grouping="single", folder=folder))
        try:
            self.assertIsNone(window.worker)
            self.assertIsNone(window._split_worker)
            self.assertTrue(model.exported)
            self.assertEqual(model.state("c1.xhtml"), STATE_DONE)
            produced = [f for f in os.listdir(folder) if f.endswith(".epub")]
            self.assertGreaterEqual(len(produced), 3)
        finally:
            window.close()


class TestSequentialPreference(unittest.TestCase):
    def test_engine_preference_sets_and_removes_concurrency_limit(self):
        from noesis_ebook_translator import appconfig

        appconfig.ensure_defaults()
        appconfig.set_engine_preference("Fake", concurrency_limit=1)
        self.assertEqual(
            appconfig.get_engine_preference("Fake").get("concurrency_limit"), 1)
        # None *removes* the key: 0 would mean "as many workers as segments".
        appconfig.set_engine_preference("Fake", concurrency_limit=None)
        self.assertNotIn("concurrency_limit",
                         appconfig.get_engine_preference("Fake"))
        # Keys outside the allow-list are ignored.
        appconfig.set_engine_preference("Fake", unrelated="x")
        self.assertNotIn("unrelated", appconfig.get_engine_preference("Fake"))


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestWizardSequentialOption(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-seq"])

    def test_config_exposes_sequential(self):
        from noesis_ebook_translator import appconfig
        from noesis_ebook_translator.ui import TranslateWizard

        appconfig.ensure_defaults()
        tmp = tempfile.mkdtemp(prefix="noesis-seq-")
        book = build_sample_epub(os.path.join(tmp, "sample.epub"))
        wizard = TranslateWizard(None, mode="book", input_path=book)
        try:
            cfg = wizard.config()
            self.assertIn("sequential", cfg)
            self.assertIsInstance(cfg["sequential"], bool)
            wizard.chk_sequential.setChecked(False)
            self.assertFalse(wizard.config()["sequential"])
        finally:
            wizard.close()
