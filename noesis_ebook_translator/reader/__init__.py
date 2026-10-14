"""Reader package: backend factory + public widgets.

The desktop app supports two reader flavours (see the project plan):

* **full** — ``foliate-js`` running inside ``QWebEngineView`` (EPUB, MOBI/AZW3,
  FB2, CBZ, PDF; spread, search, annotations, print-to-PDF);
* **lite** — ``QTextBrowser`` (EPUB only; no WebEngine dependency).

``create_backend('auto')`` picks the full backend when WebEngine is importable
and silently falls back to lite otherwise.
"""
from __future__ import annotations

__all__ = ["create_backend", "available_backends", "ReaderWidget", "EpubDocument"]
# session imported lazily to avoid circular imports at module import time


def available_backends() -> list[str]:
    backends = ["lite"]
    try:
        import PyQt6.QtWebEngineWidgets  # noqa: F401
        backends.insert(0, "full")
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    return backends


def _preferred_mode() -> str:
    import os
    # Default to the lite reader (deterministic, no WebEngine subprocess). The
    # "full" packaging flavour exports NOESIS_READER_BACKEND=full.
    return os.environ.get("NOESIS_READER_BACKEND", "lite").lower()


def prepare_full() -> bool:
    """Import QtWebEngine and register the scheme *before* QApplication."""
    if _preferred_mode() == "lite":
        return False
    try:
        import PyQt6.QtWebEngineWidgets  # noqa: F401  (must precede QApplication)
    except Exception:  # noqa: BLE001
        return False
    from .scheme import ensure_scheme
    ensure_scheme()
    return True


def create_backend(mode: str = "auto", parent=None):
    mode = (mode or "auto").lower()
    if mode == "auto":
        mode = _preferred_mode()
    if mode in ("auto", "full"):
        try:
            from .webengine_backend import WebEngineBackend
            return WebEngineBackend(parent)
        except Exception:  # noqa: BLE001 - not available → fall back
            if mode == "full":
                raise
    from .lite_backend import LiteBackend
    return LiteBackend(parent)


def __getattr__(name):  # PEP 562 lazy attributes
    if name == "ReaderWidget":
        from .widget import ReaderWidget
        return ReaderWidget
    if name == "EpubDocument":
        from .document import EpubDocument
        return EpubDocument
    raise AttributeError(name)
