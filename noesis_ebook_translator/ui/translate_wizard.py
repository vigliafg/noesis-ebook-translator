"""Translation wizards: translate a whole book or selected chapters.

Both wizards share the engine/options/output pages; the chapters wizard adds
chapter selection and a grouping choice (one EPUB per chapter or a single EPUB).
``TranslateWizard(...).config()`` returns a plain dict the caller uses to start
the translation.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton,
    QVBoxLayout, QWizard, QWizardPage)

from .. import appconfig, chapters as chapters_mod
from ..engines.languages import google as GOOGLE_LANGUAGES
from ..i18n import T

__all__ = ["TranslateWizard"]


class TranslateWizard(QWizard):
    def __init__(self, parent=None, *, mode: str = "book",
                 input_path: str | None = None,
                 source: str = "English", target: str = "Italian",
                 engine: str | None = None) -> None:
        super().__init__(parent)
        self.mode = "chapters" if mode == "chapters" else "book"
        self.input_path = input_path
        self.setWindowTitle(T("wizard.translate_title"))
        self.resize(680, 540)
        settings = appconfig.load_settings()

        # -- page 1: content + languages ---------------------------------
        content = QWizardPage()
        content.setTitle(T("panel.content"))
        form = QFormLayout(content)
        form.addRow(T("label.input"), QLabel(input_path or "—"))
        self.cmb_source = QComboBox()
        self.cmb_source.addItem("Auto detect")
        self.cmb_source.addItems(list(GOOGLE_LANGUAGES))
        if source:
            self.cmb_source.setCurrentText(source)
        self.cmb_target = QComboBox()
        self.cmb_target.addItems(list(GOOGLE_LANGUAGES))
        if target:
            self.cmb_target.setCurrentText(target)
        form.addRow(T("label.source"), self.cmb_source)
        form.addRow(T("label.target"), self.cmb_target)

        self.chapter_list: QListWidget | None = None
        if self.mode == "chapters":
            self.chapter_list = QListWidget()
            self.chapter_list.setMinimumHeight(160)
            for file_name, name in self._chapter_choices():
                item = QListWidgetItem(name or file_name)
                item.setData(Qt.ItemDataRole.UserRole, file_name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.chapter_list.addItem(item)
            form.addRow(T("label.select_chapters"), self.chapter_list)

        # -- page 2: engine ----------------------------------------------
        engine_page = QWizardPage()
        engine_page.setTitle(T("panel.engine"))
        engine_form = QFormLayout(engine_page)
        self.cmb_engine = QComboBox()
        self.cmb_engine.addItems(appconfig.engine_names())
        if engine:
            idx = self.cmb_engine.findText(engine)
            if idx >= 0:
                self.cmb_engine.setCurrentIndex(idx)
        self.edt_api_key = QLineEdit()
        self.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cmb_model = QComboBox()
        self.cmb_model.setEditable(True)
        engine_form.addRow(T("panel.engine"), self.cmb_engine)
        engine_form.addRow(T("label.api_key"), self.edt_api_key)
        engine_form.addRow(T("label.model"), self.cmb_model)
        self.cmb_engine.currentTextChanged.connect(self._on_engine_changed)
        self._on_engine_changed(self.cmb_engine.currentText())

        # -- page 3: options ---------------------------------------------
        options_page = QWizardPage()
        options_page.setTitle(T("panel.options"))
        options_layout = QVBoxLayout(options_page)
        self.chk_bilingual = QCheckBox(T("label.bilingual"))
        self.chk_bilingual.setChecked(settings.get("translation_position") == "below")
        self.chk_cache = QCheckBox(T("label.cache"))
        self.chk_cache.setChecked(bool(settings.get("cache_enabled", True)))
        self.chk_batch = QCheckBox(T("label.batch"))
        self.chk_batch.setChecked(bool(settings.get("online_batching", False)))
        for widget in (self.chk_bilingual, self.chk_cache, self.chk_batch):
            options_layout.addWidget(widget)
        self.radio_grouped = QRadioButton(T("grouping.grouped"))
        self.radio_single = QRadioButton(T("grouping.single"))
        self.radio_grouped.setChecked(True)
        if self.mode == "chapters":
            options_layout.addSpacing(8)
            options_layout.addWidget(QLabel(T("label.grouping")))
            options_layout.addWidget(self.radio_grouped)
            options_layout.addWidget(self.radio_single)

        # -- page 4: output ----------------------------------------------
        output_page = QWizardPage()
        output_page.setTitle(T("panel.output"))
        output_form = QFormLayout(output_page)
        base = os.path.splitext(os.path.basename(input_path or "book.epub"))[0]
        self.edt_name = QLineEdit(base)
        output_form.addRow(T("label.output_name"), self.edt_name)
        folder_row = QHBoxLayout()
        self.edt_folder = QLineEdit(os.path.dirname(input_path or ""))
        browse = QPushButton(T("action.browse"))
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.edt_folder, 1)
        folder_row.addWidget(browse)
        output_form.addRow(T("label.output_folder"), folder_row)

        self.addPage(content)
        self.addPage(engine_page)
        self.addPage(options_page)
        self.addPage(output_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, T("action.translate"))

    # ------------------------------------------------------------------
    def _chapter_choices(self) -> list[tuple[str, str]]:
        """Return ``[(file_name, name), ...]`` for the chapter selection list."""
        out: list[tuple[str, str]] = []
        if not self.input_path:
            return out
        try:
            for chapter in chapters_mod.flatten(
                    chapters_mod.load_chapters(self.input_path)):
                if chapter.file:
                    out.append((chapter.file, chapter.name or chapter.file))
        except Exception:  # noqa: BLE001
            out = []
        return out

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
        if pref.get("model"):
            self.cmb_model.setCurrentText(pref["model"])
        keys = pref.get("api_keys") or []
        self.edt_api_key.setText(keys[0] if keys else "")

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, T("label.output_folder"))
        if folder:
            self.edt_folder.setText(folder)

    # ------------------------------------------------------------------
    def selected_chapters(self) -> list[str]:
        if self.chapter_list is None:
            return []
        result = []
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def config(self) -> dict:
        folder = self.edt_folder.text().strip() or os.path.dirname(self.input_path or "")
        name = self.edt_name.text().strip() or "book"
        return {
            "source": self.cmb_source.currentText(),
            "target": self.cmb_target.currentText(),
            "engine": self.cmb_engine.currentText(),
            "api_key": self.edt_api_key.text().strip(),
            "model": self.cmb_model.currentText().strip(),
            "bilingual": self.chk_bilingual.isChecked(),
            "cache": self.chk_cache.isChecked(),
            "batching": self.chk_batch.isChecked(),
            "chapters": self.selected_chapters(),
            "grouping": "single" if self.radio_single.isChecked() else "grouped",
            "folder": folder,
            "name": name,
        }
