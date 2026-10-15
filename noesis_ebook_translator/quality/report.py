"""Quality report model, evaluation entry point and report writers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .judge import Judge, sample_pairs
from .metrics import SegmentResult, align_segments, compute_metrics

__all__ = ["EvaluationReport", "evaluate", "write_report"]


@dataclass
class EvaluationReport:
    metrics: dict
    segments: list[SegmentResult] = field(default_factory=list)
    judge_score: float | None = None
    judge_samples: list[dict] = field(default_factory=list)
    source: str = ""
    translated: str = ""

    def to_dict(self) -> dict:
        return {
            "source": os.path.basename(self.source),
            "translated": os.path.basename(self.translated),
            "metrics": self.metrics,
            "judge_score": self.judge_score,
            "judge_samples": self.judge_samples,
        }

    def to_markdown(self) -> str:
        m = self.metrics
        lines = [
            "# Translation quality report",
            "",
            f"- Source: `{os.path.basename(self.source)}`",
            f"- Translated: `{os.path.basename(self.translated)}`",
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Segments | {m.get('total', 0)} |",
            f"| Untranslated | {m.get('untranslated', 0)} "
            f"({m.get('untranslated_ratio', 0):.1%}) |",
            f"| Empty | {m.get('empty', 0)} ({m.get('empty_ratio', 0):.1%}) |",
            f"| Mean length ratio | {m.get('mean_length_ratio', 0):.3f} |",
            f"| Digits preserved | {m.get('digits_ok_ratio', 1):.1%} |",
        ]
        if self.judge_score is not None:
            lines.append(f"| AI judge score | {self.judge_score:.1f}/100 |")
        if self.judge_samples:
            lines += ["", "## AI judge samples", "",
                      "| Source | Translation | Score |", "| --- | --- | --- |"]
            for sample in self.judge_samples:
                src = (sample.get("source", "")[:60]).replace("|", "\\|")
                tgt = (sample.get("translation", "")[:60]).replace("|", "\\|")
                lines.append(f"| {src} | {tgt} | {sample.get('score', 0):.1f} |")
        lines.append("")
        return "\n".join(lines)


def evaluate(source_epub: str, translated_epub: str, *,
             judge: Judge | None = None,
             judge_sample: int = 10,
             selected=None) -> EvaluationReport:
    """Evaluate ``translated_epub`` against ``source_epub``.

    ``judge`` is an optional callable ``(source, translation) -> float`` (0-100);
    ``judge_sample`` limits how many pairs are sent to it.
    """
    pairs = align_segments(source_epub, translated_epub, selected=selected)
    metrics = compute_metrics(pairs)
    report = EvaluationReport(metrics=metrics, segments=pairs,
                              source=source_epub, translated=translated_epub)
    if judge is not None:
        chosen = [p for p in sample_pairs(pairs, judge_sample) if p.source.strip()]
        scores: list[float] = []
        for pair in chosen:
            score = float(judge(pair.source, pair.translation))
            scores.append(score)
            report.judge_samples.append({
                "file": pair.file, "order": pair.order,
                "source": pair.source, "translation": pair.translation,
                "score": score,
            })
        report.judge_score = (sum(scores) / len(scores)) if scores else None
    return report


def write_report(report: EvaluationReport, path: str, fmt: str | None = None) -> str:
    """Write ``report`` to ``path`` (format inferred from the extension)."""
    fmt = (fmt or Path(path).suffix.lstrip(".").lower() or "markdown")
    if fmt in ("json",):
        Path(path).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    else:
        Path(path).write_text(report.to_markdown(), encoding="utf-8")
    return path
