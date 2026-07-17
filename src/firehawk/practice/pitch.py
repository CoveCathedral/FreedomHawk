"""Fundamental-pitch estimation for drum samples — UI-free, numpy only.

Drums are only *partly* pitched: kicks, toms and 808s have a clear fundamental,
snares a weaker resonant tone under the noise, and hats/cymbals essentially none.
So estimation returns a *confidence* alongside the note, and the caller decides
whether the pitch is meaningful (see :func:`is_pitched`).

Kept independent of the pedal and the UI so it can travel with the standalone
step sequencer.  Only depends on numpy, already required for the drum looper.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

try:  # numpy is required for any audio work; degrade to "no estimate" without it
    import numpy as np
except Exception:  # pragma: no cover - numpy always present where audio runs
    np = None  # type: ignore

#: Semitone names, C-based (sharps), matching how drummers label tuned toms.
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

#: Below this normalized-autocorrelation peak a sound is treated as unpitched
#: (noise-dominated: most snares, all hats and cymbals).  Tuned drums — kicks,
#: toms, 808s — land above it; rides/snares/hats fall clearly below.
PITCH_CONFIDENCE_MIN = 0.45

#: Highest plausible fundamental per role, so a kick can't lock onto a high harmonic.
#: 808s live in the sub-bass; kicks range from sub-bass to a mid "knock"; toms higher;
#: tuned percussion may ring up top.  (Snares/hats stay noise and fall out on confidence.)
_ROLE_FMAX = {"kick": 150.0, "808": 200.0, "tom": 400.0, "snare": 520.0}


def role_fmax(role: str | None) -> float:
    """The highest fundamental worth searching for a given drum role."""
    return _ROLE_FMAX.get(role or "", 1200.0)


@dataclass(frozen=True)
class Pitch:
    """An estimated pitch: frequency, its nearest note, cents error, confidence."""
    freq_hz: float
    note: str        # e.g. "G1" — nearest equal-tempered note (A4 = 440 Hz)
    cents: float     # signed distance to that note, -50..+50
    confidence: float  # 0..1 normalized autocorrelation at the detected period

    @property
    def pitched(self) -> bool:
        return self.confidence >= PITCH_CONFIDENCE_MIN

    def label(self) -> str:
        """A spoken/displayed label: 'G1 (+12 cents)', or '~G1' when uncertain."""
        cents = f" ({self.cents:+.0f} cents)" if abs(self.cents) >= 3 else ""
        return f"{self.note}{cents}" if self.pitched else f"~{self.note}"


def note_from_freq(freq: float) -> tuple[str, float]:
    """Nearest equal-tempered note name (A4 = 440 Hz) and signed cents error."""
    if freq <= 0:
        return "?", 0.0
    midi = 69.0 + 12.0 * math.log2(freq / 440.0)
    nearest = int(round(midi))
    cents = (midi - nearest) * 100.0
    name = NOTE_NAMES[nearest % 12]
    octave = nearest // 12 - 1
    return f"{name}{octave}", cents


def note_name_for_semitones(base_freq: float, semitones: int) -> str:
    """The note *semitones* away from *base_freq* — used for tuning readouts."""
    name, _ = note_from_freq(base_freq * (2.0 ** (semitones / 12.0)))
    return name


def estimate_pitch(samples, rate: int, fmin: float = 25.0,
                   fmax: float | None = None, role: str | None = None) -> Pitch | None:
    """Estimate a sample's fundamental by autocorrelation; None if it can't.

    Skips the attack, tries a few windows down the decay and keeps the most
    self-similar, and searches the *fmin*..*fmax* period band.  Pass *role* (or an
    explicit *fmax*) to bound the search to that drum's plausible range — a kick
    can't then lock onto a high harmonic.  The peak height over the zero-lag energy
    is the confidence, so noise-only sounds come back low rather than confidently wrong.
    """
    if np is None:
        return None
    if fmax is None:
        fmax = role_fmax(role)
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:                       # downmix stereo/multi-channel to mono
        x = x.mean(axis=1)
    if len(x) < rate // 100:             # shorter than ~10 ms: nothing to measure
        return None
    peak_amp = float(np.max(np.abs(x)))
    if peak_amp <= 0.0:
        return None
    onset = int(np.argmax(np.abs(x) > 0.1 * peak_amp))
    # Kicks and 808s glide down in pitch over the first tens-to-hundreds of ms, so the
    # settled fundamental (the "note" a drummer tunes to) can sit well past the onset —
    # and how far varies by sample.  Try a few windows down the decay and keep the most
    # self-similar (highest-confidence) one: that auto-selects the settled sustain for
    # tuned drums while still working for short one-shots (only the early window fits).
    best: Pitch | None = None
    for skip in (0.045, 0.12, 0.22):
        start = onset + int(skip * rate)
        win = x[start:start + int(0.35 * rate)]
        if len(win) < rate // 50:        # too little left here; earlier windows covered it
            continue
        cand = _autocorr_pitch(win, rate, fmin, fmax)
        if cand and (best is None or cand.confidence > best.confidence):
            best = cand
    if best is None:                     # very short sound: measure the body as-is
        win = x[onset:onset + int(0.35 * rate)]
        if len(win) >= rate // 100:
            best = _autocorr_pitch(win, rate, fmin, fmax)
    return best


def _autocorr_pitch(win, rate: int, fmin: float, fmax: float) -> Pitch | None:
    """Estimate the fundamental of one already-sliced window by autocorrelation."""
    win = (win - np.mean(win)) * np.hanning(len(win))
    n = 1
    while n < 2 * len(win):              # zero-pad to a power of two for the FFT
        n <<= 1
    spec = np.fft.rfft(win, n)
    ac = np.fft.irfft(spec * np.conj(spec), n)[: len(win)]
    if ac[0] <= 0:
        return None
    lag_min = max(1, int(rate / fmax))
    lag_max = min(len(ac) - 1, int(rate / fmin))
    if lag_max <= lag_min:
        return None
    # Skip the zero-lag lobe: a low fundamental keeps the autocorrelation high near
    # tiny lags, so a plain argmax grabs the left edge and reports a bogus high note.
    # The real period sits past the lobe's first zero crossing.
    below = np.where(ac[:lag_max + 1] <= 0)[0]
    search_lo = max(lag_min, int(below[0])) if len(below) else lag_min
    if search_lo >= lag_max:
        search_lo = lag_min
    peak = int(np.argmax(ac[search_lo:lag_max + 1])) + search_lo
    confidence = float(ac[peak] / ac[0])
    lag = float(peak)
    if 1 <= peak < len(ac) - 1:          # parabolic refine for sub-sample accuracy
        a, b, c = ac[peak - 1], ac[peak], ac[peak + 1]
        denom = a - 2 * b + c
        if denom:
            shift = 0.5 * (a - c) / denom
            if -0.5 <= shift <= 0.5:     # a true interior max never moves further
                lag = peak + shift
    freq = rate / lag
    note, cents = note_from_freq(freq)
    return Pitch(freq, note, cents, max(0.0, min(1.0, confidence)))
