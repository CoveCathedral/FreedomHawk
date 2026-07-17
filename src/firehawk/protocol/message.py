"""Message-body encoding: the key -> TypedValue stream.

Confirmed by decompilation of ``L6SPePresetSerializer`` (see ``docs/protocol.md``).
The message body is a sequence of entries, each a 4-byte key followed by a TypedValue:

    entry      = uint32 key  +  typed_value
    typed_value = uint16 type + value

TypedValue types (from ``SerializeStringValue``/``SerializeVArrayValue``/the Store* calls):

    1 BOOL     4-byte value
    2 INT      4-byte value
    3 FLOAT    4-byte IEEE-754
    4 STRING   uint32 length + bytes
    6 VARRAY   uint32 count  + bytes
    7 UINT     4-byte value

Structural directive keys have the high bit set: 0x80000000 section id,
0x80000001 section param, 0x80000003 slot id.

Parameter entries (``SerializeParameterPSKey``) address a (group, param) by a numeric
**PSKey** and coerce the value to a float before writing, i.e.
``[uint32 psKey][uint16 type][float32 value]``.  The PSKey <-> (group, param, type)
mapping is a static table in the pedal's library; extract it with
``tools/dump_pskey_table``.
"""

from __future__ import annotations

import struct
from enum import IntEnum

# Directive keys (high bit set).
KEY_SECTION_ID = 0x80000000
KEY_SECTION_PARAM = 0x80000001
KEY_SLOT_ID = 0x80000003


class TVType(IntEnum):
    BOOL = 1
    INT = 2
    FLOAT = 3
    STRING = 4
    VARRAY = 6
    UINT = 7


def encode_typed_value(tv_type: int, value) -> bytes:
    """Encode a standalone TypedValue (``[uint16 type][value]``)."""
    t = int(tv_type)
    if t == TVType.STRING:
        data = value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
        return struct.pack("<HI", t, len(data)) + bytes(data)
    if t == TVType.VARRAY:
        data = bytes(value)
        return struct.pack("<HI", t, len(data) // 4) + data
    if t == TVType.FLOAT:
        return struct.pack("<Hf", t, float(value))
    if t == TVType.INT:
        return struct.pack("<Hi", t, int(value))
    if t == TVType.UINT:
        return struct.pack("<HI", t, int(value) & 0xFFFFFFFF)
    if t == TVType.BOOL:
        return struct.pack("<HI", t, 1 if value else 0)
    raise ValueError(f"unsupported TypedValue type: {tv_type}")


def encode_key_value(key: int, tv_type: int, value) -> bytes:
    """Encode one ``key -> TypedValue`` entry."""
    return struct.pack("<I", key & 0xFFFFFFFF) + encode_typed_value(tv_type, value)


def encode_param(ps_key: int, value: float, tv_type: int = TVType.FLOAT) -> bytes:
    """Encode a parameter entry: ``[uint32 psKey][uint16 type][float32 value]``.

    The pedal coerces every parameter value to a float before writing, so continuous
    params (normalised 0.0-1.0), and ints/bools carried as a param, all serialize the
    value as a 4-byte float.  *tv_type* is the parameter's TypedValue type from the
    PSKey table (defaults to FLOAT, the continuous case).
    """
    return struct.pack("<IHf", ps_key & 0xFFFFFFFF, int(tv_type), float(value))
