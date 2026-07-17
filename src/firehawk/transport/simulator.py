"""Offline simulator transport.

Lets the whole application run and be exercised with a screen reader without any
hardware connected.  It records everything "written" (so tests and the UI can show
what *would* be sent once framing is finalised) and never emits inbound bytes unless a
test injects them.
"""

from __future__ import annotations

from .base import Transport


class SimulatorTransport(Transport):
    """A no-hardware transport that captures writes and can inject reads."""

    def __init__(self) -> None:
        super().__init__()
        self._open = False
        self.written: list[bytes] = []

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, data: bytes) -> int:
        if not self._open:
            raise RuntimeError("simulator transport is not open")
        self.written.append(bytes(data))
        return len(data)

    def inject(self, data: bytes) -> None:
        """Simulate inbound bytes arriving from the pedal (for tests)."""
        self._emit(bytes(data))

    @property
    def is_open(self) -> bool:
        return self._open
