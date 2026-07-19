"""Sequin — the accessible step sequencer: a customizable, screen-reader-first drum machine.

Sequin is the drum sequencer that ships inside FreedomHawk and is designed to spin out as
its own standalone project (the ``practice`` engine is deliberately UI-free for that).

The main tab stays lean: kit, groove (500 built in), fill cadence and style, tempo,
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

import shutil
from pathlib import Path
from typing import Callable

import wx

from .. import config
from ..practice import (
    CORE_ROLES,
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
from ..practice.drums import (
    ORNAMENTS,
    RATE,
    ROLE_FOLDER,
    _auto_hat_choke,
    _buf_to_wav,
    fill_span,
    load_sample,
    render_count_in,
    render_song,
    render_song_buffer,
    section_seconds,
    song_seconds,
    split_kit_choice,
    tempo_ramp,
)
from ..practice.patternstore import (
    MAX_CHOKE_GROUP,
    MAX_GAIN_DB,
    MAX_LINES,
    MAX_TUNE,
    MIN_GAIN_DB,
    all_categories,
    build_line_kit,
    builtin_category,
    choke_map,
    clamp_choke,
    clamp_gain_db,
    clamp_tune,
    delete_pattern,
    delete_song,
    line_pitch,
    lines_for_kit,
    inline_record_from_pattern,
    make_line,
    make_record,
    make_song_record,
    normalize_section,
    split_section_repeat,
    record_from_file_dict,
    record_to_file_dict,
    record_to_pattern,
    rename_category,
    rename_pattern,
    resolve_pattern_by_name,
    resolve_section_pattern,
    save_song,
    save_user_pattern,
    set_pattern_category,
    user_patterns,
    user_songs,
)
from ..practice.pitch import estimate_pitch, note_name_for_semitones
from ..practice.patternstore import SYNTH_KIT_NAME
from ..practice.songgrid import SongGrid
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
_ALL_CATEGORIES = "All categories"


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


class _VisualTrack(wx.ScrolledWindow):
    """A large, high-contrast visual mirror of the pattern grid, for low-vision use.

    **Display-only.** It never takes focus and is not in the tab order — the ListBox
    stays the operable, screen-reader surface (per the project's accessibility rule that
    nothing you *operate* is custom-painted). This just paints what the grid already holds,
    with big cells and strong colour/intensity contrast so a low-vision user can see the
    beat at a glance. Others who rely more on sight than the primary user benefit too.
    """

    CELL = 30           # step-cell width (large, for low vision)
    ROW_H = 34
    GUTTER = 110        # left column holding each line's name

    BG = wx.Colour(0x10, 0x10, 0x10)
    EMPTY = wx.Colour(0x30, 0x30, 0x30)
    BEAT = wx.Colour(0x60, 0x60, 0x60)
    BAR = wx.Colour(0xB0, 0xB0, 0xB0)
    HIT = wx.Colour(0x22, 0xC8, 0xFF)       # bright cyan — a normal hit
    ACCENT = wx.Colour(0xFF, 0xD4, 0x00)    # bright yellow — accent (loudest)
    GHOST = wx.Colour(0x0E, 0x63, 0x86)     # dim cyan — ghost (quietest)
    CURSOR = wx.Colour(0xFF, 0x3B, 0x30)    # red outline — the cursor
    ROW_HL = wx.Colour(0x20, 0x3A, 0x48)    # current line's row background
    TEXT = wx.Colour(0xFF, 0xFF, 0xFF)
    MUTED = wx.Colour(0x70, 0x70, 0x70)

    def __init__(self, parent: wx.Window, editor: "PatternEditorDialog"):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self._editor = editor
        self.SetScrollRate(15, 15)
        self.SetBackgroundColour(self.BG)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)   # for AutoBufferedPaintDC
        self.Bind(wx.EVT_PAINT, self._on_paint)

    # Keep it out of keyboard focus / tab order — it is a visual aid, not a control.
    def AcceptsFocus(self) -> bool:
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:
        return False

    def refresh_view(self) -> None:
        if not self.IsShown():
            return
        p = self._editor.pattern
        steps = max(1, p.steps)
        self.SetVirtualSize(self.GUTTER + steps * self.CELL + 4,
                            max(1, len(self._editor.lines)) * self.ROW_H + 4)
        self.Refresh()

    def _cell_colour(self, on: bool, level, silenced: bool) -> wx.Colour:
        if not on:
            return self.EMPTY
        if silenced:
            return self.MUTED
        if level == LEVEL_ACCENT:
            return self.ACCENT
        if level == LEVEL_GHOST:
            return self.GHOST
        return self.HIT

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        self._paint(dc)

    def _paint(self, dc: wx.DC) -> None:
        dc.SetBackground(wx.Brush(self.BG))
        dc.Clear()
        ed = self._editor
        p = ed.pattern
        steps = max(1, p.steps)
        spb = max(1, p.steps_per_beat)
        per_bar = max(1, p.steps // max(1, p.bars))
        sel = ed.grid_list.GetSelection()
        cursor = ed._cursor
        dc.SetFont(wx.Font(wx.FontInfo(11).Bold()))
        grid_right = self.GUTTER + steps * self.CELL

        for r, line in enumerate(ed.lines):
            y = r * self.ROW_H + 2
            lid = line["id"]
            silenced = lid in ed.silenced
            if r == sel:                                  # highlight the current line's row
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.SetBrush(wx.Brush(self.ROW_HL))
                dc.DrawRectangle(0, y - 2, grid_right, self.ROW_H)

            dc.SetTextForeground(self.MUTED if silenced else self.TEXT)
            dc.DrawText(str(line.get("label", lid))[:14], 6, y + (self.ROW_H - 18) // 2)

            hits = set(p.hits.get(lid, []))
            levels = p.levels.get(lid, {})
            chances = p.probs.get(lid, {})
            orns = p.ornaments.get(lid, {})
            line_len = p.line_length(lid)
            for s in range(steps):
                x = self.GUTTER + s * self.CELL
                on = s in hits and s < line_len
                dc.SetPen(wx.Pen(self.BG))
                colour = self._cell_colour(on, levels.get(s), silenced)
                if on and s in chances:
                    # A chance step is drawn half-filled — literally a "maybe".
                    dc.SetBrush(wx.Brush(self.EMPTY))
                    dc.DrawRectangle(x + 1, y + 1, self.CELL - 2, self.ROW_H - 6)
                    half = max(3, (self.ROW_H - 6) // 2)
                    dc.SetBrush(wx.Brush(colour))
                    dc.DrawRectangle(x + 1, y + 1 + (self.ROW_H - 6 - half),
                                     self.CELL - 2, half)
                else:
                    dc.SetBrush(wx.Brush(colour))
                    dc.DrawRectangle(x + 1, y + 1, self.CELL - 2, self.ROW_H - 6)
                if on and s in orns:
                    # An ornamented hit gets a grace tick hugging its left edge.
                    dc.SetBrush(wx.Brush(self.TEXT))
                    dc.DrawRectangle(x + 1, y + 1, 3, self.ROW_H - 6)
                if s % per_bar == 0:                      # bar / beat separators
                    dc.SetPen(wx.Pen(self.BAR, 2))
                    dc.DrawLine(x, y - 2, x, y + self.ROW_H - 2)
                elif s % spb == 0:
                    dc.SetPen(wx.Pen(self.BEAT, 1))
                    dc.DrawLine(x, y, x, y + self.ROW_H - 4)

            if r == sel and 0 <= cursor < steps:          # the time cursor
                cx = self.GUTTER + cursor * self.CELL
                dc.SetPen(wx.Pen(self.CURSOR, 3))
                dc.SetBrush(wx.TRANSPARENT_BRUSH)
                dc.DrawRectangle(cx, y, self.CELL, self.ROW_H - 4)


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
                 bpm: int, dark: bool = True, settings=None, base_kit=None):
        super().__init__(parent, title="Pattern Editor",
                         size=(660, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.pattern = pattern
        self.lines = [dict(ln) for ln in lines]
        self.silenced: set[str] = set(silenced or ())
        self._kits_dir = Path(kits_dir)
        self._settings = settings
        self._player = player
        self._bpm = bpm
        self._base_kit = base_kit  # the globally selected kit (follow-global lines use it)
        self._dark = dark
        self._auditioning = False
        self._cursor = 0
        self._mark_start = None   # ; and ' set a fill span across all lines
        self._mark_end = None
        self._fill_complexity = 50
        self._fill_spill = False
        self._undo: list = []   # (what, snapshot) pairs; Ctrl+Z / Ctrl+Y
        self._redo: list = []
        self._preview = _PreviewPlayer()
        self._pitch_cache: dict = {}   # (id, kit, sample) -> estimated base Pitch
        self._line_kit = build_line_kit(self.lines, self._kits_dir, base_kit=self._base_kit)

        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=(
            "One line per part; add lines to stack drums or mix libraries. Up/Down "
            "move between lines; Left/Right move by step, Ctrl by beat, Ctrl+Shift "
            "by bar; Space toggles a hit; Enter picks the line's sample (or None); "
            "Left/Right brackets tune the line (Shift for an octave); "
            "comma and period set its volume; C sets a choke group; number keys set "
            "a hit's chance (0 = always); F cycles flam, drag, roll; "
            "Ctrl+Z / Ctrl+Y undo and redo; R reads the line's rhythm; S plays "
            "the cursor step across lines; "
            "Delete removes a line; P previews; F1 speaks the keys."))
        intro.Wrap(620)
        root.Add(intro, 0, wx.ALL, 10)

        self.grid_list = wx.ListBox(self, choices=[], style=wx.LB_SINGLE)
        set_accessible_name(self.grid_list, "Pattern grid")
        root.Add(self.grid_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Optional high-contrast visual mirror of the grid (display-only; low-vision aid).
        # The preference persists — a low-vision user who wants it will want it every time.
        show_visual = bool(settings.get("show_visual_track")) if settings is not None else False
        self.visual_cb = wx.CheckBox(self, label="Show &visual track (high-contrast grid)")
        self.visual_cb.SetValue(show_visual)
        self.visual_cb.Bind(wx.EVT_CHECKBOX, self._on_toggle_visual)
        root.Add(self.visual_cb, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.visual_track = _VisualTrack(self, self)
        self.visual_track.SetMinSize((-1, 200))
        self.visual_track.Show(show_visual)
        root.Add(self.visual_track, 0, wx.EXPAND | wx.ALL, 10)

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

        # Feel — saved WITH this groove (a shuffle keeps its shuffle). Swing delays the
        # off-beats; humanize adds subtle timing/level drift so the loop isn't stamped out.
        feel = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        self.swing_label = wx.StaticText(self, label="Swing: 0% (straight)")
        feel.Add(self.swing_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.swing_slider = wx.Slider(self, value=int(round(self.pattern.swing * 100)),
                                      minValue=0, maxValue=100)
        set_accessible_name(self.swing_slider, "Swing",
                            value_fn=lambda: f"{self.swing_slider.GetValue()} percent")
        self.swing_slider.Bind(wx.EVT_SLIDER, self._on_feel)
        feel.Add(self.swing_slider, 0, wx.EXPAND)
        self.humanize_label = wx.StaticText(self, label="Humanize: 0%")
        feel.Add(self.humanize_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.humanize_slider = wx.Slider(self, value=int(round(self.pattern.humanize * 100)),
                                         minValue=0, maxValue=100)
        set_accessible_name(self.humanize_slider, "Humanize",
                            value_fn=lambda: f"{self.humanize_slider.GetValue()} percent")
        self.humanize_slider.Bind(wx.EVT_SLIDER, self._on_feel)
        feel.Add(self.humanize_slider, 0, wx.EXPAND)
        feel.AddGrowableCol(1, 1)
        root.Add(feel, 0, wx.EXPAND | wx.ALL, 10)

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
        self._sync_feel_labels()
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
        extras = []
        nch = len(self.pattern.probs.get(line["id"], {}))
        if nch:
            extras.append(f"{nch} by chance")
        norn = len(self.pattern.ornaments.get(line["id"], {}))
        if norn:
            extras.append(f"{norn} ornamented")
        if extras:
            hits += f" ({', '.join(extras)})"
        length = self.pattern.line_length(line["id"])
        poly = f", length {length} steps" if length != self.pattern.steps else ""
        tune = clamp_tune(line.get("tune"))
        note = self._tuned_note(line) if tune else None
        tuned = f", tuned {tune:+d}{f' to {note}' if note else ''}" if tune else ""
        gain = clamp_gain_db(line.get("gain_db"))
        vol = f", volume {gain:+d} dB" if gain else ""
        ch = clamp_choke(line.get("choke"))
        choke = f", choke group {ch}" if ch else ""
        return f"{line['label']}: {hits}{poly}{tuned}{vol}{choke}, sample {self._sample_desc(line)}"

    def _rebuild_rows(self) -> None:
        keep = max(0, self.grid_list.GetSelection())
        self.grid_list.Set([self._row_label(ln) for ln in self.lines])
        if self.lines:
            self.grid_list.SetSelection(min(keep, len(self.lines) - 1))
        self._refresh_visual()

    def _refresh_row(self, line: dict) -> None:
        for i, ln in enumerate(self.lines):
            if ln is line:
                self.grid_list.SetString(i, self._row_label(line))
                break
        self._refresh_visual()

    def _refresh_visual(self) -> None:
        """Repaint the visual track if it's showing (a no-op otherwise)."""
        track = getattr(self, "visual_track", None)
        if track is not None:
            track.refresh_view()

    def _on_toggle_visual(self, event: wx.CommandEvent) -> None:
        show = self.visual_cb.GetValue()
        self.visual_track.Show(show)
        self.visual_track.refresh_view()
        self.Layout()
        if self._settings is not None:
            self._settings.set("show_visual_track", show)
        speech.speak("Visual track shown." if show else "Visual track hidden.")

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
        self._refresh_visual()

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
        self._refresh_visual()

    _LENGTHEN_KEYS = frozenset({ord("="), ord("+"), wx.WXK_NUMPAD_ADD})
    _SHORTEN_KEYS = frozenset({ord("-"), ord("_"), wx.WXK_NUMPAD_SUBTRACT})
    _TUNE_DOWN_KEYS = frozenset({ord("["), ord("{")})   # Shift for a whole octave
    _TUNE_UP_KEYS = frozenset({ord("]"), ord("}")})
    _QUIETER_KEYS = frozenset({ord(","), ord("<")})     # Shift for a bigger step
    _LOUDER_KEYS = frozenset({ord("."), ord(">")})
    _CHOKE_KEYS = frozenset({ord("C"), ord("c")})       # cycle this line's choke group
    _CHANCE_KEYS = frozenset(range(ord("0"), ord("9") + 1)) | frozenset(
        range(wx.WXK_NUMPAD0, wx.WXK_NUMPAD9 + 1))      # 1-9 = 10-90% chance, 0 = always
    _ORNAMENT_KEYS = frozenset({ord("F"), ord("f")})    # cycle flam / drag / roll
    _RHYTHM_KEYS = frozenset({ord("R"), ord("r")})      # speak this line's rhythm
    _STEP_AUDITION_KEYS = frozenset({ord("S"), ord("s")})  # hear/name the cursor step
    _MARK_START_KEYS = frozenset({ord(";"), ord(":")})  # start of a fill span (all lines)
    _MARK_END_KEYS = frozenset({ord("'"), ord('"')})    # end of a fill span
    _FILL_KEYS = frozenset({ord("L"), ord("l")})        # drop an improvised fill
    _GRID_KEYS = frozenset({wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT,
                            wx.WXK_HOME, wx.WXK_END, wx.WXK_SPACE, wx.WXK_RETURN,
                            wx.WXK_NUMPAD_ENTER, wx.WXK_F1, wx.WXK_DELETE,
                            ord("P"), ord("p")}) | _LENGTHEN_KEYS | _SHORTEN_KEYS \
        | _TUNE_DOWN_KEYS | _TUNE_UP_KEYS | _QUIETER_KEYS | _LOUDER_KEYS | _CHOKE_KEYS \
        | _CHANCE_KEYS | _ORNAMENT_KEYS | _RHYTHM_KEYS | _STEP_AUDITION_KEYS \
        | _MARK_START_KEYS | _MARK_END_KEYS | _FILL_KEYS

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        # Alt+P plays/pauses the audition WITHOUT moving focus off the grid (the
        # audio starting or stopping is the feedback).
        if event.AltDown() and event.GetKeyCode() in (ord("P"), ord("p")):
            self._on_play(None)
            return
        # Undo/redo work dialog-wide (no text controls here to want Ctrl+Z natively).
        if event.ControlDown() and event.GetKeyCode() in (ord("Z"), ord("z")):
            self._redo_last() if event.ShiftDown() else self._undo_last()
            return
        if event.ControlDown() and event.GetKeyCode() in (ord("Y"), ord("y")):
            self._redo_last()
            return
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
        elif code in self._TUNE_DOWN_KEYS:
            self._change_tune(-12 if shift else -1)
        elif code in self._TUNE_UP_KEYS:
            self._change_tune(12 if shift else 1)
        elif code in self._QUIETER_KEYS:
            self._change_gain(-6 if shift else -1)
        elif code in self._LOUDER_KEYS:
            self._change_gain(6 if shift else 1)
        elif code in self._CHOKE_KEYS and not ctrl:   # plain C; leave Ctrl+C alone
            self._cycle_choke()
        elif code in self._CHANCE_KEYS and not ctrl:
            digit = code - (ord("0") if ord("0") <= code <= ord("9") else wx.WXK_NUMPAD0)
            self._set_chance(digit * 10)
        elif code in self._ORNAMENT_KEYS and not ctrl:
            self._cycle_ornament()
        elif code in self._RHYTHM_KEYS and not ctrl:
            self._speak_rhythm()
        elif code in self._STEP_AUDITION_KEYS and not ctrl:
            self._audition_step()
        elif code in self._MARK_START_KEYS:
            self._set_fill_mark("start")
        elif code in self._MARK_END_KEYS:
            self._set_fill_mark("end")
        elif code in self._FILL_KEYS and not ctrl:
            self._do_fill()
        elif code in (ord("P"), ord("p")):
            self._preview_line()
        elif code == wx.WXK_F1:
            speech.speak(
                "Up and Down move between lines. Left and Right move by step. "
                "Control Left and Right move by beat. Control Shift Left and Right "
                "move by bar. Home and End jump to the start and end. Space cycles "
                "a step: on, accent, ghost, off. Minus and Plus set this line's "
                "length for polymeter, so lines can loop in different lengths and "
                "phase against each other. Left and Right square brackets tune this "
                "line down and up a semitone; hold Shift for a whole octave, and P "
                "speaks the note it plays. Comma and period trim this line's volume "
                "in decibels, Shift for a bigger step, to balance the mix. C cycles "
                "this line's choke group: lines in the same group cut each other off, "
                "so put an open hat and a closed hat in one group and the closed hat "
                "chokes the open one. Number keys set a hit's chance: one through "
                "nine is ten to ninety percent, zero makes it always play — a chance "
                "hit rolls fresh on every pass, so the loop varies itself. "
                "F cycles a hit's ornament: flam, one soft grace stroke before it; "
                "drag, two; roll, the stroke rebounds across its step; then back to "
                "plain. Control Z undoes the last edit, up to one hundred steps; "
                "Control Y or Control Shift Z redoes. "
                "R reads this line's whole rhythm as beat positions. "
                "S names and plays everything landing on the cursor step, across "
                "all lines. Semicolon and apostrophe mark the start and end of a span "
                "across all lines, and L drops an improvised fill across it — or the "
                "whole pattern if nothing is marked — asking how busy the fill is and "
                "whether it may spill past the end. Alt P plays and pauses without "
                "leaving the grid. "
                "Enter picks this line's sample or None. "
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
        self._push_undo("length change")
        new_len = max(1, min(POLY_MAX_LINE, self._line_len() + delta))
        self.pattern.set_line_length(line["id"], new_len)
        self._cursor = min(self._cursor, new_len - 1)
        self._refresh_row(line)
        synced = " (synced with the pattern)" if new_len == self.pattern.steps else ""
        speech.speak(f"{line['label']} length {new_len} steps{synced}")
        self._reaudition()

    def _base_pitch(self, line: dict):
        """The estimated pitch of a line's source sample (before tuning), cached."""
        key = (line["id"], line.get("kit"), line.get("sample"))
        if key not in self._pitch_cache:
            self._pitch_cache[key] = line_pitch(line, self._kits_dir, self._base_kit)
        return self._pitch_cache[key]

    def _tuned_note(self, line: dict) -> str | None:
        """The note this line sounds at now (base pitch shifted by its tuning)."""
        p = self._base_pitch(line)
        if p is None or not p.pitched:
            return None
        return note_name_for_semitones(p.freq_hz, clamp_tune(line.get("tune")))

    def _change_tune(self, delta: int) -> None:
        """Tune the current line up or down in semitones (Shift = a whole octave)."""
        line = self._current_line()
        if line is None:
            return
        cur = clamp_tune(line.get("tune"))
        new = max(-MAX_TUNE, min(MAX_TUNE, cur + delta))
        if new != cur:
            self._push_undo("tuning change")
        line["tune"] = new
        self._rebuild_line_kit()
        self._refresh_row(line)
        if new == cur:
            speech.speak(f"{line['label']} tuning at its {'top' if delta > 0 else 'bottom'} limit")
        else:
            amount = "no change" if new == 0 else \
                f"{new:+d} semitone{'s' if abs(new) != 1 else ''}"
            note = self._tuned_note(line)
            speech.speak(f"{line['label']} tuned {amount}{f', {note}' if note else ''}")
        self._reaudition()

    def _change_gain(self, delta: int) -> None:
        """Trim the current line's volume in decibels (Shift = a 6 dB step)."""
        line = self._current_line()
        if line is None:
            return
        cur = clamp_gain_db(line.get("gain_db"))
        new = max(MIN_GAIN_DB, min(MAX_GAIN_DB, cur + delta))
        if new != cur:
            self._push_undo("volume change")
        line["gain_db"] = new
        self._rebuild_line_kit()
        self._refresh_row(line)
        if new == cur:
            speech.speak(f"{line['label']} volume at its {'top' if delta > 0 else 'bottom'} limit")
        else:
            level = "unity" if new == 0 else f"{new:+d} dB"
            speech.speak(f"{line['label']} volume {level}")
        self._reaudition()

    def _cycle_choke(self) -> None:
        """Cycle the current line's choke group (0=none .. MAX). Lines in the same
        group cut each other's ring — an open hat closed off by the closed hat."""
        line = self._current_line()
        if line is None:
            return
        cur = clamp_choke(line.get("choke"))
        new = 0 if cur >= MAX_CHOKE_GROUP else cur + 1
        self._push_undo("choke change")
        line["choke"] = new
        self._refresh_row(line)
        if new == 0:
            speech.speak(f"{line['label']} no choke group")
        else:
            others = [ln["label"] for ln in self.lines
                      if ln is not line and clamp_choke(ln.get("choke")) == new]
            who = f", choking with {', '.join(others)}" if others else ", alone so far"
            speech.speak(f"{line['label']} choke group {new}{who}")
        self._reaudition()

    def _toggle_hit(self) -> None:
        """Space cycles a step's state: off -> on -> accent -> ghost -> off."""
        line = self._current_line()
        if line is None:
            return
        self._push_undo("step change")
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
                self.pattern.set_chance(line_id, self._cursor, None)
                self.pattern.set_ornament(line_id, self._cursor, None)
                spoken = "off"
        if steps:
            self.pattern.hits[line_id] = sorted(steps)
        else:
            self.pattern.hits.pop(line_id, None)
        self._refresh_row(line)
        speech.speak(f"{line['label']} {spoken}, {step_label(self.pattern, self._cursor)}")
        self._reaudition()

    def _set_chance(self, percent: int) -> None:
        """Number keys set the cursor hit's play chance: 1-9 = 10-90 percent, 0 =
        always.  A "sometimes" hit rolls fresh on every pass, so the loop breathes."""
        line = self._current_line()
        if line is None:
            return
        line_id = line["id"]
        if self._cursor not in self.pattern.hits.get(line_id, []):
            speech.speak("No hit at this step. Space places one first.")
            return
        self._push_undo("chance change")
        self.pattern.set_chance(line_id, self._cursor, percent or None)
        self._refresh_row(line)
        what = f"{percent} percent chance" if percent else "always plays"
        speech.speak(f"{line['label']} {what}, {step_label(self.pattern, self._cursor)}")
        self._reaudition()

    def _cycle_ornament(self) -> None:
        """F cycles the cursor hit's ornament: plain -> flam -> drag -> roll -> plain.
        A flam adds one soft grace stroke just before the hit, a drag two (a ruff),
        and a roll rebounds the stroke across its step (a ratchet)."""
        line = self._current_line()
        if line is None:
            return
        line_id = line["id"]
        if self._cursor not in self.pattern.hits.get(line_id, []):
            speech.speak("No hit at this step. Space places one first.")
            return
        self._push_undo("ornament change")
        order = [None] + list(ORNAMENTS)
        cur = self.pattern.ornament_of(line_id, self._cursor)
        new = order[(order.index(cur) + 1) % len(order)]
        self.pattern.set_ornament(line_id, self._cursor, new)
        self._refresh_row(line)
        speech.speak(f"{line['label']} {new or 'plain stroke'}, "
                     f"{step_label(self.pattern, self._cursor)}")
        self._reaudition()

    def _state_at(self, line_id: str, step: int) -> str:
        if step not in self.pattern.hits.get(line_id, []):
            return "empty"
        state = self.pattern.level_of(line_id, step) or "hit"
        orn = self.pattern.ornament_of(line_id, step)
        if orn:
            state += f", {orn}"
        chance = self.pattern.chance_of(line_id, step)
        return f"{state}, {chance} percent chance" if chance else state

    # -- fill span (; and ' mark it, L drops a fill) ---------------------------

    def _set_fill_mark(self, which: str) -> None:
        """; and ' set the start / end of a fill span (a step range across all lines)."""
        if which == "start":
            self._mark_start = self._cursor
        else:
            self._mark_end = self._cursor
        speech.speak(f"{'Start' if which == 'start' else 'End'} marker at "
                     f"{step_label(self.pattern, self._cursor)}.")

    def _do_fill(self) -> None:
        """L drops an improvised fill across the marked span (or the whole pattern),
        after asking for complexity and whether it may spill past the end.  Undoable."""
        dlg = _FillOptionsDialog(self, self._fill_complexity, self._fill_spill, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            speech.speak("Fill cancelled.")
            return
        self._fill_complexity, self._fill_spill = dlg.values()
        dlg.Destroy()
        if self._mark_start is not None and self._mark_end is not None:
            lo, hi = sorted((self._mark_start, self._mark_end))
            start, end, where = lo, min(self.pattern.steps, hi + 1), "the marked span"
        else:
            start, end, where = 0, self.pattern.steps, "the pattern"
        self._push_undo("fill")
        fill_span(self.pattern, start, end, self._fill_complexity / 100.0, self._fill_spill)
        # A fill can bring in parts (toms, crash) that have no line yet — give each one a
        # line so its hits are visible and survive Save (make_record only writes lines).
        # If the line limit is already reached, drop those hits rather than orphan them
        # (they'd play but vanish on Save), and say how many were left out.
        have = {ln["id"] for ln in self.lines}
        dropped = 0
        for role in list(self.pattern.hits):
            if role in have:
                continue
            if role in ROLES and len(self.lines) < MAX_LINES:
                self.lines.append(make_line(role, existing=self.lines))
                have.add(role)
            else:
                self.pattern.hits.pop(role, None)
                for store in (self.pattern.levels, self.pattern.probs, self.pattern.ornaments):
                    store.pop(role, None)
                dropped += 1
        self._rebuild_line_kit()
        self._mark_start = self._mark_end = None
        self._rebuild_rows()
        spill = "spilling past the end" if self._fill_spill else "resolving on the bar"
        limit = (f" {dropped} part{'s' if dropped != 1 else ''} left out; line limit reached."
                 if dropped else "")
        speech.speak(f"Fill dropped across {where}, complexity {self._fill_complexity} "
                     f"percent, {spill}.{limit}")
        self._reaudition()

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
        self._push_undo("add line")
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
        self._push_undo("remove line")
        self.lines.remove(line)
        self.pattern.hits.pop(line["id"], None)
        self.pattern.levels.pop(line["id"], None)
        self.pattern.lengths.pop(line["id"], None)
        self.pattern.probs.pop(line["id"], None)      # or a later line reusing this
        self.pattern.ornaments.pop(line["id"], None)  # id would inherit stale state
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
            self._push_undo("sample change")
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

    def _speak_rhythm(self) -> None:
        """R: read the current line's rhythm as musical positions, so you can learn a
        groove by ear-and-description without arrowing across every step."""
        line = self._current_line()
        if line is None:
            return
        length = self.pattern.line_length(line["id"])
        steps = [s for s in self.pattern.hits.get(line["id"], []) if s < length]
        if not steps:
            speech.speak(f"{line['label']}: no hits")
            return
        cap = 24                                     # keep dense lines listenable
        spoken = "; ".join(step_label(self.pattern, s) for s in steps[:cap])
        more = f"; and {len(steps) - cap} more" if len(steps) > cap else ""
        n = len(steps)
        speech.speak(f"{line['label']}, {n} hit{'s' if n != 1 else ''}: {spoken}{more}")

    def _audition_step(self) -> None:
        """S: name and play everything that lands on the cursor step, across all
        lines — one vertical slice of the groove, in your ears and in words."""
        here, voices = [], []
        for ln in self.lines:
            lid = ln["id"]
            if lid in self.silenced or self._cursor >= self.pattern.line_length(lid):
                continue
            if self._cursor in self.pattern.hits.get(lid, []):
                desc = ln["label"]
                level = self.pattern.level_of(lid, self._cursor)
                if level:
                    desc += f" {level}"
                orn = self.pattern.ornament_of(lid, self._cursor)
                if orn:
                    desc += f" {orn}"
                chance = self.pattern.chance_of(lid, self._cursor)
                if chance:
                    desc += f" {chance} percent"
                here.append(desc)
                v = self._line_kit.voice(lid)
                if v is not None and len(v):
                    voices.append(v)
        where = step_label(self.pattern, self._cursor)
        if not here:
            speech.speak(f"{where}: nothing")
            return
        if voices and NUMPY_AVAILABLE:
            import numpy as np
            mix = np.zeros(max(len(v) for v in voices), dtype=np.float32)
            for v in voices:
                mix[: len(v)] += v
            peak = float(np.max(np.abs(mix)))
            if peak > 1.0:
                mix = mix / peak
            if self._auditioning:
                self._stop_audition()                # the preview needs the channel
            self._preview.play_voice(mix)
        speech.speak(f"{where}: {', '.join(here)}")

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
            note = self._tuned_note(line)
            speech.speak(f"{line['label']}{f', {note}' if note else ''}")
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
        self._push_undo("load groove")
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
        self._sync_feel_controls()  # the loaded groove carries its own saved feel
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
        p = self.pattern
        if (beats, unit, grid, bars) != (p.beats_per_bar, p.beat_unit,
                                         p.steps_per_beat, p.bars):
            self._push_undo("meter change")
        grid_changed = grid != self.pattern.steps_per_beat
        was_poly = self.pattern.is_polymetric()
        self.pattern = retime_pattern(self.pattern, beats, unit, grid, bars)
        self._cursor = min(self._cursor, self._line_len() - 1)
        self._rebuild_rows()
        # Always speak the WHOLE resulting state — meter, grid, bars — after any change.
        # The grid is a subdivision, not the time signature, so changing it leaves the
        # meter alone; a blind user must still hear the meter reaffirmed every time, or
        # an unchanged "4/4" reads as if the pattern were stuck there.
        grid_name = next((label for label, g in GRID_CHOICES
                          if g == self.pattern.steps_per_beat), "custom").lower()
        bars_txt = f"{self.pattern.bars} bar{'s' if self.pattern.bars != 1 else ''}"
        state = f"{self.pattern.meter_label()}, {grid_name} grid, {bars_txt}"
        note = " Per-line lengths reset." if (was_poly and grid_changed) else ""
        if grid_changed:
            speech.speak(f"{state}. Hits re-quantized to the new grid.{note}")
        else:
            speech.speak(f"{state}.")
        self._reaudition()

    def _effective_pattern(self) -> Pattern:
        p = self.pattern
        return Pattern(p.name, p.steps, p.steps_per_beat,
                       {r: s for r, s in p.hits.items() if r not in self.silenced},
                       p.beats_per_bar, p.beat_unit, p.bars,
                       {r: dict(m) for r, m in p.levels.items() if r not in self.silenced},
                       {r: L for r, L in p.lengths.items() if r not in self.silenced},
                       p.swing, p.humanize,
                       {r: dict(m) for r, m in p.probs.items() if r not in self.silenced},
                       {r: dict(m) for r, m in p.ornaments.items()
                        if r not in self.silenced})

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
        # Audition the pattern you're editing, with its own FEEL (the swing + humanize
        # sliders below, saved with the groove), but not the arrangement (Fill every /
        # Improvised) — those multiply the loop over many bars, which belongs on the main
        # tab, not while editing a 1-4 bar pattern.  render_loop reads the pattern's feel.
        effective = flatten_polymeter(self._effective_pattern())
        return render_loop(effective, self._line_kit, self._bpm,
                           choke_groups=choke_map(self.lines))

    def _reaudition(self) -> None:
        if self._auditioning:
            self._player.play(self._render())

    def _stop_audition(self) -> None:
        if self._auditioning:
            self._player.stop()
            self._auditioning = False
            self.play_btn.SetLabel("&Play")

    def _on_feel(self, event: wx.CommandEvent) -> None:
        # The sliders ARE the groove's saved feel; write straight into the pattern so it
        # travels with Save (and inline into a song).  NVDA speaks the value from the
        # slider's accessible name; a live audition restarts to reflect the new feel.
        self.pattern.swing = self.swing_slider.GetValue() / 100.0
        self.pattern.humanize = self.humanize_slider.GetValue() / 100.0
        self._sync_feel_labels()
        self._reaudition()

    def _sync_feel_labels(self) -> None:
        sw = self.swing_slider.GetValue()
        self.swing_label.SetLabel(f"Swing: {sw}%" + (" (straight)" if sw == 0 else ""))
        self.humanize_label.SetLabel(f"Humanize: {self.humanize_slider.GetValue()}%")

    def _sync_feel_controls(self) -> None:
        """Point the feel sliders at the current pattern's saved swing/humanize —
        needed whenever the pattern object is replaced (load groove, undo)."""
        self.swing_slider.SetValue(int(round(self.pattern.swing * 100)))
        self.humanize_slider.SetValue(int(round(self.pattern.humanize * 100)))
        self._sync_feel_labels()

    # -- undo / redo -----------------------------------------------------------

    _UNDO_DEPTH = 100

    def _snapshot(self):
        return (self.pattern.copy(), [dict(ln) for ln in self.lines], set(self.silenced))

    def _push_undo(self, what: str) -> None:
        """Call at the START of every mutation, with a spoken-friendly description."""
        self._undo.append((what, self._snapshot()))
        if len(self._undo) > self._UNDO_DEPTH:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, snap) -> None:
        self.pattern, self.lines, self.silenced = snap
        self._rebuild_line_kit()
        self._sync_meter_controls()
        self._sync_feel_controls()
        self._rebuild_rows()
        self._cursor = max(0, min(self._cursor, self._line_len() - 1))
        self._reaudition()

    def _undo_last(self) -> None:
        if not self._undo:
            speech.speak("Nothing to undo.")
            return
        what, snap = self._undo.pop()
        self._redo.append((what, self._snapshot()))
        self._restore(snap)
        speech.speak(f"Undone: {what}.")

    def _redo_last(self) -> None:
        if not self._redo:
            speech.speak("Nothing to redo.")
            return
        what, snap = self._redo.pop()
        self._undo.append((what, self._snapshot()))
        self._restore(snap)
        speech.speak(f"Redone: {what}.")

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
    """Choose which sample each drum part uses, by ear — from this kit or any other.

    Part dropdown -> From-kit dropdown -> Sample dropdown.  Arrowing through the
    samples previews each one, so you audition with the arrow keys alone.  Sourcing a
    part from a different kit builds a **hybrid kit** (this kit's kick, another's
    snare), stored with this kit's choices; a borrowed part can even fill a gap this
    kit never shipped (a kit with no 808 folder can take one from a neighbour).
    Save remembers the choices for this kit.
    """

    def __init__(self, parent: wx.Window, kit_dir: Path, choices: dict[str, str],
                 dark: bool = True):
        super().__init__(parent, title="Kit Sounds", size=(560, 400),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._home = Path(kit_dir).name
        # Sibling kits (same parent folder — exactly where the loader resolves borrowed
        # parts from), listed by role so every part can be sourced from any of them.
        self._kit_files: dict[str, dict] = {self._home: list_role_files(kit_dir)}
        parent_dir = Path(kit_dir).parent
        if parent_dir.is_dir():
            for d in sorted(p for p in parent_dir.iterdir() if p.is_dir()):
                if d.name != self._home:
                    files = list_role_files(d)
                    if files:
                        self._kit_files[d.name] = files
        all_roles = {r for files in self._kit_files.values() for r in files}
        self._roles = [r for r in ROLES if r in all_roles]
        self.choices = dict(choices)  # role -> "file.wav" | "Kit/file.wav"; read on Save
        self._sources: list[str] = []  # kit names aligned with source_choice's entries
        self._player = _PreviewPlayer()
        self._pitch_cache: dict = {}   # file path -> estimated Pitch (lazy)

        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=(
            "Pick a part, then arrow through its samples — each one plays as you land on "
            "it (lengths are shown; names are the kit maker's own). Tuned sounds speak "
            "their musical key after the name, so you can match 808s and toms. From kit "
            "sources the part from ANOTHER kit — mix kits into a hybrid, or borrow a part "
            "this kit doesn't have. Save keeps your choices for this kit; Cancel or "
            "Escape leaves it unchanged."))
        intro.Wrap(520)
        root.Add(intro, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="Part:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.part_choice = wx.Choice(self, choices=[ROLE_LABELS.get(r, r) for r in self._roles])
        set_accessible_name(self.part_choice, "Part")
        self.part_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_sources())
        grid.Add(self.part_choice, 0, wx.EXPAND)

        grid.Add(wx.StaticText(self, label="From kit:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.source_choice = wx.Choice(self)
        set_accessible_name(self.source_choice, "Kit to take this part from")
        self.source_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_samples())
        grid.Add(self.source_choice, 0, wx.EXPAND)

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
            self._load_sources()
        # Announce the dialog by focusing its primary control on open.
        wx.CallAfter(self.part_choice.SetFocus)

    # -- state ----------------------------------------------------------------

    def _current_role(self) -> str | None:
        sel = self.part_choice.GetSelection()
        return self._roles[sel] if 0 <= sel < len(self._roles) else None

    def _current_source(self) -> str | None:
        sel = self.source_choice.GetSelection()
        return self._sources[sel] if 0 <= sel < len(self._sources) else None

    def _source_files(self) -> list:
        return self._kit_files.get(self._current_source() or "", {}).get(
            self._current_role(), [])

    def _load_sources(self) -> None:
        """Rebuild the From-kit list for the current part: only kits that HAVE the part
        (no silent dead ends), this kit first, the saved choice's source selected."""
        role = self._current_role()
        self._sources = [k for k in ([self._home] + sorted(
            n for n in self._kit_files if n != self._home))
            if role in self._kit_files[k]]
        self.source_choice.Set(
            [f"This kit ({k})" if k == self._home else k for k in self._sources])
        src_kit, _name = split_kit_choice(self.choices.get(role))
        wanted = src_kit if src_kit in self._sources else (
            self._home if self._home in self._sources else
            (self._sources[0] if self._sources else None))
        if wanted is not None:
            self.source_choice.SetSelection(self._sources.index(wanted))
        self._load_samples()

    def _choice_value(self, filename: str) -> str:
        """How a pick is stored: plain for this kit, 'Kit/file.wav' when borrowed."""
        source = self._current_source()
        return filename if source == self._home else f"{source}/{filename}"

    def _load_samples(self) -> None:
        role = self._current_role()
        files = self._source_files()
        labels = []
        for f in files:
            dur = wav_duration(f)
            labels.append(f"{f.stem}  ({dur:.2f}s)" if dur else f.stem)
        self.sample_choice.Set(labels)
        src_kit, current = split_kit_choice(self.choices.get(role))
        names = [f.name for f in files]
        source = self._current_source()
        if (src_kit or self._home) == source and current in names:
            self.sample_choice.SetSelection(names.index(current))
        else:
            default = default_sample_for(role, files)
            if default is not None:
                self.sample_choice.SetSelection(names.index(default.name))

    def _on_sample(self, event: wx.CommandEvent) -> None:
        role = self._current_role()
        files = self._source_files()
        i = self.sample_choice.GetSelection()
        if role is None or not (0 <= i < len(files)):
            return
        self.choices[role] = self._choice_value(files[i].name)
        self._preview()

    def _preview(self) -> None:
        """Play the selected sample once, and speak its musical key if it has one."""
        role = self._current_role()
        files = self._source_files()
        i = self.sample_choice.GetSelection()
        if not NUMPY_AVAILABLE or role is None or not (0 <= i < len(files)):
            return
        try:
            voice = load_sample(files[i])
        except Exception:  # noqa: BLE001 - preview is best-effort
            return
        self._player.play_voice(voice)
        note = self._sample_note(files[i], voice, role)
        if note:                        # follow (not interrupt) the sample name NVDA read
            speech.speak(note, interrupt=False)

    def _sample_note(self, path, voice, role: str) -> str | None:
        """The sample's detected note, cached; None when it isn't clearly pitched."""
        if path not in self._pitch_cache:
            self._pitch_cache[path] = estimate_pitch(voice, RATE, role=role)
        p = self._pitch_cache[path]
        return p.note if (p and p.pitched) else None

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


class KitBuilderDialog(wx.Dialog):
    """Build a new drum kit from scratch, part by part, by ear.

    Every part starts on the synth; for each one you keep the synth voice or borrow a
    sample from a kit you've imported, auditioning with the arrow keys.  Save returns the
    name and the per-part sample picks; the panel writes a real, self-contained kit folder
    (chosen samples copied in, the synth voice baked to a WAV for every untouched part) so
    it then behaves like any imported kit and every part plays.
    """

    def __init__(self, parent: wx.Window, kits_dir, existing_names, dark: bool = True):
        super().__init__(parent, title="Build Kit", size=(560, 460),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._kits_dir = Path(kits_dir)
        self._existing = {str(n).lower() for n in existing_names}
        self._kits: dict[str, dict] = {}    # kit name -> {role: [Path]}
        if self._kits_dir.is_dir():
            for d in sorted(p for p in self._kits_dir.iterdir() if p.is_dir()):
                files = list_role_files(d)
                if files:
                    self._kits[d.name] = files
        self._roles = list(ROLES)
        self.choices: dict[str, Path] = {}   # role -> chosen sample Path; absent = synth
        self.kit_name = ""                   # set on Save
        self._sources: list[str] = []
        self._player = _PreviewPlayer()
        self._synth = synth_kit() if NUMPY_AVAILABLE else None
        self._pitch_cache: dict = {}

        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=(
            "Build a kit part by part. Type a name, pick a part, then choose Synth (the "
            "built-in voice) or a kit to borrow a sample from — arrow the samples to hear "
            "each. Parts you leave on Synth keep the synth voice. Save writes a new kit "
            "folder you can play, edit in Kit Sounds, and share."))
        intro.Wrap(520)
        root.Add(intro, 0, wx.ALL, 10)

        namer = wx.BoxSizer(wx.HORIZONTAL)
        namer.Add(wx.StaticText(self, label="Kit name:"), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.name_field = wx.TextCtrl(self)
        set_accessible_name(self.name_field, "New kit name")
        namer.Add(self.name_field, 1)
        root.Add(namer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="Part:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.part_choice = wx.Choice(self, choices=[ROLE_LABELS.get(r, r) for r in self._roles])
        set_accessible_name(self.part_choice, "Part")
        self.part_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_sources())
        grid.Add(self.part_choice, 0, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Sound from:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.source_choice = wx.Choice(self)
        set_accessible_name(self.source_choice, "Sound source for this part")
        self.source_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_samples())
        grid.Add(self.source_choice, 0, wx.EXPAND)
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
        save_btn = wx.Button(self, wx.ID_OK, "&Save Kit")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        btns.Add(save_btn, 0, wx.RIGHT, 8)
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        btns.Add(cancel_btn, 0)
        root.Add(btns, 0, wx.ALL, 10)
        self.SetSizer(root)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)
        theme.apply(self, dark)
        self.part_choice.SetSelection(0)
        self._load_sources()
        wx.CallAfter(self.name_field.SetFocus)

    def _current_role(self) -> str | None:
        sel = self.part_choice.GetSelection()
        return self._roles[sel] if 0 <= sel < len(self._roles) else None

    def _current_source(self) -> str | None:
        sel = self.source_choice.GetSelection()
        return self._sources[sel] if 0 <= sel < len(self._sources) else None

    def _load_sources(self) -> None:
        """Sources for the current part: Synth first, then every kit that HAS this part."""
        role = self._current_role()
        self._sources = ["Synth"] + [k for k in sorted(self._kits)
                                     if role in self._kits[k]]
        self.source_choice.Set(["Synth (built-in)" if s == "Synth" else s
                                for s in self._sources])
        chosen, sel = self.choices.get(role), 0
        if chosen is not None:
            for i, s in enumerate(self._sources):
                if s != "Synth" and chosen in self._kits.get(s, {}).get(role, []):
                    sel = i
                    break
        self.source_choice.SetSelection(sel)
        self._load_samples()

    def _source_files(self) -> list:
        src = self._current_source()
        if not src or src == "Synth":
            return []
        return self._kits.get(src, {}).get(self._current_role(), [])

    def _load_samples(self) -> None:
        role = self._current_role()
        files = self._source_files()
        self.sample_choice.Set([f"{f.stem}  ({wav_duration(f):.2f}s)"
                                if wav_duration(f) else f.stem for f in files])
        if not files:                        # Synth source -> this part is a synth voice
            self.choices.pop(role, None)
            return
        chosen, names = self.choices.get(role), [f.name for f in files]
        if chosen is not None and chosen in files:
            self.sample_choice.SetSelection(names.index(chosen.name))
        else:
            default = default_sample_for(role, files)
            i = names.index(default.name) if default is not None else 0
            self.sample_choice.SetSelection(i)
            self.choices[role] = files[i]    # choosing a kit assigns its default sample

    def _on_sample(self, event: wx.CommandEvent) -> None:
        role, files = self._current_role(), self._source_files()
        i = self.sample_choice.GetSelection()
        if role is None or not (0 <= i < len(files)):
            return
        self.choices[role] = files[i]
        self._preview()

    def _preview(self) -> None:
        role = self._current_role()
        if role is None or not NUMPY_AVAILABLE:
            return
        files = self._source_files()
        i = self.sample_choice.GetSelection()
        if 0 <= i < len(files):
            try:
                voice = load_sample(files[i])
            except Exception:  # noqa: BLE001 - preview is best-effort
                return
            self._player.play_voice(voice)
            if path_note := self._note(files[i], voice, role):
                speech.speak(path_note, interrupt=False)
        else:                                # Synth source: play the synth voice
            v = self._synth.voice(role) if self._synth is not None else None
            if v is not None:
                self._player.play_voice(v)
                speech.speak("synth voice", interrupt=False)
            else:                            # FX has no synth voice — never leave it silent
                speech.speak("No synth voice for this part; pick a sample from a kit.")

    def _note(self, path, voice, role: str) -> str | None:
        if path not in self._pitch_cache:
            self._pitch_cache[path] = estimate_pitch(voice, RATE, role=role)
        p = self._pitch_cache[path]
        return p.note if (p and p.pitched) else None

    def _on_save(self, event: wx.CommandEvent) -> None:
        name = self.name_field.GetValue().strip()
        # Reject empties, path punctuation, and relative names (. / .. / leading dot) that
        # would escape or land on the kits directory itself.
        if (not name or set(name) & set('\\/:*?"<>|')
                or name.startswith(".") or name in (".", "..")):
            wx.MessageBox("Please give the kit a plain name with no slashes, leading dot, "
                          "or punctuation like : * ? < >.",
                          "Build Kit", wx.OK | wx.ICON_INFORMATION, self)
            self.name_field.SetFocus()
            return
        if name.lower() in self._existing or name == SYNTH_LABEL:
            wx.MessageBox(f"A kit named '{name}' already exists. Choose another name.",
                          "Build Kit", wx.OK | wx.ICON_INFORMATION, self)
            self.name_field.SetFocus()
            return
        self.kit_name = name
        self._player.dispose()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, event=None) -> None:
        self._player.dispose()
        self.EndModal(wx.ID_CANCEL)


class TempoTrainerDialog(wx.Dialog):
    """Configure the tempo trainer: how fast it climbs, and whether it stops.

    Ramp mode climbs from the current tempo to a target and holds; continuous mode
    keeps nudging the tempo up past the target until you stop.  Every change is spoken
    as the trainer runs, so the climbing speed is audible without watching the screen.
    """

    _BAR_CHOICES = [1, 2, 4, 8]

    def __init__(self, parent, cfg: dict, start_bpm: int, dark: bool = True):
        super().__init__(parent, title="Tempo Trainer", size=(460, 320),
                         style=wx.DEFAULT_DIALOG_STYLE)
        self.result = dict(cfg)
        try:
            root = wx.BoxSizer(wx.VERTICAL)
            root.Add(wx.StaticText(self, label=(
                f"Speed up as you practice, starting from the current tempo "
                f"({start_bpm} BPM). Each step is spoken as it happens.")),
                0, wx.ALL, 10)

            grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
            grid.AddGrowableCol(1, 1)

            grid.Add(wx.StaticText(self, label="Speed up by (BPM):"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.step = wx.Slider(self, value=int(cfg["step"]), minValue=1, maxValue=30)
            set_accessible_name(self.step, "Speed up by, BPM per step",
                                value_fn=lambda: f"{self.step.GetValue()} BPM")
            grid.Add(self.step, 0, wx.EXPAND)

            grid.Add(wx.StaticText(self, label="Every (bars):"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.bars = wx.Choice(self, choices=[str(n) for n in self._BAR_CHOICES])
            self.bars.SetSelection(self._BAR_CHOICES.index(cfg["bars"])
                                   if cfg["bars"] in self._BAR_CHOICES else 1)
            set_accessible_name(self.bars, "Speed up every how many bars")
            grid.Add(self.bars, 0, wx.EXPAND)

            grid.Add(wx.StaticText(self, label="Up to target (BPM):"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.target = wx.Slider(self, value=int(cfg["target"]),
                                    minValue=TEMPO_MIN, maxValue=TEMPO_MAX)
            set_accessible_name(self.target, "Target tempo, BPM",
                                value_fn=lambda: f"{self.target.GetValue()} BPM")
            grid.Add(self.target, 0, wx.EXPAND)
            root.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

            self.continuous = wx.CheckBox(
                self, label="Keep climbing past the target (endurance mode)")
            self.continuous.SetValue(bool(cfg["continuous"]))
            root.Add(self.continuous, 0, wx.ALL, 10)

            btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
            if btns:
                root.Add(btns, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
            self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
            self.SetSizer(root)
            theme.apply(self, dark)
            wx.CallAfter(self.step.SetFocus)
        except Exception as exc:  # noqa: BLE001 - a swallowed error is a dead button
            wx.MessageBox(f"Could not open Tempo Trainer:\n{exc}", "Tempo Trainer",
                          wx.OK | wx.ICON_ERROR, self)
            self.EndModal(wx.ID_CANCEL)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        self.result = {
            "step": self.step.GetValue(),
            "bars": self._BAR_CHOICES[max(0, self.bars.GetSelection())],
            "target": self.target.GetValue(),
            "continuous": self.continuous.GetValue(),
        }
        self.EndModal(wx.ID_OK)


class _SongTrack(wx.ScrolledWindow):
    """A high-contrast visual timeline of a song's sections (display-only, not focusable).

    Each section is a coloured block whose width tracks its playing time; the selected one
    is outlined.  A low-vision aid that never takes focus — the section list stays the thing
    you operate — mirroring the Pattern Editor's visual track.
    """

    H = 60
    MIN_W = 56
    PAD = 8
    PX_PER_SEC = 22
    BG = wx.Colour(0x10, 0x10, 0x10)
    TEXT = wx.Colour(0xFF, 0xFF, 0xFF)
    SEL = wx.Colour(0xFF, 0x3B, 0x30)
    PALETTE = [wx.Colour(*c) for c in (
        (0x22, 0xC8, 0xFF), (0xFF, 0xD4, 0x00), (0x5C, 0xE0, 0x8A), (0xFF, 0x8A, 0x3D),
        (0xC9, 0x8A, 0xFF), (0xFF, 0x6B, 0x9D), (0x4D, 0xD0, 0xE1), (0xB8, 0xC7, 0x4A))]

    def __init__(self, parent: wx.Window, dialog: "SongDialog"):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self._dialog = dialog
        self.SetScrollRate(15, 0)
        self.SetBackgroundColour(self.BG)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def AcceptsFocus(self) -> bool:
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:
        return False

    def refresh_view(self) -> None:
        if not self.IsShown():
            return
        total = self.PAD
        for _, secs, _ in self._dialog._section_blocks():
            total += max(self.MIN_W, int(secs * self.PX_PER_SEC)) + 4
        self.SetVirtualSize(max(total, 10), self.H + 2 * self.PAD)
        self.Refresh()

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(self.BG))
        dc.Clear()
        dc.SetFont(wx.Font(wx.FontInfo(11).Bold()))
        blocks = self._dialog._section_blocks()
        if not blocks:
            dc.SetTextForeground(self.TEXT)
            dc.DrawText("No sections yet — add grooves on the Add tab.", self.PAD, self.PAD + 18)
            return
        x, y = self.PAD, self.PAD
        for i, (label, secs, selected) in enumerate(blocks):
            w = max(self.MIN_W, int(secs * self.PX_PER_SEC))
            dc.SetBrush(wx.Brush(self.PALETTE[i % len(self.PALETTE)]))
            dc.SetPen(wx.Pen(self.SEL, 3) if selected else wx.Pen(self.BG, 1))
            dc.DrawRectangle(x, y, w, self.H)
            dc.SetTextForeground(wx.Colour(0, 0, 0))     # dark text on the bright block
            dc.SetClippingRegion(x, y, w, self.H)
            dc.DrawText(label, x + 6, y + 8)
            dc.DestroyClippingRegion()
            x += w + 4


class SongDialog(wx.Dialog):
    """Song mode — chain grooves into an arrangement and play it end to end.

    Accessible builder: a list of sections (each a groove + a repeat count), reordered and
    edited by keyboard and spoken as you go.  Play renders the whole song gapless and loops
    it; songs save, load, and export to WAV.  Sections reference grooves by name (built-in
    or your saved patterns) — save a pattern as a preset first to use it in a song.
    """

    _MAX_REPEATS = 32

    def __init__(self, parent: wx.Window, panel: "DrumsPanel", dark: bool = True):
        super().__init__(parent, title="Song Builder", size=(640, 540),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._panel = panel
        self._settings = panel._settings
        self._dark = dark
        self._sections: list[dict] = []   # [{pattern, repeats, tempo, kit, inline}, ...]
        self._kit_cache: dict = {}         # kit name -> DrumKit (loaded once per song)
        self._playing = False
        self._previewing = False           # auditioning a groove in the Add tab
        self._end_timer: wx.CallLater | None = None
        self._poly_tails = False           # let polymeter lines run past section ends
        try:
            self._build()
        except Exception as exc:  # noqa: BLE001 - a swallowed error is a dead button
            wx.MessageBox(f"Could not open Song Builder:\n{exc}", "Song Builder",
                          wx.OK | wx.ICON_ERROR, self)
            self.EndModal(wx.ID_CANCEL)
            return
        self._baseline = self._state_key()   # for the unsaved-changes close prompt
        self.Bind(wx.EVT_CLOSE, self._on_close)
        # Alt shortcuts that DON'T move focus (NVDA stays on the list you're working):
        # Alt+1/2/3 switch tabs, Alt+P plays/stops the song, Alt+V previews a groove.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_dialog_key)
        theme.apply(self, dark)
        wx.CallAfter(self.list.SetFocus)

    def _on_dialog_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if event.AltDown() and not event.ControlDown():
            if ord("1") <= code <= ord("9"):
                page = code - ord("1")
                if page < self.notebook.GetPageCount():
                    self._goto_tab(page)
                    return
            if code in (ord("P"), ord("p")):
                self._on_play(None)          # speaks Playing/Stopped; focus unmoved
                return
            if code in (ord("V"), ord("v")):
                self._preview_groove()       # speaks Previewing/stopped; focus unmoved
                return
        event.Skip()

    def _goto_tab(self, page: int) -> None:
        """Jump to a tab and land focus on its main control, the tab name spoken."""
        self.notebook.SetSelection(page)
        target = [self.list, self.groove, self.songs_list][min(page, 2)]
        wx.CallAfter(target.SetFocus)
        speech.speak(f"{self.notebook.GetPageText(page)} tab.")

    def _groove_categories(self) -> tuple[list[str], dict]:
        """All groove names (built-in + saved) and a name -> category map."""
        names = [p.name for p in PATTERN_LIBRARY]
        cats = {p.name: builtin_category(p.name) for p in PATTERN_LIBRARY}
        for r in user_patterns(self._settings):
            names.append(r["name"])
            cats[r["name"]] = r.get("category") or "My patterns"
        return names, cats

    def _rebuild_grooves(self) -> None:
        """Repopulate the groove dropdown, filtered by the chosen category."""
        names, cats = self._groove_categories()
        chosen = self.category.GetStringSelection()
        if chosen and chosen != _ALL_CATEGORIES:
            names = [n for n in names if cats.get(n) == chosen]
        self.groove.Set(names)
        if names:
            self.groove.SetSelection(0)

    def _build(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(self)

        # --- Arrange: the section list + the visual timeline ---
        arrange = wx.Panel(self.notebook)
        av = wx.BoxSizer(wx.VERTICAL)
        av.Add(wx.StaticText(arrange, label=(
            "Up/Down select a section; Left/Right change its repeats (Left takes one "
            "away; Shift for HALF a loop); Alt+Up/Alt+Down reorder; Delete removes; "
            "E edits it. M marks a section for a group edit: with the cursor ON a marked "
            "section, the Tempo, Kit, Swing and Fills controls below change every marked "
            "section at once; on an unmarked section they change just that one. They "
            "apply as the song plays. Alt+1, Alt+2, Alt+3 switch tabs; Alt+P plays or "
            "stops from anywhere.")),
            0, wx.ALL, 8)
        self.list = wx.ListBox(arrange, choices=[], style=wx.LB_SINGLE)
        set_accessible_name(self.list, "Song sections")
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        self.list.Bind(wx.EVT_LISTBOX, lambda e: (self._refresh_visual(), self._sync_section_props()))
        av.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)

        # Per-section properties for the selected section: edit its groove, its own tempo,
        # its own kit. Blank/"song"/"global" mean "follow the song's tempo / the global kit".
        props = wx.BoxSizer(wx.HORIZONTAL)
        self.edit_btn = wx.Button(arrange, label="&Edit Section...")
        self.edit_btn.Bind(wx.EVT_BUTTON, lambda e: self._edit_section())
        props.Add(self.edit_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        props.Add(wx.StaticText(arrange, label="Tempo:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.sec_tempo = wx.Choice(
            arrange, choices=["Song tempo"] + [str(t) for t in range(TEMPO_MIN, TEMPO_MAX + 1, 5)])
        set_accessible_name(self.sec_tempo, "This section's tempo")
        self.sec_tempo.Bind(wx.EVT_CHOICE, self._on_section_tempo)
        props.Add(self.sec_tempo, 0, wx.RIGHT, 8)
        props.Add(wx.StaticText(arrange, label="Kit:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.sec_kit = wx.Choice(arrange, choices=["Global kit"] + self._panel._kit_choices())
        set_accessible_name(self.sec_kit, "This section's kit")
        self.sec_kit.Bind(wx.EVT_CHOICE, self._on_section_kit)
        props.Add(self.sec_kit, 0)
        av.Add(props, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # On-the-fly feel and fills for the selected section — trial a swung chorus or
        # improvised fills while the song plays, no Edit Section round-trip needed.
        props2 = wx.BoxSizer(wx.HORIZONTAL)
        props2.Add(wx.StaticText(arrange, label="Swing:"), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.sec_swing = wx.Choice(
            arrange, choices=["Groove's own"] + [f"{v}%" for v in range(0, 101, 10)])
        set_accessible_name(self.sec_swing, "This section's swing")
        self.sec_swing.Bind(wx.EVT_CHOICE, self._on_section_swing)
        props2.Add(self.sec_swing, 0, wx.RIGHT, 8)
        props2.Add(wx.StaticText(arrange, label="Fills:"), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.sec_fill = wx.Choice(arrange, choices=["As written", "Improvised"])
        set_accessible_name(self.sec_fill, "This section's fill style")
        self.sec_fill.Bind(wx.EVT_CHOICE, self._on_section_fill)
        props2.Add(self.sec_fill, 0, wx.RIGHT, 8)
        props2.Add(wx.StaticText(arrange, label="Fill amount:"), 0,
                   wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.sec_fill_amt = wx.Choice(
            arrange, choices=["Default"] + [f"{v}%" for v in (25, 50, 75, 100)])
        set_accessible_name(self.sec_fill_amt,
                            "This section's fill amount, longer busier fills")
        self.sec_fill_amt.Bind(wx.EVT_CHOICE, self._on_section_fill_amount)
        props2.Add(self.sec_fill_amt, 0)
        av.Add(props2, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Song-wide: by default an odd-length (polymetric) line is cut off at its
        # section's end so the next section starts on its own count; this lets it
        # run over instead (the old behavior, for deliberately loose composing).
        self.poly_tails = wx.CheckBox(
            arrange, label="Polymeter lines push past section ends")
        self.poly_tails.Bind(wx.EVT_CHECKBOX, self._on_poly_tails)
        av.Add(self.poly_tails, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.song_track = _SongTrack(arrange, self)
        self.song_track.SetMinSize((-1, 92))
        av.Add(self.song_track, 0, wx.EXPAND | wx.ALL, 8)
        arrange.SetSizer(av)
        self.notebook.AddPage(arrange, "Arrange")

        # --- Add: category filter, groove, repeats ---
        addp = wx.Panel(self.notebook)
        ap = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(addp, label="Category:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.category = wx.Choice(addp, choices=[_ALL_CATEGORIES] + all_categories(self._settings))
        set_accessible_name(self.category, "Filter grooves by category")
        self.category.SetSelection(0)
        self.category.Bind(wx.EVT_CHOICE, lambda e: self._rebuild_grooves())
        grid.Add(self.category, 0, wx.EXPAND)
        grid.Add(wx.StaticText(addp, label="Groove:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.groove = wx.Choice(addp, choices=[])
        set_accessible_name(self.groove, "Groove to add")
        grid.Add(self.groove, 0, wx.EXPAND)
        grid.Add(wx.StaticText(addp, label="Repeats:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.repeats = wx.Choice(addp, choices=[str(n) for n in range(1, 17)])
        set_accessible_name(self.repeats, "Repeats for the added groove")
        self.repeats.SetSelection(0)
        grid.Add(self.repeats, 0)
        # Starting swing/fills for the new section (editable later on Arrange).
        grid.Add(wx.StaticText(addp, label="Swing:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.add_swing = wx.Choice(
            addp, choices=["Groove's own"] + [f"{v}%" for v in range(0, 101, 10)])
        set_accessible_name(self.add_swing, "Swing for the added section")
        self.add_swing.SetSelection(0)
        grid.Add(self.add_swing, 0)
        grid.Add(wx.StaticText(addp, label="Fills:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.add_fill = wx.Choice(addp, choices=["As written", "Improvised"])
        set_accessible_name(self.add_fill, "Fill style for the added section")
        self.add_fill.SetSelection(0)
        grid.Add(self.add_fill, 0)
        # Where the new section lands: the end by default, or before any existing
        # section (rebuilt as the song changes; "Before 1" is the start of the song).
        grid.Add(wx.StaticText(addp, label="Insert at:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.add_pos = wx.Choice(addp, choices=["End of song"])
        set_accessible_name(self.add_pos, "Where in the song to insert the new section")
        self.add_pos.SetSelection(0)
        grid.Add(self.add_pos, 0, wx.EXPAND)
        ap.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        add_row = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(addp, label="&Add Section")
        add_btn.Bind(wx.EVT_BUTTON, lambda e: self._add())
        add_row.Add(add_btn, 0, wx.RIGHT, 8)
        self.preview_btn = wx.Button(addp, label="Pre&view Groove")
        self.preview_btn.Bind(wx.EVT_BUTTON, lambda e: self._preview_groove())
        add_row.Add(self.preview_btn, 0)
        ap.Add(add_row, 0, wx.ALL, 10)
        addp.SetSizer(ap)
        self.notebook.AddPage(addp, "Add")
        self._rebuild_grooves()

        # --- My Songs: browse saved songs; save the current one; export ---
        songs = wx.Panel(self.notebook)
        sp = wx.BoxSizer(wx.VERTICAL)
        sp.Add(wx.StaticText(songs, label=(
            "Your saved songs. Select one, then Load it into Arrange, Play it, or Delete it. "
            "Save the current arrangement, or export it as audio, below.")), 0, wx.ALL, 8)
        self.songs_list = wx.ListBox(songs, choices=[], style=wx.LB_SINGLE)
        set_accessible_name(self.songs_list, "Saved songs")
        self.songs_list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._load_selected())
        sp.Add(self.songs_list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, fn in (("&Load into Arrange", self._load_selected),
                          ("Pla&y", self._play_selected), ("De&lete", self._delete_selected)):
            b = wx.Button(songs, label=label)
            b.Bind(wx.EVT_BUTTON, lambda e, f=fn: f())
            row.Add(b, 0, wx.RIGHT, 6)
        sp.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        row2 = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(songs, label="&Save Current Song...")
        save_btn.Bind(wx.EVT_BUTTON, lambda e: self._save())
        row2.Add(save_btn, 0, wx.RIGHT, 6)
        export_btn = wx.Button(songs, label="Export as &WAV...")
        export_btn.Bind(wx.EVT_BUTTON, lambda e: self._export())
        row2.Add(export_btn, 0)
        sp.Add(row2, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        songs.SetSizer(sp)
        self.notebook.AddPage(songs, "My Songs")
        self._rebuild_songs()

        root.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)

        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(self, label="&Play")
        self.play_btn.Bind(wx.EVT_BUTTON, self._on_play)
        bottom.Add(self.play_btn, 0, wx.RIGHT, 8)
        beat_btn = wx.Button(self, label="&Beat Editor...")
        beat_btn.Bind(wx.EVT_BUTTON, lambda e: self._open_beat_editor())
        bottom.Add(beat_btn, 0, wx.RIGHT, 8)
        cancel = wx.Button(self, wx.ID_CANCEL, "Close")
        cancel.Bind(wx.EVT_BUTTON, lambda e: self._on_close(e))
        bottom.Add(cancel, 0)
        root.Add(bottom, 0, wx.ALL, 8)
        self.SetSizer(root)
        self._rebuild()

    # -- section list ---------------------------------------------------------

    def _record(self) -> dict:
        return {"sections": [dict(s) for s in self._sections]}

    def _resolve_kit(self, name: str | None):
        """The DrumKit a section plays: None -> the globally selected kit; else load it."""
        if not name:
            return self._panel._kit
        if name not in self._kit_cache:
            if name == SYNTH_LABEL:
                self._kit_cache[name] = synth_kit()
            else:
                try:
                    self._kit_cache[name] = load_kit_from_folder(
                        self._panel._kits_dir() / name,
                        choices=self._panel._saved_choices(name))
                except Exception:  # noqa: BLE001 - missing/unreadable -> fall back
                    self._kit_cache[name] = self._panel._kit
        return self._kit_cache[name]

    def _resolve_one(self, s: dict):
        """One section resolved to (Pattern, repeats, bpm) with tempo/swing/fill overrides
        applied — or None if its groove is missing.  Shared by render and the timeline so
        the drawn block length always matches the audio (an improvised-fill section renders
        as one nominal-length pattern, not its polymetric LCM)."""
        pattern = resolve_section_pattern(s, self._settings)
        if pattern is None:
            return None
        bpm = s.get("tempo") or self._panel.bpm
        reps = max(0.5, float(s["repeats"]))
        if s.get("swing") is not None:          # override the groove's own saved feel
            pattern = pattern.copy()
            pattern.swing = s["swing"] / 100.0
        if s.get("fill") == "improv":
            # Each repeat becomes a cycle ending in a freshly generated fill; the section
            # renders as one long pattern (same total length as the repeats).  Fills need
            # whole cycles, so half repeats round here.
            pattern = improvised_loop(
                pattern, max(1, pattern.bars), max(1, int(round(reps))),
                fill_amount=(s.get("fill_amount") or 0) / 100.0)
            reps = 1
        return pattern, reps, bpm

    def _resolved(self) -> list:
        """[(Pattern, repeats, bpm, kit)] for render — per-section tempo, kit, swing
        and fill overrides applied."""
        out = []
        for s in self._sections:
            r = self._resolve_one(s)
            if r is not None:
                out.append((*r, self._resolve_kit(s.get("kit"))))
        return out

    @staticmethod
    def _fmt(secs: float) -> str:
        m, s = divmod(int(round(secs)), 60)
        return f"{m}:{s:02d}" if m else f"{s} seconds"

    def _song_len(self) -> float:
        return song_seconds(self._resolved(), contain_polymeter=not self._poly_tails)

    def _section_label(self, s: dict) -> str:
        base = (s.get("pattern") or "pattern") + (" (edited)" if s.get("inline") else "")
        extra = []
        if s.get("tempo"):
            extra.append(f"{s['tempo']} BPM")
        if s.get("kit"):
            extra.append(s["kit"])
        if s.get("swing") is not None:
            extra.append(f"swing {s['swing']}%")
        if s.get("fill"):
            amt = s.get("fill_amount")
            extra.append("improvised fills" + (f" {amt}%" if amt is not None else ""))
        return f"{base} x{s['repeats']}" + (", " + ", ".join(extra) if extra else "")

    def _section_blocks(self) -> list:
        """(label, seconds, selected) per section, aligned to the list — for the timeline."""
        sel = self.list.GetSelection()
        blocks = []
        for i, s in enumerate(self._sections):
            r = self._resolve_one(s)              # same resolution the audio uses
            secs = (section_seconds(r[0], r[1], r[2], not self._poly_tails)
                    if r is not None else 0.0)
            label = (s.get("pattern") or "pattern") + (" (edit)" if s.get("inline") else "")
            blocks.append((f"{label} x{s['repeats']}", secs, i == sel))
        return blocks

    def _refresh_visual(self) -> None:
        track = getattr(self, "song_track", None)
        if track is not None:
            track.refresh_view()

    def _row_label(self, i: int, s: dict) -> str:
        """A section's list row.  A marked section (for a bulk edit) carries a spoken,
        visible ' — marked' so NVDA announces the mark as you arrow and low vision can
        see it; the transient '_sel' flag never persists (dropped by normalize_section,
        ignored by _state_key), so marking sections is not an unsaved change."""
        mark = "  ✓ marked" if s.get("_sel") else ""
        return f"{i + 1}. {self._section_label(s)}{mark}"

    def _rebuild(self) -> None:
        keep = max(0, self.list.GetSelection())
        self.list.Set([self._row_label(i, s) for i, s in enumerate(self._sections)])
        if self._sections:
            self.list.SetSelection(min(keep, len(self._sections) - 1))
        # The Add tab's insert positions track the arrangement; back to the
        # predictable default so a stale "Before N" never surprises a later add.
        self.add_pos.Set(["End of song"] + [
            f"Before {i + 1}: {s.get('pattern') or 'section'}"
            for i, s in enumerate(self._sections)])
        self.add_pos.SetSelection(0)
        self._refresh_visual()
        self._sync_section_props()

    def _selected(self) -> int:
        i = self.list.GetSelection()
        return i if 0 <= i < len(self._sections) else -1

    def _select(self, i: int) -> None:
        """Move the list highlight to *i* and keep the property row and timeline in
        sync.  A programmatic SetSelection fires no EVT_LISTBOX, so without this the
        Tempo/Kit/Swing/Fill controls would keep announcing the previously-selected
        section's values while edits landed on the newly-highlighted one."""
        self.list.SetSelection(i)
        self._sync_section_props()
        self._refresh_visual()

    def _toggle_mark(self) -> None:
        """M marks/unmarks the current section for a bulk edit, spoken with the running
        count so a blind user always knows the selection.  The cursor stays put."""
        i = self._selected()
        if i < 0:
            return
        s = self._sections[i]
        on = not s.get("_sel")
        s["_sel"] = on
        self.list.SetString(i, self._row_label(i, s))   # refresh just this row's mark
        self.list.SetSelection(i)                        # SetString can drop selection
        n = self._marked_count()
        tail = (" No sections marked; edits apply to the current one."
                if n == 0 else
                f" {n} section{'s' if n != 1 else ''} marked.")
        speech.speak(f"{s.get('pattern', 'section')} {'marked' if on else 'unmarked'}.{tail}")

    def _marked_count(self) -> int:
        return sum(1 for s in self._sections if s.get("_sel"))

    def _targets(self) -> list:
        """Sections a property change affects.

        The edit ALWAYS includes the section under the cursor (what the property row is
        showing), so it can never land silently on a section you're not on: a bulk edit
        happens only when the cursor is itself on a marked section — then it reaches every
        marked section. On an unmarked section, marks elsewhere are ignored and only the
        cursor section changes. (This is why a stray leftover mark can't misdirect an
        edit made from somewhere else.)"""
        i = self._selected()
        if i < 0:
            return []
        cursor = self._sections[i]
        marked = [s for s in self._sections if s.get("_sel")]
        if cursor.get("_sel") and len(marked) > 1:
            return marked
        return [cursor]

    def _apply_to_targets(self, field: str, value, one_msg: str, many_verb: str) -> None:
        """Set *field* to *value* on every target section, keep the cursor and its
        property row put, restart playback if live, and speak the scope (one section vs
        'N sections') so the reach of a bulk edit is never silent."""
        targets = self._targets()
        if not targets:
            return
        for s in targets:
            s[field] = value
        i = self._selected()
        self._rebuild()
        if i >= 0:
            self.list.SetSelection(i)
        n = len(targets)
        speech.speak(one_msg if n == 1 else f"{n} sections {many_verb}.")
        self._reaudition()

    def _add(self) -> None:
        i = self.groove.GetSelection()
        if i < 0:
            return
        name = self.groove.GetString(i)
        r = self.repeats.GetSelection() + 1
        self._stop_preview()             # done auditioning; it's a section now
        sw_sel = self.add_swing.GetSelection()
        pos = self.add_pos.GetSelection()      # 0 = end; n = before section n
        at = len(self._sections) if pos <= 0 else min(pos - 1, len(self._sections))
        self._sections.insert(at, normalize_section({
            "pattern": name, "repeats": r,
            "swing": None if sw_sel <= 0 else (sw_sel - 1) * 10,
            "fill": "improv" if self.add_fill.GetSelection() == 1 else None,
        }))
        self._rebuild()
        self._select(at)
        speech.speak(f"Added {name} at position {at + 1} of {len(self._sections)}, "
                     f"{r} repeat{'s' if r != 1 else ''}. "
                     f"{self._fmt(self._song_len())} total.")
        self._reaudition()

    @staticmethod
    def _say_reps(r) -> str:
        whole, half = int(r), float(r) != int(r)
        if half:
            return f"{whole} and a half repeats" if whole else "half a repeat"
        return f"{whole} repeat{'s' if whole != 1 else ''}"

    def _change_repeats(self, delta: float) -> None:
        """Left/Right change the selected section's repeats by one; with Shift, by
        HALF a loop — extend a verse by just half. (Improvised-fill sections play
        whole cycles, so halves round when they render.)"""
        i = self._selected()
        if i < 0:
            return
        s = self._sections[i]
        r = max(0.5, min(self._MAX_REPEATS, float(s["repeats"]) + delta))
        s["repeats"] = int(r) if r == int(r) else r
        self._rebuild()
        self.list.SetSelection(i)
        speech.speak(f"{s.get('pattern', 'section')}, {self._say_reps(s['repeats'])}")
        self._reaudition()

    def _move(self, delta: int) -> None:
        i = self._selected()
        j = i + delta
        if i < 0 or not (0 <= j < len(self._sections)):
            return
        self._sections[i], self._sections[j] = self._sections[j], self._sections[i]
        self._rebuild()
        self._select(j)
        speech.speak(f"{self._sections[j].get('pattern', 'section')} moved to "
                     f"position {j + 1} of {len(self._sections)}")
        self._reaudition()

    def _remove(self) -> None:
        i = self._selected()
        if i < 0:
            return
        name = self._sections.pop(i).get("pattern", "section")
        self._rebuild()
        if self._sections:
            self.list.SetSelection(min(i, len(self._sections) - 1))
        speech.speak(f"Removed {name}. {len(self._sections)} left.")
        self._reaudition()

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_LEFT:
            self._change_repeats(-0.5 if event.ShiftDown() else -1)
        elif code == wx.WXK_RIGHT:
            self._change_repeats(0.5 if event.ShiftDown() else 1)
        elif code == wx.WXK_UP and event.AltDown():
            self._move(-1)
        elif code == wx.WXK_DOWN and event.AltDown():
            self._move(1)
        elif code == wx.WXK_DELETE:
            self._remove()
        elif code in (ord("E"), ord("e")):
            self._edit_section()
        elif code in (ord("M"), ord("m")):
            self._toggle_mark()
        else:
            event.Skip()

    # -- per-section properties (tempo / kit / inline edit) -------------------

    def _sync_section_props(self) -> None:
        """Reflect the selected section's tempo/kit/swing/fills in the property controls."""
        i = self._selected()
        s = self._sections[i] if i >= 0 else None
        for ctl in (self.edit_btn, self.sec_tempo, self.sec_kit,
                    self.sec_swing, self.sec_fill, self.sec_fill_amt):
            ctl.Enable(s is not None)
        if s is None:
            for ctl in (self.sec_tempo, self.sec_kit, self.sec_swing,
                        self.sec_fill, self.sec_fill_amt):
                ctl.SetSelection(0)
            return
        tempo = s.get("tempo")
        idx = self.sec_tempo.FindString(str(tempo)) if tempo else 0
        self.sec_tempo.SetSelection(idx if idx != wx.NOT_FOUND else 0)
        kit = s.get("kit")
        idx = self.sec_kit.FindString(kit) if kit else 0
        self.sec_kit.SetSelection(idx if idx != wx.NOT_FOUND else 0)
        swing = s.get("swing")
        self.sec_swing.SetSelection(0 if swing is None else 1 + swing // 10)
        self.sec_fill.SetSelection(1 if s.get("fill") == "improv" else 0)
        amt = s.get("fill_amount")
        idx = self.sec_fill_amt.FindString(f"{amt}%") if amt is not None else 0
        self.sec_fill_amt.SetSelection(idx if idx != wx.NOT_FOUND else 0)

    def _on_section_tempo(self, event: wx.CommandEvent) -> None:
        sel = self.sec_tempo.GetStringSelection()
        val = None if sel == "Song tempo" else int(sel)
        one = f"Section tempo {val} BPM." if val else "Section follows the song tempo."
        self._apply_to_targets("tempo", val, one,
                               f"set to {val} BPM" if val else "follow the song tempo")

    def _on_section_kit(self, event: wx.CommandEvent) -> None:
        sel = self.sec_kit.GetStringSelection()
        val = None if sel == "Global kit" else sel
        self._apply_to_targets("kit", val, f"Section kit: {sel}.", f"set to kit {sel}")

    def _on_section_swing(self, event: wx.CommandEvent) -> None:
        sel = self.sec_swing.GetSelection()
        val = None if sel <= 0 else (sel - 1) * 10
        one = ("Section uses its groove's own swing." if val is None
               else f"Section swing {val} percent.")
        self._apply_to_targets("swing", val, one,
                               "use their groove's own swing" if val is None
                               else f"set to swing {val} percent")

    def _on_section_fill(self, event: wx.CommandEvent) -> None:
        improv = self.sec_fill.GetSelection() == 1
        val = "improv" if improv else None
        one = ("Section fills improvised: each repeat ends in a fresh fill."
               if improv else "Section plays as written.")
        self._apply_to_targets("fill", val, one,
                               "set to improvised fills" if improv else "play as written")

    def _on_section_fill_amount(self, event: wx.CommandEvent) -> None:
        sel = self.sec_fill_amt.GetStringSelection()
        val = None if sel == "Default" else int(sel.rstrip("%"))
        one = "Fill amount default." if val is None else f"Fill amount {val} percent."
        self._apply_to_targets("fill_amount", val, one,
                               "set to default fill amount" if val is None
                               else f"set to fill amount {val} percent")

    def _on_poly_tails(self, event) -> None:
        """Song-wide toggle: contained polymeter (default) vs let-lines-run-over."""
        self._poly_tails = self.poly_tails.GetValue()
        self._refresh_visual()
        speech.speak(
            "Polymeter lines now push past section ends: each repeat runs the full "
            "realignment loop." if self._poly_tails else
            "Polymeter lines now cut off at section ends; the next section starts "
            "on its own count.")
        self._reaudition()

    def _edit_section(self) -> None:
        """Open the Pattern Editor on the selected section; store the tweak inline."""
        i = self._selected()
        if i < 0:
            speech.speak("Select a section to edit.")
            return
        s = self._sections[i]
        pattern = resolve_section_pattern(s, self._settings)
        if pattern is None:
            speech.speak("This section's groove is missing.")
            return
        kit = self._resolve_kit(s.get("kit"))
        lines = lines_for_kit(pattern, kit, None)
        was_playing = self._playing
        self._stop()
        dlg = PatternEditorDialog(self._panel, pattern.copy(), lines, self._panel._kits_dir(),
                                  set(), self._panel.player, int(s.get("tempo") or self._panel.bpm),
                                  dark=self._dark, settings=self._settings, base_kit=kit)
        if dlg.ShowModal() == wx.ID_OK:
            s["inline"] = make_record(
                "section", "Song", dlg.pattern.beats_per_bar, dlg.pattern.beat_unit,
                dlg.pattern.steps_per_beat, dlg.pattern.bars, dlg.lines, dlg.pattern)
            self._rebuild()
            self.list.SetSelection(i)
            speech.speak(f"{s.get('pattern', 'section')} edited.")
        dlg.Destroy()
        if was_playing:
            self._start_playback(announce=False)

    def _open_beat_editor(self) -> None:
        """Open the song-wide beat editor on the whole arrangement; adopt its edits."""
        if not self._sections:
            speech.speak("Add a section first.")
            return
        was_playing = self._playing
        self._stop()
        dlg = SongBeatEditorDialog(self._panel, self._panel, self._sections, dark=self._dark)
        ok = dlg.ShowModal() == wx.ID_OK and dlg.result_sections is not None
        result = dlg.result_sections
        dlg.Destroy()
        if ok:
            self._sections = [normalize_section(s) for s in result]
            self._rebuild()
            speech.speak(f"Beat editor changes applied. {len(self._sections)} sections, "
                         f"{self._fmt(self._song_len())}.")
            self._reaudition()
        elif was_playing:
            self._start_playback(announce=False)

    # -- playback & files -----------------------------------------------------

    def _render(self):
        resolved = self._resolved()   # (pattern, repeats, bpm, kit) per section
        if not resolved:
            return None
        # Each section carries its own feel (its groove's saved swing/humanize), so
        # render_song reads them per section — no song-wide feel override here.
        return render_song(resolved,
                           volume=self._panel.volume_slider.GetValue() / 100.0,
                           contain_polymeter=not self._poly_tails)

    def _start_playback(self, announce: bool) -> None:
        wav = self._render()
        if wav is None:
            speech.speak("Add a section first.")
            return
        self._stop_preview()             # a song takes over the shared audio channel
        self._panel.stop()               # stop the main loop; the audio channel is shared
        self._panel.player.play(wav, loop=False)   # a song plays through once and ends
        self._playing = True
        self.play_btn.SetLabel("&Stop")
        length = self._song_len()
        if self._end_timer is not None:
            self._end_timer.Stop()
        self._end_timer = wx.CallLater(int(length * 1000) + 300, self._song_ended)
        if announce:
            speech.speak(f"Playing song, {self._fmt(length)}.")

    def _on_play(self, event) -> None:
        if self._playing:
            self._stop()
            speech.speak("Stopped.")
            return
        self._start_playback(announce=True)

    def _song_ended(self) -> None:
        self._end_timer = None
        if self._playing:
            self._playing = False
            self.play_btn.SetLabel("&Play")
            speech.speak("Song finished.")

    def _stop(self) -> None:
        self._stop_preview()
        if self._end_timer is not None:
            self._end_timer.Stop()
            self._end_timer = None
        if self._playing:
            self._panel.player.stop()
            self._playing = False
            self.play_btn.SetLabel("&Play")

    def _reaudition(self) -> None:
        if self._playing:                # a live edit while playing: restart from the top
            self._start_playback(announce=False)

    def _preview_groove(self) -> None:
        """Audition the groove selected in the Add tab — looping — so you can hear it
        before committing it as a section.  Toggles: press again (or Add Section) to stop."""
        if self._previewing:
            self._stop_preview()
            speech.speak("Preview stopped.")
            return
        i = self.groove.GetSelection()
        if i < 0:
            speech.speak("Pick a groove to preview.")
            return
        name = self.groove.GetString(i)
        pattern = resolve_pattern_by_name(name, self._settings)
        if pattern is None:
            speech.speak("That groove is missing.")
            return
        kit = self._panel._kit
        if kit is None or not self._panel.player.available:
            speech.speak("Audio isn't available on this system.")
            return
        self._stop()                     # the audio channel is shared with the song
        self._panel.stop()               # and with the main tab's loop
        wav = render_loop(pattern, kit, self._panel.bpm,
                          volume=self._panel.volume_slider.GetValue() / 100.0,
                          choke_groups=_auto_hat_choke(pattern))
        self._panel.player.play(wav, loop=True)
        self._previewing = True
        self.preview_btn.SetLabel("Stop Pre&view")
        speech.speak(f"Previewing {name}. Add Section keeps it.")

    def _stop_preview(self) -> None:
        if self._previewing:
            self._panel.player.stop()
            self._previewing = False
            self.preview_btn.SetLabel("Pre&view Groove")

    def _state_key(self) -> str:
        """The current arrangement as a comparable snapshot (for unsaved-changes checks).
        Transient UI-only keys (the "_sel" bulk-edit checkmarks) are excluded — checking
        sections to edit them together is not a change to the song."""
        clean = [{k: v for k, v in s.items() if not k.startswith("_")}
                 for s in self._sections]
        return repr((clean, self._poly_tails))

    def _unsaved(self) -> bool:
        return bool(self._sections) and self._state_key() != self._baseline

    def _poly_note(self) -> str:
        """A spoken clause naming the polymeter mode when it's the non-default (so a
        load that flips it isn't silent) — empty when containment is on (the default)."""
        return " Polymeter lines push past section ends." if self._poly_tails else ""

    def _confirm_discard(self, what: str) -> bool:
        """True when it's OK to drop the current arrangement (asks only if unsaved).

        Stops playback first so the drum mix doesn't talk over NVDA reading the prompt,
        and defaults to the SAFE answer (No, keep my song) so a reflexive Enter can't
        discard unsaved work.
        """
        if not self._unsaved():
            return True
        self._stop()
        return wx.MessageBox(
            f"Your current song has unsaved changes. {what}",
            "Song Builder", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) == wx.YES

    def _save(self) -> None:
        if not self._sections:
            speech.speak("Nothing to save yet.")
            return
        with wx.TextEntryDialog(self, "Save song as:", "Save Song") as dlg:
            theme.apply(dlg, self._dark)
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.GetValue().strip()
        if not name:
            return
        save_song(self._settings,
                  make_song_record(name, self._sections, self._poly_tails))
        self._baseline = self._state_key()
        self._rebuild_songs()
        speech.speak(f"Saved song {name}.")

    # -- the My Songs list ----------------------------------------------------

    def _rebuild_songs(self) -> None:
        keep = self.songs_list.GetSelection()
        songs = user_songs(self._settings)
        self.songs_list.Set([s.get("name", "?") for s in songs])
        if songs:
            self.songs_list.SetSelection(min(max(0, keep), len(songs) - 1))

    def _selected_song(self) -> dict | None:
        songs = user_songs(self._settings)
        i = self.songs_list.GetSelection()
        return songs[i] if 0 <= i < len(songs) else None

    def _adopt_record(self, rec: dict) -> None:
        """Make *rec* the current arrangement (sections + song-wide settings)."""
        self._sections = [normalize_section(s) for s in rec.get("sections", [])]
        self._poly_tails = bool(rec.get("poly_tails"))
        self.poly_tails.SetValue(self._poly_tails)
        self._rebuild()
        self._baseline = self._state_key()   # a just-loaded song is saved by definition

    def _load_selected(self) -> None:
        rec = self._selected_song()
        if rec is None:
            speech.speak("No saved songs yet." if not user_songs(self._settings)
                         else "Select a song first.")
            return
        if not self._confirm_discard("Load anyway and replace it?"):
            speech.speak("Load cancelled; your song is untouched.")
            return
        self._adopt_record(rec)
        self.notebook.SetSelection(0)        # jump to Arrange to see it
        wx.CallAfter(self.list.SetFocus)
        speech.speak(f"Loaded {rec.get('name', 'song')}, {len(self._sections)} sections, "
                     f"{self._fmt(self._song_len())}.{self._poly_note()}")
        self._reaudition()

    def _play_selected(self) -> None:
        rec = self._selected_song()
        if rec is None:
            speech.speak("Select a song first.")
            return
        if not self._confirm_discard("Playing this saved song replaces it. Continue?"):
            speech.speak("Cancelled; your song is untouched.")
            return
        self._adopt_record(rec)
        self._stop()
        # Announce here (not via _start_playback) so the polymeter mode rides along —
        # loading a poly-tails song must never flip that setting silently.
        self._start_playback(announce=False)
        speech.speak(f"Playing {rec.get('name', 'song')}, "
                     f"{self._fmt(self._song_len())}.{self._poly_note()}")

    def _delete_selected(self) -> None:
        rec = self._selected_song()
        if rec is None:
            speech.speak("Select a song first.")
            return
        delete_song(self._settings, rec.get("name", ""))
        self._rebuild_songs()
        speech.speak(f"Deleted {rec.get('name', 'song')}.")

    def _export(self) -> None:
        wav = self._render()
        if wav is None:
            speech.speak("Add a section first.")
            return
        with wx.FileDialog(self, "Export song as WAV", wildcard="WAV files (*.wav)|*.wav",
                           defaultFile="song.wav",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        try:
            Path(path).write_bytes(wav)
            speech.speak("Song exported.")
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(f"Could not export:\n{exc}", "Export", wx.ICON_ERROR, self)

    def _on_close(self, event) -> None:
        # Time spent arranging must never vanish on an accidental Escape: an unsaved
        # song gets a Save / Don't Save / Cancel prompt (an empty one just closes).
        # Buttons are self-labeled so NVDA reads "Save"/"Don't Save"/"Cancel" — not a
        # bare Yes/No the user has to map to the question. Not calling EndModal keeps
        # the dialog open on Cancel.
        if self._unsaved():
            was_playing = self._playing
            self._stop()                 # don't let the mix talk over the prompt
            dlg = wx.MessageDialog(
                self, "This song hasn't been saved. Save it before closing?",
                "Song Builder", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
            dlg.SetYesNoCancelLabels("&Save", "Do&n't Save", "&Cancel")
            choice = dlg.ShowModal()
            dlg.Destroy()
            if choice == wx.ID_CANCEL:
                speech.speak("Staying in the Song Builder.")
                if was_playing:
                    self._start_playback(announce=False)
                return
            if choice == wx.ID_YES:
                self._save()
                if self._unsaved():      # she backed out of the name prompt
                    speech.speak("Not saved. Staying in the Song Builder.")
                    if was_playing:
                        self._start_playback(announce=False)
                    return
        self._stop()
        self.EndModal(wx.ID_CANCEL)


class _FillOptionsDialog(wx.Dialog):
    """A tiny accessible prompt for an improvised fill: how busy, and may it spill past
    the end.  A slider (never a spin control) and a checkbox — both read cleanly to NVDA."""

    def __init__(self, parent: wx.Window, complexity: int, spill: bool, dark: bool):
        super().__init__(parent, title="Fill", style=wx.DEFAULT_DIALOG_STYLE)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label="Complexity (how busy the fill is):"),
                 0, wx.ALL, 8)
        self.slider = wx.Slider(self, value=complexity, minValue=0, maxValue=100,
                                style=wx.SL_HORIZONTAL)
        set_accessible_name(self.slider, "Fill complexity",
                            value_fn=lambda: f"{self.slider.GetValue()} percent")
        root.Add(self.slider, 0, wx.EXPAND | wx.ALL, 8)
        self.spill = wx.CheckBox(self, label="Let the fill spill past the end "
                                             "(off = it resolves on the bar)")
        self.spill.SetValue(spill)
        root.Add(self.spill, 0, wx.ALL, 8)
        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            root.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizerAndFit(root)
        theme.apply(self, dark)
        wx.CallAfter(self.slider.SetFocus)

    def values(self) -> tuple[int, bool]:
        return self.slider.GetValue(), self.spill.GetValue()


class SongBeatEditorDialog(wx.Dialog):
    """Edit a whole song on one spoken tracker grid — the section editor's grid expanded
    across every section and repeat, for fine beat-by-beat control of an arrangement.

    Navigation (the surface is big, so the ladder climbs by musical unit):
      Left/Right = one step, Shift = beat, Ctrl = bar, Ctrl+Shift or PageUp/Down = section,
      Home/End = the song's start/end, Up/Down = between parts.
    Space cycles a hit (off -> on -> accent -> ghost), F cycles its ornament — both spoken.
    Add Line brings any part of the full kit into the song.  Edit scope: "all repeats"
    (default; the edit changes the section's pattern everywhere it repeats) or "this repeat
    only" (that repeat splits off as its own section so you can vary it alone).
    """

    def __init__(self, parent: wx.Window, panel: "DrumsPanel", sections: list,
                 dark: bool = True):
        super().__init__(parent, title="Song Beat Editor", size=(780, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._panel = panel
        self._settings = panel._settings
        self._dark = dark
        self._pos = 0
        self._added: set[str] = set()      # parts added via Add Line (shown even if empty)
        self._playing = False
        self.result_sections = None        # the edited sections, set on Save
        # Editable working copy: one entry per playable section, each with a private
        # pattern copy so edits don't touch the shared library groove until Save.
        self._did_split = False            # a split happened during the current edit
        self._mark_a = None                # ( section, step ) span markers, set by [ and ]
        self._mark_b = None
        self._fill_complexity = 50         # remembered between fills
        self._fill_spill = False
        self._end_timer = None             # ends a once-through song playback
        self._entries = []
        for s in sections:
            p = resolve_section_pattern(s, self._settings)
            if p is None:
                continue
            # dirty=False: an untouched section (even one with an inline) is written back
            # verbatim on Save, so its per-line kit/sample/tune/volume/choke are preserved.
            # "base" is the original inline whose per-line properties an edit must keep.
            self._entries.append({"section": dict(s), "pattern": p.copy(),
                                  "base": s.get("inline"),
                                  "name": s.get("pattern") or p.name or "section",
                                  "dirty": False})
        try:
            if not self._entries:
                raise ValueError("This song has no playable sections yet.")
            self._build()
        except Exception as exc:  # noqa: BLE001 - a swallowed error is a dead button
            wx.MessageBox(f"Could not open the Song Beat Editor:\n{exc}",
                          "Song Beat Editor", wx.OK | wx.ICON_ERROR, self)
            self.EndModal(wx.ID_CANCEL)
            return
        self.Bind(wx.EVT_CLOSE, lambda e: self._on_cancel())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        theme.apply(self, dark)
        wx.CallAfter(self.grid_list.SetFocus)

    # -- model ----------------------------------------------------------------

    def _reload_grid(self) -> None:
        self._grid = SongGrid([(e["pattern"], e["section"].get("repeats", 1), e["name"])
                               for e in self._entries])
        roles = set(self._added) | set(CORE_ROLES)
        for e in self._entries:
            roles |= set(e["pattern"].hits)
        self._parts = [r for r in ROLES if r in roles]

    def _entry_at(self, pos: int) -> dict:
        return self._entries[self._grid.section_of(pos)]

    def _current_part(self) -> str | None:
        sel = self.grid_list.GetSelection()
        return self._parts[sel] if 0 <= sel < len(self._parts) else None

    def _state_at(self, pattern: Pattern, part: str, step: int) -> str:
        if step not in pattern.hits.get(part, []):
            return "empty"
        state = pattern.level_of(part, step) or "hit"
        orn = pattern.ornament_of(part, step)
        if orn:
            state += f", {orn}"
        chance = pattern.chance_of(part, step)
        return f"{state}, {chance} percent chance" if chance else state

    # -- UI -------------------------------------------------------------------

    def _build(self) -> None:
        self._reload_grid()
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label=(
            "One grid across the whole song. Left/Right move a step, Shift a beat, Ctrl a "
            "bar, Ctrl+Shift or Page Up/Down a section; Home/End jump to the song's ends; "
            "Up/Down pick a part. Space cycles a hit (on, accent, ghost, off); F cycles its "
            "ornament. [ and ] mark a span, L drops a fill across it (or the whole "
            "section), T sets the section's tempo. F1 lists the keys.")),
            0, wx.ALL, 8)
        self.grid_list = wx.ListBox(self, choices=[], style=wx.LB_SINGLE)
        set_accessible_name(self.grid_list, "Song beat grid, parts")
        root.Add(self.grid_list, 1, wx.EXPAND | wx.ALL, 8)

        self.scope_cb = wx.CheckBox(self, label="Edit this repeat only (split it off as a variation)")
        self.scope_cb.Bind(wx.EVT_CHECKBOX, self._on_scope)
        root.Add(self.scope_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(self, label="&Add Line...")
        add_btn.Bind(wx.EVT_BUTTON, lambda e: self._add_line())
        btns.Add(add_btn, 0, wx.RIGHT, 8)
        self.play_btn = wx.Button(self, label="Play &section")
        self.play_btn.Bind(wx.EVT_BUTTON, lambda e: self._play_section())
        btns.Add(self.play_btn, 0, wx.RIGHT, 8)
        song_btn = wx.Button(self, label="Play s&ong")
        song_btn.Bind(wx.EVT_BUTTON, lambda e: self._play_song(from_here=False))
        btns.Add(song_btn, 0, wx.RIGHT, 8)
        here_btn = wx.Button(self, label="Play from &here")
        here_btn.Bind(wx.EVT_BUTTON, lambda e: self._play_song(from_here=True))
        btns.Add(here_btn, 0, wx.RIGHT, 8)
        save_btn = wx.Button(self, wx.ID_OK, "&Save")
        save_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_save())
        btns.Add(save_btn, 0, wx.RIGHT, 8)
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_cancel())
        btns.Add(cancel_btn, 0)
        root.Add(btns, 0, wx.ALL, 10)
        self.SetSizer(root)
        self._rebuild_rows()
        self.grid_list.SetSelection(0)

    def _row_label(self, part: str) -> str:
        total = sum(len(e["pattern"].hits.get(part, [])) for e in self._entries)
        hits = "no hits" if total == 0 else ("1 hit" if total == 1 else f"{total} hits")
        return f"{ROLE_LABELS.get(part, part)}: {hits} in the song"

    def _rebuild_rows(self) -> None:
        keep = max(0, self.grid_list.GetSelection())
        self.grid_list.Set([self._row_label(p) for p in self._parts])
        if self._parts:
            self.grid_list.SetSelection(min(keep, len(self._parts) - 1))

    def _refresh_part_row(self, part: str) -> None:
        if part in self._parts:
            self.grid_list.SetString(self._parts.index(part), self._row_label(part))

    # -- navigation & speech --------------------------------------------------

    def _speak_cursor(self) -> None:
        part = self._current_part()
        pat = self._entry_at(self._pos)["pattern"]
        loc = self._grid.locate(self._pos)
        state = self._state_at(pat, part, loc.step_in_pattern) if part else "empty"
        label = ROLE_LABELS.get(part, part) if part else "no part"
        speech.speak(f"{self._grid.describe(self._pos)}. {label}: {state}")

    def _move(self, unit: str, direction: int) -> None:
        mover = {"step": self._grid.step, "beat": self._grid.beat,
                 "bar": self._grid.bar, "section": self._grid.section}[unit]
        self._pos = mover(self._pos, direction)
        self._speak_cursor()

    def _move_part(self, delta: int) -> None:
        if not self._parts:
            return
        sel = max(0, self.grid_list.GetSelection())
        new = max(0, min(len(self._parts) - 1, sel + delta))
        self.grid_list.SetSelection(new)
        self._speak_cursor()

    def _on_scope(self, event=None) -> None:
        on = self.scope_cb.GetValue()
        speech.speak("Editing this repeat only; the repeat you edit splits into its own "
                     "section." if on else "Editing all repeats of the section.")

    # -- editing --------------------------------------------------------------

    def _target(self) -> tuple[Pattern, int] | None:
        """The pattern an edit lands on and the step within it — honouring the edit scope.
        In 'this repeat only' mode the current repeat is split off first."""
        part = self._current_part()
        if part is None:
            return None
        loc = self._grid.locate(self._pos)
        entry = self._entries[loc.section]
        if self.scope_cb.GetValue() and entry["section"].get("repeats", 1) > 1:
            entry = self._split_here(loc)
            loc = self._grid.locate(self._pos)
        entry["dirty"] = True
        return entry["pattern"], loc.step_in_pattern

    def _split_here(self, loc) -> dict:
        """Split the section under the cursor so the current repeat becomes its own entry,
        rebuild the grid, land the cursor on that repeat's same step, and return the new
        (variant) entry to edit.

        The split is seeded from the LIVE edited pattern (folded into the section's inline
        first), so any edits already made to this section in 'all repeats' mode carry into
        every piece — nothing the user did is thrown away by the re-resolve.
        """
        si = loc.section
        entry = self._entries[si]
        seeded = dict(entry["section"])
        seeded["inline"] = inline_record_from_pattern(entry["pattern"],
                                                      base_record=entry.get("base"))
        parts, variant_local = split_section_repeat([seeded], 0, loc.repeat, self._settings)
        new_entries = []
        for sd in parts:
            p = resolve_section_pattern(sd, self._settings) or entry["pattern"]
            new_entries.append({"section": dict(sd), "pattern": p.copy(),
                                "base": sd.get("inline"),
                                "name": sd.get("pattern") or entry["name"],
                                "dirty": False})
        self._entries[si:si + 1] = new_entries
        self._mark_a = self._mark_b = None    # entry indices shifted; markers are now stale
        self._reload_grid()
        self._rebuild_rows()
        # Land on the split-off variant's start plus the same in-pattern step.
        variant = self._entries[si + variant_local]
        self._pos = self._grid.section_start(si + variant_local) + loc.step_in_pattern
        self._did_split = True             # the edit announcement will mention it
        return variant

    def _toggle(self) -> None:
        part = self._current_part()
        if part is None:
            return
        # Don't let a shared song cursor place a hit past a polymetric line's own loop
        # length — it would be announced as placed but silently dropped on save.
        loc = self._grid.locate(self._pos)
        if loc.step_in_pattern >= self._entry_at(self._pos)["pattern"].line_length(part):
            speech.speak(f"Past the {ROLE_LABELS.get(part, part)} loop length here; "
                         "no hit placed.")
            return
        self._did_split = False
        target = self._target()
        if target is None:
            return
        pattern, step = target
        steps = set(pattern.hits.get(part, []))
        if step not in steps:
            steps.add(step)
            pattern.set_level(part, step, None)
            spoken = "on"
        else:
            level = pattern.level_of(part, step)
            if level is None:
                pattern.set_level(part, step, LEVEL_ACCENT)
                spoken = "accent"
            elif level == LEVEL_ACCENT:
                pattern.set_level(part, step, LEVEL_GHOST)
                spoken = "ghost"
            else:
                steps.discard(step)
                pattern.set_level(part, step, None)
                pattern.set_ornament(part, step, None)
                spoken = "off"
        if steps:
            pattern.hits[part] = sorted(steps)
        else:
            pattern.hits.pop(part, None)
        self._refresh_part_row(part)
        prefix = "Repeat split off as its own section. " if self._did_split else ""
        speech.speak(f"{prefix}{ROLE_LABELS.get(part, part)} {spoken}, "
                     f"{self._grid.describe(self._pos)}")

    def _cycle_ornament(self) -> None:
        part = self._current_part()
        loc = self._grid.locate(self._pos)
        pat = self._entry_at(self._pos)["pattern"]
        if part is None or loc.step_in_pattern not in pat.hits.get(part, []):
            speech.speak("No hit here. Space places one first.")
            return
        self._did_split = False
        target = self._target()
        if target is None:
            return
        pattern, step = target
        order = [None] + list(ORNAMENTS)
        cur = pattern.ornament_of(part, step)
        new = order[(order.index(cur) + 1) % len(order)]
        pattern.set_ornament(part, step, new)
        self._refresh_part_row(part)
        prefix = "Repeat split off as its own section. " if self._did_split else ""
        speech.speak(f"{prefix}{ROLE_LABELS.get(part, part)} {new or 'plain stroke'}, "
                     f"{self._grid.describe(self._pos)}")

    # -- markers, fills, tempo ------------------------------------------------

    def _set_mark(self, which: str) -> None:
        """[ and ] drop a start / end marker across all parts (a span for a fill)."""
        loc = self._grid.locate(self._pos)
        mark = (loc.section, loc.step_in_pattern)
        if which == "start":
            self._mark_a = mark
        else:
            self._mark_b = mark
        speech.speak(f"{'Start' if which == 'start' else 'End'} marker at "
                     f"{self._grid.describe(self._pos)}.")

    def _fill_range(self, entry_section: int, pattern: Pattern) -> tuple[int, int, str]:
        """The step range a fill covers: the marked span when both markers sit in this
        section, otherwise the whole section."""
        a, b = self._mark_a, self._mark_b
        if a and b and a[0] == entry_section and b[0] == entry_section:
            lo, hi = sorted((a[1], b[1]))
            return lo, min(pattern.steps, hi + 1), "the marked span"
        return 0, pattern.steps, "the section"

    def _do_fill(self) -> None:
        """L drops an improvised fill across the marked span (or the whole section),
        after asking for its complexity and whether it may spill past the end."""
        loc = self._grid.locate(self._pos)
        entry = self._entries[loc.section]
        dlg = _FillOptionsDialog(self, self._fill_complexity, self._fill_spill, self._dark)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            speech.speak("Fill cancelled.")
            return
        self._fill_complexity, self._fill_spill = dlg.values()
        dlg.Destroy()
        start, end, where = self._fill_range(loc.section, entry["pattern"])
        # Honour "Edit this repeat only" like Space/F do — split the repeat off first so
        # the fill lands on that repeat alone instead of overwriting every repeat.
        self._did_split = False
        if self.scope_cb.GetValue() and entry["section"].get("repeats", 1) > 1:
            entry = self._split_here(loc)
        entry["dirty"] = True
        fill_span(entry["pattern"], start, end, self._fill_complexity / 100.0,
                  self._fill_spill)
        self._mark_a = self._mark_b = None       # markers consumed; don't let them go stale
        self._reload_grid()
        self._rebuild_rows()
        prefix = "Repeat split off as its own section. " if self._did_split else ""
        spill = "spilling past the end" if self._fill_spill else "resolving on the bar"
        speech.speak(f"{prefix}Fill dropped across {where} of {entry['name']}, "
                     f"complexity {self._fill_complexity} percent, {spill}.")

    def _do_tempo(self) -> None:
        """T sets the tempo of the section under the cursor (the marked section)."""
        loc = self._grid.locate(self._pos)
        entry = self._entries[loc.section]
        choices = ["Song tempo"] + [str(t) for t in range(TEMPO_MIN, TEMPO_MAX + 1, 5)]
        dlg = wx.SingleChoiceDialog(self, f"Tempo for {entry['name']}:",
                                    "Section tempo", choices)
        theme.apply(dlg, self._dark)
        cur = entry["section"].get("tempo")
        if cur and str(cur) in choices:
            dlg.SetSelection(choices.index(str(cur)))
        if dlg.ShowModal() == wx.ID_OK:
            sel = dlg.GetStringSelection()
            entry["section"]["tempo"] = None if sel == "Song tempo" else int(sel)
            speech.speak(f"{entry['name']} tempo "
                         + ("follows the song." if sel == "Song tempo" else f"{sel} BPM."))
        dlg.Destroy()

    def _add_line(self) -> None:
        available = [r for r in ROLES if r not in self._parts]
        if not available:
            speech.speak("Every part is already in the song.")
            return
        labels = [ROLE_LABELS[r] for r in available]
        dlg = wx.SingleChoiceDialog(self, "Which part to add to the song?", "Add line", labels)
        theme.apply(dlg, self._dark)
        if dlg.ShowModal() == wx.ID_OK:
            role = available[dlg.GetSelection()]
            self._added.add(role)
            self._reload_grid()
            self._rebuild_rows()
            self.grid_list.SetSelection(self._parts.index(role))
            speech.speak(f"Added {ROLE_LABELS[role]}. Space places its hits across the song.")
        dlg.Destroy()

    # -- playback & save ------------------------------------------------------

    def _resolved(self) -> list:
        """[(pattern, repeats, bpm, kit)] for the whole song at its current edit state."""
        bpm0 = self._panel.bpm
        return [(e["pattern"], e["section"].get("repeats", 1),
                 e["section"].get("tempo") or bpm0, self._panel._kit)
                for e in self._entries]

    def _cursor_seconds(self) -> float:
        """Playing time from the song's start up to the cursor (per-section tempos)."""
        loc = self._grid.locate(self._pos)
        secs = 0.0
        for i, e in enumerate(self._entries):
            bpm = e["section"].get("tempo") or self._panel.bpm
            if i < loc.section:
                secs += section_seconds(e["pattern"], e["section"].get("repeats", 1), bpm)
            elif i == loc.section:
                step_offset = self._pos - self._grid.section_start(i)
                secs += step_offset * e["pattern"].step_seconds(bpm)
                break
        return secs

    def _audio_ok(self) -> bool:
        if not self._panel.player.available or self._panel._kit is None:
            speech.speak("Audio isn't available on this system.")
            return False
        return True

    def _play_section(self) -> None:
        """Loop the section under the cursor — the working audition while you edit."""
        if self._playing:
            self._stop()
            speech.speak("Stopped.")
            return
        if not self._audio_ok():
            return
        entry = self._entry_at(self._pos)
        bpm = entry["section"].get("tempo") or self._panel.bpm
        self._panel.stop()
        wav = render_loop(entry["pattern"], self._panel._kit, bpm,
                          volume=self._panel.volume_slider.GetValue() / 100.0,
                          choke_groups=_auto_hat_choke(entry["pattern"]))
        self._panel.player.play(wav, loop=True)
        self._playing = True
        self.play_btn.SetLabel("&Stop section")
        speech.speak(f"Playing {entry['name']}.")

    def _play_song(self, from_here: bool) -> None:
        """Play the whole song once — from the top, or from the cursor position."""
        if self._playing:
            self._stop()
            speech.speak("Stopped.")
            return
        if not self._audio_ok():
            return
        vol = self._panel.volume_slider.GetValue() / 100.0
        buf = render_song_buffer(self._resolved())
        if from_here:
            offset = max(0, min(len(buf) - 1, int(self._cursor_seconds() * RATE)))
            buf = buf[offset:]
        wav = _buf_to_wav(buf, vol, RATE)
        self._panel.stop()
        self._panel.player.play(wav, loop=False)      # a song plays through once
        self._playing = True
        self.play_btn.SetLabel("&Stop")
        secs = len(buf) / RATE
        where = (f"from {self._grid.describe(self._pos)}" if from_here else "from the top")
        self._end_timer = wx.CallLater(int(secs * 1000) + 300, self._song_ended)
        speech.speak(f"Playing the song {where}.")

    def _song_ended(self) -> None:
        self._end_timer = None
        if self._playing:
            self._playing = False
            self.play_btn.SetLabel("Play &section")
            speech.speak("Song finished.")

    def _stop(self) -> None:
        if getattr(self, "_end_timer", None) is not None:
            self._end_timer.Stop()
            self._end_timer = None
        if self._playing:
            self._panel.player.stop()
            self._playing = False
            self.play_btn.SetLabel("Play &section")

    def _on_save(self) -> None:
        out = []
        for e in self._entries:
            s = dict(e["section"])
            if e["dirty"]:      # keep the original per-line source/tune/volume/choke
                s["inline"] = inline_record_from_pattern(e["pattern"],
                                                         base_record=e.get("base"))
            out.append(s)
        self.result_sections = out
        self._stop()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self) -> None:
        self._stop()
        self.EndModal(wx.ID_CANCEL)

    # -- keys -----------------------------------------------------------------

    def _keys_help(self) -> None:
        wx.MessageBox(
            "Song Beat Editor keys:\n\n"
            "Left/Right — move one step\n"
            "Shift+Left/Right — one beat\n"
            "Ctrl+Left/Right — one bar\n"
            "Ctrl+Shift+Left/Right, or Page Up/Down — one section\n"
            "Home/End — start / end of the song\n"
            "Up/Down — choose a part\n"
            "Space — cycle a hit: on, accent, ghost, off\n"
            "F — cycle the hit's ornament: flam, drag, roll\n"
            "[ and ] — set the start / end marker of a span\n"
            "L — drop an improvised fill across the span (or the whole section)\n"
            "T — set the tempo of the section under the cursor\n"
            "P — play the whole song from the cursor (Shift+P from the top); P again stops\n"
            "Play section button — loop the section you're on while you edit\n"
            "Add Line — add any part of the kit to the song\n"
            "'Edit this repeat only' checkbox — edit one repeat as its own variation\n"
            "Save / Cancel — keep or discard your edits",
            "Song Beat Editor — Keys", wx.OK | wx.ICON_INFORMATION, self)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if wx.Window.FindFocus() is not self.grid_list:
            event.Skip()
            return
        code = event.GetKeyCode()
        ctrl, shift = event.ControlDown(), event.ShiftDown()
        if code == wx.WXK_LEFT or code == wx.WXK_RIGHT:
            direction = 1 if code == wx.WXK_RIGHT else -1
            unit = ("section" if ctrl and shift else "bar" if ctrl
                    else "beat" if shift else "step")
            self._move(unit, direction)
        elif code == wx.WXK_UP:
            self._move_part(-1)
        elif code == wx.WXK_DOWN:
            self._move_part(1)
        elif code == wx.WXK_PAGEUP:
            self._move("section", -1)
        elif code == wx.WXK_PAGEDOWN:
            self._move("section", 1)
        elif code == wx.WXK_HOME:
            self._pos = self._grid.home()
            self._speak_cursor()
        elif code == wx.WXK_END:
            self._pos = self._grid.end()
            self._speak_cursor()
        elif code == wx.WXK_SPACE:
            self._toggle()
        elif code in (ord("F"), ord("f")):
            self._cycle_ornament()
        elif code in (ord("["), ord("{")):
            self._set_mark("start")
        elif code in (ord("]"), ord("}")):
            self._set_mark("end")
        elif code in (ord("L"), ord("l")):
            self._do_fill()
        elif code in (ord("T"), ord("t")):
            self._do_tempo()
        elif code in (ord("P"), ord("p")):
            self._play_song(from_here=not shift)   # P from the cursor, Shift+P from the top
        elif code == wx.WXK_F1:
            self._keys_help()
        else:
            event.Skip()


class DrumsPanel(wx.Panel):
    def __init__(self, parent: wx.Window, settings=None, status: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._settings = settings
        self._status = status
        self.player = DrumLoopPlayer()
        self._countin_player = _PreviewPlayer()   # one-shot channel for the count-in
        self._countin_timer: wx.CallLater | None = None
        # Tempo trainer: climb the BPM as you practice (see TempoTrainerDialog).
        self._trainer_cfg = {"step": 5, "bars": 2, "target": 160, "continuous": False}
        self._trainer_timer: wx.CallLater | None = None
        self._trainer_bpm = 0
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
        # Separate buttons (not dropdown entries) so arrowing through kits never springs
        # a dialog on you: build one from scratch, or import a folder.
        self.build_button = wx.Button(self, label="&Build Kit...")
        self.build_button.Bind(wx.EVT_BUTTON, self._on_build_kit)
        kit_row.Add(self.build_button, 0, wx.RIGHT, 8)
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

        # How long/busy improvised fills get (only affects "Improvised" fill style).
        self.fill_amount_label = wx.StaticText(self, label="Fill amount: 0%")
        grid.Add(self.fill_amount_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self.fill_amount_slider = wx.Slider(self, value=0, minValue=0, maxValue=100)
        set_accessible_name(self.fill_amount_slider, "Fill amount",
                            value_fn=lambda: f"{self.fill_amount_slider.GetValue()}%")
        self.fill_amount_slider.Bind(wx.EVT_SLIDER, self._on_fill_amount)
        grid.Add(self.fill_amount_slider, 0, wx.EXPAND)

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

        # Feel (swing + humanize) now lives IN the Pattern Editor and saves with each
        # groove — a shuffle keeps its shuffle. The main tab stays selection-focused.

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
        self.countin_cb = wx.CheckBox(self, label="Count-&in")
        self.countin_cb.SetToolTip("Play one bar of clicks before the loop starts")
        buttons.Add(self.countin_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.trainer_cb = wx.CheckBox(self, label="Tempo &trainer")
        self.trainer_cb.SetToolTip("Speed the tempo up as you play; configure with Trainer Options")
        buttons.Add(self.trainer_cb, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.trainer_btn = wx.Button(self, label="Trainer &Options...")
        self.trainer_btn.Bind(wx.EVT_BUTTON, lambda e: self._open_trainer_options())
        buttons.Add(self.trainer_btn, 0, wx.RIGHT, 8)
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
            # Show the parts this groove uses plus the core (kick/snare/hats), NOT every
            # voice in the full 24-part kit — same curation as the editor's line list, so
            # the Part chooser isn't a wall of silent parts to arrow through.
            wanted = set(self._pattern.hits) | set(CORE_ROLES)
            self._part_roles = [r for r in ROLES if r in wanted]
            self._part_roles += [r for r in self._pattern.hits if r not in self._part_roles]
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

    def _build_kit_folder(self, name: str, choices: dict) -> Path:
        """Write a self-contained kit folder: each chosen sample copied into its part's
        folder, and the synth voice baked to a WAV for every other part (so parts left on
        the synth still play, and the kit stands on its own).  Returns the folder path."""
        dest = self._kits_dir() / name
        synth = synth_kit()
        try:
            for role in ROLES:
                role_dir = dest / ROLE_FOLDER[role]
                src = choices.get(role)
                if src is not None:
                    role_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, role_dir / Path(src).name)
                else:
                    voice = synth.voice(role)      # fx has no synth voice; skip it
                    if voice is not None:
                        role_dir.mkdir(parents=True, exist_ok=True)
                        (role_dir / f"synth_{role}.wav").write_bytes(
                            _buf_to_wav(voice, 1.0, RATE))
        except Exception:                          # don't leave a half-written kit behind
            shutil.rmtree(dest, ignore_errors=True)
            raise
        return dest

    def _on_build_kit(self, event: wx.CommandEvent) -> None:
        self._kits_dir().mkdir(parents=True, exist_ok=True)
        dark = getattr(wx.GetTopLevelParent(self), "dark_mode", True)
        was_playing = self._playing
        if was_playing:
            self.player.stop()               # previews share the audio channel
        try:
            dlg = KitBuilderDialog(self, self._kits_dir(), self._kit_folder_names(), dark)
        except Exception as exc:  # noqa: BLE001 - surface, don't leave a dead button
            wx.MessageBox(f"Could not open Build Kit:\n{exc}", "Build Kit", wx.ICON_ERROR)
            if was_playing:
                self._render_and_play()
            return
        if dlg.ShowModal() == wx.ID_OK:
            name, choices = dlg.kit_name, dlg.choices
            try:
                dest = self._build_kit_folder(name, choices)
                kit = load_kit_from_folder(dest)
            except Exception as exc:  # noqa: BLE001
                wx.MessageBox(f"Could not save the kit:\n{exc}", "Build Kit", wx.ICON_ERROR)
                dlg.Destroy()
                if was_playing:
                    self._render_and_play()
                return
            self.kit_choice.Set(self._kit_choices())
            idx = self.kit_choice.FindString(name)
            self.kit_choice.SetSelection(idx if idx != wx.NOT_FOUND else 0)
            self._kit_dir = dest
            self._set_kit(kit)
            n = len(choices)
            self._announce(f"Kit '{name}' built and selected: {n} sampled "
                           f"part{'s' if n != 1 else ''}, the rest synth.")
            was_playing = False              # a new kit is selected; don't resume the old mix
        else:
            self._announce("Build Kit cancelled.")
        dlg.Destroy()
        if was_playing:
            self._render_and_play()

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

    def _on_fill_amount(self, event: wx.CommandEvent) -> None:
        self.fill_amount_label.SetLabel(f"Fill amount: {self.fill_amount_slider.GetValue()}%")
        self._apply()

    def _on_volume(self, event: wx.CommandEvent) -> None:
        self.volume_label.SetLabel(f"Drum volume: {self.volume_slider.GetValue()}%")
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
                                      base_kit=self._kit)
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

    def toggle_transport(self) -> None:
        """Start or stop the drum loop — the app-wide Play/Stop (F5) hook, callable from
        anywhere in the window without tabbing to the button. Start/stop speak their own
        state, so it's audible even when focus is elsewhere."""
        self._on_start_stop(None)

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
            {r: L for r, L in p.lengths.items() if r not in self._muted},
            p.swing, p.humanize,
            {r: dict(m) for r, m in p.probs.items() if r not in self._muted},
            {r: dict(m) for r, m in p.ornaments.items() if r not in self._muted})
        return flatten_polymeter(effective)

    def _apply_fills(self, effective: Pattern) -> Pattern:
        fill_bars = self._fill_every_bars()
        if self.fillstyle_choice.GetSelection() == 1:
            # Improvised: several passes, each ending in a different generated fill.
            # With no explicit cadence, improvise on a 4-bar cycle — a 1-bar cycle
            # would put a fill in every single bar and wreck the meter's feel.
            cycle = fill_bars or max(4, effective.bars)
            cycles = 2 if cycle >= 12 else 4
            return improvised_loop(effective, cycle, cycles,
                                   fill_amount=self.fill_amount_slider.GetValue() / 100.0)
        if fill_bars:
            return expand_with_fill(effective, fill_bars)
        return effective

    def _render_and_play(self) -> None:
        effective = self._apply_fills(self._muted_pattern())
        kit = self._pattern_voices or self._kit  # composite voices for line patterns
        # Feel travels with the groove now: render_loop reads effective.swing/humanize.
        self.player.play(render_loop(effective, kit, self.bpm,
                                     volume=self.volume_slider.GetValue() / 100.0,
                                     choke_groups=choke_map(self._current_lines())))

    def _apply(self) -> None:
        """Re-render and swap the loop if we're currently playing."""
        if self._playing and self._kit is not None:
            self._render_and_play()

    def _start(self) -> None:
        if not NUMPY_AVAILABLE or not self.player.available or self._kit is None:
            self._announce("The drum looper isn't available on this system.")
            return
        self._playing = True
        self.start_button.SetLabel("&Stop")
        if self.countin_cb.GetValue():           # a bar of clicks, then the loop
            beats = self._pattern.beats_per_bar
            buf, dur = render_count_in(beats, self._pattern.beat_unit, self.bpm)
            if buf is not None and self._countin_player.play_voice(buf):
                self._announce(f"Counting in, {beats} beat{'s' if beats != 1 else ''}.")
                self._countin_timer = wx.CallLater(max(1, int(dur * 1000)), self._begin_loop)
                return
        self._begin_loop()

    def _begin_loop(self) -> None:
        self._countin_timer = None
        if not self._playing:                    # stopped during the count-in
            return
        if self.trainer_cb.GetValue():
            self._start_trainer()
        else:
            self._render_and_play()
            self._announce(f"Drum loop started: {self._pattern.name}, {self.bpm} BPM.")

    # -- tempo trainer --------------------------------------------------------

    def _start_trainer(self) -> None:
        self._trainer_bpm = self.bpm             # the Tempo slider is the starting speed
        self._play_at_trainer_bpm()
        cfg = self._trainer_cfg
        if cfg["continuous"]:
            self._announce(f"Tempo trainer from {self._trainer_bpm} BPM, climbing "
                           f"{cfg['step']} every {cfg['bars']} bars.")
        else:
            steps = len(tempo_ramp(self._trainer_bpm, cfg["target"], cfg["step"]))
            self._announce(f"Tempo trainer: {self._trainer_bpm} to {cfg['target']} BPM, "
                           f"{steps} step{'s' if steps != 1 else ''}.")
        self._schedule_trainer_bump()

    def _play_at_trainer_bpm(self) -> None:
        bpm = max(TEMPO_MIN, min(TEMPO_MAX, self._trainer_bpm))
        self.tempo_slider.SetValue(bpm)          # programmatic: fires no EVT_SLIDER
        self.tempo_label.SetLabel(f"Tempo: {bpm} BPM")
        self._render_and_play()                  # renders at self.bpm (the slider)

    def _schedule_trainer_bump(self) -> None:
        bar_s = self._pattern.loop_seconds(self.bpm) / max(1, self._pattern.bars)
        interval = max(0.5, self._trainer_cfg["bars"] * bar_s)
        self._trainer_timer = wx.CallLater(int(interval * 1000), self._trainer_bump)

    def _trainer_bump(self) -> None:
        self._trainer_timer = None
        if not self._playing:
            return
        cfg = self._trainer_cfg
        nxt = self._trainer_bpm + cfg["step"]
        if not cfg["continuous"] and nxt >= cfg["target"]:
            self._trainer_bpm = cfg["target"]    # reached the ceiling: hold and stop climbing
            self._play_at_trainer_bpm()
            self._announce(f"Reached target, holding at {cfg['target']} BPM.")
            return
        if nxt > TEMPO_MAX:                       # continuous mode hit the very top
            self._trainer_bpm = TEMPO_MAX
            self._play_at_trainer_bpm()
            self._announce(f"Top speed, {TEMPO_MAX} BPM.")
            return
        self._trainer_bpm = nxt
        self._play_at_trainer_bpm()
        self._announce(f"{nxt} BPM.")
        self._schedule_trainer_bump()

    def _open_trainer_options(self) -> None:
        dlg = TempoTrainerDialog(self, self._trainer_cfg, self.bpm, dark=self._dark())
        if dlg.ShowModal() == wx.ID_OK:
            self._trainer_cfg = dlg.result
            self.trainer_cb.SetValue(True)        # configuring it turns it on
            c = self._trainer_cfg
            mode = "climbing past the target" if c["continuous"] else f"up to {c['target']} BPM"
            self._announce(f"Tempo trainer on: +{c['step']} BPM every {c['bars']} bars, {mode}.")
        dlg.Destroy()

    def _cancel_countin(self) -> None:
        if self._countin_timer is not None:
            self._countin_timer.Stop()
            self._countin_timer = None
        self._countin_player.stop()

    def _cancel_trainer(self) -> None:
        if self._trainer_timer is not None:
            self._trainer_timer.Stop()
            self._trainer_timer = None

    def stop(self) -> None:
        self._cancel_countin()
        self._cancel_trainer()
        self.player.stop()
        self._playing = False
        self.start_button.SetLabel("&Start")
        self._announce("Drum loop stopped.")

    def dispose(self) -> None:
        # Teardown-safe: stop audio and free the temp file, touch no UI.
        self._cancel_countin()
        self._cancel_trainer()
        self._countin_player.dispose()
        self.player.dispose()
        self._playing = False

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetWindow() is self:
            self.dispose()
        event.Skip()

    def _announce(self, message: str) -> None:
        # Speak it AND show it. These are user actions with no native control feedback
        # (Start/Stop, the tempo trainer's climbing BPM, the count-in, kit loading), so the
        # status bar alone would be silent to a screen reader — speak through NVDA too.
        speech.speak(message)
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
                              choke_groups=choke_map(self._current_lines()))
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

    def open_song_builder(self) -> None:
        """Song mode: chain grooves into an arrangement (Tools > Song Builder)."""
        dlg = SongDialog(self, self, dark=self._dark())
        dlg.ShowModal()
        dlg.Destroy()


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
