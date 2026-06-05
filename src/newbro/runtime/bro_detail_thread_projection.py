from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Awaitable, Callable, Literal
from uuid import uuid4

from newbro.blackboard.interfaces import BlackboardStore
from newbro.interaction.manager import InteractionManager
from newbro.observability.bootstrap import SessionObservability
from newbro.protocol import (
    AgentResumeHandle,
    BroThread,
    BroTimelineMessage,
    BroTimelineTurn,
    CodexThreadEventMessage,
    CodexTurnEventMessage,
    ExecutionRun,
    ExecutionSession,
    OutboundTurnRequest,
    Persona,
    Task,
    TaskStatus,
    TaskSummary,
)
from newbro.runtime.executor_node_manager import ExecutorNodeManager
from newbro.runtime.models import (
    BroThreadPageResponse,
    BroThreadSubscriptionResponse,
    BroTimelineTurnPageResponse,
    CursorPageInfo,
)
from .bro_detail_thread_helpers import (
    IMPORTED_CODEX_THREAD_PREFIX,
    SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS,
    DateParseCache,
    _bro_timeline_turn_from_codex_turn_event,
    _build_bro_thread_projection,
    _build_bro_timeline_projection,
    _codex_item_role,
    _codex_thread_alias_key,
    _codex_thread_event_timestamp,
    _codex_thread_goal,
    _codex_thread_status,
    _codex_thread_status_from_outbound_request,
    _event_metadata_string,
    _extract_codex_item_text,
    _extract_codex_plan,
    _imported_bro_thread_id,
    _is_ephemeral_codex_thread,
    _iso_from_epoch_seconds,
    _mark_timeline_message_plan_mode,
    _merge_timeline_turn,
    _new_bro_thread_id,
    _outbound_request_status_from_codex_event,
    _public_thread_id,
    _session_matches_thread_id,
    _should_emit_selected_thread_plan_delta,
    _task_belongs_to_persona,
    _task_metadata_string,
    _task_thread_public_id,
    _task_updated_at,
    _task_workspace_id,
    _thread_progress,
    _timeline_turns_from_codex_thread,
    _title_from_codex_thread,
    _title_from_draft_text,
    _workspace_from_resume_handle,
    _workspace_name,
)

LOGGER = logging.getLogger(__name__)
IMPORTED_CODEX_THREAD_PAGE_LIMIT = 25
SELECTED_CODEX_TURN_PAGE_LIMIT = 15


@dataclass
class BroDetailThreadProjectionSnapshot:
    bro_threads: list[BroThread]
    bro_timeline_turns: list[BroTimelineTurn]


@dataclass
class SelectedCodexThreadSubscription:
    subscription_id: str
    persona_id: str
    public_thread_id: str
    thread_continuity_key: str
    node_id: str
    codex_thread_id: str
    resume_handle: AgentResumeHandle
    fallback_timestamp: str | None = None


@dataclass
class BroDetailThreadProjection:
    session_id: str
    blackboard: BlackboardStore
    executor_node_manager: ExecutorNodeManager
    interaction_manager: InteractionManager
    observability: SessionObservability
    publish_snapshot: Callable[[], Awaitable[object]]
    record_native_turn_reasoning: Callable[[OutboundTurnRequest, CodexTurnEventMessage, str], None] | None = None
    imported_codex_threads: dict[str, BroThread] = field(default_factory=dict)
    imported_codex_thread_resume_handles: dict[str, AgentResumeHandle] = field(default_factory=dict)
    imported_codex_thread_page_info: dict[str, CursorPageInfo] = field(default_factory=dict)
    imported_codex_thread_pages_by_persona: dict[str, list[str]] = field(default_factory=dict)
    codex_thread_public_id_aliases: dict[str, str] = field(default_factory=dict)
    last_codex_thread_sync_monotonic: float = 0.0
    codex_thread_sync_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    selected_codex_thread_subscriptions: dict[str, SelectedCodexThreadSubscription] = field(default_factory=dict)
    subscribe_bro_thread_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    bro_thread_executor_turns: dict[str, list[BroTimelineTurn]] = field(default_factory=dict)
    bro_thread_live_message_deltas: dict[tuple[str, str, str], str] = field(default_factory=dict)
    bro_thread_live_item_phase: dict[tuple[str, str, str], str] = field(default_factory=dict)
    timeline_status: dict[str, Literal["not_loaded", "loading", "loaded", "failed"]] = field(default_factory=dict)
    timeline_errors: dict[str, str] = field(default_factory=dict)
    timeline_load_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    bro_thread_timeline_page_info: dict[str, CursorPageInfo] = field(default_factory=dict)
    bro_thread_live_plan_deltas: dict[tuple[str, str, str], str] = field(default_factory=dict)
    bro_thread_live_plan_emitted_text: dict[tuple[str, str, str], str] = field(default_factory=dict)
    bro_thread_goals: dict[str, str] = field(default_factory=dict)

    def _project_imported_codex_thread(
        self,
        *,
        persona: Persona,
        node_id: str,
        codex_thread,
    ) -> tuple[BroThread, AgentResumeHandle]:
        public_thread_id = self.codex_thread_public_id_aliases.get(
            _codex_thread_alias_key(persona.persona_id, codex_thread.thread_id)
        ) or _imported_bro_thread_id(persona.persona_id, codex_thread.thread_id)
        status = _codex_thread_status(codex_thread.status)
        thread_title = _title_from_codex_thread(codex_thread)
        thread_updated_at = _iso_from_epoch_seconds(codex_thread.updated_at or codex_thread.created_at)
        resume_handle = AgentResumeHandle(
            executor_id="codex",
            session_handle=codex_thread.thread_id,
            opaque={
                "cwd": codex_thread.cwd or "",
                "path": codex_thread.path or "",
                "cliVersion": codex_thread.cli_version or "",
                "title": thread_title,
                "listUpdatedAt": thread_updated_at or "",
            },
        )
        diagnostics = {
            **codex_thread.diagnostics,
            "codex_thread_id": codex_thread.thread_id,
            "codex_session_id": codex_thread.session_id,
            "codex_cwd": codex_thread.cwd,
            "codex_path": codex_thread.path,
            "codex_cli_version": codex_thread.cli_version,
            "codex_thread_source": codex_thread.source,
            "imported_from_codex_thread_list": True,
        }
        thread = BroThread(
            thread_id=public_thread_id,
            persona_id=persona.persona_id,
            persona_name=persona.name,
            executor_id="codex",
            executor_node_id=node_id,
            workspace_id=codex_thread.cwd,
            workspace_name=_workspace_name(codex_thread.cwd),
            execution_session_id=None,
            status=status,  # type: ignore[arg-type]
            title=thread_title,
            preview=codex_thread.preview,
            progress=_thread_progress(status),
            task_ids=[],
            active_task_id=None,
            latest_task_id=None,
            has_resume_handle=True,
            updated_at=thread_updated_at,
            diagnostics=diagnostics,
        )
        return thread, resume_handle

    async def snapshot_parts(
        self,
        *,
        tasks: list[Task],
        sessions: list[ExecutionSession],
        runs: list[ExecutionRun],
        summaries: list[TaskSummary],
        personas: list[Persona],
        sync_imported_codex_threads: bool = True,
    ) -> BroDetailThreadProjectionSnapshot:
        imported_threads = (
            await self.sync_imported_codex_threads(
                personas=personas,
                sessions=sessions,
            )
            if sync_imported_codex_threads
            else list(self.imported_codex_threads.values())
        )
        bro_threads = self.with_timeline_state(
            _build_bro_thread_projection(
                tasks=tasks,
                sessions=sessions,
                runs=runs,
                summaries=summaries,
                personas=personas,
                imported_threads=imported_threads,
            )
        )
        return BroDetailThreadProjectionSnapshot(
            bro_threads=bro_threads,
            bro_timeline_turns=_build_bro_timeline_projection(
                tasks=tasks,
                sessions=sessions,
                runs=runs,
                summaries=summaries,
                executor_turns=self.executor_turn_snapshot(),
            ),
        )

    def with_timeline_state(self, threads: list[BroThread]) -> list[BroThread]:
        return [
            thread.model_copy(
                update={
                    "timeline_status": self.timeline_status.get(thread.thread_id, "not_loaded"),
                    "timeline_error": self.timeline_errors.get(thread.thread_id),
                }
            )
            for thread in threads
        ]

    def session_matches_thread_id(self, session: ExecutionSession, thread_id: str) -> bool:
        return _session_matches_thread_id(session, thread_id)

    def executor_turn_snapshot(self) -> list[BroTimelineTurn]:
        turns: list[BroTimelineTurn] = []
        for thread_turns in self.bro_thread_executor_turns.values():
            turns.extend(thread_turns)
        return turns

    async def sync_imported_codex_threads(
        self,
        *,
        personas: list[Persona],
        sessions: list[ExecutionSession],
    ) -> list[BroThread]:
        eligible_personas = [
            persona
            for persona in personas
            if persona.executor_node_id
            and self.executor_node_manager.is_executor_connected("codex", node_id=persona.executor_node_id)
            and self.executor_node_manager.executor_supports_thread_list("codex", node_id=persona.executor_node_id)
        ]
        if not eligible_personas:
            self.imported_codex_threads.clear()
            self.imported_codex_thread_resume_handles.clear()
            self.imported_codex_thread_page_info.clear()
            self.imported_codex_thread_pages_by_persona.clear()
            return []

        now = time.monotonic()
        if self.imported_codex_threads and now - self.last_codex_thread_sync_monotonic < 5.0:
            return list(self.imported_codex_threads.values())

        async with self.codex_thread_sync_lock:
            now = time.monotonic()
            if self.imported_codex_threads and now - self.last_codex_thread_sync_monotonic < 5.0:
                return list(self.imported_codex_threads.values())

            existing_codex_thread_ids = {
                session.latest_resume_handle.session_handle
                for session in sessions
                if session.latest_resume_handle is not None
                and session.latest_resume_handle.executor_id == "codex"
                and isinstance(session.latest_resume_handle.session_handle, str)
                and session.latest_resume_handle.session_handle
            }
            personas_by_node: dict[str, list[Persona]] = {}
            for persona in eligible_personas:
                personas_by_node.setdefault(persona.executor_node_id, []).append(persona)

            imported_threads: dict[str, BroThread] = {}
            imported_resume_handles: dict[str, AgentResumeHandle] = {}
            imported_page_ids_by_persona: dict[str, list[str]] = {}
            for node_id, node_personas in personas_by_node.items():
                try:
                    codex_page = await self.executor_node_manager.request_codex_threads(
                        node_id=node_id,
                        limit=IMPORTED_CODEX_THREAD_PAGE_LIMIT,
                        cursor=None,
                    )
                    codex_threads = codex_page.threads
                except Exception as exc:
                    for persona in node_personas:
                        previous = self.imported_codex_thread_page_info.get(persona.persona_id, CursorPageInfo())
                        self.imported_codex_thread_page_info[persona.persona_id] = previous.model_copy(
                            update={
                                "status": "failed",
                                "error": str(exc),
                            }
                        )
                    self.observability.logger.emit_event(
                        level="WARNING",
                        event_name="runtime.codex_thread_sync_failed",
                        component="runtime.bro_threads",
                        summary="Codex thread import sync failed",
                        conversation_id=self.session_id,
                        details={"executor_node_id": node_id, "error": str(exc)},
                    )
                    continue
                skipped_ephemeral_count = 0
                imported_thread_count = 0
                for persona in node_personas:
                    imported_page_ids_by_persona[persona.persona_id] = []
                for codex_thread in codex_threads:
                    if codex_thread.thread_id in existing_codex_thread_ids:
                        continue
                    if _is_ephemeral_codex_thread(codex_thread):
                        skipped_ephemeral_count += 1
                        continue
                    imported_thread_count += 1
                    for persona in node_personas:
                        thread, resume_handle = self._project_imported_codex_thread(
                            persona=persona,
                            node_id=node_id,
                            codex_thread=codex_thread,
                        )
                        imported_threads[thread.thread_id] = thread
                        imported_page_ids_by_persona[persona.persona_id].append(thread.thread_id)
                        imported_resume_handles[thread.thread_id] = resume_handle
                page_info = CursorPageInfo(
                    next_cursor=codex_page.next_cursor,
                    previous_cursor=codex_page.previous_cursor,
                    has_more=bool(codex_page.next_cursor),
                    status="loaded",
                    error=None,
                )
                for persona in node_personas:
                    self.imported_codex_thread_page_info[persona.persona_id] = page_info
                self.observability.logger.emit_event(
                    level="INFO",
                    event_name="runtime.codex_thread_sync",
                    component="runtime.bro_threads",
                    summary="Codex thread import sync",
                    conversation_id=self.session_id,
                    details={
                        "executor_node_id": node_id,
                        "raw_thread_count": len(codex_threads),
                        "imported_thread_count": imported_thread_count,
                        "skipped_ephemeral_count": skipped_ephemeral_count,
                    },
                )
            self.imported_codex_threads.clear()
            self.imported_codex_threads.update(imported_threads)
            self.imported_codex_thread_resume_handles.clear()
            self.imported_codex_thread_resume_handles.update(imported_resume_handles)
            self.imported_codex_thread_pages_by_persona.clear()
            self.imported_codex_thread_pages_by_persona.update(imported_page_ids_by_persona)
            self.last_codex_thread_sync_monotonic = time.monotonic()
            return list(self.imported_codex_threads.values())

    async def list_bro_thread_page(
        self,
        *,
        persona: Persona,
        sessions: list[ExecutionSession],
        limit: int = IMPORTED_CODEX_THREAD_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> BroThreadPageResponse:
        if not persona.executor_node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        page = await self.executor_node_manager.request_codex_threads(
            node_id=persona.executor_node_id,
            limit=limit,
            cursor=cursor,
        )
        existing_codex_thread_ids = {
            session.latest_resume_handle.session_handle
            for session in sessions
            if session.latest_resume_handle is not None
            and session.latest_resume_handle.executor_id == "codex"
            and isinstance(session.latest_resume_handle.session_handle, str)
            and session.latest_resume_handle.session_handle
        }
        threads: list[BroThread] = []
        for codex_thread in page.threads:
            if codex_thread.thread_id in existing_codex_thread_ids or _is_ephemeral_codex_thread(codex_thread):
                continue
            thread, resume_handle = self._project_imported_codex_thread(
                persona=persona,
                node_id=persona.executor_node_id,
                codex_thread=codex_thread,
            )
            self.imported_codex_threads[thread.thread_id] = thread
            self.imported_codex_thread_resume_handles[thread.thread_id] = resume_handle
            persona_page_ids = self.imported_codex_thread_pages_by_persona.setdefault(persona.persona_id, [])
            if thread.thread_id not in persona_page_ids:
                persona_page_ids.append(thread.thread_id)
            threads.append(thread)
        info = CursorPageInfo(
            next_cursor=page.next_cursor,
            previous_cursor=page.previous_cursor,
            has_more=bool(page.next_cursor),
            status="loaded",
            error=None,
        )
        self.imported_codex_thread_page_info[persona.persona_id] = info
        return BroThreadPageResponse(
            persona_id=persona.persona_id,
            threads=self.with_timeline_state(threads),
            page=info,
        )

    def bro_thread_subscription_response(
        self,
        *,
        thread_id: str,
        persona_id: str,
        subscribed: bool,
    ) -> BroThreadSubscriptionResponse:
        return BroThreadSubscriptionResponse(
            thread_id=thread_id,
            persona_id=persona_id,
            subscribed=subscribed,
            timeline_status=self.timeline_status.get(thread_id, "not_loaded"),
            timeline_error=self.timeline_errors.get(thread_id),
        )

    async def subscribe_bro_thread(
        self,
        *,
        target_persona_id: str,
        thread_id: str,
    ) -> BroThreadSubscriptionResponse:
        persona = await self.blackboard.get_persona(target_persona_id)
        if persona is None:
            raise ValueError("Selected Bro is not available.")
        if not persona.executor_node_id:
            raise ValueError("Selected Bro is not bound to an executor node.")
        if not self.executor_node_manager.is_executor_connected("codex", node_id=persona.executor_node_id):
            raise ValueError("Selected Bro's Codex executor node is not connected.")

        if thread_id.startswith(IMPORTED_CODEX_THREAD_PREFIX):
            imported = self.imported_codex_threads.get(thread_id)
            imported_resume_handle = self.imported_codex_thread_resume_handles.get(thread_id)
            if (
                imported is None
                or imported.persona_id != persona.persona_id
                or imported_resume_handle is None
            ):
                raise ValueError("Thread is not loaded; list thread page first.")

        resolved_thread_id, thread_continuity_key, selected_session, imported_resume_handle = await self.resolve_bro_thread_target(
            persona=persona,
            target_thread_id=thread_id,
            create_new_thread=False,
        )
        resume_handle = imported_resume_handle or (
            selected_session.latest_resume_handle if selected_session is not None else None
        )
        if (
            resume_handle is None
            or resume_handle.executor_id != "codex"
            or not isinstance(resume_handle.session_handle, str)
            or not resume_handle.session_handle
        ):
            return self.bro_thread_subscription_response(
                thread_id=resolved_thread_id,
                persona_id=persona.persona_id,
                subscribed=False,
            )

        node_id = selected_session.executor_node_id if selected_session is not None else persona.executor_node_id
        if not node_id:
            raise ValueError("Selected Codex thread is not connected to an executor node.")

        if persona.persona_id not in self.subscribe_bro_thread_locks:
            self.subscribe_bro_thread_locks[persona.persona_id] = asyncio.Lock()
        async with self.subscribe_bro_thread_locks[persona.persona_id]:
            return await self._subscribe_bro_thread_locked(
                persona=persona,
                resolved_thread_id=resolved_thread_id,
                thread_continuity_key=thread_continuity_key,
                resume_handle=resume_handle,
                node_id=node_id,
            )

    async def _subscribe_bro_thread_locked(
        self,
        *,
        persona: Persona,
        resolved_thread_id: str,
        thread_continuity_key: str,
        resume_handle: AgentResumeHandle,
        node_id: str,
    ) -> BroThreadSubscriptionResponse:
        imported_thread = self.imported_codex_threads.get(resolved_thread_id)
        current_subscription = self.selected_codex_thread_subscriptions.get(persona.persona_id)
        if current_subscription is not None:
            same = (
                current_subscription.public_thread_id == resolved_thread_id
                and current_subscription.codex_thread_id == resume_handle.session_handle
                and current_subscription.node_id == node_id
            )
            if same:
                return self.bro_thread_subscription_response(
                    thread_id=resolved_thread_id,
                    persona_id=persona.persona_id,
                    subscribed=True,
                )
            await self.stop_selected_codex_thread_subscription(persona_id=persona.persona_id, wait=False)

        await self.replace_selected_codex_thread_subscription(
            persona=persona,
            public_thread_id=resolved_thread_id,
            thread_continuity_key=thread_continuity_key,
            node_id=node_id,
            resume_handle=resume_handle,
            fallback_timestamp=imported_thread.updated_at if imported_thread is not None else None,
            stop_wait=False,
        )
        return self.bro_thread_subscription_response(
            thread_id=resolved_thread_id,
            persona_id=persona.persona_id,
            subscribed=True,
        )

    def should_load_bro_thread_timeline(
        self,
        *,
        public_thread_id: str,
        resume_handle: AgentResumeHandle,
    ) -> bool:
        if not public_thread_id.startswith(IMPORTED_CODEX_THREAD_PREFIX):
            return False
        if public_thread_id in self.bro_thread_executor_turns:
            return False
        if self.timeline_status.get(public_thread_id) == "loaded":
            return False
        return (
            resume_handle.executor_id == "codex"
            and isinstance(resume_handle.session_handle, str)
            and bool(resume_handle.session_handle)
        )

    async def load_bro_thread_timeline(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
    ) -> None:
        if self.timeline_status.get(public_thread_id) == "loaded":
            return

        existing_task = self.timeline_load_tasks.get(public_thread_id)
        if existing_task is not None:
            if not existing_task.done():
                await asyncio.shield(existing_task)
                return
            self.timeline_load_tasks.pop(public_thread_id, None)

        load_task = asyncio.create_task(
            self._load_bro_thread_timeline_once(
                persona=persona,
                public_thread_id=public_thread_id,
                node_id=node_id,
                resume_handle=resume_handle,
            )
        )
        self.timeline_load_tasks[public_thread_id] = load_task

        def clear_load_task(task: asyncio.Task[None]) -> None:
            if self.timeline_load_tasks.get(public_thread_id) is task:
                self.timeline_load_tasks.pop(public_thread_id, None)

        load_task.add_done_callback(clear_load_task)
        await asyncio.shield(load_task)

    async def _load_bro_thread_timeline_once(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
    ) -> None:
        native_thread_id = resume_handle.session_handle
        if not isinstance(native_thread_id, str) or not native_thread_id:
            return
        self.timeline_status[public_thread_id] = "loading"
        self.timeline_errors.pop(public_thread_id, None)
        await self.publish_snapshot()
        try:
            page = await self.executor_node_manager.request_codex_thread_turns(
                node_id=node_id,
                thread_id=native_thread_id,
                limit=SELECTED_CODEX_TURN_PAGE_LIMIT,
                cursor=None,
            )
        except Exception as exc:
            message = str(exc).strip() or "Codex thread history could not be loaded."
            self.bro_thread_executor_turns.pop(public_thread_id, None)
            self.timeline_status[public_thread_id] = "failed"
            self.timeline_errors[public_thread_id] = message
            LOGGER.warning(
                "Failed to load Codex thread history for %s/%s: %s",
                public_thread_id,
                native_thread_id,
                message,
            )
            return
        if page.goal:
            self.bro_thread_goals[public_thread_id] = page.goal
        for turn in _timeline_turns_from_codex_thread(
            thread={"id": page.thread_id, "goal": page.goal, "turns": list(reversed(page.turns))},
            public_thread_id=public_thread_id,
            executor_thread_id=native_thread_id,
            persona_id=persona.persona_id,
            executor_id="codex",
        ):
            self.upsert_bro_thread_executor_turn(turn)
        self.bro_thread_timeline_page_info[public_thread_id] = CursorPageInfo(
            next_cursor=page.next_cursor,
            previous_cursor=page.previous_cursor,
            has_more=bool(page.next_cursor),
            status="loaded",
            error=None,
        )
        self.timeline_status[public_thread_id] = "loaded"
        self.timeline_errors.pop(public_thread_id, None)

    async def list_bro_timeline_page(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        node_id: str,
        cursor: str | None = None,
        limit: int = SELECTED_CODEX_TURN_PAGE_LIMIT,
    ) -> BroTimelineTurnPageResponse:
        resume_handle = self.imported_codex_thread_resume_handles.get(public_thread_id)
        if (
            resume_handle is None
            or resume_handle.executor_id != "codex"
            or not isinstance(resume_handle.session_handle, str)
            or not resume_handle.session_handle
        ):
            raise ValueError("Selected Codex thread is not available.")
        page = await self.executor_node_manager.request_codex_thread_turns(
            node_id=node_id,
            thread_id=resume_handle.session_handle,
            limit=limit,
            cursor=cursor,
        )
        if page.goal:
            self.bro_thread_goals[public_thread_id] = page.goal
        turns = list(
            _timeline_turns_from_codex_thread(
                thread={"id": page.thread_id, "goal": page.goal, "turns": list(reversed(page.turns))},
                public_thread_id=public_thread_id,
                executor_thread_id=page.thread_id,
                persona_id=persona.persona_id,
                executor_id="codex",
            )
        )
        for turn in turns:
            self.upsert_bro_thread_executor_turn(turn)
        info = CursorPageInfo(
            next_cursor=page.next_cursor,
            previous_cursor=page.previous_cursor,
            has_more=bool(page.next_cursor),
            status="loaded",
            error=None,
        )
        self.bro_thread_timeline_page_info[public_thread_id] = info
        return BroTimelineTurnPageResponse(thread_id=public_thread_id, turns=turns, page=info)

    async def unsubscribe_bro_thread(
        self,
        *,
        target_persona_id: str,
        thread_id: str | None = None,
    ) -> BroThreadSubscriptionResponse:
        if target_persona_id not in self.subscribe_bro_thread_locks:
            self.subscribe_bro_thread_locks[target_persona_id] = asyncio.Lock()
        async with self.subscribe_bro_thread_locks[target_persona_id]:
            current = self.selected_codex_thread_subscriptions.get(target_persona_id)
            response_thread_id = thread_id or (current.public_thread_id if current is not None else "")
            await self.stop_selected_codex_thread_subscription(
                persona_id=target_persona_id,
                public_thread_id=thread_id,
            )
            return self.bro_thread_subscription_response(
                thread_id=response_thread_id,
                persona_id=target_persona_id,
                subscribed=False,
            )

    async def replace_selected_codex_thread_subscription(
        self,
        *,
        persona: Persona,
        public_thread_id: str,
        thread_continuity_key: str,
        node_id: str,
        resume_handle: AgentResumeHandle,
        fallback_timestamp: str | None,
        stop_wait: bool = True,
    ) -> bool:
        codex_thread_id = resume_handle.session_handle
        if not isinstance(codex_thread_id, str) or not codex_thread_id:
            return False
        current = self.selected_codex_thread_subscriptions.get(persona.persona_id)
        if (
            current is not None
            and current.public_thread_id == public_thread_id
            and current.codex_thread_id == codex_thread_id
            and current.node_id == node_id
        ):
            return False
        await self.stop_selected_codex_thread_subscription(
            persona_id=persona.persona_id,
            wait=stop_wait,
        )
        subscription_id = f"codex-sub-{uuid4().hex[:12]}"
        workspace_id = None
        cwd = resume_handle.opaque.get("cwd")
        if isinstance(cwd, str) and cwd:
            workspace_id = cwd
        subscription = SelectedCodexThreadSubscription(
            subscription_id=subscription_id,
            persona_id=persona.persona_id,
            public_thread_id=public_thread_id,
            thread_continuity_key=thread_continuity_key,
            node_id=node_id,
            codex_thread_id=codex_thread_id,
            resume_handle=resume_handle,
            fallback_timestamp=fallback_timestamp,
        )
        self.selected_codex_thread_subscriptions[persona.persona_id] = subscription
        try:
            await self.executor_node_manager.subscribe_codex_thread(
                node_id=node_id,
                subscription_id=subscription_id,
                session_id=self.session_id,
                target_persona_id=persona.persona_id,
                target_thread_id=public_thread_id,
                thread_id=codex_thread_id,
                workspace_id=workspace_id,
                timeout_seconds=SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            if self.selected_codex_thread_subscriptions.get(persona.persona_id) is subscription:
                self.selected_codex_thread_subscriptions.pop(persona.persona_id, None)
            cleanup_task = asyncio.create_task(
                self._unsubscribe_selected_codex_thread(persona_id=persona.persona_id, current=subscription)
            )
            await asyncio.shield(cleanup_task)
            raise
        except Exception:
            if self.selected_codex_thread_subscriptions.get(persona.persona_id) is subscription:
                self.selected_codex_thread_subscriptions.pop(persona.persona_id, None)
            await self._unsubscribe_selected_codex_thread(persona_id=persona.persona_id, current=subscription)
            raise
        return True

    async def stop_selected_codex_thread_subscription(
        self,
        *,
        persona_id: str,
        public_thread_id: str | None = None,
        wait: bool = True,
    ) -> None:
        current = self.selected_codex_thread_subscriptions.get(persona_id)
        if current is None:
            return
        if public_thread_id is not None and current.public_thread_id != public_thread_id:
            return
        self.selected_codex_thread_subscriptions.pop(persona_id, None)

        async def unsubscribe() -> None:
            await self._unsubscribe_selected_codex_thread(persona_id=persona_id, current=current)

        if not wait:
            asyncio.create_task(unsubscribe())
            return
        await unsubscribe()

    async def _unsubscribe_selected_codex_thread(
        self,
        *,
        persona_id: str,
        current: SelectedCodexThreadSubscription,
    ) -> None:
        try:
            response = await self.executor_node_manager.unsubscribe_codex_thread(
                node_id=current.node_id,
                subscription_id=current.subscription_id,
                thread_id=current.codex_thread_id,
                timeout_seconds=SELECTED_THREAD_SUBSCRIPTION_TIMEOUT_SECONDS,
            )
            status = response.status if response is not None else "node_unavailable"
        except Exception as exc:
            status = f"error:{exc}"
        LOGGER.info(
            "Stopped selected Codex thread subscription",
            extra={
                "session_id": self.session_id,
                "persona_id": persona_id,
                "public_thread_id": current.public_thread_id,
                "codex_thread_id": current.codex_thread_id,
                "unsubscribe_status": status,
            },
        )

    async def handle_codex_thread_event(self, message: CodexThreadEventMessage) -> None:
        current = self.selected_codex_thread_subscriptions.get(message.target_persona_id)
        if current is None:
            return
        if (
            current.subscription_id != message.subscription_id
            or current.public_thread_id != message.target_thread_id
            or current.codex_thread_id != message.thread_id
            or current.node_id != message.node_id
        ):
            return
        if message.method not in {
            "turn/completed",
            "item/started",
            "item/agentMessage/delta",
            "item/plan/delta",
            "item/completed",
            "thread/goal/updated",
            "thread/goal/cleared",
            "thread/status/changed",
            "thread/closed",
        }:
            return
        if message.method in {
            "item/started",
            "item/agentMessage/delta",
            "item/plan/delta",
            "item/completed",
            "turn/completed",
            "thread/goal/updated",
            "thread/goal/cleared",
        }:
            if await self.apply_codex_thread_timeline_event(message, current):
                await self.publish_snapshot()
        if message.method == "thread/closed":
            await self.stop_selected_codex_thread_subscription(
                persona_id=current.persona_id,
                public_thread_id=current.public_thread_id,
            )
        return

    async def handle_codex_turn_event(self, message: CodexTurnEventMessage) -> None:
        request = await self.blackboard.get_outbound_turn_request(message.request_id)
        if request is None:
            return
        if (
            request.persona_id != message.target_persona_id
            or request.executor_node_id != message.node_id
            or request.target_thread_id != message.target_thread_id
        ):
            return
        timestamp = datetime.now(tz=UTC).isoformat()
        request_status = _outbound_request_status_from_codex_event(message)
        updated_request = request.model_copy(
            update={
                "status": request_status,
                "error": message.error if not message.ok or request_status == "failed" else None,
                "executor_thread_id": message.executor_thread_id or request.executor_thread_id,
                "executor_turn_id": message.executor_turn_id or request.executor_turn_id,
                "updated_at": timestamp,
            }
        )
        await self.blackboard.put_outbound_turn_request(updated_request)
        LOGGER.warning(
            "[turn-reco] channelA request_id=%s client_request_id=%s exec_thread=%s exec_turn=%s status=%s",
            message.request_id,
            updated_request.client_request_id,
            updated_request.executor_thread_id,
            updated_request.executor_turn_id,
            request_status,
        )
        await self.attach_outbound_new_thread_resume_handle(updated_request, message)
        self.upsert_bro_thread_executor_turn(
            _bro_timeline_turn_from_codex_turn_event(
                request=updated_request,
                message=message,
                timestamp=timestamp,
            )
        )
        if self.record_native_turn_reasoning is not None:
            self.record_native_turn_reasoning(updated_request, message, timestamp)
        await self.interaction_manager.handle_outbound_codex_blocked(
            outbound_request=updated_request,
            message=message,
        )
        await self.publish_snapshot()

    async def attach_outbound_new_thread_resume_handle(
        self,
        request: OutboundTurnRequest,
        message: CodexTurnEventMessage,
    ) -> None:
        if not request.create_new_thread:
            return
        if not request.target_thread_id or not message.executor_thread_id:
            return
        persona = await self.blackboard.get_persona(request.persona_id)
        if persona is None:
            return
        alias_key = _codex_thread_alias_key(request.persona_id, message.executor_thread_id)
        self.codex_thread_public_id_aliases[alias_key] = request.target_thread_id
        title = _title_from_draft_text(request.text or message.message or "Direct Codex thread")
        resume_handle = AgentResumeHandle(
            executor_id=request.executor_id,
            session_handle=message.executor_thread_id,
            opaque={
                "cwd": request.workspace_id or "",
                "title": title,
                "createdFromOutboundTurnRequest": request.request_id,
            },
        )
        status = _codex_thread_status_from_outbound_request(request.status)
        self.imported_codex_threads[request.target_thread_id] = BroThread(
            thread_id=request.target_thread_id,
            persona_id=request.persona_id,
            persona_name=persona.name,
            executor_id=request.executor_id,
            executor_node_id=request.executor_node_id,
            workspace_id=request.workspace_id,
            workspace_name=_workspace_name(request.workspace_id),
            execution_session_id=None,
            status=status,  # type: ignore[arg-type]
            title=title,
            progress=_thread_progress(status),
            task_ids=[],
            active_task_id=None,
            latest_task_id=None,
            has_resume_handle=True,
            updated_at=request.updated_at,
            diagnostics={
                "codex_thread_id": message.executor_thread_id,
                "codex_cwd": request.workspace_id,
                "created_from_outbound_turn_request": request.request_id,
                "source": "outbound_turn_request",
            },
        )
        self.imported_codex_thread_resume_handles[request.target_thread_id] = resume_handle

    async def client_request_id_for_selected_thread_turn(
        self,
        *,
        public_thread_id: str,
        executor_thread_id: str,
        executor_turn_id: str,
    ) -> str | None:
        tasks = await self.blackboard.list_tasks()
        task_by_id = {task.task_id: task for task in tasks}
        for run in await self.blackboard.list_runs():
            task = task_by_id.get(run.task_id)
            if task is None or _task_thread_public_id(task) != public_thread_id:
                continue
            source_kind = _task_metadata_string(task, "source_kind")
            if source_kind not in {"bro_detail_text", "bro_detail_ptt"}:
                continue
            run_thread_id = _event_metadata_string(run, "executor_thread_id") or _event_metadata_string(run, "thread_id")
            run_turn_id = _event_metadata_string(run, "executor_turn_id") or _event_metadata_string(run, "turn_id")
            if run_thread_id != executor_thread_id or run_turn_id != executor_turn_id:
                continue
            client_request_id = _task_metadata_string(task, "client_request_id")
            if client_request_id is not None:
                LOGGER.warning(
                    "[turn-reco] channelB resolve thread=%s exec_turn=%s exact=hit -> %s",
                    public_thread_id, executor_turn_id, client_request_id,
                )
                return client_request_id

        direct_candidates: list[tuple[str, str]] = []
        pending_candidates: list[tuple[str, str]] = []
        for task in tasks:
            if _task_thread_public_id(task) != public_thread_id:
                continue
            source_kind = _task_metadata_string(task, "source_kind")
            if source_kind not in {"bro_detail_text", "bro_detail_ptt"}:
                continue
            client_request_id = _task_metadata_string(task, "client_request_id")
            if client_request_id is None:
                continue
            candidate = (_task_updated_at(task) or "", client_request_id)
            direct_candidates.append(candidate)
            if task.status in {
                TaskStatus.CREATED,
                TaskStatus.QUEUED,
                TaskStatus.WAITING_EXECUTOR,
                TaskStatus.RUNNING,
                TaskStatus.WAITING_USER_INPUT,
            }:
                pending_candidates.append(candidate)
        unique_pending = {client_request_id for _, client_request_id in pending_candidates}
        unique_direct = {client_request_id for _, client_request_id in direct_candidates}
        if len(unique_pending) == 1:
            pending_candidates.sort()
            result = pending_candidates[-1][1] if pending_candidates else None
            branch = "pending-single"
        elif len(unique_direct) == 1:
            direct_candidates.sort()
            result = direct_candidates[-1][1] if direct_candidates else None
            branch = "direct-single"
        else:
            result = None
            branch = "ambiguous-none"
        LOGGER.warning(
            "[turn-reco] channelB resolve thread=%s exec_turn=%s exact=miss branch=%s pending=%s direct=%s -> %s",
            public_thread_id, executor_turn_id, branch,
            sorted(unique_pending), sorted(unique_direct), result,
        )
        return result

    async def apply_codex_thread_timeline_event(
        self,
        message: CodexThreadEventMessage,
        subscription: SelectedCodexThreadSubscription,
    ) -> bool:
        params = message.params
        if message.method in {"thread/goal/updated", "thread/goal/cleared"}:
            if message.method == "thread/goal/cleared":
                self.bro_thread_goals.pop(subscription.public_thread_id, None)
            else:
                goal = _codex_thread_goal(params)
                if not goal:
                    goal_value = params.get("goal") or params.get("text") or params.get("objective")
                    goal = goal_value.strip() if isinstance(goal_value, str) and goal_value.strip() else None
                if goal:
                    self.bro_thread_goals[subscription.public_thread_id] = goal
            existing_turns = self.bro_thread_executor_turns.get(subscription.public_thread_id, [])
            updated: list[BroTimelineTurn] = []
            for turn in existing_turns:
                metadata = dict(turn.metadata)
                if message.method == "thread/goal/cleared":
                    metadata.pop("codex_goal", None)
                else:
                    metadata["codex_goal"] = self.bro_thread_goals.get(subscription.public_thread_id)
                updated.append(turn.model_copy(update={"metadata": metadata}))
            if updated:
                self.bro_thread_executor_turns[subscription.public_thread_id] = updated
            return bool(updated)
        if message.method == "turn/completed":
            # Turn-level completion is the authoritative settle signal. Commentary
            # item completions keep the turn live, so the turn settles here (or via
            # the outbound codex_turn_event 'completed') rather than per message.
            turn = params.get("turn")
            completed_turn_id = turn.get("id") if isinstance(turn, dict) else None
            if not isinstance(completed_turn_id, str) or not completed_turn_id:
                return False
            return self.settle_selected_thread_turn(
                public_thread_id=subscription.public_thread_id,
                executor_turn_id=completed_turn_id,
            )
        turn_id = params.get("turnId") or params.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            return False
        timestamp = _codex_thread_event_timestamp(params)
        client_request_id = await self.client_request_id_for_selected_thread_turn(
            public_thread_id=subscription.public_thread_id,
            executor_thread_id=subscription.codex_thread_id,
            executor_turn_id=turn_id,
        )
        codex_goal = self.bro_thread_goals.get(subscription.public_thread_id)
        item = params.get("item")
        if isinstance(item, dict):
            if item.get("type") == "plan":
                plan = _extract_codex_plan(item)
                if plan is None:
                    return False
                paired_user_message, original_user_turn_id = self.pop_selected_thread_pending_user_turn(
                    public_thread_id=subscription.public_thread_id,
                    executor_thread_id=subscription.codex_thread_id,
                    plan_turn_id=turn_id,
                    plan_timestamp=timestamp,
                )
                self.upsert_bro_thread_executor_turn(
                    BroTimelineTurn(
                        turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                        thread_id=subscription.public_thread_id,
                        persona_id=subscription.persona_id,
                        executor_id="codex",
                        owner="executor",
                        client_request_id=client_request_id,
                        executor_thread_id=subscription.codex_thread_id,
                        executor_turn_id=turn_id,
                        input_modality="text" if paired_user_message is not None else "unknown",
                        user=_mark_timeline_message_plan_mode(paired_user_message),
                        status="running" if message.method == "item/started" else "completed",
                        created_at=paired_user_message.created_at if paired_user_message is not None else timestamp,
                        updated_at=timestamp,
                        metadata={
                            "source": "selected_thread_event",
                            "executor_thread_id": subscription.codex_thread_id,
                            "executor_turn_id": turn_id,
                            "client_request_id": client_request_id,
                            "codex_goal": codex_goal,
                            "codex_plan": plan,
                            "plan_mode": True,
                            "assistant_title": paired_user_message.text if paired_user_message is not None else None,
                            "original_user_executor_turn_id": original_user_turn_id,
                        },
                    )
                )
                return True
            role = _codex_item_role(item)
            item_id = item.get("id")
            item_id_text = str(item_id) if isinstance(item_id, str) and item_id else "completed"
            phase = item.get("phase")
            # Record the agentMessage phase as soon as it is known (item/started,
            # then item/completed) so streaming deltas — which carry no phase — can
            # be routed: 'commentary' is intermediate working narration shown as a
            # reasoning step, only 'final_answer' (or a phase-less native answer) is
            # the settled answer.
            if role == "assistant" and isinstance(item_id, str) and item_id and isinstance(phase, str) and phase:
                self.bro_thread_live_item_phase[(subscription.public_thread_id, turn_id, item_id)] = phase
            text = _extract_codex_item_text(item)
            if role is None:
                return False
            # Commentary is surfaced via the channel-A reasoning step stream; keep
            # the turn live but never place it in the answer slot, which would
            # double-render the message (once as a step, once as the answer).
            if role == "assistant" and self._selected_thread_item_is_commentary(
                subscription.public_thread_id, turn_id, item_id if isinstance(item_id, str) else None
            ):
                return self._keep_selected_thread_turn_live(
                    subscription=subscription,
                    turn_id=turn_id,
                    client_request_id=client_request_id,
                    codex_goal=codex_goal,
                    timestamp=timestamp,
                )
            if not text:
                return False
            status = item.get("status")
            default_status = status if isinstance(status, str) and status else "completed"
            if role == "user":
                # The echoed user message completing does not finish the turn; the
                # assistant answer is still pending, so keep the turn live (the
                # message itself keeps its own reported status).
                message_status = default_status
                turn_status = "running"
            else:
                message_status = default_status
                turn_status = "running" if message_status in {"running", "inProgress"} else "completed"
            timeline_message = BroTimelineMessage(
                message_id=f"{subscription.public_thread_id}:{turn_id}:{role}",
                role=role,
                kind="text",
                text=text,
                created_at=timestamp,
                status=message_status,
                metadata={
                    "executor_turn_id": turn_id,
                    "codex_item_id": item_id_text,
                    "codex_item_type": item.get("type") if isinstance(item.get("type"), str) else None,
                    "codex_agent_message_phase": phase if isinstance(phase, str) else None,
                    "source": "selected_thread_event",
                },
            )
            self.upsert_bro_thread_executor_turn(
                BroTimelineTurn(
                    turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                    thread_id=subscription.public_thread_id,
                    persona_id=subscription.persona_id,
                    executor_id="codex",
                    owner="executor",
                    client_request_id=client_request_id,
                    executor_thread_id=subscription.codex_thread_id,
                    executor_turn_id=turn_id,
                    input_modality="text" if role == "user" else "unknown",
                    user=timeline_message if role == "user" else None,
                    assistant=timeline_message if role == "assistant" else None,
                    status=turn_status,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "source": "selected_thread_event",
                        "executor_thread_id": subscription.codex_thread_id,
                        "executor_turn_id": turn_id,
                        "client_request_id": client_request_id,
                        "codex_goal": codex_goal,
                    },
                )
            )
            return True
        if message.method == "item/plan/delta":
            item_id = params.get("itemId") or params.get("item_id")
            delta = params.get("delta")
            if not isinstance(item_id, str) or not item_id or not isinstance(delta, str) or not delta:
                return False
            key = (subscription.public_thread_id, turn_id, item_id)
            text = f"{self.bro_thread_live_plan_deltas.get(key, '')}{delta}"
            self.bro_thread_live_plan_deltas[key] = text
            candidate = text.strip()
            previous = self.bro_thread_live_plan_emitted_text.get(key, "")
            if not candidate or not _should_emit_selected_thread_plan_delta(candidate, previous):
                return False
            self.bro_thread_live_plan_emitted_text[key] = candidate
            self.upsert_bro_thread_executor_turn(
                BroTimelineTurn(
                    turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                    thread_id=subscription.public_thread_id,
                    persona_id=subscription.persona_id,
                    executor_id="codex",
                    owner="executor",
                    client_request_id=client_request_id,
                    executor_thread_id=subscription.codex_thread_id,
                    executor_turn_id=turn_id,
                    input_modality="unknown",
                    status="running",
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "source": "selected_thread_event",
                        "executor_thread_id": subscription.codex_thread_id,
                        "executor_turn_id": turn_id,
                        "client_request_id": client_request_id,
                        "codex_goal": codex_goal,
                        "codex_plan": {"text": text, "steps": []},
                        "plan_mode": True,
                    },
                )
            )
            return True
        if message.method != "item/agentMessage/delta":
            return False
        item_id = params.get("itemId") or params.get("item_id")
        delta = params.get("delta")
        if not isinstance(item_id, str) or not item_id or not isinstance(delta, str) or not delta:
            return False
        if self._selected_thread_item_is_commentary(subscription.public_thread_id, turn_id, item_id):
            # Commentary streams as a reasoning step (channel-A), not the answer.
            return self._keep_selected_thread_turn_live(
                subscription=subscription,
                turn_id=turn_id,
                client_request_id=client_request_id,
                codex_goal=codex_goal,
                timestamp=timestamp,
            )
        key = (subscription.public_thread_id, turn_id, item_id)
        text = f"{self.bro_thread_live_message_deltas.get(key, '')}{delta}"
        self.bro_thread_live_message_deltas[key] = text
        self.upsert_bro_thread_executor_turn(
            BroTimelineTurn(
                turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                thread_id=subscription.public_thread_id,
                persona_id=subscription.persona_id,
                executor_id="codex",
                owner="executor",
                client_request_id=client_request_id,
                executor_thread_id=subscription.codex_thread_id,
                executor_turn_id=turn_id,
                input_modality="unknown",
                assistant=BroTimelineMessage(
                    message_id=f"{subscription.public_thread_id}:{turn_id}:assistant",
                    role="assistant",
                    kind="text",
                    text=text,
                    created_at=timestamp,
                    status="running",
                    metadata={
                        "executor_turn_id": turn_id,
                        "codex_item_id": item_id,
                        "codex_item_type": "agentMessage",
                        "source": "selected_thread_event",
                    },
                ),
                status="running",
                created_at=timestamp,
                updated_at=timestamp,
                metadata={
                    "source": "selected_thread_event",
                    "executor_thread_id": subscription.codex_thread_id,
                    "executor_turn_id": turn_id,
                    "client_request_id": client_request_id,
                    "codex_goal": codex_goal,
                },
            )
        )
        return True

    def pop_selected_thread_pending_user_turn(
        self,
        *,
        public_thread_id: str,
        executor_thread_id: str,
        plan_turn_id: str,
        plan_timestamp: str,
    ) -> tuple[BroTimelineMessage | None, str | None]:
        turns = list(self.bro_thread_executor_turns.get(public_thread_id, []))
        plan_time = DateParseCache.parse(plan_timestamp)
        for index in range(len(turns) - 1, -1, -1):
            candidate = turns[index]
            if candidate.executor_id != "codex":
                continue
            if candidate.executor_thread_id != executor_thread_id:
                continue
            if candidate.executor_turn_id == plan_turn_id:
                continue
            if candidate.user is None or candidate.assistant is not None or candidate.task is not None:
                continue
            if candidate.metadata.get("source") != "selected_thread_event":
                continue
            if candidate.metadata.get("codex_plan") is not None:
                continue
            candidate_time = DateParseCache.parse(candidate.created_at or candidate.updated_at or "")
            if candidate_time > plan_time:
                continue
            turns.pop(index)
            if turns:
                self.bro_thread_executor_turns[public_thread_id] = turns
            else:
                self.bro_thread_executor_turns.pop(public_thread_id, None)
            return candidate.user, candidate.executor_turn_id
        return None, None

    def _selected_thread_item_is_commentary(
        self, public_thread_id: str, turn_id: str, item_id: str | None
    ) -> bool:
        if not isinstance(item_id, str) or not item_id:
            return False
        return self.bro_thread_live_item_phase.get((public_thread_id, turn_id, item_id)) == "commentary"

    def _keep_selected_thread_turn_live(
        self,
        *,
        subscription: "SelectedCodexThreadSubscription",
        turn_id: str,
        client_request_id: str | None,
        codex_goal: str | None,
        timestamp: str,
    ) -> bool:
        # Commentary agentMessages are intermediate working narration surfaced as
        # reasoning steps (via the channel-A progress stream); keep the turn live
        # without placing the streaming text in the answer slot, which would
        # double-render it (once as a step, once as the answer).
        self.upsert_bro_thread_executor_turn(
            BroTimelineTurn(
                turn_id=f"{subscription.public_thread_id}:codex:{turn_id}",
                thread_id=subscription.public_thread_id,
                persona_id=subscription.persona_id,
                executor_id="codex",
                owner="executor",
                client_request_id=client_request_id,
                executor_thread_id=subscription.codex_thread_id,
                executor_turn_id=turn_id,
                input_modality="unknown",
                status="running",
                created_at=timestamp,
                updated_at=timestamp,
                metadata={
                    "source": "selected_thread_event",
                    "executor_thread_id": subscription.codex_thread_id,
                    "executor_turn_id": turn_id,
                    "client_request_id": client_request_id,
                    "codex_goal": codex_goal,
                },
            )
        )
        return True

    def settle_selected_thread_turn(self, *, public_thread_id: str, executor_turn_id: str) -> bool:
        turns = self.bro_thread_executor_turns.get(public_thread_id)
        if not turns:
            return False
        changed = False
        updated: list[BroTimelineTurn] = []
        for turn in turns:
            if (
                turn.executor_turn_id == executor_turn_id
                and turn.status not in {"completed", "failed", "cancelled"}
            ):
                assistant = turn.assistant
                if assistant is not None and (assistant.status or "").lower() in {
                    "running", "in_progress", "inprogress", "pending", "streaming"
                }:
                    assistant = assistant.model_copy(update={"status": "completed"})
                turn = turn.model_copy(update={"status": "completed", "assistant": assistant})
                changed = True
            updated.append(turn)
        if changed:
            self.bro_thread_executor_turns[public_thread_id] = updated
        return changed

    def upsert_bro_thread_executor_turn(self, turn: BroTimelineTurn) -> None:
        turns = list(self.bro_thread_executor_turns.get(turn.thread_id, []))
        existing_index = next(
            (
                index
                for index, candidate in enumerate(turns)
                if candidate.turn_id == turn.turn_id
                or (
                    candidate.executor_id == turn.executor_id
                    and candidate.executor_thread_id == turn.executor_thread_id
                    and candidate.executor_turn_id == turn.executor_turn_id
                    and turn.executor_turn_id is not None
                )
            ),
            None,
        )
        LOGGER.warning(
            "[turn-reco] upsert thread=%s turn_id=%s exec_turn=%s client_request_id=%s source=%s merged=%s",
            turn.thread_id, turn.turn_id, turn.executor_turn_id,
            turn.client_request_id, turn.metadata.get("source"),
            existing_index is not None,
        )
        if existing_index is None:
            turns.append(turn)
        else:
            turns[existing_index] = _merge_timeline_turn(turns[existing_index], turn)
        self.bro_thread_executor_turns[turn.thread_id] = turns
        if self.timeline_status.get(turn.thread_id) != "failed":
            self.timeline_status[turn.thread_id] = "loaded"
            self.timeline_errors.pop(turn.thread_id, None)

    async def resolve_bro_thread_target(
        self,
        *,
        persona: Persona,
        target_thread_id: str | None,
        create_new_thread: bool,
        workspace_id: str | None = None,
    ) -> tuple[str, str, ExecutionSession | None, AgentResumeHandle | None]:
        if target_thread_id and create_new_thread:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and create a new thread.")
        if target_thread_id and workspace_id:
            raise ValueError("Direct Bro Detail instruction cannot target an existing thread and choose a new workspace.")

        if create_new_thread:
            await self.validate_new_codex_thread_workspace(persona=persona, workspace_id=workspace_id)
            thread_id = _new_bro_thread_id()
            return thread_id, thread_id, None, None

        if target_thread_id:
            session = await self.find_codex_thread_session_for_persona(
                persona.persona_id,
                target_thread_id,
            )
            if session is not None:
                return _public_thread_id(session), session.continuity_key or session.execution_session_id, session, None
            imported = self.imported_codex_threads.get(target_thread_id)
            imported_resume_handle = self.imported_codex_thread_resume_handles.get(target_thread_id)
            if (
                imported is not None
                and imported.persona_id == persona.persona_id
                and imported_resume_handle is not None
            ):
                return imported.thread_id, imported.thread_id, None, imported_resume_handle
            pending_task = await self.find_direct_task_thread_for_persona(
                persona.persona_id,
                target_thread_id,
            )
            if pending_task is not None:
                continuity_key = _task_metadata_string(pending_task, "bro_thread_id") or target_thread_id
                return target_thread_id, continuity_key, None, None
            raise ValueError("Selected Codex thread is not available for this Bro.")

        raise ValueError("Direct Bro Detail instruction requires explicit thread intent.")

    async def validate_new_codex_thread_workspace(self, *, persona: Persona, workspace_id: str | None) -> None:
        normalized_workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else ""
        if not normalized_workspace_id:
            raise ValueError("New Codex thread requires a workspace selection.")
        known_workspaces = await self.known_codex_workspaces_for_persona(persona)
        if normalized_workspace_id not in known_workspaces:
            raise ValueError("Selected Codex workspace is not available for this Bro.")

    async def known_codex_workspaces_for_persona(self, persona: Persona) -> set[str]:
        workspaces: set[str] = set()
        for imported in self.imported_codex_threads.values():
            if imported.persona_id != persona.persona_id:
                continue
            if imported.executor_node_id != persona.executor_node_id:
                continue
            if imported.workspace_id:
                workspaces.add(imported.workspace_id)
            cwd = imported.diagnostics.get("codex_cwd")
            if isinstance(cwd, str) and cwd.strip():
                workspaces.add(cwd.strip())
        for session in await self.blackboard.list_sessions():
            if session.base_executor_id != "codex":
                continue
            if session.executor_node_id != persona.executor_node_id:
                continue
            if not await self.session_belongs_to_persona(session, persona.persona_id):
                continue
            workspace_id = _workspace_from_resume_handle(session.latest_resume_handle)
            if workspace_id:
                workspaces.add(workspace_id)
        for task in await self.blackboard.list_tasks():
            if not _task_belongs_to_persona(task, persona.persona_id):
                continue
            if task.preferred_executor != "codex":
                continue
            executor_node_id = _task_metadata_string(task, "executor_node_id")
            if executor_node_id and executor_node_id != persona.executor_node_id:
                continue
            workspace_id = _task_workspace_id(task)
            if workspace_id:
                workspaces.add(workspace_id)
        return workspaces

    async def find_codex_thread_session_for_persona(
        self,
        persona_id: str,
        thread_id: str,
    ) -> ExecutionSession | None:
        for session in reversed(await self.blackboard.list_sessions()):
            if session.base_executor_id != "codex" or not _session_matches_thread_id(session, thread_id):
                continue
            if await self.session_belongs_to_persona(session, persona_id):
                return session
        return None

    async def find_direct_task_thread_for_persona(self, persona_id: str, thread_id: str) -> Task | None:
        for task in reversed(await self.blackboard.list_tasks()):
            if _task_thread_public_id(task) != thread_id:
                continue
            if _task_belongs_to_persona(task, persona_id):
                return task
        return None

    async def session_belongs_to_persona(self, session: ExecutionSession, persona_id: str) -> bool:
        task_ids = list(session.run_ids)
        if session.latest_run_id and session.latest_run_id not in task_ids:
            task_ids.append(session.latest_run_id)
        for run_id in task_ids:
            run = await self.blackboard.get_run(run_id)
            if run is None:
                continue
            task = await self.blackboard.get_task(run.task_id)
            if _task_belongs_to_persona(task, persona_id):
                return True
        task = await self.blackboard.get_task(session.task_id)
        if _task_belongs_to_persona(task, persona_id):
            return True
        persona = await self.blackboard.get_persona(persona_id)
        return persona is not None and session.continuity_key == persona.bro_detail_session_id
