"""Central Settings dialog: everything in one place, organised in tabs.

Reached from the gear button (and ``Ctrl+,``). The tabs cover general options,
the reader, translation, quality, export, paths/data and help/about.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .. import appconfig
from .. import theme as theme_mod
from ..engines.languages import google as GOOGLE_LANGUAGES
from ..i18n import LANGUAGES, T, get_language
from ..reader import available_backends
from .provider_slots import ProviderSlotRow

__all__ = ["SettingsDialog"]


class SettingsDialog(QDialog):
    applied = pyqtSignal(dict)

    def __init__(self, parent=None, apply_theme_cb=None, *,
                 model_test_runner=None, models_fetcher=None,
                 synchronous_tests: bool = False) -> None:
        super().__init__(parent)
        self._apply_theme_cb = apply_theme_cb
        self._model_test_runner = model_test_runner
        self._models_fetcher = models_fetcher
        self._synchronous_tests = synchronous_tests
        self.setWindowTitle(T("action.settings"))
        self.resize(680, 560)
        self._settings = appconfig.load_settings()

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._build_general()
        self._build_reader()
        self._build_translation()
        self._build_providers()
        self._build_quality()
        self._build_export()
        self._build_paths()
        self._build_about()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ pages
    def _page(self, key: str) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        layout.addLayout(form)
        layout.addStretch(1)
        self.tabs.addTab(page, T(f"settings.tab.{key}").replace("&", "&&"))
        return page, form

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _build_general(self) -> None:
        _page, form = self._page("general")
        self.cmb_language = QComboBox()
        for code in LANGUAGES:
            self.cmb_language.addItem(LANGUAGES[code], code)
        self._select(self.cmb_language, self._settings.get("ui_language", "it"))
        self.cmb_theme = QComboBox()
        for mode in theme_mod.theme_choices():
            self.cmb_theme.addItem(T(f"theme.{mode}"), mode)
        self._select(self.cmb_theme, self._settings.get("ui_theme", "system"))
        self.chk_reduce = QCheckBox(T("label.reduce_motion"))
        self.chk_reduce.setChecked(bool(self._settings.get("reduce_motion", False)))
        form.addRow(T("label.ui_language"), self.cmb_language)
        form.addRow(T("label.theme"), self.cmb_theme)
        form.addRow("", self.chk_reduce)
        self.cmb_theme.currentIndexChanged.connect(self._preview_theme)

    def _build_reader(self) -> None:
        _page, form = self._page("reader")
        self.cmb_backend = QComboBox()
        self.cmb_backend.addItem(T("backend.auto"), "auto")
        for backend in available_backends():
            self.cmb_backend.addItem(T(f"backend.{backend}"), backend)
        self._select(self.cmb_backend, self._settings.get("reader_backend", "auto"))
        self.cmb_reader_theme = QComboBox()
        for name in ("light", "sepia", "dark"):
            self.cmb_reader_theme.addItem(T(f"theme.{name}"), name)
        self._select(self.cmb_reader_theme, self._settings.get("reader_theme", "light"))
        self.cmb_font = QComboBox()
        self.cmb_font.addItems(["serif", "sans-serif", "monospace"])
        self._select(self.cmb_font, self._settings.get("reader_font", "serif"))
        self.cmb_line = QComboBox()
        for value in ("1.0", "1.2", "1.4", "1.5", "1.8", "2.0"):
            self.cmb_line.addItem(value, float(value))
        self._select(self.cmb_line, float(self._settings.get("reader_line_height", 1.5)))
        self.chk_justify = QCheckBox(T("label.justify"))
        self.chk_justify.setChecked(bool(self._settings.get("reader_justify", True)))
        self.chk_hyphenate = QCheckBox(T("label.hyphenate"))
        self.chk_hyphenate.setChecked(bool(self._settings.get("reader_hyphenate", True)))
        self.cmb_flow = QComboBox()
        self.cmb_flow.addItem(T("flow.paginated"), "paginated")
        self.cmb_flow.addItem(T("flow.scrolled"), "scrolled")
        self._select(self.cmb_flow, self._settings.get("reader_flow", "paginated"))
        self.chk_spread = QCheckBox(T("label.spread"))
        self.chk_spread.setChecked(bool(self._settings.get("reader_spread", False)))
        form.addRow(T("label.reader_backend"), self.cmb_backend)
        form.addRow(T("label.reader_theme"), self.cmb_reader_theme)
        form.addRow(T("label.font"), self.cmb_font)
        form.addRow(T("label.line_height"), self.cmb_line)
        form.addRow("", self.chk_justify)
        form.addRow("", self.chk_hyphenate)
        form.addRow(T("label.flow"), self.cmb_flow)
        form.addRow("", self.chk_spread)

    def _build_translation(self) -> None:
        _page, form = self._page("translation")
        self.cmb_engine = QComboBox()
        # The curated providers are owned by the Provider page; here only the
        # verbatim plugin engines are edited.
        self.cmb_engine.addItems(appconfig.legacy_engine_names())
        engine = self._settings.get("translate_engine")
        if engine:
            index = self.cmb_engine.findText(engine)
            if index >= 0:
                self.cmb_engine.setCurrentIndex(index)
        self.edt_api_key = QLineEdit()
        self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cmb_model = QComboBox()
        self.cmb_model.setEditable(True)
        self.edt_prompt = QLineEdit()
        self.cmb_source = QComboBox()
        self.cmb_source.addItem("Auto detect")
        self.cmb_source.addItems(list(GOOGLE_LANGUAGES))
        self.cmb_source.setCurrentText(self._settings.get("ui_source_lang", "English"))
        self.cmb_target = QComboBox()
        self.cmb_target.addItems(list(GOOGLE_LANGUAGES))
        self.cmb_target.setCurrentText(self._settings.get("ui_target_lang", "Italian"))
        self.cmb_position = QComboBox()
        for key, value in (("position.only", "only"), ("position.below", "below"),
                           ("position.above", "above")):
            self.cmb_position.addItem(T(key), value)
        self._select(self.cmb_position,
                     self._settings.get("translation_position", "only"))
        self.chk_cache = QCheckBox(T("label.cache"))
        self.chk_cache.setChecked(bool(self._settings.get("cache_enabled", True)))
        self.chk_batch = QCheckBox(T("label.batch"))
        self.chk_batch.setChecked(bool(self._settings.get("online_batching", False)))
        self.edt_reserve = QLineEdit(
            ", ".join(self._settings.get("reserve_rules") or []))
        form.addRow(T("panel.engine"), self.cmb_engine)
        form.addRow(T("label.api_key"), self.edt_api_key)
        form.addRow(T("label.model"), self.cmb_model)
        form.addRow(T("label.prompt"), self.edt_prompt)
        form.addRow(T("label.source"), self.cmb_source)
        form.addRow(T("label.target"), self.cmb_target)
        form.addRow(T("label.position"), self.cmb_position)
        form.addRow("", self.chk_cache)
        form.addRow("", self.chk_batch)
        form.addRow(T("panel.rules"), self.edt_reserve)
        self.cmb_engine.currentTextChanged.connect(self._on_engine_changed)
        self._on_engine_changed(self.cmb_engine.currentText())

    def _build_providers(self) -> None:
        page = QWidget()
        outer = QVBoxLayout(page)
        hint = QLabel(T("settings.providers_hint"))
        hint.setWordWrap(True)
        outer.addWidget(hint)
        actions = QHBoxLayout()
        self.btn_refresh_all = QPushButton(T("action.refresh_all_models"))
        self.btn_refresh_all.clicked.connect(self._refresh_all_models)
        actions.addWidget(self.btn_refresh_all)
        actions.addStretch(1)
        outer.addLayout(actions)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        self._slot_rows: list[ProviderSlotRow] = []
        for index, slot in enumerate(appconfig.provider_slots()):
            row = ProviderSlotRow(
                index, model_test_runner=self._model_test_runner,
                models_fetcher=self._models_fetcher,
                synchronous_tests=self._synchronous_tests)
            row.set_values(slot)
            inner_layout.addWidget(row)
            self._slot_rows.append(row)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.tabs.addTab(page, T("settings.tab.providers"))

    def _refresh_all_models(self) -> None:
        """Regenerate the model list of every configured provider."""
        for row in self._slot_rows:
            if row.can_refresh():
                row._refresh_models()

    def _build_quality(self) -> None:
        _page, form = self._page("quality")
        self.spn_samples = QSpinBox()
        self.spn_samples.setRange(1, 100)
        self.spn_samples.setValue(int(self._settings.get("quality_samples", 10)))
        self.spn_threshold = QSpinBox()
        self.spn_threshold.setRange(0, 100)
        self.spn_threshold.setValue(int(self._settings.get("quality_threshold", 60)))
        self.cmb_judge = QComboBox()
        self.cmb_judge.addItem(T("panel.engine") + ": auto", "")
        self.cmb_judge.addItems(appconfig.engine_names())
        current_judge = self._settings.get("quality_judge_engine", "")
        index = self.cmb_judge.findText(current_judge)
        if index >= 0:
            self.cmb_judge.setCurrentIndex(index)
        form.addRow(T("label.samples"), self.spn_samples)
        form.addRow(T("label.threshold"), self.spn_threshold)
        form.addRow(T("panel.engine"), self.cmb_judge)

    def _build_export(self) -> None:
        from .. import exporter
        _page, form = self._page("export")
        self.cmb_format = QComboBox()
        for fmt in exporter.supported_exports():
            self.cmb_format.addItem(T(f"format.{fmt}"), fmt)
        self._select(self.cmb_format, self._settings.get("export_format", "epub"))
        self.cmb_edition = QComboBox()
        self.cmb_edition.addItem(T("edition.original"), "original")
        self.cmb_edition.addItem(T("edition.translated"), "translated")
        self._select(self.cmb_edition, self._settings.get("export_edition", "original"))
        form.addRow(T("label.format"), self.cmb_format)
        form.addRow(T("label.edition"), self.cmb_edition)

    def _build_paths(self) -> None:
        _page, form = self._page("paths")
        row = QHBoxLayout()
        self.edt_output = QLineEdit(self._settings.get("output_dir", ""))
        browse = QPushButton(T("action.browse"))
        browse.clicked.connect(self._browse_output)
        row.addWidget(self.edt_output, 1)
        row.addWidget(browse)
        form.addRow(T("label.output_dir"), row)
        from ..paths import data_dir
        data = str(data_dir())
        form.addRow(settings_label("settings.database"), QLabel(data))
        actions = QHBoxLayout()
        open_data = QPushButton(T("action.data_dir"))
        open_data.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data)))
        clear = QPushButton(T("action.clear_cache"))
        clear.clicked.connect(self._clear_cache)
        actions.addWidget(open_data)
        actions.addWidget(clear)
        form.addRow("", actions)

    def _build_about(self) -> None:
        from noesis_ebook_translator import EbookTranslator, __version__
        _page, form = self._page("about")
        self.btn_help = QPushButton(T("action.open_online_help"))
        self.btn_help.clicked.connect(self._open_help)
        self.btn_wizard = QPushButton(T("action.wizard"))
        self.btn_wizard.clicked.connect(self._open_wizard)
        self.chk_reset_onboarding = QCheckBox(T("settings.reset_onboarding"))
        form.addRow(self.btn_help)
        form.addRow(self.btn_wizard)
        form.addRow("", self.chk_reset_onboarding)
        from ..help import help_url
        form.addRow(QUrl(help_url(get_language())).toString() and T("action.help"),
                    QLabel(f"{T('app.title')} {__version__} · "
                           f"Engine {EbookTranslator.__version__}"))
        form.addRow(T("about.text").splitlines()[0] if T("about.text") else "",
                    QLabel("GNU GPL v3.0 · bookfere Ebook Translator"))

    # ------------------------------------------------------------------ actions
    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, T("label.output_dir"))
        if folder:
            self.edt_output.setText(folder)

    def _clear_cache(self) -> None:
        import shutil
        from ..paths import data_dir
        cache = data_dir() / "cache"
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)

    def _open_help(self) -> None:
        from ..help import help_url
        QDesktopServices.openUrl(QUrl(help_url(get_language())))

    def _open_wizard(self) -> None:
        from .wizard import OnboardingWizard
        OnboardingWizard(self).exec()

    def _on_engine_changed(self, name: str) -> None:
        info = appconfig.engine_info(name)
        self.edt_api_key.setEnabled(info["need_api_key"])
        self.edt_api_key.setPlaceholderText(info["api_key_hint"])
        self.cmb_model.clear()
        models = info["models"] or []
        if models:
            self.cmb_model.addItems(models)
            self.cmb_model.setEnabled(True)
        else:
            self.cmb_model.setEnabled(False)
        pref = appconfig.get_engine_preference(name)
        keys = pref.get("api_keys") or []
        self.edt_api_key.setText(keys[0] if keys else "")
        self.cmb_model.setCurrentText(pref.get("model", "") or "")
        self.edt_prompt.setText(pref.get("prompt", "") or "")

    def _preview_theme(self) -> None:
        if self._apply_theme_cb is not None:
            self._apply_theme_cb(self.cmb_theme.currentData())

    # ------------------------------------------------------------------ values
    def values(self) -> dict:
        return {
            "ui_language": self.cmb_language.currentData(),
            "ui_theme": self.cmb_theme.currentData(),
            "reduce_motion": self.chk_reduce.isChecked(),
            "reader_backend": self.cmb_backend.currentData() or "auto",
            "reader_theme": self.cmb_reader_theme.currentData() or "light",
            "reader_font": self.cmb_font.currentData() or "serif",
            "reader_line_height": float(self.cmb_line.currentData() or 1.5),
            "reader_justify": self.chk_justify.isChecked(),
            "reader_hyphenate": self.chk_hyphenate.isChecked(),
            "reader_flow": self.cmb_flow.currentData() or "paginated",
            "reader_spread": self.chk_spread.isChecked(),
            "translate_engine": self.cmb_engine.currentText(),
            "ui_source_lang": self.cmb_source.currentText(),
            "ui_target_lang": self.cmb_target.currentText(),
            "translation_position": self.cmb_position.currentData() or "only",
            "cache_enabled": self.chk_cache.isChecked(),
            "online_batching": self.chk_batch.isChecked(),
            "reserve_rules": [p.strip() for p in self.edt_reserve.text().split(",")
                              if p.strip()],
            "quality_samples": self.spn_samples.value(),
            "quality_threshold": self.spn_threshold.value(),
            "quality_judge_engine": self.cmb_judge.currentText()
            if self.cmb_judge.currentIndex() > 0 else "",
            "export_format": self.cmb_format.currentData() or "epub",
            "export_edition": self.cmb_edition.currentData() or "original",
            "output_dir": self.edt_output.text().strip(),
            "provider_slots": [row.values() for row in self._slot_rows],
            "onboarding_done": False if self.chk_reset_onboarding.isChecked()
            else self._settings.get("onboarding_done", False),
        }

    def apply(self) -> dict:
        values = self.values()
        engine = values["translate_engine"]
        appconfig.save_settings(values)
        appconfig.set_provider_slots(values.get("provider_slots") or [])
        appconfig.set_engine_preference(
            engine,
            api_keys=[self.edt_api_key.text().strip()]
            if self.edt_api_key.text().strip() else [],
            model=self.cmb_model.currentText().strip() or None,
            prompt=self.edt_prompt.text().strip() or None)
        self.applied.emit(values)
        return values


def settings_label(key: str) -> QLabel:
    return QLabel(T(key))
