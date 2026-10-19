"""The two new wizard pages: text analysis and cost/duration estimate (offscreen).

Everything runs offline: the analysis runner is injected and the price table is
patched, so the assertions are deterministic.
"""
import json
import os
import tempfile
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001 - optional dependency
    _HAS_GUI = False

from tests.fixtures import build_rich_epub, register_fake_engine

_REPLY = json.dumps({
    "category": "fiction", "genre": "novel", "subgenre": "gothic",
    "register": "formal", "tone": "dark", "audience": "adults",
    "guidance": ["keep the names"], "confidence": 0.8})


def _runner_factory(*_args, **_kwargs):
    return lambda prompt: _REPLY


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class WizardPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.engine = register_fake_engine()

    def setUp(self):
        from noesis_ebook_translator import appconfig, estimate, provider_catalog

        self.appconfig = appconfig
        self.estimate = estimate
        self.provider_catalog = provider_catalog
        appconfig.ensure_defaults()
        # ``Fake`` is an LLM (it has a prompt) and would not be offered by the
        # wizard until it has credentials in ``engine_preferences``.
        appconfig.set_engine_preference("Fake", api_keys=["fake-key"])
        self._price = provider_catalog.price
        self._dev_map = dict(estimate.ENGINE_TO_MODELS_DEV)
        self.tmp = tempfile.mkdtemp(prefix="wizard-estimate-")
        self.src = build_rich_epub(os.path.join(self.tmp, "book.epub"))
        self._window = None

    def tearDown(self):
        self.provider_catalog.price = self._price
        self.estimate.ENGINE_TO_MODELS_DEV.clear()
        self.estimate.ENGINE_TO_MODELS_DEV.update(self._dev_map)
        if self._window is not None:
            self._window.close()
        self.app.processEvents()

    def _wizard(self, engine="Fake", **kwargs):
        from noesis_ebook_translator.ui import TranslateWizard

        wizard = TranslateWizard(None, mode="book", input_path=self.src,
                                 engine=engine, synchronous_tests=True,
                                 analysis_runner=_runner_factory, **kwargs)
        return wizard

    def _main_window(self):
        import main

        window = main.MainWindow()
        window._apply_source(self.src)
        self._window = window
        return window

    # -----------------------------------------------------------------
    def test_pages_order_and_analysis_result(self):
        wizard = self._wizard()
        try:
            self.assertEqual(wizard.pageIds(),
                             [wizard._content_id, wizard._engine_id,
                              wizard._analysis_id, wizard._estimate_id,
                              wizard._options_id, wizard._output_id])
            wizard.analysis_page.initializePage()
            self.assertIn("novel", wizard.analysis_page.status.text())
            prompt = wizard.analysis_page.style_prompt()
            self.assertIn("gothic", prompt)
            self.assertIn("keep the names", prompt)
            self.assertIn("Never summarise", prompt)      # integrity preserved
            self.assertEqual(wizard.config()["genre"], "novel — gothic")
            self.assertTrue(wizard.config()["style_prompt"])
        finally:
            wizard.close()

    def test_analysis_failure_falls_back_without_blocking(self):
        def factory(*_args, **_kwargs):
            def runner(prompt):
                raise RuntimeError("offline")
            return runner

        from noesis_ebook_translator.ui import TranslateWizard

        wizard = TranslateWizard(None, mode="book", input_path=self.src,
                                 engine="Fake", synchronous_tests=True,
                                 analysis_runner=factory)
        try:
            wizard.analysis_page.initializePage()
            self.assertIn("offline", wizard.analysis_page.status.text())
            self.assertIn("Never summarise",
                          wizard.analysis_page.style_prompt())
        finally:
            wizard.close()

    def test_skip_disables_the_style_prompt(self):
        wizard = self._wizard()
        try:
            wizard.analysis_page.initializePage()
            wizard.analysis_page._skip()
            self.assertEqual(wizard.analysis_page.style_prompt(), "")
            self.assertEqual(wizard.config()["style_prompt"], "")
        finally:
            wizard.close()

    def test_non_llm_engine_skips_the_analysis_page(self):
        wizard = self._wizard(engine="DeepL")
        try:
            wizard.analysis_page.initializePage()
            self.assertFalse(wizard.analysis_page.editor.isEnabled())
            self.assertIn("system prompt", wizard.analysis_page.status.text())
            wizard.currentId = lambda: wizard._analysis_id
            self.assertEqual(wizard.nextId(), wizard._estimate_id)
        finally:
            wizard.close()

    def test_estimate_page_renders_tokens_cost_and_chapters(self):
        self.estimate.ENGINE_TO_MODELS_DEV["Fake"] = "groq"
        self.provider_catalog.price = lambda provider, model: (2.0, 4.0)
        wizard = self._wizard()
        try:
            wizard.analysis_page.initializePage()
            wizard.estimate_page.initializePage()
            est = wizard.estimate_page.estimate()
            self.assertIsNotNone(est)
            self.assertGreater(est.segments, 0)
            self.assertGreater(est.cost_usd, 0)
            self.assertNotEqual(wizard.estimate_page.lbl_cost.text(), "")
            self.assertIn("$", wizard.estimate_page.lbl_cost.text())
            self.assertEqual(wizard.estimate_page.table.rowCount(),
                             len(est.per_chapter))
            self.assertIn("tiktoken", wizard.estimate_page.note.text())
        finally:
            wizard.close()

    def test_parallel_spinbox_feeds_the_config(self):
        wizard = self._wizard()
        try:
            # Up to the engine's executor ceiling.
            self.assertEqual(wizard.spn_parallel.maximum(), 32)
            wizard.chk_sequential.setChecked(False)
            self.assertTrue(wizard.spn_parallel.isEnabled())
            wizard.spn_parallel.setValue(6)
            self.assertEqual(wizard.config()["concurrency"], 6)
            wizard.chk_sequential.setChecked(True)
            self.assertFalse(wizard.spn_parallel.isEnabled())
            self.assertEqual(wizard.config()["concurrency"], 1)
        finally:
            wizard.close()

    def test_start_translation_passes_style_and_concurrency(self):
        window = self._main_window()
        cfg = {
            "engine": "Fake", "source": "English", "target": "Italian",
            "model": "model-x", "sequential": False, "concurrency": 5,
            "style_prompt": "STYLE-ADDENDUM", "genre": "novel",
            "output_confirmed": True,
        }
        window._start_translation(cfg)
        self.assertIsNotNone(window.worker)
        self.assertEqual(window.worker.style_prompt, "STYLE-ADDENDUM")
        self.assertEqual(window.worker.genre, "novel")
        preference = self.appconfig.get_engine_preference("Fake")
        self.assertEqual(preference.get("concurrency_limit"), 5)
        worker = window.worker
        worker.wait(20000)
        self.app.processEvents()

    def test_resume_passes_the_stored_style(self):
        window = self._main_window()
        captured = []
        window._start_translation = captured.append
        window._resume_run({
            "engine": "Fake", "model": "model-x", "source_lang": "English",
            "target_lang": "Italian", "chapters": "1",
            "output_path": os.path.join(self.tmp, "book-italian.epub"),
            "style_prompt": "STORED-STYLE", "genre": "poetry",
            "options": {"translation_position": "only", "cache_enabled": True,
                        "online_batching": False, "sequential": False,
                        "concurrency": 3},
        })
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["style_prompt"], "STORED-STYLE")
        self.assertEqual(captured[0]["genre"], "poetry")
        self.assertEqual(captured[0]["concurrency"], 3)


if __name__ == "__main__":
    unittest.main()
