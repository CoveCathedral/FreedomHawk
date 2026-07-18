"""Tests for the drum looper engine: synthesis, WAV loading, and loop rendering.

The key guarantee is the timing compensator — every hit's attack lands on its exact
beat offset regardless of sample length — verified in test_compensator_*.
"""

import io
import random
import struct
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from firehawk.practice import drums


def _write_int16_wav(path, samples, rate=44100, channels=1):
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    w = wave.open(str(path), "wb")
    w.setnchannels(channels)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(pcm.tobytes())
    w.close()


def _write_float32_wav(path, samples, rate=44100):
    data = np.asarray(samples, dtype="<f4").tobytes()
    n = len(data)
    block = 1 * 32 // 8
    header = b"RIFF" + struct.pack("<I", 36 + n) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 3, 1, rate, rate * block, block, 32)
    header += b"data" + struct.pack("<I", n)
    Path(path).write_bytes(header + data)


def _frames(wav_bytes):
    w = wave.open(io.BytesIO(wav_bytes))
    return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def test_synth_kit_has_expected_roles():
    kit = drums.synth_kit()
    assert {"kick", "snare", "hihat", "808"} <= set(kit.roles())
    for role in kit.roles():
        assert len(kit.voice(role)) > 0


def test_render_loop_length_and_valid_wav():
    kit = drums.synth_kit()
    pat = drums.GENRE_PATTERNS[0]
    wav = drums.render_loop(pat, kit, bpm=120)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    w = wave.open(io.BytesIO(wav))
    assert w.getnframes() == pytest.approx(pat.loop_seconds(120) * 44100, rel=0.01)


def test_compensator_places_hit_on_the_beat():
    # A single kick on step 4 must begin at exactly that step's sample offset,
    # no matter how long the sample is.
    kit = drums.synth_kit()
    pat = drums.Pattern("one", 16, 4, {"kick": [4]})
    pcm = _frames(drums.render_loop(pat, kit, bpm=120))
    first = int(np.argmax(np.abs(pcm) > 200))
    expected = round(4 * pat.step_seconds(120) * 44100)
    assert abs(first - expected) <= 2


def test_mix_wrap_sums_overlapping_voices():
    # True polyphony: two hits at the same offset sum, they don't cut each other off.
    buf = np.zeros(100, dtype=np.float32)
    v = np.full(10, 0.3, dtype=np.float32)
    drums._mix_wrap(buf, v, 5)
    drums._mix_wrap(buf, v, 5)
    assert buf[5] == pytest.approx(0.6)
    assert buf[4] == 0.0


def test_mix_wrap_wraps_tail_to_start():
    # A hit near the loop end rings into the start, so the loop is seamless.
    buf = np.zeros(20, dtype=np.float32)
    v = np.ones(8, dtype=np.float32)
    drums._mix_wrap(buf, v, 16)  # samples 16..23 -> 16,17,18,19 then wrap to 0,1,2,3
    assert buf[16] == 1.0 and buf[19] == 1.0
    assert buf[0] == 1.0 and buf[3] == 1.0
    assert buf[4] == 0.0 and buf[15] == 0.0


def test_load_float32_wav(tmp_path):
    # 32-bit float WAVs (what real kits ship) load even though stdlib wave cannot read them.
    x = 0.5 * np.sin(2 * np.pi * 220 * np.arange(4410) / 44100)
    p = tmp_path / "tone.wav"
    _write_float32_wav(p, x)
    loaded, rate = drums.load_wav_float(p)
    assert rate == 44100
    assert np.allclose(loaded, x, atol=1e-3)


def test_load_int16_wav(tmp_path):
    x = 0.5 * np.sin(2 * np.pi * 220 * np.arange(4410) / 44100)
    p = tmp_path / "tone16.wav"
    _write_int16_wav(p, x)
    loaded, rate = drums.load_wav_float(p)
    assert rate == 44100
    assert np.allclose(loaded, x, atol=1e-3)


def test_stereo_downmixes_to_mono(tmp_path):
    frames = 2205
    stereo = np.zeros(frames * 2, dtype=np.float32)
    stereo[0::2] = 0.4   # left
    stereo[1::2] = 0.2   # right
    p = tmp_path / "stereo.wav"
    _write_int16_wav(p, stereo, channels=2)
    mono, _ = drums.load_wav_float(p)
    assert len(mono) == frames
    assert np.allclose(mono, 0.3, atol=1e-3)  # (0.4 + 0.2) / 2


def test_resample_changes_length():
    x = np.sin(2 * np.pi * 220 * np.arange(2205) / 22050).astype(np.float32)
    up = drums.resample(x, 22050, 44100)
    assert len(up) == pytest.approx(4410, abs=1)


def test_load_kit_from_folder(tmp_path):
    for role_dir in ("KICK", "SNARE", "HIHAT"):
        d = tmp_path / role_dir
        d.mkdir()
        _write_int16_wav(d / "sample.wav", 0.5 * np.sin(np.arange(2000) / 5))
    kit = drums.load_kit_from_folder(tmp_path)
    assert kit.roles() == ["kick", "snare", "hihat"]  # canonical ROLES order
    assert kit.name == tmp_path.name


def test_pattern_copy_is_independent():
    pat = drums.GENRE_PATTERNS[0].copy()
    pat.hits["kick"].append(15)
    assert 15 not in drums.GENRE_PATTERNS[0].hits["kick"]  # original untouched


def test_steps_per_bar_for_meters():
    assert drums.steps_per_bar(4, 4, 4) == 16   # 4/4 sixteenths
    assert drums.steps_per_bar(7, 8, 2) == 7    # 7/8 eighth grid
    assert drums.steps_per_bar(5, 4, 4) == 20   # 5/4 sixteenths
    assert drums.steps_per_bar(6, 8, 2) == 6    # 6/8 eighth grid


def test_blank_pattern_meter_and_length():
    p = drums.blank_pattern(7, 8, 2, bars=2)
    assert p.beats_per_bar == 7 and p.beat_unit == 8 and p.bars == 2
    assert p.steps == 14 and p.hits == {}
    assert p.meter_label() == "7/8"


def test_odd_meter_pattern_renders_correct_length():
    kit = drums.synth_kit()
    seven_eight = next(p for p in drums.GENRE_PATTERNS if p.name.startswith("7/8"))
    assert seven_eight.steps == 7
    wav = drums.render_loop(seven_eight, kit, bpm=120)
    w = wave.open(io.BytesIO(wav))
    # 7 eighth-note steps at 120 BPM (quarter) = 3.5 beats = 1.75 s
    assert w.getnframes() == pytest.approx(seven_eight.loop_seconds(120) * 44100, rel=0.01)


def test_all_genre_patterns_hits_in_range():
    for p in drums.GENRE_PATTERNS:
        for role, steps in p.hits.items():
            assert all(0 <= s < p.steps for s in steps), f"{p.name}/{role} out of range"


def test_pattern_library_size_and_uniqueness():
    lib = drums.PATTERN_LIBRARY
    assert len(lib) == 500
    names = [p.name for p in lib]
    assert len(set(names)) == 500
    # The hand-made bases come first, unchanged.
    assert names[: len(drums.GENRE_PATTERNS)] == [p.name for p in drums.GENRE_PATTERNS]


def test_library_spans_many_genres():
    from firehawk.practice import patternstore as ps
    cats = {ps.builtin_category(p.name) for p in drums.PATTERN_LIBRARY}
    assert "" not in cats                       # every pattern maps to a genre
    assert len(cats) >= 40                       # a broad spread of styles


def test_pattern_library_is_valid_and_deterministic():
    for p in drums.PATTERN_LIBRARY:
        assert p.hits, f"{p.name} is empty"
        assert 1 <= p.steps <= drums.MAX_STEPS
        for role, steps in p.hits.items():
            assert all(0 <= s < p.steps for s in steps), f"{p.name}/{role} out of range"
    # Same seeds -> the same library forever (pattern N is stable across launches).
    again = drums.build_pattern_library()
    assert all(a.name == b.name and a.hits == b.hits
               for a, b in zip(drums.PATTERN_LIBRARY, again))


def test_pattern_library_fills_land_on_the_meter():
    fills = [p for p in drums.PATTERN_LIBRARY if p.name.endswith("fill")]
    assert len(fills) > 50
    for p in fills:
        # Every fill puts a crash on the loop restart (step 0).
        assert 0 in p.hits.get("crash", []), f"{p.name} missing restart crash"


def test_synth_kit_covers_fill_roles():
    kit = drums.synth_kit()
    assert {"kick", "snare", "tom", "crash", "ride", "perc"} <= set(kit.roles())


def _sine(n=4410):
    return 0.4 * np.sin(2 * np.pi * 220 * np.arange(n) / 44100)


def test_wav_duration_reads_header_only(tmp_path):
    p = tmp_path / "t.wav"
    _write_int16_wav(p, _sine(22050))  # 0.5 s
    assert drums.wav_duration(p) == pytest.approx(0.5, abs=0.01)
    assert drums.wav_duration(tmp_path / "missing.wav") is None


def test_default_sample_skips_vocal_names(tmp_path):
    d = tmp_path / "PERC"
    d.mkdir()
    _write_int16_wav(d / "740 PERC AHH.wav", _sine())     # vocal chop: alphabetically first
    _write_int16_wav(d / "740 PERC ANVIL.wav", _sine())
    files = drums.list_role_files(tmp_path)["perc"]
    pick = drums.default_sample_for("perc", files)
    assert pick.name == "740 PERC ANVIL.wav"


def test_default_sample_skips_long_hits(tmp_path):
    d = tmp_path / "SNARE"
    d.mkdir()
    _write_int16_wav(d / "a_long.wav", _sine(44100 * 2))  # 2 s: too long for a hit
    _write_int16_wav(d / "b_short.wav", _sine(8000))
    files = drums.list_role_files(tmp_path)["snare"]
    assert drums.default_sample_for("snare", files).name == "b_short.wav"


def test_default_sample_falls_back_when_all_filtered(tmp_path):
    d = tmp_path / "PERC"
    d.mkdir()
    _write_int16_wav(d / "AHH.wav", _sine())  # only option, vocal-named
    files = drums.list_role_files(tmp_path)["perc"]
    assert drums.default_sample_for("perc", files).name == "AHH.wav"


def test_retime_growing_bars_repeats_music():
    # 1 bar of 4/4 sixteenths -> 4 bars: the bar is tiled, not followed by silence.
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4, 12]}, 4, 4, 1)
    grown = drums.retime_pattern(p, 4, 4, 4, 4)
    assert grown.steps == 64 and grown.bars == 4
    assert grown.hits["kick"] == [0, 8, 16, 24, 32, 40, 48, 56]
    assert grown.hits["snare"] == [4, 12, 20, 28, 36, 44, 52, 60]


def test_retime_two_bar_fill_tiles_cyclically():
    # A 2-bar pattern grown to 4 bars repeats bars 1,2,1,2 (fills recur too).
    p = drums.Pattern("t", 32, 4, {"tom": [24, 28]}, 4, 4, 2)  # fill in bar 2
    grown = drums.retime_pattern(p, 4, 4, 4, 4)
    assert grown.hits["tom"] == [24, 28, 56, 60]  # bar 2 and bar 4


def test_retime_shrinking_keeps_first_bars():
    p = drums.Pattern("t", 32, 4, {"kick": [0, 16], "tom": [28]}, 4, 4, 2)
    shrunk = drums.retime_pattern(p, 4, 4, 4, 1)
    assert shrunk.steps == 16
    assert shrunk.hits["kick"] == [0]
    assert "tom" not in shrunk.hits  # bar-2-only content drops with its bar


def test_retime_grid_change_remaps_by_time_not_clip():
    # Changing the grid must keep every hit at its musical position, not drop the ones
    # past the new length (the "parts missing / out of time" bug).
    p = drums.Pattern("t", 16, 4, {"snare": [4, 12]}, 4, 4, 1)  # backbeats
    trip = drums.retime_pattern(p, 4, 4, 3, 1)                  # sixteenths -> triplets
    assert trip.steps == 12
    assert len(trip.hits["snare"]) == 2                        # nothing dropped
    assert trip.hits["snare"] == [3, 9]                        # still beats 2 and 4
    back = drums.retime_pattern(trip, 4, 4, 4, 1)              # triplets -> sixteenths
    assert back.hits["snare"] == [4, 12]                       # backbeat round-trips


def test_retime_bar_count_is_reversible():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4, 12]}, 4, 4, 1,
                      {"snare": {4: drums.LEVEL_ACCENT}})
    grown = drums.retime_pattern(p, 4, 4, 4, 2)   # 1 -> 2 bars (tiles)
    shrunk = drums.retime_pattern(grown, 4, 4, 4, 1)  # 2 -> 1
    assert shrunk.hits == p.hits and shrunk.levels == p.levels


def test_retime_grid_change_keeps_dynamics_and_resets_polymeter():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8]}, 4, 4, 1,
                      {"kick": {0: drums.LEVEL_ACCENT}})
    p.set_line_length("kick", 7)  # polymetric
    changed = drums.retime_pattern(p, 4, 4, 2, 1)   # grid change
    assert changed.levels.get("kick")               # a dynamic survived the remap
    assert not changed.is_polymetric()              # per-line length reset (grid-relative)


def test_expand_with_fill_places_fill_last():
    # 2-bar groove (bar 1 plain, bar 2 has the fill) stretched to 4 bars:
    # plain, plain, plain, fill.
    p = drums.Pattern("t", 32, 4, {"kick": [0, 8, 16, 24], "tom": [28, 30]}, 4, 4, 2)
    ex = drums.expand_with_fill(p, 4)
    assert ex.steps == 64 and ex.bars == 4
    assert ex.hits["kick"] == [0, 8, 16, 24, 32, 40, 48, 56]  # bar-1 kicks everywhere
    assert ex.hits["tom"] == [60, 62]  # the fill only in the final bar


def test_expand_with_fill_crash_only_on_restart():
    # Library fills put a crash at step 0 (the post-fill downbeat). Stretched out,
    # that crash must land once per cycle — not at the top of every body bar.
    p = drums.Pattern("t", 32, 4, {"kick": [0, 16], "crash": [0], "tom": [28]}, 4, 4, 2)
    ex = drums.expand_with_fill(p, 12)
    assert ex.hits["crash"] == [0]


def test_expand_with_fill_single_bar_repeats():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8]}, 4, 4, 1)
    ex = drums.expand_with_fill(p, 12)
    assert ex.bars == 12 and ex.steps == 192
    assert len(ex.hits["kick"]) == 24  # 2 kicks x 12 bars


def test_expand_with_fill_noop_when_not_longer():
    p = drums.Pattern("t", 32, 4, {"kick": [0]}, 4, 4, 2)
    assert drums.expand_with_fill(p, 2) is p


def test_improvised_loop_structure():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4, 12]}, 4, 4, 1)
    loop = drums.improvised_loop(p, cycle_bars=4, cycles=4, seed=1)
    per = loop.steps // loop.bars
    assert loop.bars == 16 and per == 16
    # A crash lands on every cycle downbeat (wrapping at the loop end).
    assert sorted({s // per for s in loop.hits["crash"]}) == [0, 4, 8, 12]
    assert all(0 <= s < loop.steps for ss in loop.hits.values() for s in ss)


def test_improvised_loop_fills_differ_between_cycles():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4, 12],
                                   "hihat": list(range(0, 16, 2))}, 4, 4, 1)
    loop = drums.improvised_loop(p, cycle_bars=2, cycles=4, seed=9)
    per = loop.steps // loop.bars

    def fill_zone(c):  # contents of each cycle's final bar
        lo, hi = (c * 2 + 1) * per, (c * 2 + 2) * per
        return tuple(sorted((r, s - lo) for r, ss in loop.hits.items()
                            for s in ss if lo <= s < hi))
    zones = {fill_zone(c) for c in range(4)}
    assert len(zones) >= 3  # the fills vary (improvised, not copies)


def test_improvised_loop_respects_odd_meter():
    seven = drums.Pattern("7/8", 7, 2, {"kick": [0, 4], "hihat": list(range(7))}, 7, 8, 1)
    loop = drums.improvised_loop(seven, cycle_bars=4, cycles=2, seed=3)
    assert loop.steps == 7 * 8 and loop.beats_per_bar == 7 and loop.beat_unit == 8
    assert all(0 <= s < loop.steps for ss in loop.hits.values() for s in ss)


def test_improvised_loop_unseeded_varies():
    p = drums.Pattern("t", 16, 4, {"kick": [0], "snare": [8]}, 4, 4, 1)
    a = drums.improvised_loop(p, 4, 4)
    b = drums.improvised_loop(p, 4, 4)
    assert a.hits != b.hits  # fresh improvisation every render


def test_fill_amount_default_is_unchanged():
    # fill_amount defaults to 0.0 and must reproduce the original roll exactly —
    # existing seeded callers (and anything built on top of them) can't shift.
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4, 12]}, 4, 4, 1)
    implicit = drums.improvised_loop(p, cycle_bars=4, cycles=4, seed=7)
    explicit = drums.improvised_loop(p, cycle_bars=4, cycles=4, seed=7, fill_amount=0.0)
    assert implicit.hits == explicit.hits and implicit.levels == explicit.levels

    implicit_len, implicit_hits, implicit_levels = drums._generate_fill_zone(
        random.Random(3), beat_len=4, per_bar=16)
    explicit_len, explicit_hits, explicit_levels = drums._generate_fill_zone(
        random.Random(3), beat_len=4, per_bar=16, fill_amount=0.0)
    assert (implicit_len, implicit_hits, implicit_levels) == (explicit_len, explicit_hits, explicit_levels)


def test_fill_amount_makes_fills_longer_and_busier():
    # Any single seed's roll can go either way, so compare totals over many seeds:
    # a high fill_amount should come out longer and busier than a low one overall.
    low_len_total = high_len_total = 0
    low_hits_total = high_hits_total = 0
    for seed in range(80):
        low_len, low_hits, _ = drums._generate_fill_zone(
            random.Random(seed), beat_len=4, per_bar=16, fill_amount=0.0)
        high_len, high_hits, _ = drums._generate_fill_zone(
            random.Random(seed), beat_len=4, per_bar=16, fill_amount=1.0)
        low_len_total += low_len
        high_len_total += high_len
        low_hits_total += sum(len(v) for v in low_hits.values())
        high_hits_total += sum(len(v) for v in high_hits.values())
    assert high_len_total > low_len_total
    assert high_hits_total > low_hits_total

    # And the same trend holds one level up, through improvised_loop's total hits.
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4, 12],
                                   "hihat": list(range(0, 16, 2))}, 4, 4, 1)
    low = drums.improvised_loop(p, cycle_bars=2, cycles=6, seed=5, fill_amount=0.0)
    high = drums.improvised_loop(p, cycle_bars=2, cycles=6, seed=5, fill_amount=1.0)
    low_hits = sum(len(v) for v in low.hits.values())
    high_hits = sum(len(v) for v in high.hits.values())
    assert high_hits >= low_hits


def test_choke_group_cuts_the_ring():
    # An open hat that rings a full second, closed off by a closed hat four steps later.
    openhat = np.ones(int(1.0 * drums.RATE), dtype=np.float32) * 0.5
    hihat = np.ones(int(0.02 * drums.RATE), dtype=np.float32) * 0.5
    kit = drums.DrumKit("t", {"openhat": openhat, "hihat": hihat})
    p = drums.Pattern("t", 16, 4, {"openhat": [0], "hihat": [4]}, 4, 4, 1)

    def energy(lo_s, hi_s, choke):
        pcm = _frames(drums.render_loop(p, kit, 120, choke_groups=choke))
        lo, hi = int(lo_s * drums.RATE), int(hi_s * drums.RATE)
        return float(np.abs(pcm[lo:hi]).mean())

    # step = 0.125 s at 120 BPM, so the closed hat lands at 0.5 s.  After it, the open
    # hat is silenced only when both share a choke group.
    grouped = {"openhat": 1, "hihat": 1}
    assert energy(0.55, 0.70, grouped) < energy(0.55, 0.70, None) * 0.25
    # Before the closing hit, the open hat rings the same either way.
    assert energy(0.30, 0.45, grouped) == pytest.approx(energy(0.30, 0.45, None), rel=0.05)
    # Different groups don't choke each other.
    assert energy(0.55, 0.70, {"openhat": 1, "hihat": 2}) == pytest.approx(
        energy(0.55, 0.70, None), rel=0.05)


def test_count_in_matches_meter_and_tempo():
    # One bar of clicks: duration is beats x the meter-unit beat length.
    buf, dur = drums.render_count_in(4, 4, 120)
    assert dur == pytest.approx(2.0, abs=0.001)          # 4 quarters at 120 BPM
    assert len(buf) == pytest.approx(2.0 * drums.RATE, rel=0.001)
    buf7, dur7 = drums.render_count_in(7, 8, 140)
    assert dur7 == pytest.approx(7 * (60 / 140) * (4 / 8), abs=0.001)
    assert float(np.max(np.abs(buf7))) > 0.0             # it actually clicks


def test_render_song_concatenates_sections():
    kit = drums.synth_kit()
    a = drums.Pattern("A", 16, 4, {"kick": [0, 8], "snare": [4, 12]}, 4, 4, 1)
    b = drums.Pattern("B", 14, 4, {"kick": [0, 6, 10]}, 7, 8, 1)   # different meter/length
    # (pattern, repeats, bpm, kit) — each section at its own tempo and kit.
    sections = [(a, 2, 120, kit), (b, 3, 120, kit)]
    wav = drums.render_song(sections)
    got = _frames(wav)
    expect_s = a.loop_seconds(120) * 2 + b.loop_seconds(120) * 3
    assert len(got) == pytest.approx(expect_s * drums.RATE, rel=0.001)
    assert drums.song_seconds(sections) == pytest.approx(expect_s, abs=0.001)
    # Per-section tempo: the same section rendered faster is shorter.
    assert drums.song_seconds([(a, 1, 240, kit)]) == pytest.approx(a.loop_seconds(240), abs=0.001)
    assert len(drums.render_song([])) > 44                  # empty song is a valid tiny WAV


def test_tempo_ramp_sequence():
    assert drums.tempo_ramp(100, 120, 5) == [100, 105, 110, 115, 120]
    assert drums.tempo_ramp(100, 118, 5) == [100, 105, 110, 115, 118]   # last jump clamps
    assert drums.tempo_ramp(120, 120, 5) == [120]                        # already there
    assert drums.tempo_ramp(140, 100, 5) == [140]                        # target below start
    assert drums.tempo_ramp(90, 300, 10)[-1] == 300


def test_render_volume_scales_output():
    kit = drums.synth_kit()
    p = drums.GENRE_PATTERNS[0]

    def peak(vol):
        pcm = _frames(drums.render_loop(p, kit, 120, volume=vol))
        return int(np.abs(pcm).max())
    full, half, silent = peak(1.0), peak(0.5), peak(0.0)
    assert silent == 0
    assert 0 < half < full
    assert abs(half * 2 - full) <= 2


def test_levels_render_at_different_gains():
    kit = drums.synth_kit()
    p = drums.Pattern("t", 16, 4, {"snare": [0, 4, 8]}, 4, 4, 1,
                      {"snare": {0: drums.LEVEL_ACCENT, 8: drums.LEVEL_GHOST}})
    pcm = _frames(drums.render_loop(p, kit, 120))
    q = len(pcm) // 16

    def peak(step):
        return int(np.abs(pcm[step * q:(step + 1) * q]).max())
    assert peak(0) > peak(4) > peak(8)  # accent > normal > ghost


def test_levels_survive_retime_and_expand():
    p = drums.Pattern("t", 16, 4, {"snare": [0, 8]}, 4, 4, 1,
                      {"snare": {0: drums.LEVEL_ACCENT, 8: drums.LEVEL_GHOST}})
    grown = drums.retime_pattern(p, 4, 4, 4, 2)
    assert grown.levels["snare"] == {0: "accent", 8: "ghost", 16: "accent", 24: "ghost"}
    two = drums.Pattern("t", 32, 4, {"kick": [0, 16], "tom": [28]}, 4, 4, 2,
                        {"tom": {28: drums.LEVEL_ACCENT}})
    ex = drums.expand_with_fill(two, 4)
    assert ex.levels["tom"] == {60: "accent"}  # the fill accent rides to the final bar


def test_improvised_fills_have_dynamics():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4, 12]}, 4, 4, 1)
    loop = drums.improvised_loop(p, 4, 4, seed=11)
    assert loop.levels  # generated fills carry accents/ghosts
    for role, m in loop.levels.items():
        assert all(s in loop.hits[role] for s in m)  # levels only where hits exist
        assert all(lv in (drums.LEVEL_ACCENT, drums.LEVEL_GHOST) for lv in m.values())


def _first_onset(wav_bytes):
    pcm = _frames(wav_bytes)
    idx = int(np.argmax(np.abs(pcm) > 300))
    return idx / 44100.0


def test_swing_delays_offbeat_not_downbeat():
    kit = drums.synth_kit()
    # One hi-hat on the off-beat eighth (step 2 of a 4-step beat) at 120 BPM.
    off = drums.Pattern("t", 4, 4, {"hihat": [2]}, 4, 4, 1)
    straight = _first_onset(drums.render_loop(off, kit, 120, swing=0.0))
    swung = _first_onset(drums.render_loop(off, kit, 120, swing=1.0))
    assert swung > straight + 0.02          # pushed clearly later
    # The downbeat is unaffected by swing.
    down = drums.Pattern("t", 4, 4, {"kick": [0]}, 4, 4, 1)
    a = _first_onset(drums.render_loop(down, kit, 120, swing=0.0))
    b = _first_onset(drums.render_loop(down, kit, 120, swing=1.0))
    assert abs(a - b) < 0.002


def test_swing_default_matches_straight():
    kit = drums.synth_kit()
    p = drums.GENRE_PATTERNS[0]
    assert drums.render_loop(p, kit, 120) == drums.render_loop(p, kit, 120, swing=0.0)


def test_humanize_varies_but_seeds_reproduce():
    kit = drums.synth_kit()
    p = drums.Pattern("t", 4, 4, {"hihat": [2]}, 4, 4, 1)
    renders = {drums.render_loop(p, kit, 120, humanize=1.0) for _ in range(4)}
    assert len(renders) > 1                                   # genuinely varies
    assert (drums.render_loop(p, kit, 120, humanize=0.8, seed=3)
            == drums.render_loop(p, kit, 120, humanize=0.8, seed=3))  # seed reproduces
    # Zero humanize is deterministic.
    assert (drums.render_loop(p, kit, 120) == drums.render_loop(p, kit, 120))


def test_polymeter_flatten_tiles_lines():
    # Kick loops every 7, hats every 16 -> flattened over LCM(7,16)=112.
    p = drums.Pattern("poly", 16, 4, {"kick": [0, 3, 5],
                                      "hihat": [0, 2, 4, 6, 8, 10, 12, 14]}, 4, 4, 1)
    p.set_line_length("kick", 7)
    assert p.is_polymetric() and p.line_length("kick") == 7
    flat = drums.flatten_polymeter(p)
    assert flat.steps == 112 and flat.bars == 7
    assert flat.hits["kick"][:6] == [0, 3, 5, 7, 10, 12]  # tiled every 7 steps
    assert len(flat.hits["kick"]) == 112 // 7 * 3
    assert len(flat.hits["hihat"]) == 112 // 16 * 8


def test_polymeter_render_length():
    kit = drums.synth_kit()
    p = drums.Pattern("poly", 16, 4, {"kick": [0], "hihat": [0, 4, 8, 12]}, 4, 4, 1)
    p.set_line_length("kick", 7)
    frames = len(_frames(drums.render_loop(p, kit, 120)))
    assert frames == pytest.approx(112 * (60 / 120 / 4) * 44100, rel=0.01)


def test_polymeter_flatten_caps_pathological_lcm():
    p = drums.Pattern("x", 16, 4, {"a": [0], "b": [0], "c": [0]}, 4, 4, 1)
    p.set_line_length("a", 7)
    p.set_line_length("b", 11)
    p.set_line_length("c", 13)
    flat = drums.flatten_polymeter(p)
    assert flat.steps <= drums.POLY_MAX_RENDER
    assert flat.steps % 16 == 0            # still whole base bars


def test_set_line_length_drops_out_of_range_hits():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8, 12]}, 4, 4, 1,
                      {"kick": {12: drums.LEVEL_ACCENT}})
    p.set_line_length("kick", 7)
    assert p.hits["kick"] == [0]           # 8 and 12 fall outside the 7-step cycle
    assert "kick" not in p.levels          # the level on step 12 went with it


def test_flatten_non_polymetric_is_identity():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8]}, 4, 4, 1)
    assert drums.flatten_polymeter(p) is p


def test_polymeter_length_defaults_and_reset():
    p = drums.Pattern("t", 16, 4, {"kick": [0]}, 4, 4, 1)
    assert p.line_length("kick") == 16 and not p.is_polymetric()
    p.set_line_length("kick", 7)
    assert p.is_polymetric()
    p.set_line_length("kick", 16)          # back to the pattern length = synced again
    assert not p.is_polymetric() and "kick" not in p.lengths


def test_pattern_copy_copies_levels():
    p = drums.Pattern("t", 16, 4, {"kick": [0]}, 4, 4, 1,
                      {"kick": {0: drums.LEVEL_ACCENT}})
    c = p.copy()
    c.set_level("kick", 0, drums.LEVEL_GHOST)
    assert p.level_of("kick", 0) == drums.LEVEL_ACCENT  # original untouched


def test_load_kit_honors_choices(tmp_path):
    d = tmp_path / "KICK"
    d.mkdir()
    _write_int16_wav(d / "a.wav", np.full(1000, 0.1))
    _write_int16_wav(d / "b.wav", np.full(2000, 0.1))
    kit = drums.load_kit_from_folder(tmp_path, choices={"kick": "b.wav"})
    assert len(kit.voice("kick")) == 2000  # the chosen file, not the first
    kit2 = drums.load_kit_from_folder(tmp_path, choices={"kick": "nonexistent.wav"})
    assert len(kit2.voice("kick")) == 1000  # bad choice falls back to the default
