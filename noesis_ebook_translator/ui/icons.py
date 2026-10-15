"""Colored icon registry backed by ``assets/icons`` (Fluent Emoji, MIT).

Icons are referenced by semantic name (``"library"``, ``"translate"``…). If a
file is missing the loader returns a null ``QIcon`` so the caller can fall back
to a text-only button instead of crashing.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PyQt6.QtGui import QIcon

__all__ = ["icon", "has_icon", "icons_dir", "available"]


def icons_dir() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidate = Path(bundle) / "assets" / "icons"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent.parent.parent / "assets" / "icons"


@lru_cache(maxsize=None)
def _path(name: str) -> Path:
    return icons_dir() / f"{name}.png"


def has_icon(name: str) -> bool:
    return bool(name) and _path(name).is_file()


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    path = _path(name)
    return QIcon(str(path)) if path.is_file() else QIcon()


def available() -> list[str]:
    directory = icons_dir()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.png"))
