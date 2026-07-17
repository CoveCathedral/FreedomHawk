"""The tone-model catalog: every model, parameter, and pick-list.

This is the app's source of truth for *what is editable and how*.  It loads:

* all ``*.models`` files -> a registry of :class:`ModelSpec` keyed by symbolic and
  numeric ID; and
* all ``*Catalog.json`` files -> the app's own curated, human-grouped pick-lists
  used to populate the model chooser for each swappable slot.

It also defines the fixed signal-chain **slots** of a preset (amp, cab, fx1..3,
reverb, wah, plus the fixed compressor/eq/gate/volume blocks and the global block).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .valuetypes import ModelSpec, ParamSpec

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_MODEL_FILES = [
    "amps.models", "amps_hd.models", "cabs.models", "delay.models",
    "fixed.models", "mod.models", "reverbs.models", "reverbs_mclass.models",
    "stomps.models", "stomps_hd.models", "wahs.models",
]

_CATALOG_FILES = {
    "amp": "AmpCatalog.json",
    "cab": "CabCatalog.json",
    "fx": "FXCatalog.json",
    "reverb": "ReverbCatalog.json",
    "wah": "WahCatalog.json",
}


@dataclass(frozen=True)
class SlotDef:
    """A fixed position in a preset's signal chain."""

    id: str
    display_name: str
    #: 'catalog' = user picks any model from a catalog; 'fixed' = one built-in model;
    #: 'global' = not a model block (tempo / tweak / assignments).
    kind: str
    catalog: str | None = None
    fixed_model: str | None = None

    @property
    def swappable(self) -> bool:
        return self.kind == "catalog"


# The standard Firehawk FX signal chain, in a sensible edit order.  Slot IDs match
# the keys under ``tone`` in default_preset.json.
SLOT_LAYOUT: tuple[SlotDef, ...] = (
    SlotDef("wah", "Wah", "catalog", catalog="wah"),
    SlotDef("compressor", "Compressor", "fixed", fixed_model="SharcPodFixedComp"),
    SlotDef("gate", "Noise Gate", "fixed", fixed_model="Gate"),
    SlotDef("amp", "Amp", "catalog", catalog="amp"),
    SlotDef("cab", "Cabinet", "catalog", catalog="cab"),
    SlotDef("eq", "EQ", "fixed", fixed_model="ParaGraphic4_band"),
    SlotDef("fx1", "FX 1", "catalog", catalog="fx"),
    SlotDef("fx2", "FX 2", "catalog", catalog="fx"),
    SlotDef("fx3", "FX 3", "catalog", catalog="fx"),
    SlotDef("reverb", "Reverb", "catalog", catalog="reverb"),
    SlotDef("volume", "Volume Pedal", "fixed", fixed_model="VolumePedal"),
    SlotDef("variax", "Variax", "fixed", fixed_model="@variax"),
    SlotDef("global", "Global", "global"),
)

SLOTS_BY_ID: dict[str, SlotDef] = {s.id: s for s in SLOT_LAYOUT}


@dataclass(frozen=True)
class CatalogGroup:
    """A named group of models within a catalog (e.g. 'British' amps)."""

    name: str
    models: tuple[ModelSpec, ...]


@dataclass(frozen=True)
class Catalog:
    """An ordered, grouped pick-list for one swappable slot kind."""

    key: str
    groups: tuple[CatalogGroup, ...]

    def all_models(self) -> list[ModelSpec]:
        return [m for g in self.groups for m in g.models]


class ModelCatalog:
    """Registry of all models plus the grouped pick-lists."""

    def __init__(self, data_dir: Path | str = DATA_DIR):
        self.data_dir = Path(data_dir)
        self._by_symbol: dict[str, ModelSpec] = {}
        self._by_numeric: dict[int, ModelSpec] = {}
        self._catalogs: dict[str, Catalog] = {}
        self._load_models()
        self._load_catalogs()

    # -- loading --------------------------------------------------------------

    def _load_models(self) -> None:
        for filename in _MODEL_FILES:
            path = self.data_dir / filename
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            for entry in raw:
                model = ModelSpec.from_json(entry)
                self._by_symbol[model.symbolic_id] = model
                self._by_numeric[model.numeric_id] = model

    def _synthetic(self, symbolic_id: str) -> ModelSpec:
        """A placeholder model for catalog names with no ``.models`` entry (e.g. Bypass)."""
        from .valuetypes import humanize
        return ModelSpec(
            symbolic_id=symbolic_id,
            numeric_id=0,
            name=humanize(symbolic_id),
            category=None,
            params=(),
            extras={"synthetic": True},
        )

    def _load_catalogs(self) -> None:
        for key, filename in _CATALOG_FILES.items():
            path = self.data_dir / filename
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            groups = []
            for group_name, symbol_ids in raw.items():
                models = tuple(
                    self._by_symbol.get(sid) or self._synthetic(sid)
                    for sid in symbol_ids
                )
                groups.append(CatalogGroup(name=group_name, models=models))
            self._catalogs[key] = Catalog(key=key, groups=tuple(groups))

    # -- access ---------------------------------------------------------------

    def model(self, symbolic_id: str) -> ModelSpec | None:
        return self._by_symbol.get(symbolic_id)

    def model_by_id(self, numeric_id: int) -> ModelSpec | None:
        return self._by_numeric.get(numeric_id)

    def catalog(self, key: str) -> Catalog | None:
        return self._catalogs.get(key)

    def all_models(self) -> list[ModelSpec]:
        return list(self._by_symbol.values())

    def __len__(self) -> int:
        return len(self._by_symbol)

    # -- slot-aware queries ---------------------------------------------------

    def models_for_slot(
        self, slot_id: str, device_id: int | None = None
    ) -> list[CatalogGroup]:
        """The grouped model choices offered for a slot, filtered by hardware.

        For a swappable slot this returns the catalog's groups (minus any model
        the given hardware does not support).  For a fixed slot it returns a
        single group holding that slot's one built-in model.  For 'global' it
        returns an empty list.
        """
        slot = SLOTS_BY_ID.get(slot_id)
        if slot is None:
            raise KeyError(f"unknown slot: {slot_id!r}")
        if slot.kind == "global":
            return []
        if slot.kind == "fixed":
            model = self._by_symbol.get(slot.fixed_model or "")
            models = (model,) if model else ()
            return [CatalogGroup(name=slot.display_name, models=models)]
        catalog = self._catalogs.get(slot.catalog or "")
        if catalog is None:
            return []
        groups: list[CatalogGroup] = []
        for group in catalog.groups:
            offered = tuple(m for m in group.models if m.available_on(device_id))
            if offered:
                groups.append(CatalogGroup(name=group.name, models=offered))
        return groups


__all__ = [
    "ModelCatalog", "Catalog", "CatalogGroup", "SlotDef",
    "SLOT_LAYOUT", "SLOTS_BY_ID", "DATA_DIR", "ModelSpec", "ParamSpec",
]
