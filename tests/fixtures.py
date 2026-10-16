"""Small EPUB fixture builder + a deterministic offline translation engine."""
from __future__ import annotations

import base64
import os

from ebooklib import epub

# 1x1 transparent PNG.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ"
    "/pLvAAAAAElFTkSuQmCC")


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


def build_rich_epub(path: str) -> str:
    """A 3-chapter EPUB with a nested TOC, a captioned figure and a table."""
    book = epub.EpubBook()
    book.set_identifier("noesis-rich-1")
    book.set_title("The Rich Test")
    book.set_language("en")

    image = epub.EpubImage()
    image.file_name = "images/pic.png"
    image.media_type = "image/png"
    image.set_content(TINY_PNG)
    book.add_item(image)

    c1 = epub.EpubHtml(title="Introduction", file_name="c1.xhtml", lang="en")
    c1.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
        "<h1>Introduction</h1>"
        "<p>Opening paragraph.</p>"
        "<div class='figcenter'><img src='images/pic.png' alt=''/>"
        "<p>Fig. 1. A very small picture.</p></div>"
        "<table><caption>Tab. 1. Sample</caption>"
        "<tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        "</body></html>")
    c2 = epub.EpubHtml(title="Chapter 2", file_name="c2.xhtml", lang="en")
    c2.content = ("<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
                  "<h1>Chapter Two</h1><p>Body of chapter two.</p></body></html>")
    c3 = epub.EpubHtml(title="Chapter 3", file_name="c3.xhtml", lang="en")
    c3.content = ("<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
                  "<h1>Chapter Three</h1><p>Body of chapter three.</p></body></html>")
    for item in (c1, c2, c3):
        book.add_item(item)
    book.toc = (
        epub.Link("c1.xhtml", "Introduction", "c1"),
        (epub.Section("Part Two"),
         (epub.Link("c2.xhtml", "Chapter 2", "c2"),
          epub.Link("c3.xhtml", "Chapter 3", "c3"))),
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2, c3]
    epub.write_epub(path, book)
    return path


def build_anchored_epub(path: str) -> str:
    """Create an EPUB whose 3 TOC entries are anchors inside one XHTML file."""
    book = epub.EpubBook()
    book.set_identifier("noesis-anchor-1")
    book.set_title("Anchored Test")
    book.set_language("en")
    doc = epub.EpubHtml(title="Book", file_name="book.xhtml", lang="en")
    doc.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
        "<h1 id='ch1'>Chapter One</h1><p>UNIQUE1 content of chapter one.</p>"
        "<h1 id='ch2'>Chapter Two</h1><p>UNIQUE2 content of chapter two.</p>"
        "<h1 id='ch3'>Chapter Three</h1><p>UNIQUE3 content of chapter three.</p>"
        "</body></html>")
    book.add_item(doc)
    book.toc = (
        epub.Link("book.xhtml#ch1", "Chapter 1", "ch1"),
        epub.Link("book.xhtml#ch2", "Chapter 2", "ch2"),
        epub.Link("book.xhtml#ch3", "Chapter 3", "ch3"),
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", doc]
    epub.write_epub(path, book)
    return path


def build_partitioned_epub(path: str) -> str:
    """Two top-level parts (one with nested sub-parts), shared documents too.

    The corpus has no section entries at all, so this is the fixture that covers
    headings (nested, and with siblings) *and* several chapters anchored inside
    one XHTML document.
    """
    book = epub.EpubBook()
    book.set_identifier("noesis-partitioned-1")
    book.set_title("The Partitioned Test")
    book.set_language("en")

    part = epub.EpubHtml(title="Part", file_name="part.xhtml", lang="en")
    part.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
        "<h1 id='ch1'>Chapter One</h1><p>UNIQUE1 content one.</p>"
        "<h1 id='ch2'>Chapter Two</h1><p>UNIQUE2 content two.</p>"
        "</body></html>")
    c3 = epub.EpubHtml(title="Chapter Three", file_name="c3.xhtml", lang="en")
    c3.content = ("<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
                  "<h1>Chapter Three</h1><p>UNIQUE3 content three.</p>"
                  "</body></html>")
    c4 = epub.EpubHtml(title="Chapter Four", file_name="c4.xhtml", lang="en")
    c4.content = ("<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
                  "<h1>Chapter Four</h1><p>UNIQUE4 content four.</p>"
                  "</body></html>")
    for item in (part, c3, c4):
        book.add_item(item)
    book.toc = (
        (epub.Section("Part One"),
         ((epub.Section("Part One-A"),
           (epub.Link("part.xhtml#ch1", "Chapter 1", "ch1"),
            epub.Link("part.xhtml#ch2", "Chapter 2", "ch2"))),
          (epub.Section("Part One-B"),
           (epub.Link("c3.xhtml", "Chapter 3", "c3"),)))),
        (epub.Section("Part Two"),
         (epub.Link("c4.xhtml", "Chapter 4", "c4"),)),
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", part, c3, c4]
    epub.write_epub(path, book)
    return path


def build_broken_manifest_epub(path: str) -> str:
    """A valid book whose package document lists a file that is not in the archive.

    That is how real "slim" re-packs are broken: the OPF still declares fonts or
    scripts that were stripped. :mod:`ebooklib` then refuses to read the book, but
    the table of contents is intact and has to be recovered from the archive.
    """
    import zipfile

    tmp = f"{path}.tmp"
    build_rich_epub(tmp)
    with zipfile.ZipFile(tmp) as source, zipfile.ZipFile(path, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.endswith("content.opf"):
                data = data.replace(
                    b"</manifest>",
                    b'<item id="ghost" href="fonts/ghost.woff" '
                    b'media-type="font/woff"/></manifest>')
            target.writestr(info, data)
    os.remove(tmp)
    return path


def build_nav_only_epub(path: str) -> str:
    """An EPUB 3 with a navigation document and no NCX at all."""
    book = epub.EpubBook()
    book.set_identifier("noesis-nav-1")
    book.set_title("The Nav Test")
    book.set_language("en")

    c1 = epub.EpubHtml(title="Intro", file_name="c1.xhtml", lang="en")
    c1.content = ("<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
                  "<h1>Intro</h1><p>Text one.</p></body></html>")
    c2 = epub.EpubHtml(title="Body", file_name="c2.xhtml", lang="en")
    c2.content = ("<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
                  "<h1>Body</h1><p>Text two.</p></body></html>")
    book.add_item(c1)
    book.add_item(c2)
    book.toc = (epub.Link("c1.xhtml", "Intro", "c1"),
                (epub.Section("Part"), (epub.Link("c2.xhtml", "Body", "c2"),)))
    book.add_item(epub.EpubNav())      # no EpubNcx: EPUB 3 only
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

    # Idempotent: several suites call this, and the harness calls it per scenario.
    for engine in engines.builtin_engines:
        if getattr(engine, "name", None) == "Fake":
            return engine

    fake = make_fake_engine()
    extended = tuple(engines.builtin_engines) + (fake,)
    # ``lib/translation.py`` binds ``builtin_engines`` at import time, so patch
    # both the package attribute and the already-imported reference.
    engines.builtin_engines = extended
    translation_mod.builtin_engines = extended
    return fake


def make_score_engine():
    """Return an offline engine that always replies with a fixed score."""
    from noesis_ebook_translator.engines.base import Base
    from noesis_ebook_translator.engines.languages import google

    class ScoreEngine(Base):
        name = "FakeScore"
        alias = "FakeScore"
        free = True
        need_api_key = False
        lang_codes = Base.load_lang_codes(google)
        endpoint = ""

        def translate(self, content):
            return "85"

    return ScoreEngine


def register_score_engine():
    """Inject the score engine into the registry (for AI-judge tests)."""
    import noesis_ebook_translator.engines as engines
    from noesis_ebook_translator.lib import translation as translation_mod
    from noesis_ebook_translator.lib import utils as utils_mod

    utils_mod.log.level = utils_mod.log.ERROR
    engine = make_score_engine()
    extended = tuple(engines.builtin_engines) + (engine,)
    engines.builtin_engines = extended
    translation_mod.builtin_engines = extended
    return engine
