"""Reader session: reading position, recent books and annotations.

This is now a thin adapter over the SQLite :class:`~noesis_ebook_translator.library.Library`
(the old ``reader.json`` file is migrated automatically on first access). The
public methods are kept stable so the reader widgets keep working.
"""
from __future__ import annotations

from pathlib import Path

from ..library import Library

__all__ = ["Session"]


class Session:
    def __init__(self, path: str | None = None) -> None:
        # ``path`` is the SQLite library path (kept for backwards compatibility).
        self.library = Library(path)
        self.path = Path(self.library.path)

    # -- persistence ------------------------------------------------------
    def save(self) -> None:
        """Kept for compatibility; SQLite commits on every write."""
        return None

    def close(self) -> None:
        self.library.close()

    # -- position ---------------------------------------------------------
    def get_position(self, book_path: str) -> dict:
        return self.library.get_position(book_path)

    def set_position(self, book_path: str, href: str | None,
                     fraction: float = 0.0) -> None:
        self.library.set_position(book_path, href, fraction)

    # -- recent -----------------------------------------------------------
    def add_recent(self, book_path: str, title: str = "") -> None:
        self.library.add_book(book_path, title=title)

    def remove_recent(self, book_path: str) -> None:
        self.library.remove_book(book_path)

    def recent(self) -> list[dict]:
        return self.library.books()

    def set_translated(self, book_path: str, translated_path: str) -> None:
        self.library.set_translated(book_path, translated_path)

    # -- annotations ------------------------------------------------------
    def annotations(self, book_path: str) -> list:
        return self.library.annotations(book_path)

    def add_annotation(self, book_path: str, item: dict) -> None:
        self.library.add_annotation(book_path, item)

    def remove_annotation(self, book_path: str, index: int) -> None:
        self.library.remove_annotation(book_path, index)
