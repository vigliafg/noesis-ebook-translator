"""Stand-in for :class:`calibre.utils.config.JSONConfig`.

A thin :class:`dict` subclass that transparently persists to a JSON file inside
:data:`calibre.constants.config_dir`. Only the operations the engine relies on
are implemented (``defaults``, ``refresh``, ``commit``).
"""
from __future__ import annotations

import json
import os
from typing import Any

from ..constants import config_dir


class JSONConfig(dict):
    def __init__(self, rel_path: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.rel_path = rel_path
        self.file_path = os.path.join(config_dir, *rel_path.split("/")) + ".json"
        self.defaults: dict[str, Any] = {}
        self.load()

    # -- persistence ------------------------------------------------------
    def load(self) -> None:
        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    self.clear()
                    self.update(data)
        except (OSError, ValueError):
            pass

    def refresh(self) -> None:
        self.load()

    def commit(self) -> None:
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as handle:
            json.dump(dict(self), handle, indent=2, ensure_ascii=False)
