"""Preset library: the factory preset(s) shipped with the app plus the user's own
saved presets on disk.

This is the offline equivalent of the old cloud "my tones": user presets live as JSON
files in a folder under the user's Documents, and the app can list, open, save, and
delete them.  Presets recalled from the connected pedal will slot in here later as a
third source.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .catalog import ModelCatalog, SLOT_LAYOUT
from .preset import Preset

DEFAULT_USER_DIR = Path.home() / "Documents" / "Firehawk Presets"

# Factory presets bundled with the app data.
_FACTORY_FILES = ("default_preset.json",)


@dataclass
class PresetEntry:
    """One selectable preset in the library."""

    name: str
    source: str           # 'factory' | 'user' | 'device'
    preset: Preset
    path: Path | None = None

    @property
    def deletable(self) -> bool:
        return self.source == "user" and self.path is not None

    @property
    def display(self) -> str:
        tag = {"factory": "Factory", "user": "User", "device": "Device"}.get(self.source, "")
        return f"{self.name}  ({tag})" if tag else self.name


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "preset"
    return cleaned[:120]


class PresetLibrary:
    def __init__(self, data_dir: Path | str, user_dir: Path | str | None = None):
        self.data_dir = Path(data_dir)
        self.user_dir = Path(user_dir) if user_dir else DEFAULT_USER_DIR

    def ensure_user_dir(self) -> None:
        self.user_dir.mkdir(parents=True, exist_ok=True)

    # -- listing --------------------------------------------------------------

    def factory_presets(self) -> list[PresetEntry]:
        entries: list[PresetEntry] = []
        for filename in _FACTORY_FILES:
            path = self.data_dir / filename
            if not path.exists():
                continue
            preset = Preset.from_json(json.loads(path.read_text(encoding="utf-8")))
            entries.append(PresetEntry(preset.meta.get("name") or path.stem, "factory", preset))
        return entries

    def user_presets(self) -> list[PresetEntry]:
        self.ensure_user_dir()
        entries: list[PresetEntry] = []
        for path in sorted(self.user_dir.glob("*.json")):
            try:
                preset = Preset.from_json(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, KeyError, OSError):
                continue  # skip anything that isn't a readable preset
            entries.append(PresetEntry(preset.meta.get("name") or path.stem, "user", preset, path))
        return entries

    def all_presets(self) -> list[PresetEntry]:
        return self.factory_presets() + self.user_presets()

    # -- mutation -------------------------------------------------------------

    def save(self, preset: Preset, name: str) -> Path:
        self.ensure_user_dir()
        preset = preset.copy()
        preset.meta["name"] = name
        path = self.user_dir / f"{_safe_filename(name)}.json"
        path.write_text(json.dumps(preset.to_json(), indent=2), encoding="utf-8")
        return path

    def delete(self, entry: PresetEntry) -> None:
        if not entry.deletable or entry.path is None:
            raise ValueError("only user presets can be deleted")
        entry.path.unlink(missing_ok=True)


def summarize_preset(preset: Preset, catalog: ModelCatalog) -> str:
    """A readable, screen-reader-friendly overview of a preset's whole signal chain."""
    lines: list[str] = [f"Name: {preset.meta.get('name', '(unnamed)')}"]
    author = preset.meta.get("author")
    if author:
        lines.append(f"Author: {author}")
    style = preset.meta.get("style")
    if style:
        lines.append(f"Style: {style}")
    global_block = preset.blocks.get("global")
    if global_block and "@tempo" in global_block.values:
        try:
            lines.append(f"Tempo: {float(global_block.values['@tempo']):.1f} BPM")
        except (TypeError, ValueError):
            pass
    lines.append("")
    lines.append("Signal chain:")
    for slot in SLOT_LAYOUT:
        if slot.id == "global":
            continue
        block = preset.blocks.get(slot.id)
        if block is None:
            continue
        model = catalog.model(block.model_id) if block.model_id else None
        model_name = model.display_name if model else (block.model_id or "-")
        state = "" if block.enabled else "  (bypassed)"
        lines.append(f"  {slot.display_name}: {model_name}{state}")
    return "\n".join(lines)
