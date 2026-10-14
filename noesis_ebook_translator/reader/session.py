"""Reader session: reading position, recent books and annotations (JSON).

Stored under the app config directory so the reader can resume where you left
off and remember the library. Simple, portable and human-readable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .. import identifier as _app_id

__all__ = ["Session"]


def _data_dir() -> Path:
    override = os.environ.get("NOESIS_CONFIG_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif os.sys.platform == "darwin":  # type: ignore[attr-defined]
        base = Path.home() / "Library" / "Preferences"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "noesis-ebook-translator"


class Session:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path else _data_dir() / "reader.json"
        self.data = {"positions": {}, "recent": [], "annotations": {}}
        self.load()

    # -- persistence ------------------------------------------------------
    def load(self) -> None:
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- position ---------------------------------------------------------
    def get_position(self, book_path: str) -> dict:
        return self.data["positions"].get(os.path.abspath(book_path), {})

    def set_position(self, book_path: str, href: str | None,
                     fraction: float = 0.0) -> None:
        self.data["positions"][os.path.abspath(book_path)] = {
            "href": href, "fraction": round(float(fraction), 4)}
        self.save()

    # -- recent -----------------------------------------------------------
    def add_recent(self, book_path: str, title: str = "") -> None:
        book_path = os.path.abspath(book_path)
        recent = [r for r in self.data["recent"] if r.get("path") != book_path]
        recent.insert(0, {"path": book_path, "title": title})
        self.data["recent"] = recent[:30]
        self.save()

    def recent(self) -> list[dict]:
        return list(self.data["recent"])

    # -- annotations ------------------------------------------------------
    def annotations(self, book_path: str) -> list:
        return self.data["annotations"].get(os.path.abspath(book_path), [])

    def add_annotation(self, book_path: str, item: dict) -> None:
        self.data["annotations"].setdefault(os.path.abspath(book_path), []).append(item)
        self.save()

    def remove_annotation(self, book_path: str, index: int) -> None:
        items = self.data["annotations"].get(os.path.abspath(book_path), [])
        if 0 <= index < len(items):
            items.pop(index)
            self.save()
