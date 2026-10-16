"""Application settings layer.

The translation engine stores its preferences through ``lib/config.py`` (the
verbatim Calibre-plugin configuration). This module adds the *app-level* defaults
Noesis wants (single-language output, no metadata translation, …) and exposes a
small, Qt-free API to read/write settings and to introspect the engines.
"""
from __future__ import annotations

from typing import Any

from .engines import builtin_engines
from .lib.config import get_config

__all__ = [
    "APP_DEFAULTS",
    "ensure_defaults",
    "load_settings",
    "save_settings",
    "engine_names",
    "engine_info",
    "set_engine_preference",
    "get_engine_preference",
]


#: App-level defaults written into the config on first run. Keys match
#: ``lib/config.py``'s ``defaults``; values are the Noesis choices.
APP_DEFAULTS: dict[str, Any] = {
    "translation_position": "only",   # translated text replaces the original
    "online_batching": False,
    "merge_enabled": False,
    "cache_enabled": True,
    "filter_scope": "text",
    "rule_mode": "normal",
    "ebook_metadata": {"metadata_translation": False},
    "priority_rules": [],
    "filter_rules": [],
    "ignore_rules": [],
    # App-level (desktop only) preferences.
    "ui_language": "it",
    "ui_theme": "system",
    "reader_backend": "auto",
    "reduce_motion": False,
    "onboarding_done": False,
    # Reader defaults (separate theme from the app).
    "reader_theme": "light",
    "reader_font": "serif",
    "reader_line_height": 1.5,
    "reader_justify": True,
    "reader_hyphenate": True,
    "reader_flow": "paginated",
    "reader_spread": False,
    # Quality defaults.
    "quality_samples": 10,
    "quality_threshold": 60,
    "quality_judge_engine": "",
    # Export defaults.
    "export_format": "epub",
    "export_edition": "original",
    "output_dir": "",
    # Reserve anchors/links so navigation targets and footnote references survive
    # translation. Emphasis tags (em/i/b/…) are intentionally NOT reserved: their
    # text must be translated, so the tag is dropped in favour of correct text.
    # The engine also reserves img/code/br/hr/sub/sup/kbd/abbr/wbr/var/canvas/
    # svg/script/style/math by default. Add more via the `reserve_rules` setting.
    "reserve_rules": ["a"],
}

#: Preference keys surfaced by the GUI for the selected engine.
_ENGINE_PREFERENCE_KEYS = (
    "api_keys", "model", "prompt", "target_lang", "concurrency_limit")


def ensure_defaults() -> None:
    """Apply :data:`APP_DEFAULTS` for any key not set yet (idempotent)."""
    config = get_config()
    changed = False
    for key, value in APP_DEFAULTS.items():
        if config.preferences.get(key) is None:
            config.set(key, value)
            changed = True
    # One-time migration: the reader backend default became "auto" (full when
    # WebEngine is available, otherwise lite). Bump legacy "lite" users.
    if not config.preferences.get("reader_backend_default_v2"):
        if config.get("reader_backend") in (None, "lite"):
            config.set("reader_backend", "auto")
        config.set("reader_backend_default_v2", True)
        changed = True
    if changed:
        config.commit()


def load_settings() -> dict[str, Any]:
    """Return the raw preferences as a plain dict."""
    return dict(get_config().preferences)


def save_settings(values: dict[str, Any]) -> None:
    """Persist ``values`` (dot-notation keys are supported)."""
    config = get_config()
    for key, value in values.items():
        config.set(key, value)
    config.commit()


def engine_names() -> list[str]:
    """All available engine display names."""
    return [e.name for e in builtin_engines if e.name]


def engine_info(name: str) -> dict[str, Any]:
    """Return UI-relevant metadata for the engine called ``name``."""
    engine = next((e for e in builtin_engines if e.name == name), None)
    if engine is None:
        return {"name": name, "need_api_key": True, "api_key_hint": "API Keys",
                "models": None, "free": False}
    return {
        "name": engine.name,
        "need_api_key": bool(engine.need_api_key),
        "api_key_hint": getattr(engine, "api_key_hint", "API Keys"),
        "models": list(getattr(engine, "models", []) or []) or None,
        "free": bool(getattr(engine, "free", False)),
    }


def get_engine_preference(engine_name: str) -> dict[str, Any]:
    config = get_config()
    preferences = config.get("engine_preferences") or {}
    return dict(preferences.get(engine_name) or {})


def set_engine_preference(engine_name: str, **values: Any) -> None:
    """Store per-engine preferences (``api_keys``, ``model``, …).

    A value of ``None`` **removes** the key: this matters for
    ``concurrency_limit``, where ``0`` is meaningful ("as many workers as
    segments") and is *not* the neutral value -- removing the key lets the engine
    class default apply again.
    """
    config = get_config()
    preferences = config.get("engine_preferences") or {}
    data = dict(preferences.get(engine_name) or {})
    for key, value in values.items():
        if key not in _ENGINE_PREFERENCE_KEYS:
            continue
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    preferences[engine_name] = data
    config.set("engine_preferences", preferences)
    config.commit()
