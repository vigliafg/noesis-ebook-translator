"""One configurable provider slot (Settings → Providers).

Each row is a small group box: enable it, pick a curated provider, paste the API
key, choose the model (with a live-refresh button) and let the shared
:class:`~noesis_ebook_translator.ui.provider_test.ModelTestWidget` prove that the
model really translates. Both the model fetch and the probe are injectable so
the GUI tests never hit the network.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QWidget)

from .. import appconfig, provider_catalog
from ..i18n import T
from .provider_test import ModelTestWidget, run_async

__all__ = ["ProviderSlotRow"]


class ProviderSlotRow(QGroupBox):
    """A single provider slot."""

    def __init__(self, index: int, *, parent=None,
                 model_test_runner: Callable[..., Any] | None = None,
                 models_fetcher: Callable[..., Any] | None = None,
                 synchronous_tests: bool = False) -> None:
        super().__init__(T("label.provider_slot").format(n=index + 1), parent)
        self.index = index
        self._fetcher = models_fetcher or appconfig.refresh_provider_models
        self._auto_refreshed: set[str] = set()
        self._synchronous = synchronous_tests

        form = QFormLayout(self)
        self.chk_enabled = QCheckBox(T("label.enable"))
        form.addRow("", self.chk_enabled)

        self.cmb_provider = QComboBox()
        self.cmb_provider.addItem("—", "")
        for choice in appconfig.provider_choices():
            self.cmb_provider.addItem(choice["name"], choice["id"])
        form.addRow(T("label.provider"), self.cmb_provider)

        self.edt_key = QLineEdit()
        self.edt_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(T("label.api_key"), self.edt_key)

        self.edt_endpoint = QLineEdit()
        self.edt_endpoint.setPlaceholderText("https://host/v1")
        self.lbl_endpoint = QLabel(T("label.custom_endpoint"))
        form.addRow(self.lbl_endpoint, self.edt_endpoint)

        model_row = QHBoxLayout()
        self.cmb_model = QComboBox()
        self.cmb_model.setEditable(True)
        self.btn_refresh = QPushButton(T("action.refresh_models"))
        model_row.addWidget(self.cmb_model, 1)
        model_row.addWidget(self.btn_refresh)
        form.addRow(T("label.model"), model_row)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        form.addRow("", self.note)

        self.test = ModelTestWidget(self, runner=model_test_runner,
                                    synchronous=synchronous_tests)
        form.addRow("", self.test)

        self.cmb_provider.currentIndexChanged.connect(self._on_provider_changed)
        self.cmb_model.currentTextChanged.connect(self._schedule_test)
        self.edt_key.editingFinished.connect(self._schedule_test)
        self.edt_endpoint.editingFinished.connect(self._schedule_test)
        self.btn_refresh.clicked.connect(self._refresh_models)
        self.chk_enabled.toggled.connect(self._on_enabled_toggled)

        self._update_visibility()

    # ------------------------------------------------------------- state
    def provider_id(self) -> str:
        return self.cmb_provider.currentData() or ""

    def values(self) -> dict[str, Any]:
        return {
            "enabled": self.chk_enabled.isChecked(),
            "provider": self.provider_id(),
            "api_key": self.edt_key.text().strip(),
            "model": self.cmb_model.currentText().strip(),
            "endpoint": self.edt_endpoint.text().strip(),
        }

    def set_values(self, slot: dict[str, Any]) -> None:
        provider_id = str(slot.get("provider") or "")
        index = self.cmb_provider.findData(provider_id)
        self.cmb_provider.blockSignals(True)
        self.cmb_provider.setCurrentIndex(index if index >= 0 else 0)
        self.cmb_provider.blockSignals(False)
        self.chk_enabled.setChecked(bool(slot.get("enabled")))
        self.edt_key.setText(str(slot.get("api_key") or ""))
        self.edt_endpoint.setText(str(slot.get("endpoint") or ""))
        self._reload_models(provider_id)
        model = str(slot.get("model") or "")
        if model:
            self.cmb_model.setCurrentText(model)
        self._update_visibility()
        self._schedule_test()

    # ------------------------------------------------------------ actions
    def _on_provider_changed(self) -> None:
        provider = provider_catalog.get(self.provider_id())
        need_key = bool(provider and not provider.custom)
        self.edt_key.setEnabled(need_key)
        self.edt_key.setPlaceholderText(
            provider.env_hint if provider else T("label.api_key"))
        if provider and not self.edt_key.text() and provider.default_model:
            if not self.cmb_model.currentText().strip():
                self.cmb_model.setCurrentText(provider.default_model)
        self._reload_models(self.provider_id())
        self._update_visibility()
        self._schedule_test()

    def _on_enabled_toggled(self, _checked: bool) -> None:
        self._update_visibility()
        self._schedule_test()

    def _update_visibility(self) -> None:
        provider = provider_catalog.get(self.provider_id())
        is_custom = bool(provider and provider.custom)
        self.lbl_endpoint.setVisible(is_custom)
        self.edt_endpoint.setVisible(is_custom)
        note_key = provider.note if provider else ""
        if note_key:
            self.note.setText(T(note_key))
            self.note.setVisible(True)
        else:
            self.note.setVisible(False)
        active = bool(provider) and self.chk_enabled.isChecked()
        for widget in (self.cmb_provider, self.cmb_model, self.btn_refresh):
            widget.setEnabled(bool(provider))
        self.edt_key.setEnabled(active and bool(provider and not provider.custom))
        self.edt_endpoint.setEnabled(active and is_custom)

    def _reload_models(self, provider_id: str,
                       models: list[str] | None = None) -> None:
        current = self.cmb_model.currentText()
        self.cmb_model.clear()
        if not provider_id:
            return
        if models is None:
            models = appconfig.provider_models(provider_id) or []
        if models:
            self.cmb_model.addItems(list(models))
        if current:
            self.cmb_model.setCurrentText(current)
        elif models:
            self.cmb_model.setCurrentText(models[0])

    def _refresh_models(self) -> None:
        provider_id = self.provider_id()
        if not provider_id:
            return
        key = self.edt_key.text().strip()
        self.btn_refresh.setEnabled(False)

        def done(result: Any) -> None:
            self.btn_refresh.setEnabled(True)
            if isinstance(result, Exception) or not result:
                return
            self._reload_models(provider_id, list(result))
            self._schedule_test()

        if self._synchronous:
            try:
                result: Any = self._fetcher(provider_id, key)
            except Exception as exc:  # noqa: BLE001 - silent fallback
                result = exc
            done(result)
            return
        run_async(lambda: self._fetcher(provider_id, key), done, self)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._auto_refresh()

    def _auto_refresh(self) -> None:
        """Refresh a stale model list once, without the user asking.

        Only for providers whose list is public or when a key is already
        present (a 401 would just be noise), and at most once per row/session.
        """
        provider_id = self.provider_id()
        if not provider_id or provider_id in self._auto_refreshed:
            return
        if not self.chk_enabled.isChecked():
            return
        if not appconfig.models_are_stale(provider_id):
            return
        provider = provider_catalog.get(provider_id)
        if provider is None:
            return
        if not (provider.models_public or self.edt_key.text().strip()):
            return
        self._auto_refreshed.add(provider_id)
        self._refresh_models()

    def _schedule_test(self, *_args) -> None:
        if not self.chk_enabled.isChecked() or not self.provider_id():
            return
        self.test.schedule(self.provider_id(), self.edt_key.text().strip(),
                           self.cmb_model.currentText().strip())

    def stop(self) -> None:
        self.test.stop()
