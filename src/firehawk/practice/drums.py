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
import random
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


def synth_crash(rate: int = RATE) -> "np.ndarray":
    t = _t(1.1, rate)
    rng = np.random.default_rng(5)
    noise = np.diff(rng.random(len(t)) * 2 - 1, prepend=0.0)  # bright wash
    return _norm(noise * np.exp(-t * 3.0), 0.75)


def synth_ride(rate: int = RATE) -> "np.ndarray":
    t = _t(0.6, rate)
    rng = np.random.default_rng(6)
    ping = np.sin(2 * np.pi * 950.0 * t) * np.exp(-t * 9.0)
    shimmer = np.diff(rng.random(len(t)) * 2 - 1, prepend=0.0) * np.exp(-t * 7.0)
    return _norm(0.55 * ping + 0.45 * shimmer, 0.7)


def synth_perc(rate: int = RATE) -> "np.ndarray":
    t = _t(0.09, rate)  # short woodblock-style blip
    return _norm(np.sin(2 * np.pi * 620.0 * t) * np.exp(-t * 40.0), 0.8)


# -- kits ------------------------------------------------------------------------

@dataclass
class DrumKit:
    name: str
    voices: dict = field(default_factory=dict)

    def voice(self, role: str):
        return self.voices.get(role)

    def roles(self) -> list[str]:
        # Canonical roles in display order, then any custom line ids (mix-and-match
        # patterns key voices by line id, e.g. "kick 2").
        known = [r for r in ROLES if r in self.voices]
        return known + sorted(k for k in self.voices if k not in ROLES)


def synth_kit(rate: int = RATE) -> DrumKit:
    return DrumKit("Synth (built-in)", {
        "kick": synth_kick(rate), "snare": synth_snare(rate), "hihat": synth_hihat(rate),
        "openhat": synth_openhat(rate), "clap": synth_clap(rate), "808": synth_808(rate),
        "tom": synth_tom(rate), "perc": synth_perc(rate), "ride": synth_ride(rate),
        "crash": synth_crash(rate),
    })


#: Name tokens that mark a sample as a vocal chop / chant rather than a drum hit.
#: Producer kits commonly hide these in PERC and FX folders; they make jarring
#: default drum voices, so the auto-pick skips them (they stay selectable by hand).
_VOCAL_TOKENS = {"AHH", "AH", "AAH", "UH", "UHH", "DUH", "HEY", "OOH", "OOOH", "WOO",
                 "YEAH", "YAH", "YA", "VOX", "VOCAL", "CHANT", "TALK", "LAUGH", "SKRRT"}

#: Roles whose default voice should be a short drum hit (808/fx may ring long).
_PERCUSSIVE_ROLES = {"kick", "snare", "hihat", "openhat", "clap", "perc", "tom",
                     "ride", "crash"}
_MAX_DEFAULT_HIT_SECONDS = 1.25


def _name_tokens(path) -> set[str]:
    return set(Path(path).stem.upper().replace("_", " ").split())


def wav_duration(path) -> float | None:
    """Seconds of audio in a WAV, from the header only (no decode).  None if unreadable."""
    try:
        raw = Path(path).read_bytes()
        if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
            return None
        rate = block = data_size = None
        pos, n = 12, len(raw)
        while pos + 8 <= n:
            cid = raw[pos:pos + 4]
            size = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
            if cid == b"fmt " and size >= 16:
                _fmt, _ch, rate, _br, block, _bits = struct.unpack(
                    "<HHIIHH", raw[pos + 8:pos + 24])
            elif cid == b"data":
                data_size = size
            pos += 8 + size + (size & 1)
        if not rate or not block or data_size is None:
            return None
        return data_size / block / rate
    except OSError:
        return None


def list_role_files(kit_dir) -> dict[str, list]:
    """Every .wav per recognised role folder in a kit directory, sorted by name."""
    p = Path(kit_dir)
    out: dict[str, list] = {}
    if not p.is_dir():
        return out
    for sub in sorted(p.iterdir()):
        if not sub.is_dir():
            continue
        role = FOLDER_ROLE_MAP.get(sub.name.upper())
        if role is None or role in out:
            continue
        wavs = sorted(sub.glob("*.wav"))
        if wavs:
            out[role] = wavs
    return out


def default_sample_for(role: str, files: list):
    """The best default file for a role: for drum-hit roles, prefer the first file
    that is neither vocal-named nor longer than a hit; otherwise just the first."""
    if not files:
        return None
    if role in _PERCUSSIVE_ROLES:
        for f in files:
            if _name_tokens(f) & _VOCAL_TOKENS:
                continue
            dur = wav_duration(f)
            if dur is not None and dur > _MAX_DEFAULT_HIT_SECONDS:
                continue
            return f
    return files[0]


def load_kit_from_folder(path, rate: int = RATE, choices: dict | None = None) -> DrumKit:
    """Load one sample per recognised ROLE subfolder (or role-named files).

    *choices* optionally maps role -> filename (basename) to use instead of the
    automatic pick, so users can select each part's sample (see the Kit Sounds
    dialog).  Unknown or missing filenames fall back to the automatic pick.
    """
    p = Path(path)
    voices: dict = {}
    for role, wavs in list_role_files(p).items():
        ordered = list(wavs)
        chosen_name = (choices or {}).get(role)
        chosen = next((w for w in ordered if w.name == chosen_name), None)
        if chosen is None:
            chosen = default_sample_for(role, ordered)
        if chosen is not None:  # try the pick first, then the rest as fallbacks
            ordered = [chosen] + [w for w in ordered if w != chosen]
        for wav in ordered:
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
    steps: int                 # total grid steps in one loop
    steps_per_beat: int        # grid steps per quarter note
    hits: dict                 # role -> list of step indices it fires on
    beats_per_bar: int = 4     # time-signature numerator
    beat_unit: int = 4         # time-signature denominator (2/4/8/16)
    bars: int = 1

    def step_seconds(self, bpm: float) -> float:
        return 60.0 / max(1.0, bpm) / max(1, self.steps_per_beat)

    def loop_seconds(self, bpm: float) -> float:
        return self.steps * self.step_seconds(bpm)

    def meter_label(self) -> str:
        return f"{self.beats_per_bar}/{self.beat_unit}"

    def copy(self) -> "Pattern":
        return Pattern(self.name, self.steps, self.steps_per_beat,
                       {r: list(s) for r, s in self.hits.items()},
                       self.beats_per_bar, self.beat_unit, self.bars)


#: Grid resolutions as (label, steps-per-quarter-note).
GRID_CHOICES = [("Quarter", 1), ("Eighth", 2), ("Triplet", 3), ("Sixteenth", 4)]
BEAT_UNITS = [2, 4, 8, 16]
MAX_STEPS = 64  # keep the step grid navigable


def steps_per_bar(beats_per_bar: int, beat_unit: int, grid: int) -> int:
    """Grid steps in one bar of beats/unit at *grid* steps per quarter note."""
    return max(1, round(beats_per_bar * (4.0 / max(1, beat_unit)) * grid))


def blank_pattern(beats_per_bar: int, beat_unit: int, grid: int, bars: int = 1) -> Pattern:
    """An empty pattern for a given time signature, grid, and bar count."""
    total = steps_per_bar(beats_per_bar, beat_unit, grid) * max(1, bars)
    return Pattern(f"{beats_per_bar}/{beat_unit}", total, grid, {},
                   beats_per_bar, beat_unit, bars)


def _p(name: str, hits: dict, beats: int = 4, unit: int = 4, grid: int = 4, bars: int = 1) -> Pattern:
    return Pattern(name, steps_per_bar(beats, unit, grid) * bars, grid, hits, beats, unit, bars)


#: Built-in grooves. 4/4 ones are 16 sixteenth-note steps; odd meters set their own grid.
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
    # --- odd / prog meters ---
    _p("5/4", {"kick": [0, 10, 16], "snare": [4, 12], "hihat": list(range(0, 20, 2))},
       beats=5, unit=4),
    _p("7/8 (2+2+3)", {"kick": [0, 4], "snare": [2], "hihat": [0, 1, 2, 3, 4, 5, 6]},
       beats=7, unit=8, grid=2),
    _p("6/8", {"kick": [0, 3], "snare": [3], "hihat": [0, 1, 2, 3, 4, 5]},
       beats=6, unit=8, grid=2),
    _p("5/8 (3+2)", {"kick": [0, 3], "snare": [3], "hihat": [0, 1, 2, 3, 4]},
       beats=5, unit=8, grid=2),
    _p("Djent 7/16 (poly)", {"kick": [0, 1, 2, 4, 5], "808": [0, 4], "snare": [3]},
       beats=7, unit=16, grid=4),
]


# -- the pattern library (200 grooves: hand-made bases + seeded variations) --------

def _metrical_beat_len(p: Pattern) -> int:
    """Grid steps in one metrical beat of the pattern (e.g. an eighth in 7/8)."""
    return max(1, round(p.steps_per_beat * 4.0 / max(1, p.beat_unit)))


def _two_bars(base: Pattern, name: str) -> Pattern:
    """The base groove repeated over two bars (so a fill can live in bar 2)."""
    per = base.steps
    hits = {r: sorted({s + b * per for b in range(2) for s in steps})
            for r, steps in base.hits.items()}
    return Pattern(name, per * 2, base.steps_per_beat, hits,
                   base.beats_per_bar, base.beat_unit, 2)


def _generate_variation(base: Pattern, seed: int, with_fill: bool, name: str) -> Pattern:
    """A deterministic musical variation of *base* (same seed -> same groove forever)."""
    rng = random.Random(seed)
    p = _two_bars(base, name)
    total = p.steps
    beat_len = _metrical_beat_len(p)

    # Hat movement: drop or add a few hat steps so the ride pattern breathes.
    hat = set(p.hits.get("hihat", []))
    if hat:
        for _ in range(rng.randint(1, 3)):
            s = rng.randrange(total)
            if s in hat and rng.random() < 0.5:
                hat.discard(s)
            else:
                hat.add(s)
        p.hits["hihat"] = sorted(hat)
    if rng.random() < 0.45:  # occasional open hat, replacing the closed one there
        s = rng.randrange(total)
        p.hits.setdefault("openhat", [])
        p.hits["openhat"] = sorted(set(p.hits["openhat"]) | {s})
        if "hihat" in p.hits:
            p.hits["hihat"] = [x for x in p.hits["hihat"] if x != s]

    # Kick syncopation: up to two extra kicks, avoiding the backbeat snares.
    snare = set(p.hits.get("snare", []))
    kicks = set(p.hits.get("kick", []))
    for _ in range(rng.randint(0, 2)):
        s = rng.randrange(total)
        if s not in snare:
            kicks.add(s)
    p.hits["kick"] = sorted(kicks)
    if "808" in base.hits:  # trap-style: the sub shadows the kick
        p.hits["808"] = sorted(kicks)

    if rng.random() < 0.4:  # light percussion sprinkle
        p.hits["perc"] = sorted(rng.sample(range(total), k=rng.randint(1, 3)))

    if with_fill:
        # Fill: clear the last beat(s) of bar 2 and run snare/tom through it, with a
        # crash landing on the loop restart. Sized from the meter, so it always fits.
        fill_beats = rng.choice((1, 2)) if p.beats_per_bar >= 4 else 1
        start = total - min(total, beat_len * fill_beats)
        for role in ("snare", "hihat", "openhat", "clap", "tom", "perc"):
            if role in p.hits:
                p.hits[role] = [s for s in p.hits[role] if s < start]
        for s in range(start, total):
            if rng.random() < 0.85:
                p.hits.setdefault(rng.choice(("snare", "tom", "tom", "snare")), []).append(s)
        for role in ("snare", "tom"):
            if role in p.hits:
                p.hits[role] = sorted(set(p.hits[role]))
        p.hits["crash"] = sorted(set(p.hits.get("crash", [])) | {0})

    p.hits = {r: s for r, s in p.hits.items() if s}  # drop emptied roles
    return p


def build_pattern_library(total: int = 200) -> list[Pattern]:
    """The full groove list: the hand-made bases plus seeded variations up to *total*.

    Seeds are fixed, so the library is identical every launch — pattern 137 today is
    pattern 137 forever.
    """
    library = [p.copy() for p in GENRE_PATTERNS]
    counters: dict[str, int] = {}
    i = 0
    while len(library) < total:
        base = GENRE_PATTERNS[i % len(GENRE_PATTERNS)]
        n = counters.get(base.name, 2)  # the base itself is number 1
        counters[base.name] = n + 1
        with_fill = i % 2 == 1
        name = f"{base.name} {n:02d}" + (" fill" if with_fill else "")
        library.append(_generate_variation(base, seed=1000 + i, with_fill=with_fill, name=name))
        i += 1
    return library


#: Built once at import; deterministic (see build_pattern_library).
PATTERN_LIBRARY = build_pattern_library()


def retime_pattern(p: Pattern, beats: int, unit: int, grid: int, bars: int) -> Pattern:
    """Return *p* fitted to a new meter/bar count.

    If the bar shape (steps per bar and grid) is unchanged, the existing bars are
    **tiled cyclically** across the new bar count — so growing 2 bars to 4 repeats
    the music instead of appending silence, and shrinking keeps the first bars.
    If the bar shape changed, hits that still fit the new step count are kept.
    """
    per_bar = steps_per_bar(beats, unit, grid)
    bars = max(1, bars)
    total = per_bar * bars
    old_bars = max(1, p.bars)
    old_per_bar = max(1, p.steps // old_bars)
    name = f"{beats}/{unit}"
    if per_bar == old_per_bar and grid == p.steps_per_beat:
        hits: dict = {}
        for role, steps in p.hits.items():
            out = set()
            for b in range(bars):
                src = b % old_bars
                lo, hi = src * old_per_bar, (src + 1) * old_per_bar
                out.update(s - lo + b * per_bar for s in steps if lo <= s < hi)
            if out:
                hits[role] = sorted(out)
    else:
        hits = {r: [s for s in steps if s < total] for r, steps in p.hits.items() if steps}
    return Pattern(name, total, grid, hits, beats, unit, bars)


def expand_with_fill(p: Pattern, total_bars: int) -> Pattern:
    """Stretch a groove to *total_bars* with its fill (last bar) landing only at the end.

    For a jam: 'fill every 12 bars' plays the plain groove for 11 bars, then the
    pattern's final bar (where library fills live) as the turnaround.  One-bar
    patterns simply repeat.  Returns *p* unchanged when no stretch is needed.
    """
    if total_bars <= p.bars:
        return p
    per_bar = max(1, p.steps // max(1, p.bars))
    if p.bars >= 2:
        body = list(range(p.bars - 1))
        order = [body[i % len(body)] for i in range(total_bars - 1)] + [p.bars - 1]
    else:
        order = [0] * total_bars
    hits: dict = {}
    for role, steps in p.hits.items():
        out = []
        for dst, src in enumerate(order):
            if role == "crash" and src == 0 and dst != 0:
                # A first-bar crash marks the post-fill downbeat (the loop restart);
                # tiling it onto every body bar would crash constantly.
                continue
            lo, hi = src * per_bar, (src + 1) * per_bar
            out.extend(s - lo + dst * per_bar for s in steps if lo <= s < hi)
        if out:
            hits[role] = sorted(out)
    return Pattern(p.name, per_bar * total_bars, p.steps_per_beat, hits,
                   p.beats_per_bar, p.beat_unit, total_bars)


# -- improvised fills (rule-bound randomness, Diablo-dungeon style) ----------------

_FILL_CLEAR_ROLES = ("snare", "hihat", "openhat", "clap", "tom", "perc")


def _generate_fill_zone(rng: "random.Random", beat_len: int, per_bar: int):
    """One generated fill: (length in grid steps, hits keyed by offset-in-zone).

    Length varies — usually one or two beats, occasionally a whole bar — and the
    run is a snare/tom mix with varying density and an occasional kick pickup, so
    consecutive fills rarely feel the same.  Everything is measured in grid steps,
    so it lands on the meter whatever the time signature.
    """
    fill_len = min(per_bar, beat_len * rng.choice((1, 1, 1, 2, 2, per_bar // max(1, beat_len))))
    fill_len = max(1, fill_len)
    hits: dict = {}
    density = rng.uniform(0.6, 0.95)
    for s in range(fill_len):
        if rng.random() < density:
            hits.setdefault(rng.choice(("snare", "tom", "tom", "snare", "perc")), []).append(s)
    if fill_len >= beat_len and rng.random() < 0.4:  # kick pickup into the fill
        hits.setdefault("kick", []).append(0)
    return fill_len, hits


def improvised_loop(p: Pattern, cycle_bars: int, cycles: int = 4,
                    seed: int | None = None) -> Pattern:
    """A long loop of *cycles* passes of the groove, each ending in a *different*
    generated fill — programmatic improvisation.

    Each cycle is *cycle_bars* long: the plain groove (the pattern minus its own
    final-bar fill, if it has one) fills the cycle, then a freshly generated fill
    is carved into the cycle's last beats, with a crash on each cycle's downbeat.
    With ``seed=None`` every render improvises anew.
    """
    rng = random.Random(seed)
    per_bar = max(1, p.steps // max(1, p.bars))
    beat_len = _metrical_beat_len(p)
    body_bars = list(range(p.bars - 1)) if p.bars >= 2 else [0]
    cycle_bars = max(1, cycle_bars)
    total_bars = cycle_bars * max(1, cycles)
    total_steps = per_bar * total_bars
    hits: dict = {}

    def copy_bar(src: int, dst: int) -> None:
        lo, hi = src * per_bar, (src + 1) * per_bar
        for role, steps in p.hits.items():
            if role == "crash":
                continue  # crashes are re-placed on cycle downbeats below
            sel = [s - lo + dst * per_bar for s in steps if lo <= s < hi]
            if sel:
                hits.setdefault(role, []).extend(sel)

    for c in range(max(1, cycles)):
        base = c * cycle_bars
        for b in range(cycle_bars):
            copy_bar(body_bars[b % len(body_bars)], base + b)
        fill_len, fill_hits = _generate_fill_zone(rng, beat_len, per_bar)
        zone_start = (base + cycle_bars) * per_bar - fill_len
        for role in _FILL_CLEAR_ROLES:
            if role in hits:
                hits[role] = [s for s in hits[role] if not (zone_start <= s)
                              or s >= zone_start + fill_len]
        for role, offsets in fill_hits.items():
            hits.setdefault(role, []).extend(zone_start + o for o in offsets)
        # Crash lands on the downbeat after each fill (wrapping at the loop end).
        hits.setdefault("crash", []).append(((base + cycle_bars) * per_bar) % total_steps)

    hits = {r: sorted(set(s)) for r, s in hits.items() if s}
    return Pattern(f"{p.name} improv", total_steps, p.steps_per_beat, hits,
                   p.beats_per_bar, p.beat_unit, total_bars)


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


def render_loop(pattern: Pattern, kit: DrumKit, bpm: float, rate: int = RATE,
                volume: float = 1.0) -> bytes:
    """Pre-mix one loop of *pattern* played on *kit* at *bpm* into a 16-bit mono WAV.

    *volume* (0..1) scales the finished mix — the drums' master volume.
    """
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
    buf = buf * max(0.0, min(1.0, volume))
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
