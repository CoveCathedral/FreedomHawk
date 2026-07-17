"""Tests for the by-ear tuner: note frequencies, tone generation, and tuning data."""

import struct

import pytest

from firehawk.tuner import INSTRUMENTS, INSTRUMENTS_BY_NAME, note_frequency, note_to_midi
from firehawk.tuner.tones import sine_wav


def test_note_to_midi():
    assert note_to_midi("A4") == 69
    assert note_to_midi("C4") == 60
    assert note_to_midi("E2") == 40
    assert note_to_midi("Eb2") == note_to_midi("D#2") == 39
    assert note_to_midi("B0") == 23


@pytest.mark.parametrize("note, hz", [
    ("A4", 440.0),
    ("A2", 110.0),
    ("E2", 82.41),     # low E, 6-string standard
    ("E4", 329.63),    # high E
    ("B0", 30.87),     # low B, 5-string bass
])
def test_note_frequency(note, hz):
    assert note_frequency(note) == pytest.approx(hz, abs=0.02)


def test_sine_wav_is_valid_wav():
    data = sine_wav(440.0)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    # non-trivial audio payload
    assert len(data) > 1000


def test_every_tuning_matches_string_count():
    for instrument in INSTRUMENTS:
        for name, notes in instrument.tunings.items():
            assert len(notes) == instrument.strings, f"{instrument.name} / {name}"
            for n in notes:
                note_frequency(n)  # every note name parses


def test_instrument_coverage():
    names = set(INSTRUMENTS_BY_NAME)
    assert {"6-String Guitar", "7-String Guitar", "8-String Guitar",
            "4-String Bass", "5-String Bass", "6-String Bass"} <= names
    g6 = INSTRUMENTS_BY_NAME["6-String Guitar"]
    assert g6.tunings["Standard (E A D G B E)"] == ["E2", "A2", "D3", "G3", "B3", "E4"]
    assert "DADGAD" in g6.tunings and "Drop D" in g6.tunings
