#!/usr/bin/env python3
"""Noesis Ebook Translator — desktop GUI (PyQt6 + pyqtribbon).

The ribbon follows the app's workflow (Home · Library · Reader · Assets ·
Translate · Quality · Export · Tools · Info) and is built by
:func:`noesis_ebook_translator.ui.ribbon.build_ribbon`. All the heavy lifting
lives in :mod:`noesis_ebook_translator.book` (the verbatim engine).
"""
from __future__ import annotations

import os
import sys
import threading
import traceback

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QTabWidget, QVBoxLayout, QWidget)

from noesis_ebook_translator import APP_NAME, __version__, appconfig, book, theme
from noesis_ebook_translator import exporter as exporter_mod
from noesis_ebook_translator.i18n import T, get_language, set_language
from noesis_ebook_translator.reader import ReaderWidget, available_backends, resolve_backend
from noesis_ebook_translator.reader.panels import (
    ChaptersWidget, FiguresWidget, LibraryWidget, PreviewWidget, TablesWidget,
    TextsWidget)
from noesis_ebook_translator.ui.animations import DotsLabel, ShimmerBar
from noesis_ebook_translator.ui.ribbon import build_ribbon
from noesis_ebook_translator.engines.languages import google as GOOGLE_LANGUAGES


def _resource(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


class TranslationWorker(QThread):
    """Runs :func:`book.translate_epub` off the UI thread."""

    progressed = pyqtSignal(float, str)
    logged = pyqtSignal(str, bool)
    paragraph = pyqtSignal(object)
    finished_ok = pyqtSignal(str)
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

    def cancel(self) -> None:
        self._cancel.set()

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
                on_progress=lambda frac, msg: self.progressed.emit(frac, msg),
                on_log=lambda text, error=False: self.logged.emit(text, error),
                on_paragraph=lambda p: self.paragraph.emit(p),
                should_cancel=self._cancel.is_set,
            )
            self.finished_ok.emit(path)
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
        self._build_ribbon()
        self._build_body()
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _build_ribbon(self) -> None:
        build_ribbon(self)
        # Switching ribbon category drives the TOC mode (read vs select).
        try:
            self.ribbon.tabBar().currentChanged.connect(self._on_ribbon_category)
        except Exception:  # noqa: BLE001 - older pyqtribbon
            pass

    def _build_body(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)

        form_box = QGroupBox(T("panel.file"))
        form = QFormLayout(form_box)
        self.lbl_input = QLabel("—")
        self.lbl_output = QLabel("—")
        form.addRow(T("label.input") + ":", self.lbl_input)
        form.addRow(T("label.output") + ":", self.lbl_output)
        outer.addWidget(form_box)

        self.progress = ShimmerBar(reduce_motion=self._reduce_motion)
        outer.addWidget(self.progress)

        self.status = DotsLabel(T("status.ready"), reduce_motion=self._reduce_motion)
        outer.addWidget(self.status)

        self.chapter_progress = QLabel("")
        outer.addWidget(self.chapter_progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        outer.addWidget(self.log, 1)

        self.reader = ReaderWidget(session=None, backend_mode=self._reader_mode())
        self.reader.statusMessage.connect(self.status.set_base_text)
        self.library = LibraryWidget(self.reader.session)
        self.chapters = ChaptersWidget()
        self.figures = FiguresWidget()
        self.tables = TablesWidget()
        self.texts = TextsWidget()
        self.preview = PreviewWidget(self._preview_options)
        self.library.openRequested.connect(self._apply_source)

        self.tabs = QTabWidget()
        self.tabs.addTab(central, T("tab.translate"))
        self.tabs.addTab(self.reader, T("tab.reader"))
        self.tabs.addTab(self.library, T("tab.library"))
        self.tabs.addTab(self.chapters, T("tab.chapters"))
        self.tabs.addTab(self.figures, T("tab.figures"))
        self.tabs.addTab(self.tables, T("tab.tables"))
        self.tabs.addTab(self.texts, T("assets.texts"))
        self.tabs.addTab(self.preview, T("tab.preview"))
        self._translate_tab = central

        self.setCentralWidget(self.tabs)
        self.resize(1180, 780)

    # ------------------------------------------------------------- helpers
    def _engine_names(self) -> list[str]:
        return appconfig.engine_names()

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
        self.lbl_input.setText(path)
        self.lbl_output.setText(self._output_path)
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
        self.chk_reduce.setChecked(bool(settings.get("reduce_motion", False)))
        theme_index = self.cmb_theme.findText(
            T(f"theme.{settings.get('ui_theme', 'system')}"))
        if theme_index >= 0:
            self.cmb_theme.setCurrentIndex(theme_index)
        lang_index = self.cmb_ui_lang.findText(T(f"language.{get_language()}"))
        if lang_index >= 0:
            self.cmb_ui_lang.setCurrentIndex(lang_index)
        # reader backend combo
        for backend in ["auto"] + available_backends():
            self.cmb_reader_default.addItem(T(f"backend.{backend}"), backend)
        rb = settings.get("reader_backend", "auto")
        rb_index = self.cmb_reader_default.findData(rb)
        if rb_index >= 0:
            self.cmb_reader_default.setCurrentIndex(rb_index)
        # export format combo
        for fmt in exporter_mod.supported_exports():
            self.cmb_export_format.addItem(T(f"format.{fmt}"), fmt)
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

    def _current_theme(self) -> str:
        return theme.theme_choices()[max(0, self.cmb_theme.currentIndex())]

    def _on_theme_changed(self, _index: int) -> None:
        from noesis_ebook_translator.ui import apply_theme
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._current_theme(), reader=self.reader.backend)
        appconfig.save_settings({"ui_theme": self._current_theme()})

    def _on_ui_language_changed(self, _index: int) -> None:
        if self._initializing:
            return
        codes = ["it", "en", "fr", "es", "de"]
        lang = codes[max(0, min(len(codes) - 1, self.cmb_ui_lang.currentIndex()))]
        appconfig.save_settings({"ui_language": lang})
        if lang != get_language():
            self._status_message(T("msg.restart_language"))

    def _on_reduce_motion(self, checked: bool) -> None:
        self._reduce_motion = bool(checked)
        self.progress.set_reduce_motion(self._reduce_motion)
        appconfig.save_settings({"reduce_motion": self._reduce_motion})

    def _on_reader_backend_changed(self, _index: int) -> None:
        if self._initializing:
            return
        backend = self.cmb_reader_default.currentData() or "auto"
        appconfig.save_settings({"reader_backend": backend})
        self._status_message(T("msg.restart_needed"))

    # --------------------------------------------------------- tab / TOC
    def _on_ribbon_category(self, index: int) -> None:
        # 1 = Library, 2 = Reader, 3 = Assets, 4 = Translate
        self._ribbon_index = index
        if index == 1:
            self.tabs.setCurrentWidget(self.library)
        elif index == 2:
            self.tabs.setCurrentWidget(self.reader)
        elif index == 3:
            self.tabs.setCurrentWidget(self.figures)
        elif index == 4:
            self.tabs.setCurrentWidget(self._translate_tab)
        self._update_toc_mode()

    def _update_toc_mode(self) -> None:
        mode = "select" if getattr(self, "_ribbon_index", 0) == 4 else "read"
        try:
            self.reader.set_toc_mode(mode)
        except Exception:  # noqa: BLE001 - reader is best effort
            pass

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
        self.tabs.setCurrentWidget(self.reader)

    def on_refresh(self) -> None:
        self.library.refresh()
        try:
            self.chapters.refresh()
        except Exception:  # noqa: BLE001
            pass

    def on_compare(self) -> None:
        self.tabs.setCurrentWidget(self.reader)
        if not self.reader.btn_parallel.isChecked():
            self.reader.btn_parallel.toggle()

    def on_retranslate(self) -> None:
        self.tabs.setCurrentWidget(self._translate_tab)

    def on_extract_chapters(self) -> None:
        if self._input_path:
            self.chapters.set_source(self._input_path)
            self.chapters.load_current()
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

    def on_toggle_spread(self) -> None:
        if hasattr(self.reader.backend, "set_spread"):
            self.reader.backend.set_spread(not self.reader.btn_parallel.isChecked())

    def on_find(self) -> None:
        self.reader.edt_find.setFocus()

    def on_find_next(self) -> None:
        self.reader._find(False)

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
    def on_settings(self) -> None:
        from noesis_ebook_translator.ui import SettingsDialog
        dialog = SettingsDialog(self, apply_theme_cb=self._apply_theme_preview)
        if dialog.exec():
            values = dialog.apply()
            self.chk_reduce.setChecked(bool(values.get("reduce_motion")))
            self._reduce_motion = bool(values.get("reduce_motion"))
            self.progress.set_reduce_motion(self._reduce_motion)
            restart = (values.get("ui_language") != get_language()
                       or values.get("reader_backend") != self._settings.get(
                           "reader_backend", "auto"))
            self._status_message(T("msg.restart_needed") if restart
                                 else T("msg.settings_saved"))

    def _apply_theme_preview(self, mode: str) -> None:
        from noesis_ebook_translator.ui import apply_theme
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, mode, reader=self.reader.backend)

    def on_wizard(self) -> None:
        from noesis_ebook_translator.ui import OnboardingWizard
        wizard = OnboardingWizard(self)
        if wizard.exec():
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
        self.tabs.setCurrentWidget(self.figures)

    def _load_tables(self) -> None:
        if self._assets_source():
            self.tables.set_source(self._assets_source())
            self.tables.load_current()
        self.tabs.setCurrentWidget(self.tables)

    def _load_texts(self) -> None:
        if self._assets_source():
            self.texts.set_source(self._assets_source())
            self.texts.load_current()
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

    def on_translate(self) -> None:
        if self.worker is not None:
            return
        if not self._input_path:
            self._status_message(T("msg.no_input"))
            return

        engine = self.cmb_engine.currentText()
        source = self.cmb_source.currentText()
        target = self.cmb_target.currentText()
        chapters = self.reader.selected_files() or None
        if chapters:
            self._output_path = book.default_output_path(
                self._input_path, target).replace(
                ".epub", f"_sel-{len(chapters)}.epub")
        else:
            self._output_path = book.default_output_path(self._input_path, target)
        self.lbl_output.setText(self._output_path)

        api_keys = [k for k in [self.edt_api_key.text().strip()] if k]
        appconfig.set_engine_preference(
            engine, api_keys=api_keys,
            model=self.cmb_model.currentText().strip() or None)

        settings = {
            "translate_engine": engine,
            "translation_position": "below" if self.chk_bilingual.isChecked() else "only",
            "cache_enabled": self.chk_cache.isChecked(),
            "online_batching": self.chk_batch.isChecked(),
            "ui_source_lang": source,
            "ui_target_lang": target,
        }
        appconfig.save_settings(settings)

        self.worker = TranslationWorker(
            self._input_path, self._output_path, engine, source, target, settings,
            chapters=chapters)
        self.worker.progressed.connect(self._on_progress)
        self.worker.logged.connect(self._on_log)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_worker_done)

        self.log.clear()
        self.btn_translate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status.set_base_text(T("status.translating"))
        self.status.start_busy()
        self.progress.setValue(0)
        self.progress.set_busy(True)
        self.worker.start()

    # --------------------------------------------------------------- slots
    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        self.chapter_progress.setText(
            T("anim.translating_chapter").format(
                current=self.progress.value(), total=100))
        if message:
            self.status.set_base_text(message)

    def _on_log(self, text: str, error: bool) -> None:
        self.log.appendPlainText(text)

    def _on_finished(self, path: str) -> None:
        self.progress.set_busy(False)
        self.progress.setValue(100)
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
        self._status_message(T("msg.done").format(path))

    def _on_failed(self, message: str) -> None:
        self.progress.set_busy(False)
        self.status.stop_busy()
        self.status.set_base_text(T("status.failed"))
        self.log.appendPlainText(message)
        self._status_message(message.splitlines()[-1])

    def _on_worker_done(self) -> None:
        self.worker = None
        self.btn_translate.setEnabled(True)
        self.btn_cancel.setEnabled(False)


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
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
