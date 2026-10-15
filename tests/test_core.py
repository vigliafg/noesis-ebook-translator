"""Core headless tests: chapters, extraction, export, chapter-scoped translation."""
import os
import tempfile
import unittest
import zipfile

from ebooklib import epub

from tests.fixtures import (
    build_anchored_epub, build_rich_epub, build_sample_epub, register_fake_engine)


class TestChapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-core-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))

    def test_nested_toc_tree(self):
        from noesis_ebook_translator import chapters

        tree = chapters.load_chapters(self.epub)
        flat = chapters.flatten(tree)
        names = [c.name for c in flat]
        self.assertIn("Introduction", names)
        self.assertIn("Chapter 2", names)
        self.assertIn("Chapter 3", names)
        # At least one node has a child (nested TOC).
        self.assertTrue(any(c.children for c in tree))

    def test_resolve_selection_by_index_and_href(self):
        from noesis_ebook_translator import chapters

        tree = chapters.load_chapters(self.epub)
        by_href = chapters.resolve_selection(tree, ["c3.xhtml"])
        self.assertEqual([c.file for c in by_href], ["c3.xhtml"])
        self.assertEqual(chapters.chapter_files(by_href), {"c3.xhtml"})

    def test_selection_of_section_includes_descendants(self):
        from noesis_ebook_translator import chapters

        tree = chapters.load_chapters(self.epub)
        # "Part Two" is the file-less Section that groups Chapter 2 and 3.
        section = next(c for c in chapters.flatten(tree) if c.name == "Part Two")
        selected = chapters.resolve_selection(tree, str(section.index))
        self.assertEqual(chapters.chapter_files(selected), {"c2.xhtml", "c3.xhtml"})

    def test_book_meta(self):
        from noesis_ebook_translator import chapters

        meta = chapters.book_meta(self.epub)
        self.assertEqual(meta["title"], "The Rich Test")


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-core-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))

    def test_figure_with_caption_and_number(self):
        from noesis_ebook_translator import chapters, extract

        tree = chapters.load_chapters(self.epub)
        figures = extract.extract_figures(self.epub, tree)
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0].number, 1)
        self.assertEqual(figures[0].caption, "Fig. 1. A very small picture.")
        self.assertTrue(figures[0].data.startswith(b"\x89PNG"))

    def test_table_with_caption(self):
        from noesis_ebook_translator import extract

        tables = extract.extract_tables(self.epub)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].caption, "Tab. 1. Sample")
        self.assertEqual(tables[0].rows, [["A", "B"], ["1", "2"]])

    def test_text_blocks(self):
        from noesis_ebook_translator import extract

        blocks = extract.extract_text(self.epub)
        texts = [t for _, _, t in blocks]
        self.assertIn("Opening paragraph.", texts)


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-core-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))

    def test_export_selected_chapters_only(self):
        from noesis_ebook_translator import chapters, exporter

        tree = chapters.load_chapters(self.epub)
        selected = chapters.resolve_selection(tree, ["c3.xhtml"])  # Chapter 3
        out = os.path.join(self.tmp, "only3.epub")
        exporter.export_chapters(self.epub, out, selected, "epub")
        book = epub.read_epub(out)
        docs = [i.file_name for i in book.get_items() if i.get_type() == 9]
        self.assertEqual(docs, ["c3.xhtml"])

    def test_export_html_md_txt(self):
        from noesis_ebook_translator import exporter

        html = os.path.join(self.tmp, "all.html")
        md = os.path.join(self.tmp, "all.md")
        txt = os.path.join(self.tmp, "all.txt")
        exporter.export_chapters(self.epub, html, None, "html")
        exporter.export_chapters(self.epub, md, None, "md")
        exporter.export_chapters(self.epub, txt, None, "txt")
        self.assertIn("The Rich Test", open(html, encoding="utf-8").read())
        self.assertIn("Chapter Three", open(md, encoding="utf-8").read())
        self.assertIn("Opening paragraph.", open(txt, encoding="utf-8").read())

    def test_export_figures_and_tables(self):
        from noesis_ebook_translator import chapters, extract, exporter

        tree = chapters.load_chapters(self.epub)
        figs = extract.extract_figures(self.epub, tree)
        tabs = extract.extract_tables(self.epub)
        img_files = exporter.export_figures(figs, os.path.join(self.tmp, "figs"), "img")
        csv_files = exporter.export_tables(tabs, os.path.join(self.tmp, "tabs"), "csv")
        self.assertEqual(len(img_files), 1)
        self.assertTrue(img_files[0].endswith(".png"))
        self.assertTrue(csv_files[0].endswith(".csv"))


class TestAnchorChapters(unittest.TestCase):
    """Chapters that share one XHTML file (TOC anchors) must isolate correctly."""

    @classmethod
    def setUpClass(cls):
        register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-anchor-")
        self.epub = build_anchored_epub(os.path.join(self.tmp, "a.epub"))

    def _body(self, path):
        with zipfile.ZipFile(path) as archive:
            return "\n".join(
                archive.read(n).decode("utf-8", "replace")
                for n in archive.namelist() if n.endswith(".xhtml"))

    def test_translate_single_anchored_chapter(self):
        from noesis_ebook_translator import book

        out = os.path.join(self.tmp, "ch2.epub")
        book.translate_epub(self.epub, out, engine="Fake", chapters=["book.xhtml#ch2"],
                            settings={"translation_position": "only",
                                      "cache_enabled": False})
        body = self._body(out)
        self.assertIn("UNIQUE2", body)
        self.assertNotIn("UNIQUE1", body)
        self.assertNotIn("UNIQUE3", body)

    def test_export_single_anchored_chapter(self):
        from noesis_ebook_translator import chapters, exporter

        tree = chapters.load_chapters(self.epub)
        selected = chapters.resolve_selection(tree, ["book.xhtml#ch2"])
        out = os.path.join(self.tmp, "ch2_export.epub")
        exporter.export_epub(self.epub, out, selected)
        body = self._body(out)
        self.assertIn("UNIQUE2", body)
        self.assertNotIn("UNIQUE1", body)
        self.assertNotIn("UNIQUE3", body)

    def test_split_isolates_anchored_chapters(self):
        from noesis_ebook_translator import segment

        parts = segment.split_epub(self.epub, os.path.join(self.tmp, "parts"),
                                   mode="flat")
        self.assertEqual(len(parts), 3)
        bodies = [self._body(p) for p in parts]
        self.assertIn("UNIQUE1", bodies[0])
        self.assertNotIn("UNIQUE2", bodies[0])
        self.assertIn("UNIQUE2", bodies[1])
        self.assertNotIn("UNIQUE1", bodies[1])
        self.assertIn("UNIQUE3", bodies[2])
        self.assertNotIn("UNIQUE2", bodies[2])


class TestChapterTranslation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-core-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))

    def test_translate_only_selected_chapter(self):
        from noesis_ebook_translator import book

        out = os.path.join(self.tmp, "ch3.epub")
        book.translate_epub(
            self.epub, out, engine="Fake", chapters=["c3.xhtml"],
            settings={"translation_position": "only", "cache_enabled": False})
        result = epub.read_epub(out)
        docs = [i.file_name for i in result.get_items() if i.get_type() == 9]
        self.assertEqual(docs, ["c3.xhtml"])
        with zipfile.ZipFile(out) as archive:
            body = "\n".join(
                archive.read(n).decode("utf-8", "replace")
                for n in archive.namelist() if n.endswith((".html", ".xhtml")))
        self.assertIn("IT&lt;", body)

    def test_preview_translation_returns_pairs(self):
        from noesis_ebook_translator import book

        pairs = book.preview_translation(
            self.epub, engine="Fake", limit=3, chapters="1")
        self.assertTrue(pairs)
        self.assertTrue(all(t.startswith("IT<") for _, t in pairs))
        self.assertEqual(len(pairs), 3)


if __name__ == "__main__":
    unittest.main()
