"""Optional AI judge for translation quality (LLM-as-judge).

A judge is any callable ``judge(source, translation) -> float`` returning a score
in ``[0, 100]``. :func:`make_engine_judge` builds one from a translation engine
(the verbatim Calibre-plugin engines translate a scoring prompt and the reply is
parsed for a number). Tests use a plain lambda instead, so nothing hits the
network.
"""
from __future__ import annotations

import re
from typing import Callable

__all__ = ["Judge", "make_engine_judge", "sample_pairs"]

Judge = Callable[[str, str], float]

_NUMBER_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)")

_PROMPT = (
    "You are a professional translation reviewer. Rate the TARGET translation of "
    "the SOURCE on a 0-100 scale for adequacy and fluency. Reply with the number "
    "only.\n\nSOURCE:\n{source}\n\nTARGET:\n{translation}\n\nSCORE:")


def _parse_score(text: str) -> float | None:
    if not text:
        return None
    for match in _NUMBER_RE.finditer(text):
        value = float(match.group(1).replace(",", "."))
        if 0.0 <= value <= 100.0:
            return value
    return None


def make_engine_judge(engine: str | None = None,
                      source_lang: str = "English",
                      target_lang: str = "Italian") -> Judge:
    """Return a judge that scores pairs using the configured translation engine."""
    from ..lib.translation import get_engine_class, get_translator

    translator = get_translator(get_engine_class(engine))
    translator.set_source_lang(source_lang)
    translator.set_target_lang(target_lang)

    def judge(source: str, translation: str) -> float:
        prompt = _PROMPT.format(source=source, translation=translation)
        try:
            reply = str(translator.translate(prompt))
        except Exception:  # noqa: BLE001 - judge must never crash the report
            return 0.0
        score = _parse_score(reply)
        return score if score is not None else 0.0

    return judge


def sample_pairs(pairs, sample: int) -> list:
    """Return at most ``sample`` evenly-spaced pairs (deterministic)."""
    if sample <= 0 or sample >= len(pairs):
        return list(pairs)
    step = len(pairs) / sample
    return [pairs[int(i * step)] for i in range(sample)]
