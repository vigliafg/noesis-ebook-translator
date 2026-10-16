#!/usr/bin/env python3
"""Run the end-to-end translation scenario matrix and report the result.

This is the "state invariant" harness: instead of asking "did it open?", each
condition checks that every planned segment was processed, that no chapter was
left half-done, and that the output carries the translation in every document and
in every TOC level. A stall becomes a failed row (watchdog), never a hung process.

    python tools/scenario_harness.py
    python tools/scenario_harness.py --json
    python tools/scenario_harness.py --keep        # keep the temp fixtures

Exit code is 0 only when every condition passes.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.harness import run_scenario_matrix  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the translation scenario matrix.")
    parser.add_argument("--json", action="store_true",
                        help="print the raw reports as JSON")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="seconds a single condition may take (default 120)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the temporary fixtures instead of deleting them")
    args = parser.parse_args(argv)

    tmpdir = tempfile.mkdtemp(prefix="noesis-scenario-harness-")
    try:
        reports = run_scenario_matrix(tmpdir, timeout=args.timeout)
    finally:
        if not args.keep:
            shutil.rmtree(tmpdir, ignore_errors=True)
        else:
            print(f"fixtures: {tmpdir}")

    if args.json:
        print(json.dumps(
            {name: dataclasses.asdict(report) for name, report in reports.items()},
            indent=2, sort_keys=True))
    else:
        print(f"{'':4} {'condition':26} {'planned':>7} {'processed':>9} "
              f"{'cached':>6} {'time':>7}  details")
        for report in reports.values():
            state = "OK" if report.ok else "FAIL"
            details = ""
            if report.stalled:
                details = "STALLED"
            elif report.error:
                details = report.error
            elif not report.ok:
                details = (f"pending={report.pending_chapters} "
                           f"output={report.output_missing} toc={report.toc_missing}")
            print(f"{state:4} {report.name:26} {report.planned_total:>7} "
                  f"{report.processed_total:>9} {report.cached_segments:>6} "
                  f"{report.seconds:>6.2f}s  {details}")

    passed = sum(1 for report in reports.values() if report.ok)
    ok = passed == len(reports)
    print(f"\n{'PASS' if ok else 'FAIL'}: {passed}/{len(reports)} conditions")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
