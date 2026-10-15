"""Translation-quality dialog: metrics + optional AI judge (in a worker)."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout)

from ..i18n import T

__all__ = ["QualityDialog"]


class QualityWorker(QThread):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source: str, translated: str, judge=None, sample: int = 10):
        super().__init__()
        self.source = source
        self.translated = translated
        self.judge = judge
        self.sample = sample

    def run(self) -> None:  # noqa: D401 - QThread entry point
        import traceback
        from ..quality import evaluate
        try:
            report = evaluate(self.source, self.translated,
                              judge=self.judge, judge_sample=self.sample)
            self.done.emit(report.to_markdown())
        except Exception:  # noqa: BLE001 - surfaced in the dialog
            self.failed.emit(traceback.format_exc())


class QualityDialog(QDialog):
    def __init__(self, source: str | None, translated: str | None,
                 judge_factory=None, parent=None) -> None:
        super().__init__(parent)
        self._source = source
        self._translated = translated
        self._judge_factory = judge_factory
        self._worker = None
        self.setWindowTitle(T("quality.title"))
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        self.chk_judge = QCheckBox(T("quality.run") + " (AI)")
        if judge_factory is None:
            self.chk_judge.setEnabled(False)
        layout.addWidget(self.chk_judge)

        bar = QHBoxLayout()
        self.btn_run = QPushButton(T("action.evaluate"))
        self.btn_save = QPushButton(T("action.report_save"))
        self.btn_close = QPushButton(T("action.close"))
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_save)
        bar.addStretch(1)
        bar.addWidget(self.btn_close)
        layout.addLayout(bar)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)

        self._last_text = ""
        self.btn_run.clicked.connect(self.run)
        self.btn_save.clicked.connect(self._save_report)
        self.btn_close.clicked.connect(self.accept)

    def _save_report(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        if not self._last_text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, T("action.report_save"), "quality.md",
            "Markdown (*.md);;JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._last_text)
        except OSError:
            pass

    def _set_output(self, text: str) -> None:
        self._last_text = text
        self.output.setPlainText(text)

    def run(self) -> None:
        if not (self._source and self._translated):
            self._set_output(T("msg.no_input"))
            return
        judge = None
        if self.chk_judge.isChecked() and self._judge_factory is not None:
            try:
                judge = self._judge_factory()
            except Exception as exc:  # noqa: BLE001
                self._set_output(str(exc))
                judge = None
        self._set_output("…")
        self._worker = QualityWorker(self._source, self._translated, judge)
        self._worker.done.connect(self._set_output)
        self._worker.failed.connect(self._set_output)
        self._worker.start()
