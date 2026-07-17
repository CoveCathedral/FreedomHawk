"""Tests for pattern lines, mix-and-match voices, and the saved-pattern store."""

import pytest

np = pytest.importorskip("numpy")

from firehawk.practice import GENRE_PATTERNS, Pattern
from firehawk.practice import patternstore as ps


class _StubSettings:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def test_make_line_unique_ids_and_labels():
    a = ps.make_line("kick")
    b = ps.make_line("kick", existing=[a])
    c = ps.make_line("kick", "MyKit", "x.wav", existing=[a, b])
    assert [a["id"], b["id"], c["id"]] == ["kick", "kick 2", "kick 3"]
    assert b["label"] == "Kick 2"
    assert c["label"] == "Kick 3 (MyKit)"


def test_lines_pattern_round_trip():
    from firehawk.practice import LEVEL_ACCENT, LEVEL_GHOST
    lines = [ps.make_line("kick"), ps.make_line("snare")]
    lines[0]["steps"] = [0, 8]
    lines[1]["steps"] = [4, 12, 99]  # out-of-range step is dropped
    p = ps.lines_to_pattern(lines, 4, 4, 4, 1, name="t")
    assert p.steps == 16
    assert p.hits == {"kick": [0, 8], "snare": [4, 12]}
    # Dynamics survive the record round trip.
    p.set_level("kick", 0, LEVEL_ACCENT)
    p.set_level("snare", 12, LEVEL_GHOST)
    rec = ps.make_record("t", "Test", 4, 4, 4, 1, lines, p)
    assert rec["lines"][0]["accents"] == [0]
    assert rec["lines"][1]["ghosts"] == [12]
    back = ps.record_to_pattern(rec)
    assert back.hits == p.hits and back.meter_label() == "4/4"
    assert back.levels == {"kick": {0: LEVEL_ACCENT}, "snare": {12: LEVEL_GHOST}}


def test_build_line_kit_follow_global_vs_explicit(tmp_path):
    import numpy as np
    from firehawk.practice import DrumKit
    # A distinct "global" kit: a kick voice that is clearly not the synth kick.
    global_kick = np.full(3000, 0.5, dtype=np.float32)
    global_kit = DrumKit("Global", {"kick": global_kick})
    # kit=None follows the global kit; SYNTH_KIT_NAME is explicitly the synth.
    follow = [ps.make_line("kick")]              # kit None
    synth_line = [dict(ps.make_line("kick"), kit=ps.SYNTH_KIT_NAME)]
    kf = ps.build_line_kit(follow, tmp_path, base_kit=global_kit)
    ks = ps.build_line_kit(synth_line, tmp_path, base_kit=global_kit)
    assert np.array_equal(kf.voice("kick"), global_kick)          # followed the global kit
    assert not np.array_equal(ks.voice("kick"), global_kick)      # explicit synth, not global
    # With no global kit, follow falls back to synth (never silent).
    assert ps.build_line_kit(follow, tmp_path).voice("kick") is not None


def test_lines_for_kit_lines_follow_global(tmp_path):
    from firehawk.practice import synth_kit, Pattern
    p = Pattern("t", 16, 4, {"kick": [0]}, 4, 4, 1)
    lines = ps.lines_for_kit(p, synth_kit(), "SomeKit")
    assert all(ln["kit"] is None for ln in lines)  # follow global, not baked to SomeKit


def test_build_line_kit_stacks_and_falls_back(tmp_path):
    # Two kick lines: both resolve to voices (synth fallback for missing kit).
    lines = [ps.make_line("kick"), ps.make_line("kick", "NoSuchKit", None, existing=None)]
    lines[1]["id"] = "kick 2"
    kit = ps.build_line_kit(lines, tmp_path)
    assert kit.voice("kick") is not None
    assert kit.voice("kick 2") is not None  # missing kit -> synth voice
    # Canonical fill roles are covered even though no line uses them.
    assert kit.voice("snare") is not None and kit.voice("crash") is not None


def test_build_line_kit_bakes_tune_and_gain(tmp_path):
    import numpy as np
    from firehawk.practice import DrumKit
    tone = np.sin(2 * np.pi * 100.0 * np.arange(4000) / 44100).astype(np.float32)
    base_kit = DrumKit("Base", {"kick": tone})
    plain = ps.build_line_kit([ps.make_line("kick")], tmp_path, base_kit=base_kit)
    assert np.array_equal(plain.voice("kick"), tone)              # untuned, unity gain

    up = ps.build_line_kit([dict(ps.make_line("kick"), tune=12)], tmp_path, base_kit=base_kit)
    assert len(up.voice("kick")) == pytest.approx(len(tone) / 2, rel=0.02)  # octave up

    quiet = ps.build_line_kit([dict(ps.make_line("kick"), gain_db=-6)], tmp_path, base_kit=base_kit)
    ratio = float(np.max(np.abs(quiet.voice("kick"))) / np.max(np.abs(tone)))
    assert ratio == pytest.approx(ps.gain_from_db(-6), rel=0.01)   # -6 dB ~= 0.5x


def test_clamp_helpers_bound_tune_and_gain():
    assert ps.clamp_tune(999) == ps.MAX_TUNE
    assert ps.clamp_tune(-999) == -ps.MAX_TUNE
    assert ps.clamp_tune("bad") == 0
    assert ps.clamp_gain_db(999) == ps.MAX_GAIN_DB
    assert ps.clamp_gain_db(-999) == ps.MIN_GAIN_DB
    assert ps.clamp_gain_db(None) == 0
    assert ps.clamp_choke(99) == ps.MAX_CHOKE_GROUP
    assert ps.clamp_choke(-1) == 0
    assert ps.clamp_choke("x") == 0


def test_choke_map_skips_ungrouped_lines():
    lines = [dict(ps.make_line("openhat"), choke=1),
             dict(ps.make_line("hihat"), choke=1),
             dict(ps.make_line("kick"))]              # no choke
    m = ps.choke_map(lines)
    assert m == {"openhat": 1, "hihat": 1}            # kick omitted


def test_pattern_file_carries_tune_gain_and_choke(tmp_path):
    line = dict(ps.make_line("openhat"), steps=[0, 8], tune=3, gain_db=-4, choke=2)
    pattern = ps.lines_to_pattern([line], 4, 4, 4, 1)
    record = ps.make_record("mix", "Imported", 4, 4, 4, 1, [line], pattern)
    back = ps.record_from_file_dict(ps.record_to_file_dict(record))
    assert back["lines"][0]["tune"] == 3
    assert back["lines"][0]["gain_db"] == -4
    assert back["lines"][0]["choke"] == 2


def test_builtin_category():
    assert ps.builtin_category("Rock") == "Rock"
    assert ps.builtin_category("Rock 04 fill") == "Rock"
    assert ps.builtin_category("7/8 (2+2+3) 03") == "7/8 (2+2+3)"


def test_store_save_replace_and_categories():
    s = _StubSettings()
    assert ps.user_patterns(s) == []
    rec = {"name": "A", "category": "Prog", "beats": 4, "unit": 4, "grid": 4,
           "bars": 1, "lines": []}
    ps.save_user_pattern(s, rec)
    ps.save_user_pattern(s, dict(rec, category="Djent"))  # same name replaces
    assert len(ps.user_patterns(s)) == 1
    assert ps.user_patterns(s)[0]["category"] == "Djent"
    cats = ps.all_categories(s)
    assert "Djent" in cats
    assert all(p.name in cats for p in GENRE_PATTERNS)


def _seed(s, name="A", category="Prog"):
    rec = {"name": name, "category": category, "beats": 4, "unit": 4, "grid": 4,
           "bars": 1, "lines": [dict(ps.make_line("kick"), steps=[0])]}
    ps.save_user_pattern(s, rec)
    return rec


def test_library_management_ops():
    s = _StubSettings()
    _seed(s, "A", "Prog")
    _seed(s, "B", "Prog")
    # Rename (with collision protection).
    assert ps.rename_pattern(s, "A", "Alpha")
    assert not ps.rename_pattern(s, "B", "Alpha")  # name taken
    assert not ps.rename_pattern(s, "missing", "X")
    # Category change and whole-category rename.
    assert ps.set_pattern_category(s, "Alpha", "Djent")
    assert ps.rename_category(s, "Prog", "Progressive") == 1  # only B
    cats = {r["category"] for r in ps.user_patterns(s)}
    assert cats == {"Djent", "Progressive"}
    # Delete.
    assert ps.delete_pattern(s, "Alpha")
    assert not ps.delete_pattern(s, "Alpha")
    assert [r["name"] for r in ps.user_patterns(s)] == ["B"]


def test_pattern_file_round_trip_and_validation():
    import json
    s = _StubSettings()
    rec = _seed(s)
    doc = ps.record_to_file_dict(rec)
    back = ps.record_from_file_dict(json.loads(json.dumps(doc)))
    assert back["name"] == rec["name"]
    assert back["lines"][0]["steps"] == [0]
    # Malformed documents are rejected with readable reasons.
    for bad in ({}, {"format": "wrong"},
                dict(doc, name=""),
                dict(doc, lines=[]),
                dict(doc, beats="lots")):
        with pytest.raises(ValueError):
            ps.record_from_file_dict(bad)
    # Out-of-range steps and unknown roles are sanitized, not fatal.
    weird = dict(doc, lines=[{"id": "z", "role": "kazoo", "steps": [0, 999]}])
    clean = ps.record_from_file_dict(weird)
    assert clean["lines"][0]["role"] == "perc"
    assert clean["lines"][0]["steps"] == [0]


def test_polymeter_length_round_trips():
    import json
    lines = [ps.make_line("kick"), ps.make_line("hihat")]
    lines[0]["steps"] = [0, 3, 5]
    lines[1]["steps"] = [0, 4, 8, 12]
    p = ps.lines_to_pattern(lines, 4, 4, 4, 1, name="poly")
    p.set_line_length(lines[0]["id"], 7)
    rec = ps.make_record("poly", "Prog", 4, 4, 4, 1, lines, p)
    assert rec["lines"][0]["length"] == 7 and rec["lines"][1]["length"] is None
    back = ps.record_to_pattern(rec)
    assert back.line_length("kick") == 7 and back.is_polymetric()
    # File round trip and validation.
    doc = ps.record_to_file_dict(rec)
    rt = ps.record_from_file_dict(json.loads(json.dumps(doc)))
    assert ps.record_to_pattern(rt).line_length("kick") == 7
    weird = dict(doc, lines=[dict(doc["lines"][0], length=999)])  # out of range
    assert ps.record_from_file_dict(weird)["lines"][0]["length"] is None


def test_lines_for_kit_covers_pattern_and_kit():
    from firehawk.practice import synth_kit
    p = Pattern("t", 16, 4, {"kick": [0], "fx": [4]}, 4, 4, 1)
    lines = ps.lines_for_kit(p, synth_kit(), None)
    ids = [ln["id"] for ln in lines]
    assert "kick" in ids and "fx" in ids          # pattern roles present
    assert "snare" in ids                          # kit roles present too
    kick = next(ln for ln in lines if ln["id"] == "kick")
    assert kick["steps"] == [0]
