"""Serial-port transport for a paired Firehawk over Bluetooth SPP.

On Windows a paired Bluetooth Serial Port Profile (SPP) device appears as a virtual
COM port, so ``pyserial`` opens it directly -- no BLE stack required.  This matches the
app's use of an insecure RFCOMM socket to the SPP UUID
``00001101-0000-1000-8000-00805f9b34fb`` (see decompiled ``AmplifiDeviceManager``).

A background reader thread pumps inbound bytes to listeners, exactly like the app's
inbound thread that reads 64-byte chunks from the socket's InputStream.
"""

from __future__ import annotations

import threading

import serial
from serial.tools import list_ports

from .base import Transport

READ_CHUNK = 64  # mirrors the app's 64-byte inbound buffer


def list_serial_ports() -> list[tuple[str, str]]:
    """Return (device, description) for every serial port on the system."""
    return [(p.device, p.description) for p in list_ports.comports()]


def find_firehawk_ports() -> list[tuple[str, str]]:
    """Best-effort filter of ports whose description looks like a Firehawk/Line 6/SPP.

    Bluetooth SPP ports commonly report descriptions containing "Bluetooth" or the
    device name; this is a hint only.  The UI should still let the user pick manually.
    """
    hints = ("firehawk", "line 6", "line6", "amplifi", "bluetooth", "standard serial over bluetooth")
    out = []
    for device, desc in list_serial_ports():
        if any(h in desc.lower() for h in hints):
            out.append((device, desc))
    return out


class SerialTransport(Transport):
    """Raw byte transport over a (Bluetooth SPP) COM port."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.1):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: serial.Serial | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()

    def open(self) -> None:
        if self._serial is not None:
            return
        # Baudrate is nominal for a virtual Bluetooth COM port but pyserial requires one.
        self._serial = serial.Serial(
            self.port, baudrate=self.baudrate, timeout=self.timeout
        )
        self._stop.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name="firehawk-serial-reader", daemon=True
        )
        self._reader.start()

    def _read_loop(self) -> None:
        assert self._serial is not None
        while not self._stop.is_set():
            try:
                data = self._serial.read(READ_CHUNK)
            except (serial.SerialException, OSError):
                break
            if data:
                self._emit(data)

    def write(self, data: bytes) -> int:
        if self._serial is None:
            raise RuntimeError("serial port is not open")
        with self._lock:
            return self._serial.write(data) or 0

    def close(self) -> None:
        self._stop.set()
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open
