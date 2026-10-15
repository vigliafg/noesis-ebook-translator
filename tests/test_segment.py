"""Split/merge tests: round-trip preserves documents and structure."""
import os
import tempfile
import unittest

from ebooklib import epub

from tests.fixtures import build_rich_epub

from noesis_ebook_translator import segment


def _documents(path: str) -> list[str]:
    book = epub.read_epub(path)
    return sorted(i.file_name for i in book.get_items() if i.get_type() == 9)


class TestSplitMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-segment-")
        self.src = build_rich_epub(os.path.join(self.tmp, "rich.epub"))

    def test_split_creates_one_epub_per_chapter(self):
        parts = segment.split_epub(self.src, os.path.join(self.tmp, "parts"))
        # top-level chapters: Introduction and "Part Two"
        self.assertEqual(len(parts), 2)
        for part in parts:
            self.assertTrue(os.path.isfile(part))
            self.assertGreaterEqual(len(_documents(part)), 1)

    def test_split_flat_mode(self):
        parts = segment.split_epub(self.src, os.path.join(self.tmp, "flat"),
                                   mode="flat")
        # Introduction + Chapter 2 + Chapter 3 (the file-less Section is skipped)
        self.assertEqual(len(parts), 3)

    def test_merge_roundtrip_keeps_documents(self):
        parts = segment.split_epub(self.src, os.path.join(self.tmp, "parts"))
        merged = segment.merge_epubs(parts, os.path.join(self.tmp, "merged.epub"),
                                     title="Merged")
        docs = [d for d in _documents(merged) if not d.endswith("nav.xhtml")]
        self.assertEqual(len(docs), 3)
        book = epub.read_epub(merged)
        self.assertTrue(book.toc)
        self.assertEqual(book.get_metadata("DC", "title")[0][0], "Merged")

    def test_sanitize_name(self):
        self.assertEqual(segment.sanitize_name("Capitolo 1: Intro"),
                         "Capitolo_1_Intro")
        self.assertEqual(segment.sanitize_name(""), "section")


if __name__ == "__main__":
    unittest.main()
