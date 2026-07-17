"""CRC-16 used by the Firehawk serial link.

Confirmed by disassembly of ``CRC16_Process`` (libAmplifiRemoteNdk.so @ 0x103b10):
CRC-16/CCITT, polynomial 0x1021, **non-reflected**, no final xor.  The initial value
is seeded by the caller in the framing layer; it is passed in here explicitly.  See
``docs/protocol.md``.
"""

from __future__ import annotations

POLY = 0x1021  # CRC-16/CCITT


def crc16_process(crc: int, data: bytes) -> int:
    """Update *crc* over *data*, exactly as the native ``CRC16_Process`` does.

    This is a byte-wise, non-reflected CRC-16/CCITT.  Pass the running CRC in and
    use the return value as the next running CRC (or the final checksum).

    >>> hex(crc16_process(0x0000, b"123456789"))   # CRC-16/XMODEM
    '0x31c3'
    >>> hex(crc16_process(0xFFFF, b"123456789"))   # CRC-16/CCITT-FALSE
    '0x29b1'
    """
    crc &= 0xFFFF
    for byte in data:
        x = (byte ^ (crc >> 8)) & 0xFF
        y = (x ^ (x >> 4)) & 0xFFFF
        crc = ((crc << 8) ^ (y << 12) ^ (y << 5) ^ y) & 0xFFFF
    return crc


def crc16_xmodem(data: bytes) -> int:
    """CRC-16 with init 0x0000 (XMODEM variant)."""
    return crc16_process(0x0000, data)


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16 with init 0xFFFF (CCITT-FALSE variant)."""
    return crc16_process(0xFFFF, data)
