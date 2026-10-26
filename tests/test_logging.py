"""Persistent log file and exception hook (never the stderr channel)."""
import logging
import sys
import tempfile
import unittest
from pathlib import Path

from noesis_ebook_translator import logging_setup


class TestLogging(unittest.TestCase):
    def setUp(self):
        logging_setup.reset_for_tests()
        self.old_hook = sys.excepthook
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "logs"

    def tearDown(self):
        logging_setup.reset_for_tests()
        sys.excepthook = self.old_hook
        self.tmp.cleanup()

    def test_writes_a_rotating_log_and_installs_the_hook(self):
        path = logging_setup.install(self.dir)
        self.assertIsNotNone(path)
        logging.getLogger("noesis").error("probe-message")
        text = Path(path).read_text("utf-8")
        self.assertIn("probe-message", text)
        self.assertIsNot(sys.excepthook, self.old_hook)

    def test_install_is_idempotent(self):
        first = logging_setup.install(self.dir)
        second = logging_setup.install(self.dir)
        self.assertEqual(first, second)
        logger = logging.getLogger("noesis")
        self.assertEqual(len(logger.handlers), 1)

    def test_unwritable_log_directory_does_not_crash(self):
        target = self.tmp.name + "/missing/child"
        # A file where a directory is expected makes mkdir fail.
        Path(self.tmp.name, "missing").write_text("x", "utf-8")
        self.assertIsNone(logging_setup.install(target))


if __name__ == "__main__":
    unittest.main()
