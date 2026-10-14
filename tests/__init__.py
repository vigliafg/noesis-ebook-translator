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
