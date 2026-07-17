"""Tests for the preset / edit-buffer state model."""

import pytest

from firehawk.model import EditBuffer, ModelCatalog, Preset


@pytest.fixture(scope="module")
def catalog() -> ModelCatalog:
    return ModelCatalog()


@pytest.fixture()
def buffer(catalog: ModelCatalog) -> EditBuffer:
    return EditBuffer(catalog)


def test_default_preset_loads(buffer: EditBuffer):
    assert buffer.block("amp").model_id == "BritGainJ800"
    assert buffer.get_param("amp", "Bass") == pytest.approx(0.593429)
    assert buffer.block("reverb").model_id == "DarkHall1"


def test_preset_round_trips(catalog: ModelCatalog):
    preset = Preset.load_default(catalog.data_dir)
    restored = Preset.from_json(preset.to_json())
    assert restored.blocks["amp"].values == preset.blocks["amp"].values
    assert restored.meta["name"] == preset.meta["name"]


def test_set_param_clamps_to_range(buffer: EditBuffer):
    # Continuous 0..1 is clamped.
    assert buffer.set_param("amp", "Bass", 5.0) == 1.0
    assert buffer.set_param("amp", "Bass", -3.0) == 0.0
    stored = buffer.set_param("amp", "Bass", 0.25)
    assert stored == pytest.approx(0.25)


def test_set_param_rounds_integers(buffer: EditBuffer):
    # cab @mic is an integer 0..3.
    assert buffer.set_param("cab", "@mic", 2.7) == 3
    assert buffer.set_param("cab", "@mic", 9) == 3


def test_set_enabled_toggles(buffer: EditBuffer):
    buffer.set_enabled("reverb", False)
    assert buffer.block("reverb").enabled is False
    buffer.set_enabled("reverb", True)
    assert buffer.block("reverb").enabled is True


def test_set_model_resets_params_to_defaults(buffer: EditBuffer):
    buffer.set_enabled("fx1", True)
    buffer.set_model("fx1", "StereoDelay")
    block = buffer.block("fx1")
    assert block.model_id == "StereoDelay"
    delay = buffer.catalog.model("StereoDelay")
    # Params initialised to model defaults.
    assert block.get("Time") == delay.param("Time").default
    # Structural attribute preserved across the swap.
    assert block.enabled is True


def test_observer_is_notified(buffer: EditBuffer):
    events = []
    buffer.add_listener(lambda slot, param, value: events.append((slot, param, value)))
    buffer.set_param("amp", "Drive", 0.4)
    assert ("amp", "Drive", pytest.approx(0.4)) in events


def test_model_of_fixed_slot_without_block(catalog: ModelCatalog):
    # Even if a preset omits a fixed block, model_of resolves its built-in model.
    empty = Preset(meta={}, blocks={})
    buffer = EditBuffer(catalog, empty)
    assert buffer.model_of("compressor").symbolic_id == "SharcPodFixedComp"
