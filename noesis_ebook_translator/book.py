"""Headless EPUB translation pipeline (the app's non-GUI core).

This module is the desktop app's own glue: it reads an EPUB with :mod:`ebooklib`,
reuses the *verbatim* Calibre-plugin engine (``lib/element.py`` +
``lib/translation.py``) to translate the content while preserving inline markup,
and writes the translated EPUB back. It exposes :func:`translate_epub`, which the
Qt GUI (``main.py``) and the CLI/TUI edition both drive.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from glob import glob
from typing import Any, Callable, Iterable

import ebooklib
from ebooklib import epub
from lxml import etree

from . import EbookTranslator
from .appconfig import ensure_defaults
from .chapters import (
    chapter_files, chapters_from_book, isolate_chapters, load_chapters,
    preserve_document_markup, resolve_selection, toc_anchors)
from .exporter import restrict_book
from .lib.cache import TranslationCache, get_cache
from .lib.config import get_config
from .lib.element import (
    get_element_handler, get_page_elements, get_toc_elements)
from .lib.exception import TranslationCanceled, TranslationFailed
from .lib.translation import get_engine_class, get_translation, get_translator
from .lib.utils import log, uid

__all__ = [
    "translate_epub", "preview_translation", "list_engine_names",
    "default_output_path", "output_name", "output_base_name", "language_slug",
    "interrupted_runs", "dismiss_interrupted_run", "collect_segments",
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


def language_slug(language: str) -> str:
    """Lowercase, hyphen-separated form of a language name.

    ``"Italian"`` -> ``"italian"``, ``"Chinese (Simplified)"`` ->
    ``"chinese-simplified"``, ``"Portuguese (Brazil)"`` -> ``"portuguese-brazil"``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (language or "").lower()).strip("-")
    return slug or "translated"


def output_name(name: str, target_lang: str) -> str:
    """The file name of a translation: ``<name>-<language>.epub``.

    The suffix is always applied (that is the app's convention) and the extension
    is forced to ``.epub``: a user typing ``Dune`` or ``Dune.epub`` gets
    ``Dune-italian.epub``. Any folder in ``name`` is ignored on purpose -- the
    destination folder comes from the wizard.
    """
    stem = os.path.splitext(os.path.basename(name or ""))[0].strip() or "book"
    return f"{stem}-{language_slug(target_lang)}.epub"


def output_base_name(output_path: str, target_lang: str) -> str:
    """The inverse of :func:`output_name`: ``Dune-italian.epub`` -> ``Dune``.

    Resuming a run must target the *same* file that was being written, and the
    wizard/``_start_translation`` append the language suffix themselves; passing
    the full name back would produce ``Dune-italian-italian.epub``.
    """
    stem = os.path.splitext(os.path.basename(output_path or ""))[0]
    suffix = "-" + language_slug(target_lang)
    if stem.lower().endswith(suffix):
        stem = stem[: -len(suffix)]
    return stem or "book"


def default_output_path(input_path: str, target_lang: str = "Italian") -> str:
    folder = os.path.dirname(input_path)
    stem = os.path.splitext(os.path.basename(input_path))[0]
    return os.path.join(folder, output_name(stem, target_lang))


def _apply_settings(settings: dict[str, Any] | None) -> None:
    """Persist the run settings so the engine's ``get_config()`` sees them."""
    if not settings:
        return
    config = get_config()
    for key, value in settings.items():
        config.set(key, value)
    config.commit()


def _apply_translation_defaults(translator) -> None:
    """Apply the optional app-level sampler override.

    ``translate_temperature`` is ``None`` by default: the engine keeps its own
    temperature (DeepSeek ships 1.3, Gemini 0.9, the generic ones 1.0). Set it
    (or the per-engine ``temperature``) to force a value — a low one keeps
    short, context-free segments like chapter titles from drifting.
    """
    temperature = get_config().get("translate_temperature")
    if temperature is None or not hasattr(translator, "temperature"):
        return
    engine_config = getattr(translator, "config", None) or {}
    if "temperature" in engine_config:
        return  # an explicit per-engine value wins
    try:
        translator.temperature = float(temperature)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        pass


# ---------------------------------------------------------------------------
#  Crash-safe resume
# ---------------------------------------------------------------------------
# The verbatim cache keys its rows by the element's **position**, so a different
# chapter selection re-indexes them and its own rebuild drops everything outside
# the selection. Work already paid for must survive a power cut *and* a different
# selection, so every finished translation is also stored in a content-keyed
# table (same SQLite file): the source text is the only stable identity.
#
# The table is scoped by engine + model + source/target language **and style
# prompt**, so switching any of them can never mix translations (and switching
# back restores its own work).
_RESUME_TABLE = "noesis_resume"
#: Column added when the style prompt became part of a run's identity.
_RESUME_STYLE_COLUMN = "style_hash"


def _resume_content_hash(content: str) -> str:
    return uid(content or "")


def _style_hash(style_prompt: str | None) -> str:
    """Stable identity of the style addendum (``""`` when there is none)."""
    return uid(style_prompt or "")


def _resume_key(translator, source_lang: str, target_lang: str,
                style_hash: str = "") -> tuple[str, ...]:
    return (translator.name or "",
            str(getattr(translator, "model", "") or ""),
            source_lang or "",
            target_lang or "",
            style_hash or "")


def _create_resume_table(cache) -> None:
    cache.cursor.execute(
        f"CREATE TABLE IF NOT EXISTS {_RESUME_TABLE}("
        "content_hash TEXT NOT NULL, engine_name TEXT NOT NULL, "
        "model TEXT NOT NULL, source_lang TEXT NOT NULL, "
        "target_lang TEXT NOT NULL, style_hash TEXT NOT NULL DEFAULT '', "
        "original TEXT, translation TEXT, updated_at INTEGER, "
        "PRIMARY KEY(content_hash, engine_name, model, source_lang, "
        "target_lang, style_hash))")


def _ensure_resume_table(cache) -> None:
    """Create the resume table, migrating the pre-style version if needed.

    The style prompt is part of the key, so the old table (without the column)
    cannot simply gain one: SQLite cannot add a column to a primary key. The
    work is carried over with ``style_hash=''``, which is exactly the scope of
    runs translated without a style prompt — those keep resuming for free.
    """
    _create_resume_table(cache)
    columns = [row[1] for row in cache.cursor.execute(
        f"PRAGMA table_info({_RESUME_TABLE})").fetchall()]
    if _RESUME_STYLE_COLUMN in columns:
        cache.connection.commit()
        return
    legacy = f"{_RESUME_TABLE}_legacy"
    cache.cursor.execute(f"DROP TABLE IF EXISTS {legacy}")
    cache.cursor.execute(f"ALTER TABLE {_RESUME_TABLE} RENAME TO {legacy}")
    _create_resume_table(cache)
    cache.cursor.execute(
        f"INSERT INTO {_RESUME_TABLE}(content_hash, engine_name, model, "
        "source_lang, target_lang, style_hash, original, translation, "
        "updated_at) SELECT content_hash, engine_name, model, source_lang, "
        f"target_lang, '', original, translation, updated_at FROM {legacy}")
    cache.cursor.execute(f"DROP TABLE {legacy}")
    cache.connection.commit()


def _remember_translation(cache, paragraph, resume_key) -> None:
    """Record one finished paragraph in the content-keyed resume table.

    The later ``cache.update_paragraph()`` commits both statements together,
    so a power cut never leaves the two tables disagreeing.
    """
    if not paragraph.translation:
        return
    engine, model, source, target, style_hash = resume_key
    cache.cursor.execute(
        f"INSERT INTO {_RESUME_TABLE}("
        "content_hash, engine_name, model, source_lang, target_lang, "
        "style_hash, original, translation, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(content_hash, engine_name, model, source_lang, "
        "target_lang, style_hash) DO UPDATE SET "
        "translation=excluded.translation, original=excluded.original, "
        "updated_at=excluded.updated_at",
        (_resume_content_hash(paragraph.original), engine, model, source,
         target, style_hash, paragraph.original, paragraph.translation,
         int(time.time())))


def _seed_resume_translations(cache, originals, resume_key) -> int:
    """Restore known translations for this run's segments (by content)."""
    engine, model, source, target, style_hash = resume_key
    rows = cache.cursor.execute(
        f"SELECT content_hash, translation FROM {_RESUME_TABLE} "
        "WHERE engine_name=? AND model=? AND source_lang=? AND target_lang=? "
        "AND style_hash=?",
        (engine, model, source, target, style_hash)).fetchall()
    known = {content_hash: translation for content_hash, translation in rows
             if translation}
    if not known:
        return 0
    restored = 0
    for entry in originals:
        oid, content = entry[0], entry[3]
        if len(entry) > 4 and entry[4]:      # ignored element
            continue
        translation = known.get(_resume_content_hash(content))
        if not translation:
            continue
        cache.cursor.execute(
            "UPDATE cache SET translation=? WHERE id=? "
            "AND (translation IS NULL OR translation='')",
            (translation, oid))
        restored += cache.cursor.rowcount or 0
    cache.connection.commit()
    return restored


def _cache_progress(cache) -> tuple[int, int]:
    """``(translated, total)`` segments of the current selection."""
    done = cache.cursor.execute(
        "SELECT COUNT(*) FROM cache WHERE NOT ignored "
        "AND translation IS NOT NULL AND translation<>''").fetchone()[0]
    total = cache.cursor.execute(
        "SELECT COUNT(*) FROM cache WHERE NOT ignored").fetchone()[0]
    return int(done), int(total)


# ---------------------------------------------------------------------------
#  Run marker: does the *app* know a translation was interrupted?
# ---------------------------------------------------------------------------
# The engine resumes by itself, but only when the same translation is started
# again: after a power cut nothing told the user that hours of work were waiting.
# Every run writes its state into the cache's ``info`` table:
#
#   running    the marker set at the start; a *crash* (power cut, SIGKILL,
#              segfault) leaves it behind, because nothing runs after the
#              process is gone -- that is its signature.
#   finished   the EPUB was written (and renamed) safely.
#   cancelled  the user stopped the run on purpose (no prompt).
#   dismissed  the user declined to resume: stop asking for this run.
#
# An ordinary engine failure keeps ``running`` too: a long run that dies on a
# network error deserves the same "your work is here" notice. Declining once
# writes ``dismissed``, so it never nags twice.
_RUN_RUNNING = "running"
_RUN_FINISHED = "finished"
_RUN_CANCELLED = "cancelled"
_RUN_DISMISSED = "dismissed"


def _mark_running(cache, input_path: str, output_path: str,
                  config, *, style_prompt: str = "",
                  genre: str = "", concurrency: int = 0) -> None:
    """Record the run so an abrupt death can be discovered and resumed."""
    options = {
        "translation_position": config.get("translation_position") or "only",
        "cache_enabled": bool(config.get("cache_enabled")),
        "online_batching": bool(config.get("online_batching")),
        "sequential": bool(config.get("translate_sequential", True)),
        "concurrency": int(concurrency or 0),
        "style_prompt": style_prompt or "",
        "genre": genre or "",
        "style_hash": _style_hash(style_prompt),
    }
    cache.set_info("input_path", os.path.abspath(input_path))
    cache.set_info("output_path", os.path.abspath(output_path))
    cache.set_info("run_options", json.dumps(options))
    cache.set_info("run_status", _RUN_RUNNING)
    cache.set_info("run_updated_at", str(int(time.time())))
    cache.set_info("run_started_at", str(int(time.time())))
    cache.set_info("run_style_hash", _style_hash(style_prompt))


def _mark_status(cache, status: str) -> None:
    """Finish the run marker (the cache may already be closed)."""
    try:
        cache.set_info("run_status", status)
        cache.set_info("run_updated_at", str(int(time.time())))
    except sqlite3.Error:  # pragma: no cover - a non-persistent cache is gone
        pass


def _mark_finished(cache, *, engine_calls: int, segments: int,
                   concurrency: int, batching: bool) -> None:
    """Close the marker **and** record the throughput of this run.

    The estimate uses these numbers to replace its default latency with the
    measured one: after one real run, "how long will this take?" is grounded in
    what the provider actually did, not in a constant.
    """
    _mark_status(cache, _RUN_FINISHED)
    try:
        cache.set_info("run_finished_at", str(int(time.time())))
        cache.set_info("run_engine_calls", str(int(engine_calls)))
        cache.set_info("run_segments", str(int(segments)))
        cache.set_info("run_concurrency", str(int(concurrency)))
        cache.set_info("run_batching", "1" if batching else "0")
    except sqlite3.Error:  # pragma: no cover - non-persistent cache
        pass


def _read_cache_state(db_path: str) -> tuple[dict[str, str], int, int]:
    """Read a cache file without disturbing it: ``(info, done, total)``.

    Opened read-only: a discovery pass must never create a directory, migrate a
    file or write a byte -- and it may run while another process holds the same
    database.
    """
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:  # pragma: no cover - unreadable file
        return {}, 0, 0
    try:
        rows = connection.execute("SELECT key, value FROM info").fetchall()
        info = {str(key): value for key, value in rows}
        progress = connection.execute(
            "SELECT COUNT(*), "
            "(SELECT COUNT(*) FROM cache WHERE NOT ignored) "
            "FROM cache WHERE NOT ignored AND translation IS NOT NULL AND "
            "translation<>''").fetchone()
        done, total = (int(progress[0]), int(progress[1])) if progress else (0, 0)
    except sqlite3.Error:
        return {}, 0, 0
    finally:
        connection.close()
    return info, done, total


def _json_or_none(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def interrupted_runs(input_path: str | None = None, *,
                     directory: str | None = None) -> list[dict[str, Any]]:
    """Translations that were still in progress when their process died.

    Scans the translation-cache directory (milliseconds: it only opens the
    ``info`` table of each ``*.db``) and returns the runs whose marker is still
    ``running``, newest first. Pass ``input_path`` to see only one book.

    ``directory`` defaults to the live cache path (``TranslationCache.cache_path``);
    tests use it to point at a private store.
    """
    store = directory if directory is not None else TranslationCache.cache_path
    if not os.path.isdir(store):
        return []
    wanted = os.path.abspath(input_path) if input_path else None
    found: list[dict[str, Any]] = []
    for db_path in glob(os.path.join(store, "*.db")):
        info, done, total = _read_cache_state(db_path)
        if info.get("run_status") != _RUN_RUNNING:
            continue
        stored = info.get("input_path") or ""
        if wanted and os.path.abspath(stored) != wanted:
            continue
        if total < 1:
            continue                       # nothing was ever prepared
        updated_at = info.get("run_updated_at") or ""
        try:
            updated = int(updated_at)
        except (TypeError, ValueError):
            try:
                updated = int(os.path.getmtime(db_path))
            except OSError:  # pragma: no cover - vanished in the meantime
                updated = 0
        options = _json_or_none(info.get("run_options")) or {}
        found.append({
            "cache_path": db_path,
            "title": info.get("title") or os.path.basename(stored or db_path),
            "input_path": stored,
            "output_path": info.get("output_path") or "",
            "engine": info.get("engine_name") or "",
            "model": info.get("model") or "",
            "source_lang": info.get("source_lang") or "",
            "target_lang": info.get("target_lang") or "",
            "chapters": _json_or_none(info.get("chapters")),
            "options": options,
            "style_prompt": options.get("style_prompt") or "",
            "genre": options.get("genre") or "",
            "done": done,
            "total": total,
            "updated_at": updated,
        })
    found.sort(key=lambda run: (run["updated_at"], run["cache_path"]),
               reverse=True)
    return found


def dismiss_interrupted_run(run: dict[str, Any] | str) -> None:
    """Stop offering ``run`` again (the user answered "No").

    Best effort by design: a cache that cannot be written (or that vanished) must
    not make opening a book fail.
    """
    path = run.get("cache_path") if isinstance(run, dict) else str(run)
    if not path or not os.path.isfile(path):
        return
    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error:  # pragma: no cover - unreadable file
        return
    try:
        connection.execute(
            "INSERT INTO info VALUES (?, ?) ON CONFLICT(key) DO UPDATE "
            "SET value=excluded.value", ("run_status", _RUN_DISMISSED))
        connection.commit()
    except sqlite3.Error:  # pragma: no cover - unexpected schema
        pass
    finally:
        connection.close()


# ---------------------------------------------------------------------------
#  The pipeline
# ---------------------------------------------------------------------------
def _segment_anchors(book, pages, elements) -> dict[int, str]:
    """Map each prepared element to the TOC anchor that owns it.

    ``isolate_chapters`` already trims a shared XHTML document to the selected
    ``[anchor, next_anchor)`` ranges, so the same "last anchor before this node"
    rule gives the chapter a segment belongs to -- which is what the estimate
    needs to report tokens **per chapter** even when two entries share a file.
    """
    anchors_by_file = toc_anchors(book)
    roots = {page.href: page.data for page in pages
             if getattr(page, "data", None) is not None}
    positions: dict[str, tuple[dict, list]] = {}
    for file_name, root in roots.items():
        try:
            order = {node: index for index, node in enumerate(root.iter())}
        except Exception:  # noqa: BLE001 - defensive: a broken page gets no anchors
            continue
        wanted = anchors_by_file.get(file_name) or set()
        found: dict[str, int] = {}
        for node in root.iter():
            identifier = node.get("id")
            if identifier and identifier in wanted and identifier not in found:
                found[identifier] = order.get(node, 0)
        positions[file_name] = (order, sorted(found.items(), key=lambda p: p[1]))

    result: dict[int, str] = {}
    for oid, element in enumerate(elements):
        page_id = getattr(element, "page_id", None)
        node = getattr(element, "element", None)
        if not page_id or page_id == "toc.ncx" or page_id not in positions:
            continue
        order, ordered = positions[page_id]
        position = order.get(node)
        if position is None or not ordered:
            continue
        current = ""
        for anchor, anchor_position in ordered:
            if anchor_position <= position:
                current = anchor
            else:
                break
        result[oid] = current
    return result


def collect_segments(
    input_path: str,
    *,
    chapters: Any = None,
    direction: str = "auto",
    engine: str | None = None,
    source_lang: str = "English",
    target_lang: str = "Italian",
) -> list[dict[str, Any]]:
    """The segments a run would translate, without translating anything.

    Returns ``[{"page", "anchor", "text", "ignored"}]`` in engine order (TOC
    titles first, page ``"toc.ncx"``). It prepares the elements exactly like
    :func:`translate_epub`, so the token/price estimate counts the same text the
    engine will be paid for. Nothing is written and no network call is made.
    """
    translator = get_translator(get_engine_class(engine))
    translator.set_source_lang(source_lang)
    translator.set_target_lang(target_lang)
    book = epub.read_epub(input_path)
    preserve_document_markup(book)
    if chapters:
        selected = resolve_selection(chapters_from_book(book), chapters)
        restrict_book(book, chapter_files(selected))
        isolate_chapters(book, selected)
    pages = _parse_pages(book)
    toc_nodes = _parse_toc(book.toc)
    handler = get_element_handler(
        translator.placeholder, translator.separator,
        direction or get_config().get("target_direction") or "auto")
    handler.set_translation_lang(translator.get_iso639_target_code(target_lang))
    elements: list = []
    elements.extend(get_toc_elements(toc_nodes, []))
    elements.extend(get_page_elements(pages))
    originals = handler.prepare_original(elements)
    anchors = _segment_anchors(book, pages, elements)
    return [{
        "page": entry[6] or "",
        "anchor": anchors.get(entry[0], ""),
        "text": entry[3],
        "ignored": bool(entry[4]),
    } for entry in originals]


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
    style_prompt: str | None = None,
    genre: str = "",
    on_progress: Callable[[float, str], None] | None = None,
    on_log: Callable[[str, bool], None] | None = None,
    on_paragraph: Callable[[Any], None] | None = None,
    on_plan: Callable[[dict[str, int]], None] | None = None,
    on_resume: Callable[[int, int], None] | None = None,
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
    _apply_translation_defaults(translator)
    style_prompt = (style_prompt or "").strip()
    if style_prompt and hasattr(translator, "prompt"):
        # *Append* the genre/style addendum: the engine's own prompt already
        # enforces completeness and placeholder handling, and replacing it would
        # throw those guarantees away.
        translator.prompt = f"{translator.prompt} {style_prompt}".strip()

    config = get_config()
    direction = direction or config.get("target_direction") or "auto"

    try:
        book = epub.read_epub(input_path)
    except Exception as exc:
        # A real case: a "slim" re-pack whose package document still lists files
        # it no longer ships. Say what is wrong instead of surfacing a KeyError.
        raise TranslationFailed(
            "Impossibile leggere il file EPUB: "
            f"{type(exc).__name__}: {exc}\n"
            "Il file sembra incompleto o malformato (il suo package document "
            "elenca risorse che non sono nell'archivio).") from exc
    preserve_document_markup(book)
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

    # Keep the run selection so "resume" can offer the same chapters again.
    cache.set_info("chapters",
                   json.dumps(chapters, default=str) if chapters else "")
    # Never mix translations produced by another model / source language / style
    # prompt: keep the rows but drop their translations (the resume table keeps
    # them per scope, so switching back restores that scope's work).
    model = str(getattr(translator, "model", "") or "")
    style_hash = _style_hash(style_prompt)
    previous_model = cache.get_info("model") or ""
    previous_source = cache.get_info("source_lang") or ""
    previous_style = cache.get_info("run_style_hash") or ""
    if ((previous_model and (previous_model != model
                             or previous_source != (source_lang or "")))
            or previous_style != style_hash):
        cache.cursor.execute(
            "UPDATE cache SET translation=NULL, engine_name=NULL, "
            "target_lang=NULL")
        cache.connection.commit()
    cache.set_info("model", model)
    cache.set_info("source_lang", source_lang or "")

    # From here on, an abrupt death of the process leaves ``running`` behind: the
    # app can then tell the user that this translation was interrupted and offer
    # to continue it (``interrupted_runs``).
    _mark_running(cache, input_path, output_path, config,
                  style_prompt=style_prompt, genre=genre,
                  concurrency=int(getattr(translator, "concurrency_limit", 0) or 0))

    cache.save(originals)
    _ensure_cache_rows(cache, originals)
    _ensure_resume_table(cache)
    resume_key = _resume_key(translator, source_lang, target_lang, style_hash)
    _seed_resume_translations(cache, originals, resume_key)
    paragraphs = cache.all_paragraphs()
    # How many calls this run will really make (used by the estimate's latency
    # calibration): everything already translated is served from the cache.
    engine_calls = sum(1 for paragraph in paragraphs if not paragraph.translation)
    if on_resume is not None:
        on_resume(*_cache_progress(cache))

    def _log(text: str, error: bool = False) -> None:
        if on_log is not None:
            on_log(text, error)
        else:
            log.info(text)

    translation = get_translation(translator, _log)
    translation.set_callback(
        lambda paragraph: _persist_paragraph(
            cache, paragraph, on_paragraph, resume_key))
    if on_progress is not None:
        translation.set_progress(
            lambda fraction, message: on_progress(fraction, message))
    if should_cancel is not None:
        translation.set_cancel_request(should_cancel)

    # The engine marks a paragraph served from the cache inside
    # ``translate_paragraph()``. The online-batching path never calls it, so a warm
    # cache would look freshly translated there (the "already in cache" notice and
    # the per-chapter accounting would be wrong). Mark them here for both paths:
    # the engine decides what to skip on ``translation``, not on this flag.
    if not translation.fresh:
        for paragraph in paragraphs:
            if paragraph.translation:
                paragraph.is_cache = True

    try:
        translation.handle(paragraphs)
    except TranslationCanceled:
        # The engine itself aborts on the cancel request: same meaning as the
        # explicit check below, so the run must not be offered as "interrupted".
        _mark_status(cache, _RUN_CANCELLED)
        raise
    # A cancelled run returns normally from the engine's handler (it drains the
    # queue), so check explicitly: writing a half-translated EPUB and reporting
    # success is worse than stopping here.
    if should_cancel is not None and should_cancel():
        _mark_status(cache, _RUN_CANCELLED)
        raise TranslationCanceled("Translation canceled.")
    handler.add_translations(paragraphs)

    for page in pages:
        page.write_back()
    for node in toc_nodes:
        node.write_back()

    _ensure_toc_uids(book.toc)
    # Write next to the target and rename atomically: a power cut during the
    # final write must not leave a truncated EPUB in place of a good one. The
    # cache is untouched either way, so a re-run rewrites it without asking the
    # engine for anything already translated.
    part_path = f"{output_path}.part"
    try:
        epub.write_epub(part_path, book)
        os.replace(part_path, output_path)
    finally:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:  # pragma: no cover - best effort
                pass
    # Only now is the run really over: until this marker changes, opening the
    # book offers to continue it.
    _mark_finished(
        cache, engine_calls=engine_calls, segments=len(paragraphs),
        concurrency=int(getattr(translator, "concurrency_limit", 0) or 0),
        batching=bool(config.get("online_batching"))
        and hasattr(translator, "translate_batch"))
    cache.done()
    return output_path


def _persist_paragraph(cache, paragraph, on_paragraph,
                       resume_key=None) -> None:
    if resume_key is not None:
        # Written first; ``update_paragraph`` commits both statements at once.
        _remember_translation(cache, paragraph, resume_key)
    cache.update_paragraph(paragraph)
    if on_paragraph is not None:
        on_paragraph(paragraph)


def _ensure_cache_rows(cache, originals) -> None:
    """Align the persistent cache with the segments of *this* run.

    The verbatim ``TranslationCache`` writes rows with ``INSERT ... ON CONFLICT
    DO NOTHING`` keyed on ``id``, and ``id`` is the element's **position**: it is
    only stable while the element list does not change. A run whose chapter
    selection differs from the previous one (a chapter added, removed or
    re-selected) shifts every following index, so an id-based match crosses
    segments -- the elements that landed on an already-used id were silently left
    untranslated, while rows of a book state that no longer exists stayed in the
    queue (wasted engine calls). ``TranslationCache.save()`` has the same flaw in
    its "fresh" path, and it also skips every insert when a >50 kB cache exists.

    ``original`` (the segment text) is the only stable identity, so the table is
    rebuilt in this run's order, carrying the known translations over by content.
    """
    rows = cache.all()
    # Cache row layout: id, md5, raw, original, ignored, attributes, page,
    # translation, engine_name, target_lang.
    expected = {entry[0]: entry[3] for entry in originals
                if not (entry[4] if len(entry) > 4 else False)}
    actual = {row[0]: row[3] for row in rows}
    if actual == expected:
        return                          # the table already matches this run
    translation_by_content = {row[3]: row[7] for row in rows if row[7]}
    if rows:
        cache.cursor.execute('DELETE FROM cache')
    for entry in originals:
        oid, md5, raw, content = entry[0], entry[1], entry[2], entry[3]
        ignored = entry[4] if len(entry) > 4 else False
        attributes = entry[5] if len(entry) > 5 else None
        page = entry[6] if len(entry) > 6 else None
        cache.cursor.execute(
            'INSERT OR REPLACE INTO cache VALUES ('
            '?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)',
            (oid, md5, raw, content, ignored, attributes, page,
             translation_by_content.get(content), None, None))
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
    _apply_translation_defaults(translator)

    book = epub.read_epub(input_path)
    preserve_document_markup(book)
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
