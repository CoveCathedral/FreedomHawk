"""Transport abstraction: raw byte I/O to the pedal.

This mirrors the thin "byte pump" found in the app's Java: it moves raw bytes to and
from the link and does no protocol parsing.  The protocol layer sits above it.  A
:class:`Transport` can be a real serial/RFCOMM port or an offline simulator, so the
whole application is usable and testable without hardware present.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Callable

#: Called with each inbound chunk of raw bytes read from the link.
BytesListener = Callable[[bytes], None]


class Transport(ABC):
    """A bidirectional raw-byte link to the pedal."""

    def __init__(self) -> None:
        self._listeners: list[BytesListener] = []
        self._lock = threading.Lock()

    def add_listener(self, listener: BytesListener) -> None:
        self._listeners.append(listener)

    def _emit(self, data: bytes) -> None:
        for listener in list(self._listeners):
            listener(data)

    @abstractmethod
    def open(self) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def write(self, data: bytes) -> int:
        """Write raw bytes to the link; returns the number of bytes written."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        ...

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
