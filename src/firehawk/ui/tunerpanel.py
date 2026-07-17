"""The by-ear tuner page.

Pick an instrument and a tuning, then press a string to hear a sustained reference
tone and tune to it by ear.  Pressing the same string again stops it.  Every control
is a labelled native widget so it reads and operates with a screen reader.
"""

from __future__ import annotations

from typing import Callable

import wx

from ..tuner import INSTRUMENTS, INSTRUMENTS_BY_NAME, TonePlayer, note_frequency
from .accessibility import set_accessible_name


class TunerPanel(wx.Panel):
    def __init__(self, parent: wx.Window, status: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._status = status
        self.player = TonePlayer()
        self._buttons: list[wx.Button] = []
        self._notes: list[str] = []
        self._playing_index: int | None = None

        root = wx.BoxSizer(wx.VERTICAL)

        hint = wx.StaticText(
            self, label="Pick an instrument and tuning, then press a string to hear its "
                        "reference tone. Press it again to stop.")
        root.Add(hint, 0, wx.ALL, 8)

        top = wx.FlexGridSizer(cols=2, vgap=6, hgap=10)
        top.Add(wx.StaticText(self, label="Instrument:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.instrument_choice = wx.Choice(self, choices=[i.name for i in INSTRUMENTS])
        self.instrument_choice.SetSelection(0)
        set_accessible_name(self.instrument_choice, "Instrument")
        self.instrument_choice.Bind(wx.EVT_CHOICE, self._on_instrument)
        top.Add(self.instrument_choice, 0, wx.EXPAND)

        top.Add(wx.StaticText(self, label="Tuning:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.tuning_choice = wx.Choice(self)
        set_accessible_name(self.tuning_choice, "Tuning")
        self.tuning_choice.Bind(wx.EVT_CHOICE, self._on_tuning)
        top.Add(self.tuning_choice, 0, wx.EXPAND)
        root.Add(top, 0, wx.ALL, 8)

        self.strings_label = wx.StaticText(self, label="Strings:")
        root.Add(self.strings_label, 0, wx.LEFT | wx.TOP, 8)
        self.string_panel = wx.Panel(self)
        self.string_sizer = wx.BoxSizer(wx.VERTICAL)
        self.string_panel.SetSizer(self.string_sizer)
        root.Add(self.string_panel, 1, wx.EXPAND | wx.ALL, 8)

        self.stop_button = wx.Button(self, label="&Stop Tone")
        self.stop_button.Bind(wx.EVT_BUTTON, lambda e: self.stop())
        root.Add(self.stop_button, 0, wx.ALL, 8)

        self.SetSizer(root)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._load_tunings()

    # -- population -----------------------------------------------------------

    def _instrument(self):
        return INSTRUMENTS_BY_NAME[self.instrument_choice.GetStringSelection()]

    def _load_tunings(self) -> None:
        self.tuning_choice.Set(list(self._instrument().tunings.keys()))
        self.tuning_choice.SetSelection(0)
        self._load_strings()

    def _load_strings(self) -> None:
        self.stop()
        self.string_sizer.Clear(delete_windows=True)
        self._buttons = []
        instrument = self._instrument()
        tuning = self.tuning_choice.GetStringSelection()
        self._notes = instrument.tunings[tuning]
        count = len(self._notes)
        for index, note in enumerate(self._notes):
            string_no = count - index  # lowest note = highest string number
            hz = note_frequency(note)
            label = f"String {string_no}:  {note}  ({hz:.1f} Hz)"
            btn = wx.Button(self.string_panel, label=label)
            btn.Bind(wx.EVT_BUTTON, lambda e, i=index: self._toggle(i))
            self.string_sizer.Add(btn, 0, wx.EXPAND | wx.BOTTOM, 4)
            self._buttons.append(btn)
        self.string_panel.Layout()
        if not self.player.available:
            self._announce("Audio playback isn't available on this system.")

    # -- events ---------------------------------------------------------------

    def _on_instrument(self, event: wx.CommandEvent) -> None:
        self._load_tunings()

    def _on_tuning(self, event: wx.CommandEvent) -> None:
        self._load_strings()

    def _toggle(self, index: int) -> None:
        if self._playing_index == index:
            self.stop()
            return
        note = self._notes[index]
        self.player.play_note(note)
        self._playing_index = index
        self._announce(f"Playing {note}")

    def stop(self) -> None:
        self.player.stop()
        if self._playing_index is not None:
            self._playing_index = None
            self._announce("Stopped.")

    def dispose(self) -> None:
        """Stop any tone and remove the tuner's temp WAV file."""
        self.player.dispose()

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetWindow() is self:
            self.dispose()
        event.Skip()

    def _announce(self, message: str) -> None:
        if self._status is not None:
            self._status(message)
