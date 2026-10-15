"""Export + asset write-back tests (formats and EPUB editing)."""
import json
import os
import tempfile
import unittest

from tests.fixtures import TINY_PNG, build_rich_epub

from noesis_ebook_translator import chapters, exporter, extract


class TestExportFormats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-export-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))

    def test_supported_exports(self):
        formats = exporter.supported_exports()
        for fmt in ("epub", "html", "markdown", "text", "json", "csv"):
            self.assertIn(fmt, formats)

    def test_export_json_structure(self):
        out = os.path.join(self.tmp, "all.json")
        exporter.export_chapters(self.epub, out, None, "json")
        data = json.loads(open(out, encoding="utf-8").read())
        self.assertIn("chapters", data)
        self.assertTrue(data["chapters"])
        self.assertTrue(data["chapters"][0]["segments"])

    def test_export_csv_rows(self):
        out = os.path.join(self.tmp, "all.csv")
        exporter.export_chapters(self.epub, out, None, "csv")
        text = open(out, encoding="utf-8").read()
        self.assertIn("chapter,chapter_name,text", text)
        self.assertIn("Opening paragraph.", text)

    def test_export_text_and_markdown(self):
        txt = os.path.join(self.tmp, "all.txt")
        md = os.path.join(self.tmp, "all.md")
        exporter.export_chapters(self.epub, txt, None, "text")
        exporter.export_chapters(self.epub, md, None, "markdown")
        self.assertIn("Opening paragraph.", open(txt, encoding="utf-8").read())
        self.assertIn("Chapter Three", open(md, encoding="utf-8").read())

    def test_export_selected_chapter_only(self):
        tree = chapters.load_chapters(self.epub)
        selected = chapters.resolve_selection(tree, ["c3.xhtml"])
        out = os.path.join(self.tmp, "sel.json")
        exporter.export_chapters(self.epub, out, selected, "json")
        data = json.loads(open(out, encoding="utf-8").read())
        text = json.dumps(data)
        self.assertIn("Chapter Three", text)
        self.assertNotIn("Opening paragraph.", text)

    @unittest.skipUnless(exporter.docx_available(), "python-docx not installed")
    def test_export_docx(self):
        out = os.path.join(self.tmp, "all.docx")
        exporter.export_chapters(self.epub, out, None, "docx")
        self.assertGreater(os.path.getsize(out), 0)


class TestWriteBack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-writeback-")
        self.epub = build_rich_epub(os.path.join(self.tmp, "rich.epub"))

    def test_text_blocks_exclude_nav(self):
        blocks = extract.extract_text_blocks(self.epub)
        self.assertTrue(blocks)
        self.assertTrue(all(not b.file.endswith("nav.xhtml") for b in blocks))

    def test_apply_text_edits(self):
        blocks = extract.extract_text_blocks(self.epub)
        first = blocks[0]
        out = os.path.join(self.tmp, "edited.epub")
        extract.apply_text_edits(self.epub, out, [(first.file, first.order,
                                                   "EDITED")])
        after = extract.extract_text_blocks(out)
        self.assertEqual(after[0].text, "EDITED")

    def test_apply_table_edits(self):
        tables = extract.extract_tables(self.epub)
        self.assertTrue(tables)
        table = tables[0]
        out = os.path.join(self.tmp, "tabled.epub")
        extract.apply_table_edits(self.epub, out, [(table.file, table.order,
                                                    [["X", "Y"], ["1", "2"]])])
        edited = extract.extract_tables(out)[0]
        self.assertEqual(edited.rows, [["X", "Y"], ["1", "2"]])

    def test_replace_image(self):
        out = os.path.join(self.tmp, "img.epub")
        extract.replace_image(self.epub, out, "images/pic.png", TINY_PNG)
        self.assertTrue(os.path.isfile(out))

    def test_replace_image_unknown_raises(self):
        out = os.path.join(self.tmp, "img2.epub")
        with self.assertRaises(KeyError):
            extract.replace_image(self.epub, out, "images/missing.png", TINY_PNG)


if __name__ == "__main__":
    unittest.main()
