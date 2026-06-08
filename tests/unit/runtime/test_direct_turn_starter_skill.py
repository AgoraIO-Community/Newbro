from newbro.protocol import ExecutorTextInstruction
from newbro.runtime.direct_turn_starter import DirectTurnStarter


def _starter():
    return DirectTurnStarter(
        session_id="s", blackboard=None, executor_node_manager=None, publish_snapshot=None
    )


def test_outbound_metadata_includes_skill():
    instruction = ExecutorTextInstruction(instruction_id="i1", target_persona_id="p", text="hi")
    meta = _starter()._outbound_metadata(
        source="bro_detail_text",
        instruction=instruction,
        continuity_key="c",
        create_new_thread=True,
        workspace_id=None,
        client_request_id=None,
        execution_session=None,
        latest_resume_handle=None,
        plan_mode=False,
        skill={"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"},
        metadata=None,
    )
    assert meta["skill"] == {"name": "doc", "path": "/x/SKILL.md", "display_name": "Word Docs"}


def test_outbound_metadata_omits_skill_when_none():
    instruction = ExecutorTextInstruction(instruction_id="i1", target_persona_id="p", text="hi")
    meta = _starter()._outbound_metadata(
        source="bro_detail_text", instruction=instruction, continuity_key="c",
        create_new_thread=True, workspace_id=None, client_request_id=None,
        execution_session=None, latest_resume_handle=None, plan_mode=False,
        skill=None, metadata=None,
    )
    assert "skill" not in meta
