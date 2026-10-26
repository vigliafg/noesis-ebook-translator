"""Help system: online (GitHub Pages) with an offline fallback (Qt-free).

The documentation site is built from ``docs/site`` and published to GitHub Pages
in five languages. The app links to the page for the current interface language
and falls back to a short local text (from the i18n catalog) when offline.
"""
from __future__ import annotations

import os

from . import i18n

__all__ = ["HELP_BASE_URL", "help_url", "local_help_dir", "fallback_html"]

#: Published GitHub Pages base URL.
HELP_BASE_URL = "https://vigliafg.github.io/noesis-ebook-translator"

#: Sections documented on the site (also used as page anchors/names).
SECTIONS = ("index", "getting-started", "install", "providers", "faq")


def help_url(lang: str | None = None, section: str = "index") -> str:
    """Return the online help URL for ``lang`` and ``section``."""
    lang = lang if lang in i18n.LANGUAGES else i18n.get_language()
    section = section or "index"
    if section in ("index", ""):
        return f"{HELP_BASE_URL}/{lang}/"
    return f"{HELP_BASE_URL}/{lang}/{section}.html"


def local_help_dir() -> str:
    """Directory holding the bundled (offline) documentation, if present."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base, "docs", "site", "docs"),
        os.path.join(base, "docs"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return ""


def fallback_html(lang: str | None = None) -> str:
    """A minimal offline help page built from the i18n catalog."""
    lang = lang if lang in i18n.LANGUAGES else i18n.get_language()
    previous = i18n.get_language()
    i18n.set_language(lang)
    try:
        title = i18n.T("help.title")
        intro = i18n.T("help.intro")
        url = help_url(lang)
    finally:
        i18n.set_language(previous)
    return (
        f"<h1>{title}</h1><p>{intro}</p>"
        f"<p><a href='{url}'>{url}</a></p>")
