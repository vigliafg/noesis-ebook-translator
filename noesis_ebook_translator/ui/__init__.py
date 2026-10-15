"""Desktop GUI widgets and dialogs (PyQt6).

This package keeps the Qt-only code out of the headless core and out of the
monolithic ``main.py``: theme application, the onboarding wizard, the settings /
help / export dialogs, the animations and the extra panels live here.
"""
from __future__ import annotations

__all__ = [
    "apply_theme", "SettingsDialog", "OnboardingWizard", "HelpDialog",
    "ExportDialog",
]

from .theme_manager import apply_theme  # noqa: F401


def __getattr__(name):  # PEP 562 lazy attributes (keep imports cheap, no cycles)
    if name == "SettingsDialog":
        from .settings_dialog import SettingsDialog
        return SettingsDialog
    if name == "OnboardingWizard":
        from .wizard import OnboardingWizard
        return OnboardingWizard
    if name == "HelpDialog":
        from .help_dialog import HelpDialog
        return HelpDialog
    if name == "ExportDialog":
        from .export_dialog import ExportDialog
        return ExportDialog
    raise AttributeError(name)
