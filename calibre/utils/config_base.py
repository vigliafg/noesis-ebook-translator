"""Subset of :mod:`calibre.utils.config_base` used by the engine."""
from __future__ import annotations

import os

from ..constants import config_dir

#: Directory Calibre reserves for the plugin's private data. Here it maps to the
#: application's own config directory.
plugin_dir = config_dir

os.makedirs(plugin_dir, exist_ok=True)
