from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
from pathlib import Path
from uuid import uuid4

from newbro.executors.core import (
    ExecutorCapabilities,
    ExecutorEvent,
    ExecutorEventType,
)
from newbro.protocol import AgentResumeHandle, ExecutionRun, Task

from .session import AcpxExecutorSession


class AcpxExecutor:
    def __init__(
        self,
        *,
        command: str = "acpx",
        agent: str = "codex",
        permission_mode: str = "approve-all",
        non_interactive_permissions: str = "deny",
        timeout_seconds: float | None = None,
    ) -> None:
        self._command = command
        self._agent = agent
        self._permission_mode = permission_mode
        self._non_interactive_permissions = non_interactive_permissions
        self._timeout_seconds = timeout_seconds
        self._capabilities = ExecutorCapabilities(
            executor_type="acpx",
            supports_resume=True,
            supports_follow_up=True,
            supports_pause=True,
            supports_cancel=True,
            supports_setup=False,
        )
        self._active_runs: dict[str, AcpxExecutorSession] = {}

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> AcpxExecutorSession:
        cwd = Path(workspace_id or os.getcwd()).resolve()
        session_name = f"newbro-{uuid4().hex[:8]}"
        session = AcpxExecutorSession(
            session_id=session_name,
            executor_type="acpx",
            metadata={},
        )
        session.attach(cwd=cwd, session_name=session_name, agent=self._agent)
        return session

    async def cancel_run(self, run_id: str) -> None:
        session = self._active_runs.get(run_id)
        if session is None:
            return
        await self._run_simple_command(
            self._build_base_command(session.cwd)
            + [session.agent, "cancel", "-s", session.session_name]
        )

    async def pause_run(self, run_id: str) -> None:
        # Managed pause matches the current Codex semantics: stop the active
        # prompt now, then rely on the persisted resume handle to continue later.
        await self.cancel_run(run_id)

    async def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: AcpxExecutorSession,
    ):
        self._active_runs[run.run_id] = session
        output_chunks: list[str] = []
        latest_status: str | None = None
        terminal_emitted = False

        try:
            await self._ensure_session(session)
            process = await self._spawn_prompt_process(session, self._build_prompt(task))
            stderr_lines: list[str] = []
            stderr_task = asyncio.create_task(_collect_stderr(process, stderr_lines))

            try:
                if process.stdout is None:
                    raise RuntimeError("ACPX prompt process did not expose stdout.")

                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    parsed = _parse_prompt_event_line(line.decode("utf-8", errors="replace"))
                    if parsed is None:
                        continue

                    event_type = parsed["type"]
                    if event_type == "text_delta":
                        if parsed.get("stream") == "output":
                            text = str(parsed["text"])
                            output_chunks.append(text)
                            yield ExecutorEvent(
                                run_id=run.run_id,
                                session_id=session.session_id,
                                event_type=ExecutorEventType.PROGRESS,
                                message=text,
                                metadata={"source": "acpx", "stream": "output"},
                            )
                        continue

                    if event_type in {"status", "tool_call"}:
                        latest_status = str(parsed["text"])
                        yield ExecutorEvent(
                            run_id=run.run_id,
                            session_id=session.session_id,
                            event_type=ExecutorEventType.PROGRESS,
                            message=latest_status,
                            metadata={"source": "acpx", "event_type": event_type},
                        )
                        continue

                    if event_type == "blocked":
                        if terminal_emitted:
                            continue
                        terminal_emitted = True
                        blocked_message = str(parsed["message"])
                        yield ExecutorEvent(
                            run_id=run.run_id,
                            session_id=session.session_id,
                            event_type=ExecutorEventType.BLOCKED,
                            message=blocked_message,
                            metadata={
                                "source": "acpx",
                                "prompt": blocked_message,
                                "interaction_kind": _classify_blocked_prompt(blocked_message),
                            },
                        )
                        continue

                    if event_type == "error":
                        if terminal_emitted:
                            continue
                        terminal_emitted = True
                        yield ExecutorEvent(
                            run_id=run.run_id,
                            session_id=session.session_id,
                            event_type=ExecutorEventType.FAILED,
                            message=str(parsed["message"]),
                            metadata={"source": "acpx", "code": parsed.get("code") or ""},
                        )
                        continue

                    if event_type == "done":
                        if terminal_emitted:
                            continue
                        terminal_emitted = True
                        stop_reason = str(parsed.get("stop_reason") or "")
                        if stop_reason == "cancelled":
                            yield ExecutorEvent(
                                run_id=run.run_id,
                                session_id=session.session_id,
                                event_type=ExecutorEventType.CANCELLED,
                                message="ACPX prompt cancelled.",
                                metadata={"source": "acpx", "stop_reason": stop_reason},
                            )
                        else:
                            final_text = "".join(output_chunks).strip() or latest_status or f"Completed: {task.title}"
                            yield ExecutorEvent(
                                run_id=run.run_id,
                                session_id=session.session_id,
                                event_type=ExecutorEventType.COMPLETED,
                                message=final_text,
                                metadata={"source": "acpx", "stop_reason": stop_reason},
                            )
                        continue

                returncode = await process.wait()
                await stderr_task
                if returncode != 0 and not terminal_emitted:
                    stderr_text = "\n".join(stderr_lines[-20:]).strip()
                    yield ExecutorEvent(
                        run_id=run.run_id,
                        session_id=session.session_id,
                        event_type=ExecutorEventType.FAILED,
                        message=stderr_text or f"acpx prompt exited with status {returncode}.",
                        metadata={"source": "acpx", "returncode": returncode},
                    )
                    return

                if not terminal_emitted:
                    final_text = "".join(output_chunks).strip() or latest_status or f"Completed: {task.title}"
                    yield ExecutorEvent(
                        run_id=run.run_id,
                        session_id=session.session_id,
                        event_type=ExecutorEventType.COMPLETED,
                        message=final_text,
                        metadata={"source": "acpx", "implicit_done": True},
                    )
            finally:
                if not stderr_task.done():
                    stderr_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stderr_task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield ExecutorEvent(
                run_id=run.run_id,
                session_id=session.session_id,
                event_type=ExecutorEventType.FAILED,
                message=str(exc),
                metadata={"source": "acpx"},
            )
        finally:
            self._active_runs.pop(run.run_id, None)

    def build_resume_handle(self, session: AcpxExecutorSession) -> AgentResumeHandle | None:
        if not session.acpx_record_id:
            return None
        return AgentResumeHandle(
            executor_id="acpx",
            session_handle=session.acpx_record_id,
            opaque={
                "agent": session.agent,
                "cwd": str(session.cwd),
                "sessionName": session.session_name,
                "acpSessionId": session.acp_session_id,
                "agentSessionId": session.agent_session_id,
            },
        )

    async def _ensure_session(self, session: AcpxExecutorSession) -> None:
        stdout = await self._run_simple_command(
            self._build_base_command(session.cwd)
            + [session.agent, "sessions", "ensure", "--name", session.session_name]
        )
        payload = _last_json_object(stdout)
        if not isinstance(payload, dict):
            raise RuntimeError("ACPX did not return JSON session metadata.")
        record_id = _optional_trimmed_string(payload.get("acpxRecordId"))
        if not record_id:
            raise RuntimeError("ACPX session ensure response did not include acpxRecordId.")
        session.update_identity(
            acpx_record_id=record_id,
            acp_session_id=_optional_trimmed_string(payload.get("acpxSessionId")),
            agent_session_id=_optional_trimmed_string(payload.get("agentSessionId")),
        )

    async def _spawn_prompt_process(
        self,
        session: AcpxExecutorSession,
        prompt_text: str,
    ) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(
            *self._build_base_command(session.cwd),
            session.agent,
            "prompt",
            "-s",
            session.session_name,
            "--file",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdin is None:
            raise RuntimeError("ACPX prompt process did not expose stdin.")
        process.stdin.write(prompt_text.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        return process

    def _build_base_command(self, cwd: Path) -> list[str]:
        command = shlex.split(self._command)
        if not command:
            raise RuntimeError("ACPX command is empty.")
        command.extend(["--cwd", str(cwd), "--format", "json", "--json-strict"])
        if self._permission_mode == "approve-all":
            command.append("--approve-all")
        elif self._permission_mode == "approve-reads":
            command.append("--approve-reads")
        elif self._permission_mode == "deny-all":
            command.append("--deny-all")
        if self._non_interactive_permissions:
            command.extend(
                [
                    "--non-interactive-permissions",
                    self._non_interactive_permissions,
                ]
            )
        if self._timeout_seconds is not None:
            command.extend(["--timeout", _format_timeout_seconds(self._timeout_seconds)])
        return command

    async def _run_simple_command(self, command: list[str]) -> str:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise RuntimeError(stderr or stdout.strip() or f"acpx command failed with {process.returncode}.")
        return stdout

    def _build_prompt(self, task: Task) -> str:
        direct_input = _direct_bro_detail_input(task)
        if direct_input is not None:
            return direct_input
        parts = [
            f"Task: {task.title}",
            f"Goal: {task.goal}",
        ]
        persona_prompt = task.metadata.get("executor_persona_prompt")
        if isinstance(persona_prompt, str) and persona_prompt.strip():
            parts.append(f"Executor persona guidance: {persona_prompt.strip()}")
        if task.latest_instruction:
            parts.append(f"Latest instruction: {task.latest_instruction}")
        notes = [
            item.strip()
            for item in task.metadata.get("notes", [])
            if isinstance(item, str) and item.strip()
        ]
        if notes:
            parts.append("Task notes:")
            parts.extend(f"- {note}" for note in notes)
        constraints = [
            item
            for item in task.metadata.get("constraints", [])
            if isinstance(item, dict) and isinstance(item.get("constraint"), str)
        ]
        if constraints:
            parts.append("Execution constraints:")
            for constraint in constraints:
                category = constraint.get("category")
                prefix = f"[{category}] " if isinstance(category, str) and category.strip() else ""
                parts.append(f"- {prefix}{constraint['constraint'].strip()}")
        parts.append("Work inside the current repository and return a concise final result.")
        return "\n".join(parts)


def _direct_bro_detail_input(task: Task) -> str | None:
    if task.metadata.get("source_kind") not in {"bro_detail_text", "bro_detail_ptt"}:
        return None
    text = task.latest_instruction if isinstance(task.latest_instruction, str) else task.goal
    return text.strip() if text.strip() else task.title.strip()


async def _collect_stderr(
    process: asyncio.subprocess.Process,
    sink: list[str],
) -> None:
    if process.stderr is None:
        return
    while True:
        line = await process.stderr.readline()
        if not line:
            return
        sink.append(line.decode("utf-8", errors="replace").rstrip())


def _format_timeout_seconds(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def _last_json_object(stdout: str) -> dict[str, object] | None:
    last: dict[str, object] | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            last = parsed
    return last


def _parse_prompt_event_line(line: str) -> dict[str, object] | None:
    trimmed = line.strip()
    if not trimmed:
        return None

    parsed = _safe_parse_json(trimmed)
    if parsed is None:
        return {"type": "status", "text": trimmed}

    blocked = _parse_blocked_event(parsed)
    if blocked is not None:
        return blocked

    top_level_error = _parse_top_level_error(parsed)
    if top_level_error is not None:
        return top_level_error

    structured_type, payload = _resolve_structured_prompt_payload(parsed)
    if structured_type == "text":
        text = _optional_string(payload.get("content"))
        if text:
            return {"type": "text_delta", "text": text, "stream": "output"}
        return None
    if structured_type == "thought":
        text = _optional_string(payload.get("content"))
        if text:
            return {"type": "text_delta", "text": text, "stream": "thought"}
        return None
    if structured_type in {"agent_message_chunk", "agent_thought_chunk"}:
        text = _resolve_text_chunk(payload)
        if not text:
            return None
        return {
            "type": "text_delta",
            "text": text,
            "stream": "thought" if structured_type == "agent_thought_chunk" else "output",
        }
    if structured_type in {"tool_call", "tool_call_update"}:
        title = _optional_trimmed_string(payload.get("title")) or "tool call"
        status = _optional_trimmed_string(payload.get("status"))
        return {
            "type": "tool_call",
            "text": f"{title} ({status})" if status else title,
        }
    if structured_type == "usage_update":
        used = payload.get("used")
        size = payload.get("size")
        if isinstance(used, (int, float)) and isinstance(size, (int, float)):
            return {"type": "status", "text": f"usage updated: {used}/{size}"}
        return {"type": "status", "text": "usage updated"}
    if structured_type in {
        "available_commands_update",
        "current_mode_update",
        "config_option_update",
        "session_info_update",
        "plan",
        "client_operation",
        "update",
    }:
        text = _resolve_status_text(structured_type, payload)
        if text:
            return {"type": "status", "text": text}
        return None
    if structured_type == "done":
        return {
            "type": "done",
            "stop_reason": _optional_trimmed_string(payload.get("stopReason")),
        }
    if structured_type == "error":
        return {
            "type": "error",
            "message": _optional_trimmed_string(payload.get("message")) or "acpx runtime error",
            "code": _optional_trimmed_string(payload.get("code")),
        }
    return None


def _safe_parse_json(line: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_blocked_event(parsed: dict[str, object]) -> dict[str, object] | None:
    method = _optional_trimmed_string(parsed.get("method"))
    if not method:
        return None
    normalized = method.lower()
    if "request_user_input" not in normalized and not (
        "question" in normalized and "request" in normalized
    ):
        return None
    params = parsed.get("params")
    if not isinstance(params, dict):
        return {"type": "blocked", "message": "Agent is waiting for user input."}
    return {
        "type": "blocked",
        "message": _extract_question_text(params) or "Agent is waiting for user input.",
    }


def _parse_top_level_error(parsed: dict[str, object]) -> dict[str, object] | None:
    error = parsed.get("error")
    if not isinstance(error, dict):
        return None
    return {
        "type": "error",
        "message": _optional_trimmed_string(error.get("message")) or "acpx runtime error",
        "code": str(error.get("code")) if error.get("code") is not None else None,
    }


def _resolve_structured_prompt_payload(
    parsed: dict[str, object],
) -> tuple[str, dict[str, object]]:
    method = _optional_trimmed_string(parsed.get("method"))
    if method == "session/update":
        params = parsed.get("params")
        if isinstance(params, dict):
            update = params.get("update")
            if isinstance(update, dict):
                return _optional_trimmed_string(update.get("sessionUpdate")) or "", update

    session_update = _optional_trimmed_string(parsed.get("sessionUpdate"))
    if session_update:
        return session_update, parsed

    return _optional_trimmed_string(parsed.get("type")) or "", parsed


def _resolve_text_chunk(payload: dict[str, object]) -> str | None:
    content = payload.get("content")
    if isinstance(content, dict):
        content_type = _optional_trimmed_string(content.get("type"))
        if content_type and content_type != "text":
            return None
        text = _optional_string(content.get("text"))
        if text:
            return text
    return _optional_string(payload.get("text"))


def _resolve_status_text(structured_type: str, payload: dict[str, object]) -> str | None:
    if structured_type == "available_commands_update":
        commands = payload.get("availableCommands")
        if isinstance(commands, list) and commands:
            return f"available commands updated ({len(commands)})"
        return "available commands updated"
    if structured_type == "current_mode_update":
        mode = (
            _optional_trimmed_string(payload.get("currentModeId"))
            or _optional_trimmed_string(payload.get("modeId"))
            or _optional_trimmed_string(payload.get("mode"))
        )
        return f"mode updated: {mode}" if mode else "mode updated"
    if structured_type == "config_option_update":
        config_id = _optional_trimmed_string(payload.get("id")) or _optional_trimmed_string(
            payload.get("configOptionId")
        )
        value = (
            _optional_trimmed_string(payload.get("currentValue"))
            or _optional_trimmed_string(payload.get("value"))
            or _optional_trimmed_string(payload.get("optionValue"))
        )
        if config_id and value:
            return f"config updated: {config_id}={value}"
        if config_id:
            return f"config updated: {config_id}"
        return "config updated"
    if structured_type == "session_info_update":
        return (
            _optional_trimmed_string(payload.get("summary"))
            or _optional_trimmed_string(payload.get("message"))
            or "session updated"
        )
    if structured_type == "plan":
        entries = payload.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    content = _optional_trimmed_string(entry.get("content"))
                    if content:
                        return f"plan: {content}"
        return None
    if structured_type == "client_operation":
        parts = [
            _optional_trimmed_string(payload.get("method")),
            _optional_trimmed_string(payload.get("status")),
            _optional_trimmed_string(payload.get("summary")),
        ]
        text = " ".join(part for part in parts if part)
        return text or None
    if structured_type == "update":
        return _optional_trimmed_string(payload.get("update"))
    return None


def _extract_question_text(params: dict[str, object]) -> str | None:
    for key in ("question", "message", "prompt"):
        value = _optional_trimmed_string(params.get(key))
        if value:
            return value
    questions = params.get("questions")
    if isinstance(questions, list):
        for question in questions:
            if isinstance(question, dict):
                prompt = _optional_trimmed_string(question.get("question")) or _optional_trimmed_string(
                    question.get("prompt")
                )
                if prompt:
                    return prompt
    return None


def _classify_blocked_prompt(prompt: str) -> str:
    normalized = prompt.lower()
    if any(token in normalized for token in ("allow", "permission", "approve", "grant access")):
        return "permission"
    if any(token in normalized for token in ("confirm", "confirmation", "are you sure")):
        return "confirmation"
    return "question"


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_trimmed_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None
