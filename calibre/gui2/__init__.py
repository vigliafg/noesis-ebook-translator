"""Subset of :mod:`calibre.gui2` used by the engine (signal dispatcher)."""
from __future__ import annotations


class Dispatcher:
    """Minimal callable dispatcher: ``Dispatcher(cb, ...)(*args)`` calls ``cb``.

    Calibre launches jobs with a :class:`Dispatcher` wrapping the completion
    callback. The standalone build runs jobs synchronously, so this just forwards
    the call while preserving any bound arguments.
    """

    def __init__(self, callback, *args, **kwargs):
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

    def __call__(self, *args, **kwargs):
        if self.callback is None:
            return None
        merged = dict(self.kwargs)
        merged.update(kwargs)
        return self.callback(*(self.args + args), **merged)
