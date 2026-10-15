"""Automatic translation-quality metrics (pure functions, no network)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .. import extract

__all__ = [
    "SegmentResult", "align_segments", "compute_metrics",
    "is_untranslated", "length_ratio", "digits_preserved",
]

_DIGITS_RE = re.compile(r"\d+")


@dataclass
class SegmentResult:
    """One aligned source/translation pair with per-segment flags."""

    file: str
    order: int
    source: str
    translation: str

    @property
    def empty(self) -> bool:
        return not self.translation.strip()

    @property
    def untranslated(self) -> bool:
        return is_untranslated(self.source, self.translation)

    @property
    def length_ratio(self) -> float:
        return length_ratio(self.source, self.translation)

    @property
    def digits_ok(self) -> bool:
        return digits_preserved(self.source, self.translation)

    def to_dict(self) -> dict:
        return {
            "file": self.file, "order": self.order,
            "source": self.source, "translation": self.translation,
            "empty": self.empty, "untranslated": self.untranslated,
            "length_ratio": round(self.length_ratio, 3),
            "digits_ok": self.digits_ok,
        }


def align_segments(source_epub: str, translated_epub: str,
                   selected=None) -> list[SegmentResult]:
    """Pair text blocks of the source and translated EPUB by ``(file, order)``."""
    src = extract.extract_text_blocks(source_epub, selected=selected)
    tgt = extract.extract_text_blocks(translated_epub, selected=selected)
    tgt_index = {(b.file, b.order): b.text for b in tgt}
    pairs: list[SegmentResult] = []
    for block in src:
        pairs.append(SegmentResult(
            file=block.file, order=block.order, source=block.text,
            translation=tgt_index.get((block.file, block.order), "")))
    return pairs


def is_untranslated(source: str, translation: str) -> bool:
    """True when the translation is identical to the source (case-insensitive)."""
    if not source.strip():
        return False
    return source.strip().casefold() == translation.strip().casefold()


def length_ratio(source: str, translation: str) -> float:
    if not source:
        return 0.0
    return len(translation) / len(source)


def digits_preserved(source: str, translation: str) -> bool:
    """True when every numeric token of the source is present in the target."""
    src_digits = set(_DIGITS_RE.findall(source))
    if not src_digits:
        return True
    tgt_digits = set(_DIGITS_RE.findall(translation))
    return src_digits.issubset(tgt_digits)


def compute_metrics(pairs: list[SegmentResult]) -> dict:
    """Aggregate metrics over aligned segments."""
    total = len(pairs)
    if total == 0:
        return {"total": 0, "untranslated": 0, "empty": 0,
                "untranslated_ratio": 0.0, "empty_ratio": 0.0,
                "mean_length_ratio": 0.0, "digits_ok_ratio": 1.0}
    untranslated = sum(1 for p in pairs if p.untranslated)
    empty = sum(1 for p in pairs if p.empty)
    ratios = [p.length_ratio for p in pairs if p.source.strip()]
    digits = [p.digits_ok for p in pairs]
    return {
        "total": total,
        "untranslated": untranslated,
        "empty": empty,
        "untranslated_ratio": round(untranslated / total, 4),
        "empty_ratio": round(empty / total, 4),
        "mean_length_ratio": round(sum(ratios) / len(ratios), 4) if ratios else 0.0,
        "digits_ok_ratio": round(sum(digits) / total, 4),
    }
