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
