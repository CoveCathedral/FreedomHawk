"""Tests for persistent app settings, especially the customizable tab order."""

import firehawk.config as config
from firehawk.config import AppSettings, DEFAULT_PAGE_ORDER, all_views


def test_default_order_puts_practice_tools_last():
    assert DEFAULT_PAGE_ORDER[0] == "presets"
    assert DEFAULT_PAGE_ORDER[-3:] == ["tuner", "metronome", "drums"]


def test_all_view_ids_are_unique():
    ids = [vid for vid, _ in all_views()]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(DEFAULT_PAGE_ORDER)


def test_page_order_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings.json")
    assert AppSettings().page_order() == DEFAULT_PAGE_ORDER


def test_page_order_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings.json")
    saved = ["tuner"] + [v for v in DEFAULT_PAGE_ORDER if v != "tuner"]
    AppSettings().set_page_order(saved)
    assert AppSettings().page_order() == saved  # reloaded from disk


def test_page_order_filters_invalid_and_appends_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings.json")
    s = AppSettings()
    s.set_page_order(["tuner", "bogus", "amp"])  # partial + a stale/unknown id
    order = s.page_order()
    assert "bogus" not in order                  # unknown views dropped
    assert order[:2] == ["tuner", "amp"]         # explicit choices kept, in order
    assert set(order) == set(DEFAULT_PAGE_ORDER)  # every real view still present


def test_corrupt_file_falls_back_to_defaults(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    assert AppSettings().page_order() == DEFAULT_PAGE_ORDER
