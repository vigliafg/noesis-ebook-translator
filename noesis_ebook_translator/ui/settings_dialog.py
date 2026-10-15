"""Settings dialog (appearance, language, behaviour) + wizard relaunch."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QPushButton,
    QVBoxLayout)

from .. import appconfig
from .. import theme as theme_mod
from ..i18n import LANGUAGES, T
from ..reader import available_backends

__all__ = ["SettingsDialog"]


class SettingsDialog(QDialog):
    def __init__(self, parent=None, apply_theme_cb=None) -> None:
        super().__init__(parent)
        self._apply_theme_cb = apply_theme_cb
        self.setWindowTitle(T("action.settings"))
        self.resize(460, 300)
        settings = appconfig.load_settings()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.cmb_language = QComboBox()
        for code in LANGUAGES:
            self.cmb_language.addItem(LANGUAGES[code], code)
        self._select(self.cmb_language, settings.get("ui_language", "it"))
        self.cmb_theme = QComboBox()
        for mode in theme_mod.theme_choices():
            self.cmb_theme.addItem(T(f"theme.{mode}"), mode)
        self._select(self.cmb_theme, settings.get("ui_theme", "system"))
        self.chk_reduce = QCheckBox(T("label.reduce_motion"))
        self.chk_reduce.setChecked(bool(settings.get("reduce_motion", False)))
        self.cmb_reader = QComboBox()
        for backend in available_backends():
            self.cmb_reader.addItem(T(f"backend.{backend}"), backend)
        self._select(self.cmb_reader, settings.get("reader_backend", "lite"))

        form.addRow(T("label.ui_language"), self.cmb_language)
        form.addRow(T("label.theme"), self.cmb_theme)
        form.addRow("", self.chk_reduce)
        form.addRow(T("label.reader_backend"), self.cmb_reader)
        layout.addLayout(form)

        self.btn_wizard = QPushButton(T("action.wizard"))
        self.btn_wizard.clicked.connect(self._relaunch_wizard)
        layout.addWidget(self.btn_wizard)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.cmb_theme.currentIndexChanged.connect(self._preview_theme)

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _preview_theme(self) -> None:
        if self._apply_theme_cb is not None:
            self._apply_theme_cb(self.cmb_theme.currentData())

    def _relaunch_wizard(self) -> None:
        from .wizard import OnboardingWizard
        OnboardingWizard(self).exec()

    def changes(self) -> dict:
        return {
            "ui_language": self.cmb_language.currentData(),
            "ui_theme": self.cmb_theme.currentData(),
            "reduce_motion": self.chk_reduce.isChecked(),
            "reader_backend": self.cmb_reader.currentData() or "lite",
        }

    def apply(self) -> dict:
        values = self.changes()
        appconfig.save_settings(values)
        return values
