"""Sequin — the accessible, screen-reader-first step sequencer / drum machine.

Designed non-visually from the ground up (built and tested with NVDA): a spoken tracker
grid IS the interface, not a visual surface being narrated.  Sequin ships embedded in
FreedomHawk and runs standalone from this same package (``python -m sequin``).

Layers:
- ``sequin.practice`` — the engine (drums, patterns, songs, metronome, MIDI, pitch).
  Deliberately UI-free and dependency-light (stdlib + numpy) so it lifts out cleanly.
- ``sequin.ui`` — the wxPython UI (the sequencer panel, metronome panel) and the shared
  accessibility helpers (speech, forced accessible names, theme) the whole app is built on.
- ``sequin.config`` — a small persistent settings store.
- ``sequin.app`` — the standalone ``SequinFrame`` window and ``main()`` entry point.
"""
