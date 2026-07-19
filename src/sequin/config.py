"""A small persistent settings store for Sequin (and anything embedding it).

Stored as JSON under the user's app-data directory so preferences survive restarts.  This
is deliberately generic — a flat key/value store plus load/save — so it carries no
knowledge of any particular app's views; FreedomHawk layers its own tab-order logic on top
(see ``firehawk.config``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _config_dir(app_name: str = "Sequin") -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / app_name


class AppSettings:
    """A flat, JSON-backed key/value store.  ``app_name`` selects the app-data folder
    (``%APPDATA%/<app_name>/settings.json``); pass ``path`` to override the file directly
    (used by tests and by hosts that keep their own settings file)."""

    def __init__(self, app_name: str = "Sequin", path=None) -> None:
        self._file = Path(path) if path is not None else _config_dir(app_name) / "settings.json"
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            self.data = json.loads(Path(self._file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        try:
            Path(self._file).parent.mkdir(parents=True, exist_ok=True)
            Path(self._file).write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()
