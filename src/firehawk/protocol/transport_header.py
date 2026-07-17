"""The 8-byte message transport header.

Confirmed by disassembly of ``MsgTransportHeader_Pack`` / ``_Unpack``
(libAmplifiRemoteNdk.so @ 0x1022b0 / 0x102280).  The header is packed into two
little-endian 32-bit words:

    word0 = (msg_type & 0xF) << 28 | (addr_type & 0x3) << 26 | (field_c & 0xFFFF)
    word1 = (addr_e & 0xFFFF) << 16 | (addr_d & 0xFFFF)

``MsgPort_PrepareTransportHeader`` fills it with ``addr_type = 2`` (constant) and the
port's two 16-bit addresses.  The precise meaning of the two addresses (which is source
vs destination) and whether ``field_c`` is a length or a message id are still being
confirmed against a capture -- see ``docs/protocol.md``.  The pack/unpack below are
byte-exact regardless of that labelling.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_WORDS = struct.Struct("<II")

ADDR_TYPE_DEFAULT = 2  # constant written by MsgPort_PrepareTransportHeader


@dataclass(frozen=True)
class TransportHeader:
    """A decoded transport header.  Field names marked (tentative) pending capture."""

    msg_type: int          # 4 bits  -- message type / class
    field_c: int           # 16 bits -- length or message id (tentative)
    addr_d: int            # 16 bits -- port address D (from port+0x14)
    addr_e: int            # 16 bits -- port address E (from port+0x16)
    addr_type: int = ADDR_TYPE_DEFAULT  # 2 bits

    def pack(self) -> bytes:
        """Serialize to the 8-byte on-wire header (byte-exact to the native packer)."""
        word0 = (
            ((self.msg_type & 0xF) << 28)
            | ((self.addr_type & 0x3) << 26)
            | (self.field_c & 0xFFFF)
        )
        word1 = ((self.addr_e & 0xFFFF) << 16) | (self.addr_d & 0xFFFF)
        return _WORDS.pack(word0 & 0xFFFFFFFF, word1 & 0xFFFFFFFF)

    @classmethod
    def unpack(cls, data: bytes) -> "TransportHeader":
        word0, word1 = _WORDS.unpack_from(data, 0)
        return cls(
            msg_type=(word0 >> 28) & 0xF,
            addr_type=(word0 >> 26) & 0x3,
            field_c=word0 & 0xFFFF,
            addr_d=word1 & 0xFFFF,
            addr_e=(word1 >> 16) & 0xFFFF,
        )


SIZE = 8
