"""Release self-test for the frozen (PyInstaller) application.

A ``--windowed`` bundle has no reliable stdout on Windows/macOS, so the result
is also written as JSON with ``--report <path>`` and the process exit code is
the gate. The checks are deliberately *inside* the bundle: ``tests.console_probe``
imports the source tree and cannot prove that PyInstaller collected the
locales, the provider snapshot, the token encodings, ``reader_web`` or the
icons. ``--self-test-reader`` additionally opens a real EPUB with the full
( QtWebEngine ) backend and waits for foliate's ``opened`` signal: a mere
import of the module is not proof that the reader works.
"""
from __future__ import annotations

import json
import os
import platform
import sqlite3
import sys
import tempfile
import time
import traceback
from pathlib import Path

__all__ = [
    "run_self_test",
    "run_reader_test",
    "report_path_from_args",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _resource_root() -> Path:
    """Root of the bundle (``_MEIPASS``) or of the source checkout."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent.parent


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def report_path_from_args(args: list[str]) -> str | None:
    """Extract ``--report <path>`` (also ``--report=<path>``) from ``args``."""
    for index, arg in enumerate(args):
        if arg == "--report" and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--report="):
            return arg.split("=", 1)[1]
    return None


def _write_report(report: dict, path: str | None) -> None:
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if path:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    stream = sys.stdout
    if stream is not None:
        try:
            stream.write(text + "\n")
            stream.flush()
        except Exception:  # noqa: BLE001
            pass


def _make_epub(directory: str) -> str:
    """Write a tiny two-chapter EPUB (no dependency on ``tests.fixtures``)."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("noesis-self-test")
    book.set_title("Self test")
    book.set_language("en")
    chapter = epub.EpubHtml(title="One", file_name="one.xhtml", lang="en")
    chapter.content = (
        "<html xmlns='http://www.w3.org/1999/xhtml'><head/><body>"
        "<h1>One</h1><p>Hello from the self-test.</p></body></html>")
    book.add_item(chapter)
    book.toc = (epub.Link("one.xhtml", "One", "one"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    path = os.path.join(directory, "self-test.epub")
    epub.write_epub(path, book)
    return path


class _Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, name: str, fn) -> bool:
        try:
            detail = fn()
            self.items.append({"name": name, "ok": True, "detail": detail})
            return True
        except Exception as exc:  # noqa: BLE001 - a check must never abort the run
            self.items.append({
                "name": name,
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=4),
            })
            return False

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.items)


# ---------------------------------------------------------------------------
# fast checks
# ---------------------------------------------------------------------------
def run_self_test(report_path: str | None = None,
                  require_full: bool = False) -> int:
    """Check the frozen bundle's resources and core imports.

    ``require_full`` makes the absence of QtWebEngine (or of the DOCX exporter)
    a failure. Release builds pass ``--require-full``; source runs may omit it
    to test a lite-only environment.
    """
    from . import APP_VERSION, __version__
    from . import i18n, provider_catalog, token_count

    checks = _Checks()
    started = time.time()

    checks.add("version", lambda: {
        "app": APP_VERSION,
        "engine": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": platform.platform(),
    })

    def core_imports():
        import ebooklib  # noqa: F401
        import lxml  # noqa: F401
        import mechanize  # noqa: F401
        import tiktoken  # noqa: F401
        import noesis_ebook_translator.engines  # noqa: F401
        return "ok"

    checks.add("core_imports", core_imports)

    def locales():
        langs = i18n.available_languages()
        missing = [lang for lang in i18n.LANGUAGES if lang not in langs]
        if missing:
            raise AssertionError(f"missing catalogs: {missing}")
        return langs

    checks.add("locales", locales)

    def providers():
        data = json.loads(
            (_package_dir() / "data" / "providers.json").read_text("utf-8"))
        if not data.get("models") or not data.get("routes"):
            raise AssertionError("provider snapshot is empty")
        if not provider_catalog.PROVIDERS:
            raise AssertionError("no curated providers")
        return {"models": len(data["models"]),
                "providers": len(provider_catalog.PROVIDERS)}

    checks.add("provider_catalog", providers)

    def encodings():
        files = sorted(
            path.name for path in token_count.BUNDLE_DIR.glob("*")
            if path.is_file())
        if len(files) < 2:
            raise AssertionError(f"bundled encodings: {files}")
        token_count.configure_cache()
        if token_count.count("hello world", "gpt-4o") <= 0:
            raise AssertionError("tokenizer returned 0")
        return files

    checks.add("token_encodings", encodings)

    def icons():
        from .ui.icons import available, icons_dir
        names = available()
        if not (icons_dir() / "icons.json").is_file():
            raise AssertionError(f"missing icons.json in {icons_dir()}")
        if len(names) < 10:
            raise AssertionError(f"only {len(names)} icons found")
        return {"dir": str(icons_dir()), "icons": len(names)}

    checks.add("icons", icons)

    def reader_assets():
        root = _resource_root() / "reader_web"
        required = [root / "reader.html", root / "noesis_bridge.js",
                    root / "foliate-js" / "reader.js"]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise AssertionError(f"missing reader assets: {missing}")
        return str(root)

    checks.add("reader_assets", reader_assets)

    def data_writable():
        from .paths import data_dir
        directory = data_dir() / "self-test"
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / "probe.txt"
        probe.write_text("ok", encoding="utf-8")
        if probe.read_text("utf-8") != "ok":
            raise AssertionError("read-back failed")
        probe.unlink()
        return str(data_dir())

    checks.add("data_dir_writable", data_writable)

    def epub_roundtrip():
        with tempfile.TemporaryDirectory(prefix="noesis-self-test-") as tmp:
            path = _make_epub(tmp)
            import ebooklib
            from ebooklib import epub
            book = epub.read_epub(path)
            if not book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                raise AssertionError("no documents after round-trip")
            return path

    checks.add("epub_roundtrip", epub_roundtrip)

    def exports():
        from .exporter import docx_available, pdf_available
        pdf = pdf_available()
        docx = docx_available()
        if require_full and not pdf:
            raise AssertionError("QtWebEngine/PDF export missing")
        if require_full and not docx:
            raise AssertionError("python-docx/DOCX export missing")
        return {"pdf": pdf, "docx": docx}

    checks.add("exports", exports)

    def full_backend():
        import importlib.util
        full = importlib.util.find_spec("PyQt6.QtWebEngineWidgets") is not None
        if require_full and not full:
            raise AssertionError("full reader backend missing")
        return full

    checks.add("full_backend", full_backend)

    report = {
        "kind": "self-test",
        "ok": checks.ok,
        "app_version": APP_VERSION,
        "engine_version": __version__,
        "elapsed_seconds": round(time.time() - started, 2),
        "checks": checks.items,
    }
    _write_report(report, report_path)
    return 0 if checks.ok else 1


# ---------------------------------------------------------------------------
# reader check (full backend)
# ---------------------------------------------------------------------------
def run_reader_test(report_path: str | None = None,
                    timeout_seconds: int = 30) -> int:
    """Open a real EPUB with foliate/QtWebEngine and require ``opened``."""
    from . import APP_VERSION

    started = time.time()
    result: dict = {
        "kind": "self-test-reader",
        "ok": False,
        "app_version": APP_VERSION,
        "backend": None,
        "opened": False,
        "error": "",
    }
    tmp = tempfile.mkdtemp(prefix="noesis-self-test-reader-")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from .reader import prepare_full
        if not prepare_full():
            raise RuntimeError("QtWebEngine is not available in this bundle")

        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(["noesis-self-test-reader"])
        from .reader.webengine_backend import WebEngineBackend

        backend = WebEngineBackend()
        result["backend"] = "full"
        loop = QEventLoop()

        def on_opened(_payload: str) -> None:
            result["opened"] = True
            loop.quit()

        def on_failed(message: str) -> None:
            result["error"] = message or "foliate reported an error"
            loop.quit()

        backend.bridge.opened.connect(on_opened)
        backend.bridge.failed.connect(on_failed)
        path = _make_epub(tmp)
        backend.open_file(path)
        QTimer.singleShot(int(timeout_seconds * 1000), loop.quit)
        loop.exec()
        try:
            backend.shutdown()
        except Exception:  # noqa: BLE001 - teardown noise is not a test result
            pass
        if not result["opened"] and not result["error"]:
            result["error"] = f"timeout after {timeout_seconds}s"
        # Give Chromium a chance to flush its own shutdown messages.
        app.processEvents()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc(limit=6)

    result["ok"] = bool(result["opened"]) and not result["error"]
    result["elapsed_seconds"] = round(time.time() - started, 2)
    _write_report(result, report_path)
    return 0 if result["ok"] else 1
