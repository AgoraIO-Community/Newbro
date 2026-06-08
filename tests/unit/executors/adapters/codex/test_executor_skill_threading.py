from newbro.executors.adapters.codex.executor import _skill_from_metadata


def test_skill_from_metadata_reads_name_and_path():
    meta = {"skill": {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}}
    assert _skill_from_metadata(meta) == {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}


def test_skill_from_metadata_none_when_absent_or_malformed():
    assert _skill_from_metadata({}) is None
    assert _skill_from_metadata({"skill": {"path": "/x"}}) is None
    assert _skill_from_metadata({"skill": "nope"}) is None
