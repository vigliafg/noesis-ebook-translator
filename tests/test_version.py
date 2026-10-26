"""The app version is separate from the verbatim engine version."""
import re
import unittest
from pathlib import Path

from noesis_ebook_translator import APP_VERSION, __version__

ROOT = Path(__file__).resolve().parent.parent


class TestVersion(unittest.TestCase):
    def test_app_version_is_a_semver_string(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")

    def test_engine_version_is_still_the_verbatim_tuple(self):
        # The engine version drives config migrations and cache metadata; the
        # app release must never overwrite it.
        self.assertTrue(__version__.startswith("v"))
        self.assertNotEqual(APP_VERSION, __version__.lstrip("v"))

    def test_pyproject_matches(self):
        # Deliberately a regex (no tomllib): the project supports Python 3.10.
        text = (ROOT / "pyproject.toml").read_text("utf-8")
        match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), APP_VERSION)

    def test_installer_default_matches(self):
        text = (ROOT / "installer.nsi").read_text("utf-8", errors="replace")
        match = re.search(r'!define\s+VERSION\s+"([^"]+)"', text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), APP_VERSION)

    def test_changelog_has_the_release(self):
        text = (ROOT / "CHANGELOG.md").read_text("utf-8")
        self.assertIn(f"## [{APP_VERSION}]", text)

    def test_version_flag_does_not_start_the_gui(self):
        import contextlib
        import io
        import main as entry

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(entry.main(["--version"]), 0)
        self.assertIn(APP_VERSION, stream.getvalue())


if __name__ == "__main__":
    unittest.main()
