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

from sequin.practice import drums


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


def test_full_standard_kit_has_every_part():
    # The synth kit voices the whole standard kit so the palette is always playable and
    # the fill engine never reaches for a part that isn't there.
    k = drums.synth_kit()
    for role in ("kick", "snare", "rimshot", "clap", "hihat", "pedalhat", "openhat",
                 "tom1", "tom2", "tom", "tom4", "tom5", "crash", "crash2", "splash",
                 "china", "ride", "ridebell", "cowbell", "tambourine", "shaker",
                 "808", "perc"):
        v = k.voice(role)
        assert v is not None and len(v) > 0
        assert np.all(np.isfinite(v)) and float(np.max(np.abs(v))) > 0.0
    # Five toms, pitched high to low.
    assert drums.TOM_ROLES == ["tom1", "tom2", "tom", "tom4", "tom5"]
    peak = lambda r: float(np.argmax(np.abs(np.fft.rfft(k.voice(r)))))  # noqa: E731
    peaks = [peak(r) for r in drums.TOM_ROLES]
    assert peaks == sorted(peaks, reverse=True)     # descending fundamentals


def test_role_folder_names_round_trip():
    # Every part's write-folder must map straight back to that part, so a kit the Kit
    # Builder writes reloads with exactly the roles it saved (the five toms included).
    assert set(drums.ROLE_FOLDER) == set(drums.ROLES)
    for role, folder in drums.ROLE_FOLDER.items():
        assert drums.folder_to_role(folder) == role


def test_legacy_roles_still_render():
    # Existing library/saved patterns key hits on "tom" and "crash"; those must keep
    # working unchanged (tom = the mid tom, crash = crash 1).
    k = drums.synth_kit()
    p = drums.Pattern("legacy", 16, 4, {"kick": [0], "tom": [4], "crash": [0]}, 4, 4, 1)
    assert len(drums.render_loop(p, k, 120)) > 1000


def test_folder_to_role_handles_real_pack_names():
    f = drums.folder_to_role
    # Exact + simple plurals.
    assert f("Kick") == "kick" and f("Kicks") == "kick"
    assert f("Snare") == "snare" and f("Snares") == "snare"
    assert f("Hihats") == "hihat" and f("Hats") == "hihat" and f("HIHAT") == "hihat"
    assert f("OH") == "openhat" and f("Open Hat") == "openhat" and f("Open Hats") == "openhat"
    # Keyword fallback for the names packs actually ship.
    assert f("Organic Percussions") == "perc"
    assert f("Percussion") == "perc" and f("Percussions") == "perc"
    # The full standard kit gives shakers, tambourines and cowbells their own parts.
    assert f("Shaker") == "shaker" and f("Shakers") == "shaker"
    assert f("Tambourine") == "tambourine" and f("Cowbell") == "cowbell"
    assert f("Floor Tom") == "tom5" and f("High Tom") == "tom1" and f("Rack Tom") == "tom1"
    assert f("Ride Bell") == "ridebell" and f("China") == "china" and f("Splash") == "splash"
    assert f("Rimshot") == "rimshot" and f("Pedal Hat") == "pedalhat"
    assert f("Closed Hats") == "hihat"
    assert f("808") == "808" and f("808 Bass") == "808" and f("Sub Bass") == "808"
    assert f("Snaps") == "clap" and f("Snap") == "clap"     # hand percussion, not the drum
    # Loops and textures are kept aside in FX so they don't crowd real one-shot defaults.
    assert f("PercLoop") == "fx" and f("Drum Loops") == "fx"
    assert f("Texture") == "fx" and f("Impacts") == "fx" and f("FXs") == "fx"
    # Genuinely unknown -> None (so nothing is silently misfiled).
    assert f("Readme") is None and f("Vocals") is None


def test_list_role_files_merges_folders_into_one_role(tmp_path):
    # A pack with several percussion folders that all resolve to perc: every sample must
    # stay reachable, merged into the one pool.  (Shakers/tambourines are their own parts
    # now, so this uses only genuine perc-named folders.)
    for name, count in (("Percussions", 3), ("Organic Percussions", 2), ("Congas", 2)):
        d = tmp_path / name
        d.mkdir()
        for i in range(count):
            _write_int16_wav(d / f"{name[:4]}_{i}.wav", _sine(4000))
    files = drums.list_role_files(tmp_path)
    assert set(files) == {"perc"}
    assert len(files["perc"]) == 7          # 3 + 2 + 2, none dropped
    # Snaps land with claps, not the snare, when both exist.
    (tmp_path / "Claps").mkdir(); (tmp_path / "Snaps").mkdir(); (tmp_path / "Snares").mkdir()
    _write_int16_wav(tmp_path / "Claps" / "c.wav", _sine(4000))
    _write_int16_wav(tmp_path / "Snaps" / "s.wav", _sine(4000))
    _write_int16_wav(tmp_path / "Snares" / "sn.wav", _sine(4000))
    files = drums.list_role_files(tmp_path)
    assert len(files["clap"]) == 2 and len(files["snare"]) == 1


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
    from sequin.practice import patternstore as ps
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


def test_song_polymeter_contained_by_default():
    # An odd-length line must not push the next section off its count: the section
    # lasts exactly its nominal length x repeats, the line cut off at the boundary.
    kit = drums.synth_kit()
    poly = drums.Pattern("P", 16, 4, {"kick": [0], "hihat": [0, 4, 8, 12]}, 4, 4, 1)
    poly.set_line_length("kick", 7)
    after = drums.Pattern("B", 16, 4, {"snare": [0]}, 4, 4, 1)
    sections = [(poly, 2, 120, kit), (after, 1, 120, kit)]
    wav = drums.render_song(sections)
    expect_s = poly.loop_seconds(120) * 2 + after.loop_seconds(120)
    assert len(_frames(wav)) == pytest.approx(expect_s * drums.RATE, rel=0.001)
    assert drums.song_seconds(sections) == pytest.approx(expect_s, abs=0.001)
    # Fractional repeats stay exact too.
    wav = drums.render_song([(poly, 1.5, 120, kit)])
    assert len(_frames(wav)) == pytest.approx(
        poly.loop_seconds(120) * 1.5 * drums.RATE, rel=0.001)


def test_song_polymeter_line_cycles_across_repeats():
    # Contained doesn't mean per-repeat restart: the 7-step kick keeps cycling
    # through the whole section (0, 7, 14, ... across two 16-step repeats).
    p = drums.Pattern("P", 16, 4, {"kick": [0]}, 4, 4, 1)
    p.set_line_length("kick", 7)
    flat = drums.flatten_polymeter(p, render_len=32)
    assert flat.steps == 32
    assert flat.hits["kick"] == [0, 7, 14, 21, 28]


def test_song_polymeter_tails_toggle_restores_lcm():
    # The escape hatch: contain_polymeter=False renders each repeat as the full
    # realignment (LCM) loop — the pre-containment behavior.
    kit = drums.synth_kit()
    p = drums.Pattern("P", 16, 4, {"kick": [0], "hihat": [0, 4, 8, 12]}, 4, 4, 1)
    p.set_line_length("kick", 7)
    sections = [(p, 1, 120, kit)]
    loose = drums.render_song(sections, contain_polymeter=False)
    lcm_s = drums.flatten_polymeter(p).loop_seconds(120)   # 112 steps, not 16
    assert lcm_s > p.loop_seconds(120)
    assert len(_frames(loose)) == pytest.approx(lcm_s * drums.RATE, rel=0.001)
    assert drums.song_seconds(sections, contain_polymeter=False) == pytest.approx(
        lcm_s, abs=0.001)
    assert drums.section_seconds(p, 1, 120) == pytest.approx(
        p.loop_seconds(120), abs=0.001)


def test_fill_span_replaces_span_and_resolves():
    p = drums.Pattern("t", 16, 4,
                      {"kick": [0, 4, 8, 12], "snare": [4, 12],
                       "hihat": list(range(16))}, 4, 4, 1)
    drums.fill_span(p, 8, 16, complexity=0.8, spill=False, seed=3)
    # The melodic parts in the span are cleared and replaced.
    assert all(not (8 <= s < 16) for s in p.hits.get("hihat", []))
    assert any(r in p.hits and any(8 <= s < 16 for s in p.hits[r]) for r in drums.TOM_ROLES)
    # Kick outside the span is preserved; a resolving crash lands on the loop start.
    assert 0 in p.hits["kick"] and 4 in p.hits["kick"]
    assert 0 in p.hits.get("crash", [])
    # Deterministic with a seed.
    a = drums.Pattern("t", 16, 4, {"snare": [4]}, 4, 4, 1)
    b = a.copy()
    drums.fill_span(a, 0, 8, 0.6, False, seed=9)
    drums.fill_span(b, 0, 8, 0.6, False, seed=9)
    assert a.hits == b.hits and a.levels == b.levels


def test_fill_span_respects_polymeter_line_length():
    # A fill must not place a hit past a line's own loop length — it would be dropped on
    # save (lines_to_pattern filters out-of-length steps), a silent divergence.
    p = drums.Pattern("t", 16, 4, {"tom1": [0]}, 4, 4, 1)
    p.set_line_length("tom1", 8)                 # tom1 loops every 8 steps
    drums.fill_span(p, 8, 16, complexity=1.0, spill=False, seed=2)
    assert all(s < 8 for s in p.hits.get("tom1", []))   # nothing placed beyond its length


def test_fill_span_spill_places_no_resolving_crash():
    p = drums.Pattern("t", 16, 4, {"kick": [0]}, 4, 4, 1)
    drums.fill_span(p, 0, 16, complexity=1.0, spill=True, seed=1)
    # Spilling: the run fills through and no resolving crash is forced at the boundary.
    assert 0 not in p.hits.get("crash", [])
    # An empty / degenerate span is a no-op.
    q = drums.Pattern("t", 16, 4, {"snare": [0]}, 4, 4, 1)
    drums.fill_span(q, 8, 8, 0.5, False, seed=1)
    assert q.hits == {"snare": [0]}


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


def test_render_loop_inherits_the_patterns_own_feel():
    # A groove carries its feel; render_loop with no swing arg uses pattern.swing.
    kit = drums.synth_kit()
    off = drums.Pattern("t", 4, 4, {"hihat": [2]}, 4, 4, 1)
    off.swing = 1.0
    assert drums.render_loop(off, kit, 120) == drums.render_loop(off, kit, 120, swing=1.0)
    assert drums.render_loop(off, kit, 120) != drums.render_loop(off, kit, 120, swing=0.0)
    # copy() and retime carry the feel with the pattern.
    assert off.copy().swing == 1.0
    assert drums.retime_pattern(off, 4, 4, 4, 2).swing == 1.0


def test_chance_steps_roll_fresh_but_seeds_reproduce():
    kit = drums.synth_kit()
    p = drums.Pattern("t", 16, 4, {"hihat": list(range(0, 16, 2))}, 4, 4, 1)
    for s in range(0, 16, 2):
        p.set_chance("hihat", s, 50)
    a = drums.render_loop(p, kit, 120, seed=1, passes=1)
    b = drums.render_loop(p, kit, 120, seed=2, passes=1)
    assert a != b                                             # different rolls
    assert a == drums.render_loop(p, kit, 120, seed=1, passes=1)  # seed reproduces
    # Clearing the chances restores plain determinism (and the always path).
    for s in range(0, 16, 2):
        p.set_chance("hihat", s, None)
    assert not p.probs
    assert drums.render_loop(p, kit, 120) == drums.render_loop(p, kit, 120)


def test_chance_loop_bakes_four_varying_passes():
    # A looping WAV repeats its buffer verbatim, so a chance pattern renders four
    # passes with fresh rolls baked into one loop.
    import io
    import wave
    kit = drums.synth_kit()
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "hihat": [4]}, 4, 4, 1)
    p.set_chance("hihat", 4, 50)
    w = wave.open(io.BytesIO(drums.render_loop(p, kit, 120)))
    assert w.getnframes() == pytest.approx(4 * p.loop_seconds(120) * 44100, rel=0.01)
    # Chance-free patterns stay a single pass.
    plain = drums.Pattern("t", 16, 4, {"kick": [0, 8]}, 4, 4, 1)
    w = wave.open(io.BytesIO(drums.render_loop(plain, kit, 120)))
    assert w.getnframes() == pytest.approx(p.loop_seconds(120) * 44100, rel=0.01)


def test_chance_survives_transforms():
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8], "snare": [4]}, 4, 4, 1)
    p.set_chance("snare", 4, 30)
    assert p.copy().chance_of("snare", 4) == 30
    assert drums.retime_pattern(p, 4, 4, 4, 2).chance_of("snare", 4) == 30  # bar tile
    assert drums.retime_pattern(p, 4, 4, 2, 1).probs["snare"]              # grid remap
    assert drums.expand_with_fill(p, 4).chance_of("snare", 4) == 30
    assert drums.flatten_polymeter(p).chance_of("snare", 4) == 30
    # Space-off semantics: clearing the hit's chance removes the entry entirely.
    p.set_chance("snare", 4, None)
    assert not p.probs


def test_ornaments_render_grace_strokes():
    kit = drums.synth_kit()
    plain = drums.Pattern("t", 16, 4, {"snare": [4]}, 4, 4, 1)
    for orn in drums.ORNAMENTS:
        p = plain.copy()
        p.set_ornament("snare", 4, orn)
        a, b = drums.render_loop(plain, kit, 120), drums.render_loop(p, kit, 120)
        assert a != b, orn                       # the ornament is audible
        assert len(a) == len(b)                  # and doesn't change the loop length
    # A flam's grace stroke lands BEFORE the main hit.
    p = plain.copy()
    p.set_ornament("snare", 4, drums.ORNAMENT_FLAM)
    assert _first_onset(drums.render_loop(p, kit, 120)) < _first_onset(
        drums.render_loop(plain, kit, 120))
    # Deterministic: no RNG involved.
    assert drums.render_loop(p, kit, 120) == drums.render_loop(p, kit, 120)


def test_ornaments_survive_transforms_and_clear_with_the_hit():
    p = drums.Pattern("t", 16, 4, {"snare": [4]}, 4, 4, 1)
    p.set_ornament("snare", 4, "drag")
    assert p.copy().ornament_of("snare", 4) == "drag"
    assert drums.retime_pattern(p, 4, 4, 4, 2).ornament_of("snare", 4) == "drag"
    assert drums.expand_with_fill(p, 4).ornament_of("snare", 4) == "drag"
    assert drums.flatten_polymeter(p).ornament_of("snare", 4) == "drag"
    p.set_ornament("snare", 4, None)
    assert not p.ornaments


def test_render_song_fractional_repeats():
    # "Extend the verse by half": x1.5 renders one full pass plus half a pass.
    import io
    import wave
    kit = drums.synth_kit()
    p = drums.Pattern("t", 16, 4, {"kick": [0, 8]}, 4, 4, 1)
    wav = drums.render_song([(p, 1.5, 120, kit)])
    w = wave.open(io.BytesIO(wav))
    assert w.getnframes() == pytest.approx(1.5 * p.loop_seconds(120) * 44100, rel=0.01)
    assert drums.song_seconds([(p, 2.5, 120, kit)]) == pytest.approx(
        2.5 * p.loop_seconds(120))
    # Chance sections take a fractional tail too (a fresh-rolled truncated pass).
    p.set_chance("kick", 8, 50)
    wav = drums.render_song([(p, 0.5, 120, kit)])
    w = wave.open(io.BytesIO(wav))
    assert w.getnframes() == pytest.approx(0.5 * p.loop_seconds(120) * 44100, rel=0.01)


def test_render_song_uses_per_section_feel():
    # Two sections, same groove/tempo/kit but one swung: the mixes must differ, proving
    # render_song reads each section pattern's own feel (not a single song-wide value).
    kit = drums.synth_kit()
    straight = drums.Pattern("t", 4, 4, {"hihat": [2]}, 4, 4, 1)
    swung = straight.copy()
    swung.swing = 1.0
    a = drums.render_song([(straight, 1, 120, kit)])
    b = drums.render_song([(swung, 1, 120, kit)])
    assert a != b


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


def test_split_kit_choice():
    assert drums.split_kit_choice(None) == (None, None)
    assert drums.split_kit_choice("kick.wav") == (None, "kick.wav")          # this kit
    assert drums.split_kit_choice("Other Kit/x.wav") == ("Other Kit", "x.wav")


def test_load_kit_borrows_parts_from_sibling_kits(tmp_path):
    # Two kits side by side, like the real Samples/ folder.
    a_kick = tmp_path / "Kit A" / "KICK"
    a_kick.mkdir(parents=True)
    _write_int16_wav(a_kick / "own.wav", np.full(1000, 0.1))
    b_kick = tmp_path / "Kit B" / "KICK"
    b_kick.mkdir(parents=True)
    _write_int16_wav(b_kick / "borrowed.wav", np.full(3000, 0.1))
    b_808 = tmp_path / "Kit B" / "808"
    b_808.mkdir()
    _write_int16_wav(b_808 / "sub.wav", np.full(4000, 0.1))

    # A hybrid: Kit A, but the kick comes from Kit B.
    kit = drums.load_kit_from_folder(tmp_path / "Kit A",
                                     choices={"kick": "Kit B/borrowed.wav"})
    assert len(kit.voice("kick")) == 3000
    # A borrowed part can fill a gap Kit A has no folder for at all (the 808).
    kit = drums.load_kit_from_folder(
        tmp_path / "Kit A", choices={"808": "Kit B/sub.wav"})
    assert len(kit.voice("808")) == 4000
    # A broken borrow (kit or file gone) falls back to this kit's own default.
    kit = drums.load_kit_from_folder(tmp_path / "Kit A",
                                     choices={"kick": "Kit Gone/x.wav"})
    assert len(kit.voice("kick")) == 1000
