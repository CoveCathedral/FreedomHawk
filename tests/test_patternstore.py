"""Tests for pattern lines, mix-and-match voices, and the saved-pattern store."""

import pytest

np = pytest.importorskip("numpy")

from sequin.practice import GENRE_PATTERNS, Pattern
from sequin.practice import patternstore as ps


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
    from sequin.practice import LEVEL_ACCENT, LEVEL_GHOST
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


def test_chance_steps_save_with_the_pattern():
    # Per-step probability survives the record round trip — including the JSON habit
    # of turning dict keys into strings (settings and .fhdrum.json files).
    import json
    lines = [ps.make_line("kick")]
    lines[0]["steps"] = [0, 8]
    p = ps.lines_to_pattern(lines, 4, 4, 4, 1, name="maybe")
    p.set_chance("kick", 8, 60)
    rec = ps.make_record("maybe", "Test", 4, 4, 4, 1, lines, p)
    assert rec["lines"][0]["chances"] == {"8": 60}
    rt = json.loads(json.dumps(rec))          # a JSON round trip, like settings storage
    back = ps.record_to_pattern(rt)
    assert back.chance_of("kick", 8) == 60 and back.chance_of("kick", 0) is None
    # Old records without the key read as always-play, not an error.
    del rt["lines"][0]["chances"]
    assert not ps.record_to_pattern(rt).probs


def test_ornaments_save_with_the_pattern():
    import json
    lines = [ps.make_line("snare")]
    lines[0]["steps"] = [4]
    p = ps.lines_to_pattern(lines, 4, 4, 4, 1, name="ruff")
    p.set_ornament("snare", 4, "drag")
    rec = ps.make_record("ruff", "Test", 4, 4, 4, 1, lines, p)
    assert rec["lines"][0]["ornaments"] == {"4": "drag"}
    back = ps.record_to_pattern(json.loads(json.dumps(rec)))
    assert back.ornament_of("snare", 4) == "drag"
    # An unknown ornament name (a future version's?) is dropped, not crashed on.
    rec["lines"][0]["ornaments"] = {"4": "sizzle"}
    assert not ps.record_to_pattern(rec).ornaments


def test_feel_saves_with_the_pattern():
    # Swing/humanize are a groove's own feel; they must survive the record round trip.
    lines = [ps.make_line("kick")]
    lines[0]["steps"] = [0, 8]
    p = ps.lines_to_pattern(lines, 4, 4, 4, 1, name="shuffle")
    p.swing = 0.6
    p.humanize = 0.25
    rec = ps.make_record("shuffle", "Test", 4, 4, 4, 1, lines, p)
    assert rec["swing"] == 0.6 and rec["humanize"] == 0.25
    back = ps.record_to_pattern(rec)
    assert back.swing == 0.6 and back.humanize == 0.25
    # A record without feel keys (older saves) reads as straight, not an error.
    del rec["swing"], rec["humanize"]
    plain = ps.record_to_pattern(rec)
    assert plain.swing == 0.0 and plain.humanize == 0.0


def test_build_line_kit_follow_global_vs_explicit(tmp_path):
    import numpy as np
    from sequin.practice import DrumKit
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
    from sequin.practice import synth_kit, Pattern
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
    from sequin.practice import DrumKit
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


def test_song_store_resolve_save_load(tmp_path, monkeypatch):
    import firehawk.config as config
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "s.json")
    from firehawk.config import AppSettings
    s = AppSettings()
    # resolve a built-in groove by name; missing -> None
    assert ps.resolve_pattern_by_name("Rock", s).name == "Rock"
    assert ps.resolve_pattern_by_name("Nope!!", s) is None
    # a saved user pattern resolves too, and takes precedence for its name
    rec = ps.make_record("MyGroove", "Mine", 4, 4, 4, 1,
                         [dict(ps.make_line("kick"), steps=[0, 8])], Pattern("x", 16, 4, {"kick": [0, 8]}))
    ps.save_user_pattern(s, rec)
    assert ps.resolve_pattern_by_name("MyGroove", s) is not None
    # song save/load/delete + section resolution (skips a missing pattern), with a
    # per-section tempo and an inline (edited-in-place) section round-tripping.
    inline_rec = ps.make_record("verse", "Song", 4, 4, 4, 1,
                                [dict(ps.make_line("kick"), steps=[0, 4, 8, 12])],
                                Pattern("x", 16, 4, {"kick": [0, 4, 8, 12]}))
    song = ps.make_song_record("Song 1", [
        {"pattern": "Rock", "repeats": 2, "tempo": 150,
         "swing": 0, "fill": "improv", "fill_amount": 75},
        {"pattern": "MyGroove", "repeats": 1, "inline": inline_rec},
        {"pattern": "Ghost", "repeats": 4}])           # missing -> skipped
    ps.save_song(s, song)
    assert [r["name"] for r in ps.user_songs(s)] == ["Song 1"]
    # Song-wide polymeter-tails choice round-trips; contained (False) is the default.
    assert ps.user_songs(s)[0]["poly_tails"] is False
    loose = ps.make_song_record("Song 2", [{"pattern": "Rock", "repeats": 1}],
                                poly_tails=True)
    ps.save_song(s, loose)
    assert next(r for r in ps.user_songs(s)
                if r["name"] == "Song 2")["poly_tails"] is True
    ps.delete_song(s, "Song 2")
    saved = ps.user_songs(s)[0]["sections"]
    assert saved[0]["tempo"] == 150 and saved[1]["inline"] is not None
    # Swing 0 is a real override (force straight), distinct from None (groove's own);
    # fill style and amount round-trip with the song.
    assert saved[0]["swing"] == 0 and saved[0]["fill"] == "improv"
    assert saved[0]["fill_amount"] == 75
    assert saved[1]["swing"] is None and saved[1]["fill"] is None
    resolved = ps.song_sections(ps.user_songs(s)[0], s)
    assert [(p.name, r, tempo) for p, r, tempo, _kit in resolved] == \
        [("Rock", 2, 150), ("verse", 1, None)]         # inline resolved to its own pattern
    assert ps.delete_song(s, "Song 1") and ps.user_songs(s) == []


def test_inline_record_round_trips_a_pattern():
    p = Pattern("Verse", 16, 4, {"kick": [0, 8], "snare": [4, 12]}, 4, 4, 1,
                {"snare": {4: ps.LEVEL_ACCENT}})
    rec = ps.inline_record_from_pattern(p)
    back = ps.record_to_pattern(rec)
    assert back.hits["kick"] == [0, 8] and back.hits["snare"] == [4, 12]
    assert back.levels.get("snare") == {4: ps.LEVEL_ACCENT}
    assert back.steps == 16 and back.meter_label() == "4/4"


def test_split_section_repeat_isolates_one_repeat():
    p = Pattern("Verse", 16, 4, {"kick": [0]}, 4, 4, 1)
    sections = [{"pattern": "Verse", "repeats": 4, "inline": ps.inline_record_from_pattern(p)}]
    new, vi = ps.split_section_repeat(sections, 0, 1)   # split off the 2nd repeat
    assert [s["repeats"] for s in new] == [1, 1, 2]     # before x1, variant x1, after x2
    assert vi == 1 and new[vi]["inline"] is not None
    # Editing the variant's inline pattern must not change the before/after repeats.
    variant_pat = ps.record_to_pattern(new[vi]["inline"])
    variant_pat.hits["snare"] = [8]
    new[vi]["inline"] = ps.inline_record_from_pattern(variant_pat)
    assert "snare" not in ps.resolve_section_pattern(new[0], None).hits
    assert ps.resolve_section_pattern(new[vi], None).hits.get("snare") == [8]
    # Splitting the first repeat yields no "before" section.
    new2, vi2 = ps.split_section_repeat(sections, 0, 0)
    assert [s["repeats"] for s in new2] == [1, 3] and vi2 == 0


def test_split_section_repeat_preserves_fractional_repeats():
    # A x2.5 section must not lose its half when a repeat is split off — the pieces still
    # add up to 2.5, so the song's length is unchanged.
    p = Pattern("Verse", 16, 4, {"kick": [0]}, 4, 4, 1)
    sections = [{"pattern": "Verse", "repeats": 2.5,
                 "inline": ps.inline_record_from_pattern(p)}]
    new, vi = ps.split_section_repeat(sections, 0, 1)
    assert [s["repeats"] for s in new] == [1, 1, 0.5] and vi == 1
    assert sum(s["repeats"] for s in new) == 2.5
    new0, vi0 = ps.split_section_repeat(sections, 0, 0)
    assert [s["repeats"] for s in new0] == [1, 1.5] and vi0 == 0
    # Splitting from the fractional TAIL (repeat index == whole) isolates the half itself,
    # not the last whole repeat — and the total still adds to 2.5.
    tail, vt = ps.split_section_repeat(sections, 0, 2)
    assert [s["repeats"] for s in tail] == [2, 0.5] and vt == 1
    assert sum(s["repeats"] for s in tail) == 2.5


def test_inline_record_preserves_per_line_properties():
    # A song-wide beat edit changes hits, but must NOT wipe a line's kit/sample/tune/etc.
    base = ps.make_record(
        "Chorus", "Song", 4, 4, 4, 1,
        [dict(ps.make_line("808"), sample="my808.wav", tune=2, gain_db=-3, choke=2)],
        Pattern("x", 16, 4, {"808": [0, 8]}))
    edited = ps.record_to_pattern(base)
    edited.hits["808"] = [0, 4, 8, 12]                 # the beat editor changed the hits
    rec = ps.inline_record_from_pattern(edited, base_record=base)
    line = next(ln for ln in rec["lines"] if ln["id"] == "808")
    assert line["sample"] == "my808.wav" and line["tune"] == 2 and line["gain_db"] == -3
    assert line["choke"] == 2
    assert line["steps"] == [0, 4, 8, 12]              # the edit landed
    # A part the edit newly introduced gets a fresh line.
    edited.hits["cowbell"] = [4]
    rec2 = ps.inline_record_from_pattern(edited, base_record=base)
    assert any(ln["id"] == "cowbell" and ln["steps"] == [4] for ln in rec2["lines"])


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


def test_lines_for_kit_auto_chokes_played_hats():
    from sequin.practice import synth_kit
    both = Pattern("t", 16, 4, {"hihat": [0, 4], "openhat": [8], "kick": [0]}, 4, 4, 1)
    m = {ln["id"]: ln.get("choke", 0) for ln in ps.lines_for_kit(both, synth_kit(), None)}
    assert m["hihat"] == 1 and m["openhat"] == 1     # closed hat chokes the open hat
    assert m["kick"] == 0
    # A groove that only plays closed hats is left untouched (nothing ringing to cut).
    closed = Pattern("t", 16, 4, {"hihat": [0, 4], "kick": [0]}, 4, 4, 1)
    m2 = {ln["id"]: ln.get("choke", 0) for ln in ps.lines_for_kit(closed, synth_kit(), None)}
    assert m2["hihat"] == 0 and m2.get("openhat", 0) == 0


def test_lines_for_kit_covers_pattern_and_kit():
    from sequin.practice import synth_kit
    p = Pattern("t", 16, 4, {"kick": [0], "fx": [4]}, 4, 4, 1)
    lines = ps.lines_for_kit(p, synth_kit(), None)
    ids = [ln["id"] for ln in lines]
    assert "kick" in ids and "fx" in ids          # pattern roles present
    assert "snare" in ids and "hihat" in ids and "openhat" in ids   # core parts too
    kick = next(ln for ln in lines if ln["id"] == "kick")
    assert kick["steps"] == [0]


def test_lines_for_kit_curates_to_used_plus_core():
    # The full standard kit has ~two dozen voices; the editor must NOT dump all of them
    # as empty lines. Only the parts the pattern uses plus a small core are shown.
    from sequin.practice import synth_kit
    p = Pattern("t", 16, 4, {"kick": [0], "tom5": [8]}, 4, 4, 1)
    ids = [ln["id"] for ln in ps.lines_for_kit(p, synth_kit(), None)]
    assert set(ids) == {"kick", "snare", "hihat", "openhat", "tom5"}
    assert "cowbell" not in ids and "ride" not in ids and "crash2" not in ids
    # Order follows the canonical ROLES order (floor tom after the hats).
    assert ids.index("tom5") == len(ids) - 1
