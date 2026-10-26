# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the desktop release (onedir).

Run from the repository root:

    pyinstaller packaging/app.spec --noconfirm --clean

`--onedir` is deliberate: QtWebEngine needs its helper process and resources
next to the executable, and a one-file build would extract hundreds of MB on
every launch (and break macOS signing/notarization later).
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))

from noesis_ebook_translator import APP_VERSION  # noqa: E402

datas = [
    (str(ROOT / "assets" / "noesis-ebook-translator.png"), "assets"),
    (str(ROOT / "assets" / "icons"), "assets/icons"),
    (str(ROOT / "reader_web"), "reader_web"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
if (ROOT / "LICENSES").is_dir():
    datas.append((str(ROOT / "LICENSES"), "LICENSES"))

package_datas, package_binaries, package_hidden = collect_all(
    "noesis_ebook_translator")
datas += package_datas

hiddenimports = package_hidden + [
    "calibre",
    "tiktoken_ext.openai_public",
] + collect_submodules("calibre")

if sys.platform == "win32":
    icon = str(ROOT / "assets" / "noesis-ebook-translator.ico")
elif sys.platform == "darwin":
    icon = str(ROOT / "assets" / "noesis-ebook-translator.icns")
else:
    icon = None

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=package_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tests", "tools", "speedtest", "corpus1",
        "pytest", "tkinter", "PIL",
        # Not used by the app or the engine; the system Qt build pulled them in
        # through optional multimedia/plotting modules (numpy/openblas is ~70 MB).
        "numpy", "scipy", "pandas", "matplotlib", "IPython",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NoesisEbookTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NoesisEbookTranslator",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="NoesisEbookTranslator.app",
        icon=icon,
        bundle_identifier="com.vigliafg.noesis-ebook-translator",
        info_plist={
            "CFBundleDisplayName": "Noesis Ebook Translator",
            "CFBundleName": "NoesisEbookTranslator",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "LSMinimumSystemVersion": "13.0",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright":
                "GPL-3.0-or-later; engine derived from bookfere's Ebook Translator",
        },
    )
