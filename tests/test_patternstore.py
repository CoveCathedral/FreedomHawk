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
    lines = [ps.make_line("kick"), ps.make_line("snare")]
    lines[0]["steps"] = [0, 8]
    lines[1]["steps"] = [4, 12, 99]  # out-of-range step is dropped
    p = ps.lines_to_pattern(lines, 4, 4, 4, 1, name="t")
    assert p.steps == 16
    assert p.hits == {"kick": [0, 8], "snare": [4, 12]}
    rec = ps.make_record("t", "Test", 4, 4, 4, 1, lines, p)
    back = ps.record_to_pattern(rec)
    assert back.hits == p.hits and back.meter_label() == "4/4"


def test_build_line_kit_stacks_and_falls_back(tmp_path):
    # Two kick lines: both resolve to voices (synth fallback for missing kit).
    lines = [ps.make_line("kick"), ps.make_line("kick", "NoSuchKit", None, existing=None)]
    lines[1]["id"] = "kick 2"
    kit = ps.build_line_kit(lines, tmp_path)
    assert kit.voice("kick") is not None
    assert kit.voice("kick 2") is not None  # missing kit -> synth voice
    # Canonical fill roles are covered even though no line uses them.
    assert kit.voice("snare") is not None and kit.voice("crash") is not None


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


def test_lines_for_kit_covers_pattern_and_kit():
    from firehawk.practice import synth_kit
    p = Pattern("t", 16, 4, {"kick": [0], "fx": [4]}, 4, 4, 1)
    lines = ps.lines_for_kit(p, synth_kit(), None)
    ids = [ln["id"] for ln in lines]
    assert "kick" in ids and "fx" in ids          # pattern roles present
    assert "snare" in ids                          # kit roles present too
    kick = next(ln for ln in lines if ln["id"] == "kick")
    assert kick["steps"] == [0]
