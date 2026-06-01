from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path

from newbro.config_home import NEWBRO_HOME_DIR

MENUBAR_CONFIG_FILE = NEWBRO_HOME_DIR / "menubar.json"

_SCHEMA_VERSION = 1


@dataclass(slots=True)
class Profile:
    id: str
    label: str
    base_url: str
    node_id: str
    token: str
    enabled_executors: list[str] = field(default_factory=list)
    auto_activate: bool = False


@dataclass(slots=True)
class ConnectCommandFields:
    base_url: str
    node_id: str
    token: str
    enabled_executors: list[str] = field(default_factory=list)


def parse_connect_command(text: str) -> ConnectCommandFields:
    tokens = shlex.split(text)
    base_url = node_id = token = ""
    enabled: list[str] = []
    index = 0
    while index < len(tokens):
        flag = tokens[index]
        if flag in {"--base-url", "--node-id", "--token", "--enabled-executor"} and index + 1 < len(tokens):
            value = tokens[index + 1]
            if flag == "--base-url":
                base_url = value
            elif flag == "--node-id":
                node_id = value
            elif flag == "--token":
                token = value
            else:
                enabled.append(value)
            index += 2
            continue
        index += 1
    missing = [name for name, value in (("--base-url", base_url), ("--node-id", node_id), ("--token", token)) if not value]
    if missing:
        raise ValueError(f"connect command is missing required fields: {', '.join(missing)}")
    return ConnectCommandFields(base_url=base_url, node_id=node_id, token=token, enabled_executors=enabled)


def conflicting_profile_ids(profiles: list[Profile]) -> set[str]:
    seen: dict[tuple[str, str], str] = {}
    conflicts: set[str] = set()
    for profile in profiles:
        key = (profile.base_url, profile.node_id)
        if key in seen:
            conflicts.add(seen[key])
            conflicts.add(profile.id)
        else:
            seen[key] = profile.id
    return conflicts


class ProfileStore:
    def __init__(self, *, path: Path = MENUBAR_CONFIG_FILE) -> None:
        self._path = path

    def load(self) -> list[Profile]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        entries = raw.get("profiles", []) if isinstance(raw, dict) else []
        return [
            Profile(
                id=str(entry["id"]),
                label=str(entry.get("label", "")),
                base_url=str(entry.get("base_url", "")),
                node_id=str(entry.get("node_id", "")),
                token=str(entry.get("token", "")),
                enabled_executors=list(entry.get("enabled_executors", []) or []),
                auto_activate=bool(entry.get("auto_activate", False)),
            )
            for entry in entries
        ]

    def save(self, profiles: list[Profile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _SCHEMA_VERSION, "profiles": [asdict(p) for p in profiles]}
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
