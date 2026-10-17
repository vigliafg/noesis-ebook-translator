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
                                 "engine_preferences": {}})

    def _dialog(self, runner=_ok_runner):
        from noesis_ebook_translator.ui import SettingsDialog
        return SettingsDialog(model_test_runner=runner,
                              models_fetcher=_fake_fetch,
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


@unittest.skipUnless(_HAS_GUI, "PyQt6 not installed")
class TestOnboardingProviders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from noesis_ebook_translator import appconfig
        appconfig.save_settings({"provider_slots": [], "model_cache": {},
                                 "engine_preferences": {},
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


if __name__ == "__main__":
    unittest.main()
