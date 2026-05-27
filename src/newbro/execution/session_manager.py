from __future__ import annotations

from uuid import uuid4

from newbro.blackboard import BlackboardStore
from newbro.executors.core import Executor, ExecutorSession
from newbro.observability.emitters.execution import ExecutionDiagnosticEmitter
from newbro.observability.reason_codes import (
    EXECUTOR_SESSION_RECREATED,
    EXISTING_LIVE_SESSION_REUSED,
)
from newbro.protocol import AgentResumeHandle, BindingStatus, ExecutionSession, SessionBinding, Task


class SessionManager:
    def __init__(self, *, observability: ExecutionDiagnosticEmitter | None = None) -> None:
        self._live_sessions: dict[str, ExecutorSession] = {}
        self._observability = observability

    async def ensure_session(
        self,
        store: BlackboardStore,
        executor: Executor,
        task: Task,
        binding: SessionBinding,
    ) -> tuple[ExecutionSession, SessionBinding, ExecutorSession]:
        metadata_node_id = task.metadata.get("executor_node_id")
        executor_node_id = (
            metadata_node_id
            if isinstance(metadata_node_id, str) and metadata_node_id
            else getattr(executor, "executor_node_id", None)
        )
        executor_type = executor.get_capabilities().executor_type
        continuity_key = _task_continuity_key(task)
        if binding.execution_session_id:
            existing = await store.get_session(binding.execution_session_id)
            if existing is not None:
                if executor_node_id is not None and existing.executor_node_id != executor_node_id:
                    existing.executor_node_id = executor_node_id
                    await store.put_session(existing)
                cached = self._live_sessions.get(existing.execution_session_id)
                # Control-plane cached sessions are reusable; executor-native liveness is
                # owned by the detached node rather than tracked here.
                if cached is not None:
                    active_binding = binding.model_copy(
                        update={
                            "binding_status": BindingStatus.ACTIVE,
                            "executor_node_id": executor_node_id,
                        }
                    )
                    await store.put_binding(active_binding)
                    if self._observability is not None:
                        self._observability.session_reused(
                            task_id=task.task_id,
                            execution_session_id=existing.execution_session_id,
                            executor_session_id=cached.session_id,
                            executor_type=cached.executor_type,
                            reason_code=EXISTING_LIVE_SESSION_REUSED,
                        )
                    return existing, active_binding, cached

                executor_session = await executor.create_session(task.session_affinity)
                _hydrate_resume_handle(executor_session, existing.latest_resume_handle)
                self._live_sessions[existing.execution_session_id] = executor_session
                active_binding = binding.model_copy(
                    update={
                        "session_id": executor_session.session_id,
                        "executor_node_id": executor_node_id,
                        "binding_status": BindingStatus.ACTIVE,
                    }
                )
                await store.put_binding(active_binding)
                if self._observability is not None:
                    self._observability.session_reused(
                        task_id=task.task_id,
                        execution_session_id=existing.execution_session_id,
                        executor_session_id=executor_session.session_id,
                        executor_type=executor_session.executor_type,
                        reason_code=EXECUTOR_SESSION_RECREATED,
                    )
                return existing, active_binding, executor_session

        if continuity_key is not None:
            reusable = await _find_reusable_session(
                store,
                continuity_key=continuity_key,
                executor_type=executor_type,
                executor_node_id=executor_node_id,
            )
            if reusable is not None:
                cached = self._live_sessions.get(reusable.execution_session_id)
                if cached is None:
                    cached = await executor.create_session(task.session_affinity)
                    _hydrate_resume_handle(cached, reusable.latest_resume_handle)
                    self._live_sessions[reusable.execution_session_id] = cached
                active_binding = binding.model_copy(
                    update={
                        "execution_session_id": reusable.execution_session_id,
                        "session_id": cached.session_id,
                        "executor_node_id": executor_node_id,
                        "binding_status": BindingStatus.ACTIVE,
                    }
                )
                await store.put_binding(active_binding)
                if self._observability is not None:
                    self._observability.session_reused(
                        task_id=task.task_id,
                        execution_session_id=reusable.execution_session_id,
                        executor_session_id=cached.session_id,
                        executor_type=cached.executor_type,
                        reason_code=EXISTING_LIVE_SESSION_REUSED,
                    )
                return reusable, active_binding, cached

        executor_session = await executor.create_session(task.session_affinity)
        imported_resume_handle = _task_imported_resume_handle(task)
        if imported_resume_handle is not None:
            _hydrate_resume_handle(executor_session, imported_resume_handle)
        execution_session = ExecutionSession(
            execution_session_id=f"exec-session-{uuid4().hex[:8]}",
            task_id=task.task_id,
            base_executor_id=executor_type,
            executor_node_id=executor_node_id,
            continuity_key=continuity_key,
            latest_resume_handle=imported_resume_handle,
        )
        self._live_sessions[execution_session.execution_session_id] = executor_session
        updated_binding = binding.model_copy(
            update={
                "execution_session_id": execution_session.execution_session_id,
                "executor_node_id": executor_node_id,
                "session_id": executor_session.session_id,
                "binding_status": BindingStatus.ACTIVE,
            }
        )
        await store.put_session(execution_session)
        await store.put_binding(updated_binding)
        if self._observability is not None:
            self._observability.session_created(
                task_id=task.task_id,
                execution_session_id=execution_session.execution_session_id,
                executor_session_id=executor_session.session_id,
                executor_type=executor_session.executor_type,
            )
        return execution_session, updated_binding, executor_session

    def drop_live_session(self, execution_session_id: str) -> None:
        self._live_sessions.pop(execution_session_id, None)

    def get_live_session(self, execution_session_id: str) -> ExecutorSession | None:
        return self._live_sessions.get(execution_session_id)


def _hydrate_resume_handle(
    session: ExecutorSession,
    resume_handle: AgentResumeHandle | None,
) -> None:
    if resume_handle is None:
        session.metadata.pop("latest_resume_handle", None)
        return
    session.metadata["latest_resume_handle"] = resume_handle.model_dump(mode="json")


def _task_continuity_key(task: Task) -> str | None:
    thread_value = task.metadata.get("bro_thread_id")
    if isinstance(thread_value, str) and thread_value:
        return thread_value
    value = task.metadata.get("bro_detail_session_id")
    return value if isinstance(value, str) and value else None


def _task_imported_resume_handle(task: Task) -> AgentResumeHandle | None:
    if task.metadata.get("codex_thread_mode") != "resume":
        return None
    value = task.metadata.get("codex_import_thread_id")
    if not isinstance(value, str) or not value:
        return None
    opaque: dict[str, object] = {}
    cwd = task.metadata.get("codex_import_cwd")
    if isinstance(cwd, str) and cwd:
        opaque["cwd"] = cwd
    path = task.metadata.get("codex_import_path")
    if isinstance(path, str) and path:
        opaque["path"] = path
    return AgentResumeHandle(executor_id="codex", session_handle=value, opaque=opaque)


async def _find_reusable_session(
    store: BlackboardStore,
    *,
    continuity_key: str,
    executor_type: str,
    executor_node_id: str | None,
) -> ExecutionSession | None:
    candidates = [
        session
        for session in await store.list_sessions()
        if session.continuity_key == continuity_key
        and session.base_executor_id == executor_type
        and session.executor_node_id == executor_node_id
    ]
    if not candidates:
        return None
    return candidates[-1]
