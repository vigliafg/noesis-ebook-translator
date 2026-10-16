"""The TOC fallback: books whose package document lies, or that have no NCX.

Real "slim" re-packs keep a manifest that lists files they no longer ship (the
Davidson's book in the user's corpus is one: 48 MathJax fonts declared and
missing), which makes :mod:`ebooklib` refuse to read the book. The table of
contents must still be recovered from the archive -- and when it cannot, the
reason has to be *reported*, never silently swallowed.
"""
import os
import tempfile
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001
    _HAS_GUI = False

from tests.fixtures import (
    build_broken_manifest_epub, build_nav_only_epub, build_rich_epub,
    register_fake_engine)


class TestBrokenManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="noesis-broken-")
        cls.good = build_rich_epub(os.path.join(cls.tmp, "good.epub"))
        cls.broken = build_broken_manifest_epub(
            os.path.join(cls.tmp, "broken.epub"))
        register_fake_engine()

    def test_the_fixture_really_breaks_ebooklib(self):
        from ebooklib import epub

        with self.assertRaises(Exception):  # noqa: B017 - any read failure
            epub.read_epub(self.broken)

    def test_the_toc_is_recovered_from_the_archive(self):
        from noesis_ebook_translator.chapters import flatten, load_chapters

        good = flatten(load_chapters(self.good))
        recovered = flatten(load_chapters(self.broken))
        self.assertTrue(recovered, "the fallback recovered nothing")
        self.assertEqual([c.name for c in recovered], [c.name for c in good])
        self.assertEqual([c.depth for c in recovered], [c.depth for c in good])
        self.assertEqual([c.file for c in recovered], [c.file for c in good])
        self.assertEqual([c.files for c in recovered], [c.files for c in good])

    def test_the_chapter_list_gets_its_rows(self):
        from noesis_ebook_translator.progress_model import build_units

        units = build_units(self.broken)
        self.assertEqual([u.name for u in units],
                         ["Introduction", "Part Two", "Chapter 2", "Chapter 3"])

    def test_translating_it_says_what_is_wrong(self):
        """The engine cannot read such a book: report it, do not dump a KeyError."""
        from noesis_ebook_translator import book

        with self.assertRaises(Exception) as caught:  # noqa: B017
            book.translate_epub(
                self.broken, os.path.join(self.tmp, "out.epub"), engine="Fake",
                settings={"cache_enabled": False})
        message = str(caught.exception)
        self.assertIn("EPUB", message)
        self.assertIn("malformato", message)


class TestUnreadableBook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-garbage-")

    def test_a_garbage_file_raises_a_readable_error(self):
        from noesis_ebook_translator.chapters import ChapterError, load_chapters

        path = os.path.join(self.tmp, "fake.epub")
        with open(path, "wb") as handle:
            handle.write(b"not an epub at all")
        with self.assertRaises(ChapterError) as caught:
            load_chapters(path)
        self.assertIn("indice", str(caught.exception))

    def test_a_missing_file_raises_a_readable_error(self):
        from noesis_ebook_translator.chapters import ChapterError, load_chapters

        with self.assertRaises(ChapterError):
            load_chapters(os.path.join(self.tmp, "not-there.epub"))


class TestNavOnly(unittest.TestCase):
    def test_the_epub3_navigation_document_is_read(self):
        """EPUB 3 without an NCX: the fallback reads <nav epub:type="toc">."""
        from noesis_ebook_translator.chapters import (
            _chapters_from_zip, flatten)

        tmp = tempfile.mkdtemp(prefix="noesis-nav-")
        path = build_nav_only_epub(os.path.join(tmp, "nav.epub"))
        chapters = _chapters_from_zip(path)
        flat = flatten(chapters)
        self.assertEqual([c.name for c in flat], ["Intro", "Part", "Body"])
        self.assertEqual([c.depth for c in flat], [0, 0, 1])
        self.assertEqual(flat[2].file, "c2.xhtml")


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestBandReportsAnUnreadableToc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["noesis-badtoc"])

    def test_the_band_shows_the_reason_not_the_empty_hint(self):
        import main
        from noesis_ebook_translator.i18n import T

        tmp = tempfile.mkdtemp(prefix="noesis-badtoc-")
        path = os.path.join(tmp, "fake.epub")
        with open(path, "wb") as handle:
            handle.write(b"nope")
        main.QMessageBox.information = staticmethod(lambda *a, **k: None)
        main.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        window = main.MainWindow()
        try:
            window._apply_source(path)
            track = window.translate_view.track
            self.assertIsNone(window.translate_view.model())
            self.assertEqual(track.visible_units(), [])
            self.assertFalse(track.lbl_empty.isHidden())
            self.assertNotEqual(track.lbl_empty.text(), T("track.empty"))
            self.assertIn("indice", track.lbl_empty.text())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
