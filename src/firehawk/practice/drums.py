"""Drum looper engine: synth voices, real-sample loading, and loop rendering.

The pedal never had a drum machine; this adds one to the app.  It is UI-free and
uses numpy for audio.

**Timing compensator.**  Samples differ wildly in length (a clap is short, an 808
rings for a second), so timing must not depend on sample length.  Instead the whole
loop is *pre-mixed* into one buffer: each hit's audio is written at the exact sample
offset of its beat, and voices are summed (true polyphony).  Anything ringing past
the loop end wraps back to the start, so the loop is seamless and every hit's attack
lands precisely on the meter regardless of how long the sample is.  The finished
buffer is looped by the OS (``winsound`` ``SND_LOOP``), the same way the tuner holds
a tone.

Sounds come from the built-in synth kit (no files needed) or a user's own kit — a
folder of ``ROLE`` subfolders (KICK, SNARE, HIHAT, ...) of ``.wav`` files.  See
``docs/drum-kits.md``.
"""

from __future__ import annotations

import io
import os
import struct
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np
except ImportError:  # numpy drives all the audio maths
    np = None

try:
    import winsound
except ImportError:  # non-Windows (tests still exercise the pure functions)
    winsound = None

NUMPY_AVAILABLE = np is not None
RATE = 44100
_MAX_SAMPLE_SECONDS = 4.0  # cap any one voice so a long sample can't bloat the loop

#: Canonical drum roles, in display order.
ROLES = ["kick", "snare", "hihat", "openhat", "clap", "perc", "808", "tom", "ride", "crash", "fx"]

#: Friendly labels for the roles.
ROLE_LABELS = {
    "kick": "Kick", "snare": "Snare", "hihat": "Hi-hat (closed)", "openhat": "Open hat",
    "clap": "Clap", "perc": "Perc", "808": "808 / sub", "tom": "Tom", "ride": "Ride",
    "crash": "Crash", "fx": "FX",
}

#: Folder names (upper-cased) mapped to canonical roles when loading a user kit.
FOLDER_ROLE_MAP = {
    "KICK": "kick", "KICKS": "kick",
    "SNARE": "snare", "SNARES": "snare", "SNAP": "snare",
    "HIHAT": "hihat", "HAT": "hihat", "HATS": "hihat", "CH": "hihat", "CLOSEDHAT": "hihat",
    "OPENHAT": "openhat", "OH": "openhat", "OPEN": "openhat",
    "CLAP": "clap", "CLAPS": "clap",
    "PERC": "perc", "PERCUSSION": "perc",
    "808": "808", "808S": "808", "BASS": "808", "SUB": "808",
    "TOM": "tom", "TOMS": "tom",
    "RIDE": "ride", "CRASH": "crash", "CYMBAL": "crash",
    "FX": "fx",
}


# -- WAV loading (handles int 8/16/24/32, float 32/64, any rate, mono/stereo) ------

def _decode_pcm(data: bytes, audio_format: int, bits: int):
    if audio_format == 1:  # integer PCM
        if bits == 8:
            return (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        if bits == 16:
            return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        if bits == 24:
            b = np.frombuffer(data, dtype=np.uint8)
            usable = (len(b) // 3) * 3
            b = b[:usable].reshape(-1, 3).astype(np.int32)
            val = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            val = np.where(val & 0x800000, val - 0x1000000, val)
            return val.astype(np.float32) / float(2 ** 23)
        if bits == 32:
            return (np.frombuffer(data, dtype="<i4").astype(np.float64) / float(2 ** 31)).astype(np.float32)
    elif audio_format == 3:  # IEEE float
        if bits == 32:
            return np.frombuffer(data, dtype="<f4").astype(np.float32)
        if bits == 64:
            return np.frombuffer(data, dtype="<f8").astype(np.float32)
    raise ValueError(f"unsupported WAV: format {audio_format}, {bits}-bit")


def load_wav_float(path) -> tuple["np.ndarray", int]:
    """Load a WAV as mono float32 in [-1, 1] plus its sample rate. Robust to format."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    fmt = data = None
    pos, n = 12, len(raw)
    while pos + 8 <= n:
        cid = raw[pos:pos + 4]
        size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        start = pos + 8
        if cid == b"fmt ":
            fmt = raw[start:start + size]
        elif cid == b"data":
            data = raw[start:start + size]
        pos = start + size + (size & 1)  # chunks are word-aligned
    if fmt is None or data is None:
        raise ValueError("missing fmt or data chunk")
    audio_format, channels, rate, _byte_rate, _block, bits = struct.unpack("<HHIIHH", fmt[:16])
    if audio_format == 0xFFFE and len(fmt) >= 26:  # WAVE_FORMAT_EXTENSIBLE
        audio_format = struct.unpack("<H", fmt[24:26])[0]
    x = _decode_pcm(data, audio_format, bits)
    channels = max(1, channels)
    if channels > 1:
        usable = (len(x) // channels) * channels
        x = x[:usable].reshape(-1, channels).mean(axis=1)
    return x.astype(np.float32), rate


def resample(x: "np.ndarray", src_rate: int, dst_rate: int) -> "np.ndarray":
    if src_rate == dst_rate or len(x) == 0:
        return x.astype(np.float32)
    n_out = max(1, int(round(len(x) * dst_rate / src_rate)))
    t = np.linspace(0, len(x), n_out, endpoint=False)
    return np.interp(t, np.arange(len(x)), x).astype(np.float32)


def load_sample(path, rate: int = RATE) -> "np.ndarray":
    """Load, downmix, resample to *rate*, and cap the length of a sample file."""
    x, src = load_wav_float(path)
    x = resample(x, src, rate)
    return x[: int(_MAX_SAMPLE_SECONDS * rate)]


# -- synth voices (no files needed) ----------------------------------------------

def _norm(x: "np.ndarray", peak: float = 0.9) -> "np.ndarray":
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    if m > 0:
        x = x / m * peak
    return x.astype(np.float32)


def _t(seconds: float, rate: int) -> "np.ndarray":
    return np.linspace(0, seconds, int(rate * seconds), endpoint=False, dtype=np.float64)


def synth_kick(rate: int = RATE) -> "np.ndarray":
    t = _t(0.18, rate)
    freq = 45.0 + 120.0 * np.exp(-t * 32.0)           # pitch drop ~165 -> 45 Hz
    phase = 2 * np.pi * np.cumsum(freq) / rate
    body = np.sin(phase) * np.exp(-t * 18.0)
    click = np.exp(-t * 450.0) * 0.6                  # beater transient
    return _norm(0.9 * body + click)


def synth_snare(rate: int = RATE) -> "np.ndarray":
    t = _t(0.2, rate)
    rng = np.random.default_rng(1)
    tone = np.sin(2 * np.pi * 180.0 * t) * np.exp(-t * 22.0)
    noise = (rng.random(len(t)) * 2 - 1) * np.exp(-t * 16.0)
    return _norm(0.4 * tone + 0.85 * noise)


def synth_hihat(rate: int = RATE) -> "np.ndarray":
    t = _t(0.05, rate)
    rng = np.random.default_rng(2)
    noise = rng.random(len(t)) * 2 - 1
    noise = np.diff(noise, prepend=0.0)               # crude high-pass -> metallic
    return _norm(noise * np.exp(-t * 90.0))


def synth_openhat(rate: int = RATE) -> "np.ndarray":
    t = _t(0.3, rate)
    rng = np.random.default_rng(3)
    noise = rng.random(len(t)) * 2 - 1
    noise = np.diff(noise, prepend=0.0)
    return _norm(noise * np.exp(-t * 9.0))


def synth_clap(rate: int = RATE) -> "np.ndarray":
    t = _t(0.25, rate)
    rng = np.random.default_rng(4)
    noise = rng.random(len(t)) * 2 - 1
    env = np.zeros(len(t))
    for delay in (0.0, 0.010, 0.020):                 # three quick bursts + a tail
        k = int(delay * rate)
        env[k:] += np.exp(-(t[: len(t) - k]) * 120.0)
    env += 0.4 * np.exp(-t * 18.0)
    return _norm(noise * env)


def synth_808(rate: int = RATE) -> "np.ndarray":
    t = _t(0.6, rate)
    freq = 52.0 + 30.0 * np.exp(-t * 20.0)            # slight drop into a sub tone
    phase = 2 * np.pi * np.cumsum(freq) / rate
    return _norm(np.sin(phase) * np.exp(-t * 5.0))


def synth_tom(rate: int = RATE) -> "np.ndarray":
    t = _t(0.25, rate)
    freq = 90.0 + 90.0 * np.exp(-t * 9.0)
    phase = 2 * np.pi * np.cumsum(freq) / rate
    return _norm(np.sin(phase) * np.exp(-t * 12.0))


# -- kits ------------------------------------------------------------------------

@dataclass
class DrumKit:
    name: str
    voices: dict = field(default_factory=dict)

    def voice(self, role: str):
        return self.voices.get(role)

    def roles(self) -> list[str]:
        return [r for r in ROLES if r in self.voices]


def synth_kit(rate: int = RATE) -> DrumKit:
    return DrumKit("Synth (built-in)", {
        "kick": synth_kick(rate), "snare": synth_snare(rate), "hihat": synth_hihat(rate),
        "openhat": synth_openhat(rate), "clap": synth_clap(rate), "808": synth_808(rate),
        "tom": synth_tom(rate),
    })


def load_kit_from_folder(path, rate: int = RATE) -> DrumKit:
    """Load one representative sample per recognised ROLE subfolder (or role-named files)."""
    p = Path(path)
    voices: dict = {}
    for sub in sorted(p.iterdir()) if p.is_dir() else []:
        if not sub.is_dir():
            continue
        role = FOLDER_ROLE_MAP.get(sub.name.upper())
        if role is None or role in voices:
            continue
        wavs = sorted(sub.glob("*.wav"))
        for wav in wavs:  # take the first that loads cleanly
            try:
                voices[role] = load_sample(wav, rate)
                break
            except Exception:  # noqa: BLE001 - skip unreadable files
                continue
    if not voices and p.is_dir():  # flat folder of role-named files (kick.wav, snare.wav)
        for wav in sorted(p.glob("*.wav")):
            role = FOLDER_ROLE_MAP.get(wav.stem.upper())
            if role and role not in voices:
                try:
                    voices[role] = load_sample(wav, rate)
                except Exception:  # noqa: BLE001
                    continue
    return DrumKit(p.name, voices)


# -- patterns --------------------------------------------------------------------

@dataclass
class Pattern:
    name: str
    steps: int                 # total steps in one loop (e.g. 16)
    steps_per_beat: int        # e.g. 4 for sixteenth notes
    hits: dict                 # role -> list of step indices it fires on

    def step_seconds(self, bpm: float) -> float:
        return 60.0 / max(1.0, bpm) / max(1, self.steps_per_beat)

    def loop_seconds(self, bpm: float) -> float:
        return self.steps * self.step_seconds(bpm)

    def copy(self) -> "Pattern":
        return Pattern(self.name, self.steps, self.steps_per_beat,
                       {r: list(s) for r, s in self.hits.items()})


def _p(name: str, hits: dict) -> Pattern:
    return Pattern(name, 16, 4, hits)


#: Built-in grooves (16 steps of sixteenth notes in 4/4).
GENRE_PATTERNS = [
    _p("Rock", {"kick": [0, 8], "snare": [4, 12], "hihat": [0, 2, 4, 6, 8, 10, 12, 14]}),
    _p("Pop", {"kick": [0, 8, 11], "snare": [4, 12], "hihat": [0, 2, 4, 6, 8, 10, 12, 14]}),
    _p("Four on the Floor", {"kick": [0, 4, 8, 12], "clap": [4, 12], "hihat": [2, 6, 10, 14]}),
    _p("Funk", {"kick": [0, 3, 6, 10], "snare": [4, 12], "hihat": list(range(16))}),
    _p("Hip-Hop", {"kick": [0, 6, 10], "snare": [4, 12], "hihat": [0, 2, 4, 6, 8, 10, 12, 14]}),
    _p("Trap", {"kick": [0, 7, 10], "808": [0, 7, 10], "clap": [4, 12],
                "hihat": [0, 2, 3, 4, 6, 8, 10, 11, 12, 14]}),
    _p("Metal", {"kick": [0, 2, 4, 6, 8, 10, 12, 14], "snare": [4, 12], "crash": [0]}),
    _p("Half-Time", {"kick": [0, 10], "snare": [8], "hihat": [0, 2, 4, 6, 8, 10, 12, 14]}),
]


# -- rendering (the compensator) -------------------------------------------------

def _mix_wrap(buf: "np.ndarray", v: "np.ndarray", offset: int) -> None:
    """Add voice *v* into *buf* at *offset*, wrapping the tail to the start (seamless)."""
    length = len(buf)
    if length == 0 or len(v) == 0:
        return
    v = v[:length]                       # never longer than one loop
    offset %= length
    end = offset + len(v)
    if end <= length:
        buf[offset:end] += v
    else:
        first = length - offset
        buf[offset:] += v[:first]
        buf[: len(v) - first] += v[first:]


def render_loop(pattern: Pattern, kit: DrumKit, bpm: float, rate: int = RATE) -> bytes:
    """Pre-mix one loop of *pattern* played on *kit* at *bpm* into a 16-bit mono WAV."""
    if np is None:
        raise RuntimeError("numpy is required for the drum looper")
    step_s = pattern.step_seconds(bpm)
    length = max(1, int(round(pattern.steps * step_s * rate)))
    buf = np.zeros(length, dtype=np.float32)
    for role, steps_on in pattern.hits.items():
        voice = kit.voice(role)
        if voice is None or len(voice) == 0:
            continue
        for step in steps_on:
            if 0 <= step < pattern.steps:
                _mix_wrap(buf, voice, int(round(step * step_s * rate)))
    peak = float(np.max(np.abs(buf))) if length else 0.0
    if peak > 1.0:                       # prevent clipping without pumping quiet loops up
        buf = buf / peak
    pcm = (np.clip(buf, -1.0, 1.0) * 32767.0).astype("<i2")
    out = io.BytesIO()
    w = wave.open(out, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(pcm.tobytes())
    w.close()
    return out.getvalue()


# -- playback --------------------------------------------------------------------

class DrumLoopPlayer:
    """Loops a rendered WAV through the speakers; re-render and call :meth:`play` to change it."""

    def __init__(self) -> None:
        self._ok = winsound is not None
        self._path: str | None = None
        self.playing = False
        if winsound is not None:
            fd, self._path = tempfile.mkstemp(prefix="firehawk_loop_", suffix=".wav")
            os.close(fd)

    @property
    def available(self) -> bool:
        return self._ok

    def play(self, wav_bytes: bytes) -> None:
        if winsound is None or self._path is None:
            return
        try:
            with open(self._path, "wb") as f:
                f.write(wav_bytes)
            winsound.PlaySound(
                self._path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            self.playing = True
        except Exception:  # noqa: BLE001
            self._ok = False

    def stop(self) -> None:
        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except Exception:  # noqa: BLE001
                pass
        self.playing = False

    def dispose(self) -> None:
        self.stop()
        if self._path:
            try:
                os.remove(self._path)
            except OSError:
                pass
            self._path = None
