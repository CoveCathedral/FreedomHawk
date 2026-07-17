"""Persistent app settings (currently the tab order and dark-mode preference).

Stored as JSON under the user's app-data directory so preferences survive restarts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import SLOT_LAYOUT


def _config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "FreedomHawk"


CONFIG_FILE = _config_dir() / "settings.json"


def all_views() -> list[tuple[str, str]]:
    """Every navigable view as (view_id, display_name), in canonical order."""
    views = [("presets", "Presets"), ("tuner", "Tuner"), ("metronome", "Metronome")]
    views += [(s.id, s.display_name) for s in SLOT_LAYOUT]
    return views


#: Default order: Presets, the signal-chain blocks, then the practice tools last.
DEFAULT_PAGE_ORDER = ["presets"] + [s.id for s in SLOT_LAYOUT] + ["tuner", "metronome"]


class AppSettings:
    def __init__(self) -> None:
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            self.data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def page_order(self) -> list[str]:
        """The saved tab order, filtered to valid views and completed with any new ones."""
        valid = {vid for vid, _ in all_views()}
        order = [v for v in self.data.get("page_order", []) if v in valid]
        for v in DEFAULT_PAGE_ORDER:  # append views not yet in the saved order
            if v not in order:
                order.append(v)
        return order

    def set_page_order(self, order: list[str]) -> None:
        self.data["page_order"] = list(order)
        self.save()

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()
