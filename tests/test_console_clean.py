"""Assert that our entry points stay **clean on stderr**.

An exception raised inside a Qt slot does not fail a test (PyQt prints it and
carries on) and Chromium warnings are invisible to ``unittest``; that is why the
reported ``AttributeError`` and the WebEngine shutdown warning survived so long.
Each path runs in a subprocess so its streams can be read and asserted.

Platform noise from a headless session (Vulkan/GL/GPU probes by the Qt platform
plugin) is allow-listed: it is not produced by our code, and a desktop session
does not print it.
"""
import os
import subprocess
import sys
import tempfile
import unittest

from tests.harness import webengine_available

#: Anything matching one of these means a real problem reached the console.
FORBIDDEN = (
    "Traceback (most recent call last)",
    "AttributeError",
    "TypeError",
    "ValueError",
    "LineEdit",
    "Release of profile requested",
    "Segmentation fault",
    "SIGSEGV",
    "Fatal Python error",
    "QObject::",
)
#: Headless platform noise (GPU/Vulkan probing) -- not ours, and absent on a
#: normal desktop session.
ALLOWED = (
    "QRhiGles2",
    "Vulkan",
    "Unable to detect GPU vendor",
    "createPlatformVulkanInstance",
    "libpng error",
    "propagateSizeHints",
    "Sandboxing disabled",
    "GL implementation",
    "Fontconfig",
    "XDG_RUNTIME_DIR",
    "QStandardPaths",
)


def noisy_lines(text: str) -> list[str]:
    """Lines that indicate a problem (platform noise excluded)."""
    found = []
    for line in text.splitlines():
        if not line.strip() or any(token in line for token in ALLOWED):
            continue
        if any(token in line for token in FORBIDDEN):
            found.append(line.strip())
    return found


class TestConsoleClean(unittest.TestCase):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _run(self, probe: str, *, timeout: int = 300) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["NOESIS_READER_BACKEND"] = "lite"
        env["NOESIS_CONFIG_DIR"] = tempfile.mkdtemp(prefix="noesis-console-")
        return subprocess.run(
            [sys.executable, "-m", "tests.console_probe", probe],
            cwd=self.root, env=env, capture_output=True, text=True,
            timeout=timeout)

    def _assert_clean(self, proc: subprocess.CompletedProcess, probe: str) -> None:
        self.assertEqual(
            proc.returncode, 0,
            f"{probe} exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
        noisy = noisy_lines(proc.stdout + "\n" + proc.stderr)
        self.assertEqual(
            noisy, [],
            f"{probe} wrote problematic lines to the console:\n  "
            + "\n  ".join(noisy))

    def test_gui_start_open_and_close_is_quiet(self):
        """Exercises the library signal paths and the window teardown."""
        self._assert_clean(self._run("gui"), "gui")

    def test_engine_translation_is_quiet(self):
        self._assert_clean(self._run("engine"), "engine")

    @unittest.skipUnless(webengine_available(), "QtWebEngine not installed")
    def test_full_reader_is_quiet(self):
        """The iframe-sandbox warning and the profile teardown must be silent."""
        self._assert_clean(self._run("reader"), "reader")


class TestNoisyLineDetection(unittest.TestCase):
    """The detector itself must catch the real thing and ignore the platform."""

    def test_catches_a_slot_exception(self):
        text = ("Traceback (most recent call last):\n"
                "  File \"x.py\", line 1, in <module>\n"
                "AttributeError: 'NoneType' object has no attribute 'data'\n")
        self.assertEqual(len(noisy_lines(text)), 2)

    def test_catches_the_webengine_warning(self):
        self.assertTrue(noisy_lines(
            "Release of profile requested but WebEnginePage still not "
            "deleted. Expect troubles !"))

    def test_ignores_platform_noise(self):
        text = ("QRhiGles2: Failed to create context\n"
                "Unable to detect GPU vendor.\n"
                "This plugin does not support createPlatformVulkanInstance\n"
                "libpng error: IDAT: CRC error\n")
        self.assertEqual(noisy_lines(text), [])


if __name__ == "__main__":
    unittest.main()
