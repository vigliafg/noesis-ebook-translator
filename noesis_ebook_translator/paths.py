"""Filesystem locations shared by the desktop app (pure module, no Qt).

Centralises where the app keeps its user data (reader sessions, the SQLite
library, extracted chapters, caches). Previously this logic lived inside
:mod:`noesis_ebook_translator.reader.session`; keeping it here lets the
headless core (library, chapter store) reuse it without importing Qt.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["data_dir", "data_file"]

#: Directory name under the OS config/data root.
_APP_DIRNAME = "noesis-ebook-translator"


def _base_dir() -> Path:
    """Return the per-OS base directory (config-style)."""
    override = os.environ.get("NOESIS_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home()))
    if sys_platform() == "darwin":
        return Path.home() / "Library" / "Preferences"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def sys_platform() -> str:
    import sys
    return sys.platform


def data_dir() -> Path:
    """Return the app's data directory (created on demand by callers)."""
    return _base_dir() / _APP_DIRNAME


def data_file(name: str) -> Path:
    """Return ``data_dir()/name`` (parent directory is NOT created here)."""
    return data_dir() / name


def cache_dir() -> Path:
    """Directory holding the translation cache (the ``*.db`` files).

    Follows ``cache_path`` from the configuration when set (``main.py`` points it
    at :func:`data_dir` so hours of work survive a reboot); otherwise it uses the
    app default under :func:`data_dir`.
    """
    from .lib.config import get_config

    configured = get_config().get("cache_path") or ""
    base = Path(configured) if configured else data_dir() / "translator-cache"
    return base / "cache"
