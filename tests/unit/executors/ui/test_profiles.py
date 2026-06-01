from __future__ import annotations

import pytest

from newbro.executors.ui.profiles import (
    ConnectCommandFields,
    Profile,
    ProfileStore,
    conflicting_profile_ids,
    parse_connect_command,
)


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


def test_parse_connect_command_extracts_fields():
    text = (
        "newbro executor run --base-url https://synopse.example.com "
        "--node-id node-1a2b --token tok-xyz "
        "--enabled-executor codex --enabled-executor acpx"
    )
    fields = parse_connect_command(text)
    assert fields == ConnectCommandFields(
        base_url="https://synopse.example.com",
        node_id="node-1a2b",
        token="tok-xyz",
        enabled_executors=["codex", "acpx"],
    )


def test_parse_connect_command_requires_core_fields():
    with pytest.raises(ValueError):
        parse_connect_command("newbro executor run --base-url https://x --node-id n")


def test_conflicting_profile_ids_flags_same_node_and_url():
    profiles = [
        Profile(id="a", label="A", base_url="https://x", node_id="n1", token="t"),
        Profile(id="b", label="B", base_url="https://x", node_id="n1", token="t2"),
        Profile(id="c", label="C", base_url="https://x", node_id="n2", token="t3"),
    ]
    assert conflicting_profile_ids(profiles) == {"a", "b"}
