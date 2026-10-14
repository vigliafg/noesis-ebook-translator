"""Subset of :mod:`calibre.ptempfile` used by the engine."""
from __future__ import annotations

import tempfile


class PersistentTemporaryFile:
    """A named temporary file that survives until explicitly removed."""

    def __init__(self, suffix: str = "", prefix: str = "", dir: str | None = None):
        handle = tempfile.NamedTemporaryFile(
            suffix=suffix, prefix=prefix, dir=dir, delete=False)
        handle.close()
        self.name = handle.name
        self._file = handle

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        return None

    def remove(self) -> None:
        import os

        try:
            os.remove(self.name)
        except OSError:
            pass
