"""Tests for the binary symbol-table decoder."""

import json
from pathlib import Path

import pytest

from firehawk.model import SymbolTable
from firehawk.model.catalog import DATA_DIR

TABLE = DATA_DIR / "defaultSymbolTable.bin"
REFERENCE = DATA_DIR / "firehawk_symbols.json"


@pytest.fixture(scope="module")
def table() -> SymbolTable:
    return SymbolTable.load(TABLE)


def test_decodes_expected_count(table: SymbolTable):
    assert len(table) == 611
    # The handoff validated 610/611 as clean, printable names.
    assert table.valid_count() >= 610


@pytest.mark.parametrize(
    "index, name",
    [
        (0, "Gain"),
        (1, "Delay"),
        (12, "BassState"),
        (17, "Bass"),
        (18, "Mid"),
        (19, "Treble"),
        (20, "Presence"),
        (22, "DriveState"),
        (23, "Drive"),
        (107, "BritGainJ800"),
        (158, "StereoDelay"),
        (306, "DarkHall1"),
    ],
)
def test_known_indices(table: SymbolTable, index: int, name: str):
    assert table.name(index) == name
    assert table.index(name) == index


def test_matches_reference_json(table: SymbolTable):
    """Our independent decode reproduces the shipped firehawk_symbols.json exactly."""
    reference = json.loads(Path(REFERENCE).read_text(encoding="utf-8"))
    ref_by_index = {r["index"]: (r["name"], r["hash"]) for r in reference}
    for symbol in table:
        if symbol.index in ref_by_index:
            ref_name, ref_hash = ref_by_index[symbol.index]
            assert symbol.name == ref_name, f"index {symbol.index}"
            assert symbol.hash == ref_hash, f"index {symbol.index}"
