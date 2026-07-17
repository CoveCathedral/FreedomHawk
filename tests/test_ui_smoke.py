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

from firehawk.model import SLOT_LAYOUT
from firehawk.ui.blockpanel import BlockPanel
from firehawk.ui.mainframe import MainFrame
from firehawk.ui.presetspanel import PresetsPanel


@pytest.fixture()
def frame():
    f = MainFrame()
    yield f
    f.Destroy()


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
    # Presets page plus one per slot.
    assert frame.listbook.GetPageCount() == len(SLOT_LAYOUT) + 1
    assert isinstance(frame.listbook.GetPage(0), PresetsPanel)


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


def test_sliders_have_forced_accessible_name(frame):
    """Sliders/spins/choices carry a forced accessible object (not just SetName)."""
    if not hasattr(wx, "Accessible"):
        pytest.skip("wx.Accessible not available on this build")
    amp = _block_page(frame, "amp")
    non_checkbox = [pc for pc in amp._params if not isinstance(pc.control, wx.CheckBox)]
    assert non_checkbox, "amp should have sliders"
    for pc in non_checkbox:
        assert hasattr(pc.control, "_firehawk_acc")
