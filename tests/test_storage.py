import json

from opensummit.storage import Store
from opensummit.weather import Rules, Spot


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "data.json"

    store = Store(path, Rules())
    store.spots.append(Spot("Jöriseen", 46.75, 9.95))
    store.rules = Rules(max_wind_kmh=40)
    store.channel_id = 123
    store.last["Jöriseen"] = {"weekend": "2026-10-31", "status": "go"}
    store.save()

    loaded = Store(path, Rules())
    assert loaded.spots == [Spot("Jöriseen", 46.75, 9.95)]
    assert loaded.rules.max_wind_kmh == 40
    assert loaded.channel_id == 123
    assert loaded.last == store.last
    assert loaded.find("jöriseen") is not None


def test_migrates_old_locations_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old = {"locations": [{"name": "Joeriseen", "lat": 46.75, "lon": 9.95}]}
    (tmp_path / "locations.json").write_text(json.dumps(old))

    store = Store(tmp_path / "data" / "data.json", Rules())
    assert store.spots == [Spot("Joeriseen", 46.75, 9.95)]
    assert (tmp_path / "data" / "data.json").exists()


def test_unknown_rule_keys_are_ignored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"rules": {"max_day_c": 30, "something_old": 1}}))
    assert Store(path, Rules()).rules.max_day_c == 30
