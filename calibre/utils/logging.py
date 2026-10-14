"""Very small stand-in for :mod:`calibre.utils.logging`.

Only the parts used by the engine are implemented: the :class:`Log` class with
the ``DEBUG``/``INFO``/``WARN``/``ERROR`` levels and printf-style methods, plus a
:class:`Stream` sink used for the optional log redirection.
"""
from __future__ import annotations

import sys
from typing import IO, Any


class Log:
    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40

    def __init__(self, level: int = INFO, out: IO[str] | None = None) -> None:
        self.level = level
        self.out = out if out is not None else sys.stderr
        self.outputs: list[Any] = []

    # -- internal ---------------------------------------------------------
    def _emit(self, prefix: str, args: tuple, kwargs: dict) -> None:
        msg = " ".join(str(a) for a in args)
        line = f"{prefix}{msg}"
        for output in self.outputs:
            try:
                output.write(line + "\n")
            except Exception:
                pass
        try:
            print(line, file=self.out)
        except Exception:
            pass

    # -- public API -------------------------------------------------------
    def debug(self, *args, **kwargs) -> None:
        if self.level <= self.DEBUG:
            self._emit("DEBUG: ", args, kwargs)

    def info(self, *args, **kwargs) -> None:
        if self.level <= self.INFO:
            self._emit("", args, kwargs)

    def warn(self, *args, **kwargs) -> None:  # noqa: A003 - Calibre name
        if self.level <= self.WARN:
            self._emit("WARN: ", args, kwargs)

    warning = warn

    def error(self, *args, **kwargs) -> None:
        if self.level <= self.ERROR:
            self._emit("ERROR: ", args, kwargs)

    def exception(self, *args, **kwargs) -> None:
        self._emit("ERROR: ", args, kwargs)

    def __call__(self, *args, **kwargs) -> None:
        self.info(*args, **kwargs)


class Stream:
    """A writable sink backed by a caller-provided callback."""

    def __init__(self, callback=None, *args, **kwargs) -> None:
        self.callback = callback

    def write(self, text: str) -> None:
        if self.callback is not None:
            self.callback(text)

    def flush(self) -> None:
        return None
