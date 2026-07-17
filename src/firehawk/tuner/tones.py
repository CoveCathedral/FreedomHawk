"""Reference-tone generation and playback for the by-ear tuner.

Synthesizes a clean, sustained tone at a note's pitch and loops it through the
computer's speakers, so you tune each string to the tone by ear.  No pedal, no
protocol, no microphone — just audio out.  Uses the Windows ``winsound`` API with an
in-memory WAV (whole number of cycles, so the loop is seamless).
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
except ImportError:  # non-Windows (tests still exercise the pure-data functions)
    winsound = None

_SEMITONES = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
    "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11,
}

A4_HZ = 440.0
A4_MIDI = 69


def note_to_midi(name: str) -> int:
    """Note name like 'E2', 'A#1', 'Bb3' -> MIDI note number (C4 = 60)."""
    s = name.strip()
    i = 1
    if len(s) > 1 and s[1] in "#b":
        i = 2
    letter = s[:i].upper()
    octave = int(s[i:])
    if letter not in _SEMITONES:
        raise ValueError(f"bad note name: {name!r}")
    return (octave + 1) * 12 + _SEMITONES[letter]


def note_frequency(name: str) -> float:
    """Equal-tempered frequency in Hz for a note name (A4 = 440 Hz)."""
    return A4_HZ * 2.0 ** ((note_to_midi(name) - A4_MIDI) / 12.0)


def sine_wav(freq: float, seconds: float = 0.35, rate: int = 44100, volume: float = 0.5) -> bytes:
    """A mono 16-bit WAV of a near-sine tone, trimmed to a whole number of cycles.

    A faint 2nd/3rd harmonic is added so the pitch reads clearly on small speakers
    while staying clean enough to tune against.
    """
    cycles = max(1, round(freq * seconds))
    n = max(1, round(cycles * rate / freq))
    frames = bytearray()
    for k in range(n):
        t = k / rate
        s = (math.sin(2 * math.pi * freq * t)
             + 0.20 * math.sin(2 * math.pi * 2 * freq * t)
             + 0.08 * math.sin(2 * math.pi * 3 * freq * t))
        frames += struct.pack("<h", int(max(-1.0, min(1.0, s / 1.28)) * volume * 32767))
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(bytes(frames))
    w.close()
    return buf.getvalue()


class TonePlayer:
    """Plays one looping reference tone at a time; call :meth:`stop` to silence.

    winsound cannot loop from memory asynchronously, so the tone is written to a temp
    WAV file and played with SND_FILENAME | SND_ASYNC | SND_LOOP (a whole number of
    cycles, so the loop is seamless).
    """

    def __init__(self) -> None:
        self.playing_freq: float | None = None
        self._ok = winsound is not None
        self._path: str | None = None
        if winsound is not None:
            fd, self._path = tempfile.mkstemp(prefix="firehawk_tone_", suffix=".wav")
            os.close(fd)

    @property
    def available(self) -> bool:
        return self._ok

    def play_note(self, name: str) -> float:
        """Play a sustained tone for a note name; returns its frequency."""
        freq = note_frequency(name)
        if winsound is None or self._path is None:
            self.playing_freq = freq
            return freq
        try:
            with open(self._path, "wb") as f:
                f.write(sine_wav(freq, seconds=0.5))
            winsound.PlaySound(
                self._path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
            self.playing_freq = freq
        except Exception:  # noqa: BLE001 - audio device may be unavailable
            self._ok = False
        return freq

    def stop(self) -> None:
        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except Exception:  # noqa: BLE001
                pass
        self.playing_freq = None

    def dispose(self) -> None:
        """Stop playback and remove the temp file."""
        self.stop()
        if self._path:
            try:
                os.remove(self._path)
            except OSError:
                pass
            self._path = None
