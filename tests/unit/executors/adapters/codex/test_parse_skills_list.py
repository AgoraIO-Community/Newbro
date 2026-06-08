import json
from pathlib import Path

from newbro.executors.adapters.codex.skills import parse_skills_list

FIXTURE = Path("docs/protocol/fixtures/codex-skills-list-sample.json")


def _result():
    return json.loads(FIXTURE.read_text())


def test_parses_all_skills_flattened():
    skills = parse_skills_list(_result())
    names = {s.name for s in skills}
    assert {"agent-browser", "cc-design", "doc", "openai-docs", "skill-creator"} <= names


def test_display_name_prefers_interface_then_name():
    skills = {s.name: s for s in parse_skills_list(_result())}
    assert skills["doc"].display_name == "Word Docs"
    assert skills["agent-browser"].display_name == "agent-browser"


def test_description_prefers_short_then_toplevel_then_truncated():
    skills = {s.name: s for s in parse_skills_list(_result())}
    assert skills["doc"].description == "Edit and review docx files"
    assert skills["skill-creator"].description == "Create or update a skill"
    assert len(skills["agent-browser"].description) <= 160


def test_hint_from_default_prompt():
    skills = {s.name: s for s in parse_skills_list(_result())}
    assert skills["cc-design"].hint and skills["cc-design"].hint.startswith("Use $cc-design")
    assert skills["agent-browser"].hint is None


def test_path_always_present():
    assert all(s.path for s in parse_skills_list(_result()))


def test_dedupe_by_name_and_path():
    result = _result()
    result["data"].append(dict(result["data"][0]))
    skills = parse_skills_list(result)
    assert len(skills) == len({(s.name, s.path) for s in skills})
