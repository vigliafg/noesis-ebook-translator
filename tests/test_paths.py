"""Data-directory split and the one-time copy migration."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from noesis_ebook_translator import paths


def _db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE t (value TEXT)")
        connection.execute("INSERT INTO t VALUES ('ok')")


class TestDataDir(unittest.TestCase):
    def setUp(self):
        paths.reset_for_tests()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "config"
        self.data = self.root / "data"
        self.old = self.config / "noesis-ebook-translator"
        self.new = self.data / "noesis-ebook-translator"

    def tearDown(self):
        paths.reset_for_tests()
        self.tmp.cleanup()

    def _patch(self):
        return (
            mock.patch.object(paths, "_override", lambda: None),
            mock.patch.object(paths, "_config_base_dir", lambda: self.config),
            mock.patch.object(paths, "_data_base_dir", lambda: self.data),
        )

    def test_override_keeps_config_and_data_together(self):
        with mock.patch.dict(os.environ, {"NOESIS_CONFIG_DIR": str(self.root)}):
            self.assertEqual(paths.data_dir(), self.root / "noesis-ebook-translator")
            self.assertEqual(paths.legacy_data_dir(),
                             self.root / "noesis-ebook-translator")

    def test_platform_roots_become_the_data_directory(self):
        patches = self._patch()
        with patches[0], patches[1], patches[2]:
            self.assertEqual(paths.data_dir(), self.new)

    def test_migration_copies_and_keeps_the_originals(self):
        _db(self.old / "library.db")
        (self.old / "reader.json").write_text(json.dumps({"books": []}), "utf-8")
        _db(self.old / "translator-cache" / "cache" / "book.db")

        patches = self._patch()
        with patches[0], patches[1], patches[2]:
            self.assertTrue(paths.migrate_legacy_data())
            self.assertTrue((self.new / "library.db").is_file())
            self.assertTrue((self.new / "reader.json").is_file())
            self.assertTrue(
                (self.new / "translator-cache" / "cache" / "book.db").is_file())
            self.assertTrue((self.new / ".migrated-from-config").is_file())
            self.assertTrue((self.old / "library.db").is_file())
            self.assertEqual(paths.data_dir(), self.new)
            # Idempotent: the marker and the existing files stop a second copy.
            self.assertTrue(paths.migrate_legacy_data())

    def test_corrupt_database_falls_back_to_the_old_directory(self):
        self.old.mkdir(parents=True)
        (self.old / "library.db").write_bytes(b"this is not sqlite")
        patches = self._patch()
        with patches[0], patches[1], patches[2]:
            self.assertFalse(paths.migrate_legacy_data())
            self.assertEqual(paths.data_dir(), self.old)
            self.assertFalse((self.new / "library.db").exists())

    def test_live_wal_defers_the_migration(self):
        _db(self.old / "library.db")
        (self.old / "library.db-wal").write_bytes(b"pending")
        patches = self._patch()
        with patches[0], patches[1], patches[2]:
            self.assertFalse(paths.migrate_legacy_data())
            self.assertEqual(paths.data_dir(), self.old)
            self.assertFalse((self.new / "library.db").exists())

    def test_no_old_directory_is_not_an_error(self):
        patches = self._patch()
        with patches[0], patches[1], patches[2]:
            self.assertTrue(paths.migrate_legacy_data())
            self.assertEqual(paths.data_dir(), self.new)


if __name__ == "__main__":
    unittest.main()
