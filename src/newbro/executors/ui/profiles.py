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
