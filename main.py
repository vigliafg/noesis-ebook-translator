#!/usr/bin/env python3
"""Noesis Ebook Translator — desktop GUI (PyQt6 + pyqtribbon).

A translation-only front-end: open an EPUB, pick an engine and the languages,
then translate. All the heavy lifting lives in
:mod:`noesis_ebook_translator.book`, which drives the verbatim Ebook Translator
engine.
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
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from pyqtribbon import RibbonBar

from noesis_ebook_translator import APP_NAME, __version__, appconfig, book, theme
from noesis_ebook_translator.i18n import T, get_language, set_language
from noesis_ebook_translator.reader import ReaderWidget
from noesis_ebook_translator.reader.panels import (
    FiguresWidget, LibraryWidget, PreviewWidget, TablesWidget)
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

    def __init__(self, input_path, output_path, engine, source, target, settings):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.engine = engine
        self.source = source
        self.target = target
        self.settings = settings
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
        panel_engine.addLabel("Engine:")
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

        read_cat = self.ribbon.addCategory("Lettura")
        panel_nav = read_cat.addPanel("Navigazione")
        panel_nav.addLargeButton("◀ Prev", slot=lambda: self.reader.backend.prev_chapter())
        panel_nav.addLargeButton("Next ▶", slot=lambda: self.reader.backend.next_chapter())
        panel_zoom = read_cat.addPanel("Vista")
        panel_zoom.addLargeButton("Zoom +", slot=lambda: self.reader.backend.set_zoom(1))
        panel_zoom.addLargeButton("Zoom −", slot=lambda: self.reader.backend.set_zoom(-1))
        self.btn_parallel = panel_zoom.addLargeButton(
            "Parallelo", slot=lambda: self.reader.btn_parallel.toggle())

        tools_cat = self.ribbon.addCategory("Strumenti")
        panel_lib = tools_cat.addPanel("Libreria")
        panel_lib.addLargeButton(
            "Libreria", slot=lambda: self.tabs.setCurrentWidget(self.library))
        panel_fig = tools_cat.addPanel("Figure")
        panel_fig.addLargeButton("Carica figure", slot=self._load_figures)
        panel_tab = tools_cat.addPanel("Tabelle")
        panel_tab.addLargeButton("Carica tabelle", slot=self._load_tables)
        panel_prev = tools_cat.addPanel("Anteprima")
        panel_prev.addLargeButton(
            "Anteprima", slot=lambda: self.tabs.setCurrentWidget(self.preview))

        info_cat = self.ribbon.addCategory(T("tab.info"))
        panel_about = info_cat.addPanel(T("tab.info"))
        panel_about.addLargeButton("About", slot=self.on_about)

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

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        outer.addWidget(self.progress)

        self.status = QLabel(T("status.ready"))
        outer.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        outer.addWidget(self.log, 1)

        self.reader = ReaderWidget()
        self.reader.statusMessage.connect(self.status.setText)
        self.library = LibraryWidget(self.reader.session)
        self.figures = FiguresWidget()
        self.tables = TablesWidget()
        self.preview = PreviewWidget(self._preview_options)
        self.library.openRequested.connect(self._apply_source)

        self.tabs = QTabWidget()
        self.tabs.addTab(central, "Traduzione")
        self.tabs.addTab(self.reader, "Lettura")
        self.tabs.addTab(self.library, "Libreria")
        self.tabs.addTab(self.figures, "Figure")
        self.tabs.addTab(self.tables, "Tabelle")
        self.tabs.addTab(self.preview, "Anteprima")

        self.setCentralWidget(self.tabs)
        self.resize(1024, 700)
        self._input_path: str | None = None
        self._output_path: str | None = None

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
        self.status.setText(T("status.ready"))
        for panel in (self.figures, self.tables, self.preview):
            panel.set_source(path)
        self.library.add_book(path)
        try:
            self.reader.open_path(path)
            self.tabs.setCurrentWidget(self.reader)
        except Exception as exc:  # noqa: BLE001 - reader is best effort
            self.log.appendPlainText(f"[reader] {exc}")

    # ------------------------------------------------------------ settings
    def _load_settings(self) -> None:
        settings = appconfig.load_settings()
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

    def on_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.status.setText(T("status.canceled"))

    def on_translate(self) -> None:
        if self.worker is not None:
            return
        if not self._input_path:
            QMessageBox.warning(self, T("app.title"), T("msg.no_input"))
            return

        engine = self.cmb_engine.currentText()
        source = self.cmb_source.currentText()
        target = self.cmb_target.currentText()
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
            self._input_path, self._output_path, engine, source, target, settings)
        self.worker.progressed.connect(self._on_progress)
        self.worker.logged.connect(self._on_log)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_worker_done)

        self.log.clear()
        self.btn_translate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status.setText(T("status.translating"))
        self.worker.start()

    # --------------------------------------------------------------- slots
    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        if message:
            self.status.setText(message)

    def _on_log(self, text: str, error: bool) -> None:
        self.log.appendPlainText(text)

    def _on_finished(self, path: str) -> None:
        self.progress.setValue(100)
        self.status.setText(T("status.done"))
        try:
            self.reader.set_translated_path(path)
        except Exception:  # noqa: BLE001
            pass
        QMessageBox.information(self, T("app.title"), T("msg.done").format(path))

    def _on_failed(self, message: str) -> None:
        self.status.setText(T("status.failed"))
        self.log.appendPlainText(message)
        QMessageBox.critical(self, T("app.title"), message.splitlines()[-1])

    def _on_worker_done(self) -> None:
        self.worker = None
        self.btn_translate.setEnabled(True)
        self.btn_cancel.setEnabled(False)


def main(argv: list[str] | None = None) -> int:
    appconfig.ensure_defaults()
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
    app.setStyleSheet(theme.stylesheet(
        appconfig.load_settings().get("ui_theme", "system")))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
