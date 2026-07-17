"""Tests for the preset library (factory + user presets on disk)."""

import pytest

from firehawk.model import ModelCatalog, Preset, PresetLibrary, summarize_preset


@pytest.fixture(scope="module")
def catalog() -> ModelCatalog:
    return ModelCatalog()


@pytest.fixture()
def library(catalog: ModelCatalog, tmp_path) -> PresetLibrary:
    return PresetLibrary(catalog.data_dir, user_dir=tmp_path / "presets")


def test_factory_preset_present(library: PresetLibrary):
    factory = library.factory_presets()
    assert len(factory) >= 1
    assert factory[0].source == "factory"
    assert not factory[0].deletable


def test_save_list_and_delete_user_preset(library: PresetLibrary, catalog: ModelCatalog):
    preset = Preset.load_default(catalog.data_dir)
    path = library.save(preset, "My Metal Tone")
    assert path.exists()

    users = library.user_presets()
    assert any(e.name == "My Metal Tone" and e.deletable for e in users)

    entry = next(e for e in users if e.name == "My Metal Tone")
    library.delete(entry)
    assert not path.exists()
    assert all(e.name != "My Metal Tone" for e in library.user_presets())


def test_save_sanitizes_filename(library: PresetLibrary, catalog: ModelCatalog):
    preset = Preset.load_default(catalog.data_dir)
    path = library.save(preset, 'bad/name:with*chars?')
    assert path.exists()
    # Round-trips and preserves the human name in metadata.
    reloaded = library.user_presets()
    assert any(e.name == "bad/name:with*chars?" for e in reloaded)


def test_summary_lists_signal_chain(catalog: ModelCatalog):
    preset = Preset.load_default(catalog.data_dir)
    text = summarize_preset(preset, catalog)
    assert "Amp:" in text and "Reverb:" in text
    # Uses friendly model display names, not raw symbolic IDs.
    assert "1990 Brit J-800" in text
