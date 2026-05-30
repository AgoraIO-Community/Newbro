from __future__ import annotations

import stat
import sys
import textwrap

import pytest

from newbro.executors.adapters.codex import CodexExecutor
from newbro.executors.adapters.codex.client import CodexAppServerClient
from newbro.executors.adapters.codex.client import _build_request_response
from newbro.executors.adapters.codex.executor import _extract_blocked_request
from newbro.protocol import AgentResumeHandle, ExecutionRun, ExecutorTextInstruction, StartCodexTurnCommand, Task


def test_codex_native_user_input_response_uses_answer_text_as_selected_option_label():
    response = _build_request_response(
        method="question/request_user_input",
        params={"questions": [{"id": "output_format", "options": [{"id": "pdf", "label": "Detailed PDF"}]}]},
        action="approve",
        answer_text="Detailed PDF",
    )

    assert response == {"answers": {"output_format": {"answers": ["Detailed PDF"]}}}


def test_codex_native_user_input_response_uses_structured_answers_for_all_questions():
    response = _build_request_response(
        method="item/tool/requestUserInput",
        params={
            "questions": [
                {"id": "audience", "options": [{"id": "leadership", "label": "Boss / leadership"}]},
                {"id": "period", "options": [{"id": "latest", "label": "Latest update"}]},
            ]
        },
        action="approve",
        answer_text="Audience: Boss / leadership; Period: Latest update",
        answers={
            "audience": ["Boss / leadership"],
            "period": ["Latest update"],
        },
    )

    assert response == {
        "answers": {
            "audience": {"answers": ["Boss / leadership"]},
            "period": {"answers": ["Latest update"]},
        }
    }


def test_codex_request_user_input_plan_proposal_preserves_all_questions():
    blocked = _extract_blocked_request(
        "native-questions",
        method="item/tool/requestUserInput",
        params={
            "questions": [
                {
                    "id": "audience",
                    "header": "Audience",
                    "question": "Who is this for?",
                    "options": [{"id": "boss", "label": "Boss / leadership", "description": "Executive summary."}],
                },
                {
                    "id": "period",
                    "header": "Period",
                    "question": "Which period?",
                    "options": [{"id": "latest", "label": "Latest update", "description": "Most recent state."}],
                },
            ]
        },
        plan_mode=True,
    )

    assert blocked is not None
    proposal = blocked["metadata"]["proposal"]
    assert proposal["question_id"] == "audience"
    assert proposal["summary"] == "Who is this for?"
    assert proposal["questions"] == [
        {
            "question_id": "audience",
            "header": "Audience",
            "summary": "Who is this for?",
            "options": [
                {
                    "id": "boss",
                    "label": "Boss / leadership",
                    "description": "Executive summary.",
                    "letter": "A",
                }
            ],
        },
        {
            "question_id": "period",
            "header": "Period",
            "summary": "Which period?",
            "options": [
                {
                    "id": "latest",
                    "label": "Latest update",
                    "description": "Most recent state.",
                    "letter": "A",
                }
            ],
        },
    ]


def _write_fake_codex(
    tmp_path,
    *,
    auth_ok: bool = True,
    account_type: str = "apiKey",
    reject_sorted_thread_list: bool = False,
):
    script = tmp_path / "fake-codex"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            thread_counter = 0
            turn_counter = 0
            auth_ok = {str(auth_ok)}
            account_type = {account_type!r}
            reject_sorted_thread_list = {str(reject_sorted_thread_list)}
            turns_by_thread = {{}}

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                params = msg.get("params", {{}})
                request_id = msg.get("id")
                if method == "initialize":
                    assert params.get("capabilities", {{}}).get("experimentalApi") is True
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send(
                        {{
                            "id": request_id,
                            "result": {{
                                "account": {{"type": account_type}} if auth_ok else None,
                                "requiresOpenaiAuth": True,
                            }},
                        }}
                    )
                elif method == "thread/start":
                    thread_counter += 1
                    thread_id = f"thread-{{thread_counter}}"
                    turns_by_thread.setdefault(thread_id, [])
                    send({{"id": request_id, "result": {{"thread": {{"id": thread_id}}}}}})
                elif method == "thread/fork":
                    original = params.get("threadId")
                    if original == "bad-thread":
                        send({{"id": request_id, "error": {{"message": "bad thread"}}}})
                    else:
                        forked = f"fork-{{original}}"
                        turns_by_thread.setdefault(forked, [])
                        send(
                            {{
                                "id": request_id,
                                "result": {{"thread": {{"id": forked}}}},
                            }}
                        )
                elif method == "thread/resume":
                    thread_id = params.get("threadId")
                    turns_by_thread.setdefault(thread_id, [])
                    send({{"id": request_id, "result": {{"thread": {{"id": thread_id, "status": {{"type": "idle"}}}}}}}})
                elif method == "thread/unsubscribe":
                    send({{"id": request_id, "result": {{"status": "unsubscribed"}}}})
                elif method == "thread/read":
                    thread_id = params.get("threadId")
                    send(
                        {{
                            "id": request_id,
                            "result": {{
                                "thread": {{
                                    "id": thread_id,
                                    "turns": turns_by_thread.get(thread_id, []),
                                }}
                            }},
                        }}
                    )
                elif method == "thread/list":
                    if reject_sorted_thread_list and params.get("sortKey"):
                        send({{"id": request_id, "error": {{"message": "unsupported sort"}}}})
                        continue
                    if params:
                        assert params.get("limit") == 100
                    if params.get("sortKey") is not None:
                        assert params.get("sortKey") == "updated_at"
                        assert params.get("sortDirection") == "desc"
                    cursor = params.get("cursor")
                    if cursor == "page-2":
                        send(
                            {{
                                "id": request_id,
                                "result": {{
                                    "data": [
                                        {{
                                            "id": "import-thread-2",
                                            "sessionId": "import-thread-2",
                                            "preview": "Task: Imported follow-up",
                                            "createdAt": 1779850200,
                                            "updatedAt": 1779850300,
                                            "status": {{"type": "notLoaded"}},
                                            "cwd": "/tmp/imported-workspace",
                                            "path": "/tmp/import-thread-2.jsonl",
                                            "cliVersion": "0.133.0",
                                            "source": "vscode",
                                        }}
                                    ],
                                    "nextCursor": None,
                                }},
                            }}
                        )
                        continue
                    send(
                        {{
                            "id": request_id,
                            "result": {{
                                "data": [
                                    {{
                                        "id": "import-thread-1",
                                        "sessionId": "import-thread-1",
                                        "preview": "Task: Imported work",
                                        "createdAt": 1779850000,
                                        "updatedAt": 1779850100,
                                        "status": {{"type": "notLoaded"}},
                                        "cwd": "/tmp/imported-workspace",
                                        "path": "/tmp/import-thread-1.jsonl",
                                        "cliVersion": "0.133.0",
                                        "source": "vscode",
                                    }}
                                ],
                                "nextCursor": "page-2",
                            }},
                        }}
                    )
                elif method == "collaborationMode/list":
                    send(
                        {{
                            "id": request_id,
                            "result": {{
                                "data": [
                                    {{
                                        "name": "Default",
                                        "mode": "default",
                                        "model": "gpt-5.1-codex",
                                        "reasoning_effort": "medium",
                                    }},
                                    {{
                                        "name": "Plan",
                                        "mode": "plan",
                                        "model": "gpt-5.1-codex",
                                        "reasoning_effort": "medium",
                                    }},
                                ]
                            }},
                        }}
                    )
                elif method == "turn/start":
                    turn_counter += 1
                    turn_id = f"turn-{{turn_counter}}"
                    thread_id = params["threadId"]
                    prompt = params["input"][0]["text"]
                    send(
                        {{
                            "id": request_id,
                            "result": {{"turn": {{"id": turn_id, "status": "inProgress"}}}},
                        }}
                    )
                    if "Need confirmation" in prompt:
                        turns_by_thread.setdefault(thread_id, []).append(
                            {{
                                "id": turn_id,
                                "items": [],
                            }}
                        )
                        send(
                            {{
                                "method": "question/request_user_input",
                                "params": {{
                                    "turnId": turn_id,
                                    "question": "Need confirmation?",
                                }},
                            }}
                        )
                    elif "Need permission" in prompt:
                        turns_by_thread.setdefault(thread_id, []).append(
                            {{
                                "id": turn_id,
                                "items": [],
                            }}
                        )
                        send(
                            {{
                                "id": f"approval-{{turn_id}}",
                                "method": "item/permissions/requestApproval",
                                "params": {{
                                    "threadId": thread_id,
                                    "turnId": turn_id,
                                    "reason": "Need permission to delete that folder.",
                                    "permissions": {{
                                        "fileSystem": {{"writeRoots": ["/tmp"]}}
                                    }},
                                }},
                            }}
                        )
                    elif "fail task" in prompt:
                        turns_by_thread.setdefault(thread_id, []).append(
                            {{
                                "id": turn_id,
                                "items": [],
                            }}
                        )
                        send(
                            {{
                                "method": "turn/completed",
                                "params": {{
                                    "turn": {{
                                        "id": turn_id,
                                        "status": "failed",
                                        "error": {{"message": "fake failure"}},
                                    }}
                                }},
                            }}
                        )
                    elif "Plan mode assert" in prompt:
                        assert params.get("collaborationMode", {{}}).get("mode") == "plan"
                        assert params.get("collaborationMode", {{}}).get("settings", {{}}).get("model") == "gpt-5.1-codex"
                        assert params.get("collaborationMode", {{}}).get("settings", {{}}).get("reasoning_effort") == "medium"
                        turns_by_thread.setdefault(thread_id, []).append(
                            {{
                                "id": turn_id,
                                "items": [
                                    {{
                                        "type": "agentMessage",
                                        "text": "Plan mode was used.",
                                    }}
                                ],
                            }}
                        )
                        send(
                            {{
                                "method": "item/completed",
                                "params": {{
                                    "turnId": turn_id,
                                    "item": {{
                                        "type": "agentMessage",
                                        "text": "Plan mode was used.",
                                    }},
                                }},
                            }}
                        )
                        send(
                            {{
                                "method": "turn/completed",
                                "params": {{
                                    "turn": {{
                                        "id": turn_id,
                                        "status": "completed",
                                        "error": None,
                                    }}
                                }},
                            }}
                        )
                    elif "Default mode assert" in prompt:
                        if params.get("collaborationMode", {{}}).get("mode") != "default":
                            turns_by_thread.setdefault(thread_id, []).append(
                                {{
                                    "id": turn_id,
                                    "items": [],
                                }}
                            )
                            send(
                                {{
                                    "method": "turn/completed",
                                    "params": {{
                                        "turn": {{
                                            "id": turn_id,
                                            "status": "failed",
                                            "error": {{"message": "default collaboration mode missing"}},
                                        }}
                                    }},
                                }}
                            )
                            continue
                        turns_by_thread.setdefault(thread_id, []).append(
                            {{
                                "id": turn_id,
                                "items": [
                                    {{
                                        "type": "agentMessage",
                                        "text": "Default mode was used.",
                                    }}
                                ],
                            }}
                        )
                        send(
                            {{
                                "method": "item/completed",
                                "params": {{
                                    "turnId": turn_id,
                                    "item": {{
                                        "type": "agentMessage",
                                        "text": "Default mode was used.",
                                    }},
                                }},
                            }}
                        )
                        send(
                            {{
                                "method": "turn/completed",
                                "params": {{
                                    "turn": {{
                                        "id": turn_id,
                                        "status": "completed",
                                        "error": None,
                                    }}
                                }},
                            }}
                        )
                    elif "Readback only" in prompt:
                        turns_by_thread.setdefault(thread_id, []).append(
                            {{
                                "id": turn_id,
                                "items": [
                                    {{
                                        "type": "agentMessage",
                                        "text": "Final text from thread read.",
                                    }}
                                ],
                            }}
                        )
                        send(
                            {{
                                "method": "turn/completed",
                                "params": {{
                                    "turn": {{
                                        "id": turn_id,
                                        "status": "completed",
                                        "error": None,
                                    }}
                                }},
                            }}
                        )
                    else:
                        turns_by_thread.setdefault(thread_id, []).append(
                            {{
                                "id": turn_id,
                                "items": [
                                    {{
                                        "type": "agentMessage",
                                        "text": "Done from Codex.",
                                    }}
                                ],
                            }}
                        )
                        send(
                            {{
                                "method": "item/completed",
                                "params": {{
                                    "turnId": turn_id,
                                    "item": {{
                                        "type": "agentMessage",
                                        "text": "Done from Codex.",
                                    }},
                                }},
                            }}
                        )
                        send(
                            {{
                                "method": "turn/completed",
                                "params": {{
                                    "turn": {{
                                        "id": turn_id,
                                        "status": "completed",
                                        "error": None,
                                    }}
                                }},
                            }}
                        )
                elif method == "thread/realtime/start":
                    if params.get("outputModality") != "text" or params.get("threadId") is None:
                        send({{"id": request_id, "error": {{"message": "bad realtime start"}}}})
                    else:
                        send({{"id": request_id, "result": {{}}}})
                elif method == "thread/realtime/appendAudio":
                    audio = params.get("audio", {{}})
                    if not audio.get("data") or not audio.get("sampleRate") or not audio.get("numChannels"):
                        send({{"id": request_id, "error": {{"message": "bad realtime audio"}}}})
                    else:
                        send({{"id": request_id, "result": {{}}}})
                elif method == "thread/realtime/stop":
                    if params.get("threadId") is None:
                        send({{"id": request_id, "error": {{"message": "bad realtime stop"}}}})
                    else:
                        send({{"id": request_id, "result": {{}}}})
                else:
                    send({{"id": request_id, "error": {{"message": f"unknown method: {{method}}"}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_noisy_fake_codex(tmp_path):
    script = tmp_path / "fake-codex-noisy"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                request_id = msg.get("id")
                if method == "initialize":
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send({{"id": request_id, "result": {{"account": {{"type": "apiKey"}}, "requiresOpenaiAuth": True}}}})
                elif method == "thread/start":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1"}}}}}})
                elif method == "turn/start":
                    send({{"id": request_id, "result": {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}}})
                    send({{"method": "item/started", "params": {{"turnId": "turn-1", "item": {{"type": "reasoning"}}}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "webSearch"}}}}}})
                    send({{"method": "item/started", "params": {{"turnId": "turn-1", "item": {{"type": "agentMessage"}}}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "agentMessage", "text": "Useful answer from Codex."}}}}}})
                    send({{"method": "turn/completed", "params": {{"turn": {{"id": "turn-1", "status": "completed", "error": None}}}}}})
                elif method == "thread/read":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1", "turns": [{{"id": "turn-1", "items": [{{"type": "agentMessage", "text": "Useful answer from Codex."}}]}}]}}}}}})
                else:
                    send({{"id": request_id, "error": {{"message": "unknown"}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_content_text_fake_codex(tmp_path):
    script = tmp_path / "fake-codex-content-text"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                request_id = msg.get("id")
                if method == "initialize":
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send({{"id": request_id, "result": {{"account": {{"type": "apiKey"}}, "requiresOpenaiAuth": True}}}})
                elif method == "thread/start":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1"}}}}}})
                elif method == "turn/start":
                    send({{"id": request_id, "result": {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "assistantMessage", "content": [{{"text": "Checked "}}, {{"text": "availability."}}]}}}}}})
                    send({{"method": "turn/completed", "params": {{"turn": {{"id": "turn-1", "status": "completed", "error": None}}}}}})
                elif method == "thread/read":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1", "turns": [{{"id": "turn-1", "items": [{{"type": "assistantMessage", "content": [{{"text": "Checked "}}, {{"text": "availability."}}]}}]}}]}}}}}})
                else:
                    send({{"id": request_id, "error": {{"message": "unknown"}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_lifecycle_only_fake_codex(tmp_path):
    script = tmp_path / "fake-codex-lifecycle-only"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                request_id = msg.get("id")
                if method == "initialize":
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send({{"id": request_id, "result": {{"account": {{"type": "apiKey"}}, "requiresOpenaiAuth": True}}}})
                elif method == "thread/start":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1"}}}}}})
                elif method == "turn/start":
                    send({{"id": request_id, "result": {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}}})
                    send({{"method": "item/started", "params": {{"turnId": "turn-1", "item": {{"type": "reasoning"}}}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "webSearch"}}}}}})
                    send({{"method": "turn/completed", "params": {{"turn": {{"id": "turn-1", "status": "completed", "error": None}}}}}})
                elif method == "thread/read":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1", "turns": [{{"id": "turn-1", "items": [{{"type": "agentMessage", "text": "Final text after lifecycle only."}}]}}]}}}}}})
                else:
                    send({{"id": request_id, "error": {{"message": "unknown"}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_thread_turns_list_fake_codex(tmp_path):
    script = tmp_path / "fake-codex-thread-turns-list"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                params = msg.get("params", {{}})
                request_id = msg.get("id")
                if method == "initialize":
                    assert params.get("capabilities", {{}}).get("experimentalApi") is True
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send({{"id": request_id, "result": {{"account": {{"type": "apiKey"}}, "requiresOpenaiAuth": True}}}})
                elif method == "thread/read":
                    assert params.get("threadId") == "thread-open"
                    assert params.get("includeTurns") is False
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-open", "name": "Open thread"}}}}}})
                elif method == "thread/goal/get":
                    assert params.get("threadId") == "thread-open"
                    send({{"id": request_id, "result": {{"goal": "Open thread goal"}}}})
                elif method == "thread/turns/list":
                    assert params.get("threadId") == "thread-open"
                    assert params.get("limit") == 100
                    assert params.get("sortDirection") == "desc"
                    assert params.get("itemsView") == "full"
                    send(
                        {{
                            "id": request_id,
                            "result": {{
                                "data": [
                                    {{"id": "turn-new", "items": [{{"type": "agentMessage", "text": "New response"}}]}},
                                    {{"id": "turn-old", "items": [{{"type": "event_msg", "payload": {{"type": "user_message", "message": "Old prompt"}}}}]}},
                                ],
                                "nextCursor": "older-turns",
                            }},
                        }}
                    )
                else:
                    send({{"id": request_id, "error": {{"message": "unknown method " + str(method)}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_delta_fake_codex(tmp_path):
    script = tmp_path / "fake-codex-delta"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                request_id = msg.get("id")
                if method == "initialize":
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send({{"id": request_id, "result": {{"account": {{"type": "apiKey"}}, "requiresOpenaiAuth": True}}}})
                elif method == "thread/start":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1"}}}}}})
                elif method == "turn/start":
                    send({{"id": request_id, "result": {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}}})
                    send({{"method": "item/started", "params": {{"turnId": "turn-1", "item": {{"type": "agentMessage", "id": "commentary-1", "text": "", "phase": "commentary"}}}}}})
                    send({{"method": "item/agentMessage/delta", "params": {{"turnId": "turn-1", "itemId": "commentary-1", "delta": "Found UI package.json and checking scripts"}}}})
                    send({{"method": "item/agentMessage/delta", "params": {{"turnId": "turn-1", "itemId": "commentary-1", "delta": "."}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "agentMessage", "id": "commentary-1", "text": "Found UI package.json and checking scripts.", "phase": "commentary"}}}}}})
                    send({{"method": "item/started", "params": {{"turnId": "turn-1", "item": {{"type": "agentMessage", "id": "final-1", "text": "", "phase": "final_answer"}}}}}})
                    send({{"method": "item/agentMessage/delta", "params": {{"turnId": "turn-1", "itemId": "final-1", "delta": "Final answer should not become progress."}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "agentMessage", "id": "final-1", "text": "Final answer should not become progress.", "phase": "final_answer"}}}}}})
                    send({{"method": "turn/completed", "params": {{"turn": {{"id": "turn-1", "status": "completed", "error": None}}}}}})
                elif method == "thread/read":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1", "turns": [{{"id": "turn-1", "items": [{{"type": "agentMessage", "id": "final-1", "text": "Final answer should not become progress.", "phase": "final_answer"}}]}}]}}}}}})
                else:
                    send({{"id": request_id, "error": {{"message": "unknown"}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_plan_fake_codex(tmp_path):
    script = tmp_path / "fake-codex-plan"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                request_id = msg.get("id")
                if method == "initialize":
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send({{"id": request_id, "result": {{"account": {{"type": "apiKey"}}, "requiresOpenaiAuth": True}}}})
                elif method == "thread/start":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1"}}}}}})
                elif method == "collaborationMode/list":
                    send({{"id": request_id, "result": {{"data": [
                        {{"name": "Plan", "mode": "plan", "model": "gpt-5.1-codex", "reasoning_effort": "medium"}},
                        {{"name": "Default", "mode": "default", "model": "gpt-5.1-codex", "reasoning_effort": "medium"}},
                    ]}}}})
                elif method == "turn/start":
                    send({{"id": request_id, "result": {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}}})
                    send({{"method": "turn/plan/updated", "params": {{"turnId": "turn-1", "threadId": "thread-1", "explanation": "Implementation plan", "plan": [{{"step": "Read files", "status": "completed"}}, {{"step": "Patch projection", "status": "inProgress"}}]}}}})
                    send({{"method": "item/plan/delta", "params": {{"turnId": "turn-1", "threadId": "thread-1", "itemId": "plan-1", "delta": "Draft plan"}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "reasoning", "text": "Hidden reasoning must stay hidden."}}}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "plan", "id": "plan-1", "text": "Final plan text."}}}}}})
                    send({{"method": "item/completed", "params": {{"turnId": "turn-1", "item": {{"type": "agentMessage", "id": "final-1", "text": "Done.", "phase": "final_answer"}}}}}})
                    send({{"method": "turn/completed", "params": {{"turn": {{"id": "turn-1", "status": "completed", "error": None}}}}}})
                elif method == "thread/read":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-1", "turns": [{{"id": "turn-1", "items": [{{"type": "agentMessage", "text": "Done.", "phase": "final_answer"}}]}}]}}}}}})
                else:
                    send({{"id": request_id, "error": {{"message": "unknown"}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_counting_fake_codex(tmp_path):
    script = tmp_path / "fake-codex-counting"
    launches = tmp_path / "launches.txt"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import sys
            from pathlib import Path

            Path({str(launches)!r}).write_text(
                Path({str(launches)!r}).read_text() + "launch\\n"
                if Path({str(launches)!r}).exists()
                else "launch\\n"
            )

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\\n")
                sys.stdout.flush()

            for raw in sys.stdin:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                method = msg.get("method")
                params = msg.get("params", {{}})
                request_id = msg.get("id")
                if method == "initialize":
                    send({{"id": request_id, "result": {{"ok": True}}}})
                elif method == "initialized":
                    continue
                elif method == "account/read":
                    send({{"id": request_id, "result": {{"account": {{"type": "apiKey"}}, "requiresOpenaiAuth": True}}}})
                elif method == "thread/list":
                    send({{"id": request_id, "result": {{"data": [], "nextCursor": None}}}})
                elif method == "thread/read":
                    send({{"id": request_id, "result": {{"thread": {{"id": params.get("threadId"), "name": "Shared"}}}}}})
                elif method == "thread/goal/get":
                    send({{"id": request_id, "result": {{"goal": "Shared thread goal"}}}})
                elif method == "thread/turns/list":
                    send({{"id": request_id, "result": {{"data": []}}}})
                elif method == "thread/resume":
                    send({{"id": request_id, "result": {{"thread": {{"id": params.get("threadId"), "status": {{"type": "idle"}}}}}}}})
                elif method == "thread/unsubscribe":
                    send({{"id": request_id, "result": {{"status": "unsubscribed"}}}})
                elif method == "thread/start":
                    send({{"id": request_id, "result": {{"thread": {{"id": "thread-started"}}}}}})
                else:
                    send({{"id": request_id, "error": {{"message": f"unknown method: {{method}}"}}}})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, launches


@pytest.mark.anyio
async def test_codex_executor_completes_task_with_fake_app_server(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Codex task",
        goal="Say hello",
    )
    run = ExecutionRun(
        run_id="run-1",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert events[-1].event_type.value == "completed"
    assert events[-1].message == "Done from Codex."
    assert session.thread_id == "thread-1"
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_refresh_capabilities_leaves_audio_to_executor_node_transcription(tmp_path):
    command = _write_fake_codex(tmp_path, account_type="apiKey")
    executor = CodexExecutor(command=str(command))

    capabilities = await executor.refresh_capabilities()

    assert capabilities.supports_audio_instruction is False
    assert capabilities.supports_follow_up is True


@pytest.mark.anyio
async def test_codex_executor_sends_transcribed_audio_instruction_as_text_follow_up(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    session.thread_id = "thread-1"
    run = ExecutionRun(
        run_id="run-audio",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
    )
    executor._active_runs[run.run_id] = session

    instruction = ExecutorTextInstruction(
        instruction_id="txt-aud-1",
        target_persona_id="forge",
        text="Please use the latest screenshot.",
        source_audio_instruction_id="aud-1",
        metadata={"source": "executor_node_whisper", "transcription_language": "en"},
    )
    events = [event async for event in executor.handle_text_instruction(run, session, instruction)]

    assert [event.event_type.value for event in events] == ["progress", "progress", "completed"]
    assert events[0].message == "Direct instruction sent to Codex."
    assert events[-1].message == "Done from Codex."
    assert events[-1].metadata["source_audio_instruction_id"] == "aud-1"
    assert events[-1].metadata["transcription_language"] == "en"
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_starts_turn_request_without_task_run_or_execution_session(tmp_path):
    command_path = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command_path))
    command = StartCodexTurnCommand(
        request_id="out-turn-1",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="thread-1",
        workspace_id=str(tmp_path),
        instruction=ExecutorTextInstruction(
            instruction_id="txt-1",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Please use the latest screenshot.",
            source_audio_instruction_id="aud-1",
            metadata={"client_request_id": "client-1", "plan_mode": False},
        ),
    )

    events = [event async for event in executor.start_turn_request(command)]

    assert [event.event_type.value for event in events] == ["progress", "progress", "completed"]
    assert events[0].run_id == "out-turn-1"
    assert events[0].session_id == "out-turn-1"
    assert events[0].metadata["client_request_id"] == "client-1"
    assert events[0].metadata["instruction_id"] == "txt-1"
    assert events[-1].message == "Done from Codex."
    assert events[-1].metadata["executor_thread_id"] == "thread-1"
    assert events[-1].metadata["executor_turn_id"] == "turn-1"
    assert events[-1].metadata["source_audio_instruction_id"] == "aud-1"
    # Once the turn completes, the outbound session must not stay registered in
    # _active_runs so a follow-up turn with the same request_id starts cleanly.
    assert "out-turn-1" not in executor._active_runs
    await executor._close_app_session()


@pytest.mark.anyio
async def test_codex_executor_rejects_invalid_turn_request_resume_handle_without_thread_fallback(tmp_path):
    command_path = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command_path))
    command = StartCodexTurnCommand(
        request_id="out-turn-invalid-resume",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        workspace_id=str(tmp_path),
        latest_resume_handle=AgentResumeHandle(
            executor_id="acpx",
            session_handle="acpx-record-1",
        ),
        instruction=ExecutorTextInstruction(
            instruction_id="txt-invalid-resume",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Please use the latest screenshot.",
        ),
    )

    events = [event async for event in executor.start_turn_request(command)]

    assert [event.event_type.value for event in events] == ["failed"]
    assert "valid Codex resume handle" in str(events[0].message)
    assert events[0].metadata.get("executor_thread_id") is None
    await executor._close_app_session()


@pytest.mark.anyio
async def test_codex_executor_rejects_new_thread_turn_request_without_workspace_before_session_creation(monkeypatch):
    executor = CodexExecutor(command="unused")
    create_session_called = False

    async def fail_if_called(workspace_id):
        nonlocal create_session_called
        create_session_called = True
        raise AssertionError("create_session must not be called without workspace_id")

    monkeypatch.setattr(executor, "create_session", fail_if_called)
    command = StartCodexTurnCommand(
        request_id="out-turn-new-no-workspace",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        create_new_thread=True,
        workspace_id=None,
        instruction=ExecutorTextInstruction(
            instruction_id="txt-new-thread",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Start in a new thread.",
        ),
    )

    events = [event async for event in executor.start_turn_request(command)]

    assert [event.event_type.value for event in events] == ["failed"]
    assert "workspace_id" in str(events[0].message)
    assert create_session_called is False


@pytest.mark.anyio
async def test_codex_executor_starts_non_plan_turn_request_with_explicit_default_mode(tmp_path):
    command_path = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command_path))
    command = StartCodexTurnCommand(
        request_id="out-turn-default-mode",
        target_persona_id="forge",
        target_thread_id="public-thread-1",
        thread_id="thread-1",
        workspace_id=str(tmp_path),
        instruction=ExecutorTextInstruction(
            instruction_id="txt-default-mode",
            target_persona_id="forge",
            target_thread_id="public-thread-1",
            text="Default mode assert",
        ),
    )

    events = [event async for event in executor.start_turn_request(command)]

    assert [event.event_type.value for event in events] == ["progress", "progress", "completed"]
    assert events[-1].message == "Default mode was used."
    await executor._close_app_session()


@pytest.mark.anyio
async def test_codex_executor_resolves_plan_collaboration_mode_when_thread_model_missing(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-plan",
        root_task_id="task-plan",
        title="Plan mode assert",
        goal="Plan mode assert",
        metadata={"plan_mode": True},
    )
    run = ExecutionRun(
        run_id="run-plan",
        task_id="task-plan",
        execution_session_id="exec-plan",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["progress", "completed"]
    assert events[-1].message == "Plan mode was used."
    await session.close()
    await executor._close_app_session()


def test_codex_executor_uses_raw_direct_bro_detail_prompt(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    task = Task(
        task_id="task-direct",
        root_task_id="task-direct",
        title="Hello hello",
        goal="Hello hello",
        latest_instruction="Hello hello",
        metadata={
            "source_kind": "bro_detail_ptt",
            "executor_persona_prompt": "Execute direct typed and push-to-talk instructions.",
        },
    )

    assert executor._build_prompt(task) == "Hello hello"


class _CapturingPeer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    async def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.requests.append((method, params))
        return {"turn": {"id": "turn-1"}}


@pytest.mark.anyio
async def test_codex_client_sends_native_plan_collaboration_mode():
    peer = _CapturingPeer()
    client = CodexAppServerClient(peer)  # type: ignore[arg-type]

    await client.turn_start(
        thread_id="thread-1",
        prompt="Plan this first",
        collaboration_mode="plan",
        model="gpt-5.1-codex",
        reasoning_effort="medium",
    )

    _, params = peer.requests[0]
    assert params["collaborationMode"] == {
        "mode": "plan",
        "settings": {
            "model": "gpt-5.1-codex",
            "reasoning_effort": "medium",
            "developer_instructions": None,
        },
    }


@pytest.mark.anyio
async def test_codex_client_sends_default_collaboration_mode_without_model():
    peer = _CapturingPeer()
    client = CodexAppServerClient(peer)  # type: ignore[arg-type]

    await client.turn_start(
        thread_id="thread-1",
        prompt="Use default mode",
        collaboration_mode="default",
        model=None,
    )

    _, params = peer.requests[0]
    assert params["collaborationMode"] == {"mode": "default"}


@pytest.mark.anyio
async def test_codex_client_does_not_silently_drop_requested_collaboration_mode():
    peer = _CapturingPeer()
    client = CodexAppServerClient(peer)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="requires a model"):
        await client.turn_start(
            thread_id="thread-1",
            prompt="Plan this first",
            collaboration_mode="plan",
            model=None,
        )

    assert peer.requests == []


class _CollaborationModeListPeer:
    def __init__(self, *, plan_model: str | None = "gpt-plan-special", plan_effort: str | None = "high") -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._plan_model = plan_model
        self._plan_effort = plan_effort

    async def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.requests.append((method, params))
        if method == "collaborationMode/list":
            return {
                "data": [
                    {
                        "name": "Plan",
                        "mode": "plan",
                        "model": self._plan_model,
                        "reasoning_effort": self._plan_effort,
                    },
                    {
                        "name": "Default",
                        "mode": "default",
                        "model": None,
                        "reasoning_effort": None,
                    },
                ]
            }
        return {}


@pytest.mark.anyio
async def test_collaboration_kwargs_for_turn_resolves_plan_model_when_thread_model_already_captured(tmp_path):
    from pathlib import Path

    from newbro.executors.adapters.codex.executor import _collaboration_kwargs_for_turn
    from newbro.executors.adapters.codex.session import CodexExecutorSession

    peer = _CollaborationModeListPeer()
    client = CodexAppServerClient(peer)  # type: ignore[arg-type]
    session = CodexExecutorSession(
        session_id="codex-session-test",
        executor_type="codex",
        metadata={
            "codex_model": "gpt-default-thread",
            "codex_reasoning_effort": "low",
        },
    )
    session.attach_shared(client=client, cwd=Path(tmp_path))

    kwargs = await _collaboration_kwargs_for_turn(session, plan_mode=True)

    assert kwargs == {
        "collaboration_mode": "plan",
        "model": "gpt-plan-special",
        "reasoning_effort": "high",
    }
    assert any(method == "collaborationMode/list" for method, _ in peer.requests)


@pytest.mark.anyio
async def test_collaboration_kwargs_for_turn_falls_back_to_session_model_when_plan_preset_model_null(tmp_path):
    from pathlib import Path

    from newbro.executors.adapters.codex.executor import _collaboration_kwargs_for_turn
    from newbro.executors.adapters.codex.session import CodexExecutorSession

    peer = _CollaborationModeListPeer(plan_model=None, plan_effort="medium")
    client = CodexAppServerClient(peer)  # type: ignore[arg-type]
    session = CodexExecutorSession(
        session_id="codex-session-chatgpt",
        executor_type="codex",
        metadata={
            "codex_model": "gpt-5.5",
            "codex_reasoning_effort": "high",
        },
    )
    session.attach_shared(client=client, cwd=Path(tmp_path))

    kwargs = await _collaboration_kwargs_for_turn(session, plan_mode=True)

    assert kwargs == {
        "collaboration_mode": "plan",
        "model": "gpt-5.5",
        "reasoning_effort": "medium",
    }
    assert any(method == "collaborationMode/list" for method, _ in peer.requests)


def test_codex_user_input_request_becomes_plan_proposal():
    blocked = _extract_blocked_request(
        request_id="request-1",
        method="item/tool/requestUserInput",
        params={
            "threadId": "thread-1",
            "questions": [
                {
                    "id": "decision",
                    "question": "Pick a plan",
                    "options": [
                        {"label": "Small", "description": "Minimal change"},
                        {"label": "Full", "description": "Complete feature"},
                    ],
                }
            ],
        },
        plan_mode=True,
    )

    assert blocked is not None
    metadata = blocked["metadata"]
    assert metadata["interaction_kind"] == "plan_proposal"
    assert metadata["proposal"] == {
        "questions": [
            {
                "question_id": "decision",
                "header": "Pick a plan",
                "summary": "Pick a plan",
                "options": [
                    {"id": "Small", "label": "Small", "description": "Minimal change", "letter": "A"},
                    {"id": "Full", "label": "Full", "description": "Complete feature", "letter": "B"},
                ],
            }
        ],
        "question_id": "decision",
        "summary": "Pick a plan",
        "options": [
            {"id": "Small", "label": "Small", "description": "Minimal change", "letter": "A"},
            {"id": "Full", "label": "Full", "description": "Complete feature", "letter": "B"},
        ],
    }


@pytest.mark.anyio
async def test_codex_executor_forks_existing_thread_on_follow_up(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    session.thread_id = "thread-1"
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Follow-up task",
        goal="Say hello again",
    )
    run = ExecutionRun(
        run_id="run-2",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert events[-1].event_type.value == "completed"
    assert session.thread_id == "fork-thread-1"
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_reuses_existing_thread_for_direct_thread_resume(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    session.thread_id = "thread-1"
    task = Task(
        task_id="task-1",
        root_task_id="task-1",
        title="Resume selected thread",
        goal="Say hello in the same thread",
        metadata={"codex_thread_mode": "resume", "target_thread_id": "exec-1"},
    )
    run = ExecutionRun(
        run_id="run-resume",
        task_id="task-1",
        execution_session_id="exec-1",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert events[-1].event_type.value == "completed"
    assert session.thread_id == "thread-1"
    assert events[-1].metadata["thread_id"] == "thread-1"
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_subscribes_and_unsubscribes_selected_thread(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))

    session = await executor.subscribe_thread("thread-1", workspace_id=str(tmp_path))
    response = await executor.unsubscribe_thread(session)

    assert session.thread_id == "thread-1"
    assert session.metadata["codex_thread_resumed"] is True
    assert response == {"status": "unsubscribed"}


@pytest.mark.anyio
async def test_codex_executor_blocks_when_user_input_is_requested(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-2",
        root_task_id="task-2",
        title="Blocked task",
        goal="Need confirmation",
    )
    run = ExecutionRun(
        run_id="run-3",
        task_id="task-2",
        execution_session_id="exec-2",
        executor_type="codex",
    )

    event_stream = executor.run_task(run, task, session)
    event = await anext(event_stream)

    assert event.event_type.value == "blocked"
    assert event.message == "Need confirmation?"
    await event_stream.aclose()
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_fails_when_blocked_wait_times_out(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(
        command=str(command),
        blocked_wait_timeout_seconds=0.01,
    )
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-timeout",
        root_task_id="task-timeout",
        title="Blocked task",
        goal="Need confirmation",
    )
    run = ExecutionRun(
        run_id="run-timeout",
        task_id="task-timeout",
        execution_session_id="exec-timeout",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["blocked", "failed"]
    assert events[-1].message == "Timed out waiting for user input."
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_blocks_when_permission_approval_is_requested(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-2b",
        root_task_id="task-2b",
        title="Permission task",
        goal="Need permission",
    )
    run = ExecutionRun(
        run_id="run-2b",
        task_id="task-2b",
        execution_session_id="exec-2b",
        executor_type="codex",
    )

    event_stream = executor.run_task(run, task, session)
    event = await anext(event_stream)

    assert event.event_type.value == "blocked"
    assert event.message == "Need permission to delete that folder."
    assert event.metadata["interaction_kind"] == "permission"
    await event_stream.aclose()
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_reads_final_text_from_thread_when_no_live_assistant_item(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-3",
        root_task_id="task-3",
        title="Readback task",
        goal="Readback only",
    )
    run = ExecutionRun(
        run_id="run-4",
        task_id="task-3",
        execution_session_id="exec-3",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["completed"]
    assert events[-1].event_type.value == "completed"
    assert events[-1].message == "Final text from thread read."
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_reads_thread_history_with_bounded_turns_list(tmp_path):
    command = _write_thread_turns_list_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))

    thread = await executor.read_thread("thread-open")

    assert thread["id"] == "thread-open"
    assert thread["name"] == "Open thread"
    assert thread["goal"] == "Open thread goal"
    assert [turn["id"] for turn in thread["turns"]] == ["turn-old", "turn-new"]


@pytest.mark.anyio
async def test_codex_executor_reuses_one_app_server_for_thread_operations(tmp_path):
    command, launches = _write_counting_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))

    session = await executor.create_session(str(tmp_path))
    await executor.list_threads(str(tmp_path))
    await executor.read_thread("thread-open")
    subscription = await executor.subscribe_thread("thread-open", workspace_id=str(tmp_path))
    response = await executor.unsubscribe_thread(subscription)
    await session.close()
    await executor._close_app_session()

    assert response == {"status": "unsubscribed"}
    assert launches.read_text().splitlines() == ["launch"]


@pytest.mark.anyio
async def test_codex_executor_uses_assistant_content_text_as_progress(tmp_path):
    command = _write_content_text_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-content",
        root_task_id="task-content",
        title="Content task",
        goal="Read content text",
    )
    run = ExecutionRun(
        run_id="run-content",
        task_id="task-content",
        execution_session_id="exec-content",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["progress", "completed"]
    assert events[0].message == "Checked availability."
    assert events[1].message == "Checked availability."
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_ignores_lifecycle_items_without_text(tmp_path):
    command = _write_lifecycle_only_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-lifecycle",
        root_task_id="task-lifecycle",
        title="Lifecycle task",
        goal="Do not synthesize progress",
    )
    run = ExecutionRun(
        run_id="run-lifecycle",
        task_id="task-lifecycle",
        execution_session_id="exec-lifecycle",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["completed"]
    assert events[0].message == "Final text after lifecycle only."
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_streams_commentary_delta_as_progress(tmp_path):
    command = _write_delta_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-delta",
        root_task_id="task-delta",
        title="Delta task",
        goal="Stream commentary progress",
    )
    run = ExecutionRun(
        run_id="run-delta",
        task_id="task-delta",
        execution_session_id="exec-delta",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["progress", "progress", "completed"]
    assert events[0].message == "Found UI package.json and checking scripts"
    assert events[0].metadata["source"] == "codex"
    assert events[0].metadata["phase"] == "commentary"
    assert events[1].message == "Found UI package.json and checking scripts."
    assert events[2].message == "Final answer should not become progress."
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_projects_documented_plan_events_without_reasoning(tmp_path):
    command = _write_plan_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-plan",
        root_task_id="task-plan",
        title="Plan task",
        goal="Display Codex plan",
    )
    run = ExecutionRun(
        run_id="run-plan",
        task_id="task-plan",
        execution_session_id="exec-plan",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["plan", "plan", "completed"]
    assert events[0].metadata["codex_plan_source"] == "turn/plan/updated"
    assert events[0].metadata["codex_plan"] == {
        "explanation": "Implementation plan",
        "steps": [
            {"step": "Read files", "status": "completed"},
            {"step": "Patch projection", "status": "inProgress"},
        ],
    }
    assert all(event.metadata.get("codex_plan_source") != "item/plan/delta" for event in events)
    assert events[1].metadata["codex_plan_source"] == "item/completed"
    assert events[1].metadata["codex_plan"] == {"text": "Final plan text.", "steps": []}
    assert all(event.message != "Hidden reasoning must stay hidden." for event in events)
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_blocks_for_approval_after_plan_mode_final_plan(tmp_path):
    command = _write_plan_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    session.metadata["codex_model"] = "gpt-5.1-codex"
    task = Task(
        task_id="task-plan-mode",
        root_task_id="task-plan-mode",
        title="Plan-mode task",
        goal="Display Codex plan for approval",
        metadata={"plan_mode": True},
    )
    run = ExecutionRun(
        run_id="run-plan-mode",
        task_id="task-plan-mode",
        execution_session_id="exec-plan-mode",
        executor_type="codex",
    )

    events = []
    async for event in executor.run_task(run, task, session):
        events.append(event)

    assert [event.event_type.value for event in events] == ["plan", "plan", "blocked"]
    blocked = events[-1]
    assert blocked.message == "Review the proposed plan before execution."
    assert blocked.metadata["interaction_kind"] == "plan_proposal"
    assert blocked.metadata["blocked_method"] == "item/completed:plan"
    assert blocked.metadata["proposal"] == {
        "summary": "Review the proposed plan before execution.",
        "options": [
            {
                "id": "approved_codex_plan",
                "label": "Run proposed plan",
                "letter": "A",
            }
        ],
        "codex_plan": {"text": "Final plan text.", "steps": []},
    }
    await session.close()
    await executor._close_app_session()


@pytest.mark.anyio
async def test_codex_executor_drops_low_value_item_lifecycle_progress(tmp_path):
    command = _write_noisy_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))
    session = await executor.create_session(str(tmp_path))
    task = Task(
        task_id="task-4",
        root_task_id="task-4",
        title="Noisy task",
        goal="Filter noisy progress",
    )
    run = ExecutionRun(
        run_id="run-5",
        task_id="task-4",
        execution_session_id="exec-4",
        executor_type="codex",
    )

    events = [event async for event in executor.run_task(run, task, session)]

    assert [event.event_type.value for event in events] == ["progress", "completed"]
    assert events[0].message == "Useful answer from Codex."
    assert events[1].message == "Useful answer from Codex."
    await session.close()


@pytest.mark.anyio
async def test_codex_executor_lists_threads_from_app_server(tmp_path):
    command = _write_fake_codex(tmp_path)
    executor = CodexExecutor(command=str(command))

    threads = await executor.list_threads(str(tmp_path))

    assert threads == [
        {
            "id": "import-thread-2",
            "sessionId": "import-thread-2",
            "preview": "Task: Imported follow-up",
            "createdAt": 1779850200,
            "updatedAt": 1779850300,
            "status": {"type": "notLoaded"},
            "cwd": "/tmp/imported-workspace",
            "path": "/tmp/import-thread-2.jsonl",
            "cliVersion": "0.133.0",
            "source": "vscode",
        },
        {
            "id": "import-thread-1",
            "sessionId": "import-thread-1",
            "preview": "Task: Imported work",
            "createdAt": 1779850000,
            "updatedAt": 1779850100,
            "status": {"type": "notLoaded"},
            "cwd": "/tmp/imported-workspace",
            "path": "/tmp/import-thread-1.jsonl",
            "cliVersion": "0.133.0",
            "source": "vscode",
        },
    ]


@pytest.mark.anyio
async def test_codex_executor_falls_back_when_sorted_thread_list_is_unsupported(tmp_path):
    command = _write_fake_codex(tmp_path, reject_sorted_thread_list=True)
    executor = CodexExecutor(command=str(command))

    threads = await executor.list_threads(str(tmp_path))

    assert [thread["id"] for thread in threads] == ["import-thread-2", "import-thread-1"]
