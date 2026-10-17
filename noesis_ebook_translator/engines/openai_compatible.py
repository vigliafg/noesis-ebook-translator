"""OpenAI-compatible provider engines (Noesis local extension).

This file is a **local extension** of the verbatim Calibre-plugin engine: it
adds a single generic transport for the curated providers listed in
:mod:`noesis_ebook_translator.provider_catalog`. Most of them speak the OpenAI
``/chat/completions`` protocol; the gateways (OpenCode, OpenCode Go) also expose
models that only answer on the OpenAI **Responses** API (``<base>/responses``),
which the snapshot marks in ``protocols`` (e.g. ``muse-spark-1.3-contributor``).

One engine class is generated per provider, so each one keeps its own API key and
model in ``engine_preferences`` (the existing per-engine configuration), and the
engine registry stays unchanged otherwise.

It is registered from the one intentionally non-verbatim file,
``engines/__init__.py`` (see ``ENGINE_SOURCE.json``). The headless engine repo
inlines this module too: keep it free of desktop-only imports at module level.
"""
from __future__ import annotations

import json
from typing import Any

from calibre.utils.localization import _  # type: ignore

from ..lib.utils import request
from ..provider_catalog import (PROVIDERS, Provider, fetch_models, protocol_for)
from .openai import ChatgptTranslate

load_translations()  # type: ignore


def _chat_url(base: str) -> str:
    """Normalise a user/provider base URL into a chat-completions endpoint."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _responses_url(base: str) -> str:
    """Normalise a base URL into an OpenAI *Responses* endpoint."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/responses"):
        return base
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return f"{base}/responses"


def parse_responses(payload: Any) -> str:
    """Text of an OpenAI Responses payload (skipping reasoning items)."""
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    error = payload.get("error")
    if error:
        raise RuntimeError(str((error or {}).get("message") or error))
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") in (
                    "output_text", "text"):
                chunks.append(str(part.get("text") or ""))
    text = "".join(chunks).strip()
    if not text:
        details = payload.get("incomplete_details") or {}
        raise RuntimeError(
            "empty Responses output "
            f"({payload.get('status') or '?'}: {details.get('reason') or '?'})")
    return text


class OpenAICompatibleTranslate(ChatgptTranslate):
    """Generic OpenAI-compatible translator.

    Subclasses (built by :func:`engine_class_for`) set :attr:`provider`.
    """

    provider: Provider | None = None
    provider_id: str = ""
    #: "chat" (chat/completions) or "responses" (the model requires it).
    protocol: str = "chat"

    def __init__(self):
        super().__init__()
        provider = self.provider
        configured = (self.config.get("endpoint") or "").strip()
        base = configured or (provider.base_url
                              if provider is not None and provider.base_url else "")
        self.protocol = protocol_for(self.provider_id, self.model) or "chat"
        if self.protocol == "responses":
            # The Responses API is used unary here: no SSE parsing.
            self.stream = False
            self.endpoint = _responses_url(base) or self.endpoint
        elif base:
            self.endpoint = _chat_url(base)

        models_url = (self.config.get("models_url") or "").strip()
        if not models_url and provider is not None and provider.base_url:
            models_url = provider.resolved_models_url
        if not models_url and self.endpoint:
            models_url = (_responses_url(self.endpoint).rsplit("/responses", 1)[0]
                          if self.protocol == "responses"
                          else self.endpoint.rsplit("/chat/completions", 1)[0]) + "/models"
        self.models_endpoint = models_url

    # ------------------------------------------------------------- requests
    def get_headers(self) -> dict[str, str]:
        headers = super().get_headers()
        provider = self.provider
        if provider is not None:
            headers.update(dict(provider.extra_headers))
        return headers

    def get_body(self, text: str) -> str:
        """Chat payload, or a Responses payload for models that need it."""
        if self.protocol == "responses":
            return json.dumps({
                "model": self.model,
                "stream": False,
                "instructions": self.get_prompt(),
                "input": [{"role": "user", "content": text}],
            })
        return super().get_body(text)

    def get_result(self, response):
        if self.protocol == "responses":
            return parse_responses(response)
        return super().get_result(response)

    def get_models(self) -> list[str]:
        """Live model list for this provider (falls back to the snapshot)."""
        try:
            return fetch_models(self.provider_id, self.api_key or "",
                                timeout=self.request_timeout)
        except Exception:  # noqa: BLE001 - the UI handles the fallback
            from ..provider_catalog import default_models
            return default_models(self.provider_id)

    # -------------------------------------------------------------- batching
    def translate_batch(self, segments: list[str]) -> list[str] | None:
        """ID-indexed JSON batching, like the OpenRouter engine."""
        if not segments:
            return []
        to_translate = {str(index): segment
                        for index, segment in enumerate(segments)}
        system_prompt = self.get_prompt() + (
            "\n\nCRITICAL: Return a JSON object where each key corresponds to the "
            "input ID and the value is the translated string. Return ONLY the "
            'JSON object. Example: {"0": "translation 1", "1": "translation 2"}')
        user_content = json.dumps(to_translate, ensure_ascii=False)
        if self.protocol == "responses":
            data: dict[str, Any] = {
                "model": self.model,
                "stream": False,
                "instructions": system_prompt,
                "input": [{"role": "user", "content": user_content}],
            }
        else:
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
            }
        was_streaming = self.stream
        self.stream = False
        try:
            response = request(
                self.endpoint, json.dumps(data), self.get_headers(), "POST",
                timeout=int(self.request_timeout),
                proxy_uri=self.proxy_uri)
            text = self.get_result(response)
        finally:
            self.stream = was_streaming
        if not text:
            return None
        clean = text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        else:
            start, end = clean.find("{"), clean.rfind("}")
            if start != -1 and end != -1:
                clean = clean[start:end + 1]
        try:
            translated: dict[str, Any] = json.loads(clean)
        except (ValueError, TypeError):
            return None
        return [str(translated.get(str(index), "")).strip()
                for index in range(len(segments))]


def _class_name(provider: Provider) -> str:
    parts = "".join(ch if ch.isalnum() else " " for ch in provider.id)
    return "".join(word.capitalize() for word in parts.split()) + "Translate"


def engine_class_for(provider: Provider) -> type[OpenAICompatibleTranslate]:
    """Build the engine class that backs ``provider``."""
    return type(_class_name(provider), (OpenAICompatibleTranslate,), {
        "provider": provider,
        "provider_id": provider.id,
        "name": provider.name,
        "alias": provider.name,
        "endpoint": provider.chat_url if provider.base_url else None,
        "models": [],
        "model": provider.default_model or None,
        "api_key_hint": _("{} API Key").format(provider.name)
        if provider.name else _("API Keys"),
        "free": False,
    })


def provider_engines() -> tuple[type[OpenAICompatibleTranslate], ...]:
    """Engine classes for every curated provider not already builtin.

    ``OpenRouter`` is skipped: the verbatim plugin engine of the same name is
    already registered and used as-is.
    """
    return tuple(engine_class_for(provider) for provider in PROVIDERS
                 if not provider.builtin)


def engine_class(provider_id: str) -> type[OpenAICompatibleTranslate] | None:
    """Engine class for ``provider_id`` (``None`` when not a curated provider)."""
    for engine in provider_engines():
        if engine.provider_id == provider_id:
            return engine
    return None
