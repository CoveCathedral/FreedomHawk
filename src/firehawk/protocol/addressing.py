"""Resolve a (group, param) pair to the on-wire slot + paramId, and encode a live set.

Confirmed from `sendParamToDevice` -> `GetDSPSlotForGroupAndParam` ->
`FirmwareServiceInterfaceEditor::SetToneMatchModelParam` (see `docs/protocol.md`):

* a **model knob** is addressed by two symbol-table indices — the block's *slot symbol*
  and the *parameter name* — both resolved via `SymbolTable::LookupString`;
* the group -> slot-symbol map below was read out of the binary's slot table and every
  entry verified against the decoded symbol table.

The value is carried as a float (see `tonematch.set_dsp_model_param`).
"""

from __future__ import annotations

from typing import Callable

from . import tonematch

#: Block group id -> its DSP slot symbol (the primary slot; cab has Studio/Live/Air
#: variants and reverb is FX4/FX5 across device variants — the defaults are used here).
GROUP_SLOT_SYMBOL: dict[str, str] = {
    "amp": "Amp",
    "cab": "StudioCab",
    "gate": "Gate",
    "compressor": "PostComp",
    "eq": "PostEQ",
    "volume": "VolumePedal",
    "wah": "Wah",
    "fx1": "FX1",
    "fx2": "FX2",
    "fx3": "FX3",
    "reverb": "FX4",
}

#: A name -> symbol-table index resolver (e.g. ``SymbolTable.index``).
IndexOf = Callable[[str], "int | None"]


def resolve_model_param(index_of: IndexOf, group: str, param: str) -> tuple[int, int] | None:
    """Return ``(slot_index, param_index)`` for a model knob, or None if unresolved."""
    slot_symbol = GROUP_SLOT_SYMBOL.get(group)
    if slot_symbol is None:
        return None
    slot = index_of(slot_symbol)
    param_id = index_of(param)
    if slot is None or param_id is None:
        return None
    return slot, param_id


def encode_set_model_param(index_of: IndexOf, group: str, param: str, value: float) -> bytes:
    """Encode a live "set this model knob" ToneMatch command for (group, param, value).

    Returns the ToneMatch command bytes (the frame payload).  Raises KeyError/ValueError
    if the group or parameter cannot be resolved to symbol-table indices.
    """
    resolved = resolve_model_param(index_of, group, param)
    if resolved is None:
        raise ValueError(f"cannot resolve model param {group!r}/{param!r} to symbol indices")
    slot, param_id = resolved
    return tonematch.set_dsp_model_param(slot, param_id, value)
