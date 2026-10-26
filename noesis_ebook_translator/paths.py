"""Filesystem locations shared by the desktop app (pure module, no Qt).

Configuration (the verbatim engine's JSON files) lives in the platform's
*config* directory, next to the ``calibre`` shim. User data (the SQLite library,
extracted chapters, the resume cache and logs) lives in the platform's *data*
directory: on macOS ``~/Library/Application Support``, on Windows
``%LOCALAPPDATA%`` and on Linux ``$XDG_DATA_HOME``. Storing a cache of hundreds
of megabytes in ``~/Library/Preferences`` or in roaming ``%APPDATA%`` was the
old behaviour and is the reason for the one-time migration below.

``NOESIS_CONFIG_DIR`` remains a single override for **both** trees (the tests
use it to keep every run in a temporary directory).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

__all__ = [
    "data_dir", "data_file", "cache_dir", "legacy_data_dir",
    "migrate_legacy_data", "reset_for_tests",
]

#: Directory name under the OS config/data root.
_APP_DIRNAME = "noesis-ebook-translator"

#: When a migration fails, the current session keeps using the old directory
#: instead of showing an empty library. The next start retries.
_legacy_fallback = False

#: Items migrated from the old config directory to the new data directory.
_LEGACY_FILES = ("library.db", "chapters.db", "reader.json")
_LEGACY_DIRS = ("translator-cache",)


def _sys_platform() -> str:
    return sys.platform


def _override() -> Path | None:
    value = os.environ.get("NOESIS_CONFIG_DIR")
    return Path(value) if value else None


def _config_base_dir() -> Path:
    override = _override()
    if override:
        return override
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home()))
    if _sys_platform() == "darwin":
        return Path.home() / "Library" / "Preferences"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _data_base_dir() -> Path:
    override = _override()
    if override:
        return override
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA")
                    or os.environ.get("APPDATA")
                    or Path.home())
    if _sys_platform() == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def legacy_data_dir() -> Path:
    """The pre-0.10.0 location (under the config root)."""
    return _config_base_dir() / _APP_DIRNAME


def data_dir() -> Path:
    """Return the app's data directory (created on demand by callers)."""
    if _legacy_fallback:
        return legacy_data_dir()
    return _data_base_dir() / _APP_DIRNAME


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


# ---------------------------------------------------------------------------
# one-time migration from the config directory
# ---------------------------------------------------------------------------
def _sqlite_ok(path: Path) -> None:
    """Raise unless ``path`` is a readable, structurally sound SQLite file."""
    uri = f"file:{path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if not row or row[0] != "ok":
        raise OSError(f"sqlite quick_check failed for {path}: {row}")


def _verify(path: Path, source: Path) -> None:
    if path.stat().st_size != source.stat().st_size:
        raise OSError(f"size mismatch for {path}")
    # ``path`` may be the ``.incoming`` staging file, so classify the source.
    if source.suffix == ".db":
        _sqlite_ok(path)
    elif source.name == "reader.json":
        json.loads(path.read_text("utf-8"))


def _copy_file(source: Path, target: Path) -> None:
    part = target.with_name(target.name + ".incoming")
    if part.exists():
        part.unlink()
    try:
        shutil.copy2(source, part)
        _verify(part, source)
        os.replace(part, target)
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def _copy_tree(source: Path, target: Path) -> None:
    part = target.with_name("." + target.name + ".incoming")
    if part.exists():
        shutil.rmtree(part, ignore_errors=True)
    try:
        shutil.copytree(source, part)
        for copied in part.rglob("*.db"):
            _verify(copied, source / copied.relative_to(part))
        os.replace(part, target)
    finally:
        if part.exists():
            shutil.rmtree(part, ignore_errors=True)


def _has_wal(directory: Path) -> bool:
    return (any(directory.glob("*.db-wal"))
            or any(directory.glob("*.db-shm"))
            or any(directory.glob("*.db-journal")))


def migrate_legacy_data() -> bool:
    """Copy old config-dir data into the new data dir (never deletes source).

    Returns ``True`` when the new directory is usable (migration succeeded, was
    not needed, or the override makes the two trees coincide). On failure the
    session falls back to :func:`legacy_data_dir` and the next start retries.
    """
    global _legacy_fallback

    if _override():
        # Tests and portable runs use one directory for config and data.
        _legacy_fallback = False
        return True

    source = legacy_data_dir()
    target = _data_base_dir() / _APP_DIRNAME
    if not source.is_dir() or source == target:
        _legacy_fallback = False
        return True

    if target.exists() and (target / ".migrated-from-config").is_file():
        _legacy_fallback = False
        return True

    # A live WAL means the database is open in another process; copying it now
    # could produce a torn snapshot. Retry on the next start.
    if _has_wal(source) or _has_wal(source / "translator-cache" / "cache"):
        _legacy_fallback = True
        return False

    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in _LEGACY_FILES:
            origin = source / name
            if not origin.is_file():
                continue
            destination = target / name
            if destination.exists():
                try:
                    _verify(destination, origin)
                except Exception:  # noqa: BLE001 - incomplete previous copy
                    _copy_file(origin, destination)
                continue
            _copy_file(origin, destination)
        for name in _LEGACY_DIRS:
            origin = source / name
            if origin.is_dir() and not (target / name).exists():
                _copy_tree(origin, target / name)
        (target / ".migrated-from-config").write_text(
            f"copied from {source}\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - startup must use the old data, not fail
        _legacy_fallback = True
        return False

    _legacy_fallback = False
    return True


def reset_for_tests() -> None:
    """Clear the migration fallback (tests only)."""
    global _legacy_fallback
    _legacy_fallback = False
