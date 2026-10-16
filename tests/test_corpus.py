"""End-to-end tests over the real Project Gutenberg corpus (offline).

Runs the full pipeline on every book in ``tests/data/corpus`` (see
``tests/data/corpus/SOURCE.md`` and ``MANIFEST.json``): parsing, element
extraction, reserving inline markup, translation, multi-level TOC translation and
EPUB re-writing. It uses the offline fake engine — no network, no API keys.

Set ``NOESIS_ONLINE_TESTS=1`` to add a real Google-translate smoke test.
"""
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from ebooklib import epub

from tests.fixtures import register_fake_engine

CORPUS = Path(__file__).resolve().parent / "data" / "corpus"
MANIFEST = json.loads((CORPUS / "MANIFEST.json").read_text(encoding="utf-8")) \
    if (CORPUS / "MANIFEST.json").is_file() else []

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")


def _documents(path):
    return [i for i in epub.read_epub(str(path)).get_items() if i.get_type() == 9]


def _toc_depth(path):
    def depth(nodes):
        best = 0
        for item in nodes or []:
            if isinstance(item, (tuple, list)):
                best = max(best, 1 + depth(item[1] if len(item) > 1 else []))
            else:
                best = max(best, 1)
        return best
    return depth(epub.read_epub(str(path)).toc)


def _xhtml_text(path):
    chunks = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith((".xhtml", ".html", ".htm")):
                chunks.append(archive.read(name).decode("utf-8", "replace"))
    return "\n".join(chunks)


def _image_stats(path):
    files = tags = 0
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            lower = name.lower()
            if lower.endswith(IMAGE_EXT):
                files += 1
            if lower.endswith((".xhtml", ".html", ".htm")):
                tags += archive.read(name).decode("utf-8", "replace").lower().count("<img")
    return files, tags


@unittest.skipUnless(MANIFEST, "corpus manifest not present")
class TestGutenbergCorpus(unittest.TestCase):
    outputs: dict = {}

    @classmethod
    def setUpClass(cls):
        from noesis_ebook_translator import book

        register_fake_engine()
        cls.tmp = tempfile.mkdtemp(prefix="noesis-corpus-")
        for entry in MANIFEST:
            src = CORPUS / entry["file"]
            cls.outputs[entry["file"]] = book.translate_epub(
                str(src), os.path.join(cls.tmp, entry["file"]), engine="Fake",
                source_lang="English", target_lang="Italian",
                settings={"translation_position": "only", "cache_enabled": False})

    def test_each_book_translates_and_stays_valid(self):
        for entry in MANIFEST:
            with self.subTest(book=entry["file"]):
                out = self.outputs[entry["file"]]
                self.assertTrue(os.path.isfile(out))
                self.assertEqual(len(_documents(CORPUS / entry["file"])),
                                 len(_documents(out)))

    def test_translation_applied_and_anchors_kept(self):
        for entry in MANIFEST:
            with self.subTest(book=entry["file"]):
                body = _xhtml_text(self.outputs[entry["file"]])
                self.assertIn("IT&lt;", body)
                self.assertIn("href=", body)

    def test_illustrations_are_preserved(self):
        for entry in MANIFEST:
            with self.subTest(book=entry["file"]):
                self.assertEqual(
                    _image_stats(CORPUS / entry["file"]),
                    (entry["images"], entry["img_tags"]))
                self.assertEqual(
                    _image_stats(CORPUS / entry["file"]),
                    _image_stats(self.outputs[entry["file"]]))

    def test_multilevel_toc_is_preserved(self):
        for entry in MANIFEST:
            with self.subTest(book=entry["file"]):
                self.assertEqual(_toc_depth(self.outputs[entry["file"]]),
                                 entry["toc_depth"])

    def test_corpus_covers_multilevel_toc_and_images(self):
        illustrated = [
            e for e in MANIFEST if e["toc_depth"] >= 2 and e["images"] >= 15]
        self.assertGreaterEqual(
            len(illustrated), 10,
            "the corpus must include at least 10 illustrated books with a "
            "multi-level TOC")


@unittest.skipUnless(os.environ.get("NOESIS_ONLINE_TESTS"), "online tests disabled")
class TestCorpusOnline(unittest.TestCase):
    def test_google_translates_a_real_book(self):
        """A real provider, for real: the segments must come back translated.

        A file that merely exists is not proof: the free endpoint answers HTTP 400
        for very long segments (17 kB of raw text in a GET url), so a check on the
        size alone would pass even if *everything* failed.
        """
        from noesis_ebook_translator import book

        entry = min(MANIFEST, key=lambda e: e["bytes"])
        out = os.path.join(tempfile.mkdtemp(prefix="noesis-online-"),
                           entry["file"])
        stats = {"translated": 0, "errors": 0, "other": 0}

        def on_paragraph(paragraph):
            if getattr(paragraph, "ignored", False):
                return
            source = (paragraph.original or "").strip()
            translation = (paragraph.translation or "").strip()
            if paragraph.error:
                stats["errors"] += 1
            elif translation and translation != source:
                stats["translated"] += 1
            else:
                stats["other"] += 1

        book.translate_epub(
            str(CORPUS / entry["file"]), out, engine="Google(Free)New",
            source_lang="English", target_lang="Italian",
            settings={"translation_position": "only", "cache_enabled": False},
            on_paragraph=on_paragraph)

        self.assertGreater(os.path.getsize(out), 0)
        total = sum(stats.values())
        self.assertGreater(total, 0, "no segment was processed")
        self.assertGreater(stats["translated"], total / 2,
                           f"the provider translated too little: {stats}")
        # A handful of very long segments is the known free-endpoint limitation.
        self.assertLess(stats["errors"], total / 10,
                        f"too many segments failed: {stats}")


if __name__ == "__main__":
    unittest.main()
