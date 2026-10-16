"""Backend-agnostic reader harness.

Runs the same scenario against the **lite** (`QTextBrowser`) and **full**
(`QWebEngineView` + foliate-js) readers and returns a structured report. Used by
``tests/test_reader_backends.py`` and by the standalone
``tools/reader_harness.py`` (handy for validating the full backend on a desktop).

The full backend needs a working WebEngine (GPU/display). When the page does not
come up (e.g. a headless CI without the Chromium flags), the report marks
``ready = False`` instead of hanging.
"""
from __future__ import annotations

import os
import threading
import time
import zipfile
from dataclasses import dataclass, field

__all__ = ["ReaderReport", "run_reader_harness", "webengine_available",
           "FeatureReport", "run_feature_harness",
           "ScenarioReport", "run_translation_scenario", "run_scenario_matrix"]

#: The fake engine wraps every translated segment as ``IT<...>``; serialized in
#: XML that becomes ``IT&lt;``, which is what the output documents contain.
TRANSLATION_MARKER = "IT&lt;"
#: Same marker *before* XML serialization (the in-memory TOC titles).
TOC_MARKER = "IT<"


def webengine_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("PyQt6.QtWebEngineWidgets") is not None


@dataclass
class ReaderReport:
    mode: str
    available: bool = False
    backend: str | None = None
    opened: bool = False
    ready: bool = False
    navigated: bool = False
    theme_ok: bool = False
    zoom_ok: bool = False
    find_ok: bool = False
    formats: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # ``navigated`` needs a rendered paginator (GPU); in headless/offscreen it
        # stays False even when the book opened fine, so it is informational.
        return self.available and self.opened

    def summary(self) -> str:
        return (f"mode={self.mode} backend={self.backend} available={self.available} "
                f"opened={self.opened} ready={self.ready} navigated={self.navigated} "
                f"theme={self.theme_ok} zoom={self.zoom_ok} find={self.find_ok} "
                f"formats={','.join(self.formats)}"
                + (f" notes={self.notes}" if self.notes else ""))


def _app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["noesis-harness"])


def run_reader_harness(mode: str, book_path: str, *, wait: float = 20.0,
                       app=None) -> ReaderReport:
    report = ReaderReport(mode=mode)
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--no-sandbox --disable-gpu --disable-software-rasterizer")

    try:
        from noesis_ebook_translator.reader import create_backend, prepare_full
        if mode == "full":
            prepare_full()
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"prepare_full: {exc}")

    app = app or _app()
    try:
        backend = create_backend(mode)
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"create_backend: {type(exc).__name__}: {exc}")
        return report

    report.available = True
    report.backend = type(backend).__name__
    report.formats = sorted(getattr(backend, "supported_extensions", []) or [])

    from noesis_ebook_translator.reader.document import EpubDocument
    doc = EpubDocument(book_path)
    backend.open_document(doc)

    # Wait until the view is usable.
    deadline = time.time() + wait
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
        if backend.current_href():
            report.opened = True
            break
        if getattr(backend, "_ready", False):
            report.ready = True
            report.opened = True
            break
    report.ready = report.ready or report.opened

    first = backend.current_href()
    try:
        backend.set_theme("dark")
        report.theme_ok = True
        backend.set_zoom(1)
        report.zoom_ok = True
        report.find_ok = bool(backend.find("the"))
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"controls: {exc}")

    backend.next_chapter()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    current = backend.current_href()
    if current and first:
        report.navigated = current != first
    elif current and not first:
        report.navigated = True
    if not report.navigated and mode == "full" and not report.ready:
        report.notes.append("full backend not ready (headless/GPU?)")

    # Hand the WebEngine page back before the process exits (otherwise Chromium
    # warns that the profile was released with the page still alive).
    teardown = getattr(backend, "shutdown", None)
    if callable(teardown):
        try:
            teardown()
            app.processEvents()
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"shutdown: {exc}")

    return report


@dataclass
class FeatureReport:
    """Result of exercising the new GUI features on a real book."""

    mode: str
    available: bool = False
    window_built: bool = False
    tabs: int = 0
    categories: int = 0
    figures: int = 0
    tables: int = 0
    texts: int = 0
    chapters: int = 0
    theme_ok: bool = False
    library_ok: bool = False
    settings_ok: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.available and self.window_built and self.figures >= 1
                and self.tables >= 1 and self.chapters >= 1 and self.theme_ok)

    def summary(self) -> str:
        return (f"mode={self.mode} available={self.available} "
                f"built={self.window_built} tabs={self.tabs} cats={self.categories} "
                f"figures={self.figures} tables={self.tables} texts={self.texts} "
                f"chapters={self.chapters} theme={self.theme_ok} "
                f"library={self.library_ok} settings={self.settings_ok}"
                + (f" notes={self.notes}" if self.notes else ""))


def run_feature_harness(book_path: str, *, app=None) -> FeatureReport:
    """Exercise the new GUI features (tabs, panels, theme, library, settings)."""
    report = FeatureReport(mode="gui")
    try:
        from PyQt6.QtWidgets import QApplication
        app = app or (QApplication.instance() or QApplication(["noesis-features"]))
    except Exception as exc:  # noqa: BLE001 - optional dependency
        report.notes.append(f"qt unavailable: {exc}")
        return report

    from noesis_ebook_translator import appconfig
    appconfig.ensure_defaults()
    import main

    report.available = True
    window = main.MainWindow()
    try:
        report.window_built = True
        report.tabs = window.tabs.count()
        report.categories = window.workflow.sections()
        window._apply_source(book_path)
        window.figures.load_current()
        window.tables.load_current()
        window.texts.load_current()
        window.chapters.load_current()
        report.figures = window.figures.list.count()
        report.tables = window.tables.cmb.count()
        report.texts = window.texts.list.count()
        report.chapters = window.chapters.list.count()
        # theme switching must not raise and must update the stylesheet
        window._set_theme("dark")
        report.theme_ok = bool(app.styleSheet())
        report.library_ok = len(window.reader.session.recent()) >= 1
        # settings dialog can be built and read
        from noesis_ebook_translator.ui import SettingsDialog
        dialog = SettingsDialog(window)
        report.settings_ok = bool(dialog.values().get("ui_theme"))
        dialog.close()
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"{type(exc).__name__}: {exc}")
    finally:
        window.close()
        app.processEvents()
    return report


# ---------------------------------------------------------------------------
#  Translation scenario harness
#
#  ``run_feature_harness`` above is a *smoke* check ("did it open?"). This one
#  asserts *state invariants* instead: every segment the engine planned must be
#  processed, no chapter may be left half-done, the output must carry the
#  translation in every document and in every TOC level. It runs each job in a
#  watchdog thread so a stall becomes a red test instead of a frozen suite.
# ---------------------------------------------------------------------------
@dataclass
class ScenarioReport:
    """Outcome of one end-to-end translation condition."""

    name: str
    seconds: float = 0.0
    stalled: bool = False
    cancelled: bool = False
    planned_total: int = 0
    processed_total: int = 0
    cached_segments: int = 0
    #: page -> segments the engine planned but never handed back (must be empty).
    short_pages: dict[str, int] = field(default_factory=dict)
    #: plan pages that did not reach their total (same info, as a list).
    pending_chapters: list[str] = field(default_factory=list)
    #: plan pages whose output document is missing or has no translation.
    output_missing: list[str] = field(default_factory=list)
    #: TOC titles of any level left in the source language.
    toc_missing: list[str] = field(default_factory=list)
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (not self.stalled and not self.cancelled and self.error is None
                and self.planned_total == self.processed_total
                and not self.pending_chapters
                and not self.output_missing and not self.toc_missing)

    def summary(self) -> str:
        state = "OK" if self.ok else "FAIL"
        extra = ""
        if self.stalled:
            extra += " STALLED"
        if self.cancelled:
            extra += " cancelled"
        if self.error:
            extra += f" error={self.error}"
        if self.pending_chapters:
            extra += f" pending={self.pending_chapters}"
        if self.output_missing:
            extra += f" output_missing={self.output_missing}"
        if self.toc_missing:
            extra += f" toc_missing={self.toc_missing}"
        if self.notes:
            extra += f" notes={self.notes}"
        return (f"{state:4} {self.name:26} planned={self.planned_total:<4} "
                f"processed={self.processed_total:<4} cached={self.cached_segments:<4} "
                f"({self.seconds:>5.2f}s){extra}")


def _cache_db_dir() -> str:
    """Where the verbatim engine keeps its persistent per-book cache."""
    import tempfile
    return os.path.join(tempfile.gettempdir(),
                        "com.bookfere.Calibre.EbookTranslator", "cache")


def _existing_cache_dbs() -> set[str]:
    import glob
    return set(glob.glob(os.path.join(_cache_db_dir(), "*.db")))


def _inflate_translation_cache(db_paths) -> None:
    """Push the given cache DBs past the 50 kB threshold.

    ``TranslationCache`` assumes a >50 kB cache means "the previous run was
    complete"; that is what used to hide a chapter translated for the first time.
    """
    import sqlite3

    for db in db_paths:
        try:
            if os.path.getsize(db) > 50000:
                continue
            connection = sqlite3.connect(db)
            connection.execute(
                "INSERT OR REPLACE INTO cache (id, md5, raw, original, ignored, "
                "page, translation, engine_name, target_lang) "
                "VALUES (?,?,?,?,0,?,?,?,?)",
                ("padding-row", "padding-md5", "x" * 60000, "padding",
                 "pad.xhtml", "padding", "Fake", "Italian"))
            connection.commit()
            connection.close()
        except Exception:  # noqa: BLE001 - fixture wiring, not the test subject
            continue


def _missing_output(out_path: str, pages, marker: str) -> list[str]:
    if not os.path.isfile(out_path):
        return sorted(pages)
    missing: list[str] = []
    with zipfile.ZipFile(out_path) as archive:
        names = archive.namelist()
        for page in sorted(pages):
            base = os.path.basename(page)
            match = next((n for n in names if os.path.basename(n) == base), None)
            if match is None:
                missing.append(page)
                continue
            text = archive.read(match).decode("utf-8", "replace")
            if marker not in text:
                missing.append(page)
    return missing


def _toc_missing(out_path: str, marker: str) -> list[str]:
    if not os.path.isfile(out_path):
        return ["<output missing>"]
    from ebooklib import epub as epub_mod

    def titles(nodes) -> list[str]:
        found: list[str] = []
        for item in nodes or []:
            if isinstance(item, (tuple, list)):
                if item:
                    title = getattr(item[0], "title", None)
                    if title:
                        found.append(title)
                if len(item) > 1:
                    found.extend(titles(item[1]))
                continue
            title = getattr(item, "title", None)
            if title:
                found.append(title)
        return found

    try:
        written = titles(epub_mod.read_epub(out_path).toc)
    except Exception as exc:  # noqa: BLE001 - a broken TOC is a failure itself
        return [f"<unreadable: {exc}>"]
    return [title for title in written if marker not in title]


def run_translation_scenario(
    name: str,
    source: str,
    *,
    tmpdir: str | None = None,
    chapters=None,
    seed_chapters=None,
    cache_enabled: bool = True,
    inflate_cache: bool = False,
    timeout: float = 120.0,
    check_output: bool = True,
    check_toc: bool = True,
    source_lang: str = "English",
    target_lang: str = "Italian",
    should_cancel=None,
) -> ScenarioReport:
    """Translate ``source`` and check that the job *completed correctly*.

    Conditions are injectable (chapter selection, a pre-existing cache, a cache
    inflated over 50 kB) so one helper covers the whole matrix below.
    """
    from noesis_ebook_translator import book as book_mod
    from tests.fixtures import register_fake_engine

    register_fake_engine()
    tmpdir = tmpdir or os.path.dirname(source)
    out = os.path.join(tmpdir, f"{name}.out.epub")
    settings = {"translation_position": "only", "cache_enabled": cache_enabled}
    report = ScenarioReport(name=name)

    # 1. Seed a cache from an earlier run over a subset of the book.
    dbs_before = _existing_cache_dbs()
    if seed_chapters:
        try:
            book_mod.translate_epub(
                source, os.path.join(tmpdir, f"{name}.seed.epub"),
                engine="Fake", source_lang=source_lang, target_lang=target_lang,
                chapters=seed_chapters, settings=settings)
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"seed: {type(exc).__name__}: {exc}")

    # 2. Optionally make that cache look like a full book's cache (>50 kB).
    if inflate_cache:
        # The cache is keyed on the input path, so the DBs that appeared during
        # the seed belong to *this* source and to no other scenario.
        created = _existing_cache_dbs() - dbs_before
        if not created:
            report.notes.append("inflate: no cache DB was created by the seed")
        _inflate_translation_cache(sorted(created))

    planned: dict[str, int] = {}
    processed: dict[str, int] = {}
    counter = {"cached": 0}

    def on_plan(counts) -> None:
        planned.update({k: int(v) for k, v in (counts or {}).items()})

    def on_paragraph(paragraph) -> None:
        if paragraph is None or getattr(paragraph, "ignored", False):
            return
        page = getattr(paragraph, "page", None)
        if not page or page == "toc.ncx":
            return
        processed[page] = processed.get(page, 0) + 1
        if getattr(paragraph, "is_cache", False):
            counter["cached"] += 1

    failure: dict[str, BaseException] = {}

    def job() -> None:
        try:
            book_mod.translate_epub(
                source, out, engine="Fake", source_lang=source_lang,
                target_lang=target_lang, chapters=chapters, settings=settings,
                on_plan=on_plan, on_paragraph=on_paragraph,
                should_cancel=should_cancel)
        except BaseException as exc:  # noqa: BLE001 - reported, not raised
            failure["exc"] = exc

    started = time.time()
    worker = threading.Thread(target=job, name=f"scenario-{name}", daemon=True)
    worker.start()
    worker.join(timeout)
    report.seconds = round(time.time() - started, 2)

    if worker.is_alive():
        report.stalled = True
        report.notes.append(f"no completion within {timeout}s")
        return report

    exc = failure.get("exc")
    if exc is not None:
        from noesis_ebook_translator.lib.exception import TranslationCanceled
        report.cancelled = isinstance(exc, TranslationCanceled)
        report.error = f"{type(exc).__name__}: {exc}"
        return report

    report.planned_total = sum(planned.values())
    report.processed_total = sum(processed.values())
    report.cached_segments = counter["cached"]
    report.short_pages = {page: planned[page] - processed.get(page, 0)
                          for page in planned if processed.get(page, 0) < planned[page]}
    report.pending_chapters = sorted(report.short_pages)
    if check_output:
        report.output_missing = _missing_output(out, planned, TRANSLATION_MARKER)
    if check_toc:
        report.toc_missing = _toc_missing(out, TOC_MARKER)
    return report


def run_scenario_matrix(tmpdir: str, *, timeout: float = 120.0) -> dict[str, ScenarioReport]:
    """Run the standard condition matrix and return ``{name: report}``.

    Each condition gets its **own source file**: the engine keys its cache on
    the input path, so sharing a file would leak one condition's cache into the
    next.
    """
    from tests.fixtures import (build_anchored_epub, build_rich_epub,
                                build_sample_epub)
    from tests.fixtures import register_fake_engine

    register_fake_engine()

    def sample(tag: str) -> str:
        return build_sample_epub(os.path.join(tmpdir, f"{tag}.epub"))

    def rich(tag: str) -> str:
        return build_rich_epub(os.path.join(tmpdir, f"{tag}.epub"))

    def anchored(tag: str) -> str:
        return build_anchored_epub(os.path.join(tmpdir, f"{tag}.epub"))

    conditions: dict[str, dict] = {
        # No cache at all: the plain path.
        "whole_book": dict(source=sample("whole"), cache_enabled=False),
        # Whole book, all chapters, warm re-run (everything from the cache).
        "all_cached": dict(source=rich("allcached"),
                           seed_chapters=["c1.xhtml", "c2.xhtml", "c3.xhtml"],
                           chapters=["c1.xhtml", "c2.xhtml", "c3.xhtml"]),
        # A selection: c1/c2 cached, c3 translated for the first time.
        "partial_cache": dict(source=rich("partial"),
                              seed_chapters=["c1.xhtml", "c2.xhtml"],
                              chapters=["c1.xhtml", "c2.xhtml", "c3.xhtml"]),
        # The regression: the same, but the cache is >50 kB (looks "complete").
        "large_cache_new_chapter": dict(
            source=rich("bigcache"),
            seed_chapters=["c1.xhtml", "c2.xhtml"],
            chapters=["c1.xhtml", "c2.xhtml", "c3.xhtml"],
            inflate_cache=True),
        # The worst manifestation: the chapter translated for the first time sits
        # *before* the cached ones, so every following index shifts by one. A
        # positional (id-based) cache match left the whole first chapter in the
        # source language.
        "chapter_added_before_cache": dict(
            source=rich("before"),
            seed_chapters=["c2.xhtml", "c3.xhtml"],
            chapters=["c1.xhtml", "c2.xhtml", "c3.xhtml"]),
        # The selection shrinks: previously cached chapters must leave the queue
        # (no wasted engine calls, no segments beyond the plan).
        "selection_shrinks": dict(
            source=rich("shrink"),
            seed_chapters=["c1.xhtml", "c2.xhtml", "c3.xhtml"],
            chapters=["c1.xhtml", "c2.xhtml"]),
        # One chapter only, the rest of the TOC stays out of the run.
        "single_chapter": dict(source=rich("single"), chapters=["c2.xhtml"]),
        # Three TOC entries that are anchors inside a single XHTML document.
        "anchored_sections": dict(source=anchored("anchored")),
        # A two-level TOC: sub-level titles must be translated too.
        "nested_toc": dict(source=rich("nested")),
    }

    reports: dict[str, ScenarioReport] = {}
    for name, kwargs in conditions.items():
        reports[name] = run_translation_scenario(
            name, tmpdir=tmpdir, timeout=timeout, **kwargs)
    return reports
