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

from dataclasses import dataclass
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

#: The fixed DSP slot symbol shared by all structural (@) params (from
#: GetDSPSlotForGroupAndParam's @-branch; GuitarProc resolves as the guitar-processor root).
STRUCTURAL_SLOT_SYMBOL = "GuitarProc"

#: group -> the prefix used to build a structural param's descriptive symbol name.
_STRUCTURAL_PREFIX: dict[str, str] = {
    "fx1": "FX1", "fx2": "FX2", "fx3": "FX3", "reverb": "FX4",
    "cab": "Cab", "gate": "Gate", "wah": "Wah",
    "compressor": "PostComp", "eq": "PostEQ", "volume": "VolumePedal",
}

#: @param -> the suffix of its descriptive symbol name.
_STRUCTURAL_SUFFIX: dict[str, str] = {
    "@enabled": "Enable", "@mix": "Mix", "@mixtype": "MixType",
    "@post": "Post", "@stereo": "StereoEnable",
}

#: Irregular descriptive names that don't follow prefix+suffix.
_STRUCTURAL_OVERRIDE: dict[tuple[str, str], str] = {
    ("volume", "@post"): "VolumePost",
    ("amp", "@volume"): "ChannelVolume",
}

#: global/variax params addressed by a fixed psKey (from the PSKey table).
#: @tempo is handled specially via set_global_tempo, so it's not here.
GLOBAL_PSKEY: dict[str, int] = {
    "@tweakmin": 0x07, "@tweakmax": 0x08, "@pedal2assign": 0x09,
    "@modelmagmode": 0x19, "@variaxmodel": 0x1A, "@toneknob": 0x1B,
    "@string1tuning": 0x1C, "@string2tuning": 0x1D, "@string3tuning": 0x1E,
    "@string4tuning": 0x1F, "@string5tuning": 0x20, "@string6tuning": 0x21,
}

#: A name -> symbol-table index resolver (e.g. ``SymbolTable.index``).
IndexOf = Callable[[str], "int | None"]


def structural_symbol(group: str, param: str) -> str | None:
    """The descriptive symbol name for a structural (@) param, e.g. (fx1,@enabled)->FX1Enable."""
    if (group, param) in _STRUCTURAL_OVERRIDE:
        return _STRUCTURAL_OVERRIDE[(group, param)]
    prefix = _STRUCTURAL_PREFIX.get(group)
    suffix = _STRUCTURAL_SUFFIX.get(param)
    if prefix is None or suffix is None:
        return None
    return prefix + suffix


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


def _as_number(value) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


@dataclass(frozen=True)
class EncodedEdit:
    """The protocol message for one edit, plus which command path it took."""

    kind: str          # model_param | structural | tempo | model_load | global_pskey
    message: bytes     # the ToneMatch command bytes (frame payload)
    detail: str        # human-readable description (for the outbox log)


def encode_edit(
    index_of: IndexOf,
    model_id_of: Callable[[str], "int | None"],
    group: str,
    param: str,
    value,
) -> EncodedEdit | None:
    """Route a single (group, param, value) edit to its ToneMatch command.

    Mirrors ``A36EditBufferContext::sendParamToDevice``: model swap, tempo, global
    psKey params, structural (@) params, and model knobs each take their own path.
    Returns None if the edit can't be resolved (logged as unmapped by the caller).
    """
    if param == "@model":
        slot_symbol = GROUP_SLOT_SYMBOL.get(group)
        slot = index_of(slot_symbol) if slot_symbol else None
        model_num = model_id_of(value) if isinstance(value, str) else None
        if slot is None or model_num is None:
            return None
        return EncodedEdit("model_load", tonematch.load_dsp_model(slot, model_num),
                           f"load {value} into {slot_symbol} (slot {slot})")

    if group == "global" and param == "@tempo":
        return EncodedEdit("tempo", tonematch.set_global_tempo(_as_number(value)),
                           f"global tempo {value}")

    if param in GLOBAL_PSKEY:
        ps = GLOBAL_PSKEY[param]
        return EncodedEdit("global_pskey", tonematch.set_preset_pskey_param(ps, _as_number(value)),
                           f"{param} via psKey {ps:#x}")

    symbol = structural_symbol(group, param)
    if symbol is not None:
        param_id = index_of(symbol)
        slot = index_of(STRUCTURAL_SLOT_SYMBOL)
        if param_id is not None and slot is not None:
            return EncodedEdit("structural",
                               tonematch.set_dsp_model_param(slot, param_id, _as_number(value)),
                               f"{group}/{param} -> {symbol} (slot {slot}, id {param_id})")
        return None

    # A model knob (including @-params that aren't structural, e.g. an enum resolved by name).
    resolved = resolve_model_param(index_of, group, param)
    if resolved is None:
        return None
    slot, param_id = resolved
    return EncodedEdit("model_param",
                       tonematch.set_dsp_model_param(slot, param_id, _as_number(value)),
                       f"{group}/{param} (slot {slot}, id {param_id})")
