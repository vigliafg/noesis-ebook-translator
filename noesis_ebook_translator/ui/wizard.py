"""Onboarding wizard (first run) — re-runnable from Settings.

Guides the user through interface language, theme, translation engine (with API
key/model) and the reader backend, then persists everything and sets the
``onboarding_done`` flag.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWizard, QWizardPage)

from .. import appconfig, provider_catalog
from .. import theme as theme_mod
from ..i18n import LANGUAGES, T, set_language
from ..reader import available_backends
from .provider_test import ModelTestWidget

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
    def __init__(self, parent=None, *, model_test_runner=None,
                 models_fetcher=None, synchronous_tests: bool = False) -> None:
        super().__init__(parent)
        self._model_test_runner = model_test_runner
        self._models_fetcher = models_fetcher
        self._synchronous_tests = synchronous_tests
        self.setWindowTitle(T("wizard.title"))
        self.resize(640, 480)
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

        # -- provider -----------------------------------------------------
        self.cmb_provider = QComboBox()
        self.cmb_provider.addItem("—", "")
        for choice in appconfig.provider_choices():
            self.cmb_provider.addItem(choice["name"], choice["id"])
        self.edt_api_key = QLineEdit()
        self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edt_model = QComboBox()
        self.edt_model.setEditable(True)
        self.lbl_provider_note = QLabel("")
        self.lbl_provider_note.setWordWrap(True)
        self.lbl_provider_note.setVisible(False)
        self.test_provider = ModelTestWidget(
            self, runner=model_test_runner, synchronous=synchronous_tests)
        provider_form = QFormLayout()
        provider_form.addRow(T("label.provider"), self.cmb_provider)
        provider_form.addRow(T("label.api_key"), self.edt_api_key)
        provider_form.addRow(T("label.model"), self.edt_model)
        provider_page = QWizardPage()
        provider_page.setTitle(T("wizard.engine_title"))
        layout = QVBoxLayout(provider_page)
        intro = QLabel(T("wizard.engine_text"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addLayout(provider_form)
        layout.addWidget(self.lbl_provider_note)
        layout.addWidget(self.test_provider)
        layout.addStretch(1)
        self.cmb_provider.currentIndexChanged.connect(self._on_provider_changed)
        self.edt_model.currentTextChanged.connect(self._schedule_test)
        self.edt_api_key.editingFinished.connect(self._schedule_test)
        self._on_provider_changed()

        # -- reader -------------------------------------------------------
        self.cmb_reader = QComboBox()
        self.cmb_reader.addItem(T("backend.auto"), "auto")
        for backend in available_backends():
            self.cmb_reader.addItem(T(f"backend.{backend}"), backend)
        reader_index = self.cmb_reader.findData(
            settings.get("reader_backend", "auto"))
        if reader_index >= 0:
            self.cmb_reader.setCurrentIndex(reader_index)
        reader_page = _page(T("wizard.reader_title"), T("wizard.reader_text"),
                            self.cmb_reader)

        # -- finish -------------------------------------------------------
        finish_page = _page(T("wizard.sample_title"), T("wizard.sample_text"))

        self.addPage(_page(T("wizard.welcome_title"), T("wizard.welcome_text")))
        self.addPage(lang_page)
        self.addPage(theme_page)
        self.addPage(provider_page)
        self.addPage(reader_page)
        self.addPage(finish_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, T("wizard.finish"))

    # ------------------------------------------------------------------
    def _current_provider(self):
        return provider_catalog.get(self.cmb_provider.currentData() or "")

    def _on_provider_changed(self, *_args) -> None:
        provider = self._current_provider()
        self.edt_api_key.setEnabled(bool(provider and not provider.custom))
        if provider:
            self.edt_api_key.setPlaceholderText(
                provider.env_hint or T("label.api_key"))
        self.edt_model.clear()
        if provider is not None:
            models = appconfig.provider_models(provider.id) or []
            if models:
                self.edt_model.addItems(models)
            if provider.default_model:
                self.edt_model.setCurrentText(provider.default_model)
        note = provider.note if provider else ""
        self.lbl_provider_note.setText(T(note) if note else "")
        self.lbl_provider_note.setVisible(bool(note))
        self._prefill_from_slots(provider.id if provider else "")
        self._schedule_test()

    def _prefill_from_slots(self, provider_id: str) -> None:
        """Reuse the key/model already configured in a slot, if any."""
        if not provider_id:
            return
        for slot in appconfig.provider_slots():
            if slot.get("provider") != provider_id or not slot.get("enabled"):
                continue
            if not self.edt_api_key.text() and slot.get("api_key"):
                self.edt_api_key.setText(slot["api_key"])
            if slot.get("model") and not self.edt_model.currentText():
                self.edt_model.setCurrentText(slot["model"])
            return

    def _schedule_test(self, *_args) -> None:
        provider = self._current_provider()
        if provider is None:
            return
        self.test_provider.schedule(provider.id, self.edt_api_key.text().strip(),
                                    self.edt_model.currentText().strip())

    def selected(self) -> dict:
        return {
            "ui_language": self.cmb_language.currentData(),
            "ui_theme": self.cmb_theme.currentData(),
            "reader_backend": self.cmb_reader.currentData() or "auto",
            "provider_id": self.cmb_provider.currentData() or "",
            "api_key": self.edt_api_key.text().strip(),
            "model": self.edt_model.currentText().strip(),
        }

    def apply(self) -> dict:
        """Persist the wizard choices and mark onboarding as done."""
        values = self.selected()
        provider_id = values.pop("provider_id", "")
        api_key = values.pop("api_key", "")
        model = values.pop("model", "")
        values["onboarding_done"] = True
        appconfig.save_settings(values)
        if provider_id:
            engine = provider_catalog.engine_name(provider_id)
            slots = appconfig.provider_slots()
            target = next((slot for slot in slots
                           if slot.get("provider") == provider_id), None)
            if target is None:
                target = next((slot for slot in slots
                               if not slot.get("provider")), None)
            if target is None:
                target = slots[0]
            target.update({"enabled": True, "provider": provider_id,
                           "api_key": api_key, "model": model})
            appconfig.set_provider_slots(slots)
            appconfig.save_settings({"translate_engine": engine})
        if values.get("ui_language"):
            set_language(values["ui_language"])
        return values

    def accept(self) -> None:  # noqa: D102 - QWizard hook
        self.apply()
        super().accept()
