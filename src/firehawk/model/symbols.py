"""Decoder for the Firehawk symbol table (``defaultSymbolTable.bin``).

The pedal's firmware and the app refer to parameters and models by a compact
symbol index.  ``defaultSymbolTable.bin`` maps those indices to human-readable
names (and carries a 32-bit hash per symbol).  This decoder is self-calibrating:
it solves the string-pool base by scoring candidate offsets rather than relying
on a hardcoded anchor, so it also handles the per-product variants
(``defaultSymbolTable_FX100.bin`` etc.).

Binary layout (all little-endian):

* Header, 12 bytes: ``uint32 count``, ``uint32 file_size``, ``uint32 reserved``.
* Records, 12 bytes each, ``count`` of them: ``uint32 hash``, ``uint32 length``,
  ``uint32 end_offset`` (a running end-offset into the string pool, i.e. the
  position just past the last character / at the NUL terminator).
* String pool: NUL-terminated ASCII.  A symbol's text is
  ``pool[base + end_offset - length : base + end_offset]``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_HEADER = struct.Struct("<III")
_RECORD = struct.Struct("<III")


@dataclass(frozen=True)
class Symbol:
    index: int
    name: str
    hash: int


class SymbolTable:
    """Loads and indexes a Firehawk binary symbol table."""

    def __init__(self, symbols: list[Symbol]):
        self._symbols = symbols
        self._by_name: dict[str, int] = {}
        for s in symbols:
            # First occurrence wins; names are effectively unique in practice.
            self._by_name.setdefault(s.name, s.index)

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_bytes(cls, data: bytes) -> "SymbolTable":
        if len(data) < _HEADER.size:
            raise ValueError("symbol table too small to contain a header")
        count, _file_size, _reserved = _HEADER.unpack_from(data, 0)
        records_end = _HEADER.size + count * _RECORD.size
        if records_end > len(data):
            raise ValueError("symbol table truncated: record array exceeds file")
        records = [
            _RECORD.unpack_from(data, _HEADER.size + i * _RECORD.size)
            for i in range(count)
        ]
        base = cls._solve_base(data, records, records_end)
        symbols = []
        for i, (hash_, length, end) in enumerate(records):
            start = base + end - length
            stop = base + end
            name = data[start:stop].decode("latin1") if 0 <= start <= stop <= len(data) else ""
            symbols.append(Symbol(index=i, name=name, hash=hash_))
        return cls(symbols)

    @classmethod
    def load(cls, path: str | Path) -> "SymbolTable":
        return cls.from_bytes(Path(path).read_bytes())

    @staticmethod
    def _solve_base(data: bytes, records: list[tuple[int, int, int]], records_end: int) -> int:
        """Find the string-pool base that decodes the most valid symbols.

        A symbol is "valid" when its bytes are printable ASCII and immediately
        followed by a NUL terminator.  Scanning a small window around the record
        array's end reliably locks onto the correct base for every known variant.
        """
        best_base, best_score = records_end, -1
        for candidate in range(records_end - 16, records_end + 16):
            score = 0
            for _hash, length, end in records:
                start, stop = candidate + end - length, candidate + end
                if start < 0 or stop >= len(data) or length == 0:
                    continue
                if data[stop] != 0x00:
                    continue
                chunk = data[start:stop]
                if chunk and all(0x20 <= b < 0x7F for b in chunk):
                    score += 1
            if score > best_score:
                best_base, best_score = candidate, score
        return best_base

    # -- access ---------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._symbols)

    def __iter__(self):
        return iter(self._symbols)

    def name(self, index: int) -> str:
        """Symbol name for a table index."""
        return self._symbols[index].name

    def index(self, name: str) -> int | None:
        """Table index for a symbol name, or None if absent."""
        return self._by_name.get(name)

    def hash(self, index: int) -> int:
        return self._symbols[index].hash

    @property
    def symbols(self) -> list[Symbol]:
        return list(self._symbols)

    def valid_count(self) -> int:
        """Number of non-empty, printable symbols (diagnostic)."""
        return sum(1 for s in self._symbols if s.name and s.name.isprintable())
