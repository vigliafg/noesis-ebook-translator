"""Headless EPUB translation pipeline (the app's non-GUI core).

This module is the desktop app's own glue: it reads an EPUB with :mod:`ebooklib`,
reuses the *verbatim* Calibre-plugin engine (``lib/element.py`` +
``lib/translation.py``) to translate the content while preserving inline markup,
and writes the translated EPUB back. It exposes :func:`translate_epub`, which the
Qt GUI (``main.py``) and the CLI/TUI edition both drive.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Iterable

import ebooklib
from ebooklib import epub
from lxml import etree

from . import EbookTranslator
from .appconfig import ensure_defaults
from .chapters import (
    chapter_files, chapters_from_book, isolate_chapters, load_chapters,
    resolve_selection)
from .exporter import restrict_book
from .lib.cache import get_cache
from .lib.config import get_config
from .lib.element import (
    get_element_handler, get_page_elements, get_toc_elements)
from .lib.translation import get_engine_class, get_translation, get_translator
from .lib.utils import log, uid

__all__ = [
    "translate_epub", "preview_translation", "list_engine_names",
    "default_output_path",
]


# ---------------------------------------------------------------------------
#  Adapters: make ebooklib objects look like what the engine expects
# ---------------------------------------------------------------------------
class Page:
    """Wraps an :class:`ebooklib.epub.EpubItem` as the engine's "page"."""

    def __init__(self, item, data: etree._Element) -> None:
        self.item = item
        self.href = item.file_name
        self.id = item.file_name
        self.data = data

    def write_back(self) -> None:
        self.item.set_content(
            etree.tostring(
                self.data, encoding="utf-8", method="xml",
                xml_declaration=True))


class TocNode:
    """Adapter exposing ``.title`` / ``.nodes`` around an ebooklib TOC entry."""

    def __init__(self, source, title: str, nodes: list["TocNode"] | None = None):
        self.source = source
        self.title = title
        self.nodes = nodes or []

    def write_back(self) -> None:
        """Copy the translated title over the ebooklib entry, **recursively**.

        Nested entries are translated like the top level (they go through
        ``get_toc_elements``), so their titles must be written back too:
        without the recursion the sub-levels stayed in the original language.
        """
        if self.source is not None:
            try:
                self.source.title = self.title
            except Exception:  # pragma: no cover - defensive
                pass
        for child in self.nodes:
            child.write_back()


def _parse_pages(book: epub.EpubBook) -> list[Page]:
    pages: list[Page] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        try:
            data = etree.fromstring(
                item.get_content(),
                parser=etree.XMLParser(recover=True, resolve_entities=False))
        except Exception:  # pragma: no cover - malformed item, skip it
            continue
        pages.append(Page(item, data))
    return pages


def _parse_toc(toc: Iterable) -> list[TocNode]:
    nodes: list[TocNode] = []
    for entry in toc or []:
        children: list[TocNode] = []
        source = entry
        if isinstance(entry, (tuple, list)) and len(entry) > 0:
            source = entry[0]
            children = _parse_toc(entry[1]) if len(entry) > 1 else []
        title = getattr(source, "title", None)
        if title:
            nodes.append(TocNode(source, title, children))
        elif children:
            nodes.extend(children)
    return nodes


def _ensure_toc_uids(toc: Iterable) -> None:
    """Give every TOC entry a stable ``uid`` (ebooklib's NCX writer needs one)."""
    for entry in toc or []:
        if isinstance(entry, (tuple, list)):
            if entry:
                _ensure_toc_uids([entry[0]])
            if len(entry) > 1:
                _ensure_toc_uids(entry[1])
            continue
        if hasattr(entry, "uid") and not entry.uid:
            entry.uid = "toc-%s" % uid(str(getattr(entry, "href", "")), str(getattr(entry, "title", "")))


# ---------------------------------------------------------------------------
#  Public helpers
# ---------------------------------------------------------------------------
def list_engine_names() -> list[str]:
    from .engines import builtin_engines

    return sorted({e.name for e in builtin_engines if e.name is not None})


def default_output_path(input_path: str, target_lang: str = "Italian") -> str:
    base = os.path.splitext(input_path)[0]
    return f"{base}_{target_lang.upper()}.epub"


def _apply_settings(settings: dict[str, Any] | None) -> None:
    """Persist the run settings so the engine's ``get_config()`` sees them."""
    if not settings:
        return
    config = get_config()
    for key, value in settings.items():
        config.set(key, value)
    config.commit()


# ---------------------------------------------------------------------------
#  The pipeline
# ---------------------------------------------------------------------------
def translate_epub(
    input_path: str,
    output_path: str | None = None,
    *,
    engine: str | None = None,
    source_lang: str = "English",
    target_lang: str = "Italian",
    direction: str = "auto",
    settings: dict[str, Any] | None = None,
    chapters: Any = None,
    cache_only: bool = False,
    on_progress: Callable[[float, str], None] | None = None,
    on_log: Callable[[str, bool], None] | None = None,
    on_paragraph: Callable[[Any], None] | None = None,
    on_plan: Callable[[dict[str, int]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    """Translate ``input_path`` and return the path of the written EPUB."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(input_path)
    output_path = output_path or default_output_path(input_path, target_lang)

    ensure_defaults()
    _apply_settings(settings)

    # Pick and configure the engine.
    engine_class = get_engine_class(engine)
    translator = get_translator(engine_class)
    translator.set_source_lang(source_lang)
    translator.set_target_lang(target_lang)

    config = get_config()
    direction = direction or config.get("target_direction") or "auto"

    book = epub.read_epub(input_path)
    if chapters:
        all_chapters = chapters_from_book(book)
        selected = resolve_selection(all_chapters, chapters)
        restrict_book(book, chapter_files(selected))
        isolate_chapters(book, selected)
    pages = _parse_pages(book)
    toc_nodes = _parse_toc(book.toc)

    handler = get_element_handler(
        translator.placeholder, translator.separator, direction)
    handler.set_translation_lang(translator.get_iso639_target_code(target_lang))

    elements: list = []
    elements.extend(get_toc_elements(toc_nodes, []))
    elements.extend(get_page_elements(pages))
    originals = handler.prepare_original(elements)

    # Report the per-document segment totals *before* translating: the GUI uses
    # them to show real per-chapter progress (and chapter completion) instead of
    # a linear estimate. ``originals`` entries are
    # ``(id, md5, raw, content, ignored, attributes, page_id)``.
    if on_plan is not None:
        counts: dict[str, int] = {}
        for entry in originals:
            if entry[4]:      # ignored element
                continue
            page = entry[6]   # page_id = XHTML file name (or "toc.ncx")
            if page and page != "toc.ncx":
                counts[page] = counts.get(page, 0) + 1
        on_plan(counts)

    # Cache persists translations across runs (deduplicated by content).
    encoding = ""
    cache_id = uid(
        input_path + translator.name + target_lang
        + str(handler.get_merge_length()) + encoding)
    cache = get_cache(cache_id)
    cache.set_cache_only(cache_only)
    cache.set_info("title", os.path.basename(input_path))
    cache.set_info("engine_name", translator.name)
    cache.set_info("target_lang", target_lang)
    cache.set_info("plugin_version", EbookTranslator.__version__)
    cache.save(originals)
    _ensure_cache_rows(cache, originals)
    paragraphs = cache.all_paragraphs()

    def _log(text: str, error: bool = False) -> None:
        if on_log is not None:
            on_log(text, error)
        else:
            log.info(text)

    translation = get_translation(translator, _log)
    translation.set_callback(
        lambda paragraph: _persist_paragraph(cache, paragraph, on_paragraph))
    if on_progress is not None:
        translation.set_progress(
            lambda fraction, message: on_progress(fraction, message))
    if should_cancel is not None:
        translation.set_cancel_request(should_cancel)

    translation.handle(paragraphs)
    handler.add_translations(paragraphs)
    cache.done()

    for page in pages:
        page.write_back()
    for node in toc_nodes:
        node.write_back()

    _ensure_toc_uids(book.toc)
    epub.write_epub(output_path, book)
    return output_path


def _persist_paragraph(cache, paragraph, on_paragraph) -> None:
    cache.update_paragraph(paragraph)
    if on_paragraph is not None:
        on_paragraph(paragraph)


def _ensure_cache_rows(cache, originals) -> None:
    """Insert the segments the persistent cache is still missing.

    ``TranslationCache.save()`` refuses to insert when a persistent cache already
    exists and is larger than 50 kB (it assumes the previous run was complete).
    That breaks incremental work: a chapter translated for the *first* time would
    never enter the queue, so it stayed at 0% and the progress never finished.
    ``add`` is an ``INSERT ... ON CONFLICT DO NOTHING``, so this is idempotent.
    """
    if cache.is_fresh():
        return                          # save() already inserted everything
    known = {row[0] for row in cache.all()}
    missing = [entry for entry in originals if entry[0] not in known]
    if not missing:
        return
    for entry in missing:
        cache.add(*entry)
    cache.connection.commit()


def preview_translation(
    input_path: str,
    *,
    engine: str | None = None,
    source_lang: str = "English",
    target_lang: str = "Italian",
    chapters: Any = None,
    limit: int = 20,
    direction: str = "auto",
    settings: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """Translate a few segments and return ``[(original, translation), ...]``.

    Nothing is written to disk: this powers the GUI/CLI *preview*.
    """
    ensure_defaults()
    _apply_settings(settings)
    translator = get_translator(get_engine_class(engine))
    translator.set_source_lang(source_lang)
    translator.set_target_lang(target_lang)

    book = epub.read_epub(input_path)
    if chapters:
        selected = resolve_selection(chapters_from_book(book), chapters)
        restrict_book(book, chapter_files(selected))
        isolate_chapters(book, selected)
    pages = _parse_pages(book)

    handler = get_element_handler(
        translator.placeholder, translator.separator,
        direction or get_config().get("target_direction") or "auto")
    originals = handler.prepare_original(get_page_elements(pages))

    preview: list[tuple[str, str]] = []
    for entry in originals:
        content = entry[3]
        if entry[4] or not content.strip():
            continue
        try:
            translation = translator.translate(content)
        except Exception as exc:  # noqa: BLE001 - preview must not crash
            translation = f"[error: {exc}]"
        preview.append((content, str(translation).strip()))
        if len(preview) >= limit:
            break
    return preview
