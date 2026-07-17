"""Tests for the model catalog and slot-aware queries."""

import pytest

from firehawk.model import ModelCatalog, ValueType
from firehawk.model.catalog import SLOT_LAYOUT


@pytest.fixture(scope="module")
def catalog() -> ModelCatalog:
    return ModelCatalog()


def test_loads_all_models(catalog: ModelCatalog):
    assert len(catalog) == 261
    # Numeric IDs are unique and resolvable.
    assert len({m.numeric_id for m in catalog.all_models()}) == 261


def test_known_model_and_params(catalog: ModelCatalog):
    amp = catalog.model("BritGainJ800")
    assert amp is not None
    assert amp.category == 1
    bass = amp.param("Bass")
    assert bass is not None
    assert bass.value_type is ValueType.CONTINUOUS
    assert bass.minimum == 0.0 and bass.maximum == 1.0


def test_class_a30_fawn_numeric_id(catalog: ModelCatalog):
    amp = catalog.model_by_id(131149)
    assert amp is not None and amp.symbolic_id == "ClassA30Fawn"


def test_value_types_present(catalog: ModelCatalog):
    # A boolean toggle, an integer/enum, and a continuous knob all decode.
    delay = catalog.model("StereoDelay")
    assert delay is not None
    assert delay.param("@enabled").value_type is ValueType.BOOL
    assert delay.param("SyncSelect").value_type is ValueType.INT
    assert delay.param("Time").value_type is ValueType.CONTINUOUS


def test_unnamed_param_falls_back_to_humanized_label(catalog: ModelCatalog):
    delay = catalog.model("StereoDelay")
    mixtype = delay.param("@mixtype")
    assert mixtype is not None
    assert mixtype.name is None
    assert mixtype.display_name == "Mixtype"  # humanized fallback, never blank


def test_catalogs_group_models(catalog: ModelCatalog):
    amps = catalog.catalog("amp")
    assert amps is not None
    group_names = [g.name for g in amps.groups]
    assert "British" in group_names
    british = next(g for g in amps.groups if g.name == "British")
    assert any(m.symbolic_id == "BritGainJ800" for m in british.models)


def test_fx_slots_share_one_catalog(catalog: ModelCatalog):
    fx1 = catalog.models_for_slot("fx1")
    fx3 = catalog.models_for_slot("fx3")
    assert [g.name for g in fx1] == [g.name for g in fx3]
    assert any(g.name == "Delays" for g in fx1)


def test_fixed_slot_returns_single_model(catalog: ModelCatalog):
    groups = catalog.models_for_slot("compressor")
    models = [m for g in groups for m in g.models]
    assert len(models) == 1 and models[0].symbolic_id == "SharcPodFixedComp"


def test_device_filtering_restricts_hd_models(catalog: ModelCatalog):
    """HD amps are restricted to devices [2097156, 2097158]."""
    hd = catalog.model("HD_AmpBritJ800")
    assert hd is not None and hd.devices == (2097156, 2097158)
    assert hd.available_on(2097156) is True
    assert hd.available_on(2097154) is False
    # A model with no restriction is available everywhere.
    assert catalog.model("BritGainJ800").available_on(2097154) is True

    on_restricted = {
        m.symbolic_id
        for g in catalog.models_for_slot("amp", device_id=2097154)
        for m in g.models
    }
    assert "HD_AmpBritJ800" not in on_restricted
    assert "BritGainJ800" in on_restricted


def test_every_slot_id_matches_layout(catalog: ModelCatalog):
    for slot in SLOT_LAYOUT:
        # Does not raise for any declared slot.
        catalog.models_for_slot(slot.id)
