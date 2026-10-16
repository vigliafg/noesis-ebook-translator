"""Per-chapter progress model and UI-update throttle (**Qt-free**).

The translation engine reports progress per *segment* (a paragraph or a merged
group), which can be tens of thousands of events for a book. Feeding every one of
those to the GUI would flood the event loop and keep paragraph objects alive in
the queue, so the desktop app splits the job in two:

* :class:`DeltaBatch` (called from the worker thread) accumulates only *counts*
  per document plus the last translated text and pending log lines.
* :class:`TransferThrottle` decides when that batch is worth sending: at most
  ``1 / interval`` emissions per second, and never more than one flush in flight
  (the GUI calls :meth:`TransferThrottle.release` when it has applied one).
* :class:`ProgressModel` (GUI thread) turns the deltas into per-unit states:
  ``pending`` / ``running`` / ``done`` / ``error`` (plus ``skipped`` for units
  with no translatable content).

Everything here is plain Python so the tricky part can be unit-tested headless.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .chapters import flatten, load_chapters
from .lib.utils import sorted_mixed_keys

__all__ = [
    "ChapterUnit", "build_units", "ProgressModel", "DeltaBatch",
    "TransferThrottle",
    "STATE_PENDING", "STATE_RUNNING", "STATE_DONE", "STATE_ERROR",
    "STATE_SKIPPED", "STATE_EXCLUDED",
]

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_SKIPPED = "skipped"
#: A chapter of the book that is not part of the current selection: shown (for
#: context) but never translated, so it stays dimmed and out of the totals.
STATE_EXCLUDED = "excluded"

#: The engine stores TOC titles as elements of this pseudo-document; they are not
#: part of any chapter, so they are excluded from the per-chapter counts.
TOC_PAGE = "toc.ncx"


@dataclass
class ChapterUnit:
    """A translatable unit: one XHTML document (one row in the progress list)."""

    file: str
    name: str = ""
    depth: int = 0

    def label(self) -> str:
        return self.name or self.file


def build_units(input_path: str | None, selected=None) -> list[ChapterUnit]:
    """Return the units to track, in the **engine's order**.

    The engine walks the documents in natural order of the file name
    (``sorted_mixed_keys``), so the list must follow the same order or the
    highlight would jump around.

    ``selected`` is an optional collection of file names (chapter selection):
    when given, only those files are tracked.
    """
    if not input_path:
        return []
    try:
        tree = flatten(load_chapters(input_path))
    except Exception:  # noqa: BLE001 - a broken TOC must not break the view
        return []
    wanted = {str(s) for s in selected} if selected else None
    units: list[ChapterUnit] = []
    seen: set[str] = set()
    for chapter in tree:
        if not chapter.file or chapter.file in seen:
            continue
        seen.add(chapter.file)
        if wanted is not None and chapter.file not in wanted:
            continue
        units.append(ChapterUnit(file=chapter.file,
                                 name=chapter.name or chapter.file,
                                 depth=chapter.depth))
    units.sort(key=lambda unit: sorted_mixed_keys(unit.file))
    return units


class TransferThrottle:
    """Rate-limit + single-flight guard for worker -> GUI updates.

    ``due()`` is called from the worker thread for every segment; it returns
    ``True`` at most every ``interval`` seconds and never while a previous flush
    is still pending in the GUI (single-flight), so the event queue can hold at
    most one progress update.
    """

    def __init__(self, interval: float = 0.05, clock=time.monotonic) -> None:
        self.interval = float(interval)
        self._clock = clock
        self._last: float | None = None
        self.pending = False

    def due(self) -> bool:
        if self.pending:
            return False
        now = self._clock()
        return self._last is None or (now - self._last) >= self.interval

    def emitted(self) -> None:
        self.pending = True
        self._last = self._clock()

    def release(self) -> None:
        """Called by the GUI thread once a flush has been applied."""
        self.pending = False


class DeltaBatch:
    """Accumulate engine callbacks into a small, plain-dict payload."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.counts: dict[str, int] = {}
        self.errors: dict[str, int] = {}
        self.cached = 0
        self.cached_pages: dict[str, int] = {}
        self.last: tuple[str, str] | None = None
        self.log: list[str] = []

    def add_paragraph(self, paragraph) -> None:
        """Count one processed segment.

        ``ignored`` segments are skipped: the plan reported by the engine
        (``on_plan``) excludes them, so counting them here would push a chapter
        past its own total.
        """
        if paragraph is None or getattr(paragraph, "ignored", False):
            return
        page = getattr(paragraph, "page", None)
        if page and page != TOC_PAGE:
            self.counts[page] = self.counts.get(page, 0) + 1
            if getattr(paragraph, "error", None):
                self.errors[page] = self.errors.get(page, 0) + 1
        if getattr(paragraph, "is_cache", False):
            self.cached += 1
            if page and page != TOC_PAGE:
                # Per-document too: a chapter served entirely from the cache was
                # already translated in an earlier run.
                self.cached_pages[page] = self.cached_pages.get(page, 0) + 1
        text = (getattr(paragraph, "translation", None) or "").strip()
        if text and page and page != TOC_PAGE:
            self.last = (page, text)

    def add_log(self, text: str) -> None:
        if text:
            self.log.append(text)

    def empty(self) -> bool:
        return not (self.counts or self.errors or self.cached
                    or self.cached_pages or self.last or self.log)

    def payload(self) -> dict | None:
        if self.empty():
            return None
        return {
            "counts": dict(self.counts),
            "errors": dict(self.errors),
            "cached": self.cached,
            "cached_pages": dict(self.cached_pages),
            "last": self.last,
            "log": list(self.log),
        }


class ProgressModel:
    """Per-unit translation state, driven by plan + deltas."""

    def __init__(self, units: list[ChapterUnit] | None = None) -> None:
        self.units: list[ChapterUnit] = list(units or [])
        self.plan: dict[str, int] = {}
        self.done: dict[str, int] = {}
        self.errors: dict[str, int] = {}
        self.cached = 0
        self.cached_pages: dict[str, int] = {}
        self.last: tuple[str, str] | None = None
        self.finished = False
        self.exported = False
        self.selection: set[str] | None = None
        self._known: set[str] = {unit.file for unit in self.units}

    # -- structure --------------------------------------------------------
    def set_selection(self, files) -> None:
        """Mark which documents are part of the translation.

        Passing ``None`` (whole book) selects everything. The units outside the
        selection stay visible as ``excluded``: they give the reader their place
        in the book but are dimmed and kept out of the progress totals.
        """
        self.selection = {str(f) for f in files} if files else None
    def set_plan(self, counts: dict[str, int] | None) -> None:
        """Attach the engine's per-document segment totals.

        Documents with no translatable content stay in the list as ``skipped``
        (visible but not part of the totals); plan documents missing from the
        chapter list are appended (front matter, cover files, …).
        """
        self.plan = {k: int(v) for k, v in (counts or {}).items() if k != TOC_PAGE}
        for file_name, total in self.plan.items():
            if total > 0 and file_name not in self._known:
                self._known.add(file_name)
                self.units.append(ChapterUnit(file=file_name, name=file_name))
        self.units.sort(key=lambda unit: sorted_mixed_keys(unit.file))

    def set_units(self, units: list[ChapterUnit]) -> None:
        self.units = list(units)
        self._known = {unit.file for unit in self.units}
        self.done.clear()
        self.errors.clear()
        self.cached = 0
        self.last = None
        self.finished = False
        self.exported = False

    # -- state ------------------------------------------------------------
    def total(self, file_name: str) -> int:
        return self.plan.get(file_name, 0)

    def state(self, file_name: str) -> str:
        if self.selection is not None and file_name not in self.selection:
            return STATE_EXCLUDED
        if self.errors.get(file_name):
            return STATE_ERROR
        total = self.total(file_name)
        if not total:
            # No translatable content (or plan not known yet).
            return STATE_SKIPPED if self.plan else STATE_PENDING
        get = self.done.get(file_name, 0)
        if get >= total:
            return STATE_DONE
        if get > 0:
            return STATE_RUNNING
        return STATE_PENDING

    def progress(self, file_name: str) -> tuple[int, int]:
        return self.done.get(file_name, 0), self.total(file_name)

    def tracked(self) -> list[ChapterUnit]:
        """Units that carry content and belong to the selection."""
        return [unit for unit in self.units
                if self.total(unit.file) > 0
                and (self.selection is None or unit.file in self.selection)]

    def overall(self) -> tuple[int, int]:
        done = sum(min(self.done.get(u.file, 0), self.total(u.file))
                   for u in self.tracked())
        total = sum(self.total(u.file) for u in self.tracked())
        return done, total

    def overall_percent(self) -> float:
        done, total = self.overall()
        return (done / total * 100.0) if total else 0.0

    def running_units(self) -> list[str]:
        return [u.file for u in self.tracked()
                if self.state(u.file) in (STATE_RUNNING, STATE_ERROR)]

    def done_chapters(self) -> int:
        """Chapters of the selection that are fully translated."""
        return sum(1 for unit in self.tracked()
                   if self.state(unit.file) == STATE_DONE)

    def cached_chapters(self) -> int:
        """Finished chapters whose segments all came from the cache."""
        return sum(1 for unit in self.tracked()
                   if self.state(unit.file) == STATE_DONE
                   and self.cached_pages.get(unit.file, 0) >= self.total(unit.file))

    def selection_size(self) -> int:
        """How many chapters the run is about (the ones with content)."""
        return len(self.tracked())

    def summary(self) -> dict[str, int]:
        """Counts for the completion notice."""
        return {"done": self.done_chapters(),
                "total": self.selection_size(),
                "cached": self.cached_chapters(),
                "segments": self.cached}

    def error_count(self) -> int:
        return sum(self.errors.values())

    # -- updates ----------------------------------------------------------
    def apply(self, delta: dict | None) -> bool:
        """Apply one delta payload; return ``True`` when something changed."""
        if not delta:
            return False
        changed = False
        for file_name, count in (delta.get("counts") or {}).items():
            self.done[file_name] = self.done.get(file_name, 0) + int(count)
            changed = True
        for file_name, count in (delta.get("errors") or {}).items():
            self.errors[file_name] = self.errors.get(file_name, 0) + int(count)
            changed = True
        cached = int(delta.get("cached") or 0)
        if cached:
            self.cached += cached
            changed = True
        for file_name, count in (delta.get("cached_pages") or {}).items():
            self.cached_pages[file_name] = (self.cached_pages.get(file_name, 0)
                                            + int(count))
            changed = True
        if delta.get("last"):
            self.last = tuple(delta["last"])  # type: ignore[assignment]
            changed = True
        return changed

    def finish(self, ok: bool = True) -> None:
        """Close the run: anything started and error-free counts as done.

        On failure the states are left alone (units stay ``running``/``pending``),
        so the view does not pretend the interrupted work completed.
        """
        self.finished = True
        if not ok:
            return
        for unit in self.units:
            if self.selection is not None and unit.file not in self.selection:
                continue
            if self.plan and not self.total(unit.file):
                continue
            if self.done.get(unit.file, 0) > 0 and not self.errors.get(unit.file):
                self.done[unit.file] = self.total(unit.file)

    def mark_exported(self) -> None:
        self.exported = True
