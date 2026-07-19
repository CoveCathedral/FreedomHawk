"""FreedomHawk's persistent settings — Sequin's key/value store plus this app's tab order.

The generic store lives in ``sequin.config``; here we add the FreedomHawk-specific view
list (pedal blocks + practice tools) and the saved page order on top of it.
"""

from __future__ import annotations

from sequin.config import AppSettings as _BaseSettings
from sequin.config import _config_dir

from .model import SLOT_LAYOUT

#: The settings file FreedomHawk uses (its own app-data folder).  Kept as a module global
#: so tests can point it at a temp file before constructing the app.
CONFIG_FILE = _config_dir("FreedomHawk") / "settings.json"


def all_views() -> list[tuple[str, str]]:
    """Every navigable view as (view_id, display_name), in canonical order."""
    # "drums" is the stable view id; the display name is the product name, Sequin.
    views = [("presets", "Presets"), ("tuner", "Tuner"), ("metronome", "Metronome"),
             ("drums", "Sequin")]
    views += [(s.id, s.display_name) for s in SLOT_LAYOUT]
    return views


#: Default order: Presets, the signal-chain blocks, then the practice tools last.
DEFAULT_PAGE_ORDER = ["presets"] + [s.id for s in SLOT_LAYOUT] + ["tuner", "metronome", "drums"]


class AppSettings(_BaseSettings):
    """Sequin's settings store plus FreedomHawk's tab-order logic."""

    def __init__(self) -> None:
        super().__init__(path=CONFIG_FILE)

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
