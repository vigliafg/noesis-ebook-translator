"""Small EPUB fixture builder + a deterministic offline translation engine."""
from __future__ import annotations

import os

from ebooklib import epub


def build_sample_epub(path: str) -> str:
    """Create a tiny 2-chapter EPUB with a TOC and inline markup."""
    book = epub.EpubBook()
    book.set_identifier("noesis-test-1")
    book.set_title("The Little Test")
    book.set_language("en")

    c1 = epub.EpubHtml(title="Chapter 1", file_name="chap_01.xhtml", lang="en")
    c1.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
        "<h1>Chapter One</h1>"
        "<p>Hello <em>world</em>, this is a test.</p>"
        "<p>Second paragraph with an <a href='x'>anchor</a> inside.</p>"
        "</body></html>")
    c2 = epub.EpubHtml(title="Chapter 2", file_name="chap_02.xhtml", lang="en")
    c2.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
        "<h1>Chapter Two</h1>"
        "<p>A lone sentence to translate.</p>"
        "</body></html>")
    book.add_item(c1)
    book.add_item(c2)
    book.toc = (epub.Link("chap_01.xhtml", "Chapter 1", "c1"),
                epub.Link("chap_02.xhtml", "Chapter 2", "c2"))
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]
    epub.write_epub(path, book)
    return path


def make_fake_engine():
    """Return an offline engine class that marks the text it receives."""
    from noesis_ebook_translator.engines.base import Base
    from noesis_ebook_translator.engines.languages import google

    class FakeEngine(Base):
        name = "Fake"
        alias = "Fake"
        free = True
        need_api_key = False
        lang_codes = Base.load_lang_codes(google)
        endpoint = ""

        def translate(self, content):
            return "IT<" + content + ">"

    return FakeEngine


def register_fake_engine():
    """Inject the fake engine into the registry and return its class."""
    import noesis_ebook_translator.engines as engines
    from noesis_ebook_translator.lib import translation as translation_mod
    from noesis_ebook_translator.lib import utils as utils_mod

    # Keep test output readable: the engine logs every paragraph at INFO.
    utils_mod.log.level = utils_mod.log.ERROR

    fake = make_fake_engine()
    extended = tuple(engines.builtin_engines) + (fake,)
    # ``lib/translation.py`` binds ``builtin_engines`` at import time, so patch
    # both the package attribute and the already-imported reference.
    engines.builtin_engines = extended
    translation_mod.builtin_engines = extended
    return fake
