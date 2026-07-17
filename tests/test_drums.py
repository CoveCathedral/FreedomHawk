"""Tests for the drum looper engine: synthesis, WAV loading, and loop rendering.

The key guarantee is the timing compensator — every hit's attack lands on its exact
beat offset regardless of sample length — verified in test_compensator_*.
"""

import io
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
    assert len(lib) == 200
    names = [p.name for p in lib]
    assert len(set(names)) == 200
    # The hand-made bases come first, unchanged.
    assert names[: len(drums.GENRE_PATTERNS)] == [p.name for p in drums.GENRE_PATTERNS]


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


def test_load_kit_honors_choices(tmp_path):
    d = tmp_path / "KICK"
    d.mkdir()
    _write_int16_wav(d / "a.wav", np.full(1000, 0.1))
    _write_int16_wav(d / "b.wav", np.full(2000, 0.1))
    kit = drums.load_kit_from_folder(tmp_path, choices={"kick": "b.wav"})
    assert len(kit.voice("kick")) == 2000  # the chosen file, not the first
    kit2 = drums.load_kit_from_folder(tmp_path, choices={"kick": "nonexistent.wav"})
    assert len(kit2.voice("kick")) == 1000  # bad choice falls back to the default
