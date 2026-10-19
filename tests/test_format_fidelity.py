"""Formatting fidelity of extraction/translation output (CSS must survive).

Three ebooklib/engine round-trip traps are covered here:

* ``EpubHtml.get_content`` rebuilds the document from ebooklib's template and
  does not keep the ``<head>`` it read, so a naive read/write drops every
  ``<link rel="stylesheet">`` (the CSS *file* stays in the package but nothing
  links it);
* an anchored chapter often sits *inside* a wrapper element
  (``<section><h1 id="...">``), so trimming by the top-level child's own
  position used to delete the wrapper -- and the chapter with it;
* a list whose only children are ``<li>`` was considered *inline-only*, so the
  whole list was translated as one segment and every item (with its ``class`` /
  ``id``) collapsed into the parent.
"""
import os
import tempfile
import unittest
import zipfile

from lxml import etree

from tests.fixtures import build_styled_epub, register_fake_engine

XHTML = "{http://www.w3.org/1999/xhtml}"


def _doc_bytes(path: str, suffix: str = "book.xhtml") -> bytes:
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith(suffix))
        return archive.read(name)


def _css_bytes(path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {n: archive.read(n) for n in archive.namelist()
                if n.lower().endswith(".css")}


def _classes(data: bytes) -> list[str]:
    root = etree.fromstring(data, etree.XMLParser(recover=True))
    return [el.get("class") for el in root.iter()
            if isinstance(el.tag, str) and el.get("class")]


def _tag_count(data: bytes, tag: str) -> int:
    root = etree.fromstring(data, etree.XMLParser(recover=True))
    return sum(1 for el in root.iter()
               if isinstance(el.tag, str) and el.tag.split("}")[-1] == tag)


def _body_text(data: bytes) -> str:
    root = etree.fromstring(data, etree.XMLParser(recover=True))
    body = root.find(f".//{XHTML}body")
    return " ".join((body if body is not None else root).itertext())


def _load_tool():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "tools" / "format_fidelity.py"
    spec = importlib.util.spec_from_file_location("format_fidelity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestToolClassification(unittest.TestCase):
    """A lost ``<br>`` is a layout nuance, not a lost *styled* block."""

    def test_br_is_neutral_and_a_lost_class_is_a_block(self):
        tool = _load_tool()
        tmp = tempfile.mkdtemp(prefix="noesis-fidelity-tool-")
        src = os.path.join(tmp, "src.epub")
        dst = os.path.join(tmp, "dst.epub")
        xhtml = ("<html xmlns='http://www.w3.org/1999/xhtml'><head></head><body>"
                 "<p class='keep'>one</p><p>line<br/>break</p></body></html>")
        xhtml_dst = ("<html xmlns='http://www.w3.org/1999/xhtml'><head></head><body>"
                     "<p>one</p><p>linebreak</p></body></html>")
        for path, body in ((src, xhtml), (dst, xhtml_dst)):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("OEBPS/c.css", b"p{color:red}")
                archive.writestr("OEBPS/doc.xhtml", body)
        report = tool.compare(src, dst)
        self.assertEqual(report["elements"]["lost_block"], 1)   # <p class='keep'>
        self.assertEqual(report["elements"]["lost_neutral"], 1)  # the <br>
        self.assertFalse(report["ok"])


class TestFormatFidelity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="noesis-fidelity-")
        cls.book = build_styled_epub(os.path.join(cls.tmp, "styled.epub"))

    def test_export_keeps_the_stylesheet_link(self):
        from noesis_ebook_translator import exporter

        out = os.path.join(self.tmp, "exported.epub")
        exporter.export_epub(self.book, out)
        doc = _doc_bytes(out)
        self.assertIn(b'rel="stylesheet"', doc)
        self.assertIn(b'href="style/book.css"', doc)
        self.assertIn(b"<title>", doc)
        self.assertEqual(_css_bytes(self.book), _css_bytes(out))

    def test_chapter_export_keeps_the_wrapper_and_drops_the_other_chapter(self):
        from noesis_ebook_translator import exporter
        from noesis_ebook_translator.chapters import (
            chapters_from_book, resolve_selection)
        from ebooklib import epub

        book = epub.read_epub(self.book)
        selected = resolve_selection(chapters_from_book(book), ["book.xhtml#c2"])
        out = os.path.join(self.tmp, "chapter2.epub")
        exporter.export_epub(self.book, out, selected=selected)

        data = _doc_bytes(out)
        text = _body_text(data)
        self.assertIn("UNIQUE2", text)
        self.assertNotIn("UNIQUE1", text)
        # The anchor lives inside the wrapper: both are kept.
        self.assertIn(b'id="wrap2"', data)
        self.assertIn(b'id="c2"', data)
        # ... and the head with it.
        self.assertIn(b'href="style/book.css"', data)

    def test_translation_keeps_css_and_block_structure(self):
        from noesis_ebook_translator import book as book_mod

        register_fake_engine()
        out = os.path.join(self.tmp, "translated.epub")
        book_mod.translate_epub(
            self.book, out, engine="Fake",
            source_lang="English", target_lang="Italian",
            settings={"translation_position": "only", "cache_enabled": False})

        source_doc = _doc_bytes(self.book)
        translated_doc = _doc_bytes(out)
        self.assertIn(b'href="style/book.css"', translated_doc)
        self.assertEqual(_css_bytes(self.book), _css_bytes(out))
        # Block-level styling (classes/ids on sections, headings, paragraphs) is
        # what the stylesheet selects: it must not move or disappear.
        self.assertEqual(_classes(source_doc), _classes(translated_doc))
        self.assertEqual(_tag_count(source_doc, "li"),
                         _tag_count(translated_doc, "li"))
        self.assertIn("IT<", _body_text(translated_doc))


if __name__ == "__main__":
    unittest.main()
