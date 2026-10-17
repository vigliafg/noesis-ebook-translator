"""Inline "test the selected model" control.

Shared by the Settings *Provider* page and the onboarding wizard: whenever a
provider / model / API key is chosen, the model is probed with a **single short
translation** and the outcome is shown inline. The probe runs in a worker thread
so the UI never blocks, stale results are dropped, and both the probe and the
model fetch are injectable so tests stay offline.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import provider_catalog
from ..i18n import T

__all__ = ["ModelTestWidget", "run_async"]

_STYLES = {
    "ok": "color: #2e7d32;",
    "fail": "color: #c62828;",
    "running": "color: #616161;",
    "pending": "color: #616161;",
    "warn": "color: #ef6c00;",
    "": "",
}


class _Worker(QThread):
    """Run ``fn`` in a thread and emit its result (or the exception)."""

    done = pyqtSignal(object)

    def __init__(self, fn: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            result: Any = self._fn()
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            result = exc
        self.done.emit(result)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None],
              parent=None) -> _Worker:
    """Run ``fn`` in a worker thread; ``on_done`` receives result or exception."""
    worker = _Worker(fn, parent)
    worker.done.connect(on_done)
    worker.finished.connect(worker.deleteLater)
    worker.start()
    return worker


class ModelTestWidget(QWidget):
    """Status label + test button for one provider slot."""

    finished = pyqtSignal(object)

    def __init__(self, parent=None, *, runner: Callable[..., Any] | None = None,
                 debounce_ms: int = 700, synchronous: bool = False) -> None:
        super().__init__(parent)
        self._runner = runner or provider_catalog.test_model
        self._synchronous = synchronous
        self._pending: tuple[str, str, str] | None = None
        self._serial = 0
        self._thread: _Worker | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.btn = QPushButton(T("action.test_model"))
        self.btn.clicked.connect(self.run_now)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.btn)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self.run_now)
        self._set_status(T("provider.test_idle"), "")

    # ------------------------------------------------------------- public
    def schedule(self, provider_id: str, api_key: str, model: str) -> None:
        """Queue a debounced test for the current selection."""
        self._pending = (provider_id or "", api_key or "", model or "")
        if not provider_id:
            self._set_status(T("provider.test_idle"), "")
            return
        self._set_status(T("provider.test_pending"), "pending")
        self._timer.start()

    def run_now(self) -> None:
        """Run the test immediately (button or debounce timer)."""
        self._timer.stop()
        if not self._pending:
            return
        provider_id, api_key, model = self._pending
        if not provider_id or not model:
            self._set_status(T("provider.test_incomplete"), "warn")
            return
        self._set_status(T("provider.testing"), "running")

        def probe() -> Any:
            return self._runner(provider_id, api_key, model)

        if self._synchronous:
            try:
                result = probe()
            except Exception as exc:  # noqa: BLE001 - shown inline
                result = exc
            self._handle(result)
            return
        self._serial += 1
        serial = self._serial
        self._thread = run_async(
            probe, lambda result, s=serial: self._on_done(s, result), self)

    def last_pending(self) -> tuple[str, str, str] | None:
        return self._pending

    # ------------------------------------------------------------ internals
    def _on_done(self, serial: int, result: Any) -> None:
        if serial != self._serial:  # a newer test superseded this one
            return
        self._handle(result)

    def _handle(self, result: Any) -> None:
        if not isinstance(result, provider_catalog.TestResult):
            result = provider_catalog.TestResult(
                ok=False, error_kind="network", message=str(result))
        if result.ok:
            seconds = f"{result.latency_ms / 1000:.1f}"
            self._set_status(T("provider.test_ok").format(seconds=seconds), "ok")
        else:
            self._set_status(
                T("provider.test_fail").format(reason=self._reason(result)), "fail")
        self.finished.emit(result)

    @staticmethod
    def _reason(result: provider_catalog.TestResult) -> str:
        key = {
            "auth": "provider.err.auth",
            "model": "provider.err.model",
            "timeout": "provider.err.timeout",
            "network": "provider.err.network",
            "empty": "provider.err.empty",
        }.get(result.error_kind)
        if key:
            return T(key)
        return (result.message or "?").strip().splitlines()[0][:120]

    def _set_status(self, text: str, state: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(_STYLES.get(state, ""))

    def stop(self) -> None:
        """Cancel the debounce timer (called when the dialog closes)."""
        self._timer.stop()
