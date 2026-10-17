"""Wizard page: how much the translation costs in tokens, money and time.

Everything comes from :mod:`noesis_ebook_translator.estimate`: tokens counted
with ``tiktoken`` on the exact segments, price from the bundled models.dev
snapshot, duration from the engine's pacing corrected by previous runs. The page
recomputes when the run changes (engine, model, languages, selection, style
prompt) and shows a per-chapter breakdown.

The computation parses the book, so it runs in a worker thread; the wizard
caches the segments and both pages share them.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QFormLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWizardPage)

from .. import estimate as estimate_mod
from ..i18n import T
from .provider_test import detach, run_async

__all__ = ["EstimatePage"]

#: Engines whose tokenizer is not the one tiktoken counts with.
_OPENAI_HINTS = ("gpt", "o1", "o3", "o4", "chatgpt", "openai")


class EstimatePage(QWizardPage):
    def __init__(self, parent=None, *, synchronous: bool = False) -> None:
        super().__init__(parent)
        self.setTitle(T("wizard.estimate_title"))
        self._synchronous = synchronous
        self._estimate: estimate_mod.BookEstimate | None = None
        self._key: tuple | None = None
        self._worker = None

        layout = QVBoxLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        form = QFormLayout()
        self.lbl_segments = QLabel("—")
        self.lbl_characters = QLabel("—")
        self.lbl_tokens = QLabel("—")
        self.lbl_requests = QLabel("—")
        self.lbl_cached = QLabel("—")
        self.lbl_cost = QLabel("—")
        self.lbl_time = QLabel("—")
        form.addRow(T("estimate.segments"), self.lbl_segments)
        form.addRow(T("estimate.characters"), self.lbl_characters)
        form.addRow(T("estimate.tokens"), self.lbl_tokens)
        form.addRow(T("estimate.requests"), self.lbl_requests)
        form.addRow(T("estimate.cached"), self.lbl_cached)
        form.addRow(T("estimate.cost"), self.lbl_cost)
        form.addRow(T("estimate.time"), self.lbl_time)
        layout.addLayout(form)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            T("estimate.chapter"), T("estimate.col_segments"),
            T("estimate.col_tokens")])
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(120)
        layout.addWidget(self.table, 1)

        self.note = QLabel("")
        self.note.setObjectName("bandHint")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        self.btn_recalc = QPushButton(T("estimate.recalc"))
        self.btn_recalc.clicked.connect(lambda: self.refresh(force=True))
        layout.addWidget(self.btn_recalc)

    # ------------------------------------------------------------------ API
    def estimate(self) -> estimate_mod.BookEstimate | None:
        return self._estimate

    # --------------------------------------------------------------- Qt
    def initializePage(self) -> None:  # noqa: N802 - Qt naming
        self.refresh(force=False)

    def stop(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None and worker.isRunning():
            detach(worker)

    # ----------------------------------------------------------- internals
    def _key_for(self, wizard) -> tuple:
        return (
            wizard.input_path,
            tuple(wizard.selected_chapters() or ()),
            wizard.cmb_engine.currentText().strip(),
            wizard.cmb_model.currentText().strip(),
            wizard.cmb_source.currentText(),
            wizard.cmb_target.currentText(),
            bool(wizard.chk_sequential.isChecked()),
            int(wizard.spn_parallel.value()),
            bool(wizard.chk_batch.isChecked()),
            bool(wizard.chk_cache.isChecked()),
            wizard.analysis_page.style_prompt(),
        )

    def refresh(self, *, force: bool = False) -> None:
        wizard = self.wizard()
        if wizard is None or not getattr(wizard, "input_path", None):
            self.status.setText(T("estimate.failed").format(reason="no book"))
            return
        key = self._key_for(wizard)
        if not force and key == self._key and self._estimate is not None:
            self._render(self._estimate)
            return
        self._key = key
        self.status.setText(T("estimate.computing"))
        self.btn_recalc.setEnabled(False)
        engine = key[2]
        model = key[3]
        source, target = key[4], key[5]
        sequential, parallel = key[6], key[7]
        batching, cache_enabled = key[8], key[9]
        style_prompt = key[10]

        def work() -> estimate_mod.BookEstimate:
            segments = wizard.segments()
            return estimate_mod.estimate_book(
                wizard.input_path, chapters_spec=wizard.selected_chapters() or None,
                engine=engine, model=model, source_lang=source,
                target_lang=target, sequential=sequential, concurrency=parallel,
                batching=batching, cache_enabled=cache_enabled,
                style_prompt=style_prompt, segments=segments)

        if self._synchronous:
            self._handle(work())
            return
        self._worker = run_async(work, self._handle, self)

    def _handle(self, result: Any) -> None:
        self._worker = None
        self.btn_recalc.setEnabled(True)
        if not isinstance(result, estimate_mod.BookEstimate):
            self._estimate = None
            self.status.setText(T("estimate.failed").format(
                reason=str(result).strip().splitlines()[0][:160]))
            return
        self._estimate = result
        self._render(result)

    def _render(self, est: estimate_mod.BookEstimate) -> None:
        self.status.setText("")
        self.lbl_segments.setText(str(est.segments))
        self.lbl_characters.setText(f"{est.characters:,}".replace(",", " "))
        self.lbl_tokens.setText(T("estimate.tokens_value").format(
            input=f"{est.tokens_in:,}".replace(",", " "),
            output=f"{est.tokens_out:,}".replace(",", " ")))
        requests = T("estimate.requests_value").format(requests=est.requests)
        if est.batching:
            requests += " " + T("estimate.batched")
        self.lbl_requests.setText(requests)
        self.lbl_cached.setText(
            T("estimate.cached_value").format(n=est.cached_segments)
            if est.cached_segments else T("estimate.nothing_cached"))

        if est.pricing is None:
            self.lbl_cost.setText(T("estimate.unknown_price"))
        elif est.pricing == (0.0, 0.0):
            self.lbl_cost.setText(T("estimate.free"))
        else:
            self.lbl_cost.setText(estimate_mod.format_usd(est.cost_usd))
        if est.seconds:
            self.lbl_time.setText(T("estimate.time_range").format(
                value=estimate_mod.format_duration(est.seconds),
                low=estimate_mod.format_duration(est.seconds_low),
                high=estimate_mod.format_duration(est.seconds_high)))
        else:
            self.lbl_time.setText(T("estimate.no_time"))

        self._fill_table(est)
        notes = [T("estimate.tokens_note").format(encoding=est.encoding)]
        if est.backend != "tiktoken":
            notes.append(T("estimate.tiktoken_fallback"))
        model = self.wizard().cmb_model.currentText().lower() if self.wizard() else ""
        if not any(hint in model for hint in _OPENAI_HINTS):
            notes.append(T("estimate.tokens_approx"))
        if est.observed_latency:
            notes.append(T("estimate.observed"))
        if est.seconds and est.concurrency > 1:
            notes.append(T("estimate.parallel_note").format(n=est.concurrency))
        if est.price_date:
            notes.append(T("estimate.price_note").format(date=est.price_date[:10]))
        if est.cached_segments:
            notes.append(T("estimate.cached_note"))
        self.note.setText(" ".join(notes))

    def _fill_table(self, est: estimate_mod.BookEstimate) -> None:
        rows = est.per_chapter
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            title = row.title or row.file
            if row.cached_segments:
                title += " " + T("estimate.cached_row").format(
                    n=row.cached_segments)
            for column, value in enumerate((
                    title, str(row.segments),
                    f"{row.tokens_in:,}".replace(",", " "))):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.table.setVisible(bool(rows))
