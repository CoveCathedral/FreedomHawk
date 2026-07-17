"""Practice tools that live in the app rather than the pedal (metronome, and later
a drum looper).  Pure-Python audio and timing helpers, kept free of any UI toolkit
so they can be unit-tested headlessly."""

from .drums import (
    GENRE_PATTERNS,
    NUMPY_AVAILABLE,
    ROLE_LABELS,
    ROLES,
    DrumKit,
    DrumLoopPlayer,
    Pattern,
    load_kit_from_folder,
    render_loop,
    synth_kit,
)
from .metronome import (
    BEAT_UNITS,
    BEATS_PER_MEASURE_MAX,
    SUBDIVISIONS,
    ClickPlayer,
    TapTempo,
    beat_interval,
    click_kind,
    click_wav,
)

__all__ = [
    "BEAT_UNITS",
    "BEATS_PER_MEASURE_MAX",
    "SUBDIVISIONS",
    "ClickPlayer",
    "TapTempo",
    "beat_interval",
    "click_kind",
    "click_wav",
    "GENRE_PATTERNS",
    "NUMPY_AVAILABLE",
    "ROLE_LABELS",
    "ROLES",
    "DrumKit",
    "DrumLoopPlayer",
    "Pattern",
    "load_kit_from_folder",
    "render_loop",
    "synth_kit",
]
