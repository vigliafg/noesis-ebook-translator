#!/usr/bin/env python3
"""Noesis Ebook Translator — desktop GUI (PyQt6 + pyqtribbon).

A translation-only front-end: open an EPUB, pick an engine and the languages,
then translate. All the heavy lifting lives in
:mod:`noesis_ebook_translator.book`, which drives the verbatim Ebook Translator
engine. The GUI is assembled from small widgets in
:mod:`noesis_ebook_translator.ui` and :mod:`noesis_ebook_translator.reader`.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from pyqtribbon import RibbonBar

from noesis_ebook_translator import APP_NAME, __version__, appconfig, book, theme
from noesis_ebook_translator.i18n import T, get_language, set_language
from noesis_ebook_translator.reader import ReaderWidget, available_backends
from noesis_ebook_translator.reader.panels import (
    ChaptersWidget, FiguresWidget, LibraryWidget, PreviewWidget, TablesWidget,
    TextsWidget)
from noesis_ebook_translator.ui.animations import DotsLabel, ShimmerBar
from noesis_ebook_translator.engines.languages import google as GOOGLE_LANGUAGES


def _resource(*parts: str) -> str:
    base = os.path.dirname(os.path.abspath(__file__))
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
        self._build_ribbon()
        self._build_body()
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _build_ribbon(self) -> None:
        self.ribbon = RibbonBar()
        self.setMenuWidget(self.ribbon)

        home = self.ribbon.addCategory(T("tab.home"))
        panel_file = home.addPanel(T("panel.file"))
        panel_file.addLargeButton(T("action.open"), slot=self.on_open)
        self.btn_translate = panel_file.addLargeButton(
            T("action.translate"), slot=self.on_translate)
        self.btn_cancel = panel_file.addLargeButton(
            T("action.cancel"), slot=self.on_cancel)
        self.btn_cancel.setEnabled(False)
        panel_file.addLargeButton(
            T("action.open_output"), slot=self.on_open_output)

        engine_cat = self.ribbon.addCategory(T("tab.engine"))
        panel_engine = engine_cat.addPanel(T("panel.engine"))
        panel_engine.addLabel(T("label.model"))
        self.cmb_engine = panel_engine.addComboBox(appconfig.engine_names())
        self.cmb_engine.currentTextChanged.connect(self._on_engine_changed)

        panel_creds = engine_cat.addPanel(T("panel.credentials"))
        panel_creds.addLabel(T("label.api_key"))
        self.edt_api_key = panel_creds.addLineEdit()
        self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)

        panel_model = engine_cat.addPanel(T("panel.model"))
        panel_model.addLabel(T("label.model"))
        self.cmb_model = panel_model.addComboBox([])
        self.cmb_model.setEditable(True)

        lang_cat = self.ribbon.addCategory(T("tab.language"))
        panel_lang = lang_cat.addPanel(T("panel.languages"))
        panel_lang.addLabel(T("label.source"))
        self.cmb_source = panel_lang.addComboBox(
            ["Auto detect"] + list(GOOGLE_LANGUAGES))
        panel_lang.addLabel(T("label.target"))
        self.cmb_target = panel_lang.addComboBox(list(GOOGLE_LANGUAGES))

        options_cat = self.ribbon.addCategory(T("tab.options"))
        panel_out = options_cat.addPanel(T("panel.output"))
        self.chk_bilingual = panel_out.addCheckBox(T("label.bilingual"))
        self.chk_cache = panel_out.addCheckBox(T("label.cache"))
        self.chk_cache.setChecked(True)
        self.chk_batch = panel_out.addCheckBox(T("label.batch"))

        cfg_cat = self.ribbon.addCategory(T("panel.appearance"))
        panel_app = cfg_cat.addPanel(T("panel.appearance"))
        panel_app.addLabel(T("label.theme"))
        self.cmb_theme = panel_app.addComboBox(
            [T(f"theme.{m}") for m in theme.theme_choices()])
        self.cmb_theme.currentIndexChanged.connect(self._on_theme_changed)
        panel_app.addLabel(T("label.ui_language"))
        self.cmb_ui_lang = panel_app.addComboBox(
            [T(f"language.{code}") for code in ("it", "en", "fr", "es", "de")])
        self.cmb_ui_lang.currentIndexChanged.connect(self._on_ui_language_changed)
        panel_cfg = cfg_cat.addPanel(T("panel.behavior"))
        self.chk_reduce = panel_cfg.addCheckBox(T("label.reduce_motion"))
        panel_cfg.addLargeButton(T("action.settings"), slot=self.on_settings)
        panel_cfg.addLargeButton(T("action.wizard"), slot=self.on_wizard)

        read_cat = self.ribbon.addCategory(T("tab.reader"))
        panel_nav = read_cat.addPanel(T("panel.navigation"))
        panel_nav.addLargeButton("◀", slot=lambda: self.reader.backend.prev_chapter())
        panel_nav.addLargeButton("▶", slot=lambda: self.reader.backend.next_chapter())
        panel_zoom = read_cat.addPanel(T("panel.view"))
        panel_zoom.addLargeButton(T("assets.zoom_in"), slot=lambda: self.reader.backend.set_zoom(1))
        panel_zoom.addLargeButton(T("assets.zoom_out"), slot=lambda: self.reader.backend.set_zoom(-1))

        tools_cat = self.ribbon.addCategory(T("panel.tools"))
        panel_lib = tools_cat.addPanel(T("panel.library"))
        panel_lib.addLargeButton(
            T("tab.library"), slot=lambda: self.tabs.setCurrentWidget(self.library))
        panel_ch = tools_cat.addPanel(T("tab.chapters"))
        panel_ch.addLargeButton(
            T("tab.chapters"), slot=lambda: self.tabs.setCurrentWidget(self.chapters))
        panel_fig = tools_cat.addPanel(T("panel.figures"))
        panel_fig.addLargeButton(T("action.load"), slot=self._load_figures)
        panel_tab = tools_cat.addPanel(T("panel.tables"))
        panel_tab.addLargeButton(T("action.load"), slot=self._load_tables)
        panel_txt = tools_cat.addPanel(T("assets.texts"))
        panel_txt.addLargeButton(T("action.load"), slot=self._load_texts)
        panel_io = tools_cat.addPanel(T("panel.export"))
        panel_io.addLargeButton(T("action.export"), slot=self.on_export)
        panel_io.addLargeButton(T("action.split"), slot=self.on_split)
        panel_io.addLargeButton(T("action.merge"), slot=self.on_merge)
        panel_q = tools_cat.addPanel(T("panel.quality"))
        panel_q.addLargeButton(T("quality.run"), slot=self.on_quality)

        info_cat = self.ribbon.addCategory(T("tab.info"))
        panel_about = info_cat.addPanel(T("tab.info"))
        panel_about.addLargeButton(T("action.about"), slot=self.on_about)
        panel_about.addLargeButton(T("action.help"), slot=self.on_help)

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

        self.chapter_progress = QListWidget()
        self.chapter_progress.setMaximumHeight(110)
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

        self.setCentralWidget(self.tabs)
        self.resize(1100, 760)
        self._input_path: str | None = None
        self._output_path: str | None = None

    def _reader_mode(self) -> str:
        requested = self._settings.get("reader_backend", "lite")
        available = available_backends()
        return requested if requested in available else "lite"

    # ------------------------------------------------------------- helpers
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

    def _apply_source(self, path: str) -> None:
        self._input_path = path
        self._output_path = book.default_output_path(path, self.cmb_target.currentText())
        self.lbl_input.setText(path)
        self.lbl_output.setText(self._output_path)
        self.status.set_base_text(T("status.ready"))
        for panel in (self.figures, self.tables, self.texts,
                      self.chapters, self.preview):
            panel.set_source(path)
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

    def _populate_chapter_progress(self) -> None:
        self.chapter_progress.clear()
        if self.reader.document is None:
            return
        for chapter in self.reader.document.chapters:
            self.chapter_progress.addItem(chapter.name or chapter.file or "")

    def _highlight_chapter(self, fraction: float) -> None:
        count = self.chapter_progress.count()
        if count:
            index = min(count - 1, int(fraction * count))
            self.chapter_progress.setCurrentRow(index)

    # ------------------------------------------------------------ settings
    def _load_settings(self) -> None:
        settings = self._settings
        engine = settings.get("translate_engine") or self.cmb_engine.currentText()
        index = self.cmb_engine.findText(engine)
        if index >= 0:
            self.cmb_engine.setCurrentIndex(index)
        self.cmb_source.setCurrentText(settings.get("ui_source_lang", "English"))
        self.cmb_target.setCurrentText(settings.get("ui_target_lang", "Italian"))
        self.chk_bilingual.setChecked(
            settings.get("translation_position") == "below")
        self.chk_cache.setChecked(bool(settings.get("cache_enabled", True)))
        self.chk_batch.setChecked(bool(settings.get("online_batching", False)))
        self.chk_reduce.setChecked(bool(settings.get("reduce_motion", False)))
        theme_index = self.cmb_theme.findText(
            T(f"theme.{settings.get('ui_theme', 'system')}"))
        if theme_index >= 0:
            self.cmb_theme.setCurrentIndex(theme_index)
        lang_index = self.cmb_ui_lang.findText(
            T(f"language.{get_language()}"))
        if lang_index >= 0:
            self.cmb_ui_lang.setCurrentIndex(lang_index)
        self._on_engine_changed(self.cmb_engine.currentText())

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
        codes = ["it", "en", "fr", "es", "de"]
        lang = codes[max(0, min(len(codes) - 1, self.cmb_ui_lang.currentIndex()))]
        appconfig.save_settings({"ui_language": lang})
        if lang != get_language():
            QMessageBox.information(self, T("app.title"),
                                    T("msg.restart_language"))

    # --------------------------------------------------------------- actions
    def on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, T("action.open"), "", "EPUB (*.epub);;All files (*)")
        if not path:
            return
        self._apply_source(path)

    def on_open_output(self) -> None:
        if not self._output_path:
            return
        folder = os.path.dirname(self._output_path)
        from noesis_ebook_translator.lib.utils import open_path

        open_path(folder)

    def on_about(self) -> None:
        QMessageBox.information(self, T("app.title"),
                                f"{T('about.text')}\n\n{__version__}")

    def on_help(self) -> None:
        from noesis_ebook_translator.ui import HelpDialog
        HelpDialog(get_language(), parent=self).exec()

    def on_settings(self) -> None:
        from noesis_ebook_translator.ui import SettingsDialog
        dialog = SettingsDialog(self, apply_theme_cb=self._apply_theme_preview)
        if dialog.exec():
            values = dialog.apply()
            self.chk_reduce.setChecked(bool(values.get("reduce_motion")))
            self._reduce_motion = bool(values.get("reduce_motion"))
            self.progress.set_reduce_motion(self._reduce_motion)
            if values.get("ui_language") != get_language():
                QMessageBox.information(self, T("app.title"),
                                        T("msg.restart_language"))
            QMessageBox.information(self, T("app.title"), T("msg.settings_saved"))

    def _apply_theme_preview(self, mode: str) -> None:
        from noesis_ebook_translator.ui import apply_theme
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, mode, reader=self.reader.backend)

    def on_wizard(self) -> None:
        from noesis_ebook_translator.ui import OnboardingWizard
        wizard = OnboardingWizard(self)
        if wizard.exec():
            QMessageBox.information(self, T("app.title"), T("msg.wizard_done"))

    def on_export(self) -> None:
        from noesis_ebook_translator.ui import ExportDialog
        translated = None
        if self._input_path:
            entry = self.reader.session.library.get_book(self._input_path)
            translated = (entry or {}).get("translated_path") or None
        ExportDialog(self._input_path, translated, self).exec()

    def on_split(self) -> None:
        from noesis_ebook_translator import segment
        if not self._input_path:
            QMessageBox.warning(self, T("app.title"), T("msg.no_input"))
            return
        directory = QFileDialog.getExistingDirectory(self, T("action.split"))
        if not directory:
            return
        try:
            written = segment.split_epub(self._input_path, directory)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, T("action.split"), str(exc))
            return
        QMessageBox.information(self, T("action.split"),
                                T("msg.export_done").format("\n".join(written)))

    def on_merge(self) -> None:
        from noesis_ebook_translator import segment
        paths, _ = QFileDialog.getOpenFileNames(
            self, T("action.merge"), "", "EPUB (*.epub)")
        if len(paths) < 1:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, T("action.merge"), "merged.epub", "EPUB (*.epub)")
        if not target:
            return
        try:
            out = segment.merge_epubs(paths, target)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, T("action.merge"), str(exc))
            return
        QMessageBox.information(self, T("action.merge"),
                                T("msg.export_done").format(out))

    def on_quality(self) -> None:
        from noesis_ebook_translator.ui.quality_dialog import QualityDialog
        translated = None
        if self._input_path:
            entry = self.reader.session.library.get_book(self._input_path)
            translated = (entry or {}).get("translated_path") or None

        def judge_factory():
            from noesis_ebook_translator.quality import make_engine_judge
            return make_engine_judge(
                self.cmb_engine.currentText(),
                self.cmb_source.currentText(), self.cmb_target.currentText())

        QualityDialog(self._input_path, translated,
                      judge_factory=judge_factory, parent=self).exec()

    def _load_figures(self) -> None:
        if self._input_path:
            self.figures.set_source(self._input_path)
            self.figures.load_current()
        self.tabs.setCurrentWidget(self.figures)

    def _load_tables(self) -> None:
        if self._input_path:
            self.tables.set_source(self._input_path)
            self.tables.load_current()
        self.tabs.setCurrentWidget(self.tables)

    def _load_texts(self) -> None:
        if self._input_path:
            self.texts.set_source(self._input_path)
            self.texts.load_current()
        self.tabs.setCurrentWidget(self.texts)

    def on_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.status.set_base_text(T("status.canceled"))

    def on_translate(self) -> None:
        if self.worker is not None:
            return
        if not self._input_path:
            QMessageBox.warning(self, T("app.title"), T("msg.no_input"))
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
        self._populate_chapter_progress()
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
        self._highlight_chapter(fraction)
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
        QMessageBox.information(self, T("app.title"), T("msg.done").format(path))

    def _on_failed(self, message: str) -> None:
        self.progress.set_busy(False)
        self.status.stop_busy()
        self.status.set_base_text(T("status.failed"))
        self.log.appendPlainText(message)
        QMessageBox.critical(self, T("app.title"), message.splitlines()[-1])

    def _on_worker_done(self) -> None:
        self.worker = None
        self.btn_translate.setEnabled(True)
        self.btn_cancel.setEnabled(False)


def main(argv: list[str] | None = None) -> int:
    appconfig.ensure_defaults()
    settings = appconfig.load_settings()
    set_language(settings.get("ui_language", "it"))
    # The full reader (foliate-js) needs QtWebEngine imported and the private
    # ``app://`` scheme registered *before* the QApplication is created.
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

    # Onboarding wizard on first run (re-runnable from Settings).
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
