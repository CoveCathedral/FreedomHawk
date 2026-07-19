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
from firehawk.practice.patternstore import build_line_kit
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


def test_sequin_standalone_frame(tmp_path, monkeypatch, _silence_audio):
    # Sequin runs on its own (the tandem standalone entry point), hosting the same
    # DrumsPanel with its own Tools/Settings/Help menu.
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings.json")
    from firehawk.sequin import SequinFrame
    f = SequinFrame()
    try:
        assert isinstance(f.drums, DrumsPanel)
        assert f.drums.groove_choice.GetCount() == 500      # built-ins, fresh settings
        assert f.GetMenuBar().GetMenuCount() == 3            # Tools, Settings, Help
        assert "Sequin" in f.GetTitle()
        # Two tabs down the left: the sequencer and a metronome.
        assert [f.listbook.GetPageText(i) for i in range(2)] == ["Sequin", "Metronome"]
        assert isinstance(f.listbook.GetPage(1), MetronomePanel)
    finally:
        f._on_close(None)                                    # dispose + Destroy path
        import wx as _wx
        _wx.SafeYield()


def test_has_presets_page_and_all_blocks(frame):
    # Presets + Tuner + Metronome + Sequin (drums) pages, plus one per slot.
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


def test_f5_plays_or_stops_the_current_tab(frame, _silence_audio):
    lb = frame.listbook

    def index_of(page):
        return next(i for i in range(lb.GetPageCount()) if lb.GetPage(i) is page)

    if not frame.metronome_page.player.available:
        pytest.skip("no audio device available")
    # F5 (routed here from the frame char hook) toggles the CURRENT tab's transport,
    # wherever focus is — no tabbing to the Start button.
    lb.SetSelection(index_of(frame.metronome_page))
    frame._toggle_current_transport()
    assert frame.metronome_page.is_running()
    frame._toggle_current_transport()
    assert not frame.metronome_page.is_running()
    # The Sequin (drums) tab is the other transport.
    lb.SetSelection(index_of(frame.drums_page))
    frame._toggle_current_transport()
    assert frame.drums_page._playing
    frame._toggle_current_transport()
    assert not frame.drums_page._playing
    # A tab with no Start control says so out loud (the status bar is inaudible), rather
    # than doing nothing.
    lb.SetSelection(0)  # Presets
    _silence_audio.clear()
    frame._toggle_current_transport()
    assert any("Start control" in m for m in _silence_audio)


def test_sequin_f5_toggles_transport(tmp_path, monkeypatch, _silence_audio):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings.json")
    from firehawk.sequin import SequinFrame
    f = SequinFrame()
    try:
        if not f.metronome.player.available:
            pytest.skip("no audio device available")
        f.listbook.SetSelection(1)  # Metronome tab
        f._toggle_current_transport()
        assert f.metronome.is_running()
        f._toggle_current_transport()
        assert not f.metronome.is_running()
    finally:
        f._on_close(None)
        wx.SafeYield()


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
    # 500 grooves in the dropdown; the kit dropdown holds only kits (import is a
    # separate button, so arrowing through kits never springs a folder dialog).
    assert d.groove_choice.GetCount() == 500
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


def test_grid_number_keys_set_chance(frame, _silence_audio):
    # Number keys give the cursor hit a play chance: 5 = 50%, 0 = always. Spoken,
    # in the row label and cursor state, cleared when the hit is turned off.
    spoken = _silence_audio
    dlg = _grid_dialog(frame)
    try:
        idx = _line_index(dlg, "kick")
        dlg.grid_list.SetSelection(idx)
        dlg._cursor = 0                              # the Rock kick has a hit at 0
        dlg._on_grid_key(_Key(ord("5")))
        assert dlg.pattern.chance_of("kick", 0) == 50
        assert "50 percent chance" in spoken[-1]
        assert "(1 by chance)" in dlg.grid_list.GetString(idx)
        assert dlg._state_at("kick", 0).endswith("50 percent chance")
        dlg._on_grid_key(_Key(ord("0")))             # back to always
        assert dlg.pattern.chance_of("kick", 0) is None
        assert "always plays" in spoken[-1]
        # On an empty step, the key explains itself instead of doing nothing.
        dlg._cursor = 1
        dlg._on_grid_key(_Key(ord("5")))
        assert "No hit at this step" in spoken[-1]
        assert dlg.pattern.chance_of("kick", 1) is None
        # Turning a chance hit off clears its chance with it.
        dlg._cursor = 0
        dlg._on_grid_key(_Key(ord("3")))
        for _ in range(4):                           # cycle to off from any dynamic
            if 0 not in dlg.pattern.hits.get("kick", []):
                break
            dlg._on_grid_key(_Key(wx.WXK_SPACE))
        assert 0 not in dlg.pattern.hits.get("kick", [])
        assert not dlg.pattern.probs
    finally:
        dlg.Destroy()


def test_grid_f_cycles_ornaments(frame, _silence_audio):
    # F cycles plain -> flam -> drag -> roll -> plain on the cursor hit, spoken.
    spoken = _silence_audio
    dlg = _grid_dialog(frame)
    try:
        idx = _line_index(dlg, "snare")
        dlg.grid_list.SetSelection(idx)
        dlg._cursor = 4                              # the Rock snare backbeat
        for expect in ("flam", "drag", "roll"):
            dlg._on_grid_key(_Key(ord("F")))
            assert dlg.pattern.ornament_of("snare", 4) == expect
            assert expect in spoken[-1]
        assert "(1 ornamented)" in dlg.grid_list.GetString(idx)
        assert "roll" in dlg._state_at("snare", 4)
        dlg._on_grid_key(_Key(ord("F")))             # back to plain
        assert dlg.pattern.ornament_of("snare", 4) is None
        assert "plain stroke" in spoken[-1]
        # No hit -> the key explains itself.
        dlg._cursor = 1
        dlg._on_grid_key(_Key(ord("F")))
        assert "No hit at this step" in spoken[-1]
    finally:
        dlg.Destroy()


def test_grid_polymeter_line_length(frame, _silence_audio):
    # Minus/plus set a line's own loop length; the cursor stays inside that line's cycle.
    spoken = _silence_audio
    dlg = _grid_dialog(frame)
    try:
        dlg.grid_list.SetSelection(_line_index(dlg, "kick"))
        base = dlg.pattern.steps
        for _ in range(base - 7):
            dlg._on_grid_key(_Key(ord("-")))       # shrink kick to 7 steps
        assert dlg.pattern.line_length("kick") == 7
        assert dlg.pattern.is_polymetric()
        assert "length 7 steps" in spoken[-1]
        assert "length 7 steps" in dlg.grid_list.GetString(_line_index(dlg, "kick"))
        # The cursor is clamped to the kick's 7-step cycle.
        dlg._cursor = 0
        for _ in range(20):
            dlg._on_grid_key(_Key(wx.WXK_RIGHT))
        assert dlg._cursor == 6
        # Lengthening back to the pattern length un-polymeters it.
        for _ in range(base - 7):
            dlg._on_grid_key(_Key(ord("=")))
        assert dlg.pattern.line_length("kick") == base
        assert not dlg.pattern.is_polymetric()
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


def test_grid_change_preserves_meter_and_speaks_it(frame, _silence_audio):
    # The user's report: "change the grid and it locks to 4/4." Changing the grid is a
    # subdivision change, NOT a meter change — the time signature must survive, and a
    # blind user must hear it reaffirmed (never silently assumed to be 4/4).
    dlg = _grid_dialog(frame)
    try:
        dlg.beats_choice.SetSelection(6)   # 7/8 first
        dlg.unit_choice.SetSelection(2)
        dlg._on_meter(None)
        assert dlg.pattern.meter_label() == "7/8"
        _silence_audio.clear()
        dlg.grid_choice.SetSelection(2)    # now change ONLY the grid
        dlg._on_meter(None)
        assert dlg.pattern.meter_label() == "7/8"      # meter did NOT lock to 4/4
        assert "7/8" in _silence_audio[-1]             # and NVDA said so
        assert "4/4" not in _silence_audio[-1]
    finally:
        dlg.Destroy()


def test_line_tuning_shifts_and_speaks(frame, _silence_audio):
    dlg = _grid_dialog(frame)
    try:
        dlg.grid_list.SetSelection(0)
        line = dlg._current_line()
        _silence_audio.clear()
        dlg._change_tune(2)                      # up a whole step
        assert line["tune"] == 2
        assert "tuned +2" in _silence_audio[-1]
        assert "tuned +2" in dlg._row_label(line)
        dlg._change_tune(-3)                      # now a semitone below base
        assert line["tune"] == -1
        # Tuning bakes into the audio: the line's voice actually changes length.
        base_kit = build_line_kit([{**line, "tune": 0}], dlg._kits_dir, base_kit=dlg._base_kit)
        assert len(dlg._line_kit.voice(line["id"])) != len(base_kit.voice(line["id"]))
    finally:
        dlg.Destroy()


def test_line_volume_trims_and_speaks(frame, _silence_audio):
    import numpy as np
    dlg = _grid_dialog(frame)
    try:
        dlg.grid_list.SetSelection(0)
        line = dlg._current_line()
        loud = float(np.max(np.abs(dlg._line_kit.voice(line["id"]))))
        _silence_audio.clear()
        dlg._change_gain(-6)
        assert line["gain_db"] == -6
        assert "-6 dB" in _silence_audio[-1] and "volume" in _silence_audio[-1]
        assert "volume -6 dB" in dlg._row_label(line)
        quiet = float(np.max(np.abs(dlg._line_kit.voice(line["id"]))))
        assert quiet < loud                         # the baked voice really got quieter
    finally:
        dlg.Destroy()


def test_count_in_defers_loop_and_stop_cancels(frame, monkeypatch):
    d = frame.drums_page
    if not d.player.available:
        pytest.skip("no audio on this system")
    monkeypatch.setattr(d._countin_player, "play_voice", lambda buf: True)  # force success
    d.countin_cb.SetValue(True)
    d._start()
    # The loop hasn't started yet — a count-in timer is pending and Stop is showing.
    assert d._playing and d._countin_timer is not None
    assert d.start_button.GetLabel() == "&Stop"
    d._begin_loop()                                  # timer fires
    assert d._countin_timer is None and d.player.playing
    d.stop()
    # Starting the count-in and stopping mid-count cancels the pending loop.
    d.countin_cb.SetValue(True)
    d._start()
    d.stop()
    assert d._countin_timer is None and not d._playing


def test_tempo_trainer_ramp_climbs_and_holds(frame, monkeypatch, _silence_audio):
    d = frame.drums_page
    if not d.player.available:
        pytest.skip("no audio on this system")
    d.tempo_slider.SetValue(100)
    d._trainer_cfg = {"step": 5, "bars": 2, "target": 115, "continuous": False}
    d.trainer_cb.SetValue(True)
    d._playing = True
    d._begin_loop()
    assert d._trainer_bpm == 100                      # starts at the slider tempo
    seq = [d._trainer_bpm]
    for _ in range(6):
        if d._trainer_timer:
            d._trainer_timer.Stop()
            d._trainer_timer = None
        else:
            break                                     # stopped climbing (held at target)
        d._trainer_bump()
        seq.append(d._trainer_bpm)
    assert seq[-1] == 115 and d._trainer_timer is None   # reached and holds at target
    assert d.tempo_slider.GetValue() == 115              # the slider tracked the climb
    d.stop()


def test_tempo_trainer_continuous_passes_target(frame, _silence_audio):
    d = frame.drums_page
    if not d.player.available:
        pytest.skip("no audio on this system")
    d.tempo_slider.SetValue(120)
    d._trainer_cfg = {"step": 10, "bars": 1, "target": 130, "continuous": True}
    d.trainer_cb.SetValue(True)
    d._playing = True
    d._begin_loop()
    for _ in range(3):
        if d._trainer_timer:
            d._trainer_timer.Stop()
            d._trainer_timer = None
        d._trainer_bump()
    assert d._trainer_bpm > 130                        # climbed past the target in endurance mode
    d.stop()
    assert not d._playing and d._trainer_timer is None


def test_song_builder_add_reorder_repeats_render(frame, _silence_audio):
    from firehawk.ui.drumspanel import SongDialog
    d = frame.drums_page
    dlg = SongDialog(d, d, dark=True)
    try:
        # Tabbed layout: Arrange / Add / Songs & Export, plus a display-only timeline.
        assert dlg.notebook.GetPageCount() == 3
        assert not dlg.song_track.AcceptsFocus()
        # Category filter narrows the groove picker (500 grooves is a lot to scroll).
        all_grooves = dlg.groove.GetCount()
        dlg.category.SetStringSelection("Rock")
        dlg._rebuild_grooves()
        assert 0 < dlg.groove.GetCount() < all_grooves
        dlg.category.SetStringSelection("All categories")
        dlg._rebuild_grooves()
        assert dlg.groove.GetCount() == all_grooves

        dlg.groove.SetStringSelection("Rock")
        dlg.repeats.SetSelection(2)          # 3 repeats
        dlg._add()
        dlg.groove.SetStringSelection("Funk")
        dlg.repeats.SetSelection(0)          # 1 repeat
        dlg._add()
        assert [(s["pattern"], s["repeats"]) for s in dlg._sections] == [("Rock", 3), ("Funk", 1)]
        dlg.list.SetSelection(0)
        dlg._change_repeats(1)               # Left/Right edits the selected section
        assert dlg._sections[0]["repeats"] == 4
        # Per-section tempo: the selected section can override the song tempo.
        dlg.sec_tempo.SetStringSelection("150")
        dlg._on_section_tempo(None)
        assert dlg._sections[0]["tempo"] == 150
        dlg._move(1)                         # Alt+Down reorders
        assert [s["pattern"] for s in dlg._sections] == ["Funk", "Rock"]
        # Visual timeline: one block per section, sized by length, selection marked.
        dlg.list.SetSelection(1)
        blocks = dlg._section_blocks()
        assert [label.split(" x")[0] for label, _, _ in blocks] == ["Funk", "Rock"]
        assert blocks[1][2] and not blocks[0][2]           # the selected block is flagged
        assert all(secs > 0 for _, secs, _ in blocks)      # resolved -> real lengths
        if d.player.available:
            assert dlg._render() is not None  # renders the whole song without error
        dlg._remove()
        assert [s["pattern"] for s in dlg._sections] == ["Funk"]
    finally:
        dlg.Destroy()


def test_song_builder_preview_groove_before_adding(frame, _silence_audio):
    from firehawk.ui.drumspanel import SongDialog
    d = frame.drums_page
    if not d.player.available:
        pytest.skip("no audio device available")
    dlg = SongDialog(d, d, dark=True)
    try:
        dlg.groove.SetStringSelection("Rock")
        assert not dlg._previewing
        dlg._preview_groove()                       # audition the selected groove, looping
        assert dlg._previewing and "Stop" in dlg.preview_btn.GetLabel()
        dlg._preview_groove()                       # press again to stop
        assert not dlg._previewing and "Groove" in dlg.preview_btn.GetLabel()
        # Adding a section stops a running preview (it's a section now, not an audition).
        dlg._preview_groove()
        assert dlg._previewing
        dlg._add()
        assert not dlg._previewing and len(dlg._sections) == 1
    finally:
        dlg.Destroy()


def test_song_builder_my_songs_and_plays_once(frame, monkeypatch, _silence_audio):
    from firehawk.ui.drumspanel import SongDialog
    from firehawk.practice.patternstore import make_song_record, save_song
    d = frame.drums_page
    loops = []
    monkeypatch.setattr(d.player, "play", lambda wav, loop=True: loops.append(loop))
    monkeypatch.setattr(d.player, "stop", lambda: None)
    dlg = SongDialog(d, d, dark=True)
    try:
        assert [dlg.notebook.GetPageText(i) for i in range(3)] == ["Arrange", "Add", "My Songs"]
        # My Songs lists saved arrangements; Load restores them into Arrange.
        save_song(d._settings, make_song_record(
            "Verse Jam", [{"pattern": "Rock", "repeats": 2}, {"pattern": "Funk", "repeats": 1}]))
        dlg._rebuild_songs()
        assert dlg.songs_list.GetString(0) == "Verse Jam"
        dlg.songs_list.SetSelection(0)
        dlg._load_selected()
        assert [(s["pattern"], s["repeats"]) for s in dlg._sections] == [("Rock", 2), ("Funk", 1)]
        # A song plays through ONCE (not looped — that was the tail-looping bug) and ends.
        dlg._play_selected()
        assert loops == [False] and dlg._end_timer is not None and dlg._playing
        dlg._song_ended()
        assert not dlg._playing and dlg.play_btn.GetLabel() == "&Play"
        dlg._delete_selected()
        assert dlg.songs_list.GetCount() == 0
    finally:
        dlg._stop()
        dlg.Destroy()


def test_visual_track_toggles_paints_and_persists(frame, _silence_audio):
    dlg = _grid_dialog(frame)
    try:
        vt = dlg.visual_track
        assert not vt.IsShown()                       # off by default
        assert not vt.AcceptsFocus()                  # display-only, never in tab order
        dlg.visual_cb.SetValue(True)
        dlg._on_toggle_visual(None)
        assert vt.IsShown()
        assert dlg._settings.get("show_visual_track") is True   # preference persisted
        vt.refresh_view()
        w, h = vt.GetVirtualSize()
        assert w > vt.GUTTER and h > 0                # sized to the pattern
        # It paints to a DC without error (proves the draw path is sound headless).
        import wx
        bmp = wx.Bitmap(max(1, w), max(1, h))
        mdc = wx.MemoryDC(bmp)
        vt._paint(mdc)
        mdc.SelectObject(wx.NullBitmap)
    finally:
        dlg.Destroy()


def test_visual_track_opens_shown_when_remembered(frame, _silence_audio):
    d = frame.drums_page
    d._settings.set("show_visual_track", True)
    dlg = _grid_dialog(frame)
    try:
        assert dlg.visual_cb.GetValue() and dlg.visual_track.IsShown()
    finally:
        dlg.Destroy()
        d._settings.set("show_visual_track", False)


def test_line_choke_group_cycles_and_speaks(frame, _silence_audio):
    dlg = _grid_dialog(frame)
    try:
        dlg.grid_list.SetSelection(0)
        line = dlg._current_line()
        _silence_audio.clear()
        dlg._cycle_choke()
        assert line["choke"] == 1
        assert "choke group 1" in _silence_audio[-1]
        assert "choke group 1" in dlg._row_label(line)
        # Cycling past the max wraps back to no group.
        from firehawk.practice.patternstore import MAX_CHOKE_GROUP
        for _ in range(MAX_CHOKE_GROUP):
            dlg._cycle_choke()
        assert line["choke"] == 0
        assert "no choke group" in _silence_audio[-1]
    finally:
        dlg.Destroy()


def test_line_tuning_clamps_to_range(frame, _silence_audio):
    dlg = _grid_dialog(frame)
    try:
        dlg.grid_list.SetSelection(0)
        line = dlg._current_line()
        for _ in range(40):                      # push well past the limit
            dlg._change_tune(1)
        assert line["tune"] == 24                 # MAX_TUNE, not higher
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
    assert all_count == 500  # built-ins with no user patterns yet
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


def test_swing_humanize_live_in_the_editor_and_save_with_the_pattern(frame):
    d = frame.drums_page
    # Feel moved OFF the main tab (it declutters + belongs with the groove).
    assert not hasattr(d, "swing_slider") and not hasattr(d, "humanize_slider")
    from firehawk.ui.drumspanel import PatternEditorDialog
    dlg = PatternEditorDialog(d, d._pattern.copy(), d._current_lines(), d._kits_dir(),
                              set(), d.player, d.bpm, dark=True, settings=d._settings)
    try:
        # Sliders start at the groove's own feel (a fresh groove is straight).
        assert dlg.swing_slider.GetValue() == 0 and dlg.humanize_slider.GetValue() == 0
        assert "straight" in dlg.swing_label.GetLabel()
        dlg.swing_slider.SetValue(60)
        dlg.humanize_slider.SetValue(30)
        dlg._on_feel(None)
        # The sliders write straight into the pattern, so feel travels with Save.
        assert dlg.pattern.swing == pytest.approx(0.6)
        assert dlg.pattern.humanize == pytest.approx(0.3)
        assert dlg.swing_label.GetLabel() == "Swing: 60%"
        assert dlg.humanize_label.GetLabel() == "Humanize: 30%"
        # Reopening on that groove restores the sliders from the pattern.
        dlg2 = PatternEditorDialog(d, dlg.pattern.copy(), d._current_lines(), d._kits_dir(),
                                   set(), d.player, d.bpm, dark=True, settings=d._settings)
        try:
            assert dlg2.swing_slider.GetValue() == 60
            assert dlg2.humanize_slider.GetValue() == 30
        finally:
            dlg2.Destroy()
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
        # Preview speaks the line, plus its musical note when the sound is pitched.
        spoken = _silence_audio[-1]
        assert spoken.startswith("Kick")
        # Non-grid keys fall through to normal dialog handling.
        tab = _Key(wx.WXK_TAB)
        tab.skipped = False
        tab.Skip = lambda: setattr(tab, "skipped", True)
        dlg._on_char_hook(tab)
        assert tab.skipped
    finally:
        dlg.Destroy()


def test_kit_change_revoices_saved_pattern(frame):
    # Regression: a saved pattern's follow-global lines must re-voice when the main
    # Kit dropdown changes (they used to be frozen to the kit active at save time).
    import numpy as np
    from firehawk.practice import DrumKit
    from firehawk.practice.patternstore import (lines_to_pattern, make_line,
                                                make_record, save_user_pattern)
    d = frame.drums_page
    lines = [make_line("kick")]
    lines[0]["steps"] = [0, 8]
    p = lines_to_pattern(lines, 4, 4, 4, 1, "Saved")
    save_user_pattern(d._settings, make_record("Saved", "Prog", 4, 4, 4, 1, lines, p))
    d._rebuild_categories(); d._rebuild_groove_list()
    idx = next(i for i, (k, _r) in enumerate(d._groove_entries) if k == "user")
    d.groove_choice.SetSelection(idx); d._on_groove(None)
    before = np.array(d._pattern_voices.voice("kick")[:1500])
    d._set_kit(DrumKit("Fake", {"kick": np.full(1500, 0.6, dtype=np.float32)}))
    after = np.array(d._pattern_voices.voice("kick")[:1500])
    assert not np.array_equal(before, after)


def test_editor_audition_has_feel_but_stays_short(frame):
    # Regression: the editor auditions with swing/humanize (feel) but does NOT apply
    # the Improvised arrangement, which would balloon a 1-bar groove into a ~16-bar,
    # 40-second loop that reads as "slow / feel gone".
    import io
    import wave
    from firehawk.ui.drumspanel import PatternEditorDialog
    d = frame.drums_page
    d.fillstyle_choice.SetSelection(1)  # improvised on the main tab
    dlg = PatternEditorDialog(d, d._pattern.copy(), d._current_lines(), d._kits_dir(),
                              set(), d.player, d.bpm, dark=True, settings=d._settings,
                              base_kit=d._kit)
    try:
        dlg.swing_slider.SetValue(40)
        dlg._on_feel(None)
        assert dlg.pattern.swing == pytest.approx(0.4)  # feel lives on the pattern now
        wav = dlg._render()
        w = wave.open(io.BytesIO(wav))
        secs = w.getnframes() / w.getframerate()
        assert secs == pytest.approx(dlg.pattern.loop_seconds(dlg._bpm), rel=0.05)
        assert secs < 10                               # the pattern's own length, not 40+
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

    def fake_improv(p, cycle, cycles, seed=None, fill_amount=0.0):
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

    # A dedicated kits folder: the dialog scans the kit's SIBLINGS for cross-kit
    # sourcing, so the parent directory must be controlled, not pytest's shared root.
    home = tmp_path / "kits" / "My Kit"
    (home / "KICK").mkdir(parents=True)
    write_wav(home / "KICK" / "a.wav", 4000)
    write_wav(home / "KICK" / "b.wav", 4000)
    dlg = KitSoundsDialog(frame.drums_page, home, {}, dark=True)
    try:
        assert dlg.part_choice.GetCount() == 1  # just Kick
        assert dlg.source_choice.GetCount() == 1  # no siblings -> just this kit
        assert "This kit" in dlg.source_choice.GetString(0)
        assert dlg.sample_choice.GetCount() == 2
        # Selecting a sample records the choice for that part.
        dlg.sample_choice.SetSelection(1)
        dlg._on_sample(None)
        assert dlg.choices["kick"] == "b.wav"
        dlg._stop_preview()
    finally:
        dlg.Destroy()


def test_kit_sounds_cross_kit_sources(frame, tmp_path):
    import numpy as np
    import wave as wave_mod
    from firehawk.ui.drumspanel import KitSoundsDialog

    def write_wav(path, n):
        pcm = (0.3 * np.sin(np.arange(n) / 5) * 32767).astype("<i2")
        w = wave_mod.open(str(path), "wb")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(pcm.tobytes()); w.close()

    kits = tmp_path / "kits"
    home = kits / "Kit A"
    (home / "KICK").mkdir(parents=True)
    write_wav(home / "KICK" / "own.wav", 4000)
    other = kits / "Kit B"
    (other / "KICK").mkdir(parents=True)
    write_wav(other / "KICK" / "loan.wav", 4000)
    (other / "808").mkdir()
    write_wav(other / "808" / "sub.wav", 4000)

    dlg = KitSoundsDialog(frame.drums_page, home, {}, dark=True)
    try:
        # The Part list is the union: Kick (both kits) plus 808 (only Kit B has one).
        assert dlg.part_choice.GetCount() == 2
        # Kick can be sourced from either kit; borrowing stores "Kit/file.wav".
        assert dlg._sources == ["Kit A", "Kit B"]
        dlg.source_choice.SetSelection(1)
        dlg._load_samples()
        dlg.sample_choice.SetSelection(0)
        dlg._on_sample(None)
        assert dlg.choices["kick"] == "Kit B/loan.wav"
        # The 808 part exists only in Kit B, so that's its only source (no dead end).
        dlg.part_choice.SetSelection(1)
        dlg._load_sources()
        assert dlg._sources == ["Kit B"]
        dlg.sample_choice.SetSelection(0)
        dlg._on_sample(None)
        assert dlg.choices["808"] == "Kit B/sub.wav"
        # Reopening with saved hybrid choices lands source AND sample back where saved.
        dlg._stop_preview()
        dlg2 = KitSoundsDialog(frame.drums_page, home, dict(dlg.choices), dark=True)
        try:
            assert dlg2._current_source() == "Kit B"
            files = dlg2._source_files()
            assert files[dlg2.sample_choice.GetSelection()].name == "loan.wav"
        finally:
            dlg2.Destroy()
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
