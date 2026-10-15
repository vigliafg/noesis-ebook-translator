"""Simulated two-row workflow toolbar (no external ribbon dependency).

Top strip: a *Start* menu, the 7 workflow sections and a Settings button.
Bottom strip: a horizontal array of icon+text controls for the active section.

The controls call the existing :class:`main.MainWindow` methods, so this module
is pure wiring + look. Icons come from :mod:`.icons` (Fluent Emoji, MIT).
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QTabBar, QToolButton,
    QVBoxLayout, QWidget)

from .. import appconfig
from .. import theme as theme_mod
from ..engines.languages import google as GOOGLE_LANGUAGES
from ..i18n import T, get_language
from ..reader import available_backends
from .icons import icon

__all__ = ["WorkflowBar", "build_workflow"]


class WorkflowButton(QWidget):
    """Toolbar button: a large icon with the function name on two lines below."""

    clicked = pyqtSignal()
    toggled = pyqtSignal(bool)

    def __init__(self, text: str, icon_name: str, slot=None, *,
                 tooltip: str | None = None, shortcut: str | None = None,
                 checkable: bool = False, on_toggle=None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._button = QToolButton(self)
        self._button.setIcon(icon(icon_name))
        self._button.setIconSize(QSize(40, 40))
        self._button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._button.setAutoRaise(True)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setCheckable(bool(checkable))
        layout.addWidget(self._button, 0, Qt.AlignmentFlag.AlignHCenter)

        self._label = None
        if text:
            self._label = QLabel(text, self)
            self._label.setWordWrap(True)
            self._label.setMaximumWidth(104)
            self._label.setAlignment(Qt.AlignmentFlag.AlignHCenter
                                     | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.setToolTip(tooltip or text)
        if shortcut:
            self._button.setShortcut(shortcut)
        self._button.clicked.connect(lambda: self.clicked.emit())
        self._button.toggled.connect(self.toggled.emit)
        if slot is not None:
            self.clicked.connect(slot)
        if on_toggle is not None:
            self.toggled.connect(on_toggle)

    # -- proxies so callers can treat it like the underlying button --------
    def setChecked(self, value: bool) -> None:
        self._button.setChecked(bool(value))

    def isChecked(self) -> bool:
        return self._button.isChecked()

    def blockSignals(self, block: bool) -> bool:  # noqa: N802 - Qt naming
        return self._button.blockSignals(block)

    def setEnabled(self, value: bool) -> None:  # noqa: N802 - Qt naming
        super().setEnabled(value)
        self._button.setEnabled(value)

    def icon(self) -> QIcon:
        return self._button.icon()

    def text(self) -> str:
        return self._label.text() if self._label is not None else ""


class SectionPage(QWidget):
    """A horizontal array of controls for one workflow section."""

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("sectionPage")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 5, 8, 5)
        self._layout.setSpacing(5)

    def _add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def stretch(self) -> None:
        self._layout.addStretch(1)

    def button(self, key: str, icon_name: str, slot=None, shortcut: str | None = None,
               tooltip: str | None = None, checkable: bool = False,
               on_toggle=None) -> WorkflowButton:
        return self._add(WorkflowButton(
            T(key), icon_name, slot, shortcut=shortcut, tooltip=tooltip,
            checkable=checkable, on_toggle=on_toggle))

    def combo(self, items=None, tooltip: str | None = None,
              width: int | None = None) -> QComboBox:
        combo = QComboBox()
        if items:
            combo.addItems(list(items))
        if tooltip:
            combo.setToolTip(tooltip)
        if width:
            combo.setMinimumWidth(width)
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        return self._add(combo)

    def check(self, key: str) -> QCheckBox:
        return self._add(QCheckBox(T(key)))

    def line(self, placeholder: str | None = None, width: int | None = None
             ) -> QLineEdit:
        edit = QLineEdit()
        if placeholder:
            edit.setPlaceholderText(placeholder)
        if width:
            edit.setMinimumWidth(width)
        return self._add(edit)

    def spin(self) -> QSpinBox:
        return self._add(QSpinBox())

    def label(self, key: str, tooltip: str | None = None) -> QLabel:
        label = QLabel(T(key))
        if tooltip:
            label.setToolTip(tooltip)
        return self._add(label)

    def separator(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.VLine)
        frame.setFrameShadow(QFrame.Shadow.Sunken)
        return self._add(frame)


class WorkflowBar(QWidget):
    sectionChanged = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowBar")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setObjectName("workflowTabs")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(6, 2, 6, 0)
        tl.setSpacing(4)
        self.btn_start = QToolButton()
        self.btn_start.setObjectName("startButton")
        self.btn_start.setAutoRaise(True)
        self.btn_start.setIconSize(QSize(20, 20))
        self.btn_start.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_start.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        tl.addWidget(self.btn_start)
        self.tabs = QTabBar()
        self.tabs.setObjectName("sectionBar")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        tl.addWidget(self.tabs)
        tl.addStretch(1)
        self.btn_settings = WorkflowButton("", "settings", tooltip=T("action.settings"))
        tl.addWidget(self.btn_settings)
        root.addWidget(top)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self._pages: list[SectionPage] = []

    # ------------------------------------------------------------------
    def add_section(self, key: str, title: str) -> SectionPage:
        page = SectionPage(key)
        self._pages.append(page)
        self.stack.addWidget(page)
        self.tabs.addTab(title)
        return page

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
        self.sectionChanged.emit(index)

    def setCurrentSection(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)

    def currentSection(self) -> int:
        return self.tabs.currentIndex()

    def sections(self) -> int:
        return self.tabs.count()


def build_workflow(window) -> WorkflowBar:
    """Create the workflow bar, wire it to ``window`` and return it."""
    bar = WorkflowBar(window)
    window.workflow = bar

    def build_start_menu() -> QMenu:
        menu = QMenu(bar)
        menu.addAction(T("action.open"), window.on_open)
        menu.addAction(T("action.add_book"), window.on_add_book)
        menu.addAction(T("action.open_output"), window.on_open_output)
        menu.addSeparator()

        settings = appconfig.load_settings()
        theme_menu = menu.addMenu(T("label.theme"))
        for mode in theme_mod.theme_choices():
            act = theme_menu.addAction(T(f"theme.{mode}"))
            act.setCheckable(True)
            act.setChecked(settings.get("ui_theme", "system") == mode)
            act.triggered.connect(lambda _c, m=mode: window._set_theme(m))
        lang_menu = menu.addMenu(T("label.ui_language"))
        for code in ("it", "en", "fr", "es", "de"):
            act = lang_menu.addAction(T(f"language.{code}"))
            act.setCheckable(True)
            act.setChecked(get_language() == code)
            act.triggered.connect(lambda _c, c=code: window._set_ui_language(c))
        backend_menu = menu.addMenu(T("label.reader_backend"))
        for backend in ["auto"] + available_backends():
            act = backend_menu.addAction(T(f"backend.{backend}"))
            act.setCheckable(True)
            act.setChecked(settings.get("reader_backend", "auto") == backend)
            act.triggered.connect(lambda _c, b=backend: window._set_reader_backend(b))

        menu.addSeparator()
        menu.addAction(T("action.settings"), window.on_settings)
        menu.addAction(T("action.wizard"), window.on_wizard)
        menu.addSeparator()
        menu.addAction(T("action.help"), window.on_help)
        menu.addAction(T("action.open_online_help"), window.on_online_help)
        menu.addAction(T("action.about"), window.on_about)
        menu.addAction(T("action.license"), window.on_license)
        menu.addAction(T("action.upstream"), window.on_upstream)
        menu.addSeparator()
        menu.addAction(T("action.engine_version"), window.on_engine_version)
        menu.addAction(T("action.data_dir"), window.on_config_dir)
        return menu

    bar.btn_start.setMenu(build_start_menu())
    if not window.windowIcon().isNull():
        bar.btn_start.setIcon(window.windowIcon())

    # -- Library -------------------------------------------------------
    p = bar.add_section("library", T("tab.library"))
    p.button("action.add_book", "add", window.on_add_book, tooltip=T("tip.add_book"))
    p.button("action.remove_book", "remove", window.on_remove_book)
    p.button("action.open_reader", "reader", window.on_open_reader)
    p.button("action.refresh", "refresh", window.on_refresh)
    p.separator()
    p.button("view.original", "library", lambda: window.set_library_view("original"))
    p.button("view.translated", "check", lambda: window.set_library_view("translated"))
    p.button("view.chapters", "chapters", lambda: window.set_library_view("chapters"))
    p.separator()
    p.button("action.compare", "parallel", window.on_compare)
    p.button("action.retranslate", "translate", window.on_retranslate)
    p.button("action.extract_chapters", "chapters", window.on_extract_chapters)
    p.separator()
    p.button("action.reveal", "folder", window.on_reveal)
    p.button("action.stats", "report", window.on_stats)
    p.stretch()

    # -- Reader --------------------------------------------------------
    p = bar.add_section("reader", T("tab.reader"))
    window.btn_toc = p.button("action.toc", "chapters", window.on_toggle_toc)
    p.separator()
    window.cmb_font = p.combo(["Serif", "Sans Serif", "Monospace"],
                              tooltip=T("label.font"))
    window.cmb_font.currentIndexChanged.connect(window.on_font_changed)
    window.cmb_line = p.combo(["1.0", "1.2", "1.5", "1.8", "2.0"],
                              tooltip=T("label.line_height"))
    window.cmb_line.setCurrentIndex(2)
    window.cmb_line.currentIndexChanged.connect(window.on_line_height_changed)
    p.button("assets.zoom_in", "zoom_in", lambda: window.reader.backend.set_zoom(1))
    p.button("assets.zoom_out", "zoom_out", lambda: window.reader.backend.set_zoom(-1))
    p.separator()
    window.edt_find = p.line(T("label.search"), width=160)
    window.edt_find.returnPressed.connect(window.on_find_run)
    p.button("action.find_next", "find", window.on_find_next)
    window.btn_parallel = p.button(
        "action.compare", "parallel", checkable=True,
        on_toggle=window.on_parallel_toggled)
    p.separator()
    p.button("action.add_note", "note", window.on_add_note)
    p.button("action.bookmarks", "bookmark", window.on_bookmarks)
    p.button("action.print_pdf", "print", window.on_print_pdf)
    p.stretch()

    # -- Assets --------------------------------------------------------
    p = bar.add_section("assets", T("tab.assets"))
    window.cmb_assets_edition = p.combo(
        [T("edition.original"), T("edition.translated")], tooltip=T("label.edition"))
    window.cmb_assets_edition.currentIndexChanged.connect(
        window._on_assets_edition_changed)
    p.button("action.refresh", "refresh", window.on_assets_reload)
    p.separator()
    p.button("action.load", "assets", window._load_figures)
    p.button("action.export_assets", "export", lambda: window.figures._export("img"))
    p.button("assets.save_back", "save", lambda: window.figures.save_back())
    p.separator()
    p.button("assets.texts", "preview", window._load_texts)
    p.button("assets.save_back", "save", lambda: window.texts.save_back())
    p.separator()
    p.button("panel.tables", "format", window._load_tables)
    p.button("assets.save_back", "save", lambda: window.tables.save_back())
    p.stretch()

    # -- Translate -----------------------------------------------------
    p = bar.add_section("translate", T("tab.translate"))
    window.btn_translate = p.button(
        "action.translate_book", "translate", window.on_translate_book, "Ctrl+Return")
    window.btn_translate_chapters = p.button(
        "action.translate_chapters", "chapters", window.on_translate_chapters)
    window.btn_cancel = p.button("action.cancel", "cancel", window.on_cancel)
    window.btn_cancel.setEnabled(False)
    p.separator()
    window.cmb_engine = p.combo(appconfig.engine_names(), tooltip=T("panel.engine"))
    window.cmb_engine.currentTextChanged.connect(window._on_engine_changed)
    window.edt_api_key = p.line(width=140)
    window.edt_api_key.setToolTip(T("label.api_key"))
    window.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
    window.cmb_model = p.combo(tooltip=T("label.model"))
    window.cmb_model.setEditable(True)
    p.separator()
    window.cmb_source = p.combo(["Auto detect"] + list(GOOGLE_LANGUAGES),
                                tooltip=T("label.source"))
    window.cmb_target = p.combo(list(GOOGLE_LANGUAGES), tooltip=T("label.target"))
    p.button("action.swap", "swap", window.on_swap_languages)
    p.separator()
    window.chk_bilingual = p.check("label.bilingual")
    window.chk_cache = p.check("label.cache")
    window.chk_cache.setChecked(True)
    window.chk_batch = p.check("label.batch")
    p.separator()
    p.button("tab.preview", "preview",
             lambda: window.tabs.setCurrentWidget(window.preview))
    p.stretch()

    # -- Quality -------------------------------------------------------
    p = bar.add_section("quality", T("tab.quality"))
    p.button("action.evaluate", "check", lambda: window.on_quality(False))
    p.button("action.evaluate_ai", "quality", lambda: window.on_quality(True))
    window.spn_samples = p.spin()
    window.spn_samples.setToolTip(T("label.samples"))
    window.spn_samples.setRange(1, 100)
    window.spn_samples.setValue(10)
    p.separator()
    p.button("action.report_save", "save", window.on_report_save)
    p.button("action.report_open", "report", window.on_report_open)
    p.separator()
    window.spn_threshold = p.spin()
    window.spn_threshold.setToolTip(T("label.threshold"))
    window.spn_threshold.setRange(0, 100)
    window.spn_threshold.setValue(60)
    p.stretch()

    # -- Export --------------------------------------------------------
    p = bar.add_section("export", T("tab.export"))
    window.cmb_export_edition = p.combo(
        [T("edition.original"), T("edition.translated")], tooltip=T("label.edition"))
    window.edt_export_chapters = p.line(T("label.chapters_filter"), width=160)
    p.separator()
    window.cmb_export_format = p.combo(tooltip=T("label.format"))
    window.cmb_export_format.setMinimumWidth(110)
    p.button("action.export", "export", window.on_export_quick)
    p.button("action.export", "package", window.on_export)
    p.separator()
    p.button("action.export_assets", "assets", window.on_export_assets)
    p.stretch()

    # -- Tools ---------------------------------------------------------
    p = bar.add_section("tools", T("tab.tools"))
    p.button("action.split", "split", window.on_split)
    p.button("action.merge", "merge", window.on_merge)
    p.separator()
    p.button("action.clear_cache", "cache", window.on_clear_cache)
    p.button("action.data_dir", "file_folder", window.on_data_dir)
    p.stretch()

    return bar
