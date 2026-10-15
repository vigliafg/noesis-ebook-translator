"""Persistent EPUB library backed by SQLite (headless, Qt-free).

Stores the books the user opened, their metadata, reading position, translated
output and annotations. Replaces the old JSON ``reader.json`` session with a
robust store; :func:`migrate_from_json` (called automatically on first run)
imports an existing ``reader.json``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from .paths import data_dir

__all__ = ["Library"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    title TEXT DEFAULT '',
    author TEXT DEFAULT '',
    language TEXT DEFAULT '',
    cover BLOB,
    added REAL DEFAULT 0,
    last_opened REAL DEFAULT 0,
    translated_path TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS positions (
    book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    href TEXT,
    fraction REAL DEFAULT 0,
    updated REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    text TEXT DEFAULT '',
    note TEXT DEFAULT '',
    color TEXT DEFAULT '',
    created REAL DEFAULT 0
);
"""


def _now() -> float:
    return time.time()


class Library:
    """A small SQLite-backed library."""

    def __init__(self, path: str | None = None, migrate: bool = True) -> None:
        self.path = str(path) if path else str(data_dir() / "library.db")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        if migrate:
            self._auto_migrate()

    # -- lifecycle --------------------------------------------------------
    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover - defensive
            pass

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- books ------------------------------------------------------------
    def add_book(self, path: str, title: str = "", author: str = "",
                 language: str = "", cover: bytes | None = None) -> int:
        path = os.path.abspath(path)
        row = self._conn.execute(
            "SELECT id FROM books WHERE path = ?", (path,)).fetchone()
        if row:
            book_id = row["id"]
            self._conn.execute(
                "UPDATE books SET last_opened = ?, "
                "title = CASE WHEN ? != '' THEN ? ELSE title END, "
                "author = CASE WHEN ? != '' THEN ? ELSE author END, "
                "language = CASE WHEN ? != '' THEN ? ELSE language END, "
                "cover = COALESCE(?, cover) WHERE id = ?",
                (_now(), title, title, author, author, language, language,
                 cover, book_id))
        else:
            cur = self._conn.execute(
                "INSERT INTO books (path, title, author, language, cover, added,"
                " last_opened) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (path, title, author, language, cover, _now(), _now()))
            book_id = int(cur.lastrowid)
        self._conn.commit()
        return book_id

    def remove_book(self, path: str) -> None:
        self._conn.execute(
            "DELETE FROM books WHERE path = ?", (os.path.abspath(path),))
        self._conn.commit()

    def _book_id(self, path: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM books WHERE path = ?",
            (os.path.abspath(path),)).fetchone()
        return int(row["id"]) if row else None

    def books(self, query: str | None = None) -> list[dict]:
        sql = "SELECT * FROM books"
        params: tuple = ()
        if query:
            sql += " WHERE title LIKE ? OR author LIKE ?"
            like = f"%{query}%"
            params = (like, like)
        sql += " ORDER BY last_opened DESC, added DESC"
        return [dict(row) for row in self._conn.execute(sql, params)]

    def get_book(self, path: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM books WHERE path = ?",
            (os.path.abspath(path),)).fetchone()
        return dict(row) if row else None

    def set_translated(self, path: str, translated_path: str) -> None:
        book_id = self.add_book(path)
        self._conn.execute(
            "UPDATE books SET translated_path = ? WHERE id = ?",
            (translated_path, book_id))
        self._conn.commit()

    def set_metadata(self, path: str, **values) -> None:
        book_id = self.add_book(path)
        allowed = {"title", "author", "language", "cover"}
        updates = {k: v for k, v in values.items() if k in allowed}
        if not updates:
            return
        columns = ", ".join(f"{k} = ?" for k in updates)
        self._conn.execute(
            f"UPDATE books SET {columns} WHERE id = ?",
            (*updates.values(), book_id))
        self._conn.commit()

    # -- positions --------------------------------------------------------
    def set_position(self, path: str, href: str | None,
                     fraction: float = 0.0) -> None:
        book_id = self.add_book(path)
        self._conn.execute(
            "INSERT INTO positions (book_id, href, fraction, updated) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(book_id) DO UPDATE SET href = excluded.href, "
            "fraction = excluded.fraction, updated = excluded.updated",
            (book_id, href, round(float(fraction), 4), _now()))
        self._conn.commit()

    def get_position(self, path: str) -> dict:
        row = self._conn.execute(
            "SELECT href, fraction FROM positions WHERE book_id = ?",
            (self._book_id(path) or -1,)).fetchone()
        if not row:
            return {}
        return {"href": row["href"], "fraction": row["fraction"]}

    # -- annotations ------------------------------------------------------
    def annotations(self, path: str) -> list[dict]:
        book_id = self._book_id(path)
        if book_id is None:
            return []
        rows = self._conn.execute(
            "SELECT id, text, note, color, created FROM annotations "
            "WHERE book_id = ? ORDER BY created", (book_id,)).fetchall()
        return [dict(row) for row in rows]

    def add_annotation(self, path: str, item: dict) -> None:
        book_id = self.add_book(path)
        self._conn.execute(
            "INSERT INTO annotations (book_id, text, note, color, created) "
            "VALUES (?, ?, ?, ?, ?)",
            (book_id, item.get("text", ""), item.get("note", ""),
             item.get("color", ""), _now()))
        self._conn.commit()

    def remove_annotation(self, path: str, index: int) -> None:
        book_id = self._book_id(path)
        if book_id is None:
            return
        rows = self._conn.execute(
            "SELECT id FROM annotations WHERE book_id = ? ORDER BY created",
            (book_id,)).fetchall()
        if 0 <= index < len(rows):
            self._conn.execute(
                "DELETE FROM annotations WHERE id = ?", (rows[index]["id"],))
            self._conn.commit()

    # -- migration --------------------------------------------------------
    def _auto_migrate(self) -> None:
        if self._conn.execute("SELECT COUNT(*) AS n FROM books").fetchone()["n"]:
            return
        legacy = data_dir() / "reader.json"
        if legacy.is_file():
            self.migrate_from_json(str(legacy))

    def migrate_from_json(self, json_path: str) -> int:
        """Import a legacy ``reader.json`` session; return imported book count."""
        try:
            data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        imported = 0
        for entry in data.get("recent", []):
            path = entry.get("path")
            if path:
                self.add_book(path, title=entry.get("title", ""))
                imported += 1
        for path, pos in (data.get("positions") or {}).items():
            self.set_position(path, pos.get("href"), pos.get("fraction", 0.0))
        for path, items in (data.get("annotations") or {}).items():
            for item in items:
                self.add_annotation(path, item)
        return imported
