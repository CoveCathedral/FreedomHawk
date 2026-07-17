"""Tests for the confirmed protocol pieces: CRC-16 and the transport header."""

import struct

import pytest

from firehawk.protocol import (
    Frame,
    TransportHeader,
    TVType,
    build_control_frame,
    crc16_ccitt_false,
    crc16_process,
    crc16_xmodem,
    encode_key_value,
    encode_param,
    encode_typed_value,
    parse_frame,
)


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


# -- serial frame (confirmed against RobustSerialMsgChannel_ExecTasks/HandleRxData) --

def test_control_frame_is_12_bytes_and_round_trips():
    raw = build_control_frame(seq=3, ack=5, window=7)
    assert len(raw) == 12
    assert raw[0:2] == b"\x55\x55"
    f = parse_frame(raw)
    assert f is not None
    assert f.seq == 3 and f.ack == 5 and f.window == 7 and f.payload == b""


def test_header_crc_covers_12_bytes_with_crc_field_zeroed():
    raw = bytearray(build_control_frame(seq=1, ack=2))
    # Recompute the way the pedal does: over all 12 bytes with the CRC field zeroed.
    header = bytearray(raw[:12])
    header[10:12] = b"\x00\x00"
    assert struct.unpack_from("<H", raw, 10)[0] == crc16_ccitt_false(bytes(header))


def test_data_frame_round_trips_with_payload_crc():
    payload = bytes(range(20))
    raw = Frame(seq=9, ack=1, payload=payload).build()
    assert len(raw) == 12 + len(payload)
    assert struct.unpack_from("<H", raw, 6)[0] == len(payload)      # length field
    assert struct.unpack_from("<H", raw, 8)[0] == crc16_ccitt_false(payload)
    f = parse_frame(raw)
    assert f is not None and f.payload == payload


def test_parse_rejects_corrupt_header_and_payload():
    raw = bytearray(Frame(seq=1, ack=1, payload=b"hello world!").build())
    good = bytes(raw)
    assert parse_frame(good) is not None
    bad_header = bytearray(good); bad_header[3] ^= 0xFF   # flip a header byte, CRC now wrong
    assert parse_frame(bytes(bad_header)) is None
    bad_payload = bytearray(good); bad_payload[13] ^= 0xFF
    assert parse_frame(bytes(bad_payload)) is None


# -- message body / value encoding (confirmed against L6SPePresetSerializer) --

def test_encode_param_is_key_type_float():
    body = encode_param(0x00012345, 0.5)
    assert len(body) == 10
    key, tv_type, value = struct.unpack("<IHf", body)
    assert key == 0x00012345
    assert tv_type == TVType.FLOAT
    assert value == pytest.approx(0.5)


def test_encode_typed_value_variants():
    assert encode_typed_value(TVType.FLOAT, 1.0) == struct.pack("<Hf", 3, 1.0)
    assert encode_typed_value(TVType.INT, -7) == struct.pack("<Hi", 2, -7)
    assert encode_typed_value(TVType.STRING, "hi") == struct.pack("<HI", 4, 2) + b"hi"


def test_encode_key_value_prefixes_key():
    kv = encode_key_value(0x80000003, TVType.UINT, 4)
    assert kv[:4] == struct.pack("<I", 0x80000003)
    assert kv[4:] == encode_typed_value(TVType.UINT, 4)
