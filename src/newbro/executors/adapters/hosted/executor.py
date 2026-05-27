from __future__ import annotations

from uuid import uuid4

from newbro.executors.core import ExecutorCapabilities, ExecutorSession, ExecutorEventType
from newbro.protocol import ExecutionRun, Task

from newbro.runtime.executor_node_manager import ExecutorNodeManager


TERMINAL_EVENT_TYPES = {
    ExecutorEventType.WAITING_EXECUTOR,
    ExecutorEventType.BLOCKED,
    ExecutorEventType.COMPLETED,
    ExecutorEventType.FAILED,
    ExecutorEventType.CANCELLED,
}


class HostedExecutor:
    def __init__(
        self,
        *,
        executor_type: str,
        manager: ExecutorNodeManager,
        supports_resume: bool,
        supports_follow_up: bool,
        supports_pause: bool,
        supports_thread_list: bool = False,
        supports_cancel: bool = True,
    ) -> None:
        self._manager = manager
        self._capabilities = ExecutorCapabilities(
            executor_type=executor_type,
            supports_resume=supports_resume,
            supports_follow_up=supports_follow_up,
            supports_thread_list=supports_thread_list,
            supports_pause=supports_pause,
            supports_cancel=supports_cancel,
            supports_setup=False,
        )

    def get_capabilities(self) -> ExecutorCapabilities:
        return self._capabilities

    async def create_session(self, workspace_id: str | None = None) -> ExecutorSession:
        return ExecutorSession(
            session_id=f"{self._capabilities.executor_type}-hosted-{uuid4().hex[:8]}",
            executor_type=self._capabilities.executor_type,
            metadata={"workspace_id": workspace_id} if workspace_id else {},
        )

    async def cancel_run(self, run_id: str) -> None:
        await self._manager.cancel_run(run_id, mode="cancel")

    async def pause_run(self, run_id: str) -> None:
        await self._manager.cancel_run(run_id, mode="pause")

    async def run_task(
        self,
        run: ExecutionRun,
        task: Task,
        session: ExecutorSession,
    ):
        queue = await self._manager.dispatch_run(
            run_id=run.run_id,
            execution_session_id=run.execution_session_id,
            executor_type=run.executor_type,
            task_id=task.task_id,
            title=task.title,
            goal=task.goal,
            latest_instruction=task.latest_instruction,
            workspace_id=task.session_affinity,
            task_metadata=dict(task.metadata),
            latest_resume_handle=_resume_handle_from_session(session),
            node_id=_node_id_from_task(task),
        )
        try:
            while True:
                envelope = await queue.get()
                if envelope.latest_resume_handle is not None:
                    session.metadata["latest_resume_handle"] = envelope.latest_resume_handle
                yield envelope.event
                if envelope.event.event_type in TERMINAL_EVENT_TYPES:
                    return
        finally:
            self._manager.finish_run(run.run_id)


def _resume_handle_from_session(session: ExecutorSession) -> dict[str, object] | None:
    value = session.metadata.get("latest_resume_handle")
    return dict(value) if isinstance(value, dict) else None


def _node_id_from_task(task: Task) -> str | None:
    value = task.metadata.get("executor_node_id")
    return value if isinstance(value, str) and value else None
