"""Lightweight UI internationalization backed by JSON catalogs.

The app ships one JSON file per language under ``noesis_ebook_translator/locales/``
(Italian, English, French, Spanish, German). The English catalog is the fallback
and the reference for the key set; a parity test guarantees all catalogs define
exactly the same keys.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = [
    "T", "get_language", "set_language", "LANGUAGES", "language_label",
    "available_languages", "catalog", "catalog_keys", "reload",
]

#: Catalog directory (``noesis_ebook_translator/locales``).
_CATALOG_DIR = Path(__file__).resolve().parent / "locales"

#: Ordered languages. Keys are the catalog file stems; values are the native
#: display names.
LANGUAGES = {
    "it": "Italiano",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
}

#: Default/fallback language.
_DEFAULT = "en"
_current = _DEFAULT

#: Loaded catalogs, keyed by language code.
_CATALOGS: dict[str, dict[str, str]] = {}


def _load_catalog(lang: str) -> dict[str, str]:
    path = _CATALOG_DIR / f"{lang}.json"
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _catalog(lang: str) -> dict[str, str]:
    if lang not in _CATALOGS:
        _CATALOGS[lang] = _load_catalog(lang)
    return _CATALOGS[lang]


def reload() -> None:
    """Drop cached catalogs (used by tests and after edits)."""
    _CATALOGS.clear()


def available_languages() -> list[str]:
    """Return the languages that actually have a catalog file."""
    found = [lang for lang in LANGUAGES if (_CATALOG_DIR / f"{lang}.json").is_file()]
    return found or [_DEFAULT]


def get_language() -> str:
    return _current


def set_language(lang: str) -> None:
    global _current
    if lang in LANGUAGES:
        _current = lang


def language_label(lang: str) -> str:
    return LANGUAGES.get(lang, lang)


def catalog(lang: str | None = None) -> dict[str, str]:
    """Return a copy of the catalog for ``lang`` (current language by default)."""
    return dict(_catalog(lang or _current))


def catalog_keys(lang: str | None = None) -> set[str]:
    return set(_catalog(lang or _current).keys())


def T(key: str) -> str:
    """Translate ``key`` using the current language (English fallback)."""
    table = _catalog(_current)
    if key in table:
        return table[key]
    fallback = _catalog(_DEFAULT)
    return fallback.get(key, key)


def _ensure_loaded() -> None:
    # Warm the fallback catalog so ``T`` never returns a bare key by accident.
    _catalog(_DEFAULT)


_ensure_loaded()
