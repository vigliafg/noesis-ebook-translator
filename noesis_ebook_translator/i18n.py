"""Lightweight UI internationalization (Italian default, English fallback)."""
from __future__ import annotations

__all__ = ["T", "get_language", "set_language", "LANGUAGES", "language_label"]

LANGUAGES = {
    "it": "Italiano",
    "en": "English",
}

_DEFAULT = "it"
_current = _DEFAULT

_STRINGS: dict[str, dict[str, str]] = {
    "it": {
        "app.title": "Noesis Ebook Translator",
        "tab.home": "Home",
        "tab.engine": "Motore",
        "tab.language": "Lingua",
        "tab.options": "Opzioni",
        "tab.info": "Info",
        "panel.file": "File",
        "panel.run": "Traduzione",
        "panel.engine": "Motore di traduzione",
        "panel.credentials": "Credenziali",
        "panel.model": "Modello e prompt",
        "panel.languages": "Lingue",
        "panel.output": "Uscita",
        "panel.rules": "Regole",
        "action.open": "Apri EPUB…",
        "action.translate": "Traduci",
        "action.cancel": "Annulla",
        "action.open_output": "Apri cartella",
        "label.input": "File di input",
        "label.output": "File di output",
        "label.source": "Lingua di origine",
        "label.target": "Lingua di destinazione",
        "label.position": "Posizione traduzione",
        "label.api_key": "Chiave API",
        "label.model": "Modello",
        "label.prompt": "Prompt",
        "label.batch": "Batching online",
        "label.cache": "Usa cache",
        "label.bilingual": "Testo bilingue (originale + traduzione)",
        "position.only": "Solo traduzione",
        "position.below": "Sotto l'originale",
        "position.above": "Sopra l'originale",
        "status.ready": "Pronto",
        "status.translating": "Traduzione in corso…",
        "status.done": "Completato",
        "status.failed": "Errore",
        "status.canceled": "Annullato",
        "msg.no_input": "Seleziona prima un file EPUB.",
        "msg.done": "Traduzione completata:\n{}",
        "about.text": (
            "Noesis Ebook Translator\n\n"
            "Traduzione di EPUB con il motore Ebook Translator (GPLv3).\n"
            "Engine e gestione elementi derivano dal plugin Calibre di bookfere."
        ),
    },
    "en": {
        "app.title": "Noesis Ebook Translator",
        "tab.home": "Home",
        "tab.engine": "Engine",
        "tab.language": "Language",
        "tab.options": "Options",
        "tab.info": "About",
        "panel.file": "File",
        "panel.run": "Translation",
        "panel.engine": "Translation engine",
        "panel.credentials": "Credentials",
        "panel.model": "Model & prompt",
        "panel.languages": "Languages",
        "panel.output": "Output",
        "panel.rules": "Rules",
        "action.open": "Open EPUB…",
        "action.translate": "Translate",
        "action.cancel": "Cancel",
        "action.open_output": "Open folder",
        "label.input": "Input file",
        "label.output": "Output file",
        "label.source": "Source language",
        "label.target": "Target language",
        "label.position": "Translation position",
        "label.api_key": "API key",
        "label.model": "Model",
        "label.prompt": "Prompt",
        "label.batch": "Online batching",
        "label.cache": "Use cache",
        "label.bilingual": "Bilingual text (original + translation)",
        "position.only": "Translation only",
        "position.below": "Below the original",
        "position.above": "Above the original",
        "status.ready": "Ready",
        "status.translating": "Translating…",
        "status.done": "Done",
        "status.failed": "Failed",
        "status.canceled": "Canceled",
        "msg.no_input": "Please choose an EPUB file first.",
        "msg.done": "Translation finished:\n{}",
        "about.text": (
            "Noesis Ebook Translator\n\n"
            "Translate EPUB with the Ebook Translator engine (GPLv3).\n"
            "Engines and element handling come from bookfere's Calibre plugin."
        ),
    },
}


def get_language() -> str:
    return _current


def set_language(lang: str) -> None:
    global _current
    if lang in _STRINGS:
        _current = lang


def language_label(lang: str) -> str:
    return LANGUAGES.get(lang, lang)


def T(key: str) -> str:
    """Translate ``key`` using the current language (English fallback)."""
    table = _STRINGS.get(_current) or _STRINGS[_DEFAULT]
    if key in table:
        return table[key]
    return _STRINGS[_DEFAULT].get(key, key)
