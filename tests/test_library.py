"""Library (SQLite) + chapter store + session adapter tests."""
import json
import os
import tempfile
import unittest

from tests.fixtures import build_rich_epub

from noesis_ebook_translator.chapter_store import ChapterStore
from noesis_ebook_translator.library import Library
from noesis_ebook_translator.reader.session import Session


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-library-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))
        self.lib = Library(os.path.join(self.tmp, "library.db"))

    def tearDown(self):
        self.lib.close()

    def test_add_and_list_books(self):
        self.lib.add_book(self.epub, title="Rich", author="Me", language="en")
        books = self.lib.books()
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["title"], "Rich")
        self.assertEqual(books[0]["author"], "Me")

    def test_position_roundtrip(self):
        self.lib.set_position(self.epub, "c1.xhtml", 0.42)
        pos = self.lib.get_position(self.epub)
        self.assertEqual(pos["href"], "c1.xhtml")
        self.assertAlmostEqual(pos["fraction"], 0.42, places=3)

    def test_translated_path(self):
        self.lib.set_translated(self.epub, "/tmp/out.epub")
        self.assertEqual(self.lib.get_book(self.epub)["translated_path"],
                         "/tmp/out.epub")

    def test_annotations(self):
        self.lib.add_annotation(self.epub, {"text": "hi", "note": "n"})
        items = self.lib.annotations(self.epub)
        self.assertEqual(len(items), 1)
        self.lib.remove_annotation(self.epub, 0)
        self.assertEqual(self.lib.annotations(self.epub), [])

    def test_remove_book(self):
        self.lib.add_book(self.epub, title="Rich")
        self.lib.remove_book(self.epub)
        self.assertEqual(self.lib.books(), [])

    def test_migration_from_reader_json(self):
        legacy = os.path.join(self.tmp, "reader.json")
        with open(legacy, "w", encoding="utf-8") as handle:
            json.dump({
                "recent": [{"path": self.epub, "title": "Legacy"}],
                "positions": {os.path.abspath(self.epub):
                              {"href": "c2.xhtml", "fraction": 0.1}},
                "annotations": {os.path.abspath(self.epub):
                                [{"text": "x", "note": "y"}]},
            }, handle)
        fresh = Library(os.path.join(self.tmp, "fresh.db"))
        try:
            imported = fresh.migrate_from_json(legacy)
            self.assertEqual(imported, 1)
            self.assertEqual(fresh.books()[0]["title"], "Legacy")
            self.assertEqual(fresh.get_position(self.epub)["href"], "c2.xhtml")
            self.assertEqual(len(fresh.annotations(self.epub)), 1)
        finally:
            fresh.close()


class TestSessionAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-session-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))
        self.session = Session(os.path.join(self.tmp, "session.db"))

    def test_recent_and_position(self):
        self.session.add_recent(self.epub, "Rich")
        self.assertEqual(self.session.recent()[0]["title"], "Rich")
        self.session.set_position(self.epub, "c1.xhtml", 0.5)
        self.assertEqual(self.session.get_position(self.epub)["fraction"], 0.5)
        self.session.remove_recent(self.epub)
        self.assertEqual(self.session.recent(), [])

    def test_translated(self):
        self.session.add_recent(self.epub)
        self.session.set_translated(self.epub, "/tmp/t.epub")
        self.assertEqual(self.session.recent()[0]["translated_path"], "/tmp/t.epub")


class TestChapterStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-chapters-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))
        self.store = ChapterStore(os.path.join(self.tmp, "chapters.db"))

    def tearDown(self):
        self.store.close()

    def test_sync_from_epub(self):
        count = self.store.sync_from_epub(self.epub)
        self.assertEqual(count, 3)
        rows = self.store.for_book(self.epub)
        indices = [r["chapter_index"] for r in rows]
        self.assertEqual(len(set(indices)), len(indices))
        self.assertTrue(all(r["source_text"] for r in rows))

    def test_translation_and_search(self):
        self.store.sync_from_epub(self.epub)
        first = self.store.for_book(self.epub)[0]
        self.store.set_translation(self.epub, first["chapter_index"],
                                   "TESTO TRADOTTO")
        updated = self.store.get(self.epub, first["chapter_index"])
        self.assertEqual(updated["translation"], "TESTO TRADOTTO")
        self.assertEqual(updated["status"], "translated")
        self.assertEqual(len(self.store.search("TRADOTTO")), 1)


if __name__ == "__main__":
    unittest.main()
