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

from .chapters import ChapterError, flatten, load_chapters
from .lib.utils import sorted_mixed_keys

__all__ = [
    "ChapterUnit", "build_units", "ProgressModel", "DeltaBatch",
    "TransferThrottle",
    "STATE_PENDING", "STATE_RUNNING", "STATE_DONE", "STATE_ERROR",
    "STATE_SKIPPED", "STATE_EXCLUDED", "STATE_HEADER",
]

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_SKIPPED = "skipped"
#: A chapter of the book that is not part of the current selection: shown (for
#: context) but never translated, so it stays dimmed and out of the totals.
STATE_EXCLUDED = "excluded"
#: A TOC entry that is only a heading (a "Part I…" with no document of its own):
#: it carries no progress, it is there to make the tree readable.
STATE_HEADER = "header"

#: The engine stores TOC titles as elements of this pseudo-document; they are not
#: part of any chapter, so they are excluded from the per-chapter counts.
TOC_PAGE = "toc.ncx"


@dataclass
class ChapterUnit:
    """One row of the chapter list: a **TOC entry**, not an XHTML document.

    Entries that share a document (``part.xhtml#ch1`` and ``part.xhtml#ch2``)
    stay distinct rows, and headings with no document of their own are kept as
    ``kind="section"`` so the tree stays readable. The progress itself is per
    document -- that is what the engine reports -- so the rows that share a file
    show the same numbers.
    """

    file: str | None = None
    name: str = ""
    depth: int = 0
    href: str | None = None
    kind: str = "document"          # "document" | "section"
    #: 1-based position in the TOC (from :func:`chapters.flatten`).
    index: int = 0
    #: A document the engine translated but the TOC does not mention (cover,
    #: nav, front matter). Appended after the TOC; the view labels it.
    extra: bool = False

    def label(self) -> str:
        return self.name or self.file or self.href or ""

    def key(self) -> str:
        """Stable identity of the entry: the href (anchor included) when there is
        one, else the document.

        A heading has neither, so it falls back to its TOC position: two headings
        must never share a key, or the list would treat them as the same row.
        """
        return self.href or self.file or f"#{self.index}"


def build_units(input_path: str | None, selected=None) -> list[ChapterUnit]:
    """Return every TOC entry, in **reading order**, as a flat list.

    The order is the TOC order (``flatten``), never a sort by file name: this list
    is what the user reads while the book is being translated. Entries are *not*
    collapsed by file, so two chapters that live in one XHTML document are two
    rows (the engine reports their progress together).

    ``selected`` optionally keeps only the entries whose href/file matches.
    This is a *convenience* for callers that want a subset; the Translate panel
    does **not** use it, because it keeps every entry visible and marks the
    others ``excluded`` with :meth:`ProgressModel.set_selection`.
    """
    if not input_path:
        return []
    try:
        tree = flatten(load_chapters(input_path))
    except ChapterError:
        raise                      # the caller has to be able to *report* it
    except Exception:  # noqa: BLE001 - a broken TOC must not break the view
        return []
    wanted = {str(s) for s in selected} if selected else None
    units: list[ChapterUnit] = []
    for chapter in tree:
        file = chapter.file or None
        href = chapter.href or None
        if wanted is not None and href not in wanted and (file or "") not in wanted:
            continue
        units.append(ChapterUnit(
            file=file, name=chapter.name or file or "", depth=chapter.depth,
            href=href, kind="document" if file else "section",
            index=chapter.index))
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

        ``counts`` means **translated successfully**; a failed segment goes to
        ``errors`` only. Keeping the two apart is what stops a run with a failed
        segment from reaching 100%: the progress bar and ``overall()`` count
        translations, not attempts.
        """
        if paragraph is None or getattr(paragraph, "ignored", False):
            return
        page = getattr(paragraph, "page", None)
        failed = bool(getattr(paragraph, "error", None))
        if page and page != TOC_PAGE:
            if failed:
                self.errors[page] = self.errors.get(page, 0) + 1
            else:
                self.counts[page] = self.counts.get(page, 0) + 1
        if (not failed and getattr(paragraph, "is_cache", False)
                and page and page != TOC_PAGE):
            # Per-document too: a chapter served entirely from the cache was
            # already translated in an earlier run. TOC titles are not part of a
            # chapter and must not inflate the global "cached" count.
            self.cached += 1
            self.cached_pages[page] = self.cached_pages.get(page, 0) + 1
        text = (getattr(paragraph, "translation", None) or "").strip()
        if text and not failed and page and page != TOC_PAGE:
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
    """Per-entry state, driven by plan + deltas.

    The list shows **every TOC entry**; the totals are computed over the **unique
    documents** behind them, so two entries that share an XHTML file are counted
    once (that is how the engine reports progress).
    """

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
        #: ``"finished"`` / ``"stopped"`` after :meth:`finish`; empty while live.
        self.stop_reason = ""
        #: Documents of the selection that ended a successful run with
        #: ``0 < done < total``: the run did not prove they were complete.
        self.incomplete: dict[str, tuple[int, int]] = {}
        self.selection: set[str] | None = None
        self._known: set[str] = {unit.file for unit in self.units if unit.file}
        #: Bumped on every change worth repainting. A big book (thousands of TOC
        #: entries) is repainted only when this moves, so the per-delta work stays
        #: O(visible rows) instead of O(entries).
        self.revision = 0

    # -- structure --------------------------------------------------------
    def set_selection(self, files) -> None:
        """Mark which entries are part of the translation.

        ``files`` holds entry identities: TOC hrefs (anchor included) and/or
        document names. Passing ``None`` (whole book) selects everything. Entries
        outside the selection stay visible as ``excluded``: they give the reader
        their place in the book but are dimmed and kept out of the totals.
        """
        self.selection = {str(f) for f in files} if files else None
        self.revision += 1

    def is_selected(self, unit: ChapterUnit) -> bool:
        if self.selection is None:
            return True
        return (unit.href in self.selection) or (unit.file in self.selection)

    def set_plan(self, counts: dict[str, int] | None) -> None:
        """Attach the engine's per-document segment totals.

        The list keeps the TOC (reading) order. Documents the TOC does not
        mention -- front matter the reader still gets, such as the nav or a cover
        page -- are appended at the end instead of being sorted into the tree.
        Entries with no translatable content stay visible as ``skipped``.
        """
        self.plan = {k: int(v) for k, v in (counts or {}).items() if k != TOC_PAGE}
        extra = [name for name, total in self.plan.items()
                 if total > 0 and name not in self._known]
        for file_name in sorted(extra, key=sorted_mixed_keys):
            self._known.add(file_name)
            self.units.append(ChapterUnit(file=file_name, name=file_name,
                                          kind="document", extra=True))
        self.revision += 1

    def set_units(self, units: list[ChapterUnit]) -> None:
        self.units = list(units)
        self._known = {unit.file for unit in self.units if unit.file}
        self.plan = {}
        self.done.clear()
        self.errors.clear()
        self.cached = 0
        self.cached_pages.clear()
        self.last = None
        self.finished = False
        self.stop_reason = ""
        self.incomplete = {}
        self.selection = None
        self.exported = False
        self.revision += 1

    # -- state ------------------------------------------------------------
    def total(self, file_name: str | None) -> int:
        return self.plan.get(file_name or "", 0)

    def file_state(self, file_name: str) -> str:
        """Progress state of a document, ignoring the selection."""
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

    def unit_state(self, unit: ChapterUnit) -> str:
        """State of one row: a heading carries no progress, an entry outside the
        selection stays dimmed."""
        if unit.kind != "document" or not unit.file:
            return STATE_HEADER
        if not self.is_selected(unit):
            return STATE_EXCLUDED
        return self.file_state(unit.file)

    def state(self, file_name: str) -> str:
        """State of a document by name.

        Legacy helper kept for callers that think in documents. It now goes
        through :meth:`unit_state` for the first unit of the file, so a shared
        document with one selected entry and one excluded entry reports the
        selected row's state instead of silently ignoring the selection.
        """
        units = [unit for unit in self.units if unit.file == file_name]
        if units:
            unit = next((unit for unit in units if self.is_selected(unit)),
                        units[0])
            return self.unit_state(unit)
        return self.file_state(file_name)

    def progress(self, file_name: str | None) -> tuple[int, int]:
        return self.done.get(file_name or "", 0), self.total(file_name)

    def tracked(self) -> list[ChapterUnit]:
        """One row per **document** with content that is part of the selection.

        Duplicate entries that share a file collapse to one, so the totals never
        count the same segments twice.
        """
        seen: set[str] = set()
        rows: list[ChapterUnit] = []
        for unit in self.units:
            if unit.kind != "document" or not unit.file or unit.file in seen:
                continue
            if not self.is_selected(unit):
                continue
            if self.total(unit.file) <= 0:
                continue
            seen.add(unit.file)
            rows.append(unit)
        return rows

    def overall(self) -> tuple[int, int]:
        done = sum(min(self.done.get(u.file, 0), self.total(u.file))
                   for u in self.tracked())
        total = sum(self.total(u.file) for u in self.tracked())
        return done, total

    def overall_percent(self) -> float:
        done, total = self.overall()
        return (done / total * 100.0) if total else 0.0

    def running_units(self) -> list[str]:
        """Documents actually in progress, not merely partially translated.

        ``running`` is derived from ``0 < done < total``, so a document stopped
        by a cancel stays ``running`` in the row. This method is the *activity*
        signal used by the pulse timer and the header: once the run is closed it
        returns nothing, and error rows are not activity either.
        """
        if self.finished:
            return []
        return [u.file for u in self.tracked()
                if self.file_state(u.file) == STATE_RUNNING]

    def done_chapters(self) -> int:
        """Documents of the selection that are fully translated."""
        return sum(1 for unit in self.tracked()
                   if self.file_state(unit.file) == STATE_DONE)

    def cached_chapters(self) -> int:
        """Finished documents whose segments all came from the cache."""
        return sum(1 for unit in self.tracked()
                   if self.file_state(unit.file) == STATE_DONE
                   and self.cached_pages.get(unit.file, 0) >= self.total(unit.file))

    def selection_size(self) -> int:
        """How many documents the run is about (the ones with content)."""
        return len(self.tracked())

    def summary(self) -> dict[str, int]:
        """Counts for the completion notice."""
        return {"done": self.done_chapters(),
                "total": self.selection_size(),
                "cached": self.cached_chapters(),
                "segments": self.cached,
                "incomplete": len(self.incomplete),
                "errors": self.error_count()}

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
        if changed:
            self.revision += 1
        return changed

    def finish(self, ok: bool = True) -> None:
        """Close the run without inventing progress.

        A successful run does **not** promote ``done > 0`` to ``total`` any more:
        the engine's callbacks are the only evidence that a segment was
        translated, and a mismatch between plan and callbacks must stay visible
        instead of becoming a fake 100%. Documents that end with
        ``done < total`` and no errors are recorded in :attr:`incomplete` so the
        caller can log them.
        """
        self.finished = True
        self.stop_reason = "finished" if ok else "stopped"
        self.revision += 1
        if not ok:
            return
        self.incomplete = {
            unit.file: (self.done.get(unit.file, 0), self.total(unit.file))
            for unit in self.tracked()
            if not self.errors.get(unit.file)
            and self.done.get(unit.file, 0) < self.total(unit.file)
        }

    def mark_exported(self) -> None:
        self.exported = True
        self.revision += 1
