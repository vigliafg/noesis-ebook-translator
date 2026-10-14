"""End-to-end tests over the real Darwin corpus (offline fake engine).

These exercise the full pipeline on three genuine Project Gutenberg EPUBs
(see ``tests/data/darwin/SOURCE.md``): parsing, element extraction, reserving
inline anchors, translation and EPUB re-writing. They run offline with the fake
engine — no network, no API keys.

Set ``NOESIS_ONLINE_TESTS=1`` to additionally run a real Google-translate smoke
test on the smallest book (needs network).
"""
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from ebooklib import epub

from tests.fixtures import register_fake_engine

CORPUS = Path(__file__).resolve().parent / "data" / "darwin"
BOOKS = {
    "origin_of_species.epub": 1228,
    "voyage_of_the_beagle.epub": 944,
    "descent_of_man.epub": 2300,
}


def _documents(path):
    book = epub.read_epub(str(path))
    return [item for item in book.get_items() if item.get_type() == 9]


def _xhtml_text(path):
    chunks = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith((".xhtml", ".html", ".htm")):
                chunks.append(archive.read(name).decode("utf-8", "replace"))
    return "\n".join(chunks)


@unittest.skipUnless(CORPUS.is_dir(), "Darwin corpus not present")
class TestDarwinCorpus(unittest.TestCase):
    outputs: dict = {}

    @classmethod
    def setUpClass(cls):
        from noesis_ebook_translator import book

        register_fake_engine()
        cls.tmp = tempfile.mkdtemp(prefix="noesis-darwin-")
        # Translate each book once; both tests share the results.
        for name in BOOKS:
            src = CORPUS / name
            cls.outputs[name] = book.translate_epub(
                str(src), os.path.join(cls.tmp, name), engine="Fake",
                source_lang="English", target_lang="Italian",
                settings={"translation_position": "only", "cache_enabled": False})

    def test_each_book_translates_and_stays_valid(self):
        for name in BOOKS:
            with self.subTest(book=name):
                self.assertTrue(os.path.isfile(self.outputs[name]))
                # Same number of content documents in and out.
                self.assertEqual(
                    len(_documents(CORPUS / name)),
                    len(_documents(self.outputs[name])))

    def test_translation_is_applied_and_anchors_kept(self):
        for name in BOOKS:
            with self.subTest(book=name):
                body = _xhtml_text(self.outputs[name])
                # The fake engine marks every translated segment.
                self.assertIn("IT&lt;", body)
                # Anchors/links survive (PG books are full of footnote links).
                self.assertIn("href=", body)
                # Content actually changed: the marker is absent from the source.
                self.assertNotIn("IT&lt;", _xhtml_text(CORPUS / name))


@unittest.skipUnless(os.environ.get("NOESIS_ONLINE_TESTS"), "online tests disabled")
class TestDarwinOnline(unittest.TestCase):
    def test_google_translates_a_real_section(self):
        from noesis_ebook_translator import book

        src = CORPUS / "origin_of_species.epub"
        tmp = tempfile.mkdtemp(prefix="noesis-darwin-online-")
        out = os.path.join(tmp, "origin_it.epub")
        book.translate_epub(
            str(src), out, engine="Google(Free)New",
            source_lang="English", target_lang="Italian",
            settings={"translation_position": "only", "cache_enabled": False})
        self.assertTrue(os.path.isfile(out))
        self.assertGreater(os.path.getsize(out), 0)


if __name__ == "__main__":
    unittest.main()
