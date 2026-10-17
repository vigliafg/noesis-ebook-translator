"""Token, cost and duration estimate for a translation run (no Qt).

The translation wizard shows this *before* spending money:

* **tokens** are counted with ``tiktoken`` on the exact segments the engine will
  send (see :mod:`token_count`), system prompt included — the prompt is re-sent
  with every request and is often the dominant cost of a long book;
* **cost** multiplies those tokens by the provider price in
  ``data/providers.json`` (models.dev, USD per 1M tokens);
* **duration** starts from the engine's request interval and concurrency, and,
  once a translation has run, uses the measured seconds-per-call instead of a
  constant (``book`` records the stats in ``cache.info``).

The estimate is read-only: it opens the cache databases in ``mode=ro`` and never
writes configuration.
"""
from __future__ import annotations

import math
import os
import sqlite3
import statistics
from dataclasses import dataclass, field
from glob import glob
from typing import Any

from . import appconfig, book, chapters, provider_catalog, token_count
from .lib.translation import get_engine_class, get_translator
from .lib.utils import uid

__all__ = [
    "BookEstimate", "ChapterEstimate", "estimate_book", "sample_segments",
    "format_duration", "format_usd", "target_ratio",
]

#: models.dev provider id behind a verbatim builtin engine (prices only).
ENGINE_TO_MODELS_DEV: dict[str, str] = {
    "ChatGPT": "openai",
    "ChatGPT(Azure)": "openai",
    "Claude": "anthropic",
    "Gemini": "google",
    "DeepSeek": "deepseek",
    "Groq": "groq",
    "Mistral": "mistral",
    "xAI (Grok)": "xai",
}

#: Output/input token ratio by target language (translated text is longer than
#: English in Romance languages, shorter in CJK). Only a ratio: the translated
#: text does not exist yet, so it cannot be tokenised.
TARGET_RATIOS: dict[str, float] = {
    "English": 0.95,
    "Italian": 1.15,
    "French": 1.18,
    "Spanish": 1.12,
    "Portuguese": 1.12,
    "Portuguese (Brazil)": 1.12,
    "German": 0.95,
    "Dutch": 1.0,
    "Russian": 0.9,
    "Ukrainian": 0.9,
    "Polish": 0.95,
    "Chinese (Simplified)": 0.55,
    "Chinese (Traditional)": 0.55,
    "Japanese": 0.75,
    "Korean": 0.8,
    "Arabic": 0.8,
    "Hebrew": 0.85,
    "Turkish": 0.95,
}
DEFAULT_RATIO = 1.1

#: The engine's online-batching path sends 20 segments per request.
BATCH_SIZE = 20
#: Chat framing overhead per request (roles, separators).
FRAMING_TOKENS = 8

#: Default seconds per request when no run of this engine+model exists yet.
DEFAULT_LATENCY_LLM = 3.0
DEFAULT_LATENCY_MT = 0.6
DEFAULT_LATENCY_BATCH = 8.0
MAX_CONCURRENCY = 8

#: Samples for the text analysis: a few excerpts, never the whole book.
SAMPLE_COUNT = 24
SAMPLE_CHARS = 300
SAMPLE_TOTAL_CHARS = 7000


def target_ratio(target_lang: str) -> float:
    """Output/input token ratio for ``target_lang``."""
    return TARGET_RATIOS.get(target_lang or "", DEFAULT_RATIO)


def format_duration(seconds: float | None) -> str:
    """``1 h 05 min`` / ``12 min`` / ``40 s`` (localisation-free)."""
    if seconds is None or not math.isfinite(seconds):
        return "—"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if minutes == 0:
        return f"{hours} h"
    return f"{hours} h {minutes:02d} min"


def format_usd(value: float | None) -> str:
    """``$0.42`` / ``$0.0031`` (more decimals for very small amounts)."""
    if value is None:
        return "—"
    if value == 0:
        return "$0"
    if value < 0.01:
        return f"${value:.4f}"
    if value < 1:
        return f"${value:.3f}"
    return f"${value:.2f}"


@dataclass
class ChapterEstimate:
    """One row of the per-chapter table."""

    key: str
    title: str
    file: str
    segments: int = 0
    characters: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cached_segments: int = 0


@dataclass
class BookEstimate:
    """Everything the *Costs and duration* page shows."""

    segments: int = 0
    characters: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    requests: int = 0
    prompt_tokens: int = 0
    cached_segments: int = 0
    cached_tokens_in: int = 0
    cached_tokens_out: int = 0
    cost_usd: float | None = None
    pricing: tuple[float, float] | None = None
    seconds: float = 0.0
    seconds_low: float = 0.0
    seconds_high: float = 0.0
    concurrency: int = 1
    batching: bool = False
    observed_latency: bool = False
    backend: str = "heuristic"
    encoding: str = ""
    price_date: str = ""
    per_chapter: list[ChapterEstimate] = field(default_factory=list)
    sample: list[str] = field(default_factory=list)

    @property
    def engine_calls(self) -> int:
        return max(0, self.requests - self.cached_requests)

    @property
    def cached_requests(self) -> int:
        if not self.cached_segments:
            return 0
        if self.batching:
            return math.ceil(self.cached_segments / BATCH_SIZE)
        return self.cached_segments


def _ratio_requests(segments: int, batching: bool) -> int:
    return math.ceil(segments / BATCH_SIZE) if batching else segments


def _read_info(db_path: str) -> dict[str, str]:
    """Read a cache's ``info`` table without writing anything."""
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:  # pragma: no cover - unreadable file
        return {}
    try:
        return {str(key): value for key, value in
                connection.execute("SELECT key, value FROM info")}
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def _read_resume_hashes(db_path: str, engine: str, model: str,
                        source_lang: str, target_lang: str,
                        style_hash: str) -> set[str]:
    """Content hashes already translated for this exact run scope."""
    if not os.path.isfile(db_path):
        return set()
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:  # pragma: no cover - unreadable file
        return set()
    try:
        rows = connection.execute(
            "SELECT content_hash FROM noesis_resume WHERE engine_name=? AND "
            "model=? AND source_lang=? AND target_lang=? AND style_hash=? "
            "AND translation IS NOT NULL AND translation<>''",
            (engine, model, source_lang, target_lang, style_hash)).fetchall()
    except sqlite3.OperationalError:
        # A cache written before the style column existed: it can only serve
        # un-styled runs, and a styled one must not reuse it.
        if style_hash:
            return set()
        try:
            rows = connection.execute(
                "SELECT content_hash FROM noesis_resume WHERE engine_name=? "
                "AND model=? AND source_lang=? AND target_lang=? AND "
                "translation IS NOT NULL AND translation<>''",
                (engine, model, source_lang, target_lang)).fetchall()
        except sqlite3.Error:
            return set()
    except sqlite3.Error:
        return set()
    finally:
        connection.close()
    return {str(row[0]) for row in rows}


def _cache_db_path(input_path: str, engine: str, target_lang: str,
                   merge_length: int = 0) -> str:
    from .lib.cache import TranslationCache

    cache_id = uid(input_path + engine + target_lang + str(merge_length) + "")
    return os.path.join(TranslationCache.cache_path, f"{cache_id}.db")


def observed_latency(engine: str, model: str, batching: bool) -> float | None:
    """Median seconds per request measured on previous runs (``None`` if none)."""
    from .lib.cache import TranslationCache

    directory = TranslationCache.cache_path
    if not os.path.isdir(directory):
        return None
    samples: list[float] = []
    for db_path in glob(os.path.join(directory, "*.db")):
        info = _read_info(db_path)
        if info.get("run_status") != "finished":
            continue
        if (info.get("engine_name") or "") != (engine or ""):
            continue
        if (info.get("model") or "") != (model or ""):
            continue
        if (info.get("run_batching") or "0") != ("1" if batching else "0"):
            continue
        try:
            calls = int(info.get("run_engine_calls") or 0)
            concurrency = int(info.get("run_concurrency") or 0)
            started = int(info.get("run_started_at") or 0)
            finished = int(info.get("run_finished_at") or 0)
        except (TypeError, ValueError):
            continue
        duration = finished - started
        if calls < 10 or duration <= 0:
            continue
        effective = min(max(1, concurrency or MAX_CONCURRENCY), 16)
        per_call = duration * effective / calls
        if 0.02 <= per_call <= 900:
            samples.append(per_call)
    if not samples:
        return None
    return statistics.median(samples)


def sample_segments(segments: list[dict[str, Any]], *,
                    count: int = SAMPLE_COUNT,
                    chars: int = SAMPLE_CHARS,
                    total_chars: int = SAMPLE_TOTAL_CHARS) -> list[str]:
    """A spread of excerpts for the genre analysis (never the whole book)."""
    usable = [segment for segment in segments
              if not segment.get("ignored")
              and segment.get("page") != "toc.ncx"
              and len((segment.get("text") or "").strip()) >= 40]
    if not usable:
        # Very short texts (and test fixtures): fall back to any non-empty text.
        usable = [segment for segment in segments
                  if not segment.get("ignored")
                  and segment.get("page") != "toc.ncx"
                  and (segment.get("text") or "").strip()]
    if not usable:
        return []
    if len(usable) > count:
        step = len(usable) / count
        usable = [usable[int(index * step)] for index in range(count)]
    excerpts: list[str] = []
    used = 0
    for segment in usable:
        text = (segment.get("text") or "").strip()
        if len(text) > chars:
            cut = text[:chars]
            boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            text = cut[: boundary + 1] if boundary >= chars // 2 else cut
        if used + len(text) > total_chars:
            break
        excerpts.append(text)
        used += len(text)
    return excerpts


def _chapter_labels(input_path: str) -> tuple[dict[tuple[str, str], str],
                                              dict[str, str]]:
    """Maps ``(file, anchor) -> title`` and ``file -> title`` from the TOC."""
    by_anchor: dict[tuple[str, str], str] = {}
    by_file: dict[str, str] = {}
    try:
        flat = chapters.flatten(chapters.load_chapters(input_path))
    except Exception:  # noqa: BLE001 - a broken TOC only labels rows generically
        return by_anchor, by_file
    for chapter in flat:
        if not chapter.file:
            continue
        title = (chapter.name or chapter.file).strip()
        anchor = ""
        if chapter.href and "#" in chapter.href:
            anchor = chapter.href.split("#", 1)[1]
        if anchor:
            by_anchor.setdefault((chapter.file, anchor), title)
        by_file.setdefault(chapter.file, title)
    return by_anchor, by_file


def estimate_book(
    input_path: str,
    *,
    chapters_spec: Any = None,
    engine: str | None = None,
    model: str | None = None,
    source_lang: str = "English",
    target_lang: str = "Italian",
    direction: str = "auto",
    sequential: bool = True,
    concurrency: int | None = None,
    batching: bool = False,
    cache_enabled: bool = True,
    style_prompt: str = "",
    segments: list[dict[str, Any]] | None = None,
) -> BookEstimate:
    """Estimate tokens, cost and duration of translating ``input_path``."""
    engine_class = get_engine_class(engine)
    translator = get_translator(engine_class)
    translator.set_source_lang(source_lang)
    translator.set_target_lang(target_lang)
    engine_name = translator.name or (engine or "")
    model_name = str(model or getattr(translator, "model", "") or "")

    if segments is None:
        segments = book.collect_segments(
            input_path, chapters=chapters_spec, direction=direction, engine=engine,
            source_lang=source_lang, target_lang=target_lang)
    usable = [segment for segment in segments if not segment.get("ignored")]
    texts = [segment.get("text") or "" for segment in usable]
    token_lists = token_count.count_many(texts, model_name)
    counts = [max(0, value) for value in token_lists]
    text_tokens = sum(counts)
    characters = sum(len(text) for text in texts)

    supports_batching = bool(batching) and hasattr(translator, "translate_batch")
    requests = _ratio_requests(len(usable), supports_batching)
    # The system prompt is re-sent with every request: count it (and the style
    # addendum) exactly. A non-LLM engine has no prompt to extend.
    base_prompt = getattr(translator, "prompt", "") or ""
    system_prompt = (f"{base_prompt} {style_prompt}".strip()
                     if base_prompt else "")
    prompt_tokens = (token_count.count(system_prompt, model_name)
                     + FRAMING_TOKENS) if system_prompt else FRAMING_TOKENS
    tokens_in = text_tokens + requests * prompt_tokens
    tokens_out = int(round(text_tokens * target_ratio(target_lang)))

    # Already translated for this exact engine/model/language/style scope.
    style_hash = uid(style_prompt or "")
    known: set[str] = set()
    cached_segments = 0
    if cache_enabled:
        try:
            from .lib.config import get_config
            from .lib.element import get_element_handler

            handler = get_element_handler(
                translator.placeholder, translator.separator,
                direction or get_config().get("target_direction") or "auto")
            db_path = _cache_db_path(input_path, engine_name, target_lang,
                                     handler.get_merge_length())
            known = _read_resume_hashes(db_path, engine_name, model_name,
                                        source_lang, target_lang, style_hash)
            if known:
                cached_segments = sum(
                    1 for segment, count in zip(usable, counts)
                    if count and uid(segment.get("text") or "") in known)
        except Exception:  # noqa: BLE001 - the estimate must not fail on cache
            known = set()
            cached_segments = 0
    cached_requests = _ratio_requests(cached_segments, supports_batching)
    cached_text_tokens = 0
    if known and cached_segments:
        cached_text_tokens = sum(
            count for segment, count in zip(usable, counts)
            if count and uid(segment.get("text") or "") in known)
    # ``cached_text_tokens`` is exact by content: identical text shares a row.
    cached_tokens_in = cached_text_tokens + cached_requests * prompt_tokens
    cached_tokens_out = int(round(cached_text_tokens
                                  * target_ratio(target_lang)))

    # Price: curated provider first, then the builtin engine's models.dev id.
    provider_id = appconfig.provider_id_for_engine(engine_name)
    if not model_name and provider_id:
        # The wizard may not have a model selected yet: price the provider default.
        provider = provider_catalog.get(provider_id)
        if provider is not None and provider.default_model:
            model_name = provider.default_model
    pricing = None
    if provider_id:
        pricing = provider_catalog.price(provider_id, model_name)
    if pricing is None:
        dev_id = ENGINE_TO_MODELS_DEV.get(engine_name)
        if dev_id:
            pricing = provider_catalog.price(dev_id, model_name)
    cost = None
    if pricing is not None:
        billable_in = max(0, tokens_in - cached_tokens_in)
        billable_out = max(0, tokens_out - cached_tokens_out)
        cost = (billable_in / 1_000_000) * pricing[0] \
            + (billable_out / 1_000_000) * pricing[1]

    # Duration: the engine's pacing, corrected by real measurements when any.
    if supports_batching:
        effective_concurrency = 1
    elif sequential:
        effective_concurrency = 1
    else:
        effective_concurrency = max(1, int(concurrency or MAX_CONCURRENCY))
        effective_concurrency = min(effective_concurrency, MAX_CONCURRENCY)
    measured = observed_latency(engine_name, model_name, supports_batching)
    interval = float(getattr(translator, "request_interval", 0.0) or 0.0)
    if measured is None:
        is_llm = hasattr(translator, "prompt")
        if supports_batching:
            per_call = DEFAULT_LATENCY_BATCH
        else:
            per_call = DEFAULT_LATENCY_LLM if is_llm else DEFAULT_LATENCY_MT
        per_call += interval
    else:
        per_call = measured
    calls = max(0, requests - cached_requests)
    seconds = (math.ceil(calls / effective_concurrency) * per_call
               if calls else 0.0)

    # Per-chapter rows: one per TOC entry when anchors identify it, else per
    # document (the engine's unit). TOC titles are reported in their own row.
    by_anchor, by_file = _chapter_labels(input_path)
    rows: dict[str, ChapterEstimate] = {}
    for segment, count in zip(usable, counts):
        page = segment.get("page") or ""
        anchor = segment.get("anchor") or ""
        if page == "toc.ncx":
            key, title, file_name = "toc", "TOC", ""
        else:
            title = by_anchor.get((page, anchor)) or by_file.get(page) or page
            file_name = page
            key = f"{page}#{anchor}" if anchor else page
        row = rows.get(key)
        if row is None:
            row = rows[key] = ChapterEstimate(key=key, title=title or page,
                                              file=file_name)
        row.segments += 1
        row.characters += len(segment.get("text") or "")
        row.tokens_in += count + prompt_tokens
        row.tokens_out += int(round(count * target_ratio(target_lang)))
    if cached_segments:
        # Subtract cached rows proportionally (per content is exact; the UI only
        # shows the aggregate for cached work).
        ratio = cached_segments / max(1, len(usable))
        for row in rows.values():
            row.cached_segments = int(round(row.segments * ratio))

    return BookEstimate(
        segments=len(usable),
        characters=characters,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        requests=requests,
        prompt_tokens=prompt_tokens,
        cached_segments=cached_segments,
        cached_tokens_in=cached_tokens_in,
        cached_tokens_out=cached_tokens_out,
        cost_usd=cost,
        pricing=pricing,
        seconds=seconds,
        seconds_low=seconds * 0.6,
        seconds_high=seconds * 1.6,
        concurrency=effective_concurrency,
        batching=supports_batching,
        observed_latency=measured is not None,
        backend=token_count.backend(model_name),
        encoding=token_count.encoding_name_for(model_name),
        price_date=provider_catalog.snapshot_generated_at(),
        per_chapter=list(rows.values()),
        sample=sample_segments(segments),
    )
