"""User-defined persona persistence and session loading.

Personas are stored in ~/.newbro/personas.yaml and loaded into the
blackboard at session start. Runtime status lives on the blackboard only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from newbro.config_home import SYNAPSE_HOME_DIR
from newbro.protocol import Persona

PERSONAS_FILE = SYNAPSE_HOME_DIR / "personas.yaml"
WORKSPACES_DIR = SYNAPSE_HOME_DIR / "workspaces"


@dataclass(slots=True)
class PersonaStore:
    personas: list[Persona] = field(default_factory=list)


def create_workspace(task_id: str) -> str:
    """Create a durable workspace id for a task."""
    return f"ws-{task_id.replace('task-', '')}"


def resolve_workspace(workspace_id: str) -> Path:
    """Resolve a durable workspace id into a local workspace path."""
    resolved_id = (
        f"ws-{workspace_id.replace('task-', '')}"
        if workspace_id.startswith("task-")
        else workspace_id
    )
    candidates = [
        WORKSPACES_DIR / resolved_id,
        Path.cwd() / ".newbro" / "workspaces" / resolved_id,
    ]
    last_error: OSError | None = None
    for workspace in candidates:
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            return workspace
        except OSError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to create a workspace directory.")


def load_personas_from_file(path: Path | None = None) -> list[Persona]:
    """Load persona definitions from YAML. Returns empty list if file missing or malformed."""
    resolved = path or PERSONAS_FILE
    if not resolved.exists():
        return []
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError:
        return []
    return _parse_persona_store_yaml(text).personas


def save_personas_to_file(personas: list[Persona], path: Path | None = None) -> None:
    """Write persona definitions to YAML."""
    resolved = path or PERSONAS_FILE
    _write_persona_store(PersonaStore(personas=personas), resolved)


def _parse_personas_yaml(text: str) -> list[Persona]:
    """Minimal parser for the personas.yaml format we generate."""
    return _parse_persona_store_yaml(text).personas


def _parse_persona_store_yaml(text: str) -> PersonaStore:
    """Minimal parser for the personas.yaml format we generate."""
    store = PersonaStore()
    personas: list[Persona] = []
    current: dict[str, str] = {}
    in_personas_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "personas:":
            in_personas_block = True
            continue
        if not in_personas_block:
            continue
        # New list item: "- name: ..."
        match = re.match(r'^-\s+(\w+):\s*(.*)', stripped)
        if match:
            if current.get("name"):
                personas.append(_build_persona(current))
            current = {match.group(1): _unquote(match.group(2))}
            continue
        # Continuation field: "  key: value"
        match = re.match(r'^(\w+):\s*(.*)', stripped)
        if match:
            current[match.group(1)] = _unquote(match.group(2))
    if current.get("name"):
        personas.append(_build_persona(current))
    store.personas = personas
    return store


def _write_persona_store(store: PersonaStore, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "personas:",
    ]
    for persona in store.personas:
        lines.append(f"  - name: {_yaml_quote(persona.name)}")
        lines.append(f"    persona_id: {_yaml_quote(persona.persona_id)}")
        lines.append(f"    avatar: {_yaml_quote(persona.avatar)}")
        lines.append(f"    base_prompt: {_yaml_quote(persona.base_prompt)}")
        lines.append(
            "    executor_node_id: "
            + (_yaml_quote(persona.executor_node_id) if persona.executor_node_id else "null")
        )
        lines.append(f"    bro_detail_session_id: {_yaml_quote(persona.bro_detail_session_id)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_persona(fields: dict[str, str]) -> Persona:
    name = fields.get("name", "")
    persona_id = fields.get("persona_id") or f"persona-{name.lower().replace(' ', '-')}"
    values = {
        "persona_id": persona_id,
        "name": name,
        "avatar": fields.get("avatar", ""),
        "base_prompt": fields.get("base_prompt", ""),
        "executor_node_id": _optional_value(fields.get("executor_node_id", "")),
    }
    bro_detail_session_id = fields.get("bro_detail_session_id")
    values["bro_detail_session_id"] = bro_detail_session_id or _legacy_bro_detail_session_id(persona_id)
    return Persona(**values)


def _legacy_bro_detail_session_id(persona_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", persona_id).strip("-") or "bro"
    return f"bro-detail-{slug}"


def _unquote(value: str) -> str:
    s = value.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return (
            s[1:-1]
            .replace("\\n", "\n")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1]
    return s


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    return f'"{escaped}"'


def _optional_value(value: str | None) -> str | None:
    if value in (None, "", "null", "~"):
        return None
    return value
