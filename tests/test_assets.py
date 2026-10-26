"""Release assets: icons exist, are valid and are referenced by the packagers."""
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


class TestAssets(unittest.TestCase):
    def test_app_icons_are_present_and_valid(self):
        png = ASSETS / "noesis-ebook-translator.png"
        ico = ASSETS / "noesis-ebook-translator.ico"
        icns = ASSETS / "noesis-ebook-translator.icns"
        for path in (png, ico, icns):
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 1000, path)
        width, height = _png_size(png)
        self.assertGreaterEqual(width, 512)
        self.assertEqual(width, height)
        self.assertEqual(ico.read_bytes()[:4], b"\x00\x00\x01\x00")
        self.assertEqual(icns.read_bytes()[:4], b"icns")

    def test_linux_icon_is_256(self):
        png = (ASSETS / "linux" / "hicolor" / "256x256" / "apps"
               / "noesis-ebook-translator.png")
        self.assertTrue(png.is_file())
        self.assertEqual(_png_size(png), (256, 256))

    def test_packagers_reference_the_icons(self):
        nsis = (ROOT / "installer.nsi").read_text("utf-8", errors="replace")
        self.assertIn("assets\\noesis-ebook-translator.ico", nsis)
        spec = (ROOT / "packaging" / "app.spec").read_text("utf-8")
        self.assertIn("noesis-ebook-translator.ico", spec)
        self.assertIn("noesis-ebook-translator.icns", spec)


if __name__ == "__main__":
    unittest.main()
