"""Persistent diagnostics for the desktop app.

A frozen ``--windowed`` build has no console, so an exception in a Qt slot is
otherwise lost (PyQt prints it and continues). This module writes a small
rotating log to the app's data directory and installs an ``excepthook``. Qt
messages are forwarded only in frozen builds, so the test suite keeps its
asserted stderr channel untouched.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

__all__ = ["install", "log_path", "reset_for_tests"]

_LOGGER_NAME = "noesis"
_installed = False
_handler: logging.Handler | None = None
_log_file: Path | None = None


def log_path() -> Path:
    from .paths import data_dir
    return data_dir() / "logs" / "app.log"


def install(log_dir: str | Path | None = None) -> Path | None:
    """Install the file handler and the exception hook (idempotent).

    Returns the log file path, or ``None`` when the directory is not writable
    (the app must still start: diagnostics are never a reason to fail).
    """
    global _installed, _handler, _log_file
    if _installed:
        return _log_file

    directory = Path(log_dir) if log_dir is not None else log_path().parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "app.log"
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        return None

    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    _handler = handler
    _log_file = path

    def _excepthook(exc_type, exc_value, exc_tb):
        try:
            logger.critical(
                "Unhandled exception",
                exc_info=(exc_type, exc_value, exc_tb))
        except Exception:  # noqa: BLE001 - never recurse
            pass
        if sys.stderr is not None:
            try:
                traceback.print_exception(exc_type, exc_value, exc_tb)
            except Exception:  # noqa: BLE001
                pass

    sys.excepthook = _excepthook

    if getattr(sys, "frozen", False):
        _install_qt_handler(logger)

    _installed = True
    return path


def _install_qt_handler(logger: logging.Logger) -> None:
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:  # noqa: BLE001 - Qt is optional for this module
        return

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(_mode, _context, message):
        try:
            logger.log(levels.get(_mode, logging.INFO), "Qt: %s", message)
        except Exception:  # noqa: BLE001
            pass

    qInstallMessageHandler(handler)


def reset_for_tests() -> None:
    """Remove the handler installed by :func:`install` (tests only)."""
    global _installed, _handler, _log_file
    logger = logging.getLogger(_LOGGER_NAME)
    if _handler is not None:
        logger.removeHandler(_handler)
        try:
            _handler.close()
        except Exception:  # noqa: BLE001
            pass
    _handler = None
    _log_file = None
    _installed = False
