"""Tests for SongGrid — the flattened navigation model behind the song-wide beat editor."""

from sequin.practice.drums import Pattern
from sequin.practice.songgrid import SongGrid


def _song():
    # Verse: 4/4, 16 steps, played twice.  Chorus: 3/4, 12 steps, once.  Mixed meters.
    verse = Pattern("Verse", 16, 4, {"kick": [0]}, 4, 4, 1)
    chorus = Pattern("Chorus", 12, 4, {"snare": [0]}, 3, 4, 1)
    return SongGrid([(verse, 2, "Verse"), (chorus, 1, "Chorus")])


def test_layout_and_totals():
    g = _song()
    assert g.sections == 2
    assert g.total_steps == 16 * 2 + 12       # 44
    assert g.section_of(0) == 0 and g.section_of(31) == 0
    assert g.section_of(32) == 1 and g.section_of(43) == 1


def test_locate_maps_repeats_bars_beats():
    g = _song()
    a = g.locate(0)
    assert (a.section, a.repeat, a.bar, a.beat, a.step_in_pattern) == (0, 0, 0, 0, 0)
    # Step 16 is the top of the SECOND repeat of the verse — same pattern step 0.
    b = g.locate(16)
    assert (b.section, b.repeat, b.step_in_pattern) == (0, 1, 0)
    # Step 20 = repeat 2, beat 2 (0-based beat 1) of the verse.
    c = g.locate(20)
    assert (c.repeat, c.beat, c.step_in_pattern) == (1, 1, 4)
    # Into the chorus.
    d = g.locate(32)
    assert (d.section, d.repeat, d.step_in_pattern, d.meter) == (1, 0, 0, "3/4")
    e = g.locate(43)
    assert (e.bar, e.beat, e.step_in_beat) == (0, 2, 3)


def test_describe_reads_the_location():
    g = _song()
    # The section ordinal leads so two same-named sections can't be confused.
    assert g.describe(16) == "Section 1, Verse, repeat 2, bar 1, beat 1"
    assert g.describe(20) == "Section 1, Verse, repeat 2, bar 1, beat 2"
    # A once-through section omits the repeat; a sub-beat step is announced.
    assert g.describe(32) == "Section 2, Chorus, bar 1, beat 1"
    assert g.describe(43) == "Section 2, Chorus, bar 1, beat 3, step 4"


def test_describe_disambiguates_same_named_sections():
    v = Pattern("Verse", 8, 2, {}, 4, 4, 1)
    g = SongGrid([(v, 1, "Verse"), (v, 1, "Verse")])   # two identically-named sections
    assert g.describe(0).startswith("Section 1, Verse")
    assert g.describe(8).startswith("Section 2, Verse")
    assert g.describe(0) != g.describe(8)


def test_step_moves_and_clamps_across_sections():
    g = _song()
    assert g.step(31, 1) == 32                 # crosses the section boundary
    assert g.step(0, -1) == 0                  # clamps at the start
    assert g.step(43, 1) == 43                 # clamps at the end
    assert g.home() == 0 and g.end() == 43


def test_beat_and_bar_stay_within_the_section():
    g = _song()
    assert g.beat(0, 1) == 4                    # +1 beat (4 grid steps)
    assert g.bar(0, 1) == 16                    # +1 bar (16 steps) — still in the verse
    # A beat move near the section end clamps to the section, never spilling into the next.
    assert g.beat(30, 1) == 31
    assert g.bar(20, 1) == 31                   # +16 would be 36; clamped to verse end 31
    assert g.beat(32, -1) == 32                 # clamps at the chorus start, not back into verse


def test_section_jump_is_two_stage_going_back():
    g = _song()
    assert g.section(0, 1) == 32                # forward -> next section start
    assert g.section(40, -1) == 32             # back -> to the start of this (chorus) section
    assert g.section(32, -1) == 0              # already at start -> previous section start
    assert g.section(43, 1) == 43              # last section, forward -> stays at its end
    assert g.section(32, 1) == 43              # forward from the last section -> its end


def test_half_repeat_section_length():
    v = Pattern("V", 16, 4, {}, 4, 4, 1)
    g = SongGrid([(v, 1.5, "V")])
    assert g.total_steps == 24                  # 16 * 1.5
    assert g.locate(16).repeat == 1 and g.locate(23).step_in_pattern == 7
