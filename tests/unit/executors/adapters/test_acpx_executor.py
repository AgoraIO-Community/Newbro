from __future__ import annotations

import stat
import sys
import textwrap

import pytest

from newbro.executors.adapters.acpx import AcpxExecutor
from newbro.protocol import ExecutionRun, Task


def _write_fake_acpx(tmp_path):
    script = tmp_path / "fake-acpx"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            argv = sys.argv[1:]

            if "sessions" in argv and "ensure" in argv:
                name = argv[argv.index("--name") + 1]
                sys.stdout.write(
                    json.dumps(
                        {{
                            "action": "session_ensured",
                            "created": True,
                            "acpxRecordId": f"acpx-record-{{name}}",
                            "acpxSessionId": f"acp-session-{{name}}",
                            "agentSessionId": f"agent-session-{{name}}",
                            "name": name,
                        }}
                    )
                    + "\\n"
                )
                sys.exit(0)

            if "cancel" in argv:
                sys.stdout.write(
                    json.dumps(
                        {{
                            "action": "cancel_result",
                            "acpxRecordId": "acpx-record",
                            "cancelled": True,
                        }}
                    )
                    + "\\n"
                )
                sys.exit(0)

            prompt = sys.stdin.read()
            if "Need confirmation" in prompt:
                sys.stdout.write(
                    json.dumps(
                        {{
                            "method": "question/request_user_input",
                            "params": {{"question": "Need confirmation?"}},
                        }}
                    )
                    + "\\n"
                )
                sys.exit(0)

            if "fail task" in prompt:
                sys.stdout.write(
                    json.dumps(
                        {{
                            "type": "error",
                            "message": "fake failure",
                            "code": "RUN_FAILED",
                        }}
                    )
                    + "\\n"
                )
                sys.exit(0)

            sys.stdout.write(
                json.dumps(
                    {{
                        "method": "session/update",
                        "params": {{
                            "update": {{
                                "sessionUpdate": "tool_call",
                                "title": "Inspect repo",
                                "status": "running",
                                "toolCallId": "tool-1",
                            }}
                        }},
                    }}
                )
                + "\\n"
            )
            sys.stdout.write(
                json.dumps(
                    {{
                        "method": "session/update",
                        "params": {{
                            "update": {{
                                "sessionUpdate": "agent_message_chunk",
                                "content": {{"type": "text", "text": "Done from acpx."}},
                            }}
                        }},
                    }}
                )
                + "\\n"
            )
            sys.stdout.write(json.dumps({{"type": "done", "stopReason": "end_turn"}}) + "\\n")
            sys.exit(0)
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.anyio
async def test_acpx_executor_completes_task_with_fake_cli(tmp_path):
    command = _write_fake_acpx(tmp_path)
    executor = AcpxExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="acpx task",
        goal="Say hello",
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="acpx",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert events[-1].event_type.value == "completed"
    assert events[-1].message == "Done from acpx."
    assert session.acpx_record_id == f"acpx-record-{session.session_name}"
    assert session.acp_session_id == f"acp-session-{session.session_name}"
    assert session.agent_session_id == f"agent-session-{session.session_name}"


def test_acpx_executor_uses_raw_direct_bro_detail_prompt(tmp_path):
    command = _write_fake_acpx(tmp_path)
    executor = AcpxExecutor(command=str(command))
    task = Task(
        task_id="task-direct",
        root_task_id="task-direct",
        title="Hello hello",
        goal="Hello hello",
        latest_instruction="Hello hello",
        metadata={
            "source_kind": "bro_detail_text",
            "executor_persona_prompt": "Execute direct typed and push-to-talk instructions.",
        },
    )

    assert executor._build_prompt(task) == "Hello hello"


@pytest.mark.anyio
async def test_acpx_executor_blocks_when_user_input_is_requested(tmp_path):
    command = _write_fake_acpx(tmp_path)
    executor = AcpxExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-2",
        root_task_id="task-2",
        title="Blocked task",
        goal="Need confirmation",
    )
    run = ExecutionRun(
        run_id="run-2",
        task_id="task-2",
        execution_session_id="exec-2",
        executor_type="acpx",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert events[-1].event_type.value == "blocked"
    assert events[-1].message == "Need confirmation?"


@pytest.mark.anyio
async def test_acpx_executor_reports_failures_from_json_output(tmp_path):
    command = _write_fake_acpx(tmp_path)
    executor = AcpxExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-3",
        root_task_id="task-3",
        title="Failing task",
        goal="fail task",
    )
    run = ExecutionRun(
        run_id="run-3",
        task_id="task-3",
        execution_session_id="exec-3",
        executor_type="acpx",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert events[-1].event_type.value == "failed"
    assert events[-1].message == "fake failure"


@pytest.mark.anyio
async def test_acpx_executor_pause_uses_managed_cancel(tmp_path):
    command = _write_fake_acpx(tmp_path)
    executor = AcpxExecutor(command=str(command))
    assert executor.get_capabilities().supports_pause is True
    seen: list[str] = []

    async def fake_cancel_run(run_id: str) -> None:
        seen.append(run_id)

    executor.cancel_run = fake_cancel_run  # type: ignore[method-assign]

    await executor.pause_run("run-pause")

    assert seen == ["run-pause"]
