"""Tests for the metronome engine: click timing, accent pattern, tap-tempo, audio."""

import pytest

from sequin.practice import (
    BEAT_UNITS,
    SUBDIVISIONS,
    TapTempo,
    beat_interval,
    click_kind,
    click_kind_grouped,
    click_wav,
    group_start_beats,
    parse_grouping,
)


def test_beat_interval():
    assert beat_interval(120, 1) == pytest.approx(0.5)
    assert beat_interval(120, 2) == pytest.approx(0.25)
    assert beat_interval(60, 1) == pytest.approx(1.0)
    assert beat_interval(90, 3) == pytest.approx(60 / 90 / 3)


def test_beat_interval_clamps_tempo():
    # Out-of-range tempo is clamped; the interval is never zero or negative.
    assert beat_interval(0, 1) == pytest.approx(beat_interval(30, 1))
    assert beat_interval(10_000, 1) == pytest.approx(beat_interval(300, 1))


def test_click_kind_4_4_eighths():
    # 4/4 with an eighth-note subdivision -> 8 ticks per measure.
    kinds = [click_kind(t, 4, 2) for t in range(8)]
    assert kinds == ["accent", "sub", "beat", "sub", "beat", "sub", "beat", "sub"]
    assert click_kind(8, 4, 2) == "accent"  # wraps to the next downbeat


def test_click_kind_quarter_notes():
    assert [click_kind(t, 4, 1) for t in range(4)] == ["accent", "beat", "beat", "beat"]


def test_click_wav_is_valid_wav():
    data = click_wav(1000.0, ms=35.0)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert len(data) > 200


def test_tap_tempo_averages_to_bpm():
    tap = TapTempo()
    assert tap.tap(0.0) is None                       # one tap isn't enough
    assert tap.tap(0.5) == pytest.approx(120, abs=1)  # 0.5 s apart -> 120 BPM
    assert tap.tap(1.0) == pytest.approx(120, abs=1)


def test_tap_tempo_resets_after_long_gap():
    tap = TapTempo(reset_gap=2.0)
    tap.tap(0.0)
    tap.tap(0.5)
    assert tap.tap(10.0) is None  # a long gap starts a fresh series


def test_subdivision_and_unit_tables():
    assert [ticks for _, ticks in SUBDIVISIONS] == [1, 2, 3, 4]
    assert BEAT_UNITS == [2, 4, 8, 16]


def test_parse_grouping():
    assert parse_grouping("2+2+3", 7) == [2, 2, 3]
    assert parse_grouping(" 3 + 2 ", 5) == [3, 2]
    assert parse_grouping("2+2+2", 7) is None   # doesn't add up to 7
    assert parse_grouping("", 7) is None         # empty
    assert parse_grouping("abc", 7) is None       # non-numeric


def test_group_start_beats():
    assert group_start_beats(7, [2, 2, 3]) == {0, 2, 4}
    assert group_start_beats(5, [3, 2]) == {0, 3}
    assert group_start_beats(7, None) == {0}      # default: only the downbeat


def test_click_kind_grouped_odd_meter():
    # 7/8 grouped 2+2+3, one click per eighth (subdivision 1): accents on beats 1, 3, 5.
    starts = group_start_beats(7, [2, 2, 3])
    kinds = [click_kind_grouped(t, 7, 1, starts) for t in range(7)]
    assert kinds == ["accent", "beat", "accent", "beat", "accent", "beat", "beat"]
