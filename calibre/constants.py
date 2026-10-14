"""Subset of :mod:`calibre.constants` used by the verbatim engine modules."""
from __future__ import annotations

import os

#: Version reported as the "host application" version in caches/logs.
__version__ = "noesis-ebook-translator"

#: Debug flag (enables verbose logging in a few engine modules).
DEBUG = bool(os.environ.get("CALIBRE_DEBUG"))


def _base_config_dir() -> str:
    override = os.environ.get("NOESIS_CONFIG_DIR")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys_platform_is_macos():
        base = os.path.join(os.path.expanduser("~"), "Library", "Preferences")
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "noesis-ebook-translator")


def sys_platform_is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


#: Directory where the app stores its configuration (JSON files).
config_dir = _base_config_dir()

os.makedirs(config_dir, exist_ok=True)
