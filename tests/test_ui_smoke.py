"""Headless smoke test: the UI constructs and reacts without errors.

Skips automatically if a wx display cannot be created (e.g. a headless CI without
the platform GUI available).
"""

import pytest

wx = pytest.importorskip("wx")

try:
    _APP = wx.App(False)
except Exception:  # pragma: no cover - no GUI available
    pytest.skip("no wx display available", allow_module_level=True)

import firehawk.config as config
from firehawk.model import SLOT_LAYOUT
from firehawk.ui.blockpanel import BlockPanel
from firehawk.ui.drumspanel import DrumsPanel
from firehawk.ui.mainframe import MainFrame
from firehawk.ui.metronomepanel import MetronomePanel
from firehawk.ui.presetspanel import PresetsPanel
from firehawk.ui.tunerpanel import TunerPanel


@pytest.fixture(autouse=True)
def _silence_audio(monkeypatch):
    """No spoken output during tests, and stop any looping sound afterwards."""
    from firehawk.ui import speech
    spoken: list[str] = []
    monkeypatch.setattr(speech, "speak",
                        lambda text, interrupt=True: spoken.append(text))
    yield spoken
    try:
        import winsound
        winsound.PlaySound(None, 0)
    except Exception:  # pragma: no cover - non-Windows / no audio
        pass


@pytest.fixture()
def frame(tmp_path, monkeypatch):
    # Isolate the tab-order settings file so tests never touch the real one.
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings.json")
    f = MainFrame()
    yield f
    # Deterministic teardown: stop audio/timers on the practice pages, then flush the
    # deferred Destroy so native resources are freed between tests (there is no running
    # event loop to process pending deletes otherwise).
    for page in (f.tuner_page, f.metronome_page, f.drums_page):
        if page is not None:
            page.dispose()
    f.Destroy()
    wx.SafeYield()


def _block_pages(frame):
    for i in range(frame.listbook.GetPageCount()):
        page = frame.listbook.GetPage(i)
        if isinstance(page, BlockPanel):
            yield page


def _block_page(frame, slot_id):
    for page in _block_pages(frame):
        if page.slot.id == slot_id:
            return page
    raise AssertionError(f"no page for slot {slot_id}")


def test_has_presets_page_and_all_blocks(frame):
    # Presets + Tuner + Metronome + Drum Looper pages, plus one per slot.
    assert frame.listbook.GetPageCount() == len(SLOT_LAYOUT) + 4
    assert isinstance(frame.listbook.GetPage(0), PresetsPanel)


def test_default_order_puts_practice_tools_last(frame):
    assert frame._view_ids[0] == "presets"
    assert frame._view_ids[-3:] == ["tuner", "metronome", "drums"]
    last = frame.listbook.GetPageCount() - 1
    assert isinstance(frame.listbook.GetPage(last), DrumsPanel)
    assert isinstance(frame.listbook.GetPage(last - 1), MetronomePanel)


def test_reorder_rebuilds_and_persists(frame):
    new_order = ["tuner"] + [v for v in frame._view_ids if v != "tuner"]
    frame.settings.set_page_order(new_order)
    frame._rebuild_after_reorder()
    assert frame._view_ids == new_order
    # The Tuner is now the first page, and the live tuner reference points to it.
    assert isinstance(frame.listbook.GetPage(0), TunerPanel)
    assert frame.tuner_page is frame.listbook.GetPage(0)
    # The order was written to the (isolated) settings file.
    assert config.AppSettings().page_order() == new_order


def test_editing_still_works_after_reorder(frame):
    frame.settings.set_page_order(list(reversed(frame._view_ids)))
    frame._rebuild_after_reorder()
    amp = _block_page(frame, "amp")
    amp._on_param("Bass", 0.42)
    assert frame.buffer.get_param("amp", "Bass") == pytest.approx(0.42)


def test_metronome_start_stop_toggles(frame):
    m = frame.metronome_page
    assert isinstance(m, MetronomePanel)
    if not m.player.available:
        pytest.skip("no audio device available")
    m._on_start_stop(None)  # start
    assert m.is_running()
    assert m.start_button.GetLabel() == "&Stop"
    m._on_start_stop(None)  # stop
    assert not m.is_running()
    assert m.start_button.GetLabel() == "&Start"


def test_metronome_survives_reorder(frame):
    # Moving the Metronome to the top must keep the same live panel object.
    metro = frame.metronome_page
    frame.settings.set_page_order(["metronome"] + [v for v in frame._view_ids if v != "metronome"])
    frame._rebuild_after_reorder()
    assert frame.metronome_page is metro
    assert frame._view_ids[0] == "metronome"


def test_drums_panel_layout(frame):
    d = frame.drums_page
    assert isinstance(d, DrumsPanel)
    assert d.part_choice.GetCount() >= 1
    # 200 grooves in the dropdown; the kit dropdown holds only kits (import is a
    # separate button, so arrowing through kits never springs a folder dialog).
    assert d.groove_choice.GetCount() == 200
    assert all("..." not in item for item in d.kit_choice.GetItems())
    assert d.import_button.GetLabel() == "&Import Drum Kit..."


def _grid_dialog(frame):
    from firehawk.ui.drumspanel import PatternEditorDialog
    d = frame.drums_page
    return PatternEditorDialog(d, d._pattern.copy(), d._current_lines(), d._kits_dir(),
                               set(), d.player, d.bpm, dark=True, settings=d._settings)


def _line_index(dlg, line_id):
    return next(i for i, ln in enumerate(dlg.lines) if ln["id"] == line_id)


class _Key:
    def __init__(self, code, ctrl=False, shift=False):
        self._code, self._ctrl, self._shift = code, ctrl, shift

    def GetKeyCode(self):
        return self._code

    def ControlDown(self):
        return self._ctrl

    def ShiftDown(self):
        return self._shift

    def Skip(self):
        pass


def test_grid_rows_one_per_line(frame):
    dlg = _grid_dialog(frame)
    try:
        assert dlg.grid_list.GetCount() == len(dlg.lines)
        assert dlg.grid_list.GetString(0).startswith("Kick:")
        assert "sample" in dlg.grid_list.GetString(0)
    finally:
        dlg.Destroy()


def test_grid_up_down_moves_lines_and_speaks(frame, _silence_audio):
    spoken = _silence_audio
    dlg = _grid_dialog(frame)
    try:
        dlg.grid_list.SetSelection(0)
        dlg._on_grid_key(_Key(wx.WXK_DOWN))
        assert dlg.grid_list.GetSelection() == 1
        assert spoken[-1].startswith("Snare:") and "Cursor:" in spoken[-1]
        dlg._on_grid_key(_Key(wx.WXK_UP))
        assert dlg.grid_list.GetSelection() == 0
        assert spoken[-1].startswith("Kick:")
        dlg._on_grid_key(_Key(wx.WXK_UP))  # clamped at the top
        assert dlg.grid_list.GetSelection() == 0
    finally:
        dlg.Destroy()


def test_grid_add_and_delete_line(frame, _silence_audio):
    from firehawk.practice.patternstore import make_line
    dlg = _grid_dialog(frame)
    try:
        before = len(dlg.lines)
        ln = make_line("kick", None, None, existing=dlg.lines)  # stacked synth kick
        assert ln["id"] == "kick 2"
        dlg.lines.append(ln)
        dlg._rebuild_line_kit()
        dlg._rebuild_rows()
        assert dlg._line_kit.voice("kick 2") is not None
        # Toggle a hit on the stacked line, then delete it.
        dlg.grid_list.SetSelection(len(dlg.lines) - 1)
        dlg._cursor = 4
        dlg._on_grid_key(_Key(wx.WXK_SPACE))
        assert 4 in dlg.pattern.hits["kick 2"]
        dlg._on_grid_key(_Key(wx.WXK_DELETE))
        assert len(dlg.lines) == before
        assert "kick 2" not in dlg.pattern.hits
    finally:
        dlg.Destroy()


def test_grid_cursor_speaks_positions(frame, _silence_audio):
    spoken = _silence_audio
    dlg = _grid_dialog(frame)
    try:
        dlg._on_grid_key(_Key(wx.WXK_RIGHT))                          # +1 step
        dlg._on_grid_key(_Key(wx.WXK_RIGHT, ctrl=True))               # +1 beat
        dlg._on_grid_key(_Key(wx.WXK_RIGHT, ctrl=True, shift=True))   # +1 bar (clamped)
        assert dlg._cursor == dlg.pattern.steps - 1
        assert spoken[-3:] == ["Beat 1.2, empty", "Beat 2.2, empty", "Beat 4.4, empty"]
        dlg._on_grid_key(_Key(wx.WXK_HOME))
        assert dlg._cursor == 0 and spoken[-1].startswith("Beat 1")
    finally:
        dlg.Destroy()


def test_grid_space_cycles_dynamics(frame, _silence_audio):
    # Space cycles off -> on -> accent -> ghost -> off, each spoken.
    from firehawk.practice import LEVEL_ACCENT, LEVEL_GHOST
    spoken = _silence_audio
    dlg = _grid_dialog(frame)
    try:
        idx = _line_index(dlg, "kick")
        dlg.grid_list.SetSelection(idx)
        dlg._cursor = 2
        dlg._on_grid_key(_Key(wx.WXK_SPACE))
        assert 2 in dlg.pattern.hits["kick"] and "Kick on" in spoken[-1]
        dlg._on_grid_key(_Key(wx.WXK_SPACE))
        assert dlg.pattern.level_of("kick", 2) == LEVEL_ACCENT
        assert "Kick accent" in spoken[-1]
        dlg._on_grid_key(_Key(wx.WXK_SPACE))
        assert dlg.pattern.level_of("kick", 2) == LEVEL_GHOST
        assert "Kick ghost" in spoken[-1]
        dlg._on_grid_key(_Key(wx.WXK_SPACE))
        assert 2 not in dlg.pattern.hits.get("kick", []) and "Kick off" in spoken[-1]
        assert dlg.pattern.level_of("kick", 2) is None
        # The row label reflects the (restored) hit count.
        assert dlg.grid_list.GetString(idx).startswith("Kick: 2 hits")
        # The cursor speaks the dynamic state too.
        dlg._on_grid_key(_Key(wx.WXK_SPACE))  # on
        dlg._on_grid_key(_Key(wx.WXK_SPACE))  # accent
        dlg._on_grid_key(_Key(wx.WXK_LEFT))
        dlg._on_grid_key(_Key(wx.WXK_RIGHT))
        assert spoken[-1].endswith("accent")
    finally:
        dlg.Destroy()


def test_grid_meter_change(frame):
    dlg = _grid_dialog(frame)
    try:
        dlg.beats_choice.SetSelection(6)   # 7 beats
        dlg.unit_choice.SetSelection(2)    # /8
        dlg.grid_choice.SetSelection(1)    # eighth grid
        dlg.bars_choice.SetSelection(0)    # 1 bar
        dlg._on_meter(None)
        assert dlg.pattern.meter_label() == "7/8"
        assert dlg.pattern.steps == 7
        assert dlg._cursor < dlg.pattern.steps  # cursor clamped into range
    finally:
        dlg.Destroy()


def test_grid_none_silences_part(frame):
    dlg = _grid_dialog(frame)
    try:
        dlg.silenced.add("kick")
        assert "kick" not in dlg._effective_pattern().hits  # silenced parts don't render
        kick = dlg.lines[_line_index(dlg, "kick")]
        assert dlg._sample_desc(kick) == "silent"
    finally:
        dlg.Destroy()


def test_grid_save_flow(frame):
    # Simulate the panel's save path without ShowModal.
    dlg = _grid_dialog(frame)
    d = frame.drums_page
    try:
        dlg.grid_list.SetSelection(_line_index(dlg, "tom"))
        dlg._cursor = 1
        dlg._on_grid_key(_Key(wx.WXK_SPACE))
        edited, lines = dlg.pattern, [dict(ln) for ln in dlg.lines]
    finally:
        dlg.Destroy()
    d._pattern = edited
    d._line_meta = lines
    d._rebuild_parts()
    assert 1 in d._pattern.hits["tom"]
    assert "Tom" in d.part_choice.GetItems()


def test_category_filter_and_user_presets(frame):
    from firehawk.practice.patternstore import make_line, make_record, save_user_pattern
    d = frame.drums_page
    all_count = len(d._groove_entries)
    assert all_count == 200  # built-ins with no user patterns yet
    # Filter to the Rock family only.
    d.category_choice.SetSelection(d.category_choice.FindString("Rock"))
    d._rebuild_groove_list()
    assert 0 < len(d._groove_entries) < all_count
    assert all(d.groove_choice.GetString(i).startswith("Rock")
               for i in range(d.groove_choice.GetCount()))
    # Save a mixed-line pattern under a new category; it appears in the list.
    lines = [make_line("kick"), make_line("snare")]
    lines[0]["steps"] = [0, 8]
    from firehawk.practice.patternstore import lines_to_pattern
    pattern = lines_to_pattern(lines, 4, 4, 4, 1, name="My Jam")
    rec = make_record("My Jam", "Prog", 4, 4, 4, 1, lines, pattern)
    save_user_pattern(d._settings, rec)
    d._rebuild_categories()
    d.category_choice.SetSelection(d.category_choice.FindString("Prog"))
    d._rebuild_groove_list()
    assert len(d._groove_entries) == 1 and d._groove_entries[0][0] == "user"
    # Selecting it loads the pattern with composite voices and line-named parts.
    d.groove_choice.SetSelection(0)
    d._on_groove(None)
    assert d._pattern.name == "My Jam"
    assert d._pattern_voices is not None
    assert d._pattern_voices.voice("kick") is not None
    assert "Kick" in d.part_choice.GetItems()


def test_drum_volume_and_fill_style_controls(frame):
    d = frame.drums_page
    assert d.volume_slider.GetValue() == 80
    d.volume_slider.SetValue(40)
    d._on_volume(None)
    assert d.volume_label.GetLabel() == "Drum volume: 40%"
    assert d.fillstyle_choice.GetStringSelection() == "As written"


def test_swing_humanize_controls(frame):
    d = frame.drums_page
    assert d.swing_slider.GetValue() == 0 and d.humanize_slider.GetValue() == 0
    assert "straight" in d.swing_label.GetLabel()
    d.swing_slider.SetValue(60)
    d.humanize_slider.SetValue(30)
    d._on_feel(None)
    assert d.swing_label.GetLabel() == "Swing: 60%"
    assert d.humanize_label.GetLabel() == "Humanize: 30%"
    # The feel values flow into the editor's auditions.
    d.open_editor  # attribute exists
    from firehawk.ui.drumspanel import PatternEditorDialog
    dlg = PatternEditorDialog(d, d._pattern.copy(), d._current_lines(), d._kits_dir(),
                              set(), d.player, d.bpm, dark=True, settings=d._settings,
                              swing=0.6, humanize=0.3)
    try:
        assert dlg._swing == 0.6 and dlg._humanize == 0.3
    finally:
        dlg.Destroy()


def test_app_window_title_is_freedomhawk(frame):
    assert frame.GetTitle() == "FreedomHawk"


def test_grid_char_hook_routes_enter_and_p(frame, monkeypatch, _silence_audio):
    # A dialog steals Enter (default button) before a list's key handler runs, so
    # grid keys route via the dialog char hook (live-tested regression: Enter and P
    # were dead in the grid).
    dlg = _grid_dialog(frame)
    try:
        monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: dlg.grid_list))
        opened = []
        monkeypatch.setattr(dlg, "_sample_options", lambda: opened.append(True))
        dlg._on_char_hook(_Key(wx.WXK_RETURN))
        assert opened == [True]
        dlg._on_char_hook(_Key(ord("P")))
        assert _silence_audio[-1] in ("Kick", "Kick: preview not available")
        # Non-grid keys fall through to normal dialog handling.
        tab = _Key(wx.WXK_TAB)
        tab.skipped = False
        tab.Skip = lambda: setattr(tab, "skipped", True)
        dlg._on_char_hook(tab)
        assert tab.skipped
    finally:
        dlg.Destroy()


def test_drum_library_dialog(frame, _silence_audio):
    from firehawk.practice.patternstore import (lines_to_pattern, make_line,
                                                make_record, save_user_pattern,
                                                user_patterns)
    from firehawk.ui.drumspanel import DrumLibraryDialog
    d = frame.drums_page
    lines = [make_line("kick")]
    lines[0]["steps"] = [0]
    p = lines_to_pattern(lines, 4, 4, 4, 1, "Lib Test")
    save_user_pattern(d._settings, make_record("Lib Test", "Prog", 4, 4, 4, 1, lines, p))
    dlg = DrumLibraryDialog(d, d._settings, dark=True)
    try:
        assert dlg.pattern_list.GetCount() == 1
        assert dlg.pattern_list.GetString(0).startswith("Lib Test")
        # Store-backed delete reflected after reload.
        from firehawk.practice.patternstore import delete_pattern
        delete_pattern(d._settings, "Lib Test")
        dlg._reload()
        assert dlg.pattern_list.GetCount() == 0
        assert user_patterns(d._settings) == []
    finally:
        dlg.Destroy()


def test_midi_import_opens_editor_and_saves(frame, monkeypatch, tmp_path,
                                            _silence_audio):
    # Importing a MIDI file must land straight in the Pattern Editor (live-tested
    # regression: it silently became the current pattern while the Groove dropdown
    # still displayed the old selection, which read as "nothing imported").
    import firehawk.ui.drumspanel as dp
    from firehawk.practice.midifile import pattern_to_midi
    d = frame.drums_page
    midi_path = tmp_path / "beat.mid"
    midi_path.write_bytes(pattern_to_midi(d._pattern, 120, {}))

    class _FakeFileDialog:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ShowModal(self):
            return wx.ID_OK

        def GetPath(self):
            return str(midi_path)

    monkeypatch.setattr(wx, "FileDialog", _FakeFileDialog)
    monkeypatch.setattr(dp.PatternEditorDialog, "ShowModal", lambda self: wx.ID_OK)
    d.import_midi()
    # The editor opened (seeded with the import) and its Save applied the pattern.
    assert d._pattern.name == "MIDI import"
    assert d._line_meta is not None
    assert "Kick" in d.part_choice.GetItems()
    assert any("Imported" in s for s in _silence_audio)


def test_improv_defaults_to_four_bar_cycle(frame, monkeypatch):
    # A 1-bar cycle would put a fill in every bar and wreck the meter (live-tested
    # regression); with Fill every unset, improv must run on a 4-bar cycle.
    import firehawk.ui.drumspanel as dp
    captured = {}

    def fake_improv(p, cycle, cycles, seed=None):
        captured["cycle"], captured["cycles"] = cycle, cycles
        return p

    d = frame.drums_page
    monkeypatch.setattr(dp, "improvised_loop", fake_improv)
    monkeypatch.setattr(d.player, "play", lambda wav: None)
    d.fillstyle_choice.SetSelection(1)  # Improvised
    d._render_and_play()
    assert captured["cycle"] == 4 and captured["cycles"] == 4


def test_kit_sounds_dialog(frame, tmp_path):
    import numpy as np
    import wave as wave_mod
    from firehawk.ui.drumspanel import KitSoundsDialog

    def write_wav(path, n):
        pcm = (0.3 * np.sin(np.arange(n) / 5) * 32767).astype("<i2")
        w = wave_mod.open(str(path), "wb")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(pcm.tobytes()); w.close()

    (tmp_path / "KICK").mkdir()
    write_wav(tmp_path / "KICK" / "a.wav", 4000)
    write_wav(tmp_path / "KICK" / "b.wav", 4000)
    dlg = KitSoundsDialog(frame.drums_page, tmp_path, {}, dark=True)
    try:
        assert dlg.part_choice.GetCount() == 1  # just Kick
        assert dlg.sample_choice.GetCount() == 2
        # Selecting a sample records the choice for that part.
        dlg.sample_choice.SetSelection(1)
        dlg._on_sample(None)
        assert dlg.choices["kick"] == "b.wav"
        dlg._stop_preview()
    finally:
        dlg.Destroy()


def test_fill_every_selector(frame):
    d = frame.drums_page
    assert d._fill_every_bars() is None  # default: pattern as written
    d.fill_choice.SetSelection(4)        # 12 bars
    assert d._fill_every_bars() == 12
    from firehawk.practice import expand_with_fill
    ex = expand_with_fill(d._pattern, 12)
    assert ex.bars == 12


def test_editor_growing_bars_repeats_pattern(frame):
    dlg = _grid_dialog(frame)
    try:
        kicks_before = list(dlg.pattern.hits["kick"])
        dlg.bars_choice.SetSelection(3)  # 4 bars
        dlg._on_meter(None)
        assert dlg.pattern.bars == 4
        # No silent bars: the last bar contains the same kicks as the first.
        per_bar = dlg.pattern.steps // 4
        last_bar = [s - 3 * per_bar for s in dlg.pattern.hits["kick"] if s >= 3 * per_bar]
        assert last_bar == kicks_before
    finally:
        dlg.Destroy()


def test_kit_sounds_guard_for_synth(frame, monkeypatch):
    # With the synth kit active, the button explains itself in a SPOKEN dialog —
    # a status-bar message is inaudible to a screen reader (live-tested regression).
    shown = {}
    monkeypatch.setattr(wx, "MessageBox",
                        lambda msg, *a, **k: shown.setdefault("msg", msg))
    d = frame.drums_page
    assert d._kit_dir is None
    d._on_kit_sounds(None)
    assert "synth kit" in shown["msg"].lower()


def test_metronome_odd_meter_toggle(frame):
    m = frame.metronome_page
    # Standard timing by default: odd-meter controls hidden.
    assert not m.grouping_text.IsShown() and not m.unit_choice.IsShown()
    m.odd_cb.SetValue(True)
    m._on_odd_toggle(None)
    assert m.grouping_text.IsShown() and m.unit_choice.IsShown()
    m.beats_choice.SetSelection(6)  # 7 beats
    m.grouping_text.SetValue("2+2+3")
    m._update_groups()
    assert m._group_starts == {0, 2, 4}
    # Turning it off resets to standard: unit 4, downbeat-only accents, hidden again.
    m.odd_cb.SetValue(False)
    m._on_odd_toggle(None)
    assert not m.grouping_text.IsShown()
    assert m._group_starts == {0}


def test_drums_start_stop_toggles(frame):
    d = frame.drums_page
    from firehawk.practice import NUMPY_AVAILABLE
    if not (NUMPY_AVAILABLE and d.player.available):
        pytest.skip("no audio / numpy")
    d._on_start_stop(None)
    assert d._playing
    assert d.start_button.GetLabel() == "&Stop"
    d._on_start_stop(None)
    assert not d._playing
    assert d.start_button.GetLabel() == "&Start"


def test_every_control_has_accessible_name(frame):
    """The core accessibility guarantee: no control announces as blank."""
    for page in _block_pages(frame):
        for pc in page._params:
            if isinstance(pc.control, wx.CheckBox):
                # A checkbox's accessible name is its own label text.
                assert pc.control.GetLabel().strip(), f"blank checkbox in {page.slot.id}"
            else:
                assert pc.control.GetName().strip(), f"blank name in {page.slot.id}"


def test_no_spin_controls_used(frame):
    """Spin controls read only their value to NVDA, so none should be present."""
    for page in _block_pages(frame):
        for pc in page._params:
            assert not isinstance(pc.control, (wx.SpinCtrl, wx.SpinCtrlDouble)), \
                f"spin control in {page.slot.id} ({pc.spec.symbolic_id})"


def test_integer_param_is_dropdown_and_maps_value(frame):
    # Cabinet @mic is an integer 0..3 -> a dropdown whose selection maps to the value.
    cab = _block_page(frame, "cab")
    mic = next(pc for pc in cab._params if pc.spec.symbolic_id == "@mic")
    assert isinstance(mic.control, wx.Choice)
    mic.control.SetSelection(3)
    cab._on_param("@mic", cab.buffer.model_of("cab").param("@mic").minimum + 3)
    assert frame.buffer.get_param("cab", "@mic") == 3


def test_enable_checkboxes_are_labelled(frame):
    for page in _block_pages(frame):
        if page.enable_cb is not None:
            assert page.enable_cb.GetLabel().strip()


def test_model_swap_rebuilds_params(frame):
    amp = _block_page(frame, "amp")
    amp.model_choice.SetSelection(2)
    amp._on_model(wx.CommandEvent(wx.EVT_CHOICE.typeId, amp.model_choice.GetId()))
    assert frame.buffer.block("amp").model_id == amp._model_ids[2]


def test_param_edit_updates_buffer(frame):
    amp = _block_page(frame, "amp")
    amp._on_param("Bass", 0.33)
    assert frame.buffer.get_param("amp", "Bass") == pytest.approx(0.33)


def test_open_preset_refreshes_pages(frame):
    presets_page = frame.listbook.GetPage(0)
    presets_page.reload()
    assert presets_page.list.GetCount() >= 1  # at least the factory preset
    # Opening the factory preset loads it and lands on the Amp page.
    presets_page.list.SetSelection(0)
    presets_page._open_selected()
    assert frame.buffer.block("amp").model_id is not None


def test_goto_changes_selection(frame):
    frame._goto(3)
    assert frame.listbook.GetSelection() == 3


def test_back_to_presets(frame):
    frame._goto_view("amp")
    assert frame.listbook.GetSelection() != 0
    frame._goto_view("presets")
    assert frame.listbook.GetSelection() == 0


def test_new_preset(frame):
    frame._on_new(None)
    assert frame.buffer.preset.meta["name"] == "New Preset"
    # Lands on the Amp page ready to edit.
    assert frame._view_ids[frame.listbook.GetSelection()] == "amp"


def test_dark_mode_toggle(frame):
    assert frame.dark_mode is True
    frame.dark_item.Check(False)
    frame._on_toggle_dark(None)
    assert frame.dark_mode is False
    frame.dark_item.Check(True)
    frame._on_toggle_dark(None)
    assert frame.dark_mode is True


def test_dirty_tracking_and_clean_after_load(frame):
    assert frame._dirty is False
    # Editing marks dirty via the buffer listener.
    frame.buffer.set_param("amp", "Bass", 0.2)
    assert frame._dirty is True
    # Loading a preset clears the dirty flag.
    frame._on_open_preset(frame.library.factory_presets()[0].preset.copy())
    assert frame._dirty is False


def test_continuous_control_is_slider(frame):
    # Noise Gate Threshold is a real-world dB range -> a slider (not a spin field).
    gate = _block_page(frame, "gate")
    thr = next(pc for pc in gate._params if pc.spec.symbolic_id == "Thresh")
    assert isinstance(thr.control, wx.Slider)
    assert thr.control.GetName().strip()


def test_forced_name_defers_to_child_items():
    """A forced accessible name must apply to the control only, not its children,
    so list items and dropdown options keep their own names (NVDA regression)."""
    from firehawk.ui import accessibility
    if not hasattr(wx, "Accessible"):
        pytest.skip("wx.Accessible not available on this build")
    acc = accessibility._NamedAccessible("Presets")
    assert acc.GetName(0) == (wx.ACC_OK, "Presets")            # the control itself
    assert acc.GetName(1)[0] == wx.ACC_NOT_IMPLEMENTED         # a child item -> native name


def test_sliders_have_forced_accessible_name(frame):
    """Sliders/spins/choices carry a forced accessible object (not just SetName)."""
    if not hasattr(wx, "Accessible"):
        pytest.skip("wx.Accessible not available on this build")
    amp = _block_page(frame, "amp")
    non_checkbox = [pc for pc in amp._params if not isinstance(pc.control, wx.CheckBox)]
    assert non_checkbox, "amp should have sliders"
    for pc in non_checkbox:
        assert hasattr(pc.control, "_firehawk_acc")
