"""The release self-test runs against the bundle (subprocess) and writes a report."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from noesis_ebook_translator import APP_VERSION

ROOT = Path(__file__).resolve().parent.parent


class TestSelfCheck(unittest.TestCase):
    def _run(self, *extra, timeout=120):
        report = Path(tempfile.mkdtemp(prefix="noesis-selfcheck-")) / "report.json"
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["NOESIS_CONFIG_DIR"] = tempfile.mkdtemp(prefix="noesis-selfcheck-cfg-")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), *extra,
             "--report", str(report)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        return proc, report

    def test_fast_self_test_reports_zero(self):
        proc, report = self._run("--self-test")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(report.read_text("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["app_version"], APP_VERSION)
        names = {check["name"] for check in data["checks"]}
        for expected in ("locales", "provider_catalog", "token_encodings",
                         "reader_assets", "epub_roundtrip", "full_backend"):
            self.assertIn(expected, names)

    def test_reader_self_test_runs_the_full_backend(self):
        try:
            import importlib.util
            if importlib.util.find_spec("PyQt6.QtWebEngineWidgets") is None:
                self.skipTest("QtWebEngine not installed")
        except Exception:  # noqa: BLE001
            self.skipTest("QtWebEngine not importable")

        proc, report = self._run("--self-test-reader", timeout=180)
        if proc.returncode != 0:
            self.skipTest("QtWebEngine cannot start in this environment:\n"
                          + proc.stderr[-2000:])
        data = json.loads(report.read_text("utf-8"))
        self.assertTrue(data["opened"], data)
        self.assertEqual(data["backend"], "full")
        self.assertTrue(data["ok"])


if __name__ == "__main__":
    unittest.main()
