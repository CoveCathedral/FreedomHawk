"""Instrument and tuning library for the by-ear tuner.

Each tuning is a list of note names from the lowest (thickest) string to the highest.
Covers 6/7/8-string guitar and 4/5/6-string bass, from standard to alternate, open,
drop, and modal/sus tunings.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str
    strings: int
    tunings: dict[str, list[str]]  # tuning name -> notes low..high


GUITAR_6 = Instrument("6-String Guitar", 6, {
    "Standard (E A D G B E)": ["E2", "A2", "D3", "G3", "B3", "E4"],
    "Half Step Down (Eb)": ["Eb2", "Ab2", "Db3", "Gb3", "Bb3", "Eb4"],
    "Whole Step Down (D)": ["D2", "G2", "C3", "F3", "A3", "D4"],
    "Drop D": ["D2", "A2", "D3", "G3", "B3", "E4"],
    "Drop C#": ["C#2", "G#2", "C#3", "F#3", "A#3", "D#4"],
    "Drop C": ["C2", "G2", "C3", "F3", "A3", "D4"],
    "Drop B": ["B1", "F#2", "B2", "E3", "G#3", "C#4"],
    "Double Drop D": ["D2", "A2", "D3", "G3", "B3", "D4"],
    "DADGAD": ["D2", "A2", "D3", "G3", "A3", "D4"],
    "Open D": ["D2", "A2", "D3", "F#3", "A3", "D4"],
    "Open D minor": ["D2", "A2", "D3", "F3", "A3", "D4"],
    "Open E": ["E2", "B2", "E3", "G#3", "B3", "E4"],
    "Open G": ["D2", "G2", "D3", "G3", "B3", "D4"],
    "Open G minor": ["D2", "G2", "D3", "G3", "Bb3", "D4"],
    "Open A": ["E2", "A2", "E3", "A3", "C#4", "E4"],
    "Open C": ["C2", "G2", "C3", "G3", "C4", "E4"],
    "All Fourths": ["E2", "A2", "D3", "G3", "C4", "F4"],
    "New Standard (C G D A E G)": ["C2", "G2", "D3", "A3", "E4", "G4"],
})

GUITAR_7 = Instrument("7-String Guitar", 7, {
    "Standard (B E A D G B E)": ["B1", "E2", "A2", "D3", "G3", "B3", "E4"],
    "Half Step Down": ["Bb1", "Eb2", "Ab2", "Db3", "Gb3", "Bb3", "Eb4"],
    "Whole Step Down": ["A1", "D2", "G2", "C3", "F3", "A3", "D4"],
    "Drop A": ["A1", "E2", "A2", "D3", "G3", "B3", "E4"],
    "Drop G#": ["G#1", "D#2", "G#2", "C#3", "F#3", "A#3", "D#4"],
    "Drop G": ["G1", "D2", "G2", "C3", "F3", "A3", "D4"],
})

GUITAR_8 = Instrument("8-String Guitar", 8, {
    "Standard (F# B E A D G B E)": ["F#1", "B1", "E2", "A2", "D3", "G3", "B3", "E4"],
    "Half Step Down": ["F1", "Bb1", "Eb2", "Ab2", "Db3", "Gb3", "Bb3", "Eb4"],
    "Whole Step Down": ["E1", "A1", "D2", "G2", "C3", "F3", "A3", "D4"],
    "Drop E": ["E1", "B1", "E2", "A2", "D3", "G3", "B3", "E4"],
    "Drop D#": ["D#1", "A#1", "D#2", "G#2", "C#3", "F#3", "A#3", "D#4"],
})

BASS_4 = Instrument("4-String Bass", 4, {
    "Standard (E A D G)": ["E1", "A1", "D2", "G2"],
    "Half Step Down (Eb)": ["Eb1", "Ab1", "Db2", "Gb2"],
    "Whole Step Down (D)": ["D1", "G1", "C2", "F2"],
    "Drop D": ["D1", "A1", "D2", "G2"],
    "Drop C#": ["C#1", "G#1", "C#2", "F#2"],
    "Drop C": ["C1", "G1", "C2", "F2"],
    "Tenor (A D G C)": ["A1", "D2", "G2", "C3"],
})

BASS_5 = Instrument("5-String Bass", 5, {
    "Standard (B E A D G)": ["B0", "E1", "A1", "D2", "G2"],
    "Half Step Down": ["Bb0", "Eb1", "Ab1", "Db2", "Gb2"],
    "Drop A": ["A0", "E1", "A1", "D2", "G2"],
    "Tenor (E A D G C)": ["E1", "A1", "D2", "G2", "C3"],
})

BASS_6 = Instrument("6-String Bass", 6, {
    "Standard (B E A D G C)": ["B0", "E1", "A1", "D2", "G2", "C3"],
    "Half Step Down": ["Bb0", "Eb1", "Ab1", "Db2", "Gb2", "B2"],
    "Drop A": ["A0", "E1", "A1", "D2", "G2", "C3"],
})

INSTRUMENTS: list[Instrument] = [GUITAR_6, GUITAR_7, GUITAR_8, BASS_4, BASS_5, BASS_6]
INSTRUMENTS_BY_NAME: dict[str, Instrument] = {i.name: i for i in INSTRUMENTS}
