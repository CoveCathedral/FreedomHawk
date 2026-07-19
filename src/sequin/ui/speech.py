"""Direct screen-reader speech for custom navigation surfaces.

Native widgets announce themselves, but a tracker-style grid (arrow keys moving a
time cursor) has nothing native to announce each move — so we speak through the
running screen reader directly (NVDA when present, SAPI otherwise), the same way
accessible DAW tools do.  Degrades to a no-op if accessible_output2 is missing, in
which case callers should fall back to widget-based feedback.
"""

from __future__ import annotations

_speaker = None
_tried = False


def _get_speaker():
    global _speaker, _tried
    if not _tried:
        _tried = True
        try:
            from accessible_output2.outputs import auto
            _speaker = auto.Auto()
        except Exception:  # noqa: BLE001 - any failure means no direct speech
            _speaker = None
    return _speaker


def available() -> bool:
    return _get_speaker() is not None


def speak(text: str, interrupt: bool = True) -> None:
    """Speak *text* through the screen reader; silently a no-op if unavailable."""
    s = _get_speaker()
    if s is not None and text:
        try:
            s.speak(text, interrupt=interrupt)
        except Exception:  # noqa: BLE001 - speech must never crash the UI
            pass
