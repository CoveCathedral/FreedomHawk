"""ToneMatch editor commands — the live single-parameter protocol.

Confirmed by decompilation of ``ToneMatchEdit_Remote::DoCommandCommon`` and its callers
(``SetDspModelParam`` / ``SetPresetPSKeyParam`` / ``SetGlobalTempo`` / ``LoadDspModel``).
See ``docs/protocol.md``.  This is what a *live* knob tweak uses — distinct from the
bulk preset serializer in :mod:`firehawk.protocol.message`.

Every command is:

    [uint32 cmdID][uint32 dataLen][data ...]

and this command message is the **payload** carried inside the transport header + serial
frame (see :mod:`firehawk.protocol.frame`).

A ToneMatch typed value is ``[uint32 type][uint32 value]``; the value word holds the
IEEE-754 float bits for a continuous parameter.
"""

from __future__ import annotations

import struct
from enum import IntEnum


class Cmd(IntEnum):
    LOAD_DSP_MODEL = 0x08          # data: [uint32 slot][uint32 modelId]
    SET_DSP_MODEL_PARAM = 0x0A     # data: [uint32 slot][uint32 paramId][typedvalue]
    SET_GLOBAL_TEMPO = 0x0E        # data: [float bpm]
    SET_PRESET_PSKEY_PARAM = 0x13  # data: [uint32 psKey][typedvalue]


# ToneMatch typed-value type tag. The float tag is not yet pinned to its exact enum
# value (confirm from a capture or the typed-value constructor); the wire *structure*
# is confirmed. Continuous params carry their value as IEEE-754 float bits.
TM_TYPE_FLOAT = 3
TM_TYPE_INT = 2


def command(cmd_id: int, data: bytes) -> bytes:
    """Wrap *data* as a ToneMatch command message ``[cmdID][len][data]``."""
    return struct.pack("<II", int(cmd_id), len(data)) + bytes(data)


def _typed_value(value: float, tv_type: int) -> bytes:
    """``[uint32 type][uint32 value]`` — value word is the float bits for a float type."""
    if tv_type == TM_TYPE_FLOAT:
        value_word = struct.unpack("<I", struct.pack("<f", float(value)))[0]
    else:
        value_word = int(value) & 0xFFFFFFFF
    return struct.pack("<II", int(tv_type), value_word)


def set_dsp_model_param(slot: int, param_id: int, value: float,
                        tv_type: int = TM_TYPE_FLOAT) -> bytes:
    """Set a model knob: cmd 0x0A, data ``[slot][paramId][type][value]`` (16 bytes).

    *param_id* is the parameter's index in the symbol table; *slot* is the DSP slot for
    the block.
    """
    data = struct.pack("<II", slot & 0xFFFFFFFF, param_id & 0xFFFFFFFF) + _typed_value(value, tv_type)
    return command(Cmd.SET_DSP_MODEL_PARAM, data)


def set_preset_pskey_param(ps_key: int, value: float,
                           tv_type: int = TM_TYPE_FLOAT) -> bytes:
    """Set a structural param: cmd 0x13, data ``[psKey][type][value]`` (12 bytes)."""
    data = struct.pack("<I", ps_key & 0xFFFFFFFF) + _typed_value(value, tv_type)
    return command(Cmd.SET_PRESET_PSKEY_PARAM, data)


def set_global_tempo(bpm: float) -> bytes:
    """Set global tempo: cmd 0x0E, data ``[float bpm]`` (4 bytes, raw float — no type tag)."""
    return command(Cmd.SET_GLOBAL_TEMPO, struct.pack("<f", float(bpm)))


def load_dsp_model(slot: int, model_id: int) -> bytes:
    """Load a model into a slot: cmd 0x08, data ``[slot][modelId]`` (8 bytes)."""
    return command(Cmd.LOAD_DSP_MODEL, struct.pack("<II", slot & 0xFFFFFFFF, model_id & 0xFFFFFFFF))
