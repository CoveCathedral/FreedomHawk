"""Tests for the confirmed protocol pieces: CRC-16 and the transport header."""

import struct

import pytest

from firehawk.protocol import TransportHeader, crc16_ccitt_false, crc16_process, crc16_xmodem


# -- CRC-16 (confirmed against CRC16_Process disassembly) ---------------------

def test_crc16_standard_check_values():
    # These are the canonical CRC-16 catalogue check values for the "123456789"
    # test vector; matching them proves poly 0x1021, non-reflected.
    assert crc16_xmodem(b"123456789") == 0x31C3
    assert crc16_ccitt_false(b"123456789") == 0x29B1


def test_crc16_is_incremental():
    whole = crc16_process(0x0000, b"hello world")
    part = crc16_process(0x0000, b"hello ")
    part = crc16_process(part, b"world")
    assert whole == part


def test_crc16_empty_is_identity():
    assert crc16_process(0x1234, b"") == 0x1234


# -- Transport header (confirmed against MsgTransportHeader_Pack) --------------

def test_header_packs_to_native_bit_layout():
    hdr = TransportHeader(msg_type=0xA, field_c=0x1234, addr_d=0x00CD, addr_e=0x00AB)
    packed = hdr.pack()
    assert len(packed) == 8
    word0, word1 = struct.unpack("<II", packed)
    # word0 = type<<28 | addr_type(2)<<26 | field_c
    assert (word0 >> 28) & 0xF == 0xA
    assert (word0 >> 26) & 0x3 == 2
    assert word0 & 0xFFFF == 0x1234
    # word1 = addr_e<<16 | addr_d
    assert word1 & 0xFFFF == 0x00CD
    assert (word1 >> 16) & 0xFFFF == 0x00AB


def test_header_round_trips():
    hdr = TransportHeader(msg_type=3, field_c=42, addr_d=7, addr_e=9, addr_type=2)
    restored = TransportHeader.unpack(hdr.pack())
    assert restored == hdr


@pytest.mark.parametrize("msg_type,field_c,d,e", [
    (0, 0, 0, 0),
    (0xF, 0xFFFF, 0xFFFF, 0xFFFF),
    (1, 8, 0x0102, 0x0304),
])
def test_header_round_trips_fuzz(msg_type, field_c, d, e):
    hdr = TransportHeader(msg_type=msg_type, field_c=field_c, addr_d=d, addr_e=e)
    assert TransportHeader.unpack(hdr.pack()) == hdr
