from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from newbro.communication.model import CommunicationModel
from newbro.communication.interaction_classifier import InteractionClassifier
from newbro.protocol import Persona

from .config import Settings
from .drafts import DraftRewriter
from .executor_node_manager import ExecutorNodeManager
from .session import SessionRuntime, create_session_runtime


@dataclass(slots=True)
class RuntimeContainer:
    communication_model: CommunicationModel
    settings: Settings
    draft_rewriter: DraftRewriter | None = None
    interaction_classifier: InteractionClassifier | None = None
    executor_node_manager: ExecutorNodeManager = field(init=False)
    _sessions: dict[str, SessionRuntime] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.executor_node_manager = ExecutorNodeManager(
            detached_executor_types=self.settings.detached_executor_types,
        )

    def create_session(self) -> SessionRuntime:
        session_id = f"session-{uuid4().hex[:8]}"
        session = create_session_runtime(
            session_id,
            model=self.communication_model,
            settings=self.settings,
            executor_node_manager=self.executor_node_manager,
            draft_rewriter=self.draft_rewriter,
            interaction_classifier=self.interaction_classifier,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionRuntime:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown session: {session_id}") from exc

    def find_session_by_dispatch_plan(self, plan_id: str) -> SessionRuntime | None:
        for session in self._sessions.values():
            draft_session = session.draft_manager.active_session
            plan = draft_session.current_dispatch_plan if draft_session is not None else None
            if plan is not None and plan.plan_id == plan_id:
                return session
        return None

    async def find_session_by_task(self, task_id: str) -> SessionRuntime | None:
        for session in self._sessions.values():
            if await session.blackboard.get_task(task_id) is not None:
                return session
        return None

    async def handle_executor_node_connected(self) -> list[str]:
        updated_task_ids: list[str] = []
        for session in self._sessions.values():
            changed = await session.requeue_waiting_executor_tasks()
            if changed:
                session.schedule_execution()
                updated_task_ids.extend(changed)
        await self.publish_session_snapshots()
        return updated_task_ids

    async def handle_executor_node_disconnected(self) -> None:
        await self.publish_session_snapshots()

    async def publish_session_snapshots(self) -> None:
        for session in self._sessions.values():
            if session.subscribers:
                await session.publish_snapshot()

    async def persona_is_busy(self, persona_id: str) -> bool:
        for session in self._sessions.values():
            persona = await session.blackboard.get_persona(persona_id)
            if persona is not None and (persona.status == "busy" or persona.current_task_id is not None):
                return True
        return False

    async def bound_persona_names_for_node(self, node_id: str) -> list[str]:
        bound_names: set[str] = set()
        for session in self._sessions.values():
            for persona in await session.blackboard.list_personas():
                if persona.executor_node_id == node_id:
                    bound_names.add(persona.name)
        return sorted(bound_names)

    async def sync_persisted_personas(self, personas: list[Persona]) -> None:
        persisted_by_id = {persona.persona_id: persona for persona in personas}
        for session in self._sessions.values():
            current_personas = {
                persona.persona_id: persona
                for persona in await session.blackboard.list_personas()
            }
            for persona_id, persisted in persisted_by_id.items():
                current = current_personas.get(persona_id)
                if current is None:
                    await session.blackboard.put_persona(persisted)
                    continue
                await session.blackboard.put_persona(
                    persisted.model_copy(
                        update={
                            "status": current.status,
                            "current_task_id": current.current_task_id,
                        }
                    )
                )
            for persona_id, current in current_personas.items():
                if persona_id in persisted_by_id:
                    continue
                if current.status == "busy" or current.current_task_id is not None:
                    continue
                await session.blackboard.delete_persona(persona_id)
        await self.publish_session_snapshots()

    async def sync_user_personas(self, *, session_id: str, personas: list[Persona]) -> None:
        session = self.get_session(session_id)
        persisted_by_id = {persona.persona_id: persona for persona in personas}
        current_personas = {
            persona.persona_id: persona
            for persona in await session.blackboard.list_personas()
        }
        for persona_id, persisted in persisted_by_id.items():
            current = current_personas.get(persona_id)
            if current is None:
                await session.blackboard.put_persona(persisted)
                continue
            await session.blackboard.put_persona(
                persisted.model_copy(
                    update={
                        "status": current.status,
                        "current_task_id": current.current_task_id,
                    }
                )
            )
        for persona_id, current in current_personas.items():
            if persona_id in persisted_by_id:
                continue
            if current.status == "busy" or current.current_task_id is not None:
                continue
            await session.blackboard.delete_persona(persona_id)
        await session.publish_snapshot()
