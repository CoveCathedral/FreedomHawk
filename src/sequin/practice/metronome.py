"""Metronome engine: click synthesis, beat timing, tap-tempo, and playback.

Deliberately UI-free.  The wx panel owns a timer and, on each tick, asks
:func:`click_kind` what to play and tells :class:`ClickPlayer` to play it.  A short
percussive click is synthesized once per sound and played as a one-shot WAV via the
Windows ``winsound`` API (the same approach the tuner uses).
"""

from __future__ import annotations

import io
import math
import os
import struct
import tempfile
import wave

try:
    import winsound
except ImportError:  # non-Windows (tests still exercise the pure functions)
    winsound = None

TEMPO_MIN = 30.0
TEMPO_MAX = 300.0
BEATS_PER_MEASURE_MAX = 16

#: Selectable subdivisions as (label, ticks-per-beat).
SUBDIVISIONS = [
    ("Quarter notes", 1),
    ("Eighth notes", 2),
    ("Triplets", 3),
    ("Sixteenth notes", 4),
]

#: Note values that can sit under the time signature (the "4" in 4/4).
BEAT_UNITS = [2, 4, 8, 16]

#: Per click kind: (frequency Hz, duration ms, volume 0..1).
_CLICK_VOICES = {
    "accent": (1568.0, 42.0, 0.9),   # downbeat: highest and loudest
    "beat": (1047.0, 36.0, 0.6),     # other main beats
    "sub": (1047.0, 24.0, 0.32),     # off-beat subdivisions: quiet
}


def beat_interval(bpm: float, subdivision: int) -> float:
    """Seconds between clicks for a tempo and subdivision (ticks per quarter note)."""
    bpm = max(TEMPO_MIN, min(TEMPO_MAX, bpm))
    subdivision = max(1, subdivision)
    return 60.0 / bpm / subdivision


def click_kind(tick: int, beats_per_measure: int, subdivision: int) -> str:
    """Classify a tick as the downbeat 'accent', a main 'beat', or a 'sub' division."""
    ticks_per_measure = max(1, beats_per_measure) * max(1, subdivision)
    pos = tick % ticks_per_measure
    if pos == 0:
        return "accent"
    if pos % max(1, subdivision) == 0:
        return "beat"
    return "sub"


def parse_grouping(text: str, beats: int) -> list[int] | None:
    """Parse an accent grouping like '2+2+3' into group sizes, or None if it doesn't fit.

    For odd meters (prog: 5/8, 7/8, 9/8, ...) this places a secondary accent at the start
    of each group, so 7 grouped as 2+2+3 accents beats 1, 3 and 5.
    """
    try:
        parts = [int(p) for p in text.replace(" ", "").split("+") if p]
    except ValueError:
        return None
    if not parts or any(p <= 0 for p in parts) or sum(parts) != beats:
        return None
    return parts


def group_start_beats(beats: int, grouping: list[int] | None) -> set[int]:
    """The 0-based beat indices that begin an accent group (just the downbeat by default)."""
    if not grouping:
        return {0}
    starts, idx = set(), 0
    for size in grouping:
        if idx >= beats:
            break
        starts.add(idx)
        idx += size
    return starts or {0}


def click_kind_grouped(tick: int, beats: int, subdivision: int, group_starts: set[int]) -> str:
    """Like click_kind, but every group start (not only beat 1) gets the 'accent' voice."""
    per_measure = max(1, beats) * max(1, subdivision)
    pos = tick % per_measure
    if pos % max(1, subdivision) != 0:
        return "sub"
    beat_index = pos // max(1, subdivision)
    return "accent" if beat_index in group_starts else "beat"


def click_wav(freq: float, ms: float = 35.0, volume: float = 0.6, rate: int = 44100) -> bytes:
    """A mono 16-bit WAV of a short percussive click (fast-decaying sine with a soft attack)."""
    n = max(1, int(rate * ms / 1000.0))
    attack = max(1, int(rate * 0.001))          # ~1 ms fade-in to avoid a pop
    tau = (ms / 1000.0) / 4.0                    # exponential decay time constant
    frames = bytearray()
    for k in range(n):
        t = k / rate
        env = math.exp(-t / tau)
        if k < attack:
            env *= k / attack
        s = math.sin(2 * math.pi * freq * t) * env * volume
        frames += struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(bytes(frames))
    w.close()
    return buf.getvalue()


class TapTempo:
    """Averages recent tap timestamps into a BPM.  A long gap starts a fresh series."""

    def __init__(self, reset_gap: float = 2.0, max_taps: int = 8) -> None:
        self._times: list[float] = []
        self._reset_gap = reset_gap
        self._max_taps = max_taps

    def tap(self, now: float) -> float | None:
        """Record a tap at time *now* (seconds); return the current BPM once there are two."""
        if self._times and now - self._times[-1] > self._reset_gap:
            self._times = []
        self._times.append(now)
        if len(self._times) > self._max_taps:
            self._times = self._times[-self._max_taps:]
        if len(self._times) < 2:
            return None
        intervals = [b - a for a, b in zip(self._times, self._times[1:])]
        avg = sum(intervals) / len(intervals)
        if avg <= 0:
            return None
        return max(TEMPO_MIN, min(TEMPO_MAX, 60.0 / avg))

    def reset(self) -> None:
        self._times = []


class ClickPlayer:
    """Pre-renders the three click voices to temp WAVs and plays them as one-shots."""

    def __init__(self) -> None:
        self._ok = winsound is not None
        self._paths: dict[str, str] = {}
        if winsound is not None:
            for kind, (freq, ms, vol) in _CLICK_VOICES.items():
                fd, path = tempfile.mkstemp(prefix=f"firehawk_click_{kind}_", suffix=".wav")
                os.close(fd)
                with open(path, "wb") as fh:
                    fh.write(click_wav(freq, ms, vol))
                self._paths[kind] = path

    @property
    def available(self) -> bool:
        return self._ok

    def play(self, kind: str) -> None:
        path = self._paths.get(kind)
        if winsound is None or path is None:
            return
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:  # noqa: BLE001 - audio device may be unavailable
            self._ok = False

    def stop(self) -> None:
        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except Exception:  # noqa: BLE001
                pass

    def dispose(self) -> None:
        self.stop()
        for path in self._paths.values():
            try:
                os.remove(path)
            except OSError:
                pass
        self._paths = {}
