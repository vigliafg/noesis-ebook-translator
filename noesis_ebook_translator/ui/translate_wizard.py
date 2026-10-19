"""Translation wizards: translate a whole book or selected chapters.

Both wizards share the engine/options/output pages; the chapters wizard adds
chapter selection and a grouping choice (one EPUB per chapter or a single EPUB).
``TranslateWizard(...).config()`` returns a plain dict the caller uses to start
the translation.
"""
from __future__ import annotations

import os
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QRadioButton, QSpinBox, QVBoxLayout, QWizard, QWizardPage)

from .. import appconfig, book as book_mod, chapters as chapters_mod
from ..engines.languages import google as GOOGLE_LANGUAGES
from ..i18n import T
from .analysis_page import AnalysisPage
from .estimate_page import EstimatePage
from .provider_test import ModelTestWidget

__all__ = ["TranslateWizard"]


class TranslateWizard(QWizard):
    def __init__(self, parent=None, *, mode: str = "book",
                 input_path: str | None = None,
                 source: str = "English", target: str = "Italian",
                 engine: str | None = None,
                 model_test_runner=None, synchronous_tests: bool = False,
                 analysis_runner=None) -> None:
        super().__init__(parent)
        self.mode = "chapters" if mode == "chapters" else "book"
        self.input_path = input_path
        self._shown = False
        self._segments_cache: tuple[tuple, list[dict]] | None = None
        self._segments_lock = threading.Lock()
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
        self.cmb_engine.addItems(appconfig.desktop_engine_names())
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
        self.test_model = ModelTestWidget(
            self, runner=model_test_runner, synchronous=synchronous_tests)
        self.test_model.setVisible(False)
        engine_form.addRow("", self.test_model)
        self.cmb_engine.currentTextChanged.connect(self._on_engine_changed)
        self.cmb_model.currentTextChanged.connect(self._schedule_model_test)
        self.edt_api_key.editingFinished.connect(self._schedule_model_test)
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
        # A reasoning model spends the batch's token budget on reasoning and
        # truncates the JSON (measured: 4 of 6 replies), so the two options are
        # mutually exclusive instead of failing at the end of the book.
        self.chk_batch.setToolTip(T("label.batch_hint"))
        batch_row = QHBoxLayout()
        self.lbl_batch_size = QLabel(T("label.batch_size"))
        self.spn_batch = QSpinBox()
        self.spn_batch.setRange(1, 50)
        self.spn_batch.setValue(int(settings.get("batch_size", 20) or 20))
        self.spn_batch.setToolTip(T("label.batch_hint"))
        batch_row.addWidget(self.lbl_batch_size)
        batch_row.addWidget(self.spn_batch)
        batch_row.addStretch(1)
        self.chk_batch.toggled.connect(self.spn_batch.setEnabled)
        self.spn_batch.setEnabled(self.chk_batch.isChecked())
        self.chk_sequential = QCheckBox(T("label.sequential"))
        self.chk_sequential.setChecked(
            bool(settings.get("translate_sequential", True)))
        self.lbl_sequential_hint = QLabel(T("label.sequential_hint"))
        self.lbl_sequential_hint.setWordWrap(True)
        parallel_row = QHBoxLayout()
        self.lbl_parallel = QLabel(T("label.parallel"))
        self.spn_parallel = QSpinBox()
        # Up to the engine's executor ceiling (Handler.MAX_WORKERS = 32). The
        # speed test: 49 s at 32 vs 63 s at 20 (streaming, same chapter).
        self.spn_parallel.setRange(1, 32)
        self.spn_parallel.setValue(int(settings.get("translate_parallel", 4) or 4))
        self.spn_parallel.setToolTip(T("label.parallel_hint"))
        parallel_row.addWidget(self.lbl_parallel)
        parallel_row.addWidget(self.spn_parallel)
        parallel_row.addStretch(1)
        for widget in (self.chk_bilingual, self.chk_cache, self.chk_batch,
                       self.chk_sequential, self.lbl_sequential_hint):
            options_layout.addWidget(widget)
        options_layout.addLayout(batch_row)
        options_layout.addLayout(parallel_row)
        self.chk_sequential.toggled.connect(self._update_parallel)
        self._update_parallel(self.chk_sequential.isChecked())
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
        # The suffix is applied automatically: show the real file name up front.
        self.lbl_output_file = QLabel("")
        self.lbl_output_file.setObjectName("bandHint")
        self.lbl_output_file.setWordWrap(True)
        output_form.addRow(T("label.output_file"), self.lbl_output_file)
        folder_row = QHBoxLayout()
        self.edt_folder = QLineEdit(os.path.dirname(input_path or ""))
        browse = QPushButton(T("action.browse"))
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.edt_folder, 1)
        folder_row.addWidget(browse)
        output_form.addRow(T("label.output_folder"), folder_row)
        self.edt_name.textChanged.connect(self._update_output_preview)
        self.edt_folder.textChanged.connect(self._update_output_preview)
        self.cmb_target.currentTextChanged.connect(self._update_output_preview)
        self._output_confirmed = False
        self._update_output_preview()

        self.analysis_page = AnalysisPage(
            self, runner_factory=analysis_runner,
            synchronous=synchronous_tests)
        self.estimate_page = EstimatePage(self, synchronous=synchronous_tests)

        # Order: the analysis decides the style prompt, and the estimate's
        # "already in cache / cost" figure depends on that style.
        self._content_id = self.addPage(content)
        self._engine_id = self.addPage(engine_page)
        self._analysis_id = self.addPage(self.analysis_page)
        self._estimate_id = self.addPage(self.estimate_page)
        self._options_id = self.addPage(options_page)
        self._output_id = self.addPage(output_page)
        self.setButtonText(QWizard.WizardButton.FinishButton, T("action.translate"))

    # ------------------------------------------------------------------
    def _update_parallel(self, sequential: bool) -> None:
        if hasattr(self, "spn_parallel"):
            self.spn_parallel.setEnabled(not sequential)

    def nextId(self) -> int:  # noqa: N802 - Qt naming
        """Skip the analysis page for engines that have no system prompt."""
        current = self.currentId()
        if current == self._analysis_id:
            engine = self.cmb_engine.currentText().strip()
            if not appconfig.engine_supports_prompt(engine):
                return self._estimate_id
        return super().nextId()

    def chapters_key(self) -> tuple:
        return tuple(self.selected_chapters() or ())

    def segments(self, force: bool = False) -> list[dict]:
        """Segments of the current selection, parsed once and shared by pages."""
        if not self.input_path:
            return []
        key = (self.chapters_key(), self.cmb_engine.currentText(),
               self.cmb_target.currentText())
        with self._segments_lock:
            cached = self._segments_cache
            if cached and cached[0] == key and not force:
                return cached[1]
        segments = book_mod.collect_segments(
            self.input_path, chapters=self.selected_chapters() or None,
            engine=self.cmb_engine.currentText(),
            source_lang=self.cmb_source.currentText(),
            target_lang=self.cmb_target.currentText())
        with self._segments_lock:
            self._segments_cache = (key, segments)
        return segments

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        for page in (self.analysis_page, self.estimate_page):
            try:
                page.stop()
            except Exception:  # noqa: BLE001 - closing must always succeed
                pass
        self.test_model.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    def _chapter_choices(self) -> list[tuple[str, str]]:
        """Return ``[(entry_key, label), ...]`` for the chapter selection list.

        The key is the **TOC entry** (href with its anchor), not the file name:
        two chapters that live in one XHTML document must be selectable
        independently, or picking one would translate its neighbour too. The label
        is indented by depth so the tree stays readable.
        """
        out: list[tuple[str, str]] = []
        if not self.input_path:
            return out
        try:
            for chapter in chapters_mod.flatten(
                    chapters_mod.load_chapters(self.input_path)):
                if not chapter.file:
                    continue
                label = "    " * chapter.depth + (chapter.name or chapter.file)
                out.append((chapter.href or chapter.file, label))
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
        self._schedule_model_test()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._shown = True
        self._schedule_model_test()

    def _schedule_model_test(self, *_args) -> None:
        """Probe the chosen model with a short translation before translating.

        Only engines that need an API key are probed; the probe is skipped until
        the wizard is actually shown, so building it in tests/headless never
        touches the network.
        """
        if not self._shown:
            return
        name = self.cmb_engine.currentText().strip()
        info = appconfig.engine_info(name) if name else {"need_api_key": False}
        need_key = bool(info.get("need_api_key"))
        self.test_model.setVisible(need_key)
        if not need_key:
            self.test_model.schedule("", "", "")
            return
        api_key = self.edt_api_key.text().strip()
        model = self.cmb_model.currentText().strip()
        if not api_key or not model:
            self.test_model.schedule("", "", "")
            return
        provider_id = appconfig.provider_id_for_engine(name) or name
        self.test_model.schedule(
            provider_id, api_key, model, engine_name=name,
            endpoint=(appconfig.get_engine_preference(name) or {}).get(
                "endpoint", "") or "")

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, T("label.output_folder"))
        if folder:
            self.edt_folder.setText(folder)

    # ------------------------------------------------------------------
    def output_path(self) -> str:
        """The file this wizard would write (suffix and ``.epub`` included)."""
        folder = (self.edt_folder.text().strip()
                  or os.path.dirname(self.input_path or ""))
        name = self.edt_name.text().strip() or "book"
        return os.path.join(folder, book_mod.output_name(
            name, self.cmb_target.currentText()))

    def _update_output_preview(self, *_args) -> None:
        if not hasattr(self, "lbl_output_file"):  # pragma: no cover - early call
            return
        path = self.output_path()
        self.lbl_output_file.setText(os.path.basename(path))
        self.lbl_output_file.setToolTip(path)

    def accept(self) -> None:
        """Confirm an existing target *before* closing.

        Declining must keep the wizard open with every field intact, which is why
        the question lives here and not after ``exec()``.
        """
        if not self._confirm_overwrite():
            return
        self._output_confirmed = True
        super().accept()

    def _confirm_overwrite(self) -> bool:
        path = self.output_path()
        if not os.path.exists(path):
            return True
        replacing_original = bool(
            self.input_path
            and os.path.abspath(path) == os.path.abspath(self.input_path))
        message = T("msg.overwrite_original" if replacing_original
                    else "msg.overwrite_confirm")
        answer = QMessageBox.question(
            self, T("app.title"), message.format(path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

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
            "batch_size": int(self.spn_batch.value()),
            "sequential": self.chk_sequential.isChecked(),
            "chapters": self.selected_chapters(),
            "grouping": "single" if self.radio_single.isChecked() else "grouped",
            "folder": folder,
            "name": name,
            # Requests sent in parallel when not sequential (1-8).
            "concurrency": (int(self.spn_parallel.value())
                            if not self.chk_sequential.isChecked() else 1),
            # Genre analysis: the addendum appended to the engine's own prompt.
            "style_prompt": self.analysis_page.style_prompt(),
            "genre": self.analysis_page.genre(),
            # The wizard already asked about an existing target in accept().
            "output_confirmed": self._output_confirmed,
        }
