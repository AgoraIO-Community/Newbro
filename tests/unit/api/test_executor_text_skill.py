from newbro.api.routes.executor_text import ExecutorTextInstructionRequest


def test_request_accepts_skill_name():
    req = ExecutorTextInstructionRequest(target_persona_id="p", text="hi", skill_name="doc")
    assert req.skill_name == "doc"


def test_request_skill_name_optional():
    req = ExecutorTextInstructionRequest(target_persona_id="p", text="hi")
    assert req.skill_name is None
