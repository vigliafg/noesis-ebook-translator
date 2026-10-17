"""Test configuration: isolate the app config/cache before importing the engine."""
import os
import tempfile

# The Calibre shim reads this at import time, so it must be set *before* any
# ``noesis_ebook_translator`` import. Keep tests away from the user's config.
_TMP = tempfile.mkdtemp(prefix="noesis-et-tests-")
os.environ.setdefault("NOESIS_CONFIG_DIR", _TMP)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Tests exercise the lite reader (deterministic, no WebEngine subprocess).
os.environ.setdefault("NOESIS_READER_BACKEND", "lite")

# A modal dialog in a headless run blocks forever, and the app asks before
# overwriting an existing output file: answer "yes" by default so no test can hang.
# A test that wants to assert the question patches ``QMessageBox.question`` itself.
try:  # pragma: no cover - the guard is the point
    from PyQt6.QtWidgets import QMessageBox

    QMessageBox.question = staticmethod(
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *args, **kwargs: None)
    QMessageBox.warning = staticmethod(lambda *args, **kwargs: None)
    QMessageBox.critical = staticmethod(lambda *args, **kwargs: None)
except Exception:  # noqa: BLE001 - Qt is optional for the pure tests
    pass
