"""Minimal ``calibre`` compatibility shim for the headless engine.

The translation engine in :mod:`noesis_ebook_translator` is imported **verbatim**
from the upstream Calibre plugin
(``bookfere/Ebook-Translator-Calibre-Plugin``). A handful of those modules import
a few helpers from Calibre (``get_proxies``, ``prepare_string_for_xml``,
``load_translations``…). This package provides just enough of that API so the
same, unmodified source runs standalone, without Calibre installed.

Two things happen here at import time:

* ``load_translations`` is injected into :mod:`builtins` (Calibre does the same),
  because several engine modules call it as a bare builtin;
* the small utility functions used by ``lib/utils.py`` are defined.

This module is only meant to be used when running the app from source or from a
bundled build; it is intentionally *not* published as a pip package named
``calibre``.
"""
from __future__ import annotations

import builtins
import os
import re

__all__ = [
    "load_translations",
    "get_proxies",
    "prepare_string_for_xml",
    "sanitize_file_name",
]


def load_translations(*args, **kwargs) -> None:
    """No-op stand-in for Calibre's runtime translation loader."""
    return None


# Calibre exposes ``load_translations`` as a global builtin (plugins call it
# without importing it); replicate that so the verbatim engine modules work.
if not hasattr(builtins, "load_translations"):
    builtins.load_translations = load_translations


def get_proxies(verbose: bool = False) -> dict[str, str]:
    """Return the HTTP(S) proxies configured through the environment.

    Mirrors the return shape of :func:`calibre.get_proxies`: a mapping with
    optional ``http`` / ``https`` keys.
    """
    proxies: dict[str, str] = {}
    for scheme in ("http", "https"):
        for var in (f"{scheme}_proxy", f"{scheme.upper()}_PROXY"):
            value = os.environ.get(var)
            if value:
                proxies[scheme] = value
                break
    return proxies


def prepare_string_for_xml(raw: str, attribute: bool = False) -> str:
    """Escape ``&``, ``<`` and ``>`` (and quotes when ``attribute`` is true).

    Matches the behaviour of ``calibre.prepare_string_for_xml`` which the engine
    imports as ``xml_escape``.
    """
    raw = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if attribute:
        raw = raw.replace('"', "&quot;").replace("'", "&apos;")
    return raw


def sanitize_file_name(name: str, replacement: str = "_") -> str:
    """Return a filesystem-safe version of ``name``."""
    if not name:
        return name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    for char in '\\/:*?"<>|':
        name = name.replace(char, replacement)
    return name.strip().strip(".")
