"""Onboarding wizard (first run) — re-runnable from Settings.

Guides the user through interface language, theme, translation engine (with API
key/model) and the reader backend, then persists everything and sets the
``onboarding_done`` flag.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWizard, QWizardPage)

from .. import appconfig
from .. import theme as theme_mod
from ..i18n import LANGUAGES, T, set_language
from ..reader import available_backends

__all__ = ["OnboardingWizard"]


def _page(title: str, body: str, extra=None) -> QWizardPage:
    page = QWizardPage()
    page.setTitle(title)
    layout = QVBoxLayout(page)
    label = QLabel(body)
    label.setWordWrap(True)
    layout.addWidget(label)
    if extra is not None:
        layout.addWidget(extra)
    layout.addStretch(1)
    return page


class OnboardingWizard(QWizard):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(T("wizard.title"))
        self.resize(640, 460)
        settings = appconfig.load_settings()

        # -- language -----------------------------------------------------
        self.cmb_language = QComboBox()
        for code in LANGUAGES:
            self.cmb_language.addItem(LANGUAGES[code], code)
        current_lang = settings.get("ui_language", "it")
        index = self.cmb_language.findData(current_lang)
        if index >= 0:
            self.cmb_language.setCurrentIndex(index)
        lang_page = _page(T("wizard.language_title"), T("wizard.language_text"),
                          self.cmb_language)

        # -- theme --------------------------------------------------------
        self.cmb_theme = QComboBox()
        for mode in theme_mod.theme_choices():
            self.cmb_theme.addItem(T(f"theme.{mode}"), mode)
        theme_index = self.cmb_theme.findData(settings.get("ui_theme", "system"))
        if theme_index >= 0:
            self.cmb_theme.setCurrentIndex(theme_index)
        theme_page = _page(T("wizard.theme_title"), T("wizard.theme_text"),
                           self.cmb_theme)

        # -- engine -------------------------------------------------------
        self.cmb_engine = QComboBox()
        self.cmb_engine.addItems(appconfig.engine_names())
        engine = settings.get("translate_engine")
        if engine:
            engine_index = self.cmb_engine.findText(engine)
            if engine_index >= 0:
                self.cmb_engine.setCurrentIndex(engine_index)
        self.edt_api_key = QLineEdit()
        self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edt_model = QComboBox()
        self.edt_model.setEditable(True)
        engine_form = QFormLayout()
        engine_form.addRow(T("panel.engine"), self.cmb_engine)
        engine_form.addRow(T("label.api_key"), self.edt_api_key)
        engine_form.addRow(T("label.model"), self.edt_model)
        engine_box = QVBoxLayout()
        engine_page = QWizardPage()
        engine_page.setTitle(T("wizard.engine_title"))
        layout = QVBoxLayout(engine_page)
        intro = QLabel(T("wizard.engine_text"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addLayout(engine_form)
        layout.addStretch(1)
        self.cmb_engine.currentTextChanged.connect(self._on_engine_changed)
        self._on_engine_changed(self.cmb_engine.currentText())

        # -- reader -------------------------------------------------------
        self.cmb_reader = QComboBox()
        for backend in available_backends():
            self.cmb_reader.addItem(T(f"backend.{backend}"), backend)
        reader_index = self.cmb_reader.findData(
            settings.get("reader_backend", "lite"))
        if reader_index >= 0:
            self.cmb_reader.setCurrentIndex(reader_index)
        reader_page = _page(T("wizard.reader_title"), T("wizard.reader_text"),
                            self.cmb_reader)

        # -- finish -------------------------------------------------------
        finish_page = _page(T("wizard.sample_title"), T("wizard.sample_text"))

        self.addPage(_page(T("wizard.welcome_title"), T("wizard.welcome_text")))
        self.addPage(lang_page)
        self.addPage(theme_page)
        self.addPage(engine_page)
        self.addPage(reader_page)
        self.addPage(finish_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, T("wizard.finish"))

    # ------------------------------------------------------------------
    def _on_engine_changed(self, name: str) -> None:
        info = appconfig.engine_info(name)
        self.edt_api_key.setEnabled(info["need_api_key"])
        self.edt_api_key.setPlaceholderText(info["api_key_hint"])
        self.edt_model.clear()
        models = info["models"] or []
        if models:
            self.edt_model.addItems(models)
            self.edt_model.setEnabled(True)
        else:
            self.edt_model.setEnabled(False)
        pref = appconfig.get_engine_preference(name)
        if pref.get("model"):
            self.edt_model.setCurrentText(pref["model"])
        keys = pref.get("api_keys") or []
        self.edt_api_key.setText(keys[0] if keys else "")

    def selected(self) -> dict:
        return {
            "ui_language": self.cmb_language.currentData(),
            "ui_theme": self.cmb_theme.currentData(),
            "translate_engine": self.cmb_engine.currentText(),
            "reader_backend": self.cmb_reader.currentData() or "lite",
            "api_key": self.edt_api_key.text().strip(),
            "model": self.edt_model.currentText().strip(),
        }

    def apply(self) -> dict:
        """Persist the wizard choices and mark onboarding as done."""
        values = self.selected()
        engine = values.pop("translate_engine")
        api_key = values.pop("api_key")
        model = values.pop("model")
        values["translate_engine"] = engine
        values["onboarding_done"] = True
        appconfig.save_settings(values)
        if engine:
            appconfig.set_engine_preference(
                engine, api_keys=[api_key] if api_key else [], model=model or None)
        if values.get("ui_language"):
            set_language(values["ui_language"])
        return values

    def accept(self) -> None:  # noqa: D102 - QWizard hook
        self.apply()
        super().accept()
