#!/usr/bin/env python3
"""Run the reader harness against the lite and full backends.

Examples::

    python tools/reader_harness.py                       # both backends, bundled sample
    python tools/reader_harness.py book.epub other.epub  # on real books
    python tools/reader_harness.py --mode lite book.epub
    NOESIS_READER_BACKEND=full python tools/reader_harness.py book.epub

Exit code is non-zero if a requested backend that is *available* fails. The full
backend requires a working QtWebEngine (GPU/display); on a headless machine it
reports ``ready=False`` and is treated as a warning, not a failure.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _sample_book() -> str:
    from tests.fixtures import build_rich_epub
    return build_rich_epub(os.path.join(tempfile.mkdtemp(), "sample.epub"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("books", nargs="*", help="EPUB files (default: bundled sample)")
    ap.add_argument("--mode", choices=["lite", "full", "both"], default="both")
    ap.add_argument("--wait", type=float, default=20.0,
                    help="seconds to wait for the full backend to become ready")
    args = ap.parse_args(argv)

    from tests.harness import run_reader_harness, webengine_available

    books = args.books or [_sample_book()]
    modes = ["lite", "full"] if args.mode == "both" else [args.mode]

    failures = 0
    for mode in modes:
        if mode == "full" and not webengine_available():
            print(f"[{mode}] skipped: QtWebEngine not installed")
            continue
        for book in books:
            report = run_reader_harness(mode, book, wait=args.wait)
            print(f"[{mode}] {Path(book).name}: {report.summary()}")
            if report.available and not report.ok and report.ready:
                failures += 1
            elif not report.available and mode == "lite":
                failures += 1
    print("\nRESULT:", "FAIL" if failures else "OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
