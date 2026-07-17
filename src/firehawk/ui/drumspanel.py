"""The Drum Looper page — a customizable, screen-reader-first drum machine.

Pick a kit (the built-in synth kit, or your own drum library), pick a groove, set
the tempo, and press Start.  Edit any groove step by step: choose a part (kick,
snare, ...) and toggle its steps.  Odd/prog meters are supported (5/4, 7/8, ...) via
the time-signature controls.  Every control is a labelled native widget.

Like the metronome, the loop keeps playing when you switch tabs, so you can jam over
it while editing a tone; Stop or closing the app ends it.  The loop is pre-mixed so
different-length samples still land exactly on the beat (see practice/drums.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import wx

from .. import config
from ..practice import (
    DRUM_BEAT_UNITS,
    GENRE_PATTERNS,
    GRID_CHOICES,
    MAX_STEPS,
    NUMPY_AVAILABLE,
    ROLE_LABELS,
    DrumLoopPlayer,
    Pattern,
    load_kit_from_folder,
    render_loop,
    steps_per_bar,
    synth_kit,
)
from .accessibility import set_accessible_name

TEMPO_MIN = 30
TEMPO_MAX = 300
SYNTH_LABEL = "Synth (built-in)"
BROWSE_LABEL = "Browse for a kit folder..."


class DrumsPanel(wx.Panel):
    def __init__(self, parent: wx.Window, settings=None, status: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._settings = settings
        self._status = status
        self.player = DrumLoopPlayer()
        self._kit = synth_kit() if NUMPY_AVAILABLE else None
        self._pattern = GENRE_PATTERNS[0].copy()
        self._muted: set[str] = set()
        self._playing = False
        self._step_boxes: list[wx.CheckBox] = []

        root = wx.BoxSizer(wx.VERTICAL)
        hint = wx.StaticText(
            self, label="Pick a kit and a groove, then Start. To customize, choose a part and "
                        "toggle its steps. Odd meters work too — set Beats per bar / Beat unit "
                        "(e.g. 7 and 8 for 7/8). The loop keeps playing while you work on other "
                        "tabs; Stop or close the app to end it.")
        root.Add(hint, 0, wx.ALL, 8)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Kit:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.kit_choice = wx.Choice(self, choices=self._kit_choices())
        self.kit_choice.SetSelection(0)
        set_accessible_name(self.kit_choice, "Drum kit")
        self.kit_choice.Bind(wx.EVT_CHOICE, self._on_kit)
        grid.Add(self.kit_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Groove:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.groove_choice = wx.Choice(self, choices=[p.name for p in GENRE_PATTERNS])
        self.groove_choice.SetSelection(0)
        set_accessible_name(self.groove_choice, "Groove")
        self.groove_choice.Bind(wx.EVT_CHOICE, self._on_groove)
        grid.Add(self.groove_choice, 0, wx.EXPAND)

        # Time signature / grid — enables odd & prog meters and multi-bar loops.
        grid.Add(wx.StaticText(self, label="Beats per bar:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.beats_choice = wx.Choice(self, choices=[str(n) for n in range(1, 17)])
        self.beats_choice.SetSelection(3)  # 4
        set_accessible_name(self.beats_choice, "Beats per bar")
        self.beats_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.beats_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Beat unit (note value):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.unit_choice = wx.Choice(self, choices=[str(n) for n in DRUM_BEAT_UNITS])
        self.unit_choice.SetSelection(DRUM_BEAT_UNITS.index(4))
        set_accessible_name(self.unit_choice, "Beat unit, note value")
        self.unit_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.unit_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Grid (steps per beat):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.grid_choice = wx.Choice(self, choices=[label for label, _ in GRID_CHOICES])
        self.grid_choice.SetSelection(3)  # Sixteenth
        set_accessible_name(self.grid_choice, "Grid resolution")
        self.grid_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.grid_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Bars in loop:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.bars_choice = wx.Choice(self, choices=["1", "2", "3", "4"])
        self.bars_choice.SetSelection(0)
        set_accessible_name(self.bars_choice, "Bars in the loop")
        self.bars_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.bars_choice, 0, wx.EXPAND)

        self.tempo_label = wx.StaticText(self, label="Tempo: 90 BPM")
        grid.Add(self.tempo_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.tempo_slider = wx.Slider(self, value=90, minValue=TEMPO_MIN, maxValue=TEMPO_MAX)
        # Announce real BPM, not the slider's percent-of-range (see metronomepanel).
        set_accessible_name(self.tempo_slider, "Tempo",
                            value_fn=lambda: f"{self.tempo_slider.GetValue()} BPM")
        self.tempo_slider.Bind(wx.EVT_SLIDER, self._on_tempo)
        grid.Add(self.tempo_slider, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Edit part:"), 0, wx.ALIGN_CENTER_VERTICAL)
        part_row = wx.BoxSizer(wx.HORIZONTAL)
        self.part_choice = wx.Choice(self)
        set_accessible_name(self.part_choice, "Part to edit")
        self.part_choice.Bind(wx.EVT_CHOICE, self._on_part)
        part_row.Add(self.part_choice, 1, wx.EXPAND | wx.RIGHT, 8)
        self.mute_cb = wx.CheckBox(self, label="Mute this part")
        self.mute_cb.Bind(wx.EVT_CHECKBOX, self._on_mute)
        part_row.Add(self.mute_cb, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(part_row, 0, wx.EXPAND)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

        self.steps_label = wx.StaticText(self, label="Steps for this part:")
        root.Add(self.steps_label, 0, wx.LEFT | wx.TOP, 8)
        self.steps_panel = wx.Panel(self)
        self.steps_sizer = wx.WrapSizer(wx.HORIZONTAL)
        self.steps_panel.SetSizer(self.steps_sizer)
        root.Add(self.steps_panel, 0, wx.EXPAND | wx.ALL, 8)

        self.start_button = wx.Button(self, label="&Start")
        self.start_button.Bind(wx.EVT_BUTTON, self._on_start_stop)
        root.Add(self.start_button, 0, wx.ALL, 8)

        self.SetSizer(root)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

        self._sync_meter_controls(self._pattern)
        self._rebuild_parts()
        if not NUMPY_AVAILABLE:
            self.start_button.Disable()
            self._announce("The drum looper needs numpy installed (pip install numpy).")
        elif not self.player.available:
            self.start_button.Disable()
            self._announce("Audio playback isn't available on this system.")

    # -- kit discovery --------------------------------------------------------

    def _kits_dir(self) -> Path:
        if self._settings is not None:
            saved = self._settings.get("drum_kits_dir")
            if saved and Path(saved).is_dir():
                return Path(saved)
        for cand in (Path.cwd() / "Samples", config._config_dir() / "Samples"):
            if cand.is_dir():
                return cand
        return Path.cwd() / "Samples"

    def _kit_folder_names(self) -> list[str]:
        d = self._kits_dir()
        if not d.is_dir():
            return []
        return [sub.name for sub in sorted(d.iterdir()) if sub.is_dir()]

    def _kit_choices(self) -> list[str]:
        return [SYNTH_LABEL, *self._kit_folder_names(), BROWSE_LABEL]

    # -- current settings -----------------------------------------------------

    @property
    def bpm(self) -> int:
        return self.tempo_slider.GetValue()

    @property
    def beats_per_bar(self) -> int:
        return self.beats_choice.GetSelection() + 1

    @property
    def beat_unit(self) -> int:
        return DRUM_BEAT_UNITS[self.unit_choice.GetSelection()]

    @property
    def grid_steps(self) -> int:
        return GRID_CHOICES[self.grid_choice.GetSelection()][1]

    @property
    def bars(self) -> int:
        return self.bars_choice.GetSelection() + 1

    def _sync_meter_controls(self, pattern: Pattern) -> None:
        """Set the time-signature controls to match a pattern (e.g. after loading a groove)."""
        self.beats_choice.SetSelection(max(0, min(15, pattern.beats_per_bar - 1)))
        if pattern.beat_unit in DRUM_BEAT_UNITS:
            self.unit_choice.SetSelection(DRUM_BEAT_UNITS.index(pattern.beat_unit))
        grids = [g for _, g in GRID_CHOICES]
        if pattern.steps_per_beat in grids:
            self.grid_choice.SetSelection(grids.index(pattern.steps_per_beat))
        self.bars_choice.SetSelection(max(0, min(3, pattern.bars - 1)))

    def _current_part(self) -> str | None:
        sel = self.part_choice.GetSelection()
        return self._part_roles[sel] if 0 <= sel < len(self._part_roles) else None

    def _step_label(self, i: int) -> str:
        """Beat-aware label for a step, so odd meters stay navigable (e.g. 'Bar 2 Beat 3.2')."""
        p = self._pattern
        per_bar = max(1, steps_per_bar(p.beats_per_bar, p.beat_unit, p.steps_per_beat))
        steps_per_metrical_beat = max(1, round(p.steps_per_beat * 4.0 / max(1, p.beat_unit)))
        within = i % per_bar
        beat = within // steps_per_metrical_beat + 1
        sub = within % steps_per_metrical_beat
        label = f"Beat {beat}" if sub == 0 else f"Beat {beat}.{sub + 1}"
        if p.bars > 1:
            label = f"Bar {i // per_bar + 1} {label}"
        return label

    # -- part / step editor ---------------------------------------------------

    def _rebuild_parts(self) -> None:
        from ..practice.drums import ROLES
        kit_roles = self._kit.roles() if self._kit else []
        self._part_roles = [r for r in ROLES if r in kit_roles or r in self._pattern.hits]
        self.part_choice.Set([ROLE_LABELS.get(r, r) for r in self._part_roles])
        if self._part_roles:
            self.part_choice.SetSelection(0)
        self._rebuild_steps()

    def _rebuild_steps(self) -> None:
        self.steps_sizer.Clear(delete_windows=True)
        self._step_boxes = []
        role = self._current_part()
        on = set(self._pattern.hits.get(role, [])) if role else set()
        for i in range(self._pattern.steps):
            cb = wx.CheckBox(self.steps_panel, label=self._step_label(i))
            cb.SetValue(i in on)
            cb.Bind(wx.EVT_CHECKBOX, lambda e, idx=i: self._on_step(idx, e))
            self.steps_sizer.Add(cb, 0, wx.RIGHT | wx.BOTTOM, 6)
            self._step_boxes.append(cb)
        role_label = ROLE_LABELS.get(role, role) if role else "part"
        self.steps_label.SetLabel(f"Steps for {role_label} ({self._pattern.meter_label()}):")
        self.mute_cb.SetValue(role in self._muted)
        self.steps_panel.Layout()
        self.Layout()

    # -- events ---------------------------------------------------------------

    def _on_kit(self, event: wx.CommandEvent) -> None:
        sel = self.kit_choice.GetStringSelection()
        if sel == SYNTH_LABEL:
            self._set_kit(synth_kit())
            self._announce("Synth kit selected.")
        elif sel == BROWSE_LABEL:
            self._browse_kit()
        else:
            self._announce(f"Loading kit: {sel}...")
            try:
                self._set_kit(load_kit_from_folder(self._kits_dir() / sel))
                self._announce(f"Kit '{sel}' loaded: {len(self._kit.roles())} parts.")
            except Exception as exc:  # noqa: BLE001
                wx.MessageBox(f"Could not load kit:\n{exc}", "Drum kit", wx.ICON_ERROR)

    def _browse_kit(self) -> None:
        with wx.DirDialog(self, "Choose a drum-kit folder (with KICK, SNARE, ... subfolders)",
                          str(self._kits_dir())) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                self.kit_choice.SetSelection(0)  # fall back to Synth in the list
                return
            path = Path(dlg.GetPath())
        try:
            kit = load_kit_from_folder(path)
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not load kit:\n{exc}", "Drum kit", wx.ICON_ERROR)
            return
        if not kit.roles():
            wx.MessageBox(
                "No recognised drum parts found in that folder.\n\n"
                "Expected subfolders named KICK, SNARE, HIHAT, OPENHAT, CLAP, PERC, 808, ...\n"
                "each containing .wav files. See docs/drum-kits.md.",
                "Drum kit", wx.ICON_INFORMATION)
            return
        if self._settings is not None:  # remember where kits live
            self._settings.set("drum_kits_dir", str(path.parent))
        self.kit_choice.Set(self._kit_choices())
        idx = self.kit_choice.FindString(path.name)
        self.kit_choice.SetSelection(idx if idx != wx.NOT_FOUND else 0)
        self._set_kit(kit)
        self._announce(f"Kit '{path.name}' loaded: {len(kit.roles())} parts.")

    def _set_kit(self, kit) -> None:
        self._kit = kit
        self._rebuild_parts()
        self._apply()

    def _on_groove(self, event: wx.CommandEvent) -> None:
        self._pattern = GENRE_PATTERNS[self.groove_choice.GetSelection()].copy()
        self._sync_meter_controls(self._pattern)  # match the groove's meter
        self._rebuild_parts()
        self._apply()
        self._announce(f"Groove: {self._pattern.name} ({self._pattern.meter_label()}).")

    def _on_meter(self, event: wx.CommandEvent) -> None:
        per_bar = steps_per_bar(self.beats_per_bar, self.beat_unit, self.grid_steps)
        bars = self.bars
        while bars > 1 and per_bar * bars > MAX_STEPS:  # keep the grid navigable
            bars -= 1
        if bars != self.bars:
            self.bars_choice.SetSelection(bars - 1)
            self._announce(f"Limited to {bars} bar(s) to keep the step grid manageable.")
        total = per_bar * bars
        # Keep any programmed hits that still fit the new step count.
        new_hits = {r: [s for s in steps if s < total] for r, steps in self._pattern.hits.items()}
        self._pattern = Pattern(
            f"{self.beats_per_bar}/{self.beat_unit}", total, self.grid_steps, new_hits,
            self.beats_per_bar, self.beat_unit, bars)
        self._rebuild_parts()
        self._apply()
        self._announce(f"Meter: {self._pattern.meter_label()}, {total} steps.")

    def _on_tempo(self, event: wx.CommandEvent) -> None:
        self.tempo_label.SetLabel(f"Tempo: {self.bpm} BPM")
        self._apply()

    def _on_part(self, event: wx.CommandEvent) -> None:
        self._rebuild_steps()

    def _on_mute(self, event: wx.CommandEvent) -> None:
        role = self._current_part()
        if role is None:
            return
        if self.mute_cb.GetValue():
            self._muted.add(role)
        else:
            self._muted.discard(role)
        self._apply()

    def _on_step(self, index: int, event: wx.CommandEvent) -> None:
        role = self._current_part()
        if role is None:
            return
        steps = set(self._pattern.hits.get(role, []))
        if event.IsChecked():
            steps.add(index)
        else:
            steps.discard(index)
        self._pattern.hits[role] = sorted(steps)
        self._apply()

    def _on_start_stop(self, event: wx.CommandEvent) -> None:
        if self._playing:
            self.stop()
        else:
            self._start()

    # -- transport ------------------------------------------------------------

    def _render_and_play(self) -> None:
        from ..practice import Pattern
        effective = Pattern(
            self._pattern.name, self._pattern.steps, self._pattern.steps_per_beat,
            {r: s for r, s in self._pattern.hits.items() if r not in self._muted})
        self.player.play(render_loop(effective, self._kit, self.bpm))

    def _apply(self) -> None:
        """Re-render and swap the loop if we're currently playing."""
        if self._playing and self._kit is not None:
            self._render_and_play()

    def _start(self) -> None:
        if not NUMPY_AVAILABLE or not self.player.available or self._kit is None:
            self._announce("The drum looper isn't available on this system.")
            return
        self._playing = True
        self._render_and_play()
        self.start_button.SetLabel("&Stop")
        self._announce(f"Drum loop started: {self._pattern.name}, {self.bpm} BPM.")

    def stop(self) -> None:
        self.player.stop()
        self._playing = False
        self.start_button.SetLabel("&Start")
        self._announce("Drum loop stopped.")

    def dispose(self) -> None:
        # Teardown-safe: stop audio and free the temp file, touch no UI.
        self.player.dispose()
        self._playing = False

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetWindow() is self:
            self.dispose()
        event.Skip()

    def _announce(self, message: str) -> None:
        if self._status is not None:
            self._status(message)
