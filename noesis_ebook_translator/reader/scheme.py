"""Custom ``app://`` URL scheme serving the foliate-js bundle and book files.

Chromium refuses to load ES modules over ``file://`` and foliate-js is ESM, so
the reader serves everything through a private scheme registered before the
``QApplication`` (see :func:`ensure_scheme`).
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PyQt6.QtWebEngineCore import (
    QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler)

SCHEME = b"app"
WEB_ROOT = Path(__file__).resolve().parent.parent.parent / "reader_web"


def ensure_scheme() -> None:
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    try:
        QWebEngineUrlScheme.registerScheme(scheme)
    except Exception:  # noqa: BLE001 - already registered
        pass


class ReaderSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serve ``app://reader/<path>`` (bundle) and ``app://book/<path>`` (book)."""

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802
        url = job.requestUrl()
        host = url.host()
        rel = url.path().lstrip("/") or "index.html"
        if host == "book":
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
