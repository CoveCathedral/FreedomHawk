"""The Drum Looper page — a customizable, screen-reader-first drum machine.

The main tab stays lean: pick a kit and one of 200 grooves, set the tempo, Start.
Deeper editing lives in the **Pattern Editor** dialog (Edit Pattern...), where a Step
dropdown selects any step by its beat name and checkboxes set which parts hit there —
no tabbing through dozens of step controls.  Odd/prog meters are set in the editor.

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
    GRID_CHOICES,
    MAX_STEPS,
    NUMPY_AVAILABLE,
    PATTERN_LIBRARY,
    ROLE_LABELS,
    ROLES,
    DrumLoopPlayer,
    Pattern,
    default_sample_for,
    expand_with_fill,
    list_role_files,
    load_kit_from_folder,
    render_loop,
    retime_pattern,
    steps_per_bar,
    synth_kit,
    wav_duration,
)
from ..practice.drums import load_sample
from . import theme
from .accessibility import set_accessible_name

try:
    import winsound
except ImportError:  # non-Windows
    winsound = None

TEMPO_MIN = 30
TEMPO_MAX = 300
SYNTH_LABEL = "Synth (built-in)"


def step_label(pattern: Pattern, i: int) -> str:
    """Beat-aware name for a step, so odd meters stay navigable (e.g. 'Bar 2 Beat 3.2')."""
    per_bar = max(1, steps_per_bar(pattern.beats_per_bar, pattern.beat_unit,
                                   pattern.steps_per_beat))
    per_beat = max(1, round(pattern.steps_per_beat * 4.0 / max(1, pattern.beat_unit)))
    within = i % per_bar
    beat = within // per_beat + 1
    sub = within % per_beat
    label = f"Beat {beat}" if sub == 0 else f"Beat {beat}.{sub + 1}"
    if pattern.bars > 1:
        label = f"Bar {i // per_bar + 1}, {label}"
    return label


class PatternEditorDialog(wx.Dialog):
    """Accessible pattern editor: Step dropdown -> per-part checkboxes for that step.

    Works on its own copy of the pattern; Save returns it, Cancel (or Escape)
    discards.  Play auditions the edited loop while you work.
    """

    def __init__(self, parent: wx.Window, pattern: Pattern, kit, player: DrumLoopPlayer,
                 bpm: int, dark: bool = True):
        super().__init__(parent, title="Pattern Editor",
                         size=(560, 640), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.pattern = pattern
        self._kit = kit
        self._player = player
        self._bpm = bpm
        self._auditioning = False

        kit_roles = kit.roles() if kit else []
        self._roles = [r for r in ROLES if r in kit_roles or r in pattern.hits]

        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=(
            "Pick a step with the Step dropdown (arrow keys move through it), then check "
            "which parts hit on that step. Play auditions the loop while you edit. "
            "Save keeps your changes; Cancel or Escape discards them."))
        intro.Wrap(520)
        root.Add(intro, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Beats per bar:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.beats_choice = wx.Choice(self, choices=[str(n) for n in range(1, 17)])
        set_accessible_name(self.beats_choice, "Beats per bar")
        self.beats_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.beats_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Beat unit (note value):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.unit_choice = wx.Choice(self, choices=[str(n) for n in DRUM_BEAT_UNITS])
        set_accessible_name(self.unit_choice, "Beat unit, note value")
        self.unit_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.unit_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Grid (steps per beat):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.grid_choice = wx.Choice(self, choices=[label for label, _ in GRID_CHOICES])
        set_accessible_name(self.grid_choice, "Grid resolution")
        self.grid_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.grid_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Bars in loop:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.bars_choice = wx.Choice(self, choices=["1", "2", "3", "4"])
        set_accessible_name(self.bars_choice, "Bars in the loop")
        self.bars_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        grid.Add(self.bars_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Step:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.step_choice = wx.Choice(self)
        set_accessible_name(self.step_choice, "Step")
        self.step_choice.Bind(wx.EVT_CHOICE, lambda e: self._refresh_part_boxes())
        grid.Add(self.step_choice, 0, wx.EXPAND)

        root.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        root.Add(wx.StaticText(self, label="Parts on this step:"), 0, wx.LEFT | wx.TOP, 10)
        self._part_boxes: dict[str, wx.CheckBox] = {}
        parts = wx.WrapSizer(wx.HORIZONTAL)
        for role in self._roles:
            cb = wx.CheckBox(self, label=ROLE_LABELS.get(role, role))
            cb.Bind(wx.EVT_CHECKBOX, lambda e, r=role: self._on_part_toggle(r, e.IsChecked()))
            parts.Add(cb, 0, wx.RIGHT | wx.BOTTOM, 8)
            self._part_boxes[role] = cb
        root.Add(parts, 1, wx.EXPAND | wx.ALL, 10)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(self, label="&Play")
        self.play_btn.Bind(wx.EVT_BUTTON, self._on_play)
        btns.Add(self.play_btn, 0, wx.RIGHT, 8)
        save_btn = wx.Button(self, wx.ID_OK, "&Save")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        btns.Add(save_btn, 0, wx.RIGHT, 8)
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        btns.Add(cancel_btn, 0)
        root.Add(btns, 0, wx.ALL, 10)

        self.SetSizer(root)
        save_btn.SetDefault()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        theme.apply(self, dark)

        self._sync_meter_controls()
        self._rebuild_step_choice()
        self._refresh_part_boxes()
        # Land focus on the Step dropdown so a screen reader announces the dialog
        # and its primary control the moment it opens.
        wx.CallAfter(self.step_choice.SetFocus)

    # -- state <-> controls ---------------------------------------------------

    def _sync_meter_controls(self) -> None:
        p = self.pattern
        self.beats_choice.SetSelection(max(0, min(15, p.beats_per_bar - 1)))
        if p.beat_unit in DRUM_BEAT_UNITS:
            self.unit_choice.SetSelection(DRUM_BEAT_UNITS.index(p.beat_unit))
        grids = [g for _, g in GRID_CHOICES]
        if p.steps_per_beat in grids:
            self.grid_choice.SetSelection(grids.index(p.steps_per_beat))
        self.bars_choice.SetSelection(max(0, min(3, p.bars - 1)))

    def _rebuild_step_choice(self) -> None:
        keep = max(0, self.step_choice.GetSelection())
        self.step_choice.Set([step_label(self.pattern, i) for i in range(self.pattern.steps)])
        self.step_choice.SetSelection(min(keep, self.pattern.steps - 1))

    def _current_step(self) -> int:
        return max(0, self.step_choice.GetSelection())

    def _refresh_part_boxes(self) -> None:
        step = self._current_step()
        for role, cb in self._part_boxes.items():
            cb.SetValue(step in self.pattern.hits.get(role, []))

    # -- events ---------------------------------------------------------------

    def _on_meter(self, event: wx.CommandEvent) -> None:
        beats = self.beats_choice.GetSelection() + 1
        unit = DRUM_BEAT_UNITS[self.unit_choice.GetSelection()]
        grid = GRID_CHOICES[self.grid_choice.GetSelection()][1]
        bars = self.bars_choice.GetSelection() + 1
        per_bar = steps_per_bar(beats, unit, grid)
        while bars > 1 and per_bar * bars > MAX_STEPS:  # keep the step list navigable
            bars -= 1
        self.bars_choice.SetSelection(bars - 1)
        # Growing the bar count repeats the existing bars (no silent gaps); shrinking
        # keeps the first bars. See retime_pattern.
        self.pattern = retime_pattern(self.pattern, beats, unit, grid, bars)
        self._rebuild_step_choice()
        self._refresh_part_boxes()
        self._reaudition()

    def _on_part_toggle(self, role: str, checked: bool) -> None:
        step = self._current_step()
        steps = set(self.pattern.hits.get(role, []))
        if checked:
            steps.add(step)
        else:
            steps.discard(step)
        if steps:
            self.pattern.hits[role] = sorted(steps)
        else:
            self.pattern.hits.pop(role, None)
        self._reaudition()

    def _on_play(self, event: wx.CommandEvent) -> None:
        if self._auditioning:
            self._stop_audition()
            return
        if self._kit is None or not self._player.available:
            return
        self._auditioning = True
        self._player.play(render_loop(self.pattern, self._kit, self._bpm))
        self.play_btn.SetLabel("&Pause")

    def _reaudition(self) -> None:
        if self._auditioning and self._kit is not None:
            self._player.play(render_loop(self.pattern, self._kit, self._bpm))

    def _stop_audition(self) -> None:
        if self._auditioning:
            self._player.stop()
            self._auditioning = False
            self.play_btn.SetLabel("&Play")

    def _on_save(self, event: wx.CommandEvent) -> None:
        self._stop_audition()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event: wx.CommandEvent) -> None:
        self._stop_audition()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event) -> None:
        self._stop_audition()
        self.EndModal(wx.ID_CANCEL)


class KitSoundsDialog(wx.Dialog):
    """Choose which sample each drum part uses, by ear.

    Part dropdown -> Sample dropdown (that part's folder).  Arrowing through the
    samples previews each one, so you audition with the arrow keys alone; Save
    remembers the choices for this kit.
    """

    def __init__(self, parent: wx.Window, kit_dir: Path, choices: dict[str, str],
                 dark: bool = True):
        super().__init__(parent, title="Kit Sounds", size=(560, 360),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._files = list_role_files(kit_dir)
        self._roles = [r for r in ROLES if r in self._files]
        self.choices = dict(choices)  # role -> filename; edited in place, read on Save
        self._preview_data: bytes | None = None  # keep alive while playing

        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=(
            "Pick a part, then arrow through its samples — each one plays as you land on "
            "it (lengths are shown; names are the kit maker's own). Save keeps your "
            "choices for this kit; Cancel or Escape leaves it unchanged."))
        intro.Wrap(520)
        root.Add(intro, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="Part:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.part_choice = wx.Choice(self, choices=[ROLE_LABELS.get(r, r) for r in self._roles])
        set_accessible_name(self.part_choice, "Part")
        self.part_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_samples())
        grid.Add(self.part_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Sample:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.sample_choice = wx.Choice(self)
        set_accessible_name(self.sample_choice, "Sample")
        self.sample_choice.Bind(wx.EVT_CHOICE, self._on_sample)
        grid.Add(self.sample_choice, 0, wx.EXPAND)
        root.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        preview_btn = wx.Button(self, label="&Preview")
        preview_btn.Bind(wx.EVT_BUTTON, lambda e: self._preview())
        btns.Add(preview_btn, 0, wx.RIGHT, 8)
        save_btn = wx.Button(self, wx.ID_OK, "&Save")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        btns.Add(save_btn, 0, wx.RIGHT, 8)
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        btns.Add(cancel_btn, 0)
        root.Add(btns, 0, wx.ALL, 10)

        self.SetSizer(root)
        save_btn.SetDefault()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        theme.apply(self, dark)
        if self._roles:
            self.part_choice.SetSelection(0)
            self._load_samples()
        # Announce the dialog by focusing its primary control on open.
        wx.CallAfter(self.part_choice.SetFocus)

    # -- state ----------------------------------------------------------------

    def _current_role(self) -> str | None:
        sel = self.part_choice.GetSelection()
        return self._roles[sel] if 0 <= sel < len(self._roles) else None

    def _load_samples(self) -> None:
        role = self._current_role()
        files = self._files.get(role, [])
        labels = []
        for f in files:
            dur = wav_duration(f)
            labels.append(f"{f.stem}  ({dur:.2f}s)" if dur else f.stem)
        self.sample_choice.Set(labels)
        current = self.choices.get(role)
        default = default_sample_for(role, files)
        names = [f.name for f in files]
        if current in names:
            self.sample_choice.SetSelection(names.index(current))
        elif default is not None:
            self.sample_choice.SetSelection(names.index(default.name))

    def _on_sample(self, event: wx.CommandEvent) -> None:
        role = self._current_role()
        files = self._files.get(role, [])
        i = self.sample_choice.GetSelection()
        if role is None or not (0 <= i < len(files)):
            return
        self.choices[role] = files[i].name
        self._preview()

    def _preview(self) -> None:
        """Play the selected sample once (converted, so float WAVs preview fine)."""
        role = self._current_role()
        files = self._files.get(role, [])
        i = self.sample_choice.GetSelection()
        if winsound is None or not NUMPY_AVAILABLE or role is None or not (0 <= i < len(files)):
            return
        try:
            import io
            import wave as wave_mod
            import numpy as np
            x = load_sample(files[i])
            pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
            buf = io.BytesIO()
            w = wave_mod.open(buf, "wb")
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(pcm.tobytes())
            w.close()
            self._preview_data = buf.getvalue()  # must outlive the async playback
            winsound.PlaySound(self._preview_data, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:  # noqa: BLE001 - preview is best-effort
            pass

    def _stop_preview(self) -> None:
        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except Exception:  # noqa: BLE001
                pass

    def _on_save(self, event: wx.CommandEvent) -> None:
        self._stop_preview()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event: wx.CommandEvent) -> None:
        self._stop_preview()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event) -> None:
        self._stop_preview()
        self.EndModal(wx.ID_CANCEL)


class DrumsPanel(wx.Panel):
    def __init__(self, parent: wx.Window, settings=None, status: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._settings = settings
        self._status = status
        self.player = DrumLoopPlayer()
        self._kit = synth_kit() if NUMPY_AVAILABLE else None
        self._kit_dir: Path | None = None  # None while the synth kit is active
        self._pattern = PATTERN_LIBRARY[0].copy()
        self._muted: set[str] = set()
        self._playing = False

        root = wx.BoxSizer(wx.VERTICAL)
        hint = wx.StaticText(
            self, label="Pick a kit and a groove (200 built in, fills included), set the "
                        "tempo, then Start. Edit Pattern opens the step editor, including "
                        "odd meters. The loop keeps playing while you work on other tabs; "
                        "Stop or close the app to end it.")
        root.Add(hint, 0, wx.ALL, 8)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Kit:"), 0, wx.ALIGN_CENTER_VERTICAL)
        kit_row = wx.BoxSizer(wx.HORIZONTAL)
        self.kit_choice = wx.Choice(self, choices=self._kit_choices())
        self.kit_choice.SetSelection(0)
        set_accessible_name(self.kit_choice, "Drum kit")
        self.kit_choice.Bind(wx.EVT_CHOICE, self._on_kit)
        kit_row.Add(self.kit_choice, 1, wx.EXPAND | wx.RIGHT, 8)
        # A separate button (not a dropdown entry) so arrowing through kits never
        # springs a folder dialog on you.
        self.import_button = wx.Button(self, label="&Import Drum Kit...")
        self.import_button.Bind(wx.EVT_BUTTON, self._on_import_kit)
        kit_row.Add(self.import_button, 0)
        grid.Add(kit_row, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Groove:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.groove_choice = wx.Choice(self, choices=[p.name for p in PATTERN_LIBRARY])
        self.groove_choice.SetSelection(0)
        set_accessible_name(self.groove_choice, "Groove")
        self.groove_choice.Bind(wx.EVT_CHOICE, self._on_groove)
        grid.Add(self.groove_choice, 0, wx.EXPAND)

        # Stretch the groove for jamming: plain bars with the fill only every N bars.
        grid.Add(wx.StaticText(self, label="Fill every:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.fill_choice = wx.Choice(self, choices=[
            "Pattern length (as written)", "2 bars", "4 bars", "8 bars",
            "12 bars", "16 bars"])
        self.fill_choice.SetSelection(0)
        set_accessible_name(self.fill_choice, "Fill every")
        self.fill_choice.Bind(wx.EVT_CHOICE, self._on_fill_every)
        grid.Add(self.fill_choice, 0, wx.EXPAND)

        self.tempo_label = wx.StaticText(self, label="Tempo: 90 BPM")
        grid.Add(self.tempo_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.tempo_slider = wx.Slider(self, value=90, minValue=TEMPO_MIN, maxValue=TEMPO_MAX)
        # Announce real BPM, not the slider's percent-of-range (see metronomepanel).
        set_accessible_name(self.tempo_slider, "Tempo",
                            value_fn=lambda: f"{self.tempo_slider.GetValue()} BPM")
        self.tempo_slider.Bind(wx.EVT_SLIDER, self._on_tempo)
        grid.Add(self.tempo_slider, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Part:"), 0, wx.ALIGN_CENTER_VERTICAL)
        part_row = wx.BoxSizer(wx.HORIZONTAL)
        self.part_choice = wx.Choice(self)
        set_accessible_name(self.part_choice, "Part")
        self.part_choice.Bind(wx.EVT_CHOICE, self._on_part)
        part_row.Add(self.part_choice, 1, wx.EXPAND | wx.RIGHT, 8)
        self.mute_cb = wx.CheckBox(self, label="Mute this part")
        self.mute_cb.Bind(wx.EVT_CHECKBOX, self._on_mute)
        part_row.Add(self.mute_cb, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(part_row, 0, wx.EXPAND)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.edit_button = wx.Button(self, label="&Edit Pattern...")
        self.edit_button.Bind(wx.EVT_BUTTON, self._on_edit_pattern)
        buttons.Add(self.edit_button, 0, wx.RIGHT, 8)
        self.sounds_button = wx.Button(self, label="&Kit Sounds...")
        self.sounds_button.Bind(wx.EVT_BUTTON, self._on_kit_sounds)
        buttons.Add(self.sounds_button, 0, wx.RIGHT, 8)
        self.start_button = wx.Button(self, label="&Start")
        self.start_button.Bind(wx.EVT_BUTTON, self._on_start_stop)
        buttons.Add(self.start_button, 0)
        root.Add(buttons, 0, wx.ALL, 8)

        self.SetSizer(root)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

        self._rebuild_parts()
        if not NUMPY_AVAILABLE:
            self.start_button.Disable()
            self.edit_button.Disable()
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
        return [SYNTH_LABEL, *self._kit_folder_names()]

    # -- current settings -----------------------------------------------------

    @property
    def bpm(self) -> int:
        return self.tempo_slider.GetValue()

    def _current_part(self) -> str | None:
        sel = self.part_choice.GetSelection()
        return self._part_roles[sel] if 0 <= sel < len(self._part_roles) else None

    def _rebuild_parts(self) -> None:
        kit_roles = self._kit.roles() if self._kit else []
        self._part_roles = [r for r in ROLES if r in kit_roles or r in self._pattern.hits]
        self.part_choice.Set([ROLE_LABELS.get(r, r) for r in self._part_roles])
        if self._part_roles:
            self.part_choice.SetSelection(0)
        role = self._current_part()
        self.mute_cb.SetValue(role in self._muted)

    # -- events ---------------------------------------------------------------

    def _saved_choices(self, kit_name: str) -> dict[str, str]:
        """The user's per-part sample choices for a kit (from the Kit Sounds dialog)."""
        if self._settings is None:
            return {}
        return dict((self._settings.get("drum_kit_sounds") or {}).get(kit_name, {}))

    def _on_kit(self, event: wx.CommandEvent) -> None:
        sel = self.kit_choice.GetStringSelection()
        if sel == SYNTH_LABEL:
            self._kit_dir = None
            self._set_kit(synth_kit())
            self._announce("Synth kit selected.")
            return
        self._announce(f"Loading kit: {sel}...")
        try:
            kit_dir = self._kits_dir() / sel
            kit = load_kit_from_folder(kit_dir, choices=self._saved_choices(sel))
            self._kit_dir = kit_dir
            self._set_kit(kit)
            self._announce(f"Kit '{sel}' loaded: {len(kit.roles())} parts.")
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not load kit:\n{exc}", "Drum kit", wx.ICON_ERROR)

    def _on_import_kit(self, event: wx.CommandEvent) -> None:
        with wx.DirDialog(self, "Choose a drum-kit folder (with KICK, SNARE, ... subfolders)",
                          str(self._kits_dir())) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            kit = load_kit_from_folder(path, choices=self._saved_choices(path.name))
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
        self._kit_dir = path
        self._set_kit(kit)
        self._announce(f"Kit '{path.name}' loaded: {len(kit.roles())} parts.")

    def _on_kit_sounds(self, event: wx.CommandEvent) -> None:
        if self._kit_dir is None:
            # A spoken dialog, not a status-bar line — screen readers don't announce
            # status text, so a silent decline reads as a dead button.
            wx.MessageBox(
                "The built-in synth kit's sounds are generated, so there are no sample\n"
                "files to choose between.\n\n"
                "To pick per-part samples, first select a sample kit in the Kit list\n"
                "(or load one with Import Drum Kit), then open Kit Sounds again.",
                "Kit Sounds", wx.ICON_INFORMATION)
            return
        was_playing = self._playing
        if was_playing:
            self.player.stop()  # previews and the loop share the audio channel
        dark = getattr(wx.GetTopLevelParent(self), "dark_mode", True)
        try:
            dlg = KitSoundsDialog(self, self._kit_dir,
                                  self._saved_choices(self._kit_dir.name), dark)
        except Exception as exc:  # noqa: BLE001 - surface instead of a silent dead button
            wx.MessageBox(f"Could not open Kit Sounds:\n{exc}", "Kit Sounds", wx.ICON_ERROR)
            if was_playing:
                self._render_and_play()
            return
        if dlg.ShowModal() == wx.ID_OK:
            if self._settings is not None:
                all_choices = dict(self._settings.get("drum_kit_sounds") or {})
                all_choices[self._kit_dir.name] = dlg.choices
                self._settings.set("drum_kit_sounds", all_choices)
            try:
                self._set_kit(load_kit_from_folder(self._kit_dir, choices=dlg.choices))
                self._announce("Kit sounds saved.")
            except Exception as exc:  # noqa: BLE001
                wx.MessageBox(f"Could not reload kit:\n{exc}", "Drum kit", wx.ICON_ERROR)
        else:
            self._announce("Kit sounds unchanged.")
        dlg.Destroy()
        if was_playing:
            self._render_and_play()

    def _set_kit(self, kit) -> None:
        self._kit = kit
        self._rebuild_parts()
        self._apply()

    def _on_groove(self, event: wx.CommandEvent) -> None:
        self._pattern = PATTERN_LIBRARY[self.groove_choice.GetSelection()].copy()
        self._rebuild_parts()
        self._apply()
        self._announce(f"Groove: {self._pattern.name} ({self._pattern.meter_label()}).")

    def _on_tempo(self, event: wx.CommandEvent) -> None:
        self.tempo_label.SetLabel(f"Tempo: {self.bpm} BPM")
        self._apply()

    def _fill_every_bars(self) -> int | None:
        sel = self.fill_choice.GetSelection()
        return (None, 2, 4, 8, 12, 16)[sel] if 0 <= sel <= 5 else None

    def _on_fill_every(self, event: wx.CommandEvent) -> None:
        n = self._fill_every_bars()
        self._apply()
        self._announce(f"Fill every {n} bars." if n else "Playing the pattern as written.")

    def _on_part(self, event: wx.CommandEvent) -> None:
        role = self._current_part()
        self.mute_cb.SetValue(role in self._muted)

    def _on_mute(self, event: wx.CommandEvent) -> None:
        role = self._current_part()
        if role is None:
            return
        if self.mute_cb.GetValue():
            self._muted.add(role)
        else:
            self._muted.discard(role)
        self._apply()

    def _on_edit_pattern(self, event: wx.CommandEvent) -> None:
        if self._kit is None:
            self._announce("The drum looper isn't available on this system.")
            return
        was_playing = self._playing
        if was_playing:
            self.player.stop()  # the editor auditions on the same player
        dark = getattr(wx.GetTopLevelParent(self), "dark_mode", True)
        try:
            dlg = PatternEditorDialog(self, self._pattern.copy(), self._kit, self.player,
                                      self.bpm, dark)
        except Exception as exc:  # noqa: BLE001 - surface instead of a silent dead button
            wx.MessageBox(f"Could not open the Pattern Editor:\n{exc}",
                          "Pattern Editor", wx.ICON_ERROR)
            if was_playing:
                self._render_and_play()
            return
        if dlg.ShowModal() == wx.ID_OK:
            self._pattern = dlg.pattern
            self._rebuild_parts()
            self._announce(
                f"Pattern saved: {self._pattern.meter_label()}, {self._pattern.steps} steps.")
        else:
            self._announce("Pattern edits discarded.")
        dlg.Destroy()
        if was_playing:  # resume the loop (new pattern if saved, previous if cancelled)
            self._render_and_play()

    def _on_start_stop(self, event: wx.CommandEvent) -> None:
        if self._playing:
            self.stop()
        else:
            self._start()

    # -- transport ------------------------------------------------------------

    def _render_and_play(self) -> None:
        effective = Pattern(
            self._pattern.name, self._pattern.steps, self._pattern.steps_per_beat,
            {r: s for r, s in self._pattern.hits.items() if r not in self._muted},
            self._pattern.beats_per_bar, self._pattern.beat_unit, self._pattern.bars)
        fill_bars = self._fill_every_bars()
        if fill_bars:
            effective = expand_with_fill(effective, fill_bars)
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
