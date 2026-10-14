"""Noesis Ebook Translator — headless translation engine + desktop GUI.

The :mod:`noesis_ebook_translator.lib` and :mod:`noesis_ebook_translator.engines`
sub-packages are imported **verbatim** from the upstream Calibre plugin
``bookfere/Ebook-Translator-Calibre-Plugin`` (see ``ENGINE_SOURCE.json`` and
``tools/import_core_from_fork.py``). This module only provides the two symbols
those modules expect from the plugin root package (``EbookTranslator`` and
``_z``) and makes sure Calibre's runtime builtins are available.
"""
from __future__ import annotations

import builtins

__all__ = ["EbookTranslator", "_z", "__version__", "identifier", "author", "APP_NAME"]

#: Human-readable application name.
APP_NAME = "Noesis Ebook Translator"

#: Application / engine version. Kept in sync with the plugin's tuple shape.
version = (2, 4, 2)
__version__ = "v" + ".".join(str(part) for part in version)

#: Same identifiers the upstream plugin exposes (used for cache metadata).
identifier = "noesis_ebook_translator"
author = "vigliafg"


def _z(message):
    """Identity marker used by some engine aliases (matches the plugin)."""
    return message


class EbookTranslator:
    """Namespace mirroring the plugin root class, for engine compatibility."""

    name = "Noesis Ebook Translator"
    version = version
    __version__ = __version__
    identifier = identifier
    author = author


def load_translations(*args, **kwargs):  # pragma: no cover - compatibility
    return None


# Calibre injects ``load_translations`` as a builtin at runtime; several verbatim
# engine modules call it as a bare name, so make it available globally.
if not hasattr(builtins, "load_translations"):
    builtins.load_translations = load_translations
