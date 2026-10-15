"""Custom ``app://`` URL scheme serving the foliate-js bundle and book files.

Chromium refuses to load ES modules over ``file://`` and foliate-js is ESM, so
the reader serves everything through a private scheme registered before the
``QApplication`` (see :func:`ensure_scheme`).

Book files are served from the **same host** as the page (``app://reader/...``)
under a reserved ``__book__/`` prefix. Keeping them same-origin avoids the CORS
restrictions that a separate ``app://book`` host would hit (the scheme handler
cannot emit CORS headers), and lets the page's CSP stay strict.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtWebEngineCore import (
    QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler)

SCHEME = b"app"
HOST = "reader"
BOOK_PREFIX = "__book__/"
WEB_ROOT = Path(__file__).resolve().parent.parent.parent / "reader_web"

_scheme_registered = False


def ensure_scheme() -> None:
    """Register the ``app://`` scheme (idempotent; must precede QApplication)."""
    global _scheme_registered
    if _scheme_registered:
        return
    scheme = QWebEngineUrlScheme(SCHEME)
    flags = (QWebEngineUrlScheme.Flag.SecureScheme
             | QWebEngineUrlScheme.Flag.LocalAccessAllowed
             | QWebEngineUrlScheme.Flag.CorsEnabled)
    # fetch() over a custom scheme requires FetchApiAllowed (Qt >= 6.6).
    fetch_flag = getattr(QWebEngineUrlScheme.Flag, "FetchApiAllowed", None)
    if fetch_flag is not None:
        flags |= fetch_flag
    scheme.setFlags(flags)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    try:
        QWebEngineUrlScheme.registerScheme(scheme)
    except Exception:  # noqa: BLE001 - already registered
        pass
    _scheme_registered = True


def book_url(path: str) -> str:
    """Return the same-origin ``app://`` URL for a book file."""
    return f"app://{HOST}/{BOOK_PREFIX}{os.path.basename(path)}"


class ReaderSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serve ``app://reader/<path>`` (bundle) and ``app://reader/__book__/<file>``."""
    #: Directory of the currently opened book (``app://reader/__book__/…``).
    book_dir: str | None = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.book_dir = None

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802
        url = job.requestUrl()
        host = url.host()
        rel = url.path().lstrip("/") or "reader.html"

        if host == "book" or rel.startswith(BOOK_PREFIX):
            # Legacy host or same-origin prefix → serve from the book directory.
            if rel.startswith(BOOK_PREFIX):
                rel = rel[len(BOOK_PREFIX):]
            root = getattr(self, "book_dir", None)
        else:
            root = WEB_ROOT
        if not root:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        target = (Path(root) / rel).resolve()
        try:
            target.relative_to(Path(root).resolve())
        except ValueError:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        if not target.is_file():
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        mime, _ = mimetypes.guess_type(str(target))
        data = QByteArray(target.read_bytes())
        buffer = QBuffer(job)
        buffer.setData(data)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply((mime or "application/octet-stream").encode(), buffer)
