"""The editable preset / edit-buffer state model.

A :class:`Preset` mirrors ``default_preset.json``: metadata plus a ``tone`` made
of per-slot :class:`Block` objects.  :class:`EditBuffer` is the live, validated
working copy the UI edits; every write is clamped against the current model's
parameter spec, and observers are notified so the (future) protocol layer can
turn a write into an on-wire message.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .catalog import DATA_DIR, ModelCatalog, SLOT_LAYOUT, SLOTS_BY_ID
from .valuetypes import ModelSpec, ParamSpec

ChangeListener = Callable[[str, str, Any], None]  # (slot_id, param_id, value)


@dataclass
class Block:
    """The state of one signal-chain slot: its model and all parameter values."""

    slot_id: str
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def model_id(self) -> str | None:
        return self.values.get("@model")

    @property
    def enabled(self) -> bool:
        # Blocks without an @enabled attribute (amp, cab, global) are always on.
        return bool(self.values.get("@enabled", True))

    def get(self, param_id: str, default: Any = None) -> Any:
        return self.values.get(param_id, default)

    def copy(self) -> "Block":
        return Block(self.slot_id, copy.deepcopy(self.values))


@dataclass
class Preset:
    """A complete preset: metadata plus a tone of per-slot blocks."""

    meta: dict[str, Any] = field(default_factory=dict)
    blocks: dict[str, Block] = field(default_factory=dict)
    device: int | None = None
    device_version: int | None = None
    schema: str = "L6Preset"
    version: int = 5

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Preset":
        data = raw["data"]
        tone = data.get("tone", {})
        blocks = {slot: Block(slot, dict(values)) for slot, values in tone.items()}
        return cls(
            meta=dict(data.get("meta", {})),
            blocks=blocks,
            device=data.get("device"),
            device_version=data.get("device_version"),
            schema=raw.get("schema", "L6Preset"),
            version=raw.get("version", 5),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "data": {
                "device": self.device,
                "device_version": self.device_version,
                "meta": dict(self.meta),
                "tone": {slot: dict(b.values) for slot, b in self.blocks.items()},
            },
            "schema": self.schema,
            "version": self.version,
        }

    def copy(self) -> "Preset":
        clone = Preset(
            meta=copy.deepcopy(self.meta),
            blocks={k: v.copy() for k, v in self.blocks.items()},
            device=self.device,
            device_version=self.device_version,
            schema=self.schema,
            version=self.version,
        )
        return clone

    @classmethod
    def load_default(cls, data_dir: Path | str = DATA_DIR) -> "Preset":
        path = Path(data_dir) / "default_preset.json"
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


class EditBuffer:
    """Live, validated editing state bound to a :class:`ModelCatalog`.

    The UI calls :meth:`set_param` / :meth:`set_model` / :meth:`set_enabled`; each
    write is clamped to the relevant :class:`ParamSpec` and broadcast to observers.
    """

    def __init__(self, catalog: ModelCatalog, preset: Preset | None = None):
        self.catalog = catalog
        self.preset = preset or Preset.load_default(catalog.data_dir)
        self._listeners: list[ChangeListener] = []

    def load_preset(self, preset: Preset) -> None:
        """Replace the working preset in place, keeping observers attached."""
        self.preset = preset

    # -- observation ----------------------------------------------------------

    def add_listener(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def _notify(self, slot_id: str, param_id: str, value: Any) -> None:
        for listener in list(self._listeners):
            listener(slot_id, param_id, value)

    # -- introspection --------------------------------------------------------

    def block(self, slot_id: str) -> Block:
        block = self.preset.blocks.get(slot_id)
        if block is None:
            block = Block(slot_id, {})
            self.preset.blocks[slot_id] = block
        return block

    def model_of(self, slot_id: str) -> ModelSpec | None:
        """The currently selected model for a slot."""
        block = self.preset.blocks.get(slot_id)
        if block is None or block.model_id is None:
            slot = SLOTS_BY_ID.get(slot_id)
            if slot and slot.kind == "fixed" and slot.fixed_model:
                return self.catalog.model(slot.fixed_model)
            return None
        return self.catalog.model(block.model_id)

    def param_spec(self, slot_id: str, param_id: str) -> ParamSpec | None:
        model = self.model_of(slot_id)
        return model.param(param_id) if model else None

    def get_param(self, slot_id: str, param_id: str) -> Any:
        return self.block(slot_id).get(param_id)

    # -- editing --------------------------------------------------------------

    def set_param(self, slot_id: str, param_id: str, value: Any) -> Any:
        """Set a parameter value, clamped to its spec.  Returns the stored value."""
        spec = self.param_spec(slot_id, param_id)
        stored = spec.clamp(value) if spec is not None else value
        self.block(slot_id).values[param_id] = stored
        self._notify(slot_id, param_id, stored)
        return stored

    def set_enabled(self, slot_id: str, enabled: bool) -> None:
        self.set_param(slot_id, "@enabled", bool(enabled))

    def set_model(self, slot_id: str, model_symbolic_id: str, reset_params: bool = True) -> None:
        """Select a model for a slot.

        When *reset_params* is true, parameter values are initialised to the new
        model's defaults while preserving structural attributes (enabled, mix,
        routing) that carry across a model swap.
        """
        model = self.catalog.model(model_symbolic_id)
        block = self.block(slot_id)
        if reset_params and model is not None:
            preserved = {
                k: v for k, v in block.values.items()
                if k in ("@enabled", "@mix", "@mixtype", "@post", "@temposync")
            }
            new_values: dict[str, Any] = {"@model": model_symbolic_id}
            for p in model.params:
                new_values[p.symbolic_id] = p.default
            new_values.update(preserved)
            block.values = new_values
        else:
            block.values["@model"] = model_symbolic_id
        self._notify(slot_id, "@model", model_symbolic_id)

    # -- convenience ----------------------------------------------------------

    def slots(self):
        """Iterate (SlotDef, Block) pairs in signal-chain order."""
        for slot in SLOT_LAYOUT:
            yield slot, self.block(slot.id)

    def snapshot(self) -> Preset:
        """A deep copy of the current preset (for save / undo)."""
        return self.preset.copy()
