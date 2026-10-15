#!/usr/bin/env python3
"""Evaluate translation quality of an EPUB against its source.

Examples::

    python tools/quality_harness.py book.epub book_ITALIAN.epub
    python tools/quality_harness.py src.epub dst.epub --judge OpenAI --sample 8 \
        --out quality.md

Without ``--judge`` only the automatic metrics run (offline, deterministic).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="source EPUB")
    ap.add_argument("translated", help="translated EPUB")
    ap.add_argument("--judge", default=None,
                    help="engine name for the AI judge (e.g. OpenAI, Gemini)")
    ap.add_argument("--sample", type=int, default=10,
                    help="number of segments sent to the judge")
    ap.add_argument("--source-lang", default="English")
    ap.add_argument("--target-lang", default="Italian")
    ap.add_argument("--out", default=None, help="report path (.md or .json)")
    ap.add_argument("--format", default=None, choices=["markdown", "json"])
    args = ap.parse_args(argv)

    from noesis_ebook_translator.quality import (
        evaluate, make_engine_judge, write_report)

    judge = None
    if args.judge:
        judge = make_engine_judge(args.judge, args.source_lang, args.target_lang)

    report = evaluate(args.source, args.translated, judge=judge,
                      judge_sample=args.sample)
    print(report.to_markdown())
    if args.out:
        write_report(report, args.out, args.format)
        print(f"\nreport written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
