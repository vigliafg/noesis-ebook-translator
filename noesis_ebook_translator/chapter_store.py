"""Persistent store of extracted / translated chapters (SQLite, Qt-free).

Keeps, per book, the source text of each chapter and its translation, plus a
status and an optional quality score. Used by the "Chapters" panel and by the
quality harness to remember per-chapter results.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from .chapters import flatten, load_chapters
from .extract import extract_text
from .paths import data_dir

__all__ = ["ChapterStore", "STATUS_PENDING", "STATUS_TRANSLATED"]

STATUS_PENDING = "pending"
STATUS_TRANSLATED = "translated"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_path TEXT NOT NULL,
    chapter_index INTEGER NOT NULL,
    name TEXT DEFAULT '',
    source_file TEXT DEFAULT '',
    source_text TEXT DEFAULT '',
    translation TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    quality REAL,
    updated REAL DEFAULT 0,
    UNIQUE(book_path, chapter_index)
);
"""


class ChapterStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = str(path) if path else str(data_dir() / "chapters.db")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass

    def __enter__(self) -> "ChapterStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writes -----------------------------------------------------------
    def upsert(self, book_path: str, chapter_index: int, name: str = "",
               source_text: str = "", source_file: str = "",
               translation: str = "", status: str = STATUS_PENDING,
               quality: float | None = None) -> None:
        book_path = os.path.abspath(book_path)
        self._conn.execute(
            "INSERT INTO chapters (book_path, chapter_index, name, source_file,"
            " source_text, translation, status, quality, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(book_path, chapter_index) DO UPDATE SET "
            "name = excluded.name, "
            "source_file = CASE WHEN excluded.source_file != '' "
            "  THEN excluded.source_file ELSE chapters.source_file END, "
            "source_text = CASE WHEN excluded.source_text != '' "
            "  THEN excluded.source_text ELSE chapters.source_text END, "
            "translation = CASE WHEN excluded.translation != '' "
            "  THEN excluded.translation ELSE chapters.translation END, "
            "status = excluded.status, "
            "quality = COALESCE(excluded.quality, chapters.quality), "
            "updated = excluded.updated",
            (book_path, int(chapter_index), name, source_file, source_text,
             translation, status, quality, time.time()))
        self._conn.commit()

    def set_translation(self, book_path: str, chapter_index: int,
                        translation: str, status: str = STATUS_TRANSLATED,
                        quality: float | None = None) -> None:
        self.upsert(book_path, chapter_index, translation=translation,
                    status=status, quality=quality)

    def clear_book(self, book_path: str) -> None:
        self._conn.execute("DELETE FROM chapters WHERE book_path = ?",
                           (os.path.abspath(book_path),))
        self._conn.commit()

    # -- reads ------------------------------------------------------------
    def for_book(self, book_path: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM chapters WHERE book_path = ? ORDER BY chapter_index",
            (os.path.abspath(book_path),)).fetchall()
        return [dict(row) for row in rows]

    def get(self, book_path: str, chapter_index: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM chapters WHERE book_path = ? AND chapter_index = ?",
            (os.path.abspath(book_path), int(chapter_index))).fetchone()
        return dict(row) if row else None

    def search(self, needle: str) -> list[dict]:
        like = f"%{needle}%"
        rows = self._conn.execute(
            "SELECT * FROM chapters WHERE name LIKE ? OR source_text LIKE ? "
            "OR translation LIKE ? ORDER BY book_path, chapter_index",
            (like, like, like)).fetchall()
        return [dict(row) for row in rows]

    # -- sync from an EPUB ------------------------------------------------
    def sync_from_epub(self, epub_path: str, chapters=None) -> int:
        """Populate/refresh rows from an EPUB's chapters; return the count."""
        tree = chapters if chapters is not None else load_chapters(epub_path)
        flatten(tree)  # assign 1-based indices used as the stable chapter key
        grouped: dict[tuple[int, str], list[str]] = {}
        for index, name, text in extract_text(epub_path, chapters=tree):
            grouped.setdefault((index, name), []).append(text)
        count = 0
        for (index, name), texts in grouped.items():
            self.upsert(epub_path, index, name=name,
                        source_text="\n\n".join(texts))
            count += 1
        return count
