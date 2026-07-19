"""Pitch estimation and per-line tuning."""
import numpy as np
import pytest

from sequin.practice import drums
from sequin.practice.pitch import (
    estimate_pitch,
    note_from_freq,
    note_name_for_semitones,
    role_fmax,
)


def test_note_from_freq_reference_pitches():
    assert note_from_freq(440.0)[0] == "A4"
    assert abs(note_from_freq(440.0)[1]) < 0.5          # exactly on A4
    assert note_from_freq(261.63)[0] == "C4"            # middle C
    assert note_from_freq(49.0)[0] == "G1"              # a low 808 region


def test_note_from_freq_cents_sign():
    # A hair sharp of A4 reports a positive cents offset, flat reports negative.
    assert note_from_freq(445.0)[1] > 0
    assert note_from_freq(435.0)[1] < 0


def test_semitone_shift_names():
    # 440 Hz is A4; up 3 semitones is C5, down 2 is G4.
    assert note_name_for_semitones(440.0, 3) == "C5"
    assert note_name_for_semitones(440.0, -2) == "G4"
    assert note_name_for_semitones(440.0, 12) == "A5"


def test_pitched_drums_resolve_to_a_note():
    # A pure-tone tom and the sub-bass 808 have a clear fundamental.
    for synth in (drums.synth_tom, drums.synth_808):
        p = estimate_pitch(synth(drums.RATE), drums.RATE)
        assert p is not None and p.pitched
        assert 20.0 < p.freq_hz < 800.0


def test_noise_drums_read_unpitched():
    # Hats and cymbals are noise: no confident fundamental.
    for synth in (drums.synth_hihat, drums.synth_openhat, drums.synth_crash):
        p = estimate_pitch(synth(drums.RATE), drums.RATE)
        assert p is None or not p.pitched


def test_synth_tom_is_about_the_right_note():
    # The synth tom settles around 90-110 Hz; accept the octave it lands in.
    p = estimate_pitch(drums.synth_tom(drums.RATE), drums.RATE, role="tom")
    assert p is not None and p.note[0] in "AG" and p.note[-1] in "23"


def test_role_bounds_keep_a_kick_in_the_sub_bass():
    assert role_fmax("kick") <= 200.0
    assert role_fmax("808") <= 200.0
    assert role_fmax(None) > role_fmax("kick")   # unknown roles search wider


def test_estimate_pitch_handles_degenerate_input():
    assert estimate_pitch(np.zeros(2000, dtype=np.float32), drums.RATE) is None
    assert estimate_pitch(np.zeros(3, dtype=np.float32), drums.RATE) is None


def test_resample_pitch_shifts_frequency_and_length():
    tom = drums.synth_tom(drums.RATE)
    up = drums.resample_pitch(tom, 12)               # up an octave
    assert len(up) == pytest.approx(len(tom) / 2, rel=0.02)   # half as long
    base = estimate_pitch(tom, drums.RATE, role="tom")
    shifted = estimate_pitch(up, drums.RATE)
    assert base and shifted
    assert shifted.freq_hz == pytest.approx(base.freq_hz * 2, rel=0.06)


def test_resample_pitch_zero_is_identity():
    tom = drums.synth_tom(drums.RATE)
    assert drums.resample_pitch(tom, 0) is tom
