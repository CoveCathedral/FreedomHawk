"""The tone-model layer: models, parameters, ranges, symbols, and preset state.

This layer is pure data with no hardware or UI dependencies, so it is fully
testable on its own.  It is the source of truth the accessible UI uses to build a
correctly labelled and ranged control for every editable parameter.
"""

from .catalog import (
    Catalog,
    CatalogGroup,
    ModelCatalog,
    SLOT_LAYOUT,
    SLOTS_BY_ID,
    SlotDef,
)
from .library import PresetEntry, PresetLibrary, summarize_preset
from .preset import Block, EditBuffer, Preset
from .symbols import Symbol, SymbolTable
from .valuetypes import ModelSpec, ParamSpec, ValueType, humanize

__all__ = [
    "Catalog", "CatalogGroup", "ModelCatalog", "SlotDef",
    "SLOT_LAYOUT", "SLOTS_BY_ID",
    "Block", "EditBuffer", "Preset",
    "PresetEntry", "PresetLibrary", "summarize_preset",
    "Symbol", "SymbolTable",
    "ModelSpec", "ParamSpec", "ValueType", "humanize",
]
