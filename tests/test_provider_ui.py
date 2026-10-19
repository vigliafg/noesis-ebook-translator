"""Provider UI: Settings "Providers" page + onboarding, fully offline.

Both the model probe and the model fetch are injected, and the tests run the
probe synchronously so nothing touches the network or a worker thread.
"""
import unittest

try:
    from PyQt6.QtWidgets import QApplication
    _HAS_GUI = True
except Exception:  # noqa: BLE001 - optional dependency
    _HAS_GUI = False


def _ok_runner(provider_id, api_key, model):
    from noesis_ebook_translator import provider_catalog
    return provider_catalog.TestResult(ok=True, latency_ms=1200, sample="Ciao")


def _fail_runner(provider_id, api_key, model):
    from noesis_ebook_translator import provider_catalog
    return provider_catalog.TestResult(ok=False, error_kind="auth",
                                       message="HTTP 401")


def _fake_fetch(provider_id, api_key):
    return ["model-a", "model-b"]


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestSettingsProviders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from noesis_ebook_translator import appconfig
        appconfig.save_settings({"provider_slots": [], "model_cache": {},
                                 "engine_preferences": {}, "model_tests": {}})

    def _dialog(self, runner=_ok_runner, fetcher=_fake_fetch):
        from noesis_ebook_translator.ui import SettingsDialog
        return SettingsDialog(model_test_runner=runner,
                              models_fetcher=fetcher,
                              synchronous_tests=True)

    def test_providers_tab_and_four_rows(self):
        dialog = self._dialog()
        try:
            titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
            from noesis_ebook_translator.i18n import T
            self.assertIn(T("settings.tab.providers").replace("&", "&&"), titles)
            self.assertEqual(len(dialog._slot_rows), 4)
            self.assertEqual(len(dialog.values()["provider_slots"]), 4)
        finally:
            dialog.close()

    def test_selecting_provider_runs_the_model_test(self):
        dialog = self._dialog()
        try:
            row = dialog._slot_rows[0]
            row.set_values({"enabled": True, "provider": "groq",
                            "api_key": "sk-x", "model": "model-a",
                            "endpoint": ""})
            row.test.run_now()
            self.assertIn("OK", row.test.status.text())
        finally:
            dialog.close()

    def test_failed_test_is_reported_inline(self):
        dialog = self._dialog(runner=_fail_runner)
        try:
            row = dialog._slot_rows[0]
            row.set_values({"enabled": True, "provider": "groq",
                            "api_key": "bad", "model": "model-a",
                            "endpoint": ""})
            row.test.run_now()
            from noesis_ebook_translator.i18n import T
            self.assertIn(T("provider.err.auth"), row.test.status.text())
        finally:
            dialog.close()

    def test_apply_persists_slots_and_mirrors_preferences(self):
        from noesis_ebook_translator import appconfig
        dialog = self._dialog()
        try:
            dialog._slot_rows[0].set_values(
                {"enabled": True, "provider": "groq", "api_key": "k1",
                 "model": "llama-3.3-70b-versatile", "endpoint": ""})
            dialog._slot_rows[1].set_values(
                {"enabled": True, "provider": "custom", "api_key": "",
                 "model": "qwen", "endpoint": "http://localhost:11434/v1"})
            dialog.apply()
        finally:
            dialog.close()

        slots = appconfig.provider_slots()
        self.assertTrue(slots[0]["enabled"])
        self.assertEqual(slots[0]["provider"], "groq")
        self.assertEqual(slots[1]["endpoint"], "http://localhost:11434/v1")
        self.assertIn("Groq", appconfig.engine_names())
        self.assertEqual(appconfig.get_engine_preference("Groq")["api_keys"],
                         ["k1"])

    def test_model_list_from_snapshot(self):
        dialog = self._dialog()
        try:
            row = dialog._slot_rows[0]
            row.set_values({"enabled": True, "provider": "mistral",
                            "api_key": "k", "model": "", "endpoint": ""})
            row._reload_models("mistral")
            # The bundled snapshot is present for mistral.
            self.assertGreater(row.cmb_model.count(), 0)
        finally:
            dialog.close()

    def test_stale_model_list_is_refreshed_automatically(self):
        dialog = self._dialog()
        try:
            row = dialog._slot_rows[0]
            row.set_values({"enabled": True, "provider": "groq",
                            "api_key": "k", "model": "", "endpoint": ""})
            row._auto_refresh()
            items = [row.cmb_model.itemText(i)
                     for i in range(row.cmb_model.count())]
            self.assertEqual(items, ["model-a", "model-b"])
        finally:
            dialog.close()

    def test_refresh_all_lists(self):
        calls = []

        def fetcher(provider_id, key):
            calls.append(provider_id)
            return ["m1", "m2"]

        dialog = self._dialog(fetcher=fetcher)
        try:
            dialog._slot_rows[0].set_values({
                "enabled": True, "provider": "groq", "api_key": "k",
                "model": "", "endpoint": ""})
            dialog._slot_rows[1].set_values({
                "enabled": True, "provider": "mistral", "api_key": "k",
                "model": "", "endpoint": ""})
            dialog._refresh_all_models()
            self.assertEqual(sorted(calls), ["groq", "mistral"])
            row = dialog._slot_rows[0]
            self.assertEqual([row.cmb_model.itemText(i)
                              for i in range(row.cmb_model.count())],
                             ["m1", "m2"])
        finally:
            dialog.close()

    def test_refresh_all_skips_providers_without_a_key(self):
        calls = []

        def fetcher(provider_id, key):
            calls.append(provider_id)
            return ["m1"]

        dialog = self._dialog(fetcher=fetcher)
        try:
            dialog._slot_rows[0].set_values({
                "enabled": True, "provider": "groq", "api_key": "",
                "model": "", "endpoint": ""})
            dialog._refresh_all_models()
            self.assertEqual(calls, [])
        finally:
            dialog.close()

    def test_fresh_cache_is_not_refetched(self):
        from noesis_ebook_translator import appconfig
        appconfig.save_provider_models("groq", ["cached-model"])
        calls = []

        def fetcher(provider_id, key):
            calls.append(provider_id)
            return ["other"]

        dialog = self._dialog(fetcher=fetcher)
        try:
            row = dialog._slot_rows[0]
            row.set_values({"enabled": True, "provider": "groq",
                            "api_key": "k", "model": "cached-model",
                            "endpoint": ""})
            row._auto_refresh()
            self.assertEqual(calls, [])
            self.assertEqual(row.cmb_model.currentText(), "cached-model")
        finally:
            dialog.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestOnboardingProviders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from noesis_ebook_translator import appconfig
        appconfig.save_settings({"provider_slots": [], "model_cache": {},
                                 "engine_preferences": {},
                                 "model_tests": {},
                                 "onboarding_done": False})

    def test_onboarding_saves_slot_one(self):
        from noesis_ebook_translator import appconfig
        from noesis_ebook_translator.ui import OnboardingWizard
        wizard = OnboardingWizard(model_test_runner=_ok_runner,
                                  synchronous_tests=True)
        try:
            index = wizard.cmb_provider.findData("groq")
            self.assertGreaterEqual(index, 0)
            wizard.cmb_provider.setCurrentIndex(index)
            wizard.edt_api_key.setText("sk-onboarding")
            wizard.edt_model.setCurrentText("llama-3.3-70b-versatile")
            wizard._schedule_test()
            wizard.test_provider.run_now()
            self.assertIn("OK", wizard.test_provider.status.text())
            values = wizard.apply()
        finally:
            wizard.close()

        self.assertTrue(values["onboarding_done"])
        slots = appconfig.provider_slots()
        self.assertTrue(slots[0]["enabled"])
        self.assertEqual(slots[0]["provider"], "groq")
        self.assertEqual(slots[0]["api_key"], "sk-onboarding")
        self.assertEqual(appconfig.load_settings().get("translate_engine"),
                         "Groq")

    def test_opencode_go_note_is_shown(self):
        from noesis_ebook_translator.ui import OnboardingWizard
        wizard = OnboardingWizard(model_test_runner=_ok_runner,
                                  synchronous_tests=True)
        try:
            index = wizard.cmb_provider.findData("opencode-go")
            wizard.cmb_provider.setCurrentIndex(index)
            self.assertFalse(wizard.lbl_provider_note.isHidden())
            self.assertTrue(wizard.lbl_provider_note.text())
        finally:
            wizard.close()

    def test_onboarding_refreshes_the_model_list(self):
        from noesis_ebook_translator.ui import OnboardingWizard
        calls = []

        def fetcher(provider_id, key):
            calls.append((provider_id, key))
            return ["fresh-1", "fresh-2"]

        wizard = OnboardingWizard(model_test_runner=_ok_runner,
                                  models_fetcher=fetcher,
                                  synchronous_tests=True)
        try:
            index = wizard.cmb_provider.findData("groq")
            wizard.cmb_provider.setCurrentIndex(index)
            wizard.edt_api_key.setText("sk")
            wizard._refresh_models()
            items = [wizard.edt_model.itemText(i)
                     for i in range(wizard.edt_model.count())]
            self.assertEqual(items, ["fresh-1", "fresh-2"])
            self.assertEqual(calls, [("groq", "sk")])
        finally:
            wizard.close()

    def test_onboarding_refresh_is_disabled_for_custom(self):
        from noesis_ebook_translator.ui import OnboardingWizard
        wizard = OnboardingWizard(model_test_runner=_ok_runner,
                                  models_fetcher=_fake_fetch,
                                  synchronous_tests=True)
        try:
            index = wizard.cmb_provider.findData("custom")
            wizard.cmb_provider.setCurrentIndex(index)
            self.assertFalse(wizard.btn_refresh_models.isEnabled())
        finally:
            wizard.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestProbePersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from noesis_ebook_translator import appconfig
        appconfig.save_settings({"provider_slots": [], "model_cache": {},
                                 "engine_preferences": {}, "model_tests": {}})

    def test_settings_probe_is_persisted(self):
        from noesis_ebook_translator import appconfig
        from noesis_ebook_translator.ui import SettingsDialog
        dialog = SettingsDialog(model_test_runner=_ok_runner,
                                models_fetcher=_fake_fetch,
                                synchronous_tests=True)
        try:
            row = dialog._slot_rows[0]
            row.set_values({"enabled": True, "provider": "groq",
                            "api_key": "k", "model": "model-a",
                            "endpoint": ""})
            row.test.run_now()
        finally:
            dialog.close()
        self.assertTrue(appconfig.model_test_status("Groq", "model-a").get("ok"))

    def test_translate_wizard_probes_and_persists(self):
        from noesis_ebook_translator import appconfig
        from noesis_ebook_translator.ui import TranslateWizard
        appconfig.set_provider_slots([{"enabled": True, "provider": "groq",
                                       "api_key": "sk",
                                       "model": "llama-3.3-70b-versatile"}])
        wizard = TranslateWizard(None, mode="book", engine="Groq",
                                 model_test_runner=_ok_runner,
                                 synchronous_tests=True)
        try:
            self.assertFalse(wizard.test_model.isVisible())
            wizard._shown = True
            wizard._schedule_model_test()
            wizard.test_model.run_now()
            self.assertIn("OK", wizard.test_model.status.text())
        finally:
            wizard.close()
        status = appconfig.model_test_status("Groq",
                                             "llama-3.3-70b-versatile")
        self.assertTrue(status.get("ok"))

    def test_translate_wizard_skips_free_engines(self):
        from noesis_ebook_translator.ui import TranslateWizard
        wizard = TranslateWizard(None, mode="book", engine="Google(Free)New",
                                 model_test_runner=_ok_runner,
                                 synchronous_tests=True)
        try:
            wizard._shown = True
            wizard._schedule_model_test()
            self.assertTrue(wizard.test_model.isHidden())
            self.assertEqual(wizard.test_model.last_pending()[0], "")
        finally:
            wizard.close()


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestRibbonBadge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from noesis_ebook_translator import appconfig
        appconfig.ensure_defaults()
        appconfig.save_settings({"model_tests": {}, "engine_preferences": {}})
        # The engine combo only offers configured LLMs: give ChatGPT a key so the
        # badge tests can select it.
        appconfig.set_engine_preference("ChatGPT", api_keys=["sk-test"])

    def test_ok_badge(self):
        from noesis_ebook_translator import appconfig
        import main
        appconfig.save_model_test("ChatGPT", ok=True, model="gpt-4o")
        window = main.MainWindow()
        try:
            window.cmb_engine.setCurrentText("ChatGPT")
            window.cmb_model.setCurrentText("gpt-4o")
            window._update_model_badge()
            self.assertEqual(window.lbl_model_test.text(), "\u2713")
            self.assertFalse(window.lbl_model_test.isHidden())
        finally:
            window.close()

    def test_failed_badge_and_unknown_model(self):
        from noesis_ebook_translator import appconfig
        import main
        appconfig.save_model_test("ChatGPT", ok=False, model="gpt-4o",
                                  error="HTTP 401")
        window = main.MainWindow()
        try:
            window.cmb_engine.setCurrentText("ChatGPT")
            window.cmb_model.setCurrentText("gpt-4o")
            window._update_model_badge()
            self.assertEqual(window.lbl_model_test.text(), "\u2717")
            window.cmb_model.setCurrentText("another-model")
            window._update_model_badge()
            self.assertTrue(window.lbl_model_test.isHidden())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()