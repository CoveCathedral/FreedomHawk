"""Tests for MIDI export/import: round trips, GM mapping, meter, malformed data."""

import pytest

np = pytest.importorskip("numpy")

from sequin.practice import PATTERN_LIBRARY, Pattern
from sequin.practice.midifile import (
    GM_TO_ROLE,
    ROLE_TO_GM,
    midi_to_pattern,
    pattern_to_midi,
)


def test_dynamics_round_trip_as_velocities():
    from sequin.practice import LEVEL_ACCENT, LEVEL_GHOST
    p = Pattern("t", 16, 4, {"snare": [0, 4, 8]}, 4, 4, 1,
                {"snare": {0: LEVEL_ACCENT, 8: LEVEL_GHOST}})
    back, _ = midi_to_pattern(pattern_to_midi(p, 120))
    assert back.hits["snare"] == [0, 4, 8]
    assert back.levels.get("snare") == {0: LEVEL_ACCENT, 8: LEVEL_GHOST}


def test_full_kit_roles_round_trip_through_gm():
    # Every part of the full standard kit maps to a distinct GM note and comes back to a
    # sensible role (the granular toms/cymbals survive an export/import round trip).
    for role in ("kick", "snare", "rimshot", "clap", "hihat", "pedalhat", "openhat",
                 "tom1", "tom2", "tom", "tom4", "tom5", "crash", "crash2", "splash",
                 "china", "ride", "ridebell", "cowbell", "tambourine", "shaker"):
        note = ROLE_TO_GM[role]
        assert GM_TO_ROLE[note] == role          # exact round trip for these
    p = Pattern("t", 16, 4, {"tom1": [0], "tom5": [4], "crash2": [8], "cowbell": [12]},
                4, 4, 1)
    back, _ = midi_to_pattern(pattern_to_midi(p, 120))
    assert set(back.hits) == {"tom1", "tom5", "crash2", "cowbell"}


def test_round_trip_preserves_hits_and_meter():
    rock = PATTERN_LIBRARY[0]
    back, info = midi_to_pattern(pattern_to_midi(rock, 120))
    assert back.meter_label() == "4/4" and back.steps == rock.steps
    for role in ("kick", "snare", "hihat"):
        assert back.hits[role] == rock.hits[role]
    assert info["notes"] == sum(len(s) for s in rock.hits.values())


def test_round_trip_odd_meter():
    seven = next(p for p in PATTERN_LIBRARY if p.name.startswith("7/8"))
    back, _ = midi_to_pattern(pattern_to_midi(seven, 140), grid=2)
    assert back.meter_label() == "7/8" and back.steps == seven.steps
    assert back.hits["kick"] == seven.hits["kick"]


def test_custom_line_ids_export_via_role_map():
    p = Pattern("t", 16, 4, {"kick 2": [0, 8]}, 4, 4, 1)
    mid = pattern_to_midi(p, 120, role_of={"kick 2": "kick"})
    back, _ = midi_to_pattern(mid)
    assert back.hits["kick"] == [0, 8]  # stacked line comes back as its role


def test_gm_maps_are_consistent():
    # GM has no "808" or "fx" concept, so those export to the nearest drum (bass
    # drum / splash) and deliberately come back as kick / crash.
    lossy = {"808", "fx"}
    for role, note in ROLE_TO_GM.items():
        if role not in lossy and note in GM_TO_ROLE:
            assert GM_TO_ROLE[note] == role, role


def test_multibar_import_caps_at_four_bars():
    p = Pattern("t", 32, 4, {"kick": [0, 16, 31]}, 4, 4, 2)
    back, info = midi_to_pattern(pattern_to_midi(p, 100))
    assert back.bars == 2 and back.hits["kick"] == [0, 16, 31]
    assert "dropped" not in info


def test_malformed_midi_rejected():
    with pytest.raises(ValueError):
        midi_to_pattern(b"not a midi file at all")
    with pytest.raises(ValueError):
        midi_to_pattern(b"MThd" + b"\x00" * 20)  # header only, no notes


def test_empty_pattern_exports_but_reimport_fails():
    p = Pattern("t", 16, 4, {}, 4, 4, 1)
    mid = pattern_to_midi(p, 120)
    assert mid[:4] == b"MThd"
    with pytest.raises(ValueError):
        midi_to_pattern(mid)  # no notes to import
