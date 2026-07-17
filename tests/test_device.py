"""Tests for the gated DeviceSession bridge and the edit dispatcher."""

import struct

import pytest

from firehawk.device import DeviceSession
from firehawk.model import ModelCatalog
from firehawk.protocol import parse_frame
from firehawk.transport import SimulatorTransport


@pytest.fixture(scope="module")
def catalog() -> ModelCatalog:
    return ModelCatalog()


@pytest.fixture()
def session(catalog) -> DeviceSession:
    return DeviceSession(catalog)


def test_dispatch_routes_each_param_type(session):
    cases = {
        ("amp", "Bass", 0.5): "model_param",
        ("amp", "Drive", 0.7): "model_param",
        ("fx1", "@enabled", True): "structural",
        ("fx1", "@mix", 0.3): "structural",
        ("reverb", "@enabled", True): "structural",
        ("global", "@tempo", 171.5): "tempo",
        ("global", "@tweakmin", 0.2): "global_pskey",
        ("amp", "@model", "BritGainJ800"): "model_load",
    }
    for (group, param, value), kind in cases.items():
        edit = session.encode(group, param, value)
        assert edit is not None, f"{group}/{param} unmapped"
        assert edit.kind == kind


def test_model_param_encodes_symbol_indices(session):
    edit = session.encode("amp", "Bass", 0.5)
    cmd, length, slot, param_id, tv_type, value_word = struct.unpack("<IIIIII", edit.message)
    assert cmd == 0x0A
    assert slot == session.symbol_table.index("Amp")
    assert param_id == session.symbol_table.index("Bass")
    assert struct.unpack("<f", struct.pack("<I", value_word))[0] == pytest.approx(0.5)


def test_structural_uses_guitarproc_slot(session):
    edit = session.encode("fx1", "@enabled", True)
    _cmd, _len, slot, param_id, _t, value_word = struct.unpack("<IIIIII", edit.message)
    assert slot == session.symbol_table.index("GuitarProc")
    assert param_id == session.symbol_table.index("FX1Enable")
    assert struct.unpack("<f", struct.pack("<I", value_word))[0] == 1.0  # True -> 1.0


def test_unmapped_edit_returns_none(session):
    assert session.encode("nope", "Whatever", 1) is None


def test_safety_gate_blocks_transmission_by_default(session):
    transport = SimulatorTransport()
    transport.open()
    session.transport = transport
    # Default: transmit disabled -> nothing written, but the edit is still logged.
    entry = session.handle_edit("amp", "Bass", 0.6)
    assert entry.transmitted is False
    assert transport.written == []
    assert session.outbox[-1] is entry
    # Enable -> the next edit is framed and written.
    session.transmit_enabled = True
    session.handle_edit("amp", "Bass", 0.7)
    assert len(transport.written) == 1


def test_transmitted_frame_round_trips(session):
    transport = SimulatorTransport()
    transport.open()
    session.transport = transport
    session.transmit_enabled = True
    edit = session.encode("amp", "Drive", 0.25)
    session.handle_edit("amp", "Drive", 0.25)
    frame = parse_frame(transport.written[-1])
    assert frame is not None
    # Payload = 8-byte transport header + the ToneMatch command.
    assert frame.payload[8:] == edit.message
