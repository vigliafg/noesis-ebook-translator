#!/usr/bin/env python3
"""Import the verbatim translation engine from the Calibre plugin fork.

This project (the desktop GUI) is the **source of truth** of the translation
engine: ``noesis_ebook_translator/lib``, ``noesis_ebook_translator/engines`` and
``noesis_ebook_translator/vendor`` are copies **verbatim** of the fork of the
upstream Calibre plugin ``bookfere/Ebook-Translator-Calibre-Plugin``.

The script copies those directories, *without* touching files that are already
byte-identical, and records the provenance in ``ENGINE_SOURCE.json``.

The single intentional deviation is ``engines/__init__.py``: the fork had
dropped some engines from ``builtin_engines`` and this app restores the full set,
so it must never be overwritten (it is listed under ``overrides``).

Usage::

    python tools/import_core_from_fork.py
    python tools/import_core_from_fork.py --fork /path/to/Ebook-Translator-Calibre-Plugin
    python tools/import_core_from_fork.py --fork ../Ebook-Translator-Calibre-Plugin
"""
from __future__ import annotations

import argparse
import datetime as _dt
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
#  Paths and constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_PKG = REPO_ROOT / "noesis_ebook_translator"
MANIFEST = REPO_ROOT / "ENGINE_SOURCE.json"

#: Default fork location (sibling of this repository). Override with --fork or
#: the NOESIS_ET_FORK environment variable.
DEFAULT_FORK = Path(os.environ.get(
    "NOESIS_ET_FORK", REPO_ROOT.parent / "Ebook-Translator-Calibre-Plugin"))

#: ``lib/`` modules copied verbatim (order = order in the manifest).
LIB_FILES = (
    "__init__.py",
    "element.py",
    "utils.py",
    "exception.py",
    "encodings.py",
    "handler.py",
    "translation.py",
    "config.py",
    "cache.py",
)

#: Files that are intentionally NOT verbatim (local overrides).
OVERRIDES = ("engines/__init__.py",)

#: Local engine extensions (files that do not exist in the fork at all). They
#: are part of the engine and must be inlined by the engine repo's sync script
#: (``tools/sync_from_desktop.py`` -> ``CORE_MODULES``).
EXTENSIONS = ("engines/openai_compatible.py",)

#: Directory names never copied.
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

_VERSION_RE = re.compile(r"version\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _run_git(fork: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(fork), *args],
            capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    text = out.stdout.strip()
    return text or None


def _fork_commit(fork: Path) -> str | None:
    return _run_git(fork, "rev-parse", "HEAD")


def _fork_repo(fork: Path) -> str:
    return _run_git(fork, "config", "--get", "remote.origin.url") or str(fork)


def _fork_version(fork: Path) -> str | None:
    init = fork / "__init__.py"
    if not init.is_file():
        return None
    match = _VERSION_RE.search(init.read_text(encoding="utf-8"))
    return ".".join(match.groups()) if match else None


def _identical(src: Path, dst: Path) -> bool:
    try:
        return dst.is_file() and filecmp.cmp(src, dst, shallow=False)
    except OSError:
        return False


def _copy(
    src: Path,
    dst: Path,
    rel: str,
    verbatim: list[str],
    changed: list[str],
) -> None:
    """Copy ``src`` -> ``dst`` unless already identical; record it either way."""
    verbatim.append(rel)
    if _identical(src, dst):
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    changed.append(rel)


def _copy_tree(
    src_dir: Path,
    dst_dir: Path,
    prefix: str,
    verbatim: list[str],
    changed: list[str],
) -> None:
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file():
            continue
        if set(path.parts) & SKIP_DIRS or path.suffix in SKIP_SUFFIXES:
            continue
        rel = (Path(prefix) / path.relative_to(src_dir)).as_posix()
        _copy(path, dst_dir / path.relative_to(src_dir), rel, verbatim, changed)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
def import_core(fork: Path) -> int:
    fork = fork.expanduser().resolve()
    src_lib = fork / "lib"
    src_engines = fork / "engines"
    src_vendor = fork / "vendor"

    if not src_lib.is_dir() or not src_engines.is_dir():
        print(f"error: '{fork}' is not an Ebook-Translator fork "
              f"(missing lib/ or engines/)", file=sys.stderr)
        return 2

    verbatim: list[str] = []
    changed: list[str] = []

    # 1) lib/ — the explicit list of verbatim modules.
    for name in LIB_FILES:
        src = src_lib / name
        if not src.is_file():
            print(f"warning: missing {src}", file=sys.stderr)
            continue
        _copy(src, TARGET_PKG / "lib" / name, f"lib/{name}", verbatim, changed)

    # 2) engines/*.py — everything except the locally-overridden __init__.py.
    for src in sorted(src_engines.glob("*.py")):
        if src.name == "__init__.py":
            continue
        _copy(src, TARGET_PKG / "engines" / src.name,
              f"engines/{src.name}", verbatim, changed)

    # 3) vendor/ — the whole tree.
    if src_vendor.is_dir():
        _copy_tree(src_vendor, TARGET_PKG / "vendor", "vendor", verbatim, changed)
    else:
        print(f"warning: missing {src_vendor}", file=sys.stderr)

    # 4) Provenance manifest.
    manifest = {
        "fork_repo": _fork_repo(fork),
        "fork_commit": _fork_commit(fork),
        "fork_version": _fork_version(fork),
        "synced_at": _dt.datetime.now(_dt.timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verbatim": verbatim,
        "overrides": list(OVERRIDES),
        "extensions": list(EXTENSIONS),
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")

    # 5) Summary.
    print(f"fork:      {fork}")
    print(f"repo:      {manifest['fork_repo']}")
    print(f"commit:    {manifest['fork_commit']}")
    print(f"version:   {manifest['fork_version']}")
    print(f"target:    {TARGET_PKG.relative_to(REPO_ROOT)}")
    print(f"manifest:  {MANIFEST.name}")
    print(f"verbatim:  {len(verbatim)} files "
          f"({len(changed)} copied, {len(verbatim) - len(changed)} unchanged)")
    for rel in changed:
        print(f"  ~ {rel}")
    print(f"overrides: {', '.join(OVERRIDES)} (never overwritten)")
    print(f"extensions: {', '.join(EXTENSIONS)} (local, inlined by the engine repo)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy the verbatim Ebook Translator engine from the "
                    "Calibre plugin fork and refresh ENGINE_SOURCE.json.")
    parser.add_argument(
        "--fork", type=Path, default=DEFAULT_FORK,
        help="path to the Ebook-Translator-Calibre-Plugin fork "
             f"(default: {DEFAULT_FORK})")
    args = parser.parse_args(argv)
    return import_core(args.fork)


if __name__ == "__main__":
    sys.exit(main())
