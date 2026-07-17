"""Tests for the transport layer (simulator; serial port is hardware-dependent)."""

import pytest

from firehawk.transport import SimulatorTransport
from firehawk.transport.serialport import list_serial_ports


def test_simulator_captures_writes():
    t = SimulatorTransport()
    t.open()
    assert t.is_open
    n = t.write(b"\x01\x02\x03")
    assert n == 3
    assert t.written == [b"\x01\x02\x03"]
    t.close()
    assert not t.is_open


def test_simulator_write_requires_open():
    t = SimulatorTransport()
    with pytest.raises(RuntimeError):
        t.write(b"x")


def test_simulator_injects_inbound_to_listeners():
    t = SimulatorTransport()
    received = []
    t.add_listener(received.append)
    t.open()
    t.inject(b"\xaa\xbb")
    assert received == [b"\xaa\xbb"]


def test_context_manager():
    t = SimulatorTransport()
    with t as tr:
        assert tr.is_open
    assert not t.is_open


def test_list_serial_ports_runs():
    # Should not raise even with no ports present.
    ports = list_serial_ports()
    assert isinstance(ports, list)
