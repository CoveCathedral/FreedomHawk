"""The Drum Looper page — a customizable, screen-reader-first drum machine.

The main tab stays lean: kit, groove (200 built in), fill cadence and style, tempo,
drum volume, Start.  Deeper editing lives in the **Pattern Editor** — a tracker-style
grid designed with its blind user: one list row per part, a time cursor on the arrow
keys (step / Ctrl=beat / Ctrl+Shift=bar) with positions spoken directly through the
screen reader, Space to toggle hits, Enter for the part's sample options, P to
preview.  Odd/prog meters are set in the editor.

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
    LEVEL_ACCENT,
    LEVEL_GHOST,
    MAX_STEPS,
    NUMPY_AVAILABLE,
    PATTERN_LIBRARY,
    POLY_MAX_LINE,
    ROLE_LABELS,
    ROLES,
    DrumLoopPlayer,
    Pattern,
    default_sample_for,
    expand_with_fill,
    flatten_polymeter,
    improvised_loop,
    list_role_files,
    load_kit_from_folder,
    render_loop,
    retime_pattern,
    steps_per_bar,
    synth_kit,
    wav_duration,
)
from ..practice.drums import load_sample
from ..practice.patternstore import (
    MAX_LINES,
    all_categories,
    build_line_kit,
    builtin_category,
    delete_pattern,
    lines_for_kit,
    make_line,
    make_record,
    record_from_file_dict,
    record_to_file_dict,
    record_to_pattern,
    rename_category,
    rename_pattern,
    save_user_pattern,
    set_pattern_category,
    user_patterns,
)
from ..practice.patternstore import SYNTH_KIT_NAME
from . import speech, theme
from .accessibility import set_accessible_name

try:
    import winsound
except ImportError:  # non-Windows
    winsound = None

TEMPO_MIN = 30
TEMPO_MAX = 300
SYNTH_LABEL = "Synth (built-in)"
FOLLOW_LABEL = "Follow the selected kit"


def step_label(pattern: Pattern, i: int) -> str:
    """Beat-aware name for a step, so odd meters stay navigable (e.g. 'Bar 2 Beat 3.2')."""
    per_bar = max(1, steps_per_bar(pattern.beats_per_bar, pattern.beat_unit,
                                   pattern.steps_per_beat))
    per_beat = max(1, round(pattern.steps_per_beat * 4.0 / max(1, pattern.beat_unit)))
    within = i % per_bar
    beat = within // per_beat + 1
    sub = within % per_beat
    label = f"Beat {beat}" if sub == 0 else f"Beat {beat}.{sub + 1}"
    if pattern.bars > 1 or i >= per_bar:  # multi-bar, or a polymetric line past bar 1
        label = f"Bar {i // per_bar + 1}, {label}"
    return label


class _PreviewPlayer:
    """One-shot sample preview via a temp WAV file.

    winsound's memory-based playback proved unreliable on real hardware (the tuner
    had the same class of bug), so previews write a temp file and play that —
    the path the tuner and the loop player already use successfully.
    """

    def __init__(self) -> None:
        self._path: str | None = None
        if winsound is not None:
            import os
            import tempfile
            fd, self._path = tempfile.mkstemp(prefix="firehawk_preview_", suffix=".wav")
            os.close(fd)

    def play_voice(self, voice) -> bool:
        """Play a float32 sample array once; True if playback was started."""
        if winsound is None or self._path is None or not NUMPY_AVAILABLE:
            return False
        try:
            import wave as wave_mod
            import numpy as np
            pcm = (np.clip(voice, -1.0, 1.0) * 32767.0).astype("<i2")
            w = wave_mod.open(self._path, "wb")
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(pcm.tobytes())
            w.close()
            winsound.PlaySound(self._path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except Exception:  # noqa: BLE001 - preview is best-effort
            return False

    def stop(self) -> None:
        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except Exception:  # noqa: BLE001
                pass

    def dispose(self) -> None:
        self.stop()
        if self._path:
            import os
            try:
                os.remove(self._path)
            except OSError:
                pass
            self._path = None


class PatternEditorDialog(wx.Dialog):
    """Tracker-style accessible pattern grid (designed with/for its blind NVDA user).

    One list row per **line** — and lines are free: stack several of the same drum,
    mix samples from different libraries, up to 24 lines.  A shared time cursor
    lives on the arrow keys, with every move spoken directly through the screen
    reader:

    - Up/Down          move between lines (spoken)
    - Left/Right       one grid step        (the smallest increment)
    - Ctrl+Left/Right  one beat
    - Ctrl+Shift+L/R   one bar              (Home/End: start / last step)
    - Space            toggle a hit for this line at the cursor
    - Enter            sample options for this line (pick a sample, or None)
    - Delete           remove an added line
    - P                preview this line's sound
    - F1               speak this key list

    Buttons: Add Line (any part, from the synth or any kit library), Load Groove
    (any built-in or saved pattern), Save as Preset (name + category), Play/Pause,
    Save, Cancel.  Works on its own copies; Save returns them, Cancel discards.
    """

    AUTO = "(automatic default)"

    def __init__(self, parent: wx.Window, pattern: Pattern, lines: list[dict],
                 kits_dir, silenced: set[str] | None, player: DrumLoopPlayer,
                 bpm: int, dark: bool = True, settings=None,
                 swing: float = 0.0, humanize: float = 0.0, base_kit=None,
                 apply_fills=None):
        super().__init__(parent, title="Pattern Editor",
                         size=(660, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.pattern = pattern
        self.lines = [dict(ln) for ln in lines]
        self.silenced: set[str] = set(silenced or ())
        self._kits_dir = Path(kits_dir)
        self._settings = settings
        self._player = player
        self._bpm = bpm
        self._swing = swing        # match the main tab's feel while auditioning
        self._humanize = humanize
        self._base_kit = base_kit  # the globally selected kit (follow-global lines use it)
        self._apply_fills = apply_fills  # panel's fill/improv transform, so audition matches
        self._dark = dark
        self._auditioning = False
        self._cursor = 0
        self._preview = _PreviewPlayer()
        self._line_kit = build_line_kit(self.lines, self._kits_dir, base_kit=self._base_kit)

        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=(
            "One line per part; add lines to stack drums or mix libraries. Up/Down "
            "move between lines; Left/Right move by step, Ctrl by beat, Ctrl+Shift "
            "by bar; Space toggles a hit; Enter picks the line's sample (or None); "
            "Delete removes a line; P previews; F1 speaks the keys."))
        intro.Wrap(620)
        root.Add(intro, 0, wx.ALL, 10)

        self.grid_list = wx.ListBox(self, choices=[], style=wx.LB_SINGLE)
        set_accessible_name(self.grid_list, "Pattern grid")
        root.Add(self.grid_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        meter = wx.FlexGridSizer(cols=4, vgap=6, hgap=8)
        meter.Add(wx.StaticText(self, label="Beats per bar:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.beats_choice = wx.Choice(self, choices=[str(n) for n in range(1, 17)])
        set_accessible_name(self.beats_choice, "Beats per bar")
        self.beats_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        meter.Add(self.beats_choice, 0)
        meter.Add(wx.StaticText(self, label="Beat unit:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.unit_choice = wx.Choice(self, choices=[str(n) for n in DRUM_BEAT_UNITS])
        set_accessible_name(self.unit_choice, "Beat unit, note value")
        self.unit_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        meter.Add(self.unit_choice, 0)
        meter.Add(wx.StaticText(self, label="Grid (steps per beat):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.grid_choice = wx.Choice(self, choices=[label for label, _ in GRID_CHOICES])
        set_accessible_name(self.grid_choice, "Grid resolution")
        self.grid_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        meter.Add(self.grid_choice, 0)
        meter.Add(wx.StaticText(self, label="Bars in loop:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.bars_choice = wx.Choice(self, choices=["1", "2", "3", "4"])
        set_accessible_name(self.bars_choice, "Bars in the loop")
        self.bars_choice.Bind(wx.EVT_CHOICE, self._on_meter)
        meter.Add(self.bars_choice, 0)
        root.Add(meter, 0, wx.ALL, 10)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(self, label="Add &Line...")
        add_btn.Bind(wx.EVT_BUTTON, lambda e: self._add_line())
        btns.Add(add_btn, 0, wx.RIGHT, 8)
        load_btn = wx.Button(self, label="Load &Groove...")
        load_btn.Bind(wx.EVT_BUTTON, lambda e: self._load_groove())
        btns.Add(load_btn, 0, wx.RIGHT, 8)
        preset_btn = wx.Button(self, label="Save as Prese&t...")
        preset_btn.Bind(wx.EVT_BUTTON, lambda e: self._save_as_preset())
        btns.Add(preset_btn, 0, wx.RIGHT, 8)
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
        self.Bind(wx.EVT_CLOSE, self._on_close)
        # Grid keys arrive via the dialog's char hook: a dialog preprocesses Enter
        # (default button) and Space before a list's own key handler ever runs.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        theme.apply(self, dark)

        self._sync_meter_controls()
        self._rebuild_rows()
        if self.lines:
            self.grid_list.SetSelection(0)
        wx.CallAfter(self.grid_list.SetFocus)

    # -- state ----------------------------------------------------------------

    def _current_line(self) -> dict | None:
        sel = self.grid_list.GetSelection()
        return self.lines[sel] if 0 <= sel < len(self.lines) else None

    def _per_bar(self) -> int:
        return max(1, self.pattern.steps // max(1, self.pattern.bars))

    def _beat_len(self) -> int:
        p = self.pattern
        return max(1, round(p.steps_per_beat * 4.0 / max(1, p.beat_unit)))

    def _line_len(self) -> int:
        """The current line's own loop length (its polymeter cycle), else the full pattern."""
        line = self._current_line()
        return self.pattern.line_length(line["id"]) if line else self.pattern.steps

    def _sample_desc(self, line: dict) -> str:
        if line["id"] in self.silenced:
            return "silent"
        kit_name = line.get("kit")
        if kit_name is None:                 # follows the globally selected kit
            base = self._base_kit.name if self._base_kit else "synth"
            return f"from {base}"
        if kit_name == SYNTH_KIT_NAME:
            return "synth"
        if line.get("sample"):
            return Path(line["sample"]).stem
        files = list_role_files(self._kits_dir / kit_name).get(line["role"], [])
        pick = default_sample_for(line["role"], files)
        return pick.stem if pick else "none"

    def _row_label(self, line: dict) -> str:
        n = len(self.pattern.hits.get(line["id"], []))
        hits = "no hits" if n == 0 else ("1 hit" if n == 1 else f"{n} hits")
        length = self.pattern.line_length(line["id"])
        poly = f", length {length} steps" if length != self.pattern.steps else ""
        return f"{line['label']}: {hits}{poly}, sample {self._sample_desc(line)}"

    def _rebuild_rows(self) -> None:
        keep = max(0, self.grid_list.GetSelection())
        self.grid_list.Set([self._row_label(ln) for ln in self.lines])
        if self.lines:
            self.grid_list.SetSelection(min(keep, len(self.lines) - 1))

    def _refresh_row(self, line: dict) -> None:
        for i, ln in enumerate(self.lines):
            if ln is line:
                self.grid_list.SetString(i, self._row_label(line))
                return

    def _rebuild_line_kit(self) -> None:
        self._line_kit = build_line_kit(self.lines, self._kits_dir, base_kit=self._base_kit)

    def _sync_meter_controls(self) -> None:
        p = self.pattern
        self.beats_choice.SetSelection(max(0, min(15, p.beats_per_bar - 1)))
        if p.beat_unit in DRUM_BEAT_UNITS:
            self.unit_choice.SetSelection(DRUM_BEAT_UNITS.index(p.beat_unit))
        grids = [g for _, g in GRID_CHOICES]
        if p.steps_per_beat in grids:
            self.grid_choice.SetSelection(grids.index(p.steps_per_beat))
        self.bars_choice.SetSelection(max(0, min(3, p.bars - 1)))

    # -- the grid keys ---------------------------------------------------------

    def _speak_cursor(self) -> None:
        line = self._current_line()
        state = self._state_at(line["id"], self._cursor) if line else "empty"
        speech.speak(f"{step_label(self.pattern, self._cursor)}, {state}")

    def _move_cursor(self, delta: int) -> None:
        # The cursor lives within the current line's own cycle (polymeter).
        self._cursor = max(0, min(self._line_len() - 1, self._cursor + delta))
        self._speak_cursor()

    def _move_line(self, delta: int) -> None:
        """Move between lines and speak the landing line ourselves — up/down is fully
        owned, so navigation is deterministic whatever the native list would do."""
        if not self.lines:
            return
        sel = max(0, self.grid_list.GetSelection())
        new = max(0, min(len(self.lines) - 1, sel + delta))
        self.grid_list.SetSelection(new)
        line = self.lines[new]
        self._cursor = min(self._cursor, self._line_len() - 1)  # clamp into the new cycle
        state = self._state_at(line["id"], self._cursor)
        speech.speak(f"{self._row_label(line)}. Cursor: "
                     f"{step_label(self.pattern, self._cursor)}, {state}")

    _LENGTHEN_KEYS = frozenset({ord("="), ord("+"), wx.WXK_NUMPAD_ADD})
    _SHORTEN_KEYS = frozenset({ord("-"), ord("_"), wx.WXK_NUMPAD_SUBTRACT})
    _GRID_KEYS = frozenset({wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT,
                            wx.WXK_HOME, wx.WXK_END, wx.WXK_SPACE, wx.WXK_RETURN,
                            wx.WXK_NUMPAD_ENTER, wx.WXK_F1, wx.WXK_DELETE,
                            ord("P"), ord("p")}) | _LENGTHEN_KEYS | _SHORTEN_KEYS

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        # Route grid keys only while the grid list has focus; everything else (Tab,
        # Escape, arrows inside the meter dropdowns, button activation) stays native.
        if wx.Window.FindFocus() is self.grid_list and event.GetKeyCode() in self._GRID_KEYS:
            self._on_grid_key(event)
            return
        event.Skip()

    def _on_grid_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        ctrl, shift = event.ControlDown(), event.ShiftDown()
        if code in (wx.WXK_UP, wx.WXK_DOWN):
            self._move_line(1 if code == wx.WXK_DOWN else -1)
        elif code in (wx.WXK_LEFT, wx.WXK_RIGHT):
            sign = 1 if code == wx.WXK_RIGHT else -1
            if ctrl and shift:
                self._move_cursor(sign * self._per_bar())
            elif ctrl:
                self._move_cursor(sign * self._beat_len())
            else:
                self._move_cursor(sign)
        elif code == wx.WXK_HOME:
            self._cursor = 0
            self._speak_cursor()
        elif code == wx.WXK_END:
            self._cursor = self._line_len() - 1
            self._speak_cursor()
        elif code == wx.WXK_SPACE:
            self._toggle_hit()
        elif code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._sample_options()
        elif code == wx.WXK_DELETE:
            self._delete_line()
        elif code in self._LENGTHEN_KEYS:
            self._change_line_length(1)
        elif code in self._SHORTEN_KEYS:
            self._change_line_length(-1)
        elif code in (ord("P"), ord("p")):
            self._preview_line()
        elif code == wx.WXK_F1:
            speech.speak(
                "Up and Down move between lines. Left and Right move by step. "
                "Control Left and Right move by beat. Control Shift Left and Right "
                "move by bar. Home and End jump to the start and end. Space cycles "
                "a step: on, accent, ghost, off. Minus and Plus set this line's "
                "length for polymeter, so lines can loop in different lengths and "
                "phase against each other. Enter picks this line's sample or None. "
                "Delete removes a line. P previews the line. Tab reaches Add Line, "
                "Load Groove, Save as Preset, the meter controls, and Play, Save "
                "and Cancel.")
        else:
            event.Skip()

    def _change_line_length(self, delta: int) -> None:
        """Grow or shrink the current line's loop length (per-line polymeter)."""
        line = self._current_line()
        if line is None:
            return
        new_len = max(1, min(POLY_MAX_LINE, self._line_len() + delta))
        self.pattern.set_line_length(line["id"], new_len)
        self._cursor = min(self._cursor, new_len - 1)
        self._refresh_row(line)
        synced = " (synced with the pattern)" if new_len == self.pattern.steps else ""
        speech.speak(f"{line['label']} length {new_len} steps{synced}")
        self._reaudition()

    def _toggle_hit(self) -> None:
        """Space cycles a step's state: off -> on -> accent -> ghost -> off."""
        line = self._current_line()
        if line is None:
            return
        line_id = line["id"]
        steps = set(self.pattern.hits.get(line_id, []))
        if self._cursor not in steps:
            steps.add(self._cursor)
            self.pattern.set_level(line_id, self._cursor, None)
            spoken = "on"
        else:
            level = self.pattern.level_of(line_id, self._cursor)
            if level is None:
                self.pattern.set_level(line_id, self._cursor, LEVEL_ACCENT)
                spoken = "accent"
            elif level == LEVEL_ACCENT:
                self.pattern.set_level(line_id, self._cursor, LEVEL_GHOST)
                spoken = "ghost"
            else:  # ghost -> off
                steps.discard(self._cursor)
                self.pattern.set_level(line_id, self._cursor, None)
                spoken = "off"
        if steps:
            self.pattern.hits[line_id] = sorted(steps)
        else:
            self.pattern.hits.pop(line_id, None)
        self._refresh_row(line)
        speech.speak(f"{line['label']} {spoken}, {step_label(self.pattern, self._cursor)}")
        self._reaudition()

    def _state_at(self, line_id: str, step: int) -> str:
        if step not in self.pattern.hits.get(line_id, []):
            return "empty"
        return self.pattern.level_of(line_id, step) or "hit"

    # -- line management -------------------------------------------------------

    def _add_line(self) -> None:
        if len(self.lines) >= MAX_LINES:
            speech.speak(f"Limit of {MAX_LINES} lines reached.")
            return
        role_labels = [ROLE_LABELS[r] for r in ROLES]
        dlg = wx.SingleChoiceDialog(self, "Which part?", "Add line", role_labels)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        role = ROLES[dlg.GetSelection()]
        dlg.Destroy()

        kit_names = [d.name for d in sorted(self._kits_dir.iterdir())
                     if d.is_dir()] if self._kits_dir.is_dir() else []
        sources = [FOLLOW_LABEL, SYNTH_LABEL] + kit_names
        dlg = wx.SingleChoiceDialog(self, f"Sound source for {ROLE_LABELS[role]}:",
                                    "Add line", sources)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        source = sources[dlg.GetSelection()]
        dlg.Destroy()

        kit_name, sample = None, None  # None follows the globally selected kit
        if source == SYNTH_LABEL:
            kit_name = SYNTH_KIT_NAME
        elif source != FOLLOW_LABEL:
            kit_name = source
            files = list_role_files(self._kits_dir / kit_name).get(role, [])
            if files:
                stems = [self.AUTO] + [f.stem for f in files]
                dlg = wx.SingleChoiceDialog(self, "Which sample?", "Add line", stems)
                theme.apply(dlg, self._dark)
                if dlg.ShowModal() == wx.ID_OK and dlg.GetSelection() > 0:
                    sample = files[dlg.GetSelection() - 1].name
                dlg.Destroy()
            else:
                speech.speak(f"{kit_name} has no {ROLE_LABELS[role]} samples; "
                             "using the synth sound.")
                kit_name = None
        line = make_line(role, kit_name, sample, existing=self.lines)
        self.lines.append(line)
        self._rebuild_line_kit()
        self._rebuild_rows()
        self.grid_list.SetSelection(len(self.lines) - 1)
        speech.speak(f"Added {line['label']}")

    def _delete_line(self) -> None:
        line = self._current_line()
        if line is None:
            return
        if len(self.lines) <= 1:
            speech.speak("Cannot remove the last line.")
            return
        self.lines.remove(line)
        self.pattern.hits.pop(line["id"], None)
        self.pattern.levels.pop(line["id"], None)
        self.pattern.lengths.pop(line["id"], None)
        self.silenced.discard(line["id"])
        self._rebuild_line_kit()
        self._rebuild_rows()
        speech.speak(f"Removed {line['label']}")
        self._reaudition()

    def _sample_options(self) -> None:
        line = self._current_line()
        if line is None:
            return
        kit_name = line.get("kit")
        files: list = []
        if kit_name is None or kit_name == SYNTH_KIT_NAME:
            # A follow-global or synth line: source choices, not individual samples
            # (its samples come from the main Kit / Kit Sounds).
            options = [FOLLOW_LABEL, "Synth (built-in)", "None (silence this line)"]
        else:
            files = list_role_files(self._kits_dir / kit_name).get(line["role"], [])
            options = [self.AUTO] + [f.stem for f in files] + ["None (silence this line)"]
        dlg = wx.SingleChoiceDialog(self, f"Sound for {line['label']}:",
                                    f"{line['label']} sample", options)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() == wx.ID_OK:
            choice = options[dlg.GetSelection()]
            if choice.startswith("None"):
                self.silenced.add(line["id"])
            else:
                self.silenced.discard(line["id"])
                if kit_name is None or kit_name == SYNTH_KIT_NAME:
                    line["kit"] = None if choice == FOLLOW_LABEL else SYNTH_KIT_NAME
                    line["sample"] = None
                else:
                    line["sample"] = None if choice == self.AUTO else \
                        files[dlg.GetSelection() - 1].name
                self._rebuild_line_kit()
            self._refresh_row(line)
            speech.speak(f"{line['label']}: {self._sample_desc(line)}")
            self._reaudition()
        dlg.Destroy()

    def _preview_line(self) -> None:
        line = self._current_line()
        if line is None:
            return
        if line["id"] in self.silenced:
            speech.speak(f"{line['label']} is silent")
            return
        voice = self._line_kit.voice(line["id"])
        if voice is None or len(voice) == 0:
            speech.speak(f"No sound for {line['label']}")
            return
        if self._auditioning:
            self._stop_audition()  # the preview needs the audio channel
        if self._preview.play_voice(voice):
            speech.speak(line["label"])
        else:
            speech.speak(f"{line['label']}: preview not available")

    # -- grooves & presets -----------------------------------------------------

    def _load_groove(self) -> None:
        """Replace the editor contents with any built-in or saved pattern."""
        user = user_patterns(self._settings)
        names = [p.name for p in PATTERN_LIBRARY]
        names += [f"{r['name']}  [{r.get('category', 'My patterns')}]" for r in user]
        dlg = wx.SingleChoiceDialog(self, "Load which groove?", "Load groove", names)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        sel = dlg.GetSelection()
        dlg.Destroy()
        if sel < len(PATTERN_LIBRARY):
            pattern = PATTERN_LIBRARY[sel].copy()
            self.lines = lines_for_kit(pattern, self._line_kit, None)
            for ln in self.lines:
                ln["kit"] = None  # built-ins load onto the synth; retune via Enter
            self.pattern = pattern
        else:
            record = user[sel - len(PATTERN_LIBRARY)]
            self.pattern = record_to_pattern(record)
            self.lines = [dict(ln) for ln in record.get("lines", [])]
        self.silenced.clear()
        self._cursor = 0
        self._rebuild_line_kit()
        self._sync_meter_controls()
        self._rebuild_rows()
        if self.lines:
            self.grid_list.SetSelection(0)
        speech.speak(f"Loaded {self.pattern.name}: {self.pattern.meter_label()}, "
                     f"{len(self.lines)} lines")
        self._reaudition()

    def _save_as_preset(self) -> None:
        if self._settings is None:
            wx.MessageBox("Saving presets isn't available here.", "Save as preset",
                          wx.ICON_INFORMATION)
            return
        with wx.TextEntryDialog(self, "Preset name:", "Save as preset") as dlg:
            theme.apply(dlg, self._dark)
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.GetValue().strip()
        if not name:
            return
        cats = all_categories(self._settings) + ["New category..."]
        dlg = wx.SingleChoiceDialog(self, "Category:", "Save as preset", cats)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        category = cats[dlg.GetSelection()]
        dlg.Destroy()
        if category == "New category...":
            with wx.TextEntryDialog(self, "New category name:", "Save as preset") as dlg2:
                theme.apply(dlg2, self._dark)
                if dlg2.ShowModal() != wx.ID_OK:
                    return
                category = dlg2.GetValue().strip() or "My patterns"
        record = make_record(name, category, self.pattern.beats_per_bar,
                             self.pattern.beat_unit, self.pattern.steps_per_beat,
                             self.pattern.bars, self.lines, self.pattern)
        save_user_pattern(self._settings, record)
        speech.speak(f"Saved preset {name} in {category}")

    # -- meter / transport -----------------------------------------------------

    def _on_meter(self, event: wx.CommandEvent) -> None:
        beats = self.beats_choice.GetSelection() + 1
        unit = DRUM_BEAT_UNITS[self.unit_choice.GetSelection()]
        grid = GRID_CHOICES[self.grid_choice.GetSelection()][1]
        bars = self.bars_choice.GetSelection() + 1
        per_bar = steps_per_bar(beats, unit, grid)
        while bars > 1 and per_bar * bars > MAX_STEPS:  # keep the grid navigable
            bars -= 1
        self.bars_choice.SetSelection(bars - 1)
        # Non-destructive: bar-count changes tile; grid/beat changes remap hits by
        # musical time so nothing drops or drifts out of time (see retime_pattern).
        grid_changed = grid != self.pattern.steps_per_beat
        was_poly = self.pattern.is_polymetric()
        self.pattern = retime_pattern(self.pattern, beats, unit, grid, bars)
        self._cursor = min(self._cursor, self._line_len() - 1)
        self._rebuild_rows()
        note = " Per-line lengths reset." if (was_poly and grid_changed) else ""
        if grid_changed:
            speech.speak(f"Grid changed; hits re-quantized to the new grid.{note}")
        else:
            speech.speak(f"Meter {self.pattern.meter_label()}, "
                         f"{self.pattern.bars} bar{'s' if self.pattern.bars != 1 else ''}.")
        self._reaudition()

    def _effective_pattern(self) -> Pattern:
        p = self.pattern
        return Pattern(p.name, p.steps, p.steps_per_beat,
                       {r: s for r, s in p.hits.items() if r not in self.silenced},
                       p.beats_per_bar, p.beat_unit, p.bars,
                       {r: dict(m) for r, m in p.levels.items() if r not in self.silenced},
                       {r: L for r, L in p.lengths.items() if r not in self.silenced})

    def _on_play(self, event: wx.CommandEvent) -> None:
        if self._auditioning:
            self._stop_audition()
            return
        if not self._player.available:
            return
        self._auditioning = True
        self._player.play(self._render())
        self.play_btn.SetLabel("&Pause")

    def _render(self):
        effective = flatten_polymeter(self._effective_pattern())
        if self._apply_fills is not None:  # match the main tab's fill cadence / improv
            effective = self._apply_fills(effective)
        return render_loop(effective, self._line_kit, self._bpm,
                           swing=self._swing, humanize=self._humanize)

    def _reaudition(self) -> None:
        if self._auditioning:
            self._player.play(self._render())

    def _stop_audition(self) -> None:
        if self._auditioning:
            self._player.stop()
            self._auditioning = False
            self.play_btn.SetLabel("&Play")

    def _on_save(self, event: wx.CommandEvent) -> None:
        self._stop_audition()
        self._preview.dispose()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event: wx.CommandEvent) -> None:
        self._stop_audition()
        self._preview.dispose()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event) -> None:
        self._stop_audition()
        self._preview.dispose()
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
        self._player = _PreviewPlayer()

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
        if not NUMPY_AVAILABLE or role is None or not (0 <= i < len(files)):
            return
        try:
            self._player.play_voice(load_sample(files[i]))
        except Exception:  # noqa: BLE001 - preview is best-effort
            pass

    def _stop_preview(self) -> None:
        self._player.stop()

    def _on_save(self, event: wx.CommandEvent) -> None:
        self._player.dispose()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event: wx.CommandEvent) -> None:
        self._player.dispose()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event) -> None:
        self._player.dispose()
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
        self._line_meta: list[dict] | None = None  # set for mix-and-match patterns
        self._pattern_voices = None                # composite kit for line patterns
        self._muted: set[str] = set()
        self._playing = False
        self._groove_entries: list[tuple[str, object]] = []

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

        # Genre filter: built-in families plus the user's own categories.
        grid.Add(wx.StaticText(self, label="Category:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.category_choice = wx.Choice(self)
        set_accessible_name(self.category_choice, "Category filter")
        self.category_choice.Bind(wx.EVT_CHOICE, lambda e: self._rebuild_groove_list())
        grid.Add(self.category_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="Groove:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.groove_choice = wx.Choice(self)
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

        # Fixed fills as written, or rule-bound improvisation (a fresh set of fills
        # is generated on every render, so the groove rarely repeats itself exactly).
        grid.Add(wx.StaticText(self, label="Fill style:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.fillstyle_choice = wx.Choice(self, choices=[
            "As written", "Improvised (varies every time)"])
        self.fillstyle_choice.SetSelection(0)
        set_accessible_name(self.fillstyle_choice, "Fill style")
        self.fillstyle_choice.Bind(wx.EVT_CHOICE, self._on_fill_style)
        grid.Add(self.fillstyle_choice, 0, wx.EXPAND)

        self.tempo_label = wx.StaticText(self, label="Tempo: 90 BPM")
        grid.Add(self.tempo_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.tempo_slider = wx.Slider(self, value=90, minValue=TEMPO_MIN, maxValue=TEMPO_MAX)
        # Announce real BPM, not the slider's percent-of-range (see metronomepanel).
        set_accessible_name(self.tempo_slider, "Tempo",
                            value_fn=lambda: f"{self.tempo_slider.GetValue()} BPM")
        self.tempo_slider.Bind(wx.EVT_SLIDER, self._on_tempo)
        grid.Add(self.tempo_slider, 0, wx.EXPAND)

        # Master volume for the drums, so they sit right against the guitar.
        self.volume_label = wx.StaticText(self, label="Drum volume: 80%")
        grid.Add(self.volume_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.volume_slider = wx.Slider(self, value=80, minValue=0, maxValue=100)
        set_accessible_name(self.volume_slider, "Drum volume",
                            value_fn=lambda: f"{self.volume_slider.GetValue()} percent")
        self.volume_slider.Bind(wx.EVT_SLIDER, self._on_volume)
        grid.Add(self.volume_slider, 0, wx.EXPAND)

        # Feel: swing delays off-beats (shuffle); humanize adds subtle timing/level drift.
        self.swing_label = wx.StaticText(self, label="Swing: 0% (straight)")
        grid.Add(self.swing_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.swing_slider = wx.Slider(self, value=0, minValue=0, maxValue=100)
        set_accessible_name(self.swing_slider, "Swing",
                            value_fn=lambda: f"{self.swing_slider.GetValue()} percent")
        self.swing_slider.Bind(wx.EVT_SLIDER, self._on_feel)
        grid.Add(self.swing_slider, 0, wx.EXPAND)

        self.humanize_label = wx.StaticText(self, label="Humanize: 0%")
        grid.Add(self.humanize_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.humanize_slider = wx.Slider(self, value=0, minValue=0, maxValue=100)
        set_accessible_name(self.humanize_slider, "Humanize",
                            value_fn=lambda: f"{self.humanize_slider.GetValue()} percent")
        self.humanize_slider.Bind(wx.EVT_SLIDER, self._on_feel)
        grid.Add(self.humanize_slider, 0, wx.EXPAND)

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

        self._rebuild_categories()
        self._rebuild_groove_list()
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
        if self._line_meta is not None:
            # Mix-and-match pattern: parts are its lines, labelled from the metadata.
            self._part_roles = [ln["id"] for ln in self._line_meta]
            labels = [ln["label"] for ln in self._line_meta]
        else:
            kit_roles = self._kit.roles() if self._kit else []
            self._part_roles = [r for r in ROLES if r in kit_roles or r in self._pattern.hits]
            labels = [ROLE_LABELS.get(r, r) for r in self._part_roles]
        self.part_choice.Set(labels)
        if self._part_roles:
            self.part_choice.SetSelection(0)
        role = self._current_part()
        self.mute_cb.SetValue(role in self._muted)

    # -- groove list & categories ----------------------------------------------

    def _rebuild_categories(self) -> None:
        keep = self.category_choice.GetStringSelection() or "All categories"
        cats = ["All categories"] + all_categories(self._settings)
        self.category_choice.Set(cats)
        idx = self.category_choice.FindString(keep)
        self.category_choice.SetSelection(idx if idx != wx.NOT_FOUND else 0)

    def _rebuild_groove_list(self) -> None:
        """Populate the Groove dropdown: built-ins plus saved patterns, filtered."""
        category = self.category_choice.GetStringSelection()
        show_all = not category or category == "All categories"
        self._groove_entries = []
        names = []
        for i, p in enumerate(PATTERN_LIBRARY):
            if show_all or builtin_category(p.name) == category:
                self._groove_entries.append(("builtin", i))
                names.append(p.name)
        for rec in user_patterns(self._settings):
            if show_all or rec.get("category") == category:
                self._groove_entries.append(("user", rec))
                names.append(f"{rec['name']}  [{rec.get('category', 'My patterns')}]")
        self.groove_choice.Set(names)
        if names:
            self.groove_choice.SetSelection(0)

    def _load_user_record(self, record: dict) -> None:
        self._pattern = record_to_pattern(record)
        self._line_meta = [dict(ln) for ln in record.get("lines", [])]
        self._pattern_voices = build_line_kit(self._line_meta, self._kits_dir(),
                                              base_kit=self._kit)
        self._muted = set()

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
        if self._line_meta is not None:  # re-voice follow-global lines through the new kit
            self._pattern_voices = build_line_kit(self._line_meta, self._kits_dir(),
                                                  base_kit=self._kit)
        self._rebuild_parts()
        self._apply()

    def _on_groove(self, event: wx.CommandEvent) -> None:
        sel = self.groove_choice.GetSelection()
        if not (0 <= sel < len(self._groove_entries)):
            return
        kind, ref = self._groove_entries[sel]
        if kind == "builtin":
            self._pattern = PATTERN_LIBRARY[ref].copy()
            self._line_meta = None
            self._pattern_voices = None
        else:
            self._load_user_record(ref)
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

    def _on_fill_style(self, event: wx.CommandEvent) -> None:
        improv = self.fillstyle_choice.GetSelection() == 1
        self._apply()
        self._announce("Improvised fills: a fresh set every time." if improv
                       else "Fills as written.")

    def _on_volume(self, event: wx.CommandEvent) -> None:
        self.volume_label.SetLabel(f"Drum volume: {self.volume_slider.GetValue()}%")
        self._apply()

    def _on_feel(self, event: wx.CommandEvent) -> None:
        sw = self.swing_slider.GetValue()
        self.swing_label.SetLabel(f"Swing: {sw}%" + (" (straight)" if sw == 0 else ""))
        self.humanize_label.SetLabel(f"Humanize: {self.humanize_slider.GetValue()}%")
        self._apply()

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
        self.open_editor(blank=False)

    def _current_lines(self) -> list[dict]:
        """The current pattern as editor lines (existing metadata, or one per part)."""
        if self._line_meta is not None:
            return [dict(ln) for ln in self._line_meta]
        kit_name = self._kit_dir.name if self._kit_dir else None
        choices = self._saved_choices(kit_name) if kit_name else {}
        return lines_for_kit(self._pattern, self._kit, kit_name, choices)

    def open_editor(self, blank: bool = False, pattern: Pattern | None = None,
                    lines: list[dict] | None = None) -> None:
        """Open the Pattern Editor — on the current groove, empty (Ctrl+D), or
        seeded with a given pattern (e.g. straight from a MIDI import)."""
        if self._kit is None:
            wx.MessageBox("The drum looper needs numpy installed (pip install numpy).",
                          "Pattern Editor", wx.ICON_INFORMATION)
            return
        was_playing = self._playing
        if was_playing:
            self.player.stop()  # the editor auditions on the same player
        dark = getattr(wx.GetTopLevelParent(self), "dark_mode", True)
        kit_name = self._kit_dir.name if self._kit_dir else None
        muted: set[str] = set()
        if pattern is not None:
            if lines is None:
                lines = lines_for_kit(pattern, self._kit, kit_name)
        elif blank:
            pattern = Pattern("new pattern", self._pattern.steps,
                              self._pattern.steps_per_beat, {},
                              self._pattern.beats_per_bar, self._pattern.beat_unit,
                              self._pattern.bars)
            lines = lines_for_kit(pattern, self._kit, kit_name)
        else:
            pattern, lines, muted = self._pattern.copy(), self._current_lines(), set(self._muted)
        try:
            dlg = PatternEditorDialog(self, pattern, lines, self._kits_dir(), muted,
                                      self.player, self.bpm, dark, settings=self._settings,
                                      swing=self.swing_slider.GetValue() / 100.0,
                                      humanize=self.humanize_slider.GetValue() / 100.0,
                                      base_kit=self._kit, apply_fills=self._apply_fills)
        except Exception as exc:  # noqa: BLE001 - surface instead of a silent dead button
            wx.MessageBox(f"Could not open the Pattern Editor:\n{exc}",
                          "Pattern Editor", wx.ICON_ERROR)
            if was_playing:
                self._render_and_play()
            return
        if dlg.ShowModal() == wx.ID_OK:
            self._pattern = dlg.pattern
            self._line_meta = [dict(ln) for ln in dlg.lines]
            self._pattern_voices = build_line_kit(self._line_meta, self._kits_dir(),
                                                  base_kit=self._kit)
            self._muted = set(dlg.silenced)  # "None" sample choices = muted lines
            self._rebuild_parts()
            self._announce(
                f"Pattern saved: {self._pattern.meter_label()}, {self._pattern.steps} steps.")
        else:
            self._announce("Pattern edits discarded.")
        dlg.Destroy()
        # Presets may have been saved from inside the editor either way.
        self._rebuild_categories()
        self._rebuild_groove_list()
        if was_playing:  # resume the loop (new pattern if saved, previous if cancelled)
            self._render_and_play()

    def _on_start_stop(self, event: wx.CommandEvent) -> None:
        if self._playing:
            self.stop()
        else:
            self._start()

    # -- transport ------------------------------------------------------------

    def _muted_pattern(self) -> Pattern:
        """The current pattern with muted lines removed, polymeter flattened to a plain
        loop so the fill/improv transforms (which are meter-based) can work on it."""
        p = self._pattern
        effective = Pattern(
            p.name, p.steps, p.steps_per_beat,
            {r: s for r, s in p.hits.items() if r not in self._muted},
            p.beats_per_bar, p.beat_unit, p.bars,
            {r: dict(m) for r, m in p.levels.items() if r not in self._muted},
            {r: L for r, L in p.lengths.items() if r not in self._muted})
        return flatten_polymeter(effective)

    def _apply_fills(self, effective: Pattern) -> Pattern:
        fill_bars = self._fill_every_bars()
        if self.fillstyle_choice.GetSelection() == 1:
            # Improvised: several passes, each ending in a different generated fill.
            # With no explicit cadence, improvise on a 4-bar cycle — a 1-bar cycle
            # would put a fill in every single bar and wreck the meter's feel.
            cycle = fill_bars or max(4, effective.bars)
            cycles = 2 if cycle >= 12 else 4
            return improvised_loop(effective, cycle, cycles)
        if fill_bars:
            return expand_with_fill(effective, fill_bars)
        return effective

    def _render_and_play(self) -> None:
        effective = self._apply_fills(self._muted_pattern())
        kit = self._pattern_voices or self._kit  # composite voices for line patterns
        self.player.play(render_loop(effective, kit, self.bpm,
                                     volume=self.volume_slider.GetValue() / 100.0,
                                     swing=self.swing_slider.GetValue() / 100.0,
                                     humanize=self.humanize_slider.GetValue() / 100.0))

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

    # -- sharing: WAV / pattern files / MIDI (Tools menu) ----------------------

    def _dark(self) -> bool:
        return getattr(wx.GetTopLevelParent(self), "dark_mode", True)

    def _export_effective_pattern(self) -> Pattern:
        """The pattern exactly as it would play: mutes, polymeter, fills."""
        return self._apply_fills(self._muted_pattern())

    def export_wav(self) -> None:
        """Render the current loop (fills and all) to a WAV file."""
        if self._kit is None:
            wx.MessageBox("The drum looper needs numpy installed.", "Export WAV",
                          wx.ICON_INFORMATION)
            return
        with wx.FileDialog(self, "Export drum loop as WAV",
                           wildcard="WAV audio (*.wav)|*.wav",
                           defaultFile=f"{self._pattern.name}.wav",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            kit = self._pattern_voices or self._kit
            wav = render_loop(self._export_effective_pattern(), kit, self.bpm,
                              volume=self.volume_slider.GetValue() / 100.0,
                              swing=self.swing_slider.GetValue() / 100.0,
                              humanize=self.humanize_slider.GetValue() / 100.0)
            path.write_bytes(wav)
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not export:\n{exc}", "Export WAV", wx.ICON_ERROR)
            return
        self._announce(f"Exported loop to {path.name}")

    def export_pattern_file(self) -> None:
        """Save the current pattern as a shareable .fhdrum.json file."""
        import json
        name = self._pattern.name if self._pattern.name not in ("custom",) else "My Pattern"
        with wx.TextEntryDialog(self, "Pattern name for the file:", "Export pattern",
                                name) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.GetValue().strip() or name
        record = make_record(name, "Shared", self._pattern.beats_per_bar,
                             self._pattern.beat_unit, self._pattern.steps_per_beat,
                             self._pattern.bars, self._current_lines(), self._pattern)
        with wx.FileDialog(self, "Export drum pattern",
                           wildcard="Drum pattern (*.fhdrum.json)|*.fhdrum.json",
                           defaultFile=f"{name}.fhdrum.json",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            path.write_text(json.dumps(record_to_file_dict(record), indent=2),
                            encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not export:\n{exc}", "Export pattern", wx.ICON_ERROR)
            return
        self._announce(f"Exported pattern to {path.name}")

    def import_pattern_file(self) -> None:
        """Load a shared pattern file into the library and select it."""
        import json
        with wx.FileDialog(self, "Import drum pattern",
                           wildcard="Drum pattern (*.fhdrum.json;*.json)|*.fhdrum.json;*.json",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            record = record_from_file_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not import {path.name}:\n{exc}", "Import pattern",
                          wx.ICON_ERROR)
            return
        save_user_pattern(self._settings, record)
        self._rebuild_categories()
        self._rebuild_groove_list()
        self._select_user_pattern(record["name"])
        wx.MessageBox(f"Imported '{record['name']}' into category "
                      f"'{record['category']}'. It is now the current groove.",
                      "Import pattern", wx.ICON_INFORMATION)

    def export_midi(self) -> None:
        """Save the current pattern as a .mid file (GM drum channel)."""
        from ..practice.midifile import pattern_to_midi
        role_of = {ln["id"]: ln["role"] for ln in self._current_lines()}
        with wx.FileDialog(self, "Export pattern as MIDI",
                           wildcard="MIDI file (*.mid)|*.mid",
                           defaultFile=f"{self._pattern.name}.mid",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            path.write_bytes(pattern_to_midi(flatten_polymeter(self._pattern),
                                             self.bpm, role_of))
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not export:\n{exc}", "Export MIDI", wx.ICON_ERROR)
            return
        self._announce(f"Exported MIDI to {path.name}")

    def import_midi(self) -> None:
        """Read a .mid file's drum notes into the current groove."""
        from ..practice.midifile import midi_to_pattern
        with wx.FileDialog(self, "Import MIDI file",
                           wildcard="MIDI files (*.mid;*.midi)|*.mid;*.midi",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = Path(dlg.GetPath())
        try:
            pattern, info = midi_to_pattern(path.read_bytes())
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not import {path.name}:\n{exc}", "Import MIDI",
                          wx.ICON_ERROR)
            return
        notes = [f"{info['notes']} notes", f"{pattern.meter_label()}",
                 f"{pattern.bars} bar(s)"]
        if info.get("no_drum_channel"):
            notes.append("no drum channel found, so all notes were mapped")
        if info.get("dropped"):
            notes.append(f"{info['dropped']} notes beyond 4 bars were dropped")
        summary = f"Imported {path.name}: " + ", ".join(notes)
        # Straight into the editor — hear it (Play), tweak it, then Save to make it
        # the current groove or Save as Preset to keep it. No extra tab-hopping.
        speech.speak(summary + ". Opening the Pattern Editor.")
        self._announce(summary)
        self.open_editor(pattern=pattern)

    def _select_user_pattern(self, name: str) -> None:
        for i, (kind, ref) in enumerate(self._groove_entries):
            if kind == "user" and ref.get("name") == name:
                self.groove_choice.SetSelection(i)
                self._on_groove(None)
                return

    def open_library(self) -> None:
        """The pattern/category manager (Tools > Drum Pattern Library)."""
        dlg = DrumLibraryDialog(self, self._settings, self._dark())
        dlg.ShowModal()
        dlg.Destroy()
        self._rebuild_categories()
        self._rebuild_groove_list()


class DrumLibraryDialog(wx.Dialog):
    """Manage saved drum patterns and their categories.

    A list of your patterns ("name — category") with Rename, Change Category,
    Delete, and Rename Category.  Built-in grooves and their genre families are
    fixed and don't appear here.
    """

    def __init__(self, parent: wx.Window, settings, dark: bool = True):
        super().__init__(parent, title="Drum Pattern Library",
                         size=(520, 460), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._settings = settings
        self._dark = dark

        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=(
            "Your saved drum patterns. Rename or delete a pattern, move it to another "
            "category, or rename a whole category. Built-in grooves are not listed — "
            "they are permanent."))
        intro.Wrap(480)
        root.Add(intro, 0, wx.ALL, 10)

        self.pattern_list = wx.ListBox(self, choices=[], style=wx.LB_SINGLE)
        set_accessible_name(self.pattern_list, "Saved patterns")
        root.Add(self.pattern_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        btns = wx.WrapSizer(wx.HORIZONTAL)
        for label, handler in (("&Rename...", self._on_rename),
                               ("Change &Category...", self._on_change_category),
                               ("&Delete", self._on_delete),
                               ("Rename Ca&tegory...", self._on_rename_category)):
            b = wx.Button(self, label=label)
            b.Bind(wx.EVT_BUTTON, handler)
            btns.Add(b, 0, wx.RIGHT | wx.BOTTOM, 6)
        root.Add(btns, 0, wx.ALL, 10)
        root.Add(self.CreateButtonSizer(wx.CLOSE), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)

        self.SetSizer(root)
        theme.apply(self, dark)
        self._reload()
        wx.CallAfter(self.pattern_list.SetFocus)

    def _reload(self) -> None:
        keep = max(0, self.pattern_list.GetSelection())
        self._records = user_patterns(self._settings)
        self.pattern_list.Set(
            [f"{r['name']}  —  {r.get('category', 'My patterns')}" for r in self._records])
        if self._records:
            self.pattern_list.SetSelection(min(keep, len(self._records) - 1))

    def _current(self) -> dict | None:
        sel = self.pattern_list.GetSelection()
        return self._records[sel] if 0 <= sel < len(self._records) else None

    def _on_rename(self, event) -> None:
        rec = self._current()
        if rec is None:
            return
        with wx.TextEntryDialog(self, "New name:", "Rename pattern", rec["name"]) as dlg:
            theme.apply(dlg, self._dark)
            if dlg.ShowModal() != wx.ID_OK:
                return
            new = dlg.GetValue().strip()
        if not new or new == rec["name"]:
            return
        if not rename_pattern(self._settings, rec["name"], new):
            wx.MessageBox(f"A pattern named '{new}' already exists.",
                          "Rename pattern", wx.ICON_INFORMATION)
            return
        self._reload()
        speech.speak(f"Renamed to {new}")

    def _on_change_category(self, event) -> None:
        rec = self._current()
        if rec is None:
            return
        cats = all_categories(self._settings) + ["New category..."]
        dlg = wx.SingleChoiceDialog(self, f"Category for '{rec['name']}':",
                                    "Change category", cats)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        category = cats[dlg.GetSelection()]
        dlg.Destroy()
        if category == "New category...":
            with wx.TextEntryDialog(self, "New category name:", "Change category") as dlg2:
                theme.apply(dlg2, self._dark)
                if dlg2.ShowModal() != wx.ID_OK:
                    return
                category = dlg2.GetValue().strip() or "My patterns"
        set_pattern_category(self._settings, rec["name"], category)
        self._reload()
        speech.speak(f"{rec['name']} moved to {category}")

    def _on_delete(self, event) -> None:
        rec = self._current()
        if rec is None:
            return
        if wx.MessageBox(f"Delete the pattern '{rec['name']}'? This cannot be undone.",
                         "Delete pattern", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        delete_pattern(self._settings, rec["name"])
        self._reload()
        speech.speak(f"Deleted {rec['name']}")

    def _on_rename_category(self, event) -> None:
        user_cats = sorted({r.get("category", "My patterns") for r in self._records})
        if not user_cats:
            wx.MessageBox("No saved patterns yet, so there are no categories to rename.",
                          "Rename category", wx.ICON_INFORMATION)
            return
        dlg = wx.SingleChoiceDialog(self, "Which category?", "Rename category", user_cats)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        old = user_cats[dlg.GetSelection()]
        dlg.Destroy()
        with wx.TextEntryDialog(self, f"New name for '{old}':", "Rename category",
                                old) as dlg2:
            theme.apply(dlg2, self._dark)
            if dlg2.ShowModal() != wx.ID_OK:
                return
            new = dlg2.GetValue().strip()
        if not new or new == old:
            return
        count = rename_category(self._settings, old, new)
        self._reload()
        speech.speak(f"Renamed {old} to {new} on {count} pattern(s)")
