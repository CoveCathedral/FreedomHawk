"""The metronome page — a practice tool the pedal never had.

Adjustable tempo, time signature, and subdivision, with an accented downbeat and
tap-tempo.  Every control is a labelled native widget so it reads and operates with
a screen reader; the beat itself is audio, so it never competes with the reader for
the keyboard.  Unlike the tuner tone, the metronome keeps running when you switch to
another tab, so you can tweak a tone while it keeps time — Stop or closing the app
ends it.
"""

from __future__ import annotations

import time
from typing import Callable

import wx

from ..practice import (
    BEAT_UNITS,
    BEATS_PER_MEASURE_MAX,
    SUBDIVISIONS,
    ClickPlayer,
    TapTempo,
    beat_interval,
    click_kind,
)
from .accessibility import set_accessible_name

TEMPO_MIN = 30
TEMPO_MAX = 300


class MetronomePanel(wx.Panel):
    def __init__(self, parent: wx.Window, status: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._status = status
        self.player = ClickPlayer()
        self._tap = TapTempo()
        self._tick = 0
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)

        root = wx.BoxSizer(wx.VERTICAL)
        hint = wx.StaticText(
            self, label="Set the tempo and time signature, then Start. The first beat of "
                        "each measure is accented. The metronome keeps playing while you "
                        "work on other tabs; press Stop or close the app to end it.")
        root.Add(hint, 0, wx.ALL, 8)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)

        # Tempo (BPM)
        self.tempo_label = wx.StaticText(self, label="Tempo: 120 BPM")
        grid.Add(self.tempo_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.tempo_slider = wx.Slider(
            self, value=120, minValue=TEMPO_MIN, maxValue=TEMPO_MAX,
            style=wx.SL_HORIZONTAL)
        set_accessible_name(self.tempo_slider, "Tempo, beats per minute")
        self.tempo_slider.Bind(wx.EVT_SLIDER, self._on_tempo)
        grid.Add(self.tempo_slider, 0, wx.EXPAND)

        # Beats per measure (top of the time signature)
        grid.Add(wx.StaticText(self, label="Beats per measure:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.beats_choice = wx.Choice(
            self, choices=[str(n) for n in range(1, BEATS_PER_MEASURE_MAX + 1)])
        self.beats_choice.SetSelection(3)  # 4
        set_accessible_name(self.beats_choice, "Beats per measure")
        self.beats_choice.Bind(wx.EVT_CHOICE, self._on_structure)
        grid.Add(self.beats_choice, 0, wx.EXPAND)

        # Beat unit (bottom of the time signature)
        grid.Add(wx.StaticText(self, label="Beat unit (note value):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.unit_choice = wx.Choice(self, choices=[str(n) for n in BEAT_UNITS])
        self.unit_choice.SetSelection(BEAT_UNITS.index(4))
        set_accessible_name(self.unit_choice, "Beat unit, note value")
        self.unit_choice.Bind(wx.EVT_CHOICE, self._on_structure)
        grid.Add(self.unit_choice, 0, wx.EXPAND)

        # Subdivision
        grid.Add(wx.StaticText(self, label="Subdivision:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.subdiv_choice = wx.Choice(self, choices=[label for label, _ in SUBDIVISIONS])
        self.subdiv_choice.SetSelection(0)  # Quarter notes
        set_accessible_name(self.subdiv_choice, "Subdivision")
        self.subdiv_choice.Bind(wx.EVT_CHOICE, self._on_structure)
        grid.Add(self.subdiv_choice, 0, wx.EXPAND)

        root.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

        self.accent_cb = wx.CheckBox(self, label="Accent the first beat of each measure")
        self.accent_cb.SetValue(True)
        root.Add(self.accent_cb, 0, wx.ALL, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.start_button = wx.Button(self, label="&Start")
        self.start_button.Bind(wx.EVT_BUTTON, self._on_start_stop)
        buttons.Add(self.start_button, 0, wx.RIGHT, 8)
        self.tap_button = wx.Button(self, label="&Tap Tempo")
        self.tap_button.Bind(wx.EVT_BUTTON, self._on_tap)
        buttons.Add(self.tap_button, 0)
        root.Add(buttons, 0, wx.ALL, 8)

        self.SetSizer(root)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        if not self.player.available:
            self._announce("Audio playback isn't available on this system.")

    # -- current settings -----------------------------------------------------

    @property
    def bpm(self) -> int:
        return self.tempo_slider.GetValue()

    @property
    def beats_per_measure(self) -> int:
        return self.beats_choice.GetSelection() + 1

    @property
    def subdivision(self) -> int:
        return SUBDIVISIONS[self.subdiv_choice.GetSelection()][1]

    def _interval_ms(self) -> int:
        return max(20, int(round(beat_interval(self.bpm, self.subdivision) * 1000)))

    def is_running(self) -> bool:
        return self._timer.IsRunning()

    # -- events ---------------------------------------------------------------

    def _on_tempo(self, event: wx.CommandEvent) -> None:
        self.tempo_label.SetLabel(f"Tempo: {self.bpm} BPM")
        if self.is_running():
            self._timer.Start(self._interval_ms())  # keep the measure, just change speed

    def _on_structure(self, event: wx.CommandEvent) -> None:
        # Changing the time signature or subdivision realigns to a fresh downbeat.
        if self.is_running():
            self._start()

    def _on_tap(self, event: wx.CommandEvent) -> None:
        bpm = self._tap.tap(time.monotonic())
        if bpm is None:
            self._announce("Tap again to set the tempo.")
            return
        self.tempo_slider.SetValue(int(round(bpm)))
        self._on_tempo(event)
        self._announce(f"Tempo: {self.bpm} BPM")

    def _on_start_stop(self, event: wx.CommandEvent) -> None:
        if self.is_running():
            self.stop()
        else:
            self._start()

    def _on_timer(self, event: wx.TimerEvent) -> None:
        self._emit()

    # -- transport ------------------------------------------------------------

    def _emit(self) -> None:
        kind = click_kind(self._tick, self.beats_per_measure, self.subdivision)
        if kind == "accent" and not self.accent_cb.GetValue():
            kind = "beat"
        self.player.play(kind)
        self._tick += 1

    def _start(self) -> None:
        if not self.player.available:
            self._announce("Audio playback isn't available on this system.")
            return
        self._tick = 0
        self._emit()                      # sound the downbeat immediately
        self._timer.Start(self._interval_ms())
        self.start_button.SetLabel("&Stop")
        beats, unit = self.beats_per_measure, BEAT_UNITS[self.unit_choice.GetSelection()]
        self._announce(f"Metronome started: {self.bpm} BPM, {beats}/{unit}.")

    def stop(self) -> None:
        if self._timer.IsRunning():
            self._timer.Stop()
        self.player.stop()
        self.start_button.SetLabel("&Start")
        self._announce("Metronome stopped.")

    def dispose(self) -> None:
        # Teardown-safe: stop the timer and free audio, but touch no UI (the status
        # bar may already be gone during window destruction).
        if self._timer.IsRunning():
            self._timer.Stop()
        self.player.dispose()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetWindow() is self:
            self.dispose()
        event.Skip()

    def _announce(self, message: str) -> None:
        if self._status is not None:
            self._status(message)
