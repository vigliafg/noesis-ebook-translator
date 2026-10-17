#!/usr/bin/env python3
"""Regenerate the bundled provider model snapshot.

The desktop app ships a small offline fallback with the model list of every
curated provider (``noesis_ebook_translator/data/providers.json``). This tool
rebuilds it from:

* **models.dev** (``https://models.dev/api.json``) for the providers whose
  ``/models`` endpoint needs an API key — the catalogue is public and covers all
  of them with text-model metadata;
* the **live** ``/models`` endpoints of the providers that expose them without
  a key (OpenCode, OpenCode Go, OpenRouter), which are authoritative.

Usage::

    python tools/fetch_provider_catalog.py
    python tools/fetch_provider_catalog.py --check   # fail if snapshot is stale

It is **not** needed at runtime: the app falls back to the bundled snapshot and
refreshes model lists live from the UI. No third-party dependency is required.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noesis_ebook_translator import provider_catalog  # noqa: E402
from noesis_ebook_translator.provider_catalog import (  # noqa: E402
    PROVIDERS, parse_models)

MODELS_DEV = "https://models.dev/api.json"

OUTPUT = ROOT / "noesis_ebook_translator" / "data" / "providers.json"

#: Curated provider id -> models.dev provider id (they differ in a few cases).
MODELS_DEV_IDS: dict[str, str] = {
    "together": "togetherai",
    "fireworks": "fireworks-ai",
    "moonshot": "moonshotai",
    "novita": "novita-ai",
}

#: Providers whose ``/models`` endpoint is public: prefer the live response.
PUBLIC: tuple[str, ...] = ("opencode", "opencode-go", "openrouter")


def _get_json(url: str, timeout: float = 30.0):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": provider_catalog.USER_AGENT,
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _text_models(models: dict) -> list[str]:
    """Model ids that accept and return text (drops audio/vision-only)."""
    out: list[str] = []
    for model in models.values():
        modalities = model.get("modalities") or {}
        inputs = modalities.get("input") or []
        outputs = modalities.get("output") or []
        if "text" in outputs and "text" in inputs:
            out.append(str(model.get("id")))
    return out


def _live_models(provider_id: str) -> list[str] | None:
    try:
        payload = _get_json(provider_catalog.models_url(provider_id))
    except Exception as exc:  # noqa: BLE001 - best effort
        print(f"  ! live {provider_id}: {exc}", file=sys.stderr)
        return None
    models = parse_models(payload)
    return models or None


def build_snapshot() -> dict:
    print(f"fetching {MODELS_DEV} ...")
    catalogue = _get_json(MODELS_DEV)
    models: dict[str, list[str]] = {}
    for provider in PROVIDERS:
        if provider.custom:
            continue
        md_id = MODELS_DEV_IDS.get(provider.id, provider.id)
        entry = catalogue.get(md_id)
        md_ids = set(_text_models(entry.get("models") or {})) if entry else set()
        if provider.id in PUBLIC:
            live = _live_models(provider.id)
            if live:
                # Drop non-text models (embeddings/audio/image) using models.dev
                # as the reference when it knows the provider.
                kept = [m for m in live if m in md_ids] if md_ids else list(live)
                kept = kept or list(live)
                models[provider.id] = sorted(set(kept), key=str.lower)
                print(f"  {provider.id}: {len(models[provider.id])} (live)")
                continue
        if not entry:
            print(f"  ! {provider.id}: not in models.dev (id {md_id})",
                  file=sys.stderr)
            continue
        ids = sorted(md_ids, key=str.lower)
        if ids:
            models[provider.id] = ids
        print(f"  {provider.id}: {len(ids)} (models.dev/{md_id})")
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "models.dev + public /models endpoints",
        "models": models,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="do not write; exit non-zero when the snapshot would change")
    args = parser.parse_args(argv)

    snapshot = build_snapshot()
    text = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != text:
            print("snapshot is outdated", file=sys.stderr)
            return 1
        print("snapshot is up to date")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    total = sum(len(v) for v in snapshot["models"].values())
    print(f"wrote {OUTPUT.relative_to(ROOT)} "
          f"({len(snapshot['models'])} providers, {total} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
