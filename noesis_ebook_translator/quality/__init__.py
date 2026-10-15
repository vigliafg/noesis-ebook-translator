"""Translation-quality evaluation harness (headless, Qt-free).

Compares a source EPUB with its translation and produces an
:class:`EvaluationReport` combining automatic metrics (untranslated/empty
segments, length ratio, digit preservation) with an *optional* AI judge (an
LLM-as-judge scoring callable, e.g. built from a translation engine).

Typical use::

    from noesis_ebook_translator.quality import evaluate, write_report
    report = evaluate("book.epub", "book_ITALIAN.epub")
    write_report(report, "quality.md")
"""
from __future__ import annotations

from .metrics import (
    SegmentResult, align_segments, compute_metrics, digits_preserved,
    is_untranslated, length_ratio)
from .judge import make_engine_judge, sample_pairs
from .report import EvaluationReport, evaluate, write_report

__all__ = [
    "SegmentResult", "EvaluationReport", "evaluate", "write_report",
    "align_segments", "compute_metrics", "digits_preserved",
    "is_untranslated", "length_ratio", "make_engine_judge", "sample_pairs",
]
