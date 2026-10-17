#!/usr/bin/env python3
"""Noesis Ebook Translator — desktop GUI (PyQt6).

The ribbon is a custom two-row workflow bar (:mod:`noesis_ebook_translator.ui.workflow_bar`).
All the heavy lifting lives in :mod:`noesis_ebook_translator.book`.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
    QVBoxLayout, QWidget)

from noesis_ebook_translator import APP_NAME, __version__, appconfig, book, theme
from noesis_ebook_translator import exporter as exporter_mod
from noesis_ebook_translator.i18n import T, get_language, set_language
from noesis_ebook_translator.progress_model import (
    DeltaBatch, ProgressModel, TransferThrottle, build_units)
from noesis_ebook_translator.reader import ReaderWidget, resolve_backend
from noesis_ebook_translator.reader.panels import (
    ChaptersWidget, FiguresWidget, LibraryWidget, PreviewWidget, TablesWidget,
    TextsWidget)
from noesis_ebook_translator.ui.workflow_bar import build_workflow
from noesis_ebook_translator.engines.languages import google as GOOGLE_LANGUAGES
from noesis_ebook_translator.chapters import ChapterError
from noesis_ebook_translator.lib.exception import TranslationCanceled


def _resource(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


class TranslationWorker(QThread):
    """Runs :func:`book.translate_epub` off the UI thread.

    Progress reaches the GUI **coalesced**: the engine reports one callback per
    segment, but the worker accumulates them into small deltas and emits at most
    ``1 / FLUSH_INTERVAL`` times per second, and never while the previous delta is
    still pending in the GUI (:class:`TransferThrottle` single-flight). A
    20k-segment book therefore costs ~20 UI updates per second instead of 20k
    queued events, and no ``Paragraph`` objects are kept alive in the queue.
    """

    FLUSH_INTERVAL = 0.05

    plan = pyqtSignal(object)
    delta = pyqtSignal(object)
    logged = pyqtSignal(str, bool)
    finished_ok = pyqtSignal(str)
    cancelled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, input_path, output_path, engine, source, target, settings,
                 chapters=None):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.engine = engine
        self.source = source
        self.target = target
        self.settings = settings
        self.chapters = chapters
        self._cancel = threading.Event()
        self._batch = DeltaBatch()
        self._throttle = TransferThrottle(self.FLUSH_INTERVAL)

    def cancel(self) -> None:
        self._cancel.set()

    # -- worker -> GUI ----------------------------------------------------
    def release_flush(self) -> None:
        """Called by the GUI thread once a delta has been applied."""
        self._throttle.release()

    def _emit_plan(self, counts) -> None:
        self.plan.emit(dict(counts or {}))

    def _on_paragraph(self, paragraph) -> None:
        self._batch.add_paragraph(paragraph)
        self._flush()

    def _on_log(self, text: str, error: bool = False) -> None:
        if error:
            # Errors are rare and worth showing immediately.
            self.logged.emit(text, True)
        else:
            self._batch.add_log(text)

    def _flush(self, force: bool = False) -> None:
        if not force and not self._throttle.due():
            return
        payload = self._batch.payload()
        if payload is None and not force:
            return
        self._batch.reset()
        self._throttle.emitted()
        self.delta.emit(payload or {"counts": {}, "errors": {}, "cached": 0,
                                    "last": None, "log": []})

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            path = book.translate_epub(
                self.input_path,
                self.output_path,
                engine=self.engine,
                source_lang=self.source,
                target_lang=self.target,
                chapters=self.chapters,
                settings=self.settings,
                on_log=self._on_log,
                on_paragraph=self._on_paragraph,
                on_plan=self._emit_plan,
                should_cancel=self._cancel.is_set,
            )
            self._flush(force=True)
            self.finished_ok.emit(path)
        except TranslationCanceled:
            # A cancelled run is not a failure: report it as such, and never as
            # a "translated" book (no output was written).
            self._flush(force=True)
            self.cancelled.emit()
        except Exception:  # noqa: BLE001 - surfaced to the UI
            self._flush(force=True)
            self.failed.emit(traceback.format_exc())


class SplitWorker(QThread):
    """Splits the translated EPUB into one file per chapter, off the UI thread.

    ``segment.split_epub`` reads and writes every chapter, which used to block the
    window for seconds; running it in a thread keeps the view responsive (and lets
    the chapters show their "exported" state only when it is really done).
    """

    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, path: str, folder: str, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.folder = folder

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            from noesis_ebook_translator import segment
            written = segment.split_epub(self.path, self.folder, mode="flat")
            self.done.emit(list(written))
        except Exception:  # noqa: BLE001 - surfaced to the UI
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(T("app.title"))
        icon_path = _resource("assets", "noesis-ebook-translator.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._settings = appconfig.load_settings()
        self._reduce_motion = bool(self._settings.get("reduce_motion", False))
        self.worker: TranslationWorker | None = None
        self._input_path: str | None = None
        self._output_path: str | None = None
        self._assets_edition = "original"
        self._initializing = False
        self._ribbon_index = 0
        self._pending_split = None
        self._split_worker = None
        self._split_ok = False
        self._split_message = ""
        self._summary_message = ""
        self._chapters_total = 0
        self._build_workflow()
        self._build_body()
        self._load_settings()
        self._apply_minimum_cap()
        # Make the shown view match the selected workflow section at startup
        # (the QTabBar emits its first currentChanged before we connect).
        self._on_section_changed(self.workflow.currentSection())

    # ------------------------------------------------------------------ UI
    def _build_workflow(self) -> None:
        self.workflow = build_workflow(self)
        self.workflow.sectionChanged.connect(self._on_section_changed)

    def _apply_minimum_cap(self) -> None:
        """Never demand more window than the screen can give.

        The toolbar of some sections is wider than a laptop screen; without an
        explicit (bounded) minimum the layout grows the window past the screen
        edge as soon as that tab is selected.
        """
        hint = self.minimumSizeHint()
        width, height = hint.width(), hint.height()
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(640, available.width() - 40))
            height = min(height, max(420, available.height() - 40))
        else:  # pragma: no cover - no screen (never happens with Qt running)
            width, height = min(width, 720), min(height, 480)
        self.setMinimumSize(width, height)

    def _startup_geometry(self) -> None:
        """Start maximised (F11 toggles real full screen later)."""
        self._apply_minimum_cap()
        try:
            self.showMaximized()
        except Exception:  # noqa: BLE001 - fall back to a plain show()
            self.show()

    def toggle_fullscreen(self) -> None:
        """F11: real full screen (no window frame), toggling back to normal."""
        if self.isFullScreen():
            self.showNormal()
            self.showMaximized()
        else:
            self.showFullScreen()

    def _build_body(self) -> None:
        from noesis_ebook_translator.ui.translate_view import TranslateView

        central = TranslateView(reduce_motion=self._reduce_motion)
        self.translate_view = central
        self._translate_tab = central
        # The four bands own these widgets; the window keeps referring to them.
        self.progress = central.progress
        self.book_label = central.book_label
        self.status = central.status
        self.log = central.log
        self.chapter_bar = central.track.bar_current
        self.chapter_label = central.track.lbl_subtitle
        self._chapter_names: list[str] = []
        central.layoutChanged.connect(self._save_view_state)

        self.reader = ReaderWidget(session=None, backend_mode=self._reader_mode())
        self.reader.statusMessage.connect(self.status.set_base_text)
        self.reader.parallelChanged.connect(self._on_parallel_changed)
        self.reader.flowChanged.connect(
            lambda flow: appconfig.save_settings({"reader_flow": flow}))
        self.reader.spreadChanged.connect(
            lambda on: appconfig.save_settings({"reader_spread": bool(on)}))
        self.library = LibraryWidget(self.reader.session)
        self.library.changed.connect(self._sync_library_buttons)
        self.chapters = ChaptersWidget()
        self.chapters.translateRequested.connect(self._translate_chapters)
        self.chapters.exportRequested.connect(self._export_chapters)
        self.figures = FiguresWidget()
        self.tables = TablesWidget()
        self.texts = TextsWidget()
        self.preview = PreviewWidget(self._preview_options)
        self.library.openRequested.connect(self._apply_source)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()  # navigation is driven by the ribbon
        self.tabs.addTab(central, T("tab.translate"))
        self.tabs.addTab(self.reader, T("tab.reader"))
        self.tabs.addTab(self.library, T("tab.library"))
        self.tabs.addTab(self.chapters, T("tab.chapters"))
        self.tabs.addTab(self.figures, T("tab.figures"))
        self.tabs.addTab(self.tables, T("tab.tables"))
        self.tabs.addTab(self.texts, T("assets.texts"))
        self.tabs.addTab(self.preview, T("tab.preview"))

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self.workflow)
        container_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(container)
        self.resize(1180, 780)

        # F11 toggles real full screen (no frame); the app starts maximised.
        self._fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._fullscreen_shortcut.activated.connect(self.toggle_fullscreen)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Tear the reader down before the WebEngine profile is released."""
        try:
            self.reader.shutdown()
        except Exception:  # noqa: BLE001 - closing must never fail
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------- helpers
    def _engine_names(self) -> list[str]:
        return appconfig.engine_names()

    def _reload_engines(self) -> None:
        """Rebuild the engine combo (providers enabled in Settings appear here)."""
        current = self.cmb_engine.currentText()
        self.cmb_engine.blockSignals(True)
        self.cmb_engine.clear()
        self.cmb_engine.addItems(appconfig.engine_names())
        index = self.cmb_engine.findText(current)
        if index >= 0:
            self.cmb_engine.setCurrentIndex(index)
        self.cmb_engine.blockSignals(False)
        self._on_engine_changed(self.cmb_engine.currentText())

    # -------------------------------------------------- translate view state
    def _choice_rows(self, cfg: dict | None = None) -> list[tuple[str, str]]:
        """Rows for band 1: what the wizard collected (never the API key)."""
        cfg = cfg or {}
        engine = cfg.get("engine") or self.cmb_engine.currentText()
        source = cfg.get("source") or self.cmb_source.currentText()
        target = cfg.get("target") or self.cmb_target.currentText()
        rows = [
            (T("panel.engine"), engine),
            (T("label.model"), cfg.get("model") or "—"),
            (T("label.source"), source),
            (T("label.target"), target),
            (T("label.input"), self._input_path or "—"),
            (T("label.output"), self._output_path or "—"),
        ]
        chapters = cfg.get("chapters")
        if chapters:
            label = T("translate.chapters_count").format(
                selected=self._selected_document_count(chapters),
                total=self._chapters_total or "?")
            rows.append((T("tab.chapters"), label))
        flags = []
        if cfg.get("bilingual"):
            flags.append(T("label.bilingual"))
        if cfg.get("cache", True):
            flags.append(T("label.cache"))
        if cfg.get("batching"):
            flags.append(T("label.batch"))
        if cfg.get("sequential", True):
            flags.append(T("label.sequential"))
        if flags:
            rows.append((T("panel.options"), " · ".join(flags)))
        return rows

    def _refresh_choices(self, cfg: dict | None = None) -> None:
        self.translate_view.set_choices(self._choice_rows(cfg))

    def _refresh_chapters_total(self) -> None:
        try:
            # The recap counts *documents*: two TOC entries that share one XHTML
            # file are one translation unit for the engine.
            units = build_units(self._input_path)
            self._chapters_total = len({u.file for u in units if u.file})
        except Exception:  # noqa: BLE001 - best effort
            self._chapters_total = 0

    def _show_toc(self, path: str | None) -> None:
        """Band 2 shows the book's whole TOC before any translation starts.

        Called as soon as a book is opened, so the trail is already there (in
        reading order, hierarchy visible, no numbers yet) instead of being filled
        in later -- or worse, left over from the previous book. When the TOC
        cannot be read at all, the reason is shown in the band.
        """
        model = None
        error = None
        if path:
            try:
                model = ProgressModel(build_units(path))
            except ChapterError as exc:
                error = str(exc)
            except Exception:  # noqa: BLE001 - a broken TOC must not break the UI
                model = None
        self.translate_view.set_model(model, toc_error=error)
        if error:
            self.log.appendPlainText(error)

    @staticmethod
    def _book_label(path: str) -> str:
        """Title from the EPUB metadata, falling back to the file name."""
        try:
            from noesis_ebook_translator.chapters import book_meta
            title = (book_meta(path) or {}).get("title") or ""
            if title.strip():
                return title.strip()
        except Exception:  # noqa: BLE001 - best effort
            pass
        return os.path.splitext(os.path.basename(path))[0]

    def _save_view_state(self) -> None:
        if getattr(self, "_initializing", False):
            return
        try:
            appconfig.save_settings(
                {"translate_view": self.translate_view.state()})
        except Exception:  # noqa: BLE001 - persistence is best effort
            pass

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _google_languages():
        return GOOGLE_LANGUAGES

    def _reader_mode(self) -> str:
        return resolve_backend(self._settings.get("reader_backend", "auto"))

    def _preview_options(self) -> dict:
        return {
            "engine": self.cmb_engine.currentText(),
            "source": self.cmb_source.currentText(),
            "target": self.cmb_target.currentText(),
            "settings": {
                "translation_position": "only",
                "cache_enabled": self.chk_cache.isChecked(),
                "online_batching": self.chk_batch.isChecked(),
            },
        }

    def _translated_path(self) -> str | None:
        if not self._input_path:
            return None
        entry = self.reader.session.library.get_book(self._input_path)
        return (entry or {}).get("translated_path") or None

    def _assets_source(self) -> str | None:
        if self._assets_edition == "translated":
            return self._translated_path() or self._input_path
        return self._input_path

    def _apply_source(self, path: str) -> None:
        self._input_path = path
        self._output_path = book.default_output_path(path, self.cmb_target.currentText())
        self._refresh_chapters_total()
        self._refresh_choices()
        # Band 2 is populated as soon as the book is open: the whole TOC, in
        # reading order, with the hierarchy and no numbers yet.
        self._show_toc(path)
        self.workflow.set_book(self._book_label(path))
        self.status.set_base_text(T("status.ready"))
        source = self._assets_source()
        for panel in (self.figures, self.tables, self.texts, self.chapters,
                      self.preview):
            panel.set_source(source)
        self.library.add_book(path)
        try:
            self.chapters.load_current()
        except Exception:  # noqa: BLE001 - best effort
            pass
        try:
            self.reader.open_path(path)
            self.tabs.setCurrentWidget(self.reader)
            self._select_category(1)
        except Exception as exc:  # noqa: BLE001 - reader is best effort
            self.log.appendPlainText(f"[reader] {exc}")

    def _status_message(self, text: str, title: str | None = None) -> None:
        QMessageBox.information(self, title or T("app.title"), text)

    # ------------------------------------------------------------ settings
    def _load_settings(self) -> None:
        self._initializing = True
        settings = self._settings
        engine = settings.get("translate_engine") or self.cmb_engine.currentText()
        index = self.cmb_engine.findText(engine)
        if index >= 0:
            self.cmb_engine.setCurrentIndex(index)
        self.cmb_source.setCurrentText(settings.get("ui_source_lang", "English"))
        self.cmb_target.setCurrentText(settings.get("ui_target_lang", "Italian"))
        self.chk_bilingual.setChecked(settings.get("translation_position") == "below")
        self.chk_cache.setChecked(bool(settings.get("cache_enabled", True)))
        self.chk_batch.setChecked(bool(settings.get("online_batching", False)))
        self._reduce_motion = bool(settings.get("reduce_motion", False))
        self.progress.set_reduce_motion(self._reduce_motion)
        self.chapter_bar.set_reduce_motion(self._reduce_motion)
        self.translate_view.set_reduce_motion(self._reduce_motion)
        self.workflow.book_toast.set_reduce_motion(self._reduce_motion)
        self.translate_view.restore_state(settings.get("translate_view"))
        self._apply_view_theme(settings.get("ui_theme", "system"))
        self._sync_library_buttons()
        self._refresh_choices()
        # Reader defaults (theme is separate from the app theme) + quick controls
        reader_themes = ("light", "sepia", "dark")
        rt = settings.get("reader_theme", "light")
        self.cmb_theme_reader.setCurrentIndex(
            reader_themes.index(rt) if rt in reader_themes else 0)
        fonts = ["serif", "sans-serif", "monospace"]
        rf = settings.get("reader_font", "serif")
        self.cmb_font.setCurrentIndex(fonts.index(rf) if rf in fonts else 0)
        line_index = self.cmb_line.findText(str(settings.get("reader_line_height", 1.5)))
        if line_index >= 0:
            self.cmb_line.setCurrentIndex(line_index)
        self.chk_justify.setChecked(bool(settings.get("reader_justify", True)))
        self.chk_hyphenate.setChecked(bool(settings.get("reader_hyphenate", True)))
        self.reader.apply_reading_settings(
            theme=rt, font=rf,
            line=float(settings.get("reader_line_height", 1.5)),
            justify=bool(settings.get("reader_justify", True)),
            hyphenate=bool(settings.get("reader_hyphenate", True)),
            flow=settings.get("reader_flow", "paginated"),
            spread=bool(settings.get("reader_spread", False)))
        for fmt in exporter_mod.supported_exports():
            self.cmb_export_format.addItem(T(f"format.{fmt}"), fmt)
        fmt_index = self.cmb_export_format.findData(settings.get("export_format", "epub"))
        if fmt_index >= 0:
            self.cmb_export_format.setCurrentIndex(fmt_index)
        self.cmb_export_edition.setCurrentIndex(
            1 if settings.get("export_edition") == "translated" else 0)
        self._on_engine_changed(self.cmb_engine.currentText())
        self._update_toc_mode()
        self._initializing = False

    def _on_engine_changed(self, name: str) -> None:
        info = appconfig.engine_info(name)
        self.edt_api_key.setEnabled(info["need_api_key"])
        self.edt_api_key.setPlaceholderText(info["api_key_hint"])
        pref = appconfig.get_engine_preference(name)
        keys = pref.get("api_keys") or []
        self.edt_api_key.setText(keys[0] if keys else "")
        self.cmb_model.clear()
        models = info["models"]
        if models:
            self.cmb_model.addItems(models)
            self.cmb_model.setEnabled(True)
        else:
            self.cmb_model.setEnabled(False)
            self.cmb_model.addItem(pref.get("model", ""))
        if pref.get("model"):
            self.cmb_model.setCurrentText(pref["model"])
        self._update_model_badge(name)

    def _update_model_badge(self, name: str | None = None) -> None:
        """Show the last live model test outcome next to the model combo."""
        label = getattr(self, "lbl_model_test", None)
        if label is None:
            return
        name = name or self.cmb_engine.currentText()
        model = self.cmb_model.currentText().strip()
        status = appconfig.model_test_status(name, model)
        if not status:
            label.setText("")
            label.setToolTip("")
            label.setVisible(False)
            return
        when = time.strftime("%d/%m %H:%M", time.localtime(status.get("at", 0)))
        if status.get("ok"):
            label.setText("\u2713")
            label.setStyleSheet("color: #2e7d32;")
            label.setToolTip(T("model_test.ok_tooltip").format(
                when=when, model=model))
        else:
            label.setText("\u2717")
            label.setStyleSheet("color: #c62828;")
            label.setToolTip(T("model_test.fail_tooltip").format(
                when=when, error=(status.get("error") or "?").strip()))
        label.setVisible(True)

    def _set_theme(self, mode: str) -> None:
        """Apply the *app* theme (the reader theme is separate)."""
        from noesis_ebook_translator.ui import apply_theme
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, mode)
        self._apply_view_theme(mode)
        appconfig.save_settings({"ui_theme": mode})

    def _apply_view_theme(self, mode: str | None = None) -> None:
        """Push the app palette to the painted bands (liquid, chapter list)."""
        try:
            from noesis_ebook_translator.ui.theme_manager import system_is_dark
            app = QApplication.instance()
            mode = mode or self._settings.get("ui_theme", "system")
            self.translate_view.set_theme(mode, system_is_dark(app))
            self.workflow.book_toast.set_theme(mode, system_is_dark(app))
        except Exception:  # noqa: BLE001 - theming is best effort
            pass

    def _set_reader_theme(self, mode: str) -> None:
        self.reader.set_theme(mode)
        appconfig.save_settings({"reader_theme": mode})

    def _set_ui_language(self, lang: str) -> None:
        appconfig.save_settings({"ui_language": lang})
        if lang != get_language():
            self._status_message(T("msg.restart_language"))

    def _set_reduce_motion(self, checked: bool) -> None:
        self._reduce_motion = bool(checked)
        self.progress.set_reduce_motion(self._reduce_motion)
        self.chapter_bar.set_reduce_motion(self._reduce_motion)
        self.translate_view.set_reduce_motion(self._reduce_motion)
        self.workflow.book_toast.set_reduce_motion(self._reduce_motion)
        appconfig.save_settings({"reduce_motion": self._reduce_motion})

    def _set_reader_backend(self, backend: str) -> None:
        appconfig.save_settings({"reader_backend": backend or "auto"})
        self._status_message(T("msg.restart_needed"))

    def _apply_theme_preview(self, mode: str) -> None:
        self._set_theme(mode)

    def _apply_settings_values(self, values: dict) -> None:
        """Apply saved settings to the running app (theme, reader, quick controls)."""
        self._set_theme(values.get("ui_theme", "system"))
        self._set_reduce_motion(bool(values.get("reduce_motion", False)))
        self.reader.apply_reading_settings(
            theme=values.get("reader_theme", "light"),
            font=values.get("reader_font", "serif"),
            line=float(values.get("reader_line_height", 1.5)),
            justify=bool(values.get("reader_justify", True)),
            hyphenate=bool(values.get("reader_hyphenate", True)),
            flow=values.get("reader_flow", "paginated"),
            spread=bool(values.get("reader_spread", False)))
        reader_themes = ("light", "sepia", "dark")
        theme_name = values.get("reader_theme", "light")
        if theme_name in reader_themes:
            self.cmb_theme_reader.setCurrentIndex(reader_themes.index(theme_name))
        fonts = ["serif", "sans-serif", "monospace"]
        font = values.get("reader_font", "serif")
        if font in fonts:
            self.cmb_font.setCurrentIndex(fonts.index(font))
        line_index = self.cmb_line.findText(str(values.get("reader_line_height", 1.5)))
        if line_index >= 0:
            self.cmb_line.setCurrentIndex(line_index)
        self.chk_justify.setChecked(bool(values.get("reader_justify", True)))
        self.chk_hyphenate.setChecked(bool(values.get("reader_hyphenate", True)))
        fmt_index = self.cmb_export_format.findData(values.get("export_format", "epub"))
        if fmt_index >= 0:
            self.cmb_export_format.setCurrentIndex(fmt_index)
        self.cmb_export_edition.setCurrentIndex(
            1 if values.get("export_edition") == "translated" else 0)
        self._reload_engines()

    # --------------------------------------------------------- tab / TOC
    def _on_section_changed(self, index: int) -> None:
        # 0 = Library, 1 = Reader, 2 = Assets, 3 = Translate
        self._ribbon_index = index
        if index == 0:
            self.tabs.setCurrentWidget(self.library)
        elif index == 1:
            self.tabs.setCurrentWidget(self.reader)
        elif index == 2:
            self.tabs.setCurrentWidget(self.figures)
        elif index == 3:
            self.tabs.setCurrentWidget(self._translate_tab)
        self._update_toc_mode()

    def _update_toc_mode(self) -> None:
        mode = "select" if getattr(self, "_ribbon_index", 0) == 3 else "read"
        try:
            self.reader.set_toc_mode(mode)
        except Exception:  # noqa: BLE001 - reader is best effort
            pass

    def _select_category(self, index: int) -> None:
        """Switch the workflow section (which shows the matching view)."""
        try:
            self.workflow.setCurrentSection(index)
        except Exception:  # noqa: BLE001
            self._on_section_changed(index)

    # ------------------------------------------------------------- actions
    def on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, T("action.open"), "", "EPUB (*.epub);;All files (*)")
        if path:
            self._apply_source(path)

    def on_add_book(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, T("action.add_book"), "", "EPUB (*.epub);;All files (*)")
        if path:
            self.library.add_book(path)

    def on_remove_book(self) -> None:
        self.library._remove()

    def on_open_reader(self) -> None:
        self._select_category(1)

    def on_refresh(self) -> None:
        self.library.refresh()
        try:
            self.chapters.refresh()
        except Exception:  # noqa: BLE001
            pass

    def on_compare(self) -> None:
        self._select_category(1)
        self.reader.set_parallel(True)

    def on_parallel_toggled(self, checked: bool) -> None:
        self.reader.set_parallel(bool(checked))

    def _on_parallel_changed(self, on: bool) -> None:
        if hasattr(self, "btn_parallel"):
            self.btn_parallel.blockSignals(True)
            self.btn_parallel.setChecked(bool(on))
            self.btn_parallel.blockSignals(False)

    def on_retranslate(self) -> None:
        self.tabs.setCurrentWidget(self._translate_tab)

    def on_extract_chapters(self) -> None:
        if self._input_path:
            self.chapters.set_source(self._input_path)
            self.chapters.load_current()
        self._select_category(0)
        self.tabs.setCurrentWidget(self.chapters)

    def on_reveal(self) -> None:
        self.on_open_output()

    def on_open_output(self) -> None:
        if not self._output_path:
            return
        folder = os.path.dirname(self._output_path)
        from noesis_ebook_translator.lib.utils import open_path
        open_path(folder)

    def on_stats(self) -> None:
        library = self.reader.session.library
        books = library.books()
        translated = sum(1 for b in books if b.get("translated_path"))
        self._status_message(
            f"{T('panel.books')}: {len(books)}\n"
            f"{T('library.translated')}: {translated}")

    def on_swap_languages(self) -> None:
        source, target = self.cmb_source.currentText(), self.cmb_target.currentText()
        if source and source != "Auto detect":
            self.cmb_target.setCurrentText(source)
        self.cmb_source.setCurrentText(target)

    def on_toggle_toc(self) -> None:
        self.reader.toc.setVisible(not self.reader.toc.isVisible())

    def on_find(self) -> None:
        self.edt_find.setFocus()

    def on_find_run(self) -> None:
        self.reader.find_text(self.edt_find.text().strip(), False)

    def on_find_next(self) -> None:
        self.reader.find_text(self.edt_find.text().strip(), False)

    def on_font_changed(self, _index: int) -> None:
        families = ["serif", "sans-serif", "monospace"]
        family = families[max(0, min(2, self.cmb_font.currentIndex()))]
        self.reader.set_font(family)
        appconfig.save_settings({"reader_font": family})

    def on_line_height_changed(self, _index: int) -> None:
        try:
            value = float(self.cmb_line.currentText())
        except ValueError:
            value = 1.5
        self.reader.set_line_height(value)
        appconfig.save_settings({"reader_line_height": value})

    def on_justify_toggled(self, checked: bool) -> None:
        self.reader.set_justify(bool(checked))
        appconfig.save_settings({"reader_justify": bool(checked)})

    def on_hyphenate_toggled(self, checked: bool) -> None:
        self.reader.set_hyphenate(bool(checked))
        appconfig.save_settings({"reader_hyphenate": bool(checked)})

    def on_expand_all(self) -> None:
        self.reader.expand_all()

    def on_collapse_all(self) -> None:
        self.reader.collapse_all()

    def on_print_pdf(self) -> None:
        backend = self.reader.backend
        if not hasattr(backend, "print_pdf"):
            self._status_message(T("msg.export_failed").format("PDF (full reader)"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, T("action.print_pdf"), "book.pdf", "PDF (*.pdf)")
        if path:
            backend.print_pdf(path)

    def on_add_note(self) -> None:
        if not self._input_path:
            return
        text, ok = QInputDialog.getText(self, T("action.add_note"), T("label.notes"))
        if ok and text.strip():
            self.reader.session.add_annotation(
                self._input_path, {"text": text.strip(),
                                   "note": self.reader.backend.current_href() or ""})

    def on_bookmarks(self) -> None:
        if self._input_path:
            items = self.reader.session.annotations(self._input_path)
            self._status_message(f"{T('action.bookmarks')}: {len(items)}")

    # ------------------------------------------------------ settings dialogs
    def on_settings(self, tab: int | None = None) -> None:
        from noesis_ebook_translator.ui import SettingsDialog
        dialog = SettingsDialog(self, apply_theme_cb=self._apply_theme_preview)
        dialog.applied.connect(self._apply_settings_values)
        if tab is not None:
            # Ribbon "dialog launcher": open Settings on the matching page.
            try:
                dialog.tabs.setCurrentIndex(int(tab))
            except Exception:  # noqa: BLE001 - cosmetic only
                pass
        if dialog.exec():
            values = dialog.apply()
            self._apply_settings_values(values)
            restart = (values.get("ui_language") != get_language()
                       or values.get("reader_backend")
                       != self._settings.get("reader_backend", "auto"))
            self._status_message(T("msg.restart_needed") if restart
                                 else T("msg.settings_saved"))

    def on_wizard(self) -> None:
        from noesis_ebook_translator.ui import OnboardingWizard
        wizard = OnboardingWizard(self)
        if wizard.exec():
            self._reload_engines()
            self._status_message(T("msg.wizard_done"))

    def on_help(self) -> None:
        from noesis_ebook_translator.ui import HelpDialog
        HelpDialog(get_language(), parent=self).exec()

    def on_online_help(self) -> None:
        from noesis_ebook_translator.help import help_url
        QDesktopServices.openUrl(QUrl(help_url(get_language())))

    def on_about(self) -> None:
        self._status_message(f"{T('about.text')}\n\n{__version__}")

    def on_license(self) -> None:
        self._status_message("GNU GPL v3.0 — derived from bookfere's Ebook "
                             "Translator (GPLv3).")

    def on_upstream(self) -> None:
        QDesktopServices.openUrl(
            QUrl("https://github.com/bookfere/Ebook-Translator-Calibre-Plugin"))

    def on_engine_version(self) -> None:
        from noesis_ebook_translator import EbookTranslator
        self._status_message(f"Engine {EbookTranslator.__version__}")

    def on_config_dir(self) -> None:
        from noesis_ebook_translator.paths import data_dir
        self._status_message(str(data_dir()))

    def on_data_dir(self) -> None:
        from noesis_ebook_translator.lib.utils import open_path
        from noesis_ebook_translator.paths import data_dir
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        open_path(str(directory))

    def on_clear_cache(self) -> None:
        from noesis_ebook_translator.paths import data_dir
        import shutil
        cache = data_dir() / "cache"
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
        self._status_message(T("action.clear_cache"))

    # ------------------------------------------------------ library / assets
    def set_library_view(self, view: str) -> None:
        self.tabs.setCurrentWidget(self.library)
        self.library.set_view(view)
        self._sync_library_buttons()

    def set_library_layout(self, layout: str) -> None:
        self.tabs.setCurrentWidget(self.library)
        self.library.set_layout(layout)
        self._sync_library_buttons()

    def _sync_library_buttons(self) -> None:
        """Show which library view/layout is active, and how much it holds."""
        try:
            counts = self.library.counts()
        except Exception:  # noqa: BLE001 - cosmetic only
            counts = {}
        groups = (
            (getattr(self.workflow, "library_view_buttons", {}),
             self.library.view()),
            (getattr(self.workflow, "library_layout_buttons", {}),
             self.library.layout_mode()),
        )
        for buttons, active in groups:
            for name, button in buttons.items():
                button.blockSignals(True)
                button.setChecked(name == active)
                button.blockSignals(False)
                if name in counts:
                    button.setToolTip(f"{T(f'view.{name}')} ({counts[name]})")

    def _on_assets_edition_changed(self, _index: int) -> None:
        self._assets_edition = (
            "translated" if self.cmb_assets_edition.currentIndex() == 1
            else "original")
        source = self._assets_source()
        for panel in (self.figures, self.tables, self.texts, self.preview):
            panel.set_source(source)

    def on_assets_reload(self) -> None:
        source = self._assets_source()
        for panel in (self.figures, self.tables, self.texts):
            panel.set_source(source)
        current = self.tabs.currentWidget()
        if current is self.figures:
            self.figures.load_current()
        elif current is self.tables:
            self.tables.load_current()
        elif current is self.texts:
            self.texts.load_current()

    def _load_figures(self) -> None:
        if self._assets_source():
            self.figures.set_source(self._assets_source())
            self.figures.load_current()
        self._select_category(2)
        self.tabs.setCurrentWidget(self.figures)

    def _load_tables(self) -> None:
        if self._assets_source():
            self.tables.set_source(self._assets_source())
            self.tables.load_current()
        self._select_category(2)
        self.tabs.setCurrentWidget(self.tables)

    def _load_texts(self) -> None:
        if self._assets_source():
            self.texts.set_source(self._assets_source())
            self.texts.load_current()
        self._select_category(2)
        self.tabs.setCurrentWidget(self.texts)

    def on_export(self) -> None:
        from noesis_ebook_translator.ui import ExportDialog
        ExportDialog(self._input_path, self._translated_path(), self).exec()

    def on_export_quick(self) -> None:
        source = self._input_path
        if self.cmb_export_edition.currentIndex() == 1:
            source = self._translated_path() or source
        if not source:
            self._status_message(T("msg.no_input"))
            return
        fmt = self.cmb_export_format.currentData() or "epub"
        chapters = self.edt_export_chapters.text().strip() or None
        dest, _ = QFileDialog.getSaveFileName(
            self, T("action.export"), os.path.splitext(source)[0] + "_export",
            f"*.{fmt}")
        if not dest:
            return
        try:
            from noesis_ebook_translator.chapters import load_chapters, resolve_selection
            selected = resolve_selection(load_chapters(source), chapters) if chapters else None
            written = exporter_mod.export_chapters(source, dest, selected, fmt)
        except Exception as exc:  # noqa: BLE001
            self._status_message(T("msg.export_failed").format(exc))
            return
        self._status_message(T("msg.export_done").format("\n".join(written)))

    def on_export_assets(self) -> None:
        source = self._assets_source()
        if not source:
            self._status_message(T("msg.no_input"))
            return
        from noesis_ebook_translator import extract
        directory = QFileDialog.getExistingDirectory(self, T("action.export_assets"))
        if not directory:
            return
        results = []
        try:
            figures = extract.extract_figures(source)
            if figures:
                results += exporter_mod.export_figures(figures, directory, "img")
            tables = extract.extract_tables(source)
            if tables:
                results += exporter_mod.export_tables(tables, directory, "csv")
        except Exception as exc:  # noqa: BLE001
            self._status_message(T("msg.export_failed").format(exc))
            return
        self._status_message(T("msg.export_done").format(f"\n{directory}"))

    # ----------------------------------------------------------------- quality
    def on_quality(self, use_ai: bool = False) -> None:
        from noesis_ebook_translator.ui.quality_dialog import QualityDialog
        translated = self._translated_path()

        def judge_factory():
            from noesis_ebook_translator.quality import make_engine_judge
            return make_engine_judge(
                self.cmb_engine.currentText(),
                self.cmb_source.currentText(), self.cmb_target.currentText())

        dialog = QualityDialog(self._input_path, translated,
                               judge_factory=judge_factory, parent=self)
        dialog.chk_judge.setChecked(bool(use_ai))
        dialog.exec()

    def on_report_save(self) -> None:
        from noesis_ebook_translator.quality import evaluate, write_report
        if not (self._input_path and self._translated_path()):
            self._status_message(T("msg.no_input"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, T("action.report_save"), "quality.md",
            "Markdown (*.md);;JSON (*.json)")
        if not path:
            return
        report = evaluate(self._input_path, self._translated_path())
        write_report(report, path)
        self._status_message(T("quality.report_written").format(path))

    def on_report_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, T("action.report_open"), "", "Report (*.md *.json);;All files (*)")
        if not path:
            return
        try:
            text = open(path, encoding="utf-8").read()
        except OSError as exc:
            self._status_message(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(T("action.report_open"))
        dialog.resize(700, 520)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        layout.addWidget(view)
        close = QPushButton(T("action.close"))
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    # -------------------------------------------------------------- tools
    def on_split(self) -> None:
        from noesis_ebook_translator import segment
        if not self._input_path:
            self._status_message(T("msg.no_input"))
            return
        directory = QFileDialog.getExistingDirectory(self, T("action.split"))
        if not directory:
            return
        try:
            written = segment.split_epub(self._input_path, directory)
        except Exception as exc:  # noqa: BLE001
            self._status_message(str(exc))
            return
        self._status_message(T("msg.export_done").format("\n".join(written)))

    def on_merge(self) -> None:
        from noesis_ebook_translator import segment
        paths, _ = QFileDialog.getOpenFileNames(
            self, T("action.merge"), "", "EPUB (*.epub)")
        if not paths:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, T("action.merge"), "merged.epub", "EPUB (*.epub)")
        if not target:
            return
        try:
            out = segment.merge_epubs(paths, target)
        except Exception as exc:  # noqa: BLE001
            self._status_message(str(exc))
            return
        self._status_message(T("msg.export_done").format(out))

    # -------------------------------------------------------------- translate
    def on_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.status.set_base_text(T("status.canceled"))

    def _selected_document_count(self, chapters) -> int:
        """How many XHTML documents the selected TOC entries cover."""
        if not chapters or not self._input_path:
            return len(chapters or [])
        wanted = {str(c) for c in chapters}
        try:
            units = build_units(self._input_path)
        except Exception:  # noqa: BLE001
            return len(chapters)
        docs = {u.file for u in units
                if u.file and (u.href in wanted or u.file in wanted)}
        return len(docs) or len(chapters)

    def _normalize_chapter_spec(self, spec) -> list[str] | None:
        """Resolve a chapter spec into **TOC entry** identities (href + anchor).

        The engine and the chapter list both identify a chapter by its TOC entry.
        Passing bare file names merged the entries that share one XHTML document:
        selecting CHAPTER V (``book.xhtml#ch5``) also dragged in CHAPTER IV, i.e.
        87 segments instead of 8. ``resolve_selection`` matches hrefs exactly, so
        the anchor is what keeps the selection honest.
        """
        if not spec or not self._input_path:
            return None
        from noesis_ebook_translator.chapters import (
            load_chapters, resolve_selection)
        try:
            selected = resolve_selection(load_chapters(self._input_path), spec)
        except Exception:  # noqa: BLE001 - fall back to what was passed
            return [str(s) for s in spec]
        keys: list[str] = []
        for chapter in selected:
            key = chapter.href or chapter.file
            if key and key not in keys:
                keys.append(key)
        return keys or None

    def _translate_chapters(self, indices) -> None:
        self.tabs.setCurrentWidget(self._translate_tab)
        chapters = self._normalize_chapter_spec(indices or None)
        if not chapters:
            self._status_message(T("msg.no_input"))
            return
        base = os.path.splitext(os.path.basename(self._input_path or "book"))[0]
        self._start_translation({
            "source": self.cmb_source.currentText(),
            "target": self.cmb_target.currentText(),
            "engine": self.cmb_engine.currentText(),
            "api_key": self.edt_api_key.text().strip(),
            "model": self.cmb_model.currentText().strip(),
            "bilingual": self.chk_bilingual.isChecked(),
            "cache": self.chk_cache.isChecked(),
            "batching": self.chk_batch.isChecked(),
            "chapters": chapters,
            "grouping": "grouped",
            "folder": os.path.dirname(self._input_path or ""),
            "name": base + "_sel",
        })

    def _export_chapters(self, indices) -> None:
        if not self._input_path:
            self._status_message(T("msg.no_input"))
            return
        spec = ",".join(str(i) for i in indices) if indices else None
        source = self._input_path
        dest, _ = QFileDialog.getSaveFileName(
            self, T("action.export_selected"),
            os.path.splitext(source)[0] + "_chapters.epub",
            "EPUB (*.epub);;All files (*)")
        if not dest:
            return
        fmt = os.path.splitext(dest)[1].lstrip(".").lower() or "epub"
        from noesis_ebook_translator.chapters import load_chapters, resolve_selection
        selected = (resolve_selection(load_chapters(source), spec)
                    if spec else None)
        try:
            written = exporter_mod.export_chapters(source, dest, selected, fmt)
        except Exception as exc:  # noqa: BLE001
            self._status_message(T("msg.export_failed").format(exc))
            return
        self._status_message(T("msg.export_done").format("\n".join(written)))

    def on_translate_book(self) -> None:
        if not self._input_path:
            self._status_message(T("msg.no_input"))
            return
        from noesis_ebook_translator.ui import TranslateWizard
        wizard = TranslateWizard(
            self, mode="book", input_path=self._input_path,
            source=self.cmb_source.currentText(),
            target=self.cmb_target.currentText(),
            engine=self.cmb_engine.currentText())
        if wizard.exec():
            self._update_model_badge()
            self._start_translation(wizard.config())

    # Backwards-compatible alias.
    def on_translate(self) -> None:
        self.on_translate_book()
    def on_translate_chapters(self) -> None:
        if not self._input_path:
            self._status_message(T("msg.no_input"))
            return
        from noesis_ebook_translator.ui import TranslateWizard
        wizard = TranslateWizard(
            self, mode="chapters", input_path=self._input_path,
            source=self.cmb_source.currentText(),
            target=self.cmb_target.currentText(),
            engine=self.cmb_engine.currentText())
        if wizard.exec():
            cfg = wizard.config()
            if not cfg.get("chapters"):
                self._status_message(T("msg.no_input"))
                return
            self._update_model_badge()
            self._start_translation(cfg)

    def _chapter_labels(self, files) -> list[str]:
        """Backwards-compatible helper: labels for the given chapter files."""
        if not self._input_path:
            return []
        try:
            from noesis_ebook_translator.chapters import flatten, load_chapters
            tree = flatten(load_chapters(self._input_path))
        except Exception:  # noqa: BLE001
            return []
        by_file = {}
        for chapter in tree:
            if chapter.file and chapter.file not in by_file:
                by_file[chapter.file] = chapter.name or chapter.file
        if files:
            return [by_file.get(f, f) for f in files]
        return [c.name or c.file for c in tree if c.file]

    def _confirm_output_path(self) -> bool:
        """Ask before overwriting; warn loudly before replacing the original.

        Returns ``False`` when the user declines, so the run must not start.
        """
        path = self._output_path
        if not path:
            return True
        replacing_original = bool(
            self._input_path
            and os.path.abspath(path) == os.path.abspath(self._input_path))
        if replacing_original:
            message = T("msg.overwrite_original")
        elif os.path.exists(path):
            message = T("msg.overwrite_confirm")
        else:
            return True
        answer = QMessageBox.question(
            self, T("app.title"), message.format(path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _start_translation(self, cfg: dict) -> None:
        if self.worker is not None:
            return
        if not self._input_path:
            self._status_message(T("msg.no_input"))
            return

        engine = cfg.get("engine") or self.cmb_engine.currentText()
        source = cfg.get("source") or "English"
        target = cfg.get("target") or "Italian"
        # A chapter spec always becomes TOC-entry identities (href + anchor): the
        # wizard and the chapter panel may hand over indices, file names or hrefs.
        chapters = self._normalize_chapter_spec(cfg.get("chapters"))
        folder = cfg.get("folder") or os.path.dirname(self._input_path)
        name = cfg.get("name") or os.path.splitext(
            os.path.basename(self._input_path))[0]
        # Convention: "<name>-<language>.epub", always (see book.output_name).
        self._output_path = os.path.join(folder, book.output_name(name, target))
        if not cfg.get("output_confirmed") and not self._confirm_output_path():
            return
        self._refresh_choices(cfg if cfg else None)

        api_key = cfg.get("api_key", "")
        # "Sequential" pins concurrency_limit=1 (one segment at a time) so the
        # per-chapter progress is truthful. Passing None *removes* the key, so the
        # engine class default (1 for most, unlimited for GenAI/DeepSeek) applies.
        sequential = bool(cfg.get("sequential", True))
        appconfig.set_engine_preference(
            engine, api_keys=[api_key] if api_key else [],
            model=cfg.get("model") or None,
            concurrency_limit=1 if sequential else None)
        settings = {
            "translate_engine": engine,
            "translation_position": "below" if cfg.get("bilingual") else "only",
            "cache_enabled": bool(cfg.get("cache", True)),
            "online_batching": bool(cfg.get("batching", False)),
            "translate_sequential": sequential,
            "ui_source_lang": source,
            "ui_target_lang": target,
        }
        appconfig.save_settings(settings)

        # When chapters must be split into one EPUB each, split after translating.
        self._pending_split = None
        if chapters and cfg.get("grouping") == "single":
            self._pending_split = {"folder": folder,
                                   "name": os.path.splitext(name)[0]}

        # Band 1 recap + band 2/3 model. ``_chapter_names`` stays empty: the
        # per-unit display is owned by the progress model (the legacy linear
        # estimate in _on_progress is only used when _chapter_names is filled).
        self._chapter_names = []
        self._refresh_choices(cfg)
        try:
            units = build_units(self._input_path)
        except ChapterError:
            # The engine will fail on the same book and report it; the band just
            # stays empty instead of taking the window down.
            units = []
        model = ProgressModel(units)
        # The whole TOC is listed; only the wizard selection is translated and
        # the other chapters stay dimmed for context.
        model.set_selection(chapters)
        self.translate_view.set_model(model, selection=bool(chapters))

        self.worker = TranslationWorker(
            self._input_path, self._output_path, engine, source, target, settings,
            chapters=chapters)
        self.worker.plan.connect(self._on_plan)
        self.worker.delta.connect(self._on_delta)
        self.worker.logged.connect(self._on_log)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_worker_done)

        self.log.clear()
        self.workflow.set_book(self._book_label(self._input_path), percent=0,
                               working=True)
        self.btn_translate.setEnabled(False)
        self.btn_translate_chapters.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status.set_base_text(T("status.translating"))
        self.status.start_busy()
        self.progress.setValue(0)
        self.progress.set_busy(True)
        self.chapter_bar.setValue(0)
        self.chapter_bar.set_busy(True)
        self.book_label.setText("0%")
        self.chapter_label.setText("—")
        self.worker.start()

    # --------------------------------------------------------------- slots
    def _on_plan(self, counts) -> None:
        """The engine reported how many segments each document holds."""
        model = self.translate_view.model()
        if model is None:  # pragma: no cover - defensive
            return
        model.set_plan(counts)
        self.translate_view.refresh()

    def _on_delta(self, payload: dict) -> None:
        """A coalesced batch of progress (counts, cached, last text, log lines)."""
        model = self.translate_view.model()
        if model is None:  # pragma: no cover - defensive
            return
        model.apply(payload)
        if payload.get("log"):
            self.log.appendPlainText("\n".join(payload["log"]))
        self.translate_view.refresh()
        percent = model.overall_percent()
        self.workflow.set_book_percent(int(percent))
        self._on_progress(percent / 100.0, "")
        if self.worker is not None:
            self.worker.release_flush()

    def _on_progress(self, fraction: float, message: str) -> None:
        fraction = max(0.0, min(1.0, fraction))
        self.progress.setValue(int(fraction * 100))
        self.book_label.setText(f"{int(fraction * 100)}%")
        names = self._chapter_names
        if names:
            # Legacy linear estimate; the progress model owns the per-unit view
            # when it is in charge (``_chapter_names`` stays empty then).
            index = min(len(names) - 1, int(fraction * len(names)))
            inner = fraction * len(names) - index
            self.chapter_bar.setValue(int(max(0.0, min(1.0, inner)) * 100))
            self.chapter_label.setText(names[index])
        if message:
            self.status.set_base_text(message)

    def _on_log(self, text: str, error: bool) -> None:
        self.log.appendPlainText(text)

    def _on_finished(self, path: str) -> None:
        self.progress.set_busy(False)
        self.chapter_bar.set_busy(False)
        self.progress.setValue(100)
        self.chapter_bar.setValue(100)
        self.book_label.setText("100%")
        self.status.stop_busy()
        self.status.set_base_text(T("status.done"))
        try:
            self.reader.set_translated_path(path)
        except Exception:  # noqa: BLE001
            pass
        if self._input_path:
            try:
                self.reader.session.set_translated(self._input_path, path)
            except Exception:  # noqa: BLE001
                pass
            try:
                self.chapters.store.sync_from_epub(self._input_path)
                self.chapters.load_current()
            except Exception:  # noqa: BLE001
                pass
        self.translate_view.set_finished(ok=True, exported=False)
        self.workflow.set_book(self._book_label(self._input_path), percent=100,
                               working=False)
        summary = self.translate_view.model().summary() if (
            self.translate_view.model() is not None) else {}
        self._summary_message = self._chapters_message(summary)
        if self._summary_message:
            self.log.appendPlainText(self._summary_message)
        if self._pending_split:
            # One EPUB per chapter: keep the message for when the split is done.
            self._split_ok = False
            self._split_message = ""
            self._start_split(path)
        else:
            self._status_message(self._done_message(path))

    def _chapters_message(self, summary: dict) -> str:
        """'Capitoli tradotti: 3/3 — 2 erano già in cache' (empty if unknown)."""
        total = int(summary.get("total") or 0)
        if total < 1:
            return ""
        done = int(summary.get("done") or 0)
        cached = int(summary.get("cached") or 0)
        if cached:
            return T("msg.chapters_cached").format(done=done, total=total,
                                                   cached=cached)
        return T("msg.chapters_done").format(done=done, total=total)

    def _done_message(self, path: str) -> str:
        message = T("msg.done").format(path)
        if self._summary_message:
            message += "\n" + self._summary_message
        return message

    def _start_split(self, path: str) -> None:
        """Split the translated EPUB in the background (chapter mode)."""
        self.status.set_base_text(T("status.exporting"))
        self.status.start_busy()
        self._split_worker = SplitWorker(path, self._pending_split["folder"], self)
        self._split_worker.done.connect(self._on_split_done)
        self._split_worker.failed.connect(self._on_split_failed)
        self._split_worker.finished.connect(self._on_split_finished)
        self._split_worker.start()

    def _on_split_done(self, written) -> None:
        self._split_ok = True
        self._split_message = T("msg.export_done").format("\n".join(written))

    def _on_split_failed(self, message: str) -> None:
        self._split_ok = False
        self.log.appendPlainText(message)
        self._split_message = T("msg.export_failed").format(
            message.strip().splitlines()[-1] if message.strip() else message)

    def _on_split_finished(self) -> None:
        self._split_worker = None
        self._pending_split = None
        self.status.stop_busy()
        self.status.set_base_text(T("status.done"))
        self.translate_view.set_finished(ok=True, exported=self._split_ok)
        message = self._done_message(self._output_path)
        if self._split_message:
            message += "\n" + self._split_message
        self._status_message(message)
        self._enable_actions()

    def _on_cancelled(self) -> None:
        """The user stopped the run: report it as cancelled, not as translated.

        The engine drains its queue on cancel and used to return normally, so the
        window marked the book as translated with a half-written file. Now the
        cancellation is reported as such: the view is left unfinished and the
        library never learns a translated path.
        """
        self.progress.set_busy(False)
        self.chapter_bar.set_busy(False)
        self.status.stop_busy()
        self.status.set_base_text(T("status.canceled"))
        self.translate_view.set_finished(ok=False)
        self.workflow.set_book_working(False)
        self._status_message(T("status.canceled"))

    def _on_failed(self, message: str) -> None:
        self.progress.set_busy(False)
        self.chapter_bar.set_busy(False)
        self.status.stop_busy()
        self.status.set_base_text(T("status.failed"))
        self.log.appendPlainText(message)
        self.translate_view.set_finished(ok=False)
        self.workflow.set_book_working(False)
        self._status_message(message.splitlines()[-1])

    def _enable_actions(self) -> None:
        self.btn_translate.setEnabled(True)
        self.btn_translate_chapters.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _on_worker_done(self) -> None:
        self.worker = None
        # Keep the actions disabled while the per-chapter split is still running.
        if self._split_worker is None:
            self._enable_actions()


def main(argv: list[str] | None = None) -> int:
    appconfig.ensure_defaults()
    settings = appconfig.load_settings()
    set_language(settings.get("ui_language", "it"))
    try:
        from noesis_ebook_translator.reader import prepare_full
        prepare_full()
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    from noesis_ebook_translator.ui import apply_theme
    apply_theme(app, settings.get("ui_theme", "system"))

    if not settings.get("onboarding_done"):
        try:
            from noesis_ebook_translator.ui import OnboardingWizard
            OnboardingWizard().exec()
            settings = appconfig.load_settings()
            set_language(settings.get("ui_language", "it"))
            apply_theme(app, settings.get("ui_theme", "system"))
        except Exception:  # noqa: BLE001 - never block startup
            pass

    window = MainWindow()
    window._startup_geometry()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
