"""Subset of :mod:`calibre.utils.localization` used by the engine.

Provides the gettext-style ``_()`` helper and ``lang_as_iso639_1()``. The
translation function is pluggable so the GUI/CLI can install the real catalogs
via :func:`install_translator`; without one it degrades to the identity.
"""
from __future__ import annotations

import builtins
from typing import Callable

__all__ = ["_", "lang_as_iso639_1", "load_translations", "install_translator"]

_translator: Callable[[str], str] | None = None


def install_translator(func: Callable[[str], str] | None) -> None:
    """Install the function used by ``_()`` (None restores the identity)."""
    global _translator
    _translator = func


def _(message: str) -> str:
    if _translator is not None:
        return _translator(message)
    return message


def load_translations(*args, **kwargs) -> None:
    """No-op: this standalone build ships its own catalogs."""
    return None


#: A minimal ISO 639-2/T → 639-1 map (the inverse of what ``languages.py``
#: stores). Unknown codes are returned unchanged.
_ISO639_1 = {
    "eng": "en", "ita": "it", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de",
    "spa": "es", "por": "pt", "nld": "nl", "dut": "nl", "pol": "pl", "rus": "ru",
    "jpn": "ja", "kor": "ko", "zho": "zh", "chi": "zh", "ara": "ar", "tur": "tr",
    "vie": "vi", "heb": "he", "ell": "el", "gre": "el", "ces": "cs", "dan": "da",
    "swe": "sv", "fin": "fi", "nor": "no", "ukr": "uk", "ron": "ro", "hun": "hu",
}


def lang_as_iso639_1(lang_code: str) -> str:
    """Return the ISO 639-1 code for ``lang_code`` (best effort)."""
    if not lang_code:
        return lang_code
    return _ISO639_1.get(lang_code.lower(), lang_code)


# Calibre injects the gettext helper ``_`` as a global builtin; several verbatim
# engine modules use it without importing it, so replicate that here. Because
# ``_`` delegates to the (mutable) installed translator, the builtin stays valid
# after :func:`install_translator`.
builtins._ = _

