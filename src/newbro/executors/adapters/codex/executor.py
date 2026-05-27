from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from uuid import uuid4

from newbro.executors.core import (
    ExecutorCapabilities,
    ExecutorEvent,
    ExecutorEventType,
)
from newbro.protocol import AgentResumeHandle, ExecutionRun, ExecutorTextInstruction, Task

from .client import CodexAppServerClient
from .jsonrpc import JsonRpcPeer
from .session import CodexExecutorSession


LOGGER = logging.getLogger(__name__)
CODEX_APP_SERVER_STREAM_LIMIT = 16 * 1024 * 1024
THREAD_LIST_PAGE_LIMIT = 100
THREAD_READ_TURNS_PAGE_LIMIT = 100


class CodexExecutor:
    def __init__(
        self,
        *,
        command: str = "codex",
        blocked_wait_timeout_seconds: float | None = 900.0,
    ) -> None:
        self._command = command
        self._blocked_wait_timeout_seconds = blocked_wait_timeout_seconds
        self._capabilities = ExecutorCapabilities(
            executor_type="codex",
            supports_resume=True,
            supports_follow_up=True,
            supports_audio_instruction=False,
            supports_thread_list=True,
            supports_pause=True,
            supports_cancel=True,
            supports_setup=False,
        )
        self._active_runs: dict[str, CodexExecutorSession] = {}
        self._app_session: CodexExecutorSession | None = None
        self._app_lock = asyncio.Lock()
        self._event_task: asyncio.Task[None] | None = None
        self._turn_event_queues: dict[str, asyncio.Queue[dict[str, object]]] = {}
        self._turn_event_backlog: dict[str, list[dict[str, object]]] = {}
        self._thread_subscription_queues: dict[
            str,
            tuple[str, asyncio.Queue[dict[str, object]]],
        ] = {}

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def refresh_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> CodexExecutorSession:
        cwd = Path(workspace_id or os.getcwd()).resolve()
        app_session = await self._ensure_app_session(cwd)
        session = CodexExecutorSession(
            session_id=f"codex-session-{uuid4().hex[:8]}",
            executor_type="codex",
            metadata={"cwd": str(cwd)},
        )
        session.attach_shared(client=app_session.client, cwd=cwd)
        return session

    async def _ensure_app_session(self, cwd: Path | None = None) -> CodexExecutorSession:
        async with self._app_lock:
            if self._app_session is not None and self._app_session.is_alive():
                self._ensure_event_task(self._app_session)
                return self._app_session
            if self._app_session is not None:
                await self._close_app_session()
            launch_cwd = Path(cwd or os.getcwd()).resolve()
            self._app_session = await self._start_app_session(launch_cwd)
            self._ensure_event_task(self._app_session)
            return self._app_session

    async def _start_app_session(self, cwd: Path) -> CodexExecutorSession:
        process = await asyncio.create_subprocess_exec(
            self._command,
            "app-server",
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=CODEX_APP_SERVER_STREAM_LIMIT,
        )
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Codex app-server did not expose stdio pipes.")
        peer = JsonRpcPeer(process.stdout, process.stdin)
        client = CodexAppServerClient(peer)
        session = CodexExecutorSession(
            session_id=f"codex-session-{uuid4().hex[:8]}",
            executor_type="codex",
            metadata={"cwd": str(cwd)},
        )
        session.attach(process=process, peer=peer, client=client, cwd=cwd)
        await client.initialize()
        account = await client.get_account()
        if account.get("requiresOpenaiAuth") and account.get("account") is None:
            await session.close()
            raise RuntimeError("Codex authentication required.")
        return session

    def _ensure_event_task(self, app_session: CodexExecutorSession) -> None:
        if self._event_task is not None and not self._event_task.done():
            return
        self._event_task = asyncio.create_task(self._dispatch_app_events(app_session))

    async def _close_app_session(self) -> None:
        if self._event_task is not None:
            self._event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._event_task
            self._event_task = None
        if self._app_session is not None:
            await self._app_session.close()
            self._app_session = None
        self._turn_event_queues.clear()
        self._turn_event_backlog.clear()
        self._thread_subscription_queues.clear()

    async def _dispatch_app_events(self, app_session: CodexExecutorSession) -> None:
        try:
            while True:
                event = await app_session.client.next_event()
                self._route_app_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Codex app-server event dispatcher stopped: %s", exc)

    def _route_app_event(self, event: dict[str, object]) -> None:
        params = event.get("params")
        if not isinstance(params, dict):
            params = {}
        turn_id = _event_turn_id(params)
        if turn_id:
            queue = self._turn_event_queues.get(turn_id)
            if queue is not None:
                queue.put_nowait(event)
            else:
                backlog = self._turn_event_backlog.setdefault(turn_id, [])
                backlog.append(event)
                if len(backlog) > 100:
                    del backlog[:-100]
        thread_id = _event_thread_id(params)
        if thread_id:
            for subscribed_thread_id, queue in list(self._thread_subscription_queues.values()):
                if subscribed_thread_id == thread_id:
                    queue.put_nowait(event)

    def _register_turn_queue(self, turn_id: str) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._turn_event_queues[turn_id] = queue
        for event in self._turn_event_backlog.pop(turn_id, []):
            queue.put_nowait(event)
        return queue

    def _unregister_turn_queue(self, turn_id: str, queue: asyncio.Queue[dict[str, object]]) -> None:
        if self._turn_event_queues.get(turn_id) is queue:
            self._turn_event_queues.pop(turn_id, None)

    async def list_threads(self, workspace_id: str | None = None) -> list[dict[str, object]]:
        last_error: Exception | None = None
        for mode in ("sorted_paged", "paged", "legacy"):
            try:
                threads = await self._list_threads_once(workspace_id, mode=mode)
                return _sort_codex_threads(threads)
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "Codex thread/list %s request failed; retrying compatibility path: %s",
                    mode,
                    exc,
                )
        if last_error is not None:
            raise last_error
        return []

    async def _list_threads_once(
        self,
        workspace_id: str | None,
        *,
        mode: str,
    ) -> list[dict[str, object]]:
        session = await self.create_session(workspace_id)
        threads: list[dict[str, object]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            if mode == "legacy":
                response = await session.client.thread_list()
            else:
                response = await session.client.thread_list(
                    cursor=cursor,
                    limit=THREAD_LIST_PAGE_LIMIT,
                    sort_key="updated_at" if mode == "sorted_paged" else None,
                    sort_direction="desc" if mode == "sorted_paged" else None,
                )
            data = response.get("data")
            if not isinstance(data, list):
                raise RuntimeError("Codex thread/list returned an unsupported response shape.")
            next_cursor = response.get("nextCursor")
            LOGGER.info(
                "Codex thread/list page received",
                extra={
                    "mode": mode,
                    "cursor_in": cursor,
                    "cursor_out": next_cursor if isinstance(next_cursor, str) else None,
                    "page_size": len(data),
                },
            )
            for item in data:
                if isinstance(item, dict):
                    threads.append(dict(item))
            if (
                mode == "legacy"
                or not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in seen_cursors
            ):
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return threads

    async def read_thread(self, thread_id: str) -> dict[str, object]:
        session = await self.create_session(None)
        response = await session.client.thread_read(
            thread_id=thread_id,
            include_turns=False,
        )
        turns_response = await session.client.thread_turns_list(
            thread_id=thread_id,
            limit=THREAD_READ_TURNS_PAGE_LIMIT,
            sort_direction="desc",
            items_view="full",
        )
        thread = response.get("thread")
        if not isinstance(thread, dict):
            raise RuntimeError("Codex thread/read returned an unsupported response shape.")
        turns_data = turns_response.get("data")
        if not isinstance(turns_data, list):
            raise RuntimeError("Codex thread/turns/list returned an unsupported response shape.")
        turns = [dict(item) for item in turns_data if isinstance(item, dict)]
        thread = dict(thread)
        thread["turns"] = list(reversed(turns))
        return thread

    async def subscribe_thread(
        self,
        thread_id: str,
        *,
        workspace_id: str | None = None,
    ) -> CodexExecutorSession:
        session = await self.create_session(workspace_id)
        await session.client.thread_resume(thread_id=thread_id)
        session.thread_id = thread_id
        session.metadata["codex_thread_resumed"] = True
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._thread_subscription_queues[session.session_id] = (thread_id, queue)
        return session

    async def unsubscribe_thread(self, session: CodexExecutorSession) -> dict[str, object]:
        if not session.thread_id:
            return {"status": "notLoaded"}
        self._thread_subscription_queues.pop(session.session_id, None)
        still_interested = any(
            subscribed_thread_id == session.thread_id
            for subscribed_thread_id, _ in self._thread_subscription_queues.values()
        )
        if still_interested:
            await session.close()
            return {"status": "unsubscribed"}
        response = await session.client.thread_unsubscribe(thread_id=session.thread_id)
        await session.close()
        return response

    async def next_thread_event(self, session: CodexExecutorSession) -> dict[str, object]:
        subscription = self._thread_subscription_queues.get(session.session_id)
        if subscription is None:
            raise RuntimeError("Codex selected-thread subscription is not active.")
        _, queue = subscription
        return await queue.get()

    async def cancel_run(self, run_id: str) -> None:
        session = self._active_runs.pop(run_id, None)
        if session is not None:
            await session.close()

    async def pause_run(self, run_id: str) -> None:
        # Managed pause: we end the current live app-server process and later
        # resume through the persisted thread resume handle rather than relying
        # on a native in-place pause primitive from Codex.
        await self.cancel_run(run_id)

    async def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: CodexExecutorSession,
    ):
        self._active_runs[run.run_id] = session
        try:
            async with session.turn_lock:
                prompt = self._build_prompt(task)
                thread_id = await self._ensure_thread(
                    session,
                    fork_existing=task.metadata.get("codex_thread_mode") != "resume",
                )
                turn = await session.client.turn_start(thread_id=thread_id, prompt=prompt)
                turn_id = _get_nested(turn, "turn", "id")
                if not isinstance(turn_id, str):
                    raise RuntimeError("Codex turn/start did not return a turn id.")
                async for event in self._stream_turn_events(
                    run,
                    session,
                    turn_id,
                    completed_message=f"Completed: {task.title}",
                ):
                    yield event
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield ExecutorEvent(
                run_id=run.run_id,
                session_id=session.session_id,
                event_type=ExecutorEventType.FAILED,
                message=str(exc),
                metadata={"stderr": session.stderr_text()},
            )
        finally:
            self._active_runs.pop(run.run_id, None)

    async def handle_text_instruction(
        self,
        run: ExecutionRun,
        session: CodexExecutorSession,
        instruction: ExecutorTextInstruction,
    ):
        active_session = self._active_runs.get(run.run_id)
        if active_session is not session:
            raise RuntimeError("Codex follow-up instructions require an active run session.")
        if not session.thread_id:
            raise RuntimeError("Codex thread is not ready for follow-up instructions.")
        text = instruction.text.strip()
        if not text:
            raise RuntimeError("Follow-up instruction text is empty.")
        async with session.turn_lock:
            turn = await session.client.turn_start(
                thread_id=session.thread_id,
                prompt=(
                    "Direct user follow-up instruction:\n"
                    f"{text}\n\n"
                    "Act on this instruction in the existing execution thread."
                ),
            )
            turn_id = _get_nested(turn, "turn", "id")
            if not isinstance(turn_id, str):
                raise RuntimeError("Codex turn/start did not return a turn id.")
            event_metadata = {
                **dict(instruction.metadata),
                "instruction_id": instruction.instruction_id,
                "source_audio_instruction_id": instruction.source_audio_instruction_id or "",
                "turn_id": turn_id,
            }
            yield ExecutorEvent(
                run_id=run.run_id,
                session_id=session.session_id,
                event_type=ExecutorEventType.PROGRESS,
                message="Direct instruction sent to Codex.",
                metadata={
                    **event_metadata,
                    "thread_id": session.thread_id,
                    "source": "codex",
                },
            )
            async for event in self._stream_turn_events(
                run,
                session,
                turn_id,
                completed_message="Codex completed the direct instruction.",
                extra_metadata=event_metadata,
            ):
                yield event

    async def _stream_turn_events(
        self,
        run: ExecutionRun,
        session: CodexExecutorSession,
        turn_id: str,
        *,
        completed_message: str,
        extra_metadata: dict[str, object] | None = None,
    ):
        extra = dict(extra_metadata or {})
        last_assistant_message: str | None = None
        assistant_item_phases: dict[str, str | None] = {}
        assistant_item_text: dict[str, str] = {}
        assistant_item_emitted_text: dict[str, str] = {}
        event_queue = self._register_turn_queue(turn_id)
        try:
            while True:
                event = await event_queue.get()
                method = str(event.get("method", ""))
                params = event.get("params")
                if not isinstance(params, dict):
                    continue

                if method == "turn/completed":
                    completed_turn = params.get("turn")
                    if isinstance(completed_turn, dict) and completed_turn.get("id") != turn_id:
                        continue
                    status = _get_nested(params, "turn", "status")
                    if status == "completed":
                        if not last_assistant_message:
                            last_assistant_message = await self._read_final_assistant_message(
                                session,
                                turn_id,
                            )
                        yield ExecutorEvent(
                            run_id=run.run_id,
                            session_id=session.session_id,
                            event_type=ExecutorEventType.COMPLETED,
                            message=last_assistant_message or completed_message,
                            metadata={**extra, "thread_id": session.thread_id or ""},
                        )
                        return
                    error_message = _get_nested(params, "turn", "error", "message")
                    yield ExecutorEvent(
                        run_id=run.run_id,
                        session_id=session.session_id,
                        event_type=ExecutorEventType.FAILED,
                        message=str(error_message or "Codex turn failed."),
                        metadata={**extra, "thread_id": session.thread_id or ""},
                    )
                    return
                if method == "error":
                    continue

                if method == "item/agentMessage/delta":
                    item_id = params.get("itemId")
                    delta = params.get("delta")
                    if not isinstance(item_id, str) or not isinstance(delta, str) or not delta:
                        continue
                    if assistant_item_phases.get(item_id) != "commentary":
                        continue
                    accumulated = assistant_item_text.get(item_id, "") + delta
                    assistant_item_text[item_id] = accumulated
                    candidate = accumulated.strip()
                    previous = assistant_item_emitted_text.get(item_id, "")
                    if candidate and _should_emit_codex_delta_progress(candidate, previous):
                        assistant_item_emitted_text[item_id] = candidate
                        yield ExecutorEvent(
                            run_id=run.run_id,
                            session_id=session.session_id,
                            event_type=ExecutorEventType.PROGRESS,
                            message=candidate,
                            metadata={
                                **extra,
                                "thread_id": session.thread_id or "",
                                "source": "codex",
                                "codex_item_id": item_id,
                                "phase": "commentary",
                            },
                        )
                    continue

                if method in {"item/started", "item/completed"}:
                    item = params.get("item")
                    if isinstance(item, dict):
                        item_type = item.get("type")
                        if item_type in {"assistantMessage", "agentMessage"}:
                            item_id = item.get("id")
                            phase = item.get("phase")
                            if isinstance(item_id, str):
                                assistant_item_phases[item_id] = phase if isinstance(phase, str) else None
                            extracted = _extract_item_text(item)
                            if extracted:
                                last_assistant_message = extracted
                                if (
                                    isinstance(item_id, str)
                                    and assistant_item_emitted_text.get(item_id) == extracted
                                ):
                                    continue
                                if phase == "final_answer":
                                    continue
                                if isinstance(item_id, str):
                                    assistant_item_emitted_text[item_id] = extracted
                                yield ExecutorEvent(
                                    run_id=run.run_id,
                                    session_id=session.session_id,
                                    event_type=ExecutorEventType.PROGRESS,
                                    message=extracted,
                                    metadata={
                                        **extra,
                                        "thread_id": session.thread_id or "",
                                        "source": "codex",
                                        "phase": phase if isinstance(phase, str) else "",
                                    },
                                )
                                continue
                    continue

                blocked_request = _extract_blocked_request(
                    request_id=event.get("id"),
                    method=method,
                    params=params,
                )
                if blocked_request is not None:
                    session.begin_blocked_wait()
                    yield ExecutorEvent(
                        run_id=run.run_id,
                        session_id=session.session_id,
                        event_type=ExecutorEventType.BLOCKED,
                        message=blocked_request["message"],
                        metadata={**extra, **blocked_request["metadata"]},
                    )
                    resolution = await session.wait_for_blocked_resolution(
                        timeout_seconds=self._blocked_wait_timeout_seconds,
                    )
                    if resolution == "resolved":
                        continue
                    if resolution == "timed_out":
                        yield ExecutorEvent(
                            run_id=run.run_id,
                            session_id=session.session_id,
                            event_type=ExecutorEventType.FAILED,
                            message="Timed out waiting for user input.",
                            metadata={**extra, "thread_id": session.thread_id or ""},
                        )
                    return

                if method == "thread/status/changed":
                    status_type = _get_nested(params, "status", "type")
                    if status_type == "systemError":
                        yield ExecutorEvent(
                            run_id=run.run_id,
                            session_id=session.session_id,
                            event_type=ExecutorEventType.FAILED,
                            message="Codex thread entered systemError state.",
                            metadata={**extra, "thread_id": session.thread_id or ""},
                        )
                        return
        finally:
            self._unregister_turn_queue(turn_id, event_queue)

    async def _ensure_thread(self, session: CodexExecutorSession, *, fork_existing: bool = True) -> str:
        if session.thread_id:
            if not fork_existing:
                if not session.metadata.get("codex_thread_resumed"):
                    await session.client.thread_resume(thread_id=session.thread_id)
                    session.metadata["codex_thread_resumed"] = True
                return session.thread_id
            try:
                result = await session.client.thread_fork(
                    thread_id=session.thread_id,
                    cwd=str(session.cwd),
                )
            except Exception:
                result = await session.client.thread_start(cwd=str(session.cwd))
        else:
            result = await session.client.thread_start(cwd=str(session.cwd))
        thread_id = _get_nested(result, "thread", "id")
        if not isinstance(thread_id, str):
            raise RuntimeError("Codex did not return a thread id.")
        session.thread_id = thread_id
        session.metadata["codex_thread_resumed"] = True
        return thread_id

    def build_resume_handle(self, session: CodexExecutorSession) -> AgentResumeHandle | None:
        if not session.thread_id:
            return None
        return AgentResumeHandle(
            executor_id="codex",
            session_handle=session.thread_id,
        )

    async def _read_final_assistant_message(
        self,
        session: CodexExecutorSession,
        turn_id: str,
    ) -> str | None:
        if not session.thread_id:
            return None
        try:
            response = await session.client.thread_read(
                thread_id=session.thread_id,
                include_turns=True,
            )
        except Exception:
            return None
        return _extract_assistant_text_from_thread(response, turn_id)

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
        parts.append(
            "Work inside the current repository and return a concise final result."
        )
        return "\n".join(parts)


def _get_nested(value: object, *keys: str) -> object:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _direct_bro_detail_input(task: Task) -> str | None:
    if task.metadata.get("source_kind") not in {"bro_detail_text", "bro_detail_ptt"}:
        return None
    text = task.latest_instruction if isinstance(task.latest_instruction, str) else task.goal
    return text.strip() if text.strip() else task.title.strip()


def _event_turn_id(params: dict[str, object]) -> str | None:
    value = params.get("turnId")
    if isinstance(value, str) and value:
        return value
    turn = params.get("turn")
    if isinstance(turn, dict):
        value = turn.get("id") or turn.get("turnId")
        if isinstance(value, str) and value:
            return value
    item = params.get("item")
    if isinstance(item, dict):
        value = item.get("turnId")
        if isinstance(value, str) and value:
            return value
    return None


def _event_thread_id(params: dict[str, object]) -> str | None:
    value = params.get("threadId")
    if isinstance(value, str) and value:
        return value
    thread = params.get("thread")
    if isinstance(thread, dict):
        value = thread.get("id") or thread.get("threadId")
        if isinstance(value, str) and value:
            return value
    turn = params.get("turn")
    if isinstance(turn, dict):
        value = turn.get("threadId")
        if isinstance(value, str) and value:
            return value
    item = params.get("item")
    if isinstance(item, dict):
        value = item.get("threadId")
        if isinstance(value, str) and value:
            return value
    return None


def _sort_codex_threads(threads: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(threads, key=_codex_thread_sort_key, reverse=True)


def _codex_thread_sort_key(thread: dict[str, object]) -> tuple[float, str]:
    timestamp = thread.get("updatedAt")
    if not isinstance(timestamp, int | float):
        timestamp = thread.get("createdAt")
    normalized_timestamp = float(timestamp) if isinstance(timestamp, int | float) else 0.0
    thread_id = thread.get("id") or thread.get("sessionId") or ""
    return (normalized_timestamp, str(thread_id))


def _extract_item_text(item: dict[str, object]) -> str | None:
    direct_text = item.get("text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()
    content = item.get("content")
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for entry in content:
        if isinstance(entry, dict):
            text = entry.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip() or None


def _should_emit_codex_delta_progress(candidate: str, previous: str) -> bool:
    if candidate == previous:
        return False
    if not previous:
        return len(candidate) >= 24 or candidate.endswith((".", "。", "!", "！", "?", "？", "\n"))
    added = candidate[len(previous) :]
    return len(added) >= 24 or candidate.endswith((".", "。", "!", "！", "?", "？", "\n"))


def _extract_question_text(params: dict[str, object]) -> str | None:
    for key in ("question", "message", "prompt"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    questions = params.get("questions")
    if isinstance(questions, list):
        for question in questions:
            if isinstance(question, dict):
                prompt = question.get("question") or question.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    return prompt.strip()
    return None


def _extract_blocked_request(
    request_id: object,
    *,
    method: str,
    params: dict[str, object],
) -> dict[str, object] | None:
    normalized = method.lower()
    if "user_input" in normalized or ("request" in normalized and "question" in normalized):
        question_text = _extract_question_text(params) or "Codex is waiting for user input."
        return {
            "message": question_text,
            "metadata": {
                "thread_id": str(params.get("threadId") or ""),
                "prompt": question_text,
                "interaction_kind": _classify_blocked_prompt(question_text),
                "blocked_method": method,
                "native_response": {
                    "request_id": request_id,
                    "method": method,
                    "params": params,
                },
            },
        }

    approval_methods = {
        "item/commandexecution/requestapproval",
        "item/filechange/requestapproval",
        "item/permissions/requestapproval",
        "execcommandapproval",
        "applypatchapproval",
    }
    if normalized not in approval_methods:
        return None

    approval_text = _extract_approval_text(method, params)
    return {
        "message": approval_text,
        "metadata": {
            "thread_id": str(params.get("threadId") or params.get("conversationId") or ""),
            "prompt": approval_text,
            "interaction_kind": "permission",
            "blocked_method": method,
            "native_response": {
                "request_id": request_id,
                "method": method,
                "params": params,
            },
        },
    }


def _extract_approval_text(method: str, params: dict[str, object]) -> str:
    reason = params.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip()

    normalized = method.lower()
    if normalized in {"item/commandexecution/requestapproval", "execcommandapproval"}:
        command = params.get("command")
        if isinstance(command, str) and command.strip():
            return f"Allow command execution? {command.strip()}"
        if isinstance(command, list):
            parts = [part for part in command if isinstance(part, str) and part.strip()]
            if parts:
                return f"Allow command execution? {' '.join(parts)}"
        return "Codex needs approval to run a command."

    if normalized in {"item/filechange/requestapproval", "applypatchapproval"}:
        grant_root = params.get("grantRoot")
        if isinstance(grant_root, str) and grant_root.strip():
            return f"Allow file changes under {grant_root.strip()}?"
        file_changes = params.get("fileChanges")
        if isinstance(file_changes, dict) and file_changes:
            names = list(file_changes.keys())[:3]
            joined = ", ".join(str(name) for name in names)
            suffix = "..." if len(file_changes) > 3 else ""
            return f"Allow file changes to {joined}{suffix}?"
        return "Codex needs approval to change files."

    if normalized == "item/permissions/requestapproval":
        permissions = params.get("permissions")
        if isinstance(permissions, dict):
            file_system = permissions.get("fileSystem")
            network = permissions.get("network")
            parts: list[str] = []
            if isinstance(file_system, dict):
                parts.append("file system access")
            if isinstance(network, dict):
                parts.append("network access")
            if parts:
                return f"Allow additional permissions: {', '.join(parts)}?"
        return "Codex needs additional permissions to continue."

    return "Codex needs approval to continue."


def _classify_blocked_prompt(prompt: str) -> str:
    normalized = prompt.lower()
    if any(token in normalized for token in ("allow", "permission", "approve", "grant access")):
        return "permission"
    if any(token in normalized for token in ("confirm", "confirmation", "are you sure")):
        return "confirmation"
    return "question"


def _extract_assistant_text_from_thread(
    response: dict[str, object],
    target_turn_id: str,
) -> str | None:
    thread = response.get("thread")
    if not isinstance(thread, dict):
        return None
    turns = thread.get("turns")
    if not isinstance(turns, list):
        return None

    matched_turns = [
        turn
        for turn in turns
        if isinstance(turn, dict) and turn.get("id") == target_turn_id
    ]
    if not matched_turns:
        matched_turns = [turn for turn in turns if isinstance(turn, dict)]

    for turn in reversed(matched_turns):
        items = turn.get("items")
        if not isinstance(items, list):
            continue
        for item in reversed(items):
            if not isinstance(item, dict):
                continue
            if item.get("type") not in {"assistantMessage", "agentMessage"}:
                continue
            extracted = _extract_item_text(item)
            if extracted:
                return extracted
    return None
