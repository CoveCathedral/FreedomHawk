"""The RobustSerialMsgChannel serial frame.

Confirmed by decompilation of ``RobustSerialMsgChannel_ExecTasks`` (builder) and
``RobustSerialMsgChannel_HandleRxData`` (parser).  See ``docs/protocol.md``.

Every frame is a 12-byte header followed by an optional payload:

    byte  0-1   sync        = 0x55 0x55
    byte  2     flags       = 0x00 (observed)
    byte  3     seq         sender sequence number
    byte  4     window      channel window / rx index
    byte  5     ack         acknowledgement number
    byte  6-7   length      payload length, little-endian (0 for a control frame)
    byte  8-9   payload_crc CRC-16/CCITT-FALSE over the payload (0 if no payload)
    byte 10-11  header_crc  CRC-16/CCITT-FALSE over bytes 0..11 with 10-11 = 0
    byte 12..   payload     `length` bytes (data frames only)

Both CRCs use init 0xFFFF (see :mod:`firehawk.protocol.crc`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .crc import crc16_ccitt_false

SYNC = b"\x55\x55"
HEADER_SIZE = 12


@dataclass(frozen=True)
class Frame:
    """A decoded serial frame."""

    seq: int
    ack: int
    payload: bytes = b""
    flags: int = 0
    window: int = 0

    def build(self) -> bytes:
        """Serialize to on-wire bytes, computing both CRCs exactly as the pedal does."""
        length = len(self.payload)
        header = bytearray(HEADER_SIZE)
        header[0:2] = SYNC
        header[2] = self.flags & 0xFF
        header[3] = self.seq & 0xFF
        header[4] = self.window & 0xFF
        header[5] = self.ack & 0xFF
        struct.pack_into("<H", header, 6, length & 0xFFFF)
        payload_crc = crc16_ccitt_false(self.payload) if self.payload else 0
        struct.pack_into("<H", header, 8, payload_crc)
        # header CRC is computed with the CRC field (bytes 10-11) still zero
        header_crc = crc16_ccitt_false(bytes(header))
        struct.pack_into("<H", header, 10, header_crc)
        return bytes(header) + self.payload


def build_control_frame(seq: int, ack: int, window: int = 0) -> bytes:
    """A 12-byte control/ack frame (no payload)."""
    return Frame(seq=seq, ack=ack, window=window).build()


def parse_frame(data: bytes) -> Frame | None:
    """Parse one frame from *data*, verifying both CRCs.

    Returns the :class:`Frame` on success, or None if the sync/CRC/length don't
    check out or the buffer is short.  Mirrors ``HandleRxData``.
    """
    if len(data) < HEADER_SIZE or data[0:2] != SYNC:
        return None
    header = bytearray(data[:HEADER_SIZE])
    stored_header_crc = struct.unpack_from("<H", header, 10)[0]
    header[10:12] = b"\x00\x00"
    if crc16_ccitt_false(bytes(header)) != stored_header_crc:
        return None
    length = struct.unpack_from("<H", header, 6)[0]
    payload_crc = struct.unpack_from("<H", header, 8)[0]
    if len(data) < HEADER_SIZE + length:
        return None
    payload = data[HEADER_SIZE:HEADER_SIZE + length]
    if length and crc16_ccitt_false(payload) != payload_crc:
        return None
    return Frame(
        seq=data[3], ack=data[5], payload=payload,
        flags=data[2], window=data[4],
    )
