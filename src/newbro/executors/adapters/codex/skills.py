from __future__ import annotations

from typing import Any

from newbro.executors.core.capabilities import ExecutorSkill

_DESCRIPTION_CAP = 160


def _coerce_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _project_skill(raw: dict[str, Any]) -> ExecutorSkill | None:
    name = _coerce_str(raw.get("name"))
    path = _coerce_str(raw.get("path"))
    if name is None or path is None:
        return None
    interface = raw.get("interface") if isinstance(raw.get("interface"), dict) else {}
    display_name = _coerce_str(interface.get("displayName")) or name
    short = _coerce_str(interface.get("shortDescription")) or _coerce_str(raw.get("shortDescription"))
    if short is not None:
        description = short
    else:
        long_desc = _coerce_str(raw.get("description")) or ""
        description = long_desc[:_DESCRIPTION_CAP]
    hint = _coerce_str(interface.get("defaultPrompt"))
    enabled = raw.get("enabled") is not False
    return ExecutorSkill(
        name=name,
        display_name=display_name,
        description=description,
        hint=hint,
        path=path,
        enabled=enabled,
    )


def parse_skills_list(result: dict[str, Any]) -> list[ExecutorSkill]:
    """Flatten a codex app-server `skills/list` result into deduped ExecutorSkills."""
    skills: list[ExecutorSkill] = []
    seen: set[tuple[str, str]] = set()
    for group in result.get("data", []) or []:
        if not isinstance(group, dict):
            continue
        for raw in group.get("skills", []) or []:
            if not isinstance(raw, dict):
                continue
            skill = _project_skill(raw)
            if skill is None:
                continue
            key = (skill.name, skill.path)
            if key in seen:
                continue
            seen.add(key)
            skills.append(skill)
    return skills
