"""Audit of the chapter list: the whole corpus + the TOC shapes it lacks.

The corpus is 13 real Project Gutenberg books, but none of them has section
entries, so "headings and shared documents together" gets its own fixture.
"""
import glob
import os
import tempfile
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import build_partitioned_epub

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "corpus")


def corpus_books() -> list[str]:
    return sorted(glob.glob(os.path.join(CORPUS_DIR, "*.epub")))


class TestCorpusTocAudit(unittest.TestCase):
    """One row per TOC entry, in reading order, for every real book."""

    def test_every_book_is_listed_faithfully(self):
        from noesis_ebook_translator.chapters import flatten, load_chapters
        from noesis_ebook_translator.progress_model import build_units

        books = corpus_books()
        self.assertGreaterEqual(len(books), 13, "the corpus is missing")
        for path in books:
            with self.subTest(book=os.path.basename(path)):
                toc = flatten(load_chapters(path))
                units = build_units(path)
                self.assertTrue(units, "empty chapter list")
                self.assertEqual(len(units), len(toc))
                self.assertEqual([u.name for u in units], [c.name for c in toc])
                self.assertEqual([u.depth for u in units],
                                 [c.depth for c in toc])
                self.assertEqual(
                    [u.kind for u in units],
                    ["document" if c.file else "section" for c in toc])
                self.assertEqual(len({u.key() for u in units}), len(units),
                                 "two entries share a key")

    def test_the_order_is_the_reading_order_not_the_file_names(self):
        """Sorting by file name would differ from the TOC for at least one book."""
        from noesis_ebook_translator.progress_model import build_units

        differing = 0
        for path in corpus_books():
            files = [u.file for u in build_units(path) if u.file]
            if files != sorted(files):
                differing += 1
        self.assertGreater(differing, 0,
                           "no corpus book proves the order is the TOC's")

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_the_track_renders_for_every_book(self):
        """No book shape breaks the delegate or the three filters."""
        from noesis_ebook_translator.progress_model import (
            ProgressModel, build_units)
        from noesis_ebook_translator.ui.chapter_track import ChapterTrackWidget

        app = QApplication.instance() or QApplication(["noesis-audit"])
        books = corpus_books()
        self.assertTrue(books, "the corpus is missing")
        for path in books:
            with self.subTest(book=os.path.basename(path)):
                track = ChapterTrackWidget(reduce_motion=True)
                try:
                    model = ProgressModel(build_units(path))
                    model.set_plan({u.file: 3 for u in model.units if u.file})
                    track.resize(600, 400)
                    track.set_model(model)
                    track.show()
                    app.processEvents()
                    self.assertEqual(track._list.count(), len(model.units))
                    self.assertFalse(track.grab().isNull())
                    for name in ("all", "todo", "done"):
                        track.set_filter(name)
                        app.processEvents()
                        self.assertFalse(track.grab().isNull())
                finally:
                    track.close()


class TestSectionsAndAnchors(unittest.TestCase):
    """The shape the corpus does not have: headings + shared documents."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="noesis-partitioned-")
        cls.book = build_partitioned_epub(os.path.join(cls.tmp, "part.epub"))

    def test_rows_are_distinct_and_ordered(self):
        from noesis_ebook_translator.progress_model import build_units

        units = build_units(self.book)
        self.assertEqual([u.label() for u in units],
                         ["Part One", "Part One-A", "Chapter 1", "Chapter 2",
                          "Part One-B", "Chapter 3", "Part Two", "Chapter 4"])
        self.assertEqual([u.depth for u in units], [0, 1, 2, 2, 1, 2, 0, 1])
        self.assertEqual([u.kind for u in units],
                         ["section", "section", "document", "document",
                          "section", "document", "section", "document"])
        # Four headings have no href and no document: they must not share a key.
        self.assertEqual(len({u.key() for u in units}), 8)
        # ... and the two chapters inside one document stay separate entries.
        self.assertEqual(units[2].file, units[3].file)
        self.assertNotEqual(units[2].href, units[3].href)

    def test_selecting_the_second_entry_leaves_the_first_excluded(self):
        from noesis_ebook_translator.progress_model import (
            ProgressModel, STATE_EXCLUDED, STATE_HEADER, STATE_PENDING,
            build_units)

        units = build_units(self.book)
        model = ProgressModel(units)
        model.set_selection([units[3].href])
        model.set_plan({units[2].file: 6})
        for index in (0, 1, 4, 6):
            self.assertEqual(model.unit_state(units[index]), STATE_HEADER)
        self.assertEqual(model.unit_state(units[2]), STATE_EXCLUDED)
        self.assertEqual(model.unit_state(units[3]), STATE_PENDING)
        self.assertEqual(len(model.tracked()), 1)

    @unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
    def test_nested_headings_do_not_swallow_a_sibling_subtree(self):
        """The subtree scan must walk nested headings and stop at a sibling."""
        from noesis_ebook_translator.progress_model import (
            ProgressModel, build_units)
        from noesis_ebook_translator.ui.chapter_track import ChapterTrackWidget

        app = QApplication.instance() or QApplication(["noesis-nested"])
        units = build_units(self.book)
        model = ProgressModel(units)
        # Chapter 2 (inside Part One-A) and Chapter 4 (inside Part Two) are the
        # selection; Chapter 4 is already translated.
        model.set_selection([units[3].key(), units[7].key()])
        model.set_plan({units[3].file: 2, units[7].file: 2})
        model.done[units[7].file] = 2
        track = ChapterTrackWidget(reduce_motion=True)
        try:
            track.set_model(model)
            track.set_filter("todo")
            self.assertEqual([u.label() for u in track.visible_units()],
                             ["Part One", "Part One-A", "Chapter 2"])
            track.set_filter("done")
            self.assertEqual([u.label() for u in track.visible_units()],
                             ["Part Two", "Chapter 4"])
        finally:
            track.close()
        self.assertIsNotNone(app)


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestRecapCountsDocuments(unittest.TestCase):
    def test_two_entries_of_one_document_count_once(self):
        """Band 1's recap counts *documents*, not TOC entries."""
        import main
        from noesis_ebook_translator.chapters import flatten, load_chapters

        shared = None
        for path in corpus_books():
            by_file: dict[str, list] = {}
            for chapter in flatten(load_chapters(path)):
                if chapter.file:
                    by_file.setdefault(chapter.file, []).append(chapter)
            shared = next((chapters for chapters in by_file.values()
                           if len(chapters) > 1), None)
            if shared:
                break
        if not shared:
            self.skipTest("no corpus book shares a document")
        app = QApplication.instance() or QApplication(["noesis-recap"])
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        try:
            window._input_path = path
            hrefs = [c.href for c in shared]
            self.assertGreaterEqual(len(hrefs), 2)
            self.assertEqual(window._selected_document_count(hrefs), 1)
            self.assertEqual(window._selected_document_count([]), 0)
        finally:
            window.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
