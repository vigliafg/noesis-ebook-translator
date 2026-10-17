"""Wizard page: analyse the book and propose a style system prompt.

The chosen model reads a spread of excerpts and describes genre, register, tone,
audience and era. :mod:`noesis_ebook_translator.text_analysis` turns that into a
**style addendum** appended to the engine's own system prompt for the run. The
user can read and edit it, apply it or skip it, and a failure never blocks the
translation (the fallback is a generic, integrity-preserving addendum).

The runner is injectable so the page can be tested without a network.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtWidgets import (
    QCheckBox, QFormLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWizardPage)

from .. import appconfig, chapters as chapters_mod, text_analysis
from ..estimate import format_usd
from ..i18n import T
from .provider_test import detach, run_async

__all__ = ["AnalysisPage"]


class AnalysisPage(QWizardPage):
    """Status + detected fields + editable style prompt."""

    def __init__(self, parent=None, *, runner_factory: Callable[..., Any] | None = None,
                 synchronous: bool = False) -> None:
        super().__init__(parent)
        self.setTitle(T("wizard.analysis_title"))
        self._runner_factory = runner_factory or text_analysis.make_runner
        self._synchronous = synchronous
        self._key: tuple | None = None
        self._result: text_analysis.AnalysisResult | None = None
        self._worker = None

        layout = QVBoxLayout(self)
        intro = QLabel(T("analysis.intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        form = QFormLayout()
        self.lbl_fields = QLabel("—")
        self.lbl_fields.setWordWrap(True)
        form.addRow(T("analysis.detected"), self.lbl_fields)
        self.lbl_cost = QLabel("")
        self.lbl_cost.setWordWrap(True)
        form.addRow(T("analysis.cost_label"), self.lbl_cost)
        layout.addLayout(form)

        self.chk_apply = QCheckBox(T("analysis.apply"))
        self.chk_apply.setChecked(True)
        layout.addWidget(self.chk_apply)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("analysisPrompt")
        self.editor.setMinimumHeight(140)
        self.editor.setPlaceholderText(T("analysis.placeholder"))
        layout.addWidget(self.editor, 1)

        self.privacy = QLabel(T("analysis.privacy_auto"))
        self.privacy.setObjectName("bandHint")
        self.privacy.setWordWrap(True)
        layout.addWidget(self.privacy)

        buttons = QVBoxLayout()
        self.btn_rerun = QPushButton(T("analysis.reanalyze"))
        self.btn_rerun.clicked.connect(lambda: self._maybe_start(force=True))
        self.btn_skip = QPushButton(T("analysis.skip"))
        self.btn_skip.clicked.connect(self._skip)
        buttons.addWidget(self.btn_rerun)
        buttons.addWidget(self.btn_skip)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ API
    def style_prompt(self) -> str:
        """The addendum the run will use (empty when the user unchecked it)."""
        if not self.chk_apply.isChecked():
            return ""
        return self.editor.toPlainText().strip()

    def genre(self) -> str:
        return self._result.label if self._result is not None else ""

    def analysis(self) -> dict[str, Any]:
        if self._result is None:
            return {}
        return {
            "category": self._result.category,
            "genre": self._result.genre,
            "subgenre": self._result.subgenre,
            "register": self._result.register,
            "tone": self._result.tone,
            "audience": self._result.audience,
            "era": self._result.era,
            "guidance": list(self._result.guidance),
            "confidence": self._result.confidence,
        }

    def result(self) -> text_analysis.AnalysisResult | None:
        return self._result

    # --------------------------------------------------------------- Qt
    def initializePage(self) -> None:  # noqa: N802 - Qt naming
        self._maybe_start(force=False)

    def _skip(self) -> None:
        self.chk_apply.setChecked(False)
        self.editor.setPlainText(text_analysis.generic_style_prompt())
        self.status.setText(T("analysis.skipped"))

    def stop(self) -> None:
        """Called when the wizard closes: never leave a running thread behind."""
        worker, self._worker = self._worker, None
        if worker is not None and worker.isRunning():
            detach(worker)

    # ----------------------------------------------------------- internals
    def _unsupported(self) -> None:
        self.status.setText(T("analysis.not_supported"))
        self.editor.setEnabled(False)
        self.chk_apply.setEnabled(False)
        self.btn_rerun.setEnabled(False)

    def _maybe_start(self, *, force: bool) -> None:
        wizard = self.wizard()
        if wizard is None or not getattr(wizard, "input_path", None):
            self._unsupported()
            return
        engine = wizard.cmb_engine.currentText().strip()
        if not appconfig.engine_supports_prompt(engine):
            self._unsupported()
            return
        self.editor.setEnabled(True)
        self.chk_apply.setEnabled(True)
        self.btn_rerun.setEnabled(True)
        model = wizard.cmb_model.currentText().strip()
        key = (wizard.input_path, tuple(wizard.selected_chapters() or ()),
               engine, model, wizard.cmb_source.currentText(),
               wizard.cmb_target.currentText())
        if not force and key == self._key and self._result is not None:
            return
        self._key = key
        self.status.setText(T("analysis.running"))
        self.btn_rerun.setEnabled(False)
        api_key = wizard.edt_api_key.text().strip()
        endpoint = (appconfig.get_engine_preference(engine) or {}).get(
            "endpoint", "") or ""
        source = wizard.cmb_source.currentText()
        target = wizard.cmb_target.currentText()

        def work() -> text_analysis.AnalysisResult:
            segments = wizard.segments()
            meta = {}
            try:
                meta = chapters_mod.book_meta(wizard.input_path) or {}
            except Exception:  # noqa: BLE001 - metadata is optional context
                meta = {}
            runner = self._runner_factory(engine, model, api_key,
                                          endpoint=endpoint,
                                          source_lang=source, target_lang=target)
            return text_analysis.analyze(
                segments, runner=runner, title=meta.get("title", ""),
                author=meta.get("author", ""), source_lang=source, model=model)

        if self._synchronous:
            self._handle(work())
            return
        self._worker = run_async(work, self._handle, self)

    def _handle(self, result: Any) -> None:
        self._worker = None
        self.btn_rerun.setEnabled(True)
        if not isinstance(result, text_analysis.AnalysisResult):
            result = text_analysis.AnalysisResult(
                error=str(result), prompt="")
        self._result = result
        if result.ok:
            self.status.setText(T("analysis.done").format(
                genre=result.label,
                confidence=int(round(result.confidence * 100))))
            self.editor.setPlainText(text_analysis.build_style_prompt(result))
            fields = [value for value in (
                result.genre, result.subgenre, result.register, result.tone,
                result.audience, result.era) if value]
            self.lbl_fields.setText(" · ".join(fields) or "—")
        else:
            reason = (result.error or "").strip().splitlines()
            self.status.setText(T("analysis.failed").format(
                reason=reason[0][:160] if reason else "?"))
            if not self.editor.toPlainText().strip():
                self.editor.setPlainText(text_analysis.generic_style_prompt())
        self._show_cost()
        wizard = self.wizard()
        engine = wizard.cmb_engine.currentText().strip() if wizard else ""
        model = wizard.cmb_model.currentText().strip() if wizard else ""
        chars = sum(len(text) for text in result.excerpts)
        if chars:
            self.privacy.setText(T("analysis.privacy").format(
                chars=chars, engine=engine or "—"))
        else:
            self.privacy.setText(T("analysis.privacy_auto"))
        self.privacy.setVisible(True)

    def _show_cost(self) -> None:
        wizard = self.wizard()
        if wizard is None or self._result is None or not self._result.prompt:
            self.lbl_cost.setText("")
            return
        engine = wizard.cmb_engine.currentText().strip()
        model = wizard.cmb_model.currentText().strip()
        try:
            info = text_analysis.analysis_cost(
                self._result.prompt, engine=engine, model=model)
        except Exception:  # noqa: BLE001 - a missing price must not break the page
            self.lbl_cost.setText("")
            return
        tokens = info["input_tokens"] + info["output_tokens"]
        if info["cost_usd"] is None:
            self.lbl_cost.setText(T("analysis.cost_unknown").format(tokens=tokens))
        else:
            self.lbl_cost.setText(T("analysis.cost").format(
                tokens=tokens, cost=format_usd(info["cost_usd"])))
