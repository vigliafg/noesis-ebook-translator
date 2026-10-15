#!/usr/bin/env python3
"""Build the app's colored icons from Microsoft Fluent Emoji (MIT).

Downloads a curated set of Fluent Emoji "Color" SVGs, rasterizes them to PNG
(96 px, transparent background) and writes them to ``assets/icons/`` together
with ``assets/icons/icons.json`` (the name → file map) and an attribution file.

The default semantic names are used by ``noesis_ebook_translator/ui/icons.py``.

Usage::

    python tools/build_icons.py            # download + build all icons
    python tools/build_icons.py --check    # only report what is missing locally
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "assets" / "icons"
RAW = ("https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/"
       "assets/{folder}/Color/{file}_color.svg")

#: semantic name → (Fluent Emoji folder, file stem)
ICONS: dict[str, tuple[str, str]] = {
    "library": ("Books", "books"),
    "reader": ("Open book", "open_book"),
    "assets": ("Framed picture", "framed_picture"),
    "translate": ("Globe showing europe-africa", "globe_showing_europe-africa"),
    "quality": ("Glowing star", "glowing_star"),
    "export": ("Outbox tray", "outbox_tray"),
    "tools": ("Toolbox", "toolbox"),
    "info": ("Information", "information"),
    "settings": ("Gear", "gear"),
    "help": ("Light bulb", "light_bulb"),
    "wizard": ("Crystal ball", "crystal_ball"),
    "theme": ("Artist palette", "artist_palette"),
    "find": ("Magnifying glass tilted left", "magnifying_glass_tilted_left"),
    "zoom_in": ("Magnifying glass tilted right", "magnifying_glass_tilted_right"),
    "zoom_out": ("Magnifying glass tilted left", "magnifying_glass_tilted_left"),
    "split": ("Scissors", "scissors"),
    "merge": ("Link", "link"),
    "cache": ("Card file box", "card_file_box"),
    "save": ("Floppy disk", "floppy_disk"),
    "folder": ("Open file folder", "open_file_folder"),
    "file_folder": ("File folder", "file_folder"),
    "add": ("Plus", "plus"),
    "remove": ("Wastebasket", "wastebasket"),
    "refresh": ("Counterclockwise arrows button", "counterclockwise_arrows_button"),
    "edit": ("Pencil", "pencil"),
    "print": ("Printer", "printer"),
    "note": ("Memo", "memo"),
    "bookmark": ("Bookmark tabs", "bookmark_tabs"),
    "chapters": ("Bookmark tabs", "bookmark_tabs"),
    "engine": ("Robot", "robot"),
    "model": ("Brain", "brain"),
    "key": ("Key", "key"),
    "language": ("Globe with meridians", "globe_with_meridians"),
    "options": ("Level slider", "level_slider"),
    "preview": ("Eye", "eye"),
    "metadata": ("Label", "label"),
    "format": ("Page facing up", "page_facing_up"),
    "report": ("Clipboard", "clipboard"),
    "license": ("Scroll", "scroll"),
    "diagnostic": ("Stethoscope", "stethoscope"),
    "cancel": ("Cross mark", "cross_mark"),
    "check": ("Check mark button", "check_mark_button"),
    "manipulate": ("Hammer and wrench", "hammer_and_wrench"),
    "package": ("Package", "package"),
    "closed_book": ("Closed book", "closed_book"),
    "swap": ("Counterclockwise arrows button", "counterclockwise_arrows_button"),
    "prompt": ("Left speech bubble", "left_speech_bubble"),
    "upstream": ("Linked paperclips", "linked_paperclips"),
    "sample": ("Wrapped gift", "wrapped_gift"),
    "parallel": ("Counterclockwise arrows button", "counterclockwise_arrows_button"),
}

ATTRIBUTION = """\
Icons in this directory are from Microsoft Fluent Emoji
(https://github.com/microsoft/fluentui-emoji), licensed under the MIT License.

Copyright (c) Microsoft Corporation.
"""


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "noesis-build-icons"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _rasterize(svg_bytes: bytes, size: int = 96):
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg_bytes))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return image


def build(check_only: bool = False) -> int:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    missing: list[str] = []
    written = 0
    for name, (folder, stem) in ICONS.items():
        target = ICONS_DIR / f"{name}.png"
        manifest[name] = f"{name}.png"
        if target.is_file() and check_only:
            continue
        if target.is_file():
            # Already built; keep it (idempotent).
            continue
        url = RAW.format(folder=urllib.parse.quote(folder), file=stem)
        try:
            svg = _download(url)
            from PyQt6.QtGui import QGuiApplication
            app = QGuiApplication.instance() or QGuiApplication([])
            image = _rasterize(svg)
            image.save(str(target), "PNG")
            written += 1
            print(f"  + {name}.png  ({folder})")
        except Exception as exc:  # noqa: BLE001 - report and continue
            missing.append(name)
            print(f"  ! {name}: {exc}", file=sys.stderr)

    (ICONS_DIR / "icons.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (ICONS_DIR / "LICENSE").write_text(ATTRIBUTION, encoding="utf-8")
    print(f"icons: {written} written, {len(missing)} missing "
          f"({', '.join(missing) if missing else 'none'})")
    return 1 if missing else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="do not download; only verify the PNGs exist")
    args = ap.parse_args(argv)
    return build(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
