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
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QSizePolicy, QSpinBox, QStackedWidget, QTabBar, QToolButton, QVBoxLayout,
    QWidget)

from .. import appconfig
from .. import theme as theme_mod
from ..engines.languages import google as GOOGLE_LANGUAGES
from ..i18n import T, get_language
from ..reader import available_backends
from .book_toast import BookToast
from .icons import icon

__all__ = ["WorkflowBar", "build_workflow", "ToolPanel"]


class WorkflowButton(QWidget):
    """Toolbar button: a large icon with the function name on two lines below."""

    clicked = pyqtSignal()
    toggled = pyqtSignal(bool)

    def __init__(self, text: str, icon_name: str, slot=None, *,
                 tooltip: str | None = None, shortcut: str | None = None,
                 checkable: bool = False, on_toggle=None, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter
                            | Qt.AlignmentFlag.AlignTop)

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


class _PanelDivider(QWidget):
    """Thin 1px vertical rule between two ribbon panels.

    Office draws a hairline that spans (almost) the panel height; the light
    colour comes from the theme stylesheet (``#panelDivider``).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panelDivider")
        # Plain QWidget backgrounds need this attribute for QSS to paint them.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)


class ToolPanel(QWidget):
    """A ribbon-style panel: controls on top, the function name underneath.

    ``break_after`` stacks the controls on two sub-rows (Office groups with a
    lot of content do the same), which also keeps the toolbar narrower.
    """

    def __init__(self, key: str, caption: str, *, break_after: int = 0,
                 launcher=None, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self._count = 0
        self._break_after = max(0, int(break_after))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(5)
        self.grid.setVerticalSpacing(2)
        outer.addLayout(self.grid, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(0)
        bottom.addStretch(1)
        self.caption = QLabel(caption)
        self.caption.setObjectName("panelCaption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        # Word wrap keeps the caption from making small panels wider.
        self.caption.setWordWrap(True)
        # Bottom-aligned so the caption row stays level with launcher panels.
        bottom.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignBottom)
        bottom.addStretch(1)

        self.launcher: QToolButton | None = None
        if launcher is not None:
            tooltip, slot = launcher
            self.launcher = QToolButton(self)
            self.launcher.setObjectName("panelLauncher")
            self.launcher.setAutoRaise(True)
            self.launcher.setText("\u25e2")
            self.launcher.setToolTip(tooltip)
            self.launcher.setCursor(Qt.CursorShape.PointingHandCursor)
            # Keep it smaller than the caption line: a taller launcher would push
            # the caption up and break the alignment across panels.
            self.launcher.setFixedSize(13, 13)
            self.launcher.clicked.connect(slot)
            bottom.addWidget(self.launcher, 0, Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(bottom)

    # -- content ----------------------------------------------------------
    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        if self._break_after and self._count >= self._break_after:
            row, column = 1, self._count - self._break_after
        else:
            row, column = 0, self._count
        self.grid.addWidget(widget, row, column, 1, 1,
                            Qt.AlignmentFlag.AlignLeft
                            | Qt.AlignmentFlag.AlignTop)
        if stretch:
            self.grid.setColumnStretch(column, stretch)
        self._count += 1
        return widget

    def caption_text(self) -> str:
        return self.caption.text()


class SectionPage(QWidget):
    """A horizontal array of ribbon panels for one workflow section."""

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("sectionPage")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 2, 8, 2)
        self._layout.setSpacing(5)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._panel: ToolPanel | None = None
        self._panels: list[ToolPanel] = []
        self._dividers: list[_PanelDivider] = []

    # -- panels -----------------------------------------------------------
    def panel(self, key: str, *, break_after: int = 0,
              launcher=None) -> ToolPanel:
        """Start a new panel (a divider is added between panels)."""
        if self._panels:
            divider = _PanelDivider(self)
            self._dividers.append(divider)
            self._layout.addWidget(divider)
        panel = ToolPanel(key, T(key), break_after=break_after,
                          launcher=launcher)
        self._panels.append(panel)
        self._layout.addWidget(panel)
        self._panel = panel
        return panel

    def panels(self) -> list[ToolPanel]:
        return list(self._panels)

    def dividers(self) -> int:
        return len(self._dividers)

    # -- content ----------------------------------------------------------
    def _add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        if self._panel is not None:
            return self._panel.add(widget, stretch)
        # Legacy: a section without panels keeps the flat single row.
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

    def labelled_combo(self, label_key: str, items=None,
                       tooltip: str | None = None,
                       max_width: int | None = None) -> QComboBox:
        """A combo box with a visible label above it (they travel together)."""
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        label = QLabel(T(label_key))
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        combo = QComboBox()
        if items:
            combo.addItems(list(items))
        if tooltip:
            combo.setToolTip(tooltip)
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        if max_width:
            # Keeps the ribbon from growing past narrow screens; the popup still
            # shows the full text.
            combo.setMaximumWidth(max_width)
        box.addWidget(label)
        box.addWidget(combo)
        self._add(container)
        return combo

    def labelled_line(self, label_key: str, placeholder: str | None = None,
                      width: int | None = None) -> QLineEdit:
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        edit = QLineEdit()
        if placeholder:
            edit.setPlaceholderText(placeholder)
        if width:
            edit.setMinimumWidth(width)
        label = QLabel(T(label_key))
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(label)
        box.addWidget(edit)
        self._add(container)
        return edit

    def labelled_spin(self, label_key: str) -> QSpinBox:
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        spin = QSpinBox()
        label = QLabel(T(label_key))
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(label)
        box.addWidget(spin)
        self._add(container)
        return spin

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

    def divider(self) -> _PanelDivider:
        """Add a thin rule inside the current panel (rarely needed)."""
        divider = _PanelDivider(self)
        return self._add(divider)


class _HeightStack(QStackedWidget):
    """QStackedWidget that sizes to the *current* page (no big empty gaps).

    The minimum *width* is capped: a wide section (the Translate row needs
    ~1460px) used to propagate its minimum to the window, which then grew past
    the screen when that tab was selected. Now the row is clipped instead.
    """

    #: Never demand more than this from the window.
    MAX_MIN_WIDTH = 700

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.currentChanged.connect(lambda *_: self.updateGeometry())

    def sizeHint(self):  # noqa: N802 - Qt naming
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 - Qt naming
        page = self.currentWidget()
        if page is None:
            return super().minimumSizeHint()
        hint = page.minimumSizeHint()
        return QSize(min(hint.width(), self.MAX_MIN_WIDTH), hint.height())


class WorkflowBar(QWidget):
    sectionChanged = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowBar")
        self._book_name = ""
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
        # The book being worked on: centred in the empty area between the last
        # tab and the settings gear, deliberately louder than the toolbar.
        self.book_toast = BookToast(self)
        self.book_toast.hide()
        tl.addWidget(self.book_toast, 0, Qt.AlignmentFlag.AlignVCenter)
        tl.addStretch(1)
        self.btn_settings = WorkflowButton("", "settings", tooltip=T("action.settings"))
        tl.addWidget(self.btn_settings)
        root.addWidget(top)

        self.stack = _HeightStack()
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

    def set_book(self, name: str | None, *, percent: int | None = None,
                 working: bool = False) -> None:
        """Show the book being worked on in the pill (hidden when there is none)."""
        name = (name or "").strip()
        toast = self.book_toast
        toast.set_text(name)
        toast.set_percent(percent)
        toast.set_working(bool(name) and working)
        toast.setVisible(bool(name))
        self._book_name = name

    def set_book_working(self, working: bool) -> None:
        self.book_toast.set_working(bool(self._book_name) and bool(working))

    def set_book_percent(self, percent: int | None) -> None:
        self.book_toast.set_percent(percent)

    def book_name(self) -> str:
        return self.book_toast.text()

    def currentSection(self) -> int:
        return self.tabs.currentIndex()

    def sections(self) -> int:
        return self.tabs.count()


def build_workflow(window) -> WorkflowBar:
    """Create the workflow bar, wire it to ``window`` and return it.

    Controls are grouped in ribbon-style panels: the caption under each panel
    comes from the existing ``panel.*`` catalog keys (leftovers of the old
    ``pyqtribbon`` bar, revived here). Panels whose settings live in the tabbed
    Settings dialog get a small "dialog launcher" in their bottom-right corner.
    """
    bar = WorkflowBar(window)
    window.workflow = bar

    def launcher(tab: int):
        """Office-like ▸ in the panel corner: opens Settings on ``tab``."""
        return (T("action.settings"),
                lambda: window.on_settings(tab))

    def build_start_menu() -> QMenu:
        menu = QMenu(bar)
        menu.addAction(T("action.open"), window.on_open)
        menu.addAction(T("action.add_book"), window.on_add_book)
        menu.addAction(T("action.open_output"), window.on_open_output)
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
    p.panel("panel.file", launcher=launcher(5))
    p.button("action.add_book", "add", window.on_add_book, tooltip=T("tip.add_book"))
    p.button("action.remove_book", "remove", window.on_remove_book)
    p.button("action.open_reader", "reader", window.on_open_reader)
    p.button("action.refresh", "refresh", window.on_refresh)
    p.panel("panel.content")
    p.button("view.original", "library", lambda: window.set_library_view("original"))
    p.button("view.translated", "check", lambda: window.set_library_view("translated"))
    p.button("view.chapters", "chapters", lambda: window.set_library_view("chapters"))
    p.panel("panel.view")
    p.button("view.grid", "assets", lambda: window.set_library_layout("grid"))
    p.button("view.list", "format", lambda: window.set_library_layout("list"))
    p.panel("panel.actions")
    p.button("action.compare", "parallel", window.on_compare)
    p.button("action.retranslate", "translate", window.on_retranslate)
    p.button("action.extract_chapters", "chapters", window.on_extract_chapters)
    p.panel("panel.information")
    p.button("action.reveal", "folder", window.on_reveal)
    p.button("action.stats", "report", window.on_stats)
    p.stretch()

    # -- Reader --------------------------------------------------------
    p = bar.add_section("reader", T("tab.reader"))
    p.panel("panel.navigation")
    window.btn_toc = p.button("action.toc", "chapters", window.on_toggle_toc)
    p.button("action.expand_all", "add", window.on_expand_all)
    p.button("action.collapse_all", "remove", window.on_collapse_all)
    # The "Appearance" group is the widest: two sub-rows keep the ribbon narrow.
    p.panel("panel.appearance", launcher=launcher(1))
    window.cmb_theme_reader = p.labelled_combo(
        "label.reader_theme", [T(f"theme.{m}") for m in ("light", "sepia", "dark")],
        tooltip=T("label.reader_theme"), max_width=140)
    window.cmb_theme_reader.currentIndexChanged.connect(
        lambda i: window._set_reader_theme(("light", "sepia", "dark")[max(0, i)]))
    window.cmb_font = p.labelled_combo(
        "label.font", ["Serif", "Sans Serif", "Monospace"],
        tooltip=T("label.font"), max_width=130)
    window.cmb_font.currentIndexChanged.connect(window.on_font_changed)
    window.cmb_line = p.labelled_combo(
        "label.line_height", ["1.0", "1.2", "1.4", "1.5", "1.8", "2.0"],
        tooltip=T("label.line_height"), max_width=110)
    window.cmb_line.setCurrentIndex(3)  # 1.5
    window.cmb_line.currentIndexChanged.connect(window.on_line_height_changed)
    window.chk_justify = p.check("label.justify")
    window.chk_justify.setChecked(True)
    window.chk_justify.toggled.connect(window.on_justify_toggled)
    window.chk_hyphenate = p.check("label.hyphenate")
    window.chk_hyphenate.setChecked(True)
    window.chk_hyphenate.toggled.connect(window.on_hyphenate_toggled)
    p.panel("label.zoom")
    p.button("assets.zoom_in", "zoom_in", lambda: window.reader.backend.set_zoom(1))
    p.button("assets.zoom_out", "zoom_out", lambda: window.reader.backend.set_zoom(-1))
    p.panel("panel.search")
    window.edt_find = p.line(T("label.search"), width=160)
    window.edt_find.returnPressed.connect(window.on_find_run)
    p.button("action.find_next", "find", window.on_find_next)
    p.panel("panel.compare")
    window.btn_parallel = p.button(
        "action.compare", "parallel", checkable=True,
        on_toggle=window.on_parallel_toggled)
    p.panel("panel.notes")
    p.button("action.add_note", "note", window.on_add_note)
    p.button("action.bookmarks", "bookmark", window.on_bookmarks)
    p.button("action.print_pdf", "print", window.on_print_pdf)
    p.stretch()

    # -- Assets --------------------------------------------------------
    p = bar.add_section("assets", T("tab.assets"))
    p.panel("panel.source", launcher=launcher(5))
    window.cmb_assets_edition = p.labelled_combo(
        "label.edition", [T("edition.original"), T("edition.translated")],
        tooltip=T("label.edition"), max_width=150)
    window.cmb_assets_edition.currentIndexChanged.connect(
        window._on_assets_edition_changed)
    p.button("action.refresh", "refresh", window.on_assets_reload)
    p.panel("panel.figures")
    p.button("action.load", "assets", window._load_figures)
    p.button("action.export_assets", "export", lambda: window.figures._export("img"))
    p.button("assets.save_back", "save", lambda: window.figures.save_back())
    p.panel("assets.texts")
    p.button("assets.texts", "preview", window._load_texts)
    p.button("assets.save_back", "save", lambda: window.texts.save_back())
    p.panel("panel.tables")
    p.button("panel.tables", "format", window._load_tables)
    p.button("assets.save_back", "save", lambda: window.tables.save_back())
    p.stretch()

    # -- Translate -----------------------------------------------------
    p = bar.add_section("translate", T("tab.translate"))
    p.panel("panel.run")
    window.btn_translate = p.button(
        "action.translate_book", "translate", window.on_translate_book, "Ctrl+Return")
    window.btn_translate_chapters = p.button(
        "action.translate_chapters", "chapters", window.on_translate_chapters)
    window.btn_cancel = p.button("action.cancel", "cancel", window.on_cancel)
    window.btn_cancel.setEnabled(False)
    p.panel("panel.engine", launcher=launcher(2))
    window.cmb_engine = p.labelled_combo("panel.engine", appconfig.engine_names(),
                                         tooltip=T("panel.engine"), max_width=190)
    window.cmb_engine.currentTextChanged.connect(window._on_engine_changed)
    window.edt_api_key = p.labelled_line("label.api_key", width=140)
    window.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
    window.cmb_model = p.labelled_combo("label.model", tooltip=T("label.model"),
                                        max_width=150)
    window.cmb_model.setEditable(True)
    p.panel("panel.languages", launcher=launcher(2))
    window.cmb_source = p.labelled_combo(
        "label.source", ["Auto detect"] + list(GOOGLE_LANGUAGES),
        tooltip=T("label.source"), max_width=170)
    window.cmb_target = p.labelled_combo(
        "label.target", list(GOOGLE_LANGUAGES), tooltip=T("label.target"),
        max_width=170)
    p.button("action.swap", "swap", window.on_swap_languages)
    p.panel("panel.options", launcher=launcher(2))
    window.chk_bilingual = p.check("label.bilingual_short")
    window.chk_bilingual.setToolTip(T("label.bilingual"))
    window.chk_cache = p.check("label.cache")
    window.chk_cache.setChecked(True)
    window.chk_batch = p.check("label.batch")
    p.panel("panel.preview")
    p.button("tab.preview", "preview",
             lambda: window.tabs.setCurrentWidget(window.preview))
    p.stretch()

    # -- Quality -------------------------------------------------------
    p = bar.add_section("quality", T("tab.quality"))
    p.panel("panel.evaluation", launcher=launcher(3))
    p.button("action.evaluate", "check", lambda: window.on_quality(False))
    p.button("action.evaluate_ai", "quality", lambda: window.on_quality(True))
    window.spn_samples = p.labelled_spin("label.samples")
    window.spn_samples.setRange(1, 100)
    window.spn_samples.setValue(10)
    p.panel("panel.report", launcher=launcher(3))
    p.button("action.report_save", "save", window.on_report_save)
    p.button("action.report_open", "report", window.on_report_open)
    p.panel("label.threshold")
    window.spn_threshold = p.labelled_spin("label.threshold")
    window.spn_threshold.setRange(0, 100)
    window.spn_threshold.setValue(60)
    p.stretch()

    # -- Export --------------------------------------------------------
    p = bar.add_section("export", T("tab.export"))
    p.panel("panel.source", launcher=launcher(4))
    window.cmb_export_edition = p.labelled_combo(
        "label.edition", [T("edition.original"), T("edition.translated")],
        tooltip=T("label.edition"), max_width=150)
    window.edt_export_chapters = p.line(T("label.chapters_filter"), width=160)
    p.panel("panel.format_grp", launcher=launcher(4))
    window.cmb_export_format = p.labelled_combo("label.format",
                                                tooltip=T("label.format"),
                                                max_width=160)
    window.cmb_export_format.setMinimumWidth(110)
    p.button("action.export", "export", window.on_export_quick)
    p.button("action.export", "package", window.on_export)
    p.panel("panel.asset_export")
    p.button("action.export_assets", "assets", window.on_export_assets)
    p.stretch()

    # -- Tools ---------------------------------------------------------
    p = bar.add_section("tools", T("tab.tools"))
    p.panel("label.segments")
    p.button("action.split", "split", window.on_split)
    p.button("action.merge", "merge", window.on_merge)
    p.panel("panel.maintenance", launcher=launcher(5))
    p.button("action.clear_cache", "cache", window.on_clear_cache)
    p.button("action.data_dir", "file_folder", window.on_data_dir)
    p.stretch()

    return bar
