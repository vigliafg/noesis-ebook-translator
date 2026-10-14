"""End-to-end pipeline test using an offline fake engine (no network)."""
import os
import tempfile
import unittest
import zipfile

from tests.fixtures import build_sample_epub, register_fake_engine


class TestTranslatePipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_fake_engine()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="noesis-et-e2e-")
        self.src = build_sample_epub(os.path.join(self.tmp, "book.epub"))
        self.out = os.path.join(self.tmp, "book_out.epub")

    def _read_docs(self):
        docs = {}
        with zipfile.ZipFile(self.out) as archive:
            for name in archive.namelist():
                if name.endswith((".xhtml", ".html")):
                    docs[name] = archive.read(name).decode("utf-8")
        return docs

    def test_translation_replaces_text_and_keeps_markup(self):
        from noesis_ebook_translator import book

        logs = []
        result = book.translate_epub(
            self.src, self.out, engine="Fake",
            source_lang="English", target_lang="Italian",
            settings={"translation_position": "only", "cache_enabled": False},
            on_log=lambda text, error=False: logs.append(text))
        self.assertEqual(result, self.out)
        self.assertTrue(os.path.isfile(self.out))

        docs = self._read_docs()
        body = "\n".join(docs.values())
        # The fake engine wraps the source text: "IT&lt;...&gt;".
        self.assertIn("IT&lt;", body)
        # Anchors are reserved and re-inserted (navigation/footnote targets).
        self.assertIn("<a", body)
        # Single-language output: the source sentence appears exactly once
        # (only inside the translated paragraph), never duplicated as bilingual.
        self.assertEqual(body.count("A lone sentence to translate."), 1)

    def test_output_path_default(self):
        from noesis_ebook_translator import book

        self.assertTrue(
            book.default_output_path("/x/Book.epub", "Italian").endswith("_ITALIAN.epub"))


if __name__ == "__main__":
    unittest.main()
