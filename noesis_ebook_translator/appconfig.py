"""Application settings layer.

The translation engine stores its preferences through ``lib/config.py`` (the
verbatim Calibre-plugin configuration). This module adds the *app-level* defaults
Noesis wants (single-language output, no metadata translation, …) and exposes a
small, Qt-free API to read/write settings and to introspect the engines.
"""
from __future__ import annotations

import time
from typing import Any

from . import provider_catalog
from .lib.config import get_config

__all__ = [
    "APP_DEFAULTS",
    "MAX_PROVIDER_SLOTS",
    "MODEL_CACHE_TTL",
    "ensure_defaults",
    "load_settings",
    "save_settings",
    "engine_names",
    "desktop_engine_names",
    "builtin_engine_names",
    "legacy_engine_names",
    "engine_info",
    "engine_supports_prompt",
    "set_engine_preference",
    "get_engine_preference",
    "provider_choices",
    "provider_slots",
    "set_provider_slots",
    "provider_id_for_engine",
    "provider_models",
    "save_provider_models",
    "model_cache_age",
    "models_are_stale",
    "save_model_test",
    "model_test_status",
    "refresh_provider_models",
]

#: Maximum number of providers the user can configure at the same time.
MAX_PROVIDER_SLOTS = 4

#: How long a live model list is trusted before a refresh is suggested.
MODEL_CACHE_TTL = 24 * 3600


#: App-level defaults written into the config on first run. Keys match
#: ``lib/config.py``'s ``defaults``; values are the Noesis choices.
APP_DEFAULTS: dict[str, Any] = {
    "translation_position": "only",   # translated text replaces the original
    "online_batching": False,
    "merge_enabled": False,
    "cache_enabled": True,
    # Translate one segment at a time (concurrency_limit = 1). Keeps the
    # per-chapter progress view truthful: a single chapter is "in progress".
    # Slower with engines that would otherwise run many requests in parallel.
    "translate_sequential": True,
    # Requests sent in parallel when "sequential" is off (1-8). Feeds both the
    # engine's concurrency_limit and the wizard's duration estimate.
    "translate_parallel": 4,
    # Sampler temperature override for LLM engines. ``None`` means "leave the
    # engine's own default" (DeepSeek ships 1.3, Gemini 0.9, the generic ones
    # 1.0). The low value that keeps short segments from drifting lives on
    # OpenRouter's engine class; set this (or the per-engine "temperature") to
    # force a value for every engine.
    "translate_temperature": None,
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
    # Provider slots (desktop-only): up to MAX_PROVIDER_SLOTS configured
    # providers, each with its own API key / model. Mirrored into
    # ``engine_preferences`` under the engine name (see set_provider_slots).
    "provider_slots": [],
    # Live model lists fetched from the providers, keyed by provider id:
    # {"groq": {"at": <epoch>, "models": [...]}}.
    "model_cache": {},
    # Last live model test per engine (desktop-only):
    # {"Groq": {"at": <epoch>, "ok": true, "model": "...", "error": ""}}.
    "model_tests": {},
}

#: Preference keys surfaced by the GUI for the selected engine.
_ENGINE_PREFERENCE_KEYS = (
    "api_keys", "model", "prompt", "target_lang", "concurrency_limit",
    "endpoint", "models_url", "temperature")


def ensure_defaults() -> None:
    """Apply :data:`APP_DEFAULTS` for any key not set yet (idempotent)."""
    config = get_config()
    changed = False
    for key, value in APP_DEFAULTS.items():
        # ``None`` means "no default": leave the engine's own value alone
        # instead of writing a null into the config.
        if value is None:
            continue
        if config.preferences.get(key) is None:
            config.set(key, value)
            changed = True
    # One-time migration: the first cut of the low-temperature default wrote
    # ``translate_temperature = 0.2`` for every engine; the value now lives on
    # the OpenRouter engine class, so drop the global override it left behind.
    if not config.preferences.get("temperature_default_v2"):
        if config.get("translate_temperature") == 0.2:
            config.delete("translate_temperature")
        config.set("temperature_default_v2", True)
        changed = True
    # One-time migration: the reader backend default became "auto" (full when
    # WebEngine is available, otherwise lite). Bump legacy "lite" users.
    if not config.preferences.get("reader_backend_default_v2"):
        if config.get("reader_backend") in (None, "lite"):
            config.set("reader_backend", "auto")
        config.set("reader_backend_default_v2", True)
        changed = True
    # One-time migration: the "sepia" app theme was removed (it looked washed
    # out); the reader keeps its own sepia background.
    if config.get("ui_theme") == "sepia":
        config.set("ui_theme", "light")
        changed = True
    # One-time migration: seed the provider slots from the single-engine
    # configuration that predates multi-provider support.
    if not config.preferences.get("provider_slots_v1"):
        slots = _slots_from_engine_preferences()
        if slots:
            config.set("provider_slots", slots)
        config.set("provider_slots_v1", True)
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


#: Engine names generated for the curated providers (``openai_compatible``).
def _provider_engine_names() -> set[str]:
    from .engines.openai_compatible import provider_engines
    return {engine.name for engine in provider_engines()}


#: Engine name -> provider id, for every curated provider (builtin included).
def _provider_id_by_engine() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for provider in provider_catalog.providers():
        mapping[provider.resolved_engine_name] = provider.id
    return mapping


def provider_choices() -> list[dict[str, Any]]:
    """Curated providers, ready for the provider pickers in the UI."""
    return [{
        "id": provider.id,
        "name": provider.name,
        "need_api_key": not provider.custom,
        "default_model": provider.default_model,
        "doc": provider.doc,
        "env_hint": provider.env_hint,
        "note": provider.note,
        "custom": provider.custom,
    } for provider in provider_catalog.providers()]


def provider_id_for_engine(name: str) -> str:
    """Provider id backed by engine ``name`` (``""`` when not a provider)."""
    return _provider_id_by_engine().get(name or "", "")


def _builtin_engines() -> tuple:
    """The engine registry **now**.

    ``register_fake_engine()`` (and any runtime registration) rebinds
    ``engines.builtin_engines`` to a new tuple; a module-level import of the
    original tuple would keep the stale one and hide the injected engine from
    the wizard. Resolved by name at call time; the headless monofile inlines the
    engines into the same namespace, where the global is already the live one.
    """
    try:
        import importlib

        return importlib.import_module(
            "noesis_ebook_translator.engines").builtin_engines
    except Exception:  # noqa: BLE001 - inlined engine: same module namespace
        return globals()["builtin_engines"]


def engine_names() -> list[str]:
    """Engine display names offered to the user.

    The verbatim plugin engines are always listed; the curated provider engines
    only appear once the user has enabled them in a slot (the settings page uses
    :func:`provider_choices` for the full roster). This keeps the wizard and the
    ribbon short while still offering any provider.
    """
    provider_engines = _provider_engine_names()
    names = [e.name for e in _builtin_engines()
             if e.name and e.name not in provider_engines]
    for slot in provider_slots():
        if not slot.get("enabled") or not slot.get("provider"):
            continue
        name = provider_catalog.engine_name(slot["provider"])
        if name and name not in names:
            names.append(name)
    return names


def _engine_is_configured(name: str) -> bool:
    """True when the engine has been chosen and can run.

    Two families, two answers:

    * a curated provider is chosen through its **slot** — the switch the Provider
      page owns, and the authoritative one: a provider whose slot is gone must
      disappear even if something left credentials behind in
      ``engine_preferences`` (a mirror left over by a removed slot is not a sign
      that the user still wants that engine);
    * a verbatim engine (ChatGPT, Gemini, …) has no slot: it counts as configured
      once the Settings *Translation* page — or the translation wizard — stored a
      key or a custom endpoint for it.
    """
    provider_id = provider_id_for_engine(name)
    if provider_id and any(slot.get("provider") == provider_id
                           and slot.get("enabled")
                           for slot in provider_slots()):
        return True
    pref = get_engine_preference(name)
    return bool(pref.get("api_keys")) or bool(pref.get("endpoint"))


def desktop_engine_names() -> list[str]:
    """The *selection* list of the desktop: non-LLM always, LLM once configured.

    The plain machine-translation engines are what the app can do out of the box,
    so they are always offered; an LLM appears only after the user has configured
    it (a provider slot with credentials, or a key stored for one of the verbatim
    engines such as ChatGPT). The configuration surfaces keep the full roster:
    :func:`legacy_engine_names` for the plugin engines, :func:`provider_choices`
    for the curated providers.

    Desktop-only: the CLI uses :func:`engine_names`, which stays complete because
    its TUI picks the engine *before* typing the API key.
    """
    names: list[str] = []
    for engine in _builtin_engines():
        if not engine.name:
            continue
        if engine_supports_prompt(engine.name) and not _engine_is_configured(
                engine.name):
            continue
        names.append(engine.name)
    return names


def builtin_engine_names() -> list[str]:
    """The verbatim plugin engines only (no curated provider engines)."""
    provider_engines = _provider_engine_names()
    return [e.name for e in _builtin_engines()
            if e.name and e.name not in provider_engines]


def legacy_engine_names() -> list[str]:
    """Engines edited in the *Translation* page of the settings.

    The curated providers (OpenRouter included) are owned by the Provider page,
    so they are excluded here to avoid two pages writing the same preference.
    """
    curated = set(_provider_id_by_engine())
    return [e.name for e in _builtin_engines()
            if e.name and e.name not in curated]


def engine_supports_prompt(name: str) -> bool:
    """True when the engine is an LLM (it has a system prompt to extend).

    Plain machine-translation engines (DeepL, the free Google ones, Baidu…) have
    no prompt: the genre analysis cannot say anything useful to them.
    """
    engine = next((e for e in _builtin_engines() if e.name == name), None)
    return bool(engine is not None and hasattr(engine, "prompt"))


def engine_info(name: str) -> dict[str, Any]:
    """Return UI-relevant metadata for the engine called ``name``."""
    engine = next((e for e in _builtin_engines() if e.name == name), None)
    if engine is None:
        return {"name": name, "need_api_key": True, "api_key_hint": "API Keys",
                "models": None, "free": False, "provider": "", "note": ""}
    provider_id = getattr(engine, "provider_id", "") or ""
    provider = provider_catalog.get(provider_id)
    models = (provider_models(provider_id) if provider_id
              else list(getattr(engine, "models", []) or []) or None)
    return {
        "name": engine.name,
        "need_api_key": bool(getattr(engine, "need_api_key", True)),
        "api_key_hint": getattr(engine, "api_key_hint", "API Keys"),
        "models": models,
        "free": bool(getattr(engine, "free", False)),
        "provider": provider_id,
        "note": provider.note if provider else "",
    }


# ------------------------------------------------------------------ slots


def _blank_slot() -> dict[str, Any]:
    return {"enabled": False, "provider": "", "api_key": "", "model": "",
            "endpoint": ""}


def provider_slots() -> list[dict[str, Any]]:
    """The configured provider slots, always padded to ``MAX_PROVIDER_SLOTS``."""
    stored = get_config().get("provider_slots") or []
    slots: list[dict[str, Any]] = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        slot = _blank_slot()
        slot.update({key: item.get(key) for key in slot if key in item})
        slots.append(slot)
    while len(slots) < MAX_PROVIDER_SLOTS:
        slots.append(_blank_slot())
    return slots[:MAX_PROVIDER_SLOTS]


def set_provider_slots(slots: list[dict[str, Any]]) -> None:
    """Persist the slots and mirror each one into ``engine_preferences``.

    The engine layer only ever reads ``engine_preferences``, so this keeps the
    translation path untouched.
    """
    config = get_config()
    # Providers that were enabled *before* this call: a slot dropped from the
    # list is never submitted, so its mirror would otherwise survive and keep the
    # engine in the selection list.
    previous_enabled = {
        slot.get("provider") for slot in (config.get("provider_slots") or [])
        if isinstance(slot, dict) and slot.get("enabled") and slot.get("provider")}
    normalized: list[dict[str, Any]] = []
    for item in (slots or [])[:MAX_PROVIDER_SLOTS]:
        slot = _blank_slot()
        if isinstance(item, dict):
            slot.update({key: item.get(key) for key in slot if key in item})
        slot["enabled"] = bool(slot["enabled"]) and bool(slot["provider"])
        slot["api_key"] = str(slot.get("api_key") or "")
        slot["model"] = str(slot.get("model") or "")
        slot["endpoint"] = str(slot.get("endpoint") or "")
        normalized.append(slot)
    config.set("provider_slots", normalized)
    config.commit()
    for slot in normalized:
        provider_id = slot.get("provider")
        if not provider_id:
            continue
        name = provider_catalog.engine_name(provider_id)
        if slot["enabled"]:
            set_engine_preference(
                name,
                api_keys=[slot["api_key"]] if slot["api_key"] else [],
                model=slot["model"] or None,
                endpoint=slot["endpoint"] or None)
        else:
            # Keep the slot data (the user can re-enable it) but drop the
            # mirrored engine config so a disabled provider is really inactive.
            set_engine_preference(
                name, api_keys=[], model=None, endpoint=None)
    # Same for a provider whose slot disappeared from the list entirely: without
    # this, its stale mirror would keep the engine selectable.
    for provider_id in previous_enabled - {
            slot["provider"] for slot in normalized if slot["enabled"]}:
        set_engine_preference(
            provider_catalog.engine_name(provider_id),
            api_keys=[], model=None, endpoint=None)


def _slots_from_engine_preferences() -> list[dict[str, Any]]:
    """Seed the slots from a pre-multi-provider configuration."""
    config = get_config()
    preferences = config.get("engine_preferences") or {}
    by_engine = _provider_id_by_engine()
    seeds: list[dict[str, Any]] = []
    current = config.get("translate_engine")
    order = ([current] if current in by_engine else []) + [
        name for name in by_engine if name != current]
    for name in order:
        if len(seeds) >= MAX_PROVIDER_SLOTS:
            break
        pref = preferences.get(name) or {}
        keys = pref.get("api_keys") or []
        if not keys and name != current:
            continue
        slots = provider_slots()
        slot = dict(slots[len(seeds)])
        slot.update({
            "enabled": bool(keys),
            "provider": by_engine[name],
            "api_key": (keys[0] if keys else ""),
            "model": pref.get("model", "") or "",
            "endpoint": pref.get("endpoint", "") or "",
        })
        seeds.append(slot)
    return seeds


# ------------------------------------------------------------ model lists


def provider_models(provider_id: str) -> list[str] | None:
    """Cached / bundled models for ``provider_id`` (``None`` when unknown)."""
    if not provider_id:
        return None
    cache = get_config().get("model_cache") or {}
    entry = cache.get(provider_id) or {}
    models = [str(m) for m in (entry.get("models") or [])]
    if models:
        return models
    snapshot = provider_catalog.default_models(provider_id)
    return snapshot or None


def save_provider_models(provider_id: str, models: list[str]) -> None:
    """Cache a freshly fetched model list for ``provider_id``."""
    if not provider_id or not models:
        return
    config = get_config()
    cache = dict(config.get("model_cache") or {})
    cache[provider_id] = {"at": int(time.time()),
                          "models": [str(m) for m in models]}
    config.set("model_cache", cache)
    config.commit()


def model_cache_age(provider_id: str) -> float | None:
    """Seconds since the cached list was fetched (``None`` when absent)."""
    cache = get_config().get("model_cache") or {}
    entry = cache.get(provider_id) or {}
    at = entry.get("at")
    return None if at is None else max(0.0, time.time() - float(at))


def models_are_stale(provider_id: str) -> bool:
    """True when the cached model list is absent or older than the TTL."""
    age = model_cache_age(provider_id)
    return age is None or age > MODEL_CACHE_TTL


def save_model_test(engine_name: str, *, ok: bool, model: str = "",
                    error: str = "") -> None:
    """Remember the outcome of the last live probe for ``engine_name``."""
    if not engine_name:
        return
    config = get_config()
    tests = dict(config.get("model_tests") or {})
    tests[engine_name] = {"at": int(time.time()), "ok": bool(ok),
                          "model": str(model or ""),
                          "error": str(error or "")[:400]}
    config.set("model_tests", tests)
    config.commit()


def model_test_status(engine_name: str, model: str | None = None) -> dict[str, Any]:
    """Last probe for ``engine_name`` (``{}`` when absent or for another model)."""
    tests = get_config().get("model_tests") or {}
    entry = dict(tests.get(engine_name) or {})
    if not entry:
        return {}
    if model is not None and str(entry.get("model") or "") != str(model or ""):
        return {}
    return entry


def refresh_provider_models(provider_id: str, api_key: str = "", *,
                            _fetch=None) -> list[str]:
    """Fetch the live model list and cache it.

    ``_fetch`` is injectable so the GUI (and its tests) can avoid the network.
    """
    fetcher = _fetch or provider_catalog.fetch_models
    models = fetcher(provider_id, api_key)
    if models:
        save_provider_models(provider_id, models)
    return models or []


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
