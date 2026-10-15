"""Declarative-ish builder for the workflow ribbon.

The ribbon follows the app's workflow:

    Home · Library · Reader · Assets · Translate · Quality · Export · Tools · Info

Every button gets a colored icon (see :mod:`.icons`); ``build_ribbon(window)``
creates the widgets and stores the handles as attributes on ``window`` so the
rest of :class:`main.MainWindow` keeps working unchanged.
"""
from __future__ import annotations

from pyqtribbon import RibbonBar

from .. import theme as theme_mod
from ..i18n import T
from .icons import icon

__all__ = ["build_ribbon"]


def build_ribbon(window) -> None:
    ribbon = RibbonBar()
    window.setMenuWidget(ribbon)
    window.ribbon = ribbon

    # -- helpers ----------------------------------------------------------
    def category(key: str):
        return ribbon.addCategory(T(key))

    def panel(cat, key: str):
        return cat.addPanel(T(key))

    def big(p, key: str, ic: str, slot, shortcut: str | None = None,
            tooltip: str | None = None):
        return p.addLargeButton(T(key), icon=icon(ic), slot=slot,
                                shortcut=shortcut, tooltip=tooltip)

    def small(p, key: str, ic: str, slot, shortcut: str | None = None,
              tooltip: str | None = None):
        return p.addSmallButton(T(key), icon=icon(ic), slot=slot,
                                shortcut=shortcut, tooltip=tooltip)

    def toggle(p, key: str, ic: str, on_toggle, checkable=True):
        btn = p.addLargeToggleButton(T(key), icon=icon(ic))
        btn.toggled.connect(on_toggle)
        return btn

    # ===================================================================
    #  Home
    # ===================================================================
    home = category("tab.home")
    pf = panel(home, "panel.file")
    big(pf, "action.open", "folder", window.on_open, "Ctrl+O",
        tooltip=T("tip.open"))
    big(pf, "action.open_output", "file_folder", window.on_open_output)

    pc = panel(home, "panel.configuration")
    big(pc, "action.settings", "settings", window.on_settings, "Ctrl+,")
    big(pc, "action.wizard", "wizard", window.on_wizard)

    pa = panel(home, "panel.appearance")
    pa.addLabel(T("label.theme"))
    window.cmb_theme = pa.addComboBox(
        [T(f"theme.{m}") for m in theme_mod.theme_choices()])
    window.cmb_theme.currentIndexChanged.connect(window._on_theme_changed)
    pa.addLabel(T("label.ui_language"))
    window.cmb_ui_lang = pa.addComboBox(
        [T(f"language.{c}") for c in ("it", "en", "fr", "es", "de")])
    window.cmb_ui_lang.currentIndexChanged.connect(window._on_ui_language_changed)
    window.chk_reduce = pa.addCheckBox(T("label.reduce_motion"))
    window.chk_reduce.toggled.connect(window._on_reduce_motion)

    pr = panel(home, "panel.reader_default")
    pr.addLabel(T("label.reader_backend"))
    window.cmb_reader_default = pr.addComboBox([])
    window.cmb_reader_default.currentIndexChanged.connect(
        window._on_reader_backend_changed)

    # ===================================================================
    #  Library
    # ===================================================================
    lib = category("tab.library")
    pl = panel(lib, "panel.books")
    big(pl, "action.add_book", "add", window.on_add_book, tooltip=T("tip.add_book"))
    big(pl, "action.remove_book", "remove", window.on_remove_book)
    big(pl, "action.open_reader", "reader", window.on_open_reader)
    small(pl, "action.refresh", "refresh", window.on_refresh)

    pv = panel(lib, "panel.views")
    window.btn_view_original = pv.addLargeButton(
        T("view.original"), icon=icon("library"))
    window.btn_view_original.clicked.connect(lambda: window.set_library_view("original"))
    window.btn_view_translated = pv.addLargeButton(
        T("view.translated"), icon=icon("check"))
    window.btn_view_translated.clicked.connect(lambda: window.set_library_view("translated"))
    window.btn_view_chapters = pv.addLargeButton(
        T("view.chapters"), icon=icon("chapters"))
    window.btn_view_chapters.clicked.connect(lambda: window.set_library_view("chapters"))

    pac = panel(lib, "panel.actions")
    big(pac, "action.compare", "parallel", window.on_compare)
    big(pac, "action.retranslate", "translate", window.on_retranslate)
    big(pac, "action.extract_chapters", "chapters", window.on_extract_chapters)

    pm = panel(lib, "panel.metadata")
    small(pm, "action.reveal", "folder", window.on_reveal)
    small(pm, "action.stats", "report", window.on_stats)

    # ===================================================================
    #  Reader
    # ===================================================================
    read = category("tab.reader")
    pn = panel(read, "panel.navigation")
    window.btn_toc = big(pn, "action.toc", "chapters", window.on_toggle_toc)

    # Per-book reading settings (font, line height, size).
    pfont = panel(read, "panel.font")
    pfont.addLabel(T("label.font"))
    window.cmb_font = pfont.addComboBox(["Serif", "Sans Serif", "Monospace"])
    window.cmb_font.currentIndexChanged.connect(window.on_font_changed)
    pfont.addLabel(T("label.line_height"))
    window.cmb_line = pfont.addComboBox(["1.0", "1.2", "1.5", "1.8", "2.0"])
    window.cmb_line.setCurrentIndex(2)  # 1.5
    window.cmb_line.currentIndexChanged.connect(window.on_line_height_changed)
    pfont.addLabel(T("label.zoom"))
    big(pfont, "assets.zoom_in", "zoom_in", lambda: window.reader.backend.set_zoom(1))
    big(pfont, "assets.zoom_out", "zoom_out", lambda: window.reader.backend.set_zoom(-1))

    ps = panel(read, "panel.search")
    window.edt_find = ps.addLineEdit()
    window.edt_find.setPlaceholderText(T("label.search"))
    window.edt_find.returnPressed.connect(window.on_find_run)
    big(ps, "action.find_next", "find", window.on_find_next)

    pcp = panel(read, "panel.compare")
    window.btn_parallel = pcp.addLargeToggleButton(
        T("action.compare"), icon=icon("parallel"))
    window.btn_parallel.toggled.connect(window.on_parallel_toggled)

    pnt = panel(read, "panel.notes")
    big(pnt, "action.add_note", "note", window.on_add_note)
    big(pnt, "action.bookmarks", "bookmark", window.on_bookmarks)

    po = panel(read, "panel.output")
    big(po, "action.print_pdf", "print", window.on_print_pdf)

    # ===================================================================
    #  Assets
    # ===================================================================
    assets = category("tab.assets")
    psa = panel(assets, "panel.source")
    psa.addLabel(T("label.edition"))
    window.cmb_assets_edition = psa.addComboBox(
        [T("edition.original"), T("edition.translated")])
    window.cmb_assets_edition.currentIndexChanged.connect(
        window._on_assets_edition_changed)
    big(psa, "action.refresh", "refresh", window.on_assets_reload)

    pimg = panel(assets, "panel.figures")
    big(pimg, "action.load", "assets", window._load_figures)
    big(pimg, "action.export_assets", "export", lambda: window.figures._export("img"))
    big(pimg, "assets.save_back", "save", lambda: window.figures.save_back())

    ptxt = panel(assets, "assets.texts")
    big(ptxt, "action.load", "preview", window._load_texts)
    big(ptxt, "assets.save_back", "save", lambda: window.texts.save_back())

    ptab = panel(assets, "panel.tables")
    big(ptab, "action.load", "format", window._load_tables)
    big(ptab, "assets.save_back", "save", lambda: window.tables.save_back())

    # ===================================================================
    #  Translate
    # ===================================================================
    tr = category("tab.translate")
    pbook = panel(tr, "panel.book")
    window.btn_translate = big(pbook, "action.translate_book", "translate",
                               window.on_translate_book, "Ctrl+Return")
    window.btn_translate_chapters = big(
        pbook, "action.translate_chapters", "chapters", window.on_translate_chapters)
    window.btn_cancel = big(pbook, "action.cancel", "cancel", window.on_cancel)
    window.btn_cancel.setEnabled(False)

    pch = panel(tr, "panel.views")
    big(pch, "action.extract_chapters", "chapters", window.on_extract_chapters)

    peng = panel(tr, "panel.engine")
    peng.addLabel(T("panel.engine"))
    window.cmb_engine = peng.addComboBox(window._engine_names())
    window.cmb_engine.currentTextChanged.connect(window._on_engine_changed)
    peng.addLabel(T("label.api_key"))
    window.edt_api_key = peng.addLineEdit()
    from PyQt6.QtWidgets import QLineEdit
    window.edt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
    peng.addLabel(T("label.model"))
    window.cmb_model = peng.addComboBox([])
    window.cmb_model.setEditable(True)

    plang = panel(tr, "panel.languages")
    plang.addLabel(T("label.source"))
    window.cmb_source = plang.addComboBox(
        ["Auto detect"] + list(window._google_languages()))
    plang.addLabel(T("label.target"))
    window.cmb_target = plang.addComboBox(list(window._google_languages()))
    big(plang, "action.swap", "swap", window.on_swap_languages)

    popt = panel(tr, "panel.options")
    window.chk_bilingual = popt.addCheckBox(T("label.bilingual"))
    window.chk_cache = popt.addCheckBox(T("label.cache"))
    window.chk_cache.setChecked(True)
    window.chk_batch = popt.addCheckBox(T("label.batch"))

    pprev = panel(tr, "panel.preview")
    big(pprev, "tab.preview", "preview",
        lambda: window.tabs.setCurrentWidget(window.preview))

    # ===================================================================
    #  Quality
    # ===================================================================
    qual = category("tab.quality")
    pev = panel(qual, "panel.evaluation")
    big(pev, "action.evaluate", "check", lambda: window.on_quality(False))
    big(pev, "action.evaluate_ai", "quality", lambda: window.on_quality(True))
    pev.addLabel(T("label.samples"))
    window.spn_samples = pev.addSpinBox()
    window.spn_samples.setRange(1, 100)
    window.spn_samples.setValue(10)

    pre = panel(qual, "panel.report")
    big(pre, "action.report_save", "save", window.on_report_save)
    big(pre, "action.report_open", "report", window.on_report_open)

    pres = panel(qual, "panel.result")
    pres.addLabel(T("label.threshold"))
    window.spn_threshold = pres.addSpinBox()
    window.spn_threshold.setRange(0, 100)
    window.spn_threshold.setValue(60)

    # ===================================================================
    #  Export
    # ===================================================================
    exp = category("tab.export")
    pcon = panel(exp, "panel.content")
    pcon.addLabel(T("label.edition"))
    window.cmb_export_edition = pcon.addComboBox(
        [T("edition.original"), T("edition.translated")])
    window.edt_export_chapters = pcon.addLineEdit()
    window.edt_export_chapters.setPlaceholderText(T("label.chapters_filter"))

    pfmt = panel(exp, "panel.format_grp")
    window.cmb_export_format = pfmt.addComboBox([])
    big(pfmt, "action.export", "export", window.on_export_quick)

    pdes = panel(exp, "panel.destination")
    big(pdes, "action.export", "package", window.on_export)
    big(pdes, "action.export_assets", "assets", window.on_export_assets)

    # ===================================================================
    #  Tools
    # ===================================================================
    tools = category("tab.tools")
    psp = panel(tools, "panel.split")
    big(psp, "action.split", "split", window.on_split)
    pmg = panel(tools, "panel.merge")
    big(pmg, "action.merge", "merge", window.on_merge)
    pmt = panel(tools, "panel.maintenance")
    big(pmt, "action.clear_cache", "cache", window.on_clear_cache)
    big(pmt, "action.data_dir", "file_folder", window.on_data_dir)

    # ===================================================================
    #  Info
    # ===================================================================
    info = category("tab.info")
    ph = panel(info, "panel.help")
    big(ph, "action.help", "help", window.on_help, "F1")
    big(ph, "action.open_online_help", "language", window.on_online_help)
    pinf = panel(info, "panel.information")
    big(pinf, "action.about", "info", window.on_about)
    small(pinf, "action.license", "license", window.on_license)
    small(pinf, "action.upstream", "upstream", window.on_upstream)
    pd = panel(info, "panel.diagnostics")
    small(pd, "action.engine_version", "engine", window.on_engine_version)
    small(pd, "action.data_dir", "file_folder", window.on_config_dir)
