from __future__ import annotations

from newbro.executors.ui.profiles import Profile, ProfileStore


def test_save_then_load_round_trips_profiles(tmp_path):
    path = tmp_path / "menubar.json"
    store = ProfileStore(path=path)
    profiles = [
        Profile(
            id="p1",
            label="Prod",
            base_url="https://synopse.example.com",
            node_id="node-1a2b",
            token="tok-1",
            enabled_executors=["codex"],
            auto_activate=True,
        ),
        Profile(id="p2", label="Staging", base_url="http://127.0.0.1:8000", node_id="node-9z", token="tok-2"),
    ]

    store.save(profiles)
    loaded = store.load()

    assert loaded == profiles
    assert loaded[1].enabled_executors == []
    assert loaded[1].auto_activate is False


def test_load_missing_file_returns_empty_list(tmp_path):
    store = ProfileStore(path=tmp_path / "does-not-exist.json")
    assert store.load() == []
