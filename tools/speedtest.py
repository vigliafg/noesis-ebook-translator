#!/usr/bin/env python3
"""Speed benchmark of the translation engine against a real OpenRouter model.

Everything the day's measurements need lives in ``speedtest/``: one directory per
run (``speedtest/runs/<id>/``) with the translated EPUB, the raw per-request log
and a ``metrics.json``; a top-level ``report.md``/``summary.json`` aggregates
them.

The subject is chapter 87 (*Stroke*) of *Rosen's Emergency Medicine*, translated
English -> Italian with ``deepseek/deepseek-v4-flash-0731``.

Three variables are exercised:

* **concurrency** -- ``concurrency_limit`` 1/5/10/15/20. The engine's default
  ``request_interval`` (20 s for the OpenAI family) would dominate the wall time,
  so the sweep runs it at 0. One extra run keeps the default interval to show
  what it costs.
* **batching** -- ``online_batching``, i.e. 20 segments concatenated into one
  JSON request (the engine's hard-coded batch size).
* **effort** -- reasoning disabled. The model reasons by default (~150 tokens
  even for a five-word segment); ``reasoning: {"enabled": false}`` removes it.
  The harness injects it by wrapping the HTTP call, so the engine stays
  untouched.

``usage`` numbers come from the provider response itself, not from an estimate:
the wrapper records prompt/completion/reasoning tokens and the real cost of every
call (``calls.jsonl``).

Each run gets its own ``NOESIS_CONFIG_DIR`` and cache directory, so no run can
see another's translations: every measurement is a cold translation.

Examples::

    python tools/speedtest.py prepare          # check the chapter and the plan
    python tools/speedtest.py run --id smoke --concurrency 20 --max-seconds 20
    python tools/speedtest.py matrix           # the whole sweep (hours)
    python tools/speedtest.py report
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SPEED_DIR = ROOT / "speedtest"
RUNS_DIR = SPEED_DIR / "runs"
INPUT_DIR = SPEED_DIR / "input"

SOURCE = ROOT / "corpus1" / "Rosen's Emergency Medicine 10ed 2023 SLIM.epub"
CHAPTER = ("XHTML/B9780323757898000876/"
           "CH0087_1224-1242_B9780323757898000876.xhtml#B9780323757898000876")
ENGINE = "OpenRouter"
MODEL = "deepseek/deepseek-v4-flash-0731"
KEY_FILE = ROOT / "openrouter.txt"

#: The sweep. ``interval`` is the engine's seconds-between-calls throttle;
#: the app keeps the class default (20 s for the OpenAI family), which is why one
#: run deliberately keeps it.
MATRIX = [
    {"id": "r01-seq-c1", "concurrency": 1, "reasoning": "off",
     "batch": False, "interval": 0.0},
    {"id": "r02-conc5", "concurrency": 5, "reasoning": "off",
     "batch": False, "interval": 0.0},
    {"id": "r03-conc10", "concurrency": 10, "reasoning": "off",
     "batch": False, "interval": 0.0},
    {"id": "r04-conc15", "concurrency": 15, "reasoning": "off",
     "batch": False, "interval": 0.0},
    {"id": "r05-conc20", "concurrency": 20, "reasoning": "off",
     "batch": False, "interval": 0.0},
    {"id": "r06-conc10-reasoning", "concurrency": 10, "reasoning": "on",
     "batch": False, "interval": 0.0},
    {"id": "r07-batch20", "concurrency": 1, "reasoning": "off",
     "batch": True, "interval": 0.0},
    {"id": "r08-batch20-reasoning", "concurrency": 1, "reasoning": "on",
     "batch": True, "interval": 0.0},
    {"id": "r09-conc20-interval20", "concurrency": 20, "reasoning": "off",
     "batch": False, "interval": 20.0},
    # Beyond the loop's default executor (8 threads on this machine): does the
    # ceiling move with a wider pool, or is the provider the limit?
    {"id": "r10-conc20-exec32", "concurrency": 20, "reasoning": "off",
     "batch": False, "interval": 0.0, "executor": 32},
    # Validation of the fixes the first sweep produced.
    {"id": "r11-conc20-fixed", "concurrency": 20, "reasoning": "off",
     "batch": False, "interval": 0.0},
    {"id": "r12-batch20-stream", "concurrency": 1, "reasoning": "off",
     "batch": True, "interval": 0.0, "stream": True},
    # Batching after the fixes: batches run in parallel and the JSON is repaired.
    {"id": "r13-batch20-parallel", "concurrency": 8, "reasoning": "off",
     "batch": True, "interval": 0.0},
    {"id": "r14-batch20-parallel-stream", "concurrency": 8, "reasoning": "off",
     "batch": True, "interval": 0.0, "stream": True},
    # Push both paths to the executor ceiling: the batch path with 20 requests
    # in flight, and the per-segment path with the app's streaming default.
    {"id": "r15-batch20-parallel20", "concurrency": 20, "reasoning": "off",
     "batch": True, "interval": 0.0},
    {"id": "r16-conc20-stream", "concurrency": 20, "reasoning": "off",
     "batch": False, "interval": 0.0, "stream": True},
    {"id": "r17-batch20-stream20", "concurrency": 20, "reasoning": "off",
     "batch": True, "interval": 0.0, "stream": True},
    {"id": "r18-conc32-stream", "concurrency": 32, "reasoning": "off",
     "batch": False, "interval": 0.0, "stream": True},
]

#: Records every HTTP call the engine makes (see ``_install_instrumentation``).
CALLS: list[dict] = []
#: ``translate`` or ``judge``: which phase a recorded call belongs to.
PHASE = {"name": "translate"}


# ---------------------------------------------------------------------------
#  Shared helpers
# ---------------------------------------------------------------------------
def _api_key() -> str:
    key = ""
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    return key or os.environ.get("OPENROUTER_API_KEY", "")


def _require_source() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"source book not found: {SOURCE}")
    if not _api_key():
        raise SystemExit(f"missing API key ({KEY_FILE} or OPENROUTER_API_KEY)")


def _isolate(run_dir: Path) -> None:
    """Point the app at a private config + cache directory (before imports)."""
    os.environ["NOESIS_CONFIG_DIR"] = str(run_dir / "config")
    (run_dir / "config").mkdir(parents=True, exist_ok=True)
    (run_dir / "cache").mkdir(parents=True, exist_ok=True)


def _configure(run_dir: Path, params: dict) -> None:
    """Write the run's config: engine, model, concurrency, batching, cache path."""
    from noesis_ebook_translator.lib.config import get_config

    config = get_config()
    preferences = dict(config.get("engine_preferences") or {})
    preferences[ENGINE] = {
        "api_keys": [_api_key()],
        "model": MODEL,
        "concurrency_limit": int(params["concurrency"]),
        "temperature": 0.2,
        # Non-streaming so the provider's ``usage`` (tokens, reasoning, cost)
        # arrives in the JSON body and can be recorded exactly. ``--stream``
        # switches to the app's default to validate that path (then the usage of
        # the streamed calls cannot be read from the body).
        "stream": bool(params.get("stream", False)),
        "request_interval": float(params["interval"]),
        "request_timeout": 180,
        "request_attempt": 3,
    }
    config.set("engine_preferences", preferences)
    config.set("translate_engine", ENGINE)
    config.set("online_batching", bool(params["batch"]))
    config.set("merge_enabled", False)
    config.set("translate_temperature", 0.2)
    config.set("cache_path", str(run_dir))
    config.set("log_translation", False)
    config.commit()


def _install_executor(max_workers: int) -> None:
    """Raise the event loop's default executor size.

    ``Handler`` runs each HTTP call with ``run_in_executor(None, ...)``, so the
    loop's *default* executor is the real ceiling on parallel calls: CPython
    sizes it ``min(32, cpu+4)`` -- 8 threads on this 4-core machine. One extra
    run with a wider pool measures what the machine allows beyond that.
    """
    import concurrent.futures as futures

    original = futures.ThreadPoolExecutor
    width = int(max_workers)

    class WideThreadPoolExecutor(original):
        def __init__(self, max_workers=None, *args, **kwargs):
            super().__init__(max_workers or width, *args, **kwargs)

    # ``run_in_executor`` looks the class up on the module at call time.
    futures.ThreadPoolExecutor = WideThreadPoolExecutor


def _install_instrumentation(reasoning_off: bool):
    """Wrap ``request`` in every loaded module: record usage, force reasoning off.

    Modules do ``from ..lib.utils import request`` at import time, so patching
    ``lib.utils`` alone would not be enough: every module attribute that still
    points at the original function is rebound.
    """
    from noesis_ebook_translator.lib import utils as utils_mod

    original = utils_mod.request

    def wrapper(url, data=None, headers={}, method="GET", timeout=30,
                proxy_uri=None, raw_object=False):
        payload = None
        if isinstance(data, (str, bytes)):
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                payload = None
        # The judge must stay comparable across runs: even in a
        # reasoning-enabled translation run the scoring calls pay no reasoning.
        off = reasoning_off or PHASE["name"] == "judge"
        if off and isinstance(payload, dict) and "chat/completions" in (url or ""):
            payload["reasoning"] = {"enabled": False}
            data = json.dumps(payload)
        started_at = time.time()
        started = time.monotonic()
        entry: dict = {
            "phase": PHASE["name"],
            "url": url,
            "model": (payload or {}).get("model"),
            "started_at": started_at,
            "prompt_chars": sum(
                len(message.get("content") or "")
                for message in (payload or {}).get("messages", [])),
        }
        try:
            response = original(url, data=data, headers=headers, method=method,
                                timeout=timeout, proxy_uri=proxy_uri,
                                raw_object=raw_object)
        except Exception as exc:  # noqa: BLE001 - recorded and re-raised
            entry["seconds"] = time.monotonic() - started
            entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
            CALLS.append(entry)
            raise
        entry["seconds"] = time.monotonic() - started
        if isinstance(response, str):
            try:
                body = json.loads(response)
            except ValueError:
                body = None
            if isinstance(body, dict):
                usage = body.get("usage") or {}
                details = usage.get("completion_tokens_details") or {}
                prompt_details = usage.get("prompt_tokens_details") or {}
                entry["prompt_tokens"] = usage.get("prompt_tokens")
                entry["completion_tokens"] = usage.get("completion_tokens")
                entry["reasoning_tokens"] = details.get("reasoning_tokens")
                entry["cached_tokens"] = prompt_details.get("cached_tokens")
                entry["cost_usd"] = usage.get("cost")
                choices = body.get("choices") or [{}]
                entry["finish_reason"] = choices[0].get("finish_reason")
                if body.get("error"):
                    entry["error"] = str(body["error"])[:500]
        CALLS.append(entry)
        return response

    patched = 0
    for module in list(sys.modules.values()):
        if getattr(module, "request", None) is original:
            module.request = wrapper
            patched += 1
    return patched


def _chapter_objects():
    """The ``Chapter`` for chapter 87, used to align source and translation."""
    from ebooklib import epub

    from noesis_ebook_translator import chapters
    from noesis_ebook_translator.chapters import preserve_document_markup

    book = epub.read_epub(str(SOURCE))
    preserve_document_markup(book)
    return chapters.resolve_selection(chapters.chapters_from_book(book), [CHAPTER])


def _cache_stats(run_dir: Path) -> dict:
    """Read the run's cache: rows, translated rows and the run marker stats."""
    stats: dict = {}
    for path in sorted((run_dir / "cache").glob("*.db")):
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        with connection:
            try:
                stats["cache_rows"] = connection.execute(
                    "SELECT COUNT(*) FROM cache WHERE ignored IS NULL"
                    " OR ignored=0 OR ignored=''").fetchone()[0]
                stats["cache_translated"] = connection.execute(
                    "SELECT COUNT(*) FROM cache WHERE translation IS NOT NULL"
                    " AND translation != ''").fetchone()[0]
                for key in ("run_status", "run_engine_calls", "run_started_at",
                            "run_finished_at", "run_concurrency",
                            "run_batching", "model", "engine_name"):
                    row = connection.execute(
                        "SELECT value FROM info WHERE key=?", (key,)).fetchone()
                    if row is not None:
                        stats[key] = row[0]
            except sqlite3.Error:
                continue
        connection.close()
    return stats


def _sum(calls: list[dict], key: str) -> int:
    return int(sum(call.get(key) or 0 for call in calls))


def _cost(calls: list[dict]) -> float:
    return round(sum(float(call.get("cost_usd") or 0.0) for call in calls), 6)


def _latency(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1,
                max(0, round(quantile * (len(ordered) - 1))))
    return round(ordered[index], 3)


def _max_in_flight(calls: list[dict]) -> int:
    events: list[tuple[float, int]] = []
    for call in calls:
        if "seconds" not in call:
            continue
        start = call["started_at"]
        events.append((start, 1))
        events.append((start + call["seconds"], -1))
    events.sort(key=lambda event: (event[0], -event[1]))
    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


# ---------------------------------------------------------------------------
#  prepare
# ---------------------------------------------------------------------------
def cmd_prepare(args) -> int:
    _require_source()
    # A scratch config: the recon must not read or write the user's real one.
    os.environ.setdefault("NOESIS_CONFIG_DIR", str(SPEED_DIR / "config-prepare"))
    from noesis_ebook_translator import book

    started = time.time()
    segments = book.collect_segments(str(SOURCE), chapters=[CHAPTER],
                                     engine=ENGINE, source_lang="English",
                                     target_lang="Italian")
    usable = [segment for segment in segments if not segment.get("ignored")]
    plan = {
        "source": str(SOURCE.relative_to(ROOT)),
        "chapter": CHAPTER,
        "engine": ENGINE,
        "model": MODEL,
        "segments_total": len(segments),
        "segments_usable": len(usable),
        "characters": sum(len(segment.get("text") or "") for segment in usable),
        "longest_segment": max((len(segment.get("text") or "")
                                for segment in usable), default=0),
        "collect_seconds": round(time.time() - started, 2),
    }
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    (INPUT_DIR / "plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
#  run
# ---------------------------------------------------------------------------
def cmd_run(args) -> int:
    _require_source()
    run_dir = RUNS_DIR / args.id
    if run_dir.exists() and not args.force:
        print(f"run dir already exists: {run_dir} (use --force)")
        return 1
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "cache").mkdir(exist_ok=True)
    output_path = run_dir / "translated.epub"
    log_lines: list[str] = []

    _isolate(run_dir)
    _configure(run_dir, {
        "concurrency": args.concurrency,
        "batch": args.batch,
        "interval": args.interval,
        "stream": args.stream,
    })

    from noesis_ebook_translator import book as book_mod

    if args.executor:
        _install_executor(args.executor)
    patched = _install_instrumentation(args.reasoning == "off")
    log_lines.append(f"request wrappers installed: {patched}")
    segments = len([
        segment for segment in book_mod.collect_segments(
            str(SOURCE), chapters=[CHAPTER], engine=ENGINE,
            source_lang="English", target_lang="Italian")
        if not segment.get("ignored")])
    log_lines.append(f"segments: {segments}")

    started_at = time.time()
    failure = ""
    cancelled = False
    deadline = (time.monotonic() + args.max_seconds) if args.max_seconds else None
    try:
        book_mod.translate_epub(
            str(SOURCE), str(output_path),
            engine=ENGINE, source_lang="English", target_lang="Italian",
            chapters=[CHAPTER],
            should_cancel=(lambda: deadline is not None
                           and time.monotonic() > deadline),
        )
    except Exception as exc:  # noqa: BLE001 - a failed run is a measurement too
        from noesis_ebook_translator.lib.exception import TranslationCanceled
        if isinstance(exc, TranslationCanceled):
            cancelled = True
        else:
            failure = f"{type(exc).__name__}: {exc}"
    wall = round(time.time() - started_at, 2)

    # -- quality, on the same output and with the same model as judge --------
    quality: dict = {}
    if output_path.is_file() and not args.no_quality:
        try:
            from noesis_ebook_translator.quality import (
                evaluate, make_engine_judge, write_report)

            PHASE["name"] = "judge"
            report = evaluate(
                str(SOURCE), str(output_path),
                judge=make_engine_judge(ENGINE, "English", "Italian"),
                judge_sample=args.judge_sample,
                selected=_chapter_objects())
            quality = report.to_dict()
            write_report(report, str(run_dir / "quality.json"), "json")
            write_report(report, str(run_dir / "quality.md"), "markdown")
        except Exception as exc:  # noqa: BLE001 - quality must never hide the run
            quality = {"error": f"{type(exc).__name__}: {exc}"}

    # -- metrics -------------------------------------------------------------
    translate_calls = [call for call in CALLS if call["phase"] == "translate"]
    judge_calls = [call for call in CALLS if call["phase"] == "judge"]
    errors = [call for call in CALLS if call.get("error")]
    latencies = [call["seconds"] for call in translate_calls if "seconds" in call]
    cache = _cache_stats(run_dir)
    metrics = {
        "id": args.id,
        "started_at": started_at,
        "wall_seconds": wall,
        "engine": ENGINE,
        "model": MODEL,
        "concurrency": args.concurrency,
        "reasoning": args.reasoning,
        "batching": bool(args.batch),
        "request_interval": args.interval,
        "cancelled": cancelled,
        "failure": failure,
        "segments": segments,
        "translate": {
            "calls": len(translate_calls),
            "failures": len([c for c in translate_calls if c.get("error")]),
            "prompt_tokens": _sum(translate_calls, "prompt_tokens"),
            "completion_tokens": _sum(translate_calls, "completion_tokens"),
            "reasoning_tokens": _sum(translate_calls, "reasoning_tokens"),
            "cached_tokens": _sum(translate_calls, "cached_tokens"),
            "cost_usd": _cost(translate_calls),
            "latency_p50": _latency(latencies, 0.5),
            "latency_p95": _latency(latencies, 0.95),
            "max_in_flight": _max_in_flight(translate_calls),
            "requests_per_second": (round(len(translate_calls) / wall, 3)
                                    if wall else None),
            "seconds_per_segment": (round(wall / segments, 3) if segments
                                    else None),
            "cost_per_1000_segments": (round(_cost(translate_calls)
                                             / segments * 1000, 4)
                                       if segments else None),
        },
        "judge": {
            "calls": len(judge_calls),
            "prompt_tokens": _sum(judge_calls, "prompt_tokens"),
            "completion_tokens": _sum(judge_calls, "completion_tokens"),
            "reasoning_tokens": _sum(judge_calls, "reasoning_tokens"),
            "cost_usd": _cost(judge_calls),
        },
        "errors": [
            {"phase": call["phase"], "url": call.get("url"),
             "error": call.get("error")}
            for call in errors
        ],
        "cache": cache,
        "quality": quality,
    }
    (run_dir / "calls.jsonl").write_text(
        "\n".join(json.dumps(call, ensure_ascii=False) for call in CALLS) + "\n",
        encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (run_dir / "run.log").write_text(
        "\n".join(log_lines) + f"\nwall: {wall}s\nfailure: {failure}\n",
        encoding="utf-8")
    translate = metrics["translate"]
    print(f"[{args.id}] wall={wall}s calls={translate['calls']} "
          f"cost=${translate['cost_usd']:.4f} "
          f"reasoning_tok={translate['reasoning_tokens']} "
          f"errors={len(errors)} quality={quality.get('judge_score')}")
    return 0 if not failure else 2


# ---------------------------------------------------------------------------
#  matrix
# ---------------------------------------------------------------------------
def cmd_matrix(args) -> int:
    _require_source()
    only = set(args.only.split(",")) if args.only else None
    entries = [entry for entry in MATRIX if not only or entry["id"] in only]
    for entry in entries:
        run_dir = RUNS_DIR / entry["id"]
        if (run_dir / "metrics.json").is_file() and not args.force:
            print(f"\n=== {entry['id']} === skipped (already done)")
            continue
        argv = [sys.executable, str(Path(__file__)),
                "run", "--id", entry["id"],
                "--concurrency", str(entry["concurrency"]),
                "--interval", str(entry["interval"]),
                "--reasoning", entry["reasoning"]]
        if entry.get("executor"):
            argv += ["--executor", str(entry["executor"])]
        if entry["batch"]:
            argv.append("--batch")
        if entry.get("stream"):
            argv.append("--stream")
        if args.force:
            argv.append("--force")
        print(f"\n=== {entry['id']} ===", flush=True)
        result = subprocess.run(argv, cwd=str(ROOT))
        if result.returncode not in (0, 2):
            print(f"[{entry['id']}] failed (exit {result.returncode})",
                  file=sys.stderr)
    return cmd_report(args)


# ---------------------------------------------------------------------------
#  report
# ---------------------------------------------------------------------------
def cmd_report(args) -> int:
    runs = []
    for path in sorted(RUNS_DIR.glob("*/metrics.json")):
        try:
            runs.append(json.loads(path.read_text()))
        except ValueError:
            continue
    if not runs:
        print("no runs found in speedtest/runs", file=sys.stderr)
        return 1
    lines = [
        "# Speed test - Rosen ch.87 *Stroke* (English -> Italian)",
        "",
        f"- Engine: `{ENGINE}` - model `{MODEL}`",
        f"- Runs: {len(runs)}",
        "",
        "| run | conc | reasoning | batch | interval | wall s | s/seg "
        "| req/s | calls | err | tok in | tok out | reason tok | cost $ "
        "| p50 s | p95 s | inflight | untransl. | length | digits | judge |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    summary = []
    for run in runs:
        translate = run.get("translate") or {}
        quality = run.get("quality") or {}
        metrics = quality.get("metrics") or {}
        judge = quality.get("judge_score")
        seconds_per_segment = translate.get("seconds_per_segment")
        row = {
            "id": run.get("id"),
            "concurrency": run.get("concurrency"),
            "reasoning": run.get("reasoning"),
            "batching": run.get("batching"),
            "request_interval": run.get("request_interval"),
            "wall_seconds": run.get("wall_seconds"),
            "seconds_per_segment": seconds_per_segment,
            "requests_per_second": translate.get("requests_per_second"),
            "calls": translate.get("calls"),
            "failures": translate.get("failures"),
            "prompt_tokens": translate.get("prompt_tokens"),
            "completion_tokens": translate.get("completion_tokens"),
            "reasoning_tokens": translate.get("reasoning_tokens"),
            "cost_usd": translate.get("cost_usd"),
            "judge_cost_usd": (run.get("judge") or {}).get("cost_usd"),
            "latency_p50": translate.get("latency_p50"),
            "latency_p95": translate.get("latency_p95"),
            "max_in_flight": translate.get("max_in_flight"),
            "untranslated_ratio": metrics.get("untranslated_ratio"),
            "mean_length_ratio": metrics.get("mean_length_ratio"),
            "digits_ok_ratio": metrics.get("digits_ok_ratio"),
            "judge_score": judge,
            "cancelled": run.get("cancelled"),
            "failure": run.get("failure"),
        }
        summary.append(row)
        lines.append(
            f"| {row['id']} | {row['concurrency']} | {row['reasoning']} "
            f"| {'yes' if row['batching'] else ''} | {row['request_interval']} "
            f"| {row['wall_seconds']} "
            f"| {('%.2f' % seconds_per_segment) if seconds_per_segment else '-'} "
            f"| {row['requests_per_second']} | {row['calls']} "
            f"| {row['failures']} | {row['prompt_tokens']} "
            f"| {row['completion_tokens']} | {row['reasoning_tokens']} "
            f"| {row['cost_usd']} | {row['latency_p50']} | {row['latency_p95']} "
            f"| {row['max_in_flight']} "
            f"| {('%.1f%%' % (100 * row['untranslated_ratio'])) if row['untranslated_ratio'] is not None else '-'} "
            f"| {row['mean_length_ratio']} "
            f"| {('%.1f%%' % (100 * row['digits_ok_ratio'])) if row['digits_ok_ratio'] is not None else '-'} "
            f"| {('%.1f' % judge) if judge is not None else '-'} |")
    lines.append("")
    (SPEED_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (SPEED_DIR / "report.md").write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare", help="check the chapter and write the plan")

    run = sub.add_parser("run", help="one benchmark run in an isolated config")
    run.add_argument("--id", required=True)
    run.add_argument("--concurrency", type=int, default=5)
    run.add_argument("--interval", type=float, default=0.0)
    run.add_argument("--reasoning", choices=["on", "off"], default="off")
    run.add_argument("--batch", action="store_true")
    run.add_argument("--stream", action="store_true",
                     help="use the app's streaming default instead of JSON usage")
    run.add_argument("--executor", type=int, default=0,
                     help="override the event loop's default executor size")
    run.add_argument("--judge-sample", type=int, default=12)
    run.add_argument("--max-seconds", type=float, default=0.0)
    run.add_argument("--no-quality", action="store_true")
    run.add_argument("--force", action="store_true")

    matrix = sub.add_parser("matrix", help="run the whole sweep, then report")
    matrix.add_argument("--only", default="")
    matrix.add_argument("--force", action="store_true")
    matrix.add_argument("--judge-sample", type=int, default=12)

    report = sub.add_parser("report", help="aggregate speedtest/runs/*")
    report.add_argument("--judge-sample", type=int, default=12)

    args = parser.parse_args(argv)
    if args.command == "prepare":
        return cmd_prepare(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "matrix":
        return cmd_matrix(args)
    if args.command == "report":
        return cmd_report(args)
    return 1


if __name__ == "__main__":
    for name in ("QT_QPA_PLATFORM",):
        os.environ.setdefault(name, "offscreen")
    # Keep the app's module-level imports away from the user's real config when
    # this script is imported/executed for recon (``run`` overrides it after).
    sys.exit(main())
