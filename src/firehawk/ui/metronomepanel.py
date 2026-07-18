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
    click_kind_grouped,
    group_start_beats,
    parse_grouping,
)
from . import speech
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

        self._group_starts = {0}

        root = wx.BoxSizer(wx.VERTICAL)
        hint = wx.StaticText(
            self, label="Set the tempo and time signature, then Start. Odd meters work too "
                        "(5/8, 7/8, ...); use Accent grouping to place the accents (e.g. 2+2+3 "
                        "for a 7). The metronome keeps playing while you work on other tabs; "
                        "press Stop or close the app to end it.")
        root.Add(hint, 0, wx.ALL, 8)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)

        # Tempo (BPM)
        self.tempo_label = wx.StaticText(self, label="Tempo: 120 BPM")
        grid.Add(self.tempo_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.tempo_slider = wx.Slider(
            self, value=120, minValue=TEMPO_MIN, maxValue=TEMPO_MAX,
            style=wx.SL_HORIZONTAL)
        # A screen reader would otherwise read a slider as a percent of its range;
        # value_fn makes it announce the real BPM instead.
        set_accessible_name(self.tempo_slider, "Tempo",
                            value_fn=lambda: f"{self.tempo_slider.GetValue()} BPM")
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

        # Beat unit (bottom of the time signature) — hidden until Non-standard meter is on
        self._unit_label = wx.StaticText(self, label="Beat unit (note value):")
        grid.Add(self._unit_label, 0, wx.ALIGN_CENTER_VERTICAL)
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

        # Accent grouping for odd meters — hidden until Non-standard meter is on
        self._grouping_label = wx.StaticText(self, label="Accent grouping (e.g. 2+2+3):")
        grid.Add(self._grouping_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.grouping_text = wx.TextCtrl(self)
        set_accessible_name(self.grouping_text, "Accent grouping, for example 2 plus 2 plus 3")
        self.grouping_text.Bind(wx.EVT_TEXT, self._on_grouping)
        grid.Add(self.grouping_text, 0, wx.EXPAND)

        root.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

        # Standard vs. non-standard timing: the odd-meter controls stay out of the way
        # until asked for, so the everyday tab path is short.
        self.odd_cb = wx.CheckBox(
            self, label="Non-standard meter (show beat unit and accent grouping)")
        self.odd_cb.Bind(wx.EVT_CHECKBOX, self._on_odd_toggle)
        root.Add(self.odd_cb, 0, wx.LEFT | wx.RIGHT, 8)

        self.accent_cb = wx.CheckBox(self, label="Accent the downbeat and grouped beats")
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
        self._show_odd_controls(False)
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
        self._update_groups()
        if self.is_running():
            self._start()

    def _on_grouping(self, event: wx.CommandEvent) -> None:
        # Accent grouping only changes which beats accent, so it applies live (no restart).
        self._update_groups()

    def _show_odd_controls(self, shown: bool) -> None:
        for w in (self._unit_label, self.unit_choice, self._grouping_label, self.grouping_text):
            w.Show(shown)
        self.Layout()

    def _on_odd_toggle(self, event: wx.CommandEvent) -> None:
        shown = self.odd_cb.GetValue()
        if not shown:
            # Back to standard timing: quarter-note unit, downbeat-only accents.
            self.unit_choice.SetSelection(BEAT_UNITS.index(4))
            self.grouping_text.ChangeValue("")  # no EVT_TEXT; we update groups ourselves
            self._update_groups()
        self._show_odd_controls(shown)
        self._announce("Non-standard meter controls shown." if shown
                       else "Standard timing: beat unit reset to 4, accents on the downbeat.")

    def _update_groups(self) -> None:
        text = self.grouping_text.GetValue().strip()
        grouping = parse_grouping(text, self.beats_per_measure)
        self._group_starts = group_start_beats(self.beats_per_measure, grouping)
        if text and grouping is None:
            self._announce(
                f"Grouping must be numbers adding up to {self.beats_per_measure} (e.g. 2+2+3).")

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

    def toggle_transport(self) -> None:
        """Start or stop the metronome — the app-wide Play/Stop (F5) hook, callable from
        anywhere in the window. Start/stop speak their own state for audible feedback."""
        self._on_start_stop(None)

    def _on_timer(self, event: wx.TimerEvent) -> None:
        self._emit()

    # -- transport ------------------------------------------------------------

    def _emit(self) -> None:
        kind = click_kind_grouped(
            self._tick, self.beats_per_measure, self.subdivision, self._group_starts)
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
        # Speak it too — Start/Stop/Tap Tempo have no native feedback, and the status bar
        # is silent to a screen reader.
        speech.speak(message)
        if self._status is not None:
            self._status(message)
